import json
import math

import aiosqlite
import pytest

from replicants.config import default_soma_config
from replicants.identity.soma import TonicBody


@pytest.mark.parametrize('backend', ['filesystem', 'database'])
@pytest.mark.parametrize('old_format', [False, True])
async def test_adaptation_round_trip(tmp_path, monkeypatch, backend, old_format):
    monkeypatch.setattr('replicants.identity.soma.time.time', lambda: 1000.0)
    body = TonicBody(default_soma_config(), tmp_path / 'soma')
    defaults = dict(body.bars._initial)
    body.bars._initial['social'] = 63.125
    body.bars._initial['comfort'] = 73.75
    body.bars.register_somatic_marker('person-a', {'comfort': 3.25, 'tension': -1.125})
    expected_initial = dict(body.bars._initial)
    expected_markers = {'person-a': {'comfort': 3.25, 'tension': -1.125}}
    restored = TonicBody(default_soma_config(), tmp_path / 'soma')
    async with aiosqlite.connect(tmp_path / 'state.db') as conn:
        await conn.execute('CREATE TABLE entity_state (key TEXT PRIMARY KEY, value TEXT)')
        if backend == 'filesystem':
            body.save_state()
            path = tmp_path / 'soma' / 'soma-state.json'
            saved = json.loads(path.read_text())
        else:
            await body.save_state_db(conn)
            row = await (await conn.execute('SELECT value FROM entity_state')).fetchone()
            saved = json.loads(row[0])
        if old_format:
            saved.pop('initial')
            saved.pop('somatic_markers')
            # Loading an old snapshot must also discard stale adaptations in a reused body.
            restored.bars._initial['social'] = 99
            restored.bars.register_somatic_marker('stale', {'social': 5})
            if backend == 'filesystem':
                path.write_text(json.dumps(saved))
            else:
                await conn.execute('UPDATE entity_state SET value=?', (json.dumps(saved),))
                await conn.commit()
        ok = restored.restore_state() if backend == 'filesystem' else await restored.restore_state_db(conn)
    assert ok
    assert restored.bars._initial == (defaults if old_format else expected_initial)
    assert restored.bars._somatic_markers == ({} if old_format else expected_markers)
    assert restored.bars._values == body.bars._values


@pytest.mark.parametrize('backend', ['filesystem', 'database'])
async def test_offline_decay_uses_restored_baseline(tmp_path, monkeypatch, backend):
    now = [1000.0]
    monkeypatch.setattr('replicants.identity.soma.time.time', lambda: now[0])
    body = TonicBody(default_soma_config(), tmp_path / 'soma')
    body.bars._initial['social'] = 70.0
    body.bars._values['social'] = 90.0
    restored = TonicBody(default_soma_config(), tmp_path / 'soma')
    async with aiosqlite.connect(tmp_path / 'state.db') as conn:
        await conn.execute('CREATE TABLE entity_state (key TEXT PRIMARY KEY, value TEXT)')
        if backend == 'filesystem':
            body.save_state()
        else:
            await body.save_state_db(conn)
        now[0] += 3600.0
        assert restored.restore_state() if backend == 'filesystem' else await restored.restore_state_db(conn)
    assert restored.bars._initial['social'] == 70.0
    assert restored.bars._values['social'] == pytest.approx(70 + 20 * math.exp(-0.4))


def test_snapshot_is_detached_from_live_markers(tmp_path):
    body = TonicBody(default_soma_config(), tmp_path)
    body.bars.register_somatic_marker('person', {'comfort': 2.0})
    saved = body._snapshot_all()
    body.bars._somatic_markers['person']['comfort'] = 4.0
    assert saved['somatic_markers']['person']['comfort'] == 2.0
