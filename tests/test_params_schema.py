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
