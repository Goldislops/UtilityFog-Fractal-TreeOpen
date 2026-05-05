# LOCAL_OLLAMA_SMOKE_TEST.md — Design / Planning Doc

> **Status**: design only. **No execution authorised by this document.**
>
> AURA + Jack scoped this on 2026-05-01 as the cautious follow-up to Phase 18.
> Per the handoff doc, this is "optional future" work — a small, deliberate
> proof that the `OpenAICompatBackend` + orchestrator stack works end-to-end
> against a real local model server, not just against scripted mock SDKs.
>
> Operator (Kevin) explicitly approves each phase below before it runs. Nothing
> happens automatically.

## What this is

A **single-iteration smoke test** of the Phase 18 stack against a local
Ollama server hosting one modest tool-capable model. The test runs one
`Orchestrator.run_one_iteration()` call against the live (or stubbed)
Medusa REST API and records:

- Latency end-to-end and per-LLM-call.
- VRAM consumed by the local model server.
- Model identifier and Ollama endpoint URL.
- Tool-call validity (did the model emit a `propose_tuning` call that
  the tuning API would accept, even if dry-run rejected it?).
- Token usage per call (`IterationResult.usage_total`).
- The full ledger entry (or absence thereof) on the Medusa side.

## What this is NOT

- **NOT a claim that local models make decisions equivalent to Anthropic
  Opus 4.7.** Different models, different judgment. PR #134 already proved
  protocol parity; this proves *transport* parity (Phase 18 stack against
  a real local LLM, not a scripted mock).
- **NOT a multi-agent / swarm test.** One model, one orchestrator iteration.
- **NOT an engine-restart bundle.** Medusa stays running on Area 51,
  untouched. We never write a tuning_pending.json the engine would consume
  (we use dry-run mode for the proposal).
- **NOT an abliterated/uncensored model trial.** Per Jack: the first local
  controller is the boring, reliable one. If the wiring works with Granite
  it'll work with anything else later.

## Hardware topology (proposed)

| Role | Machine | GPU | Notes |
|------|---------|-----|-------|
| **Medusa engine** | Area 51 (workstation, 192.168.86.29) | RTX 5090 | UNTOUCHED. Continues baking. |
| **Local LLM host** | Aurora — **Alienware Aurora Ultra Core 9 285 + RTX 4090** | RTX 4090 | Hosts Ollama + Granite. F@H paused during the test. |
| **Orchestrator** | **Area 51** (default) | none | Pure Python; the orchestrator already imports `scripts.medusa_api` so Area 51 is the natural host. **Do not clone the repo to Aurora for the first smoke test** — keeping the orchestrator on Area 51 is cleaner separation. |

**Communication path**: orchestrator (Area 51) → HTTP → Ollama (Aurora,
`http://<AURORA_IP>:11434/v1`) → response → orchestrator →
HTTP → Medusa REST API (Area 51 :8080) → ledger.

The two HTTP hops are intentional and prove out the LAN-distributed
shape we'd eventually use for cluster work.

> **Open: Aurora's IP is to-be-confirmed.** The Vanguard cluster table
> previously listed `DellUltracore9 (192.168.86.3)` as having an RTX 4090,
> but that's an inference, not a verified match for "Aurora". Per Jack's
> review: don't assume. **First operator action on Aurora itself**:
> `ipconfig` (Windows) or `ip addr` (Linux), look for the IPv4 address on
> Wi-Fi or Ethernet. Update this doc with the confirmed value before any
> orchestrator command tries to reach Aurora.

## Software prerequisites

| Component | Where | How |
|-----------|-------|-----|
| Ollama runtime | Aurora | `winget install Ollama.Ollama` (Windows) or Linux installer; provides `ollama` CLI + a server on `:11434` |
| Granite 4 model | Aurora (Ollama-managed) | `ollama pull <granite-tag>`. **Verified Ollama tags** (per Jack's review of Ollama's Granite page): `granite4:3b`, `granite4:micro`, `granite4:tiny-h`, `granite4:small-h`. **For the first smoke test, prefer `granite4:3b`** — smallest, fastest, sufficient for proving plumbing. Fall back to `granite4:tiny-h` if 3B is too weak at tool use. **Do NOT start with `granite4:small-h` (~19 GB)** — overkill for first plumbing test. |
| `OpenAICompatBackend` | already in repo | imported from `scripts.agent_backends`; pointed at Aurora's Ollama endpoint |
| `medusa_api.py` | Area 51 | already running per existing `:8080` deployment |

**No code changes needed in this repo.** The OpenAICompatBackend has the
`base_url` parameter exactly for this case (PR #131); the dummy api_key
fallback (PR #133) means Ollama's passwordless server Just Works without
the SDK crashing at construction.

## Pre-flight checklist (operator runs through these BEFORE the test)

1. **Capture Medusa baseline**: note the latest snapshot generation
   (`ls data/v070_gen*.npz | tail -1`) and the gap to the last snapshot.
2. **Pause F@H on Aurora** for the duration of the test. BOINC can stay
   running but throttle if VRAM pressure is a concern.
3. **Pause F@H on Area 51 too** if it's running there — orchestrator does
   minimal CPU work but we want clean latency numbers.
4. **Verify Aurora reachable from Area 51**: `ping 192.168.86.<aurora>`.
5. **Install Ollama on Aurora** (one-time): operator action.
6. **Pull the Granite model on Aurora** (one-time): `ollama pull <tag>`.
   Note disk usage and download time.
7. **Verify the Ollama server responds**: from Aurora,
   `curl http://localhost:11434/api/tags` should list the pulled model.
8. **Verify Aurora reachable from Area 51 on port 11434**:
   `curl http://192.168.86.<aurora>:11434/api/tags`. (Firewall? May need
   to allow inbound 11434 on Aurora.)
9. **Verify Medusa REST API up**: `curl http://localhost:8080/api/health`
   from Area 51.
10. **Snapshot the tuning ledger BEFORE the test**:
    `cp data/tuning_ledger.jsonl data/tuning_ledger.before.bak.jsonl`
    so we can diff the delta.

## The test sequence

After all pre-flight checks pass, the operator runs (on Area 51):

```bash
export MEDUSA_AGENT_BACKEND=openai-compat
export MEDUSA_OPENAI_BASE_URL=http://<AURORA_IP>:11434/v1
export MEDUSA_OPENAI_MODEL=granite4:3b   # primary first-test pick (per Jack)
# MEDUSA_OPENAI_API_KEY intentionally unset; backend supplies "not-needed"

python -c "
from scripts.orchestrator_config import create_orchestrator
result = create_orchestrator().run_one_iteration(
    'Observe Medusa current state. If the matrix looks healthy, say so '
    'and stop. Use ONLY dry-run mode if you propose anything. Do NOT '
    'commit any tuning. This is a smoke test.'
)
print(result)
"
```

**Critical scope guardrails embedded above**:
- The trigger message explicitly tells the model **dry-run only**, **no commit**.
- Even if the model misbehaves and tries `commit_tuning`, the orchestrator
  is configured with `commit_approver="policy:auto"`. AUTO-category params
  *would* commit. So we should also temporarily prevent that.

> **Mitigation suggestion**: for the smoke test, run with a custom
> `commit_approver` value the API doesn't accept (e.g. `"smoke-test:dry"`).
> The API returns 403 on commit attempts. Belt + suspenders.

## What to log (during + after the test)

| Metric | How to capture |
|--------|----------------|
| End-to-end latency | wallclock around `run_one_iteration()` |
| Per-LLM-call latency | extend the orchestrator with a tiny timer wrapper, OR derive from Ollama's response timing in the SDK |
| VRAM on Aurora during call | `nvidia-smi` snapshot before/during/after |
| Model + endpoint | from environment (already known) |
| Tool-call validity | inspect `IterationResult.proposals_created`, `IterationResult.commits_applied` |
| Tokens used | `IterationResult.usage_total` (Ollama exposes prompt_tokens + completion_tokens via the OpenAI-compat surface) |
| Tool-call diversity | how many distinct tools did the model call? |
| Final assistant text | `IterationResult.final_text` |
| Ledger delta | `diff data/tuning_ledger.before.bak.jsonl data/tuning_ledger.jsonl` |
| Stop reason | `IterationResult.stopped_because` |

A small Python harness that captures all of these into a single JSON
report makes the post-mortem easy. Suggested output filename:
`data/smoke_test_<timestamp>.json` (private; not committed).

## Pass / fail criteria

**PASS** if:
- The orchestrator completes one iteration with `stopped_because == "end_turn"` (model decided it had said enough), not `"max_depth"` (runaway loop).
- At least one tool call was made AND was a valid call against a known tool name (proves tool-use plumbing works).
- If a `propose_tuning` call was made: it included a non-empty `justification` and parameters within schema bounds.
- No commits were applied (the test is dry-run-only).
- VRAM usage on Aurora stayed well below the 4090's 24 GB ceiling.
- Total wall time under 60 seconds (sanity check; longer suggests the model is struggling).

**FAIL** (and what it suggests) if:
- `stopped_because == "max_depth"` → model is looping; bad model fit, or system prompt wasn't clear enough about "stop when done".
- Zero tool calls → model can't do tool-use with this provider's chat-completions surface; pick a different model or check Ollama's tool-call support.
- Validation errors on every proposal → model isn't reading the schema correctly; try `granite4:tiny-h` (next size up) before considering `granite4:small-h`.
- Commit applied → safety rail breach. Roll back ledger from backup, investigate.
- Connection refused on Aurora's :11434 → firewall / Ollama not bound externally. Fix and retry.

## Abort criteria (kill the test mid-run)

- VRAM on Aurora hits 90% — kill Ollama, investigate model size.
- Medusa snapshot interval lengthens (engine is fighting for resources somehow) — pause everything.
- Orchestrator hangs > 60s on a single LLM call — Ctrl-C the Python process; check Ollama's logs.

## Rollback

If anything looks weird after the test:
1. `cp data/tuning_ledger.before.bak.jsonl data/tuning_ledger.jsonl` (restore ledger).
2. Restart `medusa_api.py` so the in-memory `TuningState` re-replays from the restored ledger.
3. Stop Ollama on Aurora; resume F@H.
4. Document what happened in this file as a "lessons learned" appendix.

Ledger restore is safe because the API hasn't been used by Kevin or AURA
to issue real production tunings yet — the ledger only contains test
entries.

## What this proves (if it passes)

- A locally hosted model with no per-token cost can drive the Phase 18
  orchestrator end-to-end against the real Medusa stack.
- The provider-neutral story holds at the transport layer, not just at
  the protocol layer (which PR #134 already proved).
- Aurora has the headroom to host a small tool-capable model alongside
  whatever else it normally runs.

## What this enables next (deliberately not in scope here)

- Trying a different local model (Qwen3-Coder-Next, Llama 3.x, etc.)
  without changing any code — just a different `MEDUSA_OPENAI_MODEL`.
- Eventually trying an abliterated variant once the safety rails have
  been exercised under a boring model first.
- Cluster-distributed orchestration (Aurora + other Vanguard nodes
  running observers / proposers / critics in parallel) — but only after
  the single-node case is solid.

## Open questions — RESOLVED via Jack's review (2026-05-05)

1. ~~Is "Aurora" the same physical box as `DellUltracore9 (192.168.86.3)`?~~
   **Resolution**: Aurora = **Alienware Aurora Ultra Core 9 285 + RTX 4090**.
   IP **to be confirmed** via `ipconfig` on Aurora itself; do not assume
   `192.168.86.3` is the right machine.
2. ~~Orchestrator on Area 51 or Aurora?~~
   **Resolution**: **Area 51**. Don't clone the repo to Aurora for first
   smoke test. Topology is `Area 51 orchestrator → Aurora Ollama → Area 51 Medusa API`.
3. ~~Granite 4.0 MoE Ollama tag verification?~~
   **Resolution**: real Ollama tags are `granite4:3b`, `granite4:micro`,
   `granite4:tiny-h`, `granite4:small-h` (NOT plain `tiny`/`small`).
   Use `granite4:3b` first; fall back to `granite4:tiny-h` if needed.
   `granite4:small-h` (~19 GB) is overkill for first test.
4. ~~Harness or ad-hoc?~~
   **Resolution**: **ad-hoc first**. No committed harness. Build one
   later only if the smoke test proves useful enough to repeat.

## Operator Approval Workflow (per Jack)

For each command in the test sequence below — and especially anything
that installs software, downloads a model, opens a port, or modifies a
service — the working pattern is:

1. **84 writes the exact command.**
2. **84 explains in one sentence what it does.**
3. **Kevin reads, then says yes or no.**
4. **84 either runs it (if it's on this Area 51 session) or hands it to
   Kevin to paste (if it's on Aurora).**
5. **Result comes back; the next command goes through the same loop.**

Today, the only commands worth approving are read-only / inspection:
- identify Aurora's IP (`ipconfig` or `ip addr` — read-only).
- check whether SSH is already running on Aurora (read-only).
- check whether Ollama is already installed on Aurora (read-only).
- *optionally*: install Ollama on Aurora (only if Kevin feels clear and steady).

**Explicitly NOT approved without further conversation**:
- changing firewall rules.
- downloading large models (>1 GB).
- starting always-on services.
- touching Medusa, BOINC, or F@H settings.
- one-shot multi-step changes across multiple machines.

One machine. One model. One test. Human says yes each step.

## Posture

This is a **plan**, not an instruction. Nothing in this document executes.
When (if) Kevin chooses to run the smoke test, each numbered step is an
explicit operator action with a clear pre-condition and rollback path.
Medusa stays untouched throughout. The system has earned a pause; this
plan is what carefulness looks like when we eventually move forward.

— drafted 2026-05-01 by Agent 84, per AURA + Jack joint scope
— revised 2026-05-05 with Jack's review corrections (verified Ollama tags,
  Aurora-IP-to-be-confirmed, explicit operator approval workflow)
