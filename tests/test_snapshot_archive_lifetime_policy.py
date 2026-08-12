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

    A ``with`` inside a nested ``def`` that is never called owns nothing in the
    outer function, so descending into one would certify a leak.
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


def _pos(node):
    """Source position, used to reason about statement ORDER.

    Order is the whole point. An earlier revision computed a whole-scope
    fixed point over name membership, which cannot tell an alias created
    BEFORE acquisition from one created after, cannot keep a valid alias alive
    once the original name is rebound, and cannot tell a `close()` that runs
    before the load from one that runs after.
    """
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def _target_key(node):
    """A stable textual key for an assignment target or context expression.

    ``d`` -> ``"d"``; ``self.data`` -> ``"self.data"``; ``cache["s"]`` ->
    ``"cache['s']"``. A QUALIFIED key is what stops ``self.data = np.load(...)``
    from tainting ``self``, after which any ``with self.<anything>`` in the
    method would have certified the load.
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


#: Adapters that genuinely CLOSE what they wrap.
#:
#: `nullcontext` is deliberately NOT here. Its `__exit__` is a no-op: it
#: discards the wrapped object's own `__exit__`, so
#: ``with nullcontext(np.load(p)) as d:`` never closes the archive. It is sound
#: only in the guarded conditional shape below, where it wraps the ndarray arm
#: and the raw archive goes to the `with` on the other arm.
_CLOSING_ADAPTERS = {"closing", "aclosing"}

#: Recognised, but only inside a guarded conditional -- never on its own.
_NULLCONTEXT_NAMES = {"nullcontext"}

_ADAPTER_NAMES = _CLOSING_ADAPTERS | _NULLCONTEXT_NAMES


def _contextlib_provenance(tree):
    """What this module may legitimately call an ownership adapter.

    Returns ``(module_aliases, bare_names, stack_factories)``.

    Provenance is checked because a NAME proves nothing:
    ``logger.nullcontext(loaded)`` and ``logger.enter_context(...)`` are
    arbitrary methods that happen to share a spelling with the real thing, and
    an earlier revision accepted both.
    """
    module_aliases, bare_names, stack_factories, bare_kind = set(), set(), set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "contextlib":
                    module_aliases.add(alias.asname or "contextlib")
        elif isinstance(node, ast.ImportFrom) and node.module == "contextlib":
            for alias in node.names:
                if alias.name in _ADAPTER_NAMES:
                    bound = alias.asname or alias.name
                    bare_names.add(bound)
                    bare_kind[bound] = alias.name
                elif alias.name in {"ExitStack", "AsyncExitStack"}:
                    stack_factories.add(alias.asname or alias.name)
    return module_aliases, bare_names, stack_factories, bare_kind


def _is_adapter_call(expr, prov, names) -> bool:
    """A contextlib adapter from ``names``, with verified provenance."""
    if not isinstance(expr, ast.Call):
        return False
    module_aliases, bare_names, _stacks, bare_kind = prov
    func = expr.func
    if (isinstance(func, ast.Attribute) and func.attr in names
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases):
        return True
    # A bare name must resolve to the RIGHT adapter: `from contextlib import
    # nullcontext as nc` must not satisfy a check for a closing adapter.
    return (isinstance(func, ast.Name) and func.id in bare_names
            and bare_kind.get(func.id) in names)


def _live_exit_stacks(scope, prov) -> list:
    """``(key, span)`` for stacks that are actually ENTERED by a ``with``.

    A stack only unwinds when its ``__exit__`` runs, so ``st = ExitStack()``
    without a ``with`` closes nothing, and a stack whose ``with`` has already
    unwound closes nothing either. An earlier revision tracked stack names in a
    whole-scope, order-blind set with no rebinding invalidation -- exactly the
    defect the archive-key logic had been rewritten to remove.
    """
    module_aliases, _bare, stack_factories, _kinds = prov
    live = []
    for node in _own_scope_nodes(scope):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        for item in node.items:
            value = item.context_expr
            if not isinstance(value, ast.Call) or item.optional_vars is None:
                continue
            func = value.func
            ok = (
                (isinstance(func, ast.Attribute)
                 and func.attr in {"ExitStack", "AsyncExitStack"}
                 and isinstance(func.value, ast.Name)
                 and func.value.id in module_aliases)
                or (isinstance(func, ast.Name) and func.id in stack_factories)
            )
            if not ok:
                continue
            key = _target_key(item.optional_vars)
            if key:
                live.append((key, _span(node)))
    return live


def _denotes(expr, keys, call, prov) -> bool:
    """Does ``expr`` certainly denote the archive at this point?

    EVERY alternative of a conditional must denote it. An earlier revision
    combined the two arms with ``or``, so a one-sided
    ``nullcontext(loaded) if condition else unrelated`` -- which hands an
    unrelated object to the ``with`` on the false branch -- was accepted.
    """
    if expr is call:
        return True
    key = _target_key(expr)
    if key is not None and key in keys:
        return True
    if isinstance(expr, ast.NamedExpr):
        return _denotes(expr.value, keys, call, prov)
    if isinstance(expr, ast.IfExp):
        # GUARDED CONDITIONAL OWNERSHIP: one arm wraps the value in
        # `nullcontext`, the other hands the raw archive to the `with`. That is
        # sound only because the guard sends an `NpzFile` down the raw arm and
        # only an ndarray -- which owns nothing -- into `nullcontext`.
        for wrapped, other in ((expr.body, expr.orelse), (expr.orelse, expr.body)):
            if (_is_adapter_call(wrapped, prov, _NULLCONTEXT_NAMES)
                    and any(_denotes(a, keys, call, prov) for a in wrapped.args)
                    and _denotes(other, keys, call, prov)):
                return True
        return (_denotes(expr.body, keys, call, prov)
                and _denotes(expr.orelse, keys, call, prov))
    if _is_adapter_call(expr, prov, _CLOSING_ADAPTERS):
        return any(_denotes(arg, keys, call, prov) for arg in expr.args)
    return False


def _bound_names(target) -> set:
    """Every name a binding target writes, recursing tuples, lists and stars.

    ``_target_key`` returns ``None`` for a tuple, so an earlier revision could
    not INVALIDATE through ``loaded, meta = something_else, None`` -- the key
    survived and a later ``with`` certified an archive that had been replaced.
    """
    keys = set()
    if isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            keys |= _bound_names(element)
        return keys
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    key = _target_key(target)
    if key:
        keys.add(key)
    return keys


def _rebinding_keys(node) -> set:
    """Names ``node`` rebinds through a form that is not a plain assignment.

    ``for x in ...``, ``with ... as x``, ``except ... as x``, ``import ... as
    x``, ``x += ...``, ``del x`` and ``match``-captures all rebind at runtime.
    An earlier revision recognised only assignments, so every one of these left
    the tracked key in place and a later ``with`` on that name certified the
    original archive -- defeating the module's own rebinding control through a
    different spelling.
    """
    keys = set()
    if isinstance(node, (ast.For, ast.AsyncFor)):
        keys |= _bound_names(node.target)
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        for item in node.items:
            if item.optional_vars is not None:
                keys |= _bound_names(item.optional_vars)
    elif isinstance(node, ast.ExceptHandler):
        if node.name:
            keys.add(node.name)
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            keys.add(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.AugAssign):
        keys |= _bound_names(node.target)
    elif isinstance(node, ast.Delete):
        for target in node.targets:
            keys |= _bound_names(target)
    elif isinstance(node, getattr(ast, "MatchAs", ())) and getattr(node, "name", None):
        keys.add(node.name)
    elif isinstance(node, getattr(ast, "MatchStar", ())) and getattr(node, "name", None):
        keys.add(node.name)
    return keys


def _binding_targets(node, call, keys, prov):
    """``(targets, denotes)`` for an assignment-like ``node``, else ``None``."""
    if isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
        targets, value = [node.target], node.value
    else:
        return None
    if value is call:
        return targets, True
    if isinstance(value, ast.Tuple):
        matched = []
        for target in targets:
            if isinstance(target, ast.Tuple):
                for sub, element in zip(target.elts, value.elts):
                    if element is call:
                        matched.append(sub)
        if matched:
            return matched, True
    return targets, _denotes(value, keys, call, prov)


def _span(node):
    """(first, last) source positions covered by ``node``."""
    positions = [_pos(n) for n in ast.walk(node) if hasattr(n, "lineno")]
    return (min(positions), max(positions)) if positions else (_pos(node), _pos(node))


def _closed_in_a_protecting_finally(scope, call, acquired_at, keys_at) -> bool:
    """Is a tracked target closed in a ``finally`` that guards its risky uses?

    A bare ``d.close()`` after a member access does NOT own the archive: if the
    access raises, the close is never reached.

    Three things this deliberately requires, each of which was a false negative
    when it was missing:

      * the ``Try`` and the ``close()`` must belong to THIS scope -- a close
        inside a nested ``def`` or ``lambda`` registered for later is not run
        here;
      * the ``close()`` must be an unconditional statement of ``finalbody``,
        not buried in an ``if``;
      * EVERY use of the archive after acquisition must sit inside that
        ``Try`` -- including uses that are not subscripts, such as passing the
        archive to a function or iterating it, which an earlier revision could
        not see, making its ``all(...)`` vacuously true.
    """
    scope_nodes = _own_scope_nodes(scope)
    in_scope = {id(node) for node in scope_nodes}

    for node in scope_nodes:
        if not isinstance(node, ast.Try) or not node.finalbody:
            continue
        keys = keys_at(_pos(node))
        if not keys:
            continue
        closes = [
            statement.value for statement in node.finalbody
            if isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "close"
            and id(statement.value) in in_scope
            and _target_key(statement.value.func.value) in keys
        ]
        if not closes:
            continue
        first, last = _span(node)
        risky = []
        for inner in scope_nodes:
            if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load):
                if inner.id in keys and _pos(inner) > acquired_at:
                    risky.append(_pos(inner))
            elif isinstance(inner, (ast.Subscript, ast.Attribute)):
                if _target_key(inner.value) in keys and _pos(inner) > acquired_at:
                    risky.append(_pos(inner))
        risky = [use for use in risky if not (first <= use <= last)]
        if not risky:
            return True
    return False


def _acquisition_position(scope, call):
    """Position of the smallest statement in ``scope`` that performs the load."""
    best = _pos(call)
    best_size = None
    for node in _own_scope_nodes(scope):
        if not isinstance(node, ast.stmt):
            continue
        if any(inner is call for inner in ast.walk(node)):
            size = sum(1 for _ in ast.walk(node))
            if best_size is None or size < best_size:
                best, best_size = _pos(node), size
    return best


def _reaches_a_with(scope, call, tree=None) -> bool:
    """Is ``call``'s result owned, judged in STATEMENT ORDER?

    Accepted: ``with np.load(...)``; a contextlib adapter around it or around a
    tracked alias; ``ExitStack.enter_context`` on a demonstrably tracked stack;
    an alias later handed to a ``with``; and ``close()`` inside a ``finally``
    that protects the archive's risky uses.

    Guaranteed by construction:
      * facts created BEFORE the load cannot be tainted by it;
      * an alias captures the value at its own assignment point;
      * rebinding the original name does not erase a valid earlier alias;
      * rebinding an alias invalidates it from that point onward;
      * an owner counts only AFTER acquisition;
      * every alternative of a conditional owner must denote the archive;
      * adapters need contextlib provenance, not a familiar-looking name.

    Deliberately conservative. Remaining static limits, stated precisely and
    without a blanket safety claim, because an earlier revision made one that
    did not hold:

      * a ``with`` inside a conditional branch is accepted without proving that
        branch runs. This is the one limit that can CERTIFY rather than merely
        over-report, and it is why the gate is a review aid, not a proof.
      * a load and an owner in mutually exclusive branches (load in ``if``,
        owner in ``else``) is accepted. Such code would already fail at
        runtime, but the gate does not reason about it.
      * ownership handed to another function, or stored and closed elsewhere,
        is not modelled -- reported unowned.
      * a target whose key cannot be spelled statically (a computed subscript)
        is untracked -- reported unowned.
      * loops are not iterated. An owner inside the same loop as the load is
        accepted; one outside it is rejected, since it would close only the
        final iteration's archive.

    Rebinding through ``for``, ``with ... as``, ``except ... as``, ``import
    ... as``, augmented assignment, ``del``, ``match`` captures and tuple or
    list targets IS modelled, and each invalidates the key from that point.
    """
    # Provenance comes from the MODULE's imports, so the tree is required:
    # `contextlib` is imported at module scope, never inside the function.
    prov = _contextlib_provenance(tree if tree is not None else scope)

    nodes = _own_scope_nodes(scope)
    live_stacks = _live_exit_stacks(scope, prov)
    # Anchor acquisition to the STATEMENT that performs the load, not to the
    # call expression's own column: `loaded = np.load(...)` starts to the left
    # of the call, so comparing against the call would skip the very binding
    # that introduces the archive.
    acquired_at = _acquisition_position(scope, call)

    ordered = sorted(nodes, key=_pos)
    keys: set = set()
    history = []  # (position, frozenset(keys)) after each step

    for node in ordered:
        if _pos(node) < acquired_at:
            continue
        rebound = _rebinding_keys(node)
        if rebound:
            keys -= rebound
            history.append((_pos(node), frozenset(keys)))
            continue
        binding = _binding_targets(node, call, keys, prov)
        if binding is None:
            continue
        targets, denotes = binding
        for target in targets:
            written = _bound_names(target)
            if denotes:
                keys |= written
            else:
                keys -= written
        history.append((_pos(node), frozenset(keys)))

    def keys_at(position):
        current = frozenset()
        for pos, snapshot in history:
            if pos <= position:
                current = snapshot
        return current

    def keys_before(position):
        """Bindings in force just BEFORE ``position``.

        `with d as d:` rebinds `d`, and that erasure is recorded at the `with`'s
        own position -- so judging the context expression with `keys_at` would
        apply the rebind before reading the very expression it rebinds. Reusing
        the handle name is common; this keeps it correct.
        """
        current = frozenset()
        for pos, snapshot in history:
            if pos < position:
                current = snapshot
        return current

    # If the load happens inside a loop, an owner OUTSIDE that loop closes only
    # the final iteration's archive and leaks the rest, so it does not count.
    loop_span = None
    for node in _own_scope_nodes(scope):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            if any(inner is call for inner in ast.walk(node)):
                span = _span(node)
                if loop_span is None or span[0] > loop_span[0]:
                    loop_span = span

    def in_force(position):
        return loop_span is None or loop_span[0] <= position <= loop_span[1]

    for node in ordered:
        if _pos(node) < acquired_at or not in_force(_pos(node)):
            continue
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if _denotes(item.context_expr, keys_before(_pos(node)), call, prov):
                    return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"enter_context", "callback", "push"}
                and in_force(_pos(node))):
            stack_key = _target_key(node.func.value)
            inside = any(
                stack_key == key and first <= _pos(node) <= last
                for key, (first, last) in live_stacks
            )
            if not inside:
                continue
            current = keys_at(_pos(node))
            handed = list(node.args)
            # `stack.callback(d.close)` hands the bound method, not the archive.
            handed += [
                arg.value for arg in node.args
                if isinstance(arg, ast.Attribute) and arg.attr == "close"
            ]
            if any(_denotes(arg, current, call, prov) for arg in handed):
                return True

    return _closed_in_a_protecting_finally(scope, call, acquired_at, keys_at)


def _owned_load_calls(tree) -> set:
    """Ids of the NumPy loads in ``tree`` whose archive reaches an owner."""
    names = _numpy_load_names(tree)
    owned = set()
    for call in _np_load_calls(tree, names):
        if _reaches_a_with(_scope_of(tree, call), call, tree):
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
    assert _reaches_a_with(loader, calls[0], tree), (
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
    assert not _reaches_a_with(_scope_of(tree, call), call, tree)


@pytest.mark.parametrize(
    "source",
    [_PLANTED_DIRECT, _PLANTED_CONDITIONAL, _PLANTED_CLOSING,
     _PLANTED_EXITSTACK, _PLANTED_TRY_FINALLY, _PLANTED_WALRUS,
     _PLANTED_ATTRIBUTE_CLOSE, _PLANTED_TUPLE_ASSIGN,
     _PLANTED_ALIAS_SURVIVES_REBIND],
    ids=["direct-with", "conditional-nullcontext", "contextlib-closing",
         "exitstack-enter-context", "try-finally-close", "walrus",
         "attribute-target-closed", "tuple-assignment",
         "alias-survives-a-later-rebind"],
)
def test_the_ownership_matcher_accepts_correct_shapes(source):
    """A gate that rejects working code is worse than no gate.

    The conditional case is what `scripts/lucid_server.py` and
    `scripts/portable_genome.py` actually do. The other four are standard
    idioms a maintainer might reasonably convert to -- `ExitStack` especially,
    since it is the usual answer to acquire-then-conditionally-own.
    """
    tree, call = _single_load(source)
    assert _reaches_a_with(_scope_of(tree, call), call, tree)


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
    assert not _reaches_a_with(_scope_of(tree, call), call, tree)


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

    Every one was reported OWNED before this control existed. They are the
    reason the matcher replays bindings in statement order, models the
    non-assignment rebinding forms, refuses to walk into nested scopes when
    looking for a `close()`, and counts a plain name load as a risky use.
    """
    tree, call = _single_load(source)
    assert not _reaches_a_with(_scope_of(tree, call), call, tree)


@pytest.mark.parametrize(
    "source",
    ["import numpy as np\n"
     "def f(paths, report):\n"
     "    for p in paths:\n"
     "        with np.load(str(p), allow_pickle=False) as d:\n"
     "            report(d['lattice'])\n",
     "import numpy as np\n"
     "def f(p, consume):\n"
     "    d = np.load(str(p), allow_pickle=False)\n"
     "    try:\n        return consume(d)\n"
     "    finally:\n        d.close()\n"],
    ids=["owner-inside-the-same-loop", "non-subscript-use-inside-the-try"],
)
def test_the_stricter_rules_still_accept_correct_code(source):
    """The tightening must not reject working idioms.

    An owner in the same loop as the load is fine -- each iteration's archive is
    closed. And a non-subscript use is fine when it sits inside the Try the
    finally protects; it is only a problem outside it.
    """
    tree, call = _single_load(source)
    assert _reaches_a_with(_scope_of(tree, call), call, tree)

# --- adapter-semantics and ExitStack-liveness controls ----------------------
#
# `nullcontext.__exit__` is a NO-OP: it discards the wrapped object's own
# `__exit__`. Treating it as an ownership adapter meant
# `with nullcontext(np.load(p)) as d:` read as owned while leaking, and -- worse
# -- deleting the `isinstance` guard from the production loader, the single most
# likely simplification, still read as owned.
#
# An ExitStack only unwinds when its own `__exit__` runs, so a stack that was
# never entered, or whose `with` has already unwound, closes nothing.

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
    "walrus-directly-in-the-context-expression":
        "import numpy as np\ndef f(p):\n"
        "    with (d := np.load(str(p), allow_pickle=False)) as data:\n"
        "        return data['lattice']\n",
    "stack-callback-close-in-a-live-stack":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = np.load(str(p), allow_pickle=False)\n"
        "        stack.callback(d.close)\n"
        "        return d['lattice']\n",
    "live-exitstack-enter-context":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return d['lattice']\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_ADAPTER_LEAKS.values()),
                         ids=list(_PLANTED_ADAPTER_LEAKS))
def test_adapter_and_stack_leaks_are_not_certified(source):
    """`nullcontext` closes nothing, and an un-entered stack unwinds nothing."""
    tree, call = _single_load(source)
    assert not _reaches_a_with(_scope_of(tree, call), call, tree)


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
    assert _reaches_a_with(_scope_of(tree, call), call, tree)


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

#: Shapes whose ownership IS structurally guaranteed. Without these the repair
#: could pass by rejecting everything.
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
    "fused-in-a-closing-adapter":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.closing(np.load(str(p), allow_pickle=False)) as d:\n"
        "        return d['lattice']\n",
    "adjacent-owner-immediately-after-acquisition":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    with d as x:\n        return x['lattice']\n",
    "production-guarded-conditional-owner":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    loaded = np.load(str(p), allow_pickle=False)\n"
        "    owner = contextlib.nullcontext(loaded) if isinstance(loaded, np.ndarray) else loaded\n"
        "    with owner as data:\n        return data['lattice']\n",
    "live-exitstack-enter-context":
        "import contextlib\nimport numpy as np\ndef f(p):\n"
        "    with contextlib.ExitStack() as stack:\n"
        "        d = stack.enter_context(np.load(str(p), allow_pickle=False))\n"
        "        return d['lattice']\n",
    "protecting-finally-close":
        "import numpy as np\ndef f(p):\n"
        "    d = np.load(str(p), allow_pickle=False)\n"
        "    try:\n        return d['lattice']\n"
        "    finally:\n        d.close()\n",
}


@pytest.mark.parametrize("source", list(_PLANTED_CONTROL_FLOW_LEAKS.values()),
                         ids=list(_PLANTED_CONTROL_FLOW_LEAKS))
def test_control_flow_leaks_are_not_certified(source):
    """Source order is not reachability, and a `with` statement is not yet
    ownership -- ownership begins at a successful ``__enter__``."""
    tree, call = _single_load(source)
    assert not _reaches_a_with(_scope_of(tree, call), call, tree)


@pytest.mark.parametrize("source", list(_PLANTED_ALREADY_REJECTED.values()),
                         ids=list(_PLANTED_ALREADY_REJECTED))
def test_already_rejected_shapes_stay_rejected(source):
    """Not failing-first: the unchanged matcher already refuses these."""
    tree, call = _single_load(source)
    assert not _reaches_a_with(_scope_of(tree, call), call, tree)


@pytest.mark.parametrize("source", list(_PLANTED_STRUCTURAL_OWNERSHIP.values()),
                         ids=list(_PLANTED_STRUCTURAL_OWNERSHIP))
def test_structurally_guaranteed_ownership_is_accepted(source):
    """The repair must not pass by rejecting everything."""
    tree, call = _single_load(source)
    assert _reaches_a_with(_scope_of(tree, call), call, tree)

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
