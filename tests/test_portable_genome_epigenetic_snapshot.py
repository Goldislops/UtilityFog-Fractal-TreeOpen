"""Structural refusal for ``scripts.portable_genome.extract_epigenetic_snapshot()``.

Scope: the *container shapes* this extractor dereferences -- the genome root,
``epigenetic_snapshot``, ``memory_layout``, ``lattice_shape``, the two base64
payload fields and ``num_channels``. Sibling module
``test_portable_genome_config_shapes.py`` covers ``import_genome()``'s seven
configuration sections. That module did not merely leave this function out of
scope -- it asserted the function was *untouched* by its package. That lock has
been updated there, deliberately, to record that this package extends into the
extractor and reuses its section helper rather than duplicating it.

Whole-schema validation, value ranges, payload lengths, dimension magnitudes
and cross-field consistency remain out of scope and are not asserted here.

Before this package every one of those was dereferenced without a shape check,
so a genome that parsed as valid JSON with the wrong type raised an ambient
``AttributeError`` (``.get()`` on a non-object) or ``TypeError`` (``tuple()``,
``base64.b64decode`` or ``reshape`` on a non-conforming value). Both are
programming-defect signals, so the Observatory CLI could not translate them
without also masking real bugs -- see
``tests/test_observatory_cli.py`` for the reachability half of this contract.

``PortableGenomeError`` subclasses ``ValueError``, so an ordinary
``ValueError`` handler translates a malformed file while genuine defects keep
propagating.
"""

from __future__ import annotations

import ast
import base64
import inspect
import json
import textwrap
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

import scripts.portable_genome as pg
from scripts.portable_genome import PortableGenomeError, extract_epigenetic_snapshot

SHAPE = (2, 2, 2)
CHANNELS = 8

# Every non-object JSON root. `{}` is excluded: it is a valid object.
NON_OBJECT_JSON = [
    pytest.param([], id="array-empty"),
    pytest.param([1, 2, 3], id="array"),
    pytest.param("genome", id="string"),
    pytest.param(5, id="number-int"),
    pytest.param(1.5, id="number-float"),
    pytest.param(True, id="bool-true"),
    pytest.param(False, id="bool-false"),
    pytest.param(None, id="null"),
]


def _b64(array):
    return base64.b64encode(array.tobytes()).decode("ascii")


def _valid_epi(with_memory=True):
    epi = {
        "included": True,
        "lattice_shape": list(SHAPE),
        "lattice_b64": _b64(np.zeros(SHAPE, dtype=np.uint8)),
        "snapshot_generation": 12,
        "snapshot_ca_step": 34,
    }
    if with_memory:
        epi["memory_grid_b64"] = _b64(np.zeros((CHANNELS,) + SHAPE, dtype=np.float32))
    return epi


def _write(tmp_path, document, name="genome.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Valid genomes keep working
# ---------------------------------------------------------------------------


def test_valid_genome_with_epigenetic_data_loads(tmp_path):
    path = _write(tmp_path, {
        "epigenetic_snapshot": _valid_epi(),
        "memory_layout": {"num_channels": CHANNELS},
    })
    lattice, memory_grid, meta = extract_epigenetic_snapshot(path)
    assert lattice.shape == SHAPE
    assert memory_grid.shape == (CHANNELS,) + SHAPE
    assert meta == {"generation": 12, "ca_step": 34}


def test_valid_genome_without_memory_grid_yields_none_grid(tmp_path):
    path = _write(tmp_path, {"epigenetic_snapshot": _valid_epi(with_memory=False)})
    lattice, memory_grid, _ = extract_epigenetic_snapshot(path)
    assert lattice.shape == SHAPE
    assert memory_grid is None


def test_absent_memory_layout_uses_default_channel_count(tmp_path):
    """The established default is preserved when the section is absent."""
    path = _write(tmp_path, {"epigenetic_snapshot": _valid_epi()})
    _, memory_grid, _ = extract_epigenetic_snapshot(path)
    assert memory_grid.shape == (pg.MEMORY_CHANNELS,) + SHAPE


def test_absent_epigenetic_snapshot_returns_none(tmp_path):
    path = _write(tmp_path, {"format": {"format_id": "utilityfog-portable-genome"}})
    assert extract_epigenetic_snapshot(path) is None


def test_epigenetic_snapshot_not_included_returns_none(tmp_path):
    path = _write(tmp_path, {"epigenetic_snapshot": {"included": False}})
    assert extract_epigenetic_snapshot(path) is None


# ---------------------------------------------------------------------------
# Structural refusals -- each at the site that dereferences the value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("root", NON_OBJECT_JSON)
def test_non_object_root_is_refused(tmp_path, root):
    """The reported defect: valid JSON with a non-object root."""
    path = _write(tmp_path, root)
    with pytest.raises(PortableGenomeError, match="genome must be a JSON object"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize("section", NON_OBJECT_JSON)
def test_non_object_epigenetic_snapshot_is_refused(tmp_path, section):
    path = _write(tmp_path, {"epigenetic_snapshot": section})
    with pytest.raises(PortableGenomeError, match="epigenetic_snapshot must be a JSON object"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize("section", NON_OBJECT_JSON)
def test_non_object_memory_layout_is_refused(tmp_path, section):
    path = _write(tmp_path, {
        "epigenetic_snapshot": _valid_epi(),
        "memory_layout": section,
    })
    with pytest.raises(PortableGenomeError, match="memory_layout must be a JSON object"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize(
    "value",
    [pytest.param(5, id="number"), pytest.param("xyz", id="string"),
     pytest.param(None, id="null"), pytest.param(True, id="bool"),
     pytest.param({"x": 1}, id="object")],
)
def test_non_array_lattice_shape_is_refused(tmp_path, value):
    epi = _valid_epi(with_memory=False)
    epi["lattice_shape"] = value
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    with pytest.raises(PortableGenomeError, match="lattice_shape must be a JSON array"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize(
    "entry",
    [pytest.param("2", id="string"), pytest.param(2.0, id="float"),
     pytest.param(None, id="null"), pytest.param(True, id="bool"),
     pytest.param([2], id="nested-array")],
)
def test_non_integer_lattice_shape_entry_is_refused(tmp_path, entry):
    """`bool` is excluded on purpose: ``type(True) is bool``, not ``int``."""
    epi = _valid_epi(with_memory=False)
    epi["lattice_shape"] = [2, entry, 2]
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    with pytest.raises(PortableGenomeError, match="lattice_shape entries must be integers"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize("field", ["lattice_b64", "memory_grid_b64"])
@pytest.mark.parametrize(
    "value",
    [pytest.param(5, id="number"), pytest.param(None, id="null"),
     pytest.param(True, id="bool"), pytest.param([], id="array"),
     pytest.param({}, id="object")],
)
def test_non_string_base64_field_is_refused(tmp_path, field, value):
    epi = _valid_epi()
    epi[field] = value
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    with pytest.raises(PortableGenomeError, match=f"{field} must be a JSON string"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize(
    "value",
    [pytest.param("eight", id="string"), pytest.param(None, id="null"),
     pytest.param([8], id="array"), pytest.param(8.0, id="float"),
     pytest.param(True, id="bool")],
)
def test_non_integer_num_channels_is_refused(tmp_path, value):
    path = _write(tmp_path, {
        "epigenetic_snapshot": _valid_epi(),
        "memory_layout": {"num_channels": value},
    })
    with pytest.raises(PortableGenomeError, match="num_channels must be an integer"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize("field", ["snapshot_generation", "snapshot_ca_step"])
@pytest.mark.parametrize(
    "value",
    [pytest.param("x", id="string"), pytest.param(None, id="null"),
     pytest.param([1], id="array"), pytest.param({}, id="object"),
     pytest.param(1.5, id="float"), pytest.param(True, id="bool")],
)
def test_non_integer_snapshot_counter_is_refused(tmp_path, field, value):
    """These are carried into the snapshot and formatted with ``:,`` by
    consumers, so a wrong type used to surface as a ValueError/TypeError raised
    far from this module."""
    epi = _valid_epi(with_memory=False)
    epi[field] = value
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    with pytest.raises(PortableGenomeError, match=f"{field} must be an integer"):
        extract_epigenetic_snapshot(path)


@pytest.mark.parametrize("field", ["snapshot_generation", "snapshot_ca_step"])
def test_absent_snapshot_counter_defaults_to_zero(tmp_path, field):
    epi = _valid_epi(with_memory=False)
    del epi[field]
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    _, _, meta = extract_epigenetic_snapshot(path)
    key = "generation" if field == "snapshot_generation" else "ca_step"
    assert meta[key] == 0


# ---------------------------------------------------------------------------
# Absence is still KeyError -- shape checks did not swallow it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["lattice_shape", "lattice_b64"])
def test_missing_required_field_still_raises_keyerror(tmp_path, field):
    epi = _valid_epi(with_memory=False)
    del epi[field]
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    with pytest.raises(KeyError):
        extract_epigenetic_snapshot(path)


# ---------------------------------------------------------------------------
# Message hygiene and the translation contract
# ---------------------------------------------------------------------------


def test_portable_genome_error_is_a_valueerror():
    """This is what lets an ordinary ValueError handler translate the refusal
    without catching AttributeError or TypeError wholesale."""
    assert issubclass(PortableGenomeError, ValueError)


HOSTILE = "s3cr3t-\r\n-value-<script>"


@pytest.mark.parametrize(
    "document, expected",
    [
        ({"epigenetic_snapshot": HOSTILE}, "epigenetic_snapshot must be a JSON object"),
        ({"epigenetic_snapshot": [HOSTILE]}, "epigenetic_snapshot must be a JSON object"),
    ],
)
def test_refusal_message_is_single_line_and_value_free(tmp_path, document, expected):
    path = _write(tmp_path, document)
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    message = str(excinfo.value)
    assert message == expected
    assert len(message.splitlines()) == 1
    assert HOSTILE not in message
    assert "s3cr3t" not in message


def test_hostile_lattice_shape_entry_is_not_echoed(tmp_path):
    epi = _valid_epi(with_memory=False)
    epi["lattice_shape"] = [2, HOSTILE, 2]
    path = _write(tmp_path, {"epigenetic_snapshot": epi})
    with pytest.raises(PortableGenomeError) as excinfo:
        extract_epigenetic_snapshot(path)
    assert str(excinfo.value) == "lattice_shape entries must be integers"


# ---------------------------------------------------------------------------
# No broad exception handler was introduced
# ---------------------------------------------------------------------------


def _handlers(func):
    source = textwrap.dedent(inspect.getsource(func))
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ExceptHandler)
    ]


@pytest.mark.parametrize(
    "func",
    [
        extract_epigenetic_snapshot,
        pg._require_json_object_section,
        pg._require_json_string,
        pg._require_lattice_shape,
        pg._require_channel_count,
        pg._require_counter,
    ],
)
def test_no_exception_handler_in_the_refusal_path(func):
    """The refusals are type checks, not caught-and-retranslated exceptions:
    nothing here can swallow an unrelated defect."""
    assert _handlers(func) == []
