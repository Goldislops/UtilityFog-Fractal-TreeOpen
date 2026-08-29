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
import json
import os
import pathlib
import re
import sys

import pytest

from experiments.general_v7_ledger.tests import _support as sup

def _ids(letter, *spans):
    numbers = []
    for low, high in spans:
        numbers.extend(range(low, high + 1))
    return tuple(f"GV7-{letter}-{number:03d}" for number in numbers)


#: Gaps are deliberate and are explained in ``sup.RETIRED_CONTROLS``. A retired
#: id is never reused and never renumbered: an auditor reading an earlier
#: handback must be able to look up what ``GV7-S-040`` was and find that it was
#: withdrawn, not find a different control wearing its name.
AUTHORED_CONTROLS = {
    "test_contract.py": _ids("D", (1, 39)),
    "test_ledger_structure.py": _ids("S", (1, 37), (43, 44), (46, 69)),
    "test_inventory.py": _ids("I", (1, 26)),
    "test_provenance.py": _ids("P", (1, 26)),
    "test_controls_manifest.py": _ids("M", (1, 25)),
}

#: Paths that belong to no admissible state, in either phase.
NEVER_AUTHORIZED_PATHS = ("records", ".gitattributes")

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
        "ntpath",
    }
)

CONTROL_ID_PATTERN = re.compile(r"\Atest_gv7_([a-z])_([0-9]{3})_")


def control_id_of(function_name: str) -> str | None:
    match = CONTROL_ID_PATTERN.match(function_name)
    if match is None:
        return None
    return f"GV7-{match.group(1).upper()}-{match.group(2)}"


def top_level_functions(module: ast.Module):
    return [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def control_ids_in_source(source: str) -> set[str]:
    """Only TOP-LEVEL definitions count, because only those are collected.

    ``ast.walk`` recurses into function and class bodies, so a control id on a
    nested ``def`` used to satisfy the manifest while pytest never collected
    it. A duplicate id in one module is likewise a fault: the second definition
    shadows the first at runtime, the first never runs, and a set-based census
    cannot see the difference.
    """
    module = ast.parse(source)
    seen: list[str] = []
    for node in top_level_functions(module):
        control_id = control_id_of(node.name)
        if control_id is not None:
            seen.append(control_id)
    assert len(seen) == len(set(seen)), f"duplicate control id in one module: {seen}"

    top_level = set(top_level_functions(module))
    for node in ast.walk(module):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node in top_level:
            continue
        assert control_id_of(node.name) is None, (
            f"control id on a definition pytest will never collect: {node.name}"
        )
    return set(seen)


def undeclared_test_functions(source: str) -> list[str]:
    """Collected ``test_*`` functions carrying no control id at all."""
    return sorted(
        node.name
        for node in top_level_functions(ast.parse(source))
        if node.name.startswith("test_") and control_id_of(node.name) is None
    )


def suite_modules() -> dict[str, pathlib.Path]:
    return {
        path.name: path
        for path in sorted(sup.TESTS_DIR.glob("*.py"))
        if path.name.startswith("test_")
    }


def test_gv7_m_001_every_declared_control_exists_in_its_declared_module():
    modules = suite_modules()
    assert modules, "the manifest scan examined nothing"
    # The module set is closed too: an entire unlisted module full of tests
    # would otherwise be invisible to a manifest that iterates the manifest.
    assert set(AUTHORED_CONTROLS) == set(modules), sorted(
        set(AUTHORED_CONTROLS) ^ set(modules)
    )
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
        source = path.read_text(encoding="utf-8")
        declared = set(AUTHORED_CONTROLS.get(filename, ()))
        present = control_ids_in_source(source)
        undeclared = sorted(present - declared)
        assert not undeclared, f"{filename}: present but undeclared {undeclared}"
        # A collected test with no control id contributes no id to either side
        # and would slip through the set arithmetic entirely.
        anonymous = undeclared_test_functions(source)
        assert not anonymous, f"{filename}: collected test with no id {anonymous}"


def test_gv7_m_003_no_declared_control_id_is_duplicated():
    seen: list[str] = []
    for declared in AUTHORED_CONTROLS.values():
        seen.extend(declared)
    assert len(seen) == len(set(seen))


BANNED_MARKS = frozenset({"skip", "skipif", "xfail"})
BANNED_CALLS = frozenset({"skip", "xfail", "importorskip", "exit"})


def test_gv7_m_004_nothing_in_the_suite_can_skip_or_expect_failure():
    """Decorators were the only shape the old scan could see.

    A runtime ``pytest.skip(...)`` call and a module-level ``pytestmark`` are
    the two shapes reached for under pressure, and both were invisible. So was
    a bare ``@skip`` imported by name. The scan now covers every ``.py`` file
    in the suite, not only ``test_*`` -- ``_support.py`` could have called
    ``pytest.skip(allow_module_level=True)`` and silenced everything.
    """
    modules = {path.name: path for path in sorted(sup.TESTS_DIR.glob("*.py"))}
    assert modules, "the marker scan examined nothing"
    for filename, path in sorted(modules.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                assert getattr(target, "id", None) != "pytestmark", filename
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    for element in ast.walk(decorator):
                        label = getattr(element, "attr", None) or getattr(
                            element, "id", None
                        )
                        assert label not in BANNED_MARKS, (filename, node.name, label)
            if isinstance(node, ast.Call):
                label = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", None)
                )
                assert label not in BANNED_CALLS, (filename, label)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "pytest"
            ):
                for alias in node.names:
                    assert alias.name not in BANNED_MARKS | BANNED_CALLS, (
                        filename,
                        alias.name,
                    )


def test_gv7_m_005_the_implementation_surface_is_absent_or_complete():
    """Never a partial surface -- and never an assertion that it stays absent.

    The old control asserted every implementation file was missing, so it could
    only be made green by deleting it. It also used ``Path.exists()``, which
    swallows ``PermissionError`` into a bare ``False``: a present-but-unreadable
    ``schema.py`` read as "this phase created nothing", the exact false green
    that CONTRACT.md section 12 and ``GV7-M-013``..``GV7-M-022`` exist to
    eliminate. Both defects are gone. Git history carries the evidence that the
    controls preceded the implementation.
    """
    present = [
        name
        for name in sup.IMPLEMENTATION_PATHS
        if not sup.entry_is_absent(sup.LAB_DIR / name)
    ]
    missing = [
        name
        for name in sup.IMPLEMENTATION_PATHS
        if sup.entry_is_absent(sup.LAB_DIR / name)
    ]
    assert not present or not missing, (
        f"partial implementation surface: present={present} absent={missing}"
    )
    for name in NEVER_AUTHORIZED_PATHS:
        assert sup.entry_is_absent(sup.LAB_DIR / name), name


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


def test_gv7_m_007_the_laboratory_is_in_one_of_the_two_admissible_states():
    """Exactly two states, and nothing else -- including no extra path."""
    assert sup.entry_is_absent(sup.LAB_DIR) is False, "a loud failure on a bad root"
    present = sup.laboratory_file_names()
    assert present, "the path scan examined nothing"
    state = sup.laboratory_state(present)
    assert state in sup.ADMISSIBLE_STATES, state


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
    # ``ModuleNotFoundError`` subclasses ``ImportError``, so the base class
    # alone would be satisfied by the very confusion this control excludes.
    assert not isinstance(excinfo.value, ModuleNotFoundError)
    assert type(excinfo.value) is ImportError

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
    assert isinstance(excinfo.value, json.JSONDecodeError), "a syntax fault"

    # A different mechanism, not a second syntax fault: the integer-conversion
    # digit limit raises a plain ``ValueError``. ``JSONDecodeError`` subclasses
    # ``ValueError``, so the base class alone would collapse the two together.
    # The digit limit is an interpreter setting, and `0` disables it. Pin it
    # for the probe and restore it, exactly as GV7-S-017 does, so this control
    # cannot pass or fail for a reason outside the suite.
    original = sys.get_int_max_str_digits()
    try:
        if original == 0:
            sys.set_int_max_str_digits(4300)
        digits = sys.get_int_max_str_digits() + 64
        oversized = tmp_path / "oversized.json"
        oversized.write_text('{"n": ' + "9" * digits + "}", encoding="utf-8")
        with pytest.raises(ValueError) as excinfo:
            sup.load_json_file(oversized, "oversized.json")
        assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)
        assert not isinstance(excinfo.value, json.JSONDecodeError)
    finally:
        sys.set_int_max_str_digits(original)


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


def test_gv7_m_017_a_permission_failure_is_never_reported_as_absence(
    tmp_path, monkeypatch
):
    """``Path.exists()`` would have swallowed this into a bare False.

    ``entry_is_absent`` uses ``lstat`` and converts only ``FileNotFoundError``,
    so an unreadable entry surfaces as the ``PermissionError`` it is.
    """
    probe = tmp_path / "unreadable.json"
    probe.write_text("{}", encoding="utf-8")
    real_lstat = sup.os.lstat

    def denying_lstat(path, *args, **kwargs):
        if sup.os.fspath(path) == sup.os.fspath(probe):
            raise PermissionError(13, "synthetic permission denial")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(sup.os, "lstat", denying_lstat)
    for call in (
        lambda: sup.entry_is_absent(probe),
        lambda: sup.require_file(probe, "unreadable.json"),
        lambda: sup.load_json_file(probe, "unreadable.json"),
        lambda: sup.require_module("gv7_probe_denied", probe),
    ):
        with pytest.raises(PermissionError) as excinfo:
            call()
        assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)


def test_gv7_m_018_a_present_but_invalid_entry_is_never_reported_as_absence(
    tmp_path,
):
    """Present-but-invalid is not absent, in two independent shapes.

    Both assertions are about **the entry itself**. A path *beneath* a dangling
    reparse point is a different fact -- the operating system cannot resolve it
    at all and reports ``ENOENT`` -- and it is pinned separately by
    ``GV7-M-020``.
    """
    # (a) a directory where a file is expected: the entry exists.
    as_directory = tmp_path / "ledger.json"
    as_directory.mkdir()
    assert sup.entry_is_absent(as_directory) is False
    for call in (
        lambda: sup.load_json_file(as_directory, "ledger.json"),
        lambda: sup.require_file(as_directory, "ledger.json"),
    ):
        with pytest.raises(OSError) as excinfo:
            call()
        assert not isinstance(excinfo.value, AssertionError)
        assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)

    # (b) a dangling reparse entry: lstat does not follow, so it is present.
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "dangling"
    sup.make_reparse_directory(link, target)
    assert sup.is_reparse_point(link)
    target.rmdir()
    assert sup.entry_is_absent(link) is False, (
        "a dangling link is present but invalid, never absent"
    )
    with pytest.raises(OSError) as excinfo:
        sup.require_file(link, "dangling")
    assert not isinstance(excinfo.value, AssertionError)
    assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)


def test_gv7_m_019_absence_detection_uses_lstat_and_converts_only_not_found():
    """The rule is visible in the source, not merely in behaviour.

    This scan is a **tripwire, not a detector**. A name-based check cannot
    exclude ``os.path.isfile``, ``os.access``, ``Path.is_file``, a bare
    ``try: open(...)``, or one level of indirection through a helper. What
    establishes the rule is the behavioural set ``GV7-M-013`` through
    ``GV7-M-022``; this control only makes the obvious rewrite loud.
    """
    source = (sup.TESTS_DIR / "_support.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "entry_is_absent"
    )
    handlers = [n for n in ast.walk(target) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "entry_is_absent must handle exactly one error class"
    for handler in handlers:
        assert isinstance(handler.type, ast.Name), "no broad or tuple catch"
        assert handler.type.id == "FileNotFoundError", handler.type.id
    calls = {
        node.func.attr
        for node in ast.walk(target)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "lstat" in calls, "absence must be decided by lstat, not exists()"
    assert "exists" not in calls
    # No other helper may fall back to the swallowing predicate.
    for name in ("require_module", "require_file", "load_json_file"):
        helper = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        used = {
            node.func.attr
            for node in ast.walk(helper)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "exists" not in used, name
    # Every absence signal is actually raised: ``absent`` is a factory, so a
    # bare ``absent(label)`` at a new call site would be a silent no-op.
    raised_exprs = {
        id(node.exc)
        for node in ast.walk(tree)
        if isinstance(node, ast.Raise) and node.exc is not None
    }
    absent_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "absent"
    ]
    assert absent_calls, "the absence factory is never called"
    for node in absent_calls:
        assert id(node) in raised_exprs, "absent(...) must always be raised"


def test_gv7_m_020_an_unresolvable_ancestor_reads_as_absence_by_decision(
    tmp_path,
):
    """The decided semantics for a path the OS cannot resolve at all.

    A missing ancestor directory and a dangling ancestor reparse point both
    surface as ``ENOENT``, so both read as absence. That is stated in
    ``entry_is_absent``'s own docstring rather than left implicit, and the
    roots the suite actually asks about are asserted present here -- so a
    misconfigured root fails loudly instead of reporting a broken harness as
    an unwritten implementation.
    """
    assert sup.entry_is_absent(tmp_path / "no_such_dir" / "ledger.json") is True

    target = tmp_path / "ancestor_target"
    target.mkdir()
    link = tmp_path / "ancestor_link"
    sup.make_reparse_directory(link, target)
    target.rmdir()
    assert sup.entry_is_absent(link / "ledger.json") is True

    # The semantics is documented, not silent.
    assert "ancestor" in (sup.entry_is_absent.__doc__ or "")

    # Absence therefore always means "the leaf under a present laboratory",
    # never "the suite was pointed at the wrong root".
    assert sup.entry_is_absent(sup.LAB_DIR) is False
    assert sup.entry_is_absent(sup.TESTS_DIR) is False


def test_gv7_m_021_a_race_time_disappearance_is_never_recategorized(
    tmp_path, monkeypatch
):
    """The entry passed ``lstat`` and vanished before the read.

    The read and the import run unguarded, so the race surfaces as the
    ``FileNotFoundError`` it is and never as absence.
    """
    probe = tmp_path / "raced.json"
    probe.write_text("{}", encoding="utf-8")
    real_read_text = sup.pathlib.Path.read_text

    def vanishing_read_text(self, *args, **kwargs):
        if sup.os.fspath(self) == sup.os.fspath(probe):
            raise FileNotFoundError(2, "synthetic race after the check")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(sup.pathlib.Path, "read_text", vanishing_read_text)
    for call in (
        lambda: sup.require_file(probe, "raced.json"),
        lambda: sup.load_json_file(probe, "raced.json"),
    ):
        with pytest.raises(FileNotFoundError) as excinfo:
            call()
        assert not isinstance(excinfo.value, AssertionError)
        assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)
    monkeypatch.undo()

    module_probe = tmp_path / "gv7_probe_raced_module.py"
    module_probe.write_text("VALUE = 1\n", encoding="utf-8")

    def vanishing_import(name, *args, **kwargs):
        raise FileNotFoundError(2, "synthetic race during import")

    monkeypatch.setattr(sup.importlib, "import_module", vanishing_import)
    with pytest.raises(FileNotFoundError) as excinfo:
        sup.require_module("gv7_probe_raced_module", module_probe)
    assert not isinstance(excinfo.value, AssertionError)
    assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)


def test_gv7_m_022_an_imported_module_must_be_the_entry_that_was_inspected(
    tmp_path, monkeypatch
):
    """The entry is checked by path but imported by dotted name.

    A stale ``sys.modules`` entry, a shadowing ``sys.path`` root, a PEP-420
    namespace portion or a compiled artifact can bind a different module than
    the one that was inspected. That is a harness fault: it must be reported
    as neither a working implementation nor an absent one.
    """
    name = "gv7_probe_identity"
    sys.modules.pop(name, None)
    try:
        real_root = tmp_path / "real"
        real_root.mkdir()
        real_module = real_root / f"{name}.py"
        real_module.write_text("VALUE = 'real'\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(real_root))

        # The agreeing case must still succeed: a check that only refuses is
        # broken, not correct.
        module = sup.require_module(name, real_module)
        assert module.VALUE == "real"
        assert pathlib.Path(module.__file__).resolve() == real_module.resolve()

        # A second, genuinely present entry of the same name. The import
        # resolves by name to the module already bound, so the path that was
        # inspected and the module that came back diverge.
        decoy_root = tmp_path / "decoy"
        decoy_root.mkdir()
        decoy_module = decoy_root / f"{name}.py"
        decoy_module.write_text("VALUE = 'decoy'\n", encoding="utf-8")
        assert sup.entry_is_absent(decoy_module) is False

        with pytest.raises(AssertionError) as excinfo:
            sup.require_module(name, decoy_module)
        assert sup.IMPLEMENTATION_ABSENT not in str(excinfo.value)
        assert "identity divergence" in str(excinfo.value)
    finally:
        sys.modules.pop(name, None)


def test_gv7_m_023_the_two_state_classifier_refuses_every_other_shape():
    """Proved on synthetic path sets, so the real directory need not be wrong.

    Fourteen partial surfaces, an unrelated extra path in both states, and a
    missing Phase-A file. Without this, ``GV7-M-005`` and ``GV7-M-007`` would
    be single observations of a directory that happens to be correct.
    """
    phase_a = frozenset(sup.PHASE_A_PATHS)
    implementation = frozenset(sup.IMPLEMENTATION_PATHS)

    assert sup.laboratory_state(phase_a) == sup.PRE_IMPLEMENTATION_STATE
    assert (
        sup.laboratory_state(phase_a | implementation) == sup.IMPLEMENTED_STATE
    )

    for name in sorted(implementation):
        partial_up = sup.laboratory_state(phase_a | {name})
        assert partial_up.startswith("invalid: partial"), (name, partial_up)
        partial_down = sup.laboratory_state((phase_a | implementation) - {name})
        assert partial_down.startswith("invalid: partial"), (name, partial_down)

    for base in (phase_a, phase_a | implementation):
        stray = sup.laboratory_state(base | {"scratch_notes.md"})
        assert stray.startswith("invalid: unrelated"), stray
        nested = sup.laboratory_state(base | {"records/keep.json"})
        assert nested.startswith("invalid: unrelated"), nested

    for name in sorted(phase_a):
        hole = sup.laboratory_state(phase_a - {name})
        assert hole.startswith("invalid: phase-A"), (name, hole)

    assert not set(sup.PHASE_A_PATHS) & set(sup.IMPLEMENTATION_PATHS)
    assert len(sup.ADMISSIBLE_STATES) == 2


def test_gv7_m_024_the_collection_environment_is_disclosed_not_assumed(request):
    """A disclosure, not an exclusion.

    This suite cannot see a ``conftest.py`` in a parent directory, and a
    control asserting one does not exist would claim a fact it cannot
    establish. What it *can* establish is what actually loaded and what is
    actually in effect, and that every collected item reached the run
    unmarked. Configuration above the laboratory stays a human-audit item, and
    CONTRACT.md section 12 says so.
    """
    config = request.config
    assert config.getini("addopts") == [], config.getini("addopts")
    assert not os.environ.get("PYTEST_ADDOPTS"), os.environ.get("PYTEST_ADDOPTS")

    loaded = sorted(
        name
        for name, module in list(sys.modules.items())
        if module is not None
        and getattr(module, "__file__", None)
        and pathlib.Path(module.__file__).name == "conftest.py"
    )
    assert not loaded, f"conftest modules loaded: {loaded}"

    # Marks injected after a static scan are only visible on the items.
    for item in request.session.items:
        offending = sorted(
            mark.name
            for mark in item.iter_markers()
            if mark.name in BANNED_MARKS
        )
        assert not offending, (item.nodeid, offending)


def test_gv7_m_025_the_manifest_equals_what_pytest_actually_collected(request):
    """The census is reconciled against the run, not only against the source.

    A nested definition is not collected and an id-less test carries no id, so
    this single control closes both gaps behaviourally, whatever the AST scan
    may have missed.
    """
    collected: dict[str, set[str]] = {}
    for item in request.session.items:
        control_id = control_id_of(item.name.split("[")[0])
        if control_id is None:
            continue
        collected.setdefault(pathlib.Path(str(item.path)).name, set()).add(control_id)

    # Compared per module, so selecting a subset of files does not turn this
    # into a false failure about the files that were never asked for.
    assert collected, "no control was collected"
    for filename, ids in sorted(collected.items()):
        declared = set(AUTHORED_CONTROLS.get(filename, ()))
        assert ids == declared, (filename, sorted(ids ^ declared))
    if set(collected) == set(AUTHORED_CONTROLS):
        every = {cid for values in AUTHORED_CONTROLS.values() for cid in values}
        assert set().union(*collected.values()) == every

    # A retired id is never reused and never reappears in a module.
    #
    # The union of EVERY declared set, not the `declared` left behind by the
    # loop above. That leak checked whichever module happened to sort last and
    # nothing else, so a retired id declared in any other module passed
    # unnoticed while the assertion still read as though it covered them all.
    retired = set(sup.RETIRED_CONTROLS)
    every_declared = {
        control for values in AUTHORED_CONTROLS.values() for control in values
    }
    assert not retired & every_declared, sorted(retired & every_declared)
    for path in sorted(sup.TESTS_DIR.glob("test_*.py")):
        present = control_ids_in_source(path.read_text(encoding="utf-8"))
        assert not retired & present, (path.name, sorted(retired & present))
    for reason in sup.RETIRED_CONTROLS.values():
        assert reason and len(reason) > 20
