import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from replicants.config import HarnessConfig, default_soma_config, entity_from_dict
from replicants.entity import Entity, TurnContext
from replicants.identity.drives import DriveSystem
from replicants.identity.soma import TonicBody
from replicants.models import Input
from replicants.presence.daemon import PresenceDaemon
from replicants.presence.wake_cycle import WakeCycleEngine


@pytest.fixture
def clock(monkeypatch):
    now = [10000.0]
    monkeypatch.setattr('replicants.identity.soma.time.time', lambda: now[0])
    monkeypatch.setattr('replicants.identity.soma.time.monotonic', lambda: now[0])
    return now


def body_with_impulse(tmp_path, mode='outcome', ttl=3600):
    cfg = default_soma_config()
    cfg.update(relief_mode=mode, pending_desire_ttl_seconds=ttl)
    body = TonicBody(cfg, tmp_path / 'soma')
    body.bars._values['social'] = 90.0
    body.bars._impulse_last_fired['reach_out'] -= 3600
    body.bars.tick(0)
    return body


def config():
    cfg = entity_from_dict(HarnessConfig(), {'name': 'outcome-test'})
    cfg.harness.autonomy.enabled = True
    cfg.harness.autonomy.transcript_enabled = False
    cfg.harness.autonomy.wake_session_max_rounds = 1
    cfg.drives.initiative_cooldown = 0
    return cfg


def client_for(effects):
    return SimpleNamespace(chat_completion=AsyncMock(return_value=SimpleNamespace(content=json.dumps({
        'bar_effects': effects, 'tags': ['observed'], 'felt': 'an observed result',
    }))))


def test_fire_records_desire_without_relief(tmp_path, clock):
    body = body_with_impulse(tmp_path)
    assert body.bars._values['social'] == 90
    desire, = body.bars.pending_desires.values()
    assert desire['id']
    assert desire['drive'] == 'social'
    assert desire['impulse_type'] == 'reach_out'
    assert desire['triggering_pressure'] == 90
    assert desire['fired_at'] == clock[0]


@pytest.mark.parametrize('gate', ['cooldown', 'silence_threshold', 'rate_limit', 'dormant'])
def test_host_gate_never_grants_relief_and_is_logged_on_expiry(tmp_path, clock, gate):
    body = body_with_impulse(tmp_path, ttl=60)
    engine = WakeCycleEngine(config())
    engine._last_cycle_at = 0
    if gate == 'cooldown':
        engine._last_cycle_at = clock[0]
    if gate == 'rate_limit':
        engine._cycle_count_this_hour = engine._auto.max_cycles_per_hour
    clock[0] += 61
    assert engine.should_wake(tonic=body, drives=[], silence_seconds=0 if gate == 'silence_threshold' else 1000,
                              dormant=gate == 'dormant') is None
    assert body.bars._values['social'] == 90
    assert not body.bars.pending_desires
    record, = body.bars.unlived_wants
    assert record['gate_type'] == 'host_rule'
    assert record['gate_reason'] == gate
    assert not body.bars.realized_relief


@pytest.mark.parametrize('effects', [
    {'social': -9, 'comfort': 4},
    {'social': -1, 'tension': 3},
    {'social': 2, 'tension': 5},
])
async def test_realized_relief_comes_only_from_appraisal_and_is_idempotent(tmp_path, clock, effects):
    body = body_with_impulse(tmp_path)
    desire_id = next(iter(body.bars.pending_desires))
    body.bars.start_desire(desire_id)
    before = dict(body.bars._values)
    kwargs = dict(input_text='reach out', reply_text='hello', person_name='person', desire_id=desire_id,
                  outcome_context='Observed recipient response, or lack of one.')
    result = await body.appraise_interaction_and_apply(client_for(effects), 'model', **kwargs)
    actual = {k: body.bars._values[k] - before[k] for k in effects}
    assert result['realized_effects'] == actual
    assert body.bars.realized_relief['reach_out']['last_effects'] == actual
    assert actual['social'] == pytest.approx(effects['social'] if effects['social'] < 0 else effects['social'] * .1)
    after = dict(body.bars._values)
    await body.appraise_interaction_and_apply(client_for(effects), 'model', **kwargs)
    assert body.bars._values == after
    assert body.bars.realized_relief['reach_out']['count'] == 1


async def test_failed_appraisal_does_not_invent_relief(tmp_path, clock):
    body = body_with_impulse(tmp_path)
    desire_id = next(iter(body.bars.pending_desires))
    body.bars.start_desire(desire_id)
    client = SimpleNamespace(chat_completion=AsyncMock(side_effect=RuntimeError('offline')))
    await body.appraise_interaction_and_apply(client, 'model', input_text='try', reply_text='hello',
                                             person_name='person', desire_id=desire_id)
    assert body.bars._values['social'] == 90
    assert desire_id in body.bars.pending_desires
    assert not body.bars.realized_relief


def test_legacy_mode_preserves_fixed_relief(tmp_path, clock):
    body = body_with_impulse(tmp_path, mode='legacy')
    assert body.bars._values['social'] == 65
    assert not body.bars.pending_desires


def test_cooldown_decay_and_dedup_survive_without_immediate_relief(tmp_path, clock):
    body = body_with_impulse(tmp_path)
    desire_id = next(iter(body.bars.pending_desires))
    for _ in range(10):
        clock[0] += 120
        body.bars.tick(0)
        assert body.bars._active_impulses[0]['on_cooldown']
        assert list(body.bars.pending_desires) == [desire_id]
    clock[0] += 600
    body.bars.tick(0)
    assert not body.bars._active_impulses[0]['on_cooldown']
    assert list(body.bars.pending_desires) == [desire_id]
    body.bars.tick(1)
    assert body.bars._values['social'] < 90


async def test_autonomous_run_attributes_real_perceive_appraisal(tmp_path, clock, monkeypatch):
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    body = body_with_impulse(tmp_path)
    cfg = config()
    engine = WakeCycleEngine(cfg)
    entity = SimpleNamespace(config=cfg, tonic=body, client=client_for({'social': -8}),
                             _history=[], _platforms={}, _last_conversation={})
    seen = []

    async def perceive(inp, **kwargs):
        seen.append(inp.metadata['soma_desire_id'])
        tc = TurnContext(inp=inp, reply_text='a completed action',
                         tool_state={'tool_output_previews': [{'tool': 'send_message_to', 'result': 'delivered'}]})
        await Entity._somatic_appraise_interaction(entity, tc)
        return tc.reply_text, False

    entity.perceive = perceive
    engine._compose_stirring = AsyncMock(return_value=('stir', None))
    await engine.run(entity=entity, tonic=body, reason='impulse:reach_out')
    assert len(seen) == 1
    assert not body.bars.pending_desires
    assert body.bars._values['social'] == 82
    assert body.bars.realized_relief['reach_out']['count'] == 1
    prompt = entity.client.chat_completion.call_args.args[1]
    assert 'external_reply_observed' in prompt[1]['content']
    assert 'Do not invent one' in prompt[0]['content']
    assert engine.should_wake(tonic=body, drives=[], silence_seconds=1000) is None


async def test_explicit_creature_decline_is_not_a_host_rule(tmp_path, clock):
    body = body_with_impulse(tmp_path, ttl=60)
    desire_id = next(iter(body.bars.pending_desires))

    async def decline(inp, **kwargs):
        kwargs['tool_names_log'].append('end_wake_session')
        tc = TurnContext(inp=inp, reply_text='', tool_state={
            'tool_output_previews': [{'tool': 'end_wake_session', 'ok': True, 'preview': '[wake session end requested]'}],
        })
        await Entity._somatic_appraise_interaction(entity, tc)
        return '', False

    entity = SimpleNamespace(tonic=body, perceive=decline, _platforms={}, _last_conversation={},
                             config=config(), client=client_for({'social': -9}))
    engine = WakeCycleEngine(config())
    await engine._run_perceive(entity, 'an opportunity', metadata={'soma_desire_id': desire_id})
    clock[0] += 61
    # A subsequent scheduler gate must not rewrite the creature's explicit choice.
    engine._last_cycle_at = clock[0]
    assert engine.should_wake(tonic=body, drives=[], silence_seconds=1000) is None
    assert body.bars.unlived_wants[0]['gate_type'] == 'creature_choice'
    assert body.bars.unlived_wants[0]['gate_reason'] == 'declined_action'
    assert body.bars._values['social'] == 90
    entity.client.chat_completion.assert_not_called()
    assert not any(event['type'] == 'idle_cycle' for event in body._recent_events)


@pytest.mark.parametrize('message', ['', RuntimeError('offline')])
async def test_unsuccessful_initiative_keeps_want_and_consumes_cooldown(tmp_path, clock, message):
    body = body_with_impulse(tmp_path)
    cfg = config()
    cfg.harness.autonomy.enabled = False
    cfg.drives.initiative_cooldown = 1800
    drives = DriveSystem(cfg)
    drives.register_initiative_time(clock[0] - 1800)
    drive = drives._d.connection
    drive.level = .9
    entity = SimpleNamespace(config=cfg, tonic=body, drives=drives, client=client_for({'social': -9}),
                             proactive_context_for_drive=AsyncMock(return_value='wanted company'),
                             broadcast_proactive=AsyncMock())
    daemon = PresenceDaemon(entity)
    compose = AsyncMock(side_effect=message) if isinstance(message, Exception) else AsyncMock(return_value=message)
    daemon._initiative.compose_proactive = compose
    if isinstance(message, Exception):
        with pytest.raises(RuntimeError):
            await daemon._run_legacy_initiative([drive], clock[0], body)
    else:
        await daemon._run_legacy_initiative([drive], clock[0], body)
    desire, = body.bars.pending_desires.values()
    assert desire['gate_type'] == 'environment'
    assert desire['gate_reason'] == ('action_failed' if isinstance(message, Exception) else 'no_generated_action')
    clock[0] += 120
    await daemon._run_legacy_initiative([drive], clock[0], body)
    assert compose.await_count == 1
    assert body.bars._values['social'] == 90
    assert drive.level == .9
    assert not body.bars.realized_relief
    entity.client.chat_completion.assert_not_called()
    entity.broadcast_proactive.assert_not_called()


@pytest.mark.parametrize('sent', [True, False, None])
async def test_legacy_initiative_uses_appraised_outcome(tmp_path, clock, sent):
    body = body_with_impulse(tmp_path)
    cfg = config()
    cfg.harness.autonomy.enabled = False
    drives = DriveSystem(cfg)
    drive = drives._d.connection
    drive.level = .9
    entity = SimpleNamespace(config=cfg, tonic=body, drives=drives, client=client_for({'social': -1}),
                             proactive_context_for_drive=AsyncMock(return_value='wanted company'),
                             broadcast_proactive=AsyncMock(return_value=sent))
    daemon = PresenceDaemon(entity)
    daemon._initiative.compose_proactive = AsyncMock(return_value='hello')
    await daemon._run_legacy_initiative([drive], clock[0], body)
    assert body.bars._values['social'] == 89
    assert drive.level == pytest.approx(.89)
    assert body.bars.realized_relief['reach_out']['count'] == 1
    prompt = entity.client.chat_completion.call_args.args[1][1]['content']
    assert ('delivered' if sent is True else 'Delivery failed' if sent is False else 'unconfirmed') in prompt


@pytest.mark.parametrize('receipt', [True, False, None, RuntimeError('offline')])
async def test_proactive_callback_completion_is_not_delivery_confirmation(receipt):
    sink = AsyncMock(side_effect=receipt) if isinstance(receipt, Exception) else AsyncMock(return_value=receipt)
    entity = SimpleNamespace(_proactive_sends=[sink], _history=[])
    actual = await Entity.broadcast_proactive(entity, 'hello')
    assert actual is (False if isinstance(receipt, Exception) else receipt)


@pytest.mark.parametrize('backend', ['filesystem', 'database'])
async def test_relief_pending_and_expiry_records_survive_restart(tmp_path, clock, backend):
    body = body_with_impulse(tmp_path, ttl=60)
    desire_id = next(iter(body.bars.pending_desires))
    body.bars.start_desire(desire_id)
    await body.appraise_interaction_and_apply(client_for({'social': -7}), 'model', input_text='hello',
                                             reply_text='response', person_name='person', desire_id=desire_id)
    body.bars.record_desire('curiosity', 'explore', 'old', 80)
    body.bars.note_desire_gate('quiet_hours', 'host_rule')
    clock[0] += 61
    body.bars.expire_desires()
    body.bars.record_desire('curiosity', 'explore', 'new', 88)
    restored = TonicBody(default_soma_config(), tmp_path / 'soma')
    async with aiosqlite.connect(tmp_path / 'state.db') as conn:
        await conn.execute('CREATE TABLE entity_state (key TEXT PRIMARY KEY, value TEXT)')
        if backend == 'filesystem':
            body.save_state()
            assert restored.restore_state()
        else:
            await body.save_state_db(conn)
            assert await restored.restore_state_db(conn)
    assert restored.bars.realized_relief == body.bars.realized_relief
    assert restored.bars.unlived_wants == body.bars.unlived_wants
    assert restored.bars.pending_desires == body.bars.pending_desires
