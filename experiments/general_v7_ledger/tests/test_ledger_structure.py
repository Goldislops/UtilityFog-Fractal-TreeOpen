"""Structural, type, refusal and validator-behaviour controls.

Implementation-dependent: these fail with ``implementation-absent`` until the
schema and validator exist. Every fixture is synthetic and no locator here
refers to a real resource.

Control ids GV7-S-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from experiments.general_v7_ledger.tests import _support as sup


class HookedStr(str):
    """A str subclass that records whether any hook ran."""

    def __new__(cls, value):
        obj = str.__new__(cls, value)
        obj.hooks = {}
        return obj

    def _bump(self, name):
        self.hooks[name] = self.hooks.get(name, 0) + 1

    def __eq__(self, other):
        self._bump("__eq__")
        return str.__eq__(self, other)

    def __hash__(self):
        self._bump("__hash__")
        return str.__hash__(self)

    def __repr__(self):
        self._bump("__repr__")
        return str.__repr__(self)

    def __len__(self):
        self._bump("__len__")
        return str.__len__(self)


#: A module-level log, so a hostile class needs no attribute of its own and
#: the probe cannot be defeated by the very interception it is testing.
class MetaclassHookLog:
    hits = []


class MroInterceptingMeta(type):
    """Intercepts ``__mro__`` and raises.

    A validator that decides the root's type by reading ``type(payload).__mro__``
    calls this, and the ``RuntimeError`` escapes the closed refusal vocabulary.
    """

    def __getattribute__(cls, name):
        if name == "__mro__":
            MetaclassHookLog.hits.append(("raising", name))
            raise RuntimeError("synthetic metaclass hook")
        return type.__getattribute__(cls, name)


class MroForgingMeta(type):
    """Intercepts ``__mro__`` and lies, without raising.

    The quieter half of the same defect: a value that is not a mapping at all
    reports an MRO containing ``dict``, and is then refused as a mapping
    subclass with the wrong token.
    """

    def __getattribute__(cls, name):
        if name == "__mro__":
            MetaclassHookLog.hits.append(("forging", name))
            return (dict,)
        return type.__getattribute__(cls, name)


class RaisingMroPropertyMeta(type):
    """A ``__mro__`` PROPERTY on the metaclass, which raises.

    ``type.__getattribute__`` bypasses an overridden ``__getattribute__`` and
    nothing else: it finds this descriptor and calls it.
    """

    @property
    def __mro__(cls):
        MetaclassHookLog.hits.append(("mro-property-raising", "__mro__"))
        raise RuntimeError("synthetic __mro__ property")


class ForgingMroPropertyMeta(type):
    """The same descriptor route, lying instead of raising."""

    @property
    def __mro__(cls):
        MetaclassHookLog.hits.append(("mro-property-forging", "__mro__"))
        return (dict,)


class ShadowMroMeta(type):
    """A PLAIN ``__mro__`` attribute shadowing the real one.

    No descriptor, no hook, nothing to invoke -- an attribute lookup simply
    finds this tuple first and returns it. There is no ``__getattribute__`` to
    bypass, so no attribute-read primitive can help.
    """

    __mro__ = (dict,)


class RaisingEqMeta(type):
    """Escapes during ``dict in <mro>``, after any read has succeeded.

    The comparison is narrowed to ``dict`` so these classes stay ordinarily
    comparable and hashable, and cannot perturb the harness. ``__hash__`` is
    inherited explicitly because defining ``__eq__`` would otherwise clear it.
    """

    __hash__ = type.__hash__

    def __eq__(cls, other):
        if other is dict:
            MetaclassHookLog.hits.append(("metaclass-eq", "__eq__"))
            raise RuntimeError("synthetic metaclass __eq__")
        return NotImplemented


class BasesInterceptingMeta(type):
    """Intercepts ``__bases__`` and raises.

    ``MroInterceptingMeta`` fires only on ``__mro__``, so an implementation
    reading ``__bases__`` slipped past every earlier fixture.
    """

    def __getattribute__(cls, name):
        if name == "__bases__":
            MetaclassHookLog.hits.append(("bases-raising", name))
            raise RuntimeError("synthetic __bases__ hook")
        return type.__getattribute__(cls, name)


class BasesForgingMeta(type):
    """Intercepts ``__bases__`` and lies, without raising."""

    def __getattribute__(cls, name):
        if name == "__bases__":
            MetaclassHookLog.hits.append(("bases-forging", name))
            return (dict,)
        return type.__getattribute__(cls, name)


class HostileRaisingRoot(metaclass=MroInterceptingMeta):
    pass


class HostileForgingRoot(metaclass=MroForgingMeta):
    pass


class RaisingMroPropertyRoot(metaclass=RaisingMroPropertyMeta):
    pass


class ForgingMroPropertyRoot(metaclass=ForgingMroPropertyMeta):
    pass


class ShadowMroRoot(metaclass=ShadowMroMeta):
    pass


class EqHostileRoot(metaclass=RaisingEqMeta):
    pass


class EqHostileDictSubclass(dict, metaclass=RaisingEqMeta):
    """A GENUINE ``dict`` subclass. The equality route escapes here too, so
    even the correct ``type-not-exact`` branch is reachable only by running
    supplied code."""


class BasesPropertyRaisingMeta(type):
    """A ``__bases__`` PROPERTY, which ``type.__getattribute__`` still calls."""

    @property
    def __bases__(cls):
        MetaclassHookLog.hits.append(("bases-property-raising", "__bases__"))
        raise RuntimeError("synthetic __bases__ property")


class BasesPropertyForgingMeta(type):
    """The same descriptor route, lying instead of raising."""

    @property
    def __bases__(cls):
        MetaclassHookLog.hits.append(("bases-property-forging", "__bases__"))
        return (dict,)


class BasesShadowMeta(type):
    """A PLAIN ``__bases__`` attribute shadowing the real one. No hook at all."""

    __bases__ = (dict,)


class MroMethodRaisingMeta(type):
    """Overrides ``mro()``. Armed after class creation, so the class builds."""

    armed = False

    def mro(cls):
        if MroMethodRaisingMeta.armed:
            MetaclassHookLog.hits.append(("mro-method-raising", "mro"))
            raise RuntimeError("synthetic mro() override")
        return type.mro(cls)


class MroMethodForgingMeta(type):
    """Overrides ``mro()`` and returns a forged sequence containing ``dict``."""

    armed = False

    def mro(cls):
        if MroMethodForgingMeta.armed:
            MetaclassHookLog.hits.append(("mro-method-forging", "mro"))
            return [cls, dict, object]
        return type.mro(cls)


class DuckTypedDecoy:
    """Not a mapping at all, but it answers to ``keys`` and ``__getitem__``.

    A validator that duck-types instead of deciding a type accepts this.
    """

    def keys(self):
        MetaclassHookLog.hits.append(("duck-keys", "keys"))
        return ()

    def __getitem__(self, key):
        MetaclassHookLog.hits.append(("duck-getitem", "__getitem__"))
        raise KeyError(key)


class _IntermediateDictSubclass(dict):
    pass


class GrandchildDictSubclass(_IntermediateDictSubclass):
    """An INDIRECT ``dict`` subclass: ``dict`` is not among its own bases."""


class BasesRaisingRoot(metaclass=BasesInterceptingMeta):
    pass


class BasesPropertyRaisingRoot(metaclass=BasesPropertyRaisingMeta):
    pass


class BasesPropertyForgingRoot(metaclass=BasesPropertyForgingMeta):
    pass


class BasesShadowRoot(metaclass=BasesShadowMeta):
    pass


class MroMethodRaisingRoot(metaclass=MroMethodRaisingMeta):
    pass


class MroMethodForgingRoot(metaclass=MroMethodForgingMeta):
    pass


class BasesForgingRoot(metaclass=BasesForgingMeta):
    pass


class ClassPropertyRaisingRoot:
    """An OBJECT-level ``__class__`` property that raises.

    Not a metaclass at all: the hook lives on the instance's own class, and it
    is what ``isinstance`` would have run. ``type(payload)`` reads the type
    slot and never performs this lookup.
    """

    @property
    def __class__(self):
        MetaclassHookLog.hits.append(("class-property-raising", "__class__"))
        raise RuntimeError("synthetic __class__ property")


class ClassPropertyForgingRoot:
    """An object-level ``__class__`` property that forges ``dict``."""

    @property
    def __class__(self):
        MetaclassHookLog.hits.append(("class-property-forging", "__class__"))
        return dict


class HookedDict(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.hooks = {}

    def __iter__(self):
        self.hooks["__iter__"] = self.hooks.get("__iter__", 0) + 1
        return dict.__iter__(self)

    def __len__(self):
        self.hooks["__len__"] = self.hooks.get("__len__", 0) + 1
        return dict.__len__(self)


class HookedList(list):
    def __init__(self, *args):
        list.__init__(self, *args)
        self.hooks = {}

    def __iter__(self):
        self.hooks["__iter__"] = self.hooks.get("__iter__", 0) + 1
        return list.__iter__(self)


def refuse(schema, payload, token):
    """Assert ``validate_ledger`` refuses with an exact token and no leakage."""
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    error = excinfo.value
    assert error.token == token, (token, error.token)
    assert error.token in schema.REFUSAL_TOKENS
    rendered = str(error)
    for marker in sup.MARKERS:
        assert marker not in rendered
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    return error


def test_gv7_s_001_the_committed_ledger_validates_against_the_schema():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    schema.validate_ledger(ledger)


def test_gv7_s_002_the_declared_identity_fields_are_exact():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert ledger["schema"] == sup.SCHEMA_ID == schema.SCHEMA_ID
    assert ledger["ledger_id"] == sup.LEDGER_ID == schema.LEDGER_ID
    assert ledger["corpus"] == sup.CORPUS == schema.CORPUS
    assert ledger["intake_state"] == sup.INTAKE_STATE == schema.INTAKE_STATE


def test_gv7_s_003_the_root_key_set_is_closed_and_exact():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert set(ledger) == sup.ROOT_KEYS == set(schema.ROOT_KEYS)
    extra = dict(ledger)
    extra["an_undeclared_root_key"] = "synthetic"
    refuse(schema, extra, "undeclared-key")
    for key in sorted(sup.ROOT_KEYS):
        missing = dict(ledger)
        del missing[key]
        refuse(schema, missing, "missing-key")


def test_gv7_s_004_every_nested_block_key_set_is_closed_and_exact():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    pairs = (
        ("batches", sup.BATCH_KEYS),
        ("sources", sup.SOURCE_KEYS),
        ("claims", sup.CLAIM_KEYS),
        ("relationships", sup.RELATIONSHIP_KEYS),
        ("unresolved", sup.UNRESOLVED_KEYS),
        ("artifacts", sup.ARTIFACT_KEYS),
    )
    for collection, keys in pairs:
        records = sup.collection_of(ledger, collection)
        assert records, collection
        for record in records:
            assert set(record) == keys, (collection, sorted(set(record) ^ keys))
        hostile = json.loads(json.dumps(ledger))
        hostile[collection][0]["an_undeclared_nested_key"] = "synthetic"
        refuse(schema, hostile, "undeclared-key")

    # `corrections` may legitimately be empty, so its closed shape is exercised
    # through a synthetic record rather than by hoping one is committed.
    for record in sup.collection_of(ledger, "corrections"):
        assert set(record) == sup.CORRECTION_KEYS, sorted(
            set(record) ^ sup.CORRECTION_KEYS
        )
    good = with_correction(ledger, synthetic_correction(ledger))
    schema.validate_ledger(good)
    hostile = with_correction(
        ledger, synthetic_correction(ledger, **{"statement": "synthetic"})
    )
    hostile["corrections"][0]["an_undeclared_nested_key"] = "synthetic"
    refuse(schema, hostile, "undeclared-key")


#: The frozen root decision, as an executable BLOCK. Correction 4 compared only
#: the two test EXPRESSIONS, which a dead compliant-looking nested ``if``
#: followed by a real classifier satisfied while the module actually decided by
#: an identity scan over ``type.mro(...)``. Matching the block structurally
#: closes that: the comparison is ``ast.dump`` against this template, so an
#: empty ``else``, an exact statement count, the absence of ``pass`` or a
#: conditional expression, and the two exact refusal calls are all enforced at
#: once, by one equality.
FROZEN_ROOT_BLOCK = (
    "if type({parameter}) is not dict:\n"
    "    if issubclass(type({parameter}), dict):\n"
    "        _refuse('type-not-exact')\n"
    "    _refuse('root-not-object')\n"
)


def _is_core_reexport(statement):
    """True for exactly ``validate_ledger = _core.validate_ledger``."""
    import ast

    target = statement.targets[0]
    value = statement.value
    return (
        isinstance(target, ast.Name)
        and target.id == "validate_ledger"
        and isinstance(value, ast.Attribute)
        and value.attr == "validate_ledger"
        and isinstance(value.value, ast.Name)
        and value.value.id == "_core"
    )


#: The refusal helper is the executable half of the frozen block: both calls in
#: that block are calls to ``_refuse``. A ``_refuse`` that RETURNS leaves both
#: falling through and hands the decision to whatever follows -- a conforming
#: block that decides nothing, which is the Correction 5 defeat shape moved one
#: level into the helper. Jack reproduced exactly that, with a dead ``raise``
#: under ``if False:`` and then ``return token``; it scored ``('payload', None)``
#: because the Correction 5 check asked only whether a ``raise`` appeared
#: SOMEWHERE inside the helper, which a dead one does.
#:
#: The helper is therefore pinned the way the block is: one signature and one
#: body, by ``ast.dump`` equality against these templates.
FROZEN_REFUSE_SIGNATURE = "def _refuse(token, path=()):\n    pass\n"
FROZEN_REFUSE_BODY = "raise LedgerError(token, path) from None\n"


def _binds(target, name):
    """True when ``target`` stores or deletes ``name``."""
    import ast

    return any(
        isinstance(inner, ast.Name)
        and inner.id == name
        and isinstance(inner.ctx, (ast.Store, ast.Del))
        for inner in ast.walk(target)
    )


def binding_census(tree, name):
    """Every ENUMERATED binding of ``name`` in ``tree``, as ``(kind, node)``.

    A scan that reads only the module's top level accepts
    ``if True: validate_ledger = _hostile``; one that looks only for assignments
    accepts ``class validate_ledger: pass``. Jack reproduced both against the
    Correction 5 matcher, each scoring ``('payload', None)``. Neither is an
    exotic route -- they are the two most ordinary ways to rebind a name that
    the previous scan happened not to look at, which is precisely the failure
    mode of asking a narrow question.

    So this asks the question that decides the matter -- *what else binds this
    name, anywhere in the module* -- and leaves the caller to permit an
    explicit, small set of nodes and refuse the remainder.

    It enumerates the forms named below. It is NOT a proof that no other form
    exists: ``setattr`` on the module object, a write through
    ``sys.modules[__name__].__dict__``, and ``exec`` of generated source each
    bind a module attribute without producing any node this can see. Those are
    disclosed as residuals rather than asserted away.

    The enumeration has already been wrong once since it was written: a PEP 695
    ``type validate_ledger = int`` binds the module attribute -- after it runs
    the name is a ``TypeAliasType`` -- and was accepted until ``ast.TypeAlias``
    was added below. That is the same defect as Jack's ``class validate_ledger:
    pass``, one spelling further out, and it is recorded here rather than
    quietly fixed, because it is the evidence for why this says "enumerated"
    everywhere it could have said "every".

    A PEP 695 *type parameter* -- ``def _f[validate_ledger]() -> None`` -- is
    deliberately NOT collected HERE: it binds inside the function's annotation
    scope and never touches the module namespace, so censusing it as a binding
    of the module name would be a false positive.

    That reasoning is right about the name being pinned and was WRONG as a
    justification for ignoring type parameters altogether. The type-parameter
    scope lexically encloses the body, so it shadows the module names the body
    READS: ``def _refuse_ceiling[LedgerCeilingError](token)`` leaves the frozen
    raise dumping identically while raising ``TypeError`` at runtime, because
    the exception class now resolves to the TypeVar. A critic reproduced it on
    the shipped implementation. Type parameters are therefore refused by the
    definition pins below, which is a different question from this census.
    """
    import ast

    census = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                census.append(("definition", node))
        elif isinstance(node, ast.ClassDef):
            if node.name == name:
                census.append(("class-definition", node))
        elif isinstance(node, getattr(ast, "TypeAlias", ())):
            # PEP 695. `type validate_ledger = int` binds the MODULE attribute:
            # after it runs, the name is a `TypeAliasType`, not the function.
            # The empty-tuple fallback makes `isinstance` simply False where
            # the node type does not exist.
            if isinstance(node.name, ast.Name) and node.name.id == name:
                census.append(("type-alias", node))
        elif isinstance(node, ast.Assign):
            if any(_binds(target, name) for target in node.targets):
                census.append(("assignment", node))
        elif isinstance(node, ast.AnnAssign):
            if _binds(node.target, name):
                census.append(("annotated-assignment", node))
        elif isinstance(node, ast.AugAssign):
            if _binds(node.target, name):
                census.append(("augmented-assignment", node))
        elif isinstance(node, ast.Delete):
            if any(_binds(target, name) for target in node.targets):
                census.append(("deletion", node))
        elif isinstance(node, ast.NamedExpr):
            if _binds(node.target, name):
                census.append(("named-expression", node))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if _binds(node.target, name):
                census.append(("loop-target", node))
        elif isinstance(node, ast.comprehension):
            if _binds(node.target, name):
                census.append(("comprehension-target", node))
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None and _binds(node.optional_vars, name):
                census.append(("context-manager-target", node))
        elif isinstance(node, ast.ExceptHandler):
            if node.name == name:
                census.append(("exception-target", node))
        elif isinstance(node, ast.MatchAs):
            if node.name == name:
                census.append(("match-capture", node))
        elif isinstance(node, ast.MatchStar):
            if node.name == name:
                census.append(("match-star", node))
        elif isinstance(node, ast.MatchMapping):
            if node.rest == name:
                census.append(("match-mapping-rest", node))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                # `from x import *` keys as the literal "*" and can never match
                # a name, so a wildcard is censused as itself: it may bind
                # anything, including this.
                if alias.name == "*":
                    census.append(("star-import", node))
                elif (alias.asname or alias.name.split(".")[0]) == name:
                    census.append(("import", node))
        elif isinstance(node, ast.arg):
            if node.arg == name:
                census.append(("parameter", node))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            if name in node.names:
                census.append(("global-or-nonlocal", node))
        elif isinstance(node, ast.Attribute):
            # `_refuse.__code__ = _tame.__code__` replaces the helper's
            # executable code and leaves its name, signature and source body
            # untouched -- an object mutation rather than a name binding, and
            # invisible to any scan looking for a Name in Store context. The
            # shipped package never reads or writes an attribute of either
            # pinned name, so all of it is refused.
            if isinstance(node.value, ast.Name) and node.value.id == name:
                census.append(("attribute-access", node))
            # `_core.validate_ledger = _hostile` writes the attribute on the
            # module object instead.
            elif node.attr == name and not isinstance(node.ctx, ast.Load):
                census.append(("module-attribute-write", node))
        elif isinstance(node, ast.Subscript):
            if (
                not isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", None)
                in ("globals", "vars", "locals")
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == name
            ):
                census.append(("namespace-mapping-write", node))
    return census


def frozen_refusal_helper(sources, defining_module):
    """``None``, or the defect in the sole production ``_refuse``.

    Kept as the name GV7-S-005 and the Correction 6 evidence use, but it is now
    one call into ``frozen_helper_defect``. The two were near-identical and
    drifted inside a single correction -- the type-parameter refusal landed in
    one while ``frozen_root_decision`` called the other, so the root pin
    accepted a helper the helper pin refused. A rule now has one home.
    """
    return frozen_helper_defect(
        sources, defining_module, "_refuse", FROZEN_REFUSE_SIGNATURE, FROZEN_REFUSE_BODY
    )


#: The names by which a module reaches its own namespace AS DATA, and so
#: rebinds anything in it without ever writing that name down.
#:
#: The first version of this correction refused only a literal
#: ``globals()["validate_ledger"] = ...`` subscript. Three independent reviews
#: each defeated it in a single token -- ``_g = globals()`` first, a computed
#: key, ``globals().update(...)``, ``globals().__setitem__(...)`` -- because it
#: was aimed at a SPELLING and not at the capability. A production module has no
#: use for any of these, and the shipped package calls none of them, so the
#: capability is refused rather than one of its shapes.
#: Attributes that ARE a module namespace, however they are reached.
NAMESPACE_DUNDERS = ("__dict__", "__globals__", "__builtins__")

NAMESPACE_REACH_NAMES = (
    "globals",
    "vars",
    "locals",
    "setattr",
    "delattr",
    "exec",
    "eval",
)


def namespace_reach_violations(tree):
    """``(kind, detail)`` for each way this module reaches its namespace as data.

    The residual is stated plainly and is NOT closed: a builtin rebound before
    use -- ``_g = globals`` and then ``_g()`` -- defeats any scan that works by
    name, exactly as it does for ``getattr`` in GV7-S-028. This refuses the
    named vocabulary, which is narrower than refusing the capability, and the
    difference is disclosed rather than described away.
    """
    import ast

    violations = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in NAMESPACE_REACH_NAMES
        ):
            violations.append(("namespace-builtin-call", node.func.id))
        elif isinstance(node, ast.Attribute) and node.attr in NAMESPACE_DUNDERS:
            # `sys.modules[__name__].__dict__["validate_ledger"] = ...` is a
            # namespace write that no name scan over the target would see.
            #
            # `__globals__` is the same dictionary through a different door,
            # and it does not have to be read off the pinned name to reach it:
            # `_leaky.__globals__["_refuse"] = _leaky`, written on ANY function
            # in the module, replaces the pinned helper while every census
            # rooted at `_refuse` sees nothing. Correction 7 closed only the
            # spelling rooted at the pinned name; a critic reproduced the other
            # door end to end, with the whole suite at baseline.
            violations.append(("module-namespace-reach", node.attr))
    return violations


def _core_is_the_package(tree):
    """True when ``_core`` is bound once, by the frozen package self-binding.

    ``_is_core_reexport`` pins the SPELLING ``_core`` and nothing else -- the
    very defect Correction 5 closed for ``sys``, re-committed one control over.
    A surface that writes ``import _hostile as _core`` and then performs the
    blessed re-export exports a different function entirely. So the permitted
    re-export is only permitted where ``_core`` demonstrably names this package.
    """
    import ast

    # Reading an attribute OF `_core` is what the permitted re-export does --
    # and what `LedgerError = _core.LedgerError` does beside it -- so those
    # reads are not rebindings of `_core`. Counting them as such was my own
    # false positive, and it failed the conforming two-module fixture.
    bindings = [
        (kind, node)
        for kind, node in binding_census(tree, "_core")
        if kind != "attribute-access"
    ]
    if len(bindings) != 1 or bindings[0][0] != "assignment":
        return False
    statement = bindings[0][1]
    if statement not in tree.body or len(statement.targets) != 1:
        return False
    value = statement.value
    return (
        isinstance(value, ast.Subscript)
        and isinstance(value.value, ast.Attribute)
        and value.value.attr == "modules"
        and isinstance(value.value.value, ast.Name)
        and value.value.value.id == "sys"
        and isinstance(value.slice, ast.Constant)
        and value.slice.value == sup.SYS_MODULES_SELF_BINDING_KEY
    )


def frozen_helper_defect(sources, defining_module, helper, signature, body):
    """``None``, or the defect in the sole production ``helper``.

    Correction 6 pinned ``_refuse`` and nothing else. ``_refuse_path``,
    ``_refuse_ceiling`` and ``_refuse_input`` carry ten of the thirty-nine
    tokens between them -- every stage-1 path refusal, the stage-2 ceiling and
    all three stage-3 parse refusals -- and appeared nowhere in the acceptance
    surface, so a sibling that returned instead of raising passed the whole
    suite and then accepted a ledger read through a redirecting junction.

    The same pin, generalised: one module-scope definition in the module that
    defines ``validate_ledger``, no other binding of the name anywhere, no
    decorator, the exact signature, and exactly one executable statement equal
    to the frozen ``raise``. Signature and body are compared by ``ast.dump``,
    so a dead or conditional raise, a wrong exception class, a missing
    ``from None``, a return, and an extra statement are all refused by the same
    equality rather than by a list of shapes somebody thought of.
    """
    import ast

    definitions = []
    census = []
    for name, source in sorted(sources.items()):
        tree = ast.parse(source)
        for kind, node in binding_census(tree, helper):
            census.append((name, kind, node))
        for statement in tree.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == helper:
                definitions.append((name, statement))

    if len(definitions) != 1:
        return (
            f"expected exactly one module-scope `{helper}` definition, found "
            f"{len(definitions)}"
        )
    module, function = definitions[0]
    if module != defining_module:
        return (
            f"`{helper}` is defined in {module}, not in {defining_module} where "
            "validate_ledger is defined"
        )

    stray = sorted(
        {f"{name}:{kind}" for name, kind, node in census if node is not function}
    )
    if stray:
        return f"`{helper}` carries other bindings: {stray}"

    reach = sorted(
        {
            f"{name}:{kind}:{detail}"
            for name, source in sorted(sources.items())
            for kind, detail in namespace_reach_violations(ast.parse(source))
        }
    )
    if reach:
        return f"a production module reaches its namespace as data: {reach}"

    if function.decorator_list:
        return f"`{helper}` carries a decorator"
    if getattr(function, "type_params", ()):
        # A type parameter shadows the module names the frozen body reads.
        return f"`{helper}` carries type parameters"
    expected = ast.parse(signature).body[0]
    if ast.dump(function.args) != ast.dump(expected.args):
        return f"`{helper}` does not take exactly the frozen signature"

    statements = list(function.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if len(statements) != 1:
        return f"`{helper}` has {len(statements)} executable statements, not one"
    if ast.dump(statements[0]) != ast.dump(ast.parse(body).body[0]):
        return f"`{helper}` does not raise exactly the frozen statement"
    return None


def defining_module_of(sources, name="validate_ledger"):
    """The production module carrying the sole module-scope definition."""
    import ast

    found = [
        module
        for module, source in sorted(sources.items())
        for statement in ast.parse(source).body
        if isinstance(statement, ast.FunctionDef) and statement.name == name
    ]
    assert len(found) == 1, found
    return found[0]


#: One mutation per defeat shape, applied to EVERY helper in turn, so no helper
#: is pinned only by a shape some other helper happened to be tested for.
#: ``{h}`` is the helper name, ``{a}`` its parameter list, ``{r}`` its frozen
#: raise statement.
HELPER_MUTATIONS = (
    ("returns normally instead of raising",
     "def {h}({a}):\n    return token\n", "does not raise"),
    ("a dead raise under `if False:`, then a return",
     "def {h}({a}):\n    if False:\n        {r}\n    return token\n",
     "executable statements"),
    ("a conditional raise",
     "def {h}({a}):\n    if token:\n        {r}\n", "does not raise"),
    ("a raise swallowed by its own try",
     "def {h}({a}):\n    try:\n        {r}\n    except Exception:\n        pass\n",
     "does not raise"),
    ("the wrong exception class",
     "def {h}({a}):\n    raise ValueError(token) from None\n", "does not raise"),
    ("no `from None`",
     "def {h}({a}):\n    {n}\n", "does not raise"),
    ("an extra executable statement before the raise",
     "def {h}({a}):\n    _log(token)\n    {r}\n", "executable statements"),
    ("a decorator that could wrap or replace it",
     "@wrapper\ndef {h}({a}):\n    {r}\n", "carries a decorator"),
    ("an async definition",
     "async def {h}({a}):\n    {r}\n", "found 0"),
    ("a class of the same name",
     "class {h}:\n    pass\n", "found 0"),
    ("a definition behind a module-scope condition",
     "if _FLAG:\n    def {h}({a}):\n        {r}\n", "found 0"),
    ("a duplicated definition",
     "def {h}({a}):\n    {r}\n\n\ndef {h}({a}):\n    {r}\n", "found 2"),
    ("a nested definition beside the module-scope one",
     "def {h}({a}):\n    {r}\n\n\ndef _factory():\n    def {h}({a}):\n"
     "        return token\n    return {h}\n", "carries other bindings"),
    ("rebound after definition",
     "def {h}({a}):\n    {r}\n\n\n{h} = _noop\n", "carries other bindings"),
    ("imported over the definition",
     "def {h}({a}):\n    {r}\n\n\nfrom _elsewhere import {h}\n",
     "carries other bindings"),
    ("its __code__ replaced",
     "def {h}({a}):\n    {r}\n\n\n{h}.__code__ = _tame.__code__\n",
     "carries other bindings"),
    ("deleted after definition",
     "def {h}({a}):\n    {r}\n\n\ndel {h}\n", "carries other bindings"),
    ("a wrong signature",
     "def {h}(token, extra, *rest, **kw):\n    {r}\n", "frozen signature"),
    ("a type parameter shadowing the exception class it raises",
     "def {h}[LedgerError]({a}):\n    {r}\n", "type parameters"),
    ("a namespace write through another function's __globals__",
     "def {h}({a}):\n    {r}\n\n\ndef _other():\n    pass\n"
     "\n\n_other.__globals__['{h}'] = _tame\n", "namespace as data"),
)


def frozen_root_decision(sources):
    """``(parameter, defect)`` for the sole production ``validate_ledger``.

    ``sources`` maps a production module name to its source text.

    What is pinned is the **exported binding**, not a ``def`` statement the
    module may never run and may immediately replace. Jack reproduced three
    shapes against the Correction 5 matcher, each scoring ``('payload', None)``:
    a ``_refuse`` holding a dead ``raise`` and returning normally; a conforming
    definition followed by ``if True: validate_ledger = _hostile``; and one
    followed by ``class validate_ledger: pass``.

    A binding census over every enumerated form therefore decides, and exactly
    two nodes are permitted **across the whole package**:

    * the sole module-scope definition carrying the frozen block; and
    * the exact public re-export ``validate_ledger = _core.validate_ledger``,
      once in the package, in a module that does not define the function and
      whose ``_core`` is demonstrably this package's own module.

    Every other enumerated binding is refused, wherever it sits; no production
    module may reach its namespace as data; and no attribute of either pinned
    name may be read or written, because ``_refuse.__code__ = _tame.__code__``
    replaces the helper's executable code while leaving every name, signature
    and source body untouched.

    This pins the enumerated DIRECT STATIC shapes and nothing further. It proves
    no runtime property, it is not exhaustive -- see
    ``namespace_reach_violations`` for the residual it cannot close -- and the
    separate human audit remains required.
    """
    import ast

    trees = {}
    definitions = []
    reexports = []
    census = []
    for name, source in sorted(sources.items()):
        tree = ast.parse(source)
        trees[name] = tree
        module_definitions = [
            statement
            for statement in tree.body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == "validate_ledger"
        ]
        definitions.extend((name, node) for node in module_definitions)
        if not module_definitions:
            reexports.extend(
                (name, statement)
                for statement in tree.body
                if isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and _is_core_reexport(statement)
            )
        for kind, node in binding_census(tree, "validate_ledger"):
            census.append((name, kind, node))

    if len(definitions) != 1:
        return None, (
            "expected exactly one module-scope validate_ledger definition, "
            f"found {len(definitions)}"
        )
    defining_module, function = definitions[0]

    # ONE re-export in the package, not one per module. Permitting it per module
    # made "exactly two nodes are permitted" false the moment a second surface
    # existed, and no fixture covered the cross-module case.
    if len(reexports) > 1:
        return None, (
            f"validate_ledger is re-exported {len(reexports)} times; "
            "exactly one re-export is permitted"
        )
    permitted = [function]
    if reexports:
        reexport_module, reexport = reexports[0]
        if not _core_is_the_package(trees[reexport_module]):
            return None, (
                f"the re-exporting module {reexport_module} binds `_core` to "
                "something that is not the package's own module"
            )
        permitted.append(reexport)

    # Identity, not `id()`: the trees stay alive in `trees`, but comparing the
    # nodes themselves removes the question entirely.
    stray = sorted(
        {
            f"{name}:{kind}"
            for name, kind, node in census
            if not any(node is allowed for allowed in permitted)
        }
    )
    if stray:
        return None, f"validate_ledger carries other bindings: {stray}"

    reach = sorted(
        {
            f"{name}:{kind}:{detail}"
            for name, tree in sorted(trees.items())
            for kind, detail in namespace_reach_violations(tree)
        }
    )
    if reach:
        return None, f"a production module reaches its namespace as data: {reach}"

    defect = frozen_refusal_helper(sources, defining_module)
    if defect:
        return None, defect

    # A decorator can wrap the function, or replace it outright, leaving the
    # frozen block below it dead -- the same defect shape as a dead nested
    # `if`. None is permitted.
    if function.decorator_list:
        return None, "validate_ledger carries a decorator"
    if getattr(function, "type_params", ()):
        return None, "validate_ledger carries type parameters"
    if isinstance(function, ast.AsyncFunctionDef):
        return None, "validate_ledger is async"
    arguments = function.args
    if (
        len(arguments.args) != 1
        or arguments.posonlyargs
        or arguments.kwonlyargs
        or arguments.vararg
        or arguments.kwarg
        or arguments.defaults
        or arguments.kw_defaults
    ):
        return None, "validate_ledger does not take exactly one plain parameter"
    parameter = arguments.args[0].arg

    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return None, "validate_ledger has no executable statement"

    expected = ast.parse(FROZEN_ROOT_BLOCK.format(parameter=parameter)).body[0]
    if ast.dump(body[0]) != ast.dump(expected):
        return None, "the first executable statement is not the frozen block"
    return parameter, None


#: The one conforming refusal helper, reused by every fixture that is not
#: itself about ``_refuse``, so each negative below is refused for its OWN
#: reason rather than for a helper defect it never meant to carry.
CONFORMING_REFUSE = (
    "def _refuse(token, path=()):\n"
    "    raise LedgerError(token, path) from None\n"
)

#: The one conforming definition, likewise.
CONFORMING_DEFINITION = (
    "def validate_ledger(payload):\n"
    "    if type(payload) is not dict:\n"
    "        if issubclass(type(payload), dict):\n"
    "            _refuse('type-not-exact')\n"
    "        _refuse('root-not-object')\n"
)

#: A whole conforming core module: the helper and the definition together.
CONFORMING_CORE = CONFORMING_REFUSE + "\n\n" + CONFORMING_DEFINITION


def _with_refuse(body):
    """A fixture module carrying the conforming helper, then ``body``."""
    return CONFORMING_REFUSE + "\n\n" + body


def _module(body):
    """A single-module fixture, named as the core."""
    return {"__init__.py": body}


#: The frozen self-binding a surface must carry before its re-export means
#: anything, and the re-export itself.
CORE_SELF_BINDING = (
    "import sys\n"
    "\n"
    "_core = sys.modules['" + sup.SYS_MODULES_SELF_BINDING_KEY + "']\n"
)
CORE_REEXPORT = "validate_ledger = _core.validate_ledger\n"


#: Jack's reproduced counterexample heads this list. The first several were
#: ACCEPTED by the Correction 4 expression matcher; the later ones close routes
#: found while correcting it, and some of those the older matcher would itself
#: have refused. The claim is deliberately not "every one of these".
FROZEN_BLOCK_NEGATIVE_FIXTURES = (
    (
        "a dead compliant nested if, with a real classifier after it",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            pass\n"
            "        lineage = type.mro(type(payload))\n"
            "        return (\n"
            "            'type-not-exact'\n"
            "            if any(base is dict for base in lineage)\n"
            "            else 'root-not-object'\n"
            "        )\n"
            "    return 'accepted'\n"
        ),
    ),
    (
        "an extra decision statement inside the outer body",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "a pass in the nested body",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            pass\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "an else on the outer if",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "    else:\n"
            "        return 'accepted'\n"
        ),
    ),
    (
        "an else on the nested if",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        else:\n"
            "            _refuse('root-not-object')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "a classifier running before the block",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    verdict = any(b is dict for b in type.mro(type(payload)))\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "two validate_ledger definitions",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "\n"
            "\n"
            "def validate_ledger(payload):\n"
            "    return 'accepted'\n"
        ),
    ),
    (
        "the wrong refusal token in the nested body",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('root-not-object')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "isinstance in place of the frozen subtype decision",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if isinstance(payload, dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "a __bases__ read in place of the frozen subtype decision",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if dict in type(payload).__bases__:\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "a conforming def nested in a factory, with the name bound elsewhere",
        _with_refuse(
            "def _factory():\n"
            "    def validate_ledger(payload):\n"
            "        if type(payload) is not dict:\n"
            "            if issubclass(type(payload), dict):\n"
            "                _refuse('type-not-exact')\n"
            "            _refuse('root-not-object')\n"
            "    return validate_ledger\n"
            "\n"
            "\n"
            "validate_ledger = _hostile\n"
        ),
    ),
    (
        "a re-export in the module that defines it",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "\n"
            "\n"
            "validate_ledger = _core.validate_ledger\n"
        ),
    ),
    (
        "a re-export from something other than _core",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "\n"
            "\n"
            "validate_ledger = _elsewhere.validate_ledger\n"
        ),
    ),
    (
        "a conforming def immediately rebound at module scope",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "\n"
            "\n"
            "validate_ledger = _real\n"
        ),
    ),
    (
        "a conforming def rebound to a lambda",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
            "\n"
            "\n"
            "validate_ledger = lambda payload: payload\n"
        ),
    ),
    (
        "a conforming def behind a module-scope condition",
        _with_refuse(
            "if _FLAG:\n"
            "    def validate_ledger(payload):\n"
            "        if type(payload) is not dict:\n"
            "            if issubclass(type(payload), dict):\n"
            "                _refuse('type-not-exact')\n"
            "            _refuse('root-not-object')\n"
        ),
    ),
    (
        "a `_refuse` that returns instead of raising",
        "def _refuse(token, path=()):\n"
        "    return token\n"
        "\n"
        "\n"
        "def validate_ledger(payload):\n"
        "    if type(payload) is not dict:\n"
        "        if issubclass(type(payload), dict):\n"
        "            _refuse('type-not-exact')\n"
        "        _refuse('root-not-object')\n"
        "    return any(b is dict for b in type.mro(type(payload)))\n",
    ),
    (
        "a decorator that could wrap or replace the function",
        _with_refuse(
            "@wrapper\n"
            "def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "an async definition",
        _with_refuse(
            "async def validate_ledger(payload):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "a second parameter with a default",
        _with_refuse(
            "def validate_ledger(payload, mode=1):\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
    (
        "a nested definition shadowing the real one",
        _with_refuse(
            "def validate_ledger(payload):\n"
            "    def validate_ledger(other):\n"
            "        return 'accepted'\n"
            "    if type(payload) is not dict:\n"
            "        if issubclass(type(payload), dict):\n"
            "            _refuse('type-not-exact')\n"
            "        _refuse('root-not-object')\n"
        ),
    ),
)

#: Correction 6. Each entry carries the fragment of the defect it must be
#: refused FOR, so a fixture cannot quietly begin passing for the wrong reason
#: -- the failure mode that let the Correction 5 negatives look conclusive
#: while three ordinary shapes walked through.
REFUSAL_AND_BINDING_FIXTURES = (
    # -- Jack's three reproduced bypasses of the Correction 5 matcher --------
    (
        "JACK 1: a dead `raise` in _refuse, which then returns",
        _module(
            "def _refuse(token, path=()):\n"
            "    if False:\n"
            "        raise LedgerError(token, path) from None\n"
            "    return token\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "executable statements",
    ),
    (
        "JACK 2: a conforming def, then `if True: validate_ledger = _hostile`",
        _module(CONFORMING_CORE + "\n\nif True:\n    validate_ledger = _hostile\n"),
        "assignment",
    ),
    (
        "JACK 3: a conforming def, then `class validate_ledger: pass`",
        _module(CONFORMING_CORE + "\n\nclass validate_ledger:\n    pass\n"),
        "class-definition",
    ),
    # -- the refusal helper, pinned as an executable statement ---------------
    (
        "a _refuse whose only statement is a conditional raise",
        _module(
            "def _refuse(token, path=()):\n"
            "    if token:\n"
            "        raise LedgerError(token, path) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "does not raise exactly",
    ),
    (
        "a _refuse that returns instead of raising",
        _module(
            "def _refuse(token, path=()):\n"
            "    return token\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "does not raise exactly",
    ),
    (
        "a _refuse that returns before raising",
        _module(
            "def _refuse(token, path=()):\n"
            "    return token\n"
            "    raise LedgerError(token, path) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "executable statements",
    ),
    (
        "a _refuse carrying an extra executable statement",
        _module(
            "def _refuse(token, path=()):\n"
            "    _log(token)\n"
            "    raise LedgerError(token, path) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "executable statements",
    ),
    (
        "a _refuse raising something other than the frozen exception",
        _module(
            "def _refuse(token, path=()):\n"
            "    raise ValueError(token) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "does not raise exactly",
    ),
    (
        "a _refuse that drops `from None`",
        _module(
            "def _refuse(token, path=()):\n"
            "    raise LedgerError(token, path)\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "does not raise exactly",
    ),
    (
        "a _refuse that drops the path from the raised error",
        _module(
            "def _refuse(token, path=()):\n"
            "    raise LedgerError(token) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "does not raise exactly",
    ),
    (
        "a decorated _refuse",
        _module(
            "@wrapper\n"
            "def _refuse(token, path=()):\n"
            "    raise LedgerError(token, path) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "carries a decorator",
    ),
    (
        "a conditional _refuse",
        _module(
            "if _FLAG:\n"
            "    def _refuse(token, path=()):\n"
            "        raise LedgerError(token, path) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "found 0",
    ),
    (
        "an async _refuse",
        _module(
            "async def _refuse(token, path=()):\n"
            "    raise LedgerError(token, path) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "found 0",
    ),
    (
        "a class-based _refuse",
        _module("class _refuse:\n    pass\n\n\n" + CONFORMING_DEFINITION),
        "found 0",
    ),
    (
        "a nested _refuse beside the module-scope one",
        _module(
            CONFORMING_CORE
            + "\n\ndef _factory():\n"
            "    def _refuse(token, path=()):\n"
            "        return token\n"
            "    return _refuse\n"
        ),
        "carries other bindings",
    ),
    (
        "a duplicated _refuse",
        _module(CONFORMING_CORE + "\n\n" + CONFORMING_REFUSE),
        "found 2",
    ),
    (
        "an imported _refuse",
        _module(CONFORMING_CORE + "\n\nfrom _elsewhere import _refuse\n"),
        "carries other bindings",
    ),
    (
        "an aliased import bound to _refuse",
        _module(CONFORMING_CORE + "\n\nimport _elsewhere as _refuse\n"),
        "carries other bindings",
    ),
    (
        "a rebound _refuse",
        _module(CONFORMING_CORE + "\n\n_refuse = _noop\n"),
        "carries other bindings",
    ),
    (
        "a _refuse rebound beneath a module-scope condition",
        _module(CONFORMING_CORE + "\n\nif True:\n    _refuse = _noop\n"),
        "carries other bindings",
    ),
    (
        "a _refuse with the wrong signature",
        _module(
            "def _refuse(token):\n"
            "    raise LedgerError(token) from None\n"
            "\n"
            "\n" + CONFORMING_DEFINITION
        ),
        "does not take exactly",
    ),
    (
        "a _refuse defined in a module other than the defining one",
        {"__init__.py": CONFORMING_DEFINITION, "schema.py": CONFORMING_REFUSE},
        "not in __init__.py",
    ),
    # -- the exported binding, decided by census -----------------------------
    (
        "an assignment beneath a module-scope loop",
        _module(CONFORMING_CORE + "\n\nfor _ in (1,):\n    validate_ledger = _h\n"),
        "assignment",
    ),
    (
        "an assignment beneath a module-scope try",
        _module(
            CONFORMING_CORE
            + "\n\ntry:\n    validate_ledger = _h\nexcept Exception:\n    pass\n"
        ),
        "assignment",
    ),
    (
        "an assignment beneath a module-scope with",
        _module(CONFORMING_CORE + "\n\nwith _ctx():\n    validate_ledger = _h\n"),
        "assignment",
    ),
    (
        "an assignment beneath a module-scope match",
        _module(
            CONFORMING_CORE
            + "\n\nmatch _mode:\n    case 1:\n        validate_ledger = _h\n"
        ),
        "assignment",
    ),
    (
        "a nested definition of the name",
        _module(
            CONFORMING_CORE
            + "\n\ndef _factory():\n"
            "    def validate_ledger(other):\n"
            "        return other\n"
            "    return validate_ledger\n"
        ),
        "definition",
    ),
    (
        "a __code__ swap on the refusal helper (reviewer A6)",
        _module(
            CONFORMING_CORE
            + "\n\ndef _tame(token, path=()):\n    return None\n"
            "\n\n_refuse.__code__ = _tame.__code__\n"
        ),
        "attribute-access",
    ),
    (
        "a __code__ swap on validate_ledger itself (reviewer B6)",
        _module(
            CONFORMING_CORE
            + "\n\ndef _p(payload):\n    return payload\n"
            "\n\nvalidate_ledger.__code__ = _p.__code__\n"
        ),
        "attribute-access",
    ),
    (
        "a write through the helper's __globals__ (reviewer A6)",
        _module(CONFORMING_CORE + "\n\n_refuse.__globals__['_refuse'] = _tame\n"),
        "module-namespace-reach",
    ),
    (
        "a write through ANOTHER function's __globals__ (critic C7-A)",
        _module(
            CONFORMING_CORE
            + "\n\ndef _leaky(token, path=()):\n"
            "    raise LedgerError(token, path) from None\n"
            "\n\n_leaky.__globals__['_refuse'] = _leaky\n"
        ),
        "module-namespace-reach",
    ),
    (
        "a type parameter shadowing the exception class (critic C7-A)",
        _module(
            "def _refuse[LedgerError](token, path=()):\n"
            "    raise LedgerError(token, path) from None\n"
            "\n\n" + CONFORMING_DEFINITION
        ),
        "type parameters",
    ),
    (
        "a star import that may bind anything (reviewer B6)",
        _module(CONFORMING_CORE + "\n\nfrom _hostile import *\n"),
        "star-import",
    ),
    (
        "a module-attribute write on the core (reviewer C6)",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": CORE_SELF_BINDING
            + CORE_REEXPORT
            + "_core.validate_ledger = _h\n",
        },
        "module-attribute-write",
    ),
    (
        "globals() bound to a name first (reviewer A6)",
        _module(CONFORMING_CORE + "\n\n_g = globals()\n_g['_refuse'] = _tame\n"),
        "namespace-builtin-call",
    ),
    (
        "a computed key into globals() (reviewer A6)",
        _module(CONFORMING_CORE + "\n\nglobals()['_ref' + 'use'] = _tame\n"),
        "namespace-builtin-call",
    ),
    (
        "globals().__setitem__ (reviewer A6)",
        _module(
            CONFORMING_CORE + "\n\nglobals().__setitem__('_refuse', _tame)\n"
        ),
        "namespace-builtin-call",
    ),
    (
        "globals().update (reviewers A6 and C6)",
        _module(CONFORMING_CORE + "\n\nglobals().update(_refuse=_tame)\n"),
        "namespace-builtin-call",
    ),
    (
        "setattr on the core module (reviewer C6)",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": CORE_SELF_BINDING
            + CORE_REEXPORT
            + "setattr(_core, 'validate_ledger', _h)\n",
        },
        "namespace-builtin-call",
    ),
    (
        "exec of generated source",
        _module(CONFORMING_CORE + "\n\nexec(_source)\n"),
        "namespace-builtin-call",
    ),
    (
        "a write through sys.modules[__name__].__dict__ (reviewer C6)",
        _module(
            CONFORMING_CORE
            + "\n\nimport sys\n"
            "sys.modules[__name__].__dict__['validate_ledger'] = _h\n"
        ),
        "module-namespace-reach",
    ),
    (
        "a re-export whose _core is an aliased import (reviewer B6)",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": "import _hostile as _core\n" + CORE_REEXPORT,
        },
        "not the package's own module",
    ),
    (
        "a re-export whose _core is a plain assignment (reviewer C6)",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": "_core = _hostile\n" + CORE_REEXPORT,
        },
        "not the package's own module",
    ),
    (
        "a re-export whose _core is rebound after the self-binding",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": CORE_SELF_BINDING + "_core = _hostile\n" + CORE_REEXPORT,
        },
        "not the package's own module",
    ),
    (
        "two surfaces each re-exporting once (reviewer C6)",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": CORE_SELF_BINDING + CORE_REEXPORT,
            "validate.py": CORE_SELF_BINDING + CORE_REEXPORT,
        },
        "exactly one re-export is permitted",
    ),
    (
        "a PEP 695 type alias of the name",
        _module(CONFORMING_CORE + "\n\ntype validate_ledger = int\n"),
        "type-alias",
    ),
    (
        "a deletion of the name",
        _module(CONFORMING_CORE + "\n\ndel validate_ledger\n"),
        "deletion",
    ),
    (
        "an annotated assignment",
        _module(CONFORMING_CORE + "\n\nvalidate_ledger: object = _h\n"),
        "annotated-assignment",
    ),
    (
        "an augmented assignment",
        _module(CONFORMING_CORE + "\n\nvalidate_ledger += _h\n"),
        "augmented-assignment",
    ),
    (
        "a loop target",
        _module(CONFORMING_CORE + "\n\nfor validate_ledger in (_h,):\n    pass\n"),
        "loop-target",
    ),
    (
        "a comprehension target",
        _module(
            CONFORMING_CORE + "\n\n_all = [validate_ledger for validate_ledger in ()]\n"
        ),
        "comprehension-target",
    ),
    (
        "a context-manager target",
        _module(CONFORMING_CORE + "\n\nwith _ctx() as validate_ledger:\n    pass\n"),
        "context-manager-target",
    ),
    (
        "an exception target",
        _module(
            CONFORMING_CORE
            + "\n\ntry:\n    pass\nexcept Exception as validate_ledger:\n    pass\n"
        ),
        "exception-target",
    ),
    (
        "a match capture pattern",
        _module(
            CONFORMING_CORE
            + "\n\nmatch _mode:\n    case validate_ledger:\n        pass\n"
        ),
        "match-capture",
    ),
    (
        "a match star pattern",
        _module(
            CONFORMING_CORE
            + "\n\nmatch [1]:\n    case [*validate_ledger]:\n        pass\n"
        ),
        "match-star",
    ),
    (
        "a match mapping rest pattern",
        _module(
            CONFORMING_CORE + "\n\nmatch {}:\n    case {**validate_ledger}:\n        pass\n"
        ),
        "match-mapping-rest",
    ),
    (
        "a named-expression target",
        _module(CONFORMING_CORE + "\n\n_seen = (validate_ledger := _h)\n"),
        "named-expression",
    ),
    (
        "a plain import of the name",
        _module(CONFORMING_CORE + "\n\nfrom _elsewhere import validate_ledger\n"),
        "import",
    ),
    (
        "an aliased import bound to the name",
        _module(CONFORMING_CORE + "\n\nimport _elsewhere as validate_ledger\n"),
        "import",
    ),
    (
        "a parameter shadowing the name",
        _module(
            CONFORMING_CORE
            + "\n\ndef _helper(validate_ledger):\n    return validate_ledger\n"
        ),
        "parameter",
    ),
    (
        "a globals() write",
        _module(CONFORMING_CORE + "\n\nglobals()['validate_ledger'] = _h\n"),
        "namespace-mapping-write",
    ),
    (
        "a vars() write",
        _module(CONFORMING_CORE + "\n\nvars()['validate_ledger'] = _h\n"),
        "namespace-mapping-write",
    ),
    (
        "a locals() write",
        _module(CONFORMING_CORE + "\n\nlocals()['validate_ledger'] = _h\n"),
        "namespace-mapping-write",
    ),
    (
        "a global declaration in a function that rebinds the name",
        _module(
            CONFORMING_CORE
            + "\n\ndef _swap():\n    global validate_ledger\n"
            "    validate_ledger = _h\n"
        ),
        "global-or-nonlocal",
    ),
    # -- the one permitted re-export, and everything shaped like it ----------
    (
        "two re-exports in one surface",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": CORE_SELF_BINDING + CORE_REEXPORT + CORE_REEXPORT,
        },
        "exactly one re-export is permitted",
    ),
    (
        "a surface re-exporting from something other than _core",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": "validate_ledger = _elsewhere.validate_ledger\n",
        },
        "assignment",
    ),
    (
        "a surface re-exporting a different attribute of _core",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": "validate_ledger = _core.something_else\n",
        },
        "assignment",
    ),
    (
        "a re-export in the defining module",
        _module(CONFORMING_CORE + "\n\nvalidate_ledger = _core.validate_ledger\n"),
        "assignment",
    ),
    (
        "a re-export nested beneath a condition in a surface",
        {
            "__init__.py": CONFORMING_CORE,
            "schema.py": "if True:\n    validate_ledger = _core.validate_ledger\n",
        },
        "assignment",
    ),
)

#: The two-module shape the production package actually has: the core defines
#: the function, one surface binds `_core` to this package and re-exports it.
#: Proved on a fixture before the matcher is pointed at anything real.
FROZEN_BINDING_POSITIVE_FIXTURE = {
    "__init__.py": CONFORMING_CORE,
    "schema.py": CORE_SELF_BINDING + CORE_REEXPORT,
}

FROZEN_BLOCK_POSITIVE_FIXTURE = (
    "def _refuse(token, path=()):\n"
    "    raise LedgerError(token, path) from None\n"
    "\n"
    "\n"
    "def validate_ledger(payload):\n"
    '    """A docstring is permitted before the block."""\n'
    "    if type(payload) is not dict:\n"
    "        if issubclass(type(payload), dict):\n"
    "            _refuse('type-not-exact')\n"
    "        _refuse('root-not-object')\n"
    "    return payload\n"
)


def test_gv7_s_005_the_root_must_be_an_exact_builtin_dict():
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    # The mechanism itself, pinned by source shape: one module-scope,
    # undecorated `validate_ledger`, never rebound, whose first executable
    # statement is the frozen block, with a `_refuse` that really raises.
    # The matcher discriminates, proved on self-contained fixtures before it is
    # pointed at anything. The first fixture is the shape that defeated the
    # Correction 4 expression matcher: a dead compliant-looking nested `if`
    # with the real classifier after it.
    parameter, defect = frozen_root_decision(
        {"schema.py": FROZEN_BLOCK_POSITIVE_FIXTURE}
    )
    assert defect is None, defect
    assert parameter == "payload", parameter
    for label, fixture in FROZEN_BLOCK_NEGATIVE_FIXTURES:
        found, found_defect = frozen_root_decision({"schema.py": fixture})
        assert found is None, f"{label}: accepted"
        assert found_defect, label

    # The two-module production shape -- a core that defines the function and a
    # surface that re-exports it -- is ACCEPTED, proved on a fixture before the
    # matcher is pointed at anything real.
    parameter, defect = frozen_root_decision(FROZEN_BINDING_POSITIVE_FIXTURE)
    assert defect is None, defect
    assert parameter == "payload", parameter

    # Jack's three reproduced bypasses, and every route found while closing
    # them. Each names the defect it must be refused FOR, so a fixture cannot
    # quietly begin passing for some other reason -- which is how the
    # Correction 5 negatives went on looking conclusive while three ordinary
    # shapes walked through.
    for label, fixture_sources, fragment in REFUSAL_AND_BINDING_FIXTURES:
        found, found_defect = frozen_root_decision(fixture_sources)
        assert found is None, f"{label}: accepted"
        assert fragment in found_defect, (label, found_defect)

    # The executable block itself, in the production source.
    parameter, defect = frozen_root_decision(
        {
            name: sup.require_file(sup.LAB_DIR / name, name)
            for name in sup.PRODUCTION_MODULES
        }
    )
    assert defect is None, defect
    assert parameter, parameter
    hostile = HookedDict(ledger)
    hostile.hooks.clear()
    refuse(schema, hostile, "type-not-exact")
    assert not hostile.hooks, hostile.hooks
    for wrong in ([], (), "", 0, None):
        refuse(schema, wrong, "root-not-object")

    # A hostile METACLASS. Deciding the root's type by reading an attribute of
    # its class -- ``__mro__``, ``__bases__``, ``__class__`` -- hands control
    # to the metaclass at the exact moment the validator is deciding whether
    # to trust the object. The metaclass may raise, and the raw exception then
    # escapes the closed refusal vocabulary; or it may return a forged answer,
    # and a value that is not a mapping is refused as a mapping subclass with
    # the wrong token. Neither is admissible. The exact type identity alone
    # decides, so the hook must never be reached at all.
    for hostile_root in (HostileRaisingRoot(), HostileForgingRoot()):
        # (a) nothing raw escapes the closed vocabulary.
        MetaclassHookLog.hits.clear()
        try:
            schema.validate_ledger(hostile_root)
        except schema.LedgerError:
            escaped = None
        except BaseException as error:  # noqa: BLE001 - the probe records a class
            escaped = type(error).__name__
        else:
            escaped = "no refusal at all"
        assert escaped is None, f"a raw {escaped} escaped the refusal vocabulary"

        # (b) the refusal is exactly root-not-object, with the usual hygiene.
        MetaclassHookLog.hits.clear()
        refuse(schema, hostile_root, "root-not-object")

        # (c) the metaclass hook was never invoked, on either attempt.
        assert not MetaclassHookLog.hits, MetaclassHookLog.hits

    # Three further routes that a bare ``type.__getattribute__`` does not
    # close. It bypasses an overridden ``__getattribute__`` and nothing else:
    # it still finds and calls a ``__mro__`` property, it still returns a
    # plain shadowing ``__mro__`` attribute, and it does nothing about the
    # ``==`` comparison that ``dict in <mro>`` performs afterwards.
    metaclass_roots = (
        ("raising __mro__ property", RaisingMroPropertyRoot(), "root-not-object"),
        ("forging __mro__ property", ForgingMroPropertyRoot(), "root-not-object"),
        ("plain __mro__ shadow", ShadowMroRoot(), "root-not-object"),
        ("metaclass __eq__, non-dict", EqHostileRoot(), "root-not-object"),
        ("metaclass __eq__, dict subclass", EqHostileDictSubclass(), "type-not-exact"),
        # Correction 4. None of these was covered before, and an
        # implementation reading __bases__ or __class__ passed the whole
        # control without them.
        ("metaclass __bases__ raising", BasesRaisingRoot(), "root-not-object"),
        ("metaclass __bases__ forging", BasesForgingRoot(), "root-not-object"),
        ("object __class__ property raising", ClassPropertyRaisingRoot(),
         "root-not-object"),
        ("object __class__ property forging", ClassPropertyForgingRoot(),
         "root-not-object"),
        # Correction 4, second round. Each of these satisfied every fixture
        # above, so each is a route the earlier set did not name.
        ("metaclass __bases__ property raising", BasesPropertyRaisingRoot(),
         "root-not-object"),
        ("metaclass __bases__ property forging", BasesPropertyForgingRoot(),
         "root-not-object"),
        ("plain metaclass __bases__ shadow", BasesShadowRoot(), "root-not-object"),
        ("metaclass mro() raising", MroMethodRaisingRoot(), "root-not-object"),
        ("metaclass mro() forging", MroMethodForgingRoot(), "root-not-object"),
        ("duck-typed decoy with keys", DuckTypedDecoy(), "root-not-object"),
        ("indirect dict subclass", GrandchildDictSubclass(), "type-not-exact"),
    )
    MroMethodRaisingMeta.armed = True
    MroMethodForgingMeta.armed = True
    for label, hostile_root, expected in metaclass_roots:
        # (a) nothing raw escapes the closed vocabulary.
        MetaclassHookLog.hits.clear()
        try:
            schema.validate_ledger(hostile_root)
        except schema.LedgerError:
            escaped = None
        except BaseException as error:  # noqa: BLE001 - the probe records a class
            escaped = type(error).__name__
        else:
            escaped = "no refusal at all"
        assert escaped is None, f"{label}: a raw {escaped} escaped"

        # (b) the exact refusal for this root, with the usual hygiene. A
        #     genuine dict subclass is `type-not-exact`; nothing else is.
        #     The log is NOT cleared here: clearing between the probes would
        #     discard any hook that fired during (a), so an implementation
        #     reading a supplied attribute once per type would pass unseen.
        first_pass_hits = list(MetaclassHookLog.hits)
        refuse(schema, hostile_root, expected)
        MetaclassHookLog.hits.extend(first_pass_hits)

        # (c) no supplied hook ran on either attempt. The plain shadow has no
        #     hook to run at all -- its fault is the forged answer, not an
        #     invocation -- and this still holds for it.
        assert not MetaclassHookLog.hits, (label, MetaclassHookLog.hits)

    # Every hook fixture is live when invoked directly, so none is inert.
    MetaclassHookLog.hits.clear()
    with pytest.raises(RuntimeError):
        dict in type(HostileRaisingRoot()).__mro__  # noqa: B015 - the read is the probe
    assert MetaclassHookLog.hits == [("raising", "__mro__")]

    MetaclassHookLog.hits.clear()
    assert dict in type(HostileForgingRoot()).__mro__, "the forged MRO must lie"
    assert MetaclassHookLog.hits == [("forging", "__mro__")]

    MetaclassHookLog.hits.clear()
    with pytest.raises(RuntimeError):
        type.__getattribute__(type(RaisingMroPropertyRoot()), "__mro__")
    assert MetaclassHookLog.hits == [("mro-property-raising", "__mro__")]

    MetaclassHookLog.hits.clear()
    forged = type.__getattribute__(type(ForgingMroPropertyRoot()), "__mro__")
    assert forged == (dict,), "the property must forge an MRO containing dict"
    assert MetaclassHookLog.hits == [("mro-property-forging", "__mro__")]

    # The plain shadow is live without any hook: no entry is recorded, and the
    # forged tuple is returned by the very primitive that was said to be safe.
    MetaclassHookLog.hits.clear()
    shadowed = type.__getattribute__(type(ShadowMroRoot()), "__mro__")
    assert shadowed == (dict,), "the plain shadow must return a forged MRO"
    assert MetaclassHookLog.hits == []

    for live_root in (EqHostileRoot(), EqHostileDictSubclass()):
        MetaclassHookLog.hits.clear()
        real_mro = type.__getattribute__(type(live_root), "__mro__")
        with pytest.raises(RuntimeError):
            dict in real_mro  # noqa: B015 - the comparison is the probe
        assert MetaclassHookLog.hits == [("metaclass-eq", "__eq__")]

    # The four Correction 4 fixtures are live too, each by its own route.
    MetaclassHookLog.hits.clear()
    with pytest.raises(RuntimeError):
        type(BasesRaisingRoot()).__bases__  # noqa: B018 - the read is the probe
    assert MetaclassHookLog.hits == [("bases-raising", "__bases__")]

    MetaclassHookLog.hits.clear()
    assert type(BasesForgingRoot()).__bases__ == (dict,), "the forged bases must lie"
    assert MetaclassHookLog.hits == [("bases-forging", "__bases__")]

    MetaclassHookLog.hits.clear()
    with pytest.raises(RuntimeError):
        ClassPropertyRaisingRoot().__class__  # noqa: B018 - the read is the probe
    assert MetaclassHookLog.hits == [("class-property-raising", "__class__")]

    MetaclassHookLog.hits.clear()
    assert ClassPropertyForgingRoot().__class__ is dict, "the forged class must lie"
    assert MetaclassHookLog.hits == [("class-property-forging", "__class__")]

    # And the frozen mechanism decides every one of them, invoking nothing.
    # This is what pins the mechanism: a `__bases__`-reading implementation
    # satisfies every fixture ABOVE, and only this table plus the two
    # `__bases__` fixtures make the difference visible.
    MetaclassHookLog.hits.clear()
    for _label, hostile_root, expected in metaclass_roots:
        subtype = issubclass(type(hostile_root), dict)
        exact = type(hostile_root) is dict
        decided = (
            "type-not-exact" if (subtype and not exact) else "root-not-object"
        )
        assert decided == expected, (_label, decided, expected)
    assert issubclass(type({}), dict) and type({}) is dict, "exact dict accepted"
    assert not MetaclassHookLog.hits, MetaclassHookLog.hits


def test_gv7_s_006_hostile_subclasses_are_refused_before_any_hook_runs():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    hostile_value = HookedStr(sup.SCHEMA_ID)
    hostile_value.hooks.clear()
    payload = dict(ledger)
    payload["schema"] = hostile_value
    refuse(schema, payload, "type-not-exact")
    assert not hostile_value.hooks, hostile_value.hooks

    hostile_list = HookedList(ledger["sources"])
    hostile_list.hooks.clear()
    payload = dict(ledger)
    payload["sources"] = hostile_list
    refuse(schema, payload, "type-not-exact")
    assert not hostile_list.hooks, hostile_list.hooks


def test_gv7_s_007_bool_and_int_are_mutually_hostile():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["batches"][0]["batch_ordinal"] = True
    refuse(schema, payload, "type-not-exact")
    payload = json.loads(json.dumps(ledger))
    payload["batches"][0]["batch_ordinal"] = 1.0
    refuse(schema, payload, "float-refused")
    payload = json.loads(json.dumps(ledger))
    payload["batches"][0]["batch_ordinal"] = sup.EXPECTED_BATCHES + 1
    refuse(schema, payload, "int-out-of-range")


def test_gv7_s_008_a_foreign_mapping_key_is_refused_without_being_touched():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = dict(ledger)
    payload[HookedStr(sup.MARKER_KEY)] = "synthetic"
    error = refuse(schema, payload, "key-not-exact-str")
    assert sup.MARKER_KEY not in str(error)


def test_gv7_s_009_every_identifier_is_globally_unique_and_well_formed():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    fields = {
        "batches": "batch_id",
        "sources": "source_id",
        "claims": "claim_id",
        "relationships": "relationship_id",
        "unresolved": "unresolved_id",
        "artifacts": "artifact_id",
        "corrections": "correction_id",
    }
    seen = []
    for collection, field in fields.items():
        for record in sup.collection_of(ledger, collection):
            value = record[field]
            assert sup.ID_RE.match(value), value
            seen.append(value)
    assert len(seen) == len(set(seen)), "identifier collision across collections"

    payload = json.loads(json.dumps(ledger))
    payload["sources"][1]["source_id"] = payload["sources"][0]["source_id"]
    refuse(schema, payload, "identifier-duplicate")

    payload = json.loads(json.dumps(ledger))
    payload["sources"][0]["source_id"] = "GV7-SRC-001"
    refuse(schema, payload, "identifier-malformed")


def test_gv7_s_010_every_reference_resolves_to_an_existing_record_of_its_kind():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    source_ids = set(sup.identifiers(ledger["sources"], "source_id"))
    batch_ids = set(sup.identifiers(ledger["batches"], "batch_id"))
    for claim in ledger["claims"]:
        assert claim["source_ref"] in source_ids, claim["claim_id"]
        assert claim["batch_ref"] in batch_ids, claim["claim_id"]
    for source in ledger["sources"]:
        assert source["batch_ref"] in batch_ids, source["source_id"]

    payload = json.loads(json.dumps(ledger))
    payload["claims"][0]["source_ref"] = "GV7-SRC-9999"
    refuse(schema, payload, "reference-not-found")

    payload = json.loads(json.dumps(ledger))
    payload["claims"][0]["source_ref"] = payload["batches"][0]["batch_id"]
    refuse(schema, payload, "reference-wrong-kind")


def test_gv7_s_011_a_self_relationship_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["relationships"][0]["right_ref"] = payload["relationships"][0]["left_ref"]
    refuse(schema, payload, "relationship-self")


def test_gv7_s_012_duplicate_set_members_and_duplicate_relationships_are_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    limitations = payload["sources"][0]["limitations"]
    payload["sources"][0]["limitations"] = [limitations[0], limitations[0]]
    refuse(schema, payload, "list-duplicate-item")

    payload = json.loads(json.dumps(ledger))
    first = payload["relationships"][0]
    clone = dict(first)
    clone["relationship_id"] = "GV7-REL-9999"
    payload["relationships"].append(clone)
    refuse(schema, payload, "relationship-duplicate")


def test_gv7_s_013_a_nested_list_longer_than_list_max_is_refused():
    """``LIST_MAX`` is a NESTED bound. ``GV7-S-047`` proves it is not a root one."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["sources"][0]["limitations"] = [
        f"synthetic limitation {index}" for index in range(sup.LIST_MAX + 1)
    ]
    refuse(schema, payload, "list-length-invalid")


def test_gv7_s_014_validation_is_pure_and_never_mutates_its_input():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    before = json.dumps(ledger, sort_keys=True)
    schema.validate_ledger(ledger)
    assert json.dumps(ledger, sort_keys=True) == before


def test_gv7_s_015_the_committed_bytes_are_unchanged_by_validation():
    validate = sup.require_validate()
    before = sup.LEDGER_PATH.read_bytes()
    validate.validate_ledger_file(sup.LEDGER_PATH)
    assert sup.LEDGER_PATH.read_bytes() == before


def test_gv7_s_016_duplicate_json_keys_are_rejected(tmp_path):
    validate = sup.require_validate()
    path = tmp_path / "ledger.json"
    path.write_text(
        '{"schema": "source-record-v3", "schema": "source-record-v3"}',
        encoding="utf-8",
    )
    with pytest.raises(validate.LedgerInputError) as excinfo:
        validate.validate_ledger_file(path)
    assert excinfo.value.token == "json-duplicate-key"


def test_gv7_s_017_a_parse_step_value_error_is_refused_without_disclosure(tmp_path):
    """The digit-limit ValueError is not a JSONDecodeError and must not escape."""
    validate = sup.require_validate()
    original = sys.get_int_max_str_digits()
    try:
        if original == 0:
            sys.set_int_max_str_digits(4300)
        limit = sys.get_int_max_str_digits()
        digits = limit + 64
        literal = "1" + "0" * (digits - 1)
        path = tmp_path / "ledger.json"
        path.write_text('{"n": ' + literal + "}", encoding="utf-8")
        with pytest.raises(validate.LedgerInputError) as excinfo:
            validate.validate_ledger_file(path)
        error = excinfo.value
        assert error.token == "json-malformed"
        rendered = str(error)
        assert "Exceeds the limit" not in rendered
        assert str(digits) not in rendered
        assert literal[:40] not in rendered
        assert error.__cause__ is None
        assert error.__suppress_context__ is True
    finally:
        sys.set_int_max_str_digits(original)


def test_gv7_s_018_the_byte_ceiling_is_enforced_before_parsing(tmp_path):
    validate = sup.require_validate()
    assert validate.MAX_LEDGER_BYTES == sup.MAX_LEDGER_BYTES
    assert type(validate.MAX_LEDGER_BYTES) is int
    path = tmp_path / "ledger.json"
    path.write_bytes(b"x" * (validate.MAX_LEDGER_BYTES + 1))
    with pytest.raises(validate.LedgerCeilingError) as excinfo:
        validate.validate_ledger_file(path)
    assert excinfo.value.token == "ledger-bytes-ceiling"


def test_gv7_s_019_the_interface_is_exactly_one_supplied_file_path(tmp_path):
    """A path outside the repository is legitimate; a non-file is not.

    CONTRACT.md section 9 withdraws the old "beneath an accepted repository
    root" rule: it was unsatisfiable alongside isolated temporary-file testing,
    and reading exactly one named file is what actually protects the validator.
    """
    schema = sup.require_schema()
    validate = sup.require_validate()

    # An isolated temporary file, entirely outside the repository. `{}` is
    # well-formed JSON whose ONLY defect is at the CONTENT stage, so the exact
    # content-stage token is the proof that the path was accepted, the bytes
    # captured, the ceiling checked, the JSON parsed and the root object
    # entered. A refusal that merely shares a superclass proves none of that.
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    resolved = str(outside.resolve()).casefold()
    root = str(sup.REPO_ROOT).casefold()
    assert not resolved.startswith(root), "the fixture must lie outside the repo"

    with pytest.raises(schema.LedgerError) as excinfo:
        validate.validate_ledger_file(outside)
    error = excinfo.value
    assert error.token == "missing-key", error.token
    for earlier in (
        validate.LedgerPathError,
        validate.LedgerCeilingError,
        validate.LedgerInputError,
    ):
        assert not isinstance(error, earlier), earlier.__name__
    assert error.__cause__ is None
    assert error.__suppress_context__ is True

    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path)
    assert excinfo.value.token == "path-not-file"
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path / "absent.json")
    assert excinfo.value.token == "path-missing"


def test_gv7_s_020_a_reparse_point_in_the_supplied_path_is_refused(tmp_path):
    """Deterministic on Windows without privilege: a directory junction.

    The fixture links a *directory* — the accepted neutral approach — and the
    supplied ledger path passes through it. A junction is a reparse point that
    ``os.path.islink`` and ``Path.is_symlink`` both report as False, so a
    validator inspecting only that predicate would follow it. Cleanup is
    bounded to the temporary fixture; no machine setting is changed and no
    Developer Mode or administrator privilege is required.
    """
    validate = sup.require_validate()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "ledger.json").write_text("{}", encoding="utf-8")

    link_dir = tmp_path / "linked"
    mechanism = sup.make_reparse_directory(link_dir, real_dir)
    assert sup.is_reparse_point(link_dir), mechanism
    # The refusal predicate, not the bare attribute: a cloud placeholder also
    # carries FILE_ATTRIBUTE_REPARSE_POINT and must NOT be refused.
    assert sup.is_refused_reparse_point(link_dir), mechanism
    assert not sup.is_refused_reparse_point(real_dir)

    through = link_dir / "ledger.json"
    assert through.exists()
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(through)
    assert excinfo.value.token == "path-symlink-refused"


def test_gv7_s_021_no_environment_variable_or_cwd_locates_the_input(
    tmp_path, monkeypatch
):
    validate = sup.require_validate()
    monkeypatch.chdir(tmp_path)
    for name in ("LEDGER", "LEDGER_PATH", "GV7_LEDGER"):
        monkeypatch.setenv(name, str(tmp_path))
    (tmp_path / "ledger.json").write_text("{}", encoding="utf-8")
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path / "absent.json")
    assert excinfo.value.token == "path-missing"
    with pytest.raises(SystemExit) as systemexit:
        validate.main([])
    assert systemexit.value.code == 2


def test_gv7_s_022_a_refusal_carries_only_a_token_and_a_schema_declared_path():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = dict(ledger)
    payload["intake_state"] = sup.MARKER_VALUE
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    error = excinfo.value
    assert isinstance(error.token, str)
    assert isinstance(error.path, tuple)
    assert sup.MARKER_VALUE not in str(error)
    for name in dir(error):
        assert "value" not in name.lower(), name
    # By content, not only by attribute name: a rejected value stashed as
    # ``.payload``, ``.item`` or ``.got`` would pass a name screen.
    assert set(vars(error)) == {"token", "path"}, sorted(vars(error))
    for attribute in vars(error).values():
        assert sup.MARKER_VALUE not in repr(attribute)
    # A schema-declared path carries declared keys, never an input-derived
    # value: every element is a str key or an int index.
    for element in error.path:
        assert type(element) in (str, int), element
        if isinstance(element, str):
            assert sup.MARKER_VALUE != element


def test_gv7_s_023_the_refusal_vocabulary_is_closed_and_well_formed():
    schema = sup.require_schema()
    tokens = tuple(schema.REFUSAL_TOKENS)
    assert tokens
    assert len(tokens) == len(set(tokens))
    for token in tokens:
        assert token == token.lower()
        assert token.strip() == token and token
        assert set(token) <= set("abcdefghijklmnopqrstuvwxyz-")


def test_gv7_s_024_success_emits_one_canonical_json_line(tmp_path, capsys):
    validate = sup.require_validate()
    code = validate.main([str(sup.LEDGER_PATH)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    body = captured.out[:-1]
    assert body == json.dumps(
        json.loads(body), sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )


def test_gv7_s_025_output_is_byte_identical_across_repeated_runs(capsys):
    validate = sup.require_validate()
    outputs = []
    for _ in range(3):
        validate.main([str(sup.LEDGER_PATH)])
        outputs.append(capsys.readouterr().out)
    assert len(set(outputs)) == 1


def test_gv7_s_026_output_is_identical_across_processes_and_optimisation_levels():
    sup.require_validate()
    outputs = []
    for flags, seed in ((["-B"], "0"), (["-B", "-O"], "1"), (["-B", "-OO"], "12345")):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(sup.REPO_ROOT)
        completed = subprocess.run(
            [sys.executable, *flags, "-m",
             "experiments.general_v7_ledger.validate", str(sup.LEDGER_PATH)],
            capture_output=True, env=env, cwd=str(sup.REPO_ROOT), check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
        outputs.append(completed.stdout)
    assert len(set(outputs)) == 1


def test_gv7_s_027_no_timestamp_or_environment_value_appears_in_the_output(capsys):
    validate = sup.require_validate()
    validate.main([str(sup.LEDGER_PATH)])
    out = capsys.readouterr().out
    for fragment in (str(os.getpid()), "T00:", str(sup.REPO_ROOT)):
        assert fragment not in out


def sys_bindings(tree):
    """Every AST node that BINDS the name ``sys``, with a label.

    Correction 4 verified the *spelling* ``sys`` and never that the name still
    referred to the imported module, so ``sys = Decoy()`` followed by
    ``sys.modules[...]`` passed as a conforming self-binding.

    This enumerates the binding forms **named below** -- it is not a proof that
    no other form exists. ``match`` capture patterns were missing from an
    earlier version of this list and rebound ``sys`` undetected, which is
    exactly why the claim here is an enumeration and not an absolute.
    """
    import ast

    bindings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "sys":
            if isinstance(node.ctx, ast.Store):
                bindings.append(("assigned", node))
            elif isinstance(node.ctx, ast.Del):
                bindings.append(("deleted", node))
        elif isinstance(node, ast.arg) and node.arg == "sys":
            bindings.append(("parameter", node))
        elif isinstance(node, ast.ExceptHandler) and node.name == "sys":
            bindings.append(("exception-target", node))
        elif isinstance(node, ast.MatchAs) and node.name == "sys":
            bindings.append(("match-capture", node))
        elif isinstance(node, ast.MatchStar) and node.name == "sys":
            bindings.append(("match-star", node))
        elif isinstance(node, ast.MatchMapping) and node.rest == "sys":
            bindings.append(("match-mapping-rest", node))
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and "sys" in node.names:
            bindings.append(("global-or-nonlocal", node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == "sys":
                bindings.append(("shadowing-definition", node))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname == "sys":
                    bindings.append(("aliased-import", node))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                # `from os import sys` binds the name with no alias at all.
                if (alias.asname or alias.name) == "sys":
                    bindings.append(("from-import-of-the-name", node))
    return bindings


def sys_modules_findings(source: str):
    """``(conforming, violations)`` for one production module's source.

    The frozen shape pins the **binding** as well as the spelling: one
    module-scope ``import sys`` with no alias, no later rebinding of that name
    by any of the **enumerated** forms, and -- in the two surfaces -- exactly one
    module-scope ``_core = sys.modules[...]`` assignment. The enumeration is a
    list of named forms, not a proof that no other exists; ``match`` captures
    and a plain ``from x import sys`` were each missing from an earlier version
    of it, and the residual is disclosed rather than asserted away. A conforming-looking subscript
    nested in a function or sitting in dead code does not count toward it.

    **This pins the direct static production shape and nothing more.** It does
    not prove that no runtime mutation could occur, it is not an absolute
    behavioural impossibility, and the separate human audit remains required.
    """
    import ast

    tree = ast.parse(source)
    violations = []

    # -- the name `sys` must be the imported module, and must stay it ---------
    module_scope_imports = [
        alias
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "sys"
    ]
    unaliased = [alias for alias in module_scope_imports if alias.asname is None]
    uses_sys = any(
        isinstance(node, ast.Name) and node.id == "sys" for node in ast.walk(tree)
    )
    if uses_sys and (len(module_scope_imports) != 1 or len(unaliased) != 1):
        violations.append(
            ("sys-not-one-module-scope-unaliased-import", len(module_scope_imports))
        )
    for label, _node in sys_bindings(tree):
        violations.append((f"sys-rebound-{label}", "sys"))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "sys":
            for alias in node.names:
                if alias.name in ("modules", "*"):
                    violations.append(("from-sys-import-modules", alias.name))

    # -- every `sys.modules[...]` subscript, classified -----------------------
    conforming_nodes = []
    examined = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        target = node.value
        if not (isinstance(target, ast.Attribute) and target.attr == "modules"):
            continue
        examined.add(id(target))
        if not (isinstance(target.value, ast.Name) and target.value.id == "sys"):
            violations.append(
                ("modules-on-a-non-sys-receiver", ast.unparse(target.value))
            )
            continue
        key = node.slice
        if not (isinstance(key, ast.Constant) and type(key.value) is str):
            violations.append(("non-constant-subscript-key", ast.unparse(key)))
            continue
        if key.value != sup.SYS_MODULES_SELF_BINDING_KEY:
            violations.append(("wrong-subscript-key", key.value))
            continue
        if not isinstance(node.ctx, ast.Load):
            violations.append(
                ("modules-entry-written-or-deleted", type(node.ctx).__name__)
            )
            continue
        conforming_nodes.append(node)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "modules"):
            continue
        if id(node) in examined:
            continue
        violations.append(
            ("modules-reference-outside-the-frozen-form", ast.unparse(node.value))
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        label = getattr(node.func, "id", None)
        if label == "getattr" and len(node.args) >= 2:
            second = node.args[1]
            if isinstance(second, ast.Constant) and second.value == "modules":
                violations.append(("getattr-indirection-to-modules", "getattr"))
        if label == "vars" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id == "sys":
                violations.append(("vars-indirection-to-the-module-table", "vars"))

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        ):
            violations.append(("dunder-dict-indirection", "sys.__dict__"))
        # `sys.__getattribute__("modules")` names the route in source.
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__getattribute__"
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
        ):
            violations.append(
                ("dunder-getattribute-indirection", "sys.__getattribute__")
            )
        # `globals()["sys"] = ...` and `vars()["sys"] = ...` rebind the name
        # without ever writing a Name node for it.
        if (
            isinstance(node, ast.Subscript)
            and not isinstance(node.ctx, ast.Load)
            and isinstance(node.value, ast.Call)
            and getattr(node.value.func, "id", None) in ("globals", "vars")
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "sys"
        ):
            violations.append(
                ("sys-rebound-through-the-namespace-mapping",
                 getattr(node.value.func, "id", "?"))
            )

    # -- only a MODULE-SCOPE `_core = <conforming subscript>` counts ----------
    permitted = set()
    core_targets = 0
    for statement in tree.body:
        for node in ast.walk(statement) if isinstance(
            statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)
        ) else ():
            if isinstance(node, ast.Name) and node.id == "_core" and isinstance(
                node.ctx, ast.Store
            ):
                core_targets += 1
    if core_targets > 1:
        violations.append(("core-rebound-at-module-scope", core_targets))
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "_core"):
            continue
        if any(statement.value is node for node in conforming_nodes):
            permitted.add(id(statement.value))
    for node in conforming_nodes:
        if id(node) not in permitted:
            violations.append(
                (
                    "self-binding-outside-the-permitted-module-scope-assignment",
                    "not `_core = sys.modules[...]` at module scope",
                )
            )
    return len(permitted), violations


#: Self-contained fixtures. Each must be rejected; none touches the filesystem.
SYS_MODULES_NEGATIVE_FIXTURES = (
    ("another literal key",
     "import sys\n_c = sys.modules['experiments.other']\n"),
    ("a computed key",
     "import sys\n_n = 'experiments.' + 'general_v7_ledger'\n_c = sys.modules[_n]\n"),
    ("an f-string key",
     "import sys\n_c = sys.modules[f'experiments.general_v7_ledger']\n"),
    ("a name key",
     "import sys\nKEY = 'experiments.general_v7_ledger'\n_c = sys.modules[KEY]\n"),
    ("an aliased sys import",
     "import sys as _s\n_c = _s.modules['experiments.general_v7_ledger']\n"),
    ("from sys import modules",
     "from sys import modules\n_c = modules['experiments.general_v7_ledger']\n"),
    ("a bare sys.modules reference",
     "import sys\n_c = sys.modules\n"),
    ("a getattr indirection",
     "import sys\n_c = getattr(sys, 'modules')['experiments.general_v7_ledger']\n"),
    ("a vars() indirection",
     "import sys\n_c = vars(sys)['modules']['socket']\n"),
    ("a __dict__ indirection",
     "import sys\n_c = sys.__dict__['modules']['socket']\n"),
    ("a write to the frozen key",
     "import sys\nsys.modules['experiments.general_v7_ledger'] = None\n"),
    ("a delete of the frozen key",
     "import sys\ndel sys.modules['experiments.general_v7_ledger']\n"),
    ("a star import from sys",
     "from sys import *\n_c = modules['experiments.general_v7_ledger']\n"),
    # Correction 5. Every one of these was ACCEPTED before: the scanner
    # verified the SPELLING `sys`, never that it was still the module.
    ("sys rebound to a decoy object",
     "import sys\n\n\nclass Decoy:\n    modules = {'experiments.general_v7_ledger': object()}\n\n\nsys = Decoy()\n_core = sys.modules['experiments.general_v7_ledger']\n"),
    ("sys deleted and rebound",
     "import sys\n\ndel sys\nsys = 1\n_core = sys.modules['experiments.general_v7_ledger']\n"),
    ("a conforming subscript inside a function",
     "import sys\n\n\ndef bind():\n    return sys.modules['experiments.general_v7_ledger']\n"),
    ("a conforming subscript in dead code",
     "import sys\n\nif False:\n    _core = sys.modules['experiments.general_v7_ledger']\n"),
    ("a conforming subscript assigned to another target",
     "import sys\n\n_elsewhere = sys.modules['experiments.general_v7_ledger']\n"),
    ("two sys imports",
     "import sys\nimport sys\n\n_core = sys.modules['experiments.general_v7_ledger']\n"),
    ("sys bound by a plain from-import",
     "import sys\n\nfrom os import sys\n"),
    ("sys bound by a match capture pattern",
     "import sys\n\nmatch object():\n    case sys:\n        pass\n"),
    ("sys bound by a match star pattern",
     "import sys\n\nmatch [1]:\n    case [*sys]:\n        pass\n"),
    ("sys bound by a match mapping rest",
     "import sys\n\nmatch {}:\n    case {**sys}:\n        pass\n"),
    ("sys rebound through globals()",
     "import sys\n\nglobals()['sys'] = 1\n"),
    ("sys rebound through vars()",
     "import sys\n\nvars()['sys'] = 1\n"),
    ("a sys.__getattribute__ indirection",
     "import sys\n\n_c = sys.__getattribute__('modules')['experiments.general_v7_ledger']\n"),
    ("_core reassigned after the permitted binding",
     "import sys\n\n_core = sys.modules['experiments.general_v7_ledger']\n_core = object()\n"),
    ("sys bound as a with-target",
     "import sys\n\nwith open('x') as sys:\n    pass\n"),
    ("sys bound by a walrus",
     "import sys\n\n_v = (sys := 1)\n"),
)

#: DISCLOSED RESIDUAL. A scan over names cannot close rebinding in
#: general: a builtin bound to another name first reaches the table
#: without ever naming it. Recorded here rather than left to be
#: discovered, and named in CONTRACT.md alongside the other gaps.
SYS_MODULES_UNCLOSED_ROUTES = (
    "a builtin rebound before use, as in `_g = getattr` then "
    "`_g(sys, 'modules')`",
)

#: Legal, and must NOT be refused: the contract requires byte-level
#: emission through `sys.stdout`, so importing a non-`modules` name
#: from `sys` has to stay available. A scanner that refused these
#: would be broken, not correct.
SYS_MODULES_PERMITTED_FIXTURES = (
    ("from sys import stdout", "from sys import stdout\n"),
    ("from sys import stderr", "from sys import stderr\n"),
)

SYS_MODULES_POSITIVE_FIXTURE = (
    "import sys\n\n_core = sys.modules['experiments.general_v7_ledger']\n"
)


def test_gv7_s_028_no_production_module_imports_outside_its_allowance():
    """An allowlist over imports, PLUS the one route an allowlist cannot see.

    A blocklist admits every network-capable package published tomorrow, so an
    allowlist over import roots is the better shape. But the earlier claim that
    it "establishes that no code path could retrieve anything" is **withdrawn**:
    it walks ``import`` statements only, and both public surfaces bind the
    shared core through a ``sys.modules`` subscript no import walker sees. That
    route is constrained here too, to a single exact form. What the layers
    jointly establish is what a production module can STATICALLY REACH -- never
    an absolute behavioural impossibility, and a human audit remains required.

    ``__init__.py`` is included: it is a production module and it runs on every
    import of ``schema``.
    """
    import ast

    # The scanner discriminates, proved on self-contained fixtures before it is
    # pointed at anything. A scanner that accepted these would be worthless.
    conforming, violations = sys_modules_findings(SYS_MODULES_POSITIVE_FIXTURE)
    assert conforming == 1, conforming
    assert violations == [], violations
    for label, fixture in SYS_MODULES_NEGATIVE_FIXTURES:
        _found_conforming, found_violations = sys_modules_findings(fixture)
        # A violation is what refuses the module. Some shapes carry a
        # conforming-LOOKING subscript together with a fatal binding fault --
        # `sys = Decoy()` is exactly that -- so the count alone is not the
        # rejection signal and asserting it here would be wrong.
        assert found_violations, f"{label}: not rejected"
    for label, fixture in SYS_MODULES_PERMITTED_FIXTURES:
        found_conforming, found_violations = sys_modules_findings(fixture)
        assert not found_violations, (label, found_violations)
        assert found_conforming == 0, (label, found_conforming)
    assert SYS_MODULES_UNCLOSED_ROUTES, "the residual must stay disclosed"

    for name in sup.PRODUCTION_MODULES:
        path = sup.LAB_DIR / name
        text = sup.require_file(path, name)
        roots = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                roots.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (name, "relative import")
                roots.add(node.module or "")
        for root in sorted(roots):
            assert root in sup.PRODUCTION_ALLOWED_IMPORTS, (name, root)
        # Retained belt-and-braces: the allowlist already excludes these.
        for forbidden in sup.NETWORK_CAPABLE_MODULES:
            assert forbidden not in roots, (name, forbidden)
            for root in roots:
                assert not root.startswith(forbidden + "."), (name, root)

        # The constrained self-binding: exact form, exact count, per module.
        conforming, violations = sys_modules_findings(text)
        assert not violations, (name, violations)
        assert conforming == sup.SYS_MODULES_ALLOWED_USES[name], (
            name,
            conforming,
            sup.SYS_MODULES_ALLOWED_USES[name],
        )


def test_gv7_s_029_no_production_module_contains_a_bare_assert_or_broad_catch():
    import ast

    for name in sup.PRODUCTION_MODULES:
        text = sup.require_file(sup.LAB_DIR / name, name)
        tree = ast.parse(text)
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)], name
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            assert node.type is not None, name
            targets = (
                node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            )
            for target in targets:
                label = getattr(target, "id", None) or getattr(target, "attr", None)
                assert label not in ("Exception", "BaseException"), (name, label)


def test_gv7_s_030_emitted_counts_equal_the_actual_collection_lengths(capsys):
    validate = sup.require_validate()
    ledger = sup.require_ledger()
    validate.main([str(sup.LEDGER_PATH)])
    summary = json.loads(capsys.readouterr().out)
    counts = summary["counts"]
    for key in sup.COLLECTION_KEYS:
        assert counts[key] == len(ledger[key]), key
    assert set(counts) == set(sup.COLLECTION_KEYS)


# --------------------------------------------------------------------------
# Reference integrity, per reference field. CONTRACT.md sections 6b-6h.
# --------------------------------------------------------------------------

REFERENCE_CASES = (
    ("batches", "introduces_sources", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("batches", "introduces_artifacts", "GV7-ART-9999", "GV7-BAT-0001"),
    ("batches", "updates_sources", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("sources", "batch_ref", "GV7-BAT-9999", "GV7-SRC-9999"),
    ("claims", "source_ref", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("claims", "batch_ref", "GV7-BAT-9999", "GV7-CLM-9999"),
    ("artifacts", "introducing_batch", "GV7-BAT-9999", "GV7-SRC-0001"),
    ("relationships", "left_ref", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("relationships", "right_ref", "GV7-CLM-9999", "GV7-BAT-0001"),
    ("unresolved", "refs", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("corrections", "target_ref", "GV7-SRC-9999", None),
)


def test_gv7_s_031_every_reference_field_refuses_an_unresolvable_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection, field, dangling, _wrong in REFERENCE_CASES:
        records = ledger.get(collection) or []
        if not records:
            continue
        payload = json.loads(json.dumps(ledger))
        target = payload[collection][0]
        if isinstance(target[field], list):
            target[field] = [dangling]
        else:
            target[field] = dangling
        refuse(schema, payload, "reference-not-found")


def test_gv7_s_032_every_reference_field_refuses_a_wrong_kind_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection, field, _dangling, wrong in REFERENCE_CASES:
        if wrong is None:
            continue
        records = ledger.get(collection) or []
        if not records:
            continue
        payload = json.loads(json.dumps(ledger))
        target = payload[collection][0]
        if isinstance(target[field], list):
            target[field] = [wrong]
        else:
            target[field] = wrong
        refuse(schema, payload, "reference-wrong-kind")


def find_batch(payload, batch_id):
    return next(b for b in payload["batches"] if b["batch_id"] == batch_id)


def other_batch(payload, batch_id, list_field):
    """A spare batch that can legitimately carry the listing under test.

    Batch 62 introduces no source and batch 63 introduces neither, so using
    either as the spare would draw a refusal from *that* frozen rule instead of
    from reciprocity -- the control would pass for the wrong reason. Both are
    excluded.
    """
    special = (sup.ARTIFACT_BEARING_BATCH, sup.BIBLIOGRAPHY_BATCH)
    return next(
        b for b in payload["batches"]
        if b["batch_id"] != batch_id
        and b["batch_id"] not in special
        and not b[list_field]
    )


def drop_listing(batch, list_field, value):
    batch[list_field] = [item for item in batch[list_field] if item != value]


def test_gv7_s_033_source_introduction_must_be_reciprocal_in_both_directions():
    """Existence is not reciprocity: both sides must agree, and only once."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    source_id = ledger["sources"][0]["source_id"]
    batch_id = ledger["sources"][0]["batch_ref"]

    # (a) the record names its batch, but the batch omits it.
    payload = json.loads(json.dumps(ledger))
    drop_listing(find_batch(payload, batch_id), "introduces_sources", source_id)
    refuse(schema, payload, "introduction-not-reciprocal")

    # (b) a DIFFERENT batch lists it and its own batch does not. Dropping the
    # original listing is what makes this distinct from (c): without that line
    # (b) and (c) construct the identical double-listing payload, and the case
    # the contract names -- "a batch listing a record whose own introducing
    # field points elsewhere" -- is never built at all.
    payload = json.loads(json.dumps(ledger))
    drop_listing(find_batch(payload, batch_id), "introduces_sources", source_id)
    other_batch(payload, batch_id, "introduces_sources")["introduces_sources"] = [
        source_id
    ]
    refuse(schema, payload, "introduction-not-reciprocal")

    # (c) the same valid record is listed by two batches: the original listing
    # stays in place, so this payload differs from (b) by exactly one element.
    payload = json.loads(json.dumps(ledger))
    assert source_id in find_batch(payload, batch_id)["introduces_sources"]
    other_batch(payload, batch_id, "introduces_sources")["introduces_sources"] = [
        source_id
    ]
    refuse(schema, payload, "introduction-not-reciprocal")


def test_gv7_s_046_artifact_introduction_must_be_reciprocal_in_both_directions():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    artifact_id = "GV7-ART-0001"
    batch_id = sup.ARTIFACT_BATCHES[artifact_id]

    # (a) the artifact names its batch, but the batch omits it.
    payload = json.loads(json.dumps(ledger))
    drop_listing(
        find_batch(payload, batch_id), "introduces_artifacts", artifact_id
    )
    refuse(schema, payload, "introduction-not-reciprocal")

    # (b) a DIFFERENT batch lists it and its own batch does not.
    payload = json.loads(json.dumps(ledger))
    drop_listing(
        find_batch(payload, batch_id), "introduces_artifacts", artifact_id
    )
    other_batch(payload, batch_id, "introduces_artifacts")[
        "introduces_artifacts"
    ] = [artifact_id]
    refuse(schema, payload, "introduction-not-reciprocal")

    # (c) the same valid artifact is listed by two batches.
    payload = json.loads(json.dumps(ledger))
    assert artifact_id in find_batch(payload, batch_id)["introduces_artifacts"]
    other_batch(payload, batch_id, "introduces_artifacts")[
        "introduces_artifacts"
    ] = [artifact_id]
    refuse(schema, payload, "introduction-not-reciprocal")


# --------------------------------------------------------------------------
# Correction and supersession. Synthetic throughout: these rules must hold
# whether or not the committed ledger happens to carry a correction.
# --------------------------------------------------------------------------


def synthetic_correction(ledger, **overrides):
    target = ledger["sources"][0]["source_id"]
    record = {
        "correction_id": "GV7-COR-0001",
        "target_ref": target,
        "correction_kind": "correction",
        "statement": "synthetic additive correction for control purposes",
        "recorded_by_role": "auditor",
        "recorded_by_label": "synthetic recorder",
    }
    record.update(overrides)
    return record


def with_correction(ledger, record):
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [record]
    return payload


def test_gv7_s_034_a_well_formed_synthetic_correction_is_accepted():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = with_correction(ledger, synthetic_correction(ledger))
    schema.validate_ledger(payload)
    assert set(payload["corrections"][0]) == sup.CORRECTION_KEYS


def test_gv7_s_035_a_correction_with_a_wrong_key_set_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    record = synthetic_correction(ledger)
    record["an_undeclared_nested_key"] = "synthetic"
    refuse(schema, with_correction(ledger, record), "undeclared-key")
    for key in sorted(sup.CORRECTION_KEYS):
        record = synthetic_correction(ledger)
        del record[key]
        refuse(schema, with_correction(ledger, record), "missing-key")


def test_gv7_s_036_a_correction_with_a_bad_id_kind_or_target_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    refuse(
        schema,
        with_correction(ledger, synthetic_correction(ledger, correction_id="COR-1")),
        "identifier-malformed",
    )
    refuse(
        schema,
        with_correction(ledger, synthetic_correction(ledger, correction_kind="edit")),
        "enum-value-invalid",
    )
    refuse(
        schema,
        with_correction(
            ledger, synthetic_correction(ledger, target_ref="GV7-SRC-9999")
        ),
        "reference-not-found",
    )


def test_gv7_s_037_a_correction_never_removes_or_edits_its_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    target_id = ledger["sources"][0]["source_id"]
    payload = with_correction(ledger, synthetic_correction(ledger))
    before = sup.canonical_bytes(payload["sources"][0])
    schema.validate_ledger(payload)
    survivors = [s for s in payload["sources"] if s["source_id"] == target_id]
    assert len(survivors) == 1, "the corrected record must remain present"
    assert sup.canonical_bytes(survivors[0]) == before, "corrections are additive"


def test_gv7_s_043_a_relationship_carries_its_own_unverified_provenance():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for field, value, token in (
        ("verification_state", "identity-verified", "enum-value-invalid"),
        ("attribution_class", "verified-implementation-evidence",
         "enum-value-invalid"),
        ("limitations", [], "list-length-invalid"),
    ):
        payload = json.loads(json.dumps(ledger))
        payload["relationships"][0][field] = value
        refuse(schema, payload, token)
    payload = json.loads(json.dumps(ledger))
    first = payload["relationships"][0]["limitations"][0]
    payload["relationships"][0]["limitations"] = [first, first]
    refuse(schema, payload, "list-duplicate-item")


def test_gv7_s_044_safety_dispositions_is_a_bounded_exclusive_list():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection in ("sources", "claims", "artifacts"):
        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = []
        refuse(schema, payload, "list-length-invalid")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = [
            "quarantined-covert-communication",
            "quarantined-covert-communication",
        ]
        refuse(schema, payload, "list-duplicate-item")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = ["not-a-disposition"]
        refuse(schema, payload, "enum-value-invalid")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = [
            "ordinary",
            "quarantined-hidden-monitoring",
        ]
        refuse(schema, payload, "disposition-ordinary-not-exclusive")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = "ordinary"
        refuse(schema, payload, "type-not-exact")


# ==========================================================================
# Correction 3. Every control below drives the production module. A mirror
# check over ``_support`` constants establishes nothing about an implementation
# and is never counted as coverage here.
# ==========================================================================


def mutate(ledger, collection, field, value, index=0):
    payload = json.loads(json.dumps(ledger))
    payload[collection][index][field] = value
    return payload


def source_index(ledger, with_locator):
    for index, source in enumerate(ledger["sources"]):
        if (source["supplied_locator"] is not None) is with_locator:
            return index
    raise AssertionError(
        f"the committed ledger has no source with_locator={with_locator}"
    )


def many_corrections(ledger, count):
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [
        synthetic_correction(ledger, correction_id=f"GV7-COR-{n:04d}")
        for n in range(1, count + 1)
    ]
    return payload


# ---------------------------------------------------- B: collection ceilings


def test_gv7_s_047_a_root_collection_is_not_capped_by_list_max():
    """65 well-formed corrections. ``LIST_MAX`` is a nested bound only.

    Section 9 used to say "every list is duplicate-free and within LIST_MAX",
    and a root collection is a list. Applying 64 there caps the ledger's entire
    additive history channel at 64 records.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert sup.LIST_MAX == 64
    payload = many_corrections(ledger, sup.LIST_MAX + 1)
    assert len(payload["corrections"]) == 65 > sup.LIST_MAX
    schema.validate_ledger(payload)


def test_gv7_s_048_a_root_collection_beyond_the_root_ceiling_is_refused():
    """The root ceiling is real, and the nested bound is still separate."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert sup.ROOT_COLLECTION_MAX > sup.LIST_MAX
    payload = many_corrections(ledger, sup.ROOT_COLLECTION_MAX + 1)
    refuse(schema, payload, "collection-length-invalid")

    # The nested bound is unchanged by the root ceiling.
    payload = mutate(
        ledger,
        "sources",
        "limitations",
        [f"synthetic limitation {n}" for n in range(sup.LIST_MAX + 1)],
    )
    refuse(schema, payload, "list-length-invalid")

    # A root collection that is empty where section 5 requires records.
    for collection in ("sources", "batches", "relationships", "unresolved"):
        payload = json.loads(json.dumps(ledger))
        payload[collection] = []
        refuse(schema, payload, "collection-length-invalid")


# ------------------------------------------------------- G: counts are computed


def test_gv7_s_049_every_emitted_count_is_computed_from_its_collection(
    tmp_path, capsys
):
    """One added record must move exactly one count, by exactly one.

    A hardcoded count table transcribed from the committed ledger satisfies a
    single-observation equality check. It cannot satisfy a delta.
    """
    schema = sup.require_schema()
    validate = sup.require_validate()
    ledger = sup.require_ledger()

    base = json.loads(json.dumps(ledger))
    plus_one = many_corrections(ledger, len(base["corrections"]) + 1)
    plus_two = many_corrections(ledger, len(base["corrections"]) + 2)
    for payload in (base, plus_one, plus_two):
        schema.validate_ledger(payload)

    def counts_of(payload, name):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert validate.main([str(path)]) == 0
        return json.loads(capsys.readouterr().out)

    before = counts_of(base, "base.json")
    after = counts_of(plus_one, "plus_one.json")
    after_two = counts_of(plus_two, "plus_two.json")

    # (a) exactly one count moved, and by exactly one.
    assert after["counts"]["corrections"] == before["counts"]["corrections"] + 1
    for key in sup.COLLECTION_KEYS:
        if key == "corrections":
            continue
        assert after["counts"][key] == before["counts"][key], key

    # (b) a length, not an increment and not a non-empty flag.
    assert (
        after_two["counts"]["corrections"] == before["counts"]["corrections"] + 2
    )
    assert after["counts"]["corrections"] == len(plus_one["corrections"])

    # (c) nothing outside `counts` drifted with the input.
    assert {k: v for k, v in after.items() if k != "counts"} == {
        k: v for k, v in before.items() if k != "counts"
    }


# ------------------------------------------- C: supersession is closed to null


def test_gv7_s_050_supersedes_is_closed_to_null_and_non_null_is_refused():
    """v1 has no live supersession channel, so it admits no block."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    for record in ledger["sources"] + ledger["claims"]:
        assert record["supersedes"] is None, record

    predecessor = ledger["sources"][0]
    block = {
        "record_id": predecessor["source_id"],
        "content_digest": sup.canonical_digest(predecessor),
    }
    # A perfectly well-formed block, refused for being a block at all.
    refuse(
        schema,
        mutate(ledger, "sources", "supersedes", block, index=1),
        "supersedes-not-permitted",
    )
    claim_predecessor = ledger["claims"][0]
    refuse(
        schema,
        mutate(
            ledger,
            "claims",
            "supersedes",
            {
                "record_id": claim_predecessor["claim_id"],
                "content_digest": sup.canonical_digest(claim_predecessor),
            },
            index=1,
        ),
        "supersedes-not-permitted",
    )
    # Anything else in the slot is a type fault, not a supersession.
    refuse(
        schema,
        mutate(ledger, "sources", "supersedes", "", index=1),
        "type-not-exact",
    )
    # Control: the committed null value is accepted.
    schema.validate_ledger(json.loads(json.dumps(ledger)))


def test_gv7_s_051_a_correction_may_not_target_another_correction():
    """Structurally impossible cycles beat a graph traversal nobody wrote."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    # An ordinary target in each permitted collection is accepted.
    for collection in sup.CORRECTION_TARGET_COLLECTIONS:
        records = ledger.get(collection) or []
        if not records:
            continue
        field = sup.ID_FIELD_BY_COLLECTION[collection]
        payload = with_correction(
            ledger, synthetic_correction(ledger, target_ref=records[0][field])
        )
        schema.validate_ledger(payload)

    # A self-target.
    record = synthetic_correction(ledger, target_ref="GV7-COR-0001")
    assert record["correction_id"] == "GV7-COR-0001"
    refuse(
        schema,
        with_correction(ledger, record),
        "correction-target-not-permitted",
    )

    # A two-record cycle, both records otherwise valid.
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [
        synthetic_correction(
            ledger, correction_id="GV7-COR-0001", target_ref="GV7-COR-0002"
        ),
        synthetic_correction(
            ledger, correction_id="GV7-COR-0002", target_ref="GV7-COR-0001"
        ),
    ]
    refuse(schema, payload, "correction-target-not-permitted")

    # A correction targeting an unrelated, existing correction: still refused,
    # and refused for its kind rather than for being missing.
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [
        synthetic_correction(ledger, correction_id="GV7-COR-0001"),
        synthetic_correction(
            ledger, correction_id="GV7-COR-0002", target_ref="GV7-COR-0001"
        ),
    ]
    error = refuse(schema, payload, "correction-target-not-permitted")
    assert error.token != "reference-not-found"


# ------------------------------ H: the production vocabularies are the frozen ones


VOCABULARY_NAMES = (
    "ATTRIBUTION_CLASSES",
    "CLAIM_ATTRIBUTION_CLASSES",
    "RELATIONSHIP_ATTRIBUTION_CLASSES",
    "ARTIFACT_CLASSES",
    "BATCH_KINDS",
    "CLAIM_VERIFICATION_STATES",
    "CONFLICT_FAMILIES",
    "CORRECTION_KINDS",
    "EXECUTABLE_STATES",
    "IDENTITY_ORIGINS",
    "LOCATOR_ABSENCE_REASONS",
    "METADATA_PROVENANCE",
    "PRESERVATION_STATES",
    "RELATIONSHIP_BASES",
    "RELATIONSHIP_TYPES",
    "RELATIONSHIP_VERIFICATION_STATES",
    "RETRIEVAL_STATES",
    "ROLES",
    "SAFETY_DISPOSITIONS",
    "SOURCE_VERIFICATION_STATES",
    "UNRESOLVED_STATES",
)

SCALAR_NAMES = ("LABEL_MAX", "TEXT_MAX", "LIST_MAX", "ROOT_COLLECTION_MAX")

#: Exempt from the SUBSTRING promotion sweep only. The frozen-equality check
#: above still covers every vocabulary, this one included.
#:
#: A conflict-family label names an unresolved topic, not a verdict on it.
#: ``immutable-raw-provenance-versus-raw-deletion`` contains ``provenance``,
#: whose first six characters are the forbidden fragment ``proven`` -- so a
#: substring sweep reads a dispute *about* provenance as a claim that
#: something has been proven. It is neither: the label records that the
#: question is open. ``GV7-D-014`` already excludes this vocabulary for the
#: same reason, and this restores the two to agreement.
PROMOTION_SWEEP_EXEMPT = ("CONFLICT_FAMILIES",)


def test_gv7_s_052_the_production_vocabularies_are_the_frozen_vocabularies():
    """Otherwise a validator whose ROLES quietly gained a value passes."""
    schema = sup.require_schema()
    for name in VOCABULARY_NAMES:
        assert hasattr(schema, name), name
        assert tuple(getattr(schema, name)) == getattr(sup, name), name
    for name in SCALAR_NAMES:
        assert getattr(schema, name) == getattr(sup, name), name
        assert type(getattr(schema, name)) is int, name
    for collection, keys in sorted(sup.KEYS_BY_COLLECTION.items()):
        assert frozenset(schema.KEYS_BY_COLLECTION[collection]) == keys, collection
    assert frozenset(schema.ROOT_KEYS) == sup.ROOT_KEYS
    assert schema.ID_PATTERN == sup.ID_PATTERN
    assert schema.NOT_SUPPLIED == sup.NOT_SUPPLIED
    # The production vocabularies carry no promoting token either, except
    # where a substring sweep cannot tell a topic label from an assertion.
    for name in VOCABULARY_NAMES:
        if name in PROMOTION_SWEEP_EXEMPT:
            continue
        for token in getattr(schema, name):
            for fragment in sup.FORBIDDEN_PROMOTION_FRAGMENTS:
                assert fragment not in token, (name, token, fragment)


def test_gv7_s_053_every_closed_vocabulary_refuses_an_invalid_value():
    """One table, every closed vocabulary, each reaching the validator."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    cases = (
        ("batches", "batch_kind", "synthetic-kind"),
        ("batches", "supplied_by_role", "synthetic-role"),
        ("sources", "carrier_role", "synthetic-role"),
        ("sources", "metadata_provenance", "synthetic-provenance"),
        ("sources", "retrieval_state", "retrieved"),
        ("sources", "verification_state", "identity-verified"),
        ("claims", "attribution_class", "synthetic-class"),
        ("claims", "verification_state", "claim-source-matched"),
        ("relationships", "relationship_type", "synthetic-type"),
        ("relationships", "basis", "synthetic-basis"),
        ("relationships", "attribution_class", "synthetic-class"),
        ("relationships", "verification_state", "identity-verified"),
        ("relationships", "recorded_by_role", "synthetic-role"),
        ("unresolved", "conflict_family", "synthetic-family"),
        ("unresolved", "resolution_state", "resolved"),
        ("unresolved", "recorded_by_role", "synthetic-role"),
        ("artifacts", "artifact_class", "authorization"),
        ("artifacts", "identity_origin", "synthetic-origin"),
        ("artifacts", "preservation_status", "adopted"),
        ("artifacts", "executable_status", "executable"),
    )
    for collection, field, value in cases:
        refuse(
            schema,
            mutate(ledger, collection, field, value),
            "enum-value-invalid",
        )
    # locator_absence is closed too, on a source that legitimately has one.
    without = source_index(ledger, with_locator=False)
    refuse(
        schema,
        mutate(
            ledger, "sources", "locator_absence", "synthetic-reason", index=without
        ),
        "enum-value-invalid",
    )
    # And the correction vocabulary, through the synthetic path.
    refuse(
        schema,
        with_correction(ledger, synthetic_correction(ledger, correction_kind="edit")),
        "enum-value-invalid",
    )


def test_gv7_s_054_the_identifier_grammar_is_enforced_by_the_validator():
    r"""``[0-9]`` is load-bearing, and the proof must reach production.

    ``\d`` matches Arabic-Indic and Devanagari digits and ``int()`` parses
    them, so a grammar written with ``\d`` would admit an identifier that
    renders as an ASCII id in some fonts and is a different string.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    malformed = (
        "GV7-SRC-\u0660\u0660\u0661\u0662",   # Arabic-Indic digits
        "GV7-SRC-\u0966\u0967\u0968\u0969",   # Devanagari digits
        "GV7-SRC-\uff10\uff10\uff10\uff11",   # full-width digits
        "GV7-SRC-001",
        "GV7-SRC-00001",
        "gv7-src-0001",
        "GV7-XXX-0001",
        "GV7-SRC-0001\n",                     # \A..\Z anchoring, not ^..$
        " GV7-SRC-0001",
        "",
    )
    for value in malformed:
        assert not sup.ID_RE.match(value), value
        refuse(
            schema,
            mutate(ledger, "sources", "source_id", value),
            "identifier-malformed",
        )

    # A well-formed id of the WRONG segment for its collection.
    for collection, field, wrong in (
        ("sources", "source_id", "GV7-BAT-0007"),
        ("batches", "batch_id", "GV7-SRC-0007"),
        ("claims", "claim_id", "GV7-REL-0007"),
        ("relationships", "relationship_id", "GV7-UNR-0007"),
        ("unresolved", "unresolved_id", "GV7-ART-0007"),
        ("artifacts", "artifact_id", "GV7-COR-0007"),
    ):
        assert sup.ID_RE.match(wrong), wrong
        refuse(
            schema,
            mutate(ledger, collection, field, wrong),
            "identifier-wrong-collection",
        )


def test_gv7_s_055_a_batch_ordinal_must_agree_with_its_own_identifier():
    """In range, and still wrong: the two must be checked against each other."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    first = ledger["batches"][0]
    assert first["batch_id"] == f"GV7-BAT-{first['batch_ordinal']:04d}"
    disagreeing = 1 if first["batch_ordinal"] != 1 else 2
    assert 1 <= disagreeing <= sup.EXPECTED_BATCHES
    refuse(
        schema,
        mutate(ledger, "batches", "batch_ordinal", disagreeing),
        "ordinal-id-mismatch",
    )
    for out_of_range in (0, -1, sup.EXPECTED_BATCHES + 1):
        refuse(
            schema,
            mutate(ledger, "batches", "batch_ordinal", out_of_range),
            "int-out-of-range",
        )


# ------------------------------------------------------ I/H: locators and dates


def test_gv7_s_056_every_locator_pairing_rule_is_enforced():
    """Present-or-null together, and the absence token exactly complements."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    with_locator = source_index(ledger, with_locator=True)
    without = source_index(ledger, with_locator=False)
    supplied = ledger["sources"][with_locator]["supplied_locator"]
    normalized = ledger["sources"][with_locator]["normalized_locator"]

    def paired(index, **fields):
        payload = json.loads(json.dumps(ledger))
        payload["sources"][index].update(fields)
        return payload

    cases = (
        # supplied present, normalized null
        paired(with_locator, normalized_locator=None),
        # supplied null, normalized present
        paired(with_locator, supplied_locator=None),
        # both present AND an absence reason
        paired(with_locator, locator_absence="no-exact-locator-supplied"),
        # both null AND no absence reason
        paired(without, locator_absence=None),
        # absent source given a locator but keeping its absence token
        paired(without, supplied_locator=supplied, normalized_locator=normalized),
    )
    for payload in cases:
        refuse(schema, payload, "locator-pairing-invalid")


def test_gv7_s_057_a_normalized_locator_must_be_https_only_in_shape():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    index = source_index(ledger, with_locator=True)
    for value in (
        "http://example.invalid/a",
        "HTTPS://example.invalid/a",
        "ftp://example.invalid/a",
        "https:/example.invalid/a",
        "//example.invalid/a",
        " https://example.invalid/a",
        "https://example.invalid/a ",
        "example.invalid/a",
        "",
    ):
        refuse(
            schema,
            mutate(ledger, "sources", "normalized_locator", value, index=index),
            "locator-not-https",
        )


def test_gv7_s_061_supplied_and_normalized_dates_are_paired_and_verbatim():
    """A supplied date is kept as supplied; only the normalized form is ISO."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        supplied = source["supplied_date"]
        normalized = source["normalized_date"]
        assert type(supplied) is str and supplied, source["source_id"]
        assert normalized is None or sup.ISO_DATE_RE.match(normalized), (
            source["source_id"],
            normalized,
        )
        if supplied == sup.NOT_SUPPLIED:
            assert normalized is None, source["source_id"]

    def dated(**fields):
        payload = json.loads(json.dumps(ledger))
        payload["sources"][0].update(fields)
        return payload

    # not-supplied with a normalized date is a contradiction.
    refuse(
        schema,
        dated(supplied_date=sup.NOT_SUPPLIED, normalized_date="2024-03-01"),
        "date-pairing-invalid",
    )
    # A malformed normalized date, including a non-ASCII-digit one.
    for value in (
        "2024-13-45",
        "2024-3-1",
        "01/02/2024",
        "Spring 2024",
        "\u0662\u0660\u0662\u0664-\u0660\u0663-\u0660\u0661",
        "",
    ):
        refuse(schema, dated(normalized_date=value), "date-pairing-invalid")
    # A supplied date that is real but not a calendar day is KEPT, with null.
    schema.validate_ledger(
        dated(supplied_date="Spring 2024", normalized_date=None)
    )
    schema.validate_ledger(dated(supplied_date="  c. 2019 ", normalized_date=None))


def test_gv7_s_062_no_v1_record_may_carry_the_reserved_evidence_class():
    """Reserved in the vocabulary, refused in every position that exists."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    reserved = "verified-implementation-evidence"
    assert reserved in schema.ATTRIBUTION_CLASSES
    assert reserved not in schema.CLAIM_ATTRIBUTION_CLASSES
    assert reserved not in schema.RELATIONSHIP_ATTRIBUTION_CLASSES
    for collection in ("claims", "relationships"):
        refuse(
            schema,
            mutate(ledger, collection, "attribution_class", reserved),
            "enum-value-invalid",
        )
    for retired in sup.RETIRED_ATTRIBUTION_CLASSES:
        refuse(
            schema,
            mutate(ledger, "claims", "attribution_class", retired),
            "enum-value-invalid",
        )


def test_gv7_s_058_relationship_endpoints_must_be_of_the_same_kind():
    """Two individually valid endpoints of different kinds is its own fault."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    source_id = ledger["sources"][0]["source_id"]
    claim_id = ledger["claims"][0]["claim_id"]
    payload = json.loads(json.dumps(ledger))
    payload["relationships"][0]["left_ref"] = source_id
    payload["relationships"][0]["right_ref"] = claim_id
    refuse(schema, payload, "relationship-endpoint-kind-mismatch")


def test_gv7_s_059_every_bounded_string_refuses_empty_and_over_length():
    """``LABEL_MAX`` and ``TEXT_MAX`` had no control of any kind."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    label_fields = (
        ("batches", "supplied_by_label"),
        ("sources", "carrier_label"),
        ("relationships", "recorded_by_label"),
        ("unresolved", "recorded_by_label"),
    )
    text_fields = (
        ("batches", "notes"),
        ("claims", "claim_text"),
        ("claims", "evidence_basis"),
        ("unresolved", "statement"),
        ("artifacts", "summary"),
        ("artifacts", "rejection_basis"),
    )
    for bound, fields in ((sup.LABEL_MAX, label_fields), (sup.TEXT_MAX, text_fields)):
        for collection, field in fields:
            refuse(
                schema, mutate(ledger, collection, field, ""), "text-length-invalid"
            )
            refuse(
                schema,
                mutate(ledger, collection, field, "x" * (bound + 1)),
                "text-length-invalid",
            )
            # The boundary itself is accepted: a bound that refuses its own
            # maximum is off by one.
            schema.validate_ledger(mutate(ledger, collection, field, "x" * bound))


def test_gv7_s_060_every_nested_list_bound_is_enforced():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    over = [f"synthetic entry {n}" for n in range(sup.LIST_MAX + 1)]
    for collection, field in (
        ("sources", "limitations"),
        ("claims", "limitations"),
        ("relationships", "limitations"),
    ):
        refuse(schema, mutate(ledger, collection, field, over), "list-length-invalid")

    ids = [f"GV7-SRC-{n:04d}" for n in range(1, sup.LIST_MAX + 2)]
    for field in ("introduces_sources", "updates_sources"):
        refuse(schema, mutate(ledger, "batches", field, ids), "list-length-invalid")

    # `positions` carries a tighter declared bound of 2..8.
    positions = ledger["unresolved"][0]["positions"]
    refuse(
        schema,
        mutate(ledger, "unresolved", "positions", positions[:1]),
        "list-length-invalid",
    )
    refuse(
        schema,
        mutate(
            ledger,
            "unresolved",
            "positions",
            [f"synthetic position {n}" for n in range(9)],
        ),
        "list-length-invalid",
    )
    refuse(schema, mutate(ledger, "unresolved", "refs", []), "list-length-invalid")


def test_gv7_s_067_every_record_shape_refuses_a_missing_key():
    """Closed shapes were proved by extra keys, never by absent ones."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection, keys in sorted(sup.KEYS_BY_COLLECTION.items()):
        if collection == "corrections":
            continue
        for key in sorted(keys):
            payload = json.loads(json.dumps(ledger))
            del payload[collection][0][key]
            refuse(schema, payload, "missing-key")


# --------------------------------------------- M/H: Windows path hazards, frozen


def test_gv7_s_063_hostile_path_shapes_are_refused_lexically(tmp_path):
    """Lexical refusal precedes existence: none of these need to exist."""
    validate = sup.require_validate()
    separator = chr(92)
    cases = (
        ("C:ledger.json", "path-drive-relative"),
        ("C:", "path-drive-relative"),
        (separator * 2 + "?" + separator + "C:" + separator + "ledger.json",
         "path-device-namespace"),
        (separator * 2 + "." + separator + "CON", "path-device-namespace"),
        (str(tmp_path / "CON"), "path-reserved-name"),
        (str(tmp_path / "CON.json"), "path-reserved-name"),
        (str(tmp_path / "nul.txt"), "path-reserved-name"),
        (str(tmp_path / "COM1"), "path-reserved-name"),
        (str(tmp_path / "LPT9.json"), "path-reserved-name"),
        (str(tmp_path / "CON") + ".", "path-reserved-name"),
        (str(tmp_path / "CON") + " ", "path-reserved-name"),
        (str(tmp_path / "aux" / "ledger.json"), "path-reserved-name"),
    )
    for value, token in cases:
        with pytest.raises(validate.LedgerPathError) as excinfo:
            validate.validate_ledger_file(value)
        assert excinfo.value.token == token, (value, excinfo.value.token)

    # Names that merely resemble a device must NOT be refused: a rule that
    # refuses `COMPANY` is a rule nobody can use.
    for name in ("COM0", "LPT0", "LPT10", "CONSOLE", "COMPANY", "nul_file"):
        assert not sup.component_is_reserved(name), name
        probe = tmp_path / f"{name}.json"
        probe.write_text("{}", encoding="utf-8")
        with pytest.raises(sup.require_schema().LedgerError) as excinfo:
            validate.validate_ledger_file(probe)
        assert excinfo.value.token == "missing-key", name


# ------------------------------------------------------------- O: refusal order


def test_gv7_s_064_the_earliest_applicable_refusal_stage_wins():
    """Each payload violates two stages. The earlier token must be the one."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    # stage 4 (exact types) before stage 5 (closed shapes): a foreign key type
    # that is ALSO an undeclared key.
    payload = dict(ledger)
    payload[HookedStr(sup.MARKER_KEY)] = "synthetic"
    refuse(schema, payload, "key-not-exact-str")

    # stage 5 before stage 6: an undeclared key alongside an invalid enum.
    payload = mutate(ledger, "claims", "attribution_class", "synthetic-class")
    payload["claims"][0]["an_undeclared_nested_key"] = "synthetic"
    refuse(schema, payload, "undeclared-key")

    # stage 6 before stage 7: an invalid enum alongside a dangling reference.
    payload = mutate(ledger, "claims", "attribution_class", "synthetic-class")
    payload["claims"][0]["source_ref"] = "GV7-SRC-9999"
    refuse(schema, payload, "enum-value-invalid")

    # stage 6 before stage 7: a malformed identifier alongside a bad reference.
    payload = mutate(ledger, "claims", "claim_id", "GV7-CLM-1")
    payload["claims"][0]["source_ref"] = "GV7-SRC-9999"
    refuse(schema, payload, "identifier-malformed")

    # within stage 7: kind is decided from the segment before existence.
    payload = mutate(ledger, "claims", "source_ref", "GV7-BAT-9999")
    refuse(schema, payload, "reference-wrong-kind")


def test_gv7_s_065_input_is_decoded_strictly_and_surrogates_are_refused(tmp_path):
    """``ensure_ascii=True`` is load-bearing, and the decode must be strict."""
    schema = sup.require_schema()
    validate = sup.require_validate()

    # Raw WTF-8. `json.loads` on BYTES decodes with errors="surrogatepass" and
    # would admit this silently; a strict decode refuses it.
    wtf8 = tmp_path / "wtf8.json"
    wtf8.write_bytes(b'{"schema":"' + b"\xed\xa0\x80" + b'"}')
    with pytest.raises(validate.LedgerInputError) as excinfo:
        validate.validate_ledger_file(wtf8)
    assert excinfo.value.token == "ledger-encoding-invalid"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True

    # A lone surrogate arriving through a legal ASCII escape.
    escaped = tmp_path / "escaped.json"
    escaped.write_text('{"schema":"\\ud800"}', encoding="utf-8")
    with pytest.raises(schema.LedgerError) as excinfo:
        validate.validate_ledger_file(escaped)
    assert excinfo.value.token == "string-not-encodable"

    # Why the flag matters: with ensure_ascii=True the canonical form does NOT
    # crash, and with ensure_ascii=False the identical value raises. The
    # refusal is defence for a flag that must never be relaxed.
    lone = json.loads('"\\ud800"')
    assert sup.has_lone_surrogate(lone)
    assert sup.canonical_bytes({"k": lone}) == b'{"k":"\\ud800"}'
    with pytest.raises(UnicodeEncodeError):
        json.dumps({"k": lone}, ensure_ascii=False).encode("utf-8")
    # A surrogate PAIR is recombined by the parser and is ordinary text.
    assert not sup.has_lone_surrogate(json.loads('"\\ud83d\\ude00"'))


def test_gv7_s_066_the_refusal_classes_and_exit_codes_are_frozen(tmp_path):
    """A content refusal must never be satisfied by a path refusal."""
    schema = sup.require_schema()
    validate = sup.require_validate()
    stage_classes = (
        validate.LedgerPathError,
        validate.LedgerCeilingError,
        validate.LedgerInputError,
    )
    assert len(set(stage_classes)) == 3
    for stage_class in stage_classes:
        assert issubclass(stage_class, schema.LedgerError), stage_class.__name__
        for other in stage_classes:
            if other is not stage_class:
                assert not issubclass(stage_class, other), (
                    stage_class.__name__,
                    other.__name__,
                )
    assert not issubclass(schema.LedgerError, AssertionError)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert validate.main([str(sup.LEDGER_PATH)]) == 0
    assert validate.main([str(invalid)]) == 1
    with pytest.raises(SystemExit) as systemexit:
        validate.main([])
    assert systemexit.value.code == 2
    with pytest.raises(SystemExit) as systemexit:
        validate.main([str(invalid), str(invalid)])
    assert systemexit.value.code == 2


def test_gv7_s_068_the_production_refusal_vocabulary_covers_every_named_token():
    """A token the controls demand but the implementation never defines is a
    contract the implementation did not meet."""
    schema = sup.require_schema()
    tokens = set(schema.REFUSAL_TOKENS)
    missing = sorted(set(sup.REQUIRED_REFUSAL_TOKENS) - tokens)
    assert not missing, missing
    assert len(sup.REQUIRED_REFUSAL_TOKENS) == len(set(sup.REQUIRED_REFUSAL_TOKENS))


def test_gv7_s_069_a_refusal_is_byte_identical_under_a_hostile_environment(
    tmp_path, monkeypatch, capsys
):
    """No flag, configuration or environment variable alters refusal content."""
    validate = sup.require_validate()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    assert validate.main([str(invalid)]) == 1
    baseline = capsys.readouterr()
    assert baseline.out == "", "a refusal emits nothing on stdout"
    assert baseline.err.count("\n") == 1, baseline.err
    assert baseline.err.strip() in set(sup.require_schema().REFUSAL_TOKENS)

    for name in ("GV7_VERBOSE", "GV7_DEBUG", "PYTHONVERBOSE", "PYTHONDEVMODE"):
        monkeypatch.setenv(name, "1")
    assert validate.main([str(invalid)]) == 1
    hostile = capsys.readouterr()
    assert hostile.out == baseline.out
    assert hostile.err == baseline.err


def test_gv7_s_070_a_relative_path_is_screened_against_the_current_directory(
    tmp_path, monkeypatch
):
    """Every spelling of one file under a redirecting directory refuses alike.

    Reproduced against the present implementation: ``ledger.json`` supplied
    from inside a junction is ACCEPTED, while ``.\\ledger.json`` supplied from
    the same place is refused ``path-symlink-refused``. Both name the same
    bytes behind the same junction, so the difference is an incomplete ancestor
    walk, not a decision to scope the rule to absolute paths --
    ``ntpath.dirname("ledger.json")`` is empty, the walk stops after one entry,
    and the current directory is never inspected while ``open`` resolves
    straight through it.

    The fixture is a real directory junction, unprivileged and bounded to
    ``tmp_path``. ``sup.make_reparse_directory`` raises rather than skipping if
    no mechanism exists, so a platform that cannot build one fails loudly and
    never manufactures a pass.
    """
    validate = sup.require_validate()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "ledger.json").write_text("{}", encoding="utf-8")
    nested = real_dir / "nested"
    nested.mkdir()
    (nested / "ledger.json").write_text("{}", encoding="utf-8")

    link_dir = tmp_path / "linked"
    mechanism = sup.make_reparse_directory(link_dir, real_dir)
    assert sup.is_refused_reparse_point(link_dir), mechanism
    assert not sup.is_refused_reparse_point(real_dir)

    spellings = (
        ("absolute, through the junction", tmp_path,
         str(link_dir / "ledger.json")),
        ("relative, junction component present", tmp_path,
         os.path.join("linked", "ledger.json")),
        ("bare filename, from inside the junction", link_dir, "ledger.json"),
        ("dot-relative, from inside the junction", link_dir,
         os.path.join(".", "ledger.json")),
        ("nested relative, from inside the junction", link_dir,
         os.path.join("nested", "ledger.json")),
    )
    escaped = []
    for label, cwd, supplied in spellings:
        monkeypatch.chdir(cwd)
        try:
            validate.validate_ledger_file(supplied)
        except validate.LedgerPathError as error:
            if error.token != "path-symlink-refused":
                escaped.append((label, f"wrong token {error.token}"))
            continue
        except validate.LedgerError as error:
            # The path stage passed and a later stage stopped it, so the
            # redirection was followed.
            escaped.append((label, f"path accepted; stopped later at {error.token}"))
            continue
        escaped.append((label, "accepted outright"))
    assert not escaped, escaped


def test_gv7_s_071_every_refusal_helper_is_pinned_not_only_the_first():
    """All four helpers, by the same executable pin, with per-shape negatives."""
    sources = {
        name: sup.require_file(sup.LAB_DIR / name, name)
        for name in sup.PRODUCTION_MODULES
    }
    defining = defining_module_of(sources)

    # The matcher discriminates, proved on self-contained fixtures BEFORE it is
    # pointed at anything real. Every mutation is applied to every helper.
    for helper, signature, body in sup.FROZEN_REFUSAL_HELPERS:
        arguments = signature.split("(", 1)[1].rsplit(")", 1)[0]
        raise_statement = body.strip()
        without_cause = raise_statement.replace(" from None", "")
        conforming = f"def {helper}({arguments}):\n    {raise_statement}\n"
        assert (
            frozen_helper_defect(
                {"m.py": conforming}, "m.py", helper, signature, body
            )
            is None
        ), helper
        for label, template, fragment in HELPER_MUTATIONS:
            source = template.format(
                h=helper, a=arguments, r=raise_statement, n=without_cause
            )
            defect = frozen_helper_defect(
                {"m.py": source}, "m.py", helper, signature, body
            )
            assert defect is not None, f"{helper}: {label}: accepted"
            assert fragment in defect, (helper, label, defect)

    # A helper defined in a module other than the defining one is not
    # demonstrably the helper the refusals call.
    for helper, signature, body in sup.FROZEN_REFUSAL_HELPERS:
        arguments = signature.split("(", 1)[1].rsplit(")", 1)[0]
        elsewhere = {
            "__init__.py": "def validate_ledger(payload):\n    pass\n",
            "schema.py": f"def {helper}({arguments}):\n    {body.strip()}\n",
        }
        defect = frozen_helper_defect(elsewhere, "__init__.py", helper, signature, body)
        assert defect and "not in __init__.py" in defect, (helper, defect)

    # The production definitions themselves.
    for helper, signature, body in sup.FROZEN_REFUSAL_HELPERS:
        defect = frozen_helper_defect(sources, defining, helper, signature, body)
        assert defect is None, defect


#: Each pair violates two stages. The token must name the EARLIER stage,
#: wherever in the document that fault sits. Every fault is also checked alone,
#: so a pair that reports the wrong stage cannot be excused as a fixture that
#: never triggered.
STAGE_ORDER_PAIRS = (
    (
        "stage 4 and stage 6 within one record",
        (("claims", 0, "evidence_basis", 5), ("claims", 0, "attribution_class", "bogus")),
        "type-not-exact",
    ),
    (
        "stage 4 in a LATER record, stage 6 in an EARLIER one",
        (("batches", 40, "batch_ordinal", True), ("batches", 0, "batch_kind", "bogus")),
        "type-not-exact",
    ),
    (
        "stage 5 in a LATER record, stage 6 in an EARLIER one",
        (("claims", 5, "an_undeclared_probe", 1), ("claims", 0, "attribution_class", "bogus")),
        "undeclared-key",
    ),
    (
        "stage 4 in sources, stage 6 in batches",
        (("sources", 60, "supplied_title", 1.0), ("batches", 0, "batch_kind", "bogus")),
        "float-refused",
    ),
    (
        "stage 4 and stage 5 within one record",
        (("claims", 0, "evidence_basis", 5), ("claims", 0, "an_undeclared_probe", 1)),
        "type-not-exact",
    ),
    (
        "stage 4 in a LATER record, stage 5 in an EARLIER one",
        (("claims", 9, "evidence_basis", 5), ("claims", 0, "an_undeclared_probe", 1)),
        "type-not-exact",
    ),
    (
        "stage 4 in batches, stage 6 in sources",
        (("batches", 40, "batch_ordinal", True), ("sources", 0, "retrieval_state", "bogus")),
        "type-not-exact",
    ),
)

#: The token each single fault must produce on its own.
STAGE_ORDER_SINGLES = {
    ("claims", 0, "evidence_basis", 5): "type-not-exact",
    ("claims", 0, "attribution_class", "bogus"): "enum-value-invalid",
    ("batches", 40, "batch_ordinal", True): "type-not-exact",
    ("batches", 0, "batch_kind", "bogus"): "enum-value-invalid",
    ("claims", 5, "an_undeclared_probe", 1): "undeclared-key",
    ("sources", 60, "supplied_title", 1.0): "float-refused",
    ("sources", 0, "retrieval_state", "bogus"): "enum-value-invalid",
    ("claims", 9, "evidence_basis", 5): "type-not-exact",
    ("claims", 0, "an_undeclared_probe", 1): "undeclared-key",
}


def apply_faults(ledger, faults):
    payload = json.loads(json.dumps(ledger))
    for collection, index, field, value in faults:
        payload[collection][index][field] = value
    return payload


def test_gv7_s_072_the_earliest_stage_wins_across_the_whole_document():
    """"Earliest applicable stage" ranges over the payload, not over one record.

    A validator that walks record by record, running every stage inside each
    record before moving on, inverts the rule for every pair of faults that
    happens to sit in that order: a stage-6 vocabulary fault in the first
    record outruns a stage-4 exact-type fault in the last. The token then
    reports the traversal rather than the fault.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    # Each fault alone first, so a pair cannot pass by never triggering.
    for fault, token in sorted(STAGE_ORDER_SINGLES.items()):
        refuse(schema, apply_faults(ledger, (fault,)), token)

    for label, faults, token in STAGE_ORDER_PAIRS:
        payload = apply_faults(ledger, faults)
        with pytest.raises(schema.LedgerError) as excinfo:
            schema.validate_ledger(payload)
        assert excinfo.value.token == token, (label, token, excinfo.value.token)


def test_gv7_s_073_the_staged_token_is_identical_under_every_execution_mode():
    """Determinism, separately from correctness.

    This pins that the token does not depend on hash seed or optimisation
    level. It deliberately asserts only that every mode agrees -- which stage
    ought to win is GV7-S-072's question, and conflating the two would let a
    wrong-but-stable answer look like two passing controls.
    """
    ledger = sup.require_ledger()
    payload = apply_faults(ledger, STAGE_ORDER_PAIRS[0][1])
    document = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    script = (
        "import json,sys\n"
        "import experiments.general_v7_ledger as core\n"
        "payload = json.loads(sys.stdin.buffer.read().decode('utf-8'))\n"
        "try:\n"
        "    core.validate_ledger(payload)\n"
        "    sys.stdout.write('ACCEPTED')\n"
        "except core.LedgerError as error:\n"
        "    sys.stdout.write(error.token)\n"
    )
    outcomes = set()
    for seed in ("0", "1", "12345"):
        for flags in ([], ["-O"], ["-OO"]):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONPATH"] = str(sup.REPO_ROOT)
            completed = subprocess.run(
                [sys.executable, *flags, "-c", script],
                input=document,
                capture_output=True,
                env=environment,
                cwd=str(sup.REPO_ROOT),
                check=False,
            )
            assert completed.returncode == 0, completed.stderr.decode(
                "utf-8", "replace"
            )
            outcomes.add(completed.stdout.decode("utf-8"))
    assert len(outcomes) == 1, sorted(outcomes)
    # And a refusal actually happened. Asserting only that nine modes agree
    # would pass on an implementation that accepts the doubly-faulted payload
    # in all nine, which pins nothing at all.
    outcome = outcomes.pop()
    assert outcome != "ACCEPTED", "the doubly-faulted payload was accepted"
    assert outcome in sup.REQUIRED_REFUSAL_TOKENS, outcome
