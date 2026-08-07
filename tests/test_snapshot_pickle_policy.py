"""Cross-module policy: snapshot loaders must not unpickle.

An NPZ member of object dtype is stored as a pickle, so loading one with
pickle enabled is arbitrary code execution by construction. This module is the
gate over ``scripts/`` and ``vis/`` -- see ``SWEPT_DIRS``, which is the honest
extent of it, not "the repository". Every covered loader must pass the literal
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
    "scripts/portable_genome.py",
)

#: There is deliberately NO exemption list. An earlier revision of this module
#: carried `KNOWN_PENDING`, holding `scripts/portable_genome.py` back because
#: its loader was pinned to `allow_pickle=True` by an AST assertion in a file
#: outside that package's authorized boundary. That assertion now asserts the
#: secure contract instead, the loader is converted, and the exemption has been
#: removed rather than left behind as a dormant hole -- an exemption mechanism
#: that no longer exempts anything is an invitation to reuse it.
#:
#: The sweep below therefore requires ZERO unguarded NumPy loads.

#: Directories the sweep covers. Asserted to exist, because `Path.rglob` on a
#: missing directory yields nothing silently -- renaming one would otherwise
#: narrow the sweep without any test noticing.
#:
#: Deliberately NOT the repository root. Widening it that far would sweep
#: `tests/`, where the pickle-enabling calls are legitimate positive controls,
#: and carving `tests/` back out would reintroduce exactly the exemption
#: mechanism removed above. Directories outside this tuple are unswept, and
#: saying so is the honest description of the gate.
SWEPT_DIRS = ("scripts", "vis")


def _numpy_load_names(tree):
    """Resolve, from ``tree``'s own imports, every name that means NumPy ``load``.

    Returns ``(module_names, direct_names)``.

    ``asname`` is honoured in BOTH import forms. An earlier revision set a flag
    from ``from numpy import load as npload`` but still matched only the literal
    name ``load``, so the aliased call slipped through the sweep entirely.

    A local rebinding is the same call under another name, so ``_l = np.load``
    is resolved too.
    """
    module_names = {"np", "numpy"}
    direct_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "numpy":
                    module_names.add(alias.asname or "numpy")
        elif isinstance(node, ast.ImportFrom) and node.module == "numpy":
            for alias in node.names:
                if alias.name == "load":
                    direct_names.add(alias.asname or "load")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if (isinstance(value, ast.Attribute) and value.attr == "load"
                and isinstance(value.value, ast.Name)
                and value.value.id in module_names):
            direct_names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return module_names, direct_names


def _np_load_calls(tree):
    """Return every NumPy ``load`` call in ``tree``.

    Deliberately NumPy-qualified. A bare ``attr == "load"`` filter would also
    match `json.load` (`medusa_api.py`) and `tomli.load`
    (`portable_genome.py`), which live in these same files and would make the
    policy fail spuriously. Working from the AST also means the docstrings
    that mention ``np.load(...)`` in prose are correctly ignored.

    Four spellings are matched: ``np.load`` / ``numpy.load`` / any aliased
    module, a direct name bound by ``from numpy import load [as ...]``, a name
    rebound from ``np.load``, and ``getattr(np, "load")(...)``. The sweep has
    no per-file "is `np` numpy?" backstop, so a module written in any of the
    other styles would otherwise slip past it.

    This matcher is necessarily name-based and therefore never complete on its
    own. ``_pickle_enabling_calls`` is the argument-based backstop that does
    not depend on guessing the callee's name.
    """
    module_names, direct_names = _numpy_load_names(tree)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == "load"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_names):
            found.append(node)
        elif isinstance(func, ast.Name) and func.id in direct_names:
            found.append(node)
        elif (isinstance(func, ast.Call) and isinstance(func.func, ast.Name)
                and func.func.id == "getattr" and len(func.args) == 2
                and isinstance(func.args[0], ast.Name)
                and func.args[0].id in module_names
                and isinstance(func.args[1], ast.Constant)
                and func.args[1].value == "load"):
            found.append(node)
    return found


def _pickle_enabling_calls(tree):
    """Calls that ask for pickle through a STATICALLY READABLE argument.

    Keyed on the argument rather than the callee, so it does not depend on
    guessing a name. ``np.load`` is not the only door: ``np.lib.npyio.NpzFile(
    fh, allow_pickle=True)`` and ``np.lib.format.read_array(fh,
    allow_pickle=True)`` reach the same unpickling code and are invisible to
    any matcher keyed on the callee's name.

    EXACTLY what is enforced, and nothing wider:

    * an explicit ``allow_pickle=`` keyword whose value is not the literal
      ``False``, on a call to anything;
    * ``**{"allow_pickle": ...}`` where the mapping is a LITERAL dict with a
      constant key.

    NOT enforced, and not claimed: any route where the argument is not
    statically readable -- ``**kwargs`` forwarded from elsewhere, a dict built
    at runtime, a name whose value is computed, ``functools.partial``, or a
    call reached through an object attribute. This is a static gate over
    literal source, not a proof that pickle can never be requested.

    Being AST rather than substring, it is not fooled by ``allow_pickle = True``
    with spaces, which the token scan below misses.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "allow_pickle":
                if not (isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is False):
                    found.append(node)
                    break
            elif keyword.arg is None and isinstance(keyword.value, ast.Dict):
                # `**{...}`. Only a literal mapping can be read; anything else
                # is out of scope and deliberately not guessed at.
                enabling = any(
                    isinstance(key, ast.Constant) and key.value == "allow_pickle"
                    and not (isinstance(value, ast.Constant) and value.value is False)
                    for key, value in zip(keyword.value.keys, keyword.value.values)
                )
                if enabling:
                    found.append(node)
                    break
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

    This is a raw substring scan and is therefore whitespace-sensitive --
    `allow_pickle = True` with spaces would pass it. That gap is closed
    structurally by `test_no_call_under_scripts_or_vis_asks_for_pickle`, which
    reads the AST and does not care how the argument is spaced. The scan is
    kept anyway because it also catches the token in prose, where a claim that
    pickle is enabled would be a lie about what the code now does.
    """
    source = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    for banned in ("allow_pickle=True", "ALLOW_PICKLE", "allow-pickle"):
        assert banned not in source, f"{rel} references {banned}"


def _sweep(root=None, dirs=None):
    """Walk ``dirs`` under ``root``; return ``(unguarded, enabling)`` per file.

    ``unguarded`` counts NumPy loads that do not pass literal ``False``;
    ``enabling`` counts calls of any name that ask for pickle.

    Parameterised on purpose. Hard-coding the repository root left the walk
    itself -- the glob, the classification, the relative-path key -- with no
    test of its own, so an inverted comparison or a wrong suffix would return
    an empty mapping and every assertion built on it would still pass.
    ``test_the_sweep_itself_can_see_a_planted_loader`` points this at a tree it
    controls for exactly that reason.
    """
    root = _REPO_ROOT if root is None else root
    dirs = SWEPT_DIRS if dirs is None else dirs
    unguarded, enabling = {}, {}
    for name in dirs:
        directory = root / name
        assert directory.is_dir(), (
            f"{name}/ is missing -- the sweep would silently cover nothing"
        )
        for path in sorted(directory.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _np_load_calls(tree):
                keywords = {kw.arg: kw.value for kw in call.keywords}
                value = keywords.get("allow_pickle")
                if not (isinstance(value, ast.Constant) and value.value is False):
                    unguarded[rel] = unguarded.get(rel, 0) + 1
            asking = len(_pickle_enabling_calls(tree))
            if asking:
                enabling[rel] = asking
    return unguarded, enabling


#: A module exercising every spelling the two matchers are meant to catch, plus
#: one they must ignore. Shared by both non-vacuity guards so the guards and
#: the matchers cannot drift apart.
_PLANTED_MODULE = (
    "import numpy as np\n"
    "import numpy as _alias\n"
    "from numpy import load as _aliased_load\n"
    "np.load('a.npz', allow_pickle=True)\n"          # plain, enabled
    "_alias.load('b.npz')\n"                          # aliased module, no kwarg
    "_aliased_load('c.npz', allow_pickle=True)\n"     # aliased direct import
    "getattr(np, 'load')('d.npz', allow_pickle=True)\n"   # getattr indirection
    "_rebound = np.load\n"
    "_rebound('e.npz', allow_pickle=True)\n"          # local rebinding
    "np.lib.npyio.NpzFile(fh, allow_pickle = True)\n"  # not `load` at all
    "np.lib.format.read_array(fh, allow_pickle=True)\n"  # nor is this
    "np.load('g.npz', **{'allow_pickle': True})\n"    # literal dict expansion
    "import json\n"
    "json.load(open('f.json'))\n"                     # must be ignored
)

#: Reaching `_np_load_calls`: the five `load`-named spellings plus the literal
#: dict expansion, which is a `load` call whose keyword is not readable as
#: `False` and so counts as unguarded. The `NpzFile` and `read_array`
#: constructors are not `load` calls and are caught only by the argument-based
#: matcher. `json.load` is caught by neither.
_PLANTED_UNGUARDED = 6
#: Every call whose `allow_pickle` is statically readable and not `False`,
#: including the whitespaced `NpzFile`, `read_array`, and the `**{...}` form.
_PLANTED_ENABLING = 7


def test_no_unguarded_np_load_survives_under_scripts_or_vis():
    """Rename-proof sweep. `TARGETS` can go stale; this cannot.

    It also catches a seventh loader appearing later. There is no exemption
    list to consult and no count to keep in step: the requirement is simply
    zero.
    """
    unguarded, _ = _sweep()
    assert unguarded == {}, (
        "NumPy load without literal allow_pickle=False (path -> count): "
        f"{unguarded}"
    )


def test_no_call_under_scripts_or_vis_asks_for_pickle():
    """The doors that are not called ``load``.

    ``np.load`` is one entry point to NumPy's unpickling code, not the only
    one: ``NpzFile(fh, allow_pickle=True)`` and ``read_array(...,
    allow_pickle=True)`` reach it directly and are invisible to a matcher keyed
    on the callee's name. This asks the other question -- did anything, under
    any name, request pickle through a statically readable argument.

    Static gate, stated exactly: it reads explicit ``allow_pickle=`` keywords
    and literal ``**{...}`` mappings. It does not resolve forwarded
    ``**kwargs``, runtime-built mappings or computed values, and does not claim
    to.
    """
    _, enabling = _sweep()
    assert enabling == {}, (
        "call requesting allow_pickle other than literal False (path -> count): "
        f"{enabling}"
    )


def test_the_matchers_can_actually_see_a_pickle_enabled_load():
    """Non-vacuity guard for the two matchers.

    Both sweeps assert an empty mapping, and an empty mapping is exactly what a
    broken matcher returns. Feeding them a module that really does enable
    pickle proves the detectors still detect, so a green sweep means "nothing
    found" rather than "nothing looked for".
    """
    tree = ast.parse(_PLANTED_MODULE)
    assert len(_np_load_calls(tree)) == _PLANTED_UNGUARDED
    assert len(_pickle_enabling_calls(tree)) == _PLANTED_ENABLING


def test_the_sweep_itself_can_see_a_planted_loader(tmp_path):
    """Non-vacuity guard for the sweep, not merely the matchers it calls.

    The guard above would still pass if `_sweep` globbed the wrong suffix,
    inverted its `allow_pickle` comparison, or walked a directory that yields
    nothing -- because it never calls `_sweep`. Pointing the real function at a
    tree this test controls exercises the walk, the classification and the
    relative-path key end to end.
    """
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "hostile.py").write_text(_PLANTED_MODULE, encoding="utf-8")
    (planted / "safe.py").write_text(
        "import numpy as np\n"
        "with np.load('a.npz', allow_pickle=False) as snap:\n"
        "    pass\n",
        encoding="utf-8",
    )

    unguarded, enabling = _sweep(root=tmp_path, dirs=("scripts",))

    assert unguarded == {"scripts/hostile.py": _PLANTED_UNGUARDED}
    assert enabling == {"scripts/hostile.py": _PLANTED_ENABLING}
