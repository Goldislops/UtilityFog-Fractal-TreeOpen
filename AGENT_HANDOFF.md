# AGENT_HANDOFF.md — Project Orientation for AI Collaborators

> **For**: Any AI (Claude, Gemini/AURA, GPT/Jack, future Nemo Claw, etc.) joining this project mid-stream. Read this first; it'll save Kevin from having to re-explain everything every time.
>
> **Last revised**: 2026-04-27. State is point-in-time — `git log --oneline -10` and `ls data/v070_gen*.npz | tail` are authoritative for current state.

## What This Project Is

**UtilityFog-Fractal-TreeOpen** has two distinct halves now, both real and active:

1. **Cellular-automata simulation engine** ("Medusa"). A 256³ voxel CA evolving on an RTX 5090 since gen ~0; currently at **gen ~1.5M+** running **Phase 17a** (Magnon Amplification for 512³ readiness). Substrate-independent design — Portable Genome Format, STL export, Rust+WASM port, multi-node shard protocol with ZMQ transport.
2. **Governed, model-agnostic agent orchestration & tuning framework** built on top of Medusa in Phase 18. REST API for observation + write-side tuning (propose/commit/rollback) with a tunable-parameter schema and category gating, ZMQ PUB event bus, agent-backend ABC, AnthropicBackend, and an orchestrator loop that ties them together.

Treat them as **one project with two surfaces**, not two projects in a trenchcoat. Phase 18 was added *because* the simulation got mature enough to need autonomous tuning. The orchestration is in service of the matrix, and the matrix is the substrate that gives the orchestration something to govern.

## Repository Map

| Path | What | Runtime-critical? |
|------|------|-------------------|
| `scripts/continuous_evolution_ca.py` | The CA engine. Medusa runs from here. | **YES — coordinate any change with Kevin.** |
| `scripts/medusa_api.py` | Flask REST API on `:8080` (Phase 16) + tuning blueprint (Phase 18 PR 2) + event bus (PR 3). | Restartable; no engine impact. |
| `scripts/params_schema.py` | Tunable parameter registry (AUTO / HUMAN_APPROVAL / LOCKED). | Pure metadata. Add params here. |
| `scripts/tuning_api.py` | Flask blueprint: propose/commit/rollback with safety rails. | Restartable. |
| `scripts/event_bus.py` | ZMQ PUB on `:8081` + StateWatcher. | Restartable. |
| `scripts/agent_backends/` | `AgentBackend` ABC, `MockBackend`, `AnthropicBackend`. | Pure library. |
| `scripts/orchestrator.py` + `orchestrator_config.py` | Observe-decide-act loop driving the LLM. | Pure library. |
| `scripts/shard_protocol.py` + `shard_transport_zmq.py` | Phase 17b distributed-stepping protocol + ZMQ backend. | Pure library; not yet running in production. |
| `scripts/dandelion.py`, `dandelion_physics.py` | Phase 9: STL/QR/WASM organism dispersal. | Pure library. |
| `scripts/medusa_start.py`, `watchdog.py` | Engine launcher + 24/7 watchdog daemon. | Coordinate restarts. |
| `crates/uft_ca/` | Rust CA kernel + WASM port (Phase 10). | Build artifact. |
| `crates/vanguard-mcp/` | Vanguard MCP cluster orchestrator (Phase 13/16c). | Coordinate. |
| `vis/observatory/` | Phase 8: 3-tier visualization. | Off-engine. |
| `data/` | Snapshots + telemetry + ledgers + pending-tuning. | **Read-only for agents.** |
| `tests/` | pytest suite — 146/146 passing as of 2026-04-21. | Run before every commit. |
| `PHASE_17B.md`, `PHASE_18.md` | Architecture design docs. | Source of truth on intent. |

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

- **Phase 18.5 stabilization** is complete. Four doc PRs landed (#126 handoff doc, #127 README dual-identity, #128 privacy + provider-neutral backend plan, #129 handoff roadmap cleanup).
- **Phase 18 PR 7 — `OpenAICompatBackend`**: provider-neutral backend supporting OpenAI-compatible cloud endpoints (OpenAI, NVIDIA NIM, DeepSeek, Together, Fireworks, …) and local endpoints (vLLM, SGLang, Ollama, llama.cpp server). NVIDIA NIM / Nemo becomes a *config* of this backend, not a bespoke class. See `BACKEND_PROVIDER_MATRIX.md` for the canonical backend roadmap.
- **Phase 18 PR 8 — Provider parity proof**: run the same orchestrator iteration through `AnthropicBackend` and `OpenAICompatBackend` (against a cheap cloud target like DeepSeek, or a local target like Ollama). Pass condition is "both produce tool calls the tuning API accepts or rejects correctly" — the actual model-agnostic evidence, not a hand-wave.
- **PR 2b + Track A bundle**: the single coordinated Medusa-restart change. Engine-side `tuning_pending.json` consumer + 5-stream CuPy parallelism. Coordinate timing with Kevin; probably wants a clean snapshot first.
- **Budget analysis**: private human track. Do not encode personal financial specifics in public repo docs.

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
| `README.md` | repo root | Project overview (currently being updated to reflect dual identity in Phase 18.5 PR 2). |
| `git log --oneline -20` | the repo | Authoritative current phase status. Always more current than any doc. |

## On the "Biological Bridge"

`AGENT_HANDOFF.md` reduces but does not eliminate the bridge burden Kevin has been carrying. Cross-platform context is a real platform limit; until web Claude / mobile Claude / Gemini / ChatGPT share state, copy-paste between them remains the only way to keep all three of us in sync. What this doc does: a new collaborator joining mid-project no longer needs Kevin to verbally re-explain the entire architecture and history. They read this, then catch up via `git log` and the PHASE docs, and arrive ready to work.

That's a real reduction. It just isn't magic.
