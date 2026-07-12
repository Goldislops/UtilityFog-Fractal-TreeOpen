# Legacy Tuning Orchestrator — Quarantine

> **What this is.** `scripts/orchestrator.py` (Phase 18 PR 6), historically
> described as *"the Swarm Hunter's brain,"* is an LLM-driven tuning
> orchestrator that could observe Medusa and POST to the tuning API. This
> document records the **proven boundaries** placed around it by the R/S/T
> package stack so its default and supported LLM-facing operation cannot mutate
> Medusa.
>
> **What this is NOT.** This is not the offline candidate-structure detector
> proposed in [`docs/SWARM_HUNTER_V1_PREFLIGHT.md`](SWARM_HUNTER_V1_PREFLIGHT.md)
> (PR #322). The two share vocabulary only. This document also does **not**
> claim the tuning API is authenticated or generally secure, that the
> Glass-Wall is complete, or anything about live engine behavior.

## The three enforced boundaries

**R — server-side auto-commit refusal** (`scripts/tuning_api.py`). The commit
endpoint refuses the orchestrator's autonomous approver identity
(`approver="policy:auto"` → `403 auto_commit_disabled`), checked before the
human-approval branch, for every parameter category. There is no env flag,
query param, header, or alternate route that re-enables it; re-enablement
requires a reviewed code change. Human commits (`approver="human:<name>"`),
reads, dry-run/propose, LOCKED-at-propose rejection, and the per-parameter rate
limit are unchanged.

**S — observe-by-default capability model** (`scripts/orchestrator.py`,
`scripts/orchestrator_config.py`). The LLM-facing surface is capability-gated:

| Mode | Observation tools | Proposal tool | Commit tool |
|---|---|---|---|
| `observe` (default) | ✅ | ❌ | ❌ |
| `propose` | ✅ | ✅ (forced `dry-run`; `commit-pending` refused) | ❌ |

`commit_tuning` is **never** registered as an LLM-facing router handler in any
mode. Mode resolution (`resolve_mode` / `MEDUSA_ORCHESTRATOR_MODE`) fails closed:
absent, malformed, or unknown values all resolve to `observe`; only the exact
tokens `observe`/`propose` are honored, and only `propose` exposes any
write-adjacent tool. The low-level `OrchestratorClient.commit_tuning` /
`rollback_tuning` primitives are retained for direct **non-LLM** callers and are
proven unable to enter the tool registry.

**T — hard runtime limits, honest error semantics, bounded audit receipts**
(`scripts/orchestrator.py`). Two validated budgets bound each iteration: a
per-turn `max_tool_depth` and a total `max_total_tool_calls` (both positive
integers within `MAX_LIMIT_CEILING`; malformed values are rejected at
construction). When a turn's tool calls would exceed the total budget, only the
permitted prefix executes; every remaining call gets an explicit
`budget_rejection` error result so the conversation history stays structurally
valid, and the iteration stops (`tool_budget_exhausted`) — the cap is never
exceeded. At most one proposal attempt per iteration is enforced in code. Tool
outcomes are categorized (`ok`, `unknown_tool`, `handler_exception`,
`transport_failure`, `http_rejection`, `budget_rejection`, `proposal_limit`,
`local_rejection`); HTTP status ≥ 400 is a genuine tool error and is never
counted as a created proposal or applied commit.

Error-shape guarantees (Jack amendment):

- **Non-dict handler returns** — the handler call, its return-shape check, and
  the `_status`/`_local_rejection` inspection all run inside one defensive
  `try`, so a handler that returns `None`, a list, a scalar, or any non-dict
  becomes a bounded `handler_exception` result and can never crash the loop.
- **`local_rejection`** — a request the router refuses *before* any HTTP call
  (blank justification, forbidden `commit-pending`) is flagged `is_error=True`
  with category `local_rejection`, counted as an error (not `ok`), and — since
  no request is sent — never mints a proposal id. Distinct from
  `http_rejection`, where the server said no.
- **Error visibility across transports** — an `is_error` result is surfaced by
  native backends via the `is_error` flag and by the OpenAI-compatible backend
  via a leading `[ERROR]` marker, so a model recognises the failure either way.

## LeanCTX audit receipt

`IterationResult.audit_receipt()` returns a bounded, deterministic,
payload-free handoff (`build_audit_receipt`): stop reason, turn/tool-call
counts, per-category outcome counts, successful proposal ids, and token usage —
**never** tool payloads, prompts, credentials, headers, or raw backend
responses. It serializes deterministically (sorted keys) and is guaranteed
≤ 64 KiB (`MAX_RECEIPT_BYTES`), with deterministic truncation as a last-resort
safety net.

## Supported modes and invocation

`observe` is the default for any construction path (bare `Orchestrator`,
`create_orchestrator`, or `MEDUSA_ORCHESTRATOR_MODE` unset/garbage). A human who
wants dry-run proposal validation sets `MEDUSA_ORCHESTRATOR_MODE=propose`. No
supported configuration exposes an LLM-facing commit.

## Non-claims

- Not general API authentication or security — only the `policy:auto` path is
  closed at the server.
- Not a completed Glass-Wall — this quarantines one write-capable module.
- Not a statement about live engine behavior, production deployment, or
  statistical validity.
- Rollback is **not** exposed to the LLM in any mode.

## Rollback (per package)

- **T:** revert `scripts/orchestrator.py` budget/receipt additions and remove
  this document; capability model (S) and server refusal (R) remain.
- **S:** revert the capability-model changes to
  `scripts/orchestrator.py` / `orchestrator_config.py`; the server refusal (R)
  remains as the backstop.
- **R:** revert the `_commit_locked` `auto_commit_disabled` guard in
  `scripts/tuning_api.py`. (Doing so re-opens the autonomous commit path — a
  reviewed decision, by design.)

## Relationship to the offline detector (PR #322)

The proposed offline Swarm Hunter detector reads immutable evidence and surfaces
candidates for human review; it has no write path. This quarantine is the
disposition of the pre-existing *tuning* orchestrator that #322's evidence pass
uncovered. The offline detector must never import, or be imported by, this
orchestrator — a one-directional boundary asserted by a static-import test in
`tests/test_orchestrator.py`.
