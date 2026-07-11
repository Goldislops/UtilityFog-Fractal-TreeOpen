# Swarm Hunter v1 — Evidence & Architecture Preflight

> **Status: preflight documentation only.** This document authorizes nothing. **Lane A
> remains PARKED. The engine (`scripts/continuous_evolution_ca.py`) was not read and is
> untouched. No Swarm Hunter code path exists in this repository**, and none is created
> by this document. Implementation of anything below requires its own separately keyed
> authorization (Jack audit + Kev's word), stage by stage (§10).
>
> **Origin:** Kev-authorized overnight preflight runway (2026-07-12, Ian's-lounge seat,
> resumable under its recorded continuity protocol). Every claim below carries an
> evidence class: `[SRC]` source-established (path cited) · `[CALC]` calculated ·
> `[PROP]` proposed contract · `[HYP]` unexecuted hypothesis · `[ABSENT]` verified
> absent from tracked text.

---

## 1. Provenance map (Pass 0)

Base: `main = 6f0c720883ec00cd6f0d0d4e0b3a273c3049012d`, clean tree. `[SRC]`

| Source | Controlling statement | Status | Constrains SH? | Unresolved owner |
|---|---|---|---|---|
| `AGENT_HANDOFF.md` (Latest State + Phase 19 block) | Lane A PARKED; Swarm Hunter unimplemented and unauthorized; no consumer acts on observer signals | current | **yes — hard gate** | Kev (activation) |
| `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entry 2 | SH may "observe and tune local interaction thresholds only … not a global controller"; gated on trusted, calibrated observer signals | current, **candidate guardrail pending ratification** | yes | team ratification |
| Ledger entry 4 + 8 (Continual Harness / RHO) | self-improving loops only atop trustworthy evaluation signals; harness-level, never autonomous engine mutation; death-spiral risk | current | yes | AURA (verification of RHO source) |
| Ledger entry 7 | SH "must never become a global fabrication boss; at most it could surface *candidate local-rule structures / export hypotheses*" | current | yes — **strongest positive definition in the repo** | — |
| Ledger entry 11 | SH as field/threshold influence, "never a per-cell master controller" | current | yes | — |
| Ledger entry 13 | "Swarm Hunter applies the *brief* gradient, never holds it" | current | yes (future-facing) | — |
| Ledger entry 14 | "Resonance / grid-spectroscopy offline detection — adjacent primitive (`DensityPhaseDetector`, dormant Nextness Observer); **observer-only**"; GPU-explore/CPU-verify doctrine | current | yes — detector precedent | — |
| `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` §2 | SH work should improve "harnesses and validation loops around *trusted telemetry* … not rewrite the Medusa engine"; symbolic regression only after observer metrics are trusted | current | yes | — |
| Maturin §3 (cascaded telemetry) | cheap macro-observers first, zoom on anomaly; read-only until a later Lane A gate | current | yes (shapes detector design) | — |
| Maturin §4 | "the Swarm Hunter must **not** command individual cells" | current | yes | — |
| `docs/LANE_A_READINESS_REVIEW.md` §9 | no global-controller behavior; any future tuning local-rule/threshold, gated on trusted observer signals | current | yes | — |
| `docs/THEORY_TRIPWIRE_ACTION_DESIGN.md` + `.github/workflows/theory-tripwire.yml` | `swarm-hunter` label triggers a one-time gate reminder on PRs | current, live since PR #310 | yes (process) | — |
| `PHASE_19_NEXTNESS_OBSERVER.md` §1, §4 | Lane B is read-only; snapshot-primary data contract; explicit non-goals: no tuning writes, no reactive control, no subscriber-as-actor | current | yes — defines the adjacent observation surface | — |
| `PHASE_19_PR3_METRICS_PIPELINE.md` | "❌ Closed-loop tuning proposals" (twice) | current | yes | — |
| Ledger provisional items (ignition/cascade study) | ops-dir, provisional, non-canonical | provisional | no (must not be cited as fact) | Kev/Jack |
| Open-issue board | **no Swarm Hunter issue exists** | current | n/a | — |

No contradictory sources were found: every statement about Swarm Hunter in tracked text
constrains it in the same direction (observe/surface: yes; control: no). `[SRC]`

## 2. Terminology ledger and concept resolution (Pass 1)

| Term | Classification | Evidence |
|---|---|---|
| `Swarm Hunter` / `swarm-hunter` | repository-defined **constraint set**, mechanism **undefined** | provenance map above; label exists; no code, no issue |
| `Lane A` | repository-defined (engine-consumer + intervention lane), PARKED | PHASE_19 §1; LANE_A_READINESS_REVIEW |
| `observer` / `nextness` | repository-defined operational mechanism (Lane B, built & calibrated) | `scripts/nextness_observer.py` vocabulary + PHASE_19 docs |
| `promotion gate` / `theory-to-architecture` | repository-defined process (ledger graduation §; tripwire labels) | ledger tail; tripwire workflow |
| `shadow grid` | **[ABSENT]** — AURA metaphor; no tracked occurrence | repo-wide search |
| `LeanCTX` | **[ABSENT]** — AURA metaphor; engineering contract proposed in §8 | repo-wide search |
| `self-label` / self-labeling | **[ABSENT]** | repo-wide search |
| `proprioception` | defined only in `crates/vanguard-mcp/src/proprioception.rs` (Vanguard subsystem, unverified-cluster lineage) — **not** a CA-engine mechanism | `[SRC]` |
| `closed loop` | appears **only as an explicit non-goal** | `PHASE_19_PR3_METRICS_PIPELINE.md:25,291` |
| control agent (SH-as-controller) | **prohibited interpretation** | ledger 2/11/13; Maturin §4 |

**Concept resolution.** The repository's evidence converges on Swarm Hunter v1 as an
**offline candidate-structure detector** — an instrument that reads immutable evidence
and *surfaces* candidate structures/hypotheses for human review (ledger entry 7's
wording), in the same family as the entry-14 "grid spectroscopy" precedent and the
Maturin §3 cascaded-telemetry shape. The rule-search reading is adjacent but governed
separately (entry 14's GPU-explore/CPU-verify doctrine; the parked calibrated
instrument). The control-agent reading is prohibited. **Deliberately left unresolved**
(conflicting pull, preserved rather than resolved): whether SH should be a *new
instrument beside* the Nextness Observer or an *extension of* it — entry 14 suggests
proximity, PHASE_19's tight Lane-B non-goals suggest separation. Decision owner:
AURA + Jack + Kev at stage S4 (§10). `[SRC/PROP]`

## 3. Glass-Wall information-flow contract (Pass 2) `[PROP]`

Six data classes, strictly ordered; information flows only rightward:

```text
(1) authoritative physics state        [live engine memory — NEVER touched by SH]
(2) immutable snapshot/checkpoint      [data/v070_gen*.npz — read-only evidence lane]
(3) derived shadow/summary data        [SH working arrays computed FROM (2)]
(4) candidate detections               [findings artifact, JSONL, schema §5]
(5) human-reviewed promotion packet    [LeanCTX artifact §8 → Jack/Kev audit]
(6) prohibited write-back              [does not exist; no arrow returns]

physics/snapshot → offline analysis → findings artifact → human/Jack audit
```

**There is no reverse arrow.** Explicitly prohibited: modifying active state; calling
the stepper from findings code; changing parameters; applying labels automatically;
opening or merging implementation PRs automatically; treating an observer token as an
instruction; adjusting survival/birth thresholds; autonomous retry loops against
production physics; using confidence scores as authorization.

**Enforcement layers (structure, interfaces, tests, governance — not comments):**

- **Repository structure:** v1 lives under `experiments/swarm_hunter_lab/` — outside
  `scripts/` (production), outside `tests/` (the CI floor, `pytest.ini`-scoped), with
  zero imports from `scripts/` and zero access to `data/`. It *cannot* reach the
  stepper without an import that review would see.
- **Interfaces:** the detector's entire input surface is `(arrays, provenance dict)`
  passed by value; it has no path/network/API arguments in v1. Its only output is a
  findings object serialized by the caller. No handle to any mutable system exists in
  its signature.
- **Tests:** property tests assert no-filesystem-writes (beyond the explicit findings
  artifact), no-network, input-hash invariance (inputs unchanged after analysis), and
  output determinism (§7). A findings-schema test rejects any field resembling an
  actuation command.
- **Governance:** the `swarm-hunter` tripwire label + this preflight + the ledger
  entry-2 guardrail + stage gates (§10). Ratifying entry 2 from *candidate* to
  *canonical* is recommended at S4.

## 4. Threat and failure model (Pass 3) `[PROP]`

| # | Risk | Cause | Detectable signal | Fail-safe behavior | Smallest falsifier | Residual risk | Blocks v1? |
|---|---|---|---|---|---|---|---|
| 1 | Observer-to-controller drift | scope creep; "just one small actuation" | any import of tuning/stepper APIs; schema gains verbs | structural fence (§3); schema test rejects | grep-based CI check on the lab dir | social, not technical | no — design excludes |
| 2 | Stale snapshot analysis | analyzing old gen believing it current | provenance `generation` + snapshot mtime in findings | findings always carry snapshot identity; no "current state" claim permitted | fixture with mismatched claimed/actual gen → must flag | low | no |
| 3 | Partial/corrupt artifact input | truncated NPZ, bad channel order | load-time shape/channel validation (channel-first contract) | refuse + structured error finding; never guess | truncated toy NPZ fixture | low | no |
| 4 | Nondeterministic ordering | set/dict iteration, parallel reduction | replay divergence | canonical ordering rule (§5); replay test | run twice, byte-compare | low | no |
| 5 | Seed/generation mismatch | provenance fields transposed | schema type/width checks | reject malformed provenance | swapped-fields fixture | low | no |
| 6 | Configuration mismatch | detector tuned for 5-state reads 3-state legacy grid | `NUM_STATES` validation at load | refuse unsupported case | legacy-shape fixture | low | no |
| 7 | Hash/provenance blind spot | hashing lattice but not memory/inactivity | hash covers the full snapshot triple (replicate precedent, `ca/docs/README.md`) | document exactly what the input hash covers | fixture differing only in uncovered array | **carried**: `age_grid`/`half_step_flags` coverage question from the RNG packet remains open | no (documented) |
| 8 | False structure detection | thresholds too loose; noise clusters | fixture suite false-positive rate | findings carry reasons + thresholds; class HYP until S3 | adversarial-noise fixture | medium — inherent | no |
| 9 | Missed structure | thresholds too tight | known-cluster fixture recall | report absence honestly; no "clean" claim beyond fixtures | single-cluster fixture | medium — inherent | no |
| 10 | Repeated-event double counting | same structure found each snapshot | stable finding IDs + dedup (§5) | dedup by (region-hash, persistence chain) | two-snapshot same-cluster fixture | low | no |
| 11 | Toroidal-boundary mistakes | treating wrapped cluster as two | periodic-aware components (§6) | torus fixtures mandatory | wraparound-cluster fixture | low | no |
| 12 | Unbounded memory | pathological component counts | hard caps (§5) | truncate + explicit truncation flag | worst-case checkerboard fixture | low | no |
| 13 | Unbounded runtime | quadratic pair scans | complexity budget; caps | abort + partial-result flag | resource-bound fixture | low | no |
| 14 | Active-region bias | analyzing only "interesting" regions | whole-lattice pass in v1 (no sampling) | if sampling ever added: deterministic keying (§9) | — | deferred | no |
| 15 | Threshold overfitting | tuning thresholds to one organism epoch | thresholds recorded per finding; S3 cross-validation | evidence classes; no generalization claim | disjoint-epoch fixtures (S2+) | medium | no |
| 16 | Accidental canonical claims | excited prose | keyword sweep (Pass 12 discipline); Jack audit | evidence-class labels mandatory | doc grep | low | no |
| 17 | Narrative outruns evidence | metaphor reuse ("hunting", "intelligence") | same | mechanism words only in contracts | doc grep | low | no |
| 18 | Resumption duplicating GitHub writes | scheduled resume re-running a completed pass | continuity file write-ledger | check branch/PR/label existence before any write | resume drill against COMPLETE state | low | no |

No risk blocks a **toy-only** v1; several (7, 15) shape the S2/S3 gates. `[PROP]`

## 5. Formal v1 contract (Pass 4) `[PROP]`

**Shape:** an offline candidate detector (per §2 resolution): a pure function from
immutable inputs to a findings artifact.

- **Allowed inputs (v1/S1, toy-only):** in-memory arrays — `states: u8[N³]` (5-state,
  `memory.rs:19–24` semantics), optional `memory: f32[8][N³]` channel-first, optional
  `inactivity: i16[N³]` — plus a provenance dict. **No file, network, API, or `data/`
  access in S1.** S2 (real snapshots) is a separately keyed stage (§10): `data/` is
  evidence-lane material under Kev's hard gate.
- **Required provenance fields:** `{snapshot_id, sha256_triple, generation: u64-safe
  int, lattice_size, num_states, channel_layout_version, source: synthetic|snapshot}` —
  findings without full provenance are invalid by schema.
- **Deterministic ordering:** cells row-major (`z·N²+y·N+x`, matching
  `voxel_lattice.rs:56–62`); components labeled by minimum member index; findings
  sorted by (label, first-seen generation); no hash-map iteration order may leak.
- **Bounded resources:** ≤ 64³ lattices in S1; component count cap (default 4,096) and
  runtime budget with **explicit truncation flags** when hit — truncation is a
  reported result, not an error.
- **Output schema (JSONL, one finding per line):** `{finding_id, detector: {name,
  version}, snapshot: provenance, region: {bbox_min[3], bbox_max[3],
  wraps: [bool;3]}, periodic_interpretation: "torus", cell_count, state_counts: {per
  state}, density, persistence: {seen_in_snapshots, chain_id} (when multiple snapshots
  supplied), reasons: [{predicate, threshold, measured}], evidence_class:
  SRC|CALC|HYP, truncated: bool}`.
- **Excluded from findings, by schema:** commands or parameter suggestions of any kind;
  birth/survival recommendations; actions; uncalibrated confidence scores; claims of
  consciousness, intent, or agency.
- **Stable IDs + dedup:** `finding_id = sha256(detector_version ‖ snapshot_id ‖
  canonical-region-encoding)[:16]`; persistence chains link findings across snapshots
  instead of re-emitting duplicates.
- **No-write guarantees:** inputs are never mutated (hash-before == hash-after test);
  the only artifact is the findings object returned to the caller.
- **Error behavior:** malformed input → structured refusal finding (`evidence_class:
  SRC`, reason `invalid_input`), never a partial silent result. **Empty result** is a
  first-class artifact: a run that finds nothing emits a header record saying so.
- **Replay contract:** identical inputs ⇒ byte-identical findings artifact.
- **Versioning:** `DETECTOR_VERSION` participates in `finding_id`; any algorithm change
  bumps it (golden fixtures make drift visible — the PR #315 pattern).
- **Rollback:** delete the lab directory; no state, no migrations.
- **Unsupported cases (explicit):** non-cubic lattices; `num_states ≠ 5`; non-periodic
  boundaries; live-process attachment; GPU arrays.

## 6. Detector options matrix (Pass 5)

| Family | Data needed | Determinism | Memory | Runtime | Torus handling | False-positive surface | Glass-Wall fit | Testability | Smallest falsifier | v1 suitability |
|---|---|---|---|---|---|---|---|---|---|---|
| **Connected-component persistence** (non-VOID components tracked across snapshots) | states (+ optional memory summaries) | full (union-find, canonical labels) | O(N³) ints | O(N³ α) | wrap-aware union-find | moderate (noise blobs → size/persistence thresholds) | pure read | excellent (small fixtures) | two-cluster + wraparound fixtures | **PRIMARY** |
| **Stable/periodic local-hash detection** (per-block content hash; stability/periodicity across snapshots) | states (+ blocks) | full | O(blocks) | O(N³) | periodic block tiling | low for stability; period claims need ≥ p+1 snapshots | pure read | excellent | stable + transient fixtures | **SECONDARY (optional)** |
| Density-spike detection | states + baseline statistics | full | O(N³) | O(N³) | box filters exist as precedent (`filters.rs:79`) | high until baselines exist (needs epoch statistics) | pure read | good | noise fixture | v2 — needs S2 baselines |
| Moving-front / cluster-cohesion tracking | dense temporal sampling | full | O(N³·T) | high | hard | high at ~10-min snapshot cadence (`PHASE_19 §4`) — motion aliases badly | pure read | moderate | oscillator fixture | rejected for v1 (cadence mismatch) `[CALC]` |
| Observer-token correlation | observer JSONL + snapshots | full | O(patches) | low | inherited | n/a (annotation, not detection) | pure read | good | token-fixture join | **S3 comparison layer, not a v1 detector** |
| Rule-search scoring | engine/replicate runs | n/a here | — | — | — | — | touches parked instrument + GPU doctrine (ledger 14) | — | — | out of scope — separately governed |

**Selection (a proposal, not canon):** primary = **connected-component persistence**;
optional secondary = **stable local-hash periodicity** (shares the block/tiling
machinery). Both run on immutable arrays alone, need no RNG, no baselines, no engine
contact, and have small mathematical fixtures. `[PROP]`

## 7. Deterministic toy harness design (Pass 6) `[PROP]` — designed, not implemented

Fixtures (all synthetic arrays, ≤ 32³ unless stated; expectations labeled
**M** mathematical / **S** source-derived / **H** hypothetical):

| Fixture | Content | Expected findings | Expectation class |
|---|---|---|---|
| empty | all VOID | none — empty-result header only | M |
| single cluster | one 3³ STRUCTURAL block | exactly 1 finding, correct bbox/counts | M |
| two separated clusters | two blocks, gap > 1 | exactly 2, stable distinct IDs | M |
| wraparound cluster | block spanning the +x/−x seam | exactly **1** finding, `wraps=[true,false,false]` | M (torus definition) |
| transient cluster | present snapshot 1, absent 2 | persistence chain length 1; no double count | M |
| stable cluster | identical across 3 snapshots | one chain, `seen_in_snapshots=3` | M |
| oscillator (period 2) | alternating pair of shapes | secondary detector reports period 2 with ≥ 3 snapshots; primary reports persistence | M |
| adversarial noise | deterministic pseudo-random single cells | findings only below thresholds → none above min-size | H (threshold-dependent — the point of the fixture) |
| malformed provenance | missing sha256 field | structured refusal, no analysis | M (schema) |
| resource bound | checkerboard (maximal components) | truncation flag set at cap, deterministic prefix | M |

Property tests: input-order independence (fixture dict order shuffled); replay identity
(byte-equal artifacts); **translation invariance on the torus** (same cluster shifted ⇒
same counts/shape, different absolute bbox, `wraps` consistent); stable IDs across
runs; dedup across snapshot chains; bounded output size; input hashes unchanged; no
network (no socket imports); no filesystem writes outside the explicit artifact.

## 8. LeanCTX artifact contract (Pass 7) `[PROP]` — metaphor → engineering

A **bounded audit handoff** (the only thing a reviewer must read), containing exactly:
run identity (detector name/version, timestamp, continuity-runway id) · input hashes
(per snapshot triple) · bounded summary (≤ 50 findings-table rows: id, region, counts,
persistence, evidence class) · **changed findings since prior run** (new / vanished /
persisted, by chain id) · **one minimal anomaly excerpt** (the single highest-signal
finding, full record) · **falsifiers or failed invariants** (any property-test failure
or truncation, always included — a summary that omits failed cases is invalid) ·
omitted-payload declaration (what was truncated and why).

Limits: ≤ 64 KiB or ≤ 200 records per artifact, whichever first; deterministic
truncation (sorted order, cut tail, `truncated: true` + counts of omitted records).
Prohibited: tensor dumps; snapshot copies; unbounded logs; silent truncation;
summaries that hide failures.

## 9. Relationship to observer and RNG work (Pass 8)

- **Can v1 operate entirely on immutable snapshots?** Yes — S1 doesn't even need
  snapshots (synthetic arrays); S2 is snapshot-only by contract. `[PROP]`
- **Does it require RNG?** **No.** Both selected detectors are deterministic. `[CALC]`
- **If sampling is ever added:** keyed deterministically by a counter tuple in the
  LAB-CRNG-v1 style (`docs/COUNTER_INDEXED_RNG_FEASIBILITY.md` Appendix) — never by a
  stateful stream. `[PROP]`
- **Does PR #315 unblock anything directly?** No hard dependency — it improves future
  replay/scheduling options. No dependency is created merely because the arcs are
  adjacent. `[SRC]`
- **What evidence would a changed RNG stream invalidate?** Trajectory-derived
  expectations only. Snapshot-anchored findings cite the snapshot hash + generation
  and remain valid for that snapshot regardless of stream. `[CALC]`
- **Observer tokens as annotations?** Yes at S3 — joined to findings as *descriptive
  context* (entry-14 precedent), with schema-level exclusion from `reasons` so a token
  can never become a control input or detection trigger. `[PROP]`

## 10. Promotion ladder (Pass 9) `[PROP]`

| Stage | Content | Prerequisites | Evidence required | Tests | Rollback | Gates |
|---|---|---|---|---|---|---|
| **S0** | this preflight document | — | provenance map | n/a | close PR | Jack audit; Kev merge word; `swarm-hunter` label |
| **S1** | toy offline detector in `experiments/swarm_hunter_lab/` (synthetic arrays only) | S0 sealed; Kev implementation word | §7 fixtures green; properties green | full §7 suite | delete lab dir | Jack audit; Kev word; label |
| **S2** | immutable-snapshot analyser (reads real `data/` NPZ) | S1 sealed; **explicit Kev evidence-lane key (`data/` is a hard gate)**; hash-coverage question resolved | S1 evidence + real-snapshot dry runs with receipts | §7 + provenance/refusal tests on real headers | disable path; artifacts deleted | Jack audit; **Kev evidence-lane word**; label |
| **S3** | comparison against observer outputs | S2 sealed; observer artifacts available | correlation report, evidence-classed | join determinism tests | drop join layer | Jack audit; Kev word; label |
| **S4** | human-reviewed candidate architecture (instrument-vs-extension decision; entry-2 ratification proposal) | S3 sealed | LeanCTX packets from S1–S3 | n/a | archive | **AURA + Jack + Kev** |
| Lane A / engine integration | **not part of this ladder's authorization** | separate future decision | — | — | — | separate keys entirely |

**Passing S1–S3 does not authorize a closed loop.** Hard-stop conditions at every
stage: any write path toward physics; any actuation field in a finding; any `data/`
access before the S2 key; any claim drift flagged by audit.

## 11. Readiness ruling (Pass 10)

**CONDITIONAL GO** for a toy-only offline v1 (S1), with named prerequisites:

1. Jack's audit of this preflight (S0) and Kev's merge word for it.
2. A separate, explicit Kev implementation word for S1 (this document is not it).
3. The S1 fence exactly as specified: new directory `experiments/swarm_hunter_lab/`
   (detector module + fixtures + lab-local tests), **no imports from `scripts/`, no
   `data/` access, not collected by the CI floor** (`pytest.ini` scopes collection to
   `tests/`); dependency policy: numpy only (already the project floor); no new
   dependencies.
4. Test fence: the §7 fixture and property suite lives inside the lab; the maintained
   `tests/` suite is untouched.
5. Estimated bounded runtime: full §7 suite < 10 s CPU on toy sizes `[CALC — to be
   measured, not promised]`.
6. Labels: `swarm-hunter` on every ladder PR (tripwire fires by design; acknowledged
   by humans, never by the seat).
7. Rollback: delete the lab directory.

**Rejected alternatives:** SH-as-controller (prohibited by ledger 2/11/13, Maturin
§4); rule-search-first (separately governed; parked instrument); moving-front tracking
at current snapshot cadence (aliasing, §6); density-spike v1 (needs S2 baselines);
starting inside `scripts/` or `tests/` (fence violations); sampling with stateful RNG
(replay hazard); any S2 start before the evidence-lane key (hard gate).

**Open questions (owners):** instrument-vs-extension identity (AURA+Jack+Kev, S4);
entry-2 ratification to canonical (team, S4); snapshot hash coverage of
`age_grid`/`half_step_flags` (engine-gated check, before S2); observer-artifact
availability contract for S3 (Jack); whether S1 belongs in the theory-sandbox policy
family or as its own lab README (Jack, at S1 PR).

---

*Preflight ends. Nothing above is activated by being written down; the ladder's keys
stay in Kev's hands, the audits in Jack's, and Lane A stays parked exactly where the
handoff says it is.*
