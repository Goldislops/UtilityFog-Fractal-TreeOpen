"""Phase 18 PR 6 — Orchestrator: the Swarm Hunter's brain.

Ties the three halves of the Phase 18 bus into one propose→commit loop:

  1. Observation (Phase 16 REST GET endpoints + Phase 18 PR 2 /api/params):
     read Medusa's current state via HTTP.
  2. Decision (Phase 18 PR 4 AgentBackend, e.g. PR 5 AnthropicBackend):
     hand the LLM the current state + a bounded tool set, let it propose.
  3. Action (Phase 18 PR 2 tuning API + PR 3 event bus):
     execute approved tool calls by POSTing to /api/tuning/*.

This module is **pure library code** — no threading, no long-running loop.
One call to `Orchestrator.run_one_iteration()` does the full observe-decide-
act cycle once and returns an `IterationResult`. A separate runner script
(future PR or simple cron) is responsible for cadence. That split keeps the
unit tests deterministic: we run one iteration with scripted `MockBackend`
responses and assert on the effects.

Safety philosophy (defense in depth, layered on top of the API's own rails):
  - `Orchestrator` only ever commits with `approver="policy:auto"`. If the
    proposal touches a HUMAN_APPROVAL parameter, the API returns 403, the
    tool_result carries that error back to the LLM on the next turn, and
    the LLM can choose to escalate or back off — the orchestrator never
    tries to bypass the gate.
  - Per-iteration `max_tool_depth` cap prevents a confused LLM from looping
    forever.
  - Every LLM call's usage is returned in `IterationResult.usage_total` so
    operators can audit token spend.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from scripts.agent_backends import (
    AgentBackend,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
)


# -- HTTP wrapper ------------------------------------------------------------


HttpDo = Callable[..., tuple[int, dict]]
"""Signature: http_do(method, url, *, json=None, timeout=5.0) -> (status, body)."""


def _default_http_do(
    method: str,
    url: str,
    *,
    json: Optional[dict] = None,
    timeout: float = 5.0,
) -> tuple[int, dict]:
    """stdlib-only JSON HTTP. Replaced via dependency injection in tests."""
    data = __import__("json").dumps(json).encode() if json is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            body = __import__("json").loads(raw) if raw else {}
            return resp.status, body
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            body = __import__("json").loads(raw) if raw else {}
        except ValueError:
            body = {"error": "http_error", "message": raw}
        return e.code, body


class OrchestratorClient:
    """Thin wrapper over Medusa's REST API. All endpoints live in one place."""

    def __init__(self, base_url: str, *, http_do: Optional[HttpDo] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http_do = http_do or _default_http_do

    # Read endpoints ---

    def get_census(self) -> tuple[int, dict]:
        return self._http_do("GET", f"{self.base_url}/api/census")

    def get_equanimity(self) -> tuple[int, dict]:
        return self._http_do("GET", f"{self.base_url}/api/equanimity")

    def get_acoustic(self) -> tuple[int, dict]:
        return self._http_do("GET", f"{self.base_url}/api/acoustic")

    def get_params(self) -> tuple[int, dict]:
        return self._http_do("GET", f"{self.base_url}/api/params")

    def get_params_schema(self) -> tuple[int, dict]:
        return self._http_do("GET", f"{self.base_url}/api/params/schema")

    def get_status(self) -> tuple[int, dict]:
        return self._http_do("GET", f"{self.base_url}/api/status")

    # Write endpoints ---

    def propose_tuning(
        self,
        params: dict,
        source: str,
        justification: str,
        mode: str = "dry-run",
    ) -> tuple[int, dict]:
        return self._http_do(
            "POST",
            f"{self.base_url}/api/tuning/propose",
            json={
                "params": params,
                "source": source,
                "justification": justification,
                "mode": mode,
            },
        )

    def commit_tuning(self, proposal_id: str, approver: str) -> tuple[int, dict]:
        return self._http_do(
            "POST",
            f"{self.base_url}/api/tuning/commit",
            json={"proposal_id": proposal_id, "approver": approver},
        )

    def rollback_tuning(self, to_proposal_id: str) -> tuple[int, dict]:
        return self._http_do(
            "POST",
            f"{self.base_url}/api/tuning/rollback",
            json={"to_proposal_id": to_proposal_id},
        )


# -- tool definitions --------------------------------------------------------


def observation_tools() -> list[ToolSpec]:
    """Read-only tools exposed to the LLM."""
    empty_schema = {"type": "object", "properties": {}, "required": []}
    return [
        ToolSpec(
            name="get_medusa_census",
            description=(
                "Get the current cell-state census: counts of VOID, STRUCTURAL, "
                "COMPUTE, ENERGY, SENSOR along with entropy, fitness, generation."
            ),
            input_schema=empty_schema,
        ),
        ToolSpec(
            name="get_medusa_equanimity",
            description=(
                "Get Sage/Elder/Ancient/Legend counts, max/median/mean age, "
                "percentile thresholds, and coordinates of the top 5 eldest Sages."
            ),
            input_schema=empty_schema,
        ),
        ToolSpec(
            name="get_acoustic_map",
            description=(
                "Get the 16x16x16 sector friction heatmap showing which regions "
                "of the 256^3 lattice are stressed (top 25%) vs silent (bottom 25%)."
            ),
            input_schema=empty_schema,
        ),
        ToolSpec(
            name="get_params",
            description=(
                "Get the current effective values of all tunable parameters, "
                "plus the current generation number."
            ),
            input_schema=empty_schema,
        ),
        ToolSpec(
            name="get_params_schema",
            description=(
                "Get the full tunable-parameter schema: type, bounds, category "
                "(auto/human_approval/locked), group, and description for each. "
                "LOCKED params cannot be tuned; HUMAN_APPROVAL params require "
                "approver='human:<name>' and will NOT be auto-committed."
            ),
            input_schema=empty_schema,
        ),
    ]


def tuning_tools() -> list[ToolSpec]:
    """Write tools exposed to the LLM. Every proposal requires a justification."""
    return [
        ToolSpec(
            name="propose_tuning",
            description=(
                "Propose a parameter tuning. Validates against the schema. "
                "Pass mode='dry-run' to test without committing; mode='commit-pending' "
                "to flag for a follow-up commit. REQUIRES a justification explaining "
                "why this change is being proposed — proposals without justification "
                "will be rejected."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "params": {
                        "type": "object",
                        "description": (
                            "Map of parameter name to new value. Only parameters "
                            "listed in the schema can be tuned. LOCKED params are "
                            "rejected unconditionally."
                        ),
                        "additionalProperties": True,
                    },
                    "justification": {
                        "type": "string",
                        "description": (
                            "Human-readable rationale for this tuning. Required."
                        ),
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["dry-run", "commit-pending"],
                        "description": "dry-run for validation only; commit-pending to mark as ready for commit.",
                    },
                },
                "required": ["params", "justification"],
            },
        ),
        ToolSpec(
            name="commit_tuning",
            description=(
                "Commit a previously-proposed tuning. This orchestrator commits "
                "with approver='policy:auto', which only works for AUTO-category "
                "proposals. HUMAN_APPROVAL proposals will return 403; don't attempt "
                "to commit them — explain what you'd want a human to approve instead."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "proposal_id": {
                        "type": "string",
                        "description": "The prop-XXXXXXXX id returned by a prior propose_tuning call.",
                    },
                },
                "required": ["proposal_id"],
            },
        ),
    ]


# -- tool router -------------------------------------------------------------


ToolHandler = Callable[[dict], dict]


class ToolRouter:
    """Maps tool-call names to handler functions. One place that knows the
    connection between the LLM's tool vocabulary and the HTTP client."""

    def __init__(
        self,
        client: OrchestratorClient,
        *,
        orchestrator_source: str = "agent:orchestrator",
        commit_approver: str = "policy:auto",
    ) -> None:
        self.client = client
        self.source = orchestrator_source
        self.approver = commit_approver
        self._handlers: dict[str, ToolHandler] = {
            "get_medusa_census": self._h_census,
            "get_medusa_equanimity": self._h_equanimity,
            "get_acoustic_map": self._h_acoustic,
            "get_params": self._h_params,
            "get_params_schema": self._h_schema,
            "propose_tuning": self._h_propose,
            "commit_tuning": self._h_commit,
        }

    def execute(self, name: str, arguments: dict) -> tuple[dict, bool]:
        """Run a tool call. Returns `(result_payload, is_error)`."""
        handler = self._handlers.get(name)
        if handler is None:
            return (
                {"error": "unknown_tool", "message": f"tool {name} not registered"},
                True,
            )
        try:
            return handler(arguments), False
        except Exception as e:  # defensive: any handler bug → LLM-visible error
            return (
                {"error": "tool_handler_exception",
                 "tool": name,
                 "message": f"{type(e).__name__}: {e}"},
                True,
            )

    # handlers ---

    def _unwrap(self, resp: tuple[int, dict]) -> dict:
        status, body = resp
        if status >= 400:
            return {"_status": status, **body}
        return body

    def _h_census(self, _args: dict) -> dict:
        return self._unwrap(self.client.get_census())

    def _h_equanimity(self, _args: dict) -> dict:
        return self._unwrap(self.client.get_equanimity())

    def _h_acoustic(self, _args: dict) -> dict:
        return self._unwrap(self.client.get_acoustic())

    def _h_params(self, _args: dict) -> dict:
        return self._unwrap(self.client.get_params())

    def _h_schema(self, _args: dict) -> dict:
        return self._unwrap(self.client.get_params_schema())

    def _h_propose(self, args: dict) -> dict:
        params = args.get("params") or {}
        justification = args.get("justification") or ""
        mode = args.get("mode", "dry-run")
        if not justification.strip():
            return {"error": "bad_request",
                    "message": "justification is required and must be non-empty"}
        return self._unwrap(self.client.propose_tuning(
            params=params,
            source=self.source,
            justification=justification,
            mode=mode,
        ))

    def _h_commit(self, args: dict) -> dict:
        proposal_id = args.get("proposal_id")
        if not proposal_id:
            return {"error": "bad_request", "message": "proposal_id is required"}
        return self._unwrap(self.client.commit_tuning(
            proposal_id=proposal_id,
            approver=self.approver,  # "policy:auto" — never a human prefix from the orchestrator
        ))


# -- orchestrator ------------------------------------------------------------


@dataclass
class IterationResult:
    """Outcome of one observe-decide-act cycle."""

    stopped_because: str
    """One of: "end_turn" (LLM finished), "max_depth" (tool_call cap reached),
    "transport_error" (LLM call failed)."""

    turns: int
    """Number of LLM `complete()` calls made this iteration."""

    tool_calls_executed: int
    """Total tool calls executed across all turns this iteration."""

    proposals_created: list[str] = field(default_factory=list)
    """Proposal IDs returned by successful propose_tuning calls."""

    commits_applied: list[str] = field(default_factory=list)
    """Proposal IDs successfully committed."""

    final_text: Optional[str] = None
    """Last assistant text block, if any."""

    usage_total: dict[str, int] = field(default_factory=dict)
    """Sum of input/output tokens across all turns this iteration."""


class Orchestrator:
    """One observe-decide-act iteration per `run_one_iteration()` call.

    The external runner (cron, scheduler, event-driven tick) is responsible
    for deciding how often to call us. That separation keeps the unit tests
    deterministic and lets operators tune cadence without touching the
    iteration logic.
    """

    def __init__(
        self,
        backend: AgentBackend,
        client: OrchestratorClient,
        *,
        system_prompt: str,
        tools: Optional[list[ToolSpec]] = None,
        router: Optional[ToolRouter] = None,
        max_tool_depth: int = 8,
        max_tokens_per_call: int = 2048,
        temperature: float = 0.0,
    ) -> None:
        self.backend = backend
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools or (observation_tools() + tuning_tools())
        self.router = router or ToolRouter(client)
        self.max_tool_depth = max_tool_depth
        self.max_tokens_per_call = max_tokens_per_call
        self.temperature = temperature

    def run_one_iteration(self, trigger_message: str) -> IterationResult:
        """Run one observe-decide-act cycle triggered by `trigger_message`."""
        messages: list[Message] = [Message(role="user", content=trigger_message)]
        turns = 0
        tool_calls_executed = 0
        proposals_created: list[str] = []
        commits_applied: list[str] = []
        usage_total: dict[str, int] = {}
        final_text: Optional[str] = None

        for depth in range(self.max_tool_depth):
            response = self.backend.complete(
                messages=messages,
                tools=self.tools,
                system=self.system_prompt,
                max_tokens=self.max_tokens_per_call,
                temperature=self.temperature,
            )
            turns += 1
            _accumulate_usage(usage_total, response.usage)
            final_text = response.text if response.text is not None else final_text

            # Append assistant content to history for the next turn.
            messages.append(Message(role="assistant", content=list(response.raw_content)))

            if not response.tool_calls:
                return IterationResult(
                    stopped_because="end_turn",
                    turns=turns,
                    tool_calls_executed=tool_calls_executed,
                    proposals_created=proposals_created,
                    commits_applied=commits_applied,
                    final_text=final_text,
                    usage_total=usage_total,
                )

            # Execute every tool call in this turn; gather result blocks.
            result_blocks: list = []
            for call in response.tool_calls:
                payload, is_error = self.router.execute(call.name, call.arguments)
                tool_calls_executed += 1
                if call.name == "propose_tuning" and not is_error:
                    pid = payload.get("proposal_id")
                    if pid:
                        proposals_created.append(pid)
                elif call.name == "commit_tuning" and not is_error:
                    pid = payload.get("proposal_id")
                    if pid and payload.get("status") == "committed":
                        commits_applied.append(pid)
                result_blocks.append(
                    ToolResultBlock(
                        tool_use_id=call.id,
                        content=json.dumps(payload, sort_keys=True, default=str),
                        is_error=is_error,
                    )
                )
            messages.append(Message(role="user", content=result_blocks))

        # Hit depth cap without the LLM naturally ending.
        return IterationResult(
            stopped_because="max_depth",
            turns=turns,
            tool_calls_executed=tool_calls_executed,
            proposals_created=proposals_created,
            commits_applied=commits_applied,
            final_text=final_text,
            usage_total=usage_total,
        )


def _accumulate_usage(total: dict[str, int], step: dict[str, Any]) -> None:
    for key in ("input_tokens", "output_tokens"):
        v = step.get(key)
        if isinstance(v, int):
            total[key] = total.get(key, 0) + v


__all__ = [
    "OrchestratorClient",
    "HttpDo",
    "ToolRouter",
    "Orchestrator",
    "IterationResult",
    "observation_tools",
    "tuning_tools",
]
