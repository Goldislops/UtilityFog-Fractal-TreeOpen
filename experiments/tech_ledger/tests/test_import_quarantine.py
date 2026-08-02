"""Bidirectional static import quarantine for the tech-ledger lab.

The lab imports only the Python standard library (plus its own modules);
no maintained production module imports the lab; the entry JSON files are
data only. All checks are static -- nothing outside this directory tree is
imported or executed.
"""

from __future__ import annotations

import ast
import pathlib

_LAB_DIR = pathlib.Path(__file__).resolve().parent.parent
_REPO_ROOT = _LAB_DIR.parent.parent

#: The complete import allowlist for lab modules: standard library only,
#: plus the lab's own package.
_ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "ast",
    "copy",
    "datetime",
    "json",
    "msvcrt",  # stdlib: Windows directory-binding handle ownership
    "os",
    "pathlib",
    "re",
    "stat",
    "sys",
    "typing",
    "_winapi",  # stdlib: Windows directory-binding primitive
    "experiments.tech_ledger.schema",
    "experiments.tech_ledger.validate",
}

_FORBIDDEN_FRAGMENTS = (
    "scripts.",
    "agent.",
    "vis.",
    "ca.",
    "crates",
    "telemetry",
    "nextness",
    "medusa",
    "event_bus",
    "orchestrat",
    "tuning",
    "swarm_hunter",
    "theory_sandbox",
    "subprocess",
    "socket",
    "http",
    "urllib",
    "requests",
    "zmq",
    "ollama",
    "numpy",
)


def _imports_of(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def _non_test_lab_modules(lab_root: pathlib.Path) -> list[pathlib.Path]:
    """Deterministic discovery of every non-test Python module under the
    lab: any future module (e.g. helpers.py) is examined automatically.
    The tests tree is excluded here and scanned through its own separate
    allowlist below."""
    tests_root = lab_root / "tests"
    return sorted(
        path
        for path in lab_root.rglob("*.py")
        if tests_root not in path.parents
        and "__pycache__" not in path.parts
    )


def _forward_violations(path: pathlib.Path) -> list[str]:
    """Every import of a lab module that falls outside the standard-library
    + lab-local allowlist, or that matches a forbidden production/network
    fragment. Purely static: nothing is imported."""
    violations: list[str] = []
    for name in _imports_of(path):
        if name not in _ALLOWED_IMPORTS:
            violations.append(name)
            continue
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in name:
                violations.append(name)
    return violations


def test_lab_modules_import_stdlib_only():
    modules = _non_test_lab_modules(_LAB_DIR)
    names = {path.name for path in modules}
    # Discovery must at minimum see today's modules; any future module is
    # included automatically by construction.
    assert {"__init__.py", "schema.py", "validate.py"} <= names, names
    for path in modules:
        violations = _forward_violations(path)
        assert not violations, f"{path.name}: {violations}"


def test_forward_discovery_examines_new_modules(tmp_path):
    # Synthetic positive control: a NEWLY INTRODUCED non-test module with
    # a production import must fail the forward guard -- proving the
    # discovery actually examines modules that did not exist when the
    # guard was written.
    fake_lab = tmp_path / "fake_lab"
    (fake_lab / "tests").mkdir(parents=True)
    (fake_lab / "__init__.py").write_bytes(b"import json\n")
    (fake_lab / "helpers.py").write_bytes(b"import scripts.event_bus\n")
    (fake_lab / "tests" / "test_x.py").write_bytes(b"import subprocess\n")
    discovered = {p.name for p in _non_test_lab_modules(fake_lab)}
    assert discovered == {"__init__.py", "helpers.py"}  # tests tree excluded
    flagged = {
        p.name: _forward_violations(p) for p in _non_test_lab_modules(fake_lab)
    }
    assert flagged["helpers.py"] == ["scripts.event_bus"]
    assert flagged["__init__.py"] == []
    # Negative control: a clean new module passes.
    (fake_lab / "helpers.py").write_bytes(b"import pathlib\n")
    assert all(
        not _forward_violations(p) for p in _non_test_lab_modules(fake_lab)
    )


def _test_tree_modules(tests_root: pathlib.Path) -> list[pathlib.Path]:
    """Deterministic RECURSIVE discovery of every Python module under the
    tests tree: a future nested module (e.g. ``tests/unit/test_helper.py``)
    is examined automatically, exactly like the non-test discovery above.
    Purely static -- nothing is imported or executed."""
    return sorted(
        path
        for path in tests_root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_lab_tests_import_stdlib_pytest_and_lab_only():
    modules = _test_tree_modules(_LAB_DIR / "tests")
    names = {path.name for path in modules}
    # Discovery must at minimum see today's modules; any future nested
    # module is included automatically by construction.
    assert {
        "__init__.py",
        "test_import_quarantine.py",
        "test_validate_cli.py",
    } <= names, names
    for path in modules:
        imports = _imports_of(path)
        allowed = _ALLOWED_IMPORTS | {
            "pytest",
            "_winapi",  # Windows junction creation in one capability test
            "experiments.tech_ledger",
            "experiments.tech_ledger.tests",
        }
        unexpected = {
            name
            for name in imports
            if name not in allowed
            and not name.startswith("experiments.tech_ledger")
        }
        rel = path.relative_to(_LAB_DIR).as_posix()  # stable, lab-relative
        assert not unexpected, f"{rel}: unexpected imports {sorted(unexpected)}"


def test_tests_tree_discovery_examines_nested_modules(tmp_path):
    # Synthetic positive control: a NESTED test module with a forbidden
    # production import must be discovered and rejected -- proving the
    # tests-tree scan cannot be evaded by directory depth. Purely
    # static; nothing is imported or executed.
    fake_tests = tmp_path / "tests"
    (fake_tests / "unit").mkdir(parents=True)
    (fake_tests / "test_direct.py").write_bytes(b"import json\n")
    (fake_tests / "unit" / "test_helper.py").write_bytes(
        b"import scripts.event_bus\n"
    )
    (fake_tests / "unit" / "__pycache__").mkdir()
    (fake_tests / "unit" / "__pycache__" / "junk.py").write_bytes(
        b"import socket\n"
    )

    discovered = _test_tree_modules(fake_tests)
    rels = [p.relative_to(fake_tests).as_posix() for p in discovered]
    # Deterministic order; nested module included; __pycache__ excluded.
    assert rels == ["test_direct.py", "unit/test_helper.py"]
    assert discovered == _test_tree_modules(fake_tests)  # repeatable

    flagged = {
        p.relative_to(fake_tests).as_posix(): sorted(
            name for name in _imports_of(p) if name not in _ALLOWED_IMPORTS
        )
        for p in discovered
    }
    assert flagged["unit/test_helper.py"] == ["scripts.event_bus"]
    assert flagged["test_direct.py"] == []  # direct children stay covered
    # Negative control: a clean nested module passes.
    (fake_tests / "unit" / "test_helper.py").write_bytes(b"import pathlib\n")
    assert all(
        not [n for n in _imports_of(p) if n not in _ALLOWED_IMPORTS]
        for p in _test_tree_modules(fake_tests)
    )


def test_no_production_module_imports_the_lab():
    # Lab-local SNAPSHOT of the reverse direction over the highest-risk
    # production trees. The CONTINUOUS, repository-wide reverse guard is
    # tests/test_tech_ledger_reverse_quarantine.py in the maintained main
    # battery (ordinary repository CI), which scans every maintained
    # Python location automatically -- this lab-local check is a fast
    # companion, not the enforcement boundary.
    production_trees = ("scripts", "agent", "agents", "vis")
    offenders: list[str] = []
    for tree_name in production_trees:
        tree = _REPO_ROOT / tree_name
        if not tree.is_dir():
            continue
        for path in tree.rglob("*.py"):
            if "tech_ledger" in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert offenders == []


def test_entries_are_data_only():
    entries_dir = _LAB_DIR / "entries"
    assert entries_dir.is_dir()
    non_json = [p.name for p in entries_dir.iterdir() if not p.name.endswith(".json")]
    assert non_json == []  # no __init__.py, no executable configuration
    for path in entries_dir.glob("*.json"):
        head = path.read_bytes()[:1]
        assert head == b"{", f"{path.name}: entries must be JSON objects"


def test_no_network_or_subprocess_anywhere_in_lab():
    for path in sorted(_LAB_DIR.rglob("*.py")):
        imports = _imports_of(path)
        for name in imports:
            for fragment in ("subprocess", "socket", "http", "urllib", "requests", "zmq"):
                assert fragment not in name, f"{path.name}: {name}"
