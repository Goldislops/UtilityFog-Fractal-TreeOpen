"""Structural refusal totality for the seven configuration sections of
``scripts.portable_genome.import_genome()``.

Scope: this module tests ONLY the *container shape* of ``stochastic``,
``contagion``, ``decay``, ``cosmic_garden``, ``experimental``, ``metadata`` and
``topology``. It deliberately does NOT assert whole-importer totality — field
values inside a correctly shaped section, ``fitness``, ``memory_layout``,
``epigenetic_snapshot``, ``extract_epigenetic_snapshot()``, schema completeness
and semantic/range validation all remain out of scope and are not exercised
here.

Before this package each of those seven values was fetched with
``genome.get(<name>, {})`` and then had ``.get()`` invoked on it directly, so a
genome whose section parsed as an array, string, number, Boolean or ``null``
raised an ambient ``AttributeError`` instead of the importer's
``PortableGenomeError``. The public ``info`` CLI catches ``PortableGenomeError``
specifically, so those shapes bypassed argparse's exit-2 lane and produced a
traceback.

Reachability is checked on two separate surfaces:
  * DIRECT — ``import_genome()`` raises ``PortableGenomeError`` with an exact,
    value-free, section-anchored message.
  * PUBLIC — ``python -m scripts.portable_genome info <file>`` exits 2 through
    argparse with that message on stderr, no traceback, and no leak of the
    offending value.
"""

from __future__ import annotations

import ast
import base64
import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import scripts.portable_genome as pg
from scripts.portable_genome import (
    STATE_NAME_TO_ID,
    PortableGenomeError,
    import_genome,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VALID_FMT = {"format_id": "utilityfog-portable-genome"}

#: The exact authorized section set, in the importer's established order. The
#: order is load-bearing: it decides which refusal wins when several sections
#: are malformed at once.
_SECTIONS = (
    "stochastic",
    "contagion",
    "decay",
    "cosmic_garden",
    "experimental",
    "metadata",
    "topology",
)

#: Every ordinary non-object JSON shape, each carrying a recognisable payload
#: where the shape allows one, so a message leak would be detectable.
_LEAK_MARKER = "ZZ-SECRET-SECTION-VALUE-ZZ"
_NON_OBJECT_SHAPES = (
    ("array", [_LEAK_MARKER]),
    ("string", _LEAK_MARKER),
    ("integer", 987654321),
    ("float", 1234.5678),
    ("true", True),
    ("false", False),
    ("null", None),
)

#: Every configuration constructor ``import_genome`` reaches *after* the seven
#: sections have been retrieved and validated.
_CONSTRUCTOR_NAMES = (
    "StochasticConfig",
    "ContagionConfig",
    "DecayConfig",
    "CosmicGardenConfig",
    "ExperimentalConfig",
    "DensityPhaseDetectorConfig",
    "VoxelMemoryParams",
    "CAConfig",
)

_SHAPE_IDS = [
    f"{section}-{shape_id}"
    for section in _SECTIONS
    for shape_id, _value in _NON_OBJECT_SHAPES
]
_SHAPE_CASES = [
    (section, value)
    for section in _SECTIONS
    for _shape_id, value in _NON_OBJECT_SHAPES
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _base_genome() -> dict:
    """A small genome that imports cleanly; tests malform one section of it."""
    return {
        "format": dict(_VALID_FMT),
        "transition_table": {"VOID": {"3": "STRUCTURAL"}},
    }


def _write(tmp_path: Path, obj, name: str = "genome.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _write_raw(tmp_path: Path, text: str, name: str = "genome.json") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _info(genome_path: Path) -> subprocess.CompletedProcess:
    """Run the PUBLIC ``info`` CLI on a genome path and capture the result."""
    return subprocess.run(
        [sys.executable, "-m", "scripts.portable_genome", "info", str(genome_path)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )


def _forbid_constructors(monkeypatch) -> list:
    """Arm every post-retrieval configuration constructor.

    Returns the list the sentinels append to. ``monkeypatch`` restores the real
    constructors at teardown. See
    :func:`test_constructor_sentinels_are_actually_reachable` — without that
    anti-vacuity check these sentinels would prove nothing.
    """
    reached: list = []

    for name in _CONSTRUCTOR_NAMES:
        def sentinel(*_a, _name=name, **_k):
            reached.append(_name)
            raise AssertionError("configuration constructor reached: " + _name)

        monkeypatch.setattr(pg, name, sentinel)
    return reached


def _patch_loaded_genome(monkeypatch, genome_obj):
    """Replace the module's JSON load seam so a non-JSON object can be injected.

    Only ``scripts.portable_genome``'s own ``json`` binding is replaced, so the
    stdlib module is untouched; ``monkeypatch`` restores the binding.
    """

    class _JsonSeam:
        @staticmethod
        def load(_fp):
            return genome_obj

    monkeypatch.setattr(pg, "json", _JsonSeam)


def _refusal_message(section: str) -> str:
    return f"{section} must be a JSON object"


class _GetRaises:
    """Not a dict. Its ``.get()`` must never be reached."""

    def __init__(self, calls):
        self.calls = calls

    def get(self, *_a, **_k):
        self.calls.append("get")
        raise AssertionError("section .get() was called")


class _ReprRaises:
    """Not a dict. Its ``__repr__`` must never be reached."""

    def __init__(self, calls):
        self.calls = calls

    def __repr__(self):
        self.calls.append("repr")
        raise AssertionError("section __repr__ was called")


class _StrRaises:
    """Not a dict. Its ``__str__`` must never be reached."""

    def __init__(self, calls):
        self.calls = calls

    def __str__(self):
        self.calls.append("str")
        raise AssertionError("section __str__ was called")


class _HostileDictSubclass(dict):
    """A real ``dict`` instance that is not an exact built-in ``dict``.

    Every hook the refusal path could plausibly touch is armed.
    """

    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    def get(self, *_a, **_k):
        self.calls.append("get")
        raise AssertionError("section .get() was called")

    def keys(self):
        self.calls.append("keys")
        raise AssertionError("section .keys() was called")

    def items(self):
        self.calls.append("items")
        raise AssertionError("section .items() was called")

    def __repr__(self):
        self.calls.append("repr")
        raise AssertionError("section __repr__ was called")

    def __str__(self):
        self.calls.append("str")
        raise AssertionError("section __str__ was called")

    def __eq__(self, _other):
        self.calls.append("eq")
        raise AssertionError("section __eq__ was called")

    def __hash__(self):
        self.calls.append("hash")
        raise AssertionError("section __hash__ was called")


# --------------------------------------------------------------------------
# DIRECT refusals — every section x every ordinary non-object JSON shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize("section,value", _SHAPE_CASES, ids=_SHAPE_IDS)
def test_non_object_section_is_refused(section, value, tmp_path, monkeypatch):
    reached = _forbid_constructors(monkeypatch)
    genome = _base_genome()
    genome[section] = value
    p = _write(tmp_path, genome)

    returned = "NOTHING-RETURNED"
    with pytest.raises(PortableGenomeError) as exc:
        returned = import_genome(p)

    message = str(exc.value)
    # 1. exact exception type (not merely a ValueError subclass).
    assert type(exc.value) is PortableGenomeError
    # 2. exact, section-anchored message.
    assert message == _refusal_message(section)
    # 3. no supplied value reflected in the message.
    assert _LEAK_MARKER not in message
    assert "987654321" not in message
    assert "1234.5678" not in message
    # 4. no configuration object returned.
    assert returned == "NOTHING-RETURNED"
    # 5. no downstream configuration constructor reached.
    assert reached == []


def test_error_type_is_valueerror_subclass():
    # Backward compatibility: callers catching ValueError keep working.
    assert issubclass(PortableGenomeError, ValueError)


def test_constructor_sentinels_are_actually_reachable(tmp_path, monkeypatch):
    # Anti-vacuity: the sentinel seam used above must be live, i.e. a genome
    # that gets past section validation really does reach a constructor.
    reached = _forbid_constructors(monkeypatch)
    p = _write(tmp_path, _base_genome())
    with pytest.raises(AssertionError):
        import_genome(p)
    assert reached == [_CONSTRUCTOR_NAMES[0]]


# --------------------------------------------------------------------------
# Hook avoidance — refusal touches none of the section object's own methods
# --------------------------------------------------------------------------


@pytest.mark.parametrize("section", _SECTIONS)
def test_section_get_is_never_called(section, tmp_path, monkeypatch):
    calls: list = []
    genome = _base_genome()
    genome[section] = _GetRaises(calls)
    _patch_loaded_genome(monkeypatch, genome)
    p = _write(tmp_path, _base_genome())

    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)

    assert str(exc.value) == _refusal_message(section)
    assert calls == []


@pytest.mark.parametrize("section", _SECTIONS)
def test_section_repr_is_never_called(section, tmp_path, monkeypatch):
    calls: list = []
    genome = _base_genome()
    genome[section] = _ReprRaises(calls)
    _patch_loaded_genome(monkeypatch, genome)
    p = _write(tmp_path, _base_genome())

    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)

    # Only plain strings are compared here — the hostile object is never fed to
    # pytest's assertion diagnostics.
    assert str(exc.value) == _refusal_message(section)
    assert calls == []


@pytest.mark.parametrize("section", _SECTIONS)
def test_section_str_is_never_called(section, tmp_path, monkeypatch):
    calls: list = []
    genome = _base_genome()
    genome[section] = _StrRaises(calls)
    _patch_loaded_genome(monkeypatch, genome)
    p = _write(tmp_path, _base_genome())

    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)

    assert str(exc.value) == _refusal_message(section)
    assert calls == []


@pytest.mark.parametrize("section", _SECTIONS)
def test_hostile_dict_subclass_is_refused(section, tmp_path, monkeypatch):
    # A dict subclass IS a dict instance, but it is not an exact built-in dict,
    # so the exact-type gate refuses it without touching a single hook.
    calls: list = []
    hostile = _HostileDictSubclass(calls)
    genome = _base_genome()
    genome[section] = hostile
    _patch_loaded_genome(monkeypatch, genome)
    p = _write(tmp_path, _base_genome())

    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)

    assert isinstance(hostile, dict)
    assert type(hostile) is not dict
    assert str(exc.value) == _refusal_message(section)
    # No hostile hook ran, so none of them could have altered the message.
    assert calls == []


def test_hostile_section_does_not_alter_the_message(tmp_path, monkeypatch):
    calls: list = []
    genome = _base_genome()
    genome["metadata"] = _HostileDictSubclass(calls)
    _patch_loaded_genome(monkeypatch, genome)
    p = _write(tmp_path, _base_genome())

    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)

    assert str(exc.value) == "metadata must be a JSON object"
    assert calls == []


# --------------------------------------------------------------------------
# Helper contract
# --------------------------------------------------------------------------


def _section_helper_names(tree: ast.Module) -> list:
    """Private refusal helpers with this package's section signature.

    A later package added sibling private refusal helpers for the
    epigenetic-snapshot extraction contract (see
    ``tests/test_portable_genome_epigenetic_snapshot.py``), so "private function
    that raises PortableGenomeError" is no longer a singleton. This package's
    helper is still uniquely identified by its ``(genome, section_name)``
    signature -- structure, not name.
    """
    return [
        name
        for name in _private_error_raising_function_names(tree)
        if [arg.arg for arg in _function_node(tree, name).args.args]
        == ["genome", "section_name"]
    ]


def _helper():
    """Resolve the private section-validation helper by structure, not name."""
    tree = ast.parse(inspect.getsource(pg))
    names = _section_helper_names(tree)
    assert len(names) == 1
    return getattr(pg, names[0])


def test_helper_returns_a_valid_section_by_identity():
    section = {"enabled": False}
    genome = {"stochastic": section}
    assert _helper()(genome, "stochastic") is section


def test_helper_returns_empty_dict_for_missing_section():
    result = _helper()({}, "stochastic")
    assert type(result) is dict
    assert result == {}


def test_helper_defaults_are_independent_objects():
    fn = _helper()
    first = fn({}, "stochastic")
    second = fn({}, "contagion")
    third = fn({}, "stochastic")
    # No persistent shared mutable default.
    assert first is not second
    assert first is not third
    first["mutated"] = True
    assert second == {}
    assert third == {}


def test_helper_refuses_every_non_object_shape():
    fn = _helper()
    for _shape_id, value in _NON_OBJECT_SHAPES:
        with pytest.raises(PortableGenomeError) as exc:
            fn({"decay": value}, "decay")
        assert str(exc.value) == "decay must be a JSON object"


# --------------------------------------------------------------------------
# Missing and valid-section behavior locks
# --------------------------------------------------------------------------


@pytest.mark.parametrize("section", _SECTIONS)
def test_missing_section_still_imports(section, tmp_path):
    # Each authorized section absent on its own (the base genome carries none
    # of them, so this is exactly "this one is missing").
    genome = _base_genome()
    for other in _SECTIONS:
        if other != section:
            genome[other] = {}
    p = _write(tmp_path, genome)
    rule_spec, ca_config, metadata = import_genome(p)
    assert isinstance(rule_spec, dict)
    assert isinstance(metadata, dict)
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {
        3: STATE_NAME_TO_ID["STRUCTURAL"]
    }


def test_all_seven_sections_missing_simultaneously(tmp_path):
    p = _write(tmp_path, _base_genome())
    rule_spec, ca_config, metadata = import_genome(p)
    # Established defaults for absent configuration sections.
    assert ca_config.stochastic.enabled is True
    assert ca_config.stochastic.baseline_transition_prob == 0.08
    assert ca_config.contagion.enabled is True
    assert ca_config.contagion.energy_neighbor_threshold == 4
    assert ca_config.decay.enabled is True
    assert ca_config.decay.structural_inactive_steps_to_decay == 6
    assert ca_config.cosmic.shield_strength == 0.85
    assert ca_config.experimental.mamba_d_model == 64
    assert rule_spec["rule"]["name"] == "imported-genome"
    assert rule_spec["rule"]["neighborhood"] == "moore-3d"
    assert rule_spec["rule"]["transition"] == "outer-totalistic"
    assert metadata["topology"] == {}


@pytest.mark.parametrize("section", _SECTIONS)
def test_empty_builtin_dict_section_is_accepted(section, tmp_path):
    genome = _base_genome()
    genome[section] = {}
    p = _write(tmp_path, genome)
    rule_spec, ca_config, metadata = import_genome(p)
    assert isinstance(rule_spec, dict)
    assert isinstance(metadata, dict)
    assert ca_config.transition_table != {}


@pytest.mark.parametrize("section", _SECTIONS)
def test_populated_builtin_dict_section_is_accepted(section, tmp_path):
    populated = {
        "stochastic": {"enabled": False},
        "contagion": {"energy_neighbor_threshold": 9},
        "decay": {"inactivity_neighbor_threshold": 5},
        "cosmic_garden": {"shield_strength": 0.11},
        "experimental": {"mamba_d_model": 128},
        "metadata": {"name": "populated-organism"},
        "topology": {"neighborhood": "von-neumann-3d"},
    }
    genome = _base_genome()
    genome[section] = populated[section]
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {
        3: STATE_NAME_TO_ID["STRUCTURAL"]
    }


def test_minimal_valid_genome_still_imports(tmp_path):
    p = _write(tmp_path, {"format": dict(_VALID_FMT)})
    rule_spec, ca_config, metadata = import_genome(p)
    assert isinstance(rule_spec, dict)
    assert ca_config.transition_table == {}
    assert isinstance(metadata, dict)


def _fully_populated_genome() -> dict:
    genome = _base_genome()
    genome["stochastic"] = {
        "enabled": False,
        "baseline_transition_prob": 0.11,
        "structural_to_energy_prob": 0.12,
        "structural_to_sensor_prob": 0.13,
        "compute_to_energy_prob": 0.14,
        "compute_to_sensor_prob": 0.15,
        "structural_to_void_decay_prob": 0.16,
        "energy_to_void_decay_prob": 0.17,
        "sensor_to_void_decay_prob": 0.18,
    }
    genome["contagion"] = {
        "enabled": False,
        "energy_neighbor_threshold": 21,
        "sensor_neighbor_threshold": 22,
        "structural_energy_conversion_prob": 0.21,
        "structural_sensor_conversion_prob": 0.22,
        "compute_energy_conversion_prob": 0.23,
        "compute_sensor_conversion_prob": 0.24,
    }
    genome["decay"] = {
        "enabled": False,
        "inactivity_neighbor_threshold": 31,
        "structural_inactive_steps_to_decay": 32,
    }
    genome["cosmic_garden"] = {
        "cluster_coherence_threshold": 41,
        "shield_strength": 0.41,
        "cluster_shield_bonus": 0.42,
        "halbach_recuperation_rate": 0.43,
        "temporal_dilation": 0.44,
        "bamboo_initial_growth": 42,
        "bamboo_max_length": 43,
        "bamboo_rebirth_age": 44,
        "biofilm_leech_rate": 0.45,
        "super_pod_threshold": 45,
        "analogue_mutation": 0.46,
        "otolith_vector": 0.47,
        "damping_radius": 46,
    }
    genome["experimental"] = {
        "mamba_d_model": 51,
        "mamba_d_state": 52,
        "mamba_enabled": True,
        "void_sanctuary_enabled": True,
        "void_sanctuary_radius": 53,
        "epsilon": 1e-6,
        "selective_memory_decay_enabled": True,
        "selective_memory_decay_threshold": 0.54,
        "selective_compute_neighbor_threshold": 55,
        "selective_low_decay_rate": 0.56,
        "selective_high_decay_rate": 0.57,
    }
    genome["metadata"] = {
        "name": "fully-populated-organism",
        "version": "9.8.7",
        "author": "test-author",
        "description": "test-description",
        "target_lambda": 2.5,
    }
    genome["topology"] = {
        "states": ["VOID", "STRUCTURAL"],
        "neighborhood": "von-neumann-3d",
        "transition_mode": "totalistic",
    }
    return genome


def test_fully_populated_genome_reconstructs_configuration(tmp_path):
    genome = _fully_populated_genome()
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)

    for field, expected in genome["stochastic"].items():
        assert getattr(ca_config.stochastic, field) == expected
    for field, expected in genome["contagion"].items():
        assert getattr(ca_config.contagion, field) == expected
    for field, expected in genome["decay"].items():
        assert getattr(ca_config.decay, field) == expected
    for field, expected in genome["cosmic_garden"].items():
        assert getattr(ca_config.cosmic, field) == expected
    for field, expected in genome["experimental"].items():
        assert getattr(ca_config.experimental, field) == expected


def test_valid_stochastic_values_unchanged(tmp_path):
    genome = _base_genome()
    genome["stochastic"] = {"enabled": False, "baseline_transition_prob": 0.99}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.stochastic.enabled is False
    assert ca_config.stochastic.baseline_transition_prob == 0.99
    # Untouched fields keep their established defaults.
    assert ca_config.stochastic.sensor_to_void_decay_prob == 0.004


def test_valid_contagion_values_unchanged(tmp_path):
    genome = _base_genome()
    genome["contagion"] = {"enabled": False, "energy_neighbor_threshold": 12}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.contagion.enabled is False
    assert ca_config.contagion.energy_neighbor_threshold == 12
    assert ca_config.contagion.compute_sensor_conversion_prob == 0.25


def test_valid_decay_values_unchanged(tmp_path):
    genome = _base_genome()
    genome["decay"] = {"enabled": False, "structural_inactive_steps_to_decay": 99}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.decay.enabled is False
    assert ca_config.decay.structural_inactive_steps_to_decay == 99
    assert ca_config.decay.inactivity_neighbor_threshold == 1


def test_valid_cosmic_garden_values_unchanged(tmp_path):
    genome = _base_genome()
    genome["cosmic_garden"] = {"shield_strength": 0.01, "damping_radius": 7}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.cosmic.shield_strength == 0.01
    assert ca_config.cosmic.damping_radius == 7
    assert ca_config.cosmic.bamboo_max_length == 500


def test_valid_experimental_values_unchanged(tmp_path):
    genome = _base_genome()
    genome["experimental"] = {"mamba_enabled": True, "epsilon": 1e-5}
    p = _write(tmp_path, genome)
    rule_spec, ca_config, _md = import_genome(p)
    assert ca_config.experimental.mamba_enabled is True
    assert ca_config.experimental.epsilon == 1e-5
    assert ca_config.experimental.mamba_d_state == 16
    # The rule_spec mirror of the selective-decay block is preserved too.
    smd = rule_spec["params"]["experimental"]["selective_memory_decay"]
    assert smd["enabled"] is False
    assert smd["memory_strength_threshold"] == 0.75


def test_valid_metadata_reaches_returned_metadata(tmp_path):
    genome = _base_genome()
    genome["metadata"] = {
        "name": "demo-organism",
        "version": "1.2.3",
        "author": "someone",
        "description": "a description",
        "target_lambda": 1.9,
    }
    p = _write(tmp_path, genome)
    rule_spec, _cfg, metadata = import_genome(p)
    assert metadata["name"] == "demo-organism"
    assert metadata["version"] == "1.2.3"
    assert metadata["author"] == "someone"
    assert rule_spec["rule"]["name"] == "demo-organism"
    assert rule_spec["params"]["meta"]["description"] == "a description"
    assert rule_spec["params"]["meta"]["target_lambda"] == 1.9


def test_valid_topology_reaches_rule_spec_and_metadata(tmp_path):
    genome = _base_genome()
    genome["topology"] = {
        "states": ["VOID", "COMPUTE"],
        "neighborhood": "von-neumann-3d",
        "transition_mode": "totalistic",
    }
    p = _write(tmp_path, genome)
    rule_spec, _cfg, metadata = import_genome(p)
    assert rule_spec["rule"]["states"] == ["VOID", "COMPUTE"]
    assert rule_spec["rule"]["neighborhood"] == "von-neumann-3d"
    assert rule_spec["rule"]["transition"] == "totalistic"
    assert metadata["topology"] == genome["topology"]


def test_valid_sections_reach_the_rule_spec_by_identity(tmp_path, monkeypatch):
    # The validated section objects, not copies, are forwarded into rule_spec —
    # confirming the helper returns the caller's object.
    stoch = {"enabled": False}
    genome = _base_genome()
    genome["stochastic"] = stoch
    _patch_loaded_genome(monkeypatch, genome)
    p = _write(tmp_path, _base_genome())
    rule_spec, _cfg, _md = import_genome(p)
    assert rule_spec["params"]["stochastic"] is stoch


# --------------------------------------------------------------------------
# Validation order and precedence
# --------------------------------------------------------------------------


def test_malformed_root_precedes_section_validation(tmp_path):
    p = _write(tmp_path, ["stochastic"])
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "genome must be a JSON object"


def test_malformed_format_precedes_section_validation(tmp_path):
    genome = _base_genome()
    genome["format"] = []
    genome["stochastic"] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "format must be a JSON object"


def test_wrong_format_identifier_precedes_section_validation(tmp_path):
    genome = _base_genome()
    genome["format"] = {"format_id": "some-other-format"}
    genome["stochastic"] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "unknown genome format"


def test_malformed_transition_table_precedes_section_validation(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = []
    genome["stochastic"] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition_table must be a JSON object"


def test_malformed_source_mapping_precedes_section_validation(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"VOID": []}
    genome["stochastic"] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition mappings must be a JSON object"


@pytest.mark.parametrize("first_index", range(len(_SECTIONS)))
def test_established_section_order_decides_the_refusal(first_index, tmp_path):
    # Malform this section and every later one; the earliest must win.
    genome = _base_genome()
    for section in _SECTIONS[first_index:]:
        genome[section] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == _refusal_message(_SECTIONS[first_index])


def test_all_seven_malformed_refuses_on_the_first(tmp_path):
    genome = _base_genome()
    for section in _SECTIONS:
        genome[section] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "stochastic must be a JSON object"


@pytest.mark.parametrize("section", _SECTIONS)
def test_refusal_precedes_every_configuration_constructor(section, tmp_path, monkeypatch):
    reached = _forbid_constructors(monkeypatch)
    genome = _base_genome()
    genome[section] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError):
        import_genome(p)
    assert reached == []


def test_refusal_precedes_transition_semantic_conversion(tmp_path, monkeypatch):
    # The source mapping is a well-shaped object, so the transition-container
    # checks pass; "BOGUS" only fails later, during source/target conversion.
    # Section validation sits between the two, so the section wins.
    reached = _forbid_constructors(monkeypatch)
    genome = _base_genome()
    genome["transition_table"] = {"BOGUS": {"notanum": "ALSO-BOGUS"}}
    genome["stochastic"] = []
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "stochastic must be a JSON object"
    assert reached == []


def test_transition_conversion_still_wins_when_sections_are_wellformed(tmp_path):
    # Anti-vacuity for the test above: with valid sections the same genome does
    # reach semantic conversion and refuses there.
    genome = _base_genome()
    genome["transition_table"] = {"BOGUS": {"notanum": "ALSO-BOGUS"}}
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition source state must be a known state name"


# --------------------------------------------------------------------------
# PUBLIC CLI reachability
# --------------------------------------------------------------------------


@pytest.mark.parametrize("section", _SECTIONS)
def test_public_info_malformed_section_exits_2(section, tmp_path):
    genome = _base_genome()
    genome["metadata"] = {"name": "cli-organism"}
    genome[section] = [_LEAK_MARKER]
    p = _write(tmp_path, genome)
    res = _info(p)

    assert res.returncode == 2
    assert _refusal_message(section) in res.stderr
    assert "with transitions" not in res.stdout
    assert _LEAK_MARKER not in res.stderr
    assert _LEAK_MARKER not in res.stdout
    assert "Traceback" not in res.stderr


def test_public_info_valid_genome_success_output_unchanged(tmp_path):
    genome = _base_genome()
    genome["metadata"] = {"name": "demo-organism", "version": "4.5.6"}
    p = _write(tmp_path, genome)
    res = _info(p)
    assert res.returncode == 0
    assert "with transitions" in res.stdout
    assert "name: demo-organism" in res.stdout
    assert "version: 4.5.6" in res.stdout
    assert "Traceback" not in res.stderr


def test_public_info_valid_sections_success_output_unchanged(tmp_path):
    genome = _fully_populated_genome()
    p = _write(tmp_path, genome)
    res = _info(p)
    assert res.returncode == 0
    assert "name: fully-populated-organism" in res.stdout
    assert "version: 9.8.7" in res.stdout
    assert "states: 1 with transitions" in res.stdout


def test_public_info_does_not_broadly_catch_json_syntax_error(tmp_path):
    p = _write_raw(tmp_path, "{not valid json")
    res = _info(p)
    assert res.returncode != 2
    assert "with transitions" not in res.stdout


def test_public_info_does_not_broadly_catch_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    res = _info(missing)
    assert res.returncode != 2
    assert "with transitions" not in res.stdout


def test_memory_error_is_not_converted_to_a_structural_refusal(tmp_path, monkeypatch):
    # Exercised directly: an unrelated MemoryError must propagate unchanged, so
    # it can never reach the CLI's PortableGenomeError catch.
    assert not issubclass(MemoryError, PortableGenomeError)

    class _ExhaustedSeam:
        @staticmethod
        def load(_fp):
            raise MemoryError("out of memory")

    monkeypatch.setattr(pg, "json", _ExhaustedSeam)
    p = _write(tmp_path, _base_genome())
    with pytest.raises(MemoryError):
        import_genome(p)


# --------------------------------------------------------------------------
# Existing transition behavior locks (compact; the transition-focused module is
# not modified by this package)
# --------------------------------------------------------------------------


def test_case_insensitive_source_and_target_names(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"void": {"1": "structural"}}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {
        1: STATE_NAME_TO_ID["STRUCTURAL"]
    }


@pytest.mark.parametrize(
    "spelling,expected",
    [("+1", 1), ("  4  ", 4), ("007", 7), ("-2", -2)],
    ids=["signed", "whitespace", "leading-zero", "negative"],
)
def test_accepted_count_spellings(spelling, expected, tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"VOID": {spelling: "COMPUTE"}}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {
        expected: STATE_NAME_TO_ID["COMPUTE"]
    }


def test_duplicate_integer_keys_last_write_wins(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"VOID": {"5": "COMPUTE", "05": "ENERGY"}}
    p = _write(tmp_path, genome)
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {
        5: STATE_NAME_TO_ID["ENERGY"]
    }


def test_unknown_source_state_still_refused(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"NOSUCHSTATE": {"0": "VOID"}}
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition source state must be a known state name"


def test_unknown_target_state_still_refused(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"VOID": {"0": "NOSUCHSTATE"}}
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition target state must be a known state name"


def test_malformed_count_still_refused(tmp_path):
    genome = _base_genome()
    genome["transition_table"] = {"VOID": {"notanum": "VOID"}}
    p = _write(tmp_path, genome)
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition neighbor count must be an integer string"


# --------------------------------------------------------------------------
# Structural (AST) evidence — supplements the behavioral tests above
# --------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(inspect.getsource(pg))


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("function not found: " + name)


def _private_error_raising_function_names(tree: ast.Module) -> list:
    """Module-level private functions that raise PortableGenomeError."""
    found = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_"):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Raise)
                and isinstance(sub.exc, ast.Call)
                and isinstance(sub.exc.func, ast.Name)
                and sub.exc.func.id == "PortableGenomeError"
            ):
                found.append(node.name)
                break
    return found


def _ordered_helper_calls(func: ast.FunctionDef, helper_name: str) -> list:
    calls = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == helper_name
    ]
    calls.sort(key=lambda n: (n.lineno, n.col_offset))
    return calls


def test_exactly_one_private_section_validation_helper():
    assert len(_section_helper_names(_module_tree())) == 1


def test_helper_uses_an_exact_builtin_dict_check():
    tree = _module_tree()
    helper = _function_node(tree, _private_error_raising_function_names(tree)[0])
    exact_checks = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], (ast.Is, ast.IsNot))
        and isinstance(node.left, ast.Call)
        and isinstance(node.left.func, ast.Name)
        and node.left.func.id == "type"
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == "dict"
    ]
    assert len(exact_checks) == 1
    # No isinstance() anywhere in the helper — a dict subclass must not pass.
    assert not [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isinstance"
    ]


def test_helper_raises_portable_genome_error_with_a_fixed_message():
    tree = _module_tree()
    helper_name = _private_error_raising_function_names(tree)[0]
    helper = _function_node(tree, helper_name)
    section_param = helper.args.args[-1].arg

    raises = [node for node in ast.walk(helper) if isinstance(node, ast.Raise)]
    assert len(raises) == 1
    call = raises[0].exc
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name) and call.func.id == "PortableGenomeError"
    assert len(call.args) == 1 and not call.keywords

    message = call.args[0]
    assert isinstance(message, ast.JoinedStr)
    interpolated = {
        sub.value.id
        for sub in message.values
        if isinstance(sub, ast.FormattedValue)
    }
    # The message is derived from the fixed section-name argument and nothing
    # else: no supplied value, repr, or type name can enter it.
    assert interpolated == {section_param}
    literals = [
        sub.value for sub in message.values if isinstance(sub, ast.Constant)
    ]
    assert literals == [" must be a JSON object"]


def test_import_genome_calls_the_helper_exactly_seven_times():
    tree = _module_tree()
    helper_name = _private_error_raising_function_names(tree)[0]
    calls = _ordered_helper_calls(_function_node(tree, "import_genome"), helper_name)
    assert len(calls) == 7


def test_helper_call_sections_are_exactly_the_authorized_set_in_order():
    tree = _module_tree()
    helper_name = _private_error_raising_function_names(tree)[0]
    calls = _ordered_helper_calls(_function_node(tree, "import_genome"), helper_name)
    names = []
    for call in calls:
        assert len(call.args) == 2
        assert isinstance(call.args[0], ast.Name) and call.args[0].id == "genome"
        assert isinstance(call.args[1], ast.Constant)
        names.append(call.args[1].value)
    assert tuple(names) == _SECTIONS
    assert set(names) == set(_SECTIONS)


def test_no_direct_get_remains_on_an_authorized_section():
    tree = _module_tree()
    helper_name = _private_error_raising_function_names(tree)[0]
    import_fn = _function_node(tree, "import_genome")

    # (a) No authorized section is fetched straight off the genome any more.
    for node in ast.walk(import_fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "genome"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            assert node.args[0].value not in _SECTIONS

    # (b) Every binding that later has .get() called on it and is not a
    # transition-table or format binding comes from a validated helper call.
    validated = set()
    for node in ast.walk(import_fn):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == helper_name
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            validated.add(node.targets[0].id)
    assert len(validated) == 7

    section_getters = {
        node.func.value.id
        for node in ast.walk(import_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
    }
    # `genome` (fitness/memory_layout, out of scope) and `fmt` (format_id) are
    # the only unvalidated-by-this-package holders left.
    assert section_getters - validated == {"genome", "fmt"}


def test_no_broad_exception_handler_is_introduced():
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.ExceptHandler):
            assert node.type is not None
            assert getattr(node.type, "id", None) not in ("Exception", "BaseException")


def test_public_cli_still_catches_only_portable_genome_error():
    handlers = [
        node
        for node in ast.walk(_module_tree())
        if isinstance(node, ast.ExceptHandler)
        and isinstance(node.type, ast.Name)
        and node.type.id == "PortableGenomeError"
    ]
    assert len(handlers) == 1
    routed = [
        node
        for node in ast.walk(handlers[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "error"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "parser"
    ]
    assert len(routed) == 1


def test_extract_epigenetic_snapshot_reuses_this_packages_section_helper():
    """Superseded lock, updated deliberately.

    This test previously asserted the extractor was *untouched* by this
    package. A later package -- the epigenetic-snapshot extraction contract in
    ``tests/test_portable_genome_epigenetic_snapshot.py`` -- extended into it on
    purpose, reusing this package's section helper rather than duplicating it,
    and added its own structural refusals. What this module still owns is that
    the shared helper is the one reused and that the extractor's own decode
    landmarks are intact.
    """
    tree = _module_tree()
    helper_name = _section_helper_names(tree)[0]
    fn = _function_node(tree, "extract_epigenetic_snapshot")
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    # The shared section helper is reused, not re-implemented …
    assert helper_name in called
    # … and the extractor's own landmarks are still in place.
    attrs = {
        node.func.attr
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"frombuffer", "reshape", "load"} <= attrs
    # `b64decode` was a landmark here until the wire-integrity package moved
    # decoding into `_decode_base64_strict` so it could be validated rather
    # than run permissively. The extractor still owns the decode, now by
    # delegation — assert that rather than the raw call it replaced.
    assert "_decode_base64_strict" in called


def test_export_genome_untouched_by_this_package():
    tree = _module_tree()
    helper_name = _private_error_raising_function_names(tree)[0]
    fn = _function_node(tree, "export_genome")
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert helper_name not in called
    assert not [node for node in ast.walk(fn) if isinstance(node, ast.Raise)]
    assert {"_load_transition_table", "_load_stochastic_config"} <= called


# ===========================================================================
# Export-CLI snapshot loading: no pickled member is ever loaded
#
# An NPZ member of object dtype IS a pickle, so loading one with pickle
# enabled is arbitrary code execution by construction. The export CLI reads a
# snapshot supplied on the command line, so the payload below is harmless: its
# reduction writes ONE marker file inside pytest's own tmp_path and returns.
# `__reduce__` runs at PICKLE time and only records the callable, so writing
# the archive is inert; the call would happen at UNPICKLE time, which is the
# event under test.
#
# Two surfaces, matching this module's existing DIRECT/PUBLIC split:
#   * IN-PROCESS -- the module's real `__main__` body, lifted from the live
#     source, so load counting, archive lifetime and call ordering can be
#     observed on the real objects.
#   * PUBLIC -- `python -m scripts.portable_genome export`, which proves the
#     shipped entry point refuses too.
#
# Scope: an OBJECT-MEMBER REFUSAL, not whole-archive validation. Nothing here
# claims resistance to decompression amplification, absurd declared shapes,
# hostile member names or defects in NumPy's own header parsing.
# ===========================================================================

_PG_MARKER = "PORTABLE_GENOME_PAYLOAD_EXECUTED"

#: Every member the export CLI actually dereferences, in the CLI's own order.
#: `generation`, `ca_step` and `best_fitness` are reached through `.get`, which
#: routes through `NpzFile.__getitem__` whenever the key is present -- a `.get`
#: default does NOT make a member safe, and each is covered here for that
#: reason.
_CLI_MEMBERS = ("lattice", "memory_grid", "generation", "ca_step", "best_fitness")


def _create_marker_pg(directory: str) -> int:
    """Stand in for a malicious payload; deliberately inert.

    Module scope is required: pickle stores a module-qualified reference, so
    this has to be importable by name at unpickle time.

    Returns ``0`` so a pickle-enabled load carries on through the CLI's
    ``int()``/``float()`` casts instead of dying on incidental type noise. That
    keeps the failing-first evidence pointed at the real defect -- the payload
    ran -- rather than at a cast that happened to blow up first.
    """
    Path(directory, _PG_MARKER).write_text("executed", encoding="utf-8")
    return 0


class _PayloadPG:
    """An object whose reduction calls :func:`_create_marker_pg`."""

    def __init__(self, directory: str) -> None:
        self._directory = directory

    def __reduce__(self):
        return (_create_marker_pg, (self._directory,))


def _payload_member_pg(directory) -> "np.ndarray":
    """A 0-d object-dtype member -- i.e. a pickle inside the archive."""
    return np.array(_PayloadPG(str(directory)), dtype=object)


def _numeric_members_pg(generation=7, ca_step=42, best_fitness=0.125) -> dict:
    """A legitimate snapshot: ndarrays and plain numeric scalars, no objects."""
    return {
        "lattice": np.arange(8, dtype=np.uint8).reshape(2, 2, 2),
        "memory_grid": np.zeros((pg.MEMORY_CHANNELS, 2, 2, 2), dtype=np.float32),
        "generation": np.int64(generation),
        "ca_step": np.int64(ca_step),
        "best_fitness": np.float64(best_fitness),
    }


def _write_snapshot_pg(tmp_path, members) -> Path:
    archive = tmp_path / "snapshot.npz"
    np.savez(archive, **members)
    return archive


def _minimal_rule_file(tmp_path) -> Path:
    """An empty rule spec.

    Every configuration loader reached by ``export_genome`` defaults cleanly on
    an absent ``params`` section, so this keeps the evidence pointed at
    snapshot loading rather than at rule parsing.
    """
    rule_file = tmp_path / "rule.toml"
    rule_file.write_text("", encoding="utf-8")
    return rule_file


def _cli_main_block() -> ast.Module:
    """The module's real ``if __name__ == "__main__":`` body, lifted live.

    Lifted from the installed source rather than reimplemented, so these tests
    cannot drift away from what ``python -m scripts.portable_genome`` actually
    runs. The single-block assertion is what keeps the lift honest.
    """
    tree = _module_tree()
    blocks = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    ]
    assert len(blocks) == 1, "portable_genome no longer has exactly one __main__ block"
    return ast.Module(body=blocks[0].body, type_ignores=[])


def _run_export_cli(monkeypatch, rule_file, snapshot, output, *extra) -> None:
    """Execute the real ``__main__`` body in-process.

    It runs against a COPY of the module's own globals, so ``export_genome``
    and ``np`` are the real objects and any monkeypatch applied BEFORE this
    call is visible to the CLI. Nothing long-running is started: the export
    branch parses one TOML file, reads one archive and writes one JSON file.
    """
    argv = [
        "portable_genome.py", "export",
        "--rule-file", str(rule_file),
        "--snapshot", str(snapshot),
        "--output", str(output),
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    namespace = dict(pg.__dict__)
    namespace["__name__"] = "__main__"
    exec(compile(_cli_main_block(), "<portable_genome __main__>", "exec"), namespace)


def _export_cli_subprocess(rule_file, snapshot, output, *extra):
    """Run the PUBLIC export CLI exactly as an operator would."""
    return subprocess.run(
        [
            sys.executable, "-m", "scripts.portable_genome", "export",
            "--rule-file", str(rule_file),
            "--snapshot", str(snapshot),
            "--output", str(output),
            *extra,
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )


def _archive_is_open(handle) -> bool:
    """True while the NPZ archive still owns operating-system resources.

    Reads the real ``NpzFile``: ``close()`` drops both ``zip`` and ``fid`` to
    ``None``. Deliberately NOT written with a ``getattr(..., default)`` --
    a default is precisely what makes a closure assertion pass on an object
    that was never observed at all.
    """
    return handle.zip is not None


# --- static contract -------------------------------------------------------


def test_export_cli_snapshot_load_is_pickle_free():
    """Supersedes ``test_export_cli_snapshot_path_unchanged``.

    That test pinned the export CLI to ``allow_pickle=True`` and described the
    loader as deliberately out of scope. It is in scope now: the pin asserted
    the insecure behaviour, so it has been replaced by an assertion of the
    intended secure contract rather than merely deleted.
    """
    tree = _module_tree()
    loads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "load"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "np"
    ]
    assert len(loads) == 1
    keywords = {kw.arg: kw.value for kw in loads[0].keywords}
    assert set(keywords) == {"allow_pickle"}
    assert isinstance(keywords["allow_pickle"], ast.Constant)
    assert keywords["allow_pickle"].value is False


def test_export_cli_owns_the_archive_through_a_context_manager():
    """The load is a ``with`` subject, and ``export_genome`` is outside it.

    The dynamic proof lives in
    ``test_the_archive_is_closed_before_export_genome_begins``; this is the
    structural half, and it is what makes the ordering visible to a reader of
    the source rather than only to a test run.
    """
    tree = _module_tree()
    owning = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "load"
            for item in node.items
        )
    ]
    assert len(owning) == 1, "the export CLI's np.load is not owned by a `with`"
    inside = {
        node.func.id
        for node in ast.walk(owning[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "export_genome" not in inside, (
        "export_genome is called while the archive is still open"
    )


# --- the payload really does execute when pickle is enabled ----------------


def test_pg_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Positive control.

    Without this, every "marker absent" assertion below would be vacuous: a
    payload that never fires proves nothing about a loader that refuses it.
    """
    archive = _write_snapshot_pg(tmp_path, {"lattice": _payload_member_pg(tmp_path)})
    marker = tmp_path / _PG_MARKER
    assert not marker.exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert marker.exists(), "the payload did not fire; the refusal tests are vacuous"


# --- refusal ---------------------------------------------------------------


@pytest.mark.parametrize("member", _CLI_MEMBERS)
def test_every_member_the_cli_touches_is_refused(monkeypatch, tmp_path, member):
    """Each of the five members the CLI dereferences, carrying the payload.

    The last three are reached through ``.get`` with a default. That default
    only applies to an ABSENT key -- a present key still decodes -- so they are
    covered exactly like the two direct subscripts.
    """
    members = _numeric_members_pg()
    members[member] = _payload_member_pg(tmp_path)
    archive = _write_snapshot_pg(tmp_path, members)
    output = tmp_path / "genome.json"
    marker = tmp_path / _PG_MARKER

    with pytest.raises(ValueError) as excinfo:
        _run_export_cli(monkeypatch, _minimal_rule_file(tmp_path), archive, output)

    assert "allow_pickle=False" in str(excinfo.value)
    assert not marker.exists(), "the payload executed"
    assert not output.exists(), "a genome was written from a refused snapshot"


def test_the_public_export_cli_refuses_a_pickled_member(tmp_path):
    """The shipped entry point, run as an operator would run it.

    Marker absence is deliberately NOT asserted here: the payload's reduction
    names a callable in THIS test module, which a fresh interpreter would fail
    to import, so an absent marker in a subprocess would prove nothing either
    way. What this surface proves is that the real console entry point refuses
    and writes no genome. The in-process tests above own the marker evidence.
    """
    archive = _write_snapshot_pg(
        tmp_path, {**_numeric_members_pg(), "lattice": _payload_member_pg(tmp_path)}
    )
    output = tmp_path / "genome.json"

    result = _export_cli_subprocess(_minimal_rule_file(tmp_path), archive, output)

    assert result.returncode != 0
    assert "allow_pickle=False" in result.stderr
    assert not output.exists()


def test_the_cli_loads_once_and_never_retries_with_pickle_enabled(monkeypatch, tmp_path):
    """A refusal must be final.

    A fallback retry would restore the vulnerability while leaving every other
    assertion in this file green, so the argument every load was made with is
    recorded and the whole sequence is asserted -- not just the first call.
    """
    archive = _write_snapshot_pg(
        tmp_path, {**_numeric_members_pg(), "lattice": _payload_member_pg(tmp_path)}
    )
    calls = []
    real_load = np.load

    def recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle", "<absent>"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(np, "load", recording_load)
    with pytest.raises(ValueError):
        _run_export_cli(
            monkeypatch, _minimal_rule_file(tmp_path), archive, tmp_path / "genome.json"
        )

    assert calls == [False], f"expected exactly one pickle-free load, got {calls}"


# --- archive lifetime ------------------------------------------------------


def test_the_archive_is_closed_before_export_genome_begins(monkeypatch, tmp_path):
    """Deterministic closure, observed on the real ``NpzFile``.

    Non-vacuity is enforced from both ends. The archive is recorded as GENUINELY
    OPEN at load time, and ``export_genome`` is recorded as GENUINELY REACHED --
    both are asserted before the closure claim, so "closed" can never be
    satisfied by an observation that never happened.
    """
    archive = _write_snapshot_pg(tmp_path, _numeric_members_pg())
    seen = {}
    real_load = np.load
    real_export = pg.export_genome

    def watching_load(*args, **kwargs):
        handle = real_load(*args, **kwargs)
        seen["handle"] = handle
        seen["open_at_load"] = _archive_is_open(handle)
        return handle

    def watching_export(*args, **kwargs):
        seen["open_at_export"] = _archive_is_open(seen["handle"])
        seen["fid_at_export"] = seen["handle"].fid
        return real_export(*args, **kwargs)

    monkeypatch.setattr(np, "load", watching_load)
    monkeypatch.setattr(pg, "export_genome", watching_export)
    _run_export_cli(
        monkeypatch, _minimal_rule_file(tmp_path), archive, tmp_path / "genome.json"
    )

    assert seen.get("open_at_load") is True, "the archive was never observed open"
    assert "open_at_export" in seen, "export_genome was never reached"
    assert seen["open_at_export"] is False, "export_genome ran with the archive open"
    assert seen["fid_at_export"] is None, "the file descriptor was still held"


# --- compatibility ---------------------------------------------------------


def test_a_numeric_snapshot_still_exports_its_counters(monkeypatch, tmp_path):
    """Generation, CA step and best fitness survive the refusal change."""
    archive = _write_snapshot_pg(tmp_path, _numeric_members_pg())
    output = tmp_path / "genome.json"

    _run_export_cli(monkeypatch, _minimal_rule_file(tmp_path), archive, output)

    metadata = json.loads(output.read_text(encoding="utf-8"))["metadata"]
    assert metadata["source_generation"] == 7
    assert metadata["source_ca_step"] == 42
    assert metadata["best_fitness"] == 0.125


def test_absent_optional_members_still_fall_back_to_their_defaults(monkeypatch, tmp_path):
    """The `.get` defaults are untouched: an ABSENT key still yields 0/0/0.0."""
    archive = _write_snapshot_pg(
        tmp_path,
        {
            "lattice": np.arange(8, dtype=np.uint8).reshape(2, 2, 2),
            "memory_grid": np.zeros((pg.MEMORY_CHANNELS, 2, 2, 2), dtype=np.float32),
        },
    )
    output = tmp_path / "genome.json"

    _run_export_cli(monkeypatch, _minimal_rule_file(tmp_path), archive, output)

    metadata = json.loads(output.read_text(encoding="utf-8"))["metadata"]
    assert metadata["source_generation"] == 0
    assert metadata["source_ca_step"] == 0
    assert metadata["best_fitness"] == 0.0


def test_the_epigenetic_payload_still_exports_intact(monkeypatch, tmp_path):
    """The arrays outlive the archive.

    ``export_genome`` base64-encodes ``lattice`` and ``memory_grid`` AFTER the
    archive is closed, so decoding them to their exact byte lengths and values
    is what proves closure did not truncate or invalidate the data.
    """
    archive = _write_snapshot_pg(tmp_path, _numeric_members_pg())
    output = tmp_path / "genome.json"

    _run_export_cli(
        monkeypatch,
        _minimal_rule_file(tmp_path),
        archive,
        output,
        "--include-epigenetic",
    )

    epi = json.loads(output.read_text(encoding="utf-8"))["epigenetic_snapshot"]
    assert epi["included"] is True
    assert epi["lattice_shape"] == [2, 2, 2]
    assert epi["snapshot_generation"] == 7
    assert epi["snapshot_ca_step"] == 42
    assert base64.b64decode(epi["lattice_b64"]) == bytes(range(8))
    assert len(base64.b64decode(epi["memory_grid_b64"])) == pg.MEMORY_CHANNELS * 8 * 4


def test_without_the_flag_the_epigenetic_section_stays_excluded(monkeypatch, tmp_path):
    """Established export semantics: the flag, not the snapshot, decides."""
    archive = _write_snapshot_pg(tmp_path, _numeric_members_pg())
    output = tmp_path / "genome.json"

    _run_export_cli(monkeypatch, _minimal_rule_file(tmp_path), archive, output)

    genome = json.loads(output.read_text(encoding="utf-8"))
    assert genome["epigenetic_snapshot"] == {"included": False}
