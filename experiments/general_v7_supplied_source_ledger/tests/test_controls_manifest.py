"""Family M --- the explicit control manifest and the meta-controls.

Every control authored for this phase is named in ``AUTHORED_CONTROLS``.
Adding or removing one requires an intentional manifest edit; a numeric test
count is never the acceptance claim, and **the manifest is never padded to
reproduce an earlier total**.

Nothing here claims a file is absent from the *repository*: this is a sparse
worktree. The surface control asserts that the laboratory is in one of the two
admissible states, which is a fact about this commit.

Every ``ast.parse`` in this module pins ``optimize=0``. Since Python 3.13 the
parser inherits the interpreter's optimization level, so under ``-OO`` an
unpinned parse silently loses docstrings and under ``-O`` it silently loses
every ``assert`` node --- which would disarm the very meta-controls that exist
to keep the optimized modes honest.
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

from experiments.general_v7_supplied_source_ledger.tests import _support as sup


def _ids(letter: str, *spans) -> tuple:
    numbers = []
    for low, high in spans:
        numbers.extend(range(low, high + 1))
    return tuple(f"G7S-{letter}-{number:03d}" for number in numbers)


#: Gaps would be deliberate and explained in ``sup.RETIRED_CONTROLS``. A
#: retired id is never reused and never renumbered: an auditor reading an
#: earlier handback must be able to look one up and find that it was
#: withdrawn, not find a different control wearing its name.
AUTHORED_CONTROLS = {
    "test_contract.py": _ids("D", (1, 47)),
    "test_controls_manifest.py": _ids("M", (1, 36)),
    "test_packet_manifest.py": _ids("R", (1, 20)),
    "test_inventory.py": _ids("I", (1, 16)),
    "test_schema.py": _ids("S", (1, 33)),
    "test_provenance.py": _ids("P", (1, 16)),
    "test_quarantine.py": _ids("Q", (1, 12)),
}

FAMILY_TOTALS = {"D": 47, "M": 36, "R": 20, "I": 16, "S": 33, "P": 16, "Q": 12}

GRAND_TOTAL = 180

BANNED_MARKS = frozenset({"skip", "skipif", "xfail"})
BANNED_CALLS = frozenset({"skip", "xfail", "importorskip", "exit", "fail"})

#: Modules pytest rewrites assertions in. Everything else must raise.
REWRITTEN_PREFIX = "test_"


def parse(source: str) -> ast.Module:
    """Parse with the optimization level pinned. Never call ``ast.parse`` bare."""
    return ast.parse(source, optimize=0)


def suite_files() -> dict:
    return {
        path.name: path
        for path in sorted(sup.TESTS_DIR.glob("*.py"))
        if path.name != "__pycache__"
    }


def authored_modules() -> dict:
    return {
        name: path
        for name, path in suite_files().items()
        if name.startswith(REWRITTEN_PREFIX)
    }


def top_level_functions(module: ast.Module) -> list:
    return [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def control_ids_in_source(source: str) -> set:
    """Only TOP-LEVEL definitions count, because only those are collected.

    ``ast.walk`` recurses into function and class bodies, so a control id on a
    nested ``def`` would satisfy a manifest while pytest never collected it. A
    duplicate id in one module is likewise a fault: the second definition
    shadows the first at runtime, the first never runs, and a set-based census
    cannot see the difference.
    """
    module = parse(source)
    seen = []
    for node in top_level_functions(module):
        control_id = sup.control_id_of(node.name)
        if control_id is not None:
            seen.append(control_id)
    assert len(seen) == len(set(seen)), f"duplicate control id in one module: {seen}"
    return set(seen)


def undeclared_test_functions(source: str) -> list:
    return sorted(
        node.name
        for node in top_level_functions(parse(source))
        if node.name.startswith("test_") and sup.control_id_of(node.name) is None
    )


def census() -> dict:
    return {
        name: control_ids_in_source(path.read_text(encoding="utf-8"))
        for name, path in authored_modules().items()
    }


def all_declared() -> set:
    return {control for values in AUTHORED_CONTROLS.values() for control in values}


def test_g7s_m_001_every_declared_control_exists_in_its_declared_module():
    found = census()
    assert found, "the manifest scan examined nothing"
    for filename, declared in sorted(AUTHORED_CONTROLS.items()):
        present = found.get(filename)
        assert present is not None, f"declared module missing: {filename}"
        missing = sorted(set(declared) - present)
        assert not missing, f"{filename}: declared but absent {missing}"


def test_g7s_m_002_every_control_in_the_suite_is_declared():
    found = census()
    assert found, "the manifest scan examined nothing"
    for filename, path in sorted(authored_modules().items()):
        source = path.read_text(encoding="utf-8")
        declared = set(AUTHORED_CONTROLS.get(filename, ()))
        undeclared = sorted(found[filename] - declared)
        assert not undeclared, f"{filename}: present but undeclared {undeclared}"
        anonymous = undeclared_test_functions(source)
        assert not anonymous, f"{filename}: collected test with no id {anonymous}"


def test_g7s_m_003_the_module_set_is_closed_in_both_directions():
    discovered = set(authored_modules())
    declared = set(AUTHORED_CONTROLS)
    assert declared == discovered, sorted(declared ^ discovered)


def test_g7s_m_004_no_declared_control_id_is_duplicated():
    flat = [control for values in AUTHORED_CONTROLS.values() for control in values]
    assert len(flat) == len(set(flat)), "a declared id appears twice"


def test_g7s_m_005_family_totals_reconcile_against_the_census():
    found = census()
    counted = {}
    for ids in found.values():
        for control in ids:
            counted[control.split("-")[1]] = counted.get(control.split("-")[1], 0) + 1
    assert counted == FAMILY_TOTALS, (counted, FAMILY_TOTALS)
    assert sum(FAMILY_TOTALS.values()) == GRAND_TOTAL
    assert sum(len(ids) for ids in found.values()) == GRAND_TOTAL
    assert len(all_declared()) == GRAND_TOTAL


def test_g7s_m_006_no_control_is_silently_retired():
    retired = set(sup.RETIRED_CONTROLS)
    assert not retired & all_declared(), sorted(retired & all_declared())
    found = census()
    for filename, ids in sorted(found.items()):
        assert not retired & ids, (filename, sorted(retired & ids))
    for reason in sup.RETIRED_CONTROLS.values():
        assert reason and len(reason) > 20, reason


def test_g7s_m_007_the_census_detects_a_removed_control():
    source = (sup.TESTS_DIR / "test_contract.py").read_text(encoding="utf-8")
    victim = "def test_g7s_d_001_"
    assert victim in source, "the probe target no longer exists"
    mutated = source.replace(victim, "def renamed_away_", 1)
    assert "G7S-D-001" not in control_ids_in_source(mutated)
    assert "G7S-D-001" in control_ids_in_source(source)


def test_g7s_m_008_the_census_detects_an_added_control():
    source = (sup.TESTS_DIR / "test_contract.py").read_text(encoding="utf-8")
    injected = source + "\n\ndef test_g7s_d_999_synthetic_probe():\n    return None\n"
    present = control_ids_in_source(injected)
    assert "G7S-D-999" in present
    assert "G7S-D-999" not in set(AUTHORED_CONTROLS["test_contract.py"])


def test_g7s_m_009_a_control_id_on_a_nested_definition_is_refused():
    for filename, path in sorted(authored_modules().items()):
        module = parse(path.read_text(encoding="utf-8"))
        outer = set(id(node) for node in top_level_functions(module))
        for node in ast.walk(module):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if id(node) in outer:
                continue
            assert sup.control_id_of(node.name) is None, (filename, node.name)


def test_g7s_m_010_nothing_in_the_suite_can_skip_or_expect_failure():
    """Decorators are only one of the four shapes this has to see.

    A runtime ``pytest.skip(...)`` call, a module-level ``pytestmark`` and a
    bare ``@skip`` imported by name are the others. The scan covers every
    ``.py`` in the suite, not only ``test_*``: ``_support.py`` could have
    called ``pytest.skip(allow_module_level=True)`` and silenced everything.
    """
    files = suite_files()
    assert files, "the marker scan examined nothing"
    for filename, path in sorted(files.items()):
        tree = parse(path.read_text(encoding="utf-8"))
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


def test_g7s_m_011_every_ast_parse_in_the_suite_pins_the_optimize_level():
    for filename, path in sorted(suite_files().items()):
        tree = parse(path.read_text(encoding="utf-8"))
        # Every name the ast module is reachable by in this file. `import ast
        # as a` used to slip past a check that only recognised the literal
        # name `ast`.
        ast_aliases = {"ast"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ast":
                        ast_aliases.add(alias.asname or "ast")
            # `from ast import parse` would produce a bare `parse(...)` call
            # indistinguishable from this module's own pinned helper, so the
            # import itself is refused rather than the call site.
            if isinstance(node, ast.ImportFrom) and node.module == "ast":
                for alias in node.names:
                    assert alias.name != "parse", (
                        filename,
                        "import ast.parse by name; use the pinned helper",
                    )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            attr = getattr(node.func, "attr", None)
            if attr != "parse":
                continue
            if getattr(node.func.value, "id", None) not in ast_aliases:
                continue
            keywords = {keyword.arg for keyword in node.keywords}
            assert "optimize" in keywords, (
                filename,
                node.lineno,
                "ast.parse without optimize=0 reads a different tree under -O/-OO",
            )
            for keyword in node.keywords:
                if keyword.arg == "optimize":
                    assert getattr(keyword.value, "value", None) == 0, (
                        filename,
                        node.lineno,
                    )


def test_g7s_m_012_the_suite_never_reads_a_runtime_docstring():
    for filename, path in sorted(suite_files().items()):
        tree = parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "__doc__", (filename, node.lineno)
            if isinstance(node, ast.Call):
                label = getattr(node.func, "attr", None)
                assert label != "get_docstring", (filename, node.lineno)


def test_g7s_m_013_no_module_level_assert_and_no_debug_builtin():
    for filename, path in sorted(suite_files().items()):
        tree = parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            assert not isinstance(node, ast.Assert), (filename, node.lineno)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "__debug__", (filename, node.lineno)


def test_g7s_m_014_no_bare_assert_outside_a_rewritten_test_module():
    """The single most dangerous shape available to this suite.

    Pytest rewrites assertions only in the modules it collects. In every other
    module a bare ``assert`` is deleted outright by ``-O``, so a helper built
    on one asserts nothing while every control depending on it still reports a
    pass --- the same count, the opposite meaning.
    """
    for filename, path in sorted(suite_files().items()):
        if filename.startswith(REWRITTEN_PREFIX):
            continue
        tree = parse(path.read_text(encoding="utf-8"))
        offenders = [
            node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)
        ]
        assert not offenders, (filename, offenders)


def _collect_node_ids(flags) -> list:
    command = [sys.executable, "-B"]
    command.extend(flags)
    command.extend(
        [
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            str(sup.TESTS_DIR),
        ]
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        cwd=str(sup.REPO_ROOT),
        env=environment,
        text=True,
    )
    if completed.returncode != 0:
        raise sup.harness_fault(
            f"collection failed for flags {flags}: {completed.stdout[-2000:]}"
        )
    return [line.strip() for line in completed.stdout.splitlines() if "::" in line]


def test_g7s_m_015_every_optimization_mode_collects_the_same_controls():
    ordinary = _collect_node_ids([])
    optimized = _collect_node_ids(["-O"])
    doubly = _collect_node_ids(["-OO"])
    assert ordinary, "ordinary collection produced nothing"
    assert ordinary == optimized, "collection differs under -O"
    assert ordinary == doubly, "collection differs under -OO"
    assert len(ordinary) == GRAND_TOTAL, (len(ordinary), GRAND_TOTAL)


def test_g7s_m_016_the_manifest_equals_what_pytest_actually_collected(request):
    """Reconciled against the run, not only against the source.

    A nested definition is not collected and an id-less test carries no id, so
    this closes both gaps behaviourally, whatever the static scan may have
    missed. Compared per module, so selecting a subset of files does not turn
    this into a false failure about files that were never asked for.
    """
    collected = {}
    for item in request.session.items:
        control_id = sup.control_id_of(item.name.split("[")[0])
        if control_id is None:
            continue
        collected.setdefault(pathlib.Path(str(item.path)).name, set()).add(control_id)
    assert collected, "no control was collected"
    for filename, ids in sorted(collected.items()):
        declared = set(AUTHORED_CONTROLS.get(filename, ()))
        assert ids == declared, (filename, sorted(ids ^ declared))
    if set(collected) == set(AUTHORED_CONTROLS):
        union = set()
        for ids in collected.values():
            union |= ids
        assert union == all_declared()


def test_g7s_m_017_the_census_never_imports_a_test_module():
    source = (sup.TESTS_DIR / "test_controls_manifest.py").read_text(encoding="utf-8")
    tree = parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "test_" not in alias.name, alias.name
        if isinstance(node, ast.ImportFrom):
            assert "test_" not in (node.module or ""), node.module
        if isinstance(node, ast.Call):
            label = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert label not in ("import_module", "__import__"), label


def test_g7s_m_018_the_two_groups_partition_the_census_exactly():
    found = census()
    contract_only = set()
    implementation_dependent = set()
    for filename, ids in found.items():
        if filename in sup.CONTRACT_ONLY_MODULES:
            contract_only |= ids
        elif filename in sup.IMPLEMENTATION_DEPENDENT_MODULES:
            implementation_dependent |= ids
        else:
            raise AssertionError(f"module in neither group: {filename}")
    assert not contract_only & implementation_dependent
    assert contract_only | implementation_dependent == all_declared()
    assert len(contract_only) == 103, len(contract_only)
    assert len(implementation_dependent) == 77, len(implementation_dependent)


def test_g7s_m_019_every_gated_control_calls_its_gate_first():
    for filename in sup.IMPLEMENTATION_DEPENDENT_MODULES:
        path = sup.TESTS_DIR / filename
        tree = parse(path.read_text(encoding="utf-8"))
        for node in top_level_functions(tree):
            if sup.control_id_of(node.name) is None:
                continue
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            assert body, (filename, node.name, "empty control body")
            first = body[0]
            call = None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
                call = first.value
            elif isinstance(first, ast.Assign) and isinstance(first.value, ast.Call):
                call = first.value
            assert call is not None, (filename, node.name, "first statement is not a call")
            label = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
            assert label in sup.GATE_HELPERS, (filename, node.name, label)


def test_g7s_m_020_no_contract_only_control_touches_the_implementation():
    for filename in sup.CONTRACT_ONLY_MODULES:
        path = sup.TESTS_DIR / filename
        tree = parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in sup.IMPLEMENTATION_PATH_CONSTANTS, (
                    filename,
                    node.attr,
                )
                assert node.attr not in sup.GATE_HELPERS, (filename, node.attr)
            if isinstance(node, ast.Name):
                assert node.id not in sup.IMPLEMENTATION_PATH_CONSTANTS, (
                    filename,
                    node.id,
                )
                assert node.id not in sup.GATE_HELPERS, (filename, node.id)


def test_g7s_m_021_the_declared_group_membership_covers_every_module():
    declared = set(sup.CONTRACT_ONLY_MODULES) | set(sup.IMPLEMENTATION_DEPENDENT_MODULES)
    discovered = set(authored_modules())
    assert declared == discovered, sorted(declared ^ discovered)
    assert not set(sup.CONTRACT_ONLY_MODULES) & set(
        sup.IMPLEMENTATION_DEPENDENT_MODULES
    )
    assert len(sup.CONTRACT_ONLY_MODULES) == 3
    assert len(sup.IMPLEMENTATION_DEPENDENT_MODULES) == 4


def test_g7s_m_022_only_a_missing_entry_is_reported_as_absent(tmp_path):
    missing = tmp_path / "definitely-absent.json"
    assert sup.entry_is_absent(missing) is True
    present = tmp_path / "present.json"
    present.write_text("{}", encoding="utf-8")
    assert sup.entry_is_absent(present) is False


def test_g7s_m_023_a_present_but_broken_module_propagates_its_own_error(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text("raise ImportError('synthetic')\n", encoding="utf-8")
    assert sup.entry_is_absent(broken) is False
    with pytest.raises(ImportError):
        exec(compile(broken.read_text(encoding="utf-8"), str(broken), "exec"), {})


def test_g7s_m_024_a_malformed_document_propagates_a_parse_error(tmp_path):
    malformed = tmp_path / "ledger.json"
    malformed.write_text("{not json", encoding="utf-8")
    assert sup.entry_is_absent(malformed) is False
    import json as _json

    with pytest.raises(ValueError):
        _json.loads(malformed.read_text(encoding="utf-8"))


def test_g7s_m_025_a_permission_failure_is_never_reported_as_absence(monkeypatch):
    def deny(_path):
        raise PermissionError(13, "synthetic permission denial")

    monkeypatch.setattr(sup.os, "lstat", deny)
    with pytest.raises(PermissionError):
        sup.entry_is_absent(pathlib.Path("anything"))


def test_g7s_m_026_a_path_too_long_error_is_never_reported_as_absence(monkeypatch):
    def too_long(_path):
        error = FileNotFoundError(2, "synthetic path too long")
        error.winerror = sup.PATH_TOO_LONG_WINERROR
        raise error

    monkeypatch.setattr(sup.os, "lstat", too_long)
    with pytest.raises(FileNotFoundError):
        sup.entry_is_absent(pathlib.Path("anything"))


def test_g7s_m_027_a_genuine_not_found_still_reads_as_absence(monkeypatch):
    def not_found(_path):
        raise FileNotFoundError(2, "synthetic absence")

    monkeypatch.setattr(sup.os, "lstat", not_found)
    assert sup.entry_is_absent(pathlib.Path("anything")) is True


def test_g7s_m_028_the_absence_factory_is_always_raised_never_returned():
    for filename, path in sorted(suite_files().items()):
        tree = parse(path.read_text(encoding="utf-8"))
        raised = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                raised.add(id(node.exc))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            label = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if label != "absent":
                continue
            assert id(node) in raised, (filename, node.lineno, "absent() not raised")


def test_g7s_m_029_the_absence_token_is_produced_in_exactly_one_place():
    occurrences = {}
    for filename, path in sorted(suite_files().items()):
        tree = parse(path.read_text(encoding="utf-8"))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and node.value == sup.IMPLEMENTATION_ABSENT
        )
        if count:
            occurrences[filename] = count
    assert occurrences == {"_support.py": 1}, occurrences


def test_g7s_m_030_the_tests_directory_holds_only_suite_code():
    entries = [
        entry
        for entry in sup.TESTS_DIR.iterdir()
        if entry.name not in ("__pycache__", ".pytest_cache")
    ]
    assert entries, "the tests-directory scan examined nothing"
    for entry in entries:
        assert entry.is_file(), entry.name
        assert entry.suffix == ".py", entry.name
        assert entry.name in ("__init__.py", "_support.py") or entry.name.startswith(
            REWRITTEN_PREFIX
        ), entry.name


def test_g7s_m_031_the_suite_imports_only_its_declared_allowance():
    for filename, path in sorted(suite_files().items()):
        tree = parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in sup.SUITE_ALLOWED_IMPORTS, (filename, alias.name)
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                root = (node.module or "").split(".")[0]
                assert root in sup.SUITE_ALLOWED_IMPORTS, (filename, node.module)


def test_g7s_m_032_the_collection_environment_is_disclosed_not_assumed(request):
    """A disclosure, not an exclusion.

    This suite cannot see a ``conftest.py`` above the laboratory, and a control
    asserting one does not exist would claim a fact it cannot establish. What
    it can establish is what actually loaded and what is actually in effect.
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
    for item in request.session.items:
        offending = sorted(
            mark.name for mark in item.iter_markers() if mark.name in BANNED_MARKS
        )
        assert not offending, (item.nodeid, offending)


def test_g7s_m_033_no_bytecode_or_cache_residue_is_tracked():
    tracked = sup.tracked_lab_paths()
    assert tracked, "git tracks nothing under the laboratory"
    for entry in tracked:
        assert "__pycache__" not in entry, entry
        assert ".pytest_cache" not in entry, entry
        assert not entry.endswith((".pyc", ".pyo")), entry
    for forbidden in sup.NEVER_AUTHORIZED_PATHS:
        assert not any(
            entry.split("/")[-1] == forbidden or f"/{forbidden}/" in entry
            for entry in tracked
        ), forbidden


def test_g7s_m_034_the_laboratory_is_in_an_admissible_state():
    names = sup.laboratory_file_names()
    assert "CONTRACT.md" in names
    assert "PACKET_RECEIPT.md" in names
    assert "tests" in names
    state = sup.laboratory_state(names)
    assert state in sup.ADMISSIBLE_STATES, state
    # The laboratory root is closed, not merely classified. `laboratory_state`
    # only inspects the seven implementation names, so an untracked stray file
    # dropped beside CONTRACT.md would otherwise be seen by nothing.
    permitted = {"CONTRACT.md", "PACKET_RECEIPT.md", "tests"} | set(
        sup.IMPLEMENTATION_PATHS
    )
    unexpected = sorted(names - permitted)
    assert not unexpected, f"unexpected entries in the laboratory: {unexpected}"


def test_g7s_m_035_the_frozen_constants_are_internally_consistent():
    assert len(sup.PHASE_A_PATHS) == 11
    assert len(set(sup.PHASE_A_PATHS)) == 11
    assert len(sup.IMPLEMENTATION_PATHS) == 7
    assert len(set(sup.IMPLEMENTATION_PATHS)) == 7
    assert not set(sup.PHASE_A_PATHS) & set(sup.IMPLEMENTATION_PATHS)
    assert len(set(sup.ATTRIBUTION_CLASSES)) == len(sup.ATTRIBUTION_CLASSES)
    assert len(set(sup.RELATIONSHIP_TYPES)) == len(sup.RELATIONSHIP_TYPES)
    assert len(sup.MARKERS) == len(set(sup.MARKERS))
    for marker in sup.MARKERS:
        assert len(marker) >= 24 and "do-not-echo" in marker
        assert marker.strip() == marker
    for token in sup.ATTRIBUTION_CLASSES + sup.RELATIONSHIP_TYPES:
        for fragment in sup.FORBIDDEN_PROMOTION_FRAGMENTS:
            assert fragment not in token, (token, fragment)
    assert sup.DIGEST_RE.match(sup.PACKET_ARCHIVE_SHA256)
    assert sup.DIGEST_RE.match(sup.PACKET_SUMS_SHA256)
    assert sup.DIGEST_RE.match(sup.PACKET_ORIGINS_SHA256)
    assert sup.PACKET_FILE_ENTRY_COUNT + sup.PACKET_DIRECTORY_ENTRY_COUNT == (
        sup.PACKET_ENTRY_COUNT
    )
    assert sup.PACKET_MEMBER_CHECKSUMS == sup.PACKET_ENTRY_COUNT - 1
    assert sup.PACKET_CHECKSUMS_PASSED == sup.PACKET_MEMBER_CHECKSUMS
    assert sup.PACKET_CHECKSUMS_FAILED == 0
    assert sup.EXPECTED_ATTACHMENT_ROWS + sup.EXPECTED_INLINE_ROWS == (
        sup.EXPECTED_ORIGIN_ROWS
    )
    assert sup.EXPECTED_ORIGIN_ROWS == sup.EXPECTED_BATCHES
    assert sup.EXPECTED_BIBLIOGRAPHY_ENTRIES == sup.EXPECTED_VIDEO_IDENTIFIERS
    assert sum(sup.LINE_ENDING_CENSUS.values()) == sup.PACKET_ENTRY_COUNT
    assert sup.LINE_ENDING_CENSUS["lf-only"] + sup.LINE_ENDING_CENSUS["mixed"] == (
        sup.EXPECTED_INLINE_ROWS
    )


def test_g7s_m_036_no_interpretive_figure_is_frozen_as_structural():
    """The control that keeps 61, 35 and 3 out of the structural inventory.

    ``3`` legitimately appears as the inline-row count, which is a reproduced
    structural fact, so the check is on the named interpretive quantities
    rather than on the bare integers.
    """
    interpretive = sup.PRIOR_INTERPRETIVE_EXPECTATIONS
    assert set(interpretive) == {
        "provisional_source_identities",
        "identities_without_exact_locator",
        "non_admitted_artifacts",
    }
    assert interpretive["provisional_source_identities"] == 61
    assert interpretive["identities_without_exact_locator"] == 35
    assert interpretive["non_admitted_artifacts"] == 3
    assert (
        interpretive["identities_without_exact_locator"]
        + sup.EXPECTED_VIDEO_IDENTIFIERS
        == interpretive["provisional_source_identities"]
    )
    for key in ("sources", "non_admitted", "claims", "relationships"):
        assert key not in sup.FROZEN_STRUCTURAL_INVENTORY, key
    assert 61 not in sup.FROZEN_STRUCTURAL_INVENTORY.values()
    assert 35 not in sup.FROZEN_STRUCTURAL_INVENTORY.values()
