"""Cross-module policy: snapshot loaders must not unpickle.

An NPZ member of object dtype is stored as a pickle, so loading one with
pickle enabled is arbitrary code execution by construction. This module is the
repository-wide gate: every covered loader must pass the literal
``allow_pickle=False``, explicitly.

Explicit rather than relying on NumPy's default -- which is already ``False`` --
because a default makes the property invisible at the call site and silently
reversible by an upstream change.

Scope note, stated once and honestly: this is an OBJECT-MEMBER REFUSAL, not
whole-archive validation. Nothing here claims resistance to decompression
amplification, absurd declared shapes, hostile member names or defects in
NumPy's own header parsing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Modules whose NPZ loader is covered by the pickle-free policy.
#: Renaming or moving one of these is a deliberate change: update this tuple.
TARGETS = (
    "scripts/acoustic_map.py",
    "scripts/geometry_daemon.py",
    "scripts/gpu_benchmark.py",
    "scripts/lucid_server.py",
    "scripts/medusa_api.py",
)

#: `scripts/portable_genome.py` is deliberately ABSENT from TARGETS.
#:
#: Its `np.load` is pinned to `allow_pickle=True` by an AST assertion in
#: `tests/test_portable_genome_config_shapes.py::test_export_cli_snapshot_path_unchanged`
#: (`assert keywords["allow_pickle"].value is True`), which lies outside this
#: package's authorized file boundary. Converting that loader requires
#: updating that assertion, so it is left for a separate authorized pass
#: rather than silently widening scope here. The repo-wide sweep below
#: therefore records it as the single known exception, by exact path, so it
#: cannot be forgotten and no OTHER regression can hide behind it.
KNOWN_PENDING = ("scripts/portable_genome.py",)


def _np_load_calls(tree):
    """Return every ``np.load(...)`` call in ``tree``.

    Deliberately np-qualified. A bare ``attr == "load"`` filter would also
    match `json.load` (`medusa_api.py`) and `tomli.load`
    (`portable_genome.py`), which live in these same files and would make the
    policy fail spuriously. Working from the AST also means the docstrings
    that mention ``np.load(...)`` in prose are correctly ignored.
    """
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "load"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "np"
    ]


def _assert_pickle_free(rel, tree):
    calls = _np_load_calls(tree)
    # Non-vacuity: a covered file that has lost its np.load has moved its
    # loader elsewhere, which is an API change, not a silent pass.
    assert calls, f"{rel}: no np.load found -- the loader moved; update TARGETS"
    for call in calls:
        keywords = {kw.arg: kw.value for kw in call.keywords}
        assert "allow_pickle" in keywords, (
            f"{rel}:{call.lineno} np.load must set allow_pickle explicitly; "
            "a bare call inherits NumPy's default, which is not a contract"
        )
        value = keywords["allow_pickle"]
        assert isinstance(value, ast.Constant) and value.value is False, (
            f"{rel}:{call.lineno} allow_pickle must be the literal False, "
            f"not {ast.dump(value)}"
        )


@pytest.mark.parametrize("rel", TARGETS)
def test_every_targeted_np_load_is_pickle_free(rel):
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} is missing -- the target list is stale"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # `np` really is numpy in this file, so the matcher means what it says.
    assert any(
        isinstance(node, ast.Import)
        and any(a.name == "numpy" and a.asname == "np" for a in node.names)
        for node in ast.walk(tree)
    ), f"{rel}: `np` is not bound to numpy"

    _assert_pickle_free(rel, tree)


@pytest.mark.parametrize("rel", TARGETS)
def test_no_pickle_enabling_escape_hatch_exists(rel):
    """No flag or compatibility mode may re-enable pickle.

    Tokens are precise. `os.environ` is NOT banned here: `medusa_api.py` reads
    `MEDUSA_EVENT_BUS_DISABLED` legitimately, and `gpu_accelerator` manipulates
    the environment for unrelated reasons. Only pickle-specific constructions
    are forbidden.
    """
    source = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    for banned in ("allow_pickle=True", "ALLOW_PICKLE", "allow-pickle"):
        assert banned not in source, f"{rel} references {banned}"


def test_no_unguarded_np_load_survives_under_scripts_or_vis():
    """Rename-proof sweep. `TARGETS` can go stale; this cannot.

    It also catches a seventh loader appearing later. The single known
    exception is listed by exact path so it is impossible to forget and
    impossible for another regression to hide behind.
    """
    offenders = []
    for path in sorted([*(_REPO_ROOT / "scripts").rglob("*.py"),
                        *(_REPO_ROOT / "vis").rglob("*.py")]):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for call in _np_load_calls(ast.parse(path.read_text(encoding="utf-8"))):
            keywords = {kw.arg: kw.value for kw in call.keywords}
            value = keywords.get("allow_pickle")
            if not (isinstance(value, ast.Constant) and value.value is False):
                offenders.append(rel)

    unexpected = sorted(set(offenders) - set(KNOWN_PENDING))
    assert unexpected == [], (
        f"np.load without literal allow_pickle=False: {unexpected}"
    )


def test_the_known_pending_exception_is_still_real():
    """If `portable_genome` is ever converted, this fails and the exception
    must be deleted -- so the list cannot rot into a permanent blind spot."""
    still_pending = []
    for rel in KNOWN_PENDING:
        tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        for call in _np_load_calls(tree):
            keywords = {kw.arg: kw.value for kw in call.keywords}
            value = keywords.get("allow_pickle")
            if not (isinstance(value, ast.Constant) and value.value is False):
                still_pending.append(rel)
    assert sorted(set(still_pending)) == sorted(KNOWN_PENDING), (
        "a KNOWN_PENDING module is now pickle-free -- remove it from the list "
        "and add it to TARGETS"
    )
