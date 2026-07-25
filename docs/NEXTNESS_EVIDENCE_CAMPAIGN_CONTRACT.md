# Nextness Offline Evidence Campaign Contract (design-only)

**Proposed module (not created by this PR)**: `scripts/nextness_evidence_campaign.py` ·
**Proposed tests (not created by this PR)**: `tests/test_nextness_evidence_campaign.py` ·
**Proposed schema id (new, not on `main`)**: `nextness-evidence-campaign-v1` · **Status**: **DESIGN ONLY**

> **This document is a frozen design contract, not an implementation.** It
> creates no runner, reads no real Medusa artifact, runs no observer, no
> calibration, no engine, no model, and no network call. It only records the
> v1 decisions a future deterministic, offline **evidence campaign runner**
> must satisfy so that a later, separately-gated implementation can be audited
> against a fixed target. No implementation, ready transition, or merge is
> authorised by the pull request that introduces this file. Every "the runner
> …", "the campaign …", "v1 …" statement below is a **proposed future
> obligation**, never a description of existing behaviour.

**Existing vs proposed (read this first).** Everything attributed to NP1–NP9
below — schema ids `nextness-predictor-v1` / `nextness-monitor-v1` /
`nextness-evaluation-v1` / `nextness-replay-lab-v1` /
`nextness-replay-protocol-v1` / `nextness-evidence-packet-v1`, their bounds,
their per-CLI exit codes, and the four NP8 provenance links — is a **fact found
in current `main` source** and is **not changed** by this contract. Everything
attributed to the *campaign* — the `nextness-evidence-campaign-v1` manifest, the
eight-file publication set, the `--workspace-dir` staging model, and the campaign
exit-code map — is **newly proposed here** and exists only as this design. The
prose marks these as *(existing at `main`)* or *(proposed, new)* wherever
confusion is possible.

**How the campaign uses the instruments (read this second).** The proposed
runner is a **module-level composition**: it calls each instrument's existing
public builders, loaders and canonical serializers in-process — `build_report`;
`observations_from_log` + `build_receipt`; `build_evaluation`; `load_protocol` +
`build_lab_report`; `build_packet`; each with its own `serialize_*`
*(existing at `main`)*. It does **not** shell out to the six standalone CLIs, and
**no obligation in this document may be read as requiring an artifact to be
reproducible through a standalone CLI invocation.** The distinction is
load-bearing, not stylistic: **NP2's CLI exposes only `log_path`, `--model`,
`--smoothing` and `--holdout-fraction`** *(existing at `main`,
`scripts/nextness_monitor.py`)* — no labelled `MonitorConfig`, no
`min_history` / `window` / threshold values, and no reader-bound options — so a
labelled-configuration receipt under campaign-selected bounds has **no CLI
invocation that produces it**, while NP2's module-level
`observations_from_log(..., max_rows=..., max_line_bytes=..., window=...)` and
`build_receipt(..., config=MonitorConfig(...))` accept exactly those inputs.
Composing the modules **adds nothing to, and changes nothing in,** any
instrument's semantics, schema, validators or exit map.

## 1. What a "campaign" is — and is not

A **campaign** is the deterministic, offline processing of **one
already-recorded** Nextness Observer log into a single provenance-checked
NP1 → NP2 → NP5 → NP6 → NP8 artifact chain, published — together with an outer
campaign manifest — as one fixed set of files in one directory.

"Campaign" means **recorded-log artifact processing only**. It explicitly does
**not** mean, and the runner must never perform:

- snapshot collection or any `process_snapshot()` call;
- observer execution (`scripts/nextness_observer.py` is a log **producer**,
  upstream of and outside the campaign — the campaign consumes a recording of
  its output read-only, it never runs it);
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
id **for an instrument**, it is the value found in that source at `main`, and it
is left unchanged. Where it names the campaign manifest, publication set, or
campaign exit map, that is **proposed here**. If any *(existing at `main`)* fact
later stops matching source, **this document must change under its own gate** —
nothing here licenses a silent drift, and nothing here proposes to *change* any
instrument interface.

## 3. Frozen v1 decisions

### 3.1 Inputs, the workspace, and the authoritative staged snapshot

- Exactly **one** already-recorded `nextness_runs.jsonl` log.
- Exactly **one** operator-authored NP6 protocol file
  (`nextness-replay-protocol-v1`).
- **`--workspace-dir <existing-dir>` is required.** It must name an **already
  existing** directory. The runner resolves it once (`os.path.realpath`) to a
  `workspace_root`.
- **Resolved-path containment.** The original log, the original protocol, the
  staging parent, and the final output directory must each, after
  `os.path.realpath`, be **equal to `workspace_root` or a descendant of it**
  (compared on resolved paths — covering `..` segments and symlinks — with the
  established fail-closed identity discipline; an inspection that cannot complete
  is itself a refusal). `workspace_root` itself must resolve **outside the
  repository `data/` tree**; consequently no campaign path may lie under `data/`.
  A path failing containment is a fail-closed refusal (§3.9, exit 4).
- **Authoritative staged snapshot.** Before running **any** instrument, the
  runner copies the log and the protocol **byte-for-byte** into the unique
  staging directory. **Every NP1 / NP2 / NP5 / NP6 / NP8 module-level call is
  given those staged paths** (and the artifact paths written into staging); the
  runner **never reopens the original source paths** after the copy. The §3.6
  completeness preflight and the §3.9 size preflight likewise read staged bytes
  only.
- **Honest input-mutation statement.** The runner **never mutates the
  originals**. It does not, however, freeze the operator's filesystem: a
  concurrent actor that mutates or replaces a source **while its copy is being
  taken** is a residual the runner cannot exclude. The **authoritative campaign
  inputs are therefore the bytes successfully captured in staging**, whose hashes
  the manifest records (§3.2); the campaign makes claims about those captured
  bytes, not about the originals' later state.

### 3.2 Exact output chain and the eight-file publication set

From the staged inputs, the proposed v1 runner produces, in dependency order,
each the **byte-identical canonical output of that instrument's own
module-level builder and serializer** applied to the staged copies — never a
re-implementation, and never a standalone-CLI invocation (see *How the campaign
uses the instruments*):

1. **NP1 predictor report** (`nextness-predictor-v1`) over the staged log;
2. **NP2 checkpoint receipt** (`nextness-monitor-v1`) for the single monitor
   configuration selected by the exact `receipt_config_label` (§3.4, §3.5),
   built through NP2's module-level `observations_from_log` +
   `build_receipt(config=...)` + `serialize_receipt`, because NP2's CLI can
   express neither a labelled configuration nor campaign reader bounds; the
   emitted bytes are exactly NP2's own canonical receipt, and NP2's semantics and
   schema are untouched;
3. **NP5 evaluation** (`nextness-evaluation-v1`) over the report and that
   receipt;
4. **NP6 replay-lab report** (`nextness-replay-lab-v1`) over the staged log and
   the staged protocol, retaining **every** protocol configuration (§3.4, §3.5);
5. **NP8 evidence packet** (`nextness-evidence-packet-v1`) over the six existing
   roles (`report`, `receipts`, `evaluation`, `lab`, `protocol`, `log`).

**Frozen final directory — exactly these eight files** (no more, no fewer),
relative names only:

| File | Contents |
|---|---|
| `nextness_runs.jsonl` | the staged log (authoritative captured bytes) |
| `nextness_replay_protocol.json` | the staged NP6 protocol |
| `nextness_predictor_report.json` | NP1 report |
| `nextness_monitor_receipt.json` | NP2 checkpoint receipt |
| `nextness_evaluation.json` | NP5 evaluation |
| `nextness_replay_lab.json` | NP6 replay-lab report |
| `nextness_evidence_packet.json` | NP8 evidence packet |
| `nextness_evidence_campaign.json` | the outer campaign manifest *(proposed, new)* |

**The outer campaign manifest** `nextness_evidence_campaign.json`
(`nextness-evidence-campaign-v1`) is **the final campaign artifact, not an NP8
role** — NP8's role set is unchanged and has no campaign entry. It has an exact
schema, the same canonical serialization as the instruments (sorted keys, fixed
separators, LF-only, no timestamp / random id / absolute path), **relative
filenames only**, and its own explicit named ceiling `MAX_CAMPAIGN_MANIFEST_BYTES`
= **64 KiB** (fail-closed; §3.9 exit 5). It records:

- each **staged input's** relative filename, byte size and SHA-256 (the log and
  protocol);
- the campaign reader bounds (`max_rows`, `max_line_bytes`) actually applied;
- the exact `receipt_config_label` and its configuration correspondence (§3.4);
- the completeness evidence (§3.6) — the campaign bounds applied, the physical
  record count the preflight observed (at most `max_rows`), and the *no record
  beyond `max_rows`* / *no oversized record* outcomes it established; the
  preflight is the campaign's **completeness witness** and this record is where
  its evidence is published;
- each **produced artifact's** relative filename, byte size and SHA-256 (the NP1
  report, NP2 receipt, NP5 evaluation, NP6 lab report and NP8 packet — the
  packet's hash being the inward pointer of *Direction of trust* below);
- the **cross-artifact coherence outcome** (§3.4) exactly as NP5 recorded it:
  for each of `ece_match` and `surprise_nll_match`, the envelope status and —
  when `computed` — the verdicts present, so a reader can see that publication
  was permitted because no verdict was `contradicted`;
- the **four NP8 link statuses** (§3.3), copied for auditability.

Together the two input records and the five produced-artifact records cover the
**seven non-manifest files**. The manifest, being a file, **does not and cannot
record its own SHA-256** — it is the outermost, unhashed-within-itself layer.

**Direction of trust.** The manifest **points inward** to the NP8 packet (it
records the packet's hash and echoes the packet's link statuses). **NP8 does not
authenticate or provenance-link the campaign manifest** — the manifest is the
outermost layer, verified by nothing above it; a consumer that re-verifies the
chain re-hashes the **seven non-manifest files** against the manifest's records
and takes the manifest itself as given.

### 3.3 The four NP8 provenance checks (existing at `main`)

The NP8 packet independently recomputes the four provenance checks the v1 schemas
embed. These are **three artifact-byte hash links plus one
accepted-sequence-representation hash link** — not four links of one identical
kind:

| Check | Kind | Recorded by → verified against |
|---|---|---|
| `evaluation_report_sha256` | artifact-byte hash | NP5 `artifacts.report.sha256` → the report **file's raw bytes** |
| `evaluation_receipts_sha256` | artifact-byte hash | NP5 `artifacts.receipts.sha256` → the receipts **file's raw bytes** |
| `lab_protocol_sha256` | artifact-byte hash | NP6 `input.protocol_sha256` → the protocol **file's raw bytes** |
| `lab_sequence_sha256` | accepted-**sequence-representation** hash | NP6 `input.sequence_sha256` → the hash of the log's **accepted dominant-token sequence**, recomputed through NP1's bounded reader **with the lab's recorded `max_rows` / `max_line_bytes`** (not a hash of the log file's bytes) |

**All four must be `verified`** before publication succeeds; a non-`verified`
outcome is an explicit **campaign** refusal (§3.9, exit 2 — *provenance not
verified*), fail-closed. **These four checks verify hashes only** — they do not,
by themselves, establish that the report, receipts and lab all came from the
**same log under the same options**. That same-log / same-options coherence is
supplied by the **campaign-level construction and the manifest** (§3.4), not by
the NP8 links.

### 3.4 Semantic lineage (campaign-level, proposed)

Because the campaign builds the whole chain, it can and must enforce lineage the
individual instruments do not cross-check:

- The protocol's **`smoothing`** and **`holdout_fraction`** drive **NP1**.
- The protocol's **`model`**, **`smoothing`** and **`holdout_fraction`**,
  together with the configuration identified by the exact `receipt_config_label`,
  drive **NP2**. Because NP2's observation bridge and its receipt take the window
  by separate arguments, the labelled configuration's **`window` must be passed
  to `observations_from_log` as well as to `build_receipt`'s `MonitorConfig`**;
  NP2's own bridge documents that requirement *(existing at `main`)*, nothing
  downstream detects a mismatch, so the campaign owns it.
- **NP1, NP2 and NP6 use identical campaign `max_rows` and `max_line_bytes`**,
  passed to `build_report`, `observations_from_log` and `build_lab_report`
  respectively. For NP2 this is reachable **only** through its module-level
  interface — its CLI has no reader-bound options — which is why the campaign
  composes modules rather than CLIs.
- **NP6 retains every protocol configuration in operator order** (its existing
  descriptive guarantee, unchanged).
- The manifest **records the selected label and its exact configuration
  correspondence**, because an **NP2 receipt records the configuration's *values*
  but not the protocol *label*** — without the manifest, the receipt could not be
  tied back to a named protocol configuration.
- **Cross-artifact coherence gate (verdict-level).** NP5 reports each of its
  cross-artifact checks (`ece_match`, `surprise_nll_match`) in the standard
  **envelope** — `computed` or `not_computable` — and, inside a `computed`
  envelope, carries **per-model results whose `verdict` is one of the three fixed
  values `consistent` / `contradicted` / `unverifiable`** *(existing at `main`:
  `nextness_evaluator.VERDICTS`)*. The gate is defined at the **verdict** level,
  never at the envelope level:
  - a `computed` result carrying a verdict of exactly **`contradicted`** — a
    genuine disagreement the evaluator was able to compute, where the campaign's
    same-source construction *should* have made agreement possible — **refuses
    publication** (§3.9, exit 2);
  - **`consistent`** permits publication;
  - **`unverifiable`** — NP5's recorded-surprise-floor lane, where the comparison
    cannot be decided in either direction — is an **evidence outcome**: it
    permits publication and is **never** silently recast as `contradicted` or as
    `not_computable`;
  - **`not_computable`** (for example `no_covering_receipt`, or any typed
    absent-evidence reason) is likewise an **evidence outcome, not a failure**.
  In every permitting case the campaign publishes and the manifest carries the
  outcome forward **exactly as NP5 recorded it** — envelope status and verdicts
  unchanged. The campaign **invents no verdict, adds no verdict value and alters
  no NP5 schema**; it only decides, from values NP5 already emits, whether to
  publish.

### 3.5 No implicit winner

- `receipt_config_label` is a **mandatory** CLI argument matching, by exact
  string, **exactly one** configuration label in the operator's NP6 protocol
  (labels are unique and ≤ 64 chars — `MAX_LABEL_CHARS` — in
  `nextness-replay-protocol-v1`).
- The runner must **never** select the first configuration implicitly, and must
  **never** rank, search, recommend, infer, or apply a **winning
  *configuration***. Configuration selection is the operator's explicit, named
  act; the campaign performs no configuration optimisation.
- **Scope of the prohibition (correction).** NP5 legitimately **ranks the three
  prediction *models*** (`empirical_prior`, `persistence`, `first_order`) with
  fixed tie-breaks — that is existing, descriptive NP5 behaviour and is
  **retained unchanged**. The campaign adds no *configuration* ranking,
  selection, recommendation, or application; model rankings inside the NP5
  evaluation are not a winner over configurations and are left exactly as NP5
  emits them.
- A missing, unknown, or duplicate `receipt_config_label` is a fail-closed
  validation refusal (§3.9, exit 2).
- **NP6 continues to retain all configurations descriptively** — every
  configuration replayed and reported side by side, in operator order, with no
  score / ranking / winner / recommendation field (NP6's guarantee, preserved);
  abstention remains a first-class outcome, never a defect.

### 3.6 Complete-log semantics (exact)

The campaign must process the **whole physical log**, never a summary of a
prefix — stated precisely:

- The obligation is that the staged log is **fully traversed under the selected
  bounds**, **not** that "every physical row is accepted". Ordinary malformed-row
  rejections (the 12 NP1 `REJECT_REASONS`) **remain normal NP1 behaviour** and do
  not fail the campaign; a fully-traversed log with rejected rows is still
  complete.
- The **completeness preflight runs against the staged log** (the authoritative
  captured bytes), under the campaign `max_rows` / `max_line_bytes`, **before any
  instrument is invoked**.
- **Mechanism — campaign-owned, streaming, byte-level.** The preflight opens the
  staged log in **binary** and frames records exactly as NP1's reader frames them
  *(existing at `main`, `scripts/nextness_predictor.py`)*: records are
  **LF-delimited** and read with bounded `readline(max_line_bytes + 2)` calls; a
  record's **content** is the returned chunk with a trailing CRLF (two bytes) or
  LF (one byte) removed, and a chunk that reached the read limit without a
  terminator is content in full; a record whose **content** exceeds
  `max_line_bytes` is the **oversized record** that terminates NP1 ingestion.
  **Every physical record counts** — accepted, rejected and blank alike —
  matching NP1's `rows_read` accounting. The preflight stops as soon as the
  question is answered: it reads **at most `max_rows + 1` records**, so its work
  is bounded by `(max_rows + 1) * (max_line_bytes + 2)` bytes.
- **Why it is campaign-owned rather than an extra reader call.** It must work at
  **every permitted bound, including `max_rows = MAX_ROWS_CEILING` = 1 000 000**.
  NP1's reader cannot be asked to read `max_rows + 1` records there: a `max_rows`
  above `MAX_ROWS_CEILING` is a typed `PredictorInputError` *(existing at
  `main`)*, and the reader stops at `max_rows` without probing further, so
  "exactly `max_rows` records" and "more than `max_rows` records" are
  indistinguishable in its return value. The preflight is therefore the
  campaign's own bounded scan — and it re-implements **no NP1 row semantics**,
  only NP1's record framing.
- **What the preflight must not do.** It performs **no JSON parsing, no rejection
  classification, no model inference and no accepted-row judgement**. It answers
  exactly two byte-level questions — *is there a physical record beyond
  `max_rows`?* and *is there a record whose content exceeds `max_line_bytes`?*
  Deciding whether a row is valid, and the **12 NP1 `REJECT_REASONS`**, remain
  **entirely NP1's** *(existing at `main`)*; the preflight neither duplicates nor
  reinterprets them and classifies nothing.
- The runner **refuses** (§3.9, exit 2 — *complete-log refusal*) when the
  preflight finds a **physical record beyond `max_rows`** (a prefix that is not
  the whole log) **or** a **record whose content exceeds the campaign
  `max_line_bytes`** (the oversized record that would terminate NP1 ingestion) —
  **before** treating the campaign as complete, and before any instrument runs. NP1 on its own would silently
  read a `max_rows` prefix and emit an exit-0 report; the campaign adopts the
  stricter, metrics-style "complete run" discipline instead.
- **NP8's `log`-role manifest entry is not the campaign completeness witness.**
  NP8 is unchanged: its `log` entry hashes the raw bytes and computes its own
  `sequence_sha256` using **NP1 *default* reader bounds**, while only its
  **`lab_sequence` link** uses the lab's recorded bounds. The
  default-bound NP8 log entry therefore says nothing about traversal under the
  campaign bounds; the **campaign preflight** is the completeness witness, and its
  evidence is recorded in the manifest.

### 3.7 Publication

- The runner builds **every** output inside a **unique staging directory that
  shares the final output directory's parent**, so promotion is a single
  same-directory rename on one filesystem. The byte-for-byte input copies (§3.1)
  land there first; all eight files are assembled in staging.
- The **final output directory must be absent at validation time**; if it already
  exists then, the run **refuses** (§3.9, exit 4 — containment).
- **No portable, absolute no-overwrite guarantee is claimed across the
  validation-to-rename race.** The absence check and the later promotion are not
  performed under a lock. If a destination is **created concurrently** between the
  check and the rename, the outcome depends on the operating system: it may cause
  a **reported publication failure** (§3.9, exit 7) where the OS reports the
  collision or the rename failure; or, where the OS **permits replacement of an
  empty directory**, the promotion may replace it. **Exit 7 applies exactly when
  the OS reports the collision or rename failure**; an **unobservable replacement
  remains an explicit non-claim** — the runner does not claim to detect or prevent
  it.
- Publication happens **only after** every produced artifact validates through its
  own validator, the NP8 packet passes its **self-validation**, **all four
  provenance checks are `verified`**, and the cross-artifact coherence gate (§3.4)
  is satisfied — that gate being satisfied exactly when **no `computed`
  cross-artifact result carries a `contradicted` verdict**, with `consistent`,
  `unverifiable` and `not_computable` all permitting publication. A failure at
  any of these gates leaves the final directory uncreated.
- **No output — staging or final — is created under the repository `data/`
  tree** (guaranteed by the workspace containment of §3.1).
- **Residuals (retained non-claims).** A hard kill (or power loss) mid-run may
  leave an **unpublished staging directory** behind; a handled failure cleans its
  staging directory, but an **uncatchable termination is not guaranteed to**. The
  runner claims **no fsync-level power-loss durability** and **no atomicity
  stronger than a single same-directory directory rename** — in particular no
  atomic multi-file publication on platforms with weaker directory-rename
  semantics. The validation-to-rename interval above is a standing non-claim,
  consistent with every instrument's own validation-to-write TOCTOU non-claim.

### 3.8 Determinism and bounds

- **Byte-identical outputs.** The same staged input bytes, the same protocol
  bytes, the same explicit `receipt_config_label`, and the same CLI options must
  produce **byte-identical** campaign outputs — the eight files **including the
  manifest**. Each instrument already guarantees sorted-key, fixed-separator,
  LF-only, timestamp-free, randomness-free, absolute-path-free serialization; the
  campaign and its manifest **add none** of timestamp, random identifier, or
  absolute path, and the manifest uses **relative filenames only**.
- **Reuse existing ceilings where their contracts apply** *(existing at `main`)*,
  by name: NP1/NP6 reader bounds `max_rows` (default 100 000, ceiling
  1 000 000) and `max_line_bytes` (default 65 536, ceiling
  `MAX_LINE_BYTES_CEILING` = 16 777 216); per-artifact serialized ceiling 64 KiB
  (`ReportTooLargeError` / `ReceiptTooLargeError` / `EvaluationTooLargeError` /
  `LabReportTooLargeError` / `PacketTooLargeError`); NP5 `MAX_INPUT_BYTES` = 1 MiB
  and `MAX_SERIES_RECEIPTS` = 256; NP6 `MAX_PROTOCOL_BYTES` = 64 KiB (the
  protocol **input** ceiling, enforced pre-parse by NP6's own loader),
  `MAX_LAB_CONFIGS` = 8 and `MAX_REPLAY_STEPS` = 2000; NP8 `MAX_INPUT_BYTES` = 1 MiB, `MAX_LOG_BYTES`
  = 16 MiB, `MAX_PACKET_ARTIFACTS` = 8, output ceiling 64 KiB.
- **Declare campaign-level bounds explicitly** *(proposed, new)*, never inherited
  by implication: the manifest ceiling `MAX_CAMPAIGN_MANIFEST_BYTES` = 64 KiB
  (fail-closed), and the **fixed eight-file publication set** itself (an exact
  set, neither extended nor reduced).
- **Four named ceiling families — never conflated** *(families 1-3 existing at
  `main`; family 4 proposed, new)*:
  1. **Generated-artifact serialization ceilings** — 64 KiB each, on what an
     instrument *emits*: `ReportTooLargeError` / `ReceiptTooLargeError` /
     `EvaluationTooLargeError` / `LabReportTooLargeError` /
     `PacketTooLargeError`, each raised by that instrument itself → campaign
     **exit 5**.
  2. **JSON-artifact and staged-log input ceilings** — NP5 / NP8
     `MAX_INPUT_BYTES` = 1 MiB and NP8 `MAX_LOG_BYTES` = 16 MiB → campaign
     **exit 5**, established by the campaign's **own size preflight** (§3.9),
     never by interpreting a typed loader exception.
  3. **NP6's protocol *input* ceiling `MAX_PROTOCOL_BYTES` = 64 KiB** — the same
     number as family 1 but a different lane: it bounds an **operator-supplied
     external input**, is enforced pre-parse by NP6's own loader and raises
     `LabInputError`, so it is a **malformed / out-of-bounds external input →
     campaign exit 2**, *not* the exit-5 ceiling lane.
  4. **The campaign manifest's own serialized ceiling**
     `MAX_CAMPAIGN_MANIFEST_BYTES` = 64 KiB → campaign **exit 5**.

### 3.9 CLI and failure contract (proposed, explicit, non-harmonising)

The Nextness family deliberately keeps **four distinct exit-code sets across six
CLIs** *(existing at `main`)* and does not harmonise them
(`docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md`). The campaign therefore defines **its
own** explicit map *(proposed, new)* — a **fifth** distinct set on a **seventh**
CLI — rather than inheriting or normalising any existing one, to be ratified at
implementation time under a separate gate.

**Proposed CLI surface** (`nextness_evidence_campaign`):

- **Positional**: `log_path` (recorded `nextness_runs.jsonl`); `protocol_path`
  (operator NP6 protocol).
- **Required options**: `--workspace-dir <existing-dir>` (§3.1);
  `--receipt-config-label <label>` (exact match to one protocol configuration,
  §3.5); `--output-dir <dir>` (the **final** campaign directory — absent before
  the run, inside the workspace, staging created in its parent).
- **Reader-bound options**: `--max-rows` (default 100 000, ceiling 1 000 000) and
  `--max-line-bytes` (default 65 536, ceiling 16 777 216), applied identically to
  NP1/NP2/NP6 **through their module-level interfaces** (NP2's CLI has no
  reader-bound options, so this is module-level by necessity — see *How the
  campaign uses the instruments*), used by the §3.6 completeness preflight, and
  echoed into the manifest for the completeness evidence.
- **Success output**: one concise line naming the published final directory;
  exit 0.
- **Error output**: exactly **one concise `error:` line** to stderr per expected
  failure, never a traceback (the campaign introduces no second prefix; it has no
  metrics-style `safety error:` lane).

**Campaign-owned size preflight** *(proposed, new — how the input half of the
exit-5 lane is decided)*. NP5's `load_json_artifact` and NP8's bounded JSON
loader raise `EvaluatorInputError` / `PacketInputError` for an **oversize**
artifact and for **malformed** content alike, and NP8's staged-log ceiling raises
`PacketInputError` as well *(existing at `main`)* — one typed class per module
covering both lanes. The campaign therefore **never infers a ceiling breach from
an instrument exception, and never parses exception-message text**. Instead,
**before invoking each affected loader**, it performs its own bounded **size
preflight** over the staged file using the **existing named ceilings** (§3.8):
NP5 / NP8 `MAX_INPUT_BYTES` = 1 MiB for each JSON artifact it is about to hand
over, and NP8 `MAX_LOG_BYTES` = 16 MiB for the staged log. A breach the preflight
**confirms** is the campaign's **exit 5**. Anything the preflight passes goes to
the existing typed loader or validator **unchanged**. No NP5 or NP8 exception
class, message, contract or exit code is changed, weakened or reinterpreted; the
preflight only decides which *campaign* lane a *campaign* failure lands in, and
it never widens the catch set.

**What a passed preflight does *not* buy — external input vs campaign-generated
artifact.** The JSON artifacts handed to NP5 and NP8 (the NP1 report, the NP2
receipt, the NP5 evaluation, the NP6 lab report) are artifacts the **campaign
itself generated** from already-accepted staged inputs — they are **not**
operator-supplied artifact inputs. Once the size preflight has passed, an
`EvaluatorInputError` or `PacketInputError` raised while consuming one of them is
therefore **not malformed external input**: it is a **loud internal invariant
failure**. It is **not** translated into `CampaignInputError`, **not** admitted to
the campaign's expected-failure catch set, and **never** exit 2 — it propagates
(see *Which failures stay loud internal failures* below). **Campaign exit 2 stays
reserved for genuinely external inputs** — the recorded log and the operator
protocol, each through its own applicable typed boundary (NP1's reader and the
§3.6 completeness preflight for the log; NP6's `load_protocol` →
`LabInputError` for the protocol, including its 64 KiB `MAX_PROTOCOL_BYTES`
ceiling) — **and for the expressly named campaign refusals** listed in the
exit-2 row.

**Proposed exit-code map** *(new; the family's non-harmonisation is respected —
this is a fifth distinct set, not a normalisation of the others)*:

| Code | Category | Meaning |
|---|---|---|
| 0 | success | eight-file set built, all four provenance checks `verified`, packet self-validated, coherence gate satisfied, published to the (previously absent) final directory |
| 2 | validation / campaign refusal | typed `CampaignInputError`: a **malformed or out-of-bounds external input** (the log or protocol — including a protocol over NP6's pre-parse `MAX_PROTOCOL_BYTES` = 64 KiB, which is NP6's `LabInputError` lane and **not** the exit-5 ceiling lane, §3.8; a `--workspace-dir` or path *existence / containment* failure is exit 4, not here); missing / unknown / duplicate `receipt_config_label`; **provenance-not-verified**; **complete-log refusal** (a physical record beyond `max_rows`, or a record whose content exceeds the campaign `max_line_bytes` — established by the §3.6 preflight); **NP5 `computed` cross-artifact `contradicted` verdict** refusal (§3.4). **Never a campaign-*generated* artifact**: an `EvaluatorInputError` / `PacketInputError` raised while NP5 or NP8 consumes an artifact the runner itself produced — after that artifact's size preflight passed — is a loud internal invariant failure, not this lane |
| 3 | insufficient-history | `InsufficientHistoryError` surfaced from NP1 / NP2 / NP6 (the family's insufficiency semantics; never re-typed) |
| 4 | containment | `--workspace-dir` is not an existing directory; the final directory already exists at validation time; a staging or final path outside the workspace, under the repository `data/` tree, or aliasing an input (resolved-path + `os.path.samefile`, fail-closed identity) |
| 5 | ceiling (named) | a **named byte-ceiling** breach only, from the source that owns it: a produced instrument artifact over its **64 KiB** serialization ceiling (`ReportTooLargeError` / `ReceiptTooLargeError` / `EvaluationTooLargeError` / `LabReportTooLargeError` / `PacketTooLargeError`, each raised by the instrument itself); the **campaign manifest** over `MAX_CAMPAIGN_MANIFEST_BYTES` (64 KiB); or — **as confirmed by the campaign's own size preflight above, never by catching a loader's typed input error** — a JSON artifact over NP5/NP8 `MAX_INPUT_BYTES` (1 MiB) or the staged log over NP8 `MAX_LOG_BYTES` (16 MiB). NP6's protocol **input** ceiling (`MAX_PROTOCOL_BYTES`, 64 KiB) is **not** in this lane — it is exit 2 (§3.8) |
| 6 | staging | failure to create the unique staging directory, to **copy the log/protocol into it**, or to write a produced artifact inside it |
| 7 | publication | the staging → final rename fails, or the OS **reports** a destination collision because the final directory appeared between the absence check and the rename (§3.7) |

**"Oversized" disambiguated.** The word covers **three** distinct lanes mapping
to **different** codes: an **oversized record** (content over the campaign
`max_line_bytes`, which terminates NP1 ingestion) is a **complete-log refusal →
exit 2**, established by the §3.6 preflight; an **oversize protocol** (over NP6's
pre-parse `MAX_PROTOCOL_BYTES` = 64 KiB, raising `LabInputError`) is a
**malformed / out-of-bounds external input → exit 2**; and a **named
byte-ceiling** breach (64 KiB generated artifact or campaign manifest, 1 MiB JSON
input, 16 MiB staged log) is the **ceiling lane → exit 5**, its input half
established by the campaign's own size preflight. No lane is described by the
bare word "oversized" alone.

**Which failures stay loud internal failures (propagate, not exit 2).** Mirroring
all six family `main()` clauses, the campaign `main()` catches **only** its
documented typed classes (`CampaignInputError` and the instrument exceptions it
deliberately surfaces — `InsufficientHistoryError`, the five `*TooLargeError`
serialization classes, the containment/output classes, and the proposed
staging/publication classes). The typed catch set is therefore **not** how the
**input** half of exit 5 is decided: NP5's `EvaluatorInputError` and NP8's
`PacketInputError` are deliberately **not** in it, precisely because each covers
oversize and malformed alike — the size preflight above settles that lane before
those loaders are ever called. Outside the catch set:

- **NP8's emitted-packet self-validation failure** is the **existing loud
  internal `RuntimeError`** *(existing at `main`)* and is **not** reclassified as
  exit 2 — it propagates loudly.
- **Structural invalidity of a campaign-*generated* artifact** (an artifact the
  runner produced from already-validated staged inputs failing its validator) is
  likewise an **internal programming / contract failure, not malformed operator
  input** — it propagates loudly, never exit 2. This **explicitly includes an
  `EvaluatorInputError` or `PacketInputError` raised while NP5 or NP8 consumes a
  campaign-generated artifact after that artifact's §3.9 size preflight has
  passed**: the artifact came from the campaign, not from the operator, so a parse
  or structure failure there is an internal invariant breach. It is **not** retyped
  as `CampaignInputError` and **not** added to the catch set. (Exit 2's validation
  lane is for malformed or out-of-bounds **external** inputs — the recorded log and
  the operator protocol through their own typed boundaries — and the explicit
  campaign refusals above, not for the campaign's own generated output.)
- Any other exception outside the documented catch set — a plain `ValueError`, a
  `RuntimeError`, a `MemoryError` — **propagates loudly** rather than masquerading
  as a concise input failure.

Argparse usage errors exit 2 via argparse's own `SystemExit(2)` with its
multi-line `usage:` output, outside this map — the standard family carve-out.

### 3.10 Future test plan (synthetic fixtures only)

The future implementation's tests must use **synthetic `tmp_path` fixtures
only** — no real Medusa artifact, no network, no engine, no observer/calibration
execution. The suite must include tests for:

- deterministic **byte identity** across two runs (all eight files, including the
  manifest);
- **explicit configuration selection** (the named label's configuration drives
  the single checkpoint receipt);
- **missing, unknown, and duplicate** `receipt_config_label` (each a fail-closed
  refusal);
- **all configurations retained by NP6** (every protocol configuration present,
  operator order, no winner/score field);
- **all four NP8 provenance checks `verified`** on a well-formed campaign;
- **complete-log enforcement** (the §3.6 preflight confirms the staged log is
  fully traversed under the campaign bounds, or refuses);
- **oversized-record and excess-row refusal** (a record whose content exceeds the
  campaign `max_line_bytes`; a log with a physical record beyond `max_rows`),
  **including a case with `max_rows` set to `MAX_ROWS_CEILING`** — proving the
  preflight is not itself bounded by NP1's `max_rows` parameter range;
- **preflight framing fidelity** — LF-terminated, CRLF-terminated, final
  unterminated and blank records all counted as physical records exactly as NP1
  counts `rows_read`, with **no** JSON parsing, rejection classification or
  accepted-row judgement performed by the preflight (malformed rows still reach
  NP1 and still land in its 12 `REJECT_REASONS`);
- **size-preflight lane separation** (§3.9), with no exception-message parsing
  anywhere:
  - a **confirmed named input-ceiling breach** — an oversize JSON artifact, or a
    staged log over `MAX_LOG_BYTES` — yields **exit 5** through the campaign
    preflight;
  - an **unexpected `EvaluatorInputError` / `PacketInputError` after a passed
    preflight**, raised while consuming a campaign-**generated** artifact,
    **propagates loudly** — neither exit 2 nor exit 5, and the catch set is not
    widened to swallow it;
  - a **malformed operator protocol** remains the NP6 `LabInputError` → **exit 2**
    lane;
- **protocol-input ceiling** — a protocol over NP6 `MAX_PROTOCOL_BYTES` (64 KiB)
  is refused on the **exit-2** lane (`LabInputError`), never the exit-5 ceiling
  lane;
- **metrics absent** from the eight-file set;
- **input byte preservation** (originals byte-identical after every path);
- **absent-final-directory requirement** and **no-overwrite at validation time**;
- **staging cleanup on a handled failure**, and the **honest hard-kill staging
  residual** (asserted as a documented residual, not a cleanup guarantee);
- **no output under repository `data/`**;
- **no engine, observer-execution, network, model, orchestration or tuning
  imports** (static import audit of the runner module);
- **staged-input authority** — the campaign reads the staged copies, not the
  originals (e.g. mutating an original after the copy does not change outputs);
- **source-replacement residual** — a source replaced *during* copy yields the
  captured-bytes behaviour the manifest hashes describe (residual asserted, not
  excluded);
- **exact eight-file publication** — precisely the eight named files, no more, no
  fewer;
- **manifest validation** — the `nextness-evidence-campaign-v1` schema, its 64 KiB
  ceiling, relative filenames, and the recorded sizes/hashes/label/link-statuses;
- **option lineage** — protocol `smoothing`/`holdout_fraction` reach NP1; protocol
  `model`/`smoothing`/`holdout_fraction` + the labelled configuration reach NP2;
  identical `max_rows`/`max_line_bytes` across NP1/NP2/NP6;
- **selected-label recording** — the manifest ties the receipt to the named
  protocol configuration;
- **NP8 default-bound exception** — the NP8 `log` entry uses NP1 default bounds
  and is not the completeness witness;
- **verdict-level coherence gate** — a `computed` cross-artifact result carrying
  a **`contradicted`** verdict refuses publication, while **`consistent`**,
  **`unverifiable`** and **`not_computable`** outcomes each publish and are
  carried into the manifest unchanged;
- **destination-race semantics** — a concurrently created destination yields a
  reported publication failure or a permitted empty-directory replacement, with
  the unobservable-replacement non-claim respected.

### 3.11 Non-claims and future implementation boundary

**Load-bearing non-claims (must be stated prominently in any future runner and
its outputs):**

- **Design-only**: this document authorises **no runner implementation**.
- No real Medusa artifact is read or processed; no snapshot, observer, or
  calibration execution occurs.
- No engine, tuning, recommendation, or control path; no **configuration** is
  ranked, selected as best, recommended, or applied (NP5's descriptive **model**
  rankings are unchanged and are not such a selection — §3.5).
- No network, HTTP, ZMQ, or model invocation.
- No consciousness, awareness, phenomenology, or biological-equivalence claim —
  the campaign is bookkeeping over recorded counting-model artifacts, nothing
  more (every instrument already embeds this non-claim; the campaign preserves
  them unchanged).

**Maximum anticipated implementation boundary** (only after a **separate Jack
audit and a fresh Kev authorisation** — nothing below is authorised by this PR):

- a new `scripts/nextness_evidence_campaign.py`;
- a new `tests/test_nextness_evidence_campaign.py`;
- **factual updates to `docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md`** consistent with
  its descriptive, non-harmonising structure. Because the campaign is a
  **seventh** CLI carrying a **fifth** distinct exit-code map, keeping that
  document factual requires **more than one row**: the new CLI **row** in the
  six-map table, **plus** the mechanical corrections that the addition forces —
  the map **count** ("four distinct code sets across six CLIs" → "five … across
  seven"), the affected **headings/summary** wording, and the
  **catch-set / unexpected-error-propagation list** (adding the campaign's typed
  catch classes). No other file's content is implied.

**No existing producer, validator, artifact schema, observer, calibration,
metrics, or any other file is authorised to change** by this contract. The
NP1–NP9 modules, their schemas, their tests, and the NP7 contract guard remain
untouched; the campaign is purely additive and composes them as-is.

## 4. Consistency with the merged interfaces

These v1 decisions **coexist with the current-`main` contracts** — the reason
this contract can be frozen without proposing any instrument change:

- The campaign touches the instruments **only through their existing public
  module-level entry points** — builders, loaders and canonical serializers — so
  every artifact it publishes is that instrument's own canonical output. No
  instrument CLI is extended, and none is invoked: NP2's CLI could not express a
  labelled configuration or campaign reader bounds even if it were used, which is
  why the composition is at module level.
- The six packet roles and the four provenance checks are exactly those
  `nextness-evidence-packet-v1` already emits and verifies; the campaign supplies
  all six roles from staged copies so all four checks are checkable, and it adds
  the **outer manifest** as a new artifact NP8 neither defines nor authenticates.
- The single-checkpoint-plus-all-configurations split is exactly the existing NP2
  (one deterministic receipt per configuration) and NP6 (all configurations,
  descriptive) division of labour. The "no implicit winner" rule restates NP6's
  no-ranking guarantee and adds a campaign-level no-**configuration**-selection
  rule; it does **not** contradict NP5's existing descriptive **model** ranking,
  which is retained.
- The same-log / same-options coherence the NP8 hash links do **not** by
  themselves guarantee is supplied by the campaign construction and recorded in
  the manifest (§3.4) — an additive invariant, not a change to NP8.
- The complete-log obligation is proved by a campaign-owned byte-level preflight
  (§3.6) that mirrors NP1's record framing while re-implementing none of its row
  semantics, and it works at every permitted bound including
  `max_rows = MAX_ROWS_CEILING`. It is stricter than NP1's silent-prefix default but is
  the discipline metrics already enforces; it is expressed as "fully traversed
  under the selected bounds" and runs against the staged log — it adds a
  campaign-level proof and contradicts no instrument.
- The staging / rename publication and the byte-for-byte input capture are
  **new** (no current CLI stages, copies inputs, or renames — metrics writes
  directly, non-atomically), so the campaign defines them explicitly and **claims
  no atomicity, no-overwrite absoluteness, or durability the mechanism cannot
  deliver**, consistent with the family's standing write-lane and TOCTOU
  non-claims.
- The exit-code map is the campaign's **own** explicit set — a fifth distinct set
  on a seventh CLI — respecting the family's deliberate non-harmonisation; the
  documentation it would later touch is `NEXTNESS_CLI_FAILURE_CONTRACTS.md`, whose
  factual upkeep needs the new row plus the count/heading/catch-set corrections
  above.

If a future reader finds any of these decisions has drifted out of consistency
with the merged contracts, the correct action is to **revise this contract under
its own gate** — never to silently reconcile it against changed source.
