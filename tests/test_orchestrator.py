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
    Orchestrator,
    OrchestratorClient,
    ToolRouter,
    observation_tools,
    tuning_tools,
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
    router = ToolRouter(client)
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
    router = ToolRouter(client, orchestrator_source="agent:swarm-hunter")
    router.execute(
        "propose_tuning",
        {"params": {"signal_interval": 14}, "justification": "reason"},
    )
    sent = http.calls[0]["json"]
    assert sent["source"] == "agent:swarm-hunter"


def test_router_commit_always_uses_configured_approver_never_human():
    """Safety: the orchestrator's router hard-codes the approver. No
    mechanism exists for the LLM to spoof a human approver."""
    client, http = _client_with_fake()
    http.set("POST", "/api/tuning/commit", 200, {"status": "committed"})
    router = ToolRouter(client, commit_approver="policy:auto")
    router.execute("commit_tuning", {"proposal_id": "prop-x", "approver": "human:evil"})
    sent = http.calls[0]["json"]
    # The human:evil from LLM input is IGNORED — router uses its configured value.
    assert sent["approver"] == "policy:auto"


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


def _make_orchestrator(backend: MockBackend) -> tuple[Orchestrator, FakeHttp]:
    http = FakeHttp()
    client = OrchestratorClient("http://test:8080", http_do=http)
    orch = Orchestrator(
        backend=backend,
        client=client,
        system_prompt="test system",
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
    orch, http = _make_orchestrator(backend)
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


def test_iteration_propose_then_commit_then_end():
    backend = MockBackend(responses=[
        _tool_use_response("tu_1", "propose_tuning", {
            "params": {"signal_interval": 12},
            "justification": "reduce overhead",
            "mode": "commit-pending",
        }),
        _tool_use_response("tu_2", "commit_tuning", {"proposal_id": "prop-xyz"}),
        _text_response("committed"),
    ])
    orch, http = _make_orchestrator(backend)
    http.set("POST", "/api/tuning/propose", 200, {"proposal_id": "prop-xyz", "status": "accepted"})
    http.set("POST", "/api/tuning/commit", 200, {"proposal_id": "prop-xyz", "status": "committed"})
    result = orch.run_one_iteration("observe")
    assert result.stopped_because == "end_turn"
    assert result.proposals_created == ["prop-xyz"]
    assert result.commits_applied == ["prop-xyz"]


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


def test_iteration_tools_default_to_observation_plus_tuning():
    backend = MockBackend(responses=[_text_response("ok")])
    orch, _ = _make_orchestrator(backend)
    orch.run_one_iteration("go")
    tool_names = [t.name for t in backend.calls[0].tools]
    for expected in (
        "get_medusa_census", "get_medusa_equanimity", "get_acoustic_map",
        "get_params", "get_params_schema",
        "propose_tuning", "commit_tuning",
    ):
        assert expected in tool_names


# -- tool spec shape ---------------------------------------------------------


def test_propose_tuning_tool_requires_justification():
    specs = {t.name: t for t in tuning_tools()}
    propose = specs["propose_tuning"]
    assert "justification" in propose.input_schema["required"]
    assert "params" in propose.input_schema["required"]


def test_commit_tuning_tool_requires_proposal_id():
    specs = {t.name: t for t in tuning_tools()}
    commit = specs["commit_tuning"]
    assert commit.input_schema["required"] == ["proposal_id"]


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
    if OpenAICompatBackend is None:
        pytest.skip("openai SDK not installed")
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
