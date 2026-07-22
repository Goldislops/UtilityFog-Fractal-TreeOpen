# Nextness Monitor Contract (NP2)

**Module**: `scripts/nextness_monitor.py` · **Tests**: `tests/test_nextness_monitor.py`
**Schema**: `nextness-monitor-v1` · **Status**: functional metacognition only — measures, never acts

## What this is

The second rung of the functional-self-awareness ladder: **can the
system detect when its own predictor should not be trusted?** The
monitor consumes NP1's bounded prediction observations and emits one
deterministic receipt saying how confident the predictor was, how
surprised it turned out to be, whether it is inside its calibrated
regime, and — centrally — whether its current output should be
**abstained from**.

**"Abstain" means exactly one thing**: *do not treat this prediction as
evidence.* It triggers no action, no tuning, no orchestration, nothing.
The receipt is a statement about trustworthiness, not a control signal.

## Explicit non-claim (load-bearing, embedded in every receipt)

Nothing here is, or is evidence of, awareness, sentience or phenomenal
experience. It is bookkeeping about a counting model's error statistics
— the functional shadow of "knowing you might be wrong", which is the
only part that can be tested.

## Receipt fields (closed allowlist)

| Field | Type | Meaning |
|---|---|---|
| `schema` | const | `nextness-monitor-v1` |
| `model` | enum | one of `empirical_prior` / `persistence` / `first_order` (fixed allowlist; fail closed) |
| `observation_count` | int | validated observations consumed |
| `mean_confidence` | float | mean top-1 probability |
| `mean_surprise_bits` | float | mean −log₂ P(actual), bounded ≤1000 (underflow guard) |
| `rolling_calibration_error` | float | fixed-bin ECE over the last `window` observations (same 10-bin scheme as NP1) |
| `distribution_drift_bits` | float | Jensen-Shannon divergence (bits), recent window vs training reference — **reuses `nextness_metrics.js_divergence`**, no new divergence code. The bridge's recent counts cover **exactly the latest `window` holdout observations** (never the whole holdout, so an older stable prefix cannot dilute a late regime change) |
| `sufficiency` | enum | `sufficient` / `insufficient` |
| `abstain` | bool | see decision procedure |
| `abstain_reason` | enum | fixed vocabulary below |
| `input_reduced` | bool | unknown observation fields were discarded |
| `discarded_field_count` | int | how many |
| `config` | object | bounded threshold echo |
| `non_claim` | const | the statement above |

No free-form text, no internal monologue, no prompt text, no source
payloads — numbers, enums and booleans only. Sorted-key deterministic
JSON, no wall-clock timestamps, byte-identical across runs, **64 KiB
fail-closed ceiling**.

## Abstention decision (fixed precedence; first match wins)

1. `insufficient_history` — fewer than `min_history` observations.
2. `unseen_state` — the latest previous token was never seen in
   training (for `first_order`: never a transition source).
3. `low_confidence` — latest top-1 probability below threshold.
4. `calibration_drift` — rolling ECE above threshold.
5. `distribution_shift` — JS divergence (recent vs reference) above
   threshold.
6. `none` — no abstention; the prediction may be treated as evidence.

**Thresholds are configuration, not constants of nature**: every one is
bounded, documented, echoed in the receipt, and none is claimed to be
universal (`min_history` ∈ [5, 10000], `window` ∈ [5, 10000], the three
float thresholds ∈ (0, 1)).

## Input contract

- Observations must be built-in dicts with exactly the allowlisted
  fields `confidence`, `hit`, `p_actual`, `prev_seen`; unknown fields
  are discarded and honestly counted (`input_reduced`); missing or
  invalid required fields **fail closed** with a typed error. All four
  fields are required — a missing `prev_seen` is **never defaulted to
  `True`** (that would mask `unseen_state` abstention).
- Numbers must be **exact builtin `int`/`float`**: bools, non-finite
  values and custom numeric subclasses are rejected through
  `MonitorInputError` *before* any conversion hook
  (`__float__`/`__index__`) can run.
- Container guards: dict subclasses, hostile `__str__`/`__float__`
  objects, bools-as-numbers, NaN/inf, out-of-range probabilities and
  astronomically large integers are all rejected *before* any
  stringification or arithmetic can touch them.
- Reference/recent token counts: built-in dicts, known vocabulary only,
  non-negative built-in ints.
- Configuration: `min_history` and `window` must be **exact builtin
  ints** within their documented ranges (bool/float/subclasses rejected);
  the bridge's inherited NP1 options (`smoothing`, `holdout_fraction`)
  keep NP1's exact bounds and fail closed on violation.

### Exact-string field boundary (reachability stated separately)

**PUBLIC CLI lane** — observations reach the monitor from the JSONL log
via NP1's bounded reader, so every record key is a `json`-produced
builtin `str`. **No CLI-reachable behavior changes**, and every public
diagnostic is byte-identical.

**DIRECT Python-API lane** — a caller may pass records built in memory,
whose keys are arbitrary objects. A proven-exact record is therefore
traversed by **item iteration only**: just the exact builtin `str` keys
on the allowlist are copied into a **fresh owned dict**, and every
required field is read from that dict alone. A foreign key is never
hashed, compared, stringified or represented, and counts as exactly one
discarded field under the existing discard-and-count policy.

This is a **soundness** boundary, not only a hook boundary. The previous
`set(record)` / `record["confidence"]` / `record.get("hit")` /
`"prev_seen" in record` sequence hashed the field names and compared them
against whatever shared their buckets, so a non-`str` key whose
`__hash__` collided with a field name had its `__eq__` invoked — and an
`__eq__` returning `True` let that foreign key **satisfy the field and
supply its own value as the reading the receipt is computed from**. All
four required fields were substitutable this way; a colliding key whose
`__eq__` raised escaped instead. A genuine field coexisting with a
colliding foreign key now wins, and the foreign key is discarded.

**The two supplied-value type-refusal diagnostics repaired in this batch
are hook-free**: they inspect the rejected value no further than exact
type identity and never inspect its class. This is **not** a module-wide
hook-free-totality claim; other DIRECT-API validation surfaces and the
caller-controlled outer `records` sequence remain outside Batch 4.

Reading `type(value).__name__` is what made those two unsafe: `__name__`
is an overridable **metaclass** property, so its getter can run
caller-controlled code from inside error formatting and escape the typed
refusal. Builtin type names now come from a bounded literal identity
table scanned by `is` comparison; anything not on it is described as
`non-builtin value`. The scan is deliberately **not** a dictionary
lookup — `mapping.get(type(value))` would hash the caller's class object
and could itself execute a hostile metaclass `__hash__`, reopening the
hole this repair closes.

## CLI expected-failure contract (inherited from NP1)

`0` success · `2` validation failure (missing log file or out-of-bounds
options) · `3` insufficient history · `5` receipt would exceed
`MAX_RECEIPT_BYTES` (`ReceiptTooLargeError`, fail closed). Every
expected failure prints one concise `error:` line to stderr — never a
traceback. The monitor writes no files on any path, success or failure.

**Exit 5 is defensive completion** (Jack's policy decision on the
2026-07-19 output-ceiling exactness audit), NOT a claim that the
current fixed public receipt shape naturally reaches the 64 KiB
ceiling — it cannot; the lane exists so that if the receipt shape ever
grows, the refusal is the family's concise exit-5 form instead of a
raw traceback. Direct `build_receipt` callers still receive the typed
`ReceiptTooLargeError` unchanged.

**Typed input boundary (monitor pilot)**: the exit-2 catch is exactly
the typed `MonitorInputError` — the two CLI-reachable validation raises
(smoothing and holdout-fraction bounds) raise it with their message text
unchanged. A plain `ValueError`, like any exception outside the
documented catch classes, **propagates** rather than being reported as a
concise input failure (test-pinned alongside the standing `RuntimeError`
propagation pin). Direct-Python note: callers catching `ValueError`
remain compatible because `MonitorInputError` subclasses it, but the
exact exception type at those two reclassified sites is now
`MonitorInputError`. This is a monitor-only decision; no family-wide
convention is implied.

## A finding worth keeping (from the test suite)

With NP1's default Laplace smoothing (α = 1.0 over 16 tokens), a
predictor that is *perfectly right* on an alternating sequence still
states only ≈0.605 confidence — systematically under-confident — and
the monitor correctly reports that gap as `calibration_drift`. The
metacognition layer catching its own predictor's smoothing bias on day
one is precisely the kind of receipt this package exists to produce
(and why thresholds are configuration: light smoothing removes the
gap). Kept as a permanent regression test.

## Safety

No tuning, orchestration, engine, Swarm Hunter or Lane-A imports (only
`nextness_predictor`, `nextness_metrics`, `nextness_observer` and
stdlib). Offline; no network. The monitor **writes no files** — the
receipt goes to the caller or stdout.
