"""Tests for nested-configuration and epigenetic-snapshot structural totality
in ``scripts/portable_genome.py``.

Scope: this module closes ONLY the residuals that
``tests/test_portable_genome.py`` explicitly left outside its boundary — the
nested configuration sections of ``import_genome`` and the whole
``extract_epigenetic_snapshot`` structural surface. The transition-table
boundary tested by that earlier module is untouched here and remains its own
regression fence.

Two properties are pinned:

* **nested-section object totality** — every named configuration section, when
  present, must be an exact JSON object, refused with a fixed, value-free
  ``PortableGenomeError`` *before* any ``.get()``, dataclass construction or
  ``dict()`` conversion consumes it;
* **epigenetic structural totality** — root, section, ``included``,
  ``lattice_shape``, both base64 members and ``memory_layout.num_channels`` are
  proven, base64 is decoded **strictly**, and the exact expected byte count is
  checked *before* ``np.frombuffer``/``reshape`` so that NumPy's
  implementation-specific message never becomes the public refusal.

This is NOT whole-schema totality. It makes no claim about semantic validity of
configuration values, state ranges, transition policy, genome authenticity,
cryptographic integrity, input size, allocation exhaustion, path containment,
atomicity or concurrency — and explicitly none about the public CLI's
``np.load(..., allow_pickle=True)`` snapshot-export path, which is a separate
residual left untouched.

All artifacts are tiny and under ``tmp_path``. No engine, real Medusa snapshot,
network, GPU, model or repository-data read is involved, and no malicious
pickle is constructed or executed anywhere.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts.portable_genome import (
    MEMORY_CHANNELS,
    STATE_NAME_TO_ID,
    PortableGenomeError,
    extract_epigenetic_snapshot,
    import_genome,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every configuration section that must be an exact JSON object when present.
SECTIONS = [
    "metadata", "topology", "stochastic", "contagion", "decay",
    "cosmic_garden", "experimental", "fitness", "memory_layout",
]

#: Non-object JSON shapes every section must refuse.
NON_OBJECTS = [
    pytest.param([], id="array-empty"),
    pytest.param([1, 2], id="array"),
    pytest.param("text", id="string"),
    pytest.param(7, id="number-int"),
    pytest.param(1.5, id="number-float"),
    pytest.param(True, id="boolean"),
    pytest.param(None, id="null"),
]

_SECRET = "SUPER-SECRET-MARKER-9999"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _base_genome(**extra):
    g = {
        "format": {"format_id": "utilityfog-portable-genome", "version": "1.0"},
        "transition_table": {"VOID": {"3": "STRUCTURAL"}},
    }
    g.update(extra)
    return g


def _write(path: Path, obj) -> str:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _info(genome_path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "scripts.portable_genome", "info", str(genome_path)],
        cwd=str(_REPO_ROOT), capture_output=True, text=True,
    )


#: Distinguishes "argument not supplied" from an explicit JSON ``null``.
_ABSENT = object()


def _epi_genome(shape, lattice_bytes=None, *, include=True, memory_bytes=None,
                memory_layout=_ABSENT, **overrides):
    n = int(np.prod(shape)) if shape else 0
    if lattice_bytes is None:
        lattice_bytes = bytes(range(1, n + 1)) if n else b""
    epi = {
        "included": include,
        "lattice_shape": list(shape),
        "lattice_b64": base64.b64encode(lattice_bytes).decode("ascii"),
        "snapshot_generation": 11,
        "snapshot_ca_step": 22,
    }
    if memory_bytes is not None:
        epi["memory_grid_b64"] = base64.b64encode(memory_bytes).decode("ascii")
    epi.update(overrides)
    g = _base_genome(epigenetic_snapshot=epi)
    if memory_layout is not _ABSENT:
        g["memory_layout"] = memory_layout
    return g


# ==========================================================================
# GROUP 1 - nested configuration sections, direct call
# ==========================================================================


@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("bad", NON_OBJECTS)
def test_non_object_section_is_refused(tmp_path, section, bad):
    path = tmp_path / "g.json"
    _write(path, _base_genome(**{section: bad}))

    with pytest.raises(PortableGenomeError) as excinfo:
        import_genome(path)

    assert str(excinfo.value) == f"{section} must be a JSON object"


@pytest.mark.parametrize("section", SECTIONS)
def test_section_refusal_leaks_no_supplied_value(tmp_path, section):
    path = tmp_path / "g.json"
    _write(path, _base_genome(**{section: [_SECRET, {"k": _SECRET}]}))

    with pytest.raises(PortableGenomeError) as excinfo:
        import_genome(path)

    msg = str(excinfo.value)
    assert _SECRET not in msg
    assert "[" not in msg and "{" not in msg
    assert msg == f"{section} must be a JSON object"


@pytest.mark.parametrize("section", SECTIONS)
def test_empty_object_section_still_imports(tmp_path, section):
    path = tmp_path / "g.json"
    _write(path, _base_genome(**{section: {}}))
    rule_spec, config, metadata = import_genome(path)
    assert rule_spec["rule"]["name"] is not None
    assert config is not None
    assert isinstance(metadata, dict)


def test_all_sections_absent_keeps_defaults(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome())
    rule_spec, config, metadata = import_genome(path)

    assert rule_spec["rule"]["name"] == "imported-genome"
    assert rule_spec["rule"]["neighborhood"] == "moore-3d"
    assert rule_spec["rule"]["transition"] == "outer-totalistic"
    assert config.stochastic.enabled is True
    assert config.stochastic.baseline_transition_prob == 0.08
    assert config.contagion.enabled is True
    assert config.contagion.energy_neighbor_threshold == 4
    assert config.decay.enabled is True
    assert config.cosmic.shield_strength == 0.85
    assert config.experimental.mamba_d_model == 64
    assert config.experimental.epsilon == 1e-8
    assert metadata["fitness"] == {}
    assert metadata["memory_layout"] == {}
    assert metadata["topology"] == {}


def test_populated_sections_preserve_every_value(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome(
        metadata={"name": "kept", "description": "d", "author": "a",
                  "version": "9.9.9", "target_lambda": 2.5},
        topology={"states": ["A", "B"], "neighborhood": "von-neumann",
                  "transition_mode": "totalistic"},
        stochastic={"enabled": False, "baseline_transition_prob": 0.42},
        contagion={"enabled": False, "energy_neighbor_threshold": 9},
        decay={"enabled": False, "inactivity_neighbor_threshold": 5},
        cosmic_garden={"shield_strength": 0.11, "damping_radius": 7},
        experimental={"mamba_d_model": 128, "epsilon": 2e-7,
                      "selective_memory_decay_enabled": True},
        fitness={"best": 0.75},
        memory_layout={"num_channels": 3},
    ))
    rule_spec, config, metadata = import_genome(path)

    assert rule_spec["rule"]["name"] == "kept"
    assert rule_spec["rule"]["states"] == ["A", "B"]
    assert rule_spec["rule"]["neighborhood"] == "von-neumann"
    assert rule_spec["rule"]["transition"] == "totalistic"
    assert rule_spec["params"]["meta"]["target_lambda"] == 2.5
    assert rule_spec["params"]["experimental"]["selective_memory_decay"]["enabled"] is True
    assert config.stochastic.enabled is False
    assert config.stochastic.baseline_transition_prob == 0.42
    assert config.contagion.energy_neighbor_threshold == 9
    assert config.decay.inactivity_neighbor_threshold == 5
    assert config.cosmic.shield_strength == 0.11
    assert config.cosmic.damping_radius == 7
    assert config.experimental.mamba_d_model == 128
    assert config.experimental.epsilon == 2e-7
    assert metadata["fitness"] == {"best": 0.75}
    assert metadata["memory_layout"] == {"num_channels": 3}
    assert metadata["name"] == "kept"


def test_transition_table_behaviour_unchanged(tmp_path):
    """The earlier package's contract still holds alongside the new checks."""
    path = tmp_path / "g.json"
    _write(path, _base_genome(transition_table={
        "void": {"3": "structural", "+4": "ENERGY"},
        "STRUCTURAL": {"0": "VOID"},
    }))
    _rule, config, _md = import_genome(path)

    # Exact expected mapping. Proves the whole earlier contract at once:
    # case-insensitive state names resolved ("void" -> VOID), neighbour keys
    # int()-converted ("+4" -> 4), and nothing else present. Comparing complete
    # dicts is order-independent, so this cannot pass by iteration accident.
    assert config.transition_table == {
        STATE_NAME_TO_ID["VOID"]: {
            3: STATE_NAME_TO_ID["STRUCTURAL"],
            4: STATE_NAME_TO_ID["ENERGY"],
        },
        STATE_NAME_TO_ID["STRUCTURAL"]: {
            0: STATE_NAME_TO_ID["VOID"],
        },
    }


def test_malformed_section_refused_before_config_construction(tmp_path, monkeypatch):
    """A malformed section must never reach a dataclass constructor."""
    import scripts.portable_genome as pg

    def _boom(*a, **k):
        raise AssertionError("configuration construction must not be reached")

    monkeypatch.setattr(pg, "StochasticConfig", _boom)
    path = tmp_path / "g.json"
    _write(path, _base_genome(stochastic=["not", "an", "object"]))

    with pytest.raises(PortableGenomeError) as excinfo:
        import_genome(path)
    assert str(excinfo.value) == "stochastic must be a JSON object"


# ==========================================================================
# GROUP 2 - public `info` CLI reachability
# ==========================================================================


@pytest.mark.parametrize("section", SECTIONS)
def test_info_cli_routes_section_refusal_to_exit_2(tmp_path, section):
    path = tmp_path / "g.json"
    _write(path, _base_genome(**{section: [1, 2, 3]}))

    proc = _info(path)

    assert proc.returncode == 2, proc.stderr
    assert f"{section} must be a JSON object" in proc.stderr
    assert "with transitions" not in proc.stdout


def test_info_cli_does_not_convert_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ this is not json", encoding="utf-8")
    proc = _info(path)
    assert proc.returncode != 2
    assert "JSONDecodeError" in proc.stderr or "Expecting" in proc.stderr


def test_info_cli_does_not_convert_missing_file(tmp_path):
    proc = _info(tmp_path / "absent.json")
    assert proc.returncode != 2
    assert "FileNotFoundError" in proc.stderr or "No such file" in proc.stderr


def test_unrelated_sentinel_is_not_converted(tmp_path, monkeypatch):
    import scripts.portable_genome as pg
    sentinel = RuntimeError("synthetic unrelated failure")

    def _boom(*a, **k):
        raise sentinel

    monkeypatch.setattr(pg, "StochasticConfig", _boom)
    path = tmp_path / "g.json"
    _write(path, _base_genome())

    with pytest.raises(RuntimeError) as excinfo:
        import_genome(path)
    assert excinfo.value is sentinel
    assert not isinstance(excinfo.value, PortableGenomeError)


# ==========================================================================
# GROUP 3 - epigenetic root and inclusion
# ==========================================================================


@pytest.mark.parametrize("root", [[], [1], "text", 7, 1.5, True, None])
def test_epigenetic_non_object_root(tmp_path, root):
    path = tmp_path / "g.json"
    _write(path, root)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "genome must be a JSON object"


@pytest.mark.parametrize("bad", NON_OBJECTS)
def test_epigenetic_section_must_be_object(tmp_path, bad):
    path = tmp_path / "g.json"
    _write(path, _base_genome(epigenetic_snapshot=bad))
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot must be a JSON object"


def test_absent_epigenetic_section_returns_none(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome())
    assert extract_epigenetic_snapshot(path) is None


def test_missing_included_returns_none(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome(epigenetic_snapshot={"lattice_shape": [1, 1, 1]}))
    assert extract_epigenetic_snapshot(path) is None


def test_included_false_returns_none_without_payload(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome(epigenetic_snapshot={"included": False}))
    assert extract_epigenetic_snapshot(path) is None


@pytest.mark.parametrize("bad", [
    pytest.param("true", id="string"), pytest.param(1, id="int-1"),
    pytest.param(0, id="int-0"), pytest.param(1.0, id="float"),
    pytest.param([], id="array"), pytest.param({}, id="object"),
    pytest.param(None, id="null"),
])
def test_included_must_be_boolean(tmp_path, bad):
    path = tmp_path / "g.json"
    _write(path, _base_genome(epigenetic_snapshot={"included": bad}))
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.included must be a boolean"


def test_included_true_missing_lattice_shape(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome(epigenetic_snapshot={"included": True, "lattice_b64": "AAA="}))
    with pytest.raises(PortableGenomeError):
        extract_epigenetic_snapshot(path)


def test_included_true_missing_lattice_b64(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _base_genome(epigenetic_snapshot={"included": True, "lattice_shape": [1, 1, 1]}))
    with pytest.raises(PortableGenomeError):
        extract_epigenetic_snapshot(path)


# ==========================================================================
# GROUP 4 - lattice shape and byte count
# ==========================================================================


@pytest.mark.parametrize("bad", [
    pytest.param("abc", id="string"), pytest.param(3, id="number"),
    pytest.param({"a": 1}, id="object"), pytest.param(None, id="null"),
    pytest.param([1, 2], id="too-short"), pytest.param([1, 2, 3, 4], id="too-long"),
    pytest.param([1, 2, True], id="boolean-dimension"),
    pytest.param([1, 2, "3"], id="string-dimension"),
    pytest.param([1, 2, 3.0], id="float-dimension"),
    pytest.param([1, 2, None], id="null-dimension"),
])
def test_lattice_shape_container_and_element_types(tmp_path, bad):
    g = _base_genome(epigenetic_snapshot={
        "included": True, "lattice_shape": bad, "lattice_b64": "AAAA"})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert "lattice_shape" in str(excinfo.value)
    assert "three integers" in str(excinfo.value)


@pytest.mark.parametrize("bad", [[-1, 2, 3], [1, -2, 3], [1, 2, -3]])
def test_negative_dimensions_have_their_own_message(tmp_path, bad):
    g = _base_genome(epigenetic_snapshot={
        "included": True, "lattice_shape": bad, "lattice_b64": "AAAA"})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.lattice_shape dimensions must be non-negative"


@pytest.mark.parametrize("bad_b64", [
    pytest.param("!!!!", id="foreign-alphabet"),
    pytest.param("QUJ", id="bad-padding"),
    pytest.param("QQ==QQ==", id="double-padding"),
])
def test_malformed_base64_is_refused_strictly(tmp_path, bad_b64):
    g = _base_genome(epigenetic_snapshot={
        "included": True, "lattice_shape": [1, 1, 1], "lattice_b64": bad_b64})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.lattice_b64 must be valid base64"


def test_non_ascii_base64_is_refused(tmp_path):
    g = _base_genome(epigenetic_snapshot={
        "included": True, "lattice_shape": [1, 1, 1], "lattice_b64": "AAé="})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.lattice_b64 must be valid base64"


@pytest.mark.parametrize("bad", [[], {}, 5, None, True])
def test_lattice_b64_must_be_string(tmp_path, bad):
    g = _base_genome(epigenetic_snapshot={
        "included": True, "lattice_shape": [1, 1, 1], "lattice_b64": bad})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.lattice_b64 must be a JSON string"


@pytest.mark.parametrize("delta, label", [(-1, "one-byte-short"), (1, "one-byte-long")])
def test_lattice_byte_count_must_match_shape(tmp_path, delta, label):
    shape = (2, 2, 2)
    n = 8 + delta
    payload = bytes(range(1, n + 1))
    path = tmp_path / "g.json"
    _write(path, _epi_genome(shape, lattice_bytes=payload))
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == (
        "epigenetic_snapshot.lattice_b64 byte count does not match lattice_shape")


def test_exact_lattice_bytes_round_trip(tmp_path):
    shape = (2, 3, 4)
    payload = bytes(range(24))
    path = tmp_path / "g.json"
    _write(path, _epi_genome(shape, lattice_bytes=payload))

    lattice, memory_grid, meta = extract_epigenetic_snapshot(path)

    assert lattice.shape == shape
    assert lattice.dtype == np.uint8
    assert np.array_equal(lattice, np.frombuffer(payload, dtype=np.uint8).reshape(shape))
    assert memory_grid is None
    assert meta == {"generation": 11, "ca_step": 22}
    # returned array is an independent copy
    assert lattice.flags["OWNDATA"]


def test_zero_sized_dimension_is_accepted(tmp_path):
    shape = (0, 2, 2)
    path = tmp_path / "g.json"
    _write(path, _epi_genome(shape, lattice_bytes=b""))
    lattice, memory_grid, _meta = extract_epigenetic_snapshot(path)
    assert lattice.shape == shape
    assert lattice.size == 0
    assert memory_grid is None


# ==========================================================================
# GROUP 5 - optional memory grid
# ==========================================================================


def test_absent_memory_grid_returns_none(tmp_path):
    path = tmp_path / "g.json"
    _write(path, _epi_genome((1, 1, 2), lattice_bytes=b"\x01\x02"))
    _lat, memory_grid, _meta = extract_epigenetic_snapshot(path)
    assert memory_grid is None


def test_malformed_memory_grid_base64(tmp_path):
    g = _epi_genome((1, 1, 1), lattice_bytes=b"\x01")
    g["epigenetic_snapshot"]["memory_grid_b64"] = "!!!!"
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.memory_grid_b64 must be valid base64"


@pytest.mark.parametrize("bad", [[], {}, 5, None, True])
def test_memory_grid_b64_must_be_string(tmp_path, bad):
    g = _epi_genome((1, 1, 1), lattice_bytes=b"\x01")
    g["epigenetic_snapshot"]["memory_grid_b64"] = bad
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "epigenetic_snapshot.memory_grid_b64 must be a JSON string"


@pytest.mark.parametrize("bad", NON_OBJECTS)
def test_memory_layout_must_be_object_on_epigenetic_path(tmp_path, bad):
    mg = np.zeros(MEMORY_CHANNELS * 1, dtype=np.float32).tobytes()
    g = _epi_genome((1, 1, 1), lattice_bytes=b"\x01", memory_bytes=mg, memory_layout=bad)
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "memory_layout must be a JSON object"


def test_missing_memory_layout_uses_default_channel_count(tmp_path):
    shape = (1, 1, 2)
    n = 2
    mg = np.arange(MEMORY_CHANNELS * n, dtype=np.float32).tobytes()
    path = tmp_path / "g.json"
    _write(path, _epi_genome(shape, lattice_bytes=b"\x01\x02", memory_bytes=mg))
    _lat, memory_grid, _meta = extract_epigenetic_snapshot(path)
    assert memory_grid.shape == (MEMORY_CHANNELS,) + shape
    assert memory_grid.dtype == np.float32


@pytest.mark.parametrize("bad", [
    pytest.param(0, id="zero"), pytest.param(-1, id="negative"),
    pytest.param(True, id="boolean"), pytest.param(2.0, id="float"),
    pytest.param("2", id="string"), pytest.param(None, id="null"),
    pytest.param([], id="array"),
])
def test_num_channels_must_be_positive_integer(tmp_path, bad):
    mg = np.zeros(4, dtype=np.float32).tobytes()
    g = _epi_genome((1, 1, 1), lattice_bytes=b"\x01", memory_bytes=mg,
                    memory_layout={"num_channels": bad})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "memory_layout.num_channels must be a positive integer"


@pytest.mark.parametrize("delta, label", [(-1, "one-short"), (1, "one-long")])
def test_memory_grid_byte_count_must_match(tmp_path, delta, label):
    shape = (1, 1, 2)
    channels = 3
    count = channels * 2 + delta
    mg = np.arange(count, dtype=np.float32).tobytes()
    g = _epi_genome(shape, lattice_bytes=b"\x01\x02", memory_bytes=mg,
                    memory_layout={"num_channels": channels})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == (
        "epigenetic_snapshot.memory_grid_b64 byte count does not match "
        "memory_layout and lattice_shape")


def test_exact_memory_grid_round_trip(tmp_path):
    shape = (1, 2, 2)
    channels = 3
    values = np.arange(channels * 4, dtype=np.float32) * 0.5
    g = _epi_genome(shape, lattice_bytes=bytes(range(4)), memory_bytes=values.tobytes(),
                    memory_layout={"num_channels": channels})
    path = tmp_path / "g.json"
    _write(path, g)

    lattice, memory_grid, meta = extract_epigenetic_snapshot(path)

    assert lattice.shape == shape
    assert memory_grid.shape == (channels,) + shape
    assert memory_grid.dtype == np.float32
    assert np.array_equal(memory_grid, values.reshape((channels,) + shape))
    assert memory_grid.flags["OWNDATA"]
    assert meta == {"generation": 11, "ca_step": 22}


# ==========================================================================
# GROUP 6 - exception hygiene and non-leak
# ==========================================================================


def test_epigenetic_messages_leak_no_payload_fragment(tmp_path):
    marker = "ZZZZSECRETZZZZ"
    payload = base64.b64encode(marker.encode()).decode("ascii")
    g = _base_genome(epigenetic_snapshot={
        "included": True, "lattice_shape": [9, 9, 9], "lattice_b64": payload})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    msg = str(excinfo.value)
    assert marker not in msg and payload not in msg
    assert "9" not in msg


def test_num_channels_refusal_leaks_no_value(tmp_path):
    mg = np.zeros(4, dtype=np.float32).tobytes()
    g = _epi_genome((1, 1, 1), lattice_bytes=b"\x01", memory_bytes=mg,
                    memory_layout={"num_channels": 987654})
    path = tmp_path / "g.json"
    _write(path, g)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert "987654" not in str(excinfo.value)


def test_invalid_json_still_propagates_from_epigenetic_path(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        extract_epigenetic_snapshot(path)


def test_missing_file_still_propagates_from_epigenetic_path(tmp_path):
    with pytest.raises(OSError):
        extract_epigenetic_snapshot(tmp_path / "absent.json")


def test_error_type_remains_valueerror_subclass():
    assert issubclass(PortableGenomeError, ValueError)
