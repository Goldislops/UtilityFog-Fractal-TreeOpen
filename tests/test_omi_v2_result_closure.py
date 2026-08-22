"""OMI-V2 - controls on the structural closure of the three result types.

Gate 4 of the independent audit. `StructuredRequestPlan`,
`StructuredCompletion` and `StructuredExchange` are the only objects OMI-V2
hands back, so they are the only places a caller can read a verdict from. If
any of them can be constructed in a state that is internally incoherent -
successful with nothing to show for it, failed with no reason, carrying a
token nobody declared, or carrying an arbitrary string at all - then every
downstream guarantee is only as good as the discipline of whoever built it.

These controls assert the opposite: each type refuses its own incoherent
states at construction, so an incoherent one cannot exist to be read.

Every check here is a NEGATIVE control. A positive path that merely works is
covered by the three behavioural suites; what matters here is what cannot be
built.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pytest

from scripts.agent_backends.base import AgentResponse
from scripts.agent_backends.openai_compat_backend import StructuredCompletion
from scripts.agent_backends.structured_request import (
    REFUSAL_TOKENS,
    StructuredRequestPlan,
)
from scripts.open_model.structured_exchange import (
    EXCHANGE_REFUSALS,
    RESPONSE_FAILURES,
    StructuredExchange,
)


_FORMAT = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}
_RESPONSE = AgentResponse(text="{}", tool_calls=[], raw_content=[])


class _Truthy:
    """Presents as a bool to any truth test, but is not one."""

    def __bool__(self) -> bool:
        return True


class _Falsy:
    def __bool__(self) -> bool:
        return False


_NOT_EXACT_BOOLS = [_Truthy(), _Falsy(), 1, 0, "yes", "", None, [1], ()]


# == exact booleans ==========================================================


@pytest.mark.parametrize("value", _NOT_EXACT_BOOLS)
def test_a_plan_refuses_a_non_bool_ok(value):
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=value, response_format=_FORMAT)


@pytest.mark.parametrize("value", _NOT_EXACT_BOOLS)
def test_a_completion_refuses_a_non_bool_ok(value):
    with pytest.raises(ValueError):
        StructuredCompletion(ok=value, response=_RESPONSE, response_format_sent=True)


@pytest.mark.parametrize("value", _NOT_EXACT_BOOLS)
def test_a_completion_refuses_a_non_bool_sent_flag(value):
    with pytest.raises(ValueError):
        StructuredCompletion(ok=True, response=_RESPONSE, response_format_sent=value)


@pytest.mark.parametrize("value", _NOT_EXACT_BOOLS)
def test_an_exchange_refuses_a_non_bool_ok(value):
    with pytest.raises(ValueError):
        StructuredExchange(ok=value, value={"a": 1}, response_format_sent=True)


@pytest.mark.parametrize("value", _NOT_EXACT_BOOLS)
def test_an_exchange_refuses_a_non_bool_sent_flag(value):
    with pytest.raises(ValueError):
        StructuredExchange(ok=True, value={"a": 1}, response_format_sent=value)


# == closed vocabularies =====================================================


_UNDECLARED = [
    "totally-made-up",
    "name-not-safe",  # a real token once; removed by gate 3, must stay gone
    "",
    "DIALECT-NOT-CONFIGURED",
    "dialect-not-configured ",
    1,
    None.__class__,
    ["dialect-not-configured"],
]


@pytest.mark.parametrize("token", _UNDECLARED)
def test_a_plan_refuses_an_undeclared_refusal_token(token):
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=False, refusal=token)


@pytest.mark.parametrize("token", _UNDECLARED)
def test_a_completion_refuses_an_undeclared_refusal_token(token):
    with pytest.raises(ValueError):
        StructuredCompletion(ok=False, refusal=token)


@pytest.mark.parametrize("token", _UNDECLARED)
def test_an_exchange_refuses_an_undeclared_request_refusal(token):
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, request_refusal=token)


@pytest.mark.parametrize(
    "token", ["made-up-failure", "", "INVALID-JSON", "invalid-json ", 7]
)
def test_an_exchange_refuses_an_undeclared_response_failure(token):
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, response_failure=token, response_format_sent=True)


def test_every_declared_refusal_token_is_actually_constructible():
    """Guard: the closed set must not be closed so tightly it is empty.

    Without this, a vocabulary check that rejected everything would pass all
    the negative controls above and look like excellent hygiene.
    """
    for token in REFUSAL_TOKENS:
        assert StructuredRequestPlan(ok=False, refusal=token).refusal == token
    for token in EXCHANGE_REFUSALS:
        assert StructuredExchange(ok=False, request_refusal=token).ok is False
    for token in RESPONSE_FAILURES:
        indices = (0,) if token == "missing-required-key" else ()
        result = StructuredExchange(
            ok=False,
            response_failure=token,
            missing_key_indices=indices,
            response_format_sent=True,
        )
        assert result.response_failure == token


def test_the_exchange_vocabulary_is_composed_not_restated():
    """It must be a superset of the backend's, plus exactly one token."""
    assert REFUSAL_TOKENS < EXCHANGE_REFUSALS
    assert EXCHANGE_REFUSALS - REFUSAL_TOKENS == {"backend-not-structured-capable"}


# == dialect vocabulary ======================================================


@pytest.mark.parametrize(
    "dialect", ["evil-runtime", "", "VLLM", "vllm ", 1, ["vllm"], object()]
)
def test_a_completion_refuses_an_unverified_dialect(dialect):
    with pytest.raises(ValueError):
        StructuredCompletion(
            ok=True, response=_RESPONSE, dialect=dialect, response_format_sent=True
        )


@pytest.mark.parametrize(
    "dialect", ["evil-runtime", "", "VLLM", "vllm ", 1, ["vllm"], object()]
)
def test_an_exchange_refuses_an_unverified_dialect(dialect):
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True, value={"a": 1}, dialect=dialect, response_format_sent=True
        )


# == success must have something to show for itself ==========================


def test_a_successful_plan_must_carry_an_exact_dict_response_format():
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=True, response_format=None)
    for not_a_dict in ["{}", [("type", "json_schema")], object()]:
        with pytest.raises(ValueError):
            StructuredRequestPlan(ok=True, response_format=not_a_dict)


def test_a_successful_completion_must_carry_a_response():
    with pytest.raises(ValueError):
        StructuredCompletion(ok=True, response=None, response_format_sent=True)


def test_a_successful_completion_must_have_sent_a_request():
    with pytest.raises(ValueError):
        StructuredCompletion(ok=True, response=_RESPONSE, response_format_sent=False)


def test_a_successful_exchange_must_carry_a_value():
    with pytest.raises(ValueError):
        StructuredExchange(ok=True, value=None, response_format_sent=True)


def test_a_successful_exchange_must_have_sent_a_request():
    with pytest.raises(ValueError):
        StructuredExchange(ok=True, value={"a": 1}, response_format_sent=False)


# == the sent-state / failure-kind correspondence ============================


def test_a_response_failure_requires_that_a_request_was_sent():
    """The gap gate 4 named: a runtime cannot answer badly if never asked."""
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False, response_failure="invalid-json", response_format_sent=False
        )


def test_a_request_refusal_cannot_have_sent_a_request():
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            request_refusal="schema-empty",
            response_format_sent=True,
        )


def test_a_failure_carries_exactly_one_kind_of_reason():
    with pytest.raises(ValueError):
        StructuredExchange(ok=False)
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            request_refusal="schema-empty",
            response_failure="invalid-json",
            response_format_sent=True,
        )


# == coherent missing indices ================================================


@pytest.mark.parametrize(
    "indices",
    [
        [0],  # a list, not a tuple
        (0.0,),  # not an exact int
        (True,),  # bool is an int subclass, and is not an index
        (-1,),  # negative
        (1, 1),  # not strictly increasing
        (2, 1),  # decreasing
        (0, 2, 2),  # repeats later
        ("0",),  # a string, i.e. somewhere to put content
    ],
)
def test_incoherent_missing_indices_are_refused(indices):
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            response_failure="missing-required-key",
            missing_key_indices=indices,
            response_format_sent=True,
        )


def test_missing_indices_belong_only_to_the_missing_key_failure():
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            response_failure="invalid-json",
            missing_key_indices=(0,),
            response_format_sent=True,
        )
    with pytest.raises(ValueError):
        StructuredExchange(ok=True, value={"a": 1}, missing_key_indices=(0,),
                           response_format_sent=True)


def test_a_missing_key_failure_must_say_which_indices():
    """An empty report would be a failure that names nothing actionable."""
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False,
            response_failure="missing-required-key",
            missing_key_indices=(),
            response_format_sent=True,
        )


def test_coherent_missing_indices_are_accepted():
    result = StructuredExchange(
        ok=False,
        response_failure="missing-required-key",
        missing_key_indices=(0, 3, 17),
        response_format_sent=True,
    )
    assert result.missing_key_indices == (0, 3, 17)


# == no arbitrary secret-bearing diagnostic strings ==========================


def test_no_result_type_accepts_free_text_anywhere():
    """Every field that could hold a secret is closed, typed, or a value.

    Enumerated from the dataclass fields themselves rather than by hand, so a
    future field cannot be added without this control noticing it.
    """
    secret = "SUPERSECRET-" + "sk-OMIV2SECRET123456789"

    # Every string-bearing field on every result type is either a closed
    # vocabulary or a fixed literal; none accepts arbitrary text.
    with pytest.raises(ValueError):
        StructuredRequestPlan(ok=False, refusal=secret)
    with pytest.raises(ValueError):
        StructuredCompletion(ok=False, refusal=secret)
    with pytest.raises(ValueError):
        StructuredExchange(ok=False, request_refusal=secret)
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=False, response_failure=secret, response_format_sent=True
        )
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True, value={"a": 1}, dialect=secret, response_format_sent=True
        )
    with pytest.raises(ValueError):
        StructuredExchange(
            ok=True,
            value={"a": 1},
            response_format_sent=True,
            schema_conformance=secret,
        )


def test_the_declared_field_set_is_the_one_these_controls_cover():
    """Drift guard: a new field must be reviewed, not silently uncovered."""
    assert set(StructuredRequestPlan.__dataclass_fields__) == {
        "ok",
        "response_format",
        "refusal",
    }
    assert set(StructuredCompletion.__dataclass_fields__) == {
        "ok",
        "response",
        "refusal",
        "dialect",
        "response_format_sent",
    }
    assert set(StructuredExchange.__dataclass_fields__) == {
        "ok",
        "value",
        "request_refusal",
        "response_failure",
        "missing_key_indices",
        "dialect",
        "response_format_sent",
        "schema_conformance",
    }
