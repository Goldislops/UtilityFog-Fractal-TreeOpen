"""The explicit control manifest and the meta-controls that guard the suite.

Every control authored for this phase is named in ``AUTHORED_CONTROLS``.
Adding or removing one requires an intentional manifest edit; a numeric test
count is never the acceptance claim, and the manifest is never padded to
reproduce an earlier total.

Nothing here claims a file is absent from the *repository*: this is a sparse
worktree. The forbidden-path control asserts that **this phase did not create**
the implementation surface, which is a fact about this commit.

Control ids GV7-M-NNN are declared below alongside every other control.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from experiments.general_v7_ledger.tests import _support as sup

AUTHORED_CONTROLS = {
    "test_contract.py": tuple(f"GV7-D-{n:03d}" for n in range(1, 28)),
    "test_ledger_structure.py": tuple(f"GV7-S-{n:03d}" for n in range(1, 45)),
    "test_inventory.py": tuple(f"GV7-I-{n:03d}" for n in range(1, 25)),
    "test_provenance.py": tuple(f"GV7-P-{n:03d}" for n in range(1, 27)),
    "test_controls_manifest.py": tuple(f"GV7-M-{n:03d}" for n in range(1, 17)),
}

#: This phase authors contract and tests only. None of these may be created here.
FORBIDDEN_IMPLEMENTATION_PATHS = (
    "__init__.py",
    "schema.py",
    "validate.py",
    "ledger.json",
    "BIBLIOGRAPHY.md",
    "INTAKE_REPORT.md",
    "README.md",
)

APPROVED_LABORATORY_PATHS = frozenset(
    {
        "CONTRACT.md",
        "tests/__init__.py",
        "tests/_support.py",
        "tests/test_contract.py",
        "tests/test_ledger_structure.py",
        "tests/test_inventory.py",
        "tests/test_provenance.py",
        "tests/test_controls_manifest.py",
    }
)

#: Roots the acceptance suite itself may import.
SUITE_ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "ast",
        "hashlib",
        "importlib",
        "json",
        "os",
        "pathlib",
        "re",
        "stat",
        "subprocess",
        "sys",
        "pytest",
    }
)

CONTROL_ID_PATTERN = re.compile(r"\Atest_gv7_([a-z])_([0-9]{3})_")


def control_id_of(function_name: str) -> str | None:
    match = CONTROL_ID_PATTERN.match(function_name)
    if match is None:
        return None
    return f"GV7-{match.group(1).upper()}-{match.group(2)}"


def control_ids_in_source(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            control_id = control_id_of(node.name)
            if control_id is not None:
                found.add(control_id)
    return found


def suite_modules() -> dict[str, pathlib.Path]:
    return {
        path.name: path
        for path in sorted(sup.TESTS_DIR.glob("*.py"))
        if path.name.startswith("test_")
    }


def test_gv7_m_001_every_declared_control_exists_in_its_declared_module():
    modules = suite_modules()
    assert modules, "the manifest scan examined nothing"
    for filename, declared in sorted(AUTHORED_CONTROLS.items()):
        path = modules.get(filename)
        assert path is not None, f"declared module missing: {filename}"
        present = control_ids_in_source(path.read_text(encoding="utf-8"))
        missing = sorted(set(declared) - present)
        assert not missing, f"{filename}: declared but absent {missing}"


def test_gv7_m_002_every_control_in_the_suite_is_declared_in_the_manifest():
    modules = suite_modules()
    assert modules, "the manifest scan examined nothing"
    for filename, path in sorted(modules.items()):
        declared = set(AUTHORED_CONTROLS.get(filename, ()))
        present = control_ids_in_source(path.read_text(encoding="utf-8"))
        undeclared = sorted(present - declared)
        assert not undeclared, f"{filename}: present but undeclared {undeclared}"


def test_gv7_m_003_no_declared_control_id_is_duplicated():
    seen: list[str] = []
    for declared in AUTHORED_CONTROLS.values():
        seen.extend(declared)
    assert len(seen) == len(set(seen))


def test_gv7_m_004_no_control_is_skipped_or_marked_expected_failure():
    modules = suite_modules()
    assert modules, "the marker scan examined nothing"
    banned = {"skip", "skipif", "xfail"}
    for filename, path in sorted(modules.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                for sub in ast.walk(decorator):
                    if isinstance(sub, ast.Attribute):
                        assert sub.attr not in banned, (filename, node.name)


def test_gv7_m_005_this_phase_created_no_implementation_file():
    for name in FORBIDDEN_IMPLEMENTATION_PATHS:
        assert not (sup.LAB_DIR / name).exists(), (
            f"this phase must not create {name}"
        )
    assert not (sup.LAB_DIR / "records").exists()
    assert not (sup.LAB_DIR / ".gitattributes").exists()


def test_gv7_m_006_the_tests_directory_holds_only_test_code_and_helpers():
    entries = sorted(sup.TESTS_DIR.iterdir())
    assert entries, "the tests-directory scan examined nothing"
    for entry in entries:
        if entry.name == "__pycache__":
            continue
        assert entry.is_file(), entry.name
        assert entry.suffix == ".py", entry.name
        assert entry.name == "__init__.py" or entry.name.startswith(
            ("test_", "_")
        ), entry.name


def test_gv7_m_007_the_laboratory_contains_exactly_the_approved_paths():
    present = {
        path.relative_to(sup.LAB_DIR).as_posix()
        for path in sup.LAB_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert present, "the path scan examined nothing"
    assert present == APPROVED_LABORATORY_PATHS, sorted(
        present ^ APPROVED_LABORATORY_PATHS
    )


def test_gv7_m_008_the_suite_imports_only_its_declared_allowance():
    modules = list(sorted(sup.TESTS_DIR.glob("*.py")))
    assert modules, "the import scan examined nothing"
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add(node.module or "")
        for root in sorted(roots):
            if root.startswith("experiments.general_v7_ledger"):
                continue
            assert root in SUITE_ALLOWED_IMPORTS, (path.name, root)


def test_gv7_m_009_the_canary_markers_are_non_empty_and_unique():
    assert len(sup.MARKERS) == len(set(sup.MARKERS))
    for marker in sup.MARKERS:
        assert marker and len(marker) >= 24
        assert marker.strip() == marker
        assert "do-not-echo" in marker


def test_gv7_m_010_the_frozen_constants_are_internally_consistent():
    assert (
        sup.EXPECTED_SOURCES_WITH_LOCATOR + sup.EXPECTED_SOURCES_WITHOUT_LOCATOR
        == sup.EXPECTED_SOURCES
    )
    assert len(sup.SOURCES_WITH_LOCATOR) == sup.EXPECTED_SOURCES_WITH_LOCATOR
    assert len(sup.SOURCES_WITHOUT_LOCATOR) == sup.EXPECTED_SOURCES_WITHOUT_LOCATOR
    assert len(sup.ALL_SOURCE_IDS) == sup.EXPECTED_SOURCES
    assert len(set(sup.ALL_SOURCE_IDS)) == sup.EXPECTED_SOURCES
    assert len(sup.ARTIFACT_IDS) == sup.EXPECTED_ARTIFACTS
    assert len(sup.ARTIFACT_BATCHES) == sup.EXPECTED_ARTIFACTS
    assert len(set(sup.ARTIFACT_BATCHES.values())) == sup.EXPECTED_ARTIFACTS
    assert sup.EXPECTED_RETRIEVED == 0
    assert sup.EXPECTED_VERIFIED_SOURCES == 0
    assert sup.EXPECTED_VERIFIED_CLAIMS == 0
    assert sup.EXPECTED_BRIDGE_RECORDS == 0
    for identifier in sup.ALL_SOURCE_IDS + sup.ARTIFACT_IDS:
        assert sup.ID_RE.match(identifier), identifier
    for batch_id in sup.ARTIFACT_BATCHES.values():
        assert sup.ID_RE.match(batch_id), batch_id


def test_gv7_m_011_no_frozen_total_is_declared_for_uncounted_collections():
    """Claims, relationships and unresolved issues have no invented total."""
    for name in dir(sup):
        if not name.startswith("EXPECTED_"):
            continue
        assert "CLAIMS" not in name or name == "EXPECTED_VERIFIED_CLAIMS", name
        assert "RELATIONSHIP" not in name, name
        assert "UNRESOLVED" not in name, name


def test_gv7_m_012_the_meta_controls_detect_the_removal_of_a_control():
    path = suite_modules()["test_contract.py"]
    source = path.read_text(encoding="utf-8")
    present = control_ids_in_source(source)
    assert "GV7-D-001" in present
    mutated = source.replace(
        "def test_gv7_d_001_the_contract_declares_the_frozen_identity",
        "def _control_removed_for_this_probe",
    )
    assert mutated != source
    reduced = control_ids_in_source(mutated)
    assert "GV7-D-001" not in reduced
    declared = set(AUTHORED_CONTROLS["test_contract.py"])
    assert sorted(declared - reduced) == ["GV7-D-001"]


# --------------------------------------------------------------------------
# Absence must be precise. A broken implementation must never be able to
# disguise itself as an unwritten one.
# --------------------------------------------------------------------------


def test_gv7_m_013_only_an_absent_file_is_reported_as_implementation_absent(tmp_path):
    with pytest.raises(AssertionError) as excinfo:
        sup.require_module("gv7_probe_missing_module", tmp_path / "absent.py")
    assert sup.IMPLEMENTATION_ABSENT in str(excinfo.value)

    with pytest.raises(AssertionError) as excinfo:
        sup.require_file(tmp_path / "absent.md", "absent.md")
    assert sup.IMPLEMENTATION_ABSENT in str(excinfo.value)

    with pytest.raises(AssertionError) as excinfo:
        sup.load_json_file(tmp_path / "absent.json", "absent.json")
    assert sup.IMPLEMENTATION_ABSENT in str(excinfo.value)


def test_gv7_m_014_an_import_broken_module_propagates_its_own_error(
    tmp_path, monkeypatch
):
    """A module that exists but fails to import is broken, not absent."""
    module_path = tmp_path / "gv7_probe_import_broken.py"
    module_path.write_text(
        "raise ImportError('synthetic broken import')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ImportError) as excinfo:
        sup.require_module("gv7_probe_import_broken", module_path)
    assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)
    assert "synthetic broken import" in str(excinfo.value)

    other = tmp_path / "gv7_probe_name_broken.py"
    other.write_text("import gv7_probe_no_such_module\n", encoding="utf-8")
    with pytest.raises(ModuleNotFoundError) as excinfo:
        sup.require_module("gv7_probe_name_broken", other)
    assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)


def test_gv7_m_015_a_malformed_ledger_propagates_a_parse_error(tmp_path):
    """A malformed document is malformed, not absent."""
    bad = tmp_path / "malformed.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        sup.load_json_file(bad, "malformed.json")
    assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)

    oversized = tmp_path / "oversized.json"
    oversized.write_text('{"n": ' + "9" * 6000 + "}", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        sup.load_json_file(oversized, "oversized.json")
    assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)


def test_gv7_m_016_missing_import_broken_and_malformed_stay_distinguishable(
    tmp_path, monkeypatch
):
    outcomes = {}

    try:
        sup.load_json_file(tmp_path / "absent.json", "absent.json")
    except BaseException as error:  # noqa: BLE001 - probe records the class
        outcomes["missing"] = type(error)

    broken = tmp_path / "gv7_probe_three_way.py"
    broken.write_text("raise ImportError('synthetic')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        sup.require_module("gv7_probe_three_way", broken)
    except BaseException as error:  # noqa: BLE001 - probe records the class
        outcomes["import_broken"] = type(error)

    malformed = tmp_path / "three_way.json"
    malformed.write_text("{not json", encoding="utf-8")
    try:
        sup.load_json_file(malformed, "three_way.json")
    except BaseException as error:  # noqa: BLE001 - probe records the class
        outcomes["malformed"] = type(error)

    assert set(outcomes) == {"missing", "import_broken", "malformed"}
    assert outcomes["missing"] is AssertionError
    assert issubclass(outcomes["import_broken"], ImportError)
    assert issubclass(outcomes["malformed"], ValueError)
    assert outcomes["import_broken"] is not AssertionError
    assert outcomes["malformed"] is not AssertionError
