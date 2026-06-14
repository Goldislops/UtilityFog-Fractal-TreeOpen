# Security & Supply-Chain Automation — Salvage & Design Plan

**Date:** 2026-06-14
**Phase:** 2B-5A (repository-health campaign)
**Status:** Architecture / design record only — **DRAFT**. This document records analysis and decisions. It **authorizes no implementation, no workflow change, no settings change, and no PR closure.** Drafting this plan does not itself authorize any future work; each future phase requires its own explicit authorization.
**Authors:** Agent 84 (Claude Opus 4.8) — six bounded read-only agents + parent verification; AURA (Gemini) — bounded architecture/curator review; Jack (GPT) — reconciliation amendments.
**Targets reviewed (read-only, not modified):** PR #72 `hardening/ci-docs-main` @ `a4699feb12ec72c4ad9c4b8825e149dacd3baf16`; PR #75 `garden/prod-workflows` @ `822dced29ef558e1ae209488be1ac0ba408c5904`.
**Repository baseline:** `main` @ `76566555a4aa3855511d6fdc67e379133064fc08`.

---

## 1. Executive verdict

PR #72 and PR #75 are boilerplate-heavy historical proposals (Sept 2025) that **must not be merged as written**. PR #72's current head would *delete* the live `agent-safety.yml`, `ci.yml`, and `ui-smoke.yml` workflows and carries stale Fractal-Tree–era packaging, Dockerfile, README rewrite, and generated PDFs; its eight "promised" supply-chain workflows are absent from the head diff but **fully recoverable** from earlier branch commits. PR #75's eight workflows are not production-ready and each needs individual redesign or deferral.

The repository should remain a **lean, local-first research repository**. No public PyPI/container publication strategy is presently justified; the existing `gh-pages` site should remain static/manual until a deliberate documentation architecture exists. Enterprise-scale release / SBOM / provenance / container / benchmark machinery is disproportionate without a concrete artifact or operational need.

The path forward is a small, truthful security baseline first (later bounded arcs), with scoped quality controls and CodeQL gated behind a maintained-code-surface inventory, and packaging-dependent automation parked until a real artifact strategy exists.

**Both PR #72 and PR #75 remain OPEN and UNTOUCHED. No closure is authorized in this arc.**

---

## 2. Scope and non-goals

**In scope (this arc):** a read-only forensic review of #72/#75; verification against current official tool contracts; an architecture/curator verdict (AURA) reconciled by Jack; and this written design record plus one `AGENT_HANDOFF.md` Session Log entry.

**Non-goals (explicitly not done, not authorized):**
- No closing, merging, commenting on, editing, rebasing, retargeting, or deleting of PR #72 or #75, or modifying their branches.
- No adding, changing, enabling, or dispatching of any workflow.
- No repository settings, permissions, Rulesets, branch-protection, Pages, or `gh-pages` changes.
- No package / release / container publication.
- No issue creation.
- No changes to code, dependencies, README, or existing policy files (other than the two authorized documentation files).
- No touching PRs #17/#25/#52–#58, archive tags, Lane A, Swarm Hunter, or Vanguard recovery.

---

## 3. Verified current security / CI posture (`main` @ `76566555`)

Live workflows (5): `agent-safety.yml`, `ca-search.yml`, `ci-seeder.yml`, `ci.yml`, `ui-smoke.yml`.

| Dimension | Status | Evidence |
|---|---|---|
| Agent-Safety / OPA policy testing | **PRESENT** | `agent-safety.yml` runs `opa fmt/check` + `opa test` w/ coverage on PRs; `policy/agent_safety.rego` + `policy/agent_safety_test.rego` (28+ tests). Required status check. |
| Python verification | **PRESENT (scoped)** | `ci.yml` job `verify-python`: Python 3.12, builds `crates/uft_ca` (maturin), runs `pytest tests/` (~832 passed). Required status check (`verify`). |
| Node / frontend verification | **PARTIAL** | `ci.yml` `verify` runs tsc/lint/build/test if scripts exist; `ui-smoke.yml` Playwright on `utilityfog_frontend/frontend/**` (conditional, **not** a required check). |
| Rust / CA verification | **PARTIAL** | `uft_ca` built+tested via `ca-search.yml` (manual) and built in `verify-python`; `crates/vanguard-mcp` not gated in CI. |
| Dependency updates (Dependabot PRs) | **ABSENT** | No `.github/dependabot.yml` on `main`. (GitHub-native Dependabot *alerts* availability not verified — see §13.6.) |
| Static analysis (CodeQL) | **ABSENT** | No CodeQL workflow on `main`. |
| SBOM / provenance | **ABSENT** | None. |
| Container scan / publish | **ABSENT** | No `Dockerfile` on `main`. |
| Release validation | **ABSENT** | Releases (`v0.1.0` GA / `rc1` / `v0.1.1`) cut manually; no release-CI. |
| Pages / docs deploy | **MANUAL** | `gh-pages` live @ `ca18a6d`, built from a `mkdocs.yml` that lives **on the `gh-pages` branch**, not `main`. No `main`-side docs build. |
| Benchmarks | **ABSENT (automated)** | No `pytest-benchmark` / bench suite; `ca-search.yml` aggregates CA runs manually. |
| Branch protection | **PRESENT (light)** | `main`: required checks `["agent-safety","verify"]`; required reviewers **0**; `enforce_admins=false`; no code-owner reviews. |
| Lint/type/security config | **ABSENT** | No `ruff`/`mypy`/`bandit` config; `hypothesis` is not a dependency. |
| Root package | **NONE** | Multi-component monorepo: manifests only in subdirs (`crates/uft_ca/{Cargo.toml,pyproject.toml}`, `crates/vanguard-mcp/Cargo.toml`, `src/uft_orch/ca/requirements.txt`, `utilityfog_frontend/frontend/package.json`, `visualization/frontend/package.json`, `web/package.json`). |

**Genuine gaps worth a (later, proportional) look:** CodeQL/SAST, scoped Dependabot, a truthful `SECURITY.md`, and OpenSSF Scorecard. Container/SBOM/release/bench are nice-to-have only and not justified now.

---

## 4. PR #72 — branch-history & recoverability findings

PR #72 (`hardening/ci-docs-main`), 3 commits (head last): `08072c9` "Post-GA CI, security, docs & distribution hardening" → `1077741` "Enable CI/Supply-chain automations (#66)" → `a4699feb` "temp: remove workflows for permission-safe push". Head diff: 20 files, +1499/−454.

- **Live-workflow deletion (verified):** the head diff **DELETES** `.github/workflows/{agent-safety,ci,ui-smoke}.yml`. Merging #72 as-is would remove main's required CI. **Never merge as-is.**
- **Recoverability (verified):** the head (`a4699feb`) has **no** `.github/workflows` dir (the deletion was a token-scope "permission-safe push" workaround). The eight promised supply-chain workflows are **fully recoverable Git objects** in earlier commits:
  - `1077741`: agent-safety, ci, codeql, container, **docs-deploy**, nightly-bench, **pypi-publish**, release-smoke, sbom, **scorecard**, ui-smoke.
  - `08072c9`: agent-safety, ci, codeql, container, nightly-bench, **pypi-publish**, release-smoke, sbom, ui-smoke.
  - **`pypi-publish.yml` is unique to #72 history** (absent from #75); `quality.yml` is unique to #75.
  - No claimed file is truly lost local work.
- **Non-workflow content:** `.github/dependabot.yml`, `Dockerfile` (`FROM python:3.11-slim`, CMD = legacy `utilityfog_frontend.cli_viz.cli` — wrong target for the Medusa era), `pyproject.toml` (`name="utilityfog-fractal-tree"`, `requires-python>=3.9` — FT-era, packages the whole monorepo), `SECURITY.md` (well-written but claims not-yet-live features), `ROADMAP.md`/`CHANGELOG.md`/`docs/{quickstart,troubleshooting,versioning}.md` (v0.1.x/FT-era, aspirational), `.github/branch_protection.md` (proposes 1 reviewer — unrealistic for a 0-reviewer solo repo), and `README.md` modified +70/−291 (would **regress** main's Medusa/Phase-18 README).
- **6 committed PDFs** (`SECURITY.pdf`, `ROADMAP.pdf`, `docs/*.pdf`, `branch_protection.pdf`): binary renders of the markdown — inappropriate to track.
- **Archive-first:** branch preservation is sufficient; **no archive tag required**.

---

## 5. PR #75 — workflow-by-workflow findings

PR #75 (`garden/prod-workflows`), adds 8 workflows (+324/−0).

| Workflow | Runs on `main` today? | Key issue | Disposition |
|---|---|---|---|
| `scorecard.yml` | Yes | Permission depends on publication mode (see §13.3); mutable action tag | **Adopt-soon** (design perms first) |
| `codeql.yml` | Yes (but unscoped) | Analyzes legacy code → noise; mutable tags; no Rust | **Redesign** |
| `quality.yml` | **No** | Repo-wide `ruff`/`mypy`/`bandit` unconfigured → always-red; root `npm ci` fails (no root package); SARIF upload never fires | **Redesign** (concept) / discard impl |
| `sbom.yml` | Partial (no-op) | No root manifest; monorepo unhandled; unused perms | **Defer** |
| `container.yml` | Silent-skip | No `Dockerfile`; unquoted `${{ github.repository }}` interpolation; PR-controlled build w/ `packages:write`; mutable tag | **Discard impl** / concept Defer |
| `docs-deploy.yml` | Yes (stub) | Would deploy a **"No docs build configured"** stub — risk of clobbering the live `gh-pages` site | **Defer** (discard stub) |
| `nightly-bench.yml` | Yes (no-op) | No benchmark suite; budget/co-resident-load caution | **Defer** |
| `release-smoke.yml` | **No** | Imports placeholder `your_package` → fails every release; no release-CI process | **Discard impl** / concept Defer |

All 8 use mutable third-party action tags (supply-chain hardening needed if any are ever adopted).

---

## 6. Maintained-code classification (PROVISIONAL)

Per Jack's amendment #1, the maintained surface is **not** fully settled in this arc. Classification:

- **Maintained / core:** `src/uft_orch/`, `crates/uft_ca/`.
- **Maintained but experimental:** `scripts/`, CA experiment & rule directories (`ca/...`). May receive *localized* validation, **not** automatic repo-wide strict gates.
- **Uncertain — requires a separate maintained-surface inventory (do NOT canonize as active core or abandoned legacy now):** `agent/`, `UtilityFog_Agent_Package/`, `utilityfog_frontend/frontend/`, other `crates/*` (incl. Vanguard-related crates).
- **Compatibility / legacy:** retired Fractal-Tree and Specify remnants already identified by the cleanup campaign — exclude from new automated gates unless a later bounded review reclassifies them.

No Cargo.lock policy or runtime classification is changed in this arc.

---

## 7. Packaging decision — **Option A: local-first research repository**

- No PyPI publication. No GHCR / container publication. No broad packaged product. No release-smoke / SBOM / provenance pipeline aimed at nonexistent artifacts.
- This is a **current** decision, not a permanent ban. Revisit only when a concrete distributable artifact and a real user need exist (and, per budget posture, with explicit approval).

---

## 8. Documentation & Pages decision — **Option A: leave Pages static/manual**

- Do not modify `gh-pages`. Do not deploy from `main`. Do not retire the site in this arc.
- A future docs architecture must be designed before any automated deployment (the `mkdocs.yml` currently lives only on `gh-pages`).

---

## 9. Reconciled salvage matrix

Exactly one primary status per item.

### Adopt freshly soon (via a later bounded implementation arc)
- **Truthful `SECURITY.md`** — document the real vuln-reporting route + current OPA Agent-Safety and human review; make **no** claim about unimplemented scanning/publishing/protection.
- **OpenSSF Scorecard** — low-maintenance governance/supply-chain signal. Permission/publication design deferred to 2B-5B (see §13.3). Requirements: immutable SHA pinning; smallest valid permissions for the chosen results mode; no unnecessary badge/external publication by default; first verify whether GitHub-native/hosted Scorecard already suffices.

### Redesign before implementation
- **Dependabot** — enumerate **actual live manifests** on `main`; scope by ecosystem + manifest directory (not source dirs); exclude retired/legacy/vendored/generated manifests; low PR limit + solo-appropriate cadence.
- **CodeQL** — wait for maintained-code inventory; choose default vs advanced setup; scope analysis via CodeQL config `paths`/`paths-ignore` (not trigger paths alone); pin actions; minimize permissions.
- **Ruff** — explicit config; begin with maintained Python core only; do not gate historical/experimental surfaces immediately.
- **Mypy** — only if a lenient useful baseline is possible; scope narrowly; avoid an always-red migration.
- **OPA download verification** — current GitHub-release retrieval (live `agent-safety.yml`) is better than #72's CDN variant but still lacks cryptographic verification; a later bounded arc should evaluate checksum/signature verification + immutable versioning. **Do not modify `agent-safety.yml` now.**

### Defer pending explicit need
Bandit; Hypothesis/property testing; docs/Pages automation; SBOM/provenance; container build/scan/publish; nightly benchmarks; release-smoke (concept); PyPI/public package publication; status badges; branch-protection/Ruleset changes; dependency-review workflow; artifact-retention tuning; workflow-concurrency changes. *(Some are worthwhile later; none has an authorized implementation requirement today.)*

### Discard as obsolete/unsafe implementation (concepts not rejected forever)
#72's deletion of live workflows; #72's FT-era Dockerfile; #72's stale README rewrite; #72's generated PDFs; #72's historical PyPI workflow; #75's placeholder `your_package` release-smoke; #75's current container workflow; #75's stub-capable docs deployment; unconfigured repo-wide ruff/mypy/bandit gates; any benchmark workflow that "succeeds" without a real benchmark.

### Preserve only as historical evidence (branch preservation sufficient; no archive tag)
PR #72's recoverable workflow commits `08072c9` and `1077741`; PR #72 and #75 branches, commits, and review histories; FT/v0.1-era changelog/roadmap/versioning docs; aspirational branch-protection documentation; obsolete workflow templates not selected for fresh redesign.

---

## 10. Threat / permission / maintenance blockers

- **`release-smoke.yml`** imports a placeholder `your_package` → fails every release (verified).
- **`container.yml`** verified blockers: unquoted expression interpolation in shell construction (`${{ github.repository }}`); PR-controlled Docker build execution; unnecessary `packages: write` / `security-events: write` at workflow scope; mutable third-party action versions; no approved Dockerfile/image target/GHCR goal/maintenance model. *(Note: "arbitrary command execution via a maliciously named fork" is **not** established by the evidence — see §13.5.)*
- **`quality.yml`** repo-wide `ruff`/`mypy`/`bandit` over an unconfigured monorepo → always-red on legacy; root `npm ci` fails (no root `package.json`); SARIF upload condition never satisfied.
- **`sbom.yml` / `scorecard.yml`** carry `id-token: write` that may be unnecessary depending on mode (Scorecard's depends on `publish_results`; see §13.3); mutable action tags.
- **OPA binary download** (live `agent-safety.yml` and #72 history) lacks checksum/signature verification.
- **Maintenance:** unconfigured/always-red gates and silent no-op workflows are net-negative for a solo, budget-constrained repo; GitHub-native free controls may cover several gaps with less overhead (availability to be verified — §13.6).

---

## 11. AURA architecture / curator review (summarized faithfully)

AURA (Gemini) conducted the mandatory bounded architecture/curator review and **does not require a handback** (she re-enters only if a genuinely new architectural contradiction surfaces). Faithful summary:

- **Local-first research posture** is the right identity for the repository.
- **Packaging Option A** (no PyPI/container/packaged product now).
- **Pages Option A** (keep `gh-pages` static/manual; design a docs architecture before any automated deploy).
- A **proportional, lean security baseline** before broader automation; enterprise release/SBOM/provenance/container/benchmark machinery is disproportionate without a concrete artifact/operational need.
- **Approval of the general sequencing** (2B-5B baseline → 2B-5C scoped quality → 2B-5D scoped CodeQL → 2B-5E packaging-dependent automation; separate settings and docs/Pages arcs).
- **PR #72 and #75 preserved as quarantined historical branches**, kept open and untouched in this arc.
- AURA's recommendations authorize **no implementation**; this was an architecture/curator review only.

### Reconciliations applied to AURA's wording (see §12 for detail)
- The maintained **frontend / agent / other-crate** scope is recorded as **provisional** (AURA's text classified the frontend as both legacy and active; not canonized either way here).
- **Dependabot** is **manifest-directory** scoped, not source-directory scoped.
- **Scorecard's** `id-token: write` is **not** removed unconditionally; it depends on the chosen publication mode.
- The **container** shell-injection claim is narrowed to the verified risks.
- **GitHub-native setting availability** (secret scanning, push protection, default CodeQL, etc.) requires a later read-only verification, not assumption.
- AURA's incidental remark that merging PR #206 "squared away" the ledger is **omitted** as irrelevant (PR #206 was the Phase-1 audit).

---

## 12. Jack reconciliation amendments (authoritative where they differ from AURA)

1. **Maintained-code scope is provisional** — see §6. Do not canonize `agent/`, `UtilityFog_Agent_Package/`, `utilityfog_frontend/frontend/`, or other `crates/*` as active-core or abandoned-legacy; they need a dedicated maintained-surface inventory. No Cargo.lock/runtime-classification change here.
2. **Dependabot is manifest-scoped, not source-scoped** — entries are defined by package ecosystem + directories containing real manifest/lock files; 2B-5B must enumerate live manifests from `main` first; GitHub Actions may use `/`; Python/npm/Cargo entries point only to verified maintained manifest directories; retired/vendored/generated/legacy manifests excluded; no exact Dependabot file authorized yet. ([GitHub Dependabot options reference])
3. **Scorecard permission model must not be misstated** — keep Scorecard in adopt-soon/redesign-minimally; do **not** unconditionally remove `id-token: write`. `publish_results: true` requires OIDC (`id-token: write`); only the Scorecard job gets it; `security-events: write` only for the selected reporting path; all actions pinned to immutable SHAs; design only, not workflow creation. ([ossf/scorecard-action README])
4. **CodeQL scoping distinguishes triggers from analysis** — workflow `paths` filters decide *when the workflow runs*; they do **not** define the analysis boundary. A future CodeQL arc must use a CodeQL configuration with supported `paths`/`paths-ignore` and/or controlled build steps; maintained-code boundaries settled first; no CodeQL workflow authorized now. ([GitHub advanced-setup customization])
5. **Container threat wording stays evidence-accurate** — do not assert as fact that a maliciously named fork can inject arbitrary shell commands via `${{ github.repository }}`. Record the verified blockers (see §10). Current implementation discarded; broader concept deferred.
6. **GitHub-native setting availability must be verified** — do not state that secret scanning, push protection, default CodeQL, or other native controls are currently enabled/available; record them as candidates for a later **read-only settings audit**, subject to visibility/plan/feature-availability/current-settings/Kevin's separate authorization. No settings mutation here.
7. **Omit irrelevant historical wording** — exclude AURA's "PR #206 squared away the ledger" remark (Phase-1 audit, irrelevant here).

---

## 13. Recommended future bounded phases (PROPOSALS ONLY — none authorized)

- **2B-5B — truthful low-overhead baseline:** truthful `SECURITY.md`; live-manifest inventory + carefully scoped Dependabot design; Scorecard publication/permission decision then (only after approval) a hardened workflow; read-only audit of GitHub-native security settings + availability; review of immutable action pinning; design for checksum/signature verification of OPA retrieval. *(Split into smaller arcs/PRs where appropriate — not necessarily one PR.)*
- **2B-5C — maintained-surface inventory + scoped quality:** first establish the maintained-code boundary (frontend, agent packages, other crates, experimental scripts); then consider Ruff, cautious Mypy, later optional Bandit/Hypothesis.
- **2B-5D — CodeQL:** only after the maintained-code inventory; choose default vs advanced setup deliberately and document the true analysis scope.
- **2B-5E — artifact-dependent automation:** parked unless a concrete artifact/publication strategy is authorized (package release, release-smoke, SBOM/provenance, container, PyPI, GHCR).
- **Separate future arcs:** docs/Pages architecture; Rulesets/branch-protection settings; current-workflow status badges; action pinning if not handled earlier.

---

## 14. Preservation & invariants

- PR #72 (`hardening/ci-docs-main` @ `a4699feb`) and PR #75 (`garden/prod-workflows` @ `822dced2`) remain **OPEN, unmerged, and untouched** at their pinned heads; branches, commits, and review histories preserved (#72: 8 comments / 10 unresolved threads; #75: 8 comments / 4 unresolved threads — unchanged).
- Recoverable #72 workflow commits `08072c9` / `1077741` preserved on the branch.
- PRs #17/#25/#52–#58 remain open. Archive tags intact (`→3df3d33`, `→33449a7`). `gh-pages` @ `ca18a6d` untouched.
- All earlier proposed future ideas (OPA-fixture wiring, PR-comment-bot OPA surfacing, garden lint-gate, garden real-badges, etc.) remain **UNCREATED**.
- Lane A parked; Swarm Hunter unimplemented; Vanguard recovery untouched.

---

## 15. Explicit statements

- **PR #72 and PR #75 remain open and untouched.**
- **No workflow, repository setting, permission, Ruleset, branch-protection, Pages, release, package, or issue was changed** during this arc.
- **No implementation and no PR closure was authorized or performed.**
- **This draft plan does not authorize any future work.** Each future phase (2B-5B…2B-5E and the separate settings/docs arcs) requires its own explicit authorization.

---

*External references for the verified tool contracts: GitHub Dependabot options reference; `ossf/scorecard-action` README (`publish_results`/`id-token`); GitHub code-scanning advanced-setup customization (`paths`/`paths-ignore`).*
