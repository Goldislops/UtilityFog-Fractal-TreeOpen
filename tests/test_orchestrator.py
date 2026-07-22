"""Tests for scripts/orchestrator.py and scripts/orchestrator_config.py
(Phase 18 PR 6).

Covers:
  - OrchestratorClient: every endpoint routes method+url+body correctly
    through the injected http_do.
  - HTTP error body propagates with status code into handler payload.
  - ToolRouter: known tools route correctly; unknown tool returns error;
    handler exception becomes an error payload (never raises up).
  - propose_tuning without a justification is rejected at the router level.
  - commit_tuning always uses the configured approver (never human:...).
  - Orchestrator.run_one_iteration: text-only response → stopped_because=end_turn.
  - Tool-use response → executes tools, appends tool_result, loops, ends
    on final text turn. Proposals and commits are counted.
  - max_tool_depth caps runaway loops.
  - Conversation history accumulates correctly (assistant raw_content +
    user tool_result) across multi-turn iterations.
  - Usage totals across turns accumulate.
  - orchestrator_config: factory wires everything sensibly; unknown backend
    raises; mock is default.
"""

from __future__ import annotations

import json
import urllib.error
from typing import Optional

import pytest

from scripts.agent_backends import (
    AgentResponse,
    Message,
    MockBackend,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from scripts.orchestrator import (
    CATEGORY_HANDLER_EXCEPTION,
    CATEGORY_LOCAL_REJECTION,
    CATEGORY_TRANSPORT_FAILURE,
    DEFAULT_MAX_TOTAL_TOOL_CALLS,
    IterationResult,
    MAX_LIMIT_CEILING,
    MAX_RECEIPT_BYTES,
    MODE_OBSERVE,
    MODE_PROPOSE,
    OUTCOME_OK,
    Orchestrator,
    OrchestratorClient,
    ToolRouter,
    build_audit_receipt,
    observation_tools,
    proposal_tools,
    resolve_mode,
    tools_for_mode,
)
from scripts.orchestrator_config import (
    DEFAULT_BASE_URL,
    DEFAULT_SYSTEM_PROMPT,
    OrchestratorConfig,
    create_backend,
    create_orchestrator,
)


# -- fake HTTP --------------------------------------------------------------


class FakeHttp:
    """Records every call, returns caller-supplied responses keyed by
    (method, path)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses: dict[tuple[str, str], tuple[int, dict]] = {}

    def set(self, method: str, path: str, status: int, body: dict) -> None:
        self.responses[(method, path)] = (status, body)

    def __call__(self, method, url, *, json=None, timeout=5.0) -> tuple[int, dict]:
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        self.calls.append({"method": method, "url": url, "path": path, "json": json})
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"unscripted HTTP call: {key}")
        return self.responses[key]


# -- OrchestratorClient ------------------------------------------------------


def _client_with_fake(base: str = "http://test:8080") -> tuple[OrchestratorClient, FakeHttp]:
    http = FakeHttp()
    client = OrchestratorClient(base, http_do=http)
    return client, http


def test_client_get_census_routes_correctly():
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 200, {"generation": 1_500_000})
    status, body = client.get_census()
    assert status == 200
    assert body == {"generation": 1_500_000}
    assert http.calls[0]["method"] == "GET"
    assert http.calls[0]["path"] == "/api/census"


def test_client_get_endpoints_all_route():
    client, http = _client_with_fake()
    for path, getter in [
        ("/api/census", client.get_census),
        ("/api/equanimity", client.get_equanimity),
        ("/api/acoustic", client.get_acoustic),
        ("/api/params", client.get_params),
        ("/api/params/schema", client.get_params_schema),
        ("/api/status", client.get_status),
    ]:
        http.set("GET", path, 200, {"path": path})
        status, body = getter()
        assert status == 200
        assert body["path"] == path


def test_client_propose_posts_json_body():
    client, http = _client_with_fake()
    http.set("POST", "/api/tuning/propose", 200,
             {"proposal_id": "prop-abc", "status": "accepted"})
    status, body = client.propose_tuning(
        params={"signal_interval": 12},
        source="agent:test",
        justification="reduce polling overhead",
        mode="dry-run",
    )
    assert status == 200
    assert body["proposal_id"] == "prop-abc"
    sent = http.calls[0]["json"]
    assert sent["params"] == {"signal_interval": 12}
    assert sent["source"] == "agent:test"
    assert sent["justification"] == "reduce polling overhead"
    assert sent["mode"] == "dry-run"


def test_client_commit_posts_proposal_id_and_approver():
    client, http = _client_with_fake()
    http.set("POST", "/api/tuning/commit", 200, {"status": "committed"})
    client.commit_tuning("prop-abc", "policy:auto")
    assert http.calls[0]["json"] == {"proposal_id": "prop-abc", "approver": "policy:auto"}


def test_client_rollback_posts_target():
    client, http = _client_with_fake()
    http.set("POST", "/api/tuning/rollback", 200, {"status": "rolled_back"})
    client.rollback_tuning("prop-abc")
    assert http.calls[0]["json"] == {"to_proposal_id": "prop-abc"}


# -- ToolRouter -------------------------------------------------------------


def test_router_unknown_tool_returns_error_payload():
    client, _ = _client_with_fake()
    router = ToolRouter(client)
    payload, is_error = router.execute("does_not_exist", {})
    assert is_error is True
    assert payload["error"] == "unknown_tool"


def test_router_routes_get_census_through_client():
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 200, {"generation": 42})
    router = ToolRouter(client)
    payload, is_error = router.execute("get_medusa_census", {})
    assert is_error is False
    assert payload == {"generation": 42}


def test_router_propose_requires_nonempty_justification():
    """A blank justification is a local rejection (Package T amendment): the
    router refuses it before any HTTP call, flags is_error=True, and categorizes
    it local_rejection. No `_local_rejection` marker leaks to the model."""
    client, _ = _client_with_fake()
    router = ToolRouter(client, mode=MODE_PROPOSE)
    payload, is_error = router.execute(
        "propose_tuning",
        {"params": {"signal_interval": 12}, "justification": "   "},
    )
    assert is_error is True
    assert payload["error"] == "bad_request"
    assert payload["category"] == CATEGORY_LOCAL_REJECTION
    assert "justification" in payload["message"]
    assert "_local_rejection" not in payload


def test_router_propose_calls_client_with_orchestrator_source():
    client, http = _client_with_fake()
    http.set("POST", "/api/tuning/propose", 200, {"proposal_id": "prop-x"})
    router = ToolRouter(client, mode=MODE_PROPOSE, orchestrator_source="agent:legacy-tuner")
    router.execute(
        "propose_tuning",
        {"params": {"signal_interval": 14}, "justification": "reason"},
    )
    sent = http.calls[0]["json"]
    assert sent["source"] == "agent:legacy-tuner"
    # Package S: the router forces dry-run at the boundary.
    assert sent["mode"] == "dry-run"


def test_router_never_registers_commit_tool_in_any_mode():
    """Package S: commit_tuning is not an LLM-facing tool in observe OR propose
    mode. A call to it returns unknown_tool and makes no HTTP request — the LLM
    has no path to the commit endpoint through the router."""
    for mode in (MODE_OBSERVE, MODE_PROPOSE):
        client, http = _client_with_fake()
        router = ToolRouter(client, mode=mode)
        payload, is_error = router.execute(
            "commit_tuning", {"proposal_id": "prop-x", "approver": "human:evil"})
        assert is_error is True
        assert payload["error"] == "unknown_tool"
        assert http.calls == []  # no POST attempted


def test_router_handler_exception_becomes_error_payload():
    """Any bug in a handler must not crash the loop — surfaces as a tool error."""
    client, http = _client_with_fake()

    class Boom(FakeHttp):
        def __call__(self, method, url, *, json=None, timeout=5.0):
            raise ValueError("boom")

    client = OrchestratorClient("http://test", http_do=Boom())
    router = ToolRouter(client)
    payload, is_error = router.execute("get_medusa_census", {})
    assert is_error is True
    assert payload["error"] == "tool_handler_exception"


def test_router_http_error_status_is_flagged_as_error():
    """Package T: HTTP status >= 400 is a genuine tool error (is_error True),
    categorized http_rejection, with bounded status/error metadata retained."""
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 500, {"error": "server_broke"})
    router = ToolRouter(client)
    payload, is_error = router.execute("get_medusa_census", {})
    assert is_error is True
    assert payload["_status"] == 500
    assert payload["error"] == "server_broke"
    assert payload["category"] == "http_rejection"


# -- Orchestrator ------------------------------------------------------------


def _text_response(text: str, *, input_tokens: int = 10, output_tokens: int = 20) -> AgentResponse:
    return AgentResponse.from_content(
        [TextBlock(text=text)],
        stop_reason="end_turn",
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )


def _tool_use_response(
    tool_use_id: str,
    name: str,
    input_: dict,
    *,
    text: Optional[str] = None,
) -> AgentResponse:
    blocks = []
    if text is not None:
        blocks.append(TextBlock(text=text))
    blocks.append(ToolUseBlock(id=tool_use_id, name=name, input=input_))
    return AgentResponse.from_content(
        blocks,
        stop_reason="tool_use",
        usage={"input_tokens": 15, "output_tokens": 25},
    )


def _make_orchestrator(backend: MockBackend, *, mode: str = MODE_OBSERVE) -> tuple[Orchestrator, FakeHttp]:
    http = FakeHttp()
    client = OrchestratorClient("http://test:8080", http_do=http)
    orch = Orchestrator(
        backend=backend,
        client=client,
        system_prompt="test system",
        mode=mode,
        max_tool_depth=4,
    )
    return orch, http


def test_iteration_text_only_stops_cleanly():
    backend = MockBackend(responses=[_text_response("looks healthy, no change")])
    orch, _ = _make_orchestrator(backend)
    result = orch.run_one_iteration("observe medusa")
    assert result.stopped_because == "end_turn"
    assert result.turns == 1
    assert result.tool_calls_executed == 0
    assert result.final_text == "looks healthy, no change"
    assert result.usage_total == {"input_tokens": 10, "output_tokens": 20}


def test_iteration_propose_then_end():
    """First turn: propose. Second turn: text 'done'."""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "propose_tuning", {
            "params": {"signal_interval": 12},
            "justification": "reduce polling overhead",
            "mode": "dry-run",
        }, text="I'll propose reducing signal_interval."),
        _text_response("proposal submitted"),
    ])
    orch, http = _make_orchestrator(backend, mode=MODE_PROPOSE)
    http.set("POST", "/api/tuning/propose", 200,
             {"proposal_id": "prop-newid", "status": "accepted"})
    result = orch.run_one_iteration("observe")
    assert result.stopped_because == "end_turn"
    assert result.turns == 2
    assert result.tool_calls_executed == 1
    assert result.proposals_created == ["prop-newid"]
    assert result.commits_applied == []
    # usage accumulated across turns
    assert result.usage_total["input_tokens"] == 15 + 10
    assert result.usage_total["output_tokens"] == 25 + 20


def test_iteration_commit_tool_call_is_unknown_and_uncommitted():
    """Package S: even if a model emits a commit_tuning tool call, there is no
    such tool — it resolves to unknown_tool, no POST is made, and nothing is
    committed. (No LLM-facing commit path exists in any mode.)"""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "commit_tuning", {"proposal_id": "prop-xyz"}),
        _text_response("nothing to commit with"),
    ])
    orch, http = _make_orchestrator(backend, mode=MODE_PROPOSE)
    result = orch.run_one_iteration("observe")
    assert result.stopped_because == "end_turn"
    assert result.commits_applied == []
    # The commit tool call was executed as unknown_tool; no commit POST made.
    assert all(c["path"] != "/api/tuning/commit" for c in http.calls)


def test_iteration_commit_pending_proposal_is_rejected():
    """propose mode forces dry-run: a commit-pending request is refused with a
    deterministic local rejection (Package T amendment), not silently
    downgraded. It counts under local_rejection, never ok, never a proposal."""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "propose_tuning", {
            "params": {"signal_interval": 12},
            "justification": "reduce overhead",
            "mode": "commit-pending",
        }),
        _text_response("ok, dry-run only"),
    ])
    orch, http = _make_orchestrator(backend, mode=MODE_PROPOSE)
    result = orch.run_one_iteration("observe")
    assert result.stopped_because == "end_turn"
    # No proposal was created (the router refused commit-pending before POSTing).
    assert result.proposals_created == []
    assert http.calls == []  # no POST — rejected at the router boundary
    # Accounting: counted as a local rejection, not a success.
    assert result.outcome_counts.get(CATEGORY_LOCAL_REJECTION) == 1
    assert result.outcome_counts.get(OUTCOME_OK, 0) == 0


def test_iteration_hits_max_depth():
    """LLM that never stops tool_use gets capped at max_tool_depth."""
    infinite = [
        _tool_use_response(f"tu_{i}", "get_medusa_census", {})
        for i in range(20)
    ]
    backend = MockBackend(responses=infinite)
    orch, http = _make_orchestrator(backend)  # max_tool_depth=4
    http.set("GET", "/api/census", 200, {"generation": 1})
    result = orch.run_one_iteration("observe")
    assert result.stopped_because == "max_depth"
    assert result.turns == 4
    assert result.tool_calls_executed == 4


def test_iteration_conversation_history_includes_tool_results():
    """The MockBackend records the messages passed to each complete() call.
    We verify turn 2 sees the tool_result from turn 1's tool_use."""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "get_medusa_census", {}),
        _text_response("done"),
    ])
    orch, http = _make_orchestrator(backend)
    http.set("GET", "/api/census", 200, {"generation": 999})
    orch.run_one_iteration("observe")
    calls = backend.calls
    assert len(calls) == 2
    turn2_messages = calls[1].messages
    # Structure: [user trigger, assistant raw_content, user tool_results]
    assert len(turn2_messages) == 3
    assert turn2_messages[0].role == "user"
    assert turn2_messages[1].role == "assistant"
    assert turn2_messages[2].role == "user"
    assert isinstance(turn2_messages[2].content, list)
    tool_result = turn2_messages[2].content[0]
    assert isinstance(tool_result, ToolResultBlock)
    assert tool_result.tool_use_id == "tu_1"
    assert "999" in tool_result.content  # json-encoded generation


def test_iteration_failed_propose_is_not_counted():
    """422 from the API is NOT counted as a created proposal."""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "propose_tuning", {
            "params": {"signal_interval": 0}, "justification": "oops", "mode": "dry-run",
        }),
        _text_response("got rejected"),
    ])
    orch, http = _make_orchestrator(backend)
    http.set("POST", "/api/tuning/propose", 422,
             {"status": "rejected", "validation": {"ok": False}})
    result = orch.run_one_iteration("observe")
    # proposals_created requires proposal_id in response body; a rejection
    # without one doesn't land in the list.
    assert result.proposals_created == []


def test_iteration_system_prompt_is_forwarded():
    backend = MockBackend(responses=[_text_response("ok")])
    orch, _ = _make_orchestrator(backend)
    orch.system_prompt = "custom system"
    orch.run_one_iteration("go")
    assert backend.calls[0].system == "custom system"


def test_iteration_tools_default_to_observation_only():
    """Package S: a default (observe) orchestrator advertises observation tools
    only — no propose, no commit."""
    backend = MockBackend(responses=[_text_response("ok")])
    orch, _ = _make_orchestrator(backend)  # default mode = observe
    orch.run_one_iteration("go")
    tool_names = [t.name for t in backend.calls[0].tools]
    for expected in (
        "get_medusa_census", "get_medusa_equanimity", "get_acoustic_map",
        "get_params", "get_params_schema",
    ):
        assert expected in tool_names
    assert "propose_tuning" not in tool_names
    assert "commit_tuning" not in tool_names


def test_iteration_propose_mode_adds_proposal_tool_only():
    backend = MockBackend(responses=[_text_response("ok")])
    orch, _ = _make_orchestrator(backend, mode=MODE_PROPOSE)
    orch.run_one_iteration("go")
    tool_names = [t.name for t in backend.calls[0].tools]
    assert "propose_tuning" in tool_names
    assert "commit_tuning" not in tool_names


# -- tool spec shape ---------------------------------------------------------


def test_proposal_tool_requires_justification_and_has_no_commit_mode():
    specs = {t.name: t for t in proposal_tools()}
    assert "commit_tuning" not in specs  # no commit tool exists
    propose = specs["propose_tuning"]
    assert "justification" in propose.input_schema["required"]
    assert "params" in propose.input_schema["required"]
    # The dry-run-only surface no longer advertises a mode enum toggle.
    assert "mode" not in propose.input_schema["properties"]


# -- orchestrator_config ----------------------------------------------------


def test_config_defaults_sensibly():
    cfg = OrchestratorConfig()
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.backend_name == "mock"
    assert cfg.mode == "observe"  # fail-closed default; no LLM-facing write surface


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("MEDUSA_API_BASE_URL", "http://medusa.local:9090")
    monkeypatch.setenv("MEDUSA_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("MEDUSA_MAX_TOOL_DEPTH", "16")
    cfg = OrchestratorConfig.from_env()
    assert cfg.base_url == "http://medusa.local:9090"
    assert cfg.backend_name == "anthropic"
    assert cfg.max_tool_depth == 16


def test_create_backend_mock_default():
    cfg = OrchestratorConfig(backend_name="mock")
    backend = create_backend(cfg)
    assert backend.name == "mock"


def test_create_backend_unknown_raises():
    cfg = OrchestratorConfig(backend_name="wibbly-wobbly")
    with pytest.raises(ValueError, match="unknown backend"):
        create_backend(cfg)


def test_create_backend_openai_compat():
    """PR 7a wiring: MEDUSA_AGENT_BACKEND=openai-compat instantiates
    OpenAICompatBackend with config-supplied base_url / model / api_key."""
    from scripts.agent_backends import OpenAICompatBackend
    pytest.importorskip("openai")  # construction needs the real openai SDK
    cfg = OrchestratorConfig(
        backend_name="openai-compat",
        openai_base_url="https://api.deepseek.com/v1",
        openai_model="deepseek-chat",
        openai_api_key="sk-fake-for-construction",  # SDK accepts at construction
    )
    backend = create_backend(cfg)
    assert isinstance(backend, OpenAICompatBackend)
    assert backend.model == "deepseek-chat"
    assert backend.name == "openai-compat"


def test_create_backend_underscore_alias_accepted():
    """PR 7b: openai_compat (with underscore) is accepted as an alias for
    openai-compat. Humans will inevitably type the underscore — env vars
    historically use underscores and the shell hyphen is awkward."""
    from scripts.agent_backends import OpenAICompatBackend
    pytest.importorskip("openai")  # construction needs the real openai SDK
    cfg = OrchestratorConfig(
        backend_name="openai_compat",  # underscore!
        openai_base_url="https://api.deepseek.com/v1",
        openai_model="deepseek-chat",
        openai_api_key="sk-fake",
    )
    backend = create_backend(cfg)
    assert isinstance(backend, OpenAICompatBackend)


def test_create_backend_nemo_cloud_redirects_to_openai_compat():
    """Friendly-error path: anyone setting MEDUSA_AGENT_BACKEND=nemo_cloud
    (the old planned-but-superseded name) gets pointed at the openai-compat
    config that replaced it."""
    cfg = OrchestratorConfig(backend_name="nemo_cloud")
    with pytest.raises(ValueError, match="openai-compat"):
        create_backend(cfg)


def test_config_from_env_reads_openai_compat_vars(monkeypatch):
    monkeypatch.setenv("MEDUSA_AGENT_BACKEND", "openai-compat")
    monkeypatch.setenv("MEDUSA_OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("MEDUSA_OPENAI_MODEL", "llama3.1:8b")
    monkeypatch.setenv("MEDUSA_OPENAI_API_KEY", "ollama")
    monkeypatch.setenv("MEDUSA_OPENAI_EXTRA_HEADERS", '{"X-Custom": "abc"}')
    cfg = OrchestratorConfig.from_env()
    assert cfg.backend_name == "openai-compat"
    assert cfg.openai_base_url == "http://localhost:11434/v1"
    assert cfg.openai_model == "llama3.1:8b"
    assert cfg.openai_api_key == "ollama"
    assert cfg.openai_extra_headers == {"X-Custom": "abc"}


def test_config_from_env_tolerates_malformed_extra_headers(monkeypatch):
    """Bad JSON in MEDUSA_OPENAI_EXTRA_HEADERS must not crash startup."""
    monkeypatch.setenv("MEDUSA_OPENAI_EXTRA_HEADERS", "{not json")
    cfg = OrchestratorConfig.from_env()
    assert cfg.openai_extra_headers is None


def test_config_from_env_extra_headers_must_be_dict(monkeypatch):
    """A JSON list/string in MEDUSA_OPENAI_EXTRA_HEADERS is rejected silently."""
    monkeypatch.setenv("MEDUSA_OPENAI_EXTRA_HEADERS", '["not", "a", "dict"]')
    cfg = OrchestratorConfig.from_env()
    assert cfg.openai_extra_headers is None


def test_create_orchestrator_smoke():
    """End-to-end wire: creates all the pieces without raising."""
    backend = MockBackend(responses=[_text_response("ok")])
    orch = create_orchestrator(
        config=OrchestratorConfig(),
        backend=backend,
    )
    assert orch.backend is backend
    assert orch.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert orch.max_tool_depth == 8


# -- Package S: observe-by-default capability model -------------------------


def test_config_default_mode_is_observe():
    assert OrchestratorConfig().mode == MODE_OBSERVE


def test_resolve_mode_fail_closed_is_exhaustive():
    """Absent, malformed, and unknown values all fail closed to observe; only
    the exact tokens observe/propose (trimmed, case-insensitive) are honored;
    only propose is a non-observe result."""
    for raw in (None, "", "   ", "garbage", "commit", "COMMIT", "obserform",
                "propose!", "0", "true", "observe ; propose"):
        assert resolve_mode(raw) == MODE_OBSERVE
    for raw in ("observe", "OBSERVE", " observe ", "Observe"):
        assert resolve_mode(raw) == MODE_OBSERVE
    for raw in ("propose", "PROPOSE", " propose ", "Propose"):
        assert resolve_mode(raw) == MODE_PROPOSE


def test_config_from_env_mode(monkeypatch):
    monkeypatch.setenv("MEDUSA_ORCHESTRATOR_MODE", "propose")
    assert OrchestratorConfig.from_env().mode == MODE_PROPOSE
    monkeypatch.setenv("MEDUSA_ORCHESTRATOR_MODE", "observe")
    assert OrchestratorConfig.from_env().mode == MODE_OBSERVE
    # Malformed → fail closed to observe.
    monkeypatch.setenv("MEDUSA_ORCHESTRATOR_MODE", "commit-everything")
    assert OrchestratorConfig.from_env().mode == MODE_OBSERVE
    monkeypatch.delenv("MEDUSA_ORCHESTRATOR_MODE", raising=False)
    assert OrchestratorConfig.from_env().mode == MODE_OBSERVE  # absent → observe


def test_tools_for_mode_inventories():
    observe_names = {t.name for t in tools_for_mode(MODE_OBSERVE)}
    propose_names = {t.name for t in tools_for_mode(MODE_PROPOSE)}
    assert "propose_tuning" not in observe_names
    assert "commit_tuning" not in observe_names
    assert "propose_tuning" in propose_names
    assert "commit_tuning" not in propose_names
    # propose is a strict superset of observe by exactly the proposal tool.
    assert propose_names - observe_names == {"propose_tuning"}


def test_observe_mode_makes_zero_posts_even_if_model_tries_to_write():
    """In observe mode, a model that emits propose/commit tool calls gets
    unknown_tool for both and the client makes zero POST requests."""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "propose_tuning",
                           {"params": {"signal_interval": 12}, "justification": "x"}),
        _tool_use_response("tu_2", "commit_tuning", {"proposal_id": "prop-x"}),
        _text_response("done"),
    ])
    orch, http = _make_orchestrator(backend, mode=MODE_OBSERVE)
    result = orch.run_one_iteration("observe")
    assert result.proposals_created == []
    assert result.commits_applied == []
    post_calls = [c for c in http.calls if c["method"] == "POST"]
    assert post_calls == []


def test_create_orchestrator_propose_mode_wires_router_and_tools():
    backend = MockBackend(responses=[_text_response("ok")])
    orch = create_orchestrator(
        config=OrchestratorConfig(mode=MODE_PROPOSE),
        backend=backend,
    )
    assert orch.mode == MODE_PROPOSE
    assert orch.router.mode == MODE_PROPOSE
    tool_names = {t.name for t in orch.tools}
    assert "propose_tuning" in tool_names
    assert "commit_tuning" not in tool_names


# -- Package T: hard limits, error semantics, bounded audit receipts ---------


def _obs_call(i: int):
    return _tool_use_response(f"tu_{i}", "get_medusa_census", {})


def test_total_tool_call_budget_executes_prefix_then_stops():
    """A single turn emitting more tool calls than the total budget executes
    only the permitted prefix; the rest get budget_rejection error results and
    the iteration stops with tool_budget_exhausted. The cap is never exceeded."""
    from scripts.agent_backends import AgentResponse, ToolUseBlock
    blocks = [ToolUseBlock(id=f"tu_{i}", name="get_medusa_census", input={}) for i in range(5)]
    resp = AgentResponse.from_content(blocks, stop_reason="tool_use",
                                      usage={"input_tokens": 1, "output_tokens": 1})
    backend = MockBackend(responses=[resp, _text_response("done")])
    http = FakeHttp()
    client = OrchestratorClient("http://test:8080", http_do=http)
    http.set("GET", "/api/census", 200, {"generation": 1})
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        max_tool_depth=4, max_total_tool_calls=3)
    result = orch.run_one_iteration("go")
    assert result.stopped_because == "tool_budget_exhausted"
    assert result.tool_calls_executed == 3          # never exceeds the cap
    assert result.outcome_counts.get("ok") == 3
    assert result.outcome_counts.get("budget_rejection") == 2
    assert len([c for c in http.calls if c["path"] == "/api/census"]) == 3


def test_budget_shared_across_turns():
    """The total budget is shared across turns, independent of max_tool_depth."""
    backend = MockBackend(responses=[_obs_call(i) for i in range(10)] + [_text_response("x")])
    http = FakeHttp()
    client = OrchestratorClient("http://test:8080", http_do=http)
    http.set("GET", "/api/census", 200, {"generation": 1})
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        max_tool_depth=10, max_total_tool_calls=2)
    result = orch.run_one_iteration("go")
    assert result.stopped_because == "tool_budget_exhausted"
    assert result.tool_calls_executed == 2


def test_second_proposal_attempt_is_refused():
    """At most one proposal attempt per iteration, enforced in code."""
    from scripts.agent_backends import AgentResponse, ToolUseBlock
    blocks = [
        ToolUseBlock(id="p1", name="propose_tuning",
                     input={"params": {"signal_interval": 12}, "justification": "a"}),
        ToolUseBlock(id="p2", name="propose_tuning",
                     input={"params": {"signal_interval": 13}, "justification": "b"}),
    ]
    resp = AgentResponse.from_content(blocks, stop_reason="tool_use",
                                      usage={"input_tokens": 1, "output_tokens": 1})
    backend = MockBackend(responses=[resp, _text_response("done")])
    http = FakeHttp()
    client = OrchestratorClient("http://test:8080", http_do=http)
    http.set("POST", "/api/tuning/propose", 200, {"proposal_id": "prop-1", "status": "accepted"})
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        mode=MODE_PROPOSE, max_tool_depth=4)
    result = orch.run_one_iteration("go")
    assert result.proposals_created == ["prop-1"]           # only the first
    assert result.outcome_counts.get("proposal_limit") == 1
    assert len([c for c in http.calls if c["path"] == "/api/tuning/propose"]) == 1


def test_http_rejections_are_errors_and_not_counted():
    """403/422/500 tool responses are is_error, categorized http_rejection, and
    never counted as created proposals or applied commits."""
    for status in (403, 422, 500):
        resp = _tool_use_response("tu_p", "propose_tuning",
                                  {"params": {"signal_interval": 12}, "justification": "x"})
        backend = MockBackend(responses=[resp, _text_response("done")])
        http = FakeHttp()
        client = OrchestratorClient("http://test:8080", http_do=http)
        http.set("POST", "/api/tuning/propose", status, {"error": "nope"})
        orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                            mode=MODE_PROPOSE, max_tool_depth=4)
        result = orch.run_one_iteration("go")
        assert result.proposals_created == []
        assert result.outcome_counts.get("http_rejection") == 1


def test_transport_failure_is_categorized():
    """A URLError from the transport surfaces as a transport_failure category,
    is_error True, without raising up into the loop."""
    import urllib.error

    def boom_http(method, url, *, json=None, timeout=5.0):
        raise urllib.error.URLError("network down")

    client = OrchestratorClient("http://test:8080", http_do=boom_http)
    router = ToolRouter(client)
    payload, is_error = router.execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == "transport_failure"


def test_handler_exception_message_does_not_leak_into_receipt():
    """A handler exception carrying a sensitive-looking string is surfaced to
    the LLM as a tool error, but the audit receipt records only the category —
    never the exception text."""
    secret = "SECRET_API_KEY_sk-abc123"

    def boom_http(method, url, *, json=None, timeout=5.0):
        raise ValueError(secret)

    resp = _tool_use_response("tu_c", "get_medusa_census", {})
    backend = MockBackend(responses=[resp, _text_response("done")])
    client = OrchestratorClient("http://test:8080", http_do=boom_http)
    orch = Orchestrator(backend=backend, client=client, system_prompt="s", max_tool_depth=4)
    result = orch.run_one_iteration("go")
    assert result.outcome_counts.get("handler_exception") == 1
    receipt_json = json.dumps(build_audit_receipt(result), sort_keys=True)
    assert secret not in receipt_json


def test_audit_receipt_is_deterministic_and_bounded():
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "get_medusa_census", {}),
        _text_response("done"),
    ])
    orch, http = _make_orchestrator(backend)
    http.set("GET", "/api/census", 200, {"generation": 1})
    result = orch.run_one_iteration("go")
    r1 = json.dumps(build_audit_receipt(result), sort_keys=True)
    r2 = json.dumps(result.audit_receipt(), sort_keys=True)
    assert r1 == r2                                   # deterministic
    assert len(r1.encode("utf-8")) <= MAX_RECEIPT_BYTES
    receipt = build_audit_receipt(result)
    assert receipt["schema"] == "leanctx-orchestrator-v1"
    assert receipt["truncated"] is False
    for banned in ("content", "payload", "system", "messages", "api_key", "headers"):
        assert banned not in receipt


def test_audit_receipt_excludes_large_tool_payloads():
    """Even if a tool returns a huge body, the receipt stays bounded and holds
    no payload text (it records only counts/ids)."""
    huge = {"generation": 1, "blob": "z" * 200000}
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "get_medusa_census", {}),
        _text_response("done"),
    ])
    orch, http = _make_orchestrator(backend)
    http.set("GET", "/api/census", 200, huge)
    result = orch.run_one_iteration("go")
    receipt_json = json.dumps(build_audit_receipt(result), sort_keys=True)
    assert len(receipt_json.encode("utf-8")) <= MAX_RECEIPT_BYTES
    assert "z" * 1000 not in receipt_json


# -- Package T amendment (Jack audit): non-dict handlers, local rejections,
#    and adversarial audit-receipt bounding -----------------------------------


@pytest.mark.parametrize("bad_return", [None, [1, 2, 3], "scalar-string", True, 42])
def test_non_dict_handler_return_becomes_handler_exception(bad_return):
    """A handler that returns a non-dict (None, list, scalar, bool) is caught by
    the defensive try boundary and surfaced as a bounded handler_exception —
    router.execute returns normally, so the iteration loop can never crash."""
    client, _ = _client_with_fake()
    router = ToolRouter(client)
    # Simulate a buggy handler returning a non-dict.
    router._handlers["get_medusa_census"] = lambda _args: bad_return
    payload, is_error = router.execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == CATEGORY_HANDLER_EXCEPTION
    assert payload["error"] == "tool_handler_exception"


@pytest.mark.parametrize("justification", ["", "   ", "\t\n "])
def test_router_local_rejection_blank_justification(justification):
    """Blank/whitespace-only justification is a local rejection: is_error, the
    local_rejection category, no HTTP POST, and no internal marker leaked."""
    client, http = _client_with_fake()
    router = ToolRouter(client, mode=MODE_PROPOSE)
    payload, is_error = router.execute(
        "propose_tuning",
        {"params": {"signal_interval": 12}, "justification": justification},
    )
    assert is_error is True
    assert payload["category"] == CATEGORY_LOCAL_REJECTION
    assert "_local_rejection" not in payload
    assert http.calls == []  # refused before any POST


def test_router_local_rejection_commit_pending():
    """commit-pending is a local rejection, not a silent downgrade: is_error,
    local_rejection category, no POST."""
    client, http = _client_with_fake()
    router = ToolRouter(client, mode=MODE_PROPOSE)
    payload, is_error = router.execute(
        "propose_tuning",
        {"params": {"signal_interval": 12}, "justification": "ok", "mode": "commit-pending"},
    )
    assert is_error is True
    assert payload["error"] == "commit_pending_forbidden"
    assert payload["category"] == CATEGORY_LOCAL_REJECTION
    assert "_local_rejection" not in payload
    assert http.calls == []


def test_iteration_blank_justification_accounting():
    """Iteration-level accounting: a blank-justification proposal increments the
    local_rejection category, never ok, and never enters proposals_created."""
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "propose_tuning",
                           {"params": {"signal_interval": 12}, "justification": "  "}),
        _text_response("acknowledged"),
    ])
    orch, http = _make_orchestrator(backend, mode=MODE_PROPOSE)
    result = orch.run_one_iteration("observe")
    assert result.outcome_counts.get(CATEGORY_LOCAL_REJECTION) == 1
    assert result.outcome_counts.get(OUTCOME_OK, 0) == 0
    assert result.proposals_created == []
    assert http.calls == []


_RECEIPT_SCHEMA_KEYS = {
    "schema", "stopped_because", "turns", "tool_calls_executed",
    "outcome_counts", "proposals_created", "commits_applied",
    "usage_total", "truncated",
}


class _StrBoom:
    """An object whose __str__/__repr__ raise — must never be invoked by the
    receipt builder (allowlisting discards it without stringifying)."""
    def __str__(self):  # pragma: no cover - must not be called
        raise RuntimeError("__str__ must not be invoked")
    def __repr__(self):  # pragma: no cover
        raise RuntimeError("__repr__ must not be invoked")
    def __hash__(self):
        return 7
    def __eq__(self, other):
        return False


def _adversarial_iteration_result() -> IterationResult:
    return IterationResult(
        stopped_because="sk-SECRET_" + "X" * 300_000,        # secret-looking, huge, unknown
        turns=10 ** 10000,                                   # absurd magnitude
        tool_calls_executed=-9,                              # negative
        proposals_created=["prop-deadbeef", "sk-SECRET_TOKEN", "prop-ABCDEF01",
                           "prop-abc", "y" * 400, None, _StrBoom(),
                           "prop-0123abcd"],                 # canonical + secret + malformed + non-str
        commits_applied=["prop-0123abcd", 42, "commit_9"],
        outcome_counts={"K" * 20_000: 1, "ok": 3, "weird" * 100: 2,    # huge/unknown keys
                        1: 9, "1": 11, "local_rejection": -3,          # colliding + negative
                        "handler_exception": _StrBoom(), True: 1},     # __str__-boom value, bool key
        usage_total={"U" * 20_000: 999, "input_tokens": 10 ** 10000,   # huge key + huge value
                     "output_tokens": [1, 2, 3], _StrBoom(): 4},       # list value + boom key
    )


def test_receipt_bounded_against_adversarial_result():
    """A manually/adversarially-constructed IterationResult cannot inflate the
    receipt, is deterministic under PLAIN json.dumps (no default=str), flags
    truncation, and survives with only allowlisted, JSON-primitive values."""
    result = _adversarial_iteration_result()
    receipt = build_audit_receipt(result)
    blob = json.dumps(receipt, sort_keys=True)          # plain dumps — no default=str
    assert blob == json.dumps(build_audit_receipt(result), sort_keys=True)  # deterministic
    assert len(blob.encode("utf-8")) <= MAX_RECEIPT_BYTES
    assert receipt["truncated"] is True
    assert set(receipt.keys()) == _RECEIPT_SCHEMA_KEYS
    # Magnitude-clamped, non-negative ints.
    assert receipt["turns"] == 10 ** 12
    assert receipt["tool_calls_executed"] == 0
    # Stop reason: unknown token, secret text gone entirely (incl. prefixes).
    assert receipt["stopped_because"] == "unknown"
    assert "SECRET" not in blob and "sk-" not in blob
    # Outcome/usage: only allowlisted keys, all non-negative ints.
    assert set(receipt["outcome_counts"]) <= {
        "ok", "unknown_tool", "handler_exception", "transport_failure",
        "http_rejection", "budget_rejection", "proposal_limit", "local_rejection"}
    assert set(receipt["usage_total"]) <= {"input_tokens", "output_tokens"}
    assert all(isinstance(v, int) and v >= 0 for v in receipt["outcome_counts"].values())
    assert all(isinstance(v, int) and v >= 0 for v in receipt["usage_total"].values())
    # Specific coercions.
    assert receipt["outcome_counts"]["ok"] == 3                       # valid small int kept
    assert receipt["usage_total"]["input_tokens"] == 10 ** 12         # huge value clamped
    assert receipt["outcome_counts"].get("local_rejection", 0) == 0   # negative → 0
    assert receipt["outcome_counts"]["handler_exception"] == 0        # boom value → 0
    assert receipt["usage_total"]["output_tokens"] == 0              # list value → 0
    # Unknown/secret keys removed entirely.
    for banned in ("K" * 20_000, "weird", "U" * 20_000, "unknown_junk"):
        assert banned not in blob
    # Ids: only canonical prop-<8 hex> survive; secret/malformed/non-str omitted.
    assert receipt["proposals_created"] == ["prop-deadbeef", "prop-0123abcd"]
    assert receipt["commits_applied"] == ["prop-0123abcd"]
    assert "SECRET_TOKEN" not in blob  # alphabet-valid secret-looking id dropped


def test_receipt_colliding_int_and_str_keys_both_discarded():
    """Integer 1 and string '1' are both outside the outcome allowlist and are
    discarded — no coercion, no key collision, no exception."""
    result = IterationResult(stopped_because="end_turn", turns=1, tool_calls_executed=0,
                             outcome_counts={1: 5, "1": 7})
    receipt = build_audit_receipt(result)
    assert receipt["outcome_counts"] == {}
    assert receipt["truncated"] is True
    # Deterministic plain serialization round-trips.
    assert json.dumps(receipt, sort_keys=True) == json.dumps(build_audit_receipt(result), sort_keys=True)


@pytest.mark.parametrize("count", [
    pytest.param(True, id="bool_true"),
    pytest.param(False, id="bool_false"),
    pytest.param(-1, id="negative"),
    pytest.param(1.5, id="float"),
    pytest.param("3", id="str"),
    pytest.param(None, id="none"),
    # Explicit id: a 10001-digit int must not be stringified for the test id
    # (Python's int->str 4300-digit limit) — the builder clamps it by value.
    pytest.param(10 ** 10000, id="ten_pow_10000"),
])
def test_receipt_rejects_non_uint_counts(count):
    """bool / negative / non-integer / oversized counts are normalized to a
    bounded non-negative int without raising, and flag truncation."""
    result = IterationResult(stopped_because="end_turn", turns=count, tool_calls_executed=0,
                             outcome_counts={"ok": count}, usage_total={"input_tokens": count})
    receipt = build_audit_receipt(result)
    assert isinstance(receipt["turns"], int) and receipt["turns"] >= 0
    assert receipt["turns"] <= 10 ** 12
    assert isinstance(receipt["outcome_counts"]["ok"], int) and receipt["outcome_counts"]["ok"] >= 0
    assert isinstance(receipt["usage_total"]["input_tokens"], int)
    assert receipt["truncated"] is True
    assert len(json.dumps(receipt, sort_keys=True).encode("utf-8")) <= MAX_RECEIPT_BYTES


def test_receipt_str_boom_object_never_stringified():
    """Objects whose __str__ raises appear as ids, keys, and values; the builder
    discards them without invoking __str__ and never raises."""
    result = IterationResult(
        stopped_because=_StrBoom(), turns=1, tool_calls_executed=1,
        proposals_created=[_StrBoom(), "prop-0000000a"],
        outcome_counts={"ok": _StrBoom()},
        usage_total={"input_tokens": _StrBoom()},
    )
    receipt = build_audit_receipt(result)   # must not raise
    assert receipt["stopped_because"] == "unknown"
    assert receipt["proposals_created"] == ["prop-0000000a"]
    assert receipt["outcome_counts"]["ok"] == 0
    assert receipt["usage_total"]["input_tokens"] == 0
    assert len(json.dumps(receipt, sort_keys=True).encode("utf-8")) <= MAX_RECEIPT_BYTES


def test_receipt_keeps_only_canonical_proposal_ids():
    """Only canonical production ids (``prop-`` + 8 lowercase hex) survive.
    Secret-looking but alphabet-valid strings, arbitrary text, uppercase,
    overlong, short, non-hex, and non-string entries are all dropped —
    including their prefixes."""
    result = IterationResult(
        stopped_because="end_turn", turns=1, tool_calls_executed=1,
        proposals_created=[
            "prop-deadbeef", "prop-0123abcd",   # canonical → survive
            "sk-SECRET_TOKEN",                  # secret-looking, alphabet-valid → drop
            "arbitrary-valid-text",             # arbitrary → drop
            "prop-DEADBEEF",                    # uppercase hex → drop
            "prop-deadbeef00",                  # overlong → drop
            "prop-abc",                         # too short → drop
            "prop-ghijklmn",                    # non-hex letters → drop
            None, 42,                           # non-string → drop
        ],
        commits_applied=["prop-0123abcd"],
    )
    receipt = build_audit_receipt(result)
    assert receipt["proposals_created"] == ["prop-deadbeef", "prop-0123abcd"]
    assert receipt["commits_applied"] == ["prop-0123abcd"]
    blob = json.dumps(receipt, sort_keys=True)
    for banned in ("SECRET", "sk-", "arbitrary", "DEADBEEF", "ghij"):
        assert banned not in blob
    assert receipt["truncated"] is True


class _HostileList(list):
    def __iter__(self):  # pragma: no cover - must not be invoked
        raise RuntimeError("__iter__ must not be invoked")


class _HostileDict(dict):
    def items(self):  # pragma: no cover
        raise RuntimeError("items must not be invoked")

    def __iter__(self):  # pragma: no cover
        raise RuntimeError("__iter__ must not be invoked")


def test_receipt_rejects_hostile_container_subclasses():
    """A list/dict subclass whose iteration hooks raise is rejected by exact
    type BEFORE any iteration — the receipt normalizes to empty with
    truncated=True and never invokes the hostile __iter__/items."""
    hostile_ids = _HostileList(["prop-deadbeef"])
    hostile_map = _HostileDict({"ok": 1})
    result = IterationResult(
        stopped_because="end_turn", turns=1, tool_calls_executed=1,
        proposals_created=hostile_ids, commits_applied=hostile_ids,
        outcome_counts=hostile_map, usage_total=hostile_map,
    )
    receipt = build_audit_receipt(result)   # must not raise
    assert receipt["proposals_created"] == []
    assert receipt["commits_applied"] == []
    assert receipt["outcome_counts"] == {}
    assert receipt["usage_total"] == {}
    assert receipt["truncated"] is True


def test_receipt_normal_production_result_not_truncated():
    """A realistic production IterationResult — canonical ids, known outcome
    categories, token usage — passes through untouched with truncated=False and
    serializes deterministically with plain json.dumps."""
    result = IterationResult(
        stopped_because="end_turn", turns=2, tool_calls_executed=3,
        proposals_created=["prop-deadbeef"],
        commits_applied=[],
        outcome_counts={"ok": 3, "local_rejection": 1},
        usage_total={"input_tokens": 120, "output_tokens": 340},
    )
    receipt = build_audit_receipt(result)
    assert receipt["truncated"] is False
    assert receipt["proposals_created"] == ["prop-deadbeef"]
    assert receipt["outcome_counts"] == {"local_rejection": 1, "ok": 3}
    assert receipt["usage_total"] == {"input_tokens": 120, "output_tokens": 340}
    assert json.dumps(receipt, sort_keys=True) == json.dumps(
        build_audit_receipt(result), sort_keys=True)


def test_receipt_minimal_fallback_is_within_limit(monkeypatch):
    """Exercise the fixed minimal fallback directly: with the cap forced just
    above the minimal receipt but below any populated one, the trim loop falls
    through to the fixed minimal fallback, which is itself within the limit."""
    import scripts.orchestrator as orch_mod
    minimal = {"schema": "leanctx-orchestrator-v1",
               "stopped_because": "unknown", "truncated": True}
    minimal_size = len(json.dumps(minimal, sort_keys=True).encode("utf-8"))
    monkeypatch.setattr(orch_mod, "MAX_RECEIPT_BYTES", minimal_size + 5)
    result = IterationResult(
        stopped_because="end_turn",
        turns=1, tool_calls_executed=1,
        proposals_created=[f"prop-{i:08x}" for i in range(500)],  # canonical ids
        outcome_counts={"ok": 500},
        usage_total={"input_tokens": 999_999},
    )
    receipt = build_audit_receipt(result)
    assert receipt == minimal
    assert receipt["truncated"] is True
    assert len(json.dumps(receipt, sort_keys=True).encode("utf-8")) <= minimal_size + 5


def test_no_post_after_budget_exhaustion():
    """Once the total budget is spent, no further HTTP POST is attempted."""
    from scripts.agent_backends import AgentResponse, ToolUseBlock
    blocks = [ToolUseBlock(id=f"p_{i}", name="propose_tuning",
                           input={"params": {"signal_interval": 12}, "justification": "j"})
              for i in range(3)]
    resp = AgentResponse.from_content(blocks, stop_reason="tool_use",
                                      usage={"input_tokens": 1, "output_tokens": 1})
    backend = MockBackend(responses=[resp, _text_response("done")])
    http = FakeHttp()
    client = OrchestratorClient("http://test:8080", http_do=http)
    http.set("POST", "/api/tuning/propose", 200, {"proposal_id": "prop-1", "status": "accepted"})
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        mode=MODE_PROPOSE, max_tool_depth=4, max_total_tool_calls=1)
    result = orch.run_one_iteration("go")
    assert result.tool_calls_executed == 1
    assert len([c for c in http.calls if c["method"] == "POST"]) == 1


def test_numeric_limits_are_validated():
    backend = MockBackend(responses=[_text_response("x")])
    client = OrchestratorClient("http://test:8080", http_do=FakeHttp())
    for bad in (0, -1, MAX_LIMIT_CEILING + 1, True):
        with pytest.raises(ValueError):
            Orchestrator(backend=backend, client=client, system_prompt="s",
                         max_total_tool_calls=bad)
    with pytest.raises(ValueError):
        Orchestrator(backend=backend, client=client, system_prompt="s", max_tool_depth=0)


def test_orchestrator_has_no_reverse_dependency_on_observer_or_engine():
    """The legacy orchestrator must not import the offline detector, observer,
    engine, or physics modules — the quarantine is one-directional."""
    import inspect
    import scripts.orchestrator as orch_mod
    src = inspect.getsource(orch_mod)
    for banned in ("continuous_evolution_ca", "nextness_observer",
                   "nextness_calibration", "swarm_hunter"):
        assert banned not in src


# -- ToolRouter.execute() message totality (sites 380/387/393) ----------------
#
# The result-message sites inside execute()'s defensive try must never run
# code belonging to a hostile handler return or exception. Contract:
#   * a handler result is accepted only when it is EXACTLY a builtin dict —
#     any subclass or other object is refused without reading its __class__,
#     its type name, or calling any of its methods;
#   * both failure messages are fixed strings — the caught exception, its
#     class, and its arguments are never stringified, represented, formatted,
#     measured, or sliced;
#   * ``_status`` is honored only as an EXACT builtin int, so a non-standard
#     value is never queried for its class.
# Every hostile hook below RECORDS instead of raising, so "not consulted" is
# proven by an empty call log rather than inferred from the absence of a crash.

_FIXED_HANDLER_MESSAGE = "tool handler failed"
_FIXED_TRANSPORT_MESSAGE = "URLError"


def _census_router(handler) -> ToolRouter:
    """A router whose get_medusa_census handler is replaced by `handler`."""
    client, _ = _client_with_fake()
    router = ToolRouter(client)
    router._handlers["get_medusa_census"] = handler
    return router


def test_handler_failure_fields_and_fixed_message():
    """Ordinary handler failure: the payload shape is pinned exactly — stable
    error/category/tool fields plus the fixed message, nothing else."""
    def boom(_args):
        raise ValueError("boom")
    payload, is_error = _census_router(boom).execute("get_medusa_census", {})
    assert is_error is True
    assert payload == {
        "error": "tool_handler_exception",
        "category": CATEGORY_HANDLER_EXCEPTION,
        "tool": "get_medusa_census",
        "message": _FIXED_HANDLER_MESSAGE,
    }


def test_transport_failure_fields_and_fixed_message():
    """Ordinary transport failure: pinned payload with the fixed ``URLError``
    message — byte-identical to what a plain URLError produced here before."""
    def boom(_args):
        raise urllib.error.URLError("network down")
    payload, is_error = _census_router(boom).execute("get_medusa_census", {})
    assert is_error is True
    assert payload == {
        "error": "transport_failure",
        "category": CATEGORY_TRANSPORT_FAILURE,
        "tool": "get_medusa_census",
        "message": _FIXED_TRANSPORT_MESSAGE,
    }


def test_exception_with_hostile_text_conversion_is_never_stringified():
    """An exception whose __str__/__repr__/__format__ record their invocation
    returns normally with the fixed message and an empty call log."""
    calls: list[str] = []

    class _TextTrapError(Exception):
        def __str__(self):
            calls.append("__str__")
            return "trap"
        def __repr__(self):
            calls.append("__repr__")
            return "trap"
        def __format__(self, spec):
            calls.append("__format__")
            return "trap"

    def boom(_args):
        raise _TextTrapError("x")
    payload, is_error = _census_router(boom).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert calls == []


def test_exception_argument_is_never_inspected():
    """An exception carrying an argument with recording text/representation/
    measurement hooks: none of the argument's methods run."""
    calls: list[str] = []

    class _HostileArg:
        def __str__(self):
            calls.append("arg.__str__")
            return "a"
        def __repr__(self):
            calls.append("arg.__repr__")
            return "a"
        def __format__(self, spec):
            calls.append("arg.__format__")
            return "a"
        def __len__(self):
            calls.append("arg.__len__")
            return 0

    def boom(_args):
        raise ValueError(_HostileArg())
    payload, is_error = _census_router(boom).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert calls == []


def test_exception_class_name_is_never_queried():
    """A custom exception class whose metaclass __name__ records access: the
    name is never read and never appears in the result."""
    calls: list[str] = []

    class _NameTrapMeta(type):
        @property
        def __name__(cls):
            calls.append("cls.__name__")
            return "TrappedName"

    class _NameTrapError(Exception, metaclass=_NameTrapMeta):
        pass

    def boom(_args):
        raise _NameTrapError("x")
    payload, is_error = _census_router(boom).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert "TrappedName" not in json.dumps(payload, sort_keys=True)
    assert calls == []


def test_url_error_subclass_gets_fixed_transport_result():
    """A URLError subclass with recording class-name and text hooks yields the
    fixed transport result with an empty call log: its class name and text
    hooks are never consulted. (Except-clause matching may consult a metaclass
    ``__subclasscheck__``, but its result cannot change the classification and
    a raise inside it stays bounded — see the review notes in the PR.)"""
    calls: list[str] = []

    class _URLNameTrapMeta(type):
        @property
        def __name__(cls):
            calls.append("cls.__name__")
            return "NotURLError"

    class _TrapURLError(urllib.error.URLError, metaclass=_URLNameTrapMeta):
        def __str__(self):
            calls.append("__str__")
            return "trap"
        def __repr__(self):
            calls.append("__repr__")
            return "trap"

    def boom(_args):
        raise _TrapURLError("no route")
    payload, is_error = _census_router(boom).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == CATEGORY_TRANSPORT_FAILURE
    assert payload["message"] == _FIXED_TRANSPORT_MESSAGE
    assert "NotURLError" not in json.dumps(payload, sort_keys=True)
    assert calls == []


def test_non_dict_return_with_hostile_class_is_refused_unconsulted():
    """A non-dict return whose __class__ property records access (and lies,
    claiming dict) is refused by exact type identity — the property never runs."""
    calls: list[str] = []

    class _ClassTrapReturn:
        @property
        def __class__(self):
            calls.append("__class__")
            return dict

    payload, is_error = _census_router(
        lambda _a: _ClassTrapReturn()).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == CATEGORY_HANDLER_EXCEPTION
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert calls == []


def test_non_dict_return_type_name_is_never_read():
    """A non-dict return whose metaclass __name__ records access and yields an
    oversized name: refused with the fixed message, name never read."""
    calls: list[str] = []

    class _NameTrapReturnMeta(type):
        @property
        def __name__(cls):
            calls.append("type.__name__")
            return "N" * 4096

    class _NameTrapReturn(metaclass=_NameTrapReturnMeta):
        pass

    payload, is_error = _census_router(
        lambda _a: _NameTrapReturn()).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert "N" * 64 not in json.dumps(payload, sort_keys=True)
    assert calls == []


def test_dict_subclass_return_is_refused_before_its_methods_run():
    """A dict subclass with recording get/items/keys/__iter__ hooks is refused
    by exact type before any of those methods is called."""
    calls: list[str] = []

    class _HookedDict(dict):
        def get(self, key, default=None):
            calls.append("get")
            return dict.get(self, key, default)
        def items(self):
            calls.append("items")
            return dict.items(self)
        def keys(self):
            calls.append("keys")
            return dict.keys(self)
        def __iter__(self):
            calls.append("__iter__")
            return dict.__iter__(self)

    payload, is_error = _census_router(
        lambda _a: _HookedDict(generation=1)).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == CATEGORY_HANDLER_EXCEPTION
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert calls == []


def test_huge_exception_payloads_never_enlarge_the_fixed_results():
    """Very large exception arguments (handler and transport lanes) neither
    appear in the result nor enlarge its fixed message."""
    big = "Z" * 1_000_000

    def boom_handler(_args):
        raise ValueError(big)
    payload, is_error = _census_router(boom_handler).execute("get_medusa_census", {})
    encoded = json.dumps(payload, sort_keys=True)
    assert is_error is True
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert big[:64] not in encoded
    assert len(encoded.encode("utf-8")) < 512

    def boom_transport(_args):
        raise urllib.error.URLError(big)
    payload, is_error = _census_router(boom_transport).execute("get_medusa_census", {})
    encoded = json.dumps(payload, sort_keys=True)
    assert is_error is True
    assert payload["message"] == _FIXED_TRANSPORT_MESSAGE
    assert big[:64] not in encoded
    assert len(encoded.encode("utf-8")) < 512


def test_exact_dict_nonstandard_status_value_class_never_accessed():
    """An exact dict whose _status value records __class__/comparison access
    passes through as an ordinary success with an empty call log."""
    calls: list[str] = []

    class _StatusTrap:
        @property
        def __class__(self):
            calls.append("__class__")
            return int
        def __ge__(self, other):
            calls.append("__ge__")
            return True
        def __gt__(self, other):
            calls.append("__gt__")
            return True

    trap_payload = {"_status": _StatusTrap(), "generation": 7}
    payload, is_error = _census_router(
        lambda _a: trap_payload).execute("get_medusa_census", {})
    assert is_error is False
    assert payload is trap_payload
    assert calls == []


def test_status_exactness_pins():
    """Exact-int statuses keep their existing classification; bool stays a
    non-rejection; an int SUBCLASS 500 is now an ordinary success BY DESIGN
    (the intentional compatibility change: non-standard values are never
    queried for their class, so they cannot classify as HTTP rejections)."""
    payload, is_error = _census_router(
        lambda _a: {"_status": 500, "error": "server_broke"}).execute(
        "get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == "http_rejection"

    payload, is_error = _census_router(
        lambda _a: {"_status": True}).execute("get_medusa_census", {})
    assert is_error is False

    class _Code(int):
        pass
    payload, is_error = _census_router(
        lambda _a: {"_status": _Code(500)}).execute("get_medusa_census", {})
    assert is_error is False


def test_iteration_completes_on_hostile_handler_exception():
    """run_one_iteration completes when the transport raises a text-trapping
    exception: correct category, fixed LLM-visible message, bounded valid
    receipt, empty call log."""
    calls: list[str] = []

    class _TextTrapError(Exception):
        def __str__(self):
            calls.append("__str__")
            return "trap-text"
        def __repr__(self):
            calls.append("__repr__")
            return "trap-text"

    def boom_http(method, url, *, json=None, timeout=5.0):
        raise _TextTrapError("x")

    backend = MockBackend(responses=[
        _tool_use_response("tu_h", "get_medusa_census", {}),
        _text_response("done"),
    ])
    client = OrchestratorClient("http://test:8080", http_do=boom_http)
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        max_tool_depth=4)
    result = orch.run_one_iteration("go")
    assert result.stopped_because == "end_turn"
    assert result.outcome_counts.get(CATEGORY_HANDLER_EXCEPTION) == 1
    block = backend.calls[1].messages[-1].content[0]
    assert isinstance(block, ToolResultBlock)
    assert block.is_error is True
    assert json.loads(block.content)["message"] == _FIXED_HANDLER_MESSAGE
    assert calls == []
    receipt_json = json.dumps(build_audit_receipt(result), sort_keys=True)
    assert len(receipt_json.encode("utf-8")) <= MAX_RECEIPT_BYTES
    assert "trap-text" not in receipt_json


def test_iteration_completes_on_hostile_transport_exception():
    """run_one_iteration completes when the transport raises a hostile URLError
    subclass: transport_failure category, fixed message, bounded valid receipt."""
    calls: list[str] = []

    class _TrapURLError(urllib.error.URLError):
        def __str__(self):
            calls.append("__str__")
            return "trap-url"
        def __repr__(self):
            calls.append("__repr__")
            return "trap-url"

    def boom_http(method, url, *, json=None, timeout=5.0):
        raise _TrapURLError("no route")

    backend = MockBackend(responses=[
        _tool_use_response("tu_t", "get_medusa_census", {}),
        _text_response("done"),
    ])
    client = OrchestratorClient("http://test:8080", http_do=boom_http)
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        max_tool_depth=4)
    result = orch.run_one_iteration("go")
    assert result.stopped_because == "end_turn"
    assert result.outcome_counts.get(CATEGORY_TRANSPORT_FAILURE) == 1
    block = backend.calls[1].messages[-1].content[0]
    assert json.loads(block.content)["message"] == _FIXED_TRANSPORT_MESSAGE
    assert calls == []
    receipt_json = json.dumps(build_audit_receipt(result), sort_keys=True)
    assert len(receipt_json.encode("utf-8")) <= MAX_RECEIPT_BYTES
    assert "trap-url" not in receipt_json


def test_handler_exception_text_never_reaches_the_model():
    """Sensitive exception text stays out of the LLM-visible tool result, not
    just out of the audit receipt: the message is the fixed string."""
    secret = "SECRET_API_KEY_sk-abc123"

    def boom_http(method, url, *, json=None, timeout=5.0):
        raise ValueError(secret)

    backend = MockBackend(responses=[
        _tool_use_response("tu_s", "get_medusa_census", {}),
        _text_response("done"),
    ])
    client = OrchestratorClient("http://test:8080", http_do=boom_http)
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        max_tool_depth=4)
    result = orch.run_one_iteration("go")
    assert result.outcome_counts.get(CATEGORY_HANDLER_EXCEPTION) == 1
    block = backend.calls[1].messages[-1].content[0]
    assert secret not in block.content
    assert json.loads(block.content)["message"] == _FIXED_HANDLER_MESSAGE


def test_local_rejection_flag_bool_is_bounded():
    """The one unavoidable in-try method execution: bool() on an exact dict's
    _local_rejection value. A raising __bool__ stays bounded to the fixed
    handler-failure result — it can never crash the iteration loop."""
    class _BoolBomb:
        def __bool__(self):
            raise RuntimeError("hostile __bool__")

    payload, is_error = _census_router(
        lambda _a: {"_local_rejection": _BoolBomb()}).execute(
        "get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == CATEGORY_HANDLER_EXCEPTION
    assert payload["message"] == _FIXED_HANDLER_MESSAGE
    assert "hostile __bool__" not in json.dumps(payload, sort_keys=True)


def test_local_rejection_cleanup_raising_key_comparison_is_bounded():
    """The remaining gap (thread-independent reproduction): an exact builtin
    dict marked as a local rejection carries a custom key whose comparison
    raises during the cleanup comprehension's ``k != "_local_rejection"``.
    The raise comes from ``__ne__`` — which only the cleanup's ``!=`` uses;
    dict lookups use ``__eq__``, so the in-try ``.get`` cannot trigger it —
    making the reproduction deterministic. Post-processing must be inside the
    defensive try: the result is the bounded fixed handler failure, never a
    crash of execute()."""
    calls: list[str] = []

    class _NeBombKey:
        def __hash__(self):
            calls.append("hash")
            return 12345
        def __eq__(self, other):
            calls.append("eq")
            return False
        def __ne__(self, other):
            calls.append("ne")
            raise RuntimeError("hostile __ne__ during cleanup")
        def __str__(self):  # pragma: no cover - must not be called
            calls.append("str")
            return "k"
        def __repr__(self):  # pragma: no cover - must not be called
            calls.append("repr")
            return "k"

    def handler(_args):
        return {_NeBombKey(): "x", "_local_rejection": True}

    payload, is_error = _census_router(handler).execute("get_medusa_census", {})
    assert is_error is True
    assert payload == {
        "error": "tool_handler_exception",
        "category": CATEGORY_HANDLER_EXCEPTION,
        "tool": "get_medusa_census",
        "message": _FIXED_HANDLER_MESSAGE,
    }
    # Exactly one comparison attempt raised; text hooks never ran. (__eq__ may
    # run 0..n times from bucket-dependent dict probes; it is benign here.)
    assert calls.count("ne") == 1
    assert "str" not in calls and "repr" not in calls
    assert "hostile __ne__" not in json.dumps(payload, sort_keys=True)


def test_local_rejection_category_insertion_with_colliding_key():
    """Local-rejection cleanup with a custom key hash-colliding with
    "category" (recording ``__eq__`` honestly returning False): the category
    default is still inserted, the colliding key and its value survive, and no
    text hook was consulted. The recorded ``__eq__`` calls include both the
    cleanup's ``!=`` (default ``__ne__`` falls back to ``__eq__``) and the
    ``setdefault`` probe — the latter is guaranteed to run by the forced
    full-hash collision, though the count alone does not isolate it."""
    calls: list[str] = []

    class _CollidingKey:
        def __hash__(self):
            calls.append("hash")
            return hash("category")
        def __eq__(self, other):
            calls.append("eq")
            return False
        def __str__(self):  # pragma: no cover - must not be called
            calls.append("str")
            return "k"
        def __repr__(self):  # pragma: no cover - must not be called
            calls.append("repr")
            return "k"

    colliding = _CollidingKey()

    def handler(_args):
        return {"_local_rejection": True, "error": "bad_request",
                colliding: "kept-value"}

    payload, is_error = _census_router(handler).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == CATEGORY_LOCAL_REJECTION
    assert payload["error"] == "bad_request"
    assert payload[colliding] == "kept-value"
    assert "_local_rejection" not in payload
    assert calls.count("eq") >= 1  # the collision comparison genuinely ran
    assert "str" not in calls and "repr" not in calls


def test_http_rejection_construction_with_nonstandard_contents():
    """HTTP-rejection rebuild with a custom key hash-colliding with
    "category" (recording, honestly-False ``__eq__``): the category is still
    added, all contents survive, and no text hook runs. A second variant whose
    ``__eq__`` raises during the rebuild is bounded to the fixed handler
    failure — it can no longer escape execute()."""
    calls: list[str] = []

    class _CollidingKey:
        def __hash__(self):
            calls.append("hash")
            return hash("category")
        def __eq__(self, other):
            calls.append("eq")
            return False
        def __str__(self):  # pragma: no cover - must not be called
            calls.append("str")
            return "k"
        def __repr__(self):  # pragma: no cover - must not be called
            calls.append("repr")
            return "k"

    colliding = _CollidingKey()

    def handler(_args):
        return {"_status": 502, "error": "bad_gateway", colliding: "kept"}

    payload, is_error = _census_router(handler).execute("get_medusa_census", {})
    assert is_error is True
    assert payload["category"] == "http_rejection"
    assert payload["_status"] == 502
    assert payload["error"] == "bad_gateway"
    assert payload[colliding] == "kept"
    assert calls.count("eq") >= 1
    assert "str" not in calls and "repr" not in calls

    raising_calls: list[str] = []

    class _EqBombKey:
        def __hash__(self):
            raising_calls.append("hash")
            return hash("category")
        def __eq__(self, other):
            raising_calls.append("eq")
            raise RuntimeError("hostile __eq__ during rebuild")

    def raising_handler(_args):
        return {"_status": 502, _EqBombKey(): "x"}

    payload, is_error = _census_router(raising_handler).execute(
        "get_medusa_census", {})
    assert is_error is True
    assert payload == {
        "error": "tool_handler_exception",
        "category": CATEGORY_HANDLER_EXCEPTION,
        "tool": "get_medusa_census",
        "message": _FIXED_HANDLER_MESSAGE,
    }
    assert raising_calls.count("eq") == 1
    assert "hostile __eq__" not in json.dumps(payload, sort_keys=True)


def test_status_collision_on_local_rejection_stays_bounded():
    """Review-caught regression pin: a local-rejection exact dict carrying a
    key that hash-collides with "_status" and raises from ``__eq__`` (benign
    ``__ne__``). The eager ``_status`` lookup — preserved in its
    pre-relocation position before the local-rejection branch — hits the
    collision inside the try, so the result is the bounded fixed handler
    failure; the live hostile key can never survive into a returned payload.
    The equal-full-hash probe makes the single ``__eq__`` call deterministic."""
    calls: list[str] = []

    class _StatusCollideBomb:
        def __hash__(self):
            calls.append("hash")
            return hash("_status")
        def __eq__(self, other):
            calls.append("eq")
            raise RuntimeError("hostile __eq__ vs _status")
        def __ne__(self, other):
            calls.append("ne")
            return True

    def handler(_args):
        return {_StatusCollideBomb(): "v", "_local_rejection": True,
                "error": "x"}

    payload, is_error = _census_router(handler).execute("get_medusa_census", {})
    assert is_error is True
    assert payload == {
        "error": "tool_handler_exception",
        "category": CATEGORY_HANDLER_EXCEPTION,
        "tool": "get_medusa_census",
        "message": _FIXED_HANDLER_MESSAGE,
    }
    assert calls.count("eq") == 1
    assert calls.count("ne") == 0
    assert "hostile __eq__" not in json.dumps(payload, sort_keys=True)

    backend = MockBackend(responses=[
        _tool_use_response("tu_sc", "get_medusa_census", {}),
        _text_response("done"),
    ])
    orch, _http = _make_orchestrator(backend)
    orch.router._handlers["get_medusa_census"] = handler
    result = orch.run_one_iteration("go")
    assert result.stopped_because == "end_turn"
    assert result.outcome_counts.get(CATEGORY_HANDLER_EXCEPTION) == 1


def test_ordinary_postprocessing_results_byte_identical():
    """Ordinary local rejection, HTTP rejection, and success flows through the
    relocated post-processing, pinned by exact dict equality against fully
    literal expected dicts (and by object identity for the success flow —
    stronger than byte equality: the payload is passed through unmodified)."""
    payload, is_error = _census_router(
        lambda _a: {"_local_rejection": True, "error": "bad_request",
                    "message": "justification is required"}).execute(
        "get_medusa_census", {})
    assert is_error is True
    assert payload == {"error": "bad_request", "category": "local_rejection",
                       "message": "justification is required"}

    payload, is_error = _census_router(
        lambda _a: {"_status": 500, "error": "server_broke"}).execute(
        "get_medusa_census", {})
    assert is_error is True
    assert payload == {"_status": 500, "error": "server_broke",
                       "category": "http_rejection"}

    success = {"generation": 41, "counts": {"VOID": 9}}
    payload, is_error = _census_router(lambda _a: success).execute(
        "get_medusa_census", {})
    assert is_error is False
    assert payload is success
    assert payload == {"generation": 41, "counts": {"VOID": 9}}


def test_iteration_completes_on_hostile_local_rejection_cleanup():
    """run_one_iteration for the newly covered path: a hostile local-rejection
    payload whose cleanup comparison raises completes the iteration, records
    handler_exception (the bounded conversion), keeps the fixed message in the
    LLM-visible result, and yields a valid bounded receipt."""
    calls: list[str] = []

    class _NeBombKey:
        def __hash__(self):
            return 12345
        def __eq__(self, other):
            return False
        def __ne__(self, other):
            calls.append("ne")
            raise RuntimeError("hostile __ne__ during cleanup")

    backend = MockBackend(responses=[
        _tool_use_response("tu_lr", "get_medusa_census", {}),
        _text_response("done"),
    ])
    orch, _http = _make_orchestrator(backend)
    orch.router._handlers["get_medusa_census"] = (
        lambda _a: {_NeBombKey(): "x", "_local_rejection": True})
    result = orch.run_one_iteration("go")
    assert result.stopped_because == "end_turn"
    assert result.outcome_counts.get(CATEGORY_HANDLER_EXCEPTION) == 1
    assert result.outcome_counts.get(CATEGORY_LOCAL_REJECTION, 0) == 0
    block = backend.calls[1].messages[-1].content[0]
    assert block.is_error is True
    assert json.loads(block.content)["message"] == _FIXED_HANDLER_MESSAGE
    assert calls.count("ne") == 1
    receipt_json = json.dumps(build_audit_receipt(result), sort_keys=True)
    assert len(receipt_json.encode("utf-8")) <= MAX_RECEIPT_BYTES
    assert "hostile __ne__" not in receipt_json


def test_execute_source_fence_no_exception_formatting():
    """Source fence: execute() contains no isinstance and no exception or
    type-name formatting — refusals decide by exact type identity alone.
    The scan runs over an ast round-trip with the docstring dropped, so only
    executable code (no comments, no docstring) is fenced."""
    import ast
    import inspect
    import textwrap
    src = textwrap.dedent(inspect.getsource(ToolRouter.execute))
    fn = ast.parse(src).body[0]
    assert isinstance(fn, ast.FunctionDef)
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body = fn.body[1:]
    body = ast.unparse(fn)
    for banned in ("type(e).__name__", "type(payload).__name__", "{e}",
                   "str(e", "repr(", "isinstance("):
        assert banned not in body


# -- result shaping: bounded, deterministic tool-result lane ------------------
#
# This section pins the result-shaping contract:
#   * Unknown-tool handling: a name is looked up only when it is exactly a
#     builtin str; the lookup runs inside the protected block; every refusal
#     is the fixed, name-free message below. No conversion, hashing, equality,
#     formatting, length, or truth method of a refused name is ever requested.
#   * Outcome recording: no str() coercion. An error result's category
#     survives only as an exact builtin str drawn from the known error
#     categories ("ok" excluded); everything else records handler_exception.
#     Success records only "ok". No arbitrary value can mint an
#     outcome_counts key.
#   * Reserved response markers: "_status" and "_local_rejection" are internal
#     router vocabulary. They are stripped from every dict body before
#     classification; on an exact-builtin-int transport status >= 400 the
#     transport status is re-inserted as the authoritative "_status". A body
#     cannot supply, replace, or imitate either marker.
#   * Live proposal/commit ids: collected only as exact builtin str, non-empty,
#     <= 64 chars. The receipt's canonical _ID_RE is deliberately NOT applied
#     to live results ("prop-newid" stays accepted).
#   * Result encoding: a payload is serialized only after validating it as an
#     exact builtin JSON tree (exact dict/list/str/int/finite-float/bool/None,
#     str keys, depth <= 32, items <= 4096, bounded cumulative string size),
#     with plain json.dumps(..., sort_keys=True, allow_nan=False) and a
#     128 KiB ceiling on the encoded bytes. Anything refused is replaced by a
#     fixed structured error block; exactly one handler_exception is recorded,
#     no id is collected, and the iteration continues.
# Hostile hooks below RECORD instead of raising, so "not consulted" is proven
# by an empty call log (same idiom as the fixed-message section above).

_RESULT_UNAVAILABLE_MESSAGE = "tool result unavailable"
_UNKNOWN_TOOL_MESSAGE = "tool not registered"
_MAX_RESULT_BYTES = 128 * 1024
_MAX_RESULT_DEPTH = 32
_MAX_RESULT_ITEMS = 4096
_MAX_LIVE_ID_LEN = 64

_REFUSAL_CONTENT = json.dumps(
    {"error": "tool_result_unavailable", "category": "handler_exception",
     "message": _RESULT_UNAVAILABLE_MESSAGE},
    sort_keys=True,
)


class _SubDict(dict):
    """Well-behaved dict subclass — refused by exact-type gates."""


class _SubList(list):
    """Well-behaved list subclass — refused by exact-type gates."""


class _SubStr(str):
    """Well-behaved str subclass — refused by exact-type gates."""


class _SubInt(int):
    """Well-behaved int subclass — refused by exact-type gates."""


class _SubFloat(float):
    """Well-behaved float subclass — refused by exact-type gates."""


class _StubRouter:
    """Injectable router yielding scripted (payload, is_error) results, so
    run_one_iteration's recording/collection/serialization lanes can be fed
    arbitrary shapes without HTTP scripting."""

    def __init__(self, results):
        self._results = list(results)
        self.calls: list = []

    def execute(self, name, arguments):
        self.calls.append(name)
        return self._results.pop(0)


def _shaping_orchestrator(responses, results, *, mode=MODE_OBSERVE):
    backend = MockBackend(responses=responses)
    client = OrchestratorClient("http://test:8080", http_do=FakeHttp())
    orch = Orchestrator(
        backend=backend,
        client=client,
        system_prompt="s",
        mode=mode,
        router=_StubRouter(results),
        max_tool_depth=4,
    )
    return orch, backend


def _single_result_iteration(result, *, name="get_medusa_census", mode=MODE_OBSERVE):
    """One iteration: a single tool call whose router result is `result`,
    then a closing text turn. Returns (IterationResult, result_blocks)."""
    orch, backend = _shaping_orchestrator(
        [_tool_use_response("tu_r1", name, {}), _text_response("done")],
        [result],
        mode=mode,
    )
    outcome = orch.run_one_iteration("observe")
    blocks = [b for b in backend.calls[-1].messages[-1].content
              if isinstance(b, ToolResultBlock)]
    return outcome, blocks


# -- unknown-tool handling ----------------------------------------------------


def test_unknown_tool_message_is_fixed_and_name_free():
    client, http = _client_with_fake()
    payload, is_error = ToolRouter(client).execute("get_weather", {})
    assert is_error is True
    assert payload == {
        "error": "unknown_tool",
        "category": "unknown_tool",
        "message": _UNKNOWN_TOOL_MESSAGE,
    }
    assert http.calls == []


@pytest.mark.parametrize(
    "name",
    [123, 1.5, True, None, b"get_params", ("get_params",), frozenset({"x"})],
    ids=["int", "float", "bool", "none", "bytes", "tuple", "frozenset"],
)
def test_unknown_tool_non_str_hashable_name_is_refused(name):
    client, http = _client_with_fake()
    payload, is_error = ToolRouter(client).execute(name, {})
    assert is_error is True
    assert payload == {
        "error": "unknown_tool",
        "category": "unknown_tool",
        "message": _UNKNOWN_TOOL_MESSAGE,
    }
    assert http.calls == []


@pytest.mark.parametrize(
    "name",
    [["get_params"], {"n": 1}, {"get_params"}],
    ids=["list", "dict", "set"],
)
def test_unknown_tool_unhashable_name_cannot_crash_execute(name):
    """An unhashable name must be refused by the exact-str gate BEFORE any
    registry lookup could hash it — execute returns the bounded refusal
    instead of letting a TypeError escape the router."""
    client, http = _client_with_fake()
    payload, is_error = ToolRouter(client).execute(name, {})
    assert is_error is True
    assert payload == {
        "error": "unknown_tool",
        "category": "unknown_tool",
        "message": _UNKNOWN_TOOL_MESSAGE,
    }
    assert http.calls == []


def test_unknown_tool_str_subclass_name_refused_without_hooks():
    """A str subclass spelling a REGISTERED name is still refused (the gate is
    exact-type, not isinstance), and none of its hooks is requested."""
    calls: list[str] = []

    class _RecordingName(str):
        def __hash__(self):
            calls.append("__hash__")
            return str.__hash__(self)

        def __eq__(self, other):
            calls.append("__eq__")
            return str.__eq__(self, other)

        def __str__(self):
            calls.append("__str__")
            return str.__str__(self)

        def __format__(self, spec):
            calls.append("__format__")
            return str.__format__(self, spec)

    client, http = _client_with_fake()
    payload, is_error = ToolRouter(client).execute(
        _RecordingName("get_medusa_census"), {})
    assert is_error is True
    assert payload == {
        "error": "unknown_tool",
        "category": "unknown_tool",
        "message": _UNKNOWN_TOOL_MESSAGE,
    }
    assert calls == []
    assert http.calls == []


def test_unknown_tool_hostile_object_name_hooks_not_requested():
    calls: list[str] = []

    class _RecordingNameObject:
        def __hash__(self):
            calls.append("__hash__")
            return 0

        def __eq__(self, other):
            calls.append("__eq__")
            return False

        def __str__(self):
            calls.append("__str__")
            return "n"

        def __repr__(self):
            calls.append("__repr__")
            return "n"

        def __format__(self, spec):
            calls.append("__format__")
            return "n"

        def __len__(self):
            calls.append("__len__")
            return 1

        def __bool__(self):
            calls.append("__bool__")
            return True

    client, http = _client_with_fake()
    payload, is_error = ToolRouter(client).execute(_RecordingNameObject(), {})
    assert is_error is True
    assert payload == {
        "error": "unknown_tool",
        "category": "unknown_tool",
        "message": _UNKNOWN_TOOL_MESSAGE,
    }
    assert calls == []
    assert http.calls == []


def test_registered_tool_exact_str_lookup_unchanged():
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 200, {"generation": 42})
    payload, is_error = ToolRouter(client).execute("get_medusa_census", {})
    assert is_error is False
    assert payload == {"generation": 42}


# -- outcome-category allowlist ----------------------------------------------


def test_error_result_keeps_known_error_category():
    result, _ = _single_result_iteration(
        ({"category": "transport_failure", "error": "x", "message": "m"}, True))
    assert result.outcome_counts == {"transport_failure": 1}


def test_error_result_without_category_records_handler_exception():
    result, _ = _single_result_iteration(({"error": "x"}, True))
    assert result.outcome_counts == {"handler_exception": 1}


def test_error_result_unknown_string_category_records_handler_exception():
    result, _ = _single_result_iteration(
        ({"category": "weird_new_category"}, True))
    assert result.outcome_counts == {"handler_exception": 1}


@pytest.mark.parametrize(
    "category",
    [123, 1.5, True, None, ["local_rejection"], {"c": "ok"}],
    ids=["int", "float", "bool", "none", "list", "dict"],
)
def test_error_result_non_str_category_records_handler_exception(category):
    """JSON-legal but non-str categories are never stringified into keys."""
    result, _ = _single_result_iteration(({"category": category}, True))
    assert result.outcome_counts == {"handler_exception": 1}


def test_error_result_ok_category_is_not_accepted():
    result, _ = _single_result_iteration(({"category": "ok"}, True))
    assert result.outcome_counts == {"handler_exception": 1}
    assert "ok" not in result.outcome_counts


def test_success_records_only_ok_even_with_category_key():
    result, _ = _single_result_iteration(
        ({"category": "http_rejection", "data": 1}, False))
    assert result.outcome_counts == {"ok": 1}


# -- reserved response-marker separation ---------------------------------------


def test_success_body_reserved_markers_are_stripped():
    """A 200 body carrying both reserved markers is an ordinary success once
    they are stripped — it cannot imitate a local rejection or an HTTP error."""
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 200,
             {"_status": 500, "_local_rejection": True, "data": 1})
    payload, is_error = ToolRouter(client).execute("get_medusa_census", {})
    assert is_error is False
    assert payload == {"data": 1}


def test_success_body_preserved_apart_from_reserved_markers():
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 200,
             {"_status": 999, "value": [1, 2], "n": None, "f": 1.5})
    payload, is_error = ToolRouter(client).execute("get_medusa_census", {})
    assert is_error is False
    assert payload == {"value": [1, 2], "n": None, "f": 1.5}


def test_http_error_transport_status_is_authoritative():
    """On a >= 400 transport status, a body-supplied "_status" (and any
    "_local_rejection") is discarded and the actual status is inserted."""
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 503,
             {"_status": 200, "_local_rejection": True, "error": "down"})
    payload, is_error = ToolRouter(client).execute("get_medusa_census", {})
    assert is_error is True
    assert payload == {"error": "down", "_status": 503,
                       "category": "http_rejection"}


def test_http_error_ordinary_body_shape_pinned():
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 404, {"error": "not_found"})
    payload, is_error = ToolRouter(client).execute("get_medusa_census", {})
    assert is_error is True
    assert payload == {"error": "not_found", "_status": 404,
                       "category": "http_rejection"}


@pytest.mark.parametrize("status", [500.0, True], ids=["float", "bool"])
def test_non_exact_int_status_never_classifies_as_http_error(status):
    """Only an exact builtin int >= 400 is an HTTP rejection; other status
    shapes fall through to the success lane with markers stripped."""
    client, http = _client_with_fake()
    http.set("GET", "/api/census", status, {"_status": 500, "x": 1})
    payload, is_error = ToolRouter(client).execute("get_medusa_census", {})
    assert is_error is False
    assert payload == {"x": 1}


def test_genuine_local_rejection_still_flagged_and_marker_free():
    """The router's own local refusals keep working after marker separation,
    and the internal marker never leaks into the payload."""
    client, _ = _client_with_fake()
    router = ToolRouter(client, mode=MODE_PROPOSE)
    payload, is_error = router.execute(
        "propose_tuning", {"params": {}, "justification": "   "})
    assert is_error is True
    assert payload["category"] == CATEGORY_LOCAL_REJECTION
    assert "_local_rejection" not in payload


# -- live proposal/commit id collection ----------------------------------------


def _propose_iteration(propose_body, *, status=200):
    backend = MockBackend(responses=[
        _tool_use_response("tu_p1", "propose_tuning", {
            "params": {"signal_interval": 12},
            "justification": "test",
        }),
        _text_response("done"),
    ])
    http = FakeHttp()
    http.set("POST", "/api/tuning/propose", status, propose_body)
    client = OrchestratorClient("http://test:8080", http_do=http)
    orch = Orchestrator(backend=backend, client=client, system_prompt="s",
                        mode=MODE_PROPOSE, max_tool_depth=4)
    return orch.run_one_iteration("observe")


@pytest.mark.parametrize(
    ("pid", "collected"),
    [
        ("p", True),
        ("a" * 64, True),
        ("a" * 65, False),
        ("", False),
    ],
    ids=["len1", "len64", "len65", "empty"],
)
def test_live_proposal_id_length_boundaries(pid, collected):
    result = _propose_iteration({"proposal_id": pid, "status": "accepted"})
    assert result.outcome_counts == {"ok": 1}
    assert result.proposals_created == ([pid] if collected else [])


@pytest.mark.parametrize(
    "pid",
    [123, 1.5, True, None, ["prop-newid"], {"id": "prop-newid"}],
    ids=["int", "float", "bool", "none", "list", "dict"],
)
def test_live_proposal_id_non_str_json_values_omitted(pid):
    """JSON-legal non-str ids pass result validation but are never collected
    — and never converted into strings."""
    result = _propose_iteration({"proposal_id": pid, "status": "accepted"})
    assert result.outcome_counts == {"ok": 1}
    assert result.proposals_created == []


@pytest.mark.parametrize(
    "pid",
    ["prop-newid", "PROP-UPPER-1234", "x" * 40],
    ids=["prop-newid", "uppercase", "arbitrary40"],
)
def test_live_proposal_id_non_canonical_shapes_stay_accepted(pid):
    """The receipt's canonical _ID_RE must NOT gate live results."""
    result = _propose_iteration({"proposal_id": pid, "status": "accepted"})
    assert result.proposals_created == [pid]


def test_live_proposal_id_str_subclass_body_is_refused_upstream():
    """A str-subclass id makes the whole body fail exact-JSON-tree validation:
    the result is replaced by the fixed refusal block and nothing is
    collected."""
    result = _propose_iteration(
        {"proposal_id": _SubStr("prop-newid"), "status": "accepted"})
    assert result.outcome_counts == {"handler_exception": 1}
    assert result.proposals_created == []


def test_commit_lane_live_id_gate():
    """commit_tuning is never registered on the real router; the collection
    gate is pinned through an injected router. The same exact-str 1..64 bound
    applies, and only status == "committed" collects."""
    long_ok = "c" * 64
    result, _ = _single_result_iteration(
        ({"proposal_id": long_ok, "status": "committed"}, False),
        name="commit_tuning")
    assert result.commits_applied == [long_ok]

    result, _ = _single_result_iteration(
        ({"proposal_id": "c" * 65, "status": "committed"}, False),
        name="commit_tuning")
    assert result.commits_applied == []

    result, _ = _single_result_iteration(
        ({"proposal_id": "c" * 10, "status": "accepted"}, False),
        name="commit_tuning")
    assert result.commits_applied == []


# -- bounded JSON result encoding: validator unit probes ------------------------


def test_safe_result_accepts_plain_tree_byte_identical():
    from scripts.orchestrator import _safe_result_content
    payload = {"b": [1, 2.5, True, None, "s"], "a": {"nested": {"k": "v"}}}
    assert _safe_result_content(payload) == json.dumps(payload, sort_keys=True)


def test_safe_result_depth_boundary_32_in_33_out():
    from scripts.orchestrator import _safe_result_content

    def _nest(n: int) -> dict:
        d: dict = {"leaf": 1}
        for _ in range(n - 1):
            d = {"k": d}
        return d

    assert _safe_result_content(_nest(_MAX_RESULT_DEPTH)) is not None
    assert _safe_result_content(_nest(_MAX_RESULT_DEPTH + 1)) is None


def test_safe_result_item_boundary_4096_in_4097_out():
    from scripts.orchestrator import _safe_result_content
    flat_ok = {f"k{i:05d}": 0 for i in range(_MAX_RESULT_ITEMS)}
    assert _safe_result_content(flat_ok) is not None
    flat_over = {f"k{i:05d}": 0 for i in range(_MAX_RESULT_ITEMS + 1)}
    assert _safe_result_content(flat_over) is None
    # the item budget is cumulative across nested containers
    nested_over = {"a": [0] * 3000, "b": [0] * (_MAX_RESULT_ITEMS - 3000 - 2 + 1)}
    assert _safe_result_content(nested_over) is None


def test_safe_result_cumulative_string_budget():
    from scripts.orchestrator import _safe_result_content
    assert _safe_result_content({"a": "x" * 1000}) is not None
    assert _safe_result_content({"s": "x" * (_MAX_RESULT_BYTES + 1)}) is None
    # split across two values: each under the cap, together over it
    assert _safe_result_content(
        {"a": "x" * 70000, "b": "x" * 70000}) is None


def test_safe_result_final_encoded_size_is_bounded():
    """JSON structural overhead (quotes, colons, commas) can push the encoded
    size past the ceiling even when raw string content is under it — the
    final encoded-byte check must still refuse."""
    from scripts.orchestrator import _safe_result_content
    # 4000 items, raw string content = 4000 * (5 + 27) = 128,000 chars
    # (< 131,072), encoded ≈ 4000 * 38 ≈ 152,000 bytes (> 131,072)
    over = {f"k{i:04d}": "x" * 27 for i in range(4000)}
    assert _safe_result_content(over) is None
    # same shape with short values stays comfortably under both bounds
    under = {f"k{i:04d}": "x" * 10 for i in range(4000)}
    assert _safe_result_content(under) == json.dumps(under, sort_keys=True)


@pytest.mark.parametrize(
    "bad",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "inf", "-inf"],
)
def test_safe_result_refuses_non_finite_floats(bad):
    from scripts.orchestrator import _safe_result_content
    assert _safe_result_content({"v": bad}) is None
    assert _safe_result_content({"v": [1.0, bad]}) is None


@pytest.mark.parametrize(
    "key",
    [1, 1.5, True, None, ("t",), b"k"],
    ids=["int", "float", "bool", "none", "tuple", "bytes"],
)
def test_safe_result_refuses_non_str_keys(key):
    from scripts.orchestrator import _safe_result_content
    assert _safe_result_content({key: "v"}) is None
    assert _safe_result_content({"outer": {key: "v"}}) is None


@pytest.mark.parametrize(
    "value",
    [
        _SubDict({"a": 1}),
        _SubList([1]),
        _SubStr("s"),
        _SubInt(1),
        _SubFloat(1.0),
        b"bytes",
        (1, 2),
        {1, 2},
        frozenset({1}),
        object(),
    ],
    ids=["dict-sub", "list-sub", "str-sub", "int-sub", "float-sub",
         "bytes", "tuple", "set", "frozenset", "object"],
)
def test_safe_result_refuses_subclasses_and_foreign_values(value):
    from scripts.orchestrator import _safe_result_content
    assert _safe_result_content({"v": value}) is None
    assert _safe_result_content({"v": [value]}) is None


def test_safe_result_refuses_str_subclass_keys():
    from scripts.orchestrator import _safe_result_content
    assert _safe_result_content({_SubStr("k"): 1}) is None


def test_safe_result_refuses_cycles():
    from scripts.orchestrator import _safe_result_content
    d: dict = {}
    d["self"] = d
    assert _safe_result_content(d) is None
    inner: list = []
    inner.append(inner)
    assert _safe_result_content({"l": inner}) is None


@pytest.mark.parametrize(
    "root",
    [_SubDict({"a": 1}), ["x"], "s", 1, None],
    ids=["dict-sub", "list", "str", "int", "none"],
)
def test_safe_result_root_must_be_exact_dict(root):
    from scripts.orchestrator import _safe_result_content
    assert _safe_result_content(root) is None


def test_safe_result_hooks_not_requested_on_refused_value():
    """A refused value's conversion, representation, formatting, iteration,
    comparison, length, and truth hooks are never requested — refusal is by
    exact type alone."""
    from scripts.orchestrator import _safe_result_content
    calls: list[str] = []

    class _RecordingValue:
        def __str__(self):
            calls.append("__str__")
            return "v"

        def __repr__(self):
            calls.append("__repr__")
            return "v"

        def __format__(self, spec):
            calls.append("__format__")
            return "v"

        def __bytes__(self):
            calls.append("__bytes__")
            return b"v"

        def __len__(self):
            calls.append("__len__")
            return 1

        def __bool__(self):
            calls.append("__bool__")
            return True

        def __iter__(self):
            calls.append("__iter__")
            return iter(())

        def __int__(self):
            calls.append("__int__")
            return 0

        def __index__(self):
            calls.append("__index__")
            return 0

        def __eq__(self, other):
            calls.append("__eq__")
            return False

        def __lt__(self, other):
            calls.append("__lt__")
            return False

        def keys(self):
            calls.append("keys")
            return []

    assert _safe_result_content({"v": _RecordingValue()}) is None
    assert calls == []


def test_safe_result_hooks_not_requested_on_refused_containers():
    """Refused container subclasses are never iterated, measured, viewed, or
    truth-tested."""
    from scripts.orchestrator import _safe_result_content
    calls: list[str] = []

    class _RecordingDict(dict):
        def keys(self):
            calls.append("keys")
            return dict.keys(self)

        def items(self):
            calls.append("items")
            return dict.items(self)

        def values(self):
            calls.append("values")
            return dict.values(self)

        def __iter__(self):
            calls.append("__iter__")
            return dict.__iter__(self)

        def __len__(self):
            calls.append("__len__")
            return dict.__len__(self)

        def __bool__(self):
            calls.append("__bool__")
            return True

    class _RecordingList(list):
        def __iter__(self):
            calls.append("__iter__")
            return list.__iter__(self)

        def __len__(self):
            calls.append("__len__")
            return list.__len__(self)

        def __bool__(self):
            calls.append("__bool__")
            return True

    assert _safe_result_content({"d": _RecordingDict({"a": 1})}) is None
    assert _safe_result_content({"l": _RecordingList([1])}) is None
    assert calls == []


# -- bounded JSON result encoding: iteration lane -------------------------------


def test_refused_result_is_replaced_by_fixed_block():
    result, blocks = _single_result_iteration(({"bad": {1, 2}}, False))
    assert result.outcome_counts == {"handler_exception": 1}
    assert result.tool_calls_executed == 1
    assert result.stopped_because == "end_turn"  # iteration continued
    assert len(blocks) == 1
    assert blocks[0].is_error is True
    assert blocks[0].content == _REFUSAL_CONTENT


def test_refused_error_result_records_handler_exception_not_its_category():
    """Validation runs BEFORE the category is read: an unserializable error
    payload cannot smuggle its own category into outcome_counts."""
    result, blocks = _single_result_iteration(
        ({"category": "http_rejection", "detail": object()}, True))
    assert result.outcome_counts == {"handler_exception": 1}
    assert "http_rejection" not in result.outcome_counts
    assert blocks[0].content == _REFUSAL_CONTENT
    assert blocks[0].is_error is True


def test_refused_success_result_never_records_ok():
    result, _ = _single_result_iteration(({"v": (1, 2)}, False))
    assert result.outcome_counts == {"handler_exception": 1}
    assert "ok" not in result.outcome_counts


def test_no_default_str_stringification_of_result_values():
    """The #403 residual: json.dumps(default=str) used to execute a foreign
    value's __str__ and feed the text to the model. Now the value's hooks are
    never requested and the fixed refusal block is returned instead."""
    calls: list[str] = []

    class _RecordingWhen:
        def __str__(self):
            calls.append("__str__")
            return "2026-07-22"

        def __repr__(self):
            calls.append("__repr__")
            return "when"

        def __format__(self, spec):
            calls.append("__format__")
            return "2026-07-22"

    result, blocks = _single_result_iteration(
        ({"when": _RecordingWhen()}, False))
    assert result.outcome_counts == {"handler_exception": 1}
    assert blocks[0].content == _REFUSAL_CONTENT
    assert calls == []


def test_non_finite_float_result_never_reaches_the_model():
    """NaN/Infinity used to serialize into the tool result as bare tokens;
    now the payload is refused with the fixed block."""
    result, blocks = _single_result_iteration(({"v": float("nan")}, False))
    assert result.outcome_counts == {"handler_exception": 1}
    assert blocks[0].content == _REFUSAL_CONTENT
    assert "NaN" not in blocks[0].content


def test_oversized_result_refused():
    result, blocks = _single_result_iteration(
        ({"blob": "x" * (_MAX_RESULT_BYTES + 1024)}, False))
    assert result.outcome_counts == {"handler_exception": 1}
    assert blocks[0].content == _REFUSAL_CONTENT


def test_accepted_result_serialization_is_byte_identical():
    payload = {"z": {"deep": [1, 2, {"k": None}]}, "a": True, "f": 2.5}
    result, blocks = _single_result_iteration((payload, False))
    assert result.outcome_counts == {"ok": 1}
    assert blocks[0].is_error is False
    assert blocks[0].content == json.dumps(payload, sort_keys=True)


def test_ordinary_router_error_payloads_still_serialize():
    """The router's own fixed error payloads are pure JSON trees and pass the
    validator unchanged."""
    payload = {"error": "transport_failure",
               "category": "transport_failure",
               "tool": "get_medusa_census",
               "message": "URLError"}
    result, blocks = _single_result_iteration((payload, True))
    assert result.outcome_counts == {"transport_failure": 1}
    assert blocks[0].is_error is True
    assert blocks[0].content == json.dumps(payload, sort_keys=True)


def test_mixed_turn_refused_and_accepted_results_keep_positions():
    ok_payload = {"data": 1}
    backend = MockBackend(responses=[
        AgentResponse.from_content(
            [ToolUseBlock(id="tu_m1", name="get_medusa_census", input={}),
             ToolUseBlock(id="tu_m2", name="get_medusa_census", input={})],
            stop_reason="tool_use",
            usage={"input_tokens": 1, "output_tokens": 1},
        ),
        _text_response("done"),
    ])
    client = OrchestratorClient("http://test:8080", http_do=FakeHttp())
    orch = Orchestrator(
        backend=backend, client=client, system_prompt="s",
        router=_StubRouter([({"bad": object()}, False), (ok_payload, False)]),
        max_tool_depth=4,
    )
    result = orch.run_one_iteration("observe")
    blocks = [b for b in backend.calls[-1].messages[-1].content
              if isinstance(b, ToolResultBlock)]
    assert result.outcome_counts == {"handler_exception": 1, "ok": 1}
    assert [b.tool_use_id for b in blocks] == ["tu_m1", "tu_m2"]
    assert blocks[0].content == _REFUSAL_CONTENT
    assert blocks[0].is_error is True
    assert blocks[1].content == json.dumps(ok_payload, sort_keys=True)
    assert blocks[1].is_error is False


def test_refusal_collects_no_proposal_id():
    """A propose result that fails validation collects nothing even though it
    carries a plausible id."""
    result, blocks = _single_result_iteration(
        ({"proposal_id": "prop-newid", "junk": {1, 2}}, False),
        name="propose_tuning", mode=MODE_PROPOSE)
    assert result.proposals_created == []
    assert result.outcome_counts == {"handler_exception": 1}
    assert blocks[0].content == _REFUSAL_CONTENT
