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
#: rather than silently widening scope here.
#:
#: Keyed to an exact COUNT, not just a path. Exempting the whole file would
#: let a SECOND pickle-enabled `np.load` be added there and hide behind the
#: exemption; requiring the count to stay at exactly one closes that.
KNOWN_PENDING = {"scripts/portable_genome.py": 1}

#: Directories the repo-wide sweep must cover. Asserted to exist, because
#: `Path.rglob` on a missing directory yields nothing silently -- renaming one
#: would otherwise narrow the sweep without any test noticing.
SWEPT_DIRS = ("scripts", "vis")


def _np_load_calls(tree):
    """Return every NumPy ``load`` call in ``tree``.

    Deliberately NumPy-qualified. A bare ``attr == "load"`` filter would also
    match `json.load` (`medusa_api.py`) and `tomli.load`
    (`portable_genome.py`), which live in these same files and would make the
    policy fail spuriously. Working from the AST also means the docstrings
    that mention ``np.load(...)`` in prose are correctly ignored.

    Both spellings are matched -- ``np.load`` / ``numpy.load`` via an
    attribute, and a bare ``load`` bound by ``from numpy import load``. The
    repo-wide sweep has no per-file "is `np` numpy?" backstop, so a new module
    written in either of the other two styles would otherwise slip past it.
    """
    aliases = {"np", "numpy"}
    bare_load_imported = any(
        isinstance(node, ast.ImportFrom) and node.module == "numpy"
        and any(a.name == "load" for a in node.names)
        for node in ast.walk(tree)
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "numpy":
                    aliases.add(alias.asname or "numpy")

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "load"
                and isinstance(func.value, ast.Name) and func.value.id in aliases):
            found.append(node)
        elif (bare_load_imported and isinstance(func, ast.Name)
                and func.id == "load"):
            found.append(node)
    return found


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


def _unguarded_load_counts():
    """Map each swept file to how many NumPy loads lack literal False."""
    counts = {}
    for name in SWEPT_DIRS:
        directory = _REPO_ROOT / name
        assert directory.is_dir(), (
            f"{name}/ is missing -- the sweep would silently cover nothing"
        )
        for path in sorted(directory.rglob("*.py")):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            for call in _np_load_calls(ast.parse(path.read_text(encoding="utf-8"))):
                keywords = {kw.arg: kw.value for kw in call.keywords}
                value = keywords.get("allow_pickle")
                if not (isinstance(value, ast.Constant) and value.value is False):
                    counts[rel] = counts.get(rel, 0) + 1
    return counts


def test_no_unguarded_np_load_survives_under_scripts_or_vis():
    """Rename-proof sweep. `TARGETS` can go stale; this cannot.

    It also catches a seventh loader appearing later. The known exception is
    matched on an exact COUNT, so a second pickle-enabled load added to the
    exempt file is still caught.
    """
    counts = _unguarded_load_counts()
    unexpected = {
        rel: n for rel, n in counts.items() if KNOWN_PENDING.get(rel) != n
    }
    assert unexpected == {}, (
        "NumPy load without literal allow_pickle=False (path -> count): "
        f"{unexpected}"
    )


def test_the_known_pending_exception_is_still_real():
    """If `portable_genome` is ever converted, this fails and the exception
    must be deleted -- so the list cannot rot into a permanent blind spot."""
    counts = _unguarded_load_counts()
    assert {rel: counts.get(rel, 0) for rel in KNOWN_PENDING} == KNOWN_PENDING, (
        "a KNOWN_PENDING module changed -- if it is now pickle-free, remove it "
        "from KNOWN_PENDING and add it to TARGETS"
    )
