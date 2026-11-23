"""Shadow-mode metabolism: measured occupancy and pace, real-time baselines, labeled model.

Specification: reports/species.md §3. Nothing here touches soma, prompts or cadence.
Measurements (occupancy, concurrency, pace, idle run) are kept separate from the
model (exertion, sluggish, crowding), which is computed only for inspection.
"""
from __future__ import annotations

import logging
import math
import time

from replicants.desktop.substrate import measurement

log = logging.getLogger(__name__)

VERSION = 2
FAST_HALF_LIFE = 5 * 60.0
SLOW_HALF_LIFE = 24 * 3600.0
# §3.5 calibration requirements.
MIN_OBSERVATION_SECONDS = 6 * 3600.0
MIN_OBSERVATIONS = 50
OCCUPANCY_FLOOR = 0.02
# Gaps longer than this (process suspended, machine asleep) are not observation time.
MAX_WINDOW_SECONDS = 300.0


class DecayedMean:
    """Time-decayed weighted mean.

    Evidence fades by real wall-clock time since the previous update, and that
    timestamp is persisted, so a restart after a long gap decays exactly as an
    uninterrupted process would.
    """

    def __init__(self, half_life: float, saved: dict | None = None):
        self.half_life = half_life
        saved = saved or {}
        self.value = measurement(saved.get('value'))
        self.weight = measurement(saved.get('weight')) or 0.0
        self.updated_at = measurement(saved.get('updated_at'))

    def add(self, x: float, weight: float, at: float) -> None:
        elapsed = 0.0 if self.updated_at is None else max(0.0, at - self.updated_at)
        prior = self.weight * 0.5 ** (elapsed / self.half_life)
        total = prior + weight
        self.updated_at = at if self.updated_at is None else max(self.updated_at, at)
        if total <= 0:
            return
        self.value = x if self.value is None else (self.value * prior + x * weight) / total
        self.weight = total

    def persisted(self) -> dict:
        return {'value': self.value, 'weight': self.weight, 'updated_at': self.updated_at}


def _pair(saved: dict | None) -> dict[str, DecayedMean]:
    saved = saved or {}
    return {'fast': DecayedMean(FAST_HALF_LIFE, saved.get('fast')),
            'slow': DecayedMean(SLOW_HALF_LIFE, saved.get('slow'))}


class Metabolism:
    def __init__(self, ledger, saved: dict | None = None, *, monotonic=time.monotonic, wall=time.time):
        self.ledger, self.monotonic, self.wall = ledger, monotonic, wall
        saved = saved if isinstance(saved, dict) and saved.get('version') == VERSION else {}
        series = saved.get('series', {})
        self.occupancy = _pair(series.get('occupancy'))
        # Pace is a property of a model on this substrate, so baselines are per model.
        self.pace = {model: _pair(pair) for model, pair in series.get('pace', {}).items()}
        counters = saved.get('counters', {})
        self.counters = {key: counters.get(key, 0) for key in (
            'observation_seconds', 'requests', 'completed_chats', 'pace_samples')}
        self.pace_samples = dict(saved.get('pace_samples', {}))
        self._window_start = self._observing_since = monotonic()
        self._done: list[tuple[float, float]] = []
        self._requests_in_window = 0
        self._last_busy_end: float | None = None
        self.last = {'occupancy': None, 'concurrency': None, 'window_seconds': None, 'idle_run_seconds': None}
        self.hardware: dict = {}
        ledger.listeners.append(self.observe)

    # Observations -------------------------------------------------------
    def observe(self, observation: dict) -> None:
        """Every finished request is work, including failed and cancelled ones (§3.3)."""
        start, end = observation['started'], observation['finished']
        self._done.append((start, end))
        self._requests_in_window += 1
        self._last_busy_end = end if self._last_busy_end is None else max(self._last_busy_end, end)
        if observation['kind'] != 'chat' or observation['status'] != 'completed':
            return
        self.counters['completed_chats'] += 1
        tokens = measurement((observation.get('reported_tokens') or {}).get('completion_tokens'))
        seconds = measurement((observation.get('provider_seconds') or {}).get('eval_duration'))
        if tokens is None or not seconds:
            return  # Unknown pace stays unknown.
        model = str(observation.get('model'))
        at = self.wall()
        for mean in self.pace.setdefault(model, _pair(None)).values():
            mean.add(tokens / seconds, 1.0, at)
        self.counters['pace_samples'] += 1
        self.pace_samples[model] = self.pace_samples.get(model, 0) + 1

    # Sampling -----------------------------------------------------------
    def sample(self, hardware: dict | None = None) -> None:
        now = self.monotonic()
        start, window = self._window_start, now - self._window_start
        self._window_start = now
        self.hardware = hardware or {}
        active = self.ledger.active_starts()
        spans = [(max(a, start), min(b, now)) for a, b in self._done]
        spans += [(max(a, start), now) for a in active]
        self._done.clear()
        requests, self._requests_in_window = self._requests_in_window, 0
        spans = [(a, b) for a, b in spans if b > a]
        # Idle is observed inactivity: zero while anything is in flight, otherwise
        # since the later of the last finished request and the start of observation.
        idle = 0.0 if active else now - max(self._last_busy_end or self._observing_since, self._observing_since)
        if window <= 0:
            return
        busy = _union_length(spans)
        occupancy = min(1.0, busy / window)
        concurrency = sum(b - a for a, b in spans) / window
        self.last = {'occupancy': occupancy, 'concurrency': concurrency,
                     'window_seconds': window, 'idle_run_seconds': idle}
        if window > MAX_WINDOW_SECONDS:
            return  # A suspended process is not evidence of rest or work.
        at = self.wall()
        for mean in self.occupancy.values():
            mean.add(occupancy, window, at)
        self.counters['observation_seconds'] += window
        self.counters['requests'] += requests

    # Calibration and model ---------------------------------------------
    def _pace_model(self) -> str | None:
        """The model with the most pace evidence; sluggishness is never mixed across models."""
        return max(self.pace_samples, key=self.pace_samples.get) if self.pace_samples else None

    def calibration(self) -> dict:
        c = self.counters
        timed = c['observation_seconds'] >= MIN_OBSERVATION_SECONDS
        model = self._pace_model()
        coverage = c['pace_samples'] / c['completed_chats'] if c['completed_chats'] else None
        return {
            'occupancy': timed and c['requests'] >= MIN_OBSERVATIONS,
            'pace': timed and model is not None and self.pace_samples[model] >= MIN_OBSERVATIONS,
            'pace_model': model, 'observation_seconds': c['observation_seconds'], 'requests': c['requests'],
            'pace_samples': dict(self.pace_samples),
            # Reported, not gated: requests whose provider path reports no eval timing
            # (e.g. thinking/streaming transport) cannot contribute pace at all.
            'pace_coverage': coverage,
            'requires': {'observation_seconds': MIN_OBSERVATION_SECONDS, 'observations': MIN_OBSERVATIONS}}

    def model(self) -> dict:
        cal = self.calibration()
        o_fast, o_slow = self.occupancy['fast'].value, self.occupancy['slow'].value
        exertion = (_clamp(o_fast / max(o_slow, OCCUPANCY_FLOOR) - 1, 0, 3)
                    if cal['occupancy'] and o_fast is not None and o_slow is not None else None)
        sluggish = None
        if cal['pace']:
            pair = self.pace[cal['pace_model']]
            p_fast, p_slow = pair['fast'].value, pair['slow'].value
            if p_fast is not None and p_slow:
                sluggish = _clamp(1 - p_fast / p_slow, 0, 1)
        return {'exertion': exertion, 'sluggish': sluggish, 'crowding': crowding(self.hardware),
                'applied': False,
                'note': 'Model, not measurement (species.md §3.5). Shadow mode: computed for inspection only; '
                        'nothing reaches soma, prompts or wake cadence.'}

    def snapshot(self) -> dict:
        return {'measured': {**self.last,
                    'occupancy_fast': self.occupancy['fast'].value, 'occupancy_slow': self.occupancy['slow'].value,
                    'pace_tokens_per_second': {model: {'fast': pair['fast'].value, 'slow': pair['slow'].value}
                                               for model, pair in self.pace.items()}},
                'calibration': self.calibration(), 'model': self.model()}

    def persisted(self) -> dict:
        return {'version': VERSION, 'counters': dict(self.counters), 'pace_samples': dict(self.pace_samples),
                'series': {'occupancy': {k: v.persisted() for k, v in self.occupancy.items()},
                           'pace': {model: {k: v.persisted() for k, v in pair.items()}
                                    for model, pair in self.pace.items()}}}


def crowding(hardware: dict) -> float | None:
    """Environmental scarcity near physical capacity (§3.5 documented exception)."""
    terms = []
    memory = hardware.get('memory') or {}
    if memory.get('status') == 'available' and measurement(memory.get('used_percent')) is not None:
        terms.append(memory['used_percent'] / 100 - 0.90)
    gpu = hardware.get('gpu') or {}
    if gpu.get('status') == 'available':
        for device in gpu.get('devices', []):
            used, total = device.get('memory_used_bytes'), device.get('memory_total_bytes')
            if used is not None and total:
                terms.append(used / total - 0.95)
    if not terms:
        return None
    return _clamp(max(terms) / 0.10, 0, 1)


def _union_length(spans: list[tuple[float, float]]) -> float:
    total, end = 0.0, -math.inf
    for a, b in sorted(spans):
        if b <= end:
            continue
        total += b - max(a, end)
        end = b
    return total


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
