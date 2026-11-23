"""One birth, continuing wakes: the portable life record around desktop presence."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time

from replicants.desktop.archive import ReplicantArchive
from replicants.desktop.entity import DesktopEntity
from replicants.desktop.design import validate_design
from replicants.desktop.genome import archive_config, conceive
from replicants.desktop.protocol import private_write
from replicants.desktop.runtime import DesktopRuntime, PERSON, launch_overlay
from replicants.presence.platforms.desktop import DesktopPlatform


class LivingReplicant(DesktopRuntime):
    def __init__(self, being: ReplicantArchive, platform: DesktopPlatform):
        self.being = being
        # The written genome plus any recorded framework defaults (format v2).
        self.genome = being.effective_genome
        config = archive_config(being)
        super().__init__(DesktopEntity(config), platform)
        self.health['file'] = str(being.path)
        self.display_name = being.manifest.get('name') or ''
        self.temperament = self.genome['temperament']['preset']
        self._life_path = being.life / 'lifecycle.json'
        if self._life_path.exists():
            self.life_state = json.loads(self._life_path.read_text(encoding='utf-8'))
        else:
            self.life_state = {'phase': 'gestating', 'elapsed': 0.0, 'first_person': None,
                               'first_breath_at': None, 'sealed': False, 'active': False, 'last_sleep_at': None}
        appearance_path = being.life / 'appearance.json'
        self.appearance = json.loads(appearance_path.read_text(encoding='utf-8')) if appearance_path.exists() else {
            'palette': self.genome['base_palette'], 'layers': []}
        if 'body_design' in self.genome:
            self.appearance['design'] = validate_design(self.genome['body_design'])
        # Retire only the mechanical inspection reward. Preserve immutable past
        # lineage and unrelated appearance, recording the correction once.
        revision = 'remove_inspection_reward_v1'
        retired = any(e['kind'] == 'host_revision' and e['data'].get('revision') == revision for e in being.lineage)
        old_reward = any(e['kind'] == 'appearance_earned' and e['data'].get('layer') == 'glasses'
            and e['data'].get('reason') == 'Completed three window inspections chosen during autonomous wakes.' for e in being.lineage)
        old_counter = self.life_state.pop('chosen_inspections', None)
        if not retired and (old_reward or old_counter):
            if old_reward:
                self.appearance['layers'] = [layer for layer in self.appearance['layers'] if layer != 'glasses']
            being.append('host_revision', {'revision': revision,
                'reason': 'Removed the inspection-count appearance reward; observations do not purchase clothing.'})
        self._last_checkpoint = time.monotonic()
        self._save_lock = asyncio.Lock()
        if self.life_state['phase'] == 'gestating':
            self.guard._last_cycle_at = 0  # There has never been a wake to cool down from.
            self.last_person_at = 0  # No person is present in gestation.

    @property
    def body_interval(self):
        return 2 if self.life_state['phase'] == 'gestating' else super().body_interval

    @property
    def asleep(self):
        return False if self.life_state['phase'] in {'gestating', 'awaiting_name', 'imprinting'} else super().asleep

    @property
    def life_active(self):
        return self.life_state['phase'] not in {'gestating', 'awaiting_name', 'imprinting'}

    def record_life_event(self, kind, data):
        self.being.append(kind, data)

    def state(self):
        return {**super().state(), 'gestating': self.life_state['phase'] == 'gestating',
                'naming': self.life_state['phase'] == 'awaiting_name', 'name': self.display_name}

    async def started(self):
        now = time.time()
        last = self.life_state.get('last_sleep_at')
        self.being.append('wake', {'gap_seconds': max(0, now - last) if last else 0,
            'after_unclean_stop': bool(self.life_state.get('active')), 'phase': self.life_state['phase']})
        self.entity.tonic.emit({'type': 'desktop_wake', 'gap_seconds': max(0, now - last) if last else 0})
        self.life_state['active'] = True
        if self.being.recovered_from:
            self.being.append('recovered_backup', {'reason': 'primary archive failed integrity verification'})
        await self.checkpoint()
        from replicants.desktop.library import remember
        remember(self.being.path)

    async def body_tick(self, seconds: float):
        if self.life_state['phase'] != 'gestating': return await super().body_tick(seconds)
        self.life_state['elapsed'] += seconds
        bars = self.entity.tonic.bars
        initial = next(v['initial'] for v in self.genome['temperament']['bars']['variables'] if v['name'] == 'curiosity')
        threshold = self.curiosity_threshold
        growth = max(1, threshold - initial) / self.genome['gestation_seconds']
        bars._values['curiosity'] += growth * seconds
        await self.entity.tonic.tick_bars(seconds / 3600, circadian_hour=self.clock.hour)

    @property
    def curiosity_threshold(self):
        return next(i['threshold'] for i in self.genome['temperament']['impulses'] if i['drive'] == 'curiosity')

    async def next_wake_reason(self):
        if self.life_state['phase'] != 'gestating': return await super().next_wake_reason()
        if not self.platform.connected or not self.entity.tonic.noise.current_fragments(): return None
        if self.life_state['elapsed'] < self.genome['gestation_seconds']: return None
        if self.entity.tonic.bars._values['curiosity'] < self.curiosity_threshold: return None
        # The bar engine already labels a just-fired impulse "cooling". First
        # breath belongs to its recorded, unacted curiosity want, not to a
        # fleeting display flag. Keep the same host limits in real time.
        guard, bars = self.guard, self.entity.tonic.bars
        guard._reset_hourly_counter()
        blocked = ('autonomy_disabled' if not guard._auto.enabled else
            'dormant' if self.entity.dormant else 'wake_running' if guard._running else
            'cooldown' if time.time() - guard._last_cycle_at < max(guard._auto.min_cycle_gap_seconds, self.entity.config.drives.initiative_cooldown) else
            'rate_limit' if guard._cycle_count_this_hour >= guard._auto.max_cycles_per_hour else '')
        if blocked:
            bars.note_desire_gate(blocked, 'host_rule'); return None
        impulse = next(i for i in self.genome['temperament']['impulses'] if i['drive'] == 'curiosity')
        reason = 'impulse:' + impulse['label']
        if bars.select_desire(reason=reason) is None:
            bars.record_desire('curiosity', impulse['type'], impulse['label'], bars._values['curiosity'])
        now = time.time()
        self.life_state.update(phase='awaiting_name', first_breath_at=now, first_breath_sim=self.clock.now())
        # A first breath is not followed by sleep before the person can answer.
        self.life_loop.vigilance.hold_until = time.monotonic() + 120
        self.being.append('first_breath', {'curiosity': self.entity.tonic.bars._values['curiosity'],
            'threshold': self.curiosity_threshold, 'gestation_seconds': self.life_state['elapsed'],
            'inner_fragments': len(self.entity.tonic.noise.current_fragments())}, now)
        self.entity.tonic.emit({'type': 'first_breath', 'at': now})
        await self.checkpoint()
        await self.publish_state()
        await self.platform.publish('say', {'text': 'What should I be called?'})
        return reason

    async def receive(self, packet):
        if packet['type'] == 'event' and self.conversation.find(packet.get('id')):
            await self.platform.publish('conversation', self.conversation.snapshot())
            return
        if self.paused and packet['type'] == 'event' and packet['payload'].get('kind') == 'chat':
            await super().receive(packet)
            return
        if self.life_state['phase'] == 'gestating':
            # Gestation has empty experience: no person, scene, or chat to echo.
            if packet['type'] != 'control': return
        data = packet['payload']
        if self.life_state['phase'] == 'awaiting_name' and packet['type'] == 'event' and data.get('kind') == 'chat':
            name = str(data.get('text', '')).strip()
            if not 1 <= len(name) <= 40 or any(ord(c) < 32 for c in name):
                await self.platform.publish('say', {'text': 'A name of 1 to 40 characters, please.'}); return
            self.display_name = name
            self.being.manifest['name'] = name
            self.life_state['phase'] = 'imprinting'
            self.being.append('naming', {'name': name, 'person_id': PERSON})
            self.save_life()
            packet = {**packet, 'payload': {'kind': 'chat', 'display_text': name,
                'text': f'The person here gave me my name: {name}. This is our first naming.'}}
            await self.publish_state()
        await super().receive(packet)

    async def _appraise(self, input_text, results, *, desire_id=None, reaction='', person=True, context=''):
        bars = self.entity.tonic.bars
        first = person and not self.life_state['first_person']
        old_rate = bars._marker_learning_rate
        if first: bars._marker_learning_rate = min(1, old_rate * 4)
        try:
            await super()._appraise(input_text, results, desire_id=desire_id, reaction=reaction, person=person, context=context)
        finally:
            bars._marker_learning_rate = old_rate
        if first and PERSON in bars._somatic_markers:
            self.life_state['first_person'] = PERSON
            self.being.append('imprinting', {'person_id': PERSON, 'learning_rate': min(1, old_rate * 4),
                'marker': dict(bars._somatic_markers[PERSON])})
        if self.display_name and self.life_state['first_person'] and not self.life_state['sealed']:
            self.life_state.update(phase='newborn', sealed=True)
            self.being.append('birth_sealed', {'name': self.display_name, 'person_id': PERSON})
        self.save_life()

    def save_life(self):
        private_write(self._life_path, self.life_state)
        private_write(self.being.life / 'appearance.json', self.appearance)
        private_write(self.being.life / 'config.json', {'desktop': self.entity.config.raw['desktop']})

    async def checkpoint(self, *, flush_database=True):
        async with self._save_lock:
            self.save_life(); self.save_runtime()
            self.entity.tonic.save_state()
            if flush_database:
                async with self.entity.store.session() as db: await self.entity.tonic.save_state_db(db)
            snapshot = self.being.snapshot()
            writer = asyncio.create_task(asyncio.to_thread(self.being.checkpoint, snapshot=snapshot))
            try:
                await asyncio.shield(writer)
            except asyncio.CancelledError:
                await writer  # Never close the identity lock while a writer still owns the file.
                raise
            self._last_checkpoint = time.monotonic()
            self.health.update(last_checkpoint_at=time.time(), error=None, status='running')
            await self.platform.publish('health', {**self.health, 'paused': self.paused})

    def extra_loops(self): return [self._checkpoint_loop]
    async def conversation_checkpoint(self):
        # Delivery can occur inside a turn's SQLite writer. Capture the last
        # committed database plus current transcript without opening another writer.
        await self.checkpoint(flush_database=False)

    async def _checkpoint_loop(self):
        while not self._stop.is_set():
            if time.monotonic() - self._last_checkpoint >= 30 and not self._cognition.locked():
                async with self._cognition: await self.checkpoint()
            await asyncio.sleep(2)

    async def before_shutdown(self):
        now = time.time()
        self.being.append('sleep', {'phase': self.life_state['phase']}, now)
        self.entity.tonic.emit({'type': 'desktop_sleep', 'at': now})
        self.life_state.update(active=False, last_sleep_at=now)
        self.save_life()

    async def after_shutdown(self):
        try:
            snapshot = self.being.snapshot()
            await asyncio.to_thread(self.being.checkpoint, snapshot=snapshot)
        finally: self.being.close()


async def wake_file(path: Path, *, headless=False):
    platform = DesktopPlatform()
    await platform.connect()
    being = None
    try:
        being = ReplicantArchive.open(path)
        if being.recovered_from: print(f'Replicants recovered the verified last-good backup: {being.recovered_from}', flush=True)
        runtime = LivingReplicant(being, platform)
        await runtime.run(launch=not headless)
    finally:
        if being is not None: being.close()
        await platform.disconnect()


async def birth(*, temperament=None, palette='pearl', gestation_seconds=90, output: Path | None = None, headless=False):
    platform = DesktopPlatform()
    await platform.connect()
    being = None
    try:
        if temperament is None:
            choices = asyncio.get_running_loop().create_future()
            async def choose(packet):
                data = packet['payload']
                if packet['type'] == 'control' and data.get('name') == 'quit':
                    await platform.publish('stopped', {'checkpointed': True})
                    choices.cancel(); return
                if packet['type'] == 'control' and data.get('name') == 'conceive' and not choices.done():
                    try: genome = conceive(data.get('temperament', 'curious'), data.get('palette', 'pearl'), data.get('gestation_seconds', 90), design=data.get('design'))
                    except ValueError as exc: await platform.publish('error', {'reason': str(exc)})
                    else: choices.set_result(genome)
            await platform.on_message(choose)
            platform.on_connect = lambda: platform.publish('conception', {'temperaments': ['curious', 'shy', 'social', 'calm', 'roll']})
            if not headless: launch_overlay(conception=True)
            try: genome = await choices
            except asyncio.CancelledError: return
        else:
            genome = conceive(temperament, palette, gestation_seconds)
        being = ReplicantArchive.create(genome, output)
        print(f'Conceived {being.id}: {being.path}', flush=True)
        runtime = LivingReplicant(being, platform)
        await runtime.run(launch=not headless and temperament is not None)
    finally:
        if being is not None: being.close()
        await platform.disconnect()
