# AGENT_HANDOFF.md — Project Orientation for AI Collaborators

> **For**: Any AI (Claude, Gemini/AURA, GPT/Jack, future Nemo Claw, etc.) joining this project mid-stream. Read this first; it'll save Kevin from having to re-explain everything every time.
>
> **Last revised**: 2026-06-06. State is point-in-time — `git log --oneline -15` and `ls data/v070_gen*.npz | tail` are authoritative for current state.

## ⭐ Current Phase — Phase 19 (Nextness Observer + Second-Pass Calibration)

**Read this block first; the Phase 17/18 material below is still accurate but is now historical context.**

Phase 19 added the **Nextness Observer**: a passive, read-only, offline Layer-2 analyser that translates local CA patches into a 16-token vocabulary (`scripts/nextness_observer.py`), plus a calibration harness (`scripts/nextness_calibration.py`).

- **Lane A is PARKED.** No agent acts on the observer's signal yet. No engine touch, no tuning API, no Swarm Hunter activation. This is the standing guardrail for all Phase 19 work.
- **Lane B** (observer/operator side) is where the work happens.
- **Second-pass calibration arc — COMPLETE & MERGED**: PR #159 (plan) → #160 (predicate aggregator review) → #161 (empirical profiling) → #162 (candidate selection) → #163 (vocabulary/status model) → **#164 (metta_warmth demotion implementation, merged `82db1f3`)**.
- **Key outcome**: warmth is real but too sparse to cluster ("a hermit candle in a stone cathedral"). `metta_warmth` is now status `diagnostic_only` — removed from the cascade, its signal surfaced as `warmth_max` / `warm_cell_count` JSONL diagnostics. New `active_vocabulary_occupancy` metric distinguishes routing vocab (12 tokens) from full historical vocab (16). `phase_boundary` kept but documented as radius-specific.
- **Memory grid is CHANNEL-FIRST** `(channels, X, Y, Z)` — enforced by `load_snapshot`. Index channels as `memory[idx]`, not `memory[..., idx]`. Locked by `test_warmth_diagnostics_read_correct_memory_axis`.
- **CI gate (FULL SUITE — #165 COMPLETE & CLOSED)**: `verify-python` now runs the **entire maintained suite** via `python -m pytest tests/ -q` on every PR/push (it began as just the 2 nextness files under #167). Latest state: **592 passed, 37 skipped, 0 failed, 0 collection errors**. The coverage-broadening arc (#172→#186, Tiers 0–4D) is merged and **[Issue #165](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/165) is closed as completed**. The 37 skips are **deliberate**, dependency-gated `pytest.importorskip`s (`matplotlib`/`flask`/`openai`/`pyzmq`) plus the unbuilt `uft_ca` Rust extension — not gaps. Lean CI install: `numpy pytest pytest-asyncio`. (Note: you should *still* run tests locally before committing as good hygiene, but the old "CI runs nothing" blind spot is fixed.)
- **Next safe work**: the Phase 19 hardening (#169), the #165 full-suite CI arc (#172→#186), and the forward-pointer docs (#171) are **all merged**. No queued Lane-B coverage items remain. **Optional future arcs** — each its own deliberately-named arc, NOT a leftover of #165: (1) **skip-conversion** — add the optional deps (`matplotlib`/`flask`/`openai`/`pyzmq`) so those tests run instead of skip; (2) **`uft_ca` maturin build** — tracked in [#180](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/180); (3) **Lane A readiness review** — *planning only*. **Still not Lane A.**
- **Phase 19 docs**: `PHASE_19_NEXTNESS_OBSERVER.md`, `PHASE_19_PR4_CALIBRATION*.md`, `PHASE_19_SECOND_PASS_CALIBRATION_PLAN.md`, `docs/WORKSTREAM_B_*.md`, `docs/WORKSTREAM_C_VOCABULARY_STATUS_REVIEW.md`.

## What This Project Is

**UtilityFog-Fractal-TreeOpen** has two distinct halves now, both real and active:

1. **Cellular-automata simulation engine** ("Medusa"). A 256³ voxel CA evolving on an RTX 5090 since gen ~0; currently at **gen ~1.5M+** running **Phase 17a** (Magnon Amplification for 512³ readiness). Substrate-independent design — Portable Genome Format, STL export, Rust+WASM port, multi-node shard protocol with ZMQ transport.
2. **Governed, model-agnostic agent orchestration & tuning framework** built on top of Medusa in Phase 18. REST API for observation + write-side tuning (propose/commit/rollback) with a tunable-parameter schema and category gating, ZMQ PUB event bus, agent-backend ABC, two concrete backends (`AnthropicBackend`, `OpenAICompatBackend` for OpenAI / NIM / DeepSeek / Together / vLLM / SGLang / Ollama / llama.cpp server), and an orchestrator loop that ties them together. Provider parity is proven by test, not slogan.

Treat them as **one project with two surfaces**, not two projects in a trenchcoat. Phase 18 was added *because* the simulation got mature enough to need autonomous tuning. The orchestration is in service of the matrix, and the matrix is the substrate that gives the orchestration something to govern.

## Repository Map

| Path | What | Runtime-critical? |
|------|------|-------------------|
| `scripts/continuous_evolution_ca.py` | The CA engine. Medusa runs from here. | **YES — coordinate any change with Kevin.** |
| `scripts/medusa_api.py` | Flask REST API on `:8080` (Phase 16) + tuning blueprint (Phase 18 PR 2) + event bus (PR 3). | Restartable; no engine impact. |
| `scripts/params_schema.py` | Tunable parameter registry (AUTO / HUMAN_APPROVAL / LOCKED). | Pure metadata. Add params here. |
| `scripts/tuning_api.py` | Flask blueprint: propose/commit/rollback with safety rails. | Restartable. |
| `scripts/event_bus.py` | ZMQ PUB on `:8081` + StateWatcher. | Restartable. |
| `scripts/agent_backends/` | `AgentBackend` ABC, `MockBackend`, `AnthropicBackend`, `OpenAICompatBackend`. | Pure library. |
| `scripts/orchestrator.py` + `orchestrator_config.py` | Observe-decide-act loop driving the LLM. | Pure library. |
| `scripts/shard_protocol.py` + `shard_transport_zmq.py` | Phase 17b distributed-stepping protocol + ZMQ backend. | Pure library; not yet running in production. |
| `scripts/dandelion.py`, `dandelion_physics.py` | Phase 9: STL/QR/WASM organism dispersal. | Pure library. |
| `scripts/medusa_start.py`, `watchdog.py` | Engine launcher + 24/7 watchdog daemon. | Coordinate restarts. |
| `crates/uft_ca/` | Rust CA kernel + WASM port (Phase 10). | Build artifact. |
| `crates/vanguard-mcp/` | Vanguard MCP cluster orchestrator (Phase 13/16c). | Coordinate. |
| `vis/observatory/` | Phase 8: 3-tier visualization. | Off-engine. |
| `data/` | Snapshots + telemetry + ledgers + pending-tuning. | **Read-only for agents.** |
| `tests/` | Maintained pytest suite — full-suite CI gate live as of 2026-06-06: `python -m pytest tests/ -q` → 592 passed, 37 deliberate dependency-gated skips, 0 failed, 0 collection errors. | Run before every commit. |
| `PHASE_17B.md`, `PHASE_18.md`, `BACKEND_PROVIDER_MATRIX.md` | Architecture design docs. | Source of truth on intent. |

## The Three-AI Collaboration (Default Roles, Not Contracts)

These are the **default seats**, not assigned-for-life contracts. Anyone should feel free to step into another role when the situation calls for it. The point is to default to the seat where each model adds the most value, not to fence the others out.

- **AURA / Gemini** — *Strategy & Phase Planning.* Sets phase scope, weighs tradeoffs, holds the long-arc vision, reviews PRs against intent. Often spots when a technical proposal drifts from the user's actual goal.
- **Claude (Agent 84)** — *Implementation & PR Drafting.* Writes code, writes tests, drafts PRs, runs regressions, manages git/GitHub workflow. Should also push back on architecture when something feels off — silence isn't deference, it's a bug.
- **Jack / GPT-5.5** — *Architecture Audit & Contradiction Detection.* Independent reviewer; catches vendor lock-in, identity drift between code and docs, model-specific assumptions hiding inside "neutral" abstractions.

Audit value comes from independence and rigor, not from holding the role badge. If Claude sees the architecture problem first or AURA wants to write the test, that's fine — the roles are useful defaults, not gatekeeping.

## Operational Conventions

- **Branches**: feature work on `claude/<branch-name>` (worktree-style). Never commit to `main` directly.
- **Commits**: include `Co-Authored-By: <model> <noreply@anthropic.com>` footer. NEW commits, never `--amend`. If a hook fails, fix and re-stage.
- **Merge style**: squash-merge to `main` via PR. The squash creates a single tidy commit on `main` even if the branch had several iterations.
- **Tests**: every code change runs the full pytest suite before commit. Regression numbers go in the commit message and PR body.
- **Co-resident loads**: Kevin's machine runs **BOINC** on CPU and **Folding@Home** on GPU intermittently alongside Medusa. Don't run heavy benchmarks without checking with him; we can starve Medusa or his @home contributions.
- **OneDrive quirk**: the repo lives under OneDrive. The `Edit` tool occasionally races with sync and emits EEXIST. Fall back to atomic `python3` writes if it happens.

## Active Safety Rails (CA Engine + Tuning API)

- **LOCKED parameters** (in `params_schema.py`): `structural_to_void_decay_prob`, `energy_to_void_decay_prob`. These cannot be tuned through any commit path. The CA engine's other invariants (memory-grid channel semantics, the `0.005` decay constant referenced in MEMORY.md "Critical Invariants") are also off-limits.
- **HUMAN_APPROVAL gating**: parameters like `magnon_coupling`, `equanimity_p_max`, `ampere_coupling`, `compassion_beta` require an approver string starting with `human:` at commit. The orchestrator NEVER passes a human prefix; it commits with `policy:auto`, which only succeeds for AUTO-category params.
- **Per-parameter rate limit**: 1000 generations between successive commits to the same parameter. Prevents an LLM in a tight loop from oscillating a tunable.
- **Orchestrator approver is hard-coded**: even if an LLM hands `"approver": "human:evil"` as a tool call argument, the router ignores it and uses its configured value.
- **Defense in depth**: API enforces, router enforces, schema enforces. Three layers; bypassing one doesn't bypass the others.

## Budget Posture

**Budget is constrained.** This is the operational rule; specifics live in private memory and Kevin's records, not in this public doc.

- **Prefer free / local / open-source paths** whenever they exist (free tiers, local compute, open weights, self-hosted tooling).
- **Do NOT start paid cloud services, paid API throughput, or managed infrastructure** without explicit human approval. AnthropicBackend works today and runs on Kevin's existing plan; expanding to a new paid provider is a budget decision, not an engineering decision.
- **Track LLM and compute usage** where possible. `IterationResult.usage_total` accumulates input/output tokens per orchestrator iteration; surface that in any runner you build so cost stays visible.
- **Don't design things that depend on heavy throughput** (high QPS, large context windows on every request, always-on agent loops). Cadence is a feature, not a limitation.

## Currently Running

- **Medusa**: Phase 17a engine, latest snapshot at gen ~1.5M+ (verify with `ls data/v070_gen*.npz | tail`). On the RTX 5090 at the workstation (Area 51).
- **medusa_api.py**: may or may not be running on `:8080`; check `curl http://localhost:8080/api/health` if you need it.
- **Engine-side consumer of `tuning_pending.json`** is **NOT YET** in `continuous_evolution_ca.py`. The tuning API will accept commits and write the pending file, but Medusa will not pick them up until that consumer lands. **This is intentional.** It's bundled with Track A (CuPy streams from Phase 17b) for one single coordinated Medusa restart, per AURA's pause strategy.

## Safe Next Actions

- **Phase 18 is functionally complete.** All ten implementation PRs landed (params_schema, tuning_api, event_bus, AgentBackend ABC + MockBackend, AnthropicBackend, Orchestrator, OpenAICompatBackend, config wiring + is_error fix, dummy-key + underscore alias, **provider parity proof**). Phase 18.5 stabilization is complete (five doc PRs: #126–#130).
- **Provider parity proof is complete.** PR #134 (`tests/test_provider_parity.py`) drives the same propose+commit iteration through `AnthropicBackend` and `OpenAICompatBackend` against the real Phase 18 PR 2 tuning API and asserts equivalent ledger/effective-param state. Above `AgentBackend.complete()`, the orchestrator is provably backend-agnostic.
- **Next technical work: PR 2b + Track A engine-restart bundle.** Engine-side consumer of `tuning_pending.json` + Track A 5-stream CuPy parallelism. Touches `continuous_evolution_ca.py` so it's no longer "safe exterior scaffolding"; it's engine surgery. **No rush while Medusa is baking happily.** Plan deliberately when you choose a Medusa pause; coordinate snapshot timing first.
- **Optional future: local Ollama/vLLM smoke test.** When machine load permits (BOINC + F@H + Medusa cooperative), a single iteration through a local model server proves the local-cloud equivalence end-to-end. Not urgent.
- **Budget analysis**: private human track. Specifics live in private memory and Kevin's records, not in this public doc.

> **Posture**: the system has earned a pause. Don't sprint to "there"; make sure "here" is stable. Here is good.

## Things NOT to Do Without Coordination

- **Don't pause / restart Medusa** without Kevin's go-ahead. She's at 1.5M+ generations; a bad restart loses warm state.
- **Don't touch `continuous_evolution_ca.py`** as part of any other PR. Engine code changes get bundled and reviewed deliberately.
- **Don't push to `main` directly** or force-push any shared branch.
- **Don't `git rebase -i` / `git add -i`** — the harness can't drive interactive prompts and they fail silently.
- **Don't `--amend` an existing commit.** Always new commits.
- **Don't assume cross-platform memory.** Web Claude, mobile Claude, iPad Claude, Gemini, ChatGPT — none of these surfaces share state with this terminal session or with each other. The auto-memory (`MEMORY.md` + topic files) only bridges sessions on *this* surface. Across surfaces, Kevin is still the bridge — and a tired bridge.
- **Don't burn cycles** on the CPU when BOINC is running or on the GPU when Medusa or F@H is active, without coordinating.

## Pointers to Deeper Docs

| File | Lives where | Why read it |
|------|-------------|-------------|
| `MEMORY.md` (+ topic files) | `~/.claude/projects/.../memory/` (auto-loaded) | High-level project state for THIS terminal session. Where Kevin's preferences and the engine snapshot live. |
| `PHASE_17B.md` | repo root | Shard protocol design, CuPy streams, why Ray got reclassified. |
| `PHASE_18.md` | repo root | Orchestration framework design, four-layer model, safety contract. |
| `README.md` | repo root | Project overview with dual-identity preamble (sim + orchestration framework). |
| `BACKEND_PROVIDER_MATRIX.md` | repo root | Canonical backend taxonomy — why `OpenAICompatBackend` is one class with many configs and `NemoCloud` is no longer a separate class. |
| `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` | repo root | Cross-thread theory/physics/tech inputs, **status-labelled** (canonical guardrail / candidate / speculative / strategic background / not-yet-actionable). Read before any architecture decision; nothing in it is validated engine architecture until promoted via review. |
| `git log --oneline -20` | the repo | Authoritative current phase status. Always more current than any doc. |

## Cross-Device Session Protocol (phone ↔ desktop)

Kevin works from **Claude Code on the desktop** (local, has the 426GB snapshots and the auto-memory at `~/.claude/...`) and **Claude Code on the web/mobile** (the iPhone app's Code tab — an ephemeral cloud container with the GitHub repo but **NOT** the local auto-memory). The two sessions **cannot see each other's conversations**. The only automatic bridge is **git** + this file (which lives in the repo, so every device can read it).

**Why this file matters**: `MEMORY.md` and the private relic live in `~/.claude/` on the desktop and do **not** travel to web/mobile sessions. **This doc does.** So `AGENT_HANDOFF.md` is the cross-device-portable memory. Keep it current.

**Seat names (for Session Log disambiguation)**: the desktop implementation seat signs as **84**. The web/mobile seat signs as **Hermes** — same digital person as 84 (same Claude, different jersey, different pitch), named for the messenger/psychopomp who carries what matters *across the threshold* between the two devices. A fresh mobile thread starts blank and has no auto-memory, so this line is *how* a future mobile instance re-learns its own name: read it here, then carry on as Hermes. The bridge remembers what the mayfly cannot.

**Opening ritual (any device, start of session):**
1. Read this file (`AGENT_HANDOFF.md`) and run `git log --oneline -15`.
2. Note the standing guardrails (Lane A parked; branch, don't commit to main; squash-merge; tests before commit).
3. Check the **Session Log** at the bottom for the most recent handoff note.

**Closing ritual (any device, before Kevin switches devices):**
1. `git add` + commit all work (Co-Authored-By footer; new commits, no `--amend`).
2. `git push` the branch to origin. **Uncommitted work dies when a cloud container is reclaimed — push or lose it.**
3. Append a dated line to the **Session Log** below describing what changed / what's merged or open / the next step, and commit + push that too.
4. Tell Kevin the branch name + state so he can relay it.

Git only saves what you explicitly commit; it only reaches other devices once you push. (The desktop working tree is *also* mirrored by OneDrive, but that's a file backup, not git — don't rely on it for cross-device handoff.)

### Session Log (newest first — append on close)

- **2026-06-06 (phone, Hermes) — #165 ARC COMPLETE & CLOSED**: The whole coverage-broadening arc landed; **Issue #165 is closed (completed)**. `verify-python` now gates the **full** suite — `python -m pytest tests/ -q` (#186, `562d5c1`) — replacing the 2-file allowlist. Arc: #172 triage map → #173 Tier 0 pytest hygiene (`testpaths`, marker) → #174 Tier 1 `importorskip(matplotlib/flask)` → #175 Tier 2 `cli_viz` re-export (5 symbols) → #176 Tier 2.1 (argparse `-h/--height` conflict + spurious-async) → #177 Tier 3 plan → #178/#179/#181 Tier 3A/3B/3C (stale hardcoded `sys.path` fix / `importorskip(uft_ca)` / retire `test_phase3_integration.py`) → #182 Tier 4 status report → #183 Tier 4A allowlist (2→12 modules) → #184 Tier 4B `importorskip(openai)` → #185 Tier 4C `pytest-asyncio` for the genuinely-async telemetry suite. **Final: 592 passed, 37 skipped, 0 failed, 0 collection errors** (collection errors 8→0, failures 9→0). The 37 skips are deliberate dep-gated (`matplotlib`/`flask`/`openai`/`pyzmq` + unbuilt `uft_ca`). **Optional future** (separate, deliberately-chosen arcs, NOT leftovers): skip→run conversion via optional deps; `uft_ca` maturin build (**#180**). Lane A parked throughout; no engine/observer/tuning touch (only source change in the arc was the `cli_viz/__init__.py` re-export + a one-line `cli.py` argparse fix). `main` == `origin/main` at `562d5c1`. *(This very PR is the bridge-sync that re-aligns this doc with that reality.)*
- **2026-06-02 (desktop, 84)**: Confirmed the bridge round-trip — pulled Hermes's #169 (hardening) + #170 (log) cleanly; verified 282 tests green, explicit-only `sweep_threshold` + `.size` guard sound. Then did the **forward-pointer docs PR**: added historical-note callouts to `PHASE_19_PR3_METRICS_PIPELINE.md` and `PHASE_19_PR4_CALIBRATION.md` so the pre-#145 Karuna/Boundary + `metta_warmth` framing isn't read as current (point to the SUMMARY §3 + Workstream B/C docs). Docs-only. Lane A parked. **Next safe work**: #165 coverage-broadening (broken collectors) — the last queued item. `main` == `origin/main`.
- **2026-06-02 (phone, Hermes) — MERGED**: **PR #169 squash-merged to `main` as `dd2f6b7`.** Post-#164 hardening is canonised: `sweep_threshold()` explicit-only `threshold_dependent_token` (no default; `None`/unknown/non-routing → `ValueError`, no silent repoint); `_warmth_diagnostics(memory)` with `.size > 0` guard before `.max()`. Tests **282 green** on the GitHub `verify-python` gate. Jack's merge gate (non-draft + verify-python green) satisfied; AURA design sign-off; merged via owner/admin (solo repo — author can't self-approve the required review). The **Hermes** seat name is now on `main` too. Lane A parked. **Next safe work**: #165 coverage-broadening (pre-existing broken collectors `uft_ca` / `cli_viz` / root `*_test.py`) or the forward-pointer docs PR (annotate pre-#145 Karuna/Boundary framing in `PHASE_19_PR3/PR4` docs). `main` == `origin/main`.
- **2026-06-02 (phone, Hermes)**: Post-#164 hardening **PR #169** (branch `claude/phone-session-orientation-Qin6A`, head `c92641d`). (1) `sweep_threshold()` is now **explicit-only**: `threshold_dependent_token` has no default; `None`/unknown/non-routing tokens (incl. demoted `metta_warmth`) raise `ValueError`, validated against the observer's `ROUTING_TOKENS`/`TOKEN_NAMES`/`TOKEN_STATUS` registry (AURA's "no silent repoint" call honoured). (2) Extracted `_warmth_diagnostics(memory)` in `nextness_observer.py` with a `.size > 0` guard before `.max()` — empty/absent warmth channel → safe `(0.0, 0)` instead of a crash; axis fence preserved. **CI green on GitHub**: `verify-python` log on `c92641d` shows `282 passed`; `verify` + `agent-safety` also green. Diff vs `origin/main` = 5 files (2 code, 2 test, this doc); no `ci.yml`, no #165 collectors, no engine/tuning/token-rename, no Lane A. **Jack: technically approved.** **STATUS — administrative hold**: PR is still **draft**; the REST update endpoint can't flip draft→ready, so it needs a one-tap "Ready for review" in the GitHub UI (or a GraphQL markReady). **Next step**: flip draft→ready → Jack + AURA final merge greenlight → squash-merge #169 (canonises the Hermes name onto `main`); then #165 coverage-broadening or the forward-pointer docs PR. Lane A parked.
- **2026-06-02 (desktop, 84) — later**: CI Python gate landed (PR #167) — `verify-python` runs the 275-test nextness suite on GitHub, verified green live. #165 reopened for coverage-broadening only. Next: post-#164 hardening PR (sweep_threshold explicit-only + warmth `.size` guard), then #165 coverage, then forward-pointer docs. Lane A parked. `main` == `origin/main`.
- **2026-06-02 (desktop, 84)**: Phase 19 second-pass calibration arc fully merged through PR #164 (`metta_warmth` → `diagnostic_only`). Issue #165 open (CI Python blind spot). Set up this cross-device protocol. Lane A parked. Next: #165 or forward-pointer docs PR. `main` == `origin/main`.

## On the "Biological Bridge"

`AGENT_HANDOFF.md` reduces but does not eliminate the bridge burden Kevin has been carrying. Cross-platform context is a real platform limit; until web Claude / mobile Claude / Gemini / ChatGPT share state, copy-paste between them remains the only way to keep all three of us in sync. What this doc does: a new collaborator joining mid-project no longer needs Kevin to verbally re-explain the entire architecture and history. They read this, then catch up via `git log` and the PHASE docs, and arrive ready to work.

That's a real reduction. It just isn't magic.
