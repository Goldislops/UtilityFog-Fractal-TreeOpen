"""The explicit control manifest and the meta-controls that guard the suite.

Every control authored for this phase is named here. Adding or removing a
control requires an intentional edit to ``AUTHORED_CONTROLS``: a numeric test
count is never the acceptance claim, and a control that quietly disappears
fails ``SR-M-002``.

``DEFERRED_CONTROLS`` names work that is **not present** and must never be
counted as present or silently substituted.

Neutrality is enforced by **approved manifests** — the path manifest and the
anchored synthetic locator pattern — never by a list of prohibited names. No
proscribed-name list is created, stored, or read here.

Control ids SR-M-NNN are declared below alongside every other control.
"""

from __future__ import annotations

import ast
import pathlib
import re

from experiments.source_record.tests import _support as sup

# --------------------------------------------------------------------------
# The manifest.
# --------------------------------------------------------------------------

AUTHORED_CONTROLS = {
    "test_schema.py": (
        "SR-S-001", "SR-S-002", "SR-S-003", "SR-S-004", "SR-S-005",
        "SR-S-006", "SR-S-007", "SR-S-008", "SR-S-009", "SR-S-010",
        "SR-S-011", "SR-S-012", "SR-S-013", "SR-S-014", "SR-S-015",
        "SR-S-016", "SR-S-017", "SR-S-018", "SR-S-019", "SR-S-020",
        "SR-S-021", "SR-S-022", "SR-S-023", "SR-S-024", "SR-S-025",
        "SR-S-026", "SR-S-027", "SR-S-028", "SR-S-029", "SR-S-030",
        "SR-S-031", "SR-S-032", "SR-S-033", "SR-S-034", "SR-S-035",
        "SR-S-036", "SR-S-037", "SR-S-038", "SR-S-039", "SR-S-040",
        "SR-S-041", "SR-S-042", "SR-S-043", "SR-S-044", "SR-S-045",
        "SR-S-046", "SR-S-047", "SR-S-048", "SR-S-049",
    ),
    "test_records.py": (
        "SR-R-001", "SR-R-002", "SR-R-003", "SR-R-004", "SR-R-005",
        "SR-R-006", "SR-R-007", "SR-R-008", "SR-R-009", "SR-R-010",
        "SR-R-011", "SR-R-012", "SR-R-013", "SR-R-014", "SR-R-015",
        "SR-R-016", "SR-R-017", "SR-R-018", "SR-R-019", "SR-R-020",
        "SR-R-021", "SR-R-022", "SR-R-023", "SR-R-024",
    ),
    "test_validate_cli.py": (
        "SR-C-001", "SR-C-002", "SR-C-003", "SR-C-004", "SR-C-005",
        "SR-C-006", "SR-C-007", "SR-C-008", "SR-C-009", "SR-C-010",
        "SR-C-011", "SR-C-012", "SR-C-013", "SR-C-014", "SR-C-015",
        "SR-C-016", "SR-C-017", "SR-C-018", "SR-C-019", "SR-C-020",
        "SR-C-021", "SR-C-022",
    ),
    "test_import_quarantine.py": (
        "SR-Q-001", "SR-Q-002", "SR-Q-003", "SR-Q-004", "SR-Q-005",
        "SR-Q-006", "SR-Q-007", "SR-Q-008",
    ),
    "test_controls_manifest.py": (
        "SR-M-001", "SR-M-002", "SR-M-003", "SR-M-004", "SR-M-005",
        "SR-M-006", "SR-M-007", "SR-M-008", "SR-M-009", "SR-M-010",
        "SR-M-011", "SR-M-012", "SR-M-013",
    ),
}

#: Work deliberately absent. Never claimed as present; never substituted by a
#: broader scan.
DEFERRED_CONTROLS = {
    "root-reverse-import-guard": (
        "tests/test_source_record_reverse_quarantine.py is NOT authored. "
        "Proving that no maintained production module imports this laboratory "
        "needs a repository-wide scan surface that has not been defined. It is "
        "deferred, is not part of this phase or the initial implementation "
        "acceptance requirement, and must not be replaced by a broad "
        "repository scan. See CONTRACT.md section 3c."
    ),
}

#: Files this laboratory is permitted to contain in this phase. An allow-list.
APPROVED_LABORATORY_PATHS = frozenset(
    {
        "CONTRACT.md",
        "tests/__init__.py",
        "tests/_support.py",
        "tests/test_schema.py",
        "tests/test_records.py",
        "tests/test_validate_cli.py",
        "tests/test_import_quarantine.py",
        "tests/test_controls_manifest.py",
    }
)

CONTROL_ID_PATTERN = re.compile(r"\Atest_sr_([a-z])_([0-9]{3})_")


def control_id_of(function_name: str) -> str | None:
    match = CONTROL_ID_PATTERN.match(function_name)
    if match is None:
        return None
    return f"SR-{match.group(1).upper()}-{match.group(2)}"


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
        for path in sup.lab_test_modules()
        if path.name.startswith("test_")
    }


# --------------------------------------------------------------------------
# Manifest integrity
# --------------------------------------------------------------------------


def test_sr_m_001_every_declared_control_exists_in_its_declared_module():
    modules = suite_modules()
    assert modules, "the manifest scan examined nothing"
    for filename, declared in sorted(AUTHORED_CONTROLS.items()):
        path = modules.get(filename)
        assert path is not None, f"declared module missing: {filename}"
        present = control_ids_in_source(path.read_text(encoding="utf-8"))
        missing = sorted(set(declared) - present)
        assert not missing, f"{filename}: declared but absent {missing}"


def test_sr_m_002_every_control_in_the_suite_is_declared_in_the_manifest():
    modules = suite_modules()
    assert modules, "the manifest scan examined nothing"
    for filename, path in sorted(modules.items()):
        declared = set(AUTHORED_CONTROLS.get(filename, ()))
        present = control_ids_in_source(path.read_text(encoding="utf-8"))
        undeclared = sorted(present - declared)
        assert not undeclared, f"{filename}: present but undeclared {undeclared}"


def test_sr_m_003_no_declared_control_id_is_duplicated_across_the_manifest():
    seen: list[str] = []
    for declared in AUTHORED_CONTROLS.values():
        seen.extend(declared)
    assert len(seen) == len(set(seen)), "duplicate control id in the manifest"


def test_sr_m_004_no_control_in_the_suite_is_skipped_or_marked_expected_failure():
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


# --------------------------------------------------------------------------
# Carrier and marker integrity
# --------------------------------------------------------------------------


def test_sr_m_005_the_hostile_carriers_still_override_the_hooks_they_claim():
    expected = {
        sup.HookedStr: ("__eq__", "__hash__", "__repr__", "__str__", "__len__"),
        sup.HookedInt: ("__eq__", "__hash__", "__repr__", "__index__"),
        sup.HookedBytes: ("__eq__", "__hash__", "__repr__", "__len__"),
        sup.HookedDict: ("__iter__", "__len__", "__getitem__", "__repr__"),
        sup.HookedList: ("__iter__", "__len__", "__repr__"),
        sup.HookedTuple: ("__iter__", "__len__", "__repr__"),
        sup.Betrayer: ("__repr__", "__str__", "__eq__", "__hash__", "__len__"),
    }
    assert set(expected) == set(sup.all_hooked_classes())
    for cls, hooks in expected.items():
        for hook in hooks:
            assert hook in cls.__dict__, (cls.__name__, hook)


def test_sr_m_006_each_hostile_carrier_actually_records_a_hook_when_exercised():
    probe = sup.HookedStr("synthetic")
    probe.reset_hooks()
    repr(probe)
    assert probe.any_hook_ran()

    probe = sup.HookedList([1])
    probe.reset_hooks()
    len(probe)
    assert probe.any_hook_ran()

    probe = sup.Betrayer()
    probe.reset_hooks()
    str(probe)
    assert probe.any_hook_ran()


def test_sr_m_007_the_mutating_mapping_still_changes_its_answer_on_a_second_read():
    probe = sup.MutatingDict({"k": "first"}, "k", "second")
    assert probe["k"] == "first"
    assert probe["k"] == "second"
    assert probe.reads == 2


def test_sr_m_008_the_canary_markers_are_non_empty_unique_and_distinctive():
    assert len(sup.MARKERS) == len(set(sup.MARKERS))
    for marker in sup.MARKERS:
        assert marker
        assert len(marker) >= 24
        assert marker.strip() == marker
        assert "do-not-echo" in marker


# --------------------------------------------------------------------------
# Deferred work, approved paths, synthetic values
# --------------------------------------------------------------------------


def test_sr_m_009_the_deferred_root_reverse_guard_is_declared_and_absent():
    assert "root-reverse-import-guard" in DEFERRED_CONTROLS
    reason = DEFERRED_CONTROLS["root-reverse-import-guard"]
    assert "deferred" in reason
    assert "must not be replaced" in reason
    declared = {
        control_id
        for declared in AUTHORED_CONTROLS.values()
        for control_id in declared
    }
    assert not any("REVERSE" in control_id for control_id in declared)
    guard = sup.REPO_ROOT / "tests" / "test_source_record_reverse_quarantine.py"
    assert not guard.exists(), (
        "the root reverse guard is deferred and must not be authored here"
    )


def test_sr_m_010_the_laboratory_contains_exactly_the_approved_paths():
    present = {
        path.relative_to(sup.LAB_DIR).as_posix()
        for path in sup.LAB_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert present, "the path scan examined nothing"
    unapproved = sorted(present - APPROVED_LABORATORY_PATHS - _future_paths(present))
    assert not unapproved, f"unapproved laboratory path present: {unapproved}"
    missing = sorted(APPROVED_LABORATORY_PATHS - present)
    assert not missing, f"approved path absent: {missing}"


def _future_paths(present: set[str]) -> set[str]:
    """Paths a later implementation phase is expected to add.

    Kept separate so this phase's approved set stays exact while a later
    implementation does not have to edit this control to land its own files.
    """
    allowed_prefixes = ("records/", "__init__.py", "schema.py", "validate.py",
                        "README.md", ".gitattributes")
    return {
        path
        for path in present
        if path.startswith(allowed_prefixes)
    }


def test_sr_m_011_every_builder_emits_only_anchored_synthetic_locator_values():
    pattern = re.compile(sup.LOCATOR_VALUE_PATTERN)
    record = sup.source_record()
    assert record["locators"], "the source builder must exercise a locator"
    for locator in record["locators"]:
        assert pattern.match(locator["value"]), locator["value"]
    assert pattern.match(sup.locator_block()["value"])
    for record_type in sup.RECORD_TYPES:
        built = sup.valid_record(record_type)
        assert built["origin"] == "synthetic-fixture"
        assert built["schema"] == sup.SCHEMA_ID


def test_sr_m_012_the_meta_controls_detect_the_removal_of_a_control():
    """Strip one control from an in-memory copy and prove the check fails."""
    path = suite_modules()["test_schema.py"]
    source = path.read_text(encoding="utf-8")
    present = control_ids_in_source(source)
    assert "SR-S-001" in present

    # Rename rather than delete: the copy must stay parseable, so the control
    # is removed from the *manifest surface* without orphaning its body.
    stripped = source.replace(
        "def test_sr_s_001_a_minimal_valid_record_of_every_type_is_accepted",
        "def _control_removed_for_this_probe",
    )
    assert stripped != source, "the probe failed to rename the target control"
    reduced = control_ids_in_source(stripped)
    assert "SR-S-001" not in reduced
    declared = set(AUTHORED_CONTROLS["test_schema.py"])
    assert sorted(declared - reduced) == ["SR-S-001"]


def test_sr_m_013_every_refusal_token_is_referenced_by_at_least_one_control():
    modules = suite_modules()
    assert modules, "the token reachability scan examined nothing"
    corpus = "".join(
        path.read_text(encoding="utf-8") for path in sorted(modules.values())
    )
    corpus += sup.TESTS_DIR.joinpath("_support.py").read_text(encoding="utf-8")
    unreferenced = sorted(
        token for token in sup.REFUSAL_TOKENS if token not in corpus
    )
    assert not unreferenced, f"refusal tokens no control mentions: {unreferenced}"
