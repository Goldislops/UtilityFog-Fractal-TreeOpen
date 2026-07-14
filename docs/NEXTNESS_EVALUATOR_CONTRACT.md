# Nextness Evaluator Contract (NP5)

**Module**: `scripts/nextness_evaluator.py` · **Tests**: `tests/test_nextness_evaluator.py`
**Schema**: `nextness-evaluation-v1` · **Status**: offline artifact evaluator — observes and scores recordings, never acts

## What this is

The first evaluation layer above NP1 and NP2: a deterministic, offline
reader of **recorded artifacts** — NP1 predictor reports
(`nextness-predictor-v1`) and NP2 monitor receipts
(`nextness-monitor-v1`, singly or as a recorded series) — that answers
one question honestly:

> What can these artifacts establish about prediction, uncertainty,
> abstention and recovery after surprise — and what remains
> uncomputable from them?

It never tunes, actuates, selects engine rules, invokes a model,
contacts a service, or writes into the engine or observer. Its only
inputs are artifact files; its only output is one deterministic JSON
evaluation.

## Non-claims (load-bearing, embedded in every evaluation)

- No awareness, consciousness, phenomenology or biological-equivalence
  claim is made or implied by any value here.
- A `not_computable` result is a statement about the **artifacts'
  evidence**, never about the underlying system.
- No "improvement" or "victory" language: model comparisons are
  reported as gaps and rankings with fixed tie-breaks, nothing more.

## The result envelope (the honest core)

Every metric is exactly one of:

```json
{"status": "computed", "value": ...}
{"status": "not_computable", "reason": "<fixed code>", "requires": "<missing evidence>"}
```

Fixed reason vocabulary: `artifact_absent` · `field_not_recorded` ·
`series_too_short` · `order_not_witnessed` · `no_covering_receipt`.
Uncomputability is typed and first-class — absent evidence is never
guessed around.

## What is computable, and why

| Question | Evidence | Result |
|---|---|---|
| Prediction error vs the uniform reference | NP1 report: per-model `nll_bits`, fixed vocabulary size | `nll_gap_to_uniform_bits` per model (`log2(16) = 4` bits reference) |
| Model ordering | NP1 report metrics | deterministic rankings (ties broken in fixed model order) + do the two proper scores agree |
| Ingestion health | NP1 report accounting | rejection rate, unseen-transition-source rate |
| Calibration magnitude | either artifact's ECE fields | echoes + series max; series "latest" only when order is witnessed |
| Abstention behaviour | NP2 series | abstention rate, fixed-vocabulary reason histogram, config-stability flag |
| Receipt internal consistency | NP2 recorded fields | tri-state verdicts per fixed check (below) |
| Recovery/reorientation | NP2 **ordered** series | abstention onsets, reorientations, completed run lengths (in receipts), unresolved trailing run |
| Inter-receipt dynamics | NP2 ordered series + prefix assumption | per-block means recovered algebraically, **with propagated error bounds** |
| Cross-artifact agreement | report + a covering receipt | ECE and surprise/NLL matches under a stated assumption |

## What is *not* computable, and why (typed in the output)

- **Full abstention-decision verification** — the v1 receipt does not
  record the latest observation's `confidence` or `prev_seen`, the two
  inputs that the `low_confidence` and `unseen_state` reasons (and part
  of `none`) depend on. Those clauses are `unverifiable` by
  construction.
- **Abstention quality** (was abstaining warranted?) — receipts record
  aggregates only; per-observation outcomes during abstained spans are
  absent (`field_not_recorded`).
- **Miscalibration direction** — both artifacts record absolute-gap
  ECE; signed per-bin gaps are absent, so over- vs under-confidence
  cannot be distinguished (`field_not_recorded`).
- **Metric-difference significance** — the report records holdout means
  only; no variance estimate is possible (`field_not_recorded`).
- **Per-observation recovery** — recovery is resolvable at receipt
  granularity only (`field_not_recorded`).
- **Series order, when unwitnessed** — see chronology below
  (`order_not_witnessed`).

## Consistency verdicts (tri-state, tolerance-guarded)

Four fixed checks per receipt: `abstain_flag_matches_reason`,
`sufficiency_matches_history`, `higher_precedence_excluded`,
`stated_reason_trigger`. Verdicts are `consistent` / `contradicted` /
`unverifiable`, aggregated per check with bounded contradiction-index
lists (explicit `truncated` flag, never silent).

**Tolerance derivation**: NP2 rounds receipt floats to 6 decimal
places, so a recorded value is within 5e-7 of the true value. Comparing
two recorded values ⇒ worst-case combined error 1e-6 ⇒
`CONTRADICTION_TOLERANCE = 2e-6` (2× margin). Comparing a recorded
value against an unrounded report value ⇒ worst case 5e-7 ⇒
`CROSS_CHECK_TOLERANCE = 1e-6`. A declared contradiction can therefore
never be a rounding artifact.

## Chronology witness

Receipts carry no timestamps (by emitter design). Series order is
trusted **iff `observation_count` strictly increases** — each receipt
saw more observations than its predecessor. Equal counts are ambiguous
(a deterministic emitter produces byte-identical receipts for identical
inputs, so an equal-count neighbour adds no ordering evidence) and fail
the witness. A failed witness degrades order-dependent metrics to
`order_not_witnessed`; order-free metrics still compute.

## Stated assumptions (emitted only when used)

- **prefix-extension** — inter-receipt block means assume consecutive
  receipts are cumulative snapshots of one growing stream. The block
  mean over the `n2 − n1` new observations is `(n2·m2 − n1·m1)/(n2 −
  n1)`, with propagated rounding-error bound `(n1 + n2)·5e-7/(n2 −
  n1)` reported beside every value (it grows without bound as blocks
  shrink). A block mean outside the field's possible range by more than
  its bound **falsifies the assumption** — reported per block and rolled
  up as `all_within_bounds`.
- **same-source** — cross-checks assume the receipts came from the same
  log and NP1 options as the report; neither artifact records this, so
  cross-check verdicts are explicitly conditional. A receipt "covers"
  the report when `observation_count == holdout_rows` and
  `config.window >= holdout_rows`; then its rolling ECE is the same
  computation as the report's holdout ECE and its mean surprise is the
  report's `nll_bits`. **Divergent-cap witness**: the emitters record
  extreme per-observation surprise differently (NP1 floors P(actual) at
  1e-300 ≈ 996.58 bits; NP2 caps at 1000 bits), and per-observation
  surprises are non-negative, so `mean × count < 996.58 bits` witnesses
  that no observation was in the divergent regime. One floored
  observation forces **both** recorded totals above that line, so the
  surprise/NLL comparison is `unverifiable` exactly when both totals
  clear `-log2(1e-300) − 1` bit (margin failing toward unverifiable);
  otherwise it is genuine evidence.

## Input contract (defensive by construction)

- Bounded read **before** parse: at most `MAX_INPUT_BYTES` (1 MiB) + 1
  probe byte ever materialized; larger files fail closed.
- Series bounded at `MAX_SERIES_RECEIPTS` (256); empty series fail
  closed.
- Exact-type, fail-closed validation at every field: builtin
  `dict`/`list`/`str`/`bool`/`int`/`float` only; bools are never
  numbers; no conversion hook (`__float__`/`__index__`) is ever
  invoked; non-finite and overflow-scale numbers are rejected;
  **exact key sets** (unknown keys = unknown variant = rejected;
  missing keys = rejected); unknown `schema` strings rejected.
- NP1 internal-accounting identities re-checked (rejections sum,
  row-count inequality, split arithmetic): an artifact violating them
  is not a v1 report, whatever its schema string says.
- Receipt internal *consistency* is deliberately **not** a load error —
  a well-formed receipt that contradicts itself is exactly the evidence
  the abstention section exists to report.

## Output contract

Deterministic JSON: sorted keys, fixed separators, newline-terminated —
the same canonical serialization as NP1/NP2. **No wall-clock
timestamps, no random identifiers, no absolute paths**; provenance is
the SHA-256 and byte count of each input artifact's raw bytes, which is
sufficient to reproduce every calculation. Byte-identical across
repeated runs, and `--output` files are written LF-only on every
platform (no newline translation), so a recorded evaluation's own
sha256 does not depend on the producing operating system. Every
per-item detail list — contradiction indices, block means, run lengths,
cross-check results — is capped at `MAX_DETAIL_ITEMS` (128) with
explicit `truncated` flags and full counts, never silently. Serialized
size is checked against a **64 KiB ceiling — fail closed**
(`EvaluationTooLargeError`), proven in tests at the maximum series
length in both saturation directions (receipts-only, and report plus a
fully-covering series).

## Write boundary

Default output is **stdout**. `--output` must resolve inside the
primary input artifact's directory (the `--report` file when provided,
else the `--receipts` file) and **never** inside the repository `data/`
tree — the same convention as `nextness_predictor`.

## CLI exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | validation failure: missing/oversized/malformed artifact, unknown variant, or no artifact provided (argparse usage errors also exit 2) |
| 4 | output-path failure: write-boundary violation or unwritable target |
| 5 | serialized evaluation exceeds the 64 KiB ceiling (fail closed) |

There is deliberately no exit-3: "not enough evidence" is never a CLI
failure — it is a typed `not_computable` result inside a successful
evaluation. Expected failures print one concise `error:` line to
stderr, never a traceback; unexpected programming errors propagate
loudly.

## Safety

Offline; no network; no tuning, orchestration, engine, Swarm Hunter or
Lane-A imports (only `nextness_predictor`, `nextness_monitor`,
`nextness_observer` and stdlib — statically auditable). Reads only the
artifact files named on the command line; writes only under the
documented boundary.

## Relationship to what comes next

Planned follow-ups in this runway (not yet part of the repository until
their own packages land): a replay laboratory for per-step abstention
trajectories over recorded logs, and a test-owned contract guard
locking the artifact schemas against silent drift. Nothing in this
package changes observer, predictor or monitor semantics, and nothing
in the runway touches the engine.

One boundary note for a future package (out of scope here, as it
requires touching NP1): `nextness_predictor`'s own `--output` writes
with platform newline translation, so an NP1 report file's sha256
differs between Windows and Linux even when its content is identical;
this evaluator hashes whatever bytes it is given and is unaffected, but
cross-platform golden-fixture work should account for it.
