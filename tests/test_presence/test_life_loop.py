import math

import pytest

from replicants.desktop.life_loop import (ASLEEP, AWAKE, DROWSY, DEFAULTS, LifeLoop,
                                          context, daypart, reward)

HOUR = 3600.0
ACTIONS = ['wave', 'approach_cursor', 'inspect_window', 'sit']


def tick(loop, *, hours, hour, step=600, occupancy=0.0, idle=3600, sim_start=0.0, real_start=0.0):
    """Advance body time; real time advances 1:1. Returns events and the final clock."""
    events, sim, real = [], sim_start, real_start
    for _ in range(int(hours * 3600 / step)):
        sim += step; real += step; hour = (hour + step / 3600) % 24
        events += loop.vigilance.tick(dt_sim=step, dt_real=step, occupancy=occupancy, hour=hour,
                                      person_idle_seconds=idle, now_real=real, now_sim=sim)
    return events, hour, sim, real


# Vigilance --------------------------------------------------------------------

def test_pressure_builds_awake_and_work_adds_to_it():
    rested, busy = LifeLoop(), LifeLoop()
    tick(rested, hours=4, hour=8)
    tick(busy, hours=4, hour=8, occupancy=1.0)
    assert 0.3 < rested.vigilance.S < busy.vigilance.S


def test_unknown_work_adds_nothing():
    a, b = LifeLoop(), LifeLoop()
    tick(a, hours=2, hour=9, occupancy=None)
    tick(b, hours=2, hour=9, occupancy=0.0)
    assert a.vigilance.S == pytest.approx(b.vigilance.S)


def test_falls_asleep_only_when_tired_and_quiet_then_wakes_rested():
    loop = LifeLoop()
    events, hour, sim, real = tick(loop, hours=18, hour=7, idle=0)  # person active all day
    assert loop.vigilance.state != ASLEEP
    events, hour, sim, real = tick(loop, hours=1, hour=hour, idle=3600, sim_start=sim, real_start=real)
    assert loop.vigilance.state == ASLEEP
    assert [e['event'] for e in events][-1] == 'fell_asleep'
    events, hour, *_ = tick(loop, hours=12, hour=hour, sim_start=sim, real_start=real)
    woke = [e for e in events if e['event'] == 'woke']
    assert woke and woke[0]['cause'] == 'rested'
    assert woke[0]['episode']['sim_seconds'] > 4 * HOUR


def test_drowsiness_precedes_sleep():
    loop = LifeLoop()
    events, *_ = tick(loop, hours=18, hour=7, idle=0)
    assert DROWSY in [e['event'] for e in events]


def test_chronotype_shifts_when_sleep_comes():
    lark, owl = LifeLoop(chronotype_hours=-3), LifeLoop(chronotype_hours=3)
    def onset(loop):
        sim = real = 0.0; hour = 7.0
        for i in range(24 * 6):
            sim += 600; real += 600; hour = (hour + 600 / 3600) % 24
            for e in loop.vigilance.tick(dt_sim=600, dt_real=600, occupancy=0, hour=hour,
                                         person_idle_seconds=3600, now_real=real, now_sim=sim):
                if e['event'] == 'fell_asleep': return i
    assert onset(lark) < onset(owl)


def test_deep_sleep_needs_a_stronger_stimulus_and_early_waking_leaves_pressure():
    loop = LifeLoop()
    loop.vigilance.S = 0.9
    assert loop.vigilance.request_sleep('self', 0, 0, 23)
    assert loop.vigilance.arouse(0.6, 'poke', 1, 1, 23) is None      # needs 0.3 + 0.5 * 0.9 = 0.75
    woke = loop.vigilance.arouse(0.8, 'chat', 2, 2, 23)
    assert woke['cause'] == 'aroused_by_chat'
    assert loop.vigilance.S == pytest.approx(0.9)                    # sleep inertia: still tired


def test_person_authority_over_sleep():
    loop = LifeLoop()
    loop.vigilance.request_sleep('person', 0, 0, 14)
    loop.vigilance.S = 0.0
    tick(loop, hours=1, hour=14)
    assert loop.vigilance.state == ASLEEP                            # only the person ends a requested sleep
    assert loop.vigilance.arouse(1.0, 'poke', 1, 1, 14) is None
    assert loop.vigilance.wake_by_person(5, 5, 14, 60)['cause'] == 'woken_by_person'
    loop.vigilance.S = 0.99
    events, *_ = tick(loop, hours=0, hour=14)
    assert loop.vigilance.tick(dt_sim=10, dt_real=10, occupancy=0, hour=2, person_idle_seconds=999,
                               now_real=30, now_sim=30) == [{'event': DROWSY, 'S': loop.vigilance.S}]


def test_person_can_take_ownership_of_an_existing_sleep_without_restarting_it():
    loop = LifeLoop()
    v = loop.vigilance
    v.request_sleep('self', 0, 0, 23)
    episode = v.episode
    assert v.request_sleep('person', 10, 10, 23) is None
    assert v.episode is episode and v.forced == 'person'
    v.request_sleep('self', 11, 11, 23)
    assert v.forced == 'person'
    assert v.arouse(1.0, 'chat', 12, 12, 23) is None


def test_replay_records_the_used_plasticity_and_every_changed_estimate():
    loop = LifeLoop()
    for ctx in ('alone/morning', 'alone/evening'):
        loop.outcome('d', 'explore', 'curiosity', ACTIONS, {'curiosity': -25}, ctx, 0)
    loop.vigilance.request_sleep('self', 0, 0, 23)
    plasticity = loop.development.plasticity
    learned = loop.sleep_work()
    episode = loop.vigilance.episode
    assert episode['plasticity'] == plasticity
    assert loop.development.plasticity < plasticity
    assert episode['learned'] == learned and len(learned) > 12
    assert {'*', 'alone/*'} <= {row['context'] for row in learned if 'context' in row}


# Wanting ---------------------------------------------------------------------

def test_reward_is_relief_of_the_wants_own_drive_minus_raised_tension():
    assert reward('social', {'social': -12.5}) == pytest.approx(0.5)
    assert reward('social', {'social': -12.5, 'tension': 10}) == pytest.approx(0.3)
    assert reward('tension', {'tension': -25}) == 1.0
    assert reward('social', {'social': 100}) == -1.0


def test_untried_actions_carry_optimism_so_a_newborn_always_explores():
    loop = LifeLoop()
    act, value = loop.wants_to_act('reach_out', 'alone/morning', ACTIONS, 0)
    assert act and value == pytest.approx(DEFAULTS['exploration'])


def test_daytime_experience_counts_half_until_slept_on():
    loop = LifeLoop()
    for _ in range(3):
        loop.outcome('d', 'explore', 'curiosity', ['inspect_window'], {'curiosity': -20}, 'alone/morning', 0)
    awake = loop.expectations.estimate('explore', 'inspect_window', 'alone/morning', 0)['expected_relief']
    assert awake == pytest.approx(0.4)                              # half of 0.8
    loop.vigilance.request_sleep('self', 0, 0, 23)
    learned = loop.sleep_work()
    assert learned[0] == {'replayed_outcomes': 3}
    slept = loop.expectations.estimate('explore', 'inspect_window', 'alone/morning', 0)['expected_relief']
    assert slept > awake
    assert loop.development.nights == 1
    assert loop.sleep_work() == []                                  # once per sleep


def test_learns_when_reaching_out_helps_and_stops_trying_when_it_does_not():
    """The emergent timing behavior: reach out when the person is around, not when alone."""
    loop = LifeLoop()
    for night in range(5):
        for _ in range(6):
            loop.outcome('d', 'reach_out', 'social', ['wave'], {'social': -0.5, 'tension': 2}, 'alone/afternoon', 0)
            loop.outcome('d', 'reach_out', 'social', ['wave'], {'social': -15, 'comfort': 4}, 'with_person/afternoon', 0)
        loop.vigilance.request_sleep('self', 0, 0, 23); loop.sleep_work(); loop.vigilance.state = AWAKE
    alone, v_alone = loop.wants_to_act('reach_out', 'alone/afternoon', ['wave'], 0)
    together, v_together = loop.wants_to_act('reach_out', 'with_person/afternoon', ['wave'], 0)
    assert not alone and together
    assert v_together > 0.4 > v_alone


def test_general_experience_informs_an_unvisited_context():
    loop = LifeLoop()
    for _ in range(8):
        loop.outcome('d', 'explore', 'curiosity', ['inspect_window'], {'curiosity': -25}, 'alone/morning', 0)
    loop.vigilance.request_sleep('self', 0, 0, 23); loop.sleep_work()
    unseen = loop.expectations.estimate('explore', 'inspect_window', 'alone/evening', 0)
    assert 0.2 < unseen['expected_relief'] < 1.0


def test_familiarity_rises_with_repetition_and_fades_with_time():
    loop = LifeLoop()
    for _ in range(4):
        loop.outcome('d', 'explore', 'curiosity', ['look_at'], {'curiosity': -1}, 'alone/morning', 0)
    fresh = loop.expectations.estimate('explore', 'look_at', 'alone/morning', 0)['familiarity']
    later = loop.expectations.estimate('explore', 'look_at', 'alone/morning', 12 * HOUR)['familiarity']
    assert fresh > 0.6 and later < fresh * math.exp(-1.9)


def test_quiet_turns_are_not_learned_as_outcomes():
    loop = LifeLoop()
    assert loop.outcome('d', 'reach_out', 'social', [], {'social': -10}, 'alone/night', 0) is None
    assert loop.expectations.buffer == []


def test_drowsiness_damps_urges():
    loop = LifeLoop()
    _, awake = loop.wants_to_act('explore', 'alone/night', ACTIONS, 0)
    loop.vigilance.state, loop.vigilance.S = DROWSY, 0.9
    _, drowsy = loop.wants_to_act('explore', 'alone/night', ACTIONS, 0)
    assert drowsy == pytest.approx(awake * 0.1)


# Development -----------------------------------------------------------------

def test_plasticity_falls_with_nights_and_stages_follow():
    loop = LifeLoop()
    assert loop.development.stage == 'newborn' and loop.development.plasticity == 0.5
    loop.development.nights = 3
    assert loop.development.stage == 'juvenile'
    loop.development.nights = 21
    assert loop.development.stage == 'adult' and loop.development.plasticity < 0.16


def test_early_life_shapes_more_than_late_life():
    young, old = LifeLoop(), LifeLoop()
    old.development.nights = 60
    for loop in (young, old):
        loop.outcome('d', 'explore', 'curiosity', ['inspect_window'], {'curiosity': -25}, 'alone/morning', 0)
        loop.vigilance.request_sleep('self', 0, 0, 23); loop.sleep_work()
    q = lambda loop: loop.expectations.values['explore|inspect_window|alone/morning']['q']
    assert q(young) > 3 * q(old)


# Persistence -----------------------------------------------------------------

def test_round_trip_and_unknown_versions_start_fresh():
    loop = LifeLoop(chronotype_hours=2)
    loop.outcome('x', 'explore', 'curiosity', ['sit'], {'curiosity': -5}, 'alone/morning', 0)
    loop.vigilance.request_sleep('self', 0, 0, 23)
    restored = LifeLoop(loop.persisted(), chronotype_hours=2)
    assert restored.persisted() == loop.persisted()
    assert LifeLoop({'version': 99, 'development': {'nights': 9}}).development.nights == 0


def test_context_labels():
    assert daypart(23) == daypart(3) == 'night'
    assert context(True, 13) == 'with_person/afternoon'


def test_rhythm_entrains_toward_when_the_person_is_present():
    loop = LifeLoop()
    sim = real = 0.0
    hour = 12.0
    for _ in range(10 * 144):                         # ten body-days, 10-minute steps
        sim += 600; real += 600; hour = (hour + 600 / 3600) % 24
        here = hour >= 21 or hour < 4
        loop.vigilance.tick(dt_sim=600, dt_real=600, occupancy=0, hour=hour,
                            person_idle_seconds=5 if here else 3600, now_real=real, now_sim=sim)
    v = loop.vigilance
    assert v.person_rhythm()['center_hour'] == pytest.approx(0.5, abs=0.3)
    assert v.person_rhythm()['consistency'] > 0.8
    shifted = abs(((v.peak - v.inborn_peak) + 12) % 24 - 12)
    assert 8 < shifted <= 10 * DEFAULTS['entrain_rate_hours_per_day'] + 0.01   # bounded drift per day
    restored = LifeLoop(loop.persisted())
    assert restored.vigilance.peak == pytest.approx(v.peak)


def test_no_person_no_entrainment():
    loop = LifeLoop(chronotype_hours=1)
    tick(loop, hours=72, hour=8)
    assert loop.vigilance.phase_shift == 0 and loop.vigilance.peak == pytest.approx(16)


def test_certainty_is_shared_across_the_day_but_not_across_presence():
    loop = LifeLoop()
    for _ in range(10):
        loop.outcome('d', 'reach_out', 'social', ['wave'], {'social': -0.5, 'tension': 2}, 'alone/morning', 0)
    loop.vigilance.request_sleep('self', 0, 0, 23); loop.sleep_work()
    dusk = loop.expectations.estimate('reach_out', 'wave', 'alone/evening', 0)
    together = loop.expectations.estimate('reach_out', 'wave', 'with_person/evening', 0)
    assert dusk['uncertainty'] < 0.1 < together['uncertainty']
    assert not loop.wants_to_act('reach_out', 'alone/evening', ['wave'], 0)[0]
    assert loop.wants_to_act('reach_out', 'with_person/evening', ['wave'], 0)[0]


def test_harsh_outcomes_alone_cannot_veto_contact_even_in_adulthood():
    loop = LifeLoop()
    loop.development.nights = 60
    for _ in range(30):
        loop.outcome('d', 'reach_out', 'social', ['wave'], {'social': 25}, 'alone/morning', 0)
    loop.vigilance.request_sleep('self', 0, 0, 23)
    loop.sleep_work()
    loop.vigilance.wake_by_person(1, 1, 8, 0)
    assert not loop.wants_to_act('reach_out', 'alone/evening', ['wave'], 0)[0]
    assert loop.wants_to_act('reach_out', 'with_person/evening', ['wave'], 0)[0]
    loop.outcome('d', 'reach_out', 'social', ['wave'], {'social': -15}, 'with_person/evening', 0)
    loop.vigilance.request_sleep('self', 2, 2, 23)
    loop.sleep_work()
    loop.vigilance.wake_by_person(3, 3, 8, 0)
    assert loop.wants_to_act('reach_out', 'with_person/evening', ['wave'], 0)[0]
