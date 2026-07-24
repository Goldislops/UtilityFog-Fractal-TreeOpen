# Nextness Offline Evidence Campaign Contract (design-only)

**Proposed module (not created by this PR)**: `scripts/nextness_evidence_campaign.py` ·
**Proposed tests (not created by this PR)**: `tests/test_nextness_evidence_campaign.py` ·
**Proposed schema id**: `nextness-evidence-campaign-v1` · **Status**: **DESIGN ONLY**

> **This document is a frozen design contract, not an implementation.** It
> creates no runner, reads no real Medusa artifact, runs no observer, no
> calibration, no engine, no model, and no network call. It only records the
> v1 decisions a future deterministic, offline **evidence campaign runner**
> must satisfy so that a later, separately-gated implementation can be audited
> against a fixed target. No implementation, ready transition, or merge is
> authorised by the pull request that introduces this file. Every "the runner
> …", "the campaign …", "v1 …" statement below is a **proposed future
> obligation**, never a description of existing behaviour.

## 1. What a "campaign" is — and is not

A **campaign** is the deterministic, offline processing of **one
already-recorded** Nextness Observer log into a single provenance-checked
NP1 → NP2 → NP5 → NP6 → NP8 artifact chain, published as one directory of
recorded artifacts.

"Campaign" means **recorded-log artifact processing only**. It explicitly does
**not** mean, and the runner must never perform:

- snapshot collection or any `process_snapshot()` call;
- observer execution (`scripts/nextness_observer.py` is a log **producer**,
  upstream of and outside the campaign — the campaign consumes its output
  read-only, it never runs it);
- calibration experimentation (`scripts/nextness_calibration.py` is a
  sweeping / discriminating experiment orchestrator — a winner-seeking activity
  a descriptive campaign must not do);
- any Medusa runtime, engine (`continuous_evolution_ca.py`), tuning,
  orchestrator, Lane-A, Swarm-Hunter, REST/HTTP, ZMQ, Ollama or model activity.

The campaign is a **composition** of the already-merged Nextness instruments;
it introduces no new metric, no new semantics, and no new decision. It measures
nothing the instruments do not already measure.

## 2. Source grounding (audited current-main interfaces)

This contract is grounded in the following current-`main` modules, their tests
and their contract documents (read-only source audit; **none is modified by
this PR**):

| Role in the chain | Module | Schema id | Contract doc |
|---|---|---|---|
| NP1 predictor report | `scripts/nextness_predictor.py` | `nextness-predictor-v1` | `docs/NEXTNESS_PREDICTION_BASELINE.md` |
| NP2 monitor receipt | `scripts/nextness_monitor.py` | `nextness-monitor-v1` | `docs/NEXTNESS_MONITOR_CONTRACT.md` |
| NP5 evaluation | `scripts/nextness_evaluator.py` | `nextness-evaluation-v1` | `docs/NEXTNESS_EVALUATOR_CONTRACT.md` |
| NP6 replay-lab report / protocol | `scripts/nextness_replay_lab.py` | `nextness-replay-lab-v1` / `nextness-replay-protocol-v1` | `docs/NEXTNESS_REPLAY_LAB_CONTRACT.md` |
| NP8 evidence packet | `scripts/nextness_evidence_packet.py` | `nextness-evidence-packet-v1` | `docs/NEXTNESS_EVIDENCE_PACKET_CONTRACT.md` |
| NP9 structural validators | `scripts/nextness_artifact_validation.py` | — | `docs/NEXTNESS_ARTIFACT_VALIDATION_CONTRACT.md` |
| NP7 contract guard | *(test-owned)* `tests/test_nextness_contracts.py` | — | `docs/NEXTNESS_CONTRACT_GUARD.md` |
| Cross-CLI failure facts | *(reference)* | — | `docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md` |
| Parked sidecar | `scripts/nextness_metrics.py` | *(observer-lineage)* | — |
| Out-of-scope experiment | `scripts/nextness_calibration.py` | — | — |
| Out-of-scope producer | `scripts/nextness_observer.py` | — | — |

Where this contract names a bound, an exit code, a provenance field or a schema
id, it is the value found in that source at `main`. If any such fact later stops
matching source, **this document must change under its own gate** — nothing here
licenses a silent drift, and nothing here proposes to *change* those interfaces.

## 3. Frozen v1 decisions

### 3.1 Inputs

- Exactly **one** already-recorded `nextness_runs.jsonl` log.
- Exactly **one** operator-authored NP6 protocol file
  (`nextness-replay-protocol-v1`).
- Both inputs reside in an **operator-selected external workspace outside the
  repository `data/` tree**. The runner discovers no live snapshots and reads no
  raw snapshot input; the log is a recording, consumed read-only.
- Both inputs remain **byte-identical** across the run: the runner is read-only
  with respect to both, mirroring every instrument's own input-protection
  guarantee (tested byte-for-byte in NP1/NP5/NP6/NP8).

### 3.2 Exact output chain

From the two inputs, the proposed v1 runner produces, in dependency order, the
following recorded artifacts, each the **byte-identical** output of the existing
instrument:

1. one deterministic **NP1 predictor report** (`nextness-predictor-v1`) over the
   log;
2. one deterministic **NP2 checkpoint receipt** (`nextness-monitor-v1`), computed
   for the single monitor configuration selected by an explicit
   `receipt_config_label` (see §3.3);
3. one **NP5 evaluation** (`nextness-evaluation-v1`) over the report and that
   receipt;
4. one **NP6 replay-lab report** (`nextness-replay-lab-v1`) over the log and the
   protocol, **retaining every protocol configuration** for descriptive
   trajectories (see §3.3);
5. one **NP8 evidence packet** (`nextness-evidence-packet-v1`) containing the
   **six** existing roles, one artifact each:
   - `report` — the NP1 report,
   - `receipts` — the NP2 checkpoint receipt,
   - `evaluation` — the NP5 evaluation,
   - `lab` — the NP6 replay-lab report,
   - `protocol` — the operator-authored NP6 protocol (input),
   - `log` — the recorded `nextness_runs.jsonl` (input).

**Provenance gate.** The NP8 packet records, per role, the artifact's schema id,
byte length and SHA-256, and independently recomputes the **four** provenance
links the v1 schemas themselves embed:

| Link | Recorded by | Verified against |
|---|---|---|
| `evaluation_report_sha256` | NP5 evaluation `artifacts.report.sha256` | the report file's bytes |
| `evaluation_receipts_sha256` | NP5 evaluation `artifacts.receipts.sha256` | the receipts file's bytes |
| `lab_protocol_sha256` | NP6 lab report `input.protocol_sha256` | the protocol file's bytes |
| `lab_sequence_sha256` | NP6 lab report `input.sequence_sha256` | the log's accepted dominant-token sequence, recomputed through NP1's bounded reader with the lab's recorded `max_rows` / `max_line_bytes` |

**All four links must be `verified`** (byte-level hash match) before publication
succeeds. A `broken` link, or a link that the packet types `not_computable`
because a counterpart was absent, is a campaign failure: the v1 campaign always
supplies all six roles, so every link is expected to be checkable, and a
non-`verified` outcome fails closed (§3.8). The campaign invents no link the
schemas do not already record and weakens none the packet already verifies.

### 3.3 No implicit winner

- `receipt_config_label` is a **mandatory** CLI argument. It must match, by exact
  string, **exactly one** configuration label in the operator's NP6 protocol
  (labels are unique and ≤ 64 chars — `MAX_LABEL_CHARS` — per
  `nextness-replay-protocol-v1`).
- The runner must **never** select the first configuration implicitly, and must
  **never** rank, search, recommend, infer, or apply a "winning" configuration.
  Selection is the operator's explicit, named act; the campaign performs no
  optimisation of any kind.
- A missing, unknown, or duplicate `receipt_config_label` is a fail-closed
  validation refusal (§3.8); "matches more than one" cannot occur for a valid
  protocol (labels are unique) but is still refused defensively rather than
  resolved.
- **NP6 continues to retain all configurations descriptively.** The single
  checkpoint receipt is for the one named configuration only; the replay-lab
  report still replays and reports **every** configuration side by side, in the
  operator's input order, with no score, ranking, winner or recommendation field
  anywhere (NP6's descriptive-only guarantee is preserved unchanged, and
  abstention remains a first-class outcome, never a defect).

### 3.4 Metrics decision (parked)

- `nextness_metrics` output is **not part of campaign v1**. `nextness_metrics`
  is an observer-lineage sidecar (it derives `nextness_run_metrics.jsonl` from
  the log); it is **not** an NP role in the NP1→NP8 provenance chain.
- The NP8 packet has **no metrics role** and **cannot presently provenance-link
  that sidecar**: there is no `metrics` role, no metrics artifact schema entry,
  and no provenance link for it in `nextness-evidence-packet-v1`. Emitting an
  unlinked metrics file beside a provenance-checked packet would be an artifact
  the chain cannot vouch for.
- This contract **does not change, and must not silently change, the NP8
  schema.** Metrics is **parked** until a separately-gated decision either (a)
  adds explicit provenance support for a metrics role to the NP8 schema, or (b)
  defines an **honestly unlinked** sidecar whose non-membership in the provenance
  chain is stated in the output itself. Neither option is proposed or authorised
  here.

### 3.5 Complete-log semantics

The campaign must process the **whole physical log**, never a summary of a
prefix:

- **No `max_rows` prefix may be treated as a complete campaign.** This is a
  campaign-level obligation that the underlying reader does **not** provide on
  its own: NP1's `read_dominant_sequence` silently reads at most `max_rows`
  physical records and treats that prefix as complete (the `max_rows`+1-th
  record is simply never read, still exit 0). By contrast `nextness_metrics`
  already refuses excess rows outright ("metrics summarizes a COMPLETE run").
  The campaign adopts the **metrics discipline**, not the predictor default: the
  runner must **prove the full physical log was accepted** under the selected
  bounds — e.g. by confirming ingestion reached end-of-file rather than the
  `max_rows` cap — **or refuse the campaign**. No silent truncation and no
  prefix summary is permitted.
- **No continuation after an oversized terminal record.** A record whose content
  exceeds `max_line_bytes` is counted `oversized_line` and terminates NP1
  ingestion fail-closed, yet NP1 still emits an exit-0 report over the records
  before it. The campaign must detect that ingestion was terminated by an
  oversized record (e.g. `rejections.oversized_line > 0`, or equivalently that
  the read stopped before EOF) and **refuse**, rather than accept the truncated
  prefix.
- The selected reader bounds are echoed into the campaign's own manifest so the
  completeness proof is reproducible and auditable, not implicit.

### 3.6 Publication

- The runner builds **every** output inside a **unique staging directory that
  shares the final output directory's parent**, so promotion is a single
  same-directory rename on one filesystem.
- The **final output directory must be absent before the run**. If it already
  exists, the run refuses (§3.8) — the runner **never overwrites** an existing
  final directory.
- Publication happens **only after** every produced artifact validates through
  its own validator, the NP8 packet passes its **self-validation**
  (`validate_evidence_packet`), and **all four provenance links are `verified`**.
  A failure at any of these gates leaves the final directory uncreated.
- **No output — staging or final — may be created under the repository `data/`
  tree**, consistent with every instrument's `WriteOutsideLogDirError`
  containment. All campaign output lives in the operator's external workspace.
- **Concurrency / TOCTOU boundary, stated honestly.** The absence of the final
  directory is checked at validation time; the later promotion does not re-verify
  under a lock. A concurrent actor that creates the final directory between the
  check and the rename is caught only to the extent the operating system refuses
  a rename onto an existing directory; this residual validation-to-publish
  interval is a **non-claim**, exactly as the instruments' own write guards state
  their validation-to-write TOCTOU non-claim.
- **Residual (hard kill).** A hard kill (or power loss) mid-run may leave an
  **unpublished staging directory** behind; the final directory is either fully
  absent or fully published, but the staging directory is not guaranteed to be
  cleaned up on an uncatchable termination (see §3.8 for handled-failure
  cleanup). The runner claims **no stronger cross-platform atomicity or
  power-loss durability** than a single same-directory directory rename provides
  — in particular it does not claim atomic multi-file publication on platforms
  where directory rename semantics are weaker, and it does not claim fsync-level
  durability.

### 3.7 Determinism and bounds

- **Byte-identical outputs.** The same input log bytes, the same protocol bytes,
  the same explicit `receipt_config_label`, and the same CLI options must produce
  **byte-identical** campaign outputs. Each instrument already guarantees
  sorted-key, fixed-separator, LF-only, timestamp-free, randomness-free,
  absolute-path-free serialization; the campaign **adds none of these** to any
  generated artifact and introduces no wall-clock timestamp, random identifier,
  or absolute path of its own (including in any campaign manifest it writes).
- **Reuse existing ceilings where their contracts apply**, by name and value:
  NP1/NP6 reader bounds `max_rows` (default 100 000, ceiling 1 000 000) and
  `max_line_bytes` (default 65 536, ceiling `MAX_LINE_BYTES_CEILING` =
  16 777 216); per-artifact serialized ceiling 64 KiB (`ReportTooLargeError` /
  `ReceiptTooLargeError` / `EvaluationTooLargeError` / `LabReportTooLargeError` /
  `PacketTooLargeError`); NP5 `MAX_INPUT_BYTES` = 1 MiB per JSON artifact and
  `MAX_SERIES_RECEIPTS` = 256; NP6 `MAX_LAB_CONFIGS` = 8 and `MAX_REPLAY_STEPS`
  = 2000; NP8 `MAX_INPUT_BYTES` = 1 MiB, `MAX_LOG_BYTES` = 16 MiB,
  `MAX_PACKET_ARTIFACTS` = 8, output ceiling 64 KiB.
- **Define any campaign-level ceiling explicitly.** Any bound the campaign layer
  needs that is not already one of the above — for example a cap on the number of
  published files, or the size of a campaign manifest — must be declared as an
  explicit named campaign constant with fail-closed enforcement, **never
  inherited by implication** from an instrument whose contract does not actually
  govern it.

### 3.8 CLI and failure contract (proposed, explicit, non-harmonising)

The Nextness family deliberately keeps **four distinct exit-code sets across six
CLIs** and does not harmonise them (`docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md`).
The campaign therefore defines **its own** explicit map rather than inheriting or
normalising any existing one. The map below is the **proposed** v1 contract, to
be ratified at implementation time under a separate gate.

**Proposed CLI surface** (`nextness_evidence_campaign`):

- **Positional**: `log_path` (the recorded `nextness_runs.jsonl`);
  `protocol_path` (the operator NP6 protocol).
- **Required option**: `--receipt-config-label <label>` (exact match to one
  protocol configuration; §3.3).
- **Output**: `--output-dir <dir>` — the **final** campaign directory, which must
  be **absent** before the run, must resolve **outside** the repository `data/`
  tree, and must not alias either input; staging is created in its parent (§3.6).
- **Reader-bound options**: `--max-rows` (default 100 000, ceiling 1 000 000) and
  `--max-line-bytes` (default 65 536, ceiling 16 777 216), applied to the log
  reads and **echoed** into the manifest for the completeness proof (§3.5).
- **Success output**: a concise success line naming the published final directory
  (and, optionally, the packet's self-reported role/link summary); exit 0.
- **Error output**: exactly **one concise `error:` line** to stderr per expected
  failure, never a traceback — matching the family's `error:` convention (the
  campaign introduces no second prefix; it has no metrics-style `safety error:`
  lane).

**Proposed exit-code map**:

| Code | Category | Meaning |
|---|---|---|
| 0 | success | full chain built, all four provenance links `verified`, packet self-validated, published to the (previously absent) final directory |
| 2 | validation | typed `CampaignInputError`: missing / malformed / oversized / unknown-variant input; missing / unknown / duplicate `receipt_config_label`; a produced or consumed artifact failing its validator or NP8 self-validation; **a provenance link not `verified`**; **a complete-log refusal** (a `max_rows` prefix that is not the whole log, or an oversized-terminal-record truncation) per §3.5 |
| 3 | insufficient-history | `InsufficientHistoryError` surfaced from NP1 / NP2 / NP6 (the family's insufficiency semantics; never re-typed) |
| 4 | containment | output-path failure: the final directory already exists; a staging or final path under the repository `data/` tree; a path outside the operator workspace; or a path aliasing either input (resolved-path + `os.path.samefile`, fail-closed identity) |
| 5 | ceiling | a produced artifact over its 64 KiB serialized ceiling, a JSON input over `MAX_INPUT_BYTES` (1 MiB), or the log over `MAX_LOG_BYTES` (16 MiB) |
| 6 | staging | staging-directory build failure (create / write inside the unique staging directory) |
| 7 | publication | publication failure: the final directory appeared between the absence check and promotion, or the staging → final rename failed |

**Which exceptions remain loud internal failures.** Mirroring all six family
`main()` clauses, the campaign `main()` catches **only** its documented typed
classes (`CampaignInputError` and the instrument exceptions it deliberately
surfaces — `InsufficientHistoryError`, the `*TooLargeError` ceiling family, the
containment/output classes, and the proposed staging/publication classes). It
**never** broadly catches plain `ValueError`; a plain `ValueError`, a
`RuntimeError` (including the NP8 self-validation re-raise), a `MemoryError`, or
any exception outside the documented catch set **propagates loudly** rather than
masquerading as a concise input failure. Argparse usage errors exit 2 via
argparse's own `SystemExit(2)` with its multi-line `usage:` output, outside this
map — the standard family carve-out.

### 3.9 Future test plan (synthetic fixtures only)

The future implementation's tests must use **synthetic `tmp_path` fixtures
only** — no real Medusa artifact, no network, no engine, no observer/calibration
execution. The suite must include tests for:

- deterministic **byte identity** (same inputs + label + options → identical
  published bytes across two runs);
- **explicit configuration selection** (the named label's configuration drives
  the single checkpoint receipt);
- **missing, unknown, and duplicate** `receipt_config_label` (each a fail-closed
  refusal);
- **all configurations retained by NP6** (every protocol configuration present in
  the lab report, operator order, no winner/score field);
- **all four NP8 provenance links `verified`** on a well-formed campaign;
- **complete-log enforcement** (the full physical log accepted, or refusal);
- **oversized-row and excess-row refusal** (oversized terminal record; a log
  longer than `max_rows`);
- **metrics absent from v1** (no metrics role or metrics artifact in the packet
  or the published directory);
- **input byte preservation** (both inputs byte-identical after every path,
  including refusals);
- **absent-final-directory requirement** (refusal when the final directory
  pre-exists);
- **no overwrite** of an existing final directory;
- **staging cleanup on a handled failure** (a handled mid-run failure removes its
  staging directory);
- **honest hard-kill staging residual** (an uncatchable termination may leave a
  staging directory — asserted as a documented residual, not a guarantee of
  cleanup);
- **no output under repository `data/`**;
- **no engine, observer-execution, network, model, orchestration or tuning
  imports** (static import audit of the runner module).

### 3.10 Non-claims and future implementation boundary

**Load-bearing non-claims (must be stated prominently in any future runner and
its outputs):**

- **Design-only**: this document authorises **no runner implementation**.
- No real Medusa artifact is read or processed; no snapshot, observer, or
  calibration execution occurs.
- No engine, tuning, recommendation, or control path; no configuration is ranked,
  selected as best, recommended, or applied.
- No network, HTTP, ZMQ, or model invocation.
- No consciousness, awareness, phenomenology, or biological-equivalence claim —
  the campaign is bookkeeping over recorded counting-model artifacts, nothing
  more (every instrument already embeds this non-claim; the campaign preserves
  them unchanged).

**Maximum anticipated implementation boundary** (only after a **separate Jack
audit and a fresh Kev authorisation** — nothing below is authorised by this PR):

- a new `scripts/nextness_evidence_campaign.py`;
- a new `tests/test_nextness_evidence_campaign.py`;
- **one factual update** to `docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md` — adding a
  single new row (and, if a genuinely new semantic is introduced, a short prose
  note) for the campaign CLI to that document's existing six-map table, in
  keeping with its descriptive, non-harmonising structure.

**No existing producer, validator, artifact schema, observer, calibration,
metrics, or any other file is implicitly authorised to change.** In particular
the NP1–NP9 modules, their schemas, their tests, and the NP7 contract guard
remain untouched; the campaign is purely additive and composes them as-is.

## 4. Consistency with the merged interfaces

These v1 decisions **coexist with the current-`main` contracts** — the reason
this contract can be frozen without proposing any interface change:

- The six packet roles, the four provenance links, and the per-role
  schema/byte/SHA-256 records are exactly those `nextness-evidence-packet-v1`
  already emits and verifies; the campaign supplies all six roles so all four
  links are checkable.
- The single-checkpoint-plus-all-configurations split is exactly the existing
  NP2 (one deterministic receipt per configuration) and NP6 (all configurations,
  descriptive) division of labour; "no implicit winner" restates NP5/NP6's
  existing no-ranking / no-recommendation guarantees.
- The complete-log obligation is stricter than NP1's silent-prefix default but
  is the **discipline metrics already enforces**; it adds a campaign-level proof
  and contradicts no instrument.
- The staging/atomic-ish publication is **new** (no current CLI stages or renames
  — metrics writes directly, non-atomically), so the campaign defines it
  explicitly and, crucially, **claims no atomicity the mechanism cannot deliver**,
  consistent with the family's standing write-lane and TOCTOU non-claims.
- The exit-code map is the campaign's **own** explicit set, respecting the
  family's deliberate non-harmonisation; the only documentation touch a future
  implementation would make is a single additive factual row.

If a future reader finds any of these decisions has drifted out of consistency
with the merged contracts, the correct action is to **revise this contract under
its own gate** — never to silently reconcile it against changed source.
