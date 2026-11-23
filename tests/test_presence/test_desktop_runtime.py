import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from replicants.desktop.entity import DesktopEntity, DESKTOP_IDENTITY
from replicants.desktop.runtime import DesktopRuntime, PERSON, desktop_config
from replicants.inference.types import ChatCompletionResult, ToolCallSpec
from replicants.models import Input


class Client:
    def __init__(self):
        self.prompts = []
        self.choice = 'wave'

    async def ensure_models(self, *args): return True, []
    async def embed(self, *args, **kwargs): return [.1] * 768
    async def close(self): pass

    async def chat_completion(self, model, messages, **kwargs):
        self.prompts.append(messages)
        if messages[0]['content'].startswith('Read this felt note'):
            return ChatCompletionResult(json.dumps(self.last_changes))
        if kwargs.get('tools'):
            if any(m.get('role') == 'tool' for m in messages):
                return ChatCompletionResult('', tool_calls=[ToolCallSpec('end_turn', {})])
            return ChatCompletionResult('', tool_calls=[ToolCallSpec(self.choice, {})])
        if 'appraisal layer' in messages[0]['content']:
            full = json.dumps(messages)
            connected = 'human_reaction\\": \\"poke' in full or 'human_reaction\\": \\"chat' in full or 'body_received_touch' in full
            effects = {'social': -8 if connected else -.5, 'comfort': 5 if connected else 0,
                       'tension': -3 if connected else 2}
            self.last_changes = {name: 'less' if value < 0 else 'more' for name, value in effects.items() if value}
            return ChatCompletionResult(json.dumps({'bar_effects': {
                name: {'change': ('decreased' if value < 0 else 'increased') if name == 'comfort'
                       else ('eased' if value < 0 else 'raised'), 'amount': abs(value)}
                for name, value in effects.items()}, 'tags': ['contact' if connected else 'unanswered'],
                'felt': 'an observed outcome'}))
        return ChatCompletionResult('{}')


class Body:
    def __init__(self): self.published = []; self.actions = []; self.connected = True
    async def publish(self, kind, payload): self.published.append((kind, payload)); return True
    async def action(self, name, args):
        result = {'name': name, 'act_id': str(len(self.actions)), 'status': 'completed', 'detail': 'sequence_finished'}
        self.actions.append(result); return result


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('REPLICANTS_EXECUTION_WORKSPACE_DIR', str(tmp_path))
    config = desktop_config()
    config.harness.memory.database_path = str(tmp_path / 'memory.db')
    config.projects_path = lambda: str(tmp_path / 'projects.json')
    config.self_model_path = lambda: str(tmp_path / 'self_model.json')
    config.harness.memory.relational.enabled = False
    config.harness.memory.distillation.enabled = False
    config.harness.soma['noise']['enabled'] = False
    client = Client()
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: client)
    return DesktopRuntime(DesktopEntity(config), Body())


@pytest.mark.asyncio
async def test_ambient_is_allowlisted_and_never_calls_model(runtime):
    for count in range(30):
        await runtime.receive({'type': 'sense', 'payload': {'window_count': count, 'window_ids': ['1'],
            'idle_seconds': 40, 'title': 'PRIVATE', 'screenshot': 'PRIVATE', 'active_app': 'PRIVATE'}})
    assert runtime.entity.client.inner.prompts == []
    assert not runtime._jobs.qsize()
    assert 'PRIVATE' not in json.dumps(runtime.senses)
    await runtime.receive({'type': 'control', 'payload': {'name': 'active_app'}})
    await runtime.receive({'type': 'sense', 'payload': {'window_count': 1, 'window_ids': ['1'], 'idle_seconds': 0, 'active_app': 'editor.exe'}})
    assert runtime.senses['active_app'] == 'editor.exe'
    await runtime.receive({'type': 'control', 'payload': {'name': 'active_app'}})
    assert 'active_app' not in runtime.senses
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_touch_is_immediate_coalesced_learned_and_restored(runtime):
    before = dict(runtime.entity.tonic.bars._values)
    for _ in range(20): await runtime.receive({'type': 'event', 'payload': {'kind': 'poke'}})
    assert runtime.entity.tonic.bars._values['social'] > before['social']
    assert runtime.entity.client.inner.prompts == []
    await runtime.appraise_touches()
    assert runtime.entity.client.inner.prompts == []
    runtime._last_touch_appraisal -= 9
    await runtime.appraise_touches()
    assert len(runtime.entity.client.inner.prompts) == 2  # Appraisal plus its metered consistency check.
    marker = dict(runtime.entity.tonic.bars._somatic_markers[PERSON])
    assert marker['comfort'] > 0
    from replicants.identity.soma import TonicBody
    restored = TonicBody(runtime.entity.config.harness.soma, Path(runtime.entity.config.soma_dir()))
    assert restored.restore_state()
    assert restored.bars._somatic_markers[PERSON]['comfort'] == pytest.approx(marker['comfort'], abs=1e-5)
    await runtime.entity.shutdown()


async def want(runtime):
    bars = runtime.entity.tonic.bars
    key = bars.record_desire(drive='social', impulse_type='reach_out', label='reach_out', pressure=90)
    bars.start_desire(key)
    inp = Input('I feel like connecting', 'self', 'self', 'desktop', 'autonomous', metadata={'soma_desire_id': key})
    result = await runtime.perform('wave', {}, inp)
    await runtime.appraise_turn(SimpleNamespace(inp=inp, tool_state={'_desktop_actions': [result]}))
    return key


@pytest.mark.asyncio
async def test_outreach_waits_for_reaction_and_ignored_relief_is_smaller(runtime):
    bars = runtime.entity.tonic.bars
    before = bars._values['social']
    key = await want(runtime)
    assert bars._values['social'] == before
    assert key in bars.pending_desires
    await runtime.settle_outreach()
    assert runtime.entity.client.inner.prompts == []
    runtime.outreach[key]['deadline'] = time.time() - 1
    await runtime.settle_outreach()
    ignored = before - bars._values['social']
    assert key not in bars.pending_desires
    key = await want(runtime)
    await runtime.receive({'type': 'event', 'payload': {'kind': 'poke'}})
    before = bars._values['social']
    await runtime.settle_outreach()
    connected = before - bars._values['social']
    assert connected > ignored * 3
    assert key not in bars.pending_desires
    assert not runtime.outreach
    assert PERSON in bars._somatic_markers
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_existing_entity_pipeline_uses_body_tools_and_permits_silence(runtime):
    await runtime.entity.perceive(Input('hello little one', PERSON, 'the person here', 'desktop', 'desktop'))
    assert [a['name'] for a in runtime.platform.actions] == ['wave']
    decision = [p for p in runtime.entity.client.inner.prompts if p[0]['content'].startswith(DESKTOP_IDENTITY)]
    assert decision
    assert all('assistant' not in p[0]['content'].lower() and 'tasks to complete' in p[0]['content'] for p in decision)
    assert PERSON in runtime.entity.tonic.bars._somatic_markers
    runtime.entity.client.inner.choice = 'end_turn'
    count = len(runtime.platform.actions)
    text, _ = await runtime.entity.perceive(Input('you may rest', PERSON, 'the person here', 'desktop', 'desktop'))
    assert text == '' and len(runtime.platform.actions) == count
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_no_action_is_creature_choice_not_a_host_rule(runtime):
    bars = runtime.entity.tonic.bars
    key = bars.record_desire(drive='social', impulse_type='reach_out', label='reach_out', pressure=90)
    bars.start_desire(key)
    inp = Input('an urge', 'self', 'self', metadata={'soma_desire_id': key})
    before = dict(bars._values)
    await runtime.appraise_turn(SimpleNamespace(inp=inp, tool_state={}))
    assert bars._values == before
    assert bars.pending_desires[key]['gate_type'] == 'creature_choice'
    bars.note_desire_gate('cooldown', 'host_rule')
    assert bars.pending_desires[key]['gate_type'] == 'creature_choice'
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_sleep_follows_pressure_on_the_body_clock_while_host_limits_keep_real_time(runtime, monkeypatch):
    from replicants.desktop.clock import SimClock
    monkeypatch.setenv('REPLICANTS_TIME_SCALE', '60')
    monkeypatch.setenv('REPLICANTS_START_HOUR', '12')
    tick = [0.0]
    # Fix the date: an elapsed 18-hour interval across DST need not end at 06:00.
    daytime = time.mktime((2026, 10, 13, 12, 0, 0, 0, 0, -1))
    runtime.clock = SimClock(wall=lambda: daytime, monotonic=lambda: tick[0])
    runtime.entity.dream_engine.clock = runtime.clock.now
    runtime._life_real, runtime._life_sim = time.monotonic(), runtime.clock.now()
    runtime.senses = {'idle_seconds': 90}
    runtime.last_person_at = time.time() - 3600
    transitions = []
    for _ in range(int(24 * 60 / 10)):           # one body day in 10-minute steps
        tick[0] += 600 / 60
        before = runtime.asleep
        await runtime.life_tick()
        if runtime.asleep != before:
            transitions.append((round(runtime.clock.hour, 1), runtime.asleep))
        if runtime.asleep:
            runtime.life_loop.vigilance.episode['real_seconds'] = 999
            await runtime.sleep_work()
    (slept_at, s1), (woke_at, s2) = transitions[:2]
    assert s1 and not s2
    assert 20 <= slept_at or slept_at < 2              # pressure plus circadian put sleep in the evening
    assert 4 <= woke_at <= 11                          # and waking in the morning
    assert runtime.life_loop.development.nights == 1
    assert runtime.life_loop.last_sleep['work_done']
    assert 'consolidated' in runtime.life_loop.last_sleep   # recorded honestly, success or not
    bars = runtime.entity.tonic.bars
    key = bars.record_desire('curiosity', 'explore', 'test curiosity', 99)
    runtime.guard._last_cycle_at = time.time()
    runtime.last_person_at = time.time() - 100
    assert await runtime.next_wake_reason() is None
    assert bars.pending_desires[key]['gate_reason'] == 'cooldown'      # host limits stay in real time
    assert not runtime.entity.client.calls
    await runtime.request_sleep('person')
    assert runtime.asleep
    await runtime.receive({'type': 'event', 'payload': {'kind': 'poke'}})
    assert runtime.asleep                              # the person asked for this sleep; a poke does not end it
    await runtime.receive({'type': 'control', 'payload': {'name': 'wake'}})
    assert not runtime.asleep
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_inspector_exposes_lived_data_and_classifies_no_opportunity(runtime):
    async with runtime.entity.store.session() as db:
        await db.execute('INSERT INTO episodes (id,timestamp,summary) VALUES (?,?,?)', ('one', time.time(), '<a remembered touch>'))
        await db.commit()
    bars = runtime.entity.tonic.bars
    key = bars.record_desire('social', 'reach_out', 'connection', 90)
    bars.pending_desires[key]['fired_at'] -= bars._desire_ttl + 1
    bars.expire_desires()
    bars._somatic_markers[PERSON] = {'comfort': 1.25}
    data = await runtime.inspect()
    assert data['memories'][0]['summary'] == '<a remembered touch>'
    assert data['markers'][PERSON]['comfort'] == 1.25
    assert data['unlived_wants'][-1]['gate_type'] == 'environment'
    assert data['unlived_wants'][-1]['gate_reason'] == 'not_selected'
    assert data['clock']['scale'] == 1 and data['model_calls_last_minute'] == 0
    assert 'energy' not in data['state']
    assert data['substrate']['inference']['seconds_since_last_completed_thought'] is None
    assert data['substrate']['gpu']['status'] == 'not_sampled'
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_solitary_action_is_not_presented_as_ignored_outreach(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    appraisal = AsyncMock(return_value={'bar_effects': {}, 'tags': [], 'felt': ''})
    monkeypatch.setattr(runtime.entity.tonic, 'appraise_interaction_and_apply', appraisal)
    await runtime._appraise('A quiet moment', [{'name': 'inspect_window', 'status': 'completed',
        'evidence': {'window_id': '123', 'width': 500}}], person=False)
    data = appraisal.call_args.kwargs
    assert json.loads(data['reply_text'])['human_reaction'] == 'not_applicable'
    assert 'not unanswered outreach' in data['outcome_context']
    assert data['person_id'] == ''
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_self_wake_does_not_create_a_relationship_reflection(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    reflection = AsyncMock(return_value=True)
    monkeypatch.setattr('replicants.memory.relational_reflection.run_relational_reflection_after_turn', reflection)
    monkeypatch.setattr(runtime.entity, '_relational_docs_enabled', lambda: True)
    runtime.entity.client.inner.choice = 'end_turn'
    await runtime.entity.perceive(Input('A quiet moment with my body and the nearby edges.', 'self', 'self', 'desktop', 'autonomous'),
        record_user_message=False, skip_relational_upsert=True, skip_drive_interaction=True)
    reflection.assert_not_awaited()
    assert runtime.guard._auto.wake_spacing_extra_minutes_max == 0
    assert not any(e['type'] == 'message_sent' for e in runtime.entity.tonic._recent_events)
    assert not any('appraisal layer' in p[0]['content'] for p in runtime.entity.client.inner.prompts)
    async with runtime.entity.store.session() as db:
        rows = await (await db.execute('SELECT summary,participants FROM episodes')).fetchall()
    assert rows and all('Conversation with self' not in row[0] and json.loads(row[1]) == [] for row in rows)
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_empty_outreach_appraisal_retries_without_erasing_the_want(runtime, monkeypatch):
    from unittest.mock import AsyncMock
    key = await want(runtime)
    runtime.outreach[key]['deadline'] = time.time() - 1
    appraisal = AsyncMock(return_value={'bar_effects': {}, 'tags': [], 'felt': ''})
    monkeypatch.setattr(runtime.entity.tonic, 'appraise_interaction_and_apply', appraisal)
    await runtime.settle_outreach()
    assert key in runtime.outreach and key in runtime.entity.tonic.bars.pending_desires
    await runtime.settle_outreach()
    assert appraisal.await_count == 1  # Retry interval stays in real time.
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_desktop_gen_uses_body_framing_and_actual_geometry_events(runtime):
    await runtime.entity.tonic.noise.generate(runtime.entity.client, 'model', bars_summary='curiosity: 90',
        affects_summary='curious', recent_events=[{'type': 'desktop_ambient', 'window_count': 3, 'idle': True, 'hour': 12},
            {'type': 'desktop_action', 'name': 'inspect_window', 'status': 'completed', 'detail': 'measured', 'evidence': {'width': 200}}],
        journal_tail='', conversation_tail='', entity_name='Pebble')
    prompt = runtime.entity.client.inner.prompts[-1]
    assert 'subconscious of Pebble' in prompt[0]['content']
    assert '3 window edges' in prompt[1]['content'] and "'width': 200" in prompt[1]['content']
    assert 'Include one domestic or tool/chore detail' not in json.dumps(prompt)
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_compute_reaches_cognition_gen_and_persisted_body(runtime):
    # Shared memory/cognition clients must not bypass accounting.
    for component in (runtime.entity.knowledge, runtime.entity.procedural, runtime.entity.router, runtime.entity.deliberate):
        assert component.client is runtime.entity.client
    await runtime.entity.perceive(Input('A measured moment beside these window edges.', PERSON, 'person', 'desktop', 'desktop'))
    decisions = [p for p in runtime.entity.client.inner.prompts if p[0]['content'].startswith(DESKTOP_IDENTITY)]
    experience = next(m['content'] for m in decisions[0] if str(m.get('content', '')).startswith('[Present experience]\n'))
    context = json.loads(experience.split('[Present experience]\n', 1)[1].split('\n\n[Stimulus]', 1)[0])
    assert context['substrate']['inference']['totals']['embedding']['completed'] >= 1
    assert context['substrate']['gpu']['status'] == 'not_sampled'
    assert 'energy' not in runtime.state()
    runtime.entity.tonic._noise_enabled = True
    runtime.entity.tonic.noise._last_tick = -1e9
    await runtime.entity.maybe_tick_noise_heartbeat()
    assert 'MEASURED PHYSICAL SUBSTRATE' in runtime.entity.client.inner.prompts[-1][1]['content']
    runtime.save_runtime()
    saved = json.loads(runtime._runtime_path.read_text())
    assert saved['compute']['totals'] == runtime.compute.totals
    assert 'hardware' not in saved['compute']  # Measurements from this host are never restored as live readings.
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_a_clock_is_not_a_reason_to_wake(runtime, monkeypatch):
    monkeypatch.setattr(runtime.guard, 'should_wake', lambda **kwargs: 'timer')
    assert await runtime.next_wake_reason() is None
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_appraised_outcomes_teach_expectation_in_the_lived_context(runtime):
    runtime.last_person_at = time.time() - 3600
    runtime.senses = {'idle_seconds': 3600}
    key = await want(runtime)
    runtime.life_loop.begin(key, 'reach_out', runtime.life_context())
    runtime.outreach[key]['deadline'] = time.time() - 1
    await runtime.settle_outreach()
    ignored = runtime.life_loop.expectations.buffer[-1]
    assert ignored['ctx'].startswith('alone/') and ignored['actions'] == ['wave'] and ignored['r'] < 0
    key = await want(runtime)
    await runtime.receive({'type': 'event', 'payload': {'kind': 'poke'}})
    await runtime.settle_outreach()
    answered = runtime.life_loop.expectations.buffer[-1]
    assert answered['r'] > 0.25 > ignored['r']
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_a_being_lets_an_urge_pass_alone_and_acts_on_it_with_the_person(runtime, monkeypatch):
    loop = runtime.life_loop
    for _ in range(5):
        for _ in range(6):
            loop.outcome('x', 'reach_out', 'social', ['wave', 'approach_cursor', 'say'], {'social': -.5, 'tension': 2},
                         f'alone/{runtime.life_context().split("/")[1]}', runtime.clock.now())
        loop.vigilance.request_sleep('self', 0, 0, 23); loop.sleep_work(); loop.vigilance.state = 'awake'
    alone = f'alone/{runtime.life_context().split("/")[1]}'
    for action in ('sit', 'look_at', 'emote', 'walk_to', 'inspect_window'):
        for ctx in ('*', alone):    # tried alone already, and none of these ever eased the want
            loop.expectations.values[f'reach_out|{action}|{ctx}'] = {'q': -.1, 'n': 40}
    bars = runtime.entity.tonic.bars
    key = bars.record_desire('social', 'reach_out', 'reach_out', 90)
    monkeypatch.setattr(runtime.guard, 'should_wake', lambda **kwargs: 'impulse:reach_out')
    runtime.last_person_at = time.time() - 3600
    runtime.senses = {'idle_seconds': 3600}
    assert await runtime.next_wake_reason() is None
    assert bars.pending_desires[key]['gate_type'] == 'creature_choice'
    assert bars.pending_desires[key]['gate_reason'].startswith('expects_little')
    runtime.senses = {'idle_seconds': 2}                # the person is back at the computer
    assert await runtime.next_wake_reason() == 'impulse:reach_out'
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_being_lifted_wakes_a_sleeper_and_life_persists(runtime):
    runtime.life_loop.vigilance.S = 0.9
    await runtime.request_sleep('self')
    await runtime.receive({'type': 'event', 'payload': {'kind': 'poke'}})
    assert runtime.asleep                               # too deep for a poke
    await runtime.receive({'type': 'event', 'payload': {'kind': 'drag_start'}})
    assert not runtime.asleep
    assert runtime.life_loop.last_sleep['woke_by'] == 'aroused_by_drag_start'
    runtime.save_runtime()
    saved = json.loads(runtime._runtime_path.read_text(encoding='utf-8'))['life_loop']
    assert saved['vigilance']['S'] == pytest.approx(0.9)
    assert saved['last_sleep']['woke_by'] == 'aroused_by_drag_start'
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_decision_context_carries_the_beings_own_history(runtime):
    bars = runtime.entity.tonic.bars
    key = bars.record_desire('curiosity', 'explore', 'explore_something', 95)
    runtime.life_loop.outcome('y', 'explore', 'curiosity', ['inspect_window'], {'curiosity': -20},
                              runtime.life_context(), runtime.clock.now())
    await runtime.entity.perceive(Input('a pull', 'self', 'self', 'desktop', 'autonomous',
                                        metadata={'soma_desire_id': key}))
    prompt = next(p for p in runtime.entity.client.inner.prompts if p[0]['content'].startswith(DESKTOP_IDENTITY))
    present = next(m['content'] for m in prompt if '[Present experience]' in str(m.get('content')))
    life = json.loads(present.split('[Present experience]\n')[1].split('\n\n[Stimulus]')[0])['life']
    lived = life['what_acting_on_this_want_has_brought_before']
    assert lived[0]['action'] == 'inspect_window' and lived[0]['unslept_times'] == 1
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_sleep_ownership_is_saved_when_person_claims_an_existing_sleep(runtime):
    await runtime.request_sleep('self')
    await runtime.request_sleep('person')
    saved = json.loads(runtime._runtime_path.read_text(encoding='utf-8'))['life_loop']
    assert saved['vigilance']['forced'] == 'person'
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_interrupted_consolidation_cannot_replay_into_the_next_sleep(runtime, monkeypatch):
    loop = runtime.life_loop
    loop.outcome('d', 'explore', 'curiosity', ['inspect_window'], {'curiosity': -20}, 'alone/night', 0)
    await runtime.request_sleep('self')
    original = loop.vigilance.episode
    original['real_seconds'] = runtime.sleep_settle_seconds + 1

    async def interrupted(entity):
        event = loop.vigilance.wake_by_person(*runtime._vigilance_now(), hold_real_seconds=0)
        await runtime._life_events([event])
        await runtime.request_sleep('self')

    monkeypatch.setattr(runtime._consolidation, 'run_for_daemon', interrupted)
    await runtime.sleep_work()
    assert loop.vigilance.episode is not original
    assert not loop.vigilance.episode['work_done']
    assert loop.development.nights == 0 and len(loop.expectations.buffer) == 1
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_model_body_actions_cannot_override_a_sleeping_body(runtime):
    await runtime.request_sleep('person')
    for name in ('wave', 'say', 'wake_up'):
        result = await runtime.perform(name, {'text': 'hello'}, Input('rest', 'self', 'self', 'desktop', 'autonomous'))
        assert result['status'] == 'interrupted' and result['detail'] == 'body_asleep'
    assert runtime.platform.actions == [] and runtime.asleep
    await runtime.entity.shutdown()


def test_every_body_wake_reason_names_a_want():
    from replicants.desktop.runtime import wake_want
    assert wake_want('drive:connection') == 'reach_out'
    assert wake_want('drive:autonomy, expression') == 'create'
    assert wake_want('drive:autonomy') == 'explore'
    assert wake_want('conflict:restless') == 'resolve_tension'
    assert wake_want('desire:reach_out:the person') == 'reach_out'
    assert wake_want('desire:follow_thread') == 'explore'
    assert wake_want('noise:why is it quiet?') == 'explore'
    assert wake_want('timer') is None


@pytest.mark.asyncio
async def test_a_drive_wake_is_gated_and_then_lived_as_a_want(runtime, monkeypatch):
    loop = runtime.life_loop
    alone = f'alone/{runtime.life_context().split("/")[1]}'
    from replicants.desktop.runtime import WANT_ACTIONS
    for action in WANT_ACTIONS:
        for ctx in ('*', alone):
            loop.expectations.values[f'reach_out|{action}|{ctx}'] = {'q': -.1, 'n': 40}
    bars = runtime.entity.tonic.bars
    bars.pending_desires.clear()
    monkeypatch.setattr(runtime.guard, 'should_wake', lambda **kwargs: 'drive:connection')
    runtime.last_person_at = time.time() - 3600
    runtime.senses = {'idle_seconds': 3600}
    assert await runtime.next_wake_reason() is None      # the drive wake passed through expectation
    [key] = [k for k, d in bars.pending_desires.items() if d['label'] == 'wake:reach_out']
    assert bars.pending_desires[key]['gate_type'] == 'creature_choice'
    runtime.senses = {'idle_seconds': 2}
    assert await runtime.next_wake_reason() == 'drive:connection'
    seen = []
    async def perceive(inp, **kwargs): seen.append(inp.metadata['soma_desire_id'])
    monkeypatch.setattr(runtime.entity, 'perceive', perceive)
    await runtime.wake('drive:connection')
    assert seen == [key] and bars.pending_desires[key]['started_at'] is not None
    assert loop.started[key]['want'] == 'reach_out'          # appraisal will teach this want
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_tool_mode_counts_decisions_and_survives_a_recovered_bad_call(runtime):
    calls = [[ToolCallSpec('fly', {})], [ToolCallSpec('wave', {})], [ToolCallSpec('say', {})], [ToolCallSpec('end_turn', {})]]
    async def chat_completion(model, messages, **kwargs):
        if kwargs.get('tools'):
            return ChatCompletionResult('', tool_calls=calls.pop(0) if calls else [ToolCallSpec('end_turn', {})])
        return ChatCompletionResult('{}')
    runtime.entity.client.chat_completion = chat_completion
    await runtime.entity.perceive(Input('hello', PERSON, 'the person here', 'desktop', 'desktop'))
    stats = runtime.entity.decision_stats
    assert stats['errors'] == {'unknown_action': 1, 'say_without_text': 1}
    assert stats['invalid'] == 2 and stats['valid'] >= 1
    assert [a['name'] for a in runtime.platform.actions] == ['wave']
    await runtime.entity.shutdown()


def test_the_subconscious_is_free_and_the_conscious_voice_knows_its_thoughts_as_thoughts():
    from replicants.desktop.inference import BOUNDARY, SUBCONSCIOUS
    noise = desktop_config().harness.soma['noise']
    assert noise['identity_prompt'].startswith(SUBCONSCIOUS)
    assert 'invent' in noise['identity_prompt'] and noise['wander'] > 0 and noise['style_filter'] is False
    assert 'subconscious' in DESKTOP_IDENTITY and 'record of what happened' in DESKTOP_IDENTITY
    assert 'name its source as your' in DESKTOP_IDENTITY
    assert 'no colors, sounds or room objects' in DESKTOP_IDENTITY
    assert 'remembered as thoughts' in BOUNDARY
    assert desktop_config().harness.soma['noise_seeder']['enabled'] is True


@pytest.mark.asyncio
async def test_gen_calls_skip_the_sensory_boundary_and_other_calls_keep_it(monkeypatch):
    from replicants.desktop.inference import DesktopOllama, BOUNDARY, SUBCONSCIOUS
    sent = []
    class Session:
        def post(self, url, json, allow_redirects):
            sent.append(json)
            class R:
                async def __aenter__(s): return s
                async def __aexit__(s, *a): return False
                def raise_for_status(s): pass
                async def json(s): return {'message': {'role': 'assistant', 'content': 'ok'}}
            return R()
    transport = SimpleNamespace(retry_attempts=1, retry_delay=0, base_url='http://127.0.0.1:1',
                                _parse_chat_response=lambda d: ChatCompletionResult(d['choices'][0]['message']['content']))
    async def session_get(): return Session()
    transport._session_get = session_get
    client = object.__new__(DesktopOllama); client._t = transport
    await client.chat_completion('m', [{'role': 'system', 'content': SUBCONSCIOUS + ' Rill.'}])
    await client.chat_completion('m', [{'role': 'system', 'content': 'You are the appraisal layer.'}])
    assert not sent[0]['messages'][0]['content'].startswith(BOUNDARY)
    assert sent[1]['messages'][0]['content'].startswith(BOUNDARY)


@pytest.mark.asyncio
async def test_provider_tool_parse_failure_recovers_as_json_and_counts_the_error(runtime):
    from replicants.desktop.inference import NativeToolProtocolError
    async def chat_completion(model, messages, **kwargs):
        if kwargs.get('tools'): raise NativeToolProtocolError('native_tool_parse_error')
        return ChatCompletionResult('{"action":"rest","args":{},"say":""}')
    runtime.entity.client.chat_completion = chat_completion
    await runtime.entity.perceive(Input('hello', PERSON, 'the person here', 'desktop', 'desktop'))
    stats = runtime.entity.decision_stats
    assert stats['errors'] == {'native_tool_parse_error': 1} and stats['json_fallbacks'] == 1
    assert stats['valid'] >= 1 and not runtime.platform.actions
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_a_repeated_empty_speech_call_finishes_the_turn_as_a_json_decision(runtime):
    async def chat_completion(model, messages, **kwargs):
        if kwargs.get('tools'):
            return ChatCompletionResult('', tool_calls=[ToolCallSpec('say', {})])
        if any('Observed results' in str(m.get('content')) for m in messages):
            return ChatCompletionResult('{"action":"rest","args":{},"say":""}')
        return ChatCompletionResult('{"action":"say","args":{"text":"hi, i am here"},"say":""}')
    runtime.entity.client.chat_completion = chat_completion
    await runtime.entity.perceive(Input('hello', PERSON, 'the person here', 'desktop', 'desktop'))
    stats = runtime.entity.decision_stats
    assert stats['errors'] == {'say_without_text': 2} and stats['json_fallbacks'] == 1
    assert [a['name'] for a in runtime.platform.actions] == ['say']
    await runtime.entity.shutdown()


def test_speech_is_fitted_at_a_word_or_sentence_boundary():
    from replicants.desktop.decision import clip_speech
    words = ' '.join(['ocean'] * 60)
    clipped = clip_speech(words)
    assert len(clipped) <= 240 and clipped.endswith('ocean…')
    sentences = 'The stars steer us. ' * 15
    assert clip_speech(sentences).endswith('us.') and len(clip_speech(sentences)) <= 240
    assert clip_speech('short') == 'short'


def test_a_document_that_gives_the_beings_name_to_the_person_is_caught():
    from replicants.memory.relational_reflection import role_confusion
    assert role_confusion('When Rill greeted me by name, I felt seen.', 'Rill', 'the person here') == 'Rill greeted'
    assert role_confusion("We talked about what I can see of Rill's screen.", 'Rill', 'the person here')
    assert role_confusion('I am Rill. They greeted me and I felt seen.', 'Rill', 'the person here') == ''


@pytest.mark.asyncio
async def test_memory_prompts_use_the_name_the_being_was_given(runtime):
    assert runtime.entity.living_name == 'an unnamed Replicant'
    runtime.display_name = 'Rill'
    assert runtime.entity.living_name == 'Rill' and runtime.entity.dream_engine.name_of() == 'Rill'
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_json_recovery_shares_the_native_turn_action_allowance(runtime):
    native_round = 0
    async def chat_completion(model, messages, **kwargs):
        nonlocal native_round
        if kwargs.get('tools'):
            native_round += 1
            if native_round == 1:
                return ChatCompletionResult('', tool_calls=[ToolCallSpec(name, {})
                    for name in ('wave', 'sit', 'look_at', 'inspect_window')])
            return ChatCompletionResult('', tool_calls=[ToolCallSpec('say', {})])
        if 'Choose what your body does' in messages[0]['content']:
            return ChatCompletionResult('{"action":"wave","args":{},"say":"hello"}')
        return ChatCompletionResult('{}')
    runtime.entity.client.chat_completion = chat_completion
    await runtime.entity.perceive(Input('hello', PERSON, 'the person here', 'desktop', 'desktop'))
    assert runtime.entity.decision_stats['json_fallbacks'] == 1
    assert len(runtime.platform.actions) == 4
    assert all(action['name'] != 'say' for action in runtime.platform.actions)
    await runtime.entity.shutdown()


@pytest.mark.asyncio
async def test_inspector_reads_hourly_allowance_without_mutation_while_sleeping(runtime):
    async with runtime.entity.store.session(): pass
    runtime.guard._hour_start = time.time() - 3601
    runtime.guard._cycle_count_this_hour = 6
    original_start = runtime.guard._hour_start
    snapshot = await runtime.inspect()
    assert snapshot['wake_limits']['wakes_this_hour'] == 6
    assert snapshot['wake_limits']['window_expires_at'] == original_start + 3600
    assert runtime.guard._hour_start == original_start
    assert snapshot['learning']['turn_telemetry'] == 'disabled_optional_modules_absent'
    await runtime.entity.shutdown()
