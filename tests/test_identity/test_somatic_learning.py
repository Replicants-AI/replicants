import math
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from replicants.config import HarnessConfig, default_soma_config, entity_from_dict
from replicants.entity import Entity, TurnContext
from replicants.identity.soma import TonicBody
from replicants.models import Input


@pytest.fixture
def body(tmp_path, monkeypatch):
    monkeypatch.setattr('replicants.identity.soma.time.time', lambda: 1000.0)
    return TonicBody(default_soma_config(), tmp_path / 'soma')


def entity_for(body):
    return SimpleNamespace(tonic=body, client=object(),
                           config=entity_from_dict(HarnessConfig(), {'name': 'learning-test'}))


def turn(person_id='alice', platform='cli'):
    return TurnContext(inp=Input(text='hello', person_id=person_id, person_name=person_id,
                                 channel='chat', platform=platform), reply_text='hello back')


@pytest.mark.parametrize('effects', [{'comfort': 4.0, 'social': 3.0}, {'tension': 8.0, 'comfort': -4.0}])
async def test_interaction_appraisal_learns_person_specific_marker(body, effects):
    body.appraiser.appraise_interaction = AsyncMock(return_value={'bar_effects': effects, 'tags': [], 'felt': 'observed'})
    entity = entity_for(body)
    for _ in range(30):
        await Entity._somatic_appraise_interaction(entity, turn())
    marker = body.bars._somatic_markers['alice']
    assert 'bob' not in body.bars._somatic_markers
    for bar, target in effects.items():
        expected = max(-5, min(5, target)) * (1 - .95 ** 30)
        assert marker[bar] == pytest.approx(expected)
        assert abs(marker[bar]) <= 5


async def test_marker_fires_before_next_input_appraisal_and_survives_restart(body, tmp_path):
    body.appraiser.appraise_interaction = AsyncMock(return_value={
        'bar_effects': {'comfort': 4.0, 'social': 3.0}, 'tags': [], 'felt': 'warm',
    })
    entity = entity_for(body)
    for _ in range(10):
        await Entity._somatic_appraise_interaction(entity, turn())
    restored = TonicBody(default_soma_config(), tmp_path / 'soma')
    assert restored.restore_state()
    assert restored.bars._somatic_markers == body.bars._somatic_markers
    entity.tonic = restored
    restored.bars._values['comfort'] = 50.0
    seen = []

    async def appraise(*args, **kwargs):
        seen.append(restored.bars._values['comfort'])
        return {'bar_effects': {}, 'tags': [], 'felt': ''}

    restored.appraise_and_apply = appraise
    await Entity._somatic_appraise_input(entity, turn())
    expected = 50 + restored.bars._somatic_markers['alice']['comfort'] * .5
    assert seen == [expected]


def test_marker_learning_is_bounded_and_decays_toward_neutral(body):
    for _ in range(500):
        body.bars.learn_somatic_marker('person', {'tension': 1000.0, 'comfort': -1000.0})
    old = dict(body.bars._somatic_markers['person'])
    assert 0 < old['tension'] <= 5
    assert -5 <= old['comfort'] < 0
    body.bars.tick(1)
    for bar in old:
        assert body.bars._somatic_markers['person'][bar] == pytest.approx(old[bar] * math.exp(-.001))
    body.bars._apply_offline_decay(1000 - 3600)
    for bar in old:
        assert body.bars._somatic_markers['person'][bar] == pytest.approx(old[bar] * math.exp(-.002))


@pytest.mark.parametrize('person_id,platform', [('', 'cli'), ('self', 'autonomous'), ('harness_emergence', 'automation')])
async def test_unidentified_or_internal_turn_does_not_form_person_marker(body, person_id, platform):
    body.appraiser.appraise_interaction = AsyncMock(return_value={
        'bar_effects': {'comfort': 4}, 'tags': [], 'felt': 'warm',
    })
    await Entity._somatic_appraise_interaction(entity_for(body), turn(person_id, platform))
    assert body.bars._somatic_markers == {}


async def test_synthetic_want_is_not_appraised_as_an_outcome(body):
    body.appraise_and_apply = AsyncMock()
    tc = turn('self', 'autonomous')
    tc.inp.metadata['soma_desire_id'] = body.bars.record_desire('social', 'reach_out', 'reach_out', 90)
    before = dict(body.bars._values)
    await Entity._somatic_appraise_input(entity_for(body), tc)
    body.appraise_and_apply.assert_not_called()
    assert body.bars._values == before
