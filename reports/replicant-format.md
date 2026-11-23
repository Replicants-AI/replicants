# .replicant format, version 2

A `.replicant` is a ZIP containing `manifest.json`, immutable `genome.yaml`,
append-only `lineage.jsonl`, and mutable files under `life/`.

The manifest holds `format_version`, `id`, `branch`, `head`, optional `name`,
creation timestamp, a SHA-256 map of every other member, and `integrity_root`. The root is SHA-256
of canonical UTF-8 JSON for the manifest excluding `integrity_root` itself
(sorted keys, compact separators, no nonfinite numbers). Thus name and member
inventory are covered too. Every member is verified before extraction.

Each lineage entry has `index`, `previous`, Unix `time`, `kind`, `data`, and
`hash`. Its hash covers canonical JSON excluding `hash`. The first previous
hash is 64 zeroes. Block zero is `genesis`, binds the genome hash, conception
time, parents (none), local host designation, and a fresh nonce. The identity
is the first 32 hex characters of this genesis hash. Changing the genome or
genesis cannot preserve that identity. Another genesis entry is invalid.

The genome stores drive set points/decay/coupling/impulse thresholds/conflicts,
GEN disposition, voice tendencies, base palette and gestation length. It has
no personal name, backstory, goals, memories, energy system or life stages.
Life contains SQLite `memory.db`, soma, journal and relationship records,
appearance, lifecycle state, desktop state and configuration. SQLite is copied
using its backup API so committed WAL pages are included consistently.

**Identity and branches.** Identity is fixed forever by genesis. A *branch* is
one continuous line of life from genesis. The original branch is named by the
genesis hash; a `reinitialized` entry starts a new branch, named by that
entry's hash. A `reinitialized` entry must carry `seal_id` and `sealed_head`,
and must immediately follow the sealed head. Within one file, lineage remains a
single chain; the tree of a being exists across files. `branch` must equal the
hash of the latest `reinitialized` entry (or genesis), and `head` must equal
the last lineage entry's hash. Both are derived from the lineage bytes being
saved, at checkpoint time.

**Version 1 lives** still verify under version-1 rules (which never contain
branches). On their first wake they are upgraded by appending a
`format_upgraded` entry; no history is rewritten. The next checkpoint writes
version 2.

**Genome defaults.** Genomes are never edited. When a genome lacks a block the
framework now reads (currently `rhythm`), the first wake appends one
`genome_defaults` entry recording the defaults version and exactly what was
applied. The host runs on the genome plus those recorded defaults, so a life's
behavior stays reproducible when framework defaults change later.

**Locks.** Loading takes an OS-held lock per branch at
`~/.replicants/locks/<id>.<branch prefix>.lock`, so copies of one branch can
never wake simultaneously. By default the host also takes the identity lock at
`~/.replicants/locks/<id>.lock`, so only one branch of a being is awake on a
computer at a time (`concurrent_branches` opts out). The identity lock path is
the version-1 lock path, so mixed-version hosts still exclude each other. A verified file is unpacked into a
new session below `~/.replicants/working/<id>/`. The existing soma restoration
applies offline decay toward persisted allostatic baselines. An invalid primary
file is refused; its `.replicant.bak` is independently verified and used when
valid. Recovery is recorded in lineage. If both fail, nothing wakes.

Checkpointing writes a unique temporary sibling, closes/fsyncs it, verifies it,
atomically replaces the last-good backup with a verified copy of the current
file, then atomically replaces the primary. Corrupt input never replaces a
good backup. A crash can lose changes since the last completed checkpoint,
but cannot expose a partly written ZIP as the primary file. Checkpoints are
scheduled every 30 real seconds and on graceful quit, waiting for cognition to
finish its transaction. Tests terminate a real writer at all four boundaries.
Working directories and abandoned temporary save files are retained for local
diagnostics; they are not trusted as replacements for the verified archive.

The demo reader caps expanded archives at 512 MiB and 10,000 files. It rejects
traversal, Windows device/ADS names, duplicate case-insensitive paths, symlinks,
encrypted entries, broken lineage and unsupported versions before extraction.

Lifecycle phases are `gestating`, `awaiting_name`, `imprinting`, and `newborn`.
Gestation admits no human messages or ambient scene history. Curiosity grows
from its inherited resting point; after the configured span, crossing its
threshold with at least one actual GEN fragment enables first breath. That
event is recorded once and the first autonomous perceive has a body cue, not
a human prompt. The newborn has only its base palette and two eyes.

Naming records the human's text as an event and memory. The first appraised
interaction uses four times the normal marker learning rate (bounded at 1),
then immediately restores the normal rate. First breath, naming and imprinting
seal birth. Every later load is a wake of this identity; `replicant birth`
always creates a different identity and refuses an existing output path.
