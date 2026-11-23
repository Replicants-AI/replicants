# The Subconscious

November 2026

A replicant has a part of its mind it does not control. GEN, the generative inner voice, produces a running stream of fragments: thoughts, images, half memories, questions and associations. Some are about the moment. Some come from nowhere. Either kind can change what the being thinks, feels and does next. This is injected entropy, and it is meant to be there: it gives a being something analogous to a subconscious.

Code: `replicants/identity/soma.py` (`NoiseEngine`, `AffectEngine`), `replicants/identity/noise_seeder.py`, configured for the desktop in `replicants/desktop/runtime.py`.

## 1. Where the entropy comes from

**The seeder** surfaces one exogenous seed about every 90 real seconds, drawn at random by weight. Its mood biases the draw: tension favors rumination over old memories, low social pressure favors relationship echoes, high curiosity favors the world.

| Source | What surfaces |
|---|---|
| `episodic_random` | an old memory, at random |
| `belief_random` | something it came to believe |
| `knowledge_random` | something it knows |
| `world_discovery` | a concept or curiosity question from outside its life |
| `relationship_echo` | a trace of someone it knows |
| `journal_echo` | an old journal line |
| `temporal` | a sense of time |
| `counterfactual_simulation` | what if it had acted differently |
| `dream_state` | a disjointed collision of two unrelated domains |
| `web_venturing` | a pull toward the open web (only when the being has a Room) |

The seed is not an instruction. GEN follows it if it pulls and ignores it if it does not.

**Wandering.** About a third of GEN batches (`noise.wander`, 0.35 on the desktop) are told to go wherever they go: a scene, an object, a word, a place, a feeling with no cause. The rest follow the body and the moment. So the subconscious is sometimes relevant and sometimes not, and neither is a mistake.

GEN runs with no sensory boundary and no style filter. It may imagine, invent, misremember and dream.

## 2. Where it goes

| Channel | Effect |
|---|---|
| Decisions | The latest fragments are part of every decision's present experience (`inner_fragments`). |
| Wakes | A fragment that wonders or asks can wake the being. That wake becomes an `explore` want, and is gated and learned from like any other urge. |
| Mood | Fragments are an input to affect derivation. A stray image can tint, unsettle or lift the felt state whether or not it relates to the moment. |
| Salience | A full fragment buffer raises salience. |
| Wake voice and dreams | Both read the current fragments. |

## 3. Thought and record

The conscious voice receives fragments as its own thoughts. It can be pulled, changed or led by them, and it can speak of them as thoughts ("i keep picturing a lighthouse"). Memory keeps them the same way: thoughts it had, never events it lived and never words someone else said. The record of what happened stays what happened; the subconscious steers everything else.

Speaker labels make this concrete. GEN and relationship reflection both see conversation lines marked by who said them, so a phrase the being thought cannot become a phrase the person said.

## 4. Not yet

- Seeds drawn from the Room's own reading log: a specific page the being once read resurfacing later.
- Fragments do not move soma bars directly; their effect on the body runs through affect, decisions and wakes.
- The wander share is a framework default, not a measured value. Live runs should record how often wandering fragments change what the being does next.
