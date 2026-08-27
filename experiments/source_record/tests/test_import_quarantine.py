"""Laboratory-local forward import quarantine.

Scope is deliberately narrow: this control scans **only**
``experiments/source_record/**``. It never scans the repository generally, and
it never reads a file outside this laboratory.

The complementary *reverse* guard — proving no maintained production module
imports this laboratory — is **deferred**. It would require a repository-wide
scan surface that has not been defined. See CONTRACT.md section 3c. It is not
claimed here, and this file must never be widened to stand in for it.

Every scan is purely static: modules are parsed with ``ast`` and never
executed.

Control ids SR-Q-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import ast
import pathlib

from experiments.source_record.tests import _support as sup

#: Standard-library roots a laboratory production module may import, plus the
#: laboratory's own package. Nothing else.
PRODUCTION_ALLOWED = frozenset(
    {
        "__future__",
        "argparse",
        "datetime",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "stat",
        "sys",
        "typing",
        "unicodedata",
        "msvcrt",
        "_winapi",
    }
)

#: Additional roots the acceptance suite itself may import.
TESTS_EXTRA_ALLOWED = frozenset(
    {
        "ast",
        "copy",
        "importlib",
        "inspect",
        "pytest",
        "socket",
        "subprocess",
    }
)

LAB_PACKAGE_PREFIX = "experiments.source_record"

#: Import-name fragments a production module may never carry, whatever the
#: allow-list says. The allow-list is the control; this is a second fence.
PRODUCTION_FORBIDDEN_FRAGMENTS = (
    "tech_ledger",
    "swarm",
    "scripts.",
    "agent_backends",
    "telemetry",
    "nextness",
    "medusa",
    "orchestrat",
    "subprocess",
    "socket",
    "http",
    "urllib",
    "requests",
    "importlib",
    "numpy",
    "pytest",
)

DYNAMIC_IMPORT_NAMES = ("__import__", "import_module")


def import_roots(path: pathlib.Path) -> set[str]:
    """Static import roots of one module. Nothing is imported or executed."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module or "")
    return roots


def function_level_imports(path: pathlib.Path) -> list[str]:
    """Import statements that sit inside a function body."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Import):
                found.extend(alias.name for alias in inner.names)
            elif isinstance(inner, ast.ImportFrom):
                found.append(inner.module or "")
    return found


def dynamic_import_calls(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = None
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            name = target.attr
        if name in DYNAMIC_IMPORT_NAMES:
            found.append(name)
    return found


def violations(path: pathlib.Path, allowed: frozenset[str]) -> list[str]:
    found: list[str] = []
    for root in sorted(import_roots(path)):
        if root.startswith(LAB_PACKAGE_PREFIX):
            continue
        if root not in allowed:
            found.append(root)
    return found


# --------------------------------------------------------------------------
# Production modules
# --------------------------------------------------------------------------


def test_sr_q_001_every_laboratory_production_module_imports_stdlib_only():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        found = violations(path, PRODUCTION_ALLOWED)
        assert not found, f"{path.name}: {found}"


def test_sr_q_002_no_production_module_carries_a_forbidden_import_fragment():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        for root in sorted(import_roots(path)):
            for fragment in PRODUCTION_FORBIDDEN_FRAGMENTS:
                assert fragment not in root, (path.name, root, fragment)


def test_sr_q_003_no_production_module_uses_a_dynamic_import_mechanism():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        assert not dynamic_import_calls(path), path.name
        deferred = [
            name
            for name in function_level_imports(path)
            if not name.startswith(LAB_PACKAGE_PREFIX)
        ]
        assert not deferred, (path.name, deferred)


# --------------------------------------------------------------------------
# Tests tree
# --------------------------------------------------------------------------


def test_sr_q_004_every_suite_module_imports_only_its_declared_allowance():
    modules = sup.lab_test_modules()
    assert modules, "the tests-tree scan examined nothing"
    allowed = PRODUCTION_ALLOWED | TESTS_EXTRA_ALLOWED
    for path in modules:
        found = violations(path, allowed)
        assert not found, f"{path.name}: {found}"


def test_sr_q_005_the_scans_are_static_and_never_execute_a_module():
    """The scan helpers parse; they contain no exec, eval, or import call."""
    this_module = pathlib.Path(__file__).resolve()
    tree = ast.parse(this_module.read_text(encoding="utf-8"))
    banned = {"exec", "eval", "compile", "runpy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned, node.func.id
    assert "importlib" not in import_roots(this_module)


# --------------------------------------------------------------------------
# Discovery controls
# --------------------------------------------------------------------------


def test_sr_q_006_discovery_examines_a_module_that_did_not_exist_before(tmp_path):
    """Synthetic control: a newly introduced module is scanned automatically."""
    fake_lab = tmp_path / "fake_lab"
    (fake_lab / "tests").mkdir(parents=True)
    (fake_lab / "helpers.py").write_text("import json\n", encoding="utf-8")
    (fake_lab / "leaky.py").write_text("import urllib.request\n", encoding="utf-8")
    (fake_lab / "tests" / "test_x.py").write_text(
        "import pytest\n", encoding="utf-8"
    )
    (fake_lab / "__pycache__").mkdir()
    (fake_lab / "__pycache__" / "junk.py").write_text(
        "import socket\n", encoding="utf-8"
    )

    discovered = sorted(
        path
        for path in fake_lab.rglob("*.py")
        if "__pycache__" not in path.parts
        and (fake_lab / "tests") not in path.parents
    )
    names = [path.name for path in discovered]
    assert names == ["helpers.py", "leaky.py"]
    assert violations(fake_lab / "helpers.py", PRODUCTION_ALLOWED) == []
    assert violations(fake_lab / "leaky.py", PRODUCTION_ALLOWED) == [
        "urllib.request"
    ]


def test_sr_q_007_discovery_is_deterministic_and_excludes_bytecode_caches():
    production = sup.lab_production_modules()
    tests = sup.lab_test_modules()
    assert production == sup.lab_production_modules()
    assert tests == sup.lab_test_modules()
    for path in production + tests:
        assert "__pycache__" not in path.parts


def test_sr_q_008_the_suite_scan_examined_a_non_zero_expected_surface():
    modules = sup.lab_test_modules()
    names = {path.name for path in modules}
    expected = {
        "__init__.py",
        "_support.py",
        "test_schema.py",
        "test_records.py",
        "test_validate_cli.py",
        "test_import_quarantine.py",
        "test_controls_manifest.py",
    }
    assert expected <= names, sorted(names)
    assert len(modules) >= len(expected)
    for path in modules:
        assert sup.LAB_DIR in path.parents, path
