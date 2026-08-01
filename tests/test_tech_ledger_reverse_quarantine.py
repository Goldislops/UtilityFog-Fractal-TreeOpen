"""Continuous reverse import-quarantine guard for experiments/tech_ledger.

Lives in the MAINTAINED tests/ battery so it runs on ordinary repository
CI: a production-only change can never bypass the reverse quarantine
merely because the lab's path-scoped workflow did not trigger. (The
forward direction -- the lab importing only the standard library -- is
enforced lab-locally by experiments/tech_ledger/tests/ under the
tech-ledger workflow.)

This guard imports NO tech-ledger module: it is a pure static scan.
"""

from __future__ import annotations

import ast
import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

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


def _lab_imports_in(source: str) -> list[str]:
    """Every import statement that reaches experiments.tech_ledger.

    Detects all three forms:
    ``import experiments.tech_ledger...``,
    ``from experiments.tech_ledger... import ...`` and
    ``from experiments import tech_ledger``.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "experiments.tech_ledger" or alias.name.startswith(
                    "experiments.tech_ledger."
                ):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "experiments.tech_ledger" or module.startswith(
                "experiments.tech_ledger."
            ):
                found.append(f"from {module} import ...")
            elif module == "experiments":
                for alias in node.names:
                    if alias.name == "tech_ledger":
                        found.append("from experiments import tech_ledger")
    return found


def test_detector_positive_controls():
    # The detector must catch every import form; a silent detector would
    # make the tree scan below meaningless.
    assert _lab_imports_in("import experiments.tech_ledger")
    assert _lab_imports_in("import experiments.tech_ledger.schema")
    assert _lab_imports_in("from experiments.tech_ledger import schema")
    assert _lab_imports_in(
        "from experiments.tech_ledger.validate import validate_directory"
    )
    assert _lab_imports_in("from experiments import tech_ledger")
    # Negative controls: neighbouring names must not trip it.
    assert not _lab_imports_in("import experiments.theory_other")
    assert not _lab_imports_in("from experiments import swarm_hunter_lab")
    assert not _lab_imports_in("import tech_ledgerish")


def test_no_maintained_python_file_imports_the_lab():
    offenders: list[str] = []
    for path in _iter_maintained_python_files():
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            hits = _lab_imports_in(source)
        except SyntaxError:
            # Unparseable legacy material cannot import anything at
            # runtime; it is outside this guard's claim.
            continue
        if hits:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}: {hits}")
    assert offenders == []
