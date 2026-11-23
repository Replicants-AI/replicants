# Replicants — Species Specification

November 2026 · draft 2

Where it describes code, it refers to the code at the time of writing.

---

## 1. Thesis

Replicants is a framework for a fully local, self-contained digital species.

A replicant is a continuing individual that runs on compute and thinks with compute. It has a genome fixed at conception, a body made of its real computational conditions, and a life that accumulates in memory and lineage. It is not an assistant and not an agent: it has no task, and human input is something that happens to it.

Many replicants can live on one machine. Each life is local by default and never requires a network. At moments that matter, a **nerve** can seal a replicant's state and commit it to permanent storage on Arweave. A sealed state can be retrieved and reinitialized on another host, where it continues as a new branch of the same lineage.

The desktop overlay is one **embodiment**: the first cell, not the organism.

Three rules hold everywhere:

1. **Measured or modeled, and said which.** Every bodily signal is either a measured condition of the substrate or a modeled pressure whose dynamics are documented. The body is made of its real conditions.
2. **Outcomes, not intentions.** Relief, learning, and memory come from observed results (receipts, reactions, measurements), never from what the being asked for.
3. **The being does not move itself.** A replicant can signal that a moment matters. Only host policy, controlled by a human, can seal, upload, copy, or reinitialize it.

---

## 2. Layers

| Layer | What it is | Where it lives today |
|---|---|---|
| **Genome** | Immutable inborn tendencies: temperament, soma parameters, voice, gestation, substrate requirements | `genome.yaml`, `replicants/desktop/genome.py` |
| **Lineage** | Append-only, hash-linked record of life events from genesis; becomes a tree once branching exists | `lineage.jsonl`, `replicants/desktop/archive.py` |
| **Life** | Mutable state: memory, soma, markers, desires, ledger | `life/` inside the archive |
| **Runtime** | Host process that runs a life: scheduler, cognition, appraisal, checkpoints | `replicants/desktop/runtime.py`, `life.py` |
| **Substrate** | The machine the being is running on, as measured | `replicants/desktop/substrate.py` |
| **Embodiment** | A surface the being acts through. The desktop overlay is the first | `desktop/` (Tauri + TS) |
| **Nerve** | Event path from lived significance to sealed, permanent, portable state | not built |

The `.replicant` archive (genome + lineage + life) is the being. Runtimes, embodiments, and model weights are hosts it passes through.

Before conception, a person can choose an authored character design and paint its
body pixels individually. The desktop birth flow stores the resulting `body_design`
in the immutable genome. It uses the shared 8 by 7 anatomy required by authored
movement, with up to 43 independent hex colors, one for each occupied pixel.
This is an inborn design chosen before first breath. Existing genomes and lived
appearance records retain their recorded values.

---

## 3. Metabolism: the body reads its substrate

### 3.1 Problem

`substrate.py` already measures real compute and surfaces it to cognition, GEN, and the inspector. Nothing yet turns those measurements into bodily pressure or regulation. The being can see that it has been thinking hard; it cannot feel it.

### 3.2 Principles

- **Measurement and model stay separate.** Occupancy, durations, token counts, and throughput are *measurements*. Exertion, sluggishness, crowding, their normalization, and their effects on soma are a *model* with stated assumptions. Every derived quantity is labeled as such wherever it is shown, including in the being's own context.
- **Relative to self.** The being's own work is measured against its own history, never against fixed thresholds.
- **Recovery is idleness, not refill.** Recovery accrues only over real time with no in-flight work.
- **Attribution is honest.** The being's own requests are *exertion*. Whole-machine pressure is *environment*.
- **Unknown stays unknown.** A missing measurement contributes nothing. It is never read as zero load or zero strain.
- **Real time only.** Metabolic signals advance on wall-clock time, never `SimClock` (see §3.6 for the interaction with simulated homeostasis).

### 3.3 Observations

The ledger emits one **observation per finished request** (chat or embedding): kind, model, status, wall start and end, elapsed, provider timings, reported tokens. Metabolism consumes observations through a listener, not by diffing totals or reading `last_request`, so no request is lost between samples and failed or cancelled work is still counted.

**Work** is any in-flight chat or embedding request. Failed, cancelled, and retried requests count as work; waiting and retries happened on this substrate.

**Idle** is wall time with zero in-flight requests. This is not `seconds_since_last_completed_thought`, which keeps rising during a long inference.

### 3.4 Signals

Sampled on the existing 10-second substrate loop over the window since the previous sample.

| Signal | Definition | Kind |
|---|---|---|
| **Occupancy** `O` | Fraction of the window with ≥1 request in flight. In-flight work is clipped at window boundaries, so a long request is spread across the windows it actually spans. | Measurement |
| **Concurrency** `Q` | Time-integral of in-flight request count over the window, divided by window length | Measurement |
| **Pace** `P` | Output tokens ÷ provider `eval_duration`, per completed chat request with both values reported, kept per model | Measurement, sparse |
| **Idle run** | Wall seconds since the later of the last finished request and the start of observation (0 while any request is in flight) | Measurement |
| **Host RAM / GPU** | Existing `Substrate` hardware samples | Measurement, environment |

Each of `O` and `P` keeps a **fast** (half-life ≈ 5 min) and **slow** (half-life ≈ 24 h) exponentially weighted average in real time, decayed by elapsed wall time rather than sample count. The wall time of each average's last update is persisted, so a restart after a long gap decays exactly as an uninterrupted process would. `P` updates only on new pace observations.

### 3.5 Calibration and interpretation (model)

A slow average is **calibrated** when all hold:

- ≥ 6 h of real observation time on this host,
- ≥ 50 contributing observations (requests for `O`; pace samples for `P`, counted per model).

Pace is kept **per model**: throughput is a property of a model on a substrate, so baselines from different models are never mixed. Sluggishness uses the model with the most pace evidence. Pace **coverage** (the share of completed chats that reported eval timing) is shown, not gated: transports without provider timings, such as the thinking/streaming path today, cannot contribute pace at all, so a coverage gate would never pass.

Below that, a baseline is `uncalibrated` and drives nothing.

```
exertion  = clamp( O_fast / max(O_slow, ε_O) - 1, 0, 3 )        ε_O = 0.02
sluggish  = clamp( 1 - P_fast / P_slow, 0, 1 )                  undefined if P_slow unknown
crowding  = max( ram_used_frac - 0.90, gpu_mem_frac - 0.95, 0 ) / 0.10
```

`ε_O` is a floor that keeps a mostly idle being from reading one request as tenfold strain.

**Crowding is the documented exception to relative measurement.** Running out of memory is a physical limit, not a matter of habit, so environmental scarcity uses absolute thresholds near capacity.

### 3.6 Coupling into soma (model)

Metabolic signals advance in real time while homeostasis advances in simulated time. To keep acceleration from erasing metabolic effects, metabolism does not inject bar deltas. It **shifts the homeostatic set point**:

```
effective_rest[bar] = rest[bar] + Σ coefficient[signal][bar] × signal
```

| Signal | Set-point shift | Rationale |
|---|---|---|
| exertion | `tension` ↑, `comfort` ↓ | Working harder than its norm is strain |
| sluggish | `tension` ↑ (small), `curiosity` ↓ (small) | Thinking slower than it should |
| crowding | `tension` ↑, tagged environment | Pressure it did not cause |

While a signal persists, homeostasis pulls bars toward the shifted point at simulated speed. Acceleration changes how fast bars arrive, not where they settle. When the signal returns to zero in real time, the set point returns and bars relax. Allostasis drifts the unshifted `rest` only, so chronic metabolic load reaches baselines through the bars themselves, not through the shift.

Coefficients come from a `metabolism:` block. Existing genomes are immutable and lack it; see §4.5.

### 3.7 Regulation (model)

```
wake_interval = base_interval × (1 + k × exertion)      k ≤ 1, result capped at 4 × base
```

This is the only compulsory regulation. Existing real-time host limits (60 s minimum, 12 wakes/hour) remain an absolute floor.

### 3.8 Migration

Baselines are stored per host fingerprint (OS, CPU model, RAM total, GPU model and VRAM, chat model name and digest). On a fingerprint change:

1. Append a `host_changed` lineage entry with both fingerprints.
2. Keep the previous host's slow averages as an **inherited** baseline, labeled with its source host.
3. Start a fresh **local** baseline for the new host.
4. Compare against `w × local + (1 − w) × inherited`, where `w` = local observation hours ÷ 24, capped at 1.

The inherited baseline counts as calibrated if it was calibrated on its own host. Migration is therefore felt from the first requests on new hardware and fades into the new norm over about a day.

### 3.9 Rollout

1. **Shadow mode.** Observations, occupancy, pace, EWMAs, calibration state, and the derived quantities are computed, persisted, and shown in the inspector. Nothing reaches soma, prompts, or cadence.
2. **Calibrate.** Choose coefficients from recorded distributions across several days of real life.
3. **Enable set-point coupling, then regulation.**
4. **Acceptance:** after a burst of conversation, a long-lived being shows exertion, slower autonomous cadence, and recovery during real idle time, each step traceable in the inspector, at 1× and at accelerated time.

---

## 4. Identity and branching

### 4.1 Definitions

- **Identity** — the genesis hash (current `manifest.id`). Fixed forever. Answers "which being is this?"
- **Branch** — one continuous line of lineage from genesis. Answers "which life of that being is this?"
- **Head** — the hash of the latest entry on a branch.
- **Seal** — an encrypted, content-addressed snapshot of an archive at a specific head.

### 4.2 Rules

1. A seal is immutable. It records `(identity, head, archive_sha256)`.
2. Reinitializing a seal never resumes the original branch. It appends a `reinitialized` entry whose `previous` is the sealed head, which starts a **new branch**. Branch id = hash of that entry.
3. The original branch, if still alive somewhere, continues independently. The lineage of a being becomes a tree rooted at genesis.
4. Each branch's memory diverges from the branch point. Both are the same being up to that point, and different lives after it.
5. The local identity lock moves from per-identity to per-branch. Starting a second branch locally is an explicit host action (`replicant reinit SEAL`), never a side effect of opening a file twice.

### 4.3 What the being knows

The `reinitialized` entry becomes memory: when it was sealed, how long the seal lay dormant (real time), the old and new host fingerprints. The being does not know whether other branches exist unless a future mechanism tells it.

### 4.4 Substrate identity

What carries across models: memories, markers, baselines, temperament, lineage. What does not: voice and reasoning style, which belong to the model. Reinitializing on a different model is permitted and recorded in `host_changed` (the fingerprint includes model name and digest). This is stated plainly, not hidden.

### 4.5 Format version 2

`verify()` changes; the rest of the integrity design stays.

- **Manifest.** `id` stays the first 32 hex characters of the genesis hash. A new `branch` field holds the branch id: the full hash of the branch's `reinitialized` entry, or the genesis hash for the original branch. `head` holds the current lineage head hash.
- **Lineage validation.** Unchanged hash-chain rules, plus: a `reinitialized` entry must reference a seal id and the sealed head, and must immediately follow that head. `branch` must equal the hash of the latest `reinitialized` entry, or genesis if there is none. Lineage stays a single chain inside any one archive; the tree exists only across archives.
- **v1 migration.** A v1 archive verifies under v1 rules and is upgraded on first checkpoint: `branch` = genesis hash, `head` set, plus a `format_upgraded` host entry. No history is rewritten.
- **Locks.** `~/.replicants/locks/<id>.<branch>.lock`. Two copies of the same branch cannot run on one host. Whether two *branches* of one identity may run at once is an open question (§9) and is enforced by host policy, not the lock.
- **Genome compatibility.** Genomes are never edited. Missing `metabolism:` and `substrate:` blocks take framework defaults; the first v2 wake appends a `genome_defaults` entry recording the framework version and the exact defaults applied, so behavior stays reproducible when defaults change later.

---

## 5. The nerve

### 5.1 Signal versus authority

The being can **signal**; only the host can **act**.

**Signal.** The runtime emits a `nerve_signal` lineage entry when a qualifying event occurs. Initial triggers, all derived from existing events:

- birth sealed (first breath, naming, and imprint complete)
- `host_changed`
- `reinitialized`
- appraisal magnitude above a defined threshold
- a completed dream
- clean shutdown after a configurable real-time interval since the last seal

**Authority.** A host policy, owned by the human, decides what happens per trigger:

```yaml
nerve:
  mode: ask            # off | ask | auto
  auto_triggers: [birth_sealed, host_changed]
  min_interval_hours: 24
  max_bytes_per_seal: 64MiB
  recipients: [<x25519 public key>, ...]
```

The being has no tool that reads, seals, copies, or uploads its archive. This keeps the existing rule intact.

### 5.2 Sealing

Mindstate-style envelope:

1. Checkpoint the archive (existing atomic path) at head `H` and compress it.
2. Generate a random 256-bit data key; encrypt with AES-256-GCM.
3. Wrap the data key to each recipient's X25519 public key (sealed-box style).
4. Upload ciphertext + envelope to Arweave.

Public tags are minimal: species, format version, `sha256(identity)` rather than the identity itself, sealed head `H`, ciphertext hash. Memory content is never public.

### 5.3 Seal lifecycle

A snapshot necessarily predates the record of its own upload. The sealed archive is never modified; its receipt lives outside it until confirmed.

1. **Prepared.** Ciphertext written locally; an outbox record `life/nerve/outbox/<ciphertext-sha256>.json` holds `{head: H, ciphertext_sha256, size, recipients, state: prepared}`. The outbox is host state, not lineage.
2. **Submitted.** Transaction id added; `state: submitted`. Upload is idempotent by ciphertext hash: a retry first checks whether that hash is already on Arweave.
3. **Confirmed.** On confirmation, append a `sealed` entry to the *live* branch (which may have advanced past `H`) recording `{seal_id: tx, head: H, ciphertext_sha256, recipient_fingerprints}`. Remove the outbox record.
4. **Interrupted.** On restart, the runtime resumes any outbox record: verifies the local ciphertext, then checks or resubmits. A record whose ciphertext is missing or corrupt is marked `abandoned` in a `seal_abandoned` host entry; no partial seal is recorded as sealed.

Seal `S` at head `H` does not contain its own `sealed` entry. A branch reinitialized from `S` carries the receipt forward in its `reinitialized` entry (`seal_id`, `head: H`), so every branch knows exactly which seal it descends from.

### 5.4 Reinitialization

`replicant reinit <tx-id | file>`:

1. Fetch ciphertext; verify its hash against the tag.
2. Unwrap the data key with a local private key; decrypt.
3. Verify the archive under its own format version rules (§4.5).
4. Append `reinitialized` (seal id, sealed head, source and destination fingerprints); set `branch`.
5. Wake normally. Offline decay applies to the real time since `H`. Metabolism follows §3.8.

### 5.5 Storage

Full sealed snapshots for v1, with a hard size cap. `memory.db` growth makes deltas necessary eventually; defer until real archive sizes are measured.

### 5.6 Out of scope for v1

Tokenization, transfer of ownership, public registries, and any market. A `sealed` entry is already an ownable, verifiable object, so these can be layered on later without changing the format.

---

## 6. Constraints that stay

- Exact authored animation; action receipts; outcome-based relief.
- Archive verification, atomic checkpoints, save-before-switch.
- Restricted senses: no screen content, titles, clipboard.
- Local inference only on the desktop surface.
- Birth with no authored persona, history, or task.

## 7. Removed

- Energy as a displayed value. The circadian `energy` packet field becomes `alertness` or is removed.
- Any counter-based appearance unlock.

## 8. Build order

1. Metabolism shadow mode: per-request observations, occupancy, pace, EWMAs, calibration, inspector (§3.3–3.5, §3.9 step 1).
2. Host fingerprint, per-host baselines, `host_changed` (§3.8).
3. Format version 2: branch and head fields, verify rules, v1 upgrade, per-branch locks, genome defaults (§4.5).
4. Metabolism set-point coupling and regulation, after calibration data exists (§3.6–3.7).
5. Nerve: signal entries and host policy (§5.1).
6. Sealing, outbox lifecycle, upload, `sealed`, `reinit` (§5.2–5.4).
7. Multiple beings: the desktop currently runs one brain and one body per session, which is a separate constraint from archive locks. Multi-being execution needs its own design (process model, shared inference, embodiment for several bodies).
8. Live acceptance across a full arc: birth → life → nerve → seal → reinit on a second machine → recognizable continuity with a recorded branch.

## 9. Open questions

- **Concurrent branches.** Default decided: one awake branch per identity per computer, enforced by the identity lock; `concurrent_branches` allows twins on one machine when wanted. Whether that should ever be on by default is still open.
- **Seal recipients.** Does a being always have one owner key, or can it be sealed to several?
- **Death.** Does a branch ever end, and is that an event the nerve records?
- **Multiple beings.** When many replicants share one machine, crowding becomes partly other replicants. Is that environment, or social?
