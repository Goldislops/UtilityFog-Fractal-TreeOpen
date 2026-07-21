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
import re
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
    # Only a normalized "propose" enables proposal mode; absent, malformed,
    # unknown, or any other value fails closed to observe. Returning the
    # module-level Literal constants keeps this typed with no cast/ignore.
    if isinstance(raw, str) and raw.strip().lower() == MODE_PROPOSE:
        return MODE_PROPOSE
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


# -- error categories & runtime limits ---------------------------------------

# Deterministic outcome categories for every tool call. "ok" is success; the
# rest are distinct failure kinds so the audit receipt can distinguish them.
OUTCOME_OK = "ok"
CATEGORY_UNKNOWN_TOOL = "unknown_tool"
CATEGORY_HANDLER_EXCEPTION = "handler_exception"
CATEGORY_TRANSPORT_FAILURE = "transport_failure"
CATEGORY_HTTP_REJECTION = "http_rejection"
CATEGORY_BUDGET_REJECTION = "budget_rejection"
CATEGORY_PROPOSAL_LIMIT = "proposal_limit"
CATEGORY_LOCAL_REJECTION = "local_rejection"
"""A request the router refused locally before any HTTP call — e.g. a blank
justification or a forbidden `commit-pending` mode. Distinct from
`http_rejection` (server said no) because no request left the process; still a
genuine tool error (is_error=True) that never creates a proposal."""

HANDLER_FAILURE_MESSAGE = "tool handler failed"
"""Fixed message for every handler failure — a raised exception or a refused
non-dict return. The offending exception/object is never stringified,
represented, formatted, measured, or sliced, so its class name and arguments
cannot enter any result."""

TRANSPORT_FAILURE_MESSAGE = "URLError"
"""Fixed message for transport failures — byte-identical to the message an
ordinary ``urllib.error.URLError`` produced here before, but emitted without
inspecting the caught exception at all."""

DEFAULT_MAX_TOTAL_TOOL_CALLS = 24
"""Total tool calls permitted across an entire iteration, independent of the
per-turn `max_tool_depth`. Bounds a model that emits many tool calls per turn."""

MAX_LIMIT_CEILING = 1000
"""Defensible upper bound for any configurable numeric limit; values above this
(or non-positive, or non-integer) are rejected rather than trusted."""

MAX_RECEIPT_BYTES = 64 * 1024
"""Hard ceiling on the serialized LeanCTX audit receipt."""


def _validate_positive_limit(name: str, value: int) -> int:
    """A configurable limit must be a positive int within the ceiling."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if value < 1 or value > MAX_LIMIT_CEILING:
        raise ValueError(f"{name} must be in [1, {MAX_LIMIT_CEILING}], got {value}")
    return value


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
    ) -> None:
        self.client = client
        self.mode = mode
        self.source = orchestrator_source
        # The router holds no commit approver: committing is not an LLM-facing
        # capability, so it never calls commit on the model's behalf. The
        # low-level `client.commit_tuning` primitive takes its approver as an
        # explicit argument and needs no router state.
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
        """Run a tool call. Returns `(result_payload, is_error)`.

        Error kinds are distinguished by a stable ``category`` field:
        unknown_tool, transport_failure, handler_exception, and http_rejection
        (HTTP status >= 400 is a genuine tool error, not a silent success).
        Failure messages are the fixed strings ``HANDLER_FAILURE_MESSAGE`` /
        ``TRANSPORT_FAILURE_MESSAGE``: the caught exception, its class, and its
        arguments are never stringified, represented, formatted, measured, or
        sliced. A handler result is accepted only when it is EXACTLY a builtin
        dict — any subclass or other object is refused without reading its
        ``__class__``, its type name, or calling any of its methods."""
        handler = self._handlers.get(name)
        if handler is None:
            return (
                {"error": "unknown_tool", "category": CATEGORY_UNKNOWN_TOOL,
                 "message": f"tool {name} not registered"},
                True,
            )
        # Handler invocation, return-shape refusal, and the _status /
        # local-rejection inspection all live inside the defensive try, so a
        # handler that raises becomes a bounded error result — it can never
        # crash the iteration loop. Refusals decide by exact builtin type
        # identity alone, before any method of the returned object could run.
        try:
            payload = handler(arguments)
            if type(payload) is not dict:
                return (
                    {"error": "tool_handler_exception",
                     "category": CATEGORY_HANDLER_EXCEPTION,
                     "tool": name, "message": HANDLER_FAILURE_MESSAGE},
                    True,
                )
            is_local_rejection = bool(payload.get("_local_rejection"))
            status = payload.get("_status")
        except urllib.error.URLError:  # network/transport-level failure
            return (
                {"error": "transport_failure", "category": CATEGORY_TRANSPORT_FAILURE,
                 "tool": name, "message": TRANSPORT_FAILURE_MESSAGE},
                True,
            )
        except Exception:  # defensive: any handler bug → LLM-visible error
            return (
                {"error": "tool_handler_exception", "category": CATEGORY_HANDLER_EXCEPTION,
                 "tool": name, "message": HANDLER_FAILURE_MESSAGE},
                True,
            )
        if is_local_rejection:
            # A refusal the router enforced locally (blank justification,
            # commit-pending). A genuine error: flagged is_error, categorized
            # local_rejection, and — because no request was sent — it cannot
            # have created a proposal. The internal marker is stripped so it
            # never reaches the model.
            clean = {k: v for k, v in payload.items() if k != "_local_rejection"}
            clean.setdefault("category", CATEGORY_LOCAL_REJECTION)
            return (clean, True)
        if type(status) is int and status >= 400:
            # An HTTP rejection is a genuine tool error. Keep bounded metadata
            # (status + any error code/message) but flag it so callers do not
            # count a rejected proposal/commit as applied. Only an EXACT
            # builtin int classifies: bool and int subclasses are not HTTP
            # statuses and are never queried for their class.
            return ({**payload, "category": CATEGORY_HTTP_REJECTION}, True)
        return payload, False

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
        # Local refusals carry `_local_rejection` so execute() flags them
        # is_error with the local_rejection category and no request is sent —
        # so they can never mint a proposal id.
        if not justification.strip():
            return {"error": "bad_request",
                    "category": CATEGORY_LOCAL_REJECTION,
                    "_local_rejection": True,
                    "message": "justification is required and must be non-empty"}
        # commit-pending is rejected outright (not silently downgraded) so the
        # caller sees that only dry-run is available in this quarantined path.
        if requested_mode == "commit-pending":
            return {"error": "commit_pending_forbidden",
                    "category": CATEGORY_LOCAL_REJECTION,
                    "_local_rejection": True,
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
    """One of: "end_turn" (LLM finished), "max_depth" (per-turn cap reached),
    "tool_budget_exhausted" (total tool-call budget reached)."""

    turns: int
    """Number of LLM `complete()` calls made this iteration."""

    tool_calls_executed: int
    """Total tool calls executed across all turns this iteration (excludes calls
    refused unexecuted once the budget was exhausted)."""

    proposals_created: list[str] = field(default_factory=list)
    """Proposal IDs returned by successful propose_tuning calls."""

    commits_applied: list[str] = field(default_factory=list)
    """Proposal IDs successfully committed. Always empty under the quarantine —
    there is no LLM-facing commit path — but retained for shape stability."""

    final_text: Optional[str] = None
    """Last assistant text block, if any."""

    usage_total: dict[str, int] = field(default_factory=dict)
    """Sum of tokens across all turns this iteration. In the audit receipt only
    ``input_tokens`` / ``output_tokens`` are retained (other keys discarded)."""

    outcome_counts: dict[str, int] = field(default_factory=dict)
    """Deterministic count of tool-call outcomes by category: ``ok``,
    ``unknown_tool``, ``handler_exception``, ``transport_failure``,
    ``http_rejection``, ``budget_rejection``, ``proposal_limit``,
    ``local_rejection``. The audit receipt keeps only these known categories."""

    def audit_receipt(self) -> dict[str, Any]:
        """A bounded, payload-free LeanCTX audit handoff for this iteration.

        Built by strict allowlist normalization (see ``build_audit_receipt``):
        only the fixed receipt schema survives — stop reason (allowlisted or
        ``unknown``), non-negative clamped counts, known outcome/usage keys, and
        canonical proposal ids. Never tool payloads, prompts,
        credentials, headers, or raw backend responses. Deterministically
        serializable with plain ``json.dumps`` and guaranteed
        ≤ MAX_RECEIPT_BYTES."""
        return build_audit_receipt(self)


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
        max_total_tool_calls: int = DEFAULT_MAX_TOTAL_TOOL_CALLS,
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
        # Two independent, validated budgets: per-turn depth and total tool
        # calls. Malformed/out-of-range limits are rejected at construction.
        self.max_tool_depth = _validate_positive_limit("max_tool_depth", max_tool_depth)
        self.max_total_tool_calls = _validate_positive_limit(
            "max_total_tool_calls", max_total_tool_calls)
        self.max_tokens_per_call = max_tokens_per_call
        self.temperature = temperature

    def run_one_iteration(self, trigger_message: str) -> IterationResult:
        """Run one observe-decide-act cycle triggered by `trigger_message`.

        Two budgets bound the loop: `max_tool_depth` caps LLM turns, and
        `max_total_tool_calls` caps total tool executions across the whole
        iteration. When a turn's tool calls would exceed the total budget, only
        the permitted prefix is executed; every remaining call in that turn gets
        an explicit budget_rejection error result (so the conversation history
        stays structurally valid) and the iteration stops."""
        messages: list[Message] = [Message(role="user", content=trigger_message)]
        turns = 0
        tool_calls_executed = 0
        proposal_attempts = 0
        proposals_created: list[str] = []
        commits_applied: list[str] = []
        usage_total: dict[str, int] = {}
        outcome_counts: dict[str, int] = {}
        final_text: Optional[str] = None

        def _record(category: str) -> None:
            outcome_counts[category] = outcome_counts.get(category, 0) + 1

        def _result(stopped: str) -> IterationResult:
            return IterationResult(
                stopped_because=stopped,
                turns=turns,
                tool_calls_executed=tool_calls_executed,
                proposals_created=proposals_created,
                commits_applied=commits_applied,
                final_text=final_text,
                usage_total=usage_total,
                outcome_counts=dict(outcome_counts),
            )

        for _depth in range(self.max_tool_depth):
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
            messages.append(Message(role="assistant", content=list(response.raw_content)))

            if not response.tool_calls:
                return _result("end_turn")

            result_blocks: list = []
            budget_hit = False
            for call in response.tool_calls:
                # Total-tool-call budget: once exhausted, refuse every remaining
                # call in this batch with an explicit error result (unexecuted).
                if tool_calls_executed >= self.max_total_tool_calls:
                    _record(CATEGORY_BUDGET_REJECTION)
                    budget_hit = True
                    result_blocks.append(_error_block(
                        call.id, "budget_exhausted", CATEGORY_BUDGET_REJECTION,
                        "total tool-call budget reached; call not executed"))
                    continue

                # At most one proposal attempt per iteration, enforced in code.
                if call.name == "propose_tuning":
                    if proposal_attempts >= 1:
                        tool_calls_executed += 1
                        _record(CATEGORY_PROPOSAL_LIMIT)
                        result_blocks.append(_error_block(
                            call.id, "proposal_limit_exceeded", CATEGORY_PROPOSAL_LIMIT,
                            "at most one proposal attempt per iteration"))
                        continue
                    proposal_attempts += 1

                payload, is_error = self.router.execute(call.name, call.arguments)
                tool_calls_executed += 1
                if is_error:
                    _record(str(payload.get("category", CATEGORY_HANDLER_EXCEPTION)))
                else:
                    _record(OUTCOME_OK)
                    if call.name == "propose_tuning":
                        pid = payload.get("proposal_id")
                        if pid:
                            proposals_created.append(pid)
                    elif call.name == "commit_tuning":
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
            if budget_hit:
                return _result("tool_budget_exhausted")

        return _result("max_depth")


def _error_block(tool_use_id: str, error: str, category: str, message: str) -> ToolResultBlock:
    """A structured, bounded error tool-result block (no payloads)."""
    return ToolResultBlock(
        tool_use_id=tool_use_id,
        content=json.dumps(
            {"error": error, "category": category, "message": message},
            sort_keys=True,
        ),
        is_error=True,
    )


# -- audit receipt: strict allowlist normalization --------------------------
#
# The receipt carries ONLY known, fixed-schema values. Every field is
# allowlisted, so no arbitrary input key, secret-looking text, or object
# __str__ can ever enter it — unknown/invalid values are DISCARDED or replaced
# by a fixed token, never stringified. Because every surviving value is already
# a bounded JSON primitive, the receipt serializes with plain
# ``json.dumps(..., sort_keys=True)`` (no ``default=str`` crutch), and the size
# guarantee holds before serialization rather than being patched after it.

_RECEIPT_MAX_LIST = 64
"""Max number of ids retained in a list field."""
_RECEIPT_MAX_UINT = 10 ** 12
"""Magnitude clamp for any count/usage integer (well beyond any real value)."""

_ID_RE = re.compile(r"\Aprop-[0-9a-f]{8}\Z")
"""The canonical production proposal id: ``prop-`` + 8 lowercase hex chars, as
minted by ``tuning_api._new_proposal_id`` (``"prop-" + secrets.token_hex(4)``).
Both ``proposals_created`` and ``commits_applied`` hold proposal ids. Anything
that is not exactly this shape — a secret-looking string, arbitrary otherwise-
valid text, an uppercase/overlong/malformed id, or a non-string — is discarded."""

_ALLOWED_STOP_REASONS = frozenset({"end_turn", "max_depth", "tool_budget_exhausted"})
_ALLOWED_OUTCOME_KEYS = frozenset({
    OUTCOME_OK, CATEGORY_UNKNOWN_TOOL, CATEGORY_HANDLER_EXCEPTION,
    CATEGORY_TRANSPORT_FAILURE, CATEGORY_HTTP_REJECTION,
    CATEGORY_BUDGET_REJECTION, CATEGORY_PROPOSAL_LIMIT, CATEGORY_LOCAL_REJECTION,
})
_ALLOWED_USAGE_KEYS = frozenset({"input_tokens", "output_tokens"})


def _norm_uint(value: Any) -> tuple[int, bool]:
    """Non-negative bounded integer normalizer → (value, changed). Rejects
    bool, negatives and non-integers (→ 0) and clamps oversized magnitudes.
    Never invokes ``__str__`` and never raises (even on 10**10000)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0, True
    if value < 0:
        return 0, True
    if value > _RECEIPT_MAX_UINT:
        return _RECEIPT_MAX_UINT, True
    return value, False


def _norm_stop_reason(value: Any) -> tuple[str, bool]:
    """Allowlist the stop reason. Any unknown or non-string value becomes the
    fixed token ``"unknown"`` — its text is never copied or prefixed."""
    if isinstance(value, str) and value in _ALLOWED_STOP_REASONS:
        return value, False
    return "unknown", True


def _norm_id_list(values: Any) -> tuple[list[str], bool]:
    """Keep only canonical proposal ids (``prop-`` + 8 lowercase hex), up to the
    list cap → (ids, changed). Anything else is omitted without invoking
    ``__str__``. Only an EXACT built-in ``list``/``tuple`` is iterated — a
    hostile subclass (e.g. one whose ``__iter__`` raises) is rejected by type
    before iteration, yielding an empty list with ``changed=True``."""
    if type(values) not in (list, tuple):
        return [], True
    items = list(values)
    changed = len(items) > _RECEIPT_MAX_LIST
    out: list[str] = []
    for v in items[:_RECEIPT_MAX_LIST]:
        if isinstance(v, str) and _ID_RE.match(v):
            out.append(v)
        else:
            changed = True  # dropped a non-canonical / non-string id
    return out, changed


def _norm_count_map(mapping: Any, allowed_keys: frozenset) -> tuple[dict[str, int], bool]:
    """Keep only allowlisted string keys mapped to normalized non-negative
    integers → (map, changed). Unknown or non-string keys are discarded (never
    stringified, so coercion cannot create a key collision). Only an EXACT
    built-in ``dict`` is read — a hostile subclass (e.g. one whose ``items``
    raises) is rejected by type before ``.items()`` is ever called."""
    if type(mapping) is not dict:
        return {}, True
    out: dict[str, int] = {}
    changed = False
    for key, value in mapping.items():
        if not isinstance(key, str) or key not in allowed_keys:
            changed = True  # discard unknown / non-string key, no __str__
            continue
        iv, ic = _norm_uint(value)
        out[key] = iv
        changed = changed or ic
    return dict(sorted(out.items())), changed


def build_audit_receipt(result: "IterationResult") -> dict[str, Any]:
    """Build a bounded, payload-free LeanCTX audit receipt from an
    IterationResult. Deterministic (sorted keys) and **guaranteed**
    ≤ MAX_RECEIPT_BYTES.

    Supported schema (all other input is discarded, never stringified):

    - ``schema`` — fixed literal.
    - ``stopped_because`` — one of ``end_turn`` / ``max_depth`` /
      ``tool_budget_exhausted``; any other value becomes ``unknown``.
    - ``turns`` / ``tool_calls_executed`` — non-negative integers, magnitude-
      clamped.
    - ``outcome_counts`` — only the known outcome categories → non-negative
      ints.
    - ``usage_total`` — only ``input_tokens`` / ``output_tokens`` → non-negative
      ints.
    - ``proposals_created`` / ``commits_applied`` — canonical proposal ids only
      (``prop-`` + 8 lowercase hex), list-capped; anything else discarded.
    - ``truncated`` — true whenever any value was normalized away, or the
      trim loop / fixed minimal fallback fired.

    Because every surviving value is a bounded JSON primitive, no arbitrary
    input key, secret-looking text, or object ``__str__`` can enter the
    receipt, and it excludes tool payloads, prompts, credentials, headers, and
    raw backend responses."""
    stopped, t_stop = _norm_stop_reason(getattr(result, "stopped_because", ""))
    turns, t_turns = _norm_uint(getattr(result, "turns", 0))
    tce, t_tce = _norm_uint(getattr(result, "tool_calls_executed", 0))
    outcome_counts, t_oc = _norm_count_map(
        getattr(result, "outcome_counts", {}), _ALLOWED_OUTCOME_KEYS)
    proposals, t_pc = _norm_id_list(getattr(result, "proposals_created", []))
    commits, t_ca = _norm_id_list(getattr(result, "commits_applied", []))
    usage, t_us = _norm_count_map(
        getattr(result, "usage_total", {}), _ALLOWED_USAGE_KEYS)
    receipt: dict[str, Any] = {
        "schema": "leanctx-orchestrator-v1",
        "stopped_because": stopped,
        "turns": turns,
        "tool_calls_executed": tce,
        "outcome_counts": outcome_counts,
        "proposals_created": proposals,
        "commits_applied": commits,
        "usage_total": usage,
        "truncated": any((t_stop, t_turns, t_tce, t_oc, t_pc, t_ca, t_us)),
    }

    # Every value is already a bounded JSON primitive → plain dumps, no
    # default=str. This is the true size, computed before any external consumer.
    def _size(obj: dict) -> int:
        return len(json.dumps(obj, sort_keys=True).encode("utf-8"))

    # Allowlisting already bounds the receipt far under the cap; this
    # deterministic trim + fixed minimal fallback are the final guarantee.
    while _size(receipt) > MAX_RECEIPT_BYTES:
        receipt["truncated"] = True
        if receipt["proposals_created"]:
            receipt["proposals_created"] = receipt["proposals_created"][:-1]
            continue
        if receipt["commits_applied"]:
            receipt["commits_applied"] = receipt["commits_applied"][:-1]
            continue
        if receipt["outcome_counts"]:
            receipt["outcome_counts"] = {}
            continue
        if receipt["usage_total"]:
            receipt["usage_total"] = {}
            continue
        # stopped_because is already a short allowlisted token; nothing else to
        # trim → fixed minimal fallback, guaranteed tiny.
        receipt = {
            "schema": "leanctx-orchestrator-v1",
            "stopped_because": "unknown",
            "truncated": True,
        }
        break
    return receipt


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
    "build_audit_receipt",
    "DEFAULT_MAX_TOTAL_TOOL_CALLS",
    "MAX_LIMIT_CEILING",
    "MAX_RECEIPT_BYTES",
    "OUTCOME_OK",
    "HANDLER_FAILURE_MESSAGE",
    "TRANSPORT_FAILURE_MESSAGE",
    "CATEGORY_UNKNOWN_TOOL",
    "CATEGORY_HANDLER_EXCEPTION",
    "CATEGORY_TRANSPORT_FAILURE",
    "CATEGORY_HTTP_REJECTION",
    "CATEGORY_BUDGET_REJECTION",
    "CATEGORY_PROPOSAL_LIMIT",
    "CATEGORY_LOCAL_REJECTION",
]
