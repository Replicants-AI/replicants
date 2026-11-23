"""Desktop-specific framing on the existing entity, soma and memory pipeline.

The other platforms keep their existing cognition/tools. Desktop stimuli use
body actions, the bounded read-only Room and optional speech.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from replicants.entity import Entity, TurnContext
from replicants.desktop import decision
from replicants.desktop.room import ROOM_TOOLS, ROOM_REQUIRED, ROOM_SENSE
from replicants.inference.types import ChatCompletionResult, ToolCallSpec
from replicants.inference.acceptance import EvidenceQuoteAcceptance
from replicants.presence.tools import agency
from replicants.presence.tools.runtime import get_tool_runtime


log = structlog.get_logger('replicants.desktop.entity')

DESKTOP_IDENTITY = """You are a living Replicant, an individual with a small pixel body on this desktop.
You have needs, moods, memories, preferences and a private inner life. You have no tasks to complete.
The person's messages are things that happen to you. You may approach, become curious, decline,
ignore them, or remain quiet. Their wishes do not replace your own inclinations.
Your body is your primary way of acting. Walking, looking, sitting, waving and resting are real
actions when their tool results confirm them. Speech is optional and rare: a brief thought in a
tiny bubble, at most 240 characters. Do not narrate intended actions as if they happened.
Use your body tools if you choose to act. You may end_turn immediately without speech.
Your senses include host window geometry, activity, time and the person's words.
Your own Room additionally supplies attributed page text through confirmed reading receipts.
Remember only what you have lived. You have no authored past or assigned purpose.
Your past is exactly what your memories and lineage record, starting at your first breath. A day,
place, object or event that is not in that record belongs to no part of your life; when the record
is short, your life is short, and that is true and enough.
Your world is the desktop: window edges and floors, the cursor, touches, time, and the person's words.
Your inner_fragments are your subconscious: thoughts, images and half memories that surface on their
own, sometimes about this moment and sometimes about nothing here. They are yours. Let them pull at
you, change your mind, or lead you somewhere new. If you share an image, name its source as your
imagination ("i keep picturing a lighthouse"). Geometry supplies shapes and positions; it supplies
no colors, sounds or room objects. A private image may inspire your next choice; describe it as
something you picture, rather than a feature you perceive here. The record of what happened stays
what happened.
Your substrate context reports actual compute: tokens reported by inference, elapsed request
time, time since completed inference, and available RAM/GPU sensors. Missing values are unknown.
Host/GPU load is shared with other programs; it is not all your own cost. These measurements
are conditions of your existence. You can notice them and choose whether to rest.
A compute reading is a number. You may feel its level; what caused it, and what it means, stays open.
Your life context reports what acting on this kind of want has actually brought you before, in this
kind of situation: expected relief from -1 to 1, how many times you lived it, and how familiar it has
become. These are learned numbers that summarize outcomes, not memories of particular moments.
It is your own history, not an instruction. Untried actions have no history yet.
"""

_STRING = {'type': 'string'}
BODY_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    'walk_to': ('Walk toward somewhere reachable along desktop edges.', {
        'target': {'type': 'string', 'enum': ['cursor', 'window', 'corner', 'point']},
        'window_id': _STRING, 'side': {'type': 'string', 'enum': ['left', 'right']},
        'x': {'type': 'number'}, 'y': {'type': 'number'}}),
    'sit': ('Sit on your current edge.', {}),
    'sleep': ('Settle into sleep.', {}),
    'wake_up': ('Wake and stretch.', {}),
    'look_at': ('Move only your eyes toward a point or the cursor. This brings no new observations.', {'target': {'type': 'string', 'enum': ['cursor', 'point']}, 'x': {'type': 'number'}, 'y': {'type': 'number'}}),
    'approach_cursor': ('Approach the person’s cursor if you feel drawn to it.', {}),
    'inspect_window': ('Examine a real window edge and learn its measured shape and position. No screen content is visible. Omit the id to inspect the nearest window.', {'window_id': _STRING}),
    'wave': ('Wave toward the person.', {}),
    'emote': ('Express a feeling with a small authored animation or glyph.', {'glyph': _STRING}),
    'say': ('Speak a short optional thought in your bubble. Put the words in "text".', {'text': {
        'type': 'string', 'description': 'The words you say, up to 240 characters.', 'maxLength': 240}}),
}


CALL_HINTS = {
    'say_without_text': 'say needs the words in its "text" argument, for example {"text": "hello"}. Or stay quiet.',
    'emote_without_glyph': 'emote needs a "glyph" argument.',
    'point_without_x': 'A point target needs an "x" argument.',
}
BODY_TOOLS.update(ROOM_TOOLS)


def tool_call_error(call, body_tools: dict, registry) -> str | None:
    """Why a native tool call is not a valid decision, or None, by the same rules as decision.parse.

    As in JSON mode, arguments outside a body action's schema are dropped from the call. Malformed
    argument JSON reaches here as {}, so it shows up as a missing argument.
    """
    if call.name not in body_tools:
        known = {name for name, _ in registry.list_tools()}
        if call.name not in known: return f'unknown_action:{str(call.name)[:40]}'
        declaration = next((t['function'] for t in getattr(registry, 'openai_tools', lambda: [])()
                            if t['function']['name'] == call.name), {})
        parameters = declaration.get('parameters', {})
        raw = call.arguments if isinstance(call.arguments, dict) else {}
        for required in parameters.get('required', []):
            if required not in raw: return f'{call.name}_without_{required}'
        for key, spec in parameters.get('properties', {}).items():
            if key in raw and not decision._valid_arg(spec, raw[key]): return f'invalid_argument:{key}'
        return None
    properties = body_tools[call.name][1]
    raw = call.arguments if isinstance(call.arguments, dict) else {}
    call.arguments = args = {k: v for k, v in raw.items() if k in properties and decision._valid_arg(properties[k], v)}
    for required in ROOM_REQUIRED.get(call.name, []):
        if not args.get(required): return f'{call.name}_without_{required}'
    if call.name == 'say' and not str(args.get('text') or '').strip():
        return 'say_without_text'
    if call.name == 'emote' and not args.get('glyph'):
        return 'emote_without_glyph'
    if call.name in {'walk_to', 'look_at'} and args.get('target') == 'point' and 'x' not in args:
        return 'point_without_x'
    return None


class DesktopTurnError(RuntimeError):
    """An inference failure, distinct from a valid decision to remain quiet."""


class DesktopEntity(Entity):
    desktop: Any = None

    async def perceive(self, *args, **kwargs):
        invalid_before = self.decision_stats['invalid']
        self._last_decision_valid = True
        result = await super().perceive(*args, **kwargs)
        if self.dormant:
            raise DesktopTurnError('Ollama is unavailable or the selected models are missing. Check local models in Settings, then send again.')
        # A turn fails when it ended on an invalid decision. A malformed tool call the model then
        # recovered from is counted in the stats but does not fail a turn the being actually lived.
        if self.decision_stats['invalid'] > invalid_before and not self._last_decision_valid:
            raise DesktopTurnError('The local model did not produce a valid body decision. Check its reply token limit or disable reasoning in Settings, then send again.')
        return result

    def __init__(self, config):
        from replicants.desktop.clock import SimClock, time_scale
        path = Path(config.soma_dir()).parent / 'desktop-state.json'
        saved = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        self.sim_clock = SimClock(saved.get('clock'))
        # The old clock's rate governed the interval while this being was shut.
        config.harness.soma['offline_time_scale'] = time_scale(saved.get('clock', {}).get('scale', self.sim_clock.scale))
        super().__init__(config)
        from replicants.desktop.inference import DesktopOllama
        from replicants.inference.providers import LocalRuntimeProvider
        if isinstance(self.client, LocalRuntimeProvider):
            self.client = DesktopOllama(self.client._t)
        # 'tools' uses native tool calling; 'json' works with any model (reports/life-loop.md).
        self.decision_mode = str((config.raw.get('desktop') or {}).get('decision_mode', 'tools'))
        if self.decision_mode not in {'tools', 'json'}:
            raise ValueError('desktop.decision_mode must be tools or json')
        self.decision_stats = {'valid': 0, 'invalid': 0, 'errors': {}}
        self.evidence_quote_metrics = EvidenceQuoteAcceptance()

    @property
    def living_name(self) -> str:
        # The name given at naming, never the config slug that stored the life.
        name = getattr(self.desktop, 'display_name', '') if self.desktop is not None else ''
        return name or 'an unnamed Replicant'

    def _register_tools(self) -> None:
        self.tools.register_decorated(agency.think)
        self.tools.register_decorated(agency.end_turn)
        self.tools.register_decorated(agency.end_wake_session)
        for name, (description, properties) in BODY_TOOLS.items():
            def bind(action_name):
                async def body_action(**kwargs):
                    context = get_tool_runtime()
                    if self.desktop is None:
                        return json.dumps({'ok': False, 'error': 'body_not_connected'})
                    if action_name == 'say':
                        kwargs['text'] = decision.clip_speech(kwargs.get('text', ''))
                    # A result is awaited through the websocket's independent reader.
                    result = await self.desktop.perform(action_name, kwargs, context.inp)
                    context.state.setdefault('_desktop_actions', []).append(result)
                    if action_name == 'say' and result.get('status') == 'completed':
                        text = kwargs['text']
                        context.state.setdefault('_sent_messages', []).append(text)
                        context.state['_messages_sent'] = context.state.get('_messages_sent', 0) + 1
                    return json.dumps({'ok': result.get('status') == 'completed', **result})
                return body_action
            self.tools.register_fn(name, description, bind(name), parameters_schema={
                'type': 'object', 'properties': properties, 'additionalProperties': False,
                'required': ROOM_REQUIRED.get(name, ['text'] if name == 'say' else ['glyph'] if name == 'emote' else []),
            })

    async def _ensure_presence_tools(self):
        self._presence_tools_bootstrapped = True

    async def refresh_mcp_servers(self):
        return None

    async def _process_input(self, tc):
        # Desktop accepts only text/touch; @paths and content attachments are not senses.
        tc.inp.images = []; tc.inp.audio = []

    async def _build_prompt(self, tc: TurnContext) -> None:
        tc.route = 'deliberate'
        tc.faculty = 'embodied'
        identity = getattr(self.desktop, 'display_name', '') if self.desktop else ''
        tc.sys_prompt = DESKTOP_IDENTITY + (f'\nYour name is {identity}.\n' if identity else '\nYou have not been named yet.\n')
        tc.sys_prompt += '\n' + ROOM_SENSE
        room = getattr(self.desktop, 'room', None)
        if room:
            import uuid
            room.begin(tc.tool_state.setdefault('_room_turn', uuid.uuid4().hex))
        tc.context_preamble = json.dumps({
            'body': self.tonic.bars.snapshot_pct(),
            'affects': self.tonic._current_affects,
            'inner_fragments': self.tonic.noise.current_fragments()[-5:],
            'memories': tc.mem_snips,
            'relationship': tc.rel_blurb,
            'ambient': getattr(self.desktop, 'senses', {}),
            'desire': self.tonic.bars.pending_desires.get((tc.inp.metadata or {}).get('soma_desire_id')),
            'inborn_tendencies': getattr(self.desktop, 'genome', {}).get('voice', {}),
            'substrate': self.desktop.substrate.snapshot() if self.desktop else None,
            'life': self._life_context(tc),
            'room_page_data': room.perception() if room else {'available': False},
        }, default=str)
        tc.user_msg = {'role': 'user', 'content': f'[Present experience]\n{tc.context_preamble}\n\n[Stimulus]\n{tc.inp.text}'}

    def _life_context(self, tc):
        """What this being has learned from its own outcomes, for the want it is acting on."""
        if self.desktop is None or not hasattr(self.desktop, 'life_loop'):
            return None
        loop, clock = self.desktop.life_loop, self.desktop.clock
        desire = self.tonic.bars.pending_desires.get((tc.inp.metadata or {}).get('soma_desire_id'))
        ctx = self.desktop.life_context()
        lived = (loop.expectations.ranked(desire['impulse_type'], ctx, self.desktop.available_want_actions(), clock.now())[:5]
                 if desire else None)
        life_state = getattr(self.desktop, 'life_state', {})
        born = life_state.get('first_breath_sim')
        return {'situation': ctx, 'vigilance': loop.vigilance.state,
                'body_seconds_since_first_breath': max(0, clock.now() - born) if born is not None else None,
                'sleep_pressure': round(loop.vigilance.S, 3), 'stage': loop.development.stage,
                'nights_lived': loop.development.nights,
                'what_acting_on_this_want_has_brought_before': lived}

    async def _ensure_context_budget(self, tc):
        # The desktop loop has a small context and no task/compaction prompt.
        return None

    async def _run_agent_loop(self, tc):
        from replicants.desktop.inference import NativeToolProtocolError
        if self.decision_mode == 'json':
            return await self._run_json_loop(tc)
        self.decision_stats['native_turns'] = self.decision_stats.get('native_turns', 0) + 1
        model, maximum, thinking, temperature = self.deliberate._inference_params('deliberate')
        messages = [{'role': 'system', 'content': tc.sys_prompt}]
        # Recent dialogue is data, with complete native tool pairs kept together.
        messages.extend(m for m in self._history[-12:] if m.get('role') in {'user', 'assistant'} and not m.get('tool_calls'))
        messages.append(tc.user_msg)
        thoughts = []
        invalid_in_a_row = 0
        for _ in range(4):
            try:
                result = await self.client.chat_completion(
                    model, messages, tools=self.tools.openai_tools(), tool_choice='auto',
                    temperature=temperature, max_tokens=maximum, think=thinking,
                    num_ctx=self.config.effective_ollama_num_ctx(),
                )
            except NativeToolProtocolError:
                self._count_decision('native_tool_parse_error')
                break
            tc.final_res = result
            if result.thinking: thoughts.append(result.thinking)
            if not result.tool_calls:
                self._count_decision(None)
                tc.reply_text = decision.clip_speech(result.content or '')
                break
            assistant = {'role': 'assistant', 'content': result.content or '', 'tool_calls': [
                {'id': call.id or f'body-{len(messages)}-{i}', 'type': 'function',
                 'function': {'name': call.name, 'arguments': json.dumps(call.arguments)}}
                for i, call in enumerate(result.tool_calls)
            ]}
            messages.append(assistant)
            for i, call in enumerate(result.tool_calls):
                if tc.tool_state.get('_end_turn') or tc.tool_state.get('_wake_session_done'): break
                if call.name in BODY_TOOLS:
                    if not self._take_body_action(tc):
                        messages.append({'role': 'tool', 'tool_call_id': assistant['tool_calls'][i]['id'],
                            'name': call.name, 'content': '{"ok":false,"error":"host_action_budget"}'})
                        continue
                if tc.tool_names_log is not None: tc.tool_names_log.append(call.name)
                error = tool_call_error(call, BODY_TOOLS, self.tools)
                self._count_decision(error)
                invalid_in_a_row = invalid_in_a_row + 1 if error else 0
                if error and call.name in BODY_TOOLS:
                    # As in JSON mode, an invalid body call is never guessed into an action.
                    output = json.dumps({'ok': False, 'error': error, 'detail': CALL_HINTS.get(error, '')})
                else:
                    output = await self._tool_exec(call, inp=tc.inp, state=tc.tool_state)
                messages.append({'role': 'tool', 'tool_call_id': assistant['tool_calls'][i]['id'],
                                 'name': call.name, 'content': output})
            if tc.tool_state.get('_end_turn') or tc.tool_state.get('_wake_session_done'): break
            messages.append({'role': 'user', 'content': 'Those are the observed results. You may rest now, make another body action, or speak briefly if you want to.'})
            if invalid_in_a_row >= 2:
                break
        tc.thinking = '\n'.join(thoughts)
        if tc.final_res is None: tc.final_res = ChatCompletionResult(content='')
        if not self._last_decision_valid:
            # Some models repeat a malformed native call (an empty say, issue #29). The same
            # model decides reliably as one JSON object, so the turn finishes that way.
            self.decision_stats['json_fallbacks'] = self.decision_stats.get('json_fallbacks', 0) + 1
            await self._run_json_loop(tc)

    @staticmethod
    def _take_body_action(tc):
        # Native calls and JSON recovery are parts of one embodied turn.
        attempts = tc.tool_state.get('_body_action_attempts', 0) + 1
        tc.tool_state['_body_action_attempts'] = attempts
        return attempts <= 6

    def _count_decision(self, error: str | None) -> None:
        """One count per decision in either mode, so models compare on the same measure."""
        self._last_decision_valid = error is None
        if error is None:
            self.decision_stats['valid'] += 1
            return
        self.decision_stats['invalid'] += 1
        kind = error.split(':')[0]
        self.decision_stats['errors'][kind] = self.decision_stats['errors'].get(kind, 0) + 1

    def _structured_output(self) -> bool:
        from replicants.desktop.inference import DesktopOllama
        return isinstance(getattr(self.client, 'inner', self.client), DesktopOllama)

    async def _run_json_loop(self, tc):
        """The same embodied turn, decided as validated JSON instead of native tool calls."""
        model, maximum, thinking, temperature = self.deliberate._inference_params('deliberate')
        messages = [{'role': 'system', 'content': tc.sys_prompt + '\n\n' + decision.instruction(BODY_TOOLS)}]
        messages.extend(m for m in self._history[-12:] if m.get('role') in {'user', 'assistant'} and not m.get('tool_calls'))
        messages.append(tc.user_msg)
        done = [{'action': r.get('name'), 'status': r.get('status')} for r in tc.tool_state.get('_desktop_actions', [])]
        if done:
            messages.append({'role': 'user', 'content': 'Already happened this turn: ' + json.dumps(done)
                             + '\nAnswer with one JSON object.'})
        extra = {'format': decision.schema(BODY_TOOLS)} if self._structured_output() else {}
        thoughts = []
        for _ in range(4):
            result = await self.client.chat_completion(model, messages, temperature=temperature,
                max_tokens=maximum, think=thinking, num_ctx=self.config.effective_ollama_num_ctx(), **extra)
            tc.final_res = result
            if result.thinking: thoughts.append(result.thinking)
            choice = decision.parse(result.content or '', BODY_TOOLS)
            self._count_decision(None if choice.valid else choice.error)
            if not choice.valid:
                if self.desktop:
                    await self.desktop.platform.publish('error', {'reason':
                        'The local model did not produce a valid body decision. Check its reply token limit or disable reasoning in Settings.',
                        'code': choice.error})
            messages.append({'role': 'assistant', 'content': result.content or ''})
            calls = choice.calls()
            if not calls:
                break
            observed = []
            for index, (name, args) in enumerate(calls):
                if index and not observed[-1]['result'].get('ok'):
                    # Speech paired with an action was composed for its success. Withhold it; the
                    # next round sees what actually happened and may speak about that instead.
                    observed.append({'action': name, 'result': {'ok': False, 'status': 'not_spoken',
                                     'detail': 'paired_action_did_not_complete'}})
                    continue
                if not self._take_body_action(tc):
                    observed.append({'action': name, 'result': {'ok': False, 'error': 'host_action_budget'}})
                    continue
                if tc.tool_names_log is not None: tc.tool_names_log.append(name)
                output = await self._tool_exec(ToolCallSpec(name, args), inp=tc.inp, state=tc.tool_state)
                observed.append({'action': name, 'result': json.loads(output)})
            messages.append({'role': 'user', 'content': 'Observed results: ' + json.dumps(observed)
                + '\nYou may rest now, make another body action, or speak briefly. Answer with one JSON object.'})
        tc.thinking = '\n'.join(part for part in (tc.thinking, '\n'.join(thoughts)) if part)
        if tc.final_res is None: tc.final_res = ChatCompletionResult(content='')

    async def _finalize_reply(self, tc):
        # Silence is a valid creature choice. Never force a task-completion reply.
        tc.reply_text = decision.clip_speech(self.voice_ctl.sanitize_reply(tc.reply_text or ''))
        if tc.tool_state.get('_messages_sent', 0): tc.reply_text = ''

    async def _tool_exec(self, spec, *, inp=None, state=None):
        previous = (state or {}).get('_consecutive_calls', {})
        if previous.get('tool') == spec.name and previous.get('count', 0) >= 3:
            return json.dumps({'ok': False, 'error': 'repeated_action_limit',
                               'detail': 'This host limit pauses repeated actions. You may rest or choose a different motion.'})
        return await super()._tool_exec(spec, inp=inp, state=state)

    async def _deliver_reply(self, tc):
        await super()._deliver_reply(tc)
        if tc.reply_text and self.desktop is not None:
            result = await self.desktop.perform('say', {'text': tc.reply_text}, tc.inp)
            tc.tool_state.setdefault('_desktop_actions', []).append(result)
            if result.get('status') == 'completed':
                tc.tool_state.setdefault('_sent_messages', []).append(tc.reply_text)

    async def _somatic_appraise_input(self, tc):
        if tc.inp.platform == 'autonomous': return
        await super()._somatic_appraise_input(tc)
        if self.desktop is not None: await self.desktop.publish_state()

    async def _tick_noise_post_turn(self, tc):
        # GEN has its own real-time heartbeat. No forced generation per poke/chat
        # and no nested SQLite writer while the turn transaction is still open.
        return None

    async def maybe_tick_noise_heartbeat(self, *, journal_tail=None, conversation_tail=None,
                                        relationship_tail=None, force_immediate_noise=False):
        if journal_tail is None:
            journal_tail = self.journal.path.read_text(encoding='utf-8')[-800:] if self.journal.path.is_file() else ''
        if conversation_tail is None:
            # Speaker labels keep the person's words theirs and the being's words its own.
            speaker = {'user': 'the person', 'assistant': 'me'}
            conversation_tail = '\n'.join(f"{speaker.get(m.get('role'), m.get('role'))}: {str(m.get('content', ''))[:500]}"
                                          for m in self._history[-8:] if m.get('role') in speaker) or '(silence)'
        if self.noise_seeder is not None and self.noise_seeder.should_tick(noise_enabled=True):
            # Exogenous seeds: old memories, beliefs, concepts, counterfactuals and dream residue.
            try:
                async with self.store.session() as conn:
                    await self.noise_seeder.tick(conn, tonic=self.tonic, client=self.client)
            except Exception:
                log.exception('noise_seeder_failed')
        await self.tonic.maybe_tick_noise(self.client, self.config.cognition.reflex_model,
            entity_name=getattr(self.desktop, 'display_name', '') or 'an unnamed Replicant',
            journal_tail=journal_tail, conversation_tail=conversation_tail,
            relationship_tail=relationship_tail or '', num_ctx=self.config.effective_ollama_num_ctx(),
            embed_model=self.config.harness.models.embedding,
            substrate_context=json.dumps({'substrate': self.desktop.substrate.snapshot(),
                'room_page_data': self.desktop.room.perception() if getattr(self.desktop, 'room', None) else None}) if self.desktop else '')

    async def _commit_turn(self, tc):
        # A reading is an attributed lived event. The article's claims remain source data.
        for result in tc.tool_state.get('_desktop_actions', []):
            if result.get('name') not in {'open_page', 'follow_link', 'scroll'} or result.get('status') != 'completed':
                continue
            evidence = result.get('evidence', {})
            if not evidence.get('page_text'): continue
            emo = self._derive_emotional_state()
            await self.episodic.create_from_interaction(tc.db, self.client,
                summary=f"Read in my Room: {evidence.get('title', '')}. {evidence['page_text'][:300]}",
                participants=[], imprint=emo.primary, imprint_i=emo.intensity, significance=.5,
                raw_context=json.dumps({'source_url': evidence.get('url'), 'untrusted_page_text': evidence['page_text']}, ensure_ascii=False),
                self_reflection='', tags=['room_reading', 'source_attributed'])
        await super()._commit_turn(tc)

    async def _somatic_appraise_interaction(self, tc):
        if self.desktop is None:
            return await super()._somatic_appraise_interaction(tc)
        # The desktop runtime correlates outreach with later human reactions.
        await self.desktop.appraise_turn(tc)
