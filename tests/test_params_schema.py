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
