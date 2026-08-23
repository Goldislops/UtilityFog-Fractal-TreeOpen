"""OMI-V2 - controls on `OpenAICompatBackend.complete_structured()`.

Hermetic throughout: every client is injected and local. No network call, no
API key, no runtime endpoint, no model download. A module-scoped autouse
fixture makes that structural rather than aspirational by breaking socket
construction for the duration of the file.

The load-bearing control here is ordering. A refused structured request must
not become a call against a runtime - not a billed one, not a logged one, not
a rate-limited one. `ExplodingClient` raises on *every* attribute access, so
any test that refuses while holding one proves the refusal completed before
the client was reached at all.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from scripts.agent_backends.base import Message, ToolSpec
from scripts.agent_backends.openai_compat_backend import (
    OpenAICompatBackend,
    StructuredCompletion,
)
from scripts.agent_backends.structured_request import (
    SUPPORTED_DIALECTS,
    StructuredOutputRequest,
)


_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
_REQUEST = StructuredOutputRequest(schema=_SCHEMA)
_MESSAGES = [Message(role="user", content="hello")]
_TOOL = ToolSpec(name="t", description="d", input_schema={"type": "object"})
_SECRET = "sk-omi-v2-secret-key-value"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Structural no-network control for every test in this file."""

    def _refuse(*args, **kwargs):
        raise AssertionError("a socket was created during a hermetic test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


class ExplodingClient:
    """Raises on every attribute access, including `chat`.

    Used to prove a refusal path never reaches the SDK. Construction and
    assignment touch no attribute, so a backend may hold one safely for as
    long as it never tries to use it.
    """

    def __getattribute__(self, name):
        raise AssertionError("the SDK client was touched: " + name)


class RecordingClient:
    """Captures the outbound request kwargs and returns a canned completion."""

    def __init__(self, text: str = '{"ok": true}', finish_reason: str = "stop"):
        self.requests: list[dict] = []
        self._text = text
        self._finish_reason = finish_reason
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._text, tool_calls=None),
                    finish_reason=self._finish_reason,
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )

    @property
    def only_request(self) -> dict:
        assert len(self.requests) == 1, self.requests
        return self.requests[0]


def _backend(dialect=None, client=None, **kwargs) -> OpenAICompatBackend:
    return OpenAICompatBackend(
        model="m", client=client if client is not None else RecordingClient(),
        dialect=dialect, **kwargs
    )


# == the dialect is explicit, closed, and validated at construction ==========


@pytest.mark.parametrize("dialect", list(SUPPORTED_DIALECTS))
def test_every_supported_dialect_constructs(dialect):
    assert _backend(dialect=dialect).dialect == dialect


def test_omitting_the_dialect_leaves_the_instance_exactly_as_before():
    backend = _backend()
    assert backend.dialect is None


@pytest.mark.parametrize(
    "dialect",
    ["", "vLLM", "llama_cpp", "openai", "tgi", "unknown", 1, 1.0, True, b"vllm", []],
)
def test_an_invalid_dialect_raises_at_construction(dialect):
    with pytest.raises(ValueError):
        OpenAICompatBackend(model="m", client=RecordingClient(), dialect=dialect)


def test_the_dialect_is_validated_before_any_client_is_built(monkeypatch):
    """No `client=` is injected, so reaching SDK construction would raise
    RuntimeError (or build a real client). ValueError proves the gate ran
    first, before anything could be constructed or any key consulted."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(ValueError):
        OpenAICompatBackend(model="m", base_url="http://127.0.0.1:9", dialect="nope")


def test_the_dialect_is_never_inferred_from_the_base_url():
    """A URL that names a runtime confers nothing; the dialect stays None."""
    for url in (
        "http://localhost:11434/v1",
        "http://localhost:8000/v1",
        "http://vllm.internal/v1",
        "http://localhost:8080/v1",
    ):
        backend = _backend(base_url=url)
        assert backend.dialect is None
        result = backend.complete_structured(
            _MESSAGES, [], structured=_REQUEST
        )
        assert result.refusal == "dialect-not-configured"


# == refusal happens before the SDK client is reached ========================


@pytest.mark.parametrize(
    "dialect,structured,tools,expected",
    [
        (None, _REQUEST, [], "dialect-not-configured"),
        ("vllm", None, [], "request-not-exact-type"),
        ("vllm", {"name": "R", "schema": _SCHEMA}, [], "request-not-exact-type"),
        ("vllm", _REQUEST, [_TOOL], "tools-with-structured-unsupported"),
        (
            "vllm",
            StructuredOutputRequest(schema=None),
            [],
            "schema-not-exact-dict",
        ),
        ("vllm", StructuredOutputRequest(schema={}), [], "schema-empty"),
        (
            "vllm",
            StructuredOutputRequest(schema={"a": object()}),
            [],
            "schema-not-serializable",
        ),
        (
            "vllm",
            StructuredOutputRequest(schema={"a": float("inf")}),
            [],
            "schema-non-finite-number",
        ),
        (
            "vllm",
            StructuredOutputRequest(schema={"a": "A" * 70000}),
            [],
            "schema-too-large",
        ),
    ],
)
def test_every_refusal_completes_without_touching_the_client(
    dialect, structured, tools, expected
):
    backend = _backend(dialect=dialect, client=ExplodingClient())
    result = backend.complete_structured(_MESSAGES, tools, structured=structured)
    assert result.ok is False
    assert result.refusal == expected
    assert result.response is None
    assert result.response_format_sent is False


def test_the_exploding_client_would_actually_fire():
    """Guard: if ExplodingClient were inert, every ordering test is vacuous."""
    backend = _backend(dialect="vllm", client=ExplodingClient())
    with pytest.raises(AssertionError):
        backend.complete(_MESSAGES, [])
    with pytest.raises(AssertionError):
        backend.complete_structured(_MESSAGES, [], structured=_REQUEST)


# == the legacy request shape did not move ===================================


def test_complete_sends_no_response_format():
    client = RecordingClient()
    _backend(dialect="vllm", client=client).complete(_MESSAGES, [])
    assert "response_format" not in client.only_request


def test_the_legacy_request_keys_are_exactly_as_before():
    client = RecordingClient()
    _backend(client=client).complete(_MESSAGES, [])
    assert set(client.only_request) == {
        "model",
        "messages",
        "max_tokens",
        "temperature",
    }


def test_configuring_a_dialect_changes_nothing_about_complete():
    """Requirement 5, stated as an equality rather than an inspection."""
    plain, dialected = RecordingClient(), RecordingClient()
    _backend(client=plain).complete(
        _MESSAGES, [_TOOL], system="s", max_tokens=99, temperature=0.5
    )
    _backend(dialect="ollama", client=dialected).complete(
        _MESSAGES, [_TOOL], system="s", max_tokens=99, temperature=0.5
    )
    assert plain.only_request == dialected.only_request


def test_structured_adds_exactly_one_key_to_the_legacy_request():
    plain, structured = RecordingClient(), RecordingClient()
    _backend(client=plain).complete(
        _MESSAGES, [], system="s", max_tokens=99, temperature=0.5
    )
    _backend(dialect="vllm", client=structured).complete_structured(
        _MESSAGES, [], structured=_REQUEST, system="s", max_tokens=99, temperature=0.5
    )
    added = set(structured.only_request) - set(plain.only_request)
    assert added == {"response_format"}
    for key in plain.only_request:
        assert structured.only_request[key] == plain.only_request[key], key


# == exact outbound wire shape, per dialect, at the backend boundary =========


@pytest.mark.parametrize(
    "dialect,expected",
    [
        (
            "llama-cpp",
            {"type": "json_schema", "json_schema": {"schema": _SCHEMA}},
        ),
        (
            "ollama",
            {"type": "json_schema", "json_schema": {"schema": _SCHEMA}},
        ),
        (
            "vllm",
            {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": _SCHEMA},
            },
        ),
        (
            "sglang",
            {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": _SCHEMA},
            },
        ),
    ],
)
def test_the_outbound_response_format_is_dialect_exact(dialect, expected):
    client = RecordingClient()
    result = _backend(dialect=dialect, client=client).complete_structured(
        _MESSAGES, [], structured=_REQUEST
    )
    assert result.ok is True
    assert client.only_request["response_format"] == expected


# == no escape hatch exists ==================================================


def test_no_request_ever_carries_an_extra_body_or_passthrough_key():
    forbidden = {
        "extra_body",
        "extra_query",
        "guided_json",
        "structured_outputs",
        "grammar",
        "seed",
        "tool_choice",
        "stream",
    }
    for dialect in SUPPORTED_DIALECTS:
        client = RecordingClient()
        _backend(dialect=dialect, client=client).complete_structured(
            _MESSAGES, [], structured=_REQUEST
        )
        assert forbidden.isdisjoint(client.only_request), dialect


def test_complete_structured_accepts_no_arbitrary_request_kwargs():
    backend = _backend(dialect="vllm")
    with pytest.raises(TypeError):
        backend.complete_structured(
            _MESSAGES, [], structured=_REQUEST, extra_body={"guided_json": _SCHEMA}
        )
    with pytest.raises(TypeError):
        backend.complete_structured(
            _MESSAGES, [], structured=_REQUEST, seed=1
        )


# == no secret reaches the request or the result =============================


def test_no_api_key_reaches_the_request_or_the_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    client = RecordingClient()
    backend = OpenAICompatBackend(
        model="m", client=client, dialect="vllm", api_key=_SECRET
    )
    result = backend.complete_structured(_MESSAGES, [], structured=_REQUEST)
    assert _SECRET not in repr(client.only_request)
    assert _SECRET not in repr(result)


def test_a_refusal_carries_no_schema_prompt_or_key_content():
    secret_prompt = "PROMPTSECRET"
    secret_key = "SCHEMAKEYSECRET"
    backend = _backend(dialect="vllm", client=ExplodingClient())
    result = backend.complete_structured(
        [Message(role="user", content=secret_prompt)],
        [],
        structured=StructuredOutputRequest(schema={secret_key: object()}),
    )
    assert result.refusal == "schema-not-serializable"
    text = repr(result)
    assert secret_prompt not in text
    assert secret_key not in text


# == sending a request is not a claim that it was honoured ===================


def test_response_format_sent_records_the_send_not_the_outcome():
    """The runtime here returns prose, not JSON, and the backend still says
    only that the request was sent - it makes no conformance claim."""
    client = RecordingClient(text="I am not JSON at all.")
    result = _backend(dialect="ollama", client=client).complete_structured(
        _MESSAGES, [], structured=_REQUEST
    )
    assert result.ok is True
    assert result.response_format_sent is True
    assert result.response.text == "I am not JSON at all."


def test_the_backend_exposes_no_conformance_claiming_field():
    result = _backend(dialect="vllm").complete_structured(
        _MESSAGES, [], structured=_REQUEST
    )
    for forbidden in ("structured", "validated", "conformant", "schema_honoured"):
        assert not hasattr(result, forbidden), forbidden


# == the result carrier cannot express a contradiction =======================


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ok": True, "refusal": "schema-empty"},
        {"ok": False},
        {"ok": False, "refusal": "schema-empty", "response": object()},
        {"ok": False, "refusal": "schema-empty", "response_format_sent": True},
    ],
)
def test_contradictory_completions_are_refused_at_construction(kwargs):
    with pytest.raises(ValueError):
        StructuredCompletion(**kwargs)


# == layering: the backend package may not reach upward ======================


def test_the_backend_module_imports_nothing_from_open_model():
    from pathlib import Path

    import scripts.agent_backends.openai_compat_backend as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "open_model" not in stripped, stripped
