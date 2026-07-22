"""Tests for scripts/params_schema.py (Phase 18, PR 1).

Verifies the schema framework and the initial parameter registry:
- TunableParam validation (type, bounds, category gating)
- LOCKED params always reject
- Proposal-level aggregate validation (collects all errors)
- Schema serialization
- Registry sanity: no duplicate names, every param has a valid group, every
  LOCKED param is listed in MEMORY.md's critical invariants (spirit check).
"""

from __future__ import annotations

import inspect

import pytest

from scripts.params_schema import (
    PARAMS,
    Category,
    ProposalValidation,
    TunableParam,
    ValidationError,
    get_param,
    groups,
    list_by_category,
    list_by_group,
    schema_as_dict,
    validate_proposal,
)


# -- TunableParam construction -----------------------------------------------


def test_tunable_param_construction_requires_bounds_for_numeric():
    with pytest.raises(ValueError, match="at least one bound"):
        TunableParam(
            name="foo",
            value_type=float,
            default=0.5,
            category=Category.AUTO,
            group="test",
            description="no bounds",
        )


def test_tunable_param_rejects_min_greater_than_max():
    with pytest.raises(ValueError, match="min_value > max_value"):
        TunableParam(
            name="foo",
            value_type=float,
            default=0.5,
            category=Category.AUTO,
            group="test",
            description="bad bounds",
            min_value=1.0,
            max_value=0.5,
        )


def test_tunable_param_rejects_unsupported_type():
    with pytest.raises(TypeError, match="bool/int/float"):
        TunableParam(
            name="foo",
            value_type=str,  # type: ignore[arg-type]
            default="x",
            category=Category.AUTO,
            group="test",
            description="bad type",
        )


def test_tunable_param_rejects_default_type_mismatch():
    with pytest.raises(TypeError, match="not of type"):
        TunableParam(
            name="foo",
            value_type=float,
            default="not-a-float",  # type: ignore[arg-type]
            category=Category.AUTO,
            group="test",
            description="bad default",
            min_value=0.0,
            max_value=1.0,
        )


# -- validate() on individual params -----------------------------------------


def _float_param(**kwargs) -> TunableParam:
    defaults = dict(
        name="x",
        value_type=float,
        default=0.5,
        category=Category.AUTO,
        group="test",
        description="x",
        min_value=0.0,
        max_value=1.0,
    )
    defaults.update(kwargs)
    return TunableParam(**defaults)


def test_validate_accepts_in_range_float():
    assert _float_param().validate(0.25).ok


def test_validate_rejects_below_min():
    result = _float_param(min_value=0.0).validate(-0.1)
    assert not result.ok
    assert result.error is ValidationError.BELOW_MIN


def test_validate_rejects_above_max():
    result = _float_param(max_value=1.0).validate(1.5)
    assert not result.ok
    assert result.error is ValidationError.ABOVE_MAX


def test_validate_rejects_wrong_type_for_float():
    result = _float_param().validate("string")
    assert not result.ok
    assert result.error is ValidationError.WRONG_TYPE


def test_validate_rejects_bool_for_float():
    """bool is a subclass of int, but we're strict: bool ≠ float."""
    result = _float_param().validate(True)
    assert not result.ok
    assert result.error is ValidationError.WRONG_TYPE


def test_validate_rejects_bool_for_int():
    p = TunableParam(
        name="n", value_type=int, default=1,
        category=Category.AUTO, group="test", description="n",
        min_value=0, max_value=10,
    )
    result = p.validate(True)
    assert not result.ok
    assert result.error is ValidationError.WRONG_TYPE


def test_validate_bool_param_accepts_true_and_false():
    p = TunableParam(
        name="enabled", value_type=bool, default=True,
        category=Category.AUTO, group="test", description="enabled",
    )
    assert p.validate(True).ok
    assert p.validate(False).ok
    assert not p.validate(1).ok


def test_locked_param_rejects_any_value():
    p = TunableParam(
        name="locked", value_type=float, default=0.005,
        category=Category.LOCKED, group="critical", description="locked",
        min_value=0.0, max_value=1.0,
    )
    result = p.validate(0.004)  # within bounds, but still locked
    assert not result.ok
    assert result.error is ValidationError.LOCKED


# -- proposal-level validation -----------------------------------------------


def test_validate_proposal_ok_for_valid_input():
    result = validate_proposal({"signal_interval": 12, "magnon_sage_age_min": 7.5})
    assert isinstance(result, ProposalValidation)
    assert result.ok
    assert set(result.known_params) == {"signal_interval", "magnon_sage_age_min"}
    assert result.unknown_params == []
    assert result.errors == {}


def test_validate_proposal_collects_all_errors():
    result = validate_proposal({
        "signal_interval": 0,                       # below min
        "magnon_coupling": "high",                  # wrong type
        "structural_to_void_decay_prob": 0.004,    # LOCKED
        "nonexistent_param": 42,                    # unknown
    })
    assert not result.ok
    assert set(result.errors) == {
        "signal_interval",
        "magnon_coupling",
        "structural_to_void_decay_prob",
        "nonexistent_param",
    }
    assert result.errors["signal_interval"].error is ValidationError.BELOW_MIN
    assert result.errors["magnon_coupling"].error is ValidationError.WRONG_TYPE
    assert result.errors["structural_to_void_decay_prob"].error is ValidationError.LOCKED
    assert result.errors["nonexistent_param"].error is ValidationError.UNKNOWN_PARAM
    assert "nonexistent_param" in result.unknown_params


def test_validate_proposal_empty_input_is_ok():
    result = validate_proposal({})
    assert result.ok


# -- registry sanity ---------------------------------------------------------


def test_registry_has_no_duplicates():
    # PARAMS is a dict, so duplicates at import time are impossible; this
    # also asserts the registry is populated.
    assert len(PARAMS) > 0


def test_registry_has_all_three_categories():
    assert len(list_by_category(Category.LOCKED)) >= 1
    assert len(list_by_category(Category.HUMAN_APPROVAL)) >= 1
    assert len(list_by_category(Category.AUTO)) >= 1


def test_registry_locks_structural_to_void_decay():
    """MEMORY.md Critical Invariants: this must be locked. Regression fence."""
    p = get_param("structural_to_void_decay_prob")
    assert p is not None
    assert p.category is Category.LOCKED


def test_registry_locks_energy_to_void_decay():
    p = get_param("energy_to_void_decay_prob")
    assert p is not None
    assert p.category is Category.LOCKED


def test_every_param_has_a_group():
    for name, p in PARAMS.items():
        assert p.group, f"{name} has empty group"


def test_groups_helper_returns_sorted_unique():
    gs = groups()
    assert gs == sorted(set(gs))
    # Sampling: known groups that must exist for the partial registry.
    assert "magnon" in gs
    assert "metta" in gs
    assert "stochastic" in gs


def test_list_by_group_roundtrip():
    for g in groups():
        for p in list_by_group(g):
            assert p.group == g


# -- schema serialization ----------------------------------------------------


def test_schema_as_dict_is_json_friendly():
    import json

    schema = schema_as_dict()
    # Must round-trip through JSON without custom encoders.
    buf = json.dumps(schema)
    loaded = json.loads(buf)
    assert loaded["version"] == 1
    assert "signal_interval" in loaded["params"]
    assert loaded["params"]["signal_interval"]["type"] == "int"
    assert loaded["params"]["signal_interval"]["category"] == "auto"
    assert "locked" in loaded["categories"]


def test_schema_dict_param_entries_have_required_keys():
    schema = schema_as_dict()
    required = {"name", "type", "default", "category", "group", "description",
                "min_value", "max_value"}
    for name, entry in schema["params"].items():
        assert required <= set(entry), f"{name} missing keys: {required - set(entry)}"


# -- Batch 5 — exact-value totality: hostile proposed values ------------------
#
# validate() must decide a proposed value by exact type(value) identity alone.
# A rejected value's methods, properties and metaclass must never run: not
# isinstance() (reads __class__), not type(value).__name__ (reads the
# metaclass), not bounds/float() on a subclass (runs __lt__/__float__).
# Each hostile below records every hook invocation; a passing test asserts
# the typed WRONG_TYPE result AND an empty call log.


def _int_param(**kwargs) -> TunableParam:
    defaults = dict(
        name="n",
        value_type=int,
        default=1,
        category=Category.AUTO,
        group="test",
        description="n",
        min_value=0,
        max_value=10,
    )
    defaults.update(kwargs)
    return TunableParam(**defaults)


def _bool_param(**kwargs) -> TunableParam:
    defaults = dict(
        name="enabled",
        value_type=bool,
        default=True,
        category=Category.AUTO,
        group="test",
        description="enabled",
    )
    defaults.update(kwargs)
    return TunableParam(**defaults)


def _hostile_name_value():
    """Value whose class-name lookup raises: type(v).__name__ consults the
    metaclass, so a hostile metaclass turns message formatting into a hook."""

    class Meta(type):
        calls: list[str] = []

        @property
        def __name__(cls):
            Meta.calls.append("__name__")
            raise RuntimeError("metaclass __name__ hook executed")

    bomb_cls = Meta("NameBomb", (), {})
    return bomb_cls(), Meta.calls


def _hostile_class_value():
    """Value whose __class__ property raises — isinstance() reads it whenever
    the exact-type fast path misses."""

    class ClassBomb:
        calls: list[str] = []

        @property
        def __class__(self):
            ClassBomb.calls.append("__class__")
            raise RuntimeError("__class__ hook executed")

    return ClassBomb(), ClassBomb.calls


def _hostile_int_subclass():
    """int subclass whose comparison and float-conversion hooks raise — the
    value the old isinstance() gate admitted to bounds/conversion."""

    class EvilInt(int):
        calls: list[str] = []

        def __lt__(self, other):
            EvilInt.calls.append("__lt__")
            raise RuntimeError("__lt__ hook executed")

        def __gt__(self, other):
            EvilInt.calls.append("__gt__")
            raise RuntimeError("__gt__ hook executed")

        def __le__(self, other):
            EvilInt.calls.append("__le__")
            raise RuntimeError("__le__ hook executed")

        def __ge__(self, other):
            EvilInt.calls.append("__ge__")
            raise RuntimeError("__ge__ hook executed")

        def __float__(self):
            EvilInt.calls.append("__float__")
            raise RuntimeError("__float__ hook executed")

        def __index__(self):
            EvilInt.calls.append("__index__")
            raise RuntimeError("__index__ hook executed")

    return EvilInt(5), EvilInt.calls


class _PlainIntSubclass(int):
    """Benign int subclass — exact-type totality refuses even quiet ones."""


class _PlainFloatSubclass(float):
    """Benign float subclass."""


def test_hostile_name_value_gets_typed_refusal_not_escape():
    for param, expected in [
        (_bool_param(), "enabled requires bool, got non-builtin value."),
        (_int_param(), "n requires int, got non-builtin value."),
        (_float_param(), "x requires float, got non-builtin value."),
    ]:
        value, calls = _hostile_name_value()
        result = param.validate(value)
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE
        assert result.message == expected
        assert calls == []


def test_hostile_class_value_gets_typed_refusal_not_escape():
    for param, expected in [
        (_bool_param(), "enabled requires bool, got non-builtin value."),
        (_int_param(), "n requires int, got non-builtin value."),
        (_float_param(), "x requires float, got non-builtin value."),
    ]:
        value, calls = _hostile_class_value()
        result = param.validate(value)
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE
        assert result.message == expected
        assert calls == []


def test_int_param_refuses_int_subclass_before_bounds():
    value, calls = _hostile_int_subclass()
    result = _int_param().validate(value)  # 5 is inside [0, 10] — type-only refusal
    assert not result.ok
    assert result.error is ValidationError.WRONG_TYPE
    assert result.message == "n requires int, got non-builtin value."
    assert calls == []


def test_float_param_refuses_int_subclass_before_conversion():
    value, calls = _hostile_int_subclass()
    result = _float_param().validate(value)
    assert not result.ok
    assert result.error is ValidationError.WRONG_TYPE
    assert result.message == "x requires float, got non-builtin value."
    assert calls == []


def test_benign_subclasses_are_refused_too():
    assert _int_param().validate(_PlainIntSubclass(5)).error is ValidationError.WRONG_TYPE
    assert _float_param().validate(_PlainIntSubclass(0)).error is ValidationError.WRONG_TYPE
    assert _float_param().validate(_PlainFloatSubclass(0.5)).error is ValidationError.WRONG_TYPE


def test_locked_param_refuses_before_inspecting_value():
    p = _float_param(category=Category.LOCKED)
    for factory in (_hostile_name_value, _hostile_class_value, _hostile_int_subclass):
        value, calls = factory()
        result = p.validate(value)
        assert not result.ok
        assert result.error is ValidationError.LOCKED
        assert calls == []


def test_bool_param_accepts_only_exact_bool():
    p = _bool_param()
    assert p.validate(True).ok
    assert p.validate(False).ok
    for bad in (1, 0, 1.0, "true", None, [], {}):
        result = p.validate(bad)
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE


def test_int_param_accepts_only_exact_int():
    p = _int_param()
    assert p.validate(5).ok
    for bad in (True, False, 5.0, "5", None):
        result = p.validate(bad)
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE


def test_float_param_accepts_exact_int_and_exact_float_only():
    p = _float_param()
    assert p.validate(0.25).ok
    assert p.validate(1).ok  # exact builtin int still converts
    for bad in (True, "0.5", None, [0.5], {"v": 0.5}):
        result = p.validate(bad)
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE


def test_builtin_json_value_messages_unchanged():
    assert _int_param().validate("x").message == "n requires int, got str."
    assert _int_param().validate(1.5).message == "n requires int, got float."
    assert _int_param().validate(True).message == "n requires int, got bool."
    assert _int_param().validate(None).message == "n requires int, got NoneType."
    assert _int_param().validate([1]).message == "n requires int, got list."
    assert _int_param().validate({}).message == "n requires int, got dict."
    assert _float_param().validate("x").message == "x requires float, got str."
    assert _bool_param().validate(1).message == "enabled requires bool, got int."


def test_float_param_int_conversion_and_bounds_retained():
    p = _float_param(min_value=0.0, max_value=1.0)
    result = p.validate(2)  # exact int converts, then trips the max bound
    assert not result.ok
    assert result.error is ValidationError.ABOVE_MAX
    assert result.message == "x=2.0 above max 1.0."


def test_validate_proposal_propagates_hostile_refusals():
    name_bomb, name_calls = _hostile_name_value()
    evil_int, evil_calls = _hostile_int_subclass()
    result = validate_proposal({
        "magnon_radius": evil_int,       # int param in the live registry
        "magnon_coupling": name_bomb,    # float param in the live registry
        "signal_interval": 12,           # valid alongside the hostiles
    })
    assert not result.ok
    assert set(result.errors) == {"magnon_radius", "magnon_coupling"}
    assert result.errors["magnon_radius"].error is ValidationError.WRONG_TYPE
    assert result.errors["magnon_coupling"].error is ValidationError.WRONG_TYPE
    assert set(result.known_params) == {
        "magnon_radius", "magnon_coupling", "signal_interval",
    }
    assert result.unknown_params == []
    assert name_calls == []
    assert evil_calls == []


def test_describe_type_is_hook_free_and_fixed():
    from scripts.params_schema import _describe_type

    assert _describe_type(True) == "bool"
    assert _describe_type(3) == "int"
    assert _describe_type(3.0) == "float"
    assert _describe_type("s") == "str"
    assert _describe_type(None) == "NoneType"
    assert _describe_type([]) == "list"
    assert _describe_type({}) == "dict"
    assert _describe_type(_PlainIntSubclass(3)) == "non-builtin value"
    for factory in (_hostile_name_value, _hostile_class_value):
        value, calls = factory()
        assert _describe_type(value) == "non-builtin value"
        assert calls == []


def test_validate_source_has_no_value_type_name_lookup():
    """The three former ``type(value).__name__`` sites must be gone, and no
    isinstance() may touch a proposed value."""
    src = inspect.getsource(TunableParam.validate)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    assert "type(value).__name__" not in code
    assert "isinstance" not in code


# -- follow-up: bounded float normalization (finite-value totality) -----------
#
# The exact-type gate proves a proposed float-param value is builtin int or
# float — but float() of an oversized int raises OverflowError, and NaN
# passes both inclusive bound comparisons. Normalization is now bounded:
# conversion failures and non-finite results get WRONG_TYPE with the
# supplied-value-free message "<name> requires a finite float value.";
# only finite normalized values reach the bound comparisons.

_OVERSIZED_INT = 10 ** 400
_FINITE_REFUSAL = "x requires a finite float value."


def test_float_param_refuses_oversized_int_without_raising():
    p = _float_param()
    for value in (_OVERSIZED_INT, -_OVERSIZED_INT):
        result = p.validate(value)  # must not raise OverflowError
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE
        assert result.message == _FINITE_REFUSAL


def test_float_param_refuses_nan_and_infinities():
    p = _float_param()
    for value in (float("nan"), float("inf"), float("-inf")):
        result = p.validate(value)
        assert not result.ok
        assert result.error is ValidationError.WRONG_TYPE
        assert result.message == _FINITE_REFUSAL


def test_finite_refusal_message_carries_no_supplied_value():
    digits = str(_OVERSIZED_INT)
    for value in (_OVERSIZED_INT, float("inf"), float("nan")):
        result = _float_param().validate(value)
        assert len(result.message) < 80
        assert digits[:20] not in result.message
        assert "inf" not in result.message
        assert "nan" not in result.message


def test_finite_int_conversion_and_bound_messages_unchanged():
    p = _float_param(min_value=0.0, max_value=1.0)
    assert p.validate(0.25).ok
    assert p.validate(1).ok
    assert p.validate(2).message == "x=2.0 above max 1.0."
    assert p.validate(-1).message == "x=-1.0 below min 0.0."


def test_validate_proposal_propagates_finite_refusals():
    result = validate_proposal({
        "magnon_coupling": _OVERSIZED_INT,       # float param, oversized int
        "magnon_sage_age_min": float("nan"),     # float param, NaN
        "signal_interval": 12,                   # valid alongside
    })
    assert not result.ok
    assert set(result.errors) == {"magnon_coupling", "magnon_sage_age_min"}
    for name in ("magnon_coupling", "magnon_sage_age_min"):
        assert result.errors[name].error is ValidationError.WRONG_TYPE
        assert result.errors[name].message == f"{name} requires a finite float value."
    assert result.unknown_params == []
    assert all(len(r.message) < 80 for r in result.errors.values())


def test_public_proposal_path_returns_validation_not_server_error():
    """POST /api/tuning/propose with an oversized int previously escaped as
    HTTP 500, and a NaN literal was ACCEPTED (200). Both must now be ordinary
    422 rejections whose bodies never carry the supplied value."""
    pytest.importorskip("flask")
    from flask import Flask

    from scripts.tuning_api import TuningState, create_blueprint

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        state = TuningState(data_dir=Path(td), gen_getter=lambda: 1_000_000)
        app = Flask(__name__)
        app.register_blueprint(create_blueprint(state))
        client = app.test_client()

        oversized_body = (
            '{"params": {"magnon_coupling": ' + str(_OVERSIZED_INT)
            + '}, "source": "human:kevin", "justification": "pin"}'
        )
        resp = client.post("/api/tuning/propose", data=oversized_body,
                           content_type="application/json")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["status"] == "rejected"
        err = body["validation"]["errors"]["magnon_coupling"]
        assert err["error"] == "wrong_type"
        assert err["message"] == "magnon_coupling requires a finite float value."
        assert str(_OVERSIZED_INT)[:20] not in resp.get_data(as_text=True)

        # A NaN literal is no longer a recorded 422 rejection: the request
        # JSON-tree proof requires exact finite floats, so it is refused at
        # the envelope (fixed 400) before validation or any ledger write.
        from scripts.tuning_api import BAD_REQUEST_MESSAGE

        nan_body = ('{"params": {"magnon_coupling": NaN}, '
                    '"source": "human:kevin", "justification": "pin"}')
        resp = client.post("/api/tuning/propose", data=nan_body,
                           content_type="application/json")
        assert resp.status_code == 400
        body = resp.get_json()
        assert body == {"error": "bad_request", "message": BAD_REQUEST_MESSAGE}


# -- request-shape totality: validate_proposal on arbitrary Python objects ----
#
# validate_proposal is a DIRECT entry point (the tuning API and direct callers
# both reach it). It must be total on any object: a non-dict proposal and a
# proposal carrying non-str keys must resolve to a not-ok result without a
# leaked AttributeError/TypeError and without hashing a hostile key into the
# registry lookup.


class _RecordingKey:
    """A non-str dict key whose hooks record. __hash__ records (dict insertion
    needs it) so a test measures only NEW invocations after construction."""

    def __init__(self):
        self.calls = []

    def __hash__(self):
        self.calls.append("__hash__")
        return 0

    def __eq__(self, other):
        self.calls.append("__eq__")
        return self is other

    def __str__(self):
        self.calls.append("__str__")
        return "k"

    def __repr__(self):
        self.calls.append("__repr__")
        return "k"


@pytest.mark.parametrize("bad", [
    [1, 2], "params", 42, 3.14, True, None, ("k", "v"),
], ids=["list", "str", "int", "float", "bool", "none", "tuple"])
def test_validate_proposal_non_dict_is_not_ok_without_raising(bad):
    result = validate_proposal(bad)  # must not raise .items() AttributeError
    assert isinstance(result, ProposalValidation)
    assert result.ok is False
    assert result.errors == {}
    assert result.known_params == []
    assert result.unknown_params == []


def test_validate_proposal_non_str_key_is_not_ok_without_lookup():
    key = _RecordingKey()
    params = {key: 1}
    key.calls.clear()  # forget the hash from dict construction
    result = validate_proposal(params)
    assert result.ok is False
    # No registry lookup / equality / stringify of the hostile key.
    assert key.calls == []


def test_validate_proposal_mixed_str_and_non_str_keys():
    """Valid str keys still validate; a non-str key alongside them forces the
    aggregate result to not-ok while the valid keys are still processed."""
    key = _RecordingKey()
    params = {"signal_interval": 12, key: 1}
    key.calls.clear()
    result = validate_proposal(params)
    assert result.ok is False
    assert "signal_interval" in result.known_params
    assert key.calls == []


def test_validate_proposal_str_key_paths_unchanged():
    """Positive control: an all-str-key proposal behaves exactly as before."""
    ok = validate_proposal({"signal_interval": 12, "magnon_sage_age_min": 7.5})
    assert ok.ok is True
    bad = validate_proposal({"signal_interval": 0})
    assert bad.ok is False
    assert bad.errors["signal_interval"].error is ValidationError.BELOW_MIN
    unknown = validate_proposal({"nope": 1})
    assert unknown.unknown_params == ["nope"]
    assert unknown.errors["nope"].error is ValidationError.UNKNOWN_PARAM


# -- follow-up: integer width ceiling (bit-length gate) ------------------------
#
# An exact builtin int wider than MAX_TUNING_INT_BITS (2048 bits) is refused by
# a bit-length check BEFORE any conversion, comparison, or formatting, so
# validation is total on oversized ints independently of the mutable
# process-wide sys.get_int_max_str_digits() setting, and no refusal message
# ever copies the supplied digits. Ints within the ceiling keep the existing
# range messages byte-for-byte: a 2048-bit int renders to at most 617 decimal
# digits, below the smallest settable digit limit (640).

import contextlib
import sys as _sys

_WIDE_OK = 2 ** 2048 - 1     # bit_length 2048 — widest accepted magnitude
_WIDE_OVER = 2 ** 2048       # bit_length 2049 — narrowest refused magnitude
_HUGE_5K = 10 ** 5000        # Jack's reproduction value (16 610 bits)
_WIDTH_REFUSAL_N = "n requires an int within 2048 bits."
_WIDTH_REFUSAL_X = "x requires an int within 2048 bits."


@contextlib.contextmanager
def _digit_limit(n):
    saved = _sys.get_int_max_str_digits()
    _sys.set_int_max_str_digits(n)
    try:
        yield
    finally:
        _sys.set_int_max_str_digits(saved)


def test_int_bits_ceiling_constant_and_repo_alignment():
    from scripts.params_schema import MAX_TUNING_INT_BITS
    assert MAX_TUNING_INT_BITS == 2048
    from scripts.orchestrator import MAX_TOOL_RESULT_INT_BITS
    assert MAX_TUNING_INT_BITS == MAX_TOOL_RESULT_INT_BITS
    # Runtime-independence arithmetic: the widest accepted int renders to 617
    # decimal digits, strictly below the smallest settable digit limit (640).
    assert len(str(_WIDE_OK)) == 617 < 640


@pytest.mark.parametrize("limit", [640, 0], ids=["digits-640", "digits-0"])
def test_int_param_oversized_int_total_and_value_free(limit):
    p = _int_param()
    with _digit_limit(limit):
        for value in (_HUGE_5K, -_HUGE_5K, _WIDE_OVER, -_WIDE_OVER):
            result = p.validate(value)  # must not raise ValueError
            assert not result.ok
            assert result.error is ValidationError.WRONG_TYPE
            assert result.message == _WIDTH_REFUSAL_N
            assert len(result.message) < 80
            assert "0" * 20 not in result.message


@pytest.mark.parametrize("limit", [640, 0], ids=["digits-640", "digits-0"])
def test_int_param_2048_bit_boundary_keeps_range_messages(limit):
    p = _int_param()  # bounds [0, 10]
    over_msg = f"n={_WIDE_OK} above max 10."      # rendered at default limit
    under_msg = f"n={-_WIDE_OK} below min 0."
    with _digit_limit(limit):
        result = p.validate(_WIDE_OK)
        assert result.error is ValidationError.ABOVE_MAX
        assert result.message == over_msg
        result = p.validate(-_WIDE_OK)
        assert result.error is ValidationError.BELOW_MIN
        assert result.message == under_msg


def test_bool_behavior_unaffected_by_width_gate():
    # bool has a bit_length method but must never be routed through the int
    # width gate: exact-type identity keeps its separate refusal and its
    # acceptance for bool params byte-identical.
    assert _int_param().validate(True).message == "n requires int, got bool."
    assert _bool_param().validate(True).ok
    assert _bool_param().validate(False).ok


@pytest.mark.parametrize("limit", [640, 0], ids=["digits-640", "digits-0"])
def test_float_param_oversized_int_width_refusal(limit):
    p = _float_param()
    with _digit_limit(limit):
        for value in (_WIDE_OVER, -_WIDE_OVER, _HUGE_5K, -_HUGE_5K):
            result = p.validate(value)
            assert not result.ok
            assert result.error is ValidationError.WRONG_TYPE
            assert result.message == _WIDTH_REFUSAL_X
    # Within the ceiling the existing finite-normalization refusal is
    # preserved byte-for-byte (10**400 is 1329 bits — inside 2048).
    assert _float_param().validate(10 ** 400).message == _FINITE_REFUSAL


@pytest.mark.parametrize("limit", [640, 0], ids=["digits-640", "digits-0"])
def test_validate_proposal_oversized_int_total_and_value_free(limit):
    with _digit_limit(limit):
        result = validate_proposal({
            "magnon_radius": _HUGE_5K,        # int param, oversized
            "magnon_coupling": -_HUGE_5K,     # float param, oversized
            "not_a_real_param": _WIDE_OVER,   # unknown name, oversized value
            "signal_interval": 12,            # valid alongside
        })
        assert result.ok is False
        assert result.errors["magnon_radius"].error is ValidationError.WRONG_TYPE
        assert result.errors["magnon_coupling"].error is ValidationError.WRONG_TYPE
        assert result.errors["not_a_real_param"].error is ValidationError.UNKNOWN_PARAM
        for r in result.errors.values():
            assert len(r.message) < 120
            assert "0" * 20 not in r.message
