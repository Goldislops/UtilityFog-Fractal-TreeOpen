"""Continuous reverse import-quarantine guard for experiments/tech_ledger.

Lives in the MAINTAINED tests/ battery so it runs on ordinary repository
CI: a production-only change can never bypass the reverse quarantine
merely because the lab's path-scoped workflow did not trigger. (The
forward direction -- the lab importing only the standard library -- is
enforced lab-locally by experiments/tech_ledger/tests/ under the
tech-ledger workflow.)

The detector resolves BOTH absolute and relative imports against each
scanned file's repository package context (namespace-package aware -- no
``__init__.py`` is required on any ancestor), so ``from .. import
tech_ledger`` inside the ``experiments`` tree is caught exactly like
``import experiments.tech_ledger``. This guard imports NO tech-ledger
module: it is a pure static scan.
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

_LAB_PACKAGE = ("experiments", "tech_ledger")

#: Clearly non-source / generated / vendor locations, excluded by NAME at
#: any depth. Everything else with a .py suffix is scanned automatically
#: -- including the plural agents tree, root-level Python files and any
#: future maintained location.
_EXCLUDED_DIR_NAMES = {
    ".git",
    ".claude",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".eggs",
    "build",
    "dist",
    "site-packages",
}


def _iter_maintained_python_files():
    lab_root = _REPO_ROOT / "experiments" / "tech_ledger"
    stack = [_REPO_ROOT]
    while stack:
        directory = stack.pop()
        for child in directory.iterdir():
            if child.is_dir():
                if child.name in _EXCLUDED_DIR_NAMES:
                    continue
                if child == lab_root:
                    continue  # the lab itself is outside this guard's scope
                stack.append(child)
            elif child.suffix == ".py":
                yield child


def _package_context(module_relpath: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """The importing module's package, derived purely from its
    repository-relative path parts (namespace-package layout: no
    ``__init__.py`` is required anywhere).

    For an ordinary module ``experiments/sub/example.py`` the package is
    ``("experiments", "sub")``; for a package ``__init__.py`` the module
    IS the package, and relative level 1 refers to that same package --
    so ``experiments/sub/__init__.py`` also yields
    ``("experiments", "sub")``.
    """
    if module_relpath is None or not module_relpath:
        return None
    *dirs, filename = module_relpath
    if not filename.endswith(".py"):
        return None
    if filename == "__init__.py":
        return tuple(dirs)
    return tuple(dirs)


def _resolved_lab_imports(
    tree: ast.AST, module_relpath: tuple[str, ...] | None = None
) -> list[str]:
    """Every import statement that resolves to experiments.tech_ledger.

    Absolute forms need no path context. Relative forms
    (``ast.ImportFrom.level`` >= 1) are resolved against the importing
    module's package context per Python's rules: base package = the
    module's package with ``level - 1`` trailing components removed; a
    given ``from``-module appends to the base; with no ``from``-module,
    each alias appends to the base. A malformed or impossible level
    (reaching past the top of the tree) never crashes the scan -- it
    simply cannot resolve to the lab and is skipped.
    """
    package = _package_context(module_relpath)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = tuple(alias.name.split("."))
                if parts[: len(_LAB_PACKAGE)] == _LAB_PACKAGE:
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            if level == 0:
                base: tuple[str, ...] | None = ()
                module_parts = tuple(module.split(".")) if module else ()
            else:
                if package is None or level - 1 > len(package):
                    # No path context, or the level climbs past the top of
                    # the repository tree: cannot resolve to the lab.
                    continue
                base = package[: len(package) - (level - 1)]
                module_parts = tuple(module.split(".")) if module else ()
            resolved_module = base + module_parts
            if resolved_module[: len(_LAB_PACKAGE)] == _LAB_PACKAGE:
                dots = "." * level
                found.append(f"from {dots}{module} import ...")
                continue
            # ``from <pkg> import tech_ledger`` (absolute or relative):
            # an alias names the lab package itself when the resolved
            # parent is exactly ("experiments",).
            if resolved_module == _LAB_PACKAGE[:-1]:
                for alias in node.names:
                    if alias.name == _LAB_PACKAGE[-1]:
                        dots = "." * level
                        found.append(
                            f"from {dots}{module} import {alias.name}"
                        )
    return found


def _lab_imports_in(
    source: str, module_relpath: tuple[str, ...] | None = None
) -> list[str]:
    return _resolved_lab_imports(ast.parse(source), module_relpath)


def test_detector_absolute_positive_controls():
    assert _lab_imports_in("import experiments.tech_ledger")
    assert _lab_imports_in("import experiments.tech_ledger.schema")
    assert _lab_imports_in("from experiments.tech_ledger import schema")
    assert _lab_imports_in(
        "from experiments.tech_ledger.validate import validate_directory"
    )
    assert _lab_imports_in("from experiments import tech_ledger")


def test_detector_relative_positive_controls():
    # Explicit fake repository paths: the same syntax resolves to the lab
    # exactly when the importing file's package context makes it so.
    assert _lab_imports_in(
        "from . import tech_ledger", ("experiments", "example.py")
    )
    assert _lab_imports_in(
        "from .tech_ledger import schema", ("experiments", "example.py")
    )
    assert _lab_imports_in(
        "from .. import tech_ledger", ("experiments", "sub", "example.py")
    )
    assert _lab_imports_in(
        "from ..tech_ledger import validate", ("experiments", "sub", "example.py")
    )
    # Deeper nesting and submodule forms.
    assert _lab_imports_in(
        "from ...tech_ledger.schema import validate_entry",
        ("experiments", "sub", "deeper", "example.py"),
    )
    assert _lab_imports_in(
        "from ...tech_ledger import schema",
        ("experiments", "sub", "deeper", "example.py"),
    )
    # A package __init__.py: level 1 refers to the package itself.
    assert _lab_imports_in(
        "from .tech_ledger import schema", ("experiments", "__init__.py")
    )
    assert _lab_imports_in(
        "from ..tech_ledger import schema", ("experiments", "sub", "__init__.py")
    )


def test_detector_negative_controls():
    # Same relative syntax under an unrelated top-level package.
    assert not _lab_imports_in(
        "from . import tech_ledger", ("otherpkg", "example.py")
    )
    assert not _lab_imports_in(
        "from .tech_ledger import schema", ("otherpkg", "example.py")
    )
    assert not _lab_imports_in(
        "from .. import tech_ledger", ("otherpkg", "sub", "example.py")
    )
    # Neighbouring names never trip it.
    assert not _lab_imports_in(
        "from . import tech_ledgerish", ("experiments", "example.py")
    )
    assert not _lab_imports_in(
        "from ..other import tech_ledger", ("experiments", "sub", "example.py")
    )
    assert not _lab_imports_in("import experiments.theory_other")
    assert not _lab_imports_in("from experiments import swarm_hunter_lab")
    assert not _lab_imports_in("import tech_ledgerish")
    assert not _lab_imports_in(
        "from . import swarm_hunter_lab", ("experiments", "example.py")
    )
    # Strings and comments containing import-like text are not imports.
    assert not _lab_imports_in(
        's = "from experiments.tech_ledger import schema"\n'
        "# import experiments.tech_ledger\n",
        ("experiments", "example.py"),
    )
    # Impossible relative levels never crash and never match.
    assert not _lab_imports_in(
        "from " + "." * 12 + " import tech_ledger",
        ("experiments", "sub", "example.py"),
    )
    assert not _lab_imports_in("from . import tech_ledger", None)
    assert not _lab_imports_in("from . import tech_ledger", ())


def test_no_maintained_python_file_imports_the_lab():
    offenders: list[str] = []
    for path in _iter_maintained_python_files():
        relpath = path.relative_to(_REPO_ROOT).parts
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            hits = _lab_imports_in(source, relpath)
        except SyntaxError:
            # Unparseable legacy material cannot import anything at
            # runtime; it is outside this guard's claim.
            continue
        if hits:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}: {hits}")
    assert offenders == []
