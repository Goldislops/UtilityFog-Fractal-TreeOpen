"""Two-way static import quarantine (S0 §3 / §11.8).

Lab side: AST import-graph analysis — no lab module may import anything under
``scripts`` or any network module, and no dynamic-import escape hatch may
appear in source text. Production side: source-text scan — nothing under the
maintained ``scripts/`` or ``tests/`` trees may reference the lab.
"""

import ast
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]

FORBIDDEN_ROOTS = {
    "scripts", "socket", "urllib", "http", "requests", "ftplib",
    "telnetlib", "subprocess",
}
DYNAMIC_IMPORT_TOKENS = ("importlib", "__import__")


def lab_sources():
    return sorted(LAB_DIR.rglob("*.py"))


def test_lab_has_expected_manifest():
    names = sorted(p.relative_to(LAB_DIR).as_posix() for p in lab_sources())
    assert names == [
        "__init__.py", "detector.py", "fixtures.py", "schema.py",
        "tests/__init__.py", "tests/test_fixtures.py",
        "tests/test_import_quarantine.py", "tests/test_properties.py",
    ]


def test_lab_imports_cross_no_quarantine_boundary():
    for path in lab_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                roots = [(node.module or "").split(".")[0]]
            for root in roots:
                assert root not in FORBIDDEN_ROOTS, f"{path}: imports {root}"


def test_lab_has_no_dynamic_import_escape():
    for path in lab_sources():
        text = path.read_text(encoding="utf-8")
        if path.name == "test_import_quarantine.py":
            continue  # this file names the tokens in order to ban them
        for token in DYNAMIC_IMPORT_TOKENS:
            assert token not in text, f"{path}: contains {token}"


def test_production_never_references_the_lab():
    for tree in ("scripts", "tests"):
        for path in sorted((REPO_ROOT / tree).rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "swarm_hunter_lab" not in text, f"{path} references the lab"
