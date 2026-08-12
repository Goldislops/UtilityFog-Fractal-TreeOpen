"""Cross-module policy: snapshot archives are owned, and closure proofs are real.

Two independent gates, both static.

1. OWNERSHIP -- every production NumPy load under `scripts/` and `vis/` must be
   written in one of THREE recognised syntactic forms, so the archive is
   released at a defined point rather than whenever finalisation happens to run.
   The claim is deliberately about FORM, not about safety: this gate does not
   decide whether arbitrary code releases a resource, because three rounds of
   review established that it cannot. See the note above Gate 1.

2. PROOF INTEGRITY -- a closure assertion in the maintained snapshot tests may
   not be written with a permissive default such as
   ``getattr(handle, "closed", True)``. That form returns its default when the
   attribute is absent, so it passes on a handle that was never closed -- and,
   worse, on one that was never even opened.

Both matchers carry planted non-vacuity guards, because "no findings" and
"the detector is broken" produce identical output otherwise.

Scope, stated plainly: this is a STATIC gate over literal source. It cannot
prove an archive was released at runtime, and it does not attempt to model
ownership handed to another function or stored on an object. It also reports
plenty of CORRECT code as unowned -- `try/finally`, `ExitStack`, `closing` and
async spellings among them -- which is the trade that makes it sound rather
than a defect awaiting a fix.
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
#
# THE RECOGNISED LANGUAGE IS DELIBERATELY TINY, AND THAT IS THE DESIGN.
#
# Earlier revisions tried to be a general Python ownership analyser: adapters,
# `ExitStack`, `try/finally`, aliases, walrus, tuple targets, async spellings.
# Every review round found more shapes it certified while the archive leaked --
# not because any single rule was careless, but because "does this arbitrary
# code release a resource on every path" is not a question a syntactic matcher
# can answer. Each patch bought one spelling and left the class open.
#
# So the question was changed. This gate no longer asks whether code is safe;
# it asks whether code is one of THREE forms already known to be safe, which
# between them cover every production site:
#
#   A. FUSED      -- `with np.load(...) as archive:`
#   B. ADJACENT   -- `archive = np.load(...)` then immediately `with archive:`
#   C. GUARDED    -- the exact production conditional-owner unit
#
# Everything else is reported UNOWNED, including correct code. That is not a
# defect to be fixed later; it is the trade that makes the gate sound. A
# maintainer who writes a correct idiom this gate does not know is told to use
# one of the three, which costs a small edit. A gate that guesses at an
# unfamiliar idiom costs an archive, silently, on the exceptional path.
#
# The consequence to accept honestly: this gate does NOT certify that
# `scripts/` releases every archive. It certifies that every load in `scripts/`
# is written in one of three forms whose release is structural.


def _numpy_load_names(tree):
    """Resolve, from ``tree``'s own imports, every name meaning NumPy ``load``.

    Returns ``(module_names, direct_names)``. Matching only the literal
    ``np.load`` was not enough: a module whose only load is spelled
    ``numpy.load``, ``from numpy import load`` or through an aliased import
    produced zero matches, and a file with zero matches is skipped entirely --
    so an unowned archive in any of those spellings was invisible to this gate
    rather than merely unclassified.

    This resolution stays deliberately BROAD, unlike everything below it. A
    load this fails to see is not judged at all, so breadth here is the
    conservative direction; breadth in the ownership rules is not.
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
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if (isinstance(value, ast.Attribute) and value.attr == "load"
                    and isinstance(value.value, ast.Name)
                    and value.value.id in module_names):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in direct_names:
                        direct_names.add(target.id)
                        changed = True
            elif isinstance(value, ast.Name) and value.id in module_names:
                # `nps = np` -- a plain module alias, the same hole that aliased
                # IMPORTS had: a file whose only load is spelled through it
                # would match nothing and be skipped rather than judged.
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in module_names:
                        module_names.add(target.id)
                        changed = True
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


def _statement_blocks(tree):
    """Every statement list in ``tree`` -- module body, function and class
    bodies, ``if``/``else``, loop bodies, ``try`` parts, ``with`` bodies.

    Forms B and C are properties of ADJACENT STATEMENTS IN ONE BLOCK, so the
    block is the whole unit of analysis. This replaced a scope walk that had to
    reason about which nodes "belong" to a scope, then about source positions
    within it, then about which bindings were still live at a position -- three
    layers of approximation, each of which shipped a false certification.
    """
    for node in ast.walk(tree):
        for _field, value in ast.iter_fields(node):
            if (isinstance(value, list) and value
                    and all(isinstance(item, ast.stmt) for item in value)):
                yield value


def _rebound_names(tree, established) -> set:
    """Every name ``tree`` can make mean something other than its import.

    Whole-tree and order-blind ON PURPOSE: a name rebound anywhere is refused
    everywhere. That over-rejects a file which rebinds after its last use, and
    that is the direction to be wrong in.

    Attribute and subscript targets contribute their ROOT name, because
    ``contextlib.nullcontext = fake`` leaves ``contextlib`` itself intact while
    changing the only thing this gate ever reads off it.
    """
    skip = {id(node) for node in established}
    rebound = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            rebound.add(node.id)
        elif (isinstance(node, (ast.Attribute, ast.Subscript))
                and isinstance(node.ctx, (ast.Store, ast.Del))):
            root = node
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name):
                rebound.add(root.id)
        elif isinstance(node, ast.arg):
            rebound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            rebound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                rebound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, getattr(ast, "MatchAs", ())) and getattr(node, "name", None):
            rebound.add(node.name)
        elif isinstance(node, getattr(ast, "MatchStar", ())) and getattr(node, "name", None):
            rebound.add(node.name)
        elif isinstance(node, getattr(ast, "MatchMapping", ())) and getattr(node, "rest", None):
            rebound.add(node.rest)
    return rebound


def _live_module_aliases(tree, module, before_line) -> set:
    """Names certainly denoting ``module`` at ``before_line``.

    Three requirements, each of which was a false certification:

      * the ``import`` must be a statement of the MODULE BODY -- one nested in
        a function, a class, an ``if TYPE_CHECKING:`` block or a
        ``try/except ImportError`` need not have run, or be in scope, where the
        guard is written;
      * it must PRECEDE the use;
      * the name must not be rebound anywhere in the file.

    Only ``import <module>`` counts. ``from`` imports bind a member, not the
    module, and are not part of the recognised language.
    """
    aliases, established = {}, []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name == module:
                name = alias.asname or module
                aliases.setdefault(name, node.lineno)
                established.append(node)
    rebound = _rebound_names(tree, established)
    return {name for name, line in aliases.items()
            if line < before_line and name not in rebound}


#: Names, beyond the module aliases resolved per file, whose meaning Form C's
#: soundness rests on. `builtins` is here because `builtins.isinstance = fake`
#: replaces the guard's predicate without ever writing the name `isinstance`.
_FORM_C_PROTECTED = frozenset({"isinstance", "builtins", "__builtins__"})


def _form_c_protected_names(tree) -> set:
    """Every name in ``tree`` whose meaning Form C depends on."""
    names = set(_FORM_C_PROTECTED)
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name in {"numpy", "contextlib"}:
                names.add(alias.asname or alias.name)
    return names


def _form_c_trust_survives(tree) -> bool:
    """Does this module leave Form C's protected objects alone?

    Form C is sound only if, AT THE GUARD, ``np.ndarray`` is NumPy's array
    type, ``isinstance`` is the builtin and ``nullcontext`` is contextlib's.
    Checking that those NAMES are not reassigned is not enough. The same
    substitution goes through ``setattr(np, "ndarray", object)``, through an
    alias (``a = np`` then ``a.ndarray = object``), through
    ``vars(np)["ndarray"] = ...``, through ``builtins.isinstance = ...``, or by
    handing the module to anything at all. Replace ``np.ndarray`` with
    ``object`` and the guard becomes TRUE for an ``NpzFile``, which then goes
    into the ``nullcontext`` arm that closes nothing -- the archive leaks while
    the three lines still read character-for-character like production.

    So the rule is not "these names are not rebound" but the narrower, purely
    syntactic "these names are only ever READ, and only in the single position
    each is legitimately used in": a module alias as the BASE of an attribute
    access, ``isinstance`` as the FUNCTION of a call. Any other appearance -- a
    bare argument, an assignment source, a return value, an element of a
    container -- is refused WITHOUT asking what the receiver does with it,
    because asking is dataflow analysis, and dataflow analysis is precisely
    what this gate gave up in exchange for being sound.

    TRUST BOUNDARY, stated plainly so it is not mistaken for more. This is a
    repository regression gate reading one module's literal source. It cannot
    resist monkeypatching performed by an IMPORTED module, a plugin, a
    `conftest`, a `.pth` file or the interpreter's start-up path, and it does
    not claim to. It closes the class a reviewer could have seen in the file in
    front of them, which is the class that reaches production by accident.
    """
    names = _form_c_protected_names(tree)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Name) and node.id in names):
            continue
        if not isinstance(node.ctx, ast.Load):
            return False
        parent = parents.get(id(node))
        if (isinstance(parent, ast.Attribute) and parent.value is node
                and isinstance(parent.ctx, ast.Load)):
            continue                      # `np.ndarray`, `contextlib.nullcontext`
        if isinstance(parent, ast.Call) and parent.func is node:
            continue                      # `isinstance(loaded, np.ndarray)`
        # The attribute access must be a READ. `builtins.isinstance = fake`
        # reads the name `builtins` and writes through it, which is the whole
        # substitution done without the protected name ever being a target.
        return False
    return True


def _is_bare_acquisition(statement, call) -> bool:
    """``<single bare name> = <the load>`` and nothing more elaborate.

    A tuple target, an attribute or subscript target, an annotated assignment
    with a wrapper, or a walrus are all refused: each needs a different rule
    about what the name means afterwards, and every such rule was a way in.
    """
    return (isinstance(statement, ast.Assign)
            and statement.value is call
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name))


def _owns_the_name(statement, name) -> bool:
    """A SYNCHRONOUS ``with`` whose FIRST context item is exactly ``name``.

    First, because an earlier item's ``__enter__`` can raise and ours would
    then never run. Synchronous, because ``NpzFile`` implements ``__enter__``
    and not ``__aenter__``: ``async with`` on one raises ``TypeError`` after
    the archive is already open, which is a leak, not a type error.
    """
    return (isinstance(statement, ast.With)
            and bool(statement.items)
            and isinstance(statement.items[0].context_expr, ast.Name)
            and statement.items[0].context_expr.id == name)


def _is_production_guard(test, archive, tree, line) -> bool:
    """``isinstance(<archive>, <numpy>.ndarray)`` -- the exact production test.

    The guard is the entire reason the ``nullcontext`` arm is sound: it is what
    sends an ``NpzFile``, the only object here holding a file handle, down the
    RAW arm where the ``with`` closes it. Any weakening -- an arbitrary
    condition, a different subject, a different type, a shadowed or spoofed
    ``isinstance``, an ``ndarray`` read off something that is not NumPy --
    routes the archive into the arm whose ``__exit__`` does nothing.
    """
    if not isinstance(test, ast.Call) or test.keywords or len(test.args) != 2:
        return False
    if any(isinstance(arg, ast.Starred) for arg in test.args):
        return False
    if not (isinstance(test.func, ast.Name) and test.func.id == "isinstance"):
        return False
    if "isinstance" in _rebound_names(tree, []):
        return False
    subject, expected = test.args
    if not (isinstance(subject, ast.Name) and subject.id == archive):
        return False
    return (isinstance(expected, ast.Attribute) and expected.attr == "ndarray"
            and isinstance(expected.value, ast.Name)
            and expected.value.id in _live_module_aliases(tree, "numpy", line))


def _is_nullcontext_wrap(expr, archive, tree, line) -> bool:
    """``<contextlib>.nullcontext(<archive>)``, module-qualified, one argument.

    Module-qualified ONLY: all three production sites spell it that way, and a
    directly imported ``nullcontext`` is therefore surface with no caller to
    justify it. Exactly one positional argument and no keywords, because
    ``nullcontext(archive, other)`` raises ``TypeError`` -- after ``np.load``
    has opened the archive, out of a statement that never entered a ``with``.
    """
    if not isinstance(expr, ast.Call) or expr.keywords or len(expr.args) != 1:
        return False
    argument = expr.args[0]
    if not (isinstance(argument, ast.Name) and argument.id == archive):
        return False
    func = expr.func
    return (isinstance(func, ast.Attribute) and func.attr == "nullcontext"
            and isinstance(func.value, ast.Name)
            and func.value.id in _live_module_aliases(tree, "contextlib", line))


def _guarded_owner_binding(statement, archive, tree):
    """The owner name bound by the exact production conditional, else ``None``.

    ``owner = nullcontext(<archive>) if isinstance(<archive>, np.ndarray)
    else <archive>`` -- in that ORIENTATION, which is the safety property and
    is asymmetric. Swapping the arms yields the same three lines and puts the
    ``NpzFile`` into the arm that closes nothing.

    The shape is necessary and not sufficient. Form C is the only recognised
    form whose safety depends on what other OBJECTS mean -- the guard's type,
    the guard's predicate, the adapter -- so it alone also requires that this
    module leaves those objects alone. See ``_form_c_trust_survives``, which
    also states the trust boundary.
    """
    if not (isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.IfExp)):
        return None
    if not _form_c_trust_survives(tree):
        return None
    conditional = statement.value
    line = statement.lineno
    if not _is_production_guard(conditional.test, archive, tree, line):
        return None
    if not _is_nullcontext_wrap(conditional.body, archive, tree, line):
        return None
    if not (isinstance(conditional.orelse, ast.Name)
            and conditional.orelse.id == archive):
        return None
    return statement.targets[0].id


def _is_owned(tree, call) -> bool:
    """Is ``call``'s archive written in one of the THREE recognised forms?

    A. FUSED -- the load IS the first context item of a synchronous ``with``.
       Acquisition and protection are one operation, so it does not matter what
       ``if``, loop or ``try`` the statement sits in: whenever the load runs,
       the ``with`` runs.

    B. ADJACENT -- ``archive = np.load(...)`` followed IMMEDIATELY, in the same
       statement block, by a synchronous ``with`` on that exact bare name.
       Nothing may intervene, because anything that can raise between the two
       leaves the archive live and unmanaged.

    C. GUARDED -- the acquisition, then the exact production conditional-owner
       assignment, then the owning ``with``: three statements, adjacent, in one
       block.

    Anything else is UNOWNED, including correct code. See the note at the top
    of this gate for why that is the design and not an omission.
    """
    # A -- FUSED. A purely local property of the load's own parent, so no scope
    # or ordering analysis is involved at all.
    for node in ast.walk(tree):
        if (isinstance(node, ast.With) and node.items
                and node.items[0].context_expr is call):
            return True

    # B and C -- the load must be the whole right-hand side of a bare-name
    # assignment, and the statements that follow it in ITS OWN block decide.
    for block in _statement_blocks(tree):
        for index, statement in enumerate(block):
            if not _is_bare_acquisition(statement, call):
                continue
            archive = statement.targets[0].id
            if index + 1 < len(block) and _owns_the_name(block[index + 1], archive):
                return True
            if index + 2 < len(block):
                owner = _guarded_owner_binding(block[index + 1], archive, tree)
                if owner and _owns_the_name(block[index + 2], owner):
                    return True
            # The acquisition has been found; a statement lives in exactly one
            # block, so no other block can own this archive.
            return False
    return False


def _owned_load_calls(tree) -> set:
    """Ids of the NumPy loads in ``tree`` written in a recognised form."""
    names = _numpy_load_names(tree)
    return {id(call) for call in _np_load_calls(tree, names)
            if _is_owned(tree, call)}


def _unowned_loads(root=None, dirs=None) -> dict:
    """Map each swept file to how many of its NumPy loads are unrecognised."""
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
    assert _is_owned(tree, calls[0]), (
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

# --- temporal-order controls ------------------------------------------------
#
# Every one of these was mis-classified by a whole-scope, order-blind matcher.
# They are planted here so the ordering guarantees cannot regress silently.

#: An alias created BEFORE the load captured a different object entirely.
_PLANTED_STALE_ALIAS = (
    "import numpy as np\n"
    "def f(p, previous):\n"
    "    owner = previous\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    with owner as data:\n"
    "        pass\n"
    "    return loaded['lattice']\n"
)

#: The alias captured the archive BEFORE the original name was rebound, so it
#: still owns it. A fixed point that erased history got this wrong the other
#: way -- reporting correct code as a defect.
_PLANTED_ALIAS_SURVIVES_REBIND = (
    "import numpy as np\n"
    "def f(p, replacement):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    owner = loaded\n"
    "    loaded = replacement\n"
    "    with owner as data:\n"
    "        return data['lattice']\n"
)

#: Only ONE arm of the conditional owns the archive; the other hands the `with`
#: an unrelated object.
_PLANTED_ONE_SIDED_CONDITIONAL = (
    "import contextlib\n"
    "import numpy as np\n"
    "def f(p, condition, unrelated):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    owner = (\n"
    "        contextlib.nullcontext(loaded)\n"
    "        if condition\n"
    "        else unrelated\n"
    "    )\n"
    "    with owner as data:\n"
    "        return data['lattice']\n"
)

#: If the member access raises, the close is never reached -- so this does not
#: own the archive on the exceptional path the gate claims to cover.
_PLANTED_BARE_CLOSE = (
    "import numpy as np\n"
    "def f(p):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    value = loaded['lattice']\n"
    "    loaded.close()\n"
    "    return value\n"
)

#: A close that runs BEFORE acquisition cannot certify the archive acquired
#: afterwards.
_PLANTED_CLOSE_BEFORE_LOAD = (
    "import numpy as np\n"
    "def f(p, loaded):\n"
    "    loaded.close()\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    return loaded['lattice']\n"
)

#: An arbitrary method that merely SHARES a name with a contextlib adapter.
_PLANTED_SPOOFED_ADAPTER = (
    "import numpy as np\n"
    "def f(p, logger):\n"
    "    loaded = np.load(str(p), allow_pickle=False)\n"
    "    with logger.nullcontext(loaded) as data:\n"
    "        return data['lattice']\n"
)
_PLANTED_SPOOFED_ENTER_CONTEXT = (
    "import numpy as np\n"
    "def f(p, logger):\n"
    "    logger.enter_context(np.load(str(p), allow_pickle=False))\n"
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
     _PLANTED_DERIVED_CLOSE, _PLANTED_NESTED_DEF, _PLANTED_STALE_ALIAS,
     _PLANTED_ONE_SIDED_CONDITIONAL, _PLANTED_BARE_CLOSE,
     _PLANTED_CLOSE_BEFORE_LOAD, _PLANTED_SPOOFED_ADAPTER,
     _PLANTED_SPOOFED_ENTER_CONTEXT],
    ids=["no-owner", "with-in-another-function", "rebound-before-the-with",
         "unrelated-wrapper-call", "ctx-expr-merely-mentions-a-derived-name",
         "self-tainted-by-attribute-target", "close-on-a-derived-name",
         "with-only-in-an-uncalled-nested-def", "alias-created-before-the-load",
         "one-sided-conditional-owner", "bare-close-after-a-raising-access",
         "close-before-acquisition", "spoofed-adapter-name",
         "spoofed-enter-context"],
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
    assert not _is_owned(tree, call)


@pytest.mark.parametrize(
    "source",
    [_PLANTED_DIRECT, _PLANTED_CONDITIONAL],
    ids=["direct-with", "conditional-nullcontext"],
)
def test_the_ownership_matcher_accepts_correct_shapes(source):
    """The two shapes production actually writes: form A and form C.

    `contextlib.closing`, `ExitStack`, `try/finally` and an attribute-target
    close used to be accepted here too. They are correct Python, and no
    production site uses any of them; each was an admission whose rules kept
    certifying leaks, so all four are now conservative rejections -- see
    `_PLANTED_NARROWED_BY_THE_SMALL_LANGUAGE`, which keeps every one of them as
    an explicit, named trade rather than deleting the evidence.
    """
    tree, call = _single_load(source)
    assert _is_owned(tree, call)


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
    assert not _is_owned(tree, call)


# --- rebinding-form and finally-shape controls ------------------------------
#
# Each of these was certified as OWNED by a matcher that recognised only plain
# assignments as bindings, walked into nested scopes when looking for a
# `close()`, or judged "risky use" by subscripts alone. They are kept as data
# rather than named constants because the point is the SHAPE, not the name.

_PLANTED_LEAKS = {
    "for-target-rebind":
        "import numpy as np\n"
        "def f(p, q):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    first = loaded['lattice']\n"
        "    for loaded in q:\n        pass\n"
        "    with loaded as d:\n        pass\n"
        "    return first\n",
    "with-as-rebind":
        "import numpy as np\n"
        "def f(p, other):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    with other as loaded:\n        pass\n"
        "    with loaded as d:\n        pass\n",
    "except-as-rebind":
        "import numpy as np\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        pass\n"
        "    except Exception as loaded:\n        pass\n"
        "    with loaded as d:\n        pass\n",
    "augmented-assign-rebind":
        "import numpy as np\n"
        "def f(p, other):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    loaded += other\n"
        "    with loaded as d:\n        pass\n",
    "del-then-with":
        "import numpy as np\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    del loaded\n"
        "    with loaded as d:\n        pass\n",
    "tuple-target-rebind":
        "import contextlib\n"
        "import numpy as np\n"
        "def f(p, q):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    first = loaded['lattice']\n"
        "    loaded, meta = contextlib.nullcontext(q), None\n"
        "    with loaded as d:\n        pass\n"
        "    return first\n",
    "swap-rebind":
        "import numpy as np\n"
        "def f(p, e):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    d, e = e, d\n"
        "    with d as x:\n        pass\n",
    "close-inside-a-nested-def-in-finally":
        "import numpy as np\n"
        "def f(p, register):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n"
        "        def later():\n            d.close()\n"
        "        register(later)\n",
    "close-via-lambda-in-finally":
        "import numpy as np\n"
        "def f(p, register):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        register(lambda: d.close())\n",
    "non-subscript-risky-use-outside-the-try":
        "import numpy as np\n"
        "def f(p, consume):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    result = consume(d)\n"
        "    try:\n        pass\n    finally:\n        d.close()\n"
        "    return result\n",
    "iteration-risky-use-outside-the-try":
        "import numpy as np\n"
        "def f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    keys = list(d)\n"
        "    try:\n        pass\n    finally:\n        d.close()\n"
        "    return keys\n",
    "loop-carried-acquisition-owned-outside-the-loop":
        "import numpy as np\n"
        "def f(paths, report):\n"
        "    for p in paths:\n"
        "        d = np.load(str(p), allow_pickle=False)\n"
        "        report(d['lattice'])\n"
        "    with d as x:\n        pass\n",
    "conditional-close-in-finally":
        "import numpy as np\n"
        "def f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n"
        "        if cond:\n            d.close()\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_LEAKS.values()),
                         ids=list(_PLANTED_LEAKS))
def test_rebinding_and_finally_shapes_are_not_certified(source):
    """Thirteen ways to leak an archive while looking managed.

    Every one was reported OWNED before this control existed. What rejects them
    NOW is worth stating exactly, because it is not what the shapes suggest:
    there is no rebinding analysis and no `finally` analysis left to catch them.
    The first ten die because a rebinding is a statement, and form B admits no
    statement between the acquisition and the `with`. The last three die because
    `try/finally` closure is not a recognised form at all.

    They stay because the SHAPES are the regression risk, whichever rule
    currently catches them -- and the rule that catches them today is the
    cheapest one this file has ever had.
    """
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize(
    "source",
    ["import numpy as np\n"
     "def f(paths, report):\n"
     "    for p in paths:\n"
     "        with np.load(str(p), allow_pickle=False) as d:\n"
     "            report(d['lattice'])\n"],
    ids=["owner-inside-the-same-loop"],
)
def test_the_stricter_rules_still_accept_correct_code(source):
    """A fused load inside a loop body is form A wherever it sits.

    Each iteration's archive is closed by its own `with`, so the enclosing loop
    is irrelevant -- which is the whole point of form A being a property of the
    load's own parent node rather than of the surrounding control flow.
    """
    tree, call = _single_load(source)
    assert _is_owned(tree, call)

# --- adapter-semantics and stack controls -----------------------------------
#
# `nullcontext.__exit__` is a NO-OP: it discards the wrapped object's own
# `__exit__`. Treating it as an ownership adapter meant
# `with nullcontext(np.load(p)) as d:` read as owned while leaking, and -- worse
# -- deleting the `isinstance` guard from the production loader, the single most
# likely simplification, still read as owned. Form C is the one place
# `nullcontext` is recognised, and only with that guard intact.
#
# The stack shapes below were once judged by a liveness rule. There is no such
# rule now -- `ExitStack` is not a recognised form in any spelling -- so they
# are refused for the same reason `print(np.load(p))` is. Kept because the day
# someone re-adds stack support, these are what fail.

_PLANTED_ADAPTER_LEAKS = {
    "unconditional-nullcontext-wraps-the-archive":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.nullcontext(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "unconditional-nullcontext-via-module-alias":
        "import contextlib as ctx\nimport numpy as np\ndef f(p):\n"
        "    with ctx.nullcontext(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "production-shape-with-the-guard-deleted":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)\n"
        "    with owner as data:\n        return data['lattice']\n",
    "exitstack-never-entered":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    stack = contextlib.ExitStack()\n"
        "    d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "    return d['lattice']\n",
    "exitstack-already-unwound":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n        pass\n"
        "    d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "    return d['lattice']\n",
    "exitstack-rebound-before-enter-context":
        "import contextlib\nimport numpy as np\ndef f(p, fake):\n"
        "    with contextlib.ExitStack() as stack:\n        pass\n"
        "    stack = fake\n"
        "    d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "    return d['lattice']\n",
}

_PLANTED_ADAPTER_CORRECT = {
    "guarded-conditional-nullcontext":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "with-d-as-d-self-rebinding":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with d as d:\n        return d['lattice']\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_ADAPTER_LEAKS.values()),
                         ids=list(_PLANTED_ADAPTER_LEAKS))
def test_adapter_and_stack_leaks_are_not_certified(source):
    """`nullcontext` closes nothing, and an un-entered stack unwinds nothing."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


#: CONSERVATIVELY REJECTED. `stack.callback(d.close)` on a live ExitStack does
#: release the archive, but no `ExitStack` spelling is recognised at all now, so
#: this is refused along with the rest. Reported unowned BY DESIGN: rejecting a
#: safe idiom costs a reviewer one look; certifying a leak costs the archive.
_PLANTED_CONSERVATIVELY_REJECTED = {
    "stack-callback-close-in-a-live-stack":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = np.load(str(p), allow_pickle=False)\n"
        "        stack.callback(d.close)\n"
        "        return d['lattice']\n",
}


#: Kept as explicit conservative rejections rather than quietly deleted. Each
#: is CORRECT Python; none is form A, B or C:
#:   * walrus in an `if` TEST with the owner in the branch body -- the load is
#:     not the `with`'s context expression, and it is not a bare-name
#:     assignment statement either;
#:   * tuple binding `d, meta = np.load(...), None` -- the acquisition target
#:     is not a single bare name, so form B cannot key on it;
#:   * an alias that survives a later rebind -- statements intervene between
#:     the acquisition and the `with`, and form B admits none.
_PLANTED_NARROWED_OUT = (
    _PLANTED_WALRUS, _PLANTED_TUPLE_ASSIGN, _PLANTED_ALIAS_SURVIVES_REBIND,
)


@pytest.mark.parametrize(
    "source", list(_PLANTED_NARROWED_OUT),
    ids=["walrus-in-an-if-test", "tuple-binding", "alias-across-a-rebind"],
)
def test_correct_but_unmodelled_shapes_are_reported_unowned(source):
    """Named as the trade they are, not hidden."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize("source", list(_PLANTED_CONSERVATIVELY_REJECTED.values()),
                         ids=list(_PLANTED_CONSERVATIVELY_REJECTED))
def test_unmodelled_but_correct_delegation_is_reported_unowned(source):
    """Documents the trade rather than hiding it."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize("source", list(_PLANTED_ADAPTER_CORRECT.values()),
                         ids=list(_PLANTED_ADAPTER_CORRECT))
def test_adapter_and_stack_correct_shapes_are_accepted(source):
    """The guarded production shape must survive the tightening.

    `nullcontext` is sound in exactly one place: as one arm of a conditional
    whose other arm hands the raw archive to the `with`. That is what
    `scripts/lucid_server.py`, `scripts/portable_genome.py` and the loader this
    package corrects all do, and rejecting it would demand edits outside this
    boundary.
    """
    tree, call = _single_load(source)
    assert _is_owned(tree, call)


def test_discovery_finds_return_style_predicate_helpers():
    """`def is_closed(h): return getattr(h, "closed", True)` is the commoner
    pytest idiom, and an assert-only rule never scanned such a file at all."""
    predicate = (
        'def is_closed(h):\n'
        '    return getattr(h, "closed", True)\n'
        'def test_x(handle):\n'
        '    assert is_closed(handle)\n'
    )
    assert _asserts_closure(ast.parse(predicate))
    assert len(_permissive_closure_defaults(ast.parse(predicate))) == 1
    assert _asserts_closure(ast.parse('def t(h):\n    assert h.closed\n'))

# --- control-flow admission controls ----------------------------------------
#
# Every shape in the first set was CERTIFIED by a matcher that searched
# flattened source order for any later owner. Source order is not
# reachability: an owner in a sibling branch, inside a possibly-empty loop,
# under an unguarded `if`, or after an early exit is not reached on the path
# the acquisition takes.
#
# The exception-edge cases matter for the same reason. Ownership begins at a
# successful `__enter__`, not at the `with` statement, so anything that can
# raise in between leaves an unmanaged window.

_PLANTED_CONTROL_FLOW_LEAKS = {
    "acquire-in-if-own-in-mutually-exclusive-else":
        "import numpy as np\ndef f(p, cond):\n"
        "    if cond:\n        d = np.load(str(p), allow_pickle=False)\n"
        "    else:\n        with d as x:\n            pass\n",
    "acquire-in-try-own-in-except":
        "import numpy as np\ndef f(p):\n"
        "    try:\n        d = np.load(str(p), allow_pickle=False)\n"
        "    except OSError:\n        with d as x:\n            pass\n"
        "    return d['lattice']\n",
    "acquire-and-own-in-different-if-arms":
        "import numpy as np\ndef f(p, a, b):\n"
        "    if a:\n        d = np.load(str(p), allow_pickle=False)\n"
        "    elif b:\n        with d as x:\n            pass\n"
        "    return d['lattice']\n",
    "owner-inside-a-possibly-empty-for":
        "import numpy as np\ndef f(p, items):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    for i in items:\n        with d as x:\n            pass\n"
        "    return d['lattice']\n",
    "owner-inside-a-possibly-zero-iteration-while":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    while cond:\n        with d as x:\n            pass\n"
        "    return d['lattice']\n",
    "owner-under-an-if-with-no-else":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    if cond:\n        with d as x:\n            pass\n"
        "    return d['lattice']\n",
    "owner-under-an-if-whose-else-does-not-own":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    if cond:\n        with d as x:\n            pass\n"
        "    else:\n        pass\n"
        "    return d['lattice']\n",
    "early-return-bypasses-the-owner":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    if cond:\n        return d['lattice']\n"
        "    with d as x:\n        pass\n",
    "early-raise-bypasses-the-owner":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    if cond:\n        raise ValueError('x')\n"
        "    with d as x:\n        pass\n",
    "intervening-statement-can-raise":
        "import numpy as np\ndef f(p, parse):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    meta = parse(d)\n"
        "    with d as x:\n        pass\n",
    "handler-returns-before-the-owner":
        "import numpy as np\ndef f(p, validate):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        validate(d)\n"
        "    except ValueError:\n        return None\n"
        "    with d as x:\n        pass\n",
    "earlier-with-item-may-prevent-our-enter":
        "import numpy as np\ndef f(p, acquire_lock):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with acquire_lock() as l, d as x:\n        pass\n",
}

#: Reproduced as red-team counterexamples but ALREADY rejected by the existing
#: rebinding and adapter-provenance machinery. Regression locks, NOT
#: failing-first evidence -- said plainly so the record is not overstated.
_PLANTED_ALREADY_REJECTED = {
    "rebound-before-ownership":
        "import numpy as np\ndef f(p, normalise):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    d = normalise(d)\n"
        "    with d as x:\n        pass\n",
    "adapter-construction-can-fail-before-ownership":
        "import contextlib\nimport numpy as np\ndef f(p, wrap):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with contextlib.closing(wrap(d)) as x:\n        pass\n",
}

#: Forms A, B and C reached from various control-flow positions. Without these
#: a narrowing could pass by rejecting everything.
_PLANTED_STRUCTURAL_OWNERSHIP = {
    "fused-direct-with-np-load":
        "import numpy as np\ndef f(p):\n"
        "    with np.load(str(p), allow_pickle=False) as d:\n"
        "        return d['lattice']\n",
    "fused-inside-an-if":
        "import numpy as np\ndef f(p, cond):\n"
        "    if cond:\n"
        "        with np.load(str(p), allow_pickle=False) as d:\n"
        "            return d['lattice']\n",
    "fused-inside-a-for-body":
        "import numpy as np\ndef f(paths):\n"
        "    for p in paths:\n"
        "        with np.load(str(p), allow_pickle=False) as d:\n"
        "            pass\n",
    "fused-inside-try":
        "import numpy as np\ndef f(p):\n"
        "    try:\n"
        "        with np.load(str(p), allow_pickle=False) as d:\n"
        "            return d['lattice']\n"
        "    except OSError:\n        return None\n",
    "adjacent-owner-immediately-after-acquisition":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with d as x:\n        return x['lattice']\n",
    "production-guarded-conditional-owner":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_CONTROL_FLOW_LEAKS.values()),
                         ids=list(_PLANTED_CONTROL_FLOW_LEAKS))
def test_control_flow_leaks_are_not_certified(source):
    """Source order is not reachability, and a `with` statement is not yet
    ownership -- ownership begins at a successful ``__enter__``."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize("source", list(_PLANTED_ALREADY_REJECTED.values()),
                         ids=list(_PLANTED_ALREADY_REJECTED))
def test_already_rejected_shapes_stay_rejected(source):
    """Not failing-first: the unchanged matcher already refuses these."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize("source", list(_PLANTED_STRUCTURAL_OWNERSHIP.values()),
                         ids=list(_PLANTED_STRUCTURAL_OWNERSHIP))
def test_structurally_guaranteed_ownership_is_accepted(source):
    """The repair must not pass by rejecting everything."""
    tree, call = _single_load(source)
    assert _is_owned(tree, call)

# --- structural-admission boundary controls ---------------------------------
#
# Six routes by which an earlier revision certified a LEAKING archive as owned.
# What makes them worth planting is that none of them looks wrong: each borrows
# the vocabulary of an admission that existed then -- `nullcontext` with a
# guard, a live `ExitStack`, `closing`, a `finally` that closes -- and spends it
# on something that does not release the archive. A matcher that keys on the
# vocabulary rather than the semantics passes all six.
#
# Four of the six families below target admissions that no longer exist. Only
# the guard and provenance families still exercise live rules; the rest are
# preserved as the cost record of admissions this gate used to carry.

#: (1) The guard, not `nullcontext`, is what makes the conditional owner sound.
#: Without validating it, every one of these reads as the production shape.
_PLANTED_GUARD_LEAKS = {
    "arbitrary-condition-instead-of-a-guard":
        "import contextlib\nimport numpy as np\ndef f(p, condition):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if condition else loaded\n"
        "    with owner as data:\n        pass\n",
    "reversed-arms-put-the-archive-in-the-no-op":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = loaded if isinstance(loaded, np.ndarray) else contextlib.nullcontext(loaded)\n"
        "    with owner as data:\n        pass\n",
    "guard-tests-an-unrelated-object":
        "import contextlib\nimport numpy as np\ndef f(p, other):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(other, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "guard-tests-the-wrong-type":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.memmap) else loaded\n"
        "    with owner as data:\n        pass\n",
    "isinstance-shadowed":
        "import contextlib\nimport numpy as np\nisinstance = lambda a, b: True\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "guard-is-an-arbitrary-method-named-isinstance":
        "import contextlib\nimport numpy as np\ndef f(p, helper):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if helper.isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "ndarray-read-off-something-that-is-not-numpy":
        "import contextlib\nimport numpy as np\ndef f(p, shim):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, shim.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "numpy-alias-rebound-so-ndarray-is-not-numpys":
        "import contextlib\nimport numpy as np\nnp = None\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
}

#: (2) Inside the span is not the same as still being the stack. The entered
#: stack unwinds perfectly; it was simply never told about the archive.
_PLANTED_STACK_LIVENESS_LEAKS = {
    "stack-rebound-inside-its-own-span":
        "import contextlib\nimport numpy as np\ndef f(p, fake):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        stack = fake\n"
        "        data = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return data['lattice']\n",
    "stack-rebound-by-a-for-target-in-the-span":
        "import contextlib\nimport numpy as np\ndef f(p, items):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        for stack in items:\n            pass\n"
        "        data = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return data['lattice']\n",
    "stack-rebound-by-an-inner-with-as":
        "import contextlib\nimport numpy as np\ndef f(p, other):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        with other as stack:\n            pass\n"
        "        data = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return data['lattice']\n",
    "async-stack-rebound-inside-its-own-span":
        "import contextlib\nimport numpy as np\nasync def f(p, fake):\n"
        "    async with contextlib.AsyncExitStack() as stack:\n"
        "        stack = fake\n"
        "        data = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return data['lattice']\n",
}

#: (3) `callback` registers a CALLABLE to run on unwind. Handed the archive
#: itself it does not close it -- unwinding calls `NpzFile(...)` and raises --
#: and `push` wants an exit callback, not a resource.
_PLANTED_STACK_TRANSFER_LEAKS = {
    "callback-registers-the-archive-as-a-callable":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        stack.callback(np.load(str(p), allow_pickle=False))\n",
    "push-registers-the-archive-as-an-exit-callback":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        stack.push(np.load(str(p), allow_pickle=False))\n",
    "archive-is-merely-one-argument-among-several":
        "import contextlib\nimport numpy as np\ndef f(p, fn):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        stack.callback(fn, np.load(str(p), allow_pickle=False))\n",
}

#: (4) A `finally` protects the paths that REACH it. Reached conditionally, it
#: leaves the others exactly as unprotected as no `try` at all.
_PLANTED_FINALLY_REACHABILITY_LEAKS = {
    "protecting-try-nested-in-an-if":
        "import numpy as np\ndef f(p, condition):\n"
        "    data = np.load(str(p), allow_pickle=False)\n"
        "    if condition:\n"
        "        try:\n            pass\n"
        "        finally:\n            data.close()\n"
        "    return None\n",
    "protecting-try-in-a-possibly-empty-for":
        "import numpy as np\ndef f(p, items):\n"
        "    data = np.load(str(p), allow_pickle=False)\n"
        "    for i in items:\n"
        "        try:\n            pass\n"
        "        finally:\n            data.close()\n"
        "    return None\n",
    "protecting-try-after-a-statement-that-can-raise":
        "import numpy as np\ndef f(p, parse):\n"
        "    data = np.load(str(p), allow_pickle=False)\n"
        "    meta = parse(p)\n"
        "    try:\n        pass\n"
        "    finally:\n        data.close()\n",
    "protecting-try-in-a-sibling-else-arm":
        "import numpy as np\ndef f(p, condition):\n"
        "    if condition:\n"
        "        data = np.load(str(p), allow_pickle=False)\n"
        "    else:\n"
        "        try:\n            pass\n"
        "        finally:\n            data.close()\n",
}

#: (5) The adapter raises AFTER the load has opened the archive, out of a
#: statement that never entered a `with`. The archive is live and unmanaged.
_PLANTED_ADAPTER_ARITY_LEAKS = {
    "closing-with-a-second-positional":
        "import contextlib\nimport numpy as np\ndef f(p, other):\n"
        "    with contextlib.closing(\n"
        "        np.load(str(p), allow_pickle=False),\n"
        "        other,\n"
        "    ) as data:\n        pass\n",
    "closing-with-a-keyword":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.closing(np.load(str(p), allow_pickle=False), extra=1) as data:\n"
        "        pass\n",
    "closing-with-an-unpacked-tail":
        "import contextlib\nimport numpy as np\ndef f(p, rest):\n"
        "    with contextlib.closing(np.load(str(p), allow_pickle=False), *rest) as data:\n"
        "        pass\n",
    "nullcontext-arm-with-a-second-positional":
        "import contextlib\nimport numpy as np\ndef f(p, other):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded, other)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "nullcontext-arm-with-a-keyword":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded, extra=1)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
}

#: (6) The import is not the use site. Between them the name can be made to
#: mean anything, while the call still reads as the standard-library adapter.
_PLANTED_ADAPTER_PROVENANCE_LEAKS = {
    "contextlib-module-alias-rebound-in-the-function":
        "import contextlib\nimport numpy as np\ndef f(p, fake):\n"
        "    contextlib = fake\n"
        "    with contextlib.closing(np.load(str(p), allow_pickle=False)) as data:\n"
        "        pass\n",
    "contextlib-module-alias-rebound-at-module-level":
        "import contextlib\nimport numpy as np\ncontextlib = None\ndef f(p):\n"
        "    with contextlib.closing(np.load(str(p), allow_pickle=False)) as data:\n"
        "        pass\n",
    "directly-imported-closing-rebound":
        "from contextlib import closing\nimport numpy as np\ndef f(p, fake):\n"
        "    closing = fake\n"
        "    with closing(np.load(str(p), allow_pickle=False)) as data:\n"
        "        pass\n",
    "directly-imported-nullcontext-rebound":
        "from contextlib import nullcontext\nimport numpy as np\ndef f(p, fake):\n"
        "    nullcontext = fake\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "exitstack-factory-name-rebound":
        "from contextlib import ExitStack\nimport numpy as np\ndef f(p, fake):\n"
        "    ExitStack = fake\n"
        "    with ExitStack() as stack:\n"
        "        data = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return data['lattice']\n",
}

_PLANTED_ADMISSION_LEAKS = {
    f"{family}::{case}": source
    for family, cases in (
        ("guard", _PLANTED_GUARD_LEAKS),
        ("stack-liveness", _PLANTED_STACK_LIVENESS_LEAKS),
        ("stack-transfer", _PLANTED_STACK_TRANSFER_LEAKS),
        ("finally-reachability", _PLANTED_FINALLY_REACHABILITY_LEAKS),
        ("adapter-arity", _PLANTED_ADAPTER_ARITY_LEAKS),
        ("adapter-provenance", _PLANTED_ADAPTER_PROVENANCE_LEAKS),
    )
    for case, source in cases.items()
}

#: Reproduced while attacking the same boundaries, but the UNCHANGED matcher
#: already refused them -- the adjacent-unit rule rejects any intervening
#: statement, whatever it rebinds. Regression locks, NOT failing-first
#: evidence, and labelled so rather than counted as repairs.
_PLANTED_BOUNDARY_ALREADY_REJECTED = {
    "numpy-alias-rebound-between-acquisition-and-guard":
        "import contextlib\nimport numpy as np\ndef f(p, fake):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    np = fake\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        pass\n",
    "guarded-conditional-written-inline-in-the-with":
        "import contextlib\nimport numpy as np\ndef f(p, cond):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    with (contextlib.nullcontext(loaded) if cond else loaded) as data:\n"
        "        pass\n",
}

#: The recognised language, one load-bearing control per form. Without these
#: the narrowing could pass by refusing everything -- and a gate that reports
#: production as a leak gets switched off within the week.
_PLANTED_FORM_A = {
    "A-fused-with-np-load":
        "import numpy as np\ndef f(p):\n"
        "    with np.load(str(p), allow_pickle=False) as d:\n"
        "        return d['lattice']\n",
    "A-fused-inside-an-if":
        "import numpy as np\ndef f(p, cond):\n"
        "    if cond:\n"
        "        with np.load(str(p), allow_pickle=False) as d:\n"
        "            return d['lattice']\n",
    "A-fused-inside-a-loop-body":
        "import numpy as np\ndef f(paths):\n"
        "    for p in paths:\n"
        "        with np.load(str(p), allow_pickle=False) as d:\n"
        "            pass\n",
    "A-fused-inside-a-try":
        "import numpy as np\ndef f(p):\n"
        "    try:\n"
        "        with np.load(str(p), allow_pickle=False) as d:\n"
        "            return d['lattice']\n"
        "    except OSError:\n        return None\n",
    "A-fused-through-the-numpy-load-spelling":
        "import numpy\ndef f(p):\n"
        "    with numpy.load(str(p), allow_pickle=False) as d:\n"
        "        return d['lattice']\n",
    "A-fused-with-a-later-second-with-item":
        "import numpy as np\ndef f(p, lock):\n"
        "    with np.load(str(p), allow_pickle=False) as d, lock:\n"
        "        return d['lattice']\n",
}

_PLANTED_FORM_B = {
    "B-adjacent-owner-immediately-after-acquisition":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with d as x:\n        return x['lattice']\n",
    "B-adjacent-owner-rebinding-the-same-name":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with d as d:\n        return d['lattice']\n",
    "B-adjacent-inside-a-loop-body":
        "import numpy as np\ndef f(paths):\n"
        "    for p in paths:\n"
        "        d = np.load(str(p), allow_pickle=False)\n"
        "        with d as x:\n            pass\n",
}

_PLANTED_FORM_C = {
    "C-exact-production-unit":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "C-with-numpy-imported-unaliased":
        "import contextlib\nimport numpy\ndef f(p):\n"
        "    loaded = numpy.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, numpy.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "C-through-an-aliased-contextlib-import":
        "import contextlib as ctx\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = ctx.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "C-written-over-several-physical-lines":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = (\n"
        "        contextlib.nullcontext(loaded)\n"
        "        if isinstance(loaded, np.ndarray)\n"
        "        else loaded\n"
        "    )\n"
        "    with owner as data:\n        return data['lattice']\n",
    # The trust rule must not cost ORDINARY use of the protected modules.
    # Production reads dozens of `np.<something>` attributes and calls
    # `isinstance` freely; only writing through them, or handing them away,
    # is refused.
    "C-alongside-heavy-ordinary-numpy-attribute-use":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n"
        "        grid = np.asarray(data['lattice'], dtype=np.float32)\n"
        "        return np.mean(grid), np.zeros(3, dtype=np.uint8)\n",
    "C-alongside-isinstance-used-elsewhere":
        "import contextlib\nimport numpy as np\ndef g(x):\n"
        "    return isinstance(x, dict) or isinstance(x, list)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "C-alongside-an-unrelated-setattr":
        "import contextlib\nimport numpy as np\ndef f(p, holder):\n"
        "    setattr(holder, 'seen', True)\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
}

_PLANTED_RECOGNISED = {**_PLANTED_FORM_A, **_PLANTED_FORM_B, **_PLANTED_FORM_C}

#: CORRECT Python that the recognised language does not cover. Every one of
#: these releases its archive; none is written in form A, B or C, so all are
#: reported UNOWNED. They are kept -- not deleted -- because they are the
#: PRICE of the narrowing, and a price that is not written down gets forgotten
#: and then re-litigated. Four of them were accepted admissions before this
#: pass; each admission cost more false certifications than it bought sites,
#: and the production census found no site using any of them.
_PLANTED_NARROWED_BY_THE_SMALL_LANGUAGE = {
    "closing-adapter-around-the-load":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.closing(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "closing-through-an-aliased-contextlib":
        "import contextlib as ctx\nimport numpy as np\ndef f(p):\n"
        "    with ctx.closing(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "closing-through-a-direct-import":
        "from contextlib import closing\nimport numpy as np\ndef f(p):\n"
        "    with closing(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "live-exitstack-enter-context":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return d['lattice']\n",
    "live-exitstack-bound-to-an-attribute-target":
        "import contextlib\nimport numpy as np\nclass C:\n    def f(self, p):\n"
        "        with contextlib.ExitStack() as self.stack:\n"
        "            d = self.stack.enter_context("
        "np.load(str(p), allow_pickle=False))\n"
        "            return d['lattice']\n",
    "protecting-try-finally-close":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        d.close()\n",
    "protecting-try-finally-on-an-attribute-target":
        "import numpy as np\nclass C:\n    def f(self, p):\n"
        "        self.data = np.load(str(p), allow_pickle=False)\n"
        "        try:\n            return self.data['lattice']\n"
        "        finally:\n            self.data.close()\n",
    "protecting-try-finally-with-a-non-subscript-use-inside":
        "import numpy as np\ndef f(p, consume):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return consume(d)\n"
        "    finally:\n        d.close()\n",
    "guarded-nullcontext-through-a-direct-import":
        "from contextlib import nullcontext\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "walrus-acquisition-in-the-context-expression":
        "import numpy as np\ndef f(p):\n"
        "    with (d := np.load(str(p), allow_pickle=False)) as data:\n"
        "        return data['lattice']\n",
    "tuple-acquisition-then-an-adjacent-owner":
        "import numpy as np\ndef f(p):\n"
        "    d, meta = np.load(str(p), allow_pickle=False), None\n"
        "    with d as x:\n        return x['lattice']\n",
    "attribute-target-acquisition-then-an-adjacent-owner":
        "import numpy as np\nclass C:\n    def f(self, p):\n"
        "        self.data = np.load(str(p), allow_pickle=False)\n"
        "        with self.data as x:\n            return x['lattice']\n",
    "stack-callback-close-on-a-live-stack":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = np.load(str(p), allow_pickle=False)\n"
        "        stack.callback(d.close)\n"
        "        return d['lattice']\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_ADMISSION_LEAKS.values()),
                         ids=list(_PLANTED_ADMISSION_LEAKS))
def test_admission_boundary_leaks_are_not_certified(source):
    """Certified OWNED two revisions ago; refused by the guard, liveness,
    arity, provenance and reachability checks added in the revision after.

    Only two of those five checks still exist -- the form-C guard and import
    provenance. The other three governed admissions that have since been
    removed outright, which is why this set now costs nothing to keep and would
    cost a great deal to have deleted: it is the record of what an admission
    charged in exchange for the sites it covered.
    """
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize("source", list(_PLANTED_BOUNDARY_ALREADY_REJECTED.values()),
                         ids=list(_PLANTED_BOUNDARY_ALREADY_REJECTED))
def test_boundary_shapes_already_rejected_stay_rejected(source):
    """Not failing-first: the unrepaired matcher refused these too."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize("source", list(_PLANTED_RECOGNISED.values()),
                         ids=list(_PLANTED_RECOGNISED))
def test_the_recognised_forms_are_accepted(source):
    """Forms A, B and C, which between them cover all 15 production sites.

    The narrowing has one obvious failure mode -- refusing everything -- and
    these are what makes that fail loudly. Form B has no production user today;
    it is recognised because it is the minimal safe shape a maintainer reaches
    for when the load will not fit on the `with` line, and refusing it would
    push people toward `try/finally`, which this gate no longer reads.
    """
    tree, call = _single_load(source)
    assert _is_owned(tree, call)


@pytest.mark.parametrize(
    "source", list(_PLANTED_NARROWED_BY_THE_SMALL_LANGUAGE.values()),
    ids=list(_PLANTED_NARROWED_BY_THE_SMALL_LANGUAGE))
def test_correct_code_outside_the_recognised_language_is_reported_unowned(source):
    """The price of the narrowing, written down instead of discovered later.

    Every one of these RELEASES its archive. They are reported UNOWNED anyway,
    because recognising them means carrying rules about adapters, stacks,
    aliases and `finally` reachability -- and those rules, not the shapes, are
    what kept certifying real leaks. A maintainer who hits one of these is told
    to write form A, B or C, which is a small edit; the alternative is a gate
    that guesses.
    """
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


# --- the audited false-certification matrix ---------------------------------
#
# Every shape below was reported OWNED by the matcher this pass replaces, and
# every one of them LEAKS. They are grouped by the admission that certified
# them, and all four of those admissions are now gone -- which is the point.
# Patching these individually was tried; the shapes kept arriving because the
# admissions, not the shapes, were the defect.
#
# They are kept as controls precisely BECAUSE the admissions are gone: nothing
# stops a future maintainer re-adding `try/finally` or `ExitStack` support on a
# reasonable-looking day, and these are what will fail when they do.

#: The archive NAME is rebound inside the very `try` whose `finally` closes it,
#: so the close runs on something else -- silently, with no exception.
_PLANTED_TRY_REBINDING_LEAKS = {
    "try-rebind-by-assignment":
        "import numpy as np\ndef f(p, other):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        d = other\n        return d['lattice']\n"
        "    finally:\n        d.close()\n",
    "try-rebind-to-a-member-of-itself":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        d = d['lattice']\n        return d\n"
        "    finally:\n        d.close()\n",
    "try-rebind-by-a-loop-target":
        "import numpy as np\ndef f(p, items):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        for d in items:\n            pass\n"
        "    finally:\n        d.close()\n",
    "try-rebind-by-with-as":
        "import numpy as np\ndef f(p, other):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        with other as d:\n            pass\n"
        "    finally:\n        d.close()\n",
    "try-rebind-by-deletion":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        del d\n"
        "    finally:\n        d.close()\n",
    "try-rebind-by-a-pattern-capture":
        "import numpy as np\ndef f(p, mm):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        match mm:\n            case [d]:\n                pass\n"
        "    finally:\n        d.close()\n",
}

#: The `finally` runs, and still never performs a valid close.
_PLANTED_FINALLY_LEAKS = {
    "raising-statement-before-the-close":
        "import numpy as np\ndef f(p, cleanup):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        cleanup()\n        d.close()\n",
    "early-return-in-finalbody-before-the-close":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        if cond:\n            return None\n"
        "        d.close()\n",
    "close-supplied-invalid-arguments":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        d.close(True)\n",
}

#: Registered on a stack that does not unwind it -- the stack is real, entered
#: and correct; it simply no longer holds the archive when it exits.
_PLANTED_EXITSTACK_LEAKS = {
    "pop-all-after-registration":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        keep = stack.pop_all()\n"
        "        return d['lattice'], keep\n",
    "generatorexp-defers-past-the-stack-lifetime":
        "import contextlib\nimport numpy as np\ndef f(paths):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        return (stack.enter_context("
        "np.load(str(p), allow_pickle=False)) for p in paths)\n",
    "nested-function-replaces-the-stack":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        spare = contextlib.ExitStack()\n"
        "        def swap():\n            nonlocal stack\n            stack = spare\n"
        "        swap()\n"
        "        d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return d['lattice']\n",
    "enter-context-in-an-earlier-with-item":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    stack = contextlib.ExitStack()\n"
        "    with contextlib.nullcontext("
        "stack.enter_context(np.load(str(p), allow_pickle=False))) as z, \\\n"
        "         contextlib.ExitStack() as stack:\n"
        "        return z['lattice']\n",
}

#: `NpzFile` is synchronous and has no `aclose`. Each of these opens the
#: archive and THEN fails on the protocol, which is a leak, not a type error.
_PLANTED_PROTOCOL_LEAKS = {
    "aclosing-applied-to-an-npzfile":
        "import contextlib\nimport numpy as np\nasync def f(p):\n"
        "    async with contextlib.aclosing("
        "np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "sync-aclosing-applied-to-an-npzfile":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.aclosing(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "asyncwith-around-a-synchronous-archive":
        "import numpy as np\nasync def f(p):\n"
        "    async with np.load(str(p), allow_pickle=False) as d:\n"
        "        return d['lattice']\n",
    "asyncwith-around-an-adjacent-archive":
        "import numpy as np\nasync def f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    async with d as x:\n        return x['lattice']\n",
}

#: The import exists somewhere in the file, but does not certainly hold where
#: the guard reads it -- so the guard raises after the archive is open.
_PLANTED_PROVENANCE_LEAKS = {
    "numpy-alias-imported-only-under-type-checking":
        "import contextlib\nimport numpy\nfrom typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n    import numpy as np\ndef f(p):\n"
        "    loaded = numpy.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "numpy-alias-imported-under-a-plain-conditional":
        "import contextlib\nimport numpy\nFLAG = True\nif FLAG:\n"
        "    import numpy as np\ndef f(p):\n"
        "    loaded = numpy.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "numpy-alias-imported-in-another-function":
        "import contextlib\nimport numpy\ndef helper():\n    import numpy as np\n"
        "    return np\ndef f(p):\n"
        "    loaded = numpy.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "numpy-alias-imported-only-inside-the-using-function":
        "import contextlib\nimport numpy\ndef f(p):\n    import numpy as np\n"
        "    loaded = numpy.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "contextlib-imported-under-a-plain-conditional":
        "import numpy as np\nFLAG = True\nif FLAG:\n    import contextlib\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "contextlib-imported-only-inside-the-using-function":
        "import numpy as np\ndef f(p):\n    import contextlib\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "match-mapping-rest-rebinds-the-numpy-alias":
        "import contextlib\nimport numpy as np\ndef f(p, mm):\n"
        "    match mm:\n        case {**np}:\n            pass\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "adapter-attribute-monkeypatched-on-the-module":
        "import contextlib\nimport numpy as np\ndef f(p, fake):\n"
        "    contextlib.nullcontext = fake\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
}

#: Form C's guard is only as good as the OBJECTS it names. Replace
#: `np.ndarray` with `object` and the guard is true for an `NpzFile`, which
#: then goes into the arm that closes nothing -- while the three lines still
#: read character-for-character like the production loader. Checking that the
#: names are not reassigned missed every spelling below, because none of them
#: writes a protected name: they write THROUGH it, or hand it away.
_PLANTED_FORM_C_TRUST_LEAKS = {
    "setattr-replaces-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "setattr(np, 'ndarray', object)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "delattr-removes-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "delattr(np, 'ndarray')\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "vars-dict-replaces-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "vars(np)['ndarray'] = object\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "alias-then-attribute-store-replaces-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "numpy_alias = np\nnumpy_alias.ndarray = object\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "alias-then-setattr-replaces-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "numpy_alias = np\nsetattr(numpy_alias, 'ndarray', object)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "setattr-replaces-the-adapter":
        "import contextlib\nimport numpy as np\n"
        "setattr(contextlib, 'nullcontext', lambda x: x)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "alias-then-attribute-store-replaces-the-adapter":
        "import contextlib\nimport numpy as np\n"
        "cl = contextlib\ncl.nullcontext = lambda x: x\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "builtins-attribute-store-replaces-the-predicate":
        "import builtins\nimport contextlib\nimport numpy as np\n"
        "builtins.isinstance = lambda a, b: True\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "builtins-setattr-replaces-the-predicate":
        "import builtins\nimport contextlib\nimport numpy as np\n"
        "setattr(builtins, 'isinstance', lambda a, b: True)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "numpy-module-handed-to-a-mutator":
        "import contextlib\nimport numpy as np\n"
        "def patch(module):\n    module.ndarray = object\n"
        "patch(np)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "contextlib-module-handed-to-a-mutator":
        "import contextlib\nimport numpy as np\n"
        "def patch(module):\n    module.nullcontext = lambda x: x\n"
        "patch(contextlib)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "predicate-handed-away-for-later-substitution":
        "import contextlib\nimport numpy as np\n"
        "def keep(fn):\n    return fn\n"
        "shim = keep(isinstance)\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
}

_PLANTED_AUDITED_LEAKS = {
    f"{family}::{case}": source
    for family, cases in (
        ("try-rebinding", _PLANTED_TRY_REBINDING_LEAKS),
        ("finally", _PLANTED_FINALLY_LEAKS),
        ("exitstack", _PLANTED_EXITSTACK_LEAKS),
        ("protocol", _PLANTED_PROTOCOL_LEAKS),
        ("provenance", _PLANTED_PROVENANCE_LEAKS),
        ("form-c-trust", _PLANTED_FORM_C_TRUST_LEAKS),
    )
    for case, source in cases.items()
}

#: Reproduced while attacking the same boundaries, but the matcher being
#: replaced ALREADY refused these. Regression locks, NOT failing-first
#: evidence, and separated so the record is not overstated.
_PLANTED_AUDITED_ALREADY_REJECTED = {
    "early-control-transfer-before-the-protecting-try":
        "import numpy as np\ndef f(p, cond):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    if cond:\n        return None\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        d.close()\n",
    "numpy-alias-conditionally-imported-with-a-fallback-rebind":
        "import contextlib\nimport numpy\ntry:\n    import numpy as np\n"
        "except ImportError:\n    np = None\ndef f(p):\n"
        "    loaded = numpy.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "contextlib-conditionally-imported-with-a-fallback-rebind":
        "import numpy as np\ntry:\n    import contextlib\nexcept ImportError:\n"
        "    contextlib = None\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    # The two guard-type substitutions that DO write a protected name, and so
    # were already caught by the rebinding check. Kept beside the ten spellings
    # that were not, because the pair is the whole lesson: the difference
    # between them is only where the assignment target happens to sit.
    "direct-attribute-store-replaces-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "np.ndarray = object\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "dunder-dict-subscript-replaces-the-guard-type":
        "import contextlib\nimport numpy as np\n"
        "np.__dict__['ndarray'] = object\n"
        "def f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded)"
        " if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_AUDITED_LEAKS.values()),
                         ids=list(_PLANTED_AUDITED_LEAKS))
def test_the_audited_false_certifications_are_refused(source):
    """The findings that ended the general-analyser approach.

    Each was reported OWNED by a matcher that had already been tightened twice
    against this same class of defect. That is the evidence: the shapes were not
    running out. What ends them is not knowing more shapes but recognising
    fewer -- the first five families are not form A, B or C and never will be.

    The `form-c-trust` family is the exception worth reading carefully. Those
    twelve ARE form C, character for character, and they leak anyway, because
    form C is the one recognised form whose safety depends on what other
    objects mean. Narrowing the LANGUAGE could not close them; only requiring
    that the module leave those objects alone could.
    """
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


@pytest.mark.parametrize(
    "source", list(_PLANTED_AUDITED_ALREADY_REJECTED.values()),
    ids=list(_PLANTED_AUDITED_ALREADY_REJECTED))
def test_audited_shapes_already_refused_stay_refused(source):
    """Not failing-first: the previous matcher refused these too."""
    tree, call = _single_load(source)
    assert not _is_owned(tree, call)


def test_the_guarded_production_loaders_are_still_owned():
    """The guard check is the tightening with real reach into production.

    Three shipped loaders depend on the conditional-`nullcontext` admission, and
    validating its guard is exactly the change that could withdraw it from them.
    Anchored per file so it cannot pass by finding no loads.
    """
    guarded = (WORKSTREAM_B, "scripts/lucid_server.py", "scripts/portable_genome.py")
    for name in guarded:
        path = _REPO_ROOT / name
        assert path.is_file(), f"{name} is missing -- the guarded loader moved"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = _np_load_calls(tree, _numpy_load_names(tree))
        assert calls, f"{name} has no NumPy load -- the anchor went stale"
        owned = _owned_load_calls(tree)
        unowned = [call.lineno for call in calls if id(call) not in owned]
        assert not unowned, (
            f"{name}: guarded production load reported unowned at line(s) {unowned}"
        )


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
    """Does this module actually ASSERT something about an archive's closure?

    An earlier revision returned true for any `.zip`/`.fid` attribute access
    anywhere in the file, so a bare read -- ``observed = handle.zip`` -- counted
    as a closure proof. The handle state must now be reached from a tested
    expression: the test of an ``assert``, or the value of a ``return``.

    Both forms are needed. An assert-only rule covered assert-style helpers but
    silently skipped the commoner pytest idiom, a ``return``-style predicate
    (``def is_closed(h): return getattr(h, "closed", True)``) -- such a file was
    never scanned for permissive defaults at all.

    RECOGNISED SHAPES, stated so the gate is not mistaken for more: an
    attribute named ``zip``, ``fid`` or ``closed``, and ``getattr(x, "closed",
    ...)``. A proof expressed some other way -- ``unittest``'s
    ``assertIsNone``, a handle state read through a computed attribute name --
    is not seen, and its file is simply not scanned.

    A substring test for "closed" preceded that and was worse: it matched
    `fail_closed`, `disclosed` and `unclosed_array`, pulling in ~30 files that
    assert nothing. That made the non-vacuity floor below meaningless -- it
    would have passed with every genuine closure proof in the repository
    deleted, which is precisely what it exists to catch.
    """
    for node in ast.walk(tree):
        # An `assert`, or the returned expression of a predicate helper --
        # `def is_closed(h): return getattr(h, "closed", True)` is the more
        # common pytest idiom, and an assert-only rule missed it entirely, so
        # such a file was never scanned for permissive defaults.
        if isinstance(node, ast.Assert):
            tested = node.test
        elif isinstance(node, ast.Return) and node.value is not None:
            tested = node.value
        else:
            continue
        for inner in ast.walk(tested):
            if isinstance(inner, ast.Attribute) and inner.attr in {"zip", "fid", "closed"}:
                return True
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
                    and inner.func.id == "getattr" and len(inner.args) >= 2
                    and isinstance(inner.args[1], ast.Constant)
                    and inner.args[1].value == "closed"):
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


#: A bare handle read with NO assertion. An earlier revision counted this as a
#: closure proof, because it looked only for a `.zip`/`.fid` attribute access
#: anywhere in the file.
_PLANTED_NON_ASSERT_READ = (
    "def test_noise(handle):\n"
    "    observed = handle.zip\n"
)

#: A genuine strict proof, which discovery must find.
_PLANTED_ASSERTED_CLOSURE = (
    "def test_real(handle):\n"
    "    assert handle.zip is None and (handle.fid is None or handle.fid.closed)\n"
)

def test_the_permissive_default_matcher_detects_a_planted_bad_example():
    """The exact shape this gate exists to keep out."""
    assert len(_permissive_closure_defaults(ast.parse(_PLANTED_PERMISSIVE))) == 1


def test_the_permissive_default_matcher_accepts_a_strict_control():
    """A genuine proof must not be flagged, or the gate would be unusable."""
    assert _permissive_closure_defaults(ast.parse(_PLANTED_STRICT)) == []


def test_discovery_requires_a_real_assertion(tmp_path):
    """A handle READ is not a closure proof.

    `_asserts_closure` previously returned true for any `.zip`/`.fid` access
    anywhere in a file, so a module that merely looked at a handle counted
    towards the non-vacuity floor. Both controls are planted: the bare read
    must be rejected, the strict assertion accepted.
    """
    assert not _asserts_closure(ast.parse(_PLANTED_NON_ASSERT_READ))
    assert _asserts_closure(ast.parse(_PLANTED_ASSERTED_CLOSURE))

    planted = tmp_path / TEST_DIR
    planted.mkdir()
    (planted / "test_noise.py").write_text(_PLANTED_NON_ASSERT_READ, encoding="utf-8")
    (planted / "test_real.py").write_text(_PLANTED_ASSERTED_CLOSURE, encoding="utf-8")

    found = [p.name for p in _closure_proof_files(tmp_path)]
    assert found == ["test_real.py"], f"discovery is imprecise: {found}"


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
