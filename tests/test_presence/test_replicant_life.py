import json
from pathlib import Path

import pytest

from replicants.desktop.archive import ReplicantArchive, verify
from replicants.desktop.genome import conceive
from replicants.desktop.life import LivingReplicant
from replicants.desktop.runtime import PERSON
from replicants.identity.soma import NoiseFragment
from replicants.inference.types import ChatCompletionResult


class Client:
    async def close(self): pass
    async def chat_completion(self, *args, **kwargs):
        if args[1][0]['content'].startswith('Read this felt note'):
            return ChatCompletionResult('{"social":"less","comfort":"more"}')
        return ChatCompletionResult('{"bar_effects":{"comfort":{"change":"increased","amount":5},'
            '"social":{"change":"eased","amount":4}},"tags":["warmth"],"felt":"a new familiar warmth"}')


class Body:
    connected = True
    def __init__(self): self.packets = []
    async def publish(self, kind, payload): self.packets.append((kind, payload)); return True


@pytest.mark.asyncio
async def test_body_and_gen_trigger_one_birth_then_naming_imprint_and_restart(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('REPLICANTS_EXECUTION_WORKSPACE_DIR', str(tmp_path / 'must-not-use'))
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: Client())
    being = ReplicantArchive.create(conceive('curious', 'mint', 5), tmp_path / 'pip.replicant', tmp_path / 'data')
    body = Body(); runtime = LivingReplicant(being, body)
    assert Path(runtime.entity.config.soma_dir()).is_relative_to(being.life)
    assert runtime.appearance == {'palette': '#C8E5D1', 'layers': []}
    await runtime.started()
    await runtime.receive({'type': 'event', 'payload': {'kind': 'chat', 'text': 'not a name yet'}})
    assert runtime._jobs.empty() and runtime.display_name == ''
    await runtime.body_tick(2)
    assert await runtime.next_wake_reason() is None
    await runtime.body_tick(4)
    assert await runtime.next_wake_reason() is None  # no generated inner life yet
    runtime.entity.tonic.noise._fragments.append(NoiseFragment('a little pull outward'))
    reason = await runtime.next_wake_reason()
    assert reason, (runtime.state(), runtime.entity.tonic.bars.pending_desires, runtime.entity.tonic.bars._active_impulses)
    assert runtime.state()['naming']
    assert len([e for e in being.lineage if e['kind'] == 'first_breath']) == 1
    assert not (tmp_path / 'must-not-use').exists()
    await runtime.receive({'type': 'event', 'payload': {'kind': 'chat', 'text': 'Pip'}})
    assert runtime.display_name == 'Pip'
    assert runtime.life_state['phase'] == 'imprinting'
    await runtime._appraise('I have been named Pip', [{'status': 'completed', 'name': 'wave'}], reaction='chat')
    assert runtime.life_state['sealed']
    assert runtime.entity.tonic.bars._somatic_markers[PERSON]['comfort'] == 1.0
    assert runtime.entity.tonic.bars._marker_learning_rate == .05
    runtime.entity.tonic.bars._initial['comfort'] = 73.125
    await runtime.checkpoint()
    await runtime.before_shutdown(); runtime.save_runtime(); await runtime.entity.shutdown(); await runtime.after_shutdown()
    manifest, _ = verify(being.path)
    assert manifest['name'] == 'Pip'
    resumed = ReplicantArchive.open(being.path, tmp_path / 'data')
    awake = LivingReplicant(resumed, body)
    try:
        assert awake.life_state['sealed'] and awake.life_state['phase'] == 'newborn'
        assert awake.display_name == 'Pip'
        assert awake.entity.tonic.bars._initial['comfort'] == 73.125
        assert awake.entity.tonic.bars._somatic_markers[PERSON]['comfort'] == pytest.approx(1, abs=1e-5)
        await awake.started()
        kinds = [e['kind'] for e in resumed.lineage]
        assert kinds.count('genesis') == kinds.count('first_breath') == kinds.count('naming') == kinds.count('imprinting') == kinds.count('birth_sealed') == 1
        assert kinds[-1] == 'wake' and resumed.lineage[-1]['data']['gap_seconds'] >= 0
    finally:
        await awake.entity.shutdown(); resumed.close()


def test_genome_contains_tendencies_only_and_birth_is_always_a_new_identity(tmp_path):
    one = ReplicantArchive.create(conceive('shy', 'pearl', 30), data_home=tmp_path)
    two = ReplicantArchive.create(conceive('shy', 'pearl', 30), data_home=tmp_path)
    try:
        assert one.id != two.id
        assert one.manifest['name'] is None
        text = json.dumps(one.genome)
        assert all(key not in text for key in ('backstory', 'goals', 'memories'))
        assert one.genome['parents'] == []
        with pytest.raises(FileExistsError): ReplicantArchive.create(conceive(), one.path, tmp_path)
    finally: one.close(); two.close()


@pytest.mark.asyncio
async def test_inspections_leave_observations_without_cosmetic_rewards(tmp_path, monkeypatch):
    from replicants.models import Input
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: Client())
    being = ReplicantArchive.create(conceive(), tmp_path / 'one.replicant', tmp_path / 'data')
    body = Body()
    result = {'act_id': 'one', 'name': 'inspect_window', 'status': 'completed', 'evidence': {'window_id': '123'}}
    async def action(name, args): return dict(result)
    body.action = action
    runtime = LivingReplicant(being, body)
    own = Input('curiosity', 'self', 'self', 'desktop', 'autonomous')
    human = Input('inspect a window', PERSON, 'person', 'desktop', 'desktop')
    await runtime.perform('inspect_window', {}, human)
    result['status'] = 'failed'
    await runtime.perform('inspect_window', {}, own)
    assert not runtime.life_state.get('chosen_inspections')
    result['status'] = 'completed'
    await runtime.perform('inspect_window', {}, own)
    await runtime.perform('inspect_window', {}, own)  # Duplicate receipt is not another experience.
    result['act_id'] = 'two'; await runtime.perform('inspect_window', {}, own)
    assert not runtime.appearance['layers']
    for index in range(3, 10):
        result['act_id'] = str(index)
        await runtime.perform('inspect_window', {}, own)
    assert not runtime.appearance['layers']
    assert not runtime.life_state.get('chosen_inspections')
    assert not any(e['kind'] == 'appearance_earned' for e in being.lineage)
    assert runtime.action_history[-1]['evidence'] == {'window_id': '123'}
    await runtime.checkpoint(); await runtime.entity.shutdown(); being.close()
    resumed = ReplicantArchive.open(being.path, tmp_path / 'data')
    awake = LivingReplicant(resumed, body)
    try:
        assert not awake.appearance['layers']
        result['act_id'] = 'four'; await awake.perform('inspect_window', {}, own)
        assert not any(e['kind'] == 'appearance_earned' for e in resumed.lineage)
    finally: await awake.entity.shutdown(); resumed.close()


@pytest.mark.asyncio
async def test_retired_reward_is_removed_without_rewriting_history(tmp_path, monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setattr('replicants.entity.build_inference_provider', lambda _: Client())
    being = ReplicantArchive.create(conceive(), tmp_path / 'old.replicant', tmp_path / 'data')
    runtime = LivingReplicant(being, Body())
    runtime.appearance['layers'] = ['glasses', 'beanie']
    runtime.life_state['chosen_inspections'] = [{'act_id': str(i)} for i in range(3)]
    original = being.append('appearance_earned', {'layer': 'glasses',
        'reason': 'Completed three window inspections chosen during autonomous wakes.'})
    await runtime.checkpoint(); await runtime.entity.shutdown(); being.close()
    for _ in range(2):
        being = ReplicantArchive.open(being.path, tmp_path / 'data')
        runtime = LivingReplicant(being, Body())
        try:
            assert runtime.appearance['layers'] == ['beanie']
            assert 'chosen_inspections' not in runtime.life_state
            assert next(e for e in being.lineage if e['kind'] == 'appearance_earned') == original
            assert len([e for e in being.lineage if e['kind'] == 'host_revision']) == 1
            await runtime.checkpoint()
        finally:
            await runtime.entity.shutdown(); being.close()
