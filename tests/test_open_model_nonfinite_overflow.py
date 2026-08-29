"""OMI-V1 - the inbound non-finite gap: overflow literals must be refused.

``validate_structured_output`` has always refused the ``NaN`` / ``Infinity`` /
``-Infinity`` tokens through its ``parse_constant`` hook. But Python's decoder
builds every other number with ``float(token)``, which maps an overflowing
literal such as ``1e400`` to an infinity rather than raising - so before this
correction the *spelling* decided the outcome: ``{"x": Infinity}`` was refused
as ``non-finite-number`` while ``{"x": 1e400}`` was accepted carrying
``float("inf")`` into a successful outcome, through the OMI-V2 exchange, and
into any consumer trusting the refusal vocabulary.

These tests pin the corrected behavior: acceptance is decided by the value's
finiteness, never by its spelling. They also pin what must NOT move - finite
boundaries, integer handling, the established refusal codes, and the first-
failure-wins ordering that the correction makes visible for payloads carrying
both an overflow and another defect.
"""

from __future__ import annotations

import json
import math
import socket
from types import SimpleNamespace

import pytest

from scripts.agent_backends.base import Message
from scripts.agent_backends.openai_compat_backend import OpenAICompatBackend
from scripts.agent_backends.structured_request import StructuredOutputRequest
from scripts.open_model.structured import validate_structured_output
from scripts.open_model.structured_exchange import request_structured_json


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("a socket was created during a hermetic test")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# -- 1. overflow literals are refused ----------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        '{"x": 1e400}',
        '{"x": -1e400}',
        '{"x": 1e309}',
        '{"x": 1.8e308}',
        '{"x": -2e308}',
        '{"x": 123456789e999999999}',
    ],
)
def test_an_overflowing_literal_is_refused_as_non_finite(payload):
    outcome = validate_structured_output(payload)
    assert outcome.ok is False
    assert outcome.failure == "non-finite-number"
    assert outcome.value is None


# -- 2. nesting is no escape --------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        '{"a": {"b": 1e400}}',
        '{"a": [1e400]}',
        '{"a": {"b": [{"c": [-1e400]}]}}',
        '{"a": [0, 1, {"deep": {"deeper": 1e309}}]}',
    ],
)
def test_a_nested_overflowing_literal_is_refused(payload):
    outcome = validate_structured_output(payload)
    assert outcome.ok is False
    assert outcome.failure == "non-finite-number"


# -- 3. the finite boundary is preserved exactly -------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ('{"x": 1.7976931348623157e308}', 1.7976931348623157e308),  # max finite
        ('{"x": -1.7976931348623157e308}', -1.7976931348623157e308),
        ('{"x": 9e307}', 9e307),
        ('{"x": 0.5}', 0.5),
        ('{"x": 1e10}', 1e10),
        # Underflow rounds to 0.0: finite, and accepted unchanged. The guard is
        # against non-finiteness, not against extreme exponents in general.
        ('{"x": 1e-400}', 0.0),
    ],
)
def test_a_finite_float_is_accepted_unchanged(payload, expected):
    outcome = validate_structured_output(payload)
    assert outcome.ok is True
    value = outcome.value["x"]
    assert type(value) is float
    assert value == expected
    assert math.isfinite(value)


def test_integers_are_untouched_by_the_float_guard():
    # Integer literals never pass through `parse_float`; Python ints do not
    # overflow, so magnitude alone must not trip the finiteness refusal.
    outcome = validate_structured_output('{"x": 10000000000000000000000000000}')
    assert outcome.ok is True
    assert type(outcome.value["x"]) is int
    assert outcome.value["x"] == 10**28


# -- 4. what validation accepts, strict JSON can render ------------------------


def test_an_accepted_object_round_trips_as_strict_json():
    """Before the correction this property failed at the first step: an
    accepted ``1e400`` rendered under ``allow_nan=False`` raised, and under the
    default it rendered as the ``Infinity`` token this validator refuses."""
    payload = '{"x": 9e307, "y": [1.5, {"z": -2.25e-5}], "w": 3}'
    outcome = validate_structured_output(payload)
    assert outcome.ok is True
    rendered = json.dumps(dict(outcome.value), allow_nan=False)
    again = validate_structured_output(rendered)
    assert again.ok is True
    assert dict(again.value) == dict(outcome.value)


# -- 5. established refusals and controls are unchanged ------------------------


@pytest.mark.parametrize(
    "payload,failure",
    [
        ('{"a": NaN}', "non-finite-number"),
        ('{"a": Infinity}', "non-finite-number"),
        ('{"a": -Infinity}', "non-finite-number"),
        ('{"ok": false, "ok": true}', "duplicate-key"),
        ("42", "not-json-object"),
        ("[1.5]", "not-json-object"),
        ('{"unclosed": ', "invalid-json"),
    ],
)
def test_established_refusal_codes_are_unchanged(payload, failure):
    outcome = validate_structured_output(payload)
    assert outcome.ok is False
    assert outcome.failure == failure


@pytest.mark.parametrize(
    "payload",
    [
        # An overflow beside a duplicated key: the decoder meets the number
        # while the object is still open, so the non-finite refusal wins under
        # the documented first-failure-wins ordering. Both spellings refuse;
        # only the code differs from a duplicate-only payload.
        '{"x": 1e400, "x": 1}',
        # A bare overflow at the top level: the decoder refusal now precedes
        # the top-level-object check, exactly as a bare ``Infinity`` always
        # did. A bare finite number still reads ``not-json-object`` above.
        "1e400",
        "[1e400]",
    ],
)
def test_an_overflow_beside_another_defect_still_refuses_non_finite(payload):
    outcome = validate_structured_output(payload)
    assert outcome.ok is False
    assert outcome.failure == "non-finite-number"


# -- 6. the OMI-V2 exchange no longer carries a non-finite success -------------


class _Client:
    """Canned OpenAI-compat client; shape mirrors tests/test_omi_v2_exchange.py."""

    def __init__(self, text):
        self._text = text
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._text, tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )


def _exchange(text):
    backend = OpenAICompatBackend(model="m", client=_Client(text), dialect="vllm")
    return request_structured_json(
        backend,
        [Message(role="user", content="hello")],
        [],
        structured=StructuredOutputRequest(
            schema={"type": "object", "properties": {"answer": {"type": "number"}}}
        ),
        required_keys=("answer",),
    )


def test_the_exchange_refuses_an_overflowing_response():
    result = _exchange('{"answer": 1e400}')
    assert result.ok is False
    assert result.response_failure == "non-finite-number"
    assert result.value is None


def test_the_exchange_still_accepts_a_finite_response():
    result = _exchange('{"answer": 42.5}')
    assert result.ok is True
    assert result.value["answer"] == 42.5
