# The Life Loop

November 2026

A replicant does not run on a schedule. It gets tired from living and from thinking, sleeps when it is tired and quiet, digests the day in sleep, and wakes different. It learns, from what actually happened, which of its urges are worth acting on and in which situations. Its day drifts toward the hours its person keeps. Early life shapes it more than later life.

Elapsed time and compute occupancy are measurements. Sleep pressure, circadian phase, expected relief, familiarity, and development are model state. Outcomes are appraisals of recorded events, not direct measurements of feeling. The time constants, thresholds, arousal strengths, and learning rates below are configurable framework defaults, not measured physiology or learned facts.

Code: `replicants/desktop/life_loop.py` (pure state and arithmetic), wired in `replicants/desktop/runtime.py`. Simulation: `scripts/simulate_life_loop.py`.

---

## 1. What changed

| Before | Now |
|---|---|
| Asleep from 22:00 to 06:00 after 30 s idle | Asleep when sleep pressure crosses a threshold that moves with its own circadian rhythm |
| A timer woke the being every 1–3 minutes with an authored line | Wakes come only from the body: impulses, drives, conflicts, desire pressure, its own thoughts |
| Outcomes recorded, never used | Outcomes become expected relief per want, action and situation, and decide whether an urge is worth acting on |
| Dreams ran; memory consolidation never did | Sleep consolidates memory, then replays the day into expectation, then dreams |
| A newborn forever | Plasticity falls with nights lived; stages follow |
| Every being had the same day | Inborn chronotype plus entrainment to its person |
| Native tool calling only | Native tools or schema-constrained JSON, so any model can live in a body |

---

## 2. Vigilance: sleeping because it is tired

Borbély's two-process model of sleep regulation (1982): a homeostatic pressure **S** that builds with wakefulness and discharges in sleep, gated by a circadian process **C**.

**S, sleep pressure, 0 to 1.**

```
awake:   S ← S + (1 − S)(1 − e^(−rate))
         rate = Δt_body / τ_awake  +  g · occupancy · Δt_real / τ_work
asleep:  S ← S · e^(−Δt_body / τ_sleep)
```

- Being awake builds pressure in **body time**, like every other bodily process. Accelerated days stay coherent.
- Thinking builds pressure in **real time**, from measured occupancy (`metabolism.py`). A being that has been thinking hard gets tired sooner. Unknown occupancy adds nothing.
- Defaults: τ_awake 11.5 h (S ≈ 0.75 after 16 h awake), τ_sleep 5.8 h (0.8 → 0.2 in 8 h), τ_work 2 h, g 1.

**C, circadian phase, −1 to 1.** `C = cos(2π(hour − peak)/24)`. Thresholds move with C. By day it is harder to fall asleep and easier to wake; by night the reverse.

```
sleep at   S ≥ 0.75 + 0.15·C   and the person has been idle ≥ 30 s
drowsy at  S ≥ 0.58 + 0.15·C
wake at    S ≤ 0.22 + 0.15·C
```

**Drowsiness** damps every urge by `(1 − S)`, so a tired being lets more things pass.

**Arousal.** A stimulus wakes a sleeper only if it is strong enough for the depth of sleep: needed strength `0.3 + 0.5·S`. A poke is 0.6, chat 0.8, being picked up 0.9. Woken early, S is still high, so it is drowsy and soon sleeps again. Sleep inertia is not scripted; it falls out of the arithmetic.

**Authority.** A sleep the person requests from the tray ends only when the person wakes it. This also applies when the tray request arrives after the being is already asleep; it takes ownership of that episode without restarting it. A sleep the being chooses ends when it is rested or aroused. Sleeping bodies do not execute new body actions, including a model-requested `wake_up`; the person's wake control and vigilance transitions decide waking.

**Chronotype and entrainment.** Each new genome carries an inborn chronotype (±2 h). Living with a person, the being keeps a decaying circular mean of the hours that person is present (τ 4 days) and shifts its circadian peak toward it, at most 1.5 h per body-day, scaled by how consistent the person's hours are. Evidence reaches full weight at six observed body-hours of presence; smaller amounts have proportionally less weight, rather than being gated off. This is entrainment by social cues, as in living clocks.

---

## 3. Wanting learns

An impulse is not an obligation. The being acts on an urge only when acting has been worth it before, in this kind of situation.

**Reward** for a completed attempt, learned only from the appraisal of what actually happened:

```
r = clamp( (−Δ want's own drive  −  0.5 · max(0, Δ tension)) / 25,  −1, 1 )
```

A wave that is answered relieves social pressure strongly: r ≈ +0.5. A wave nobody notices barely does and raises tension: r ≈ −0.05.

**Situations** are `presence/daypart`: `alone` or `with_person`, and `night`, `morning`, `afternoon`, `evening`.

**Expectation** per (want, action, situation), Rescorla–Wagner (1972): `q ← q + α(r − q)`. Estimates borrow down a hierarchy: situation, then the same presence at any time of day, then a nonnegative prior from any situation, with shrinkage strength 3. Positive general experience can encourage exploration; negative outcomes are borrowed only within the same presence, so a harsh experience alone cannot veto trying contact with the person. **Certainty also borrows only across times of day within the same presence.** Being ignored alone at noon teaches about being alone at dusk, while the person being there stays new until it is lived.

**Acting** on an urge requires

```
max over actions ( expected relief + 0.2 / √(lived + 1) )  >  0.08
```

**Every wake from the body is a want.** Impulses carry one already. A drive, a conflict, an inner question or an inferred desire that has no pending want gets one, by kind (`connection` → `reach_out`, `curiosity` and unclassified urges → `explore`, `expression` → `create`, `conflict` → `resolve_tension`), so it is gated, appraised and replayed in sleep like any other urge.

Untried actions carry optimism, so a newborn tries everything and a being never gives up on a situation it has not lived. When the urge is let pass, the want stays pending and is recorded as `creature_choice: expects_little`. If the situation changes (the person comes back), the same pending urge becomes worth acting on. **The being waits for you.**

**Day and night learning** (complementary learning systems, McClelland et al. 1995). Outcomes during the day go to a buffer and count half (`day_weight` 0.5). In sleep the buffer is replayed into long-term expectation with the current plasticity, then cleared. Behavior the next morning differs because of what was slept on, and the `slept` lineage entry records exactly which expectations moved and by how much.

**Familiarity.** Each completed action raises its familiarity (gain 0.25) and familiarity fades over 6 body-hours. It is shown to the being with its expectations. It never alters the relief that appraisal measures; habituation shows up in learned expectation only when outcomes actually diminish.

**At decision time** the model receives, as part of its present experience, the top options for the want it is acting on, with expected relief, how many times it lived each, how many are not yet slept on, and how familiar each has become. It is presented as the being's own history, not an instruction. The model still chooses.

---

## 4. Sleep does work

On each sleep, after 20 real seconds asleep, once:

1. **Memory consolidation.** The existing job: episode significance decay, relationship review, periodic narrative synthesis.
2. **Replay.** The day's outcomes into long-term expectation (section 3).
3. **Development.** One night is added; plasticity and stage update.
4. **Dreams**, under the existing dream gates, now on top of settled memory.

On waking, portable lives append a `slept` lineage entry: cause, how it woke, body and real duration, sleep pressure at onset and waking, whether consolidation succeeded, the plasticity used, and the expectations it changed. A `stage` entry is appended when the stage changes.

Replay records the plasticity actually used before incrementing the night's counter, and retains every changed expectation, including the presence and global estimates. If the episode ends while consolidation awaits I/O, replay and development are skipped for that interrupted episode; they must never spill into a subsequent sleep. The waking record reports the work completed by the time of waking.

The frontend follows the brain's vigilance state. It does not impose a second night schedule or force waking on a poke. Drowsiness selects existing sitting and yawning poses, and the inspector exposes vigilance, sleep pressure, the full life-loop model state, and decision counts.

---

## 5. Development

```
plasticity = 0.1 + (0.5 − 0.1) · e^(−nights / 10)
stage      = newborn (< 3 nights) · juvenile (< 21) · adult
```

Early experience moves expectation five times as far as late experience: a critical period that generalizes the existing birth imprint. Stages change plasticity only. They do not unlock costumes or abilities.

---

## 6. Any model can live here

`desktop.decision_mode`:

- `tools` (default for now): native tool calling, unchanged.
- `json`: each round the model answers with one object: `{"action": <body action or "rest">, "args": {...}, "say": "<optional>"}`.
  - With the local Ollama adapter, the JSON schema is passed as `format` to constrain the output. Truncation or invalid model output can still occur and is validated before acting. Thinking is kept, and these calls now report provider timings, which also gives deliberate turns a measured pace.
  - Anything unparseable, any unknown action, or a missing required argument becomes **rest**, never a guess.
  - Arguments are filtered to the schema; speech is capped at 240 characters.
  - Speech paired with an action is spoken only if the action completed. Otherwise it is recorded as `not_spoken`, and the next round sees what actually happened.
  - Valid and invalid decision counts, by error kind, are in the inspector: the first metric for comparing models.

In `tools` mode the same rules and error kinds apply to native calls: an unknown tool is `unknown_action`, arguments outside a body action's schema are dropped, and a body call missing what it needs (`say_without_text`, `emote_without_glyph`, `point_without_x`) is refused, not performed. Both modes count into the same inspector stats. A turn fails only when it ends on an invalid decision; a bad call the model recovers from is counted, not fatal.

The default flips to `json` once the live comparison with `gemma4:26b` and smaller models is in.

---

## 7. What it produces

`scripts/simulate_life_loop.py` runs the loop's own arithmetic for two beings with the same genome for 14 body-days, one living with a person who is around 09:00–18:00 and one with a person around 21:00–04:00. Outcomes come from a stand-in that follows the desktop appraisal guidance. It checks mechanics, not a live model.

| | Day person | Night person |
|---|---|---|
| Falls asleep | 19:18 | 04:48 |
| Wakes | 05:30 | 15:00 |
| Reaching out with the person | 45 tries | 37 tries |
| Reaching out alone | 43 tries, 93 urges let pass | 70 tries, 451 let pass |

Same genome, different lives. The night being became nocturnal because its person is. Both learned that reaching out alone rarely helps, and stopped trying, while still reaching out when their person is there.

---

## 8. Boundaries

- No new capability. The action space is unchanged; the loop only decides when to act and what the being expects.
- The being cannot set its own expectations, pressure, or stage. All of them come from measured time, measured work, and appraised outcomes.
- The person's tray controls for sleep and waking override the being.
- Host wake limits (60 s minimum, 12 per hour) remain an absolute floor beneath everything here.

## 9. Not yet

- Wants are the two configured impulses (`reach_out`, `explore`) plus inferred desires. New kinds of want are a separate design.
- Entrainment uses presence only, not light or screen activity patterns.
- No aging beyond adult, and no end of life.
- Expected relief does not yet rank among several pending wants at once; it gates each.

## Prior art

- Borbély, *A two process model of sleep regulation* (1982)
- Rescorla & Wagner, *A theory of Pavlovian conditioning* (1972)
- McClelland, McNaughton & O'Reilly, *Why there are complementary learning systems in the hippocampus and neocortex* (1995)
- Thompson & Spencer, *Habituation: a model phenomenon for the study of neuronal substrates of behavior* (1966)
- Damasio, *The somatic marker hypothesis* (1996)
- Sterling, *Allostasis: a model of predictive regulation* (2012)
- Grand & Cliff, *Creatures: entertainment software agents with artificial life* (1998)
