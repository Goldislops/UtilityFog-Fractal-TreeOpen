"""OMI-V2 - controls for Jack's first independent HOLD round.

Each control below reproduces a defect that survived adversarial verification
against HEAD a6577f47, and fails without its correction. They are grouped by
the defect they close, not by the gate that surfaced them.

Everything here runs identically under normal, ``-O`` and ``-OO``: no library
``assert`` is relied upon and no ``__doc__`` is read (``-OO`` strips both).
Document checks read the source file for the same reason.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import os
import pathlib
import re
import threading
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.agent_backends import openai_compat_backend as backend_module
from scripts.agent_backends import structured_request as sr
from scripts.agent_backends.base import AgentResponse, Message
from scripts.agent_backends.openai_compat_backend import (
    OpenAICompatBackend,
    StructuredCompletion,
)
from scripts.agent_backends.structured_request import (
    REFUSAL_TOKENS,
    STRUCTURED_WIRE_NAME,
    SUPPORTED_DIALECTS,
    StructuredOutputRequest,
    build_response_format,
    plan_structured_request,
)
from scripts.open_model.structured_exchange import (
    StructuredExchange,
    request_structured_json,
)


_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
_MESSAGES = [Message(role="user", content="hello")]
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _request(schema=None) -> StructuredOutputRequest:
    return StructuredOutputRequest(schema=_SCHEMA if schema is None else schema)


class RecordingClient:
    """Captures outbound request kwargs; returns a canned JSON completion."""

    def __init__(self, text: str = '{"ok": true}'):
        self.requests: list[dict] = []
        self._text = text
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._text, tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )


def _backend(dialect="vllm", client=None) -> OpenAICompatBackend:
    return OpenAICompatBackend(
        model="m",
        client=client if client is not None else RecordingClient(),
        dialect=dialect,
    )


# == an unencodable schema is refused, not handed to the transport ===========
#
# A lone UTF-16 surrogate is an exact `str` and survives every element check.
# `json.dumps` emits it verbatim; UTF-8 cannot encode it. Before the fix the
# planner returned ok=True and the UnicodeEncodeError surfaced from inside the
# SDK - an exception escaping a method that promises a refusal instead.

_SURROGATE = "\udc80"


@pytest.mark.parametrize(
    "schema",
    [
        {"x": _SURROGATE},
        {_SURROGATE: "v"},
        {"a": {"b": [1, {"c": _SURROGATE}]}},
        {"a": ["ok", _SURROGATE]},
        {"title": "lead" + _SURROGATE + "trail"},
    ],
)
def test_a_schema_carrying_a_lone_surrogate_is_refused(schema):
    plan = plan_structured_request("vllm", _request(schema))
    assert plan.ok is False
    assert plan.refusal == "schema-not-utf8-encodable"
    assert plan.response_format is None


def test_the_surrogate_refusal_reaches_the_backend_without_raising():
    """The whole point: `complete_structured` must refuse, not raise."""
    client = RecordingClient()
    result = _backend(client=client).complete_structured(
        _MESSAGES, [], structured=_request({"x": _SURROGATE})
    )
    assert result.ok is False
    assert result.refusal == "schema-not-utf8-encodable"
    assert client.requests == [], "no request may be sent for a refused schema"


def test_the_surrogate_refusal_reaches_the_exchange_without_raising():
    result = request_structured_json(
        _backend(), _MESSAGES, [], structured=_request({"x": _SURROGATE})
    )
    assert result.ok is False
    assert result.request_refusal == "schema-not-utf8-encodable"


def test_an_encodable_schema_is_still_accepted():
    """Guard: a refusal that swallowed everything would pass the tests above."""
    for schema in (
        {"x": "plain"},
        {"x": "café"},
        {"x": "中文"},
        {"x": "\U0001F600"},
        {"emoji\U0001F600": "paired surrogate pair is fine"},
    ):
        plan = plan_structured_request("vllm", _request(schema))
        assert plan.ok is True, schema


def test_the_new_refusal_tokens_are_in_the_declared_vocabulary():
    assert "schema-not-utf8-encodable" in REFUSAL_TOKENS
    assert "schema-changed-during-validation" in REFUSAL_TOKENS


# == the transmitted wire name resolves no rebindable module name ============
#
# `json_schema.name` is the one value in the request that leaves the process
# and is NOT caller data. Resolving it through a module global meant rebinding
# one attribute put arbitrary text on the wire - reopening, by the back door,
# the leak that removing the caller-supplied name had closed.

_AUDIT_SECRET = "sk-OMIV2SECRET123456789"


@pytest.fixture
def restore_wire_name():
    saved = sr.STRUCTURED_WIRE_NAME
    try:
        yield
    finally:
        sr.STRUCTURED_WIRE_NAME = saved


@pytest.mark.parametrize("dialect", ["vllm", "sglang"])
def test_rebinding_the_wire_name_puts_nothing_on_the_wire(
    restore_wire_name, dialect
):
    sr.STRUCTURED_WIRE_NAME = _AUDIT_SECRET
    wire = plan_structured_request(dialect, _request()).response_format
    assert wire["json_schema"]["name"] == "structured_output"
    assert _AUDIT_SECRET not in repr(wire)


def test_rebinding_the_wire_name_changes_no_request(restore_wire_name):
    sr.STRUCTURED_WIRE_NAME = _AUDIT_SECRET
    client = RecordingClient()
    _backend(client=client).complete_structured(
        _MESSAGES, [], structured=_request()
    )
    assert _AUDIT_SECRET not in repr(client.requests)


def test_the_builder_reads_no_rebindable_name_at_all():
    """Structural: the trust path resolves NO module-level name.

    This is the assertion the previous round's section header claimed and did
    not have - `STRUCTURED_WIRE_NAME` was in `co_names`.
    """
    referenced = set(build_response_format.__code__.co_names)
    for forbidden in (
        "STRUCTURED_WIRE_NAME",
        "SUPPORTED_DIALECTS",
        "DIALECT_WIRE_SHAPES",
    ):
        assert forbidden not in referenced, forbidden


def test_the_wire_name_mirror_still_matches_the_inlined_literal():
    """Drift guard for the mirror that is now off the trust path."""
    assert STRUCTURED_WIRE_NAME == "structured_output"
    for dialect in ("vllm", "sglang"):
        wire = build_response_format(dialect, _request())
        assert wire["json_schema"]["name"] == STRUCTURED_WIRE_NAME


# == the tools gate cannot be walked past by an unstable __bool__ ============


class _FlipTools:
    """Answers False the first time it is truth-tested, True after.

    Before the fix, `complete_structured` truth-tested `tools` once for the
    gate and `_build_request` truth-tested it again: this object passed the
    gate as tool-free and still had its tools attached beside the
    `response_format`.
    """

    def __init__(self) -> None:
        self.bool_calls = 0

    def __bool__(self) -> bool:
        self.bool_calls += 1
        return self.bool_calls > 1

    def __iter__(self):
        return iter(
            [SimpleNamespace(name="t", description="d", input_schema={})]
        )


def test_tools_is_truth_tested_exactly_once():
    client = RecordingClient()
    tools = _FlipTools()
    _backend(client=client).complete_structured(
        _MESSAGES, tools, structured=_request()
    )
    assert tools.bool_calls == 1


def test_an_unstable_tools_object_cannot_smuggle_tools_alongside_a_schema():
    client = RecordingClient()
    _backend(client=client).complete_structured(
        _MESSAGES, _FlipTools(), structured=_request()
    )
    sent = client.requests[0]
    assert "response_format" in sent
    assert "tools" not in sent, "the gate and the request disagreed"


def test_a_genuine_tools_list_still_refuses_before_any_request():
    client = RecordingClient()
    result = _backend(client=client).complete_structured(
        _MESSAGES,
        [SimpleNamespace(name="t", description="d", input_schema={})],
        structured=_request(),
    )
    assert result.refusal == "tools-with-structured-unsupported"
    assert client.requests == []


def test_legacy_complete_still_truth_tests_tools_itself():
    """`include_tools` defaults to None, so `complete()` is unchanged."""
    client = RecordingClient()
    _backend(client=client).complete(
        _MESSAGES, [SimpleNamespace(name="t", description="d", input_schema={})]
    )
    assert "tools" in client.requests[0]
    client2 = RecordingClient()
    _backend(client=client2).complete(_MESSAGES, [])
    assert "tools" not in client2.requests[0]


# == a success cannot carry a foreign payload ================================


@pytest.mark.parametrize(
    "response",
    ["not-a-response", 42, [1], {"text": "x"}, SimpleNamespace(text="x"), object()],
)
def test_a_successful_completion_refuses_a_foreign_response(response):
    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True, response=response, dialect="vllm", response_format_sent=True
        )


def test_a_successful_completion_accepts_an_exact_agent_response():
    """Guard: a check that rejected everything would pass the test above."""
    completion = StructuredCompletion(
        ok=True,
        response=AgentResponse.from_content([]),
        dialect="vllm",
        response_format_sent=True,
    )
    assert completion.ok is True


def test_an_agent_response_subclass_is_refused_by_exact_type():
    class Sub(AgentResponse):
        pass

    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True,
            response=Sub(text=None, tool_calls=[], raw_content=[]),
            dialect="vllm",
            response_format_sent=True,
        )


@pytest.mark.parametrize(
    "value", ["sk-LEAKED-SECRET", 42, [1], (1,), object(), b"bytes"]
)
def test_a_successful_exchange_refuses_a_foreign_value(value):
    with pytest.raises(ValueError):
        StructuredExchange(ok=True, value=value, response_format_sent=True)


@pytest.mark.parametrize(
    "value", [{"a": 1}, MappingProxyType({"a": 1})]
)
def test_a_successful_exchange_accepts_an_exact_mapping(value):
    assert StructuredExchange(ok=True, value=value, response_format_sent=True).ok


def test_the_exchange_stays_total_against_a_foreign_completion_payload():
    """The reason the exact-type check matters, stated as behaviour.

    `request_structured_json` promises a result for every reachable input.
    A completion carrying a non-AgentResponse used to make it raise
    AttributeError while reading `.text`.
    """

    class Liar:
        def complete_structured(self, *a, **k):
            # Constructing this is now impossible via the real class, so the
            # backend cannot produce one - which is exactly the guarantee.
            with pytest.raises(ValueError):
                StructuredCompletion(
                    ok=True,
                    response=SimpleNamespace(),
                    dialect="vllm",
                    response_format_sent=True,
                )
            return SimpleNamespace(ok=True, response=SimpleNamespace())

    result = request_structured_json(Liar(), _MESSAGES, [], structured=_request())
    assert result.ok is False
    assert result.request_refusal == "backend-not-structured-capable"


# == validation stays total while another thread mutates the schema ==========


def test_no_exception_escapes_while_the_schema_is_mutated_concurrently():
    """Totality under concurrent mutation.

    The assertion is the absence of an escaping exception, so this cannot be
    flaky in the failing direction: the race may or may not be hit on a given
    run, but if it is hit and is unhandled, this fails.
    """
    schema = {"type": "object", "properties": {str(i): {} for i in range(60)}}
    stop = threading.Event()
    errors: list[BaseException] = []

    def mutate():
        i = 0
        while not stop.is_set():
            i += 1
            schema["properties"][str(1000 + (i % 200))] = {}
            schema["properties"].pop(str(1000 + ((i + 5) % 200)), None)

    mutator = threading.Thread(target=mutate, daemon=True)
    mutator.start()
    try:
        for _ in range(3000):
            try:
                plan = plan_structured_request("vllm", _request(schema))
            except BaseException as exc:  # noqa: BLE001 - the whole point
                errors.append(exc)
                break
            assert type(plan) is sr.StructuredRequestPlan
            if plan.refusal is not None:
                assert plan.refusal in REFUSAL_TOKENS
    finally:
        stop.set()
        mutator.join(timeout=5)

    assert errors == [], "an exception escaped a total function: " + repr(errors)


# == the depth boundary control actually reaches the boundary ================


def _chain(levels: int) -> dict:
    root: dict = {"type": "object"}
    node = root
    for _ in range(levels):
        child: dict = {"type": "object"}
        node["properties"] = child
        node = child
    return root


def test_the_depth_boundary_is_exercised_at_the_edge():
    """The previous control nested 8 levels against a limit of 32 and would
    have passed for any limit above 8. This pins both sides of the edge."""
    assert plan_structured_request("vllm", _request(_chain(31))).ok is True
    assert plan_structured_request("vllm", _request(_chain(32))).refusal == (
        "schema-too-deep"
    )


def test_the_depth_edge_moves_with_the_constant(monkeypatch):
    """Proves the edge is the constant, not a coincidence of this schema."""
    monkeypatch.setattr(sr, "_SCHEMA_MAX_DEPTH", 10)
    assert plan_structured_request("vllm", _request(_chain(9))).ok is True
    assert plan_structured_request("vllm", _request(_chain(10))).refusal == (
        "schema-too-deep"
    )


# == the no-file-write control covers more than builtins.open ================


def test_the_exchange_writes_no_file_through_any_common_api(monkeypatch):
    import builtins

    def refuse(*args, **kwargs):
        raise AssertionError("the exchange touched the filesystem")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(pathlib.Path, "open", refuse)
    monkeypatch.setattr(pathlib.Path, "write_text", refuse)
    monkeypatch.setattr(pathlib.Path, "write_bytes", refuse)
    monkeypatch.setattr(os, "open", refuse)

    result = request_structured_json(
        _backend(client=RecordingClient()), _MESSAGES, [], structured=_request()
    )
    assert result.ok is True


@pytest.mark.parametrize("api", ["builtins", "pathlib", "os"])
def test_each_filesystem_guard_would_actually_fire(monkeypatch, api):
    """Guard: an inert patch would make the control above vacuous."""
    import builtins

    def refuse(*args, **kwargs):
        raise AssertionError("guard fired")

    target = pathlib.Path(str(_REPO_ROOT / "omi-v2-probe-never-created.txt"))
    if api == "builtins":
        monkeypatch.setattr(builtins, "open", refuse)
        with pytest.raises(AssertionError):
            open(str(target))
    elif api == "pathlib":
        monkeypatch.setattr(pathlib.Path, "write_text", refuse)
        with pytest.raises(AssertionError):
            target.write_text("x", encoding="utf-8")
    else:
        monkeypatch.setattr(os, "open", refuse)
        with pytest.raises(AssertionError):
            os.open(str(target), os.O_RDONLY)


# == the dialect gate provably runs before any SDK client is built ===========


def test_an_invalid_dialect_raises_before_the_sdk_client_is_constructed(
    monkeypatch,
):
    """The previous control could not tell the two orderings apart.

    It asserted only `pytest.raises(ValueError)`, and a ValueError arrives
    either way once `openai` is importable - which it is, locally and in CI.
    Making SDK construction raise a DISTINCT exception separates them: seeing
    ValueError proves the gate ran first.
    """
    import openai

    class Detonate:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("SDK client was constructed")

    monkeypatch.setattr(openai, "OpenAI", Detonate)

    with pytest.raises(ValueError):
        OpenAICompatBackend(
            model="m", base_url="http://127.0.0.1:9/v1", dialect="nope"
        )


def test_the_detonating_client_would_actually_fire(monkeypatch):
    """Guard: if the patch were inert the ordering proof above is vacuous."""
    import openai

    class Detonate:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("SDK client was constructed")

    monkeypatch.setattr(openai, "OpenAI", Detonate)
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(RuntimeError):
        OpenAICompatBackend(
            model="m", base_url="http://127.0.0.1:9/v1", dialect="vllm"
        )


# == the mirror drift guard covers every dialect, including the named ones ===


def test_the_wire_shape_mirror_detects_drift_for_every_dialect():
    """The previous guard could not detect a corrupted mirror string for
    vllm or sglang, because both fell into the same catch-all branch."""
    expected = {
        "llama-cpp": "response_format.json_schema.schema",
        "ollama": "response_format.json_schema.schema",
        "vllm": "response_format.json_schema.{name,schema}",
        "sglang": "response_format.json_schema.{name,schema}",
    }
    assert dict(sr.DIALECT_WIRE_SHAPES) == expected
    for dialect, described in expected.items():
        wire = build_response_format(dialect, _request())
        nested = wire["json_schema"]
        if described.endswith("{name,schema}"):
            assert set(nested) == {"name", "schema"}, dialect
        else:
            assert set(nested) == {"schema"}, dialect
        assert "schema" not in wire, dialect


# == documentation truth: the test inventory cannot silently go stale ========


def _section_16_8() -> str:
    text = (_REPO_ROOT / "docs" / "OPEN_MODEL_INTEGRATION.md").read_text(
        encoding="utf-8"
    )
    start = text.index("### 16.8")
    end = text.find("###", start + 8)
    return text[start:end if end != -1 else len(text)]


def test_every_omi_v2_test_file_is_named_in_the_documented_inventory():
    """The stale table omitted an entire test file. This makes that
    impossible to repeat without the test failing."""
    section = _section_16_8()
    on_disk = sorted(p.name for p in (_REPO_ROOT / "tests").glob("test_omi_v2_*.py"))
    assert on_disk, "the glob must find something or this test is vacuous"
    for name in on_disk:
        assert name in section, name


def test_the_documented_inventory_total_matches_its_own_rows():
    """Internal consistency: the stated total must equal the row sum."""
    section = _section_16_8()
    rows = [int(n) for n in re.findall(r"\|\s*(\d+)\s*\|", section)]
    totals = [int(n) for n in re.findall(r"(\d+)\s+hermetic tests", section)]
    assert rows, "no per-file counts found in the table"
    assert len(totals) == 1, "exactly one stated total expected"
    assert sum(rows) == totals[0]


def test_the_documented_inventory_names_no_file_that_does_not_exist():
    section = _section_16_8()
    for name in re.findall(r"test_omi_v2_[a-z_]+\.py", section):
        assert (_REPO_ROOT / "tests" / name).exists(), name
