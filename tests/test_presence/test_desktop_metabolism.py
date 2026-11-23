from types import SimpleNamespace

import pytest

from replicants.desktop import metabolism as m
from replicants.desktop.metabolism import DecayedMean, Metabolism, crowding
from replicants.desktop.substrate import ComputeLedger, MeteredClient


class Result:
    def __init__(self, completion=None, eval_seconds=None):
        self.usage = {} if completion is None else {'completion_tokens': completion}
        self.timings = {} if eval_seconds is None else {'eval_duration': eval_seconds}


def make(saved=None):
    clock = {'tick': 100.0, 'wall': 10_000.0}
    ledger = ComputeLedger(wall=lambda: clock['wall'], monotonic=lambda: clock['tick'])
    meta = Metabolism(ledger, saved, monotonic=lambda: clock['tick'], wall=lambda: clock['wall'])
    return clock, ledger, meta


def advance(clock, seconds):
    clock['tick'] += seconds
    clock['wall'] += seconds


def chat(clock, ledger, seconds, result=None, model='model'):
    key = ledger.begin('chat', model)
    advance(clock, seconds)
    ledger.finish(key, 'completed', result)


def test_long_request_is_spread_across_the_windows_it_spans():
    clock, ledger, meta = make()
    key = ledger.begin('chat', 'model')
    advance(clock, 10); meta.sample()
    assert meta.last['occupancy'] == 1.0
    assert meta.last['idle_run_seconds'] == 0.0  # Thinking is not rest.
    advance(clock, 5); ledger.finish(key, 'completed')
    advance(clock, 5); meta.sample()
    assert meta.last['occupancy'] == pytest.approx(0.5)
    assert meta.last['idle_run_seconds'] == pytest.approx(5)


def test_fresh_process_reports_observed_idle_before_any_request():
    clock, ledger, meta = make()
    advance(clock, 30); meta.sample()
    assert meta.last['idle_run_seconds'] == pytest.approx(30)
    key = ledger.begin('chat', 'model'); advance(clock, 10); meta.sample()
    assert meta.last['idle_run_seconds'] == 0.0
    ledger.finish(key, 'completed'); advance(clock, 4); meta.sample()
    assert meta.last['idle_run_seconds'] == pytest.approx(4)


def test_failed_and_cancelled_work_counts_and_overlap_is_not_double_counted():
    clock, ledger, meta = make()
    a = ledger.begin('chat', 'model'); b = ledger.begin('embedding', 'embed')
    advance(clock, 4); ledger.finish(a, 'failed'); ledger.finish(b, 'cancelled')
    advance(clock, 6); meta.sample()
    assert meta.last['occupancy'] == pytest.approx(0.4)
    assert meta.last['concurrency'] == pytest.approx(0.8)
    assert meta.counters['requests'] == 2


def test_pace_is_per_model_and_unknown_pace_stays_unknown():
    clock, ledger, meta = make()
    chat(clock, ledger, 3, Result(completion=40, eval_seconds=2.0), model='large')
    chat(clock, ledger, 3, Result(completion=300, eval_seconds=1.0), model='small')
    chat(clock, ledger, 3, Result(), model='large')  # No usage or timings reported.
    assert meta.pace['large']['fast'].value == 20.0
    assert meta.pace['small']['fast'].value == 300.0
    assert meta.pace_samples == {'large': 1, 'small': 1}
    assert meta.calibration()['pace_coverage'] == pytest.approx(2 / 3)


def test_restart_decays_exactly_like_an_uninterrupted_process():
    """Builder's regression: a 24-hour gap must decay the same with or without a restart."""
    def history(meta, clock, ledger):
        chat(clock, ledger, 1, Result(completion=100, eval_seconds=1.0))  # 100 tok/s
        meta.sample()
        advance(clock, 24 * 3600)

    clock, ledger, uninterrupted = make()
    history(uninterrupted, clock, ledger)
    chat(clock, ledger, 1, Result(completion=10, eval_seconds=1.0))  # 10 tok/s
    expected = uninterrupted.pace['model']['fast'].value

    clock, ledger, before = make()
    history(before, clock, ledger)
    saved = before.persisted()
    ledger = ComputeLedger(wall=lambda: clock['wall'], monotonic=lambda: clock['tick'])
    restored = Metabolism(ledger, saved, monotonic=lambda: clock['tick'], wall=lambda: clock['wall'])
    chat(clock, ledger, 1, Result(completion=10, eval_seconds=1.0))
    assert restored.pace['model']['fast'].value == pytest.approx(expected)
    assert restored.pace['model']['slow'].value == pytest.approx(uninterrupted.pace['model']['slow'].value)
    assert expected == pytest.approx(10.0, abs=1e-6)


def test_listener_failure_never_fails_inference():
    clock, ledger, meta = make()
    def broken(observation):
        raise RuntimeError('telemetry bug')
    ledger.listeners.insert(0, broken)
    chat(clock, ledger, 2, Result(completion=20, eval_seconds=1.0))
    assert ledger.totals['chat']['completed'] == 1
    assert meta.pace_samples == {'model': 1}  # Later listeners still run.


@pytest.mark.asyncio
async def test_listener_failure_does_not_surface_through_metered_client():
    ledger = ComputeLedger()
    ledger.listeners.append(lambda observation: 1 / 0)
    async def ok(*args, **kwargs):
        return SimpleNamespace(usage={}, timings={}, content='fine')
    client = MeteredClient(SimpleNamespace(chat_completion=ok), ledger)
    assert (await client.chat_completion('model', [])).content == 'fine'


def test_model_is_withheld_until_calibrated_and_never_applied():
    clock, ledger, meta = make()
    for _ in range(3):
        chat(clock, ledger, 5); advance(clock, 5); meta.sample()
    model = meta.model()
    assert model['exertion'] is None and model['sluggish'] is None
    assert model['applied'] is False
    assert meta.snapshot()['calibration']['occupancy'] is False


def test_exertion_relative_to_own_baseline_once_calibrated():
    clock, ledger, meta = make()
    meta.counters.update(observation_seconds=m.MIN_OBSERVATION_SECONDS, requests=m.MIN_OBSERVATIONS)
    meta.occupancy['slow'].value, meta.occupancy['fast'].value = 0.1, 0.25
    assert meta.model()['exertion'] == pytest.approx(1.5)
    meta.occupancy['slow'].value = 0.0  # Near-zero baseline uses the floor, not a division blow-up.
    assert meta.model()['exertion'] == 3


def test_sluggish_uses_the_best_evidenced_model_only():
    clock, ledger, meta = make()
    meta.counters['observation_seconds'] = m.MIN_OBSERVATION_SECONDS
    for model, fast, slow, count in (('large', 15.0, 20.0, 60), ('small', 300.0, 100.0, 5)):
        pair = meta.pace.setdefault(model, m._pair(None))
        pair['fast'].value, pair['slow'].value = fast, slow
        meta.pace_samples[model] = count
    assert meta.calibration()['pace_model'] == 'large'
    assert meta.model()['sluggish'] == pytest.approx(0.25)


def test_suspended_gap_is_not_observation_time():
    clock, ledger, meta = make()
    advance(clock, 3600); meta.sample()
    assert meta.counters['observation_seconds'] == 0
    assert meta.occupancy['slow'].value is None


def test_decayed_mean_fades_by_elapsed_time():
    mean = DecayedMean(10.0)
    mean.add(1.0, 1.0, 0)
    mean.add(0.0, 1.0, 10)  # Prior evidence now carries half weight.
    assert mean.value == pytest.approx(1 / 3)


def test_crowding_is_absolute_near_capacity_and_unknown_without_sensors():
    assert crowding({}) is None
    assert crowding({'memory': {'status': 'unavailable'}}) is None
    assert crowding({'memory': {'status': 'available', 'used_percent': 50}}) == 0
    assert crowding({'memory': {'status': 'available', 'used_percent': 95}}) == pytest.approx(0.5)
    gpu = {'status': 'available', 'devices': [{'memory_used_bytes': 99, 'memory_total_bytes': 100}]}
    assert crowding({'gpu': gpu}) == pytest.approx(0.4)


def test_persistence_round_trip_and_unknown_versions_start_fresh():
    clock, ledger, meta = make()
    chat(clock, ledger, 5, Result(completion=10, eval_seconds=1.0)); advance(clock, 5); meta.sample()
    saved = meta.persisted()
    restored = Metabolism(ComputeLedger(), saved)
    assert restored.counters == meta.counters
    assert restored.occupancy['slow'].value == meta.occupancy['slow'].value
    assert restored.occupancy['slow'].updated_at == meta.occupancy['slow'].updated_at
    assert restored.pace['model']['fast'].value == 10.0
    assert Metabolism(ComputeLedger(), {'version': 1, 'counters': {'requests': 7}}).counters['requests'] == 0
