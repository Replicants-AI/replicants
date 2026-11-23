"""Offline life-loop simulation: no model, no body, only the loop's own arithmetic.

Two beings with the same genome live 14 body-days with two different people:
one who is at the computer by day, one who works through the night. Wants arise
from a simple pressure model; outcomes come from a stand-in appraisal that follows
the desktop's appraisal guidance (answered outreach relieves social pressure,
ignored outreach barely does and raises tension; inspecting a window settles
curiosity less each time the same thing has just been inspected).

It prints how each being's life diverges. It is a check on the loop's mechanics,
not evidence about a live model: the outcome model here is a simplification.

    python scripts/simulate_life_loop.py [--days 14] [--seed 7]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replicants.desktop.life_loop import ASLEEP, LifeLoop, context  # noqa: E402

STEP = 600  # ten body-minutes
OUTREACH = ['wave', 'approach_cursor', 'say']
EXPLORE = ['inspect_window', 'walk_to', 'look_at']


def present(person: str, hour: float) -> bool:
    if person == 'day':
        return 9 <= hour < 18
    return hour >= 21 or hour < 4  # works through the night


def appraise(want, action, with_person, familiarity, rng):
    if want == 'reach_out':
        if action in OUTREACH and with_person and rng.random() < 0.8:
            return {'social': -rng.uniform(10, 18), 'tension': -2}
        return {'social': -rng.uniform(0, 1.5), 'tension': rng.uniform(1, 3)}
    gain = {'inspect_window': 18, 'walk_to': 9, 'look_at': 2}[action]
    return {'curiosity': -gain * (1 - 0.8 * familiarity) * rng.uniform(.7, 1.1)}


def choose(loop, want, ctx, actions, now, rng):
    """Stand-in for the model: picks the best-looking option, with some noise."""
    rows = loop.expectations.ranked(want, ctx, actions, now)
    noisy = [(r['expected_relief'] + r['uncertainty'] + rng.gauss(0, .05), r['action']) for r in rows]
    return max(noisy)[1]


def live(person: str, days: int, seed: int, chronotype: float = 0.0) -> dict:
    rng = random.Random(seed)
    loop = LifeLoop(chronotype_hours=chronotype)
    social, curiosity, hour, sim = 50.0, 50.0, 8.0, 0.0
    record = {'attempts': {'with_person': 0, 'alone': 0}, 'let_pass': {'with_person': 0, 'alone': 0},
              'sleep_onsets': [], 'wakes': [], 'explore_choice': {}}
    for _ in range(int(days * 86400 / STEP)):
        sim += STEP
        hour = (hour + STEP / 3600) % 24
        here = present(person, hour)
        for e in loop.vigilance.tick(dt_sim=STEP, dt_real=STEP, occupancy=0.02, hour=hour,
                                     person_idle_seconds=10 if here else 3600, now_real=sim, now_sim=sim):
            if e['event'] == 'fell_asleep': record['sleep_onsets'].append(round(hour, 1))
            if e['event'] == 'woke': record['wakes'].append(round(hour, 1)); loop.note_woke(e)
        if loop.vigilance.state == ASLEEP:
            loop.vigilance.episode['real_seconds'] += 60
            loop.sleep_work()
            continue
        social = min(100, social + 1.2)       # social pressure builds while awake
        curiosity = min(100, curiosity + 0.9)
        for want, level, actions in (('reach_out', social, OUTREACH + ['sit']), ('explore', curiosity, EXPLORE)):
            if level < 80:
                continue
            ctx = context(here, hour)
            act, _ = loop.wants_to_act(want, ctx, actions, sim)
            key = 'with_person' if here else 'alone'
            if not act:
                if want == 'reach_out': record['let_pass'][key] += 1
                continue
            action = choose(loop, want, ctx, actions, sim, rng)
            fam = loop.expectations.estimate(want, action, ctx, sim)['familiarity']
            effects = appraise(want, action, here, fam, rng)
            loop.outcome('d', want, 'social' if want == 'reach_out' else 'curiosity', [action], effects, ctx, sim)
            if want == 'reach_out':
                record['attempts'][key] += 1
                social = max(0, social + effects['social'] * 2.5)
            else:
                curiosity = max(0, curiosity + effects['curiosity'] * 2.5)
                record['explore_choice'][action] = record['explore_choice'].get(action, 0) + 1
    record['loop'] = loop
    return record


def summary(name: str, r: dict) -> None:
    loop = r['loop']
    def rate(key):
        tried, passed = r['attempts'][key], r['let_pass'][key]
        return f'{tried} tries / {passed} let pass'
    onsets, wakes = r['sleep_onsets'][-7:], r['wakes'][-7:]
    print(f'\n{name}: {loop.development.stage}, {loop.development.nights} nights, plasticity {loop.development.plasticity:.2f}')
    print(f'  reaching out with the person: {rate("with_person")}')
    print(f'  reaching out alone:           {rate("alone")}')
    print(f'  last week fell asleep at:     {onsets}')
    print(f'  last week woke at:            {wakes}')
    print(f'  explore choices:              {r["explore_choice"]}')
    learned = sorted(((k, v) for k, v in loop.expectations.values.items() if k.startswith('reach_out|wave|') and '*' not in k),
                     key=lambda kv: -kv[1]['q'])
    for key, v in learned:
        print(f'    expects from waving {key.split("|")[2]:<26} {v["q"]:+.2f}  ({v["n"]} lived)')


if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--days', type=int, default=14)
    args.add_argument('--seed', type=int, default=7)
    a = args.parse_args()
    summary('living with a daytime person', live('day', a.days, a.seed))
    summary('living with a night person', live('night', a.days, a.seed))
