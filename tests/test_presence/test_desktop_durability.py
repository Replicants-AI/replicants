import asyncio
import json
import time

import pytest

from replicants.desktop.archive import ReplicantArchive, verify
from replicants.desktop.genome import conceive
from replicants.desktop.life import LivingReplicant
from replicants.desktop.runtime import PERSON
from replicants.models import Input


class Client:
    async def close(self): pass


class Body:
    connected = True
    async def publish(self, kind, payload): return True
    async def action(self, name, args):
        return {'name': name, 'status': 'completed', 'act_id': 'receipt', 'detail': 'sequence_finished'}


@pytest.mark.asyncio
async def test_received_and_delivered_messages_are_portable_before_post_turn_work(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: Client())
    being = ReplicantArchive.create(conceive(), tmp_path / 'life.replicant', tmp_path / 'home')
    runtime = LivingReplicant(being, Body())
    runtime.life_state['phase'] = 'newborn'
    try:
        await runtime.receive({'type': 'event', 'id': 'hello', 'payload': {'kind': 'chat', 'text': 'hello'}})
        _, members = verify(being.path)
        received = json.loads(members['life/conversation.json'])
        assert received[0]['text'] == 'hello' and received[0]['status'] == 'queued'
        inp = Input('hello', PERSON, 'the person here', 'desktop', 'desktop',
                    metadata={'desktop_message_id': 'hello'})
        async with runtime.entity.store.session() as db:
            await db.execute('CREATE TABLE delivery_probe (value TEXT)')
            await db.execute("INSERT INTO delivery_probe VALUES ('turn still open')")
            await asyncio.wait_for(runtime.perform('say', {'text': 'hello back'}, inp), 3)
        _, members = verify(being.path)
        delivered = json.loads(members['life/conversation.json'])
        assert [m['text'] for m in delivered] == ['hello', 'hello back']
        assert delivered[-1]['status'] == 'delivered'
        # The turn worker and its post-turn reflection have never run.
        assert runtime._jobs.qsize() == 1
    finally:
        await runtime.entity.shutdown()
        being.close()


@pytest.mark.asyncio
async def test_hourly_allowance_and_cooldown_survive_portable_reopen(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: Client())
    path, home = tmp_path / 'life.replicant', tmp_path / 'home'
    being = ReplicantArchive.create(conceive(), path, home)
    runtime = LivingReplicant(being, Body())
    runtime.life_state['phase'] = 'newborn'
    hour, last = time.time() - 120, time.time() - 5
    runtime.guard._hour_start = hour
    runtime.guard._cycle_count_this_hour = 6
    runtime.guard._last_cycle_at = last
    await runtime.checkpoint()
    await runtime.entity.shutdown()
    being.close()
    reopened = ReplicantArchive.open(path, home)
    resumed = LivingReplicant(reopened, Body())
    try:
        assert resumed.guard._cycle_count_this_hour == 6
        assert resumed.guard._hour_start == hour
        assert resumed.guard._last_cycle_at == last
        resumed.guard._hour_start -= 3600
        resumed.guard._reset_hourly_counter()
        assert resumed.guard._cycle_count_this_hour == 0
    finally:
        await resumed.entity.shutdown()
        reopened.close()


@pytest.mark.asyncio
async def test_inspector_does_not_reset_allowance_and_body_loop_does(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: Client())
    being = ReplicantArchive.create(conceive(), tmp_path / 'life.replicant', tmp_path / 'home')
    runtime = LivingReplicant(being, Body())
    try:
        runtime.guard._hour_start = time.time() - 3601
        runtime.guard._cycle_count_this_hour = 6
        async with runtime.entity.store.session(): pass
        before = runtime.guard._hour_start
        snapshot = await runtime.inspect()
        assert snapshot['wake_limits']['wakes_this_hour'] == 6
        assert runtime.guard._hour_start == before
        assert snapshot['acceptance']['appraisal']['checked_bar_acceptance_rate'] is None
        async def finish_tick(): runtime._stop.set()
        monkeypatch.setattr(runtime, 'life_tick', finish_tick)
        await runtime._body_loop()
        assert runtime.guard._cycle_count_this_hour == 0 and runtime.guard._hour_start > before
    finally:
        await runtime.entity.shutdown()
        being.close()
