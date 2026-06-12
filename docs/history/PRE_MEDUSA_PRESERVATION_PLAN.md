# Pre-Medusa Historical Preservation Plan (Phase 2A — Evidence & Design)

> **Date**: 2026-06-12 · **Seat**: Fab5 (desktop/84) · **Arc**: Phase 2A — Historical Preservation Anchors: Evidence and Design
> **Status**: **DESIGN ONLY.** No archive tag, frozen branch, or prose-copy has been created. Nothing was deleted, closed, pruned, cleaned or mutated. This document and one `AGENT_HANDOFF.md` Session Log entry are the only tracked changes of this arc.
> **Parent record**: Phase-1 audit `docs/REPOSITORY_HEALTH_AUDIT_2026-06.md` (merged as `3e188a4`, PR #206). Findings F-03/F-05 and AURA's 2026-06-12 architecture review motivated this arc.
> **Evidence labels**: [verified] = command run this arc · [strong]/[weak] inference · [unknown].

---

## Part A — `hungry-nash` history: verified

### A.1 Topology [verified]

`origin/claude/hungry-nash` tip = `3df3d335d02782b61c440ef5772445ddb04c8225`. Exactly **three** commits exist on the branch and not on `main` — the audit's reported set is complete and correct:

| # | SHA | Parent | Author | Authored (local) | Subject | Diff |
|---|---|---|---|---|---|---|
| 1 | `4d42b728cf5c3d274d59625aa94c8bbaab09bcf5` | `4410a8a0` (merge-base, on `main`) | Goldislops | 2026-03-09 13:41 +11:00 | docs: overnight v0.6.0 analysis — 13hr stable limit cycle confirmed | `work.md` **+117/−0** |
| 2 | `8223ea9b300bb26ab59e85411cd95aee3dcb850c` | `4d42b72` | Goldislops | 2026-03-09 14:00 +11:00 | docs: v0.7.0 spec — The OpenClaw Memory Update (Spatial RAG + Machine Economy) | `work.md` **+534/−0** |
| 3 | `3df3d335d02782b61c440ef5772445ddb04c8225` | `8223ea9` | Goldislops | 2026-03-10 13:11 +11:00 | docs: v0.7.x Cosmic Garden spec — premise veto + overnight analysis + 5 new mechanisms | `work.md` **+526/−0** |

- **Linear chain, no merge commits, no unrelated changes** — every commit touches only `work.md`, additions only, zero deletions; 117+534+526 = **1,177 lines**, matching audit finding F-05 exactly. [verified]
- **Cumulative**: because the chain is strictly append-only, the terminal tree (`3df3d33:work.md`) contains all 1,177 lines; and because Git refs preserve **ancestry**, any ref on `3df3d33` keeps all three commits (and the entire pre-pivot history beneath them) reachable. **One terminal anchor is sufficient.** [verified]
- The in-file signature block attributes §13–§16 to "Claude (Opus 4.6) — Premise Veto Officer & Swarm Commander"; committer identity is Goldislops. [verified]
- Cross-check: "Cosmic Garden", "OpenClaw", and the 13-hr analysis text are absent from `origin/main:work.md`. [verified]

### A.2 Content sections — finer-grained than the audit's three labels [verified]

The terminal commit actually contains **four** section groups, so the material is richer than F-05's summary:

| Section (work.md) | Commit | Lines (approx.) | Historical value | Current explanatory value | Implemented / superseded? | Doctrine-confusion risk | Treatment |
|---|---|---|---|---|---|---|---|
| **§11** Overnight v0.6.0 Analysis (13-hr stable limit cycle) | 1 | 117 | High — first long-run stability evidence for the engine lineage | Medium | Superseded by later runs + live telemetry | Low (self-dated metrics) | preserve raw via anchor |
| **§12** v0.7.0 Spec "OpenClaw Memory Update" (Voxel Memory / Spatial RAG + Machine Economy; tasks for Nemo & Jack) | 2 | 534 | High — an **early design record of voxel memory**, the concept that became the engine's memory grid (generative provenance may have been distributed across sessions; no unique-origin claim is made) | High — explains *why* memory channels exist | Implemented in v0.7.0 then evolved (memory grid now 5-channel, post-#110/#111) | Medium (stale parameters read as current) | preserve raw via anchor |
| **§13** Overnight v0.7.0 Analysis (22-hr run; root cause: voxel memory inert) | 3 | ~88 | Medium | High — motivates the v0.7.1/v0.7.5 changes that *are* on `main` | Superseded by merged #110/#111 | Low | preserve raw via anchor |
| **§14** Premise Veto Rulings — Cosmic Garden proposals (7 rulings: Quantum Sync ⚠️, Halbach ✅, Agentic Micro-Economy ⚠️, Bamboo ✅, Chaos Avoidance ⚠️, Multiplexed State Passing ❌ REJECTED, CUDA 🔶 DEFERRED) | 3 | ~190 | **Highest — the governance/decision record** behind rulings still cited today | High | Decisions executed; record itself never landed on `main` | Medium — verdicts could be misread as *currently binding text*; they are a historical record, not permanently binding future decisions (operational authority: `AGENT_HANDOFF.md`; theory status: the Intake Ledger; executable truth: code + tests on `main`) | preserve raw via anchor; manifest carries explicit warning |
| **§15** v0.7.x Spec "Cosmic Garden (Vetted)" (5 mechanisms; 5-channel memory design incl. `structural_age` ch3 and `structural_stress` ch4 "reserved for v0.8.0") | 3 | ~190 | High — the spec that v0.7.5 (#110/#111) implemented; documents the design intent of today's channel layout | High | Implemented & since evolved | Medium (stale parameters) | preserve raw via anchor |
| **§16** Operational Directives (Hybrid Memory/RAG directive incl. "Jack: create `scripts/snapshot_indexer.py`"; Quarantine Vault zero-trust protocol; closing signature) | 3 | ~50 | Medium | Low | **Never implemented** — no `snapshot_indexer.py`, no `quarantine/` on `main` [verified]; role superseded by current governance (sandbox policy #199, intake ledger #188, tripwire design #198) | **High — imperative, addressee-directed instructions read as live ops** | preserve raw via anchor; manifest warning names this section specifically |

### A.3 Safety screen [verified]

Scanned all 1,177 added lines: **no secrets, no credentials, no personal data beyond author identity, no generated data, no oversized artifacts** (one false positive: "bid … tokens" is machine-economy vocabulary). Misleading-as-current-instructions risk exists only as classified above (§14 medium, §16 high) and is mitigated by the annotation/manifest wording in Part D — **the historical text itself is not edited or normalised.**

---

## Part B — PR #17 and its source branch: verified

### B.1 Identity & topology [verified]

- PR **#17** (open, untouched): head `docs/research-and-design` @ `33449a74daa8bc44dc0261222d374d09a92c5b38`, base `main`, created 2025-09-20.
- **Single commit**; parent `882aac2` (on `main`). A coherent one-shot documentation snapshot — no mixed unrelated content.
- **12 files, +1,447 markdown lines + 6 PDF twins totalling 508,224 bytes (~496 KiB)**. Every path has **zero history on `main`** — fully unique. [verified]

### B.2 Per-file classification [verified scans; value judgements are strong inference]

| File | Lines/size | Classification | Rationale |
|---|---|---|---|
| `algorithms/mindfulness_protocol.md` | 256 | **preserve raw** | unique pre-pivot concept spec with pseudocode; part of the project's founding mindfulness/memetics frame. (A hypothesised lineage to the Phase-19 observer's metta/karuna/mudita tokens was tested and **failed verification** — those names do not appear in this file [verified]; no ancestry claim is made.) |
| `algorithms/replication_rules.md` | 359 | **preserve raw** | unique concept spec with pseudocode |
| `algorithms/meme_propagation.md` | 425 | **preserve raw** | unique concept spec with pseudocode |
| `docs/DESIGN_PHILOSOPHY.md` | 188 | **preserve raw** | the BEAM/mindful-replication founding philosophy statement |
| `docs/RESEARCH_INDEX.md` | 126 | preserve **through commit history** | an index referencing structures that mostly never existed; misleading if surfaced as a document, harmless as reachable history |
| `docs/PROJECT_LOG.md` | 93 | preserve **through commit history** | point-in-time log (2025-09-20) with SpecKit-era "✅ Implemented" statuses that are now dead; self-dated but misleading if featured |
| 6 × `.pdf` twins | ~496 KiB | preserve **through commit history only** | binary duplicates of the `.md` content; oversized to feature; remain reachable via the anchor |
| *(any file)* | — | **unsafe/inappropriate to anchor: none** | secret/credential scan clean (3 false positives in PROJECT_LOG are prose *describing* a mock-first token strategy, not secrets) [verified] |

"Preserve raw" here means *raw within the anchored commit* — discoverable via the archive ref — not copied onto `main`.

### B.3 Conscious exclusion — PR #25 (`docs-cohesion`)

PR #25 carries divergent, shallower variants of two of these docs plus four 27-line "Under Development" stubs; the Phase-1 skeptic verified #17 as strictly the better salvage source and #25 as containing nothing uniquely valuable. **This plan proposes anchoring only #17's commit.** Flagged in Part H for explicit Kevin/Jack/AURA confirmation, since the #25 variant *text* (not value) is genuinely unique.

---

## Part C — Preservation-mechanism comparison

Assessed for both material sets against the verified topology (each set has a single terminal commit anchoring its entire unique chain):

| Criterion | 1. Annotated tag on terminal commit | 2. Frozen archive branch | 3. Copy into `docs/history/` | 4. Leave branch+PR untouched | 5. Annotated tag + small manifest on `main` |
|---|---|---|---|---|---|
| Durability | High — survives all branch cleanup | High, *until* a branch sweep mistakes it | High for prose; loses commit identity | Low — blocks on nothing, protects nothing once cleanup starts | **High** |
| Discoverability | Medium (`git tag -l`, GitHub tags page) | Medium | High (on `main`) | Poor (buried in 116 branches / 26 PRs) | **High** (manifest on `main` names the refs) |
| Accidental-deletion risk | Low — tag deletion requires an explicit `push --delete`; outside Phase-2F branch-sweep tooling by construction | **Elevated** — Phase 2F is literally a branch-deletion campaign; an archive *branch* sits in the blast radius and also invites accidental commits | n/a | High (the current hazard, F-05) | **Low** |
| History-vs-doctrine confusion | Low (tags read as plaques, not workspaces) | Medium (branches read as active) | **High** — 2,600+ stale lines + 496 KiB PDFs land on active `main` | Medium | **Low** (manifest states "history, not doctrine") |
| Maintenance burden | None | Low but nonzero | Ongoing (docs rot on main) | Zero now, permanent later | **Near-none** |
| Reversibility | Full (tag deletable by decision) | Full | Messy (revert commits) | Full | Full |
| Raw ancestry visible | **Yes — full chain + all pre-pivot parents** | Yes | **No** (prose only) | Yes | **Yes** |
| Branch-protection changes needed | **No** (optional GitHub tag-protection ruleset later = settings change, **not** part of this proposal) | Yes, realistically (to survive sweeps) | No | No | **No** |

**What tags do and do not guarantee**: annotated tags preserve reachability, ancestry and an explicit historical label; they do **not** make commits immutable, inaccessible, or impossible to cherry-pick into current code. The non-canonical boundary is enforced by repository governance — review gates and the annotation/manifest framing — not by the tag mechanism itself: **museum artifact, not current instruction**.

**Recommendation: Option 5, with two annotated tags** — one per material set. AURA's tag instinct is **confirmed by the verified topology**, not assumed: each set has a clean single terminal commit; tags preserve raw ancestry without protection changes; the upcoming Phase-2F branch sweeps cannot touch tags; and the manifest on `main` (this document, §D updated at implementation time) provides discoverability without promoting stale prose into active doctrine. Option 3 is explicitly rejected for the bulk text per the preferred principle; Option 2 is rejected because a preservation mechanism should not live inside the demolition zone it guards against.

---

## Part D — Proposed preservation anchors (PROPOSALS ONLY — nothing created)

| Material set | Source ref | Exact anchor SHA | Included history | Unique value | Already represented on `main` | Proposed mechanism | Candidate archive name | Risks |
|---|---|---|---|---|---|---|---|---|
| Cosmic-Garden / hungry-nash design history | `origin/claude/hungry-nash` | `3df3d335d02782b61c440ef5772445ddb04c8225` | 3 linear commits (+ full pre-pivot ancestry) — §11–§16 of `work.md`, 1,177 lines | overnight analyses, the OpenClaw spec (an early design record of voxel memory), **Premise Veto Rulings**, vetted Cosmic-Garden spec, operational directives | **No** (verbatim absent; *outcomes* implemented via #110/#111) | annotated tag + manifest row | `archive/cosmic-garden-hungry-nash-2026-03` | §14/§16 misread as live doctrine → mitigated by annotation text |
| Pre-Medusa research & design docs | PR #17 head `docs/research-and-design` | `33449a74daa8bc44dc0261222d374d09a92c5b38` | 1 commit (+ ancestry) — 6 concept docs + 6 PDF twins | founding BEAM/mindfulness/memetics philosophy + 3 algorithm concept specs | **No** (zero history for all 12 paths) | annotated tag + manifest row | `archive/pre-medusa-research-design-2025-09` | RESEARCH_INDEX/PROJECT_LOG misleading if surfaced without framing; PDFs are dead weight (acceptable inside an anchor) |

Naming uses the **material's** date (more informative as a museum label); the **preservation** date lives in the annotation. Alternative (preservation-dated `…-2026-06`) listed as open question H-2. Both names verified uncreated locally and on `origin` (only `v0.1.0`, `v0.1.0-rc1`, `v0.1.1` exist). [verified]

**The annotation message should include all of**: source branch/PR · source SHA · preservation date · "historical, non-canonical" warning · relationship to current Medusa architecture · links to the Phase-1 audit and this manifest. Draft texts:

> **Draft annotation — `archive/cosmic-garden-hungry-nash-2026-03`**
> Historical archive — NOT current doctrine.
> Preserves the pre-/early-Medusa design history from branch `claude/hungry-nash` (terminal commit `3df3d33`, authored 2026-03-09/10): overnight v0.6.0/v0.7.0 analyses, the v0.7.0 "OpenClaw Memory Update" spec (an early design record of voxel memory), the **Premise Veto Rulings** for the Cosmic-Garden proposals, the vetted v0.7.x spec, and period operational directives (§16 — never implemented; superseded by the Theory Sandbox policy and Theory Intake Ledger).
> The *outcomes* of this material were implemented and then evolved on `main` (v0.7.5, PRs #110/#111); the text here is a primary source, not implementation guidance. Operational authority is recorded in `AGENT_HANDOFF.md`; current theory status is recorded in `docs/MEDUSA_THEORY_INTAKE_LEDGER.md`; executable truth is the current code and tests on `main`.
> Preserved 2026-06 under Phase 2A (see `docs/history/PRE_MEDUSA_PRESERVATION_PLAN.md` and `docs/REPOSITORY_HEALTH_AUDIT_2026-06.md`, finding F-05).
> The fog breathes. The veto officer watches. The garden grows.

> **Draft annotation — `archive/pre-medusa-research-design-2025-09`**
> Historical archive — NOT current doctrine.
> Preserves the founding research-and-design documentation set from PR #17 (head `docs/research-and-design`, commit `33449a7`, authored 2025-09-20): BEAM/mindful-replication design philosophy, research index, project log, and three algorithm concept specs (mindfulness protocol, replication rules, meme propagation), with PDF twins.
> This material predates the February-2026 pivot to the Medusa CA engine and has **no binding current architectural authority**; it is preserved as the project's founding lore and ideation record. Operational authority is recorded in `AGENT_HANDOFF.md`; current theory status is recorded in `docs/MEDUSA_THEORY_INTAKE_LEDGER.md`; executable truth is the current code and tests on `main`.
> Preserved 2026-06 under Phase 2A (see `docs/history/PRE_MEDUSA_PRESERVATION_PLAN.md` and `docs/REPOSITORY_HEALTH_AUDIT_2026-06.md`, finding F-03/PR #17 record).

---

## Part E — Cleanup protections (in force until anchors are created AND verified)

The following must remain untouched by any cleanup wave:

- PR **#17** (must not be closed, merged or commented into a state change) and its head branch `origin/docs/research-and-design`;
- `origin/claude/hungry-nash` and the three commits `4d42b72`, `8223ea9`, `3df3d33`;
- the local branch `claude/hungry-nash` and its worktree `.claude/worktrees/hungry-nash` (a second reachable copy of the chain);
- the local branch `docs/research-and-design` (same-name local copy at `33449a7`);
- every ancestor ref required for the chains — automatically satisfied: both merge-bases (`4410a8a`, `882aac2`) are on `main`.

Explicit statements, as required:
- **No branch-cleanup wave may touch these refs.**
- **No related PR may be closed until preservation is complete** — and note: closing PR #17 would *not* itself delete `origin/docs/research-and-design`, but the rule stands so that no closure-then-sweep sequence can outrun the anchors.
- **No tag or branch deletion is authorised** by this plan.
- **Archived material is history, not implementation guidance** — it must never be cited as current architecture without going through the Theory Intake Ledger / sandbox promotion gates.

(Standing Phase-1 protections continue unchanged: `recovery/vanguard-phase13-wiring`, `gh-pages`, heads of PRs #72/#75 pending their own salvage decisions.)

---

## Part F — Architecture boundary (reconciled M'WE position, recorded verbatim-in-substance)

- The FT framework is **architecturally retired**; its generic reliability concepts (graded health, retry/backoff, failure injection, message routing) need **no Theory Intake Ledger entry** — if Medusa ever needs them, they will be implemented natively for the CA runtime.
- Pre-Medusa material has **no binding current architectural authority**; it may retain historical and explanatory value (Jack's calibration of AURA's "zero relevance" — same boundary, gentler label).
- **Vanguard** remains a separate, preserved-but-unapproved concern: passing tests prove compilation, not validity; module names alone prove neither validity nor invalidity; integration discussion requires a **mechanism-first specification and naming review**.
- **Passing tests do not promote architecture.**
- **Lane A remains parked. Swarm Hunter remains unimplemented. Sandbox evidence remains non-canonical.**

**Historical-boundary confirmations (curator-required, explicit):**
- the archived Premise Veto Rulings (§14) are **historical governance records, not permanently binding future decisions**;
- the §16 operational directives were **never implemented** [verified] and are superseded/non-operative;
- the founding memetics and mindfulness documents are **historical lore and philosophical context, not instructions to revive the pre-Medusa architecture**;
- **archive tags preserve history; they do not promote it.**

---

## Required conclusion

1. **Verified source refs and SHAs** (each checked twice this arc):
   `origin/claude/hungry-nash` → `3df3d335d02782b61c440ef5772445ddb04c8225` (chain: `4d42b728…` → `8223ea9b…` → tip); PR #17 head `docs/research-and-design` → `33449a74daa8bc44dc0261222d374d09a92c5b38` (single commit).
2. **Material requiring preservation**: the 1,177-line hungry-nash `work.md` corpus (§11–§16, incl. the Premise Veto Rulings) and PR #17's 12-file founding-docs snapshot.
3. **Material already represented on `main`**: none of the above text verbatim; the *implementations/outcomes* of §12/§15 landed via v0.7.x (#110/#111) and later evolution; §16 was never implemented and is superseded by current governance.
4. **Recommended mechanism (both sets)**: Option 5 — one **annotated tag** per set on the terminal commit, plus this manifest on `main` (updated with "created ✓" status at implementation). AURA's tag preference is confirmed by topology, not assumed.
5. **Proposed names & annotations**: `archive/cosmic-garden-hungry-nash-2026-03` and `archive/pre-medusa-research-design-2025-09`; draft annotation texts in Part D. Both names verified uncreated.
6. **Refs that must remain protected**: the Part E list (PR #17 + its branch, hungry-nash remote branch + 3 commits + local branch/worktree).
7. **Actions explicitly NOT authorised by this plan**: creating tags or branches; closing/merging/commenting PRs or issues; deleting or pruning anything; copying historical prose onto `main`; altering branch protection, settings, workflows, `.gitignore`, Vanguard, frontend, CI, Lane A, Swarm Hunter.
8. **Unresolved questions for Kevin, Jack and AURA**:
   - **H-1**: Confirm PR #25's divergent doc variants are *excluded* from anchoring (Phase-1 skeptic verdict: shallower variants + stubs, nothing uniquely valuable) — or include a third anchor?
   - **H-2**: Naming-date convention — material date (proposed: `…-2026-03` / `…-2025-09`) vs preservation date (`…-2026-06`)?
   - **H-3**: After anchors are verified, add a GitHub **tag-protection ruleset** for `archive/*`? (Settings change — would belong to Phase 2C, not this arc.)
   - **H-4**: Should the implementation arc also append a two-line "archives exist; history not doctrine" pointer to `docs/MEDUSA_THEORY_INTAKE_LEDGER.md`, or does the manifest + handoff suffice?
9. **Binary recommendation**:

**`READY FOR PRESERVATION-ANCHOR IMPLEMENTATION`**

— source set is complete and verified, topology is clean (two terminal commits suffice), content is safe (no secrets/personal/oversized-beyond-PDF concerns), names are free, and the only open questions (H-1…H-4) are preference-level, not source- or scope-uncertainty.
