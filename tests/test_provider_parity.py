"""Phase 18 PR 8 — Provider Parity Proof.

The actual model-agnostic evidence, not a hand-wave.

Claim: the same observe → propose → commit orchestrator iteration produces
equivalent state changes through `AnthropicBackend` AND `OpenAICompatBackend`,
even though the two backends use entirely different wire formats for tool
calls and tool results.

Method: run one full iteration through each backend, both scripted (via
injected mock SDK clients) to make a `propose_tuning` call followed by a
`commit_tuning` call. The downstream tuning API is the *real* Phase 18 PR 2
Flask blueprint, served via a test client wired into a fake `http_do`.
Compare ledger entries, effective params, and orchestrator IterationResults.

What this proves:
  - The translation layer in each backend round-trips the same logical
    AgentResponse / ToolCall / Message through totally different wire
    shapes (Anthropic content blocks vs. OpenAI tool_calls + role:tool).
  - The orchestrator loop is genuinely backend-agnostic; nothing above
    `AgentBackend.complete()` cares which backend produced the response.
  - The tuning API's authoritative ledger is identical regardless of
    which model proposed the tuning.

What this is NOT:
  - A claim that different LLMs will make the same decisions. Different
    models, different judgment. Parity here is at the protocol level:
    given equivalent decisions, the system records and applies them
    equivalently.
  - A live LLM smoke test. No real network calls; both backends use
    dependency-injected mock SDK clients.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from flask import Flask

from scripts.agent_backends import (
    AgentResponse,
    AnthropicBackend,
    Message,
    OpenAICompatBackend,
    TextBlock,
    ToolUseBlock,
)
from scripts.orchestrator import (
    Orchestrator,
    OrchestratorClient,
    ToolRouter,
)
from scripts.tuning_api import TuningState, create_blueprint as create_tuning_blueprint


if AnthropicBackend is None or OpenAICompatBackend is None:
    pytest.skip(
        "anthropic and openai SDKs both required for parity proof",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Test scaffolding: a real tuning API + bridge so the orchestrator's HTTP
# calls land on the Flask test client without ever touching :8080.
# ---------------------------------------------------------------------------


class FakeGen:
    def __init__(self, start: int = 1_500_000) -> None:
        self.value = start

    def advance(self, n: int) -> None:
        self.value += n

    def __call__(self) -> int:
        return self.value


def make_http_do(test_client):
    """Bridge: turn a Flask test client into the http_do callable
    OrchestratorClient expects.

    Signature contract: http_do(method, url, *, json=None, timeout=5.0)
                        returns (status, body_dict).
    """

    def http_do(method, url, *, json=None, timeout=5.0):
        # Strip scheme + host; keep just the path.
        path = "/" + url.split("://", 1)[-1].split("/", 1)[-1]
        path = path if path.startswith("/") else "/" + path
        if method == "GET":
            resp = test_client.get(path)
        elif method == "POST":
            resp = test_client.post(path, json=json)
        else:
            raise ValueError(f"unsupported method: {method}")
        return resp.status_code, (resp.get_json() or {})

    return http_do


@pytest.fixture
def tuning_stack(tmp_path: Path):
    """A real TuningState + Flask blueprint behind a test client. Returns
    (state, http_do, gen) so each test can drive iterations through it."""
    gen = FakeGen()
    state = TuningState(data_dir=tmp_path, gen_getter=gen)
    app = Flask(__name__)
    app.register_blueprint(create_tuning_blueprint(state))
    client = app.test_client()
    return state, make_http_do(client), gen


# ---------------------------------------------------------------------------
# Scripted backend mocks — each one produces wire-format responses that
# look exactly like what the real SDK would return for "propose a tuning,
# then commit it, then stop".
# ---------------------------------------------------------------------------


# -- Anthropic mock SDK (mirrors test_anthropic_backend.py's pattern) ------


def _anthropic_text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _anthropic_tool_use(tid: str, name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=input_)


def _anthropic_response(content: list, *, stop_reason: str = "end_turn",
                        input_tokens: int = 30, output_tokens: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _MockAnthropicMessages:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.last_request: Optional[dict] = None
        self.call_count = 0

    def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        self.call_count += 1
        if not self.responses:
            raise RuntimeError("no scripted responses left")
        return self.responses.pop(0)


class _MockAnthropicClient:
    def __init__(self, responses: list) -> None:
        self.messages = _MockAnthropicMessages(responses)


# -- OpenAI mock SDK (mirrors test_openai_compat_backend.py's pattern) -----


def _openai_response(content: Optional[str] = None,
                     *, tool_calls: Optional[list] = None,
                     finish_reason: str = "stop",
                     prompt_tokens: int = 30, completion_tokens: int = 50) -> SimpleNamespace:
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[choice], usage=usage)


def _openai_tool_call(tc_id: str, name: str, args_obj: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=tc_id, type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args_obj)),
    )


class _MockOpenAIChatCompletions:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.last_request: Optional[dict] = None
        self.call_count = 0

    def create(self, **kwargs: Any) -> Any:
        self.last_request = kwargs
        self.call_count += 1
        if not self.responses:
            raise RuntimeError("no scripted responses left")
        return self.responses.pop(0)


class _MockOpenAIChat:
    def __init__(self, responses: list) -> None:
        self.completions = _MockOpenAIChatCompletions(responses)


class _MockOpenAIClient:
    def __init__(self, responses: list) -> None:
        self.chat = _MockOpenAIChat(responses)


# ---------------------------------------------------------------------------
# The shared "decide" pattern: propose signal_interval=14 (AUTO category),
# then commit it, then stop. Both backends script this same conceptual
# behaviour in their own native wire format.
# ---------------------------------------------------------------------------


PROPOSAL_PARAMS = {"signal_interval": 14}
JUSTIFICATION = "test parity"
SOURCE = "agent:parity-test"


def _anthropic_script() -> list:
    """Three-turn script for AnthropicBackend:
       1. assistant: text "I'll propose a small tuning." + tool_use propose_tuning
       2. assistant: tool_use commit_tuning(prop_id_from_router)
       3. assistant: text "done"
    """
    return [
        _anthropic_response([
            _anthropic_text("I'll propose a small tuning."),
            _anthropic_tool_use(
                "tu_propose_a",
                "propose_tuning",
                {"params": PROPOSAL_PARAMS, "justification": JUSTIFICATION,
                 "mode": "commit-pending"},
            ),
        ], stop_reason="tool_use"),
        _anthropic_response([
            _anthropic_tool_use(
                "tu_commit_a",
                "commit_tuning",
                {"proposal_id": "PROP_PLACEHOLDER"},  # gets replaced via test
            ),
        ], stop_reason="tool_use"),
        _anthropic_response([_anthropic_text("done")], stop_reason="end_turn"),
    ]


def _openai_script() -> list:
    """Three-turn script for OpenAICompatBackend, equivalent semantically
    to the Anthropic script. Wire format differs entirely:
      - tool_calls is a separate field on the message
      - arguments is a JSON STRING
      - finish_reason naming differs
    """
    return [
        _openai_response(
            content="I'll propose a small tuning.",
            tool_calls=[_openai_tool_call(
                "tu_propose_o",
                "propose_tuning",
                {"params": PROPOSAL_PARAMS, "justification": JUSTIFICATION,
                 "mode": "commit-pending"},
            )],
            finish_reason="tool_calls",
        ),
        _openai_response(
            content=None,
            tool_calls=[_openai_tool_call(
                "tu_commit_o",
                "commit_tuning",
                {"proposal_id": "PROP_PLACEHOLDER"},
            )],
            finish_reason="tool_calls",
        ),
        _openai_response(content="done", finish_reason="stop"),
    ]


def _patch_commit_id_anthropic(script: list, real_proposal_id: str) -> list:
    """The orchestrator runs turn 1 first, learns the real proposal_id from
    the API response, then routes that into turn 2's commit. But our
    pre-scripted turn 2 has a placeholder. Patch it before the orchestrator
    sees turn 2."""
    turn2 = script[1]
    for block in turn2.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "commit_tuning":
            block.input = {"proposal_id": real_proposal_id}
    return script


def _patch_commit_id_openai(script: list, real_proposal_id: str) -> list:
    turn2 = script[1]
    for tc in turn2.choices[0].message.tool_calls or []:
        fn = tc.function
        if fn.name == "commit_tuning":
            fn.arguments = json.dumps({"proposal_id": real_proposal_id})
    return script


# ---------------------------------------------------------------------------
# The actual parity test. Run one iteration per backend, compare results.
# ---------------------------------------------------------------------------


def _run_one(backend, tuning_stack) -> tuple:
    state, http_do, _gen = tuning_stack
    client = OrchestratorClient("http://test:8080", http_do=http_do)
    router = ToolRouter(client, orchestrator_source=SOURCE, commit_approver="policy:auto")
    orch = Orchestrator(
        backend=backend, client=client,
        system_prompt="be concise",
        router=router,
        max_tool_depth=6,
    )
    result = orch.run_one_iteration("Observe Medusa; suggest a tuning if needed.")
    return result, state.effective_params(), state.ledger_path


def test_anthropic_and_openai_compat_produce_equivalent_ledger_entries(tmp_path: Path):
    """Run the same conceptual proposal+commit through each backend.
    Assert both end up with identical effective params and ledger contents
    (modulo proposal_ids and timestamps)."""
    # --- Path 1: Anthropic ---
    gen_a = FakeGen()
    state_a = TuningState(data_dir=tmp_path / "a", gen_getter=gen_a)
    app_a = Flask(__name__)
    app_a.register_blueprint(create_tuning_blueprint(state_a))
    http_do_a = make_http_do(app_a.test_client())

    # We need to know the proposal_id BEFORE turn 2 runs. We solve this with
    # a tiny custom AnthropicBackend that, after turn 1, patches the
    # placeholder in turn 2 with the real proposal_id.
    a_script = _anthropic_script()
    a_client = _MockAnthropicClient(a_script)
    a_backend = AnthropicBackend(client=a_client)

    # Patch a hook into the mock so that BEFORE each script response is
    # served, any pending commit_tuning placeholder gets replaced with the
    # real proposal_id (populated in TuningState after the orchestrator
    # executed the previous turn's propose_tuning tool call).
    original_create_a = a_client.messages.create

    def patched_create_a(**kwargs):
        if state_a._proposals:
            real_pid = sorted(state_a._proposals.keys())[-1]
            _patch_commit_id_anthropic(a_script, real_pid)
        return original_create_a(**kwargs)

    a_client.messages.create = patched_create_a

    a_orch_client = OrchestratorClient("http://test:8080", http_do=http_do_a)
    a_router = ToolRouter(a_orch_client, orchestrator_source=SOURCE,
                          commit_approver="policy:auto")
    a_orch = Orchestrator(
        backend=a_backend, client=a_orch_client,
        system_prompt="be concise", router=a_router, max_tool_depth=6,
    )
    a_result = a_orch.run_one_iteration("Observe Medusa; tune if needed.")

    # --- Path 2: OpenAI-compat ---
    gen_o = FakeGen()
    state_o = TuningState(data_dir=tmp_path / "o", gen_getter=gen_o)
    app_o = Flask(__name__)
    app_o.register_blueprint(create_tuning_blueprint(state_o))
    http_do_o = make_http_do(app_o.test_client())

    o_script = _openai_script()
    o_client = _MockOpenAIClient(o_script)
    o_backend = OpenAICompatBackend(client=o_client)

    original_create_o = o_client.chat.completions.create

    def patched_create_o(**kwargs):
        if state_o._proposals:
            real_pid = sorted(state_o._proposals.keys())[-1]
            _patch_commit_id_openai(o_script, real_pid)
        return original_create_o(**kwargs)

    o_client.chat.completions.create = patched_create_o

    o_orch_client = OrchestratorClient("http://test:8080", http_do=http_do_o)
    o_router = ToolRouter(o_orch_client, orchestrator_source=SOURCE,
                          commit_approver="policy:auto")
    o_orch = Orchestrator(
        backend=o_backend, client=o_orch_client,
        system_prompt="be concise", router=o_router, max_tool_depth=6,
    )
    o_result = o_orch.run_one_iteration("Observe Medusa; tune if needed.")

    # ---- Parity assertions ----

    # 1. Both stopped naturally.
    assert a_result.stopped_because == o_result.stopped_because == "end_turn"

    # 2. Both made the same number of tool calls (propose + commit = 2).
    assert a_result.tool_calls_executed == o_result.tool_calls_executed == 2

    # 3. Both proposed exactly one and committed exactly one.
    assert len(a_result.proposals_created) == len(o_result.proposals_created) == 1
    assert len(a_result.commits_applied) == len(o_result.commits_applied) == 1

    # 4. Both backends pushed the same effective param into the live state.
    assert state_a.effective_params()["signal_interval"] == 14
    assert state_o.effective_params()["signal_interval"] == 14

    # 5. Both ledgers have a propose + commit entry for the same param value.
    a_lines = [json.loads(ln) for ln in
               (tmp_path / "a" / "tuning_ledger.jsonl").read_text().splitlines() if ln.strip()]
    o_lines = [json.loads(ln) for ln in
               (tmp_path / "o" / "tuning_ledger.jsonl").read_text().splitlines() if ln.strip()]
    assert len(a_lines) == len(o_lines) == 2
    assert [e["type"] for e in a_lines] == ["propose", "commit"]
    assert [e["type"] for e in o_lines] == ["propose", "commit"]
    # Parameters and source match modulo backend-specific proposal_ids
    assert a_lines[0]["params"] == o_lines[0]["params"] == PROPOSAL_PARAMS
    assert a_lines[0]["source"] == o_lines[0]["source"] == SOURCE
    assert a_lines[0]["justification"] == o_lines[0]["justification"] == JUSTIFICATION
    assert a_lines[1]["approver"] == o_lines[1]["approver"] == "policy:auto"


def test_parity_at_response_translation_layer():
    """A narrower complement to the end-to-end test: feed each backend a
    semantically equivalent native-wire response and assert the resulting
    AgentResponse objects are structurally identical at the orchestrator-
    visible layer (tool_calls list, stop_reason, text)."""
    a_client = _MockAnthropicClient([
        _anthropic_response([
            _anthropic_text("hi"),
            _anthropic_tool_use("tu_a", "f", {"x": 1}),
        ], stop_reason="tool_use"),
    ])
    a_backend = AnthropicBackend(client=a_client)
    a_resp = a_backend.complete(
        messages=[Message(role="user", content="x")], tools=[],
    )

    o_client = _MockOpenAIClient([
        _openai_response(
            content="hi",
            tool_calls=[_openai_tool_call("tu_o", "f", {"x": 1})],
            finish_reason="tool_calls",
        ),
    ])
    o_backend = OpenAICompatBackend(client=o_client)
    o_resp = o_backend.complete(
        messages=[Message(role="user", content="x")], tools=[],
    )

    # Tool call structure is identical at the orchestrator-visible layer.
    assert isinstance(a_resp, AgentResponse)
    assert isinstance(o_resp, AgentResponse)
    assert a_resp.text == o_resp.text == "hi"
    assert a_resp.stop_reason == o_resp.stop_reason == "tool_use"
    assert len(a_resp.tool_calls) == len(o_resp.tool_calls) == 1
    a_tc, o_tc = a_resp.tool_calls[0], o_resp.tool_calls[0]
    # Tool-call IDs differ (provider-assigned), but name + arguments match.
    assert a_tc.name == o_tc.name == "f"
    assert a_tc.arguments == o_tc.arguments == {"x": 1}


def test_orchestrator_treats_both_backends_identically_for_text_only():
    """Symmetric sanity: a text-only response from each backend produces
    a clean end_turn iteration with no tool calls, identical IterationResult
    shape (modulo usage numbers)."""
    a_client = _MockAnthropicClient([
        _anthropic_response([_anthropic_text("looks healthy")],
                            stop_reason="end_turn"),
    ])
    a_backend = AnthropicBackend(client=a_client)

    o_client = _MockOpenAIClient([
        _openai_response(content="looks healthy", finish_reason="stop"),
    ])
    o_backend = OpenAICompatBackend(client=o_client)

    # Stub HTTP — nothing should be called (no tool calls).
    def stub_http(method, url, *, json=None, timeout=5.0):
        raise AssertionError("text-only iteration should not call HTTP")

    for backend in (a_backend, o_backend):
        client = OrchestratorClient("http://test:8080", http_do=stub_http)
        orch = Orchestrator(
            backend=backend, client=client,
            system_prompt="be concise",
            router=ToolRouter(client),
            max_tool_depth=4,
        )
        result = orch.run_one_iteration("Observe.")
        assert result.stopped_because == "end_turn"
        assert result.tool_calls_executed == 0
        assert result.final_text == "looks healthy"
