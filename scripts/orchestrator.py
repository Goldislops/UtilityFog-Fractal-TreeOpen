"""Phase 18 PR 6 — Legacy tuning orchestrator (quarantined).

Historically described as "the Swarm Hunter's brain," this module is the
Phase 18 tuning orchestrator. It is distinct from the offline
candidate-structure detector proposed in `docs/SWARM_HUNTER_V1_PREFLIGHT.md`
(PR #322) — do not conflate the two.

It ties the Phase 18 bus into one observe→decide loop:

  1. Observation (Phase 16 REST GET endpoints + Phase 18 PR 2 /api/params):
     read Medusa's current state via HTTP.
  2. Decision (Phase 18 PR 4 AgentBackend): hand the LLM the current state +
     a bounded tool set, let it observe and (in `propose` mode only) validate a
     dry-run proposal.

This module is **pure library code** — no threading, no long-running loop.
One call to `Orchestrator.run_one_iteration()` does one cycle and returns an
`IterationResult`.

Capability quarantine (Package S):
  - The LLM-facing surface is **observe by default**. There is **no supported
    LLM-facing commit tool**: `commit_tuning` is never registered in the tool
    router, so no model turn can commit a parameter.
  - Capability modes (`OrchestratorMode`): `observe` (observation tools only)
    and `propose` (observation + a proposal tool that is **forced to
    `mode="dry-run"`** at the router boundary; `commit-pending` is rejected,
    not silently downgraded).
  - The low-level `OrchestratorClient.commit_tuning` / `rollback_tuning`
    methods are retained as **non-LLM-facing** primitives for existing direct
    callers (e.g. provider-parity tests); they cannot enter the tool registry.
  - Defense in depth: even if a proposal were somehow committed, the server
    boundary (Package R) refuses the orchestrator's `policy:auto` approver.
  - Per-iteration `max_tool_depth` caps a confused LLM; usage is returned in
    `IterationResult.usage_total` for cost audit.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from scripts.agent_backends import (
    AgentBackend,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSpec,
)


# -- capability modes --------------------------------------------------------

OrchestratorMode = Literal["observe", "propose"]
"""LLM-facing capability level. `observe` = observation tools only (default);
`propose` = observation + a dry-run-forced proposal tool. There is deliberately
no `commit` mode: committing is not an LLM-facing capability."""

MODE_OBSERVE: OrchestratorMode = "observe"
MODE_PROPOSE: OrchestratorMode = "propose"
VALID_MODES: tuple[OrchestratorMode, ...] = (MODE_OBSERVE, MODE_PROPOSE)


def resolve_mode(raw: Optional[str]) -> OrchestratorMode:
    """Fail-closed mode resolution. Absent, malformed, or unknown values all
    resolve to the safe `observe` mode; only the exact tokens "observe" and
    "propose" (case-insensitive, trimmed) are honored. `propose` — the only
    mode that exposes any write-adjacent tool — must be opted into explicitly."""
    if not isinstance(raw, str):
        return MODE_OBSERVE
    token = raw.strip().lower()
    if token in VALID_MODES:
        return token  # type: ignore[return-value]
    return MODE_OBSERVE


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


def proposal_tools() -> list[ToolSpec]:
    """The single write-adjacent tool exposed to the LLM in `propose` mode.

    Only `propose_tuning` is offered, and the router forces it to dry-run.
    There is deliberately **no** `commit_tuning` tool — committing is not an
    LLM-facing capability."""
    return [
        ToolSpec(
            name="propose_tuning",
            description=(
                "Validate a parameter tuning as a DRY RUN. The tuning is checked "
                "against the schema but never committed — this orchestrator has no "
                "commit capability. REQUIRES a justification explaining why this "
                "change is being proposed; proposals without justification are "
                "rejected."
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
                },
                "required": ["params", "justification"],
            },
        ),
    ]


def tools_for_mode(mode: OrchestratorMode) -> list[ToolSpec]:
    """The LLM-facing tool set for a capability mode. `observe` → observation
    only; `propose` → observation + the dry-run proposal tool. No mode exposes
    a commit tool."""
    tools = observation_tools()
    if mode == MODE_PROPOSE:
        tools = tools + proposal_tools()
    return tools


# -- tool router -------------------------------------------------------------


ToolHandler = Callable[[dict], dict]


class ToolRouter:
    """Maps tool-call names to handler functions. One place that knows the
    connection between the LLM's tool vocabulary and the HTTP client.

    Capability-gated (Package S): observation handlers are always registered;
    `propose_tuning` is registered ONLY in `propose` mode (and forced to
    dry-run). `commit_tuning` is **never** registered as an LLM-facing handler,
    so no model turn can reach the commit endpoint through the router."""

    def __init__(
        self,
        client: OrchestratorClient,
        *,
        mode: OrchestratorMode = MODE_OBSERVE,
        orchestrator_source: str = "agent:orchestrator",
        commit_approver: str = "policy:auto",
    ) -> None:
        self.client = client
        self.mode = mode
        self.source = orchestrator_source
        # Retained for the non-LLM-facing client.commit_tuning primitive only;
        # the router never calls commit on the LLM's behalf.
        self.approver = commit_approver
        handlers: dict[str, ToolHandler] = {
            "get_medusa_census": self._h_census,
            "get_medusa_equanimity": self._h_equanimity,
            "get_acoustic_map": self._h_acoustic,
            "get_params": self._h_params,
            "get_params_schema": self._h_schema,
        }
        if mode == MODE_PROPOSE:
            handlers["propose_tuning"] = self._h_propose
        # commit_tuning is intentionally absent from every mode's registry.
        self._handlers: dict[str, ToolHandler] = handlers

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
        requested_mode = args.get("mode", "dry-run")
        if not justification.strip():
            return {"error": "bad_request",
                    "message": "justification is required and must be non-empty"}
        # commit-pending is rejected outright (not silently downgraded) so the
        # caller sees that only dry-run is available in this quarantined path.
        if requested_mode == "commit-pending":
            return {"error": "commit_pending_forbidden",
                    "message": "This orchestrator validates dry-run only; "
                               "commit-pending is not permitted."}
        # Any other requested mode is forced to dry-run at the boundary.
        return self._unwrap(self.client.propose_tuning(
            params=params,
            source=self.source,
            justification=justification,
            mode="dry-run",
        ))

    # NOTE: there is deliberately no _h_commit handler. Committing is not an
    # LLM-facing capability; the low-level client.commit_tuning primitive is
    # retained for direct non-LLM callers but never wired into the router.


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
        mode: OrchestratorMode = MODE_OBSERVE,
        tools: Optional[list[ToolSpec]] = None,
        router: Optional[ToolRouter] = None,
        max_tool_depth: int = 8,
        max_tokens_per_call: int = 2048,
        temperature: float = 0.0,
    ) -> None:
        self.backend = backend
        self.client = client
        self.system_prompt = system_prompt
        self.mode = mode
        # Fail-safe defaults: the tool set and router both derive from `mode`,
        # which defaults to observe. An explicit `tools`/`router` overrides,
        # but a bare Orchestrator is observation-only.
        self.tools = tools if tools is not None else tools_for_mode(mode)
        self.router = router or ToolRouter(client, mode=mode)
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
    "OrchestratorMode",
    "MODE_OBSERVE",
    "MODE_PROPOSE",
    "VALID_MODES",
    "resolve_mode",
    "observation_tools",
    "proposal_tools",
    "tools_for_mode",
]
