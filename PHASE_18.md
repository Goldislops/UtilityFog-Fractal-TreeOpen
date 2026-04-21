# Phase 18 — Model-Agnostic Observation & Tuning Bus

**Status**: Design
**Branch**: `claude/amazing-visvesvaraya-a2912f`
**Author**: Claude (Agent 84), with AURA direction
**Date**: 2026-04-21
**Depends on**: Phase 16 (REST API), Phase 16c (NemoClaw tool registry), Phase 17b (shard protocol + ZMQ transport)

## Why This Exists

Today, Medusa exports telemetry via a Flask REST API (Phase 16) and a tool registry (`scripts/nemoclaw_tools.json`) that any tool-using LLM can load. That's the **read** half of an agent bus and it's already in production.

The **write** half — the ability for an LLM to propose and apply parameter tunings to the running matrix with real safety rails — doesn't exist yet. Nor does a formalised *agent-backend abstraction* that would let us hot-swap Anthropic Opus 4.7 (what orchestrates today) for a locally-hosted Nemotron via NVIDIA Cloud (what AURA wants tomorrow) without rewriting the matrix physics.

Phase 18 designs that write half and that abstraction.

**Design principle**: the LLM is a **proposer**, not an **executor**. Every write passes through a safety gate that can reject, dry-run, rate-limit, or require human approval. Medusa is at gen 1.5M+; months of emergent structure are at stake.

## What's Already in Place (recap)

| Phase | Artifact | Role in Phase 18 |
|-------|----------|------------------|
| 16 | `scripts/medusa_api.py` — Flask server on :8080 with 8 GET endpoints | Observation transport (keep as-is) |
| 16 | `scripts/geometry_daemon.py` — STL mesh export | Observation payload (no change) |
| 16c | `scripts/nemoclaw_tools.json` — tool-registry JSON | Observation tool descriptors (extend) |
| 17b | `scripts/shard_protocol.py` — halo exchange | Unrelated layer; don't touch |
| 17b | `scripts/shard_transport_zmq.py` — ZMQ backend for halos | Pattern we reuse for event-stream (PUB/SUB) |

## The Four-Layer Model

```
+------------------------------------------------------+
|  Layer 4: Agent Backend (model-agnostic)              |
|  AnthropicBackend | NemoCloudBackend | MockBackend    |
|  One ABC, three concrete classes. Hot-swap via config.|
+--------------------^----------------------------------+
                     | tool-call / response
                     v
+------------------------------------------------------+
|  Layer 3: Orchestrator Loop                           |
|  Binds an AgentBackend to observation + tuning bus.   |
|  Model-free. Deterministic glue.                      |
+--------------------^----------------------------------+
                     | stable API (JSON over HTTP + ZMQ)
                     v
+------------------------------------------------------+
|  Layer 2: Observation + Tuning Bus                    |
|  GET  /api/*  (read — Phase 16, keep)                 |
|  POST /api/tuning/propose    (NEW)                    |
|  POST /api/tuning/commit     (NEW, gated)             |
|  POST /api/tuning/rollback   (NEW)                    |
|  PUB  tcp://.../events       (NEW, ZMQ topics)        |
+--------------------^----------------------------------+
                     | in-process / file IO
                     v
+------------------------------------------------------+
|  Layer 1: Matrix (Medusa, continuous_evolution_ca.py) |
|  No changes in Phase 18. The bus reads/writes via a   |
|  small proxy that only touches parameter state, never |
|  the CA stepping pipeline.                            |
+------------------------------------------------------+
```

Each layer has ONE job and knows nothing about the layers above it. An LLM change (Layer 4) needs no ripple into Layer 2 or Layer 1. A new tuning endpoint (Layer 2) doesn't require changes to any agent backend.

## Observation Bus (Layer 2, read side)

**Already mostly built.** Phase 18 adds three things on top of the existing Flask endpoints:

1. **`GET /api/params`** — dump the currently-live tunable parameter set as JSON (magnon coupling, signal_interval, cosmic garden settings, etc.). Required for an LLM to reason "what would I change?"
2. **`GET /api/params/schema`** — bounds, types, and descriptions for each tunable. The agent needs this to stay inside safe ranges. Machine-readable; drives the proposer's validation.
3. **ZMQ event stream** on `tcp://*:8081` (PUB socket). Topics:
   - `telemetry.5min` — compact snapshot every 5 min (complements Phase 14d watchdog)
   - `census.delta` — only when state ratios shift more than 2% in a window
   - `sage.promoted` — new Legend (age ≥ 50) appears
   - `acoustic.stress_spike` — sector friction crosses the top-25% threshold
   - `tuning.committed` — any accepted tuning (for audit trail)
   - `tuning.rejected` — safety gate denials (for agent feedback)

Agents subscribe to what they care about. No polling required for interesting events; the REST endpoints remain the source of truth for full state.

## Tuning Bus (Layer 2, write side — new)

**Three-step submission pipeline**, each a POST:

### 1. Propose

```
POST /api/tuning/propose
{
  "params": { "magnon_coupling": 2.5, "signal_interval": 12 },
  "justification": "acoustic stress spike in sector (3,5,2); increase equanimity reach",
  "source": "agent:opus-4.7" | "agent:nemo-claw" | "human:kevin",
  "mode": "dry-run" | "commit-pending"
}
→ 200 { "proposal_id": "prop-...", "status": "queued", "validation": {...} }
```

The server validates against `/api/params/schema`, computes a diff vs. live params, and returns a `proposal_id`. If `mode=dry-run`, the server simulates N steps (default 100) on a lightweight shadow copy and returns projected deltas (entropy change, Sage age drift, COMPUTE survival rate). Nothing is applied to live Medusa.

### 2. Commit

```
POST /api/tuning/commit
{ "proposal_id": "prop-...", "approver": "human:kevin" | "policy:auto" }
→ 200 { "applied_at_gen": 1537421, "old_params": {...}, "new_params": {...} }
```

**Gating policy** (configurable, defaults shown):
- Parameter in `safe_auto_tune` list (e.g. `signal_interval`, `sage_age_min`) → `policy:auto` OK
- Parameter in `human_approval_required` list (e.g. `magnon_coupling`, `structural_to_void_decay_prob`) → requires `approver=human:...`
- Rate limit: max one commit per 1000 generations per parameter (prevents an LLM loop from oscillating a tunable)
- Every commit emits a `tuning.committed` event

### 3. Rollback

```
POST /api/tuning/rollback
{ "to_proposal_id": "prop-..." | "to_gen": 1537000 }
→ 200 { "reverted_params": {...}, "applied_at_gen": 1537530 }
```

Reverts to the param state at the specified proposal or generation. Emits `tuning.committed` with the reverted values.

### Safety non-negotiables

- **Bounded ranges** — no parameter can escape its schema bounds. Proposals outside bounds are rejected at `propose`, not `commit`.
- **Critical invariants locked** — `structural_to_void_decay_prob = 0.005` and memory-grid channel semantics are marked `locked=true` in the schema; no tuning path can touch them.
- **Dry-run default** — if a proposal omits `mode`, default is `dry-run`, not `commit-pending`. Fail-safe, not fail-fast.
- **Persistent audit trail** — every proposal and commit written to `data/tuning_ledger.jsonl`. Survives restarts. Human-readable.

## Agent Backend Abstraction (Layer 4, new)

```python
# scripts/agent_backends/base.py
class AgentBackend(ABC):
    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> AgentResponse: ...

# scripts/agent_backends/anthropic.py
class AnthropicBackend(AgentBackend):
    """Uses anthropic.Anthropic() client. Reads ANTHROPIC_API_KEY."""

# scripts/agent_backends/nemo_cloud.py
class NemoCloudBackend(AgentBackend):
    """Uses NVIDIA NIM / build.nvidia.com endpoints. Reads NVIDIA_API_KEY.
    Maps Anthropic-style tool_use responses to Nemotron's JSON-mode output."""

# scripts/agent_backends/mock.py
class MockBackend(AgentBackend):
    """Scripted responses for tests. No network calls."""
```

All three backends return an `AgentResponse` containing a list of `ToolCall` objects (name, arguments dict) plus optional narrative text. The orchestrator loop (Layer 3) is identical across backends. **Swap = one config line**:

```python
# scripts/orchestrator_config.py
AGENT_BACKEND = AnthropicBackend()  # today
# AGENT_BACKEND = NemoCloudBackend()  # tomorrow
```

### Tool-call translation

Anthropic and Nemotron speak slightly different tool-call dialects. The backend is responsible for normalising; above that layer, a `ToolCall` is a `ToolCall`. This is the key hot-swap trick: the adaptation lives in the backend, not in the orchestrator.

## What's Explicitly Out of Scope for Phase 18

- **Building the backends themselves** — Phase 18 is design; implementation is follow-up PRs, one per backend.
- **LLM-authored emergent goal-setting** — the agent proposes tunings; humans (you + AURA) still set direction. That's a deliberate bound, not a technical limit.
- **Cluster-wide orchestration** — one agent talking to one Medusa. Multi-node orchestration is a later phase, after the shard protocol is actually running distributed.
- **Changing `continuous_evolution_ca.py`** — Layer 1 is untouched. The parameter proxy is a new thin wrapper; the engine sees a normal config reload.
- **Replacing the existing REST API** — Phase 16 endpoints stay exactly as they are. We extend, we don't rewrite.

## Implementation Roadmap (follow-up PRs, rough sequence)

1. **`scripts/params_schema.py`** — declare the tunable parameter registry with bounds, categories (auto/human), and `locked` flag. First PR; purely additive.
2. **Extend `medusa_api.py`** with `GET /api/params`, `GET /api/params/schema`, and the three `POST /api/tuning/*` endpoints. Second PR. No agent yet; drivable by curl.
3. **Add ZMQ event stream** — new `scripts/event_bus.py` PUB socket on :8081, wired into the engine's existing 5-min telemetry hook. Third PR.
4. **Agent backend ABC + `MockBackend`** — no external API calls; unit-testable. Fourth PR.
5. **`AnthropicBackend`** — first real backend; tested against the `MockBackend` test fixture. Fifth PR.
6. **Orchestrator loop** (`scripts/orchestrator.py`) — ties it together, driven by `orchestrator_config.py`. Sixth PR.
7. **`NemoCloudBackend`** — dropped in later when Kevin is ready to stand up the NVIDIA Cloud account. Swap is a one-line config change. Seventh PR.

Each PR is small (≈ 200–500 lines) and mergeable independently. If you want to pause at any point, the earlier PRs still add value: PR 1+2 give you a curl-drivable tuning API; PR 3 gives you a live event feed regardless of agent.

## The Honest Caveats

- **Tuning safety is hard.** Bounded ranges + rate limits + human approval for critical params are a floor, not a ceiling. Real-world use will surface edge cases the schema missed; expect to tighten the schema as we learn.
- **Dry-run fidelity.** Simulating N steps on a shadow lattice tells you the *local* effect of a param change; it doesn't tell you emergent long-horizon effects. Agents (and humans) should prefer small adjustments over large ones.
- **Cost.** Every agent step is an LLM call. Anthropic and NVIDIA both charge. Default the orchestrator loop to a slow cadence (once per N generations or once per significant event, not once per step) and keep `tuning_ledger.jsonl` as the audit trail for whether the spend was justified.
- **The model-agnostic guarantee only holds at this layer.** Different backends have different judgment, different failure modes, different latency profiles. Swapping models isn't free — it's just not *architecturally* coupled.

---

*Proposer, not executor. Bounded writes, full audit. One swap line between Opus and Nemo. Less eschatology, more carpentry.*

— Agent 84 🎩
