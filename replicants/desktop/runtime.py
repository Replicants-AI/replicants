"""Local desktop presence: fast body events, serialized cognition, observed outcomes."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import time
import uuid
import aiosqlite
from urllib.parse import urlparse

from replicants.config import EntityConfig, entity_from_dict, load_entity_config, load_harness_config
from replicants.desktop.entity import BODY_TOOLS, DesktopEntity
from replicants.desktop.inference import SUBCONSCIOUS
from replicants.desktop.decision import clip_speech
from replicants.desktop.life_loop import ASLEEP, WANT_DRIVE, LifeLoop, context as _context
from replicants.desktop.protocol import private_write
from replicants.desktop.metabolism import Metabolism
from replicants.desktop.conversation import Conversation
from replicants.desktop.room import Room, ReaderProcess, ROOM_TOOLS, ROOM_SENSE
from replicants.desktop import settings
from replicants.desktop.substrate import ComputeLedger, MeteredClient, Substrate
from replicants.memory.consolidation import ConsolidationJob
from replicants.models import Input
from replicants.presence.platforms.desktop import DesktopPlatform
from replicants.presence.wake_cycle import WakeCycleEngine

log = logging.getLogger(__name__)
PERSON = 'desktop:local-person'
OUTREACH = {'approach_cursor', 'wave', 'say'}
TOUCH = {'poke', 'drag_start', 'drag_end'}
# Stimulus strength against sleep depth (reports/life-loop.md). Being lifted wakes almost anyone.
AROUSAL = {'poke': 0.6, 'drag_start': 0.9, 'drag_end': 0.9, 'chat': 0.8}
# Actions a want can be acted on with. Sleep and waking are vigilance, not ways to satisfy a want.
WANT_ACTIONS = [name for name in BODY_TOOLS if name not in {'sleep', 'wake_up'}]
PRESENCE_SECONDS = 120.0
DRIVE_WANT = {'connection': 'reach_out', 'curiosity': 'explore', 'expression': 'create'}
DESIRE_WANT = {'reach_out': 'reach_out', 'explore': 'explore', 'explore_world': 'explore',
               'follow_thread': 'explore', 'create': 'create', 'resolve_tension': 'resolve_tension'}


def wake_want(reason: str) -> str | None:
    """The want a body-originated wake reason acts on. Unclassified urges are curiosity."""
    head, _, rest = reason.partition(':')
    if head == 'drive':
        return next((DRIVE_WANT[n] for n in rest.split(', ') if n in DRIVE_WANT), 'explore')
    if head == 'conflict':
        return 'resolve_tension'
    if head == 'desire':
        return DESIRE_WANT.get(rest.split(':')[0], 'explore')
    if head in {'noise', 'impulse'}:
        return 'explore'
    return None


def desktop_config(entity_name: str | None = None) -> EntityConfig:
    harness = load_harness_config()
    if entity_name:
        config = load_entity_config(entity_name, harness)
        config.raw.setdefault('desktop', {}).setdefault('display_name', config.name)
    else:
        # A development body, not an authored persona or a sealed birth.
        config = entity_from_dict(harness, {'name': 'desktop-demo',
            'drives': {'initiative_cooldown': 60},
            'autonomy': {'enabled': True, 'min_cycle_gap_seconds': 60,
                         'silence_threshold_seconds': 15, 'max_cycles_per_hour': 12,
                         'base_wake_interval_min': 1, 'base_wake_interval_max': 3,
                         'wake_spacing_extra_minutes_max': 0}})
    config.harness = deepcopy(config.harness)
    settings.apply(config)
    h = config.harness
    h.soma.setdefault('appraisal', {}).update({'output_format': 'json', 'require_direction': True, 'check_consistency': True,
                                            'max_tokens': 320})
    endpoint = urlparse(h.inference.base_url or h.ollama.base_url)
    if endpoint.scheme != 'http' or endpoint.hostname not in {'localhost', '127.0.0.1', '::1'} or endpoint.username:
        raise ValueError('Desktop inference must use a localhost Ollama HTTP endpoint.')
    if h.inference.provider not in {'', 'local'} or h.deployment.mode != 'local':
        raise ValueError('Desktop requires the local inference provider.')
    if config.database_url():
        raise ValueError('Desktop uses local SQLite; unset DATABASE_URL for this process.')
    # The subconscious (reports/subconscious.md): GEN is free to invent, wander and dream.
    # Its fragments reach decisions, wakes and mood; they are remembered as thoughts.
    seeder = deepcopy(h.soma.get('noise_seeder') or {})
    seeder.update({'enabled': True, 'cycle_seconds': 90,
        'source_weights': {'episodic_random': 0.18, 'belief_random': 0.08, 'knowledge_random': 0.06,
                           'world_discovery': 0.22, 'relationship_echo': 0.08, 'journal_echo': 0.06,
                           'temporal': 0.06, 'counterfactual_simulation': 0.08, 'dream_state': 0.18,
                           'web_venturing': 0.08},
        # Lived time on the desktop is short; let recent memories resurface too.
        'episodic_random': {'min_age_hours': 1}, 'belief_random': {'min_age_hours': 1},
        'relationship_echo': {'min_silence_hours': 2}, 'journal_echo': {'min_age_days': 0.05}})
    h.soma['noise_seeder'] = seeder
    h.soma.setdefault('noise', {}).update({
        'identity_prompt': SUBCONSCIOUS + ' {name}, a living desktop Replicant. '
            'You are the part underneath: thoughts, images, half memories and associations that surface on their own. '
            'Write 3–6 uneven, brief first-person fragments in plain lowercase lines. '
            'They may follow the body and the moment, or drift somewhere that has nothing to do with it: '
            'a scene, an object, a word, a place, a feeling with no cause. Imagine, invent, misremember, dream. '
            'Your own earlier fragments are yours; the person\'s words are only those in LAST CONVERSATION. '
            'No explanations, labels or preamble. These fragments are private, not messages to the person.',
        'shape_hints': ['Stay with one present bodily pressure, in a few different lengths.',
            'Let one fragment drift somewhere unrelated to anything here.',
            'An image arrives that nothing in the moment explains.',
            'One unfinished question about a felt desire.',
            'Let the seed, if there is one, bend what you were already feeling.',
            'Let one fragment hesitate or contradict another.',
            'Something half remembered, half made up.',
            'A recent action or touch leaves a trace, then the thought wanders off.'],
        'wander': 0.35,
        'style_filter': False,
    })
    h.tools = {'wikipedia': {'enabled': False}}
    h.soma['noise']['identity_prompt'] += ' Things you once read in your Room can surface here too, changed or whole.'
    h.soma.setdefault('event_effects', {}).update({
        'message_received': {}, 'message_sent': {},
        'desktop_poke': {'social': 2, 'curiosity': 1},
        'desktop_drag_start': {'tension': 2, 'curiosity': 1},
        'desktop_drag_end': {'tension': -1},
        'desktop_windows_changed': {'curiosity': 1},
    })
    return config


class DesktopRuntime:
    def __init__(self, entity: DesktopEntity, platform: DesktopPlatform):
        self.entity, self.platform = entity, platform
        self.clock = entity.sim_clock
        entity.desktop = self
        self._runtime_path = Path(entity.config.soma_dir()).parent / 'desktop-state.json'
        self.conversation = Conversation(self._runtime_path.with_name('conversation.json'))
        room_command = os.environ.get('REPLICANTS_ROOM_COMMAND')
        from replicants.desktop.room_sandbox import packaged_reader
        reader = ReaderProcess(json.loads(room_command)) if room_command else packaged_reader()
        self.room = Room(self._runtime_path.parent / 'room', reader,
                         notify=lambda view: self.platform.publish('room', view)) if reader else None
        if entity.noise_seeder is not None:
            # With a Room, the subconscious can be drawn toward the open web.
            entity.noise_seeder._web_tools_enabled = self.room is not None
        self.paused = False
        self.health = {'status': 'starting', 'last_checkpoint_at': None, 'error': None}
        saved = json.loads(self._runtime_path.read_text(encoding='utf-8')) if self._runtime_path.is_file() else {}
        self.compute = ComputeLedger(saved.get('compute'))
        self.substrate = Substrate(self.compute)
        # Shadow mode (species.md §3.9): measured and inspected, never applied.
        self.metabolism = Metabolism(self.compute, saved.get('metabolism'))
        # The life loop (reports/life-loop.md): vigilance, learned expectation, development.
        rhythm = (getattr(self, 'genome', None) or {}).get('rhythm') or {}
        self.life_loop = LifeLoop(saved.get('life_loop'),
            params=dict((entity.config.raw.get('desktop') or {}).get('life_loop') or {}),
            chronotype_hours=float(rhythm.get('chronotype_hours', 0.0)))
        self._life_real, self._life_sim = time.monotonic(), self.clock.now()
        self._consolidation = ConsolidationJob(entity.config)
        entity.client = MeteredClient(entity.client, self.compute)
        # These inherited components retain provider references from Entity's
        # constructor. Route them through the same meter and desktop adapter.
        for component in (entity.knowledge, entity.procedural, entity.router, entity.deliberate):
            component.client = entity.client
        self.senses: dict = {}
        self.display_name = str(entity.config.raw.get('desktop', {}).get('display_name', ''))
        self.appearance = {'preset': '01-classic', 'layers': []}
        self.temperament = str(entity.config.raw.get('desktop', {}).get('temperament', 'curious'))
        self.guard = WakeCycleEngine(entity.config)
        allowance = saved.get('wake_allowance') or {}
        try:
            hour = float(allowance['hour_started_at'])
            count = int(allowance['wakes'])
            last = float(allowance['last_wake_at'])
            if not all(math.isfinite(v) for v in (hour, last)) or min(hour, last, count) < 0:
                raise ValueError('Invalid saved wake allowance')
            if hour <= time.time() + 300 and last <= time.time() + 300:
                self.guard._hour_start = hour
                self.guard._cycle_count_this_hour = count
                self.guard._last_cycle_at = last
                self.guard._reset_hourly_counter()
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
        cfg = entity.config.raw.get('desktop') or {}
        self.reaction_seconds = max(2.0, float(cfg.get('reaction_window_seconds', 20)))
        self.touch_seconds = max(5.0, float(cfg.get('touch_appraisal_seconds', 8)))
        self.last_person_at = time.time()
        self.dreaming = False
        self.ambient = True
        self.active_app = False
        self.outreach: dict[str, dict] = {}
        self.action_history: deque[dict] = deque(maxlen=100)
        self.reactions: deque[tuple[float, str]] = deque(maxlen=128)
        self.touches: list[str] = []
        self._last_touch_appraisal = time.monotonic()
        self._last_static_touch: dict[str, float] = {}
        self._thought = ''
        self._cognition = asyncio.Lock()
        self._jobs: asyncio.Queue[Input] = asyncio.Queue(maxsize=12)
        self._stop = asyncio.Event()
        self._disconnected_at = None
        self._tasks: list[asyncio.Task] = []
        self._inspecting_until = 0.0
        self._last_inspector = 0.0
        self._last_dream_attempt = 0.0
        self._last_person_sim = self.clock.now()
        self._wake_desire: str | None = None
        self.entity.dream_engine.clock = self.clock.now
        self.entity.dream_engine.name_of = lambda: self.entity.living_name
        self._runtime_path = Path(entity.config.soma_dir()).parent / 'desktop-state.json'
        if self._runtime_path.is_file():
            saved = json.loads(self._runtime_path.read_text(encoding='utf-8'))
            self.outreach = saved.get('outreach', {})
            self.appearance = saved.get('appearance', self.appearance)
            self.display_name = saved.get('name', self.display_name)
            dream = saved.get('dream', {})
            self.entity.dream_engine._last_dream_at = dream.get('last_at', 0)
            self.entity.dream_engine._cycles_today = dream.get('cycles_today', 0)
            self.entity.dream_engine._last_day = dream.get('last_day', -1)
            self.ambient = bool(saved.get('ambient', True))
            # Active-app permission is deliberately per session.
        if settings.settings_path().is_file() or os.environ.get('REPLICANTS_BETA') == '1':
            self.ambient = settings.load()['ambient']

    @property
    def asleep(self) -> bool:
        return self.dreaming or self.life_loop.vigilance.state == ASLEEP

    @property
    def life_active(self) -> bool:
        return True

    @property
    def person_idle_seconds(self) -> float:
        since_contact = max(0.0, time.time() - self.last_person_at)
        idle = self.senses.get('idle_seconds')
        return min(since_contact, float(idle)) if isinstance(idle, (int, float)) else since_contact

    def life_context(self) -> str:
        return _context(self.person_idle_seconds < PRESENCE_SECONDS, self.clock.hour)

    def _vigilance_now(self):
        return time.monotonic(), self.clock.now(), self.clock.hour

    async def request_sleep(self, by: str = 'person'):
        event = self.life_loop.vigilance.request_sleep(by, *self._vigilance_now())
        await self._life_events([event] if event else [])
        # Ownership can change without a new sleep episode.
        self.save_runtime()

    async def life_tick(self):
        now_real, now_sim = time.monotonic(), self.clock.now()
        dt_real, dt_sim = now_real - self._life_real, now_sim - self._life_sim
        self._life_real, self._life_sim = now_real, now_sim
        if not self.life_active:
            return
        self.life_loop.development.lived_real_seconds += max(0.0, dt_real)
        events = self.life_loop.vigilance.tick(dt_sim=dt_sim, dt_real=dt_real,
            occupancy=self.metabolism.last.get('occupancy'), hour=self.clock.hour,
            person_idle_seconds=self.person_idle_seconds, now_real=now_real, now_sim=now_sim)
        await self._life_events(events)

    async def _life_events(self, events: list[dict]):
        for event in events:
            kind = event['event']
            self.entity.tonic.emit({'type': 'vigilance_' + kind, 'cause': event.get('cause'),
                                    'sleep_pressure': round(event['S'], 4)})
            if kind == 'woke':
                self.life_loop.note_woke(event)
                episode = event['episode']
                self.record_life_event('slept', {key: episode.get(key) for key in (
                    'cause', 'woke_by', 'sim_seconds', 'real_seconds', 'S_at_onset', 'S_at_waking',
                    'work_done', 'consolidated', 'plasticity', 'learned')})
                if episode.get('stage_after') and episode.get('stage_after') != episode.get('stage_before'):
                    self.record_life_event('stage', {'from': episode['stage_before'], 'to': episode['stage_after'],
                        'nights': self.life_loop.development.nights})
            if kind in {'woke', 'fell_asleep'}:
                self.save_runtime()
        if events:
            await self.publish_state()

    def record_life_event(self, kind: str, data: dict):
        """Portable lives record this in lineage; development bodies only log it."""
        log.info('life_event', extra={'kind': kind})

    async def sleep_work(self):
        """Sleep does work: memory settles first, then the day is replayed into expectation."""
        episode = self.life_loop.vigilance.episode
        if not episode or episode['work_done'] or episode['real_seconds'] < self.sleep_settle_seconds:
            return
        consolidated = True
        try:
            await self._consolidation.run_for_daemon(self.entity)
        except Exception:
            consolidated = False
            log.exception('sleep_consolidation_failed')
        # Arousal and the body clock can end this episode while consolidation
        # awaits I/O. Never replay into, or age, a different sleep episode.
        if self.life_loop.vigilance.episode is not episode:
            return
        self.life_loop.sleep_work()
        episode['consolidated'] = consolidated
        self.save_runtime()

    @property
    def sleep_settle_seconds(self) -> float:
        return float((self.entity.config.raw.get('desktop') or {}).get('sleep_settle_seconds', 20))

    def state(self) -> dict:
        bars = {key: value / 100 for key, value in self.entity.tonic.bars.snapshot_pct().items()}
        hour = self.clock.hour
        affects = self.entity.tonic._current_affects
        return {'bars': bars, 'substrate': self.substrate.snapshot(), 'asleep': self.asleep,
                'vigilance': self.life_loop.vigilance.state, 'sleep_pressure': self.life_loop.vigilance.S,
                'salience': self.entity.tonic.compute_salience(),
                'affects': [str(a.get('name', a.get('text', '')))[:120] for a in affects if isinstance(a, dict)],
                'mood_tags': [str(a.get('name', '')) for a in affects if isinstance(a, dict) and a.get('name')],
                'sim_hour': hour, 'temperament': self.temperament}

    async def publish_state(self):
        await self.platform.publish('state', self.state())
        fragments = self.entity.tonic.noise.current_fragments()
        if fragments and fragments[-1] != self._thought:
            self._thought = fragments[-1]
            await self.platform.publish('thought', {'text': self._thought})
        if time.monotonic() < self._inspecting_until and time.monotonic() - self._last_inspector >= 2:
            self._last_inspector = time.monotonic()
            await self.platform.publish('inspector', await self.inspect())

    async def inspect(self):
        bars = self.entity.tonic.bars
        async with aiosqlite.connect(Path(self.entity.store.db_path).resolve().as_uri() + '?mode=ro', uri=True) as db:
            rows = await (await db.execute('SELECT id,timestamp,summary FROM episodes ORDER BY timestamp DESC LIMIT 12')).fetchall()
        being = getattr(self, 'being', None)
        lineage = being.lineage[-100:] if being else []
        def classified(want):
            # Unselected is absence of an opportunity, not a creature's refusal.
            return {**want, 'gate_type': want['gate_type'] if want.get('gate_type') in {'creature_choice', 'host_rule', 'environment'} else 'environment'}
        return {'name': self.display_name or 'Unnamed', 'id': being.id if being else 'development body',
            'file': str(being.path) if being else None, 'phase': getattr(self, 'life_state', {}).get('phase', 'development'),
            'clock': self.clock.snapshot(), 'state': self.state(), 'baselines': dict(bars._initial),
            'affects': self.entity.tonic._current_affects, 'fragments': self.entity.tonic.noise.current_fragments(),
            'pending_desires': [classified(w) for w in bars.pending_desires.values()],
            'unlived_wants': [classified(w) for w in bars.unlived_wants[-30:]],
            'realized_relief': bars.realized_relief, 'markers': bars._somatic_markers,
            'memories': [dict(zip(('id', 'timestamp', 'summary'), row)) for row in rows], 'lineage': lineage,
            'appearance': self.appearance, 'substrate': self.substrate.snapshot(),
            'metabolism': self.metabolism.snapshot(),
            'room': self.room.perception() if getattr(self, 'room', None) else None,
            'life_loop': self.life_loop.snapshot(hour=self.clock.hour, now_sim=self.clock.now()),
            'decisions': {'mode': self.entity.decision_mode, **self.entity.decision_stats},
            'learning': {'expectations': 'active',
                'turn_telemetry': 'active' if self.entity._turn_outcomes is not None else 'disabled_optional_modules_absent'},
            'last_appraisal': self.entity.tonic._last_appraisal_for_noise,
            'acceptance': {'appraisal': self.entity.tonic.appraiser.acceptance_metrics.snapshot(),
                           'evidence_quotes': self.entity.evidence_quote_metrics.snapshot()},
            'actions': list(self.action_history)[-15:], 'senses': self.senses,
            'sense_permissions': {'ambient': self.ambient, 'active_app': self.active_app},
            'model_calls_last_minute': sum(at >= time.time() - 60 for at in self.entity.client.calls),
            'wake_limits': {'seconds_since_wake': time.time() - self.guard._last_cycle_at,
                'minimum_real_gap': max(self.guard._auto.min_cycle_gap_seconds, self.entity.config.drives.initiative_cooldown),
                'wakes_this_hour': self.guard._cycle_count_this_hour,
                'window_started_at': self.guard._hour_start, 'window_expires_at': self.guard._hour_start + 3600,
                'maximum_per_real_hour': self.guard._auto.max_cycles_per_hour},
            'dreaming': self.dreaming, 'connected': self.platform.connected}

    async def connected(self):
        self._thought = ''
        await self.publish_state()
        await self.platform.publish('appearance', self.appearance)
        await self.platform.publish('senses', {'ambient': self.ambient, 'active_app': self.active_app})
        await self.platform.publish('conversation', self.conversation.snapshot())
        await self.platform.publish('health', {**self.health, 'paused': self.paused})
        if getattr(self, 'room', None):
            await self.platform.publish('room', self.room.view())
        else:
            await self.platform.publish('room', {'open': False, 'available': False, 'status': 'unavailable'})

    async def receive(self, packet: dict):
        data = packet['payload']
        if packet['type'] == 'sense':
            if not self.ambient: return
            # Allowlist: never store unknown fields, titles, or screen content.
            count = data.get('window_count')
            idle = data.get('idle_seconds')
            if not isinstance(count, int) or not 0 <= count <= 10000: return
            if not isinstance(idle, (int, float)) or not math.isfinite(idle): return
            ids = [s for s in data.get('window_ids', [])[:200] if isinstance(s, str) and len(s) <= 32]
            prior = self.senses.get('window_ids')
            self.senses = {'window_count': count, 'window_ids': ids,
                           'idle_seconds': max(0, min(idle, 86400 * 30)), 'idle': bool(data.get('idle'))}
            app = data.get('active_app')
            if self.active_app and isinstance(app, str) and len(app) <= 128 and not any(c in app for c in '/\\:\n\r'):
                self.senses['active_app'] = app
            if prior is not None and prior != ids:
                self.entity.tonic.apply_immediate({'type': 'desktop_windows_changed',
                    'opened': len(set(ids) - set(prior)), 'closed': len(set(prior) - set(ids))})
            self.entity.tonic.emit({'type': 'desktop_ambient', 'window_count': count,
                'idle': self.senses['idle'], 'hour': self.clock.hour,
                **({'active_app': self.senses['active_app']} if 'active_app' in self.senses else {})})
            # Ambient updates never enqueue inference.
            return
        if packet['type'] == 'control':
            name = data.get('name')
            if name == 'room_open' and self.room:
                await self.room.open_window()
                await self.platform.publish('room', self.room.view())
            elif name == 'room_close' and self.room:
                await self.room.perform('close_page', {}, act_id=uuid.uuid4().hex, initiator='person')
                await self.platform.publish('room', self.room.view())
            elif name == 'room_scroll' and self.room and data.get('direction') in {'up', 'down'}:
                await self.room.perform('scroll', {'direction': data['direction']}, act_id=uuid.uuid4().hex, initiator='person')
            elif name == 'room_move' and self.room:
                rect = data.get('rect', {})
                if all(isinstance(rect.get(k), (float, int)) and math.isfinite(rect[k]) for k in ('x', 'y', 'width', 'height')):
                    if 160 <= rect['width'] <= 1600 and 120 <= rect['height'] <= 1200:
                        self.room.rectangle = {'id': 'replicants-room', **{k: rect[k] for k in ('x', 'y', 'width', 'height')}}
                        self.room.front = data.get('front', True) is not False
                        await self.platform.publish('room', self.room.view())
            if name == 'quit': self._stop.set()
            elif name == 'sleep': await self.request_sleep('person')
            elif name == 'wake':
                event = self.life_loop.vigilance.wake_by_person(*self._vigilance_now(), hold_real_seconds=60)
                await self._life_events([event] if event else [])
            elif name == 'inspect': self._inspecting_until = time.monotonic() + 15
            elif name in {'pause', 'resume'}:
                self.paused = name == 'pause'
                await self.platform.publish('health', {**self.health, 'paused': self.paused,
                    'finishing_turn': self._cognition.locked()})
            elif name == 'time_scale':
                try: self.clock.change_scale(data.get('scale', 1))
                except (ValueError, TypeError) as exc: await self.platform.publish('error', {'reason': str(exc)})
                else:
                    self.entity.tonic.bars._offline_time_scale = self.clock.scale
                    self.save_runtime()
            elif name in {'ambient', 'active_app'}:
                if name == 'ambient': self.ambient = not self.ambient
                else: self.active_app = not self.active_app
                self.senses = {}
                await self.platform.publish('senses', {'ambient': self.ambient, 'active_app': self.active_app})
            await self.publish_state()
            return
        if packet['type'] != 'event': return
        kind = data.get('kind')
        if kind not in TOUCH | {'chat'}: return
        now = time.time()
        self.last_person_at = now
        self._last_person_sim = self.clock.now()
        self.reactions.append((now, kind))
        event = self.life_loop.vigilance.arouse(AROUSAL.get(kind, 0.5), kind, *self._vigilance_now())
        await self._life_events([event] if event else [])
        reaction_changed = False
        for pending in self.outreach.values():
            if pending['started'] <= now <= pending['deadline']:
                if not pending.get('reaction'):
                    pending['reaction'] = kind; reaction_changed = True
        if reaction_changed: self.save_runtime()
        if kind in TOUCH:
            # Trigger the familiar gut feeling before appraisal, once per batch.
            if not self.touches: self.entity.tonic.bars.trigger_somatic_marker(PERSON)
            if now - self._last_static_touch.get(kind, 0) >= .25:
                self.entity.tonic.apply_immediate({'type': 'desktop_' + kind, 'from': PERSON})
                self._last_static_touch[kind] = now
            self.touches.append(kind); self.touches = self.touches[-100:]
        else:
            text = str(data.get('text', '')).strip()[:4000]
            if text:
                message_id = str(packet.get('id') or uuid.uuid4())[:128]
                if self.paused:
                    await self.platform.publish('error', {'reason': 'thinking_paused', 'message_id': message_id})
                    return
                _, fresh = self.conversation.receive(message_id, str(data.get('display_text', text))[:4000])
                if fresh:
                    # A received message belongs to the portable life before work starts.
                    await self.conversation_checkpoint()
                    try:
                        self._jobs.put_nowait(Input(text, PERSON, 'the person here', 'desktop', 'desktop',
                            metadata={'desktop_message_id': message_id}))
                    except asyncio.QueueFull:
                        self.conversation.status(message_id, 'failed', 'Conversation queue is full. Wait and send again.')
                await self.platform.publish('conversation', self.conversation.snapshot())
        await self.publish_state()

    async def perform(self, name: str, args: dict, inp: Input) -> dict:
        started = time.time()
        if name == 'say':
            args = {**args, 'text': clip_speech(args.get('text', ''))}
        if self.asleep and name != 'sleep':
            result = {'name': name, 'status': 'interrupted', 'detail': 'body_asleep'}
        elif name in ROOM_TOOLS:
            result = (await self.room.perform(name, args, act_id=uuid.uuid4().hex) if self.room else
                      {'name': name, 'status': 'failed', 'detail': 'room_unavailable'})
            if self.room: await self.platform.publish('room', self.room.view())
        else:
            result = await self.platform.action(name, args)
        if result['status'] == 'completed' and name == 'say':
            result['expression'] = args['text']
            self.conversation.spoken(result['expression'], inp.metadata.get('desktop_message_id'))
            # Save receipt-confirmed speech before reflection or another inference.
            await self.conversation_checkpoint()
            await self.platform.publish('conversation', self.conversation.snapshot())
        if result['status'] == 'completed' and name == 'emote': result['expression'] = str(args.get('glyph', ''))[:40]
        self.action_history.append({'at': time.time(), 'source': inp.platform, **result})
        self.entity.tonic.emit({'type': 'desktop_action', **result})
        if result['status'] == 'completed':
            if name == 'sleep': await self.request_sleep('self')
            desire_id = inp.metadata.get('soma_desire_id')
            if desire_id and name in OUTREACH:
                pending = self.outreach.setdefault(desire_id, {
                    'started': started, 'deadline': time.time() + self.reaction_seconds,
                    'input': inp.text, 'results': []})
                pending['results'].append(result)
                for at, kind in self.reactions:
                    if started <= at <= pending['deadline']: pending.setdefault('reaction', kind)
                self.save_runtime()
        await self.publish_state()
        return result

    async def _appraise(self, input_text: str, results: list, *, desire_id: str | None = None,
                        reaction: str = '', person: bool = True, context: str = ''):
        want = self.entity.tonic.bars.pending_desires.get(desire_id) if desire_id else None
        outreach = any(r.get('name') in OUTREACH and r.get('status') == 'completed' for r in results)
        observed = json.dumps({'originating_desire': want,
            'human_reaction': reaction or ('none_observed' if outreach or person else 'not_applicable'), 'actions': results}, ensure_ascii=False)
        guidance = ('A delivered wave or bubble alone is not connection. An observed human reaction is connection; '
            'unanswered outreach is not rejection of your worth. Scale relief to what actually happened: '
            'connection can relieve social pressure strongly; no reaction gives little or no social relief and may increase tension.'
            if outreach else 'These actions did not reach out to a person. Lack of a human reaction is not unanswered outreach. '
            'Appraise the actual bodily outcome: learning measured geometry may satisfy curiosity, while moving the eyes alone '
            'brings no new observations. Do not invent an unanswered signal or an obligation to socialize.')
        result = await self.entity.tonic.appraise_interaction_and_apply(
            self.entity.client, self.entity.config.cognition.reflex_model or self.entity.config.cognition.deliberate_model,
            input_text=input_text, reply_text=observed, person_name='the person here' if person else 'self',
            person_id=PERSON if person else '', desire_id=desire_id,
            outcome_context=observed[:1600] + '\n' + context + '\nOnly the listed results happened. ' + guidance,
            num_ctx=self.entity.config.effective_ollama_num_ctx())
        self._learn(desire_id, want, results)
        await self.publish_state()

        return result

    def _learn(self, desire_id, want, results):
        """Expectation is learned only from an appraised outcome of completed actions."""
        bars = self.entity.tonic.bars
        if not want or desire_id in bars.pending_desires:
            return None
        stats = bars.realized_relief.get(want['impulse_type'], {})
        if stats.get('last_desire_id') != desire_id:
            return None
        actions = [r['name'] for r in results if r.get('status') == 'completed' and r.get('name') in BODY_TOOLS]
        return self.life_loop.outcome(desire_id, want['impulse_type'],
            WANT_DRIVE.get(want['impulse_type'], want['drive']), actions, stats.get('last_effects', {}),
            self.life_context(), self.clock.now())

    async def appraise_turn(self, tc):
        desire_id = tc.inp.metadata.get('soma_desire_id')
        results = tc.tool_state.get('_desktop_actions', [])
        if desire_id and desire_id in self.outreach:
            self.outreach[desire_id]['results'] = list(results)
            self.save_runtime()
            return  # Wait for the person's reaction, or the real-time deadline.
        if not results and (desire_id or tc.inp.platform == 'autonomous'):
            if desire_id: self.entity.tonic.bars.note_desire_gate('chose_not_to_act', 'creature_choice', desire_id)
            return
        await self._appraise(tc.inp.text, results or [{'status': 'completed', 'detail': 'remained_quiet'}],
            desire_id=desire_id, person=tc.inp.platform != 'autonomous',
            reaction='chat' if tc.inp.platform == 'desktop' else '')

    async def settle_outreach(self):
        now = time.time()
        for desire_id, pending in list(self.outreach.items()):
            if now < pending.get('retry_after', 0): continue
            if not pending.get('reaction') and now < pending['deadline']: continue
            if desire_id in self.entity.tonic.bars.pending_desires:
                await self._appraise(pending['input'], pending['results'], desire_id=desire_id,
                    reaction=pending.get('reaction', ''), context='This is the outcome of earlier outreach; the reaction window has settled.')
                if desire_id in self.entity.tonic.bars.pending_desires:
                    pending['retry_after'] = now + self.touch_seconds
                    continue  # Empty/failed appraisal did not settle this want.
            self.outreach.pop(desire_id, None)
            self.save_runtime()

    async def appraise_touches(self):
        if not self.touches or time.monotonic() - self._last_touch_appraisal < self.touch_seconds: return
        batch, self.touches = self.touches, []
        self._last_touch_appraisal = time.monotonic()
        text = 'The person touched my body: ' + ', '.join(f'{name} x{batch.count(name)}' for name in sorted(set(batch)))
        await self._appraise(text, [{'status': 'completed', 'detail': 'body_received_touch'}], reaction='touch')
        async with self.entity.store.session() as db:
            await self.entity.relational.upsert_interaction(db, PERSON, 'the person here', meaningful=False)
            await self.entity.tonic.save_state_db(db)

    def _want_for_wake(self, reason: str) -> str | None:
        """Every wake from the body acts on a want, so every wake is gated and learned from.

        Impulses and matching drives already carry a pending want. A drive, conflict, inner
        thought or inferred desire that has none gets one here, keyed by its kind, so it passes
        through expectation, appraisal and sleep replay like any other urge.
        """
        kind = wake_want(reason)
        if kind is None:
            return None
        bars = self.entity.tonic.bars
        drive = WANT_DRIVE[kind]
        return bars.record_desire(drive, kind, f'wake:{kind}', float(bars._values.get(drive, 0.0)))

    def available_want_actions(self):
        room = getattr(self, 'room', None)
        return [name for name in WANT_ACTIONS if name not in ROOM_TOOLS or (room and room.opened)]

    async def wake(self, reason: str):
        bars = self.entity.tonic.bars
        desire_id, self._wake_desire = self._wake_desire, None
        if desire_id not in bars.pending_desires:
            desire_id = bars.select_desire(reason=reason)
        if desire_id:
            want = bars.pending_desires[desire_id]
            self.life_loop.begin(desire_id, want['impulse_type'], self.life_context())
            bars.start_desire(desire_id)
            self.entity.tonic.save_state()
        self.guard._running = True
        previous = self.guard._last_cycle_at
        self.guard._last_cycle_at = time.time()
        self.guard._cycle_count_this_hour += 1
        self.guard._next_timer_wake = self.guard._schedule_next_timer(gap_seconds_since_previous_wake=time.time() - previous)
        try:
            self.save_runtime()
            await self.conversation_checkpoint()
            stimulus = 'Something in my present body is drawing my attention. I can explore, rest, approach, or let it pass.'
            await self.entity.perceive(Input(stimulus,
                'self', 'self', 'desktop', 'autonomous', metadata={'soma_desire_id': desire_id}),
                record_user_message=False, preserve_conversation_route=True,
                skip_relational_upsert=True, skip_drive_interaction=True)
        finally:
            self.guard._running = False

    async def _turn_worker(self):
        while True:
            inp = await self._jobs.get()
            message_id = inp.metadata.get('desktop_message_id')
            try:
                while self.paused: await asyncio.sleep(.2)
                self.conversation.status(message_id, 'processing')
                await self.platform.publish('conversation', self.conversation.snapshot())
                async with self._cognition:
                    await self.entity.perceive(inp)
                    await self.settle_outreach()
                    self.conversation.status(message_id, 'completed')
                    await self.conversation_checkpoint()
            except asyncio.CancelledError:
                self.conversation.status(message_id, 'interrupted', 'Session stopped. Send again to retry.')
                raise
            except Exception as exc:
                from replicants.desktop.entity import DesktopTurnError
                detail = str(exc) if isinstance(exc, DesktopTurnError) else 'The local model could not finish this turn. Check Ollama and retry.'
                self.conversation.status(message_id, 'failed', detail)
                log.exception('desktop_turn_failed')
                await self.platform.publish('error', {'reason': detail})
            finally:
                self._jobs.task_done()
                await self.platform.publish('conversation', self.conversation.snapshot())

    async def _body_loop(self):
        last_body = self.clock.now()
        while not self._stop.is_set():
            if self.platform.connected:
                self._disconnected_at = None
            else:
                self._disconnected_at = self._disconnected_at or time.monotonic()
                if os.environ.get('REPLICANTS_BETA') == '1' and time.monotonic() - self._disconnected_at >= 90:
                    self.health.update(status='stopping', error='The desktop disconnected. Saving this life.')
                    self._stop.set()
                    break
            self.guard._reset_hourly_counter()
            now = self.clock.now()
            if now - last_body >= self.body_interval:
                await self.body_tick(now - last_body)
                last_body = now
            await self.life_tick()
            await self.publish_state()
            await asyncio.sleep(2)

    @property
    def body_interval(self): return self.entity.config.harness.presence.heartbeat_interval

    async def body_tick(self, seconds: float):
        # Keep the original per-heartbeat conflict/coupling cadence in body time.
        remaining = seconds
        while remaining > 0:
            step = min(remaining, self.body_interval)
            await self.entity.tonic.tick_bars(step / 3600, circadian_hour=self.clock.hour)
            self.entity.drives.tick(max(0, self.clock.now() - self._last_person_sim))
            remaining -= step

    async def next_wake_reason(self):
        if not self.platform.connected:
            self.entity.tonic.bars.note_desire_gate('overlay_disconnected', 'environment')
        elif self.asleep:
            self.entity.tonic.bars.note_desire_gate('sleeping', 'environment')
        else:
            reason = self.guard.should_wake(tonic=self.entity.tonic, drives=self.entity.drives.all_drives(),
                silence_seconds=time.time() - self.last_person_at, dormant=self.entity.dormant)
            if reason == 'timer':
                # A clock is not a reason to live. Wakes come from the body (reports/life-loop.md).
                return None
            if reason:
                bars = self.entity.tonic.bars
                desire_id = bars.select_desire(reason=reason) or self._want_for_wake(reason)
                want = bars.pending_desires.get(desire_id) if desire_id else None
                if want:
                    act, value = self.life_loop.wants_to_act(want['impulse_type'], self.life_context(),
                                                             self.available_want_actions(), self.clock.now())
                    if not act:
                        bars.note_desire_gate(f'expects_little:{value:.3f}', 'creature_choice', desire_id)
                        return None
                self._wake_desire = desire_id
            return reason
        return None

    async def _mind_loop(self):
        last_background = 0.0
        while not self._stop.is_set():
            if self.platform.connected and not self.paused and not self._cognition.locked() and self._jobs.empty():
                try:
                    async with self._cognition:
                        await self.settle_outreach()
                        await self.appraise_touches()
                        now = time.monotonic()
                        if now - last_background >= 30:
                            last_background = now
                            # Existing GEN and affect engines retain real-time rate limits.
                            await self.entity.tonic.maybe_tick_affects(self.entity.client,
                                self.entity.config.cognition.reflex_model, num_ctx=self.entity.config.effective_ollama_num_ctx())
                            await self.entity.maybe_tick_noise_heartbeat()
                            if self.asleep: await self.sleep_work()
                            dream = self.entity.dream_engine
                            if self.asleep and now - self._last_dream_attempt >= 300 and dream.should_dream(self.clock.now() - self._last_person_sim):
                                self._last_dream_attempt = now  # Real-time protection, even with no memory pairs.
                                self.dreaming = True
                                try: await dream.dream_cycle(self.entity)
                                finally: self.dreaming = False
                        reason = await self.next_wake_reason()
                        if reason: await self.wake(reason)
                        self.entity.tonic.bars.expire_desires()
                        await self.publish_state()
                except Exception:
                    log.exception('desktop_heartbeat_failed')
                    self.health.update(status='degraded', error='Background thinking failed. Check the local model connection.')
                    await self.platform.publish('health', self.health)
            await asyncio.sleep(2)

    def save_runtime(self):
        dream = self.entity.dream_engine
        private_write(self._runtime_path, {'name': self.display_name, 'appearance': self.appearance, 'outreach': self.outreach,
            'clock': self.clock.snapshot(), 'ambient': self.ambient, 'compute': self.compute.persisted(),
            'metabolism': self.metabolism.persisted(), 'life_loop': self.life_loop.persisted(),
            'wake_allowance': {'hour_started_at': self.guard._hour_start,
                'wakes': self.guard._cycle_count_this_hour, 'last_wake_at': self.guard._last_cycle_at},
            'dream': {'last_at': dream._last_dream_at, 'cycles_today': dream._cycles_today, 'last_day': dream._last_day}})

    def extra_loops(self): return []
    async def conversation_checkpoint(self): pass
    async def started(self): pass
    async def before_shutdown(self): pass
    async def after_shutdown(self): pass

    async def _substrate_loop(self):
        while not self._stop.is_set():
            await self.substrate.sample()
            self.metabolism.sample(self.substrate.hardware)
            await asyncio.sleep(10)  # Wall time: acceleration never multiplies sensor polls.

    async def run(self, *, launch: bool = True):
        try:
            if self.platform._runner is None: await self.platform.connect()
            async with self.entity.store.session() as db:
                await self.entity._ensure_state_hydrated(db)
                await self.entity.tonic.restore_state_db(db)
                self.entity._soma_db_restored = True
            await self.started()
            await self.platform.on_message(self.receive)
            self.platform.on_connect = self.connected
            if self.platform.connected: await self.connected()
            if launch: launch_overlay()
            self.health['status'] = 'running'
            await self.platform.publish('health', self.health)
            self._tasks = [asyncio.create_task(fn(), name=fn.__name__) for fn in (self._body_loop, self._mind_loop, self._turn_worker, self._substrate_loop, *self.extra_loops())]
            waiter = asyncio.create_task(self._stop.wait(), name='stop_requested')
            try:
                done, _ = await asyncio.wait([waiter, *self._tasks], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is not waiter and not task.cancelled():
                        error = task.exception()
                        self.health.update(status='stopping', error=f'{task.get_name()} stopped unexpectedly')
                        log.error('desktop_loop_stopped: %s', task.get_name(), exc_info=error)
                        await self.platform.publish('health', self.health)
            finally:
                waiter.cancel()
                with suppress(asyncio.CancelledError): await waiter
        finally:
            self._stop.set()
            for task in self._tasks: task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            try:
                await self.before_shutdown()
                self.save_runtime()
                await self.entity.shutdown()
                await self.after_shutdown()
                await self.platform.publish('stopped', {'checkpointed': True})
                # Let the overlay receive the acknowledgement before closing its socket.
                await asyncio.sleep(.1)
            except Exception as exc:
                await self.platform.publish('error', {'reason': 'checkpoint_failed: ' + str(exc)})
                raise
            finally:
                room = getattr(self, 'room', None)
                if room: await room.reader.close()
                await self.platform.disconnect()


def launch_overlay(*, conception=False):
    root = Path(__file__).resolve().parents[2]
    choices = [Path(os.environ['REPLICANTS_OVERLAY_EXE'])] if os.environ.get('REPLICANTS_OVERLAY_EXE') else [
        root / 'desktop/src-tauri/target/release/replicants-desktop.exe',
        root / 'desktop/src-tauri/target/debug/replicants-desktop.exe']
    binary = next((p for p in choices if p.is_file()), None)
    if binary is None: raise RuntimeError('Build the desktop first: cd desktop; npm run tauri build -- --debug --no-bundle')
    env = dict(os.environ)
    if conception: env['REPLICANTS_CONCEPTION'] = '1'
    subprocess.Popen([str(binary)], cwd=root, env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


async def run_desktop(entity_name: str | None = None, *, headless: bool = False):
    platform = DesktopPlatform()
    # Acquire desktop exclusivity before opening an entity's files/database.
    await platform.connect()
    try:
        runtime = DesktopRuntime(DesktopEntity(desktop_config(entity_name)), platform)
        await runtime.run(launch=not headless)
    finally:
        await platform.disconnect()
