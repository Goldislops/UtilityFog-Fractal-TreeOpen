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
    IterationResult,
    MODE_OBSERVE,
    MODE_PROPOSE,
    Orchestrator,
    OrchestratorClient,
    ToolRouter,
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
    client, _ = _client_with_fake()
    router = ToolRouter(client, mode=MODE_PROPOSE)
    payload, is_error = router.execute(
        "propose_tuning",
        {"params": {"signal_interval": 12}, "justification": "   "},
    )
    assert is_error is False  # the handler returns the error as a payload, not raises
    assert payload["error"] == "bad_request"
    assert "justification" in payload["message"]


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


def test_router_commit_empty_proposal_id_rejected_client_side():
    client, _ = _client_with_fake()
    router = ToolRouter(client)
    payload, _ = router.execute("commit_tuning", {})
    assert payload["error"] == "bad_request"


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


def test_router_http_error_status_propagates():
    client, http = _client_with_fake()
    http.set("GET", "/api/census", 500, {"error": "server_broke"})
    router = ToolRouter(client)
    payload, is_error = router.execute("get_medusa_census", {})
    # is_error is False at router level (handler succeeded), but _status is in payload.
    assert is_error is False
    assert payload["_status"] == 500
    assert payload["error"] == "server_broke"


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
    deterministic error, not silently downgraded."""
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
    assert cfg.commit_approver == "policy:auto"  # never accidentally human:


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
