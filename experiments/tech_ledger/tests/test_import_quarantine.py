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
    "os",
    "pathlib",
    "re",
    "sys",
    "typing",
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


def test_lab_modules_import_stdlib_only():
    for module in ("__init__.py", "schema.py", "validate.py"):
        imports = _imports_of(_LAB_DIR / module)
        unexpected = imports - _ALLOWED_IMPORTS
        assert not unexpected, f"{module}: unexpected imports {sorted(unexpected)}"
        for name in imports:
            for fragment in _FORBIDDEN_FRAGMENTS:
                assert fragment not in name, f"{module}: forbidden import {name}"


def test_lab_tests_import_stdlib_pytest_and_lab_only():
    for path in sorted((_LAB_DIR / "tests").glob("*.py")):
        imports = _imports_of(path)
        allowed = _ALLOWED_IMPORTS | {
            "pytest",
            "experiments.tech_ledger",
            "experiments.tech_ledger.tests",
        }
        unexpected = {
            name
            for name in imports
            if name not in allowed
            and not name.startswith("experiments.tech_ledger")
        }
        assert not unexpected, f"{path.name}: unexpected imports {sorted(unexpected)}"


def test_no_production_module_imports_the_lab():
    # Reverse quarantine: maintained production Python trees contain no
    # reference to the lab package. Static text scan (cheap, total).
    production_trees = ("scripts", "agent", "vis")
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
