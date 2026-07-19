# Nextness Prediction Baseline (NP1)

**Module**: `scripts/nextness_predictor.py` · **Tests**: `tests/test_nextness_predictor.py`
**Schema**: `nextness-predictor-v1` · **Status**: baseline instrument, offline-only

## What this is

The first measurable capacity on the "functional self-awareness" ladder:
**can the system anticipate what happens next?** — asked in the most
honest way available: three transparent baselines over the existing
Nextness Observer log, so that any future, cleverer predictor has
something falsifiable to beat.

It reads `nextness_runs.jsonl` rows (never raw snapshots, never live
engine state), reduces each row to its **dominant vocabulary token**
(maximal count; ties broken by canonical `TOKEN_NAMES` order), and
evaluates next-token prediction on a **chronological holdout**.

## Non-claims (load-bearing)

- This measures **sequence regularity in observer logs**, nothing more.
  No intelligence, awareness, understanding or performance-victory claim
  is made or implied.
- A simple baseline outperforming a complex model is an **expected,
  fully-reported outcome** — that is what baselines are for.
- Dominant-token reduction discards within-row distribution detail by
  design; a future instrument may predict full distributions.

## The three baselines

All three emit a full-vocabulary probability distribution using the same
additive (Laplace) smoothing `α` (default 1.0, bounded (0, 1000]), so
their likelihoods are directly comparable.

| Model | P(next = t) | Notes |
|---|---|---|
| `empirical_prior` | (train count of t + α) / (train rows + 16α) | ignores the previous token |
| `persistence` | (1[t = prev] + α) / (1 + 16α) | "tomorrow equals today" |
| `first_order` | (C[prev][t] + α) / (ΣC[prev] + 16α) | Markov transition counts from consecutive train pairs |

**First-order fallback**: a previous token never seen as a transition
*source* in training has no row to smooth. The model falls back to the
`empirical_prior` distribution (never an invented uniform row), and the
report carries `first_order_unseen_source_count` so the frequency of
fallback is visible.

## Evaluation protocol

- **Chronological split only**: first `floor(N·(1−h))` accepted rows
  train (`h` = holdout fraction, default 0.25, bounded [0.05, 0.5]); the
  remainder is holdout. Nothing is shuffled; models never see a holdout
  token before predicting it. The first holdout target's "previous
  token" is the last training token (known at prediction time).
- **Metrics** (all deterministic):
  - `nll_bits` — mean −log₂ P(actual); base-2 to match the repository's
    bits-everywhere convention.
  - `brier` — mean multiclass Brier score Σ_t (p_t − 1[t=actual])².
  - `top1_accuracy` — argmax prediction, canonical-order tie-break.
  - `ece` — expected calibration error over **10 fixed equal-width
    confidence bins** (final bin closed above), bin-size weighted.
- Every exact-metric test fixture is calculated independently in the
  test file from these formulas — the module is never asked to verify
  itself.

## Input contract (defensive by construction)

- Built-in `dict` rows only; `generation` must be a non-bool `int`;
  `token_counts` must be a built-in `dict`.
- **Known vocabulary only** — any unknown key rejects the row.
- Counts must be real, finite, non-negative numbers; `bool` is rejected
  explicitly (schema violation, not a count of one).
- **Strictly increasing generations** over accepted rows: duplicates and
  out-of-order rows are rejected and counted, never silently reordered
  (sorting could hide train/holdout leakage; refusing cannot).
- Bounded raw work: `max_rows` (default 100 000, ceiling 1 000 000)
  counts **every physical input record** — accepted, rejected and blank
  alike — so a blank-line flood cannot buy unbounded reading. Blank
  records are neither observations nor violations: they consume row
  budget but appear in no rejection count, so `rows_read ≥
  rows_accepted + rows_rejected`, with `rows_accepted` the
  accepted-observation count.
- Bounded line size (pre-allocation guard): records are `\n`-delimited
  and read via bounded `readline` calls of at most `max_line_bytes + 2`
  bytes (default `max_line_bytes` 65 536; the parameter itself accepts
  only a non-boolean built-in integer in **[1, 16 777 216]**
  (`MAX_LINE_BYTES_CEILING`), validated before the log is opened, so
  the probe arithmetic can never overflow an index-sized integer —
  arbitrary positive integers are NOT accepted), so an oversized or
  unterminated record is **never materialized in full**. A record whose
  content (raw bytes; LF or CRLF terminator excluded) exceeds
  `max_line_bytes` is counted `oversized_line` and **terminates
  ingestion — fail closed**: skipping past it would require unbounded
  scanning for the next record boundary. Total read work is bounded by
  `max_rows × (max_line_bytes + 2)` bytes.
- Every rejection is accounted by a fixed reason vocabulary; the report
  carries **counts only** — row payloads are never copied anywhere.
- **Parser depth totality**: a row nested beyond the JSON parser's
  recursion limit (while inside the byte ceilings) follows the same
  malformed-row containment policy — its ``RecursionError`` is caught
  at the row decode only, counted ``malformed_json``, and the run
  continues (recursion depth recovers when the parser unwinds). This is
  the reader's own row policy, not a family-wide convention; a
  ``RecursionError`` outside the row-decode seam still propagates.
  Consumers of the shared reader (NP2 monitor, NP6 replay-lab log path)
  inherit the containment.

## Report contract

Deterministic JSON: sorted keys, fixed separators, `schema` +
configuration echo + row/rejection accounting + split boundary +
per-model metrics + explicit non-claims. **No wall-clock timestamps.**
Byte-identical across repeated runs on the same input. Serialized size
is checked against a **64 KiB ceiling — fail closed** (`ReportTooLargeError`).

## Write boundary

- Default output is **stdout** (unchanged: `sys.stdout.write` of the
  canonical serialization).
- `--output` must resolve **inside the input-log directory** (mirrors
  `nextness_metrics`; `WriteOutsideLogDirError` otherwise) and must
  **never** resolve inside the repository `data/` tree — even when the
  input log itself lives there. Reports about `data/` logs go to stdout.
- **Input-identity guard** (same convention as NP6/NP8): `--output` may
  never name or alias the input log itself. Refused by **resolved path**
  (covers the direct path, lexical variants like `sub/../log.jsonl`, and
  symlink aliases — resolution targets are compared, not link or segment
  names) and by **file identity** (`os.path.samefile`: device + inode /
  file ID, which catches existing hard links whose paths differ). Any
  failure to verify identity is itself a refusal — **fail closed**,
  never a fall-through. Refusal exits 4 with one concise `error:` line,
  no traceback; the input log is left byte-identical and no report is
  written. Ordinary sibling outputs — nonexistent or existing non-alias
  files — remain allowed.
- **Residual race, stated precisely**: identity is verified at
  validation time; the later write does not re-verify. A concurrent
  actor replacing the output path between validation and write can still
  redirect the write. The guard defends against aliases that exist when
  it validates; it does not claim to eliminate the validation-to-write
  (TOCTOU) interval.
- **File-output byte contract**: the report file is written as explicit
  UTF-8 **bytes** — exactly `serialize_report(report).encode("utf-8")`,
  with a single trailing LF — on every platform. Windows newline
  translation (`\n` → `\r\n`, the old `write_text` behavior) can never
  alter the canonical bytes, so file reports are byte-identical across
  platforms and match the documented byte-identity guarantee.
- **Destination boundary on operational write failure** (audited 2026-07-17;
  stage-pinned in the focused tests): a failure **at or before the binary
  open** — an unwritable or read-only destination, an absent or invalid
  parent — preserves any existing destination byte-identically and creates
  no output. **After a successful direct non-atomic open**, a later failure
  may truncate the destination or leave partial output (the whole-buffer
  write truncates on open, so a failed write leaves an empty file). A
  **close-time failure** may leave the complete canonical report bytes
  in place even though the run reports the operational-failure exit —
  a present file does not imply a successful run. Supplied-input
  preservation on these lanes is bounded by the existing validation-to-write
  (TOCTOU) non-claim. No atomic-write behavior is provided or implied.
- No network, HTTP, ZMQ, Ollama or model calls anywhere in the module
  (statically auditable: the only imports are stdlib + `TOKEN_NAMES` /
  `WriteOutsideLogDirError` from `scripts.nextness_observer`).

## CLI exit codes

Expected failures print one concise `error:` line to stderr — **never a
traceback**. Only the expected error types are caught; unexpected
programming errors propagate loudly rather than masquerade as clean
exits.

| Code | Meaning |
|---|---|
| 0 | success |
| 2 | validation failure: missing log file or out-of-bounds configuration (typed `PredictorInputError`; argparse usage errors also exit 2) |
| 3 | insufficient history for a train/holdout split |
| 4 | output-path failure: write-boundary violation, input-log alias (direct path / lexical / symlink / hard link / unverifiable identity), or unwritable target |
| 5 | serialized report exceeds the 64 KiB ceiling (fail closed) |

**Typed input boundary (predictor pilot)**: the exit-2 catch is exactly
the typed `PredictorInputError` — the four CLI-reachable validation
raises (`max_rows`, `max_line_bytes`, `smoothing`, `holdout_fraction`
bounds) raise it (the `max_line_bytes` message states the
`[1, 16777216]` acceptance range since the boundary-totality repair;
the other three message texts are unchanged). A plain
`ValueError` — like any exception outside the documented catch
classes — **propagates** rather than being reported as a concise input
failure (test-pinned); `evaluate_predictions`' equal-length/non-empty
invariant deliberately stays a plain `ValueError` for exactly that
reason. Direct-Python note: callers catching `ValueError` remain
compatible because `PredictorInputError` subclasses it, but the exact
exception type at those four sites is now `PredictorInputError` —
including where importers re-expose the reader bounds (the replay lab's
`--max-rows`/`--max-line-bytes` lanes still exit 2 through its own
documented broad catch; test-pinned there). This is a predictor-only
decision; no family-wide convention is implied.

## Relationship to what comes next

NP2 (`nextness_monitor`) consumes this instrument's outputs to measure
*when the predictor should not be trusted* (uncertainty, surprise,
calibration drift, abstention). Neither package changes observer
semantics, vocabulary, or the engine.
