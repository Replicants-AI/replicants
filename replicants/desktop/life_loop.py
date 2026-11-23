"""The life loop: how a replicant lives across a moment, a day and a life.

Specification: reports/life-loop.md. Everything here is pure state and arithmetic,
with no I/O and no model calls, so any model can sit behind it and every number
can be inspected. Three mechanisms, each from established prior art:

- Vigilance: Borbély's two-process model. Sleep pressure (S) builds with time awake
  and with measured work, and discharges in sleep. A circadian signal (C), shifted by
  an inborn chronotype, moves the thresholds for falling asleep and waking.
- Wanting learns: Rescorla-Wagner expected relief per (want, action, context),
  learned only from appraised outcomes. Daytime experience counts half until it is
  slept on; sleep replays the day into long-term expectation (complementary
  learning systems). Familiarity rises with repetition and fades with time.
- Development: plasticity falls with the number of nights lived, so early life
  shapes a being more than later life does.
"""
from __future__ import annotations

from copy import deepcopy
import math

VERSION = 1
AWAKE, DROWSY, ASLEEP = 'awake', 'drowsy', 'asleep'

DEFAULTS = {
    # Process S. Awake build-up runs in body (simulated) time; work runs in real time.
    'tau_awake_hours': 11.5,      # S reaches ~0.75 after 16 body-hours awake.
    'tau_sleep_hours': 5.8,       # S falls from ~0.8 to ~0.2 in 8 body-hours of sleep.
    'work_gain': 1.0,             # Extra build-up at full measured occupancy.
    'tau_work_hours': 2.0,        # Real hours of continuous thinking to add ~63 % of the gap.
    # Process C thresholds: C is +1 at the circadian peak, -1 at the trough.
    'sleep_threshold': 0.75, 'drowsy_threshold': 0.58, 'wake_threshold': 0.22, 'circadian_amplitude': 0.15,
    'circadian_peak_hour': 15.0,
    'quiet_seconds': 30.0,        # Real seconds of human inactivity before sleep can begin.
    'arousal_base': 0.3, 'arousal_depth': 0.5,
    'wake_hold_seconds': 60.0,    # A human "wake" keeps the being up at least this long.
    # Entrainment: the being's day drifts toward the hours its person is actually present.
    'presence_seconds': 120.0,    # Human input within this many real seconds counts as present.
    'tau_entrain_days': 4.0,      # Memory of when the person tends to be around.
    'entrain_rate_hours_per_day': 1.5,  # Most a circadian phase can move per body-day.
    'entrain_min_hours': 6.0,     # Observed body-hours of presence for full evidence weight.
    # Wanting.
    'reward_scale': 25.0,         # Bar points of relief that count as a full reward.
    'tension_cost': 0.5,          # Weight of tension raised by an outcome.
    'day_weight': 0.5,            # Unslept experience counts this much.
    'prior_strength': 3.0,        # Shrinkage of a specific context toward the general estimate.
    'exploration': 0.2,           # Optimism for untried or rarely tried actions.
    'act_threshold': 0.08,        # Below this expected value, the being lets an urge pass.
    'familiarity_gain': 0.25, 'tau_familiarity_hours': 6.0,
    # Development.
    'plasticity_newborn': 0.5, 'plasticity_adult': 0.1, 'plasticity_tau_nights': 10.0,
    'juvenile_after_nights': 3, 'adult_after_nights': 21,
    'buffer_limit': 500,
}

WANT_DRIVE = {'reach_out': 'social', 'explore': 'curiosity', 'create': 'creative', 'resolve_tension': 'tension'}


def daypart(hour: float) -> str:
    if hour < 6 or hour >= 22: return 'night'
    if hour < 12: return 'morning'
    if hour < 17: return 'afternoon'
    return 'evening'


def context(person_present: bool, hour: float) -> str:
    return ('with_person' if person_present else 'alone') + '/' + daypart(hour)


def _wrap(hours: float) -> float:
    """Signed circular difference in hours, in [-12, 12)."""
    return (hours + 12) % 24 - 12


def reward(drive: str, effects: dict, *, scale: float = 25.0, tension_cost: float = 0.5) -> float:
    """Relief of the want's own drive, minus tension the outcome raised. Range [-1, 1]."""
    relief = -float(effects.get(drive, 0.0))
    cost = 0.0 if drive == 'tension' else tension_cost * max(0.0, float(effects.get('tension', 0.0)))
    return max(-1.0, min(1.0, (relief - cost) / scale))


class Vigilance:
    def __init__(self, params: dict, saved: dict | None = None, *, chronotype_hours: float = 0.0):
        self.p, saved = params, saved or {}
        self.chronotype = float(chronotype_hours)
        self.S = float(saved.get('S', 0.3))
        self.state = saved.get('state', AWAKE)
        self.forced = saved.get('forced')          # 'self' or 'person' when sleep was requested
        self.hold_until = 0.0                      # real monotonic; not persisted
        self.episode = saved.get('episode')        # current sleep episode, if asleep
        # Entrainment state: a decaying record of when the person is present, and the
        # phase shift it has produced so far.
        self.presence = dict(saved.get('presence') or {'x': 0.0, 'y': 0.0, 'hours': 0.0})
        self.phase_shift = float(saved.get('phase_shift', 0.0))

    @property
    def inborn_peak(self) -> float:
        return (self.p['circadian_peak_hour'] + self.chronotype) % 24

    @property
    def peak(self) -> float:
        return (self.inborn_peak + self.phase_shift) % 24

    def circadian(self, hour: float) -> float:
        return math.cos((hour - self.peak) * 2 * math.pi / 24)

    def person_rhythm(self) -> dict:
        """Circular mean of the hours the person has been present, and how consistent they are."""
        x, y, hours = self.presence['x'], self.presence['y'], self.presence['hours']
        if hours <= 0:
            return {'center_hour': None, 'consistency': 0.0, 'hours_observed': 0.0}
        center = (math.atan2(y, x) * 24 / (2 * math.pi)) % 24
        return {'center_hour': center, 'consistency': min(1.0, math.hypot(x, y) / hours), 'hours_observed': hours}

    def _entrain(self, dt_sim: float, hour: float, present: bool) -> None:
        if dt_sim <= 0:
            return
        decay = math.exp(-dt_sim / (self.p['tau_entrain_days'] * 86400))
        for key in ('x', 'y', 'hours'):
            self.presence[key] *= decay
        if present:
            angle = hour * 2 * math.pi / 24
            h = dt_sim / 3600
            self.presence['x'] += h * math.cos(angle)
            self.presence['y'] += h * math.sin(angle)
            self.presence['hours'] += h
        rhythm = self.person_rhythm()
        if rhythm['center_hour'] is None:
            return
        evidence = min(1.0, rhythm['hours_observed'] / self.p['entrain_min_hours'])
        target = _wrap(rhythm['center_hour'] - self.inborn_peak) * rhythm['consistency'] * evidence
        step = self.p['entrain_rate_hours_per_day'] * dt_sim / 86400
        gap = _wrap(target - self.phase_shift)
        self.phase_shift = _wrap(self.phase_shift + max(-step, min(step, gap)))

    def thresholds(self, hour: float) -> dict:
        a = self.p['circadian_amplitude'] * self.circadian(hour)
        # By day it is harder to fall asleep and easier to wake; by night the reverse.
        return {'sleep': self.p['sleep_threshold'] + a, 'drowsy': self.p['drowsy_threshold'] + a,
                'wake': self.p['wake_threshold'] + a}

    def arousal_needed(self) -> float:
        return self.p['arousal_base'] + self.p['arousal_depth'] * self.S

    def tick(self, *, dt_sim: float, dt_real: float, occupancy: float | None, hour: float,
             person_idle_seconds: float, now_real: float, now_sim: float) -> list[dict]:
        events = []
        self._entrain(dt_sim, hour, person_idle_seconds < self.p['presence_seconds'])
        if self.state == ASLEEP:
            self.S *= math.exp(-max(0.0, dt_sim) / (self.p['tau_sleep_hours'] * 3600))
            self.episode['sim_seconds'] += max(0.0, dt_sim)
            self.episode['real_seconds'] += max(0.0, dt_real)
            if self.S <= self.thresholds(hour)['wake'] and self.forced != 'person':
                events.append(self._wake('rested', now_real, now_sim, hour))
        else:
            rate = max(0.0, dt_sim) / (self.p['tau_awake_hours'] * 3600)
            if occupancy is not None:  # Unknown work adds nothing.
                rate += self.p['work_gain'] * occupancy * max(0.0, dt_real) / (self.p['tau_work_hours'] * 3600)
            self.S += (1 - self.S) * (1 - math.exp(-rate))
            t = self.thresholds(hour)
            held = now_real < self.hold_until
            if not held and self.S >= t['sleep'] and person_idle_seconds >= self.p['quiet_seconds']:
                events.append(self._sleep('pressure', now_real, now_sim, hour))
            else:
                state = DROWSY if self.S >= t['drowsy'] else AWAKE
                if state != self.state:
                    self.state = state
                    events.append({'event': state, 'S': self.S})
        return events

    def request_sleep(self, by: str, now_real: float, now_sim: float, hour: float) -> dict | None:
        if self.state == ASLEEP:
            # The person's tray request owns even an already sleeping body.
            # A later creature choice cannot release that ownership.
            if by == 'person':
                self.forced = by
            return None
        self.forced = by
        return self._sleep('requested_by_' + by, now_real, now_sim, hour)

    def arouse(self, strength: float, cause: str, now_real: float, now_sim: float, hour: float) -> dict | None:
        """A stimulus wakes a sleeper only if it is strong enough for this depth of sleep."""
        if self.state != ASLEEP or self.forced == 'person' or strength < self.arousal_needed():
            return None
        return self._wake('aroused_by_' + cause, now_real, now_sim, hour)

    def wake_by_person(self, now_real: float, now_sim: float, hour: float, hold_real_seconds: float) -> dict | None:
        self.hold_until = now_real + hold_real_seconds
        self.forced = None
        return self._wake('woken_by_person', now_real, now_sim, hour) if self.state == ASLEEP else None

    def _sleep(self, cause, now_real, now_sim, hour):
        self.state = ASLEEP
        self.episode = {'cause': cause, 'started_sim': now_sim, 'S_at_onset': self.S, 'hour_at_onset': hour,
                        'sim_seconds': 0.0, 'real_seconds': 0.0, 'work_done': False, 'learned': []}
        return {'event': 'fell_asleep', 'cause': cause, 'S': self.S}

    def _wake(self, cause, now_real, now_sim, hour):
        episode = {**(self.episode or {}), 'woke_by': cause, 'S_at_waking': self.S, 'hour_at_waking': hour}
        self.state, self.episode, self.forced = AWAKE, None, None
        return {'event': 'woke', 'cause': cause, 'S': self.S, 'episode': episode}

    def persisted(self) -> dict:
        return {'S': self.S, 'state': self.state, 'forced': self.forced, 'episode': deepcopy(self.episode),
                'presence': dict(self.presence), 'phase_shift': self.phase_shift}


class Expectations:
    """What the being has learned to expect from acting on each kind of want."""

    def __init__(self, params: dict, saved: dict | None = None):
        self.p, saved = params, saved or {}
        self.values: dict[str, dict] = deepcopy(saved.get('values', {}))
        self.buffer: list[dict] = deepcopy(saved.get('buffer', []))
        self.familiarity: dict[str, dict] = deepcopy(saved.get('familiarity', {}))

    @staticmethod
    def _keys(want, action, ctx):
        """Situation, then presence (any time of day), then any situation."""
        return f'{want}|{action}|{ctx}', f'{want}|{action}|{ctx.split("/")[0]}/*', f'{want}|{action}|*'

    def _familiarity(self, action: str, now_sim: float) -> float:
        f = self.familiarity.get(action)
        if not f: return 0.0
        return f['f'] * math.exp(-max(0.0, now_sim - f['at']) / (self.p['tau_familiarity_hours'] * 3600))

    def _long_term(self, want, action, ctx) -> tuple[float, float]:
        empty = {'q': 0.0, 'n': 0}
        s, p, g = (self.values.get(k, empty) for k in self._keys(want, action, ctx))
        m = self.p['prior_strength']
        # Expectation borrows down the hierarchy. Certainty borrows only across times of
        # day within the same presence: being alone at noon teaches about being alone at
        # dusk, but nothing about being with the person, which stays new until lived.
        # A negative outcome in another presence must not veto trying this one.
        # Positive experience can encourage exploration; negative experience is
        # borrowed only within the same presence through p and s.
        global_prior = max(0.0, g['q'])
        q_presence = (p['n'] * p['q'] + m * global_prior) / (p['n'] + m)
        q = (s['n'] * s['q'] + m * q_presence) / (s['n'] + m)
        return q, s['n'] + 0.5 * max(0, p['n'] - s['n'])

    def estimate(self, want, action, ctx, now_sim: float) -> dict:
        q, n = self._long_term(want, action, ctx)
        day = [o['r'] for o in self.buffer if o['want'] == want and action in o['actions'] and o['ctx'] == ctx]
        if day:
            q += self.p['day_weight'] * (sum(day) / len(day) - q) * min(1.0, len(day) / 3)
        uncertainty = self.p['exploration'] / math.sqrt(n + len(day) * self.p['day_weight'] + 1)
        return {'action': action, 'expected_relief': round(q, 4), 'uncertainty': round(uncertainty, 4),
                'lived_times': int(n) + len(day), 'unslept_times': len(day),
                'familiarity': round(self._familiarity(action, now_sim), 4)}

    def ranked(self, want, ctx, actions, now_sim: float) -> list[dict]:
        rows = [self.estimate(want, a, ctx, now_sim) for a in actions]
        return sorted(rows, key=lambda r: r['expected_relief'] + r['uncertainty'], reverse=True)

    def value_of_acting(self, want, ctx, actions, now_sim: float) -> float:
        rows = self.ranked(want, ctx, actions, now_sim)
        return rows[0]['expected_relief'] + rows[0]['uncertainty'] if rows else 0.0

    def record(self, want: str, actions: list[str], ctx: str, r: float, now_sim: float) -> None:
        self.buffer.append({'want': want, 'actions': sorted(set(actions)), 'ctx': ctx, 'r': r, 'at': now_sim})
        self.buffer = self.buffer[-self.p['buffer_limit']:]
        for action in set(actions):
            f = self._familiarity(action, now_sim)
            self.familiarity[action] = {'f': f + (1 - f) * self.p['familiarity_gain'], 'at': now_sim}

    def replay(self, alpha: float) -> list[dict]:
        """Sleep: integrate the day's outcomes into long-term expectation, then clear them."""
        before = {k: dict(v) for k, v in self.values.items()}
        for outcome in self.buffer:
            for action in outcome['actions']:
                for key in self._keys(outcome['want'], action, outcome['ctx']):
                    v = self.values.setdefault(key, {'q': 0.0, 'n': 0})
                    v['q'] += alpha * (outcome['r'] - v['q'])
                    v['n'] += 1
        replayed, self.buffer = len(self.buffer), []
        changes = []
        for key, v in self.values.items():
            old = before.get(key, {'q': 0.0, 'n': 0})
            if v['n'] != old['n']:
                want, action, ctx = key.split('|')
                changes.append({'want': want, 'action': action, 'context': ctx, 'before': round(old['q'], 4),
                                'after': round(v['q'], 4), 'lived_times': v['n']})
        changes.sort(key=lambda c: abs(c['after'] - c['before']), reverse=True)
        return [{'replayed_outcomes': replayed}] + changes if replayed else []

    def persisted(self) -> dict:
        return {'values': deepcopy(self.values), 'buffer': deepcopy(self.buffer), 'familiarity': deepcopy(self.familiarity)}


class Development:
    def __init__(self, params: dict, saved: dict | None = None):
        self.p, saved = params, saved or {}
        self.nights = int(saved.get('nights', 0))
        self.lived_real_seconds = float(saved.get('lived_real_seconds', 0.0))

    @property
    def stage(self) -> str:
        if self.nights >= self.p['adult_after_nights']: return 'adult'
        if self.nights >= self.p['juvenile_after_nights']: return 'juvenile'
        return 'newborn'

    @property
    def plasticity(self) -> float:
        lo, hi = self.p['plasticity_adult'], self.p['plasticity_newborn']
        return lo + (hi - lo) * math.exp(-self.nights / self.p['plasticity_tau_nights'])

    def persisted(self) -> dict:
        return {'nights': self.nights, 'lived_real_seconds': self.lived_real_seconds}


class LifeLoop:
    def __init__(self, saved: dict | None = None, *, params: dict | None = None, chronotype_hours: float = 0.0):
        saved = saved if isinstance(saved, dict) and saved.get('version') == VERSION else {}
        self.p = {**DEFAULTS, **(params or {})}
        self.vigilance = Vigilance(self.p, saved.get('vigilance'), chronotype_hours=chronotype_hours)
        self.expectations = Expectations(self.p, saved.get('expectations'))
        self.development = Development(self.p, saved.get('development'))
        self.last_sleep: dict | None = deepcopy(saved.get('last_sleep'))
        self.started: dict[str, dict] = deepcopy(saved.get('started', {}))

    # Moment ------------------------------------------------------------
    def wants_to_act(self, want: str, ctx: str, actions: list[str], now_sim: float) -> tuple[bool, float]:
        """An urge becomes an attempt only if acting on it is expected to help.

        Untried actions carry optimism, so a being always explores before it gives up.
        Drowsiness damps every urge.
        """
        value = self.expectations.value_of_acting(want, ctx, actions, now_sim)
        if self.vigilance.state == DROWSY:
            value *= max(0.0, 1 - self.vigilance.S)
        return value > self.p['act_threshold'], value

    def begin(self, desire_id: str, want: str, ctx: str) -> None:
        self.started[desire_id] = {'want': want, 'ctx': ctx}
        if len(self.started) > 200:
            self.started.pop(next(iter(self.started)))

    def outcome(self, desire_id: str, want: str, drive: str, actions: list[str], effects: dict,
                ctx: str, now_sim: float) -> float | None:
        started = self.started.pop(desire_id, None) or {'want': want, 'ctx': ctx}
        if not actions:
            return None
        r = reward(drive, effects, scale=self.p['reward_scale'], tension_cost=self.p['tension_cost'])
        self.expectations.record(started['want'], actions, started['ctx'], r, now_sim)
        return r

    # Day ---------------------------------------------------------------
    def sleep_work(self) -> list[dict]:
        """Once per sleep: replay the day with this age's plasticity."""
        episode = self.vigilance.episode
        if episode is None or episode['work_done']:
            return []
        plasticity = self.development.plasticity
        learned = self.expectations.replay(plasticity)
        stage_before = self.development.stage
        self.development.nights += 1
        episode.update(work_done=True, learned=learned, plasticity=plasticity,
                       stage_before=stage_before, stage_after=self.development.stage)
        return learned

    def note_woke(self, event: dict) -> None:
        self.last_sleep = event.get('episode')

    # Inspection ----------------------------------------------------------
    def snapshot(self, *, hour: float, now_sim: float, want_actions: list[str] | None = None) -> dict:
        v = self.vigilance
        return {
            'vigilance': {'state': v.state, 'sleep_pressure': round(v.S, 4), 'circadian': round(v.circadian(hour), 4),
                          'chronotype_hours': v.chronotype, 'inborn_peak_hour': round(v.inborn_peak, 2),
                          'entrained_peak_hour': round(v.peak, 2), 'phase_shift_hours': round(v.phase_shift, 2),
                          'person_rhythm': {k: (round(x, 2) if isinstance(x, float) else x)
                                            for k, x in v.person_rhythm().items()},
                          'thresholds': {k: round(x, 4) for k, x in v.thresholds(hour).items()},
                          'arousal_needed': round(v.arousal_needed(), 4), 'sleep_requested_by': v.forced},
            'development': {'stage': self.development.stage, 'nights': self.development.nights,
                            'plasticity': round(self.development.plasticity, 4)},
            'expectations': self.expectations.persisted()['values'],
            'unslept_outcomes': len(self.expectations.buffer),
            'familiarity': {a: round(self.expectations._familiarity(a, now_sim), 4) for a in self.expectations.familiarity},
            'last_sleep': deepcopy(self.last_sleep),
            'note': 'Sleep pressure and expectations are model state (reports/life-loop.md). '
                    'Expectations are learned only from appraised outcomes of completed actions.'}

    def persisted(self) -> dict:
        return {'version': VERSION, 'vigilance': self.vigilance.persisted(),
                'expectations': self.expectations.persisted(), 'development': self.development.persisted(),
                'last_sleep': deepcopy(self.last_sleep), 'started': deepcopy(self.started)}
