# Nextness Contract Guard (NP7)

**Tests**: `tests/test_nextness_contracts.py` (test-owned; no runtime module)
**Guards**: NP1 (`nextness-predictor-v1`) · NP2 (`nextness-monitor-v1`) · NP5 (`nextness-evaluation-v1`) · NP6 (`nextness-replay-lab-v1` / `nextness-replay-protocol-v1`)
**Status**: drift tripwire only — runs under existing pytest discovery, changes nothing

## What this is

A test-owned compatibility layer that makes **silent** schema or
metric-contract drift among the Nextness instruments **loud**. Four
mechanisms:

1. **Golden byte-stability.** Canonical artifacts recorded from the
   live emitters over a small non-trivial synthetic log (12 accepted
   rows plus blank / malformed / duplicate-generation / unknown-token
   records, so the accounting is exercised) are embedded in the test
   file as string literals. Every regeneration must be byte-identical.
   The literals live **inside the `.py` file** deliberately: Python
   source decoding normalizes physical line endings, so the pins are
   immune to git checkout newline translation on any platform — no
   fixture files, no `.gitattributes` dependency.
2. **Vocabulary and constant freezes.** The contracts the packages
   promise each other are pinned exactly: `TOKEN_NAMES` including order
   (order is the dominant-token tie-break), `ABSTAIN_REASONS` including
   order (order is the decision precedence), `REJECT_REASONS`,
   `MODEL_ALLOWLIST`, `OBSERVATION_FIELDS`, the evaluator's reason /
   verdict / check vocabularies, every 64 KiB ceiling, `ECE_BINS`, NP1
   bounds, lab bounds, the monitor's 6-dp rounding, the evaluator's
   derived tolerances, and the mirrored constants
   (`evaluator.SURPRISE_BITS_MAX == monitor._MAX_SURPRISE_BITS`,
   `NLL_BITS_MAX == -log2(1e-300)`) that comments elsewhere promise are
   "kept in sync".
3. **Emitter ↔ validator structure locks.** Live `build_report` /
   `build_receipt` output key sets must equal the NP5 validator's
   expected key sets at every nesting level, and the live artifacts
   must validate — so the two sides of each schema cannot drift apart
   even in ways the byte goldens might miss.
4. **Compatibility corpus.** The goldens double as the
   backward-compatibility corpus (they must keep validating in every
   future revision), and a 16-case mutation table over them checks
   that unknown variants — schema bumps, extra keys, missing sections,
   out-of-bound values, bool-as-int — stay **fail-closed** at the NP5
   and NP6 input boundaries.
5. **Correction-semantics locks** (added with the 2026-07-15 Jack
   delta): mixed-model series can never silently compute block
   recovery (`model_not_stable`), changed-config series can never
   silently compute abstention transitions (`config_not_stable`), an
   oversized holdout can never reach observation allocation
   (spy-verified non-invocation of `replay_observations`), and a
   hard-link output alias to an input is refused with the input
   byte-intact.

## Drift-detection receipts (failing-first)

Each of these emitter mutations was applied temporarily and the guard
failed, then the original was restored and the guard passed (29/29):

| Synthetic drift | Result |
|---|---|
| monitor rounding 6 → 5 dp | caught (2 failures) |
| `REPORT_SCHEMA` bumped to v1.1 | caught (6 failures) |
| extra field added to receipts | caught (2 failures) |
| evaluator cross-check tolerance 1e-6 → 1e-5 | caught (2 failures) |

## Honest scope and limitations

- The guard runs **when the test suite runs** (CI and local); it
  detects drift at test time, not at artifact-read time. Read-time
  fail-closed behavior lives in the instruments themselves (NP5/NP6
  validators) — the guard checks that behavior stays present.
- It guards these packages' contracts with **each other**; it does not
  guard the observer's log format beyond what `read_dominant_sequence`
  consumes, and it cannot see drift in packages it does not import.
- Pytest discovery (`pytest.ini` `testpaths = tests`) already collects
  the guard; **no workflow, required-check or configuration change is
  made or needed.**
- No consciousness, awareness, phenomenology or biological-equivalence
  claim; the guard is bookkeeping about schemas.

## Regeneration record

- **2026-07-15 (Jack HOLD delta)**: `GOLDEN_EVALUATION` regenerated
  after the NP5 corrections. Sole delta (7 lines): the new
  `recovery.series_comparability` field, `computed` with
  `{config_stable: true, model_stable: true}` for the single-receipt
  golden series. Every other golden literal byte-unchanged (verified:
  the NP1/NP2 emitters were untouched and the NP6 corrections do not
  alter report content for valid inputs). Frozen vocabularies extended
  in step: `NOT_COMPUTABLE_REASONS` + `model_not_stable` /
  `config_not_stable`; numeric freezes + `evaluator.MAX_DETAIL_ITEMS`,
  `lab.MAX_PROTOCOL_BYTES`, `lab.MAX_DETAIL_ITEMS`,
  `lab.MAX_LABEL_CHARS`.

## Deliberate contract changes (regeneration procedure)

A guard failure after an intentional contract change is the guard
working. To regenerate:

1. Build the golden log exactly as embedded (`GOLDEN_LOG` literal).
2. Re-run the four emitters over it in dependency order (NP1 report →
   NP2 receipt via `observations_from_log(log, "first_order")` +
   `build_receipt` with `MonitorConfig()` defaults → NP5 evaluation
   over the two recorded files → NP6 lab over log + embedded protocol),
   serializing with each package's own `serialize_*` and writing files
   with `newline=""`. The model/config choices are also noted in the
   comment beside each literal.
3. Replace the corresponding `GOLDEN_*` literals, and update the frozen
   vocabulary/constant assertions that changed.
4. State in the PR body **which contract changed and why** — the diff
   of the goldens is the reviewable receipt of the drift.
