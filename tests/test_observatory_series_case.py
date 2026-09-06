"""Default discovery is exact-case; custom globs retain native semantics.

All filesystem inputs are disposable. Archive-call doubles observe discovery
without replacing Path.glob; real eight-channel archives avoid engine migration.
Animation is replaced only at the rendering boundary, never executed.
"""

import json
import os
from pathlib import Path
import sys
import types

import numpy as np
import pytest

from vis.observatory import cli, loader


_WINDOWS = os.name == "nt"
_MIXED = ["V070_001.NPZ", "V070_3.npz", "v070_002.npz", "v070_10.npz"]


def _populate(root, names):
    for generation, name in enumerate(names, 1):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Passing a stream prevents NumPy appending '.npz' to an '.NPZ' name.
        with path.open("wb") as stream:
            np.savez(
                stream,
                lattice=np.zeros((1, 1, 1), dtype=np.uint8),
                memory_grid=np.zeros((8, 1, 1, 1), dtype=np.float32),
                generation=generation,
                ca_step=0,
                best_fitness=0.0,
            )


def _record_loads(monkeypatch, root, *, real=False, fail_on=None):
    calls = []
    original = loader.load_npz

    def record(path):
        relative = Path(path).relative_to(root).as_posix()
        calls.append(relative)
        if relative == fail_on:
            raise ValueError("selected archive sentinel")
        return original(path) if real else relative

    monkeypatch.setattr(loader, "load_npz", record)
    return calls


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("names,expected", [
    (["v070_10.npz", "v070_2.npz", "v070_002.npz"],
     ["v070_002.npz", "v070_2.npz", "v070_10.npz"]),
    (["V070_1.npz"], []),
    (["v070_1.NPZ"], []),
    ([], []),
    (_MIXED, _MIXED[2:]),
    (["v070_GEN3.npz", "v070_gen2.npz"],
     ["v070_GEN3.npz", "v070_gen2.npz"]),
    (["v070_.npz"], ["v070_.npz"]),
])
def test_default_exact_literals(tmp_path, monkeypatch, explicit, names, expected):
    _populate(tmp_path, names)
    calls = _record_loads(monkeypatch, tmp_path)
    options = {"pattern": "v070_*.npz"} if explicit else {}
    if expected:
        assert loader.load_snapshot_series(tmp_path, **options) == expected
    else:
        with pytest.raises(FileNotFoundError) as exc:
            loader.load_snapshot_series(tmp_path, **options)
        assert str(exc.value) == "No files matching 'v070_*.npz' in {}".format(tmp_path)
    assert calls == expected


def test_default_filter_precedes_sort_limit_and_loading(tmp_path, monkeypatch):
    _populate(tmp_path, _MIXED)
    calls = _record_loads(monkeypatch, tmp_path)
    keyed = []
    original_key = loader._natural_key

    def key(path):
        keyed.append(path.name)
        return original_key(path)

    monkeypatch.setattr(loader, "_natural_key", key)
    result = loader.load_snapshot_series(tmp_path, max_count=1)
    assert sorted(keyed) == sorted(_MIXED[2:])
    assert result == ["v070_002.npz"]
    assert calls == result


@pytest.mark.parametrize("pattern,names,windows,posix", [
    ("*.npz", _MIXED, _MIXED, _MIXED[1:]),
    ("*.NPZ", _MIXED, _MIXED, _MIXED[:1]),
    ("V070_*.npz", _MIXED, _MIXED, _MIXED[1:2]),
    ("**/v070_*.npz", ["a/v070_10.npz", "b/v070_2.npz", "c/V070_3.npz"],
     ["c/V070_3.npz", "b/v070_2.npz", "a/v070_10.npz"],
     ["b/v070_2.npz", "a/v070_10.npz"]),
    ("sub/*.npz", ["SUB/v070_2.npz"], None, None),
    ("SUB/*.npz", ["SUB/v070_2.npz"], ["SUB/v070_2.npz"], ["SUB/v070_2.npz"]),
])
def test_custom_patterns_keep_native_behavior(tmp_path, monkeypatch, pattern, names, windows, posix):
    _populate(tmp_path, names)
    calls = _record_loads(monkeypatch, tmp_path)
    expected = windows if _WINDOWS else posix
    if expected is None:
        # This single-fixture custom pattern follows native parent spelling,
        # which may use the pattern's casing or the on-disk casing. Do not
        # impose that spelling on top of native glob's matching contract.
        expected = [p.relative_to(tmp_path).as_posix() for p in tmp_path.glob(pattern)]
    if expected:
        assert loader.load_snapshot_series(tmp_path, pattern=pattern) == expected
    else:
        with pytest.raises(FileNotFoundError) as exc:
            loader.load_snapshot_series(tmp_path, pattern=pattern)
        assert str(exc.value) == "No files matching '{}' in {}".format(pattern, tmp_path)
    assert calls == expected


@pytest.mark.parametrize("limit,expected", [
    (None, 3), (1, 1), (2, 2), (99, 3), (0, 0),
    (-1, 2), (-100, 0), (True, 1), (False, 0),
])
def test_existing_slice_semantics(tmp_path, monkeypatch, limit, expected):
    ordered = ["v070_1.npz", "v070_2.npz", "v070_10.npz"]
    _populate(tmp_path, ordered)
    calls = _record_loads(monkeypatch, tmp_path)
    if expected:
        assert loader.load_snapshot_series(tmp_path, max_count=limit) == ordered[:expected]
    else:
        with pytest.raises(FileNotFoundError) as exc:
            loader.load_snapshot_series(tmp_path, max_count=limit)
        assert str(exc.value) == "No files matching 'v070_*.npz' in {}".format(tmp_path)
    assert calls == ordered[:expected]


@pytest.mark.parametrize("limit", [1.5, "1"])
@pytest.mark.parametrize("names", [[], ["v070_1.npz"], ["V070_1.NPZ"]])
def test_invalid_limit_precedes_empty_result_and_loading(tmp_path, monkeypatch, limit, names):
    _populate(tmp_path, names)
    calls = _record_loads(monkeypatch, tmp_path)
    with pytest.raises(TypeError):
        loader.load_snapshot_series(tmp_path, max_count=limit)
    assert calls == []


def test_discovery_failure_precedes_invalid_limit(tmp_path, monkeypatch):
    # Deliberate exception seam, not evidence of native permission behavior.
    sentinel = OSError("discovery sentinel")

    def fail_glob(self, pattern):
        raise sentinel

    monkeypatch.setattr(Path, "glob", fail_glob)
    calls = _record_loads(monkeypatch, tmp_path)
    with pytest.raises(OSError) as exc:
        loader.load_snapshot_series(tmp_path, max_count="bad")
    assert exc.value is sentinel
    assert calls == []


def test_selected_failure_stops_loading_and_limit_prevents_it(tmp_path, monkeypatch):
    _populate(tmp_path, ["v070_1.npz", "v070_2.npz", "v070_3.npz"])
    calls = _record_loads(monkeypatch, tmp_path, fail_on="v070_2.npz")
    assert loader.load_snapshot_series(tmp_path, max_count=1) == ["v070_1.npz"]
    assert calls == ["v070_1.npz"]
    calls.clear()
    with pytest.raises(ValueError, match="selected archive sentinel"):
        loader.load_snapshot_series(tmp_path)
    assert calls == ["v070_1.npz", "v070_2.npz"]


def test_matching_directory_still_reaches_archive_loader(tmp_path, monkeypatch):
    (tmp_path / "v070_1.npz").mkdir()
    calls = _record_loads(monkeypatch, tmp_path, real=True)
    with pytest.raises(OSError):
        loader.load_snapshot_series(tmp_path)
    assert calls == ["v070_1.npz"]


def test_discovery_adds_no_existence_or_file_type_probe(tmp_path, monkeypatch):
    _populate(tmp_path, _MIXED)
    calls = _record_loads(monkeypatch, tmp_path)

    def unexpected_probe(*args, **kwargs):
        pytest.fail("series discovery must not add an existence/file-type probe")

    # Spy at the Path layer after fixture setup; Path.glob remains genuine.
    with monkeypatch.context() as probes:
        probes.setattr(Path, "exists", unexpected_probe)
        probes.setattr(Path, "is_file", unexpected_probe)
        result = loader.load_snapshot_series(tmp_path)
    assert result == _MIXED[2:]
    assert calls == result


def test_real_archive_custom_upper_suffix_remains_supported(tmp_path):
    _populate(tmp_path, ["V070_001.NPZ"])
    path = tmp_path / "V070_001.NPZ"
    with pytest.raises(ValueError, match="Unknown file format: .NPZ"):
        loader.load_snapshot(path)
    snapshots = loader.load_snapshot_series(tmp_path, pattern="*.NPZ")
    assert len(snapshots) == 1
    assert Path(snapshots[0].source_path) == path
    assert snapshots[0].generation == 1


def test_real_default_does_not_open_malformed_mismatch(tmp_path, monkeypatch):
    _populate(tmp_path, ["v070_002.npz"])
    (tmp_path / "V070_001.NPZ").write_bytes(b"not an archive")
    calls = _record_loads(monkeypatch, tmp_path, real=True)
    snapshots = loader.load_snapshot_series(tmp_path, max_count=1)
    assert [Path(s.source_path).name for s in snapshots] == ["v070_002.npz"]
    assert calls == ["v070_002.npz"]


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("only_upper", [False, True])
def test_cli_default_membership_and_errors(tmp_path, monkeypatch, capsys, json_mode, only_upper):
    _populate(tmp_path, ["V070_001.NPZ"] if only_upper else ["v070_002.npz"])
    if not only_upper:
        (tmp_path / "V070_001.NPZ").write_bytes(b"not an archive")
    rendered = []
    animation = types.ModuleType("vis.observatory.animation")
    animation.animate_slices = lambda snapshots, **kw: rendered.append(
        [Path(s.source_path).name for s in snapshots]
    )
    monkeypatch.setitem(sys.modules, "vis.observatory.animation", animation)
    argv = (["--error-format", "json"] if json_mode else []) + ["animate", str(tmp_path)]
    status = cli.main(argv)
    output = capsys.readouterr()
    assert output.out == ""
    if only_upper:
        assert status == 1
        assert rendered == []
        assert len(output.err.splitlines()) == 1
        if json_mode:
            envelope = json.loads(output.err)
            assert envelope["code"] == "animation-directory-invalid"
            assert envelope["exit_status"] == 1
        else:
            assert "cannot animate" in output.err
    else:
        assert status == 0
        assert rendered == [["v070_002.npz"]]
        assert output.err == ""


def test_cli_renderer_failure_keeps_its_identity(tmp_path, monkeypatch):
    _populate(tmp_path, ["v070_1.npz"])
    animation = types.ModuleType("vis.observatory.animation")
    sentinel = ValueError("rendering sentinel")

    def fail_render(*args, **kwargs):
        raise sentinel

    animation.animate_slices = fail_render
    monkeypatch.setitem(sys.modules, "vis.observatory.animation", animation)
    with pytest.raises(ValueError) as exc:
        cli.main(["animate", str(tmp_path)])
    assert exc.value is sentinel
