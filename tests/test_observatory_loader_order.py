"""Tests for vis/observatory/loader.py — chronological snapshot series order."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vis.observatory.loader as loader_mod
from vis.observatory.loader import load_snapshot_series


def test_load_snapshot_series_is_chronological(tmp_path, monkeypatch):
    # Regression: sorted(glob(...)) is lexicographic, so gen9 loaded AFTER
    # gen10/gen100 despite the docstring's chronological promise (the
    # AGENT_HANDOFF snapshot-listing caveat, inside the loader itself).
    for name in ("v070_gen100.npz", "v070_gen9.npz", "v070_gen10.npz"):
        (tmp_path / name).touch()

    loaded = []
    monkeypatch.setattr(
        loader_mod, "load_npz", lambda p: (loaded.append(Path(p).name), p)[1]
    )

    load_snapshot_series(tmp_path)

    assert loaded == ["v070_gen9.npz", "v070_gen10.npz", "v070_gen100.npz"]


def test_natural_key_handles_mixed_tokens():
    from vis.observatory.loader import _natural_key

    names = [
        "v070_gen10_step2.npz",
        "v070_gen9_step10.npz",
        "v070_gen9_step2.npz",
        "v070_gen2.npz",
    ]
    ordered = sorted(names, key=lambda n: _natural_key(Path(n)))
    assert ordered == [
        "v070_gen2.npz",
        "v070_gen9_step2.npz",
        "v070_gen9_step10.npz",
        "v070_gen10_step2.npz",
    ]
