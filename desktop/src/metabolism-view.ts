/** Inspector-only presentation. Unknown observations must never look like zero. */
export interface MetabolismSnapshot {
  measured?: {
    window_seconds?: number | null; occupancy?: number | null; concurrency?: number | null;
    idle_run_seconds?: number | null; occupancy_fast?: number | null; occupancy_slow?: number | null;
    pace_tokens_per_second?: Record<string, { fast?: number | null; slow?: number | null }>;
    pace_fast_tokens_per_second?: number | null; pace_slow_tokens_per_second?: number | null;
  };
  calibration?: {
    occupancy?: boolean; pace?: boolean;
    observation_seconds?: number; requests?: number; pace_samples?: number | Record<string, number>;
    pace_model?: string | null;
    pace_coverage?: number | null;
    requires?: { observation_seconds?: number; observations?: number; pace_coverage?: number };
  };
  model?: { exertion?: number | null; sluggish?: number | null; crowding?: number | null; applied?: boolean; note?: string };
}

const number = (value: unknown, digits = 2, unit = '') =>
  typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)}${unit}` : 'Unknown';
const percent = (value: unknown) => typeof value === 'number' ? number(value * 100, 1, '%') : 'Unknown';
const calibrated = (value: unknown) => value === true ? 'Calibrated' : value === false ? 'Uncalibrated' : 'Unknown';

export function metabolismReadout(data?: MetabolismSnapshot | null) {
  if (!data) return { measured: 'No metabolism sample yet.', calibration: 'No calibration data yet.', model: 'No model output yet.' };
  const m = data.measured ?? {}, c = data.calibration ?? {}, model = data.model ?? {};
  const derived = (value: unknown, ready?: boolean) =>
    value == null && ready === false ? 'Uncalibrated' : number(value);
  const pace = m.pace_tokens_per_second;
  const paceLines = pace ? Object.entries(pace).sort(([a], [b]) => a.localeCompare(b)).flatMap(([model, pair]) => [
    `Pace model: ${model}`,
    `  5-minute half-life: ${number(pair.fast, 2, ' output tokens/eval second')}`,
    `  24-hour half-life: ${number(pair.slow, 2, ' output tokens/eval second')}`,
  ]) : [
    `Pace mean, 5-minute half-life: ${number(m.pace_fast_tokens_per_second, 2, ' output tokens/eval second')}`,
    `Pace mean, 24-hour half-life: ${number(m.pace_slow_tokens_per_second, 2, ' output tokens/eval second')}`,
  ];
  const paceCounts = typeof c.pace_samples === 'object' && c.pace_samples !== null
    ? Object.entries(c.pace_samples).sort(([a], [b]) => a.localeCompare(b)).map(([model, count]) => `Pace observations — ${model}: ${number(count, 0)}`)
    : [`Pace observations: ${number(c.pace_samples, 0)}`];
  return {
    measured: [
      `Sample window: ${number(m.window_seconds, 1, ' real seconds')}`,
      `Occupancy (time with any request in flight): ${percent(m.occupancy)}`,
      `Concurrency (average in-flight requests): ${number(m.concurrency)}`,
      `Idle run at sample (zero in-flight requests): ${number(m.idle_run_seconds, 1, ' real seconds')}`,
      '',
      `Occupancy mean, 5-minute half-life: ${percent(m.occupancy_fast)}`,
      `Occupancy mean, 24-hour half-life: ${percent(m.occupancy_slow)}`,
      ...(paceLines.length ? paceLines : ['Pace: Unknown — no reported eval timing yet.']),
      '',
      'Window measurements include chat and embedding work. Pace uses reported provider generation time.',
      'These are the latest substrate-loop samples, not continuously updated counters.',
    ].join('\n'),
    calibration: [
      `Occupancy baseline: ${calibrated(c.occupancy)}`,
      `Pace baseline: ${calibrated(c.pace)}`,
      `Observed time: ${number(c.observation_seconds, 0, ' real seconds')}`,
      `Request observations: ${number(c.requests, 0)}`,
      `Selected pace baseline: ${c.pace_model ?? 'Unknown'}`,
      ...(paceCounts.length ? paceCounts : ['Pace observations: None yet.']),
      `Pace coverage: ${percent(c.pace_coverage)} (informational)`,
      '',
      `Required observed time: ${number(c.requires?.observation_seconds, 0, ' real seconds')}`,
      `Required observations: ${number(c.requires?.observations, 0)}`,
      ...(c.requires?.pace_coverage == null ? [] : [`Required pace coverage (legacy sample): ${percent(c.requires.pace_coverage)}`]),
    ].join('\n'),
    model: [
      'Derived interpretation — separate from measurements.',
      `Effects applied: ${model.applied === false ? 'No — shadow mode' : model.applied === true ? 'Yes' : 'Unknown'}`,
      `Exertion (relative excess, 0–3): ${derived(model.exertion, c.occupancy)}`,
      `Sluggishness (relative slowdown, 0–1): ${derived(model.sluggish, c.pace)}`,
      ...(c.pace_model ? [`Sluggishness baseline model: ${c.pace_model}`] : []),
      `Crowding (shared memory pressure, 0–1): ${number(model.crowding)}`,
      '',
      'Crowding uses absolute near-capacity thresholds and does not require a personal baseline.',
      ...(model.note ? [model.note] : []),
    ].join('\n'),
  };
}
