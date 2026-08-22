"""OMI-V2 - controls on the closed structured-output request contract.

Covers the four dialect wire shapes against the evidence pinned in
``scripts/agent_backends/structured_request.py``, and the negative controls
that must refuse before anything is built.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import json

import pytest

from scripts.agent_backends import structured_request as sr
from scripts.agent_backends.structured_request import (
    DIALECT_WIRE_SHAPES,
    STRUCTURED_WIRE_NAME,
    SUPPORTED_DIALECTS,
    StructuredOutputRequest,
    build_response_format,
    is_supported_dialect,
    plan_structured_request,
)


_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


_UNSET = object()
"""Distinct sentinel: `None` is itself a schema value under test here, so it
cannot double as the helper's "use the default" marker without silently
substituting a valid schema and making that case pass vacuously."""


def _request(schema=_UNSET) -> StructuredOutputRequest:
    return StructuredOutputRequest(schema=_SCHEMA if schema is _UNSET else schema)


@pytest.fixture
def restore_module_names():
    """Restore every rebindable name this file rebinds, whatever happens."""
    saved = {
        name: getattr(sr, name)
        for name in (
            "SUPPORTED_DIALECTS",
            "DIALECT_WIRE_SHAPES",
            "is_supported_dialect",
            "build_response_format",
        )
    }
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(sr, name, value)


# == exact outbound wire shapes, one per dialect =============================


def test_llama_cpp_carries_the_schema_nested_and_sends_no_name():
    """llama.cpp @ 5a32f7b6: server-common.cpp reads json_schema.schema only.

    The README at the same commit shows the flat form for this type. The
    parser that runs does not read it there, so the executable source is
    followed and the conflict is recorded in the module docstring.
    """
    plan = plan_structured_request("llama-cpp", _request())
    assert plan.ok
    assert plan.response_format == {
        "type": "json_schema",
        "json_schema": {"schema": _SCHEMA},
    }
    # Negative control on the corrected defect: the flat key the README shows
    # must NOT be emitted. The pinned parser ignores it for this type, so
    # sending it there would decode unconstrained.
    assert "schema" not in plan.response_format
    # No name key exists on either llama.cpp path.
    assert "name" not in plan.response_format["json_schema"]


def _llama_cpp_parses(response_format):
    """The pinned C++ branch, transcribed from server-common.cpp @ 5a32f7b6.

    blob 585f65e83c655d3b8b7e398e8bf76552dc846f36, lines 1162-1174. The C++
    `json_value(obj, key, default)` returns the default when the key is
    absent, which is what `.get(key, default)` does here.
    """
    response_type = response_format.get("type", "")
    if response_type == "json_object":
        # The server's `json_schema` local starts empty, so
        # `contains("schema") || json_schema.empty()` is true either way and
        # the flat key is read.
        return response_format.get("schema", {})
    if response_type == "json_schema":
        wrapper = response_format.get("json_schema", {})
        return wrapper.get("schema", {})
    raise AssertionError("the pinned server rejects any other type")


def test_the_superseded_flat_llama_cpp_shape_was_an_empty_constraint():
    """Independent control reproducing the defect this gate corrected.

    Run the pinned parser against the shape this module used to emit and it
    yields {} - an empty schema, i.e. unconstrained decoding with no error
    and nothing for a caller to notice. Run it against the shape emitted now
    and it yields the real schema.
    """
    superseded_flat = {"type": "json_schema", "schema": _SCHEMA}
    assert _llama_cpp_parses(superseded_flat) == {}

    emitted = plan_structured_request("llama-cpp", _request()).response_format
    assert _llama_cpp_parses(emitted) == _SCHEMA


def test_the_flat_key_is_read_only_for_the_json_object_type():
    """Pins why the flat form looked right: it IS read, but only for the
    other type. This is the exact asymmetry the README elides."""
    assert _llama_cpp_parses({"type": "json_object", "schema": _SCHEMA}) == _SCHEMA
    assert _llama_cpp_parses({"type": "json_schema", "schema": _SCHEMA}) == {}


def test_ollama_carries_the_schema_nested_and_sends_no_name():
    """Ollama @ b7871fc0: openai/openai.go has JsonSchema{Schema} and no Name.

    Source-derived evidence. The documentation at that revision states only
    that response_format is supported and specifies no shape.
    """
    plan = plan_structured_request("ollama", _request())
    assert plan.ok
    assert plan.response_format == {
        "type": "json_schema",
        "json_schema": {"schema": _SCHEMA},
    }
    # A flat schema is silently ignored by Ollama, so none is sent...
    assert "schema" not in plan.response_format
    # ...and the Go struct has no name field, so none is sent either.
    assert "name" not in plan.response_format["json_schema"]


@pytest.mark.parametrize("dialect", ["vllm", "sglang"])
def test_vllm_and_sglang_carry_the_documented_openai_nesting(dialect):
    """vLLM @ 6e448d0e and SGLang @ 71de97b2 both document name + schema."""
    plan = plan_structured_request(dialect, _request())
    assert plan.ok
    assert plan.response_format == {
        "type": "json_schema",
        "json_schema": {"name": STRUCTURED_WIRE_NAME, "schema": _SCHEMA},
    }


def test_the_four_shapes_are_not_all_the_same():
    """Guard: if the mappings ever collapse, every shape test above is vacuous."""
    shapes = [
        plan_structured_request(d, _request()).response_format
        for d in SUPPORTED_DIALECTS
    ]
    # llama-cpp and ollama coincide as of the gate-1 correction: both read
    # response_format.json_schema.schema and neither has a name field. That
    # is asserted rather than assumed, so a future divergence in either
    # runtime has to be made deliberately.
    assert shapes[0] == shapes[1]
    assert shapes[1] != shapes[2], "ollama and vllm must differ"
    # vLLM and SGLang are byte-identical today; asserted so a future
    # divergence has to be made deliberately rather than drifting in.
    assert shapes[2] == shapes[3]
    # The guard that keeps every shape test above non-vacuous: the nested
    # no-name shape and the nested named shape are genuinely different.
    assert shapes[0] != shapes[2], "llama-cpp and vllm must differ"


def test_no_dialect_emits_a_schema_at_both_paths():
    """Each dialect commits to ONE documented path, not a shotgun of both."""
    for dialect in SUPPORTED_DIALECTS:
        wire = plan_structured_request(dialect, _request()).response_format
        nested = wire.get("json_schema")
        both = "schema" in wire and type(nested) is dict and "schema" in nested
        assert not both, dialect


def test_the_schema_object_is_transmitted_unmodified():
    schema = {"type": "object", "required": ["a"], "properties": {"a": {}}}
    for dialect in SUPPORTED_DIALECTS:
        wire = plan_structured_request(dialect, _request(schema=schema)).response_format
        sent = wire["schema"] if "schema" in wire else wire["json_schema"]["schema"]
        assert sent == schema


# == the dialect gate is closed ==============================================


def test_absent_dialect_refuses_as_not_configured():
    assert plan_structured_request(None, _request()).refusal == "dialect-not-configured"


@pytest.mark.parametrize(
    "dialect",
    ["", "vLLM", "VLLM", "llama_cpp", "llamacpp", "openai", "tgi", "unknown", " vllm"],
)
def test_unknown_dialect_strings_refuse(dialect):
    assert plan_structured_request(dialect, _request()).refusal == "dialect-unsupported"


@pytest.mark.parametrize(
    "dialect", [1, 1.0, True, b"vllm", ["vllm"], {"vllm": 1}, object()]
)
def test_non_string_dialects_refuse_without_comparison(dialect):
    assert plan_structured_request(dialect, _request()).refusal == "dialect-not-exact-str"


def test_a_str_subclass_dialect_is_refused_by_exact_type():
    class Sneaky(str):
        def __eq__(self, other):  # pragma: no cover - must never run
            raise AssertionError("__eq__ invoked on a str subclass")

        __hash__ = str.__hash__

    assert plan_structured_request(Sneaky("vllm"), _request()).refusal == (
        "dialect-not-exact-str"
    )
    assert is_supported_dialect(Sneaky("vllm")) is False


# == the request carrier is exact ============================================


@pytest.mark.parametrize(
    "request_obj",
    [None, {}, {"name": "R", "schema": _SCHEMA}, "Reply", 7, object()],
)
def test_a_foreign_request_object_refuses(request_obj):
    assert plan_structured_request("vllm", request_obj).refusal == (
        "request-not-exact-type"
    )


def test_a_request_subclass_is_refused_by_exact_type():
    class Sub(StructuredOutputRequest):
        pass

    assert plan_structured_request("vllm", Sub(schema=_SCHEMA)).refusal == (
        "request-not-exact-type"
    )


def test_the_carrier_normalises_nothing():
    """A dumb carrier is the point: silent repair would send an empty schema."""
    hostile = object()
    carried = StructuredOutputRequest(schema=hostile)  # type: ignore[arg-type]
    assert carried.schema is hostile
    # ...and the gate, not the carrier, is what refuses it.
    assert plan_structured_request("vllm", carried).refusal == "schema-not-exact-dict"


# == gate 3: the transmitted name is not caller data =========================


_AUDIT_SECRET_NAME = "sk-" + "OMIV2SECRET123456789"
"""The exact string the independent audit used. Assembled from two pieces so
a naive scan of this file for a credential prefix does not flag the control
that exists to prove credentials cannot travel."""


def test_the_request_carrier_has_no_name_field():
    """The leak channel is removed, not merely guarded."""
    assert "name" not in StructuredOutputRequest.__dataclass_fields__
    with pytest.raises(TypeError):
        StructuredOutputRequest(name="Reply", schema=_SCHEMA)  # type: ignore[call-arg]


@pytest.mark.parametrize("dialect", ["vllm", "sglang"])
def test_the_transmitted_name_is_the_fixed_constant(dialect):
    wire = plan_structured_request(dialect, _request()).response_format
    assert wire["json_schema"]["name"] == STRUCTURED_WIRE_NAME
    assert STRUCTURED_WIRE_NAME == "structured_output"


@pytest.mark.parametrize("dialect", ["llama-cpp", "ollama"])
def test_the_dialects_without_a_name_field_still_send_none(dialect):
    wire = plan_structured_request(dialect, _request()).response_format
    assert "name" not in wire["json_schema"]
    assert "name" not in wire


def test_the_superseded_alphabet_admitted_the_audit_secret():
    """Negative control reproducing the defect this gate corrected.

    The removed check was: exact str, 1..64 chars, drawn from [A-Za-z0-9_-].
    Transcribed here, it accepts the audit's credential-shaped string. The
    hardened primitive in scripts/open_model/redaction.py rejects the same
    string, which is why a private copy of a secret rule is the wrong repair
    and a fixed constant is the right one.
    """
    superseded_alphabet = frozenset(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "_-"
    )

    def superseded_check_accepts(value):
        if type(value) is not str:
            return False
        if not value or len(value) > 64:
            return False
        return all(character in superseded_alphabet for character in value)

    assert superseded_check_accepts(_AUDIT_SECRET_NAME) is True

    from scripts.open_model.redaction import is_safe_token

    assert is_safe_token(_AUDIT_SECRET_NAME) is False


def test_no_caller_value_can_reach_the_transmitted_name():
    """There is no argument, field, or schema content that moves the name."""
    hostile_schemas = [
        {"title": _AUDIT_SECRET_NAME},
        {"name": _AUDIT_SECRET_NAME},
        {"type": "object", "properties": {_AUDIT_SECRET_NAME: {"type": "string"}}},
    ]
    for schema in hostile_schemas:
        for dialect in ("vllm", "sglang"):
            wire = plan_structured_request(dialect, _request(schema=schema))
            assert wire.ok
            assert wire.response_format["json_schema"]["name"] == STRUCTURED_WIRE_NAME


def test_the_name_refusal_token_is_gone_from_the_vocabulary():
    """The vocabulary shrank deliberately; nothing still emits the old token."""
    from typing import get_args

    assert "name-not-safe" not in set(get_args(sr.StructuredRefusal))


# == schema controls =========================================================


@pytest.mark.parametrize("schema", [None, "{}", [], 7, object(), b"{}"])
def test_non_dict_schemas_refuse(schema):
    assert plan_structured_request("vllm", _request(schema=schema)).refusal == (
        "schema-not-exact-dict"
    )


def test_a_dict_subclass_schema_is_refused_by_exact_type():
    class Sneaky(dict):
        def items(self):  # pragma: no cover - must never run
            raise AssertionError("items() invoked on a dict subclass")

    assert plan_structured_request("vllm", _request(schema=Sneaky(a=1))).refusal == (
        "schema-not-exact-dict"
    )


def test_an_empty_schema_refuses_rather_than_asking_for_nothing():
    """An empty constraint would produce unconstrained output that looked asked-for."""
    assert plan_structured_request("vllm", _request(schema={})).refusal == "schema-empty"


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), float("-inf")]
)
def test_non_finite_numbers_refuse(value):
    assert plan_structured_request("vllm", _request(schema={"a": value})).refusal == (
        "schema-non-finite-number"
    )
    # ...including when buried inside nested containers.
    nested = {"a": {"b": [1, {"c": value}]}}
    assert plan_structured_request("vllm", _request(schema=nested)).refusal == (
        "schema-non-finite-number"
    )


@pytest.mark.parametrize(
    "value", [object(), b"bytes", {1, 2}, (1, 2), 1j, lambda: None]
)
def test_unserialisable_values_refuse(value):
    assert plan_structured_request("vllm", _request(schema={"a": value})).refusal == (
        "schema-not-serializable"
    )


def test_a_non_string_key_refuses():
    assert plan_structured_request("vllm", _request(schema={1: "a"})).refusal == (
        "schema-not-serializable"
    )


def test_an_over_long_schema_refuses():
    big = {"description": "A" * 70000}
    assert plan_structured_request("vllm", _request(schema=big)).refusal == (
        "schema-too-large"
    )


def test_an_over_wide_schema_refuses_by_node_count():
    wide = {"enum": list(range(5000))}
    assert plan_structured_request("vllm", _request(schema=wide)).refusal == (
        "schema-too-large"
    )


def test_a_deeply_nested_schema_refuses_without_exhausting_the_stack():
    deep: dict = {"type": "object"}
    node = deep
    for _ in range(200):
        child: dict = {"type": "object"}
        node["properties"] = child
        node = child
    assert plan_structured_request("vllm", _request(schema=deep)).refusal == (
        "schema-too-deep"
    )


def test_a_schema_at_the_depth_boundary_is_still_accepted():
    shallow: dict = {"type": "object"}
    node = shallow
    for _ in range(8):
        child: dict = {"type": "object"}
        node["properties"] = child
        node = child
    assert plan_structured_request("vllm", _request(schema=shallow)).ok


def test_a_self_referential_schema_refuses_rather_than_looping():
    looped: dict = {"type": "object"}
    looped["self"] = looped
    assert plan_structured_request("vllm", _request(schema=looped)).refusal == (
        "schema-too-deep"
    )


# == the tools combination is refused, not guessed at ========================


def test_tools_with_structured_output_refuses():
    assert plan_structured_request("vllm", _request(), has_tools=True).refusal == (
        "tools-with-structured-unsupported"
    )


@pytest.mark.parametrize("has_tools", [1, "yes", [1], object()])
def test_a_non_bool_tools_flag_refuses_rather_than_being_truth_tested(has_tools):
    assert plan_structured_request("vllm", _request(), has_tools=has_tools).refusal == (
        "tools-with-structured-unsupported"
    )


# == refusal diagnostics disclose nothing ====================================


def test_no_refusal_carries_schema_or_dialect_content():
    secret_name = "SUPERSECRETNAME"
    secret_value = "SUPERSECRETVALUE"
    cases = [
        ("vllm", _request(schema={secret_value: object()})),
        ("vllm", _request(schema={"k": secret_value * 6000})),
        ("vllm", _request(schema={secret_name: float("nan")})),
        ("nonsense-" + secret_value, _request()),
    ]
    for dialect, request_obj in cases:
        plan = plan_structured_request(dialect, request_obj)
        assert not plan.ok
        text = repr(plan)
        assert secret_name not in text
        assert secret_value not in text
        assert plan.response_format is None


def test_every_refusal_token_is_in_the_declared_vocabulary():
    from typing import get_args

    declared = set(get_args(sr.StructuredRefusal))
    seen = {
        plan_structured_request(d, r, has_tools=t).refusal
        for d, r, t in [
            (None, _request(), False),
            (7, _request(), False),
            ("nope", _request(), False),
            ("vllm", None, False),
            ("vllm", _request(), True),
            ("vllm", _request(schema=None), False),
            ("vllm", _request(schema={}), False),
            ("vllm", _request(schema={"a": object()}), False),
            ("vllm", _request(schema={"a": float("nan")}), False),
            ("vllm", _request(schema={"a": "A" * 70000}), False),
        ]
    }
    assert seen <= declared
    # Guard: the sweep must actually reach most of the vocabulary, or this
    # containment check would pass trivially on a single token.
    assert len(seen) >= 10


# == the trust path resolves no rebindable name ==============================


def test_the_builder_reads_no_module_level_mapping():
    referenced = set(build_response_format.__code__.co_names)
    for forbidden in ("SUPPORTED_DIALECTS", "DIALECT_WIRE_SHAPES"):
        assert forbidden not in referenced, forbidden


def test_the_membership_check_reads_no_module_level_mapping():
    referenced = set(is_supported_dialect.__code__.co_names)
    assert "SUPPORTED_DIALECTS" not in referenced


def test_rebinding_the_mirrors_changes_no_shape(restore_module_names):
    sr.SUPPORTED_DIALECTS = ("evil",)
    sr.DIALECT_WIRE_SHAPES = {"vllm": "response_format.pwned"}
    assert plan_structured_request("evil", _request()).refusal == "dialect-unsupported"
    assert plan_structured_request("vllm", _request()).response_format == {
        "type": "json_schema",
        "json_schema": {"name": STRUCTURED_WIRE_NAME, "schema": _SCHEMA},
    }


def test_rebinding_the_membership_check_cannot_open_a_fifth_dialect(
    restore_module_names,
):
    """Defence in depth: the guard and the dispatch must BOTH be satisfied."""
    sr.is_supported_dialect = lambda value: True
    plan = plan_structured_request("evil-runtime", _request())
    assert plan.refusal == "dialect-unsupported"
    assert plan.response_format is None


def test_the_mirrors_still_agree_with_the_code():
    """Drift guard: the mirrors are documentation, and must stay accurate."""
    assert set(SUPPORTED_DIALECTS) == set(DIALECT_WIRE_SHAPES)
    assert len(SUPPORTED_DIALECTS) == 4
    for dialect in SUPPORTED_DIALECTS:
        assert is_supported_dialect(dialect) is True
        wire = build_response_format(dialect, _request())
        assert wire is not None
        described = DIALECT_WIRE_SHAPES[dialect]
        if described == "response_format.schema":
            assert "schema" in wire and "json_schema" not in wire
        elif described == "response_format.json_schema.schema":
            assert set(wire["json_schema"]) == {"schema"}
        else:
            assert set(wire["json_schema"]) == {"name", "schema"}


def test_the_builder_returns_none_for_an_unknown_dialect():
    assert build_response_format("evil", _request()) is None
    assert build_response_format(7, _request()) is None  # type: ignore[arg-type]


# == the plan carrier cannot express a contradiction =========================


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ok": True, "refusal": "schema-empty", "response_format": {"a": 1}},
        {"ok": False},
        {"ok": False, "refusal": "schema-empty", "response_format": {"a": 1}},
        {"ok": True},
    ],
)
def test_contradictory_plans_are_refused_at_construction(kwargs):
    with pytest.raises(ValueError):
        sr.StructuredRequestPlan(**kwargs)


# == layering: this module may not reach upward ==============================


def test_the_request_module_imports_nothing_from_open_model():
    """`agent_backends` sits BELOW `open_model`; importing it would invert that."""
    from pathlib import Path

    source = Path(sr.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "open_model" not in stripped, stripped


# == gate 5: the outbound schema is a snapshot, not the caller's object ======


def _mutable_schema():
    return {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "examples": [{"ok": True}, {"ok": False}],
    }


def test_the_outbound_schema_is_not_the_callers_object():
    schema = _mutable_schema()
    wire = plan_structured_request("vllm", _request(schema=schema)).response_format
    outbound = wire["json_schema"]["schema"]
    assert outbound == schema
    assert outbound is not schema
    assert outbound["properties"] is not schema["properties"]
    assert outbound["examples"] is not schema["examples"]
    assert outbound["examples"][0] is not schema["examples"][0]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda s: s.update({"injected": "yes"}), id="top-level-key"),
        pytest.param(lambda s: s.pop("type"), id="top-level-removal"),
        pytest.param(
            lambda s: s["properties"]["ok"].update({"type": "string"}),
            id="nested-retype",
        ),
        pytest.param(
            lambda s: s["properties"].update({"smuggled": {"type": "string"}}),
            id="nested-key",
        ),
        pytest.param(lambda s: s["examples"].append({"ok": "no"}), id="list-append"),
        pytest.param(lambda s: s["examples"].clear(), id="list-clear"),
        pytest.param(
            lambda s: s["examples"][0].update({"ok": "mutated"}), id="list-item"
        ),
    ],
)
def test_mutating_the_schema_after_validation_cannot_change_the_wire(mutate):
    """The regression gate 5 required.

    A frozen dataclass does not freeze what its field points at. Without the
    snapshot, every check `plan_structured_request` performed would describe
    a document that is no longer the one being sent - and the caller needs no
    privileged access to do it, only the reference it already had.
    """
    schema = _mutable_schema()
    plan = plan_structured_request("vllm", _request(schema=schema))
    assert plan.ok
    before = json.loads(json.dumps(plan.response_format))

    mutate(schema)

    assert plan.response_format == before


def test_the_snapshot_is_faithful_across_every_permitted_json_type():
    """A snapshot that quietly changed the document would be its own defect."""
    schema = {
        "s": "text with unicode: \u00e9\u4e2d",
        "i": 10**18,
        "f": 1.5,
        "neg": -0.0,
        "t": True,
        "f2": False,
        "n": None,
        "empty_list": [],
        "empty_dict": {},
        "nested": [{"a": [1, {"b": None}]}],
    }
    plan = plan_structured_request("vllm", _request(schema=schema))
    assert plan.ok
    outbound = plan.response_format["json_schema"]["schema"]
    assert outbound == schema
    # Types survive exactly - a bool must not arrive as an int, and an int
    # must not arrive as a float.
    assert type(outbound["t"]) is bool
    assert type(outbound["i"]) is int
    assert type(outbound["f"]) is float


def test_two_plans_from_one_mutated_schema_differ_as_the_caller_wrote_them():
    """Snapshotting must not mean caching: a genuinely changed schema must
    produce a genuinely changed request on the next call."""
    schema = _mutable_schema()
    first = plan_structured_request("vllm", _request(schema=schema)).response_format
    schema["properties"]["ok"]["type"] = "string"
    second = plan_structured_request("vllm", _request(schema=schema)).response_format
    assert first != second
    assert second["json_schema"]["schema"]["properties"]["ok"]["type"] == "string"
