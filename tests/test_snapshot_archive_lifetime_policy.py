"""Cross-module policy: snapshot archives are owned, and closure proofs are real.

Two independent gates, both static.

1. OWNERSHIP -- every production NumPy load under `scripts/` and `vis/` must
   hand its result to a `with`, so the archive is released at a defined point
   rather than whenever finalisation happens to run.

2. PROOF INTEGRITY -- a closure assertion in the maintained snapshot tests may
   not be written with a permissive default such as
   ``getattr(handle, "closed", True)``. That form returns its default when the
   attribute is absent, so it passes on a handle that was never closed -- and,
   worse, on one that was never even opened.

Both matchers carry planted non-vacuity guards, because "no findings" and
"the detector is broken" produce identical output otherwise.

Scope, stated plainly: this is a STATIC gate over literal source. It cannot
prove an archive was released at runtime, and it does not attempt to model
ownership handed to another function or stored on an object.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories whose production loads must be owned.
SWEPT_DIRS = ("scripts", "vis")

#: Where closure proofs live. Asserted to exist and to yield files, because a
#: renamed directory would make `rglob` return nothing and the scan would pass
#: by looking at zero files.
TEST_DIR = "tests"

#: The loader this package exists to correct.
WORKSTREAM_B = "scripts/workstream_b_profile_predicates.py"


# ---------------------------------------------------------------------------
# Gate 1 -- production archive ownership
# ---------------------------------------------------------------------------


def _np_load_calls(node) -> list:
    """Every ``np.load(...)`` call inside ``node``.

    Deliberately narrow: a bare ``attr == "load"`` filter would also match
    `json.load` and `tomli.load`, which appear in these same trees. Pickle
    spellings and aliasing are already covered, far more thoroughly, by
    `tests/test_snapshot_pickle_policy.py`; this module asks a different
    question of the same call sites.
    """
    return [
        call for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "load"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "np"
    ]


def _owned_load_calls(scope) -> set:
    """Ids of the ``np.load`` calls in ``scope`` whose result reaches a ``with``.

    TWO shapes are accepted, and accepting both is essential:

      * direct   -- ``with np.load(path, allow_pickle=False) as snap:``
      * indirect -- ``loaded = np.load(...)``
                    ``owner = nullcontext(loaded) if isinstance(...) else loaded``
                    ``with owner as snap:``

    The indirect form is CONDITIONAL OWNERSHIP, used deliberately by
    `scripts/lucid_server.py` and `scripts/portable_genome.py`: `np.load`
    returns an `NpzFile` for a zip but a plain ndarray for a `.npy`, and an
    ndarray has no context-manager protocol. A matcher that recognised only the
    direct shape would report those two correct files as defects.

    Binding is followed transitively through ordinary assignments, so any
    number of intermediate names is fine.
    """
    owned = set()
    for call in _np_load_calls(scope):
        if _reaches_a_with(scope, call):
            owned.add(id(call))
    return owned


def _reaches_a_with(scope, call) -> bool:
    withs = [node for node in ast.walk(scope) if isinstance(node, ast.With)]

    # Direct: the call itself is the context expression.
    for node in withs:
        for item in node.items:
            if item.context_expr is call:
                return True

    # Indirect: follow the name the call was bound to, transitively.
    names: set = set()
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and node.value is call:
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    if not names:
        return False

    changed = True
    while changed:
        changed = False
        for node in ast.walk(scope):
            if not isinstance(node, ast.Assign):
                continue
            used = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
            if not (used & names):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True

    for node in withs:
        for item in node.items:
            if isinstance(item.context_expr, ast.Name) and item.context_expr.id in names:
                return True
    return False


def _unowned_loads(root=None, dirs=None) -> dict:
    """Map each swept file to how many of its NumPy loads reach no ``with``."""
    root = _REPO_ROOT if root is None else root
    dirs = SWEPT_DIRS if dirs is None else dirs
    counts: dict = {}
    for name in dirs:
        directory = root / name
        assert directory.is_dir(), (
            f"{name}/ is missing -- the sweep would silently cover nothing"
        )
        for path in sorted(directory.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = _np_load_calls(tree)
            if not calls:
                continue
            owned = _owned_load_calls(tree)
            missing = sum(1 for call in calls if id(call) not in owned)
            if missing:
                counts[path.relative_to(root).as_posix()] = missing
    return counts


def test_the_workstream_b_loader_owns_its_archive():
    """The specific defect this package corrects.

    Anchored so it cannot pass by finding nothing: the module, the function and
    exactly one load call must all be present before ownership is judged.
    """
    path = _REPO_ROOT / WORKSTREAM_B
    assert path.is_file(), f"{WORKSTREAM_B} is missing -- the target moved"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    loaders = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "load_snapshot"
    ]
    assert len(loaders) == 1, "expected exactly one load_snapshot definition"
    loader = loaders[0]

    calls = _np_load_calls(loader)
    assert len(calls) == 1, (
        f"expected exactly one np.load in load_snapshot, found {len(calls)}"
    )
    assert _reaches_a_with(loader, calls[0]), (
        "load_snapshot's archive is not handed to a `with`; release depends on "
        "finalisation, which does not hold on the exceptional path"
    )


def test_no_production_snapshot_load_is_left_unowned():
    """Rename-proof sweep. The named test above can go stale; this cannot."""
    counts = _unowned_loads()
    assert counts == {}, (
        f"NumPy load whose archive reaches no `with` (path -> count): {counts}"
    )


# --- ownership matcher non-vacuity ------------------------------------------

_PLANTED_UNOWNED = (
    "import numpy as np\n"
    "def f(p):\n"
    "    data = np.load(str(p), allow_pickle=False)\n"
    "    return data['lattice']\n"
)

_PLANTED_DIRECT = (
    "import numpy as np\n"
    "def f(p):\n"
    "    with np.load(str(p), allow_pickle=False) as data:\n"
    "        return data['lattice']\n"
)

_PLANTED_CONDITIONAL = (
    "import contextlib\n"
    "import numpy as np\n"
    "def f(p):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
    "    with owner as data:\n"
    "        return data['lattice']\n"
)


def test_the_ownership_matcher_detects_an_unowned_load():
    """Without this, an empty findings dict could mean a broken matcher."""
    tree = ast.parse(_PLANTED_UNOWNED)
    calls = _np_load_calls(tree)
    assert len(calls) == 1
    assert not _reaches_a_with(tree, calls[0])


@pytest.mark.parametrize(
    "source", [_PLANTED_DIRECT, _PLANTED_CONDITIONAL],
    ids=["direct-with", "conditional-nullcontext"],
)
def test_the_ownership_matcher_accepts_both_correct_shapes(source):
    """The conditional case is not academic: it is exactly what
    `scripts/lucid_server.py` and `scripts/portable_genome.py` do, and a
    matcher that rejected it would demand edits to correct files."""
    tree = ast.parse(source)
    calls = _np_load_calls(tree)
    assert len(calls) == 1
    assert _reaches_a_with(tree, calls[0])


def test_the_ownership_sweep_itself_can_see_a_planted_defect(tmp_path):
    """Non-vacuity for the sweep, not merely the matcher it calls.

    The sweep asserts an empty mapping, and an empty mapping is also what a
    wrong glob or an inverted comparison returns. Pointing the real function at
    a tree this test controls exercises the walk and the classification end to
    end -- including that a correct file is NOT reported.
    """
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "leaky.py").write_text(_PLANTED_UNOWNED, encoding="utf-8")
    (planted / "direct.py").write_text(_PLANTED_DIRECT, encoding="utf-8")
    (planted / "conditional.py").write_text(_PLANTED_CONDITIONAL, encoding="utf-8")

    assert _unowned_loads(root=tmp_path, dirs=("scripts",)) == {"scripts/leaky.py": 1}


# ---------------------------------------------------------------------------
# Gate 2 -- closure proofs may not use a permissive default
# ---------------------------------------------------------------------------


def _permissive_closure_defaults(tree) -> list:
    """``getattr(x, "closed", <default>)`` calls that supply a default.

    The default is the whole problem. `NpzFile` releases its handle by setting
    `fid` to ``None``, and `fid` is a CLASS attribute that is only assigned on
    the instance when `np.load` owned the file. So a handle that was never
    owned has no `closed` attribute to read, the default is returned, and an
    assertion built on it reports success for an archive that was never closed.

    Any default is flagged, not just a literal ``True``: a non-literal default
    cannot be read statically and is no safer.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "getattr"):
            continue
        if len(node.args) != 3:
            continue
        attr = node.args[1]
        if isinstance(attr, ast.Constant) and attr.value == "closed":
            found.append(node)
    return found


def _closure_proof_files() -> list:
    """Maintained tests that assert something about archive closure."""
    directory = _REPO_ROOT / TEST_DIR
    assert directory.is_dir(), (
        f"{TEST_DIR}/ is missing -- the closure-proof scan would cover nothing"
    )
    files = [
        path for path in sorted(directory.rglob("test_*.py"))
        if "closed" in path.read_text(encoding="utf-8")
    ]
    assert files, (
        f"no closure-asserting tests discovered under {TEST_DIR}/ -- the scan "
        "is looking in the wrong place"
    )
    return files


def test_closure_proof_files_are_actually_discovered():
    """Explicit non-vacuity for the scan's inputs.

    Everything below asserts "no bad pattern found". If discovery silently
    returned nothing, that would be indistinguishable from a clean tree.
    """
    files = _closure_proof_files()
    assert len(files) >= 5, (
        f"only {len(files)} closure-asserting test files found; the repository "
        "has many more, so discovery is probably broken"
    )


def test_no_snapshot_closure_proof_uses_a_permissive_default():
    """A closure assertion must fail when the handle was never closed."""
    offenders = {}
    for path in _closure_proof_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = _permissive_closure_defaults(tree)
        if hits:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            offenders[rel] = [node.lineno for node in hits]
    assert offenders == {}, (
        "closure proof written with a permissive getattr default "
        f"(path -> lines): {offenders}. Assert on the archive's own state "
        "instead -- `NpzFile.close()` drops `zip` unconditionally, so "
        "`handle.zip is None` is a witness that cannot pass by default."
    )


_PLANTED_PERMISSIVE = (
    'def test_bad(handle):\n'
    '    assert handle.fid is None or getattr(handle.fid, "closed", True)\n'
)

_PLANTED_STRICT = (
    'def test_good(handle):\n'
    '    assert handle.zip is None and (handle.fid is None or handle.fid.closed)\n'
)


def test_the_permissive_default_matcher_detects_a_planted_bad_example():
    """The exact shape this gate exists to keep out."""
    assert len(_permissive_closure_defaults(ast.parse(_PLANTED_PERMISSIVE))) == 1


def test_the_permissive_default_matcher_accepts_a_strict_control():
    """A genuine proof must not be flagged, or the gate would be unusable."""
    assert _permissive_closure_defaults(ast.parse(_PLANTED_STRICT)) == []
