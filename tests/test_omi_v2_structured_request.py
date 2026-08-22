"""OMI-V2 - controls on the closed structured-output request contract.

Covers the four dialect wire shapes against the evidence pinned in
``scripts/agent_backends/structured_request.py``, and the negative controls
that must refuse before anything is built.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pytest

from scripts.agent_backends import structured_request as sr
from scripts.agent_backends.structured_request import (
    DIALECT_WIRE_SHAPES,
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


def _request(name: str = "Reply", schema=_UNSET) -> StructuredOutputRequest:
    return StructuredOutputRequest(
        name=name, schema=_SCHEMA if schema is _UNSET else schema
    )


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


def test_llama_cpp_carries_the_schema_flat_and_sends_no_name():
    """llama.cpp @ 5a32f7b6: tools/server/README.md documents the flat form."""
    plan = plan_structured_request("llama-cpp", _request())
    assert plan.ok
    assert plan.response_format == {"type": "json_schema", "schema": _SCHEMA}
    # The flat form is the whole object: no nesting, and no name key exists
    # anywhere in llama.cpp's documented response_format.
    assert "json_schema" not in plan.response_format
    assert "name" not in plan.response_format


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
    plan = plan_structured_request(dialect, _request(name="Reply"))
    assert plan.ok
    assert plan.response_format == {
        "type": "json_schema",
        "json_schema": {"name": "Reply", "schema": _SCHEMA},
    }


def test_the_four_shapes_are_not_all_the_same():
    """Guard: if the mappings ever collapse, every shape test above is vacuous."""
    shapes = [
        plan_structured_request(d, _request()).response_format
        for d in SUPPORTED_DIALECTS
    ]
    assert shapes[0] != shapes[1], "llama-cpp and ollama must differ"
    assert shapes[1] != shapes[2], "ollama and vllm must differ"
    # vLLM and SGLang are byte-identical today; asserted so a future
    # divergence has to be made deliberately rather than drifting in.
    assert shapes[2] == shapes[3]


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

    assert plan_structured_request("vllm", Sub(name="R", schema=_SCHEMA)).refusal == (
        "request-not-exact-type"
    )


def test_the_carrier_normalises_nothing():
    """A dumb carrier is the point: silent repair would send an empty schema."""
    hostile = object()
    carried = StructuredOutputRequest(name=hostile, schema=hostile)  # type: ignore[arg-type]
    assert carried.name is hostile
    assert carried.schema is hostile
    # ...and the gate, not the carrier, is what refuses it.
    assert plan_structured_request("vllm", carried).refusal == "name-not-safe"


# == name controls ===========================================================


@pytest.mark.parametrize(
    "name",
    [
        "",
        "A" * 65,
        "has space",
        "has.dot",
        "has/slash",
        "has:colon",
        "sk-secretlooking!",
        "naïve",
        chr(32) + "leading",
        "trailing" + chr(32),
        "tab" + chr(9) + "bed",
        "new" + chr(10) + "line",
    ],
)
def test_unsafe_names_refuse(name):
    assert plan_structured_request("vllm", _request(name=name)).refusal == "name-not-safe"


@pytest.mark.parametrize("name", [None, 1, b"Reply", ["Reply"], object()])
def test_non_string_names_refuse(name):
    assert plan_structured_request("vllm", _request(name=name)).refusal == "name-not-safe"


@pytest.mark.parametrize("name", ["A", "Reply", "reply_v2", "a-b_c", "A" * 64, "0"])
def test_safe_names_are_accepted(name):
    assert plan_structured_request("vllm", _request(name=name)).ok


def test_the_name_boundary_is_exact():
    assert plan_structured_request("vllm", _request(name="A" * 64)).ok
    assert plan_structured_request("vllm", _request(name="A" * 65)).refusal == (
        "name-not-safe"
    )


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


def test_no_refusal_carries_schema_or_name_content():
    secret_name = "SUPERSECRETNAME"
    secret_value = "SUPERSECRETVALUE"
    cases = [
        ("vllm", _request(name=secret_name + "!", schema=_SCHEMA)),
        ("vllm", _request(name="R", schema={secret_value: object()})),
        ("vllm", _request(name="R", schema={"k": secret_value * 6000})),
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
            ("vllm", _request(name=""), False),
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
    assert len(seen) >= 9


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
        "json_schema": {"name": "Reply", "schema": _SCHEMA},
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
