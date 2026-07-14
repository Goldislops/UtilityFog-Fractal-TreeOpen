# Nextness Artifact Validation Contract (NP9)

**Module**: `scripts/nextness_artifact_validation.py` · **Tests**: `tests/test_nextness_artifact_validation.py`
**Validates**: `nextness-evaluation-v1` · `nextness-replay-lab-v1` · `nextness-evidence-packet-v1`
**Status**: validation only — accepts or rejects, never scores, repairs or normalizes

## What this is

Full public **structural** validators for the three recorded artifact
schemas that previously had none:

| Public function | Artifact | File loader |
|---|---|---|
| `validate_evaluation_artifact` | NP5 evaluation | `load_evaluation_artifact` |
| `validate_lab_artifact` | NP6 lab report | `load_lab_artifact` |
| `validate_evidence_packet` | NP8 evidence packet | `load_evidence_packet` |

Each validator either returns a **sanitized builtin copy** (the
caller's object is never mutated and never aliased into the result) or
raises `ArtifactValidationError` with a deterministic, field-anchored
message. The file loaders add a 1 MiB pre-parse bound, duplicate-JSON-
key rejection and a recursion fail-closed guard. No library function
writes to the filesystem.

## Validation principles (enforced, tested)

Exact builtin types everywhere (`bool` never passes as `int`; no
conversion hook ever runs; hostile dict/list/str subclasses are
rejected before any iteration or member access); finite numbers only
(NaN/infinity/overflow-scale integers rejected); **exact key sets** at
every nesting level (unknown and missing keys both fail closed); fixed
vocabularies for every enum; deterministic error messages with no
`repr` of hostile values; fixed validation depth by construction
(per-section functions, no recursion over unknown structure).

## What structural validation establishes — and what it cannot

**Establishes**: the object has exactly the v1 shape the live emitters
produce — envelope forms (`computed` / `not_computable` with the fixed
reason vocabulary), tri-state verdict vocabularies, chronology /
series-comparability structures, provenance slots with exact `provided`
booleans, SHA-256 forms and byte-count ranges, bounded detail lists
**whose truncation flags must agree with their lists and tallies**, v1
configuration constants and tolerances, and the cross-field identities
the artifact itself records:

- reason counts and verdict tallies sum to their populations;
- `abstention_step_rate` equals the reason-count identity exactly;
- `final_abstain` ⟺ `final_reason != "none"`; trailing-run presence ⟺
  final abstention; first-non-abstain null ⟺ all steps abstained;
- run/trailing sums match abstained steps (untruncated case only —
  truncation hides the identity and it is then *not* checked);
- gate coherence in recovery: a failed chronology witness forbids
  computed order-dependent sections **and pins their not-computable
  reason to `order_not_witnessed`** (the order gate runs first in the
  emitter); unstable model/config series forbid their gated sections;
- `assumptions` must match exactly the computed sections that use them;
- evaluation ingestion identities (`train + holdout == accepted`,
  `rows_read >= accepted`); lab accounting identities (rejections sum,
  `train + holdout_steps == accepted`);
- packet roles unique and in canonical order; per-role validation-depth
  vocabulary; link statements' **form coherence** (`verified` requires
  equal recorded hashes, `broken` requires unequal — validating the
  statement, never converting a broken link into success);
- `proper_score_rankings_agree` must match the recorded rankings;
  rankings must be permutations of the model allowlist.

**Cannot establish** (documented non-claims): prediction-metric
correctness (needs the underlying report/receipts), provenance-hash
truth against real bytes (NP8's job), replay-decision correctness
(needs the source log), and any identity hidden by truncation.
Structural validation is not provenance verification.

## Cross-section couplings deliberately not enforced

`latest_rolling_calibration_error`'s computability depends on the
chronology witness recorded in a different section; the evaluator's
per-receipt evidence is not recorded in the evaluation artifact, so
several such couplings are real in the emitter but only partially
recoverable from the artifact. The validator enforces the couplings
listed above and no others; nothing outside that list is claimed.

## Test program

Live producer-generated artifacts for all three schemas (plus both
partial-evaluation variants) pass and round-trip unmutated; one
hand-written independent golden packet passes; **60 table-driven
single-field mutations** (26 evaluation / 19 lab / 15 packet) each fail
at the expected boundary — covering hostile subclasses, duplicate keys,
missing/extra fields, bool-as-int, NaN/infinity/huge integers, wrong
vocabularies, count/rate disagreements, ordering/duplicate-role faults
and truncation contradictions; seeded stdlib random corruption (3
seeds × 40 corruptions × 3 validators) never escapes the typed error;
error messages are deterministic across repeated validation; bounded
file loaders reject oversized, duplicate-key and pathologically nested
files.

## Safety

Offline; no network; imports only the Nextness instrument modules and
stdlib. Validation never mutates inputs, never writes files, and is
deterministic with no timestamps, randomness or environment dependence.
