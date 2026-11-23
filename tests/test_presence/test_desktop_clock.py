import math
import time

import pytest

from replicants.desktop.clock import SimClock, time_scale
from replicants.identity.soma import BarEngine


def test_clock_dilation_changes_continuously_and_restores_offline_time(monkeypatch):
    monkeypatch.delenv('REPLICANTS_START_HOUR', raising=False)
    monkeypatch.setenv('REPLICANTS_TIME_SCALE', '60')
    tick = [100.0]
    wall = [1800000000.0]
    clock = SimClock(wall=lambda: wall[0], monotonic=lambda: tick[0])
    start = clock.now()
    tick[0] += 10
    assert clock.now() - start == 600
    clock.change_scale(360)
    assert clock.now() - start == 600
    tick[0] += 5
    assert clock.now() - start == 2400
    saved = clock.snapshot()
    wall[0] += 20
    monkeypatch.delenv('REPLICANTS_TIME_SCALE')
    resumed = SimClock(saved, wall=lambda: wall[0], monotonic=lambda: tick[0])
    assert resumed.scale == 360 and resumed.now() == saved['sim'] + 7200
    for value in [0, -1, 361, float('inf'), float('nan')]:
        with pytest.raises(ValueError): time_scale(value)


def test_offline_decay_uses_saved_sim_rate_and_drifted_baseline(monkeypatch):
    bars = BarEngine({'bars': {'variables': [{'name': 'comfort', 'initial': 20, 'decay_rate': -30}]}, 'offline_time_scale': 60})
    bars._initial['comfort'] = 70
    bars._values['comfort'] = 90
    bars._somatic_markers['person'] = {'comfort': 2}
    now = time.time()
    monkeypatch.setattr('replicants.identity.soma.time.time', lambda: now)
    bars._apply_offline_decay(now - 60)
    assert bars._values['comfort'] == pytest.approx(70 + 20 * math.exp(-.3))
    assert bars._somatic_markers['person']['comfort'] == pytest.approx(2 * math.exp(-.001))
