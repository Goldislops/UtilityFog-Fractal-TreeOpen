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
| `distribution_drift_bits` | float | Jensen-Shannon divergence (bits), recent window vs training reference — **reuses `nextness_metrics.js_divergence`**, no new divergence code |
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
  invalid required fields **fail closed** with a typed error.
- Container guards: dict subclasses, hostile `__str__`/`__float__`
  objects, bools-as-numbers, NaN/inf, out-of-range probabilities and
  astronomically large integers are all rejected *before* any
  stringification or arithmetic can touch them.
- Reference/recent token counts: built-in dicts, known vocabulary only,
  non-negative built-in ints.

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
