"""Structural, type, refusal and validator-behaviour controls.

Implementation-dependent: these fail with ``implementation-absent`` until the
schema and validator exist. Every fixture is synthetic and no locator here
refers to a real resource.

Control ids GV7-S-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from experiments.general_v7_ledger.tests import _support as sup


class HookedStr(str):
    """A str subclass that records whether any hook ran."""

    def __new__(cls, value):
        obj = str.__new__(cls, value)
        obj.hooks = {}
        return obj

    def _bump(self, name):
        self.hooks[name] = self.hooks.get(name, 0) + 1

    def __eq__(self, other):
        self._bump("__eq__")
        return str.__eq__(self, other)

    def __hash__(self):
        self._bump("__hash__")
        return str.__hash__(self)

    def __repr__(self):
        self._bump("__repr__")
        return str.__repr__(self)

    def __len__(self):
        self._bump("__len__")
        return str.__len__(self)


class HookedDict(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.hooks = {}

    def __iter__(self):
        self.hooks["__iter__"] = self.hooks.get("__iter__", 0) + 1
        return dict.__iter__(self)

    def __len__(self):
        self.hooks["__len__"] = self.hooks.get("__len__", 0) + 1
        return dict.__len__(self)


class HookedList(list):
    def __init__(self, *args):
        list.__init__(self, *args)
        self.hooks = {}

    def __iter__(self):
        self.hooks["__iter__"] = self.hooks.get("__iter__", 0) + 1
        return list.__iter__(self)


def refuse(schema, payload, token):
    """Assert ``validate_ledger`` refuses with an exact token and no leakage."""
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    error = excinfo.value
    assert error.token == token, (token, error.token)
    assert error.token in schema.REFUSAL_TOKENS
    rendered = str(error)
    for marker in sup.MARKERS:
        assert marker not in rendered
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    return error


def test_gv7_s_001_the_committed_ledger_validates_against_the_schema():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    schema.validate_ledger(ledger)


def test_gv7_s_002_the_declared_identity_fields_are_exact():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert ledger["schema"] == sup.SCHEMA_ID == schema.SCHEMA_ID
    assert ledger["ledger_id"] == sup.LEDGER_ID == schema.LEDGER_ID
    assert ledger["corpus"] == sup.CORPUS == schema.CORPUS
    assert ledger["intake_state"] == sup.INTAKE_STATE == schema.INTAKE_STATE


def test_gv7_s_003_the_root_key_set_is_closed_and_exact():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert set(ledger) == sup.ROOT_KEYS == set(schema.ROOT_KEYS)
    extra = dict(ledger)
    extra["an_undeclared_root_key"] = "synthetic"
    refuse(schema, extra, "undeclared-key")
    for key in sorted(sup.ROOT_KEYS):
        missing = dict(ledger)
        del missing[key]
        refuse(schema, missing, "missing-key")


def test_gv7_s_004_every_nested_block_key_set_is_closed_and_exact():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    pairs = (
        ("batches", sup.BATCH_KEYS),
        ("sources", sup.SOURCE_KEYS),
        ("claims", sup.CLAIM_KEYS),
        ("relationships", sup.RELATIONSHIP_KEYS),
        ("unresolved", sup.UNRESOLVED_KEYS),
        ("artifacts", sup.ARTIFACT_KEYS),
    )
    for collection, keys in pairs:
        records = sup.collection_of(ledger, collection)
        assert records, collection
        for record in records:
            assert set(record) == keys, (collection, sorted(set(record) ^ keys))
        hostile = json.loads(json.dumps(ledger))
        hostile[collection][0]["an_undeclared_nested_key"] = "synthetic"
        refuse(schema, hostile, "undeclared-key")

    # `corrections` may legitimately be empty, so its closed shape is exercised
    # through a synthetic record rather than by hoping one is committed.
    for record in sup.collection_of(ledger, "corrections"):
        assert set(record) == sup.CORRECTION_KEYS, sorted(
            set(record) ^ sup.CORRECTION_KEYS
        )
    good = with_correction(ledger, synthetic_correction(ledger))
    schema.validate_ledger(good)
    hostile = with_correction(
        ledger, synthetic_correction(ledger, **{"statement": "synthetic"})
    )
    hostile["corrections"][0]["an_undeclared_nested_key"] = "synthetic"
    refuse(schema, hostile, "undeclared-key")


def test_gv7_s_005_the_root_must_be_an_exact_builtin_dict():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    hostile = HookedDict(ledger)
    hostile.hooks.clear()
    refuse(schema, hostile, "type-not-exact")
    assert not hostile.hooks, hostile.hooks
    for wrong in ([], (), "", 0, None):
        refuse(schema, wrong, "root-not-object")


def test_gv7_s_006_hostile_subclasses_are_refused_before_any_hook_runs():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    hostile_value = HookedStr(sup.SCHEMA_ID)
    hostile_value.hooks.clear()
    payload = dict(ledger)
    payload["schema"] = hostile_value
    refuse(schema, payload, "type-not-exact")
    assert not hostile_value.hooks, hostile_value.hooks

    hostile_list = HookedList(ledger["sources"])
    hostile_list.hooks.clear()
    payload = dict(ledger)
    payload["sources"] = hostile_list
    refuse(schema, payload, "type-not-exact")
    assert not hostile_list.hooks, hostile_list.hooks


def test_gv7_s_007_bool_and_int_are_mutually_hostile():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["batches"][0]["batch_ordinal"] = True
    refuse(schema, payload, "type-not-exact")
    payload = json.loads(json.dumps(ledger))
    payload["batches"][0]["batch_ordinal"] = 1.0
    refuse(schema, payload, "float-refused")
    payload = json.loads(json.dumps(ledger))
    payload["batches"][0]["batch_ordinal"] = sup.EXPECTED_BATCHES + 1
    refuse(schema, payload, "int-out-of-range")


def test_gv7_s_008_a_foreign_mapping_key_is_refused_without_being_touched():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = dict(ledger)
    payload[HookedStr(sup.MARKER_KEY)] = "synthetic"
    error = refuse(schema, payload, "key-not-exact-str")
    assert sup.MARKER_KEY not in str(error)


def test_gv7_s_009_every_identifier_is_globally_unique_and_well_formed():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    fields = {
        "batches": "batch_id",
        "sources": "source_id",
        "claims": "claim_id",
        "relationships": "relationship_id",
        "unresolved": "unresolved_id",
        "artifacts": "artifact_id",
        "corrections": "correction_id",
    }
    seen = []
    for collection, field in fields.items():
        for record in sup.collection_of(ledger, collection):
            value = record[field]
            assert sup.ID_RE.match(value), value
            seen.append(value)
    assert len(seen) == len(set(seen)), "identifier collision across collections"

    payload = json.loads(json.dumps(ledger))
    payload["sources"][1]["source_id"] = payload["sources"][0]["source_id"]
    refuse(schema, payload, "identifier-duplicate")

    payload = json.loads(json.dumps(ledger))
    payload["sources"][0]["source_id"] = "GV7-SRC-001"
    refuse(schema, payload, "identifier-malformed")


def test_gv7_s_010_every_reference_resolves_to_an_existing_record_of_its_kind():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    source_ids = set(sup.identifiers(ledger["sources"], "source_id"))
    batch_ids = set(sup.identifiers(ledger["batches"], "batch_id"))
    for claim in ledger["claims"]:
        assert claim["source_ref"] in source_ids, claim["claim_id"]
        assert claim["batch_ref"] in batch_ids, claim["claim_id"]
    for source in ledger["sources"]:
        assert source["batch_ref"] in batch_ids, source["source_id"]

    payload = json.loads(json.dumps(ledger))
    payload["claims"][0]["source_ref"] = "GV7-SRC-9999"
    refuse(schema, payload, "reference-not-found")

    payload = json.loads(json.dumps(ledger))
    payload["claims"][0]["source_ref"] = payload["batches"][0]["batch_id"]
    refuse(schema, payload, "reference-wrong-kind")


def test_gv7_s_011_a_self_relationship_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["relationships"][0]["right_ref"] = payload["relationships"][0]["left_ref"]
    refuse(schema, payload, "relationship-self")


def test_gv7_s_012_duplicate_set_members_and_duplicate_relationships_are_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    limitations = payload["sources"][0]["limitations"]
    payload["sources"][0]["limitations"] = [limitations[0], limitations[0]]
    refuse(schema, payload, "list-duplicate-item")

    payload = json.loads(json.dumps(ledger))
    first = payload["relationships"][0]
    clone = dict(first)
    clone["relationship_id"] = "GV7-REL-9999"
    payload["relationships"].append(clone)
    refuse(schema, payload, "relationship-duplicate")


def test_gv7_s_013_a_list_longer_than_its_declared_bound_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["sources"][0]["limitations"] = [
        f"synthetic limitation {index}" for index in range(sup.LIST_MAX + 1)
    ]
    refuse(schema, payload, "list-length-invalid")


def test_gv7_s_014_validation_is_pure_and_never_mutates_its_input():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    before = json.dumps(ledger, sort_keys=True)
    schema.validate_ledger(ledger)
    assert json.dumps(ledger, sort_keys=True) == before


def test_gv7_s_015_the_committed_bytes_are_unchanged_by_validation():
    validate = sup.require_validate()
    before = sup.LEDGER_PATH.read_bytes()
    validate.validate_ledger_file(sup.LEDGER_PATH)
    assert sup.LEDGER_PATH.read_bytes() == before


def test_gv7_s_016_duplicate_json_keys_are_rejected(tmp_path):
    validate = sup.require_validate()
    path = tmp_path / "ledger.json"
    path.write_text(
        '{"schema": "source-record-v3", "schema": "source-record-v3"}',
        encoding="utf-8",
    )
    with pytest.raises(validate.LedgerInputError) as excinfo:
        validate.validate_ledger_file(path)
    assert excinfo.value.token == "json-duplicate-key"


def test_gv7_s_017_a_parse_step_value_error_is_refused_without_disclosure(tmp_path):
    """The digit-limit ValueError is not a JSONDecodeError and must not escape."""
    validate = sup.require_validate()
    original = sys.get_int_max_str_digits()
    try:
        if original == 0:
            sys.set_int_max_str_digits(4300)
        limit = sys.get_int_max_str_digits()
        digits = limit + 64
        literal = "1" + "0" * (digits - 1)
        path = tmp_path / "ledger.json"
        path.write_text('{"n": ' + literal + "}", encoding="utf-8")
        with pytest.raises(validate.LedgerInputError) as excinfo:
            validate.validate_ledger_file(path)
        error = excinfo.value
        assert error.token == "json-malformed"
        rendered = str(error)
        assert "Exceeds the limit" not in rendered
        assert str(digits) not in rendered
        assert literal[:40] not in rendered
        assert error.__cause__ is None
        assert error.__suppress_context__ is True
    finally:
        sys.set_int_max_str_digits(original)


def test_gv7_s_018_the_byte_ceiling_is_enforced_before_parsing(tmp_path):
    validate = sup.require_validate()
    assert validate.MAX_LEDGER_BYTES == sup.MAX_LEDGER_BYTES
    assert type(validate.MAX_LEDGER_BYTES) is int
    path = tmp_path / "ledger.json"
    path.write_bytes(b"x" * (validate.MAX_LEDGER_BYTES + 1))
    with pytest.raises(validate.LedgerCeilingError) as excinfo:
        validate.validate_ledger_file(path)
    assert excinfo.value.token == "ledger-bytes-ceiling"


def test_gv7_s_019_the_interface_is_exactly_one_supplied_file_path(tmp_path):
    """A path outside the repository is legitimate; a non-file is not.

    CONTRACT.md section 9 withdraws the old "beneath an accepted repository
    root" rule: it was unsatisfiable alongside isolated temporary-file testing,
    and reading exactly one named file is what actually protects the validator.
    """
    validate = sup.require_validate()

    # An isolated temporary file, entirely outside the repository, is accepted
    # as far as the parser — proving the interface is satisfiable.
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    assert str(sup.REPO_ROOT) not in str(outside.resolve())
    with pytest.raises(validate.LedgerInputError):
        validate.validate_ledger_file(outside)

    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path)
    assert excinfo.value.token == "path-not-file"
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path / "absent.json")
    assert excinfo.value.token == "path-missing"


def test_gv7_s_020_a_reparse_point_in_the_supplied_path_is_refused(tmp_path):
    """Deterministic on Windows without privilege: a directory junction.

    The fixture links a *directory* — the accepted neutral approach — and the
    supplied ledger path passes through it. A junction is a reparse point that
    ``os.path.islink`` and ``Path.is_symlink`` both report as False, so a
    validator inspecting only that predicate would follow it. Cleanup is
    bounded to the temporary fixture; no machine setting is changed and no
    Developer Mode or administrator privilege is required.
    """
    validate = sup.require_validate()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "ledger.json").write_text("{}", encoding="utf-8")

    link_dir = tmp_path / "linked"
    mechanism = sup.make_reparse_directory(link_dir, real_dir)
    assert sup.is_reparse_point(link_dir), mechanism

    through = link_dir / "ledger.json"
    assert through.exists()
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(through)
    assert excinfo.value.token == "path-symlink-refused"


def test_gv7_s_021_no_environment_variable_or_cwd_locates_the_input(
    tmp_path, monkeypatch
):
    validate = sup.require_validate()
    monkeypatch.chdir(tmp_path)
    for name in ("LEDGER", "LEDGER_PATH", "GV7_LEDGER"):
        monkeypatch.setenv(name, str(tmp_path))
    (tmp_path / "ledger.json").write_text("{}", encoding="utf-8")
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path / "absent.json")
    assert excinfo.value.token == "path-missing"
    with pytest.raises(SystemExit) as systemexit:
        validate.main([])
    assert systemexit.value.code == 2


def test_gv7_s_022_a_refusal_carries_only_a_token_and_a_schema_declared_path():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = dict(ledger)
    payload["intake_state"] = sup.MARKER_VALUE
    with pytest.raises(schema.LedgerError) as excinfo:
        schema.validate_ledger(payload)
    error = excinfo.value
    assert isinstance(error.token, str)
    assert isinstance(error.path, tuple)
    assert sup.MARKER_VALUE not in str(error)
    for name in dir(error):
        assert "value" not in name.lower(), name


def test_gv7_s_023_the_refusal_vocabulary_is_closed_and_well_formed():
    schema = sup.require_schema()
    tokens = tuple(schema.REFUSAL_TOKENS)
    assert tokens
    assert len(tokens) == len(set(tokens))
    for token in tokens:
        assert token == token.lower()
        assert token.strip() == token and token
        assert set(token) <= set("abcdefghijklmnopqrstuvwxyz-")


def test_gv7_s_024_success_emits_one_canonical_json_line(tmp_path, capsys):
    validate = sup.require_validate()
    code = validate.main([str(sup.LEDGER_PATH)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    body = captured.out[:-1]
    assert body == json.dumps(
        json.loads(body), sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )


def test_gv7_s_025_output_is_byte_identical_across_repeated_runs(capsys):
    validate = sup.require_validate()
    outputs = []
    for _ in range(3):
        validate.main([str(sup.LEDGER_PATH)])
        outputs.append(capsys.readouterr().out)
    assert len(set(outputs)) == 1


def test_gv7_s_026_output_is_identical_across_processes_and_optimisation_levels():
    sup.require_validate()
    outputs = []
    for flags, seed in ((["-B"], "0"), (["-B", "-O"], "1"), (["-B", "-OO"], "12345")):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(sup.REPO_ROOT)
        completed = subprocess.run(
            [sys.executable, *flags, "-m",
             "experiments.general_v7_ledger.validate", str(sup.LEDGER_PATH)],
            capture_output=True, env=env, cwd=str(sup.REPO_ROOT), check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
        outputs.append(completed.stdout)
    assert len(set(outputs)) == 1


def test_gv7_s_027_no_timestamp_or_environment_value_appears_in_the_output(capsys):
    validate = sup.require_validate()
    validate.main([str(sup.LEDGER_PATH)])
    out = capsys.readouterr().out
    for fragment in (str(os.getpid()), "T00:", str(sup.REPO_ROOT)):
        assert fragment not in out


def test_gv7_s_028_neither_module_imports_a_network_capable_module():
    import ast

    for name in ("schema.py", "validate.py"):
        path = sup.LAB_DIR / name
        text = sup.require_file(path, name)
        roots = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                roots.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                roots.add(node.module or "")
        for forbidden in sup.NETWORK_CAPABLE_MODULES:
            assert forbidden not in roots, (name, forbidden)
            for root in roots:
                assert not root.startswith(forbidden + "."), (name, root)


def test_gv7_s_029_no_production_module_contains_a_bare_assert_or_broad_catch():
    import ast

    for name in ("schema.py", "validate.py"):
        text = sup.require_file(sup.LAB_DIR / name, name)
        tree = ast.parse(text)
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)], name
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            assert node.type is not None, name
            targets = (
                node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            )
            for target in targets:
                label = getattr(target, "id", None) or getattr(target, "attr", None)
                assert label not in ("Exception", "BaseException"), (name, label)


def test_gv7_s_030_emitted_counts_equal_the_actual_collection_lengths(capsys):
    validate = sup.require_validate()
    ledger = sup.require_ledger()
    validate.main([str(sup.LEDGER_PATH)])
    summary = json.loads(capsys.readouterr().out)
    counts = summary["counts"]
    for key in sup.COLLECTION_KEYS:
        assert counts[key] == len(ledger[key]), key
    assert set(counts) == set(sup.COLLECTION_KEYS)


# --------------------------------------------------------------------------
# Reference integrity, per reference field. CONTRACT.md sections 6b-6h.
# --------------------------------------------------------------------------

REFERENCE_CASES = (
    ("batches", "introduces_sources", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("batches", "introduces_artifacts", "GV7-ART-9999", "GV7-BAT-0001"),
    ("batches", "updates_sources", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("sources", "batch_ref", "GV7-BAT-9999", "GV7-SRC-9999"),
    ("claims", "source_ref", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("claims", "batch_ref", "GV7-BAT-9999", "GV7-CLM-9999"),
    ("artifacts", "introducing_batch", "GV7-BAT-9999", "GV7-SRC-0001"),
    ("relationships", "left_ref", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("relationships", "right_ref", "GV7-CLM-9999", "GV7-BAT-0001"),
    ("unresolved", "refs", "GV7-SRC-9999", "GV7-BAT-0001"),
    ("corrections", "target_ref", "GV7-SRC-9999", None),
)


def test_gv7_s_031_every_reference_field_refuses_an_unresolvable_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection, field, dangling, _wrong in REFERENCE_CASES:
        records = ledger.get(collection) or []
        if not records:
            continue
        payload = json.loads(json.dumps(ledger))
        target = payload[collection][0]
        if isinstance(target[field], list):
            target[field] = [dangling]
        else:
            target[field] = dangling
        refuse(schema, payload, "reference-not-found")


def test_gv7_s_032_every_reference_field_refuses_a_wrong_kind_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection, field, _dangling, wrong in REFERENCE_CASES:
        if wrong is None:
            continue
        records = ledger.get(collection) or []
        if not records:
            continue
        payload = json.loads(json.dumps(ledger))
        target = payload[collection][0]
        if isinstance(target[field], list):
            target[field] = [wrong]
        else:
            target[field] = wrong
        refuse(schema, payload, "reference-wrong-kind")


def test_gv7_s_033_batch_and_record_introduction_must_stay_reciprocal():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    for batch in payload["batches"]:
        if batch["introduces_sources"]:
            batch["introduces_sources"] = list(batch["introduces_sources"])[1:]
            break
    refuse(schema, payload, "introduction-not-reciprocal")

    payload = json.loads(json.dumps(ledger))
    for batch in payload["batches"]:
        if batch["introduces_artifacts"]:
            batch["introduces_artifacts"] = []
            break
    refuse(schema, payload, "introduction-not-reciprocal")


# --------------------------------------------------------------------------
# Correction and supersession. Synthetic throughout: these rules must hold
# whether or not the committed ledger happens to carry a correction.
# --------------------------------------------------------------------------


def synthetic_correction(ledger, **overrides):
    target = ledger["sources"][0]["source_id"]
    record = {
        "correction_id": "GV7-COR-0001",
        "target_ref": target,
        "correction_kind": "correction",
        "statement": "synthetic additive correction for control purposes",
        "recorded_by_role": "auditor",
        "recorded_by_label": "synthetic recorder",
    }
    record.update(overrides)
    return record


def with_correction(ledger, record):
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [record]
    return payload


def test_gv7_s_034_a_well_formed_synthetic_correction_is_accepted():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = with_correction(ledger, synthetic_correction(ledger))
    schema.validate_ledger(payload)
    assert set(payload["corrections"][0]) == sup.CORRECTION_KEYS


def test_gv7_s_035_a_correction_with_a_wrong_key_set_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    record = synthetic_correction(ledger)
    record["an_undeclared_nested_key"] = "synthetic"
    refuse(schema, with_correction(ledger, record), "undeclared-key")
    for key in sorted(sup.CORRECTION_KEYS):
        record = synthetic_correction(ledger)
        del record[key]
        refuse(schema, with_correction(ledger, record), "missing-key")


def test_gv7_s_036_a_correction_with_a_bad_id_kind_or_target_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    refuse(
        schema,
        with_correction(ledger, synthetic_correction(ledger, correction_id="COR-1")),
        "identifier-malformed",
    )
    refuse(
        schema,
        with_correction(ledger, synthetic_correction(ledger, correction_kind="edit")),
        "enum-value-invalid",
    )
    refuse(
        schema,
        with_correction(
            ledger, synthetic_correction(ledger, target_ref="GV7-SRC-9999")
        ),
        "reference-not-found",
    )


def test_gv7_s_037_a_correction_never_removes_or_edits_its_target():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    target_id = ledger["sources"][0]["source_id"]
    payload = with_correction(ledger, synthetic_correction(ledger))
    before = sup.canonical_bytes(payload["sources"][0])
    schema.validate_ledger(payload)
    survivors = [s for s in payload["sources"] if s["source_id"] == target_id]
    assert len(survivors) == 1, "the corrected record must remain present"
    assert sup.canonical_bytes(survivors[0]) == before, "corrections are additive"


def test_gv7_s_038_a_valid_synthetic_supersession_chain_is_accepted():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    predecessor = payload["sources"][0]
    successor = json.loads(json.dumps(predecessor))
    successor["source_id"] = "GV7-SRC-0099"
    successor["supersedes"] = {
        "record_id": predecessor["source_id"],
        "content_digest": sup.canonical_digest(predecessor),
    }
    payload["sources"].append(successor)
    schema.validate_ledger(payload)
    assert any(
        s["source_id"] == predecessor["source_id"] for s in payload["sources"]
    ), "the predecessor must remain present"


def test_gv7_s_039_a_supersedes_block_of_the_wrong_shape_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    predecessor = ledger["sources"][0]
    good = {
        "record_id": predecessor["source_id"],
        "content_digest": sup.canonical_digest(predecessor),
    }
    for key in sorted(sup.SUPERSEDES_KEYS):
        payload = json.loads(json.dumps(ledger))
        block = dict(good)
        del block[key]
        payload["sources"][1]["supersedes"] = block
        refuse(schema, payload, "missing-key")
    payload = json.loads(json.dumps(ledger))
    block = dict(good)
    block["an_undeclared_nested_key"] = "synthetic"
    payload["sources"][1]["supersedes"] = block
    refuse(schema, payload, "undeclared-key")


def test_gv7_s_040_a_supersedes_digest_mismatch_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["sources"][1]["supersedes"] = {
        "record_id": payload["sources"][0]["source_id"],
        "content_digest": "0" * 64,
    }
    refuse(schema, payload, "supersedes-digest-mismatch")
    payload = json.loads(json.dumps(ledger))
    payload["sources"][1]["supersedes"] = {
        "record_id": payload["sources"][0]["source_id"],
        "content_digest": "G" * 64,
    }
    refuse(schema, payload, "digest-format-invalid")


def test_gv7_s_041_a_missing_or_cross_collection_predecessor_is_refused():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    payload["sources"][1]["supersedes"] = {
        "record_id": "GV7-SRC-9999",
        "content_digest": "a" * 64,
    }
    refuse(schema, payload, "supersedes-target-missing")

    payload = json.loads(json.dumps(ledger))
    claim = payload["claims"][0]
    payload["sources"][1]["supersedes"] = {
        "record_id": claim["claim_id"],
        "content_digest": sup.canonical_digest(claim),
    }
    refuse(schema, payload, "supersedes-collection-mismatch")


def test_gv7_s_042_a_supersession_cannot_promote_verification_state():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    payload = json.loads(json.dumps(ledger))
    predecessor = payload["sources"][0]
    successor = json.loads(json.dumps(predecessor))
    successor["source_id"] = "GV7-SRC-0099"
    successor["verification_state"] = "identity-verified"
    successor["supersedes"] = {
        "record_id": predecessor["source_id"],
        "content_digest": sup.canonical_digest(predecessor),
    }
    payload["sources"].append(successor)
    refuse(schema, payload, "enum-value-invalid")


def test_gv7_s_043_a_relationship_carries_its_own_unverified_provenance():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for field, value, token in (
        ("verification_state", "identity-verified", "enum-value-invalid"),
        ("attribution_class", "verified-implementation-evidence",
         "enum-value-invalid"),
        ("limitations", [], "list-length-invalid"),
    ):
        payload = json.loads(json.dumps(ledger))
        payload["relationships"][0][field] = value
        refuse(schema, payload, token)
    payload = json.loads(json.dumps(ledger))
    first = payload["relationships"][0]["limitations"][0]
    payload["relationships"][0]["limitations"] = [first, first]
    refuse(schema, payload, "list-duplicate-item")


def test_gv7_s_044_safety_dispositions_is_a_bounded_exclusive_list():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection in ("sources", "claims", "artifacts"):
        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = []
        refuse(schema, payload, "list-length-invalid")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = [
            "quarantined-covert-communication",
            "quarantined-covert-communication",
        ]
        refuse(schema, payload, "list-duplicate-item")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = ["not-a-disposition"]
        refuse(schema, payload, "enum-value-invalid")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = [
            "ordinary",
            "quarantined-hidden-monitoring",
        ]
        refuse(schema, payload, "disposition-ordinary-not-exclusive")

        payload = json.loads(json.dumps(ledger))
        payload[collection][0]["safety_dispositions"] = "ordinary"
        refuse(schema, payload, "type-not-exact")
