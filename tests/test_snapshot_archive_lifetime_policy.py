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


def _numpy_load_names(tree):
    """Resolve, from ``tree``'s own imports, every name meaning NumPy ``load``.

    Returns ``(module_names, direct_names)``. Matching only the literal
    ``np.load`` was not enough: a module whose only load is spelled
    ``numpy.load``, ``from numpy import load`` or through an aliased import
    produced zero matches, and a file with zero matches is skipped entirely --
    so an unowned archive in any of those spellings was invisible to this gate
    rather than merely unclassified.
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
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
    return module_names, direct_names


def _np_load_calls(node, names=None) -> list:
    """Every NumPy ``load`` call inside ``node``.

    Deliberately NumPy-qualified: a bare ``attr == "load"`` filter would also
    match `json.load` and `tomli.load`, which appear in these same trees.
    ``names`` carries the resolution from the enclosing module, so a function
    scope can be searched with module-level import knowledge.
    """
    module_names, direct_names = names or _numpy_load_names(node)
    found = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if (isinstance(func, ast.Attribute) and func.attr == "load"
                and isinstance(func.value, ast.Name)
                and func.value.id in module_names):
            found.append(call)
        elif isinstance(func, ast.Name) and func.id in direct_names:
            found.append(call)
        elif (isinstance(func, ast.Call) and isinstance(func.func, ast.Name)
                and func.func.id == "getattr" and len(func.args) == 2
                and isinstance(func.args[0], ast.Name)
                and func.args[0].id in module_names
                and isinstance(func.args[1], ast.Constant)
                and func.args[1].value == "load"):
            found.append(call)
    return found


def _enclosing_scopes(tree) -> list:
    """Every function body in ``tree``, plus the module itself."""
    return [tree] + [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _scope_of(tree, call):
    """The innermost function containing ``call``, or the module tree."""
    best, best_size = tree, None
    for scope in _enclosing_scopes(tree):
        if scope is tree:
            continue
        if any(node is call for node in ast.walk(scope)):
            size = sum(1 for _ in ast.walk(scope))
            if best_size is None or size < best_size:
                best, best_size = scope, size
    return best


def _own_scope_nodes(scope) -> list:
    """Nodes belonging to ``scope`` itself, not to a nested function or lambda.

    A ``with`` inside a nested ``def`` that is never called does not own
    anything in the outer function, so descending into one would certify a leak.
    """
    out = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda, ast.ClassDef)):
                continue
            out.append(child)
            walk(child)

    walk(scope)
    return out


def _target_key(node):
    """A stable textual key for an assignment target or context expression.

    ``d`` -> ``"d"``; ``self.data`` -> ``"self.data"``; ``cache["s"]`` ->
    ``"cache['s']"``. Returning a QUALIFIED key rather than the base name is
    what stops ``self.data = np.load(...)`` from tainting ``self``, after which
    any ``with self.<anything>`` in the method would have certified the load.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _target_key(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Subscript):
        base = _target_key(node.value)
        if base is None or not isinstance(node.slice, ast.Constant):
            return None
        return f"{base}[{node.slice.value!r}]"
    return None


#: Context-manager adapters that genuinely pass ownership through to what they
#: wrap. Filtered by NAME on purpose: an earlier revision accepted ANY call
#: containing the load, so `with some_logger(np.load(p)) as fh:` counted as
#: ownership when it owns nothing.
_OWNERSHIP_ADAPTERS = {"closing", "nullcontext", "aclosing"}


def _refers_to(expr, keys, call) -> bool:
    """Does ``expr`` denote the archive -- the call, a tracked target, or an
    accepted adapter/conditional over one?

    Deliberately EXACT. An earlier revision accepted any expression that merely
    MENTIONED a tracked name, so ``with open(out % gen, "w")`` -- where ``gen``
    derived from the archive -- was read as owning it.
    """
    if expr is call:
        return True
    key = _target_key(expr)
    if key is not None and key in keys:
        return True
    if isinstance(expr, ast.IfExp):
        return (_refers_to(expr.body, keys, call)
                or _refers_to(expr.orelse, keys, call))
    if isinstance(expr, ast.Call):
        func = expr.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None)
        if name in _OWNERSHIP_ADAPTERS:
            return any(_refers_to(arg, keys, call) for arg in expr.args)
    return False


def _bound_targets(nodes, call) -> set:
    """Targets the archive is bound to, including one leg of a tuple assign."""
    keys = set()
    for node in nodes:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
            targets, value = [node.target], node.value
        else:
            continue
        if value is call:
            for target in targets:
                key = _target_key(target)
                if key:
                    keys.add(key)
        elif isinstance(value, ast.Tuple):
            for target in targets:
                if isinstance(target, ast.Tuple):
                    for sub, element in zip(target.elts, value.elts):
                        if element is call:
                            key = _target_key(sub)
                            if key:
                                keys.add(key)
    return keys


def _reaches_a_with(scope, call) -> bool:
    """Is ``call``'s result handed to a ``with`` (or explicitly closed) in ``scope``?

    Accepted, because each genuinely bounds the archive's lifetime:

      * ``with np.load(...) as snap:``                          -- direct
      * ``with contextlib.closing(np.load(...)) as snap:``      -- adapter
      * ``stack.enter_context(np.load(...))``                   -- ExitStack
      * ``loaded = np.load(...)`` / ``owner = nullcontext(loaded) if ... else loaded``
        / ``with owner as snap:``                               -- CONDITIONAL
      * ``d = np.load(...)`` / ``try: ... finally: d.close()``   -- explicit close
        (including ``self.data.close()`` and ``cache['s'].close()``)

    The conditional form is what `scripts/lucid_server.py` and
    `scripts/portable_genome.py` do, where `np.load` may return an ndarray with
    no context-manager protocol.

    REBINDING is honoured, adapters are matched by NAME, targets are tracked as
    QUALIFIED keys, and nested function bodies are excluded -- each of those
    closed a way of certifying an unowned archive.

    Stated limits, because a static gate cannot do reachability or aliasing:
    a ``with`` inside a conditional branch is accepted without proving that
    branch runs; ownership handed to another function is not modelled; and a
    target whose key cannot be spelled statically (a computed subscript) is not
    tracked. This answers "is the archive given an owner in this scope", not
    "does that owner run on every path".
    """
    nodes = _own_scope_nodes(scope)
    withs = [n for n in nodes if isinstance(n, (ast.With, ast.AsyncWith))]

    for node in nodes:
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "enter_context"
                and any(arg is call for arg in node.args)):
            return True

    keys = _bound_targets(nodes, call)

    changed = True
    while changed:
        changed = False
        for node in nodes:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if value is call:
                continue
            if _refers_to(value, keys, call):
                for target in targets:
                    key = _target_key(target)
                    if key and key not in keys:
                        keys.add(key)
                        changed = True
            else:
                for target in targets:
                    key = _target_key(target)
                    if key in keys:
                        keys.discard(key)
                        changed = True

    for node in withs:
        for item in node.items:
            if _refers_to(item.context_expr, keys, call):
                return True

    for node in nodes:
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "close"
                and _target_key(node.func.value) in keys):
            return True
    return False


def _owned_load_calls(tree) -> set:
    """Ids of the NumPy loads in ``tree`` whose archive reaches an owner."""
    names = _numpy_load_names(tree)
    owned = set()
    for call in _np_load_calls(tree, names):
        if _reaches_a_with(_scope_of(tree, call), call):
            owned.add(id(call))
    return owned


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

    calls = _np_load_calls(loader, _numpy_load_names(tree))
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

#: Correct idioms an earlier revision of this matcher reported as defects.
#: Keeping them here means a maintainer converting a loader to any of these is
#: not told their working code is broken.
_PLANTED_CLOSING = (
    "import contextlib\n"
    "import numpy as np\n"
    "def f(p):\n"
    "    with contextlib.closing(np.load(str(p), allow_pickle=False)) as d:\n"
    "        return d['lattice']\n"
)
_PLANTED_EXITSTACK = (
    "import contextlib\n"
    "import numpy as np\n"
    "def f(p):\n"
    "    with contextlib.ExitStack() as stack:\n"
    "        d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
    "        return d['lattice']\n"
)
_PLANTED_TRY_FINALLY = (
    "import numpy as np\n"
    "def f(p):\n"
    "    d = np.load(str(p), allow_pickle=False)\n"
    "    try:\n"
    "        return d['lattice']\n"
    "    finally:\n"
    "        d.close()\n"
)
_PLANTED_WALRUS = (
    "import numpy as np\n"
    "def f(p):\n"
    "    if (d := np.load(str(p), allow_pickle=False)) is not None:\n"
    "        with d as data:\n"
    "            return data['lattice']\n"
)

#: Unowned shapes an earlier revision certified as OWNED. Each is a real way to
#: leak an archive while looking managed.
_PLANTED_CROSS_FUNCTION = (
    "import numpy as np\n"
    "def a(p):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    return loaded['lattice']\n"
    "def b(loaded):\n"
    "    with loaded as d:\n"
    "        pass\n"
)
_PLANTED_REBOUND = (
    "import contextlib\n"
    "import numpy as np\n"
    "def f(p, q):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    first = loaded['lattice']\n"
    "    loaded = contextlib.nullcontext(q)\n"
    "    with loaded as d:\n"
    "        pass\n"
    "    return first\n"
)

#: Aliased spellings that produced ZERO matches before, so their files were
#: skipped entirely rather than judged.
_PLANTED_ALIASED = (
    "import numpy\n"
    "def f(p):\n"
    "    d = numpy.load(str(p), allow_pickle=False)\n"
    "    return d['lattice']\n"
)
_PLANTED_FROM_IMPORT = (
    "from numpy import load\n"
    "def f(p):\n"
    "    d = load(str(p), allow_pickle=False)\n"
    "    return d['lattice']\n"
)

#: Shapes an EARLIER revision of this matcher certified as owned. Each is a
#: real way to leak an archive while looking managed, and each is now flagged.
_PLANTED_UNRELATED_WRAPPER = (
    "import numpy as np\n"
    "def f(p, logger):\n"
    "    with logger(np.load(str(p), allow_pickle=False)) as fh:\n"
    "        pass\n"
)
_PLANTED_MENTIONS_DERIVED = (
    "import numpy as np\n"
    "def f(p, outdir):\n"
    "    d = np.load(str(p), allow_pickle=False)\n"
    "    gen = int(d['generation'])\n"
    "    out = outdir / ('r_%d.txt' % gen)\n"
    "    with open(out, 'w') as fh:\n"
    "        pass\n"
)
_PLANTED_SELF_TAINT = (
    "import numpy as np\n"
    "class C:\n"
    "    def f(self, p):\n"
    "        self.data = np.load(str(p), allow_pickle=False)\n"
    "        with self.lock:\n"
    "            pass\n"
)
_PLANTED_DERIVED_CLOSE = (
    "import numpy as np\n"
    "def f(p, mk):\n"
    "    d = np.load(str(p), allow_pickle=False)\n"
    "    stream = mk(d['lattice'])\n"
    "    stream.close()\n"
)
_PLANTED_NESTED_DEF = (
    "import numpy as np\n"
    "def f(p):\n"
    "    d = np.load(str(p), allow_pickle=False)\n"
    "    def never():\n"
    "        with d as x:\n"
    "            pass\n"
    "    return d['lattice']\n"
)

#: Correct shapes an earlier revision reported as defects.
_PLANTED_ATTRIBUTE_CLOSE = (
    "import numpy as np\n"
    "class C:\n"
    "    def f(self, p):\n"
    "        self.data = np.load(str(p), allow_pickle=False)\n"
    "        try:\n"
    "            return self.data['lattice']\n"
    "        finally:\n"
    "            self.data.close()\n"
)
_PLANTED_TUPLE_ASSIGN = (
    "import numpy as np\n"
    "def f(p):\n"
    "    d, meta = np.load(str(p), allow_pickle=False), None\n"
    "    with d as x:\n"
    "        return x['lattice']\n"
)


def _single_load(source):
    tree = ast.parse(source)
    calls = _np_load_calls(tree, _numpy_load_names(tree))
    assert len(calls) == 1, f"expected one NumPy load, found {len(calls)}"
    return tree, calls[0]


@pytest.mark.parametrize(
    "source",
    [_PLANTED_UNOWNED, _PLANTED_CROSS_FUNCTION, _PLANTED_REBOUND,
     _PLANTED_UNRELATED_WRAPPER, _PLANTED_MENTIONS_DERIVED, _PLANTED_SELF_TAINT,
     _PLANTED_DERIVED_CLOSE, _PLANTED_NESTED_DEF],
    ids=["no-owner", "with-in-another-function", "rebound-before-the-with",
         "unrelated-wrapper-call", "ctx-expr-merely-mentions-a-derived-name",
         "self-tainted-by-attribute-target", "close-on-a-derived-name",
         "with-only-in-an-uncalled-nested-def"],
)
def test_the_ownership_matcher_detects_unowned_loads(source):
    """Without these, an empty findings mapping could mean a broken matcher.

    The last two are not hypothetical: an earlier revision of this matcher
    searched the whole MODULE tree and propagated names through any assignment
    that merely mentioned them, so a `with` in a DIFFERENT function -- or one
    on a name since rebound to something else -- certified a leaking archive as
    owned.
    """
    tree, call = _single_load(source)
    assert not _reaches_a_with(_scope_of(tree, call), call)


@pytest.mark.parametrize(
    "source",
    [_PLANTED_DIRECT, _PLANTED_CONDITIONAL, _PLANTED_CLOSING,
     _PLANTED_EXITSTACK, _PLANTED_TRY_FINALLY, _PLANTED_WALRUS,
     _PLANTED_ATTRIBUTE_CLOSE, _PLANTED_TUPLE_ASSIGN],
    ids=["direct-with", "conditional-nullcontext", "contextlib-closing",
         "exitstack-enter-context", "try-finally-close", "walrus",
         "attribute-target-closed", "tuple-assignment"],
)
def test_the_ownership_matcher_accepts_correct_shapes(source):
    """A gate that rejects working code is worse than no gate.

    The conditional case is what `scripts/lucid_server.py` and
    `scripts/portable_genome.py` actually do. The other four are standard
    idioms a maintainer might reasonably convert to -- `ExitStack` especially,
    since it is the usual answer to acquire-then-conditionally-own.
    """
    tree, call = _single_load(source)
    assert _reaches_a_with(_scope_of(tree, call), call)


@pytest.mark.parametrize(
    "source", [_PLANTED_ALIASED, _PLANTED_FROM_IMPORT],
    ids=["numpy-load", "from-numpy-import-load"],
)
def test_aliased_numpy_load_spellings_are_still_seen(source):
    """A file whose only load matched nothing was SKIPPED, not judged.

    So an unowned archive spelled `numpy.load` or `from numpy import load` was
    invisible to this gate rather than merely unclassified.
    """
    tree, call = _single_load(source)
    assert not _reaches_a_with(_scope_of(tree, call), call)


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

    What this does NOT model, stated so the gate is not mistaken for more than
    it is: a bare ``assert handle.fid is None`` used as the SOLE witness is
    equally permissive for the same reason, but distinguishing it from the
    legitimate ``zip is None and (fid is None or fid.closed)`` conjunction
    needs dataflow this static matcher does not have. Nor does it see
    ``h.__dict__.get("closed", True)`` or a ``getattr`` whose attribute name is
    a variable. It catches the one spelling that actually occurred here.
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


def _asserts_closure(tree) -> bool:
    """Does this module actually touch an archive's closure machinery?

    A substring test for "closed" was far too coarse: it matched `fail_closed`,
    `disclosed`, `unclosed_array` and `test_category_vocabulary_is_closed`,
    pulling in ~30 files that assert nothing about closure. That did not harm
    the scan, but it made the non-vacuity floor below meaningless -- the guard
    would still have passed with every real closure proof in the repository
    deleted, which is precisely what it exists to catch.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"zip", "fid"}:
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) == 3
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "closed"):
            return True
    return False


def _closure_proof_files(root=None) -> list:
    """Maintained tests that genuinely assert something about archive closure."""
    root = _REPO_ROOT if root is None else root
    directory = root / TEST_DIR
    assert directory.is_dir(), (
        f"{TEST_DIR}/ is missing -- the closure-proof scan would cover nothing"
    )
    files = [
        path for path in sorted(directory.rglob("test_*.py"))
        if _asserts_closure(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert files, (
        f"no closure-asserting tests discovered under {TEST_DIR}/ -- the scan "
        "is looking in the wrong place"
    )
    return files


def _permissive_offenders(root=None) -> dict:
    """Path -> line numbers of permissive closure defaults."""
    root = _REPO_ROOT if root is None else root
    offenders = {}
    for path in _closure_proof_files(root):
        hits = _permissive_closure_defaults(
            ast.parse(path.read_text(encoding="utf-8"))
        )
        if hits:
            offenders[path.relative_to(root).as_posix()] = [n.lineno for n in hits]
    return offenders


def test_closure_proof_files_are_actually_discovered():
    """Explicit non-vacuity for the scan's inputs.

    Everything below asserts "no bad pattern found". If discovery silently
    returned nothing, that would be indistinguishable from a clean tree.
    """
    files = _closure_proof_files()
    # Six snapshot-consumer suites carry a real `zip`/`fid` witness, plus this
    # package's own. Discovery is now AST-based, so this floor counts genuine
    # closure proofs rather than any file that happens to contain "closed".
    assert len(files) >= 5, (
        f"only {len(files)} closure-asserting test files found; the repository "
        "has more, so discovery is probably broken"
    )


def test_no_snapshot_closure_proof_uses_a_permissive_default():
    """A closure assertion must fail when the handle was never closed."""
    offenders = _permissive_offenders()
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


def test_the_permissive_default_scan_itself_can_see_a_planted_file(tmp_path):
    """Non-vacuity for the whole assembly, not just the matcher.

    `test_no_snapshot_closure_proof_uses_a_permissive_default` asserts an empty
    mapping, and an empty mapping is also what a broken walk, a wrong glob or a
    failed discovery filter returns. Pointing the real functions at a tree this
    test controls exercises discovery, parsing and offender assembly end to
    end -- including that the strict control is NOT reported.
    """
    planted = tmp_path / TEST_DIR
    planted.mkdir()
    (planted / "test_bad.py").write_text(_PLANTED_PERMISSIVE, encoding="utf-8")
    (planted / "test_good.py").write_text(_PLANTED_STRICT, encoding="utf-8")

    assert len(_closure_proof_files(tmp_path)) == 2, "discovery missed a file"
    assert _permissive_offenders(tmp_path) == {f"{TEST_DIR}/test_bad.py": [2]}
