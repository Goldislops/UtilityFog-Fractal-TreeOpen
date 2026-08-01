# Nextness CLI Failure Contracts — Cross-Module Fact Table

**Status**: descriptive reference, source-audited. **This note records current
behavior; it does not propose, request, or imply harmonization.** The exit-code
maps below are **five distinct code sets across seven CLIs, not one convention**,
and each map is individually documented, tested, and (where noted) retained for
compatibility. Any future change to any lane is its own gated decision.

Audited against the source at the merge of PR #372 (typed metrics output-write
lane). Companion evidence: the 2026-07-17 CLI failure-contract audit (65 public
subprocess probes; receipts in the operator's audit records) and the focused
test suites named per row. The seventh row (`nextness_evidence_campaign`) was
added with the campaign implementation, per the frozen contract in
`docs/NEXTNESS_EVIDENCE_CAMPAIGN_CONTRACT.md` section 3.11.

## The seven maps

| CLI (`scripts/…`) | Exit map | Success | Data/input failures | Pre-write safety refusal | Operational write failure | Ceiling / oversize | stderr prefix |
|---|---|---|---|---|---|---|---|
| `nextness_predictor` | **0/2/3/4/5** | 0 (report → stdout or `--output`) | 2 missing log, out-of-bounds config (typed `PredictorInputError`; plain `ValueError` propagates — predictor typed-boundary pilot) · 3 insufficient history (`InsufficientHistoryError`) | 4 (`WriteOutsideLogDirError`: containment, `data/` tree, input alias by resolved path + `os.path.samefile`, fail-closed identity) | 4 (write-lane `OSError`: directory target, unwritable destination) | 5 (`ReportTooLargeError`, 64 KiB fail-closed) | `error:` |
| `nextness_metrics` | **0/1/2/3/4** | 0 (summary → stdout; derived JSONL written) | **1 missing log** · 2 malformed JSONL / invalid-UTF-8 log / bad config / **strict-domain violation** / **input-work-bounds refusal** (typed `MetricsInputError` — §9.4 strict input domain: JSON-constant rejection, unit fields in [0,1] with absent→0.0 policy, token-count shape, finite params, pre-write whole-row finiteness (recursive), finite-computability totality on unit/helper/parameter surfaces (oversized integers typed, never OverflowError), decoder conversion-limit ValueError and parser-depth RecursionError both located-typed at the narrow decode boundary; §9.5 input-work bounds: `--max-rows` (default 100000, ceiling 1000000) / `--max-line-bytes` (default 65536, ceiling 16777216 — the shared `MAX_LINE_BYTES_CEILING`) over raw physical records and content bytes (LF/CRLF excluded), bounded binary `readline(max_line_bytes+2)` pre-materialization reads, excess rows = located typed refusal — **never prefix truncation** (metrics summarizes a COMPLETE run); plus the invalid-UTF-8 wrapping boundary; `FileNotFoundError` race lane retained; plain `ValueError` propagates) | **3 with `safety error:`** (`WriteOutsideLogDirError`: containment, directory target, input alias, fail-closed identity — all pre-read, pre-compute) | **4** (`MetricsOutputWriteError`: typed `OSError` region = output-parent creation + binary open/write/close) | input bounds ride the **2**-lane (typed, located); — no serialized **output** ceiling (unchanged by §9.5) | `error:`; **`safety error:` on the 3-lane only** |
| `nextness_monitor` | **0/2/3/5** | 0 (receipt → stdout; writes no files on any path) | 2 missing log, typed `MonitorInputError` (plain `ValueError` propagates — monitor typed-boundary pilot) | — (no output lane exists) | — | 5 (`ReceiptTooLargeError`, 64 KiB fail-closed — **defensive completion**: the current fixed public receipt shape cannot naturally reach the ceiling; no public reachability is claimed) | `error:` |
| `nextness_evaluator` | **0/2/4/5** | 0 (evaluation → stdout or `--output`) | 2 missing/oversized/malformed/unknown-variant artifact, `EvaluatorInputError` | 4 (`WriteOutsideLogDirError`: primary-dir containment, `data/` tree, alias of ANY supplied role, fail-closed identity) | 4 (write-lane `OSError`) | 5 (`EvaluationTooLargeError`) | `error:` |
| `nextness_replay_lab` | **0/2/3/4/5** | 0 (lab report → stdout or `--output`) | 2 missing input, malformed/oversized protocol, or out-of-bounds reader configuration — all typed `LabInputError` (reader bounds translated from `PredictorInputError` at the reader call, message byte-identical; plain `ValueError` propagates — replay-lab typed-boundary pilot) · 3 insufficient history | 4 (`WriteOutsideLogDirError`: containment, both-input alias, fail-closed identity) | 4 (write-lane `OSError`) | 5 (`LabReportTooLargeError`) | `error:` |
| `nextness_evidence_packet` | **0/2/4/5** | 0 (packet → stdout or `--output`) | 2 none/missing/oversized artifact — typed `PacketInputError`, incl. wrapped validators (plain `ValueError` propagates — evidence-packet typed-boundary pilot) | 4 (`WriteOutsideLogDirError`: primary-dir containment, alias of any of the six roles, fail-closed identity) | 4 (write-lane `OSError`) | 5 (`PacketTooLargeError`) | `error:` |
| `nextness_evidence_campaign` | **0/2/3/4/5/6/7** | 0 (one concise `published:` line; the eight-file set + outer manifest promoted by one same-directory rename) | 2 typed `CampaignInputError` (option bounds, unknown `receipt_config_label`, complete-log refusal, provenance-not-verified, `contradicted` cross-artifact coherence refusal) **plus NP6's `LabInputError` caught directly, never translated** (malformed / oversized operator protocol incl. its 64 KiB pre-parse `MAX_PROTOCOL_BYTES` ceiling, the reader-bound translation from `PredictorInputError`, the `MAX_REPLAY_STEPS` bound; plain `ValueError` propagates) · 3 insufficient history (`InsufficientHistoryError` surfaced from NP1/NP2/NP6, never re-typed) | 4 (`CampaignContainmentError`: workspace existence, resolved-path containment, repository `data/` exclusion applied independently to every campaign path — log, protocol, final directory, staging parent and the created staging directory, so an ancestor-of-`data/` workspace confers no exemption — absent-final-directory requirement, and input alias via resolved-path comparison plus `os.path.samefile` where both ends exist; a containment or identity inspection that cannot complete is itself a refusal) | 6 (`CampaignStagingError`: staging-directory creation, input copy, artifact write) · 7 (`CampaignPublicationError`: staging→final rename failure or an OS-reported destination collision; the unobservable-replacement race is a standing non-claim) | 5 (the five instrument `*TooLargeError` serialization ceilings, surfaced unchanged; typed `CampaignCeilingError` for a size-preflight-confirmed input over NP5/NP8 `MAX_INPUT_BYTES` or NP8 `MAX_LOG_BYTES`, or the campaign manifest over `MAX_CAMPAIGN_MANIFEST_BYTES` = 64 KiB — never decided by interpreting an instrument's typed input exception) | `error:` |

Monitor's exit 3 is `InsufficientHistoryError` — the same *insufficiency*
semantics as predictor and replay lab; the evidence campaign surfaces the same
class from the instruments it composes, on the same code. The evaluator
**deliberately has no exit 3**: "not enough evidence" is a typed
`not_computable` result inside a successful evaluation, never a CLI failure.
Non-CLI modules (`nextness_observer`,
`nextness_calibration`, `nextness_artifact_validation`) expose no `main()`/
argparse surface and belong to no CLI exit convention.

## The code-3 semantic collision (fact, not defect)

Exit **3 means two different things** in this family: **insufficiency**
(predictor, monitor, replay lab, evidence campaign) versus **pre-write safety refusal** (metrics,
with the distinct `safety error:` prefix). **Metrics' exit 3 is intentionally
retained for documented compatibility**: the in-source PR #142-lineage comment
("Return distinct non-zero code so callers can distinguish safety refusals from
data errors"), the design-doc §9.1/§9.2 record, and exact-code regression tests
all pin it. Renumbering it would be a breaking interface change and is exactly
the kind of false uniformity this note exists to prevent. Likewise, missing
input is **1 in metrics and 2 everywhere else** — documented per module, pinned
per module, not to be "fixed" into sameness.

## Bounded shared invariants (exercised lanes only)

Across the **exercised ordinary expected-failure lanes** (the 2026-07-17 audit's
public probe set plus the focused suites), every ordinary expected failure
prints **exactly one concise stderr line** with the module's declared prefix
and produces **no traceback**.

Output and input preservation are **lane-specific**, not universal:

- Exercised ordinary expected failures emit their documented concise error
  form and leave supplied inputs unchanged **in the non-concurrent probes**
  (the TOCTOU non-claim below governs concurrent interference).
- **Pre-write refusals and at-or-before-open failures** create no output and
  preserve an existing destination — nothing was truncated.
- **Once a direct non-atomic output open has succeeded**, a later write or
  close failure **may leave a truncated or partial destination**.
- **Therefore no cross-module whole-or-partial-output prohibition is
  claimed.** Each module's preservation boundary is exactly its own write
  path's, per its own documentation.

This statement is **bounded to those exercised lanes** — it is an observed and
test-pinned property, not an unconditional theorem about unprobed branches.

**Argparse is excluded from that invariant**: every CLI's usage error exits via
argparse's own `SystemExit(2)` — bypassing `main()`'s return path — with
**multi-line** `usage:`-prefixed stderr. Five module docstrings state the
carve-out ("argparse's own usage errors also exit 2"); the argparse pins in the
focused suites assert code 2, the `usage:` prefix, and no traceback.

## Unexpected-error propagation (bounded by each catch set)

Each CLI's `main()` catches its **documented catch classes**; exceptions
outside those classes propagate. **Zero of the seven `main()` catch clauses
broadly catch plain `ValueError`**:

- The **evaluator catches its typed `EvaluatorInputError`**, and — via
  their typed-boundary pilots — the **monitor catches its typed
  `MonitorInputError` (and, since the boundary-totality repair, its
  typed `ReceiptTooLargeError` → exit 5, defensive completion)**, the
  **predictor its typed `PredictorInputError`**, **metrics its typed
  `MetricsInputError` (plus the `FileNotFoundError` validation-to-read
  race lane)**, the **evidence packet its typed `PacketInputError`**,
  and the **replay lab its typed `LabInputError`** — each alongside its
  other typed classes. The **evidence campaign catches its own five
  typed classes** (`CampaignInputError`, `CampaignContainmentError`,
  `CampaignCeilingError`, `CampaignStagingError`,
  `CampaignPublicationError`) **together with the instrument classes it
  deliberately surfaces** — NP6's `LabInputError` caught directly and
  never translated, `InsufficientHistoryError`, and the five
  `*TooLargeError` serialization classes — while **`EvaluatorInputError`
  and `PacketInputError` are deliberately excluded** from its catch set:
  the campaign's own size preflight settles the input-ceiling lane
  before those loaders ever run, and after a passed preflight such an
  error on a campaign-generated artifact is a loud internal invariant
  failure that propagates.
  In all seven, a plain `ValueError` raised inside the `try` region
  propagates. Each map remains that module's own decision, per this
  document's non-harmonizing rule — the shared end state is a fact, not
  a convention.
- **Inner input-validation regions may still deliberately catch or
  translate base `ValueError` locally.** The six typed `main()` clauses
  above are the top-level catch boundary; beneath them, some tightly
  scoped validation regions retain base-class wrappers by design: the
  replay lab's protocol loader catches base `ValueError` in its
  JSON-parse and `MonitorConfig.validate` input-validation regions
  (→ `LabInputError`); the evidence packet's bounded JSON loader
  retains a scoped base-`ValueError` wrapper (→ `PacketInputError`);
  the evaluator's artifact loader and exact-float helpers do the same
  (→ `EvaluatorInputError`). Other inner boundaries are exact-class:
  metrics wraps the read-region `UnicodeDecodeError` and the
  malformed-JSONL `json.JSONDecodeError`; the replay lab translates the
  shared reader's `PredictorInputError` at the reader call (message
  byte-identical, cause preserved). **These existing local boundaries
  are distinct from the six `main()` catch clauses and were not
  normalized by the typed-boundary train.**
- The focused propagation pins prove **their exact lanes only**: a sentinel
  `RuntimeError` propagating in predictor, monitor, evaluator, replay lab,
  evidence packet and the evidence campaign, a read-side `OSError`
  propagating in metrics
  (PR #372's pin), and a sentinel plain `ValueError` propagating in the
  monitor, the predictor, metrics, the evidence packet, the replay
  lab and the evidence campaign (the pilots' pins; the campaign's pin also
  proves its `EvaluatorInputError` / `PacketInputError` exclusions
  propagate after a passed size preflight). They prove **their named seams only** — a
  sentinel injected at the established build/core seam of each module —
  not every possible origin of a plain `ValueError` (a plain
  `ValueError` arising *inside* one of the scoped inner validation
  regions above is translated there by design, never reaching
  `main()`).

**No claim is made that every possible programming error propagates**;
propagation is exactly the complement of each CLI's documented catch set,
per the maps above.

## Identity-inspection fail-closed rows

Every output-identity guard (predictor, metrics, evaluator, replay lab,
evidence packet) treats a failed identity inspection (`os.path.samefile`
raising) as a **refusal, never a fall-through** — mapped to each module's own
safety code (metrics 3 + `safety error:`; the others 4 + `error:`). Previously
source-visible only; now test-backed by the identity-inspection pins added
alongside this note (targeted argument-conditional patches, following the
calibration stat-probe idiom). The evidence campaign follows the same rule on
its resolved-path + `os.path.samefile` alias and containment lane: an
inspection that cannot complete is itself a refusal (4 + `error:`), never a
fall-through (pinned by its identity-inspection and hard-link-alias tests).

## Standing non-claims

- The **validation-to-write TOCTOU interval remains a non-claim** everywhere:
  identity and containment are verified at validation time; a concurrent actor
  replacing a path between validation and the later direct write can still
  redirect that write. No module claims otherwise (see each guard's docstring
  and, for metrics, design-doc §9.1/§9.2).
- Metrics makes **no unconditional input-log guarantee** and **no
  destination-preservation guarantee after a successful binary open** (direct
  streamed non-atomic output; see PR #372's final wording).
- Exit-5 ceiling branches exist in source and are covered by focused
  monkeypatched tests. Public reachability has not been established; no
  plausibility claim is made.
- Symlink-dependent lanes are skip-guarded on hosts without symlink privilege
  and exercised on Ubuntu CI.
- The evidence campaign's validation-to-rename destination race is the same
  standing non-claim family: exit 7 applies exactly when the OS reports the
  collision or rename failure; an unobservable replacement of a concurrently
  created empty directory is not claimed to be detected. A handled failure
  cleans its staging directory; a hard kill or power loss mid-run may leave an
  unpublished staging directory behind (uncatchable-termination cleanup is not
  guaranteed).

**This document is descriptive and non-harmonizing.** If any map above stops
matching source, the document is what must change — or the change is a
contract-breaking event that needs its own gate; nothing here licenses either
silently.
