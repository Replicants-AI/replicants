import { test } from 'node:test';
import assert from 'node:assert/strict';
import { metabolismReadout } from '../src/metabolism-view.ts';

test('unknown metabolism measurements stay distinct from observed zero', () => {
  const view = metabolismReadout({ measured: { occupancy: 0, concurrency: 0, idle_run_seconds: null,
    pace_fast_tokens_per_second: null, window_seconds: 10 }, calibration: { occupancy: false, pace: false },
    model: { exertion: null, sluggish: null, crowding: 0, applied: false } });
  assert.match(view.measured, /Occupancy.*: 0\.0%/);
  assert.match(view.measured, /Idle run.*: Unknown/);
  assert.match(view.measured, /Pace mean, 5-minute half-life: Unknown/);
  assert.match(view.model, /Exertion.*: Uncalibrated/);
  assert.match(view.model, /Crowding.*: 0\.00/);
  assert.match(view.model, /Effects applied: No — shadow mode/);
  assert.doesNotMatch(view.measured, /Exertion|Sluggishness/);
});

test('inspector retains units, fractional concurrency and separate calibration coverage', () => {
  const view = metabolismReadout({ measured: { occupancy: .25, concurrency: 1.5,
    pace_fast_tokens_per_second: 23.456, idle_run_seconds: 4.2 },
    calibration: { occupancy: true, pace: false, pace_coverage: .75, observation_seconds: 21600 },
    model: { exertion: 1.5, sluggish: null, crowding: .4, applied: false } });
  assert.match(view.measured, /25\.0%/);
  assert.match(view.measured, /Concurrency.*: 1\.50/);
  assert.match(view.measured, /23\.46 output tokens\/eval second/);
  assert.match(view.measured, /4\.2 real seconds/);
  assert.match(view.calibration, /Pace coverage: 75\.0%/);
  assert.match(view.calibration, /Pace baseline: Uncalibrated/);
  assert.match(view.model, /Exertion.*: 1\.50/);
});

test('older inspector payloads do not imply calibrated or applied metabolism', () => {
  const view = metabolismReadout();
  assert.match(view.measured, /No metabolism sample/);
  assert.match(view.model, /No model output/);
  assert.match(metabolismReadout({ model: { applied: true } }).model, /Effects applied: Yes/);
});

test('per-model pace stays separate and coverage is informative rather than a gate', () => {
  const view = metabolismReadout({ measured: { pace_tokens_per_second: {
    large: { fast: 20, slow: 25 }, small: { fast: 200, slow: 220 },
  } }, calibration: { pace: true, pace_model: 'large', pace_samples: { large: 60, small: 5 },
    pace_coverage: .55, requires: { observation_seconds: 21600, observations: 50 } },
    model: { sluggish: .2, applied: false } });
  assert.match(view.measured, /Pace model: large\n  5-minute half-life: 20\.00/);
  assert.match(view.measured, /Pace model: small\n  5-minute half-life: 200\.00/);
  assert.match(view.calibration, /Pace observations — large: 60/);
  assert.match(view.calibration, /Pace coverage: 55\.0% \(informational\)/);
  assert.doesNotMatch(view.calibration, /Required pace coverage/);
  assert.match(view.model, /Sluggishness baseline model: large/);
  const empty = metabolismReadout({ measured: { pace_tokens_per_second: {} }, calibration: { pace_samples: {} } });
  assert.match(empty.measured, /Pace: Unknown/);
  assert.match(empty.calibration, /Pace observations: None yet/);
});
