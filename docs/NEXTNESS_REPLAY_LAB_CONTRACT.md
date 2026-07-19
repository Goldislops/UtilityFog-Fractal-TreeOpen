# Nextness Replay Laboratory Contract (NP6)

**Module**: `scripts/nextness_replay_lab.py` · **Tests**: `tests/test_nextness_replay_lab.py`
**Schemas**: `nextness-replay-lab-v1` (output) · `nextness-replay-protocol-v1` (input) · **Status**: laboratory observations only — replays recordings, never acts

## What this is

An offline replay laboratory: it takes **one recorded**
`nextness_runs.jsonl` log and **one operator-written protocol file**
(up to 8 monitor configurations), replays the log through NP2's own
abstention decision procedure at **every holdout step**, and reports
each configuration's abstention trajectory side by side.

This reaches the granularity the NP5 evaluator cannot: NP5 reads
receipts, and receipts record aggregates — so recovery after surprise
is only resolvable at receipt granularity there. The lab replays the
recording itself, so it can state *at which step the monitor first
stopped abstaining, whether and how many times it re-abstained, and how
many steps each completed reorientation took* — per configuration, over
the same immutable input. (Onset step positions themselves are not
emitted — the summary carries counts and run lengths, not a per-step
timeline.)

## Laboratory observations only (load-bearing)

- Comparisons are **descriptive**. There is no ranking, no winner, no
  recommendation and no score field anywhere in the output (tested by
  key-walk); configurations appear in exactly the operator's input
  order.
- **Abstention is preserved**, not treated as a defect: a configuration
  that never leaves abstention is reported exactly as such
  (`first_non_abstain_step: null`, unresolved trailing run) — the test
  suite pins this on NP2's known under-confidence regime.
- **No search**: the operator hand-writes every configuration; the lab
  never generates, perturbs, sweeps or optimizes them, and never reads
  or writes any engine parameter.
- No awareness, consciousness, phenomenology or biological-equivalence
  claim.

## No new semantics (the equivalence lock)

The replay reuses NP1's public sequence reader, split arithmetic and
distribution builders, and NP2's public `decide_abstention`,
`rolling_ece`, `canonical_top` and `nextness_metrics.js_divergence`.
The bridge loop is re-derived because `observations_from_log` returns
the full observation list but **not** the train/holdout token lists the
per-step drift windows need (its recent counts cover only the final
window), and it accepts only a log path — reusing it would re-read the
log and decouple the observations from the already-read sequence the
lab hashes for provenance.

The re-derivation is pinned to the live NP2 path by a parametrized
lock across all three models, three configurations (including one where
`distribution_shift` is the reason that actually decides) and two
fixtures (one with a **fractional split**, so the floor arithmetic is
discriminated; both with the regime change inside the holdout, so
observations vary step to step): replayed observations must equal
`observations_from_log`'s **float-for-float**, re-derived
reference/recent counts must equal the bridge's, and the final-step
decision must equal what `build_receipt` emits. Two per-step
differential tests additionally rebuild every step's decision from
independently written slices (one exercising `distribution_shift`
mid-trajectory, one where per-step confidence alternates across the
`low_confidence` threshold). These locks were mutation-tested: drift
hardwired to zero, prefix-diluted recent windows, holdout-derived
references, first-window slices, stale latest observations and
floor→round split changes each fail the suite.

At step *t* the monitor has seen exactly the first *t* bridge
observations; rolling ECE runs over the last `window` of them, and
drift compares the training reference against the last `window` holdout
tokens — precisely NP2's receipt semantics evaluated at every prefix.

## Protocol contract (input, fail-closed)

`nextness-replay-protocol-v1`, exact key sets, exact types (no
conversion hooks, bools never numbers, NaN/overflow rejected), bounded
before parse (64 KiB): shared `model` / `smoothing` /
`holdout_fraction` (NP1's own bounds), plus 1–8 configurations, each a
unique label (≤ 64 chars) and the five `MonitorConfig` fields.
Threshold validation is **delegated to NP2's own
`MonitorConfig.validate`** — the lab cannot accept a configuration the
monitor itself would reject. Unknown schema strings, unknown keys,
duplicate labels and out-of-bounds values all fail closed.

**Hook-free refusal diagnostics (DIRECT Python API included).** A refusal
never reads an attribute of the rejected value or of its class — in
particular never `type(value).__name__`, since `__name__` is an
overridable **metaclass** property whose getter would run
caller-controlled code from inside error formatting and escape the typed
`LabInputError`. Builtin type names come from a literal identity table;
anything else is described as `non-builtin value`. Public CLI/artifact
messages are unaffected: `json.loads` yields only builtins, so every
reachable-lane diagnostic is byte-identical to before.

**Exact-string key partition.** A proven-exact `dict` is iterated
*without* hashing, comparing, stringifying or representing an unproven
key; only exact builtin `str` keys enter a set, and set membership,
difference, comparison and sorting run on those strings alone.
Non-string keys are reported as `<non-builtin value>` and always force a
mismatch. This closes a **soundness** hole as well as a hook path: a
non-string key whose `__hash__` collided with an expected name
previously had its `__eq__` invoked by the key-set comparison, and an
`__eq__` returning `True` let that key *satisfy* a required name and
pass validation.

## Trajectory summary (per configuration)

`step_count` · `abstention_step_rate` · `reason_step_counts` (fixed
NP2 vocabulary) · `first_non_abstain_step` (1-based, or null) ·
`abstention_onsets` · `reorientations` · completed run lengths (capped
at 128 with an explicit `truncated` flag) · unresolved trailing run ·
`final_abstain` / `final_reason` (directly comparable to a real NP2
receipt). Seeded property tests hold the accounting identities (reason
counts sum to steps; completed runs plus trailing equal abstained
steps; run count equals reorientations).

## Bounds (fail closed, never silent)

- ≤ `MAX_LAB_CONFIGS` (8) configurations; ≤ `MAX_REPLAY_STEPS` (2000)
  holdout steps — a longer holdout is **refused**, because dropping
  early steps would misstate `first_non_abstain_step` and every run
  length. The bound is enforced from the already-bounded sequence
  length **before any observation list is allocated**
  (`replay_observations` is provably never invoked for an oversized
  holdout — spy-tested), and a split-arithmetic invariant re-checks the
  early computation against the bridge's own holdout. Per-step rolling
  statistics cost O(steps × window), so the bound also caps total work.
- Log reading inherits NP1's `max_rows` / `max_line_bytes` bounds via
  `read_dominant_sequence` (`max_line_bytes` accepts only a non-boolean
  built-in integer in [1, 16 777 216] — the shared
  `MAX_LINE_BYTES_CEILING`; the re-exposed CLI flag inherits the same
  validated range); protocol files are size-checked before
  parsing; output is checked against a **64 KiB ceiling — fail closed**.

## Determinism and provenance

Sorted-key JSON, fixed separators, newline-terminated; no wall-clock
timestamps, no random identifiers, no absolute paths; byte-identical
across repeated runs; `--output` files are LF-only on every platform.
Provenance: the SHA-256 of the protocol file's raw bytes, and the
SHA-256 of the **accepted dominant-token sequence** — the log enters
the computation only through that sequence, so together with the row
accounting and the configuration echo this reproduces every
calculation. `--output` files are written as raw UTF-8 bytes (LF-only,
no dependence on newer `Path.write_text` parameters).

**Input protection**: the lab is read-only with respect to both inputs
(tested byte-for-byte, including through the CLI). An `--output` that
aliases either input is refused: by resolved path (which covers
symlink aliases, including dangling ones — resolution targets are
compared, not link names) and by file identity via `os.path.samefile`
(device + inode, which covers existing hard links whose paths differ);
an identity check that cannot complete is itself a refusal.
**Residual race, stated precisely**: identity is verified at validation
time and the later write does not re-verify, so a concurrent actor
replacing the output path between validation and write can still
redirect the write. The lab defends against aliases that exist when it
validates; it does not claim protection against concurrent hostile
filesystem manipulation.

## Write boundary and CLI

Default output is **stdout**; `--output` must resolve inside the input
log's directory and never inside the repository `data/` tree (NP1's
convention).

**Destination boundary on operational write failure** (audited 2026-07-17;
stage-pinned in the focused tests): a failure **at or before the binary
open** — an unwritable or read-only destination, an absent or invalid
parent — preserves any existing destination byte-identically and creates
no output. **After a successful direct non-atomic open**, a later failure
may truncate the destination or leave partial output (the whole-buffer
write truncates on open, so a failed write leaves an empty file). A
**close-time failure** may leave the complete canonical lab-report bytes
in place even though the run reports the operational-failure exit —
a present file does not imply a successful run. Supplied-input
preservation on these lanes is bounded by the existing validation-to-write
(TOCTOU) non-claim. No atomic-write behavior is provided or implied.

Exit codes mirror NP1: `0` success · `2` validation
failure (including a holdout beyond the replay bound) · `3`
insufficient history · `4` write-boundary/unwritable · `5` report over
the ceiling. Expected failures print one concise `error:` line, never a
traceback.

**Typed input boundary (replay-lab pilot)**: the exit-2 catch is
exactly the typed `LabInputError`. The shared reader's typed
`PredictorInputError` (this lab publicly re-exposes `--max-rows`/
`--max-line-bytes`) is **translated at the single reader call** —
`except PredictorInputError` exactly, never broad `ValueError` —
into `LabInputError` with the message byte-identical (`str(e)`) and
the original error preserved as `__cause__`. A plain `ValueError`
**reaching `main()` outside the existing scoped input-validation
translations propagates** (the committed build-seam and reader-seam
pins prove those exact lanes; a plain `ValueError` from the reader seam
is deliberately not wrapped). No claim is made that every inner
validation helper lacks a local base-class wrapper — the protocol
loader's JSON-parse and `MonitorConfig.validate` regions deliberately
catch base `ValueError` and translate it to `LabInputError`.
Direct-Python note: callers catching `ValueError` remain compatible
(`LabInputError` subclasses it); `read_dominant_sequence` called
directly still raises `PredictorInputError`. This is a lab-only
decision; no family-wide convention is implied.

## Safety

Offline; no network; imports only `nextness_predictor`,
`nextness_monitor`, `nextness_metrics`, `nextness_observer` and stdlib
(statically auditable). Never invokes a model, never touches the
engine, observer, orchestrator or tuning surfaces.
