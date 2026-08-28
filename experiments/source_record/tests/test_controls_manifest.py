"""The explicit control manifest and the meta-controls that guard the suite.

Every control authored for this phase is named in ``AUTHORED_CONTROLS``. Every
retained refusal token is bound to at least one real control in
``TOKEN_CONTROLS``, and ``SR-M-014`` verifies mechanically that each such
control actually asserts that exact token — not an exit class, not a textual
mention. A token with no such control is removed from the contract rather than
carried as an untested claim; ``CONTRACT.md`` section 8b records every removal
and its reason.

``DEFERRED_CONTROLS`` names work that is **not present** and must never be
counted as present or silently substituted. Deferral is asserted through the
contract and this manifest only. Nothing here claims a file is absent from the
repository: a sparse checkout materializes part of the tree, so on-disk absence
inside this worktree proves nothing.

Neutrality is enforced by **approved manifests** — the exact path allow-list and
the anchored synthetic locator pattern — never by a list of prohibited names.

Control ids SR-M-NNN are declared below alongside every other control.
"""

from __future__ import annotations

import ast
import pathlib
import re

from experiments.source_record.tests import _support as sup

# --------------------------------------------------------------------------
# The control manifest.
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
        "SR-S-046", "SR-S-047", "SR-S-048", "SR-S-049", "SR-S-050",
        "SR-S-051",
    ),
    "test_records.py": (
        "SR-R-001", "SR-R-002", "SR-R-003", "SR-R-004", "SR-R-005",
        "SR-R-006", "SR-R-007", "SR-R-008", "SR-R-009", "SR-R-010",
        "SR-R-011", "SR-R-012", "SR-R-013", "SR-R-014", "SR-R-015",
        "SR-R-016", "SR-R-017", "SR-R-018", "SR-R-019", "SR-R-020",
        "SR-R-021", "SR-R-022", "SR-R-023", "SR-R-024", "SR-R-025",
    ),
    "test_validate_cli.py": (
        "SR-C-001", "SR-C-002", "SR-C-003", "SR-C-004", "SR-C-005",
        "SR-C-006", "SR-C-007", "SR-C-008", "SR-C-009", "SR-C-010",
        "SR-C-011", "SR-C-012", "SR-C-013", "SR-C-014", "SR-C-015",
        "SR-C-016", "SR-C-017", "SR-C-018", "SR-C-019", "SR-C-020",
        "SR-C-021", "SR-C-022", "SR-C-023", "SR-C-024", "SR-C-025",
        "SR-C-026", "SR-C-027", "SR-C-028", "SR-C-029", "SR-C-030",
        "SR-C-031", "SR-C-032", "SR-C-033", "SR-C-034", "SR-C-035",
        "SR-C-036", "SR-C-037", "SR-C-038", "SR-C-039",
    ),
    "test_import_quarantine.py": (
        "SR-Q-001", "SR-Q-002", "SR-Q-003", "SR-Q-004", "SR-Q-005",
        "SR-Q-006", "SR-Q-007", "SR-Q-008", "SR-Q-009", "SR-Q-010",
        "SR-Q-011", "SR-Q-012", "SR-Q-013",
    ),
    "test_controls_manifest.py": (
        "SR-M-001", "SR-M-002", "SR-M-003", "SR-M-004", "SR-M-005",
        "SR-M-006", "SR-M-007", "SR-M-008", "SR-M-009", "SR-M-010",
        "SR-M-011", "SR-M-012", "SR-M-013", "SR-M-014", "SR-M-015",
        "SR-M-016", "SR-M-017", "SR-M-018", "SR-M-019", "SR-M-020",
    ),
}

#: Every retained refusal token, bound to the controls that construct its
#: condition and assert it exactly. SR-M-013 checks coverage in both
#: directions; SR-M-014 checks that each named control really does assert it.
TOKEN_CONTROLS = {
    # path and binding, exit 4
    "path-missing": ("SR-C-004",),
    "path-not-directory": ("SR-C-004",),
    "path-symlink-refused": ("SR-C-030", "SR-C-031"),
    "path-binding-failed": (
        "SR-C-032", "SR-C-036", "SR-C-037", "SR-C-038", "SR-C-039",
    ),
    "records-root-missing-directory": ("SR-R-007",),
    "records-root-unexpected-entry": ("SR-R-006",),
    "record-directory-unexpected-entry": ("SR-R-008", "SR-C-026"),
    # resource, exit 5
    "record-count-ceiling": ("SR-C-007",),
    "record-bytes-ceiling": ("SR-C-023",),
    "total-bytes-ceiling": ("SR-C-024",),
    # parse, schema and record, exit 2
    "json-malformed": ("SR-C-006", "SR-C-035"),
    "json-duplicate-key": ("SR-C-006",),
    "root-not-object": ("SR-S-011",),
    "key-not-exact-str": ("SR-S-008",),
    "undeclared-key": ("SR-S-005", "SR-S-006", "SR-S-036"),
    "missing-key": ("SR-S-004", "SR-S-007"),
    "schema-id-invalid": ("SR-S-025",),
    "record-id-malformed": ("SR-S-022",),
    "record-id-filename-mismatch": ("SR-R-009",),
    "record-id-directory-mismatch": ("SR-R-010",),
    "record-id-register-mismatch": ("SR-S-023",),
    "record-id-type-mismatch": ("SR-S-024",),
    "type-not-exact": (
        "SR-S-011", "SR-S-012", "SR-S-013", "SR-S-014", "SR-S-015",
        "SR-S-016", "SR-S-017", "SR-S-050",
    ),
    "float-refused": ("SR-S-018",),
    "int-out-of-range": ("SR-S-019",),
    "enum-value-invalid": ("SR-S-026",),
    "digits-not-ascii": ("SR-S-020",),
    "date-invalid": ("SR-S-021",),
    "string-empty": ("SR-S-033",),
    "string-length-invalid": ("SR-S-033",),
    "string-not-valid-unicode": ("SR-S-034",),
    "string-contains-record-id": ("SR-S-035",),
    "list-length-invalid": ("SR-S-043", "SR-S-051"),
    "list-duplicate-item": ("SR-S-029", "SR-S-042"),
    "locator-value-not-synthetic": ("SR-S-027",),
    "null-not-permitted": ("SR-S-032",),
    "unknown-token-not-permitted": ("SR-S-032",),
    "attribution-author-mismatch": ("SR-S-031",),
    "derived-from-required": ("SR-S-028",),
    "derived-from-forbidden": ("SR-S-028",),
    "instrument-context-required": ("SR-S-030",),
    "instrument-context-forbidden": ("SR-S-030",),
    "reference-not-found": ("SR-R-011",),
    "reference-wrong-register": ("SR-S-029", "SR-S-038"),
    "reference-wrong-type": ("SR-S-029", "SR-S-039"),
    "reference-self": ("SR-S-040",),
    "reference-cycle": ("SR-R-012",),
    "bridge-side-register-invalid": ("SR-S-037",),
    "bridge-endpoint-not-source": ("SR-S-037",),
    "bridge-duplicate-pair": ("SR-R-013",),
    "digest-format-invalid": ("SR-S-050",),
    "supersedes-target-missing": ("SR-R-025",),
    "supersedes-register-mismatch": ("SR-S-041",),
    "supersedes-type-mismatch": ("SR-S-041",),
    "supersedes-digest-mismatch": ("SR-R-014", "SR-R-015"),
    "supersedes-fork-refused": ("SR-R-017",),
    "supersedes-self": ("SR-S-040",),
    "supersedes-cycle": ("SR-R-018",),
    "verification-state-invalid": ("SR-S-026",),
    "verification-evidence-not-null": ("SR-S-026",),
    "resolution-state-invalid": ("SR-S-026",),
}

#: Tokens deliberately removed from v1. CONTRACT.md section 8b carries the
#: reasons; SR-M-019 asserts they are gone from the vocabulary.
REMOVED_TOKENS = {
    "record-id-duplicate": (
        "unreachable: I12 derives uniqueness from the filename and directory "
        "rules, so no duplicate full record id can be constructed"
    ),
    "attribution-class-mismatch": (
        "redundant: every per-class rule already has its own exact token"
    ),
    "directory-set-incomplete": (
        "redundant with records-root-missing-directory, which names the same "
        "condition precisely"
    ),
}

#: Tokens an earlier revision wrongly removed and this revision reinstated.
#: Removing them left the contract unsatisfiable: I02 and I06 require the
#: behaviour and I61 requires every refusal to carry a retained token.
REINSTATED_TOKENS = {
    "path-symlink-refused": (
        "reinstated with a deterministic fixture: a symbolic link where "
        "privilege allows, a Windows directory junction otherwise, built "
        "entirely under tmp_path and never skipped"
    ),
    "path-binding-failed": (
        "reinstated with a frozen private seam, _acquire_directory_binding, "
        "carrying no public configuration and no verbose mode"
    ),
}

#: Work deliberately absent. Never claimed as present; never substituted by a
#: broader scan; never asserted through a filesystem absence check.
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

#: Files this laboratory contains in this phase. An exact allow-list.
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

#: Files a later implementation phase may add, by EXACT name only. Prefix
#: matching would admit schema.py.extra, README.md.backup and the like.
FUTURE_EXACT_FILES = frozenset(
    {
        "__init__.py",
        "schema.py",
        "validate.py",
        "README.md",
        ".gitattributes",
    }
)

#: Record files, handled separately: exactly three directories, direct JSON.
FUTURE_RECORD_PATTERN = re.compile(
    r"\Arecords/(register-a|register-b|bridge)/[^/]+\.json\Z"
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


def exact_token_assertions(function_node) -> set[str]:
    """Tokens a control asserts EXACTLY, counted only in two exact shapes.

    A literal counts when it is either

    * the **token position** — the third positional argument — of an
      ``assert_refused(...)`` call; or
    * one side of an ``==`` comparison whose **opposite operand is a ``.token``
      attribute access**.

    Nothing else counts. An earlier revision counted any literal in any
    equality, so a harmless ``"token" == "token"`` left behind after the real
    ``error.token`` assertion disappeared would have preserved the binding.
    Membership tests are excluded too: asserting one of several tokens is not
    asserting the exact token. SR-M-020 proves the discrimination.
    """
    found: set[str] = set()
    for node in ast.walk(function_node):
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
                continue
            left, right = node.left, node.comparators[0]
            for literal, opposite in ((left, right), (right, left)):
                if not (
                    isinstance(literal, ast.Constant)
                    and isinstance(literal.value, str)
                ):
                    continue
                if (
                    isinstance(opposite, ast.Attribute)
                    and opposite.attr == "token"
                ):
                    found.add(literal.value)
        elif isinstance(node, ast.Call):
            target = node.func
            name = (
                target.attr
                if isinstance(target, ast.Attribute)
                else getattr(target, "id", None)
            )
            if name != "assert_refused" or len(node.args) < 3:
                continue
            argument = node.args[2]
            if isinstance(argument, ast.Constant) and isinstance(
                argument.value, str
            ):
                found.add(argument.value)
    return found


def control_functions() -> dict[str, ast.AST]:
    """Every control in the suite, keyed by control id."""
    found: dict[str, ast.AST] = {}
    for path in sorted(suite_modules().values()):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            control_id = control_id_of(node.name)
            if control_id is not None:
                found[control_id] = node
    return found


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


def test_sr_m_009_every_deferred_control_is_declared_labelled_and_uncounted():
    """Deferral is asserted through the contract and the manifest only.

    No filesystem absence check appears here. This worktree is a sparse
    checkout, so on-disk absence proves nothing about the repository, and a
    control that claimed otherwise would be asserting a fact it cannot know.
    """
    expected = {"root-reverse-import-guard"}
    assert set(DEFERRED_CONTROLS) == expected
    for name, reason in sorted(DEFERRED_CONTROLS.items()):
        assert reason.strip() == reason and reason
        assert "deferred" in reason or "removed" in reason
        assert "must not be replaced" in reason
    declared = {
        control_id
        for controls in AUTHORED_CONTROLS.values()
        for control_id in controls
    }
    for name in expected:
        assert name not in declared
    # A deferred control never appears as a token binding.
    assert not (set(DEFERRED_CONTROLS) & set(TOKEN_CONTROLS))


def test_sr_m_010_the_laboratory_contains_exactly_the_approved_paths():
    present = {
        path.relative_to(sup.LAB_DIR).as_posix()
        for path in sup.LAB_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert present, "the path scan examined nothing"
    allowed = APPROVED_LABORATORY_PATHS | _future_paths(present)
    unapproved = sorted(present - allowed)
    assert not unapproved, f"unapproved laboratory path present: {unapproved}"
    missing = sorted(APPROVED_LABORATORY_PATHS - present)
    assert not missing, f"approved path absent: {missing}"


def _future_paths(present: set[str]) -> set[str]:
    """Paths a later implementation phase may add.

    Exact equality for files, and a bound pattern for record files. Prefix
    matching would admit ``schema.py.extra``, ``README.md.backup`` and
    ``.gitattributes.unapproved``.
    """
    return {
        path
        for path in present
        if path in FUTURE_EXACT_FILES or FUTURE_RECORD_PATTERN.match(path)
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
    """Rename one control in an in-memory copy and prove the check notices."""
    path = suite_modules()["test_schema.py"]
    source = path.read_text(encoding="utf-8")
    present = control_ids_in_source(source)
    assert "SR-S-001" in present

    stripped = source.replace(
        "def test_sr_s_001_a_minimal_valid_record_of_every_type_is_accepted",
        "def _control_removed_for_this_probe",
    )
    assert stripped != source, "the probe failed to rename the target control"
    reduced = control_ids_in_source(stripped)
    assert "SR-S-001" not in reduced
    declared = set(AUTHORED_CONTROLS["test_schema.py"])
    assert sorted(declared - reduced) == ["SR-S-001"]


# --------------------------------------------------------------------------
# Token-to-control manifest
# --------------------------------------------------------------------------


def test_sr_m_013_every_retained_token_is_bound_to_a_control_and_the_reverse():
    assert set(TOKEN_CONTROLS) == set(sup.REFUSAL_TOKENS), (
        sorted(set(TOKEN_CONTROLS) ^ set(sup.REFUSAL_TOKENS))
    )
    declared = {
        control_id
        for controls in AUTHORED_CONTROLS.values()
        for control_id in controls
    }
    for token, controls in sorted(TOKEN_CONTROLS.items()):
        assert controls, f"{token}: bound to no control"
        assert len(controls) == len(set(controls)), token
        for control_id in controls:
            assert control_id in declared, (token, control_id)


def test_sr_m_014_every_bound_control_asserts_its_exact_token():
    """Each binding must be real: the control asserts that exact token.

    An exit-class assertion or a textual mention is not enough; the token must
    appear in an equality comparison or as a literal ``assert_refused``
    argument. Membership tests are excluded by ``exact_token_assertions``.
    """
    functions = control_functions()
    assert functions, "the token-assertion scan examined nothing"
    for token, controls in sorted(TOKEN_CONTROLS.items()):
        for control_id in controls:
            node = functions.get(control_id)
            assert node is not None, (token, control_id)
            asserted = exact_token_assertions(node)
            assert token in asserted, (
                f"{control_id} is bound to {token!r} but does not assert it "
                f"exactly; it asserts {sorted(asserted)}"
            )


def test_sr_m_015_no_control_asserts_a_removed_token_and_every_refusal_is_retained():
    """Two directions, both narrow enough to be exact.

    No control may assert a token this phase removed, and every literal token
    passed to ``assert_refused`` must be a member of the retained vocabulary.
    Both are decidable from the source; neither guesses at what a string means.
    """
    functions = control_functions()
    assert functions, "the token-assertion scan examined nothing"
    retained = set(sup.REFUSAL_TOKENS)
    removed = set(REMOVED_TOKENS)
    checked = 0
    for control_id, node in sorted(functions.items()):
        for asserted in exact_token_assertions(node):
            assert asserted not in removed, (
                f"{control_id} asserts removed token {asserted!r}"
            )
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            target = inner.func
            name = (
                target.attr
                if isinstance(target, ast.Attribute)
                else getattr(target, "id", None)
            )
            if name != "assert_refused" or len(inner.args) < 3:
                continue
            token_argument = inner.args[2]
            if isinstance(token_argument, ast.Constant) and isinstance(
                token_argument.value, str
            ):
                checked += 1
                assert token_argument.value in retained, (
                    control_id,
                    token_argument.value,
                )
    assert checked > 0, "no assert_refused token argument was examined"


def test_sr_m_016_removed_tokens_are_gone_and_reinstated_tokens_are_bound():
    for token, reason in sorted(REMOVED_TOKENS.items()):
        assert token not in sup.REFUSAL_TOKENS, token
        assert token not in TOKEN_CONTROLS, token
        assert reason.strip() == reason and len(reason) > 20
    for token, reason in sorted(REINSTATED_TOKENS.items()):
        assert token in sup.REFUSAL_TOKENS, token
        assert token in TOKEN_CONTROLS, token
        assert TOKEN_CONTROLS[token], token
        assert reason.strip() == reason and len(reason) > 20
    assert not (set(REMOVED_TOKENS) & set(REINSTATED_TOKENS))


# --------------------------------------------------------------------------
# Frozen content of future files
# --------------------------------------------------------------------------


def test_sr_m_017_the_contract_carries_the_epistemic_limit_verbatim():
    text = sup.LAB_DIR.joinpath("CONTRACT.md").read_text(encoding="utf-8")
    assert sup.EPISTEMIC_LIMIT_TEXT in text, (
        "CONTRACT.md section 2 no longer matches the frozen epistemic limit"
    )


def test_sr_m_018_the_readme_and_gitattributes_carry_their_frozen_content():
    readme = sup.require_future_file(sup.README_PATH, "README.md")
    assert sup.EPISTEMIC_LIMIT_TEXT in readme, (
        "README.md must reproduce the epistemic limit verbatim"
    )
    attributes = sup.require_future_file(
        sup.GITATTRIBUTES_PATH, ".gitattributes"
    )
    assert attributes == sup.GITATTRIBUTES_CONTENT, repr(attributes)


def test_sr_m_019_the_source_record_workflow_matches_its_canonical_bytes():
    """Byte-for-byte equality against one canonical string, final newline included.

    Fragment presence cannot enforce trigger scope, permissions, the commands
    actually run, or the absence of extra network steps: every fragment could
    sit inside a comment while a far broader workflow still passed. Byte
    equality is the only assertion here that means what it says.

    This control addresses **one exact path** and never scans ``.github`` or any
    wider surface.

    Epistemic limit, stated in the control as well as the contract: a workflow
    file, and a job name inside it, cannot establish that a check is not
    required. Required-check status is external repository configuration. This
    phase neither changes nor attests branch protection, and nothing below
    claims it does.
    """
    text = sup.require_future_file(
        sup.WORKFLOW_PATH, ".github/workflows/source-record.yml"
    )
    assert text == sup.WORKFLOW_CONTENT
    assert sup.WORKFLOW_CONTENT.endswith("\n")
    assert "non-required" not in sup.WORKFLOW_CONTENT
    assert "informational, path-scoped" in sup.WORKFLOW_CONTENT
    # The disclosed network surface: two SHA-pinned actions plus one package
    # index installation, pinned to the exact locally observed version.
    assert f"pip install pytest=={sup.PYTEST_PIN}" in sup.WORKFLOW_CONTENT
    assert "Contacts the configured Python package index" in sup.WORKFLOW_CONTENT
    assert sup.WORKFLOW_CONTENT.count("pip install") == 1
    assert sup.WORKFLOW_CONTENT.count("uses:") == 2


def _function_named(source: str, name: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == name:
                return node
    raise AssertionError(f"function not found in the probe source: {name}")


def test_sr_m_020_a_token_assertion_downgraded_to_a_literal_equality_is_detected():
    """In-memory mutation probe for ``exact_token_assertions``.

    Replacing a real ``error.token == "..."`` assertion with a harmless
    ``"..." == "..."`` must lose the binding. An earlier revision counted any
    literal in any equality, so the mutation would have gone unnoticed and a
    token could have kept a control that no longer tested it.
    """
    path = suite_modules()["test_records.py"]
    source = path.read_text(encoding="utf-8")
    real = 'assert excinfo.value.token == "supersedes-cycle"'
    harmless = 'assert "supersedes-cycle" == "supersedes-cycle"'
    assert real in source, "the probe target assertion is missing"

    target = "test_sr_r_018_a_supersession_cycle_is_refused_before_digests_are_compared"
    before = exact_token_assertions(_function_named(source, target))
    assert "supersedes-cycle" in before

    mutated = source.replace(real, harmless)
    assert mutated != source
    after = exact_token_assertions(_function_named(mutated, target))
    assert "supersedes-cycle" not in after, (
        "a literal-to-literal equality must not preserve a token binding"
    )

    # The same discrimination, on minimal synthetic sources.
    counted = (
        'def f():\n    assert error.token == "reference-self"\n',
        'def f():\n    assert "reference-self" == error.token\n',
        'def f():\n    sup.assert_refused(s, p, "reference-self")\n',
        'def f():\n    sup.assert_refused(s, p, "reference-self", ("a",))\n',
    )
    for probe in counted:
        assert "reference-self" in exact_token_assertions(
            _function_named(probe, "f")
        ), probe
    not_counted = (
        'def f():\n    assert "reference-self" == "reference-self"\n',
        'def f():\n    assert error.token in ("reference-self", "reference-cycle")\n',
        'def f():\n    assert label == "reference-self"\n',
        'def f():\n    sup.assert_refused(s, "reference-self")\n',
        'def f():\n    assert error.path == "reference-self"\n',
    )
    for probe in not_counted:
        assert "reference-self" not in exact_token_assertions(
            _function_named(probe, "f")
        ), probe
