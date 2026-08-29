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


def test_gv7_s_013_a_nested_list_longer_than_list_max_is_refused():
    """``LIST_MAX`` is a NESTED bound. ``GV7-S-047`` proves it is not a root one."""
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
    schema = sup.require_schema()
    validate = sup.require_validate()

    # An isolated temporary file, entirely outside the repository. `{}` is
    # well-formed JSON whose ONLY defect is at the CONTENT stage, so the exact
    # content-stage token is the proof that the path was accepted, the bytes
    # captured, the ceiling checked, the JSON parsed and the root object
    # entered. A refusal that merely shares a superclass proves none of that.
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    resolved = str(outside.resolve()).casefold()
    root = str(sup.REPO_ROOT).casefold()
    assert not resolved.startswith(root), "the fixture must lie outside the repo"

    with pytest.raises(schema.LedgerError) as excinfo:
        validate.validate_ledger_file(outside)
    error = excinfo.value
    assert error.token == "missing-key", error.token
    for earlier in (
        validate.LedgerPathError,
        validate.LedgerCeilingError,
        validate.LedgerInputError,
    ):
        assert not isinstance(error, earlier), earlier.__name__
    assert error.__cause__ is None
    assert error.__suppress_context__ is True

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
    # The refusal predicate, not the bare attribute: a cloud placeholder also
    # carries FILE_ATTRIBUTE_REPARSE_POINT and must NOT be refused.
    assert sup.is_refused_reparse_point(link_dir), mechanism
    assert not sup.is_refused_reparse_point(real_dir)

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
    # By content, not only by attribute name: a rejected value stashed as
    # ``.payload``, ``.item`` or ``.got`` would pass a name screen.
    assert set(vars(error)) == {"token", "path"}, sorted(vars(error))
    for attribute in vars(error).values():
        assert sup.MARKER_VALUE not in repr(attribute)
    # A schema-declared path carries declared keys, never an input-derived
    # value: every element is a str key or an int index.
    for element in error.path:
        assert type(element) in (str, int), element
        if isinstance(element, str):
            assert sup.MARKER_VALUE != element


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


def test_gv7_s_028_no_production_module_imports_outside_its_allowance():
    """An allowlist, not a blocklist -- and it is the authoritative rule.

    A blocklist admits every network-capable package published tomorrow. An
    allowlist over imported roots, together with the ban on dynamic-import
    mechanisms, is what actually establishes that no code path could retrieve
    anything. ``__init__.py`` is included: it is a production module, it runs
    on every import of ``schema``, and it was previously unscanned.
    """
    import ast

    for name in sup.PRODUCTION_MODULES:
        path = sup.LAB_DIR / name
        text = sup.require_file(path, name)
        roots = set()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                roots.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, (name, "relative import")
                roots.add(node.module or "")
        for root in sorted(roots):
            assert root in sup.PRODUCTION_ALLOWED_IMPORTS, (name, root)
        # Retained belt-and-braces: the allowlist already excludes these.
        for forbidden in sup.NETWORK_CAPABLE_MODULES:
            assert forbidden not in roots, (name, forbidden)
            for root in roots:
                assert not root.startswith(forbidden + "."), (name, root)


def test_gv7_s_029_no_production_module_contains_a_bare_assert_or_broad_catch():
    import ast

    for name in sup.PRODUCTION_MODULES:
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


def find_batch(payload, batch_id):
    return next(b for b in payload["batches"] if b["batch_id"] == batch_id)


def other_batch(payload, batch_id, list_field):
    """A spare batch that can legitimately carry the listing under test.

    Batch 62 introduces no source and batch 63 introduces neither, so using
    either as the spare would draw a refusal from *that* frozen rule instead of
    from reciprocity -- the control would pass for the wrong reason. Both are
    excluded.
    """
    special = (sup.ARTIFACT_BEARING_BATCH, sup.BIBLIOGRAPHY_BATCH)
    return next(
        b for b in payload["batches"]
        if b["batch_id"] != batch_id
        and b["batch_id"] not in special
        and not b[list_field]
    )


def drop_listing(batch, list_field, value):
    batch[list_field] = [item for item in batch[list_field] if item != value]


def test_gv7_s_033_source_introduction_must_be_reciprocal_in_both_directions():
    """Existence is not reciprocity: both sides must agree, and only once."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    source_id = ledger["sources"][0]["source_id"]
    batch_id = ledger["sources"][0]["batch_ref"]

    # (a) the record names its batch, but the batch omits it.
    payload = json.loads(json.dumps(ledger))
    drop_listing(find_batch(payload, batch_id), "introduces_sources", source_id)
    refuse(schema, payload, "introduction-not-reciprocal")

    # (b) a DIFFERENT batch lists it and its own batch does not. Dropping the
    # original listing is what makes this distinct from (c): without that line
    # (b) and (c) construct the identical double-listing payload, and the case
    # the contract names -- "a batch listing a record whose own introducing
    # field points elsewhere" -- is never built at all.
    payload = json.loads(json.dumps(ledger))
    drop_listing(find_batch(payload, batch_id), "introduces_sources", source_id)
    other_batch(payload, batch_id, "introduces_sources")["introduces_sources"] = [
        source_id
    ]
    refuse(schema, payload, "introduction-not-reciprocal")

    # (c) the same valid record is listed by two batches: the original listing
    # stays in place, so this payload differs from (b) by exactly one element.
    payload = json.loads(json.dumps(ledger))
    assert source_id in find_batch(payload, batch_id)["introduces_sources"]
    other_batch(payload, batch_id, "introduces_sources")["introduces_sources"] = [
        source_id
    ]
    refuse(schema, payload, "introduction-not-reciprocal")


def test_gv7_s_046_artifact_introduction_must_be_reciprocal_in_both_directions():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    artifact_id = "GV7-ART-0001"
    batch_id = sup.ARTIFACT_BATCHES[artifact_id]

    # (a) the artifact names its batch, but the batch omits it.
    payload = json.loads(json.dumps(ledger))
    drop_listing(
        find_batch(payload, batch_id), "introduces_artifacts", artifact_id
    )
    refuse(schema, payload, "introduction-not-reciprocal")

    # (b) a DIFFERENT batch lists it and its own batch does not.
    payload = json.loads(json.dumps(ledger))
    drop_listing(
        find_batch(payload, batch_id), "introduces_artifacts", artifact_id
    )
    other_batch(payload, batch_id, "introduces_artifacts")[
        "introduces_artifacts"
    ] = [artifact_id]
    refuse(schema, payload, "introduction-not-reciprocal")

    # (c) the same valid artifact is listed by two batches.
    payload = json.loads(json.dumps(ledger))
    assert artifact_id in find_batch(payload, batch_id)["introduces_artifacts"]
    other_batch(payload, batch_id, "introduces_artifacts")[
        "introduces_artifacts"
    ] = [artifact_id]
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


# ==========================================================================
# Correction 3. Every control below drives the production module. A mirror
# check over ``_support`` constants establishes nothing about an implementation
# and is never counted as coverage here.
# ==========================================================================


def mutate(ledger, collection, field, value, index=0):
    payload = json.loads(json.dumps(ledger))
    payload[collection][index][field] = value
    return payload


def source_index(ledger, with_locator):
    for index, source in enumerate(ledger["sources"]):
        if (source["supplied_locator"] is not None) is with_locator:
            return index
    raise AssertionError(
        f"the committed ledger has no source with_locator={with_locator}"
    )


def many_corrections(ledger, count):
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [
        synthetic_correction(ledger, correction_id=f"GV7-COR-{n:04d}")
        for n in range(1, count + 1)
    ]
    return payload


# ---------------------------------------------------- B: collection ceilings


def test_gv7_s_047_a_root_collection_is_not_capped_by_list_max():
    """65 well-formed corrections. ``LIST_MAX`` is a nested bound only.

    Section 9 used to say "every list is duplicate-free and within LIST_MAX",
    and a root collection is a list. Applying 64 there caps the ledger's entire
    additive history channel at 64 records.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert sup.LIST_MAX == 64
    payload = many_corrections(ledger, sup.LIST_MAX + 1)
    assert len(payload["corrections"]) == 65 > sup.LIST_MAX
    schema.validate_ledger(payload)


def test_gv7_s_048_a_root_collection_beyond_the_root_ceiling_is_refused():
    """The root ceiling is real, and the nested bound is still separate."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    assert sup.ROOT_COLLECTION_MAX > sup.LIST_MAX
    payload = many_corrections(ledger, sup.ROOT_COLLECTION_MAX + 1)
    refuse(schema, payload, "collection-length-invalid")

    # The nested bound is unchanged by the root ceiling.
    payload = mutate(
        ledger,
        "sources",
        "limitations",
        [f"synthetic limitation {n}" for n in range(sup.LIST_MAX + 1)],
    )
    refuse(schema, payload, "list-length-invalid")

    # A root collection that is empty where section 5 requires records.
    for collection in ("sources", "batches", "relationships", "unresolved"):
        payload = json.loads(json.dumps(ledger))
        payload[collection] = []
        refuse(schema, payload, "collection-length-invalid")


# ------------------------------------------------------- G: counts are computed


def test_gv7_s_049_every_emitted_count_is_computed_from_its_collection(
    tmp_path, capsys
):
    """One added record must move exactly one count, by exactly one.

    A hardcoded count table transcribed from the committed ledger satisfies a
    single-observation equality check. It cannot satisfy a delta.
    """
    schema = sup.require_schema()
    validate = sup.require_validate()
    ledger = sup.require_ledger()

    base = json.loads(json.dumps(ledger))
    plus_one = many_corrections(ledger, len(base["corrections"]) + 1)
    plus_two = many_corrections(ledger, len(base["corrections"]) + 2)
    for payload in (base, plus_one, plus_two):
        schema.validate_ledger(payload)

    def counts_of(payload, name):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert validate.main([str(path)]) == 0
        return json.loads(capsys.readouterr().out)

    before = counts_of(base, "base.json")
    after = counts_of(plus_one, "plus_one.json")
    after_two = counts_of(plus_two, "plus_two.json")

    # (a) exactly one count moved, and by exactly one.
    assert after["counts"]["corrections"] == before["counts"]["corrections"] + 1
    for key in sup.COLLECTION_KEYS:
        if key == "corrections":
            continue
        assert after["counts"][key] == before["counts"][key], key

    # (b) a length, not an increment and not a non-empty flag.
    assert (
        after_two["counts"]["corrections"] == before["counts"]["corrections"] + 2
    )
    assert after["counts"]["corrections"] == len(plus_one["corrections"])

    # (c) nothing outside `counts` drifted with the input.
    assert {k: v for k, v in after.items() if k != "counts"} == {
        k: v for k, v in before.items() if k != "counts"
    }


# ------------------------------------------- C: supersession is closed to null


def test_gv7_s_050_supersedes_is_closed_to_null_and_non_null_is_refused():
    """v1 has no live supersession channel, so it admits no block."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    for record in ledger["sources"] + ledger["claims"]:
        assert record["supersedes"] is None, record

    predecessor = ledger["sources"][0]
    block = {
        "record_id": predecessor["source_id"],
        "content_digest": sup.canonical_digest(predecessor),
    }
    # A perfectly well-formed block, refused for being a block at all.
    refuse(
        schema,
        mutate(ledger, "sources", "supersedes", block, index=1),
        "supersedes-not-permitted",
    )
    claim_predecessor = ledger["claims"][0]
    refuse(
        schema,
        mutate(
            ledger,
            "claims",
            "supersedes",
            {
                "record_id": claim_predecessor["claim_id"],
                "content_digest": sup.canonical_digest(claim_predecessor),
            },
            index=1,
        ),
        "supersedes-not-permitted",
    )
    # Anything else in the slot is a type fault, not a supersession.
    refuse(
        schema,
        mutate(ledger, "sources", "supersedes", "", index=1),
        "type-not-exact",
    )
    # Control: the committed null value is accepted.
    schema.validate_ledger(json.loads(json.dumps(ledger)))


def test_gv7_s_051_a_correction_may_not_target_another_correction():
    """Structurally impossible cycles beat a graph traversal nobody wrote."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    # An ordinary target in each permitted collection is accepted.
    for collection in sup.CORRECTION_TARGET_COLLECTIONS:
        records = ledger.get(collection) or []
        if not records:
            continue
        field = sup.ID_FIELD_BY_COLLECTION[collection]
        payload = with_correction(
            ledger, synthetic_correction(ledger, target_ref=records[0][field])
        )
        schema.validate_ledger(payload)

    # A self-target.
    record = synthetic_correction(ledger, target_ref="GV7-COR-0001")
    assert record["correction_id"] == "GV7-COR-0001"
    refuse(
        schema,
        with_correction(ledger, record),
        "correction-target-not-permitted",
    )

    # A two-record cycle, both records otherwise valid.
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [
        synthetic_correction(
            ledger, correction_id="GV7-COR-0001", target_ref="GV7-COR-0002"
        ),
        synthetic_correction(
            ledger, correction_id="GV7-COR-0002", target_ref="GV7-COR-0001"
        ),
    ]
    refuse(schema, payload, "correction-target-not-permitted")

    # A correction targeting an unrelated, existing correction: still refused,
    # and refused for its kind rather than for being missing.
    payload = json.loads(json.dumps(ledger))
    payload["corrections"] = [
        synthetic_correction(ledger, correction_id="GV7-COR-0001"),
        synthetic_correction(
            ledger, correction_id="GV7-COR-0002", target_ref="GV7-COR-0001"
        ),
    ]
    error = refuse(schema, payload, "correction-target-not-permitted")
    assert error.token != "reference-not-found"


# ------------------------------ H: the production vocabularies are the frozen ones


VOCABULARY_NAMES = (
    "ATTRIBUTION_CLASSES",
    "CLAIM_ATTRIBUTION_CLASSES",
    "RELATIONSHIP_ATTRIBUTION_CLASSES",
    "ARTIFACT_CLASSES",
    "BATCH_KINDS",
    "CLAIM_VERIFICATION_STATES",
    "CONFLICT_FAMILIES",
    "CORRECTION_KINDS",
    "EXECUTABLE_STATES",
    "IDENTITY_ORIGINS",
    "LOCATOR_ABSENCE_REASONS",
    "METADATA_PROVENANCE",
    "PRESERVATION_STATES",
    "RELATIONSHIP_BASES",
    "RELATIONSHIP_TYPES",
    "RELATIONSHIP_VERIFICATION_STATES",
    "RETRIEVAL_STATES",
    "ROLES",
    "SAFETY_DISPOSITIONS",
    "SOURCE_VERIFICATION_STATES",
    "UNRESOLVED_STATES",
)

SCALAR_NAMES = ("LABEL_MAX", "TEXT_MAX", "LIST_MAX", "ROOT_COLLECTION_MAX")


def test_gv7_s_052_the_production_vocabularies_are_the_frozen_vocabularies():
    """Otherwise a validator whose ROLES quietly gained a value passes."""
    schema = sup.require_schema()
    for name in VOCABULARY_NAMES:
        assert hasattr(schema, name), name
        assert tuple(getattr(schema, name)) == getattr(sup, name), name
    for name in SCALAR_NAMES:
        assert getattr(schema, name) == getattr(sup, name), name
        assert type(getattr(schema, name)) is int, name
    for collection, keys in sorted(sup.KEYS_BY_COLLECTION.items()):
        assert frozenset(schema.KEYS_BY_COLLECTION[collection]) == keys, collection
    assert frozenset(schema.ROOT_KEYS) == sup.ROOT_KEYS
    assert schema.ID_PATTERN == sup.ID_PATTERN
    assert schema.NOT_SUPPLIED == sup.NOT_SUPPLIED
    # The production vocabularies carry no promoting token either.
    for name in VOCABULARY_NAMES:
        for token in getattr(schema, name):
            for fragment in sup.FORBIDDEN_PROMOTION_FRAGMENTS:
                assert fragment not in token, (name, token, fragment)


def test_gv7_s_053_every_closed_vocabulary_refuses_an_invalid_value():
    """One table, every closed vocabulary, each reaching the validator."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    cases = (
        ("batches", "batch_kind", "synthetic-kind"),
        ("batches", "supplied_by_role", "synthetic-role"),
        ("sources", "carrier_role", "synthetic-role"),
        ("sources", "metadata_provenance", "synthetic-provenance"),
        ("sources", "retrieval_state", "retrieved"),
        ("sources", "verification_state", "identity-verified"),
        ("claims", "attribution_class", "synthetic-class"),
        ("claims", "verification_state", "claim-source-matched"),
        ("relationships", "relationship_type", "synthetic-type"),
        ("relationships", "basis", "synthetic-basis"),
        ("relationships", "attribution_class", "synthetic-class"),
        ("relationships", "verification_state", "identity-verified"),
        ("relationships", "recorded_by_role", "synthetic-role"),
        ("unresolved", "conflict_family", "synthetic-family"),
        ("unresolved", "resolution_state", "resolved"),
        ("unresolved", "recorded_by_role", "synthetic-role"),
        ("artifacts", "artifact_class", "authorization"),
        ("artifacts", "identity_origin", "synthetic-origin"),
        ("artifacts", "preservation_status", "adopted"),
        ("artifacts", "executable_status", "executable"),
    )
    for collection, field, value in cases:
        refuse(
            schema,
            mutate(ledger, collection, field, value),
            "enum-value-invalid",
        )
    # locator_absence is closed too, on a source that legitimately has one.
    without = source_index(ledger, with_locator=False)
    refuse(
        schema,
        mutate(
            ledger, "sources", "locator_absence", "synthetic-reason", index=without
        ),
        "enum-value-invalid",
    )
    # And the correction vocabulary, through the synthetic path.
    refuse(
        schema,
        with_correction(ledger, synthetic_correction(ledger, correction_kind="edit")),
        "enum-value-invalid",
    )


def test_gv7_s_054_the_identifier_grammar_is_enforced_by_the_validator():
    r"""``[0-9]`` is load-bearing, and the proof must reach production.

    ``\d`` matches Arabic-Indic and Devanagari digits and ``int()`` parses
    them, so a grammar written with ``\d`` would admit an identifier that
    renders as an ASCII id in some fonts and is a different string.
    """
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    malformed = (
        "GV7-SRC-\u0660\u0660\u0661\u0662",   # Arabic-Indic digits
        "GV7-SRC-\u0966\u0967\u0968\u0969",   # Devanagari digits
        "GV7-SRC-\uff10\uff10\uff10\uff11",   # full-width digits
        "GV7-SRC-001",
        "GV7-SRC-00001",
        "gv7-src-0001",
        "GV7-XXX-0001",
        "GV7-SRC-0001\n",                     # \A..\Z anchoring, not ^..$
        " GV7-SRC-0001",
        "",
    )
    for value in malformed:
        assert not sup.ID_RE.match(value), value
        refuse(
            schema,
            mutate(ledger, "sources", "source_id", value),
            "identifier-malformed",
        )

    # A well-formed id of the WRONG segment for its collection.
    for collection, field, wrong in (
        ("sources", "source_id", "GV7-BAT-0007"),
        ("batches", "batch_id", "GV7-SRC-0007"),
        ("claims", "claim_id", "GV7-REL-0007"),
        ("relationships", "relationship_id", "GV7-UNR-0007"),
        ("unresolved", "unresolved_id", "GV7-ART-0007"),
        ("artifacts", "artifact_id", "GV7-COR-0007"),
    ):
        assert sup.ID_RE.match(wrong), wrong
        refuse(
            schema,
            mutate(ledger, collection, field, wrong),
            "identifier-wrong-collection",
        )


def test_gv7_s_055_a_batch_ordinal_must_agree_with_its_own_identifier():
    """In range, and still wrong: the two must be checked against each other."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    first = ledger["batches"][0]
    assert first["batch_id"] == f"GV7-BAT-{first['batch_ordinal']:04d}"
    disagreeing = 1 if first["batch_ordinal"] != 1 else 2
    assert 1 <= disagreeing <= sup.EXPECTED_BATCHES
    refuse(
        schema,
        mutate(ledger, "batches", "batch_ordinal", disagreeing),
        "ordinal-id-mismatch",
    )
    for out_of_range in (0, -1, sup.EXPECTED_BATCHES + 1):
        refuse(
            schema,
            mutate(ledger, "batches", "batch_ordinal", out_of_range),
            "int-out-of-range",
        )


# ------------------------------------------------------ I/H: locators and dates


def test_gv7_s_056_every_locator_pairing_rule_is_enforced():
    """Present-or-null together, and the absence token exactly complements."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    with_locator = source_index(ledger, with_locator=True)
    without = source_index(ledger, with_locator=False)
    supplied = ledger["sources"][with_locator]["supplied_locator"]
    normalized = ledger["sources"][with_locator]["normalized_locator"]

    def paired(index, **fields):
        payload = json.loads(json.dumps(ledger))
        payload["sources"][index].update(fields)
        return payload

    cases = (
        # supplied present, normalized null
        paired(with_locator, normalized_locator=None),
        # supplied null, normalized present
        paired(with_locator, supplied_locator=None),
        # both present AND an absence reason
        paired(with_locator, locator_absence="no-exact-locator-supplied"),
        # both null AND no absence reason
        paired(without, locator_absence=None),
        # absent source given a locator but keeping its absence token
        paired(without, supplied_locator=supplied, normalized_locator=normalized),
    )
    for payload in cases:
        refuse(schema, payload, "locator-pairing-invalid")


def test_gv7_s_057_a_normalized_locator_must_be_https_only_in_shape():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    index = source_index(ledger, with_locator=True)
    for value in (
        "http://example.invalid/a",
        "HTTPS://example.invalid/a",
        "ftp://example.invalid/a",
        "https:/example.invalid/a",
        "//example.invalid/a",
        " https://example.invalid/a",
        "https://example.invalid/a ",
        "example.invalid/a",
        "",
    ):
        refuse(
            schema,
            mutate(ledger, "sources", "normalized_locator", value, index=index),
            "locator-not-https",
        )


def test_gv7_s_061_supplied_and_normalized_dates_are_paired_and_verbatim():
    """A supplied date is kept as supplied; only the normalized form is ISO."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for source in ledger["sources"]:
        supplied = source["supplied_date"]
        normalized = source["normalized_date"]
        assert type(supplied) is str and supplied, source["source_id"]
        assert normalized is None or sup.ISO_DATE_RE.match(normalized), (
            source["source_id"],
            normalized,
        )
        if supplied == sup.NOT_SUPPLIED:
            assert normalized is None, source["source_id"]

    def dated(**fields):
        payload = json.loads(json.dumps(ledger))
        payload["sources"][0].update(fields)
        return payload

    # not-supplied with a normalized date is a contradiction.
    refuse(
        schema,
        dated(supplied_date=sup.NOT_SUPPLIED, normalized_date="2024-03-01"),
        "date-pairing-invalid",
    )
    # A malformed normalized date, including a non-ASCII-digit one.
    for value in (
        "2024-13-45",
        "2024-3-1",
        "01/02/2024",
        "Spring 2024",
        "\u0662\u0660\u0662\u0664-\u0660\u0663-\u0660\u0661",
        "",
    ):
        refuse(schema, dated(normalized_date=value), "date-pairing-invalid")
    # A supplied date that is real but not a calendar day is KEPT, with null.
    schema.validate_ledger(
        dated(supplied_date="Spring 2024", normalized_date=None)
    )
    schema.validate_ledger(dated(supplied_date="  c. 2019 ", normalized_date=None))


def test_gv7_s_062_no_v1_record_may_carry_the_reserved_evidence_class():
    """Reserved in the vocabulary, refused in every position that exists."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    reserved = "verified-implementation-evidence"
    assert reserved in schema.ATTRIBUTION_CLASSES
    assert reserved not in schema.CLAIM_ATTRIBUTION_CLASSES
    assert reserved not in schema.RELATIONSHIP_ATTRIBUTION_CLASSES
    for collection in ("claims", "relationships"):
        refuse(
            schema,
            mutate(ledger, collection, "attribution_class", reserved),
            "enum-value-invalid",
        )
    for retired in sup.RETIRED_ATTRIBUTION_CLASSES:
        refuse(
            schema,
            mutate(ledger, "claims", "attribution_class", retired),
            "enum-value-invalid",
        )


def test_gv7_s_058_relationship_endpoints_must_be_of_the_same_kind():
    """Two individually valid endpoints of different kinds is its own fault."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    source_id = ledger["sources"][0]["source_id"]
    claim_id = ledger["claims"][0]["claim_id"]
    payload = json.loads(json.dumps(ledger))
    payload["relationships"][0]["left_ref"] = source_id
    payload["relationships"][0]["right_ref"] = claim_id
    refuse(schema, payload, "relationship-endpoint-kind-mismatch")


def test_gv7_s_059_every_bounded_string_refuses_empty_and_over_length():
    """``LABEL_MAX`` and ``TEXT_MAX`` had no control of any kind."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    label_fields = (
        ("batches", "supplied_by_label"),
        ("sources", "carrier_label"),
        ("relationships", "recorded_by_label"),
        ("unresolved", "recorded_by_label"),
    )
    text_fields = (
        ("batches", "notes"),
        ("claims", "claim_text"),
        ("claims", "evidence_basis"),
        ("unresolved", "statement"),
        ("artifacts", "summary"),
        ("artifacts", "rejection_basis"),
    )
    for bound, fields in ((sup.LABEL_MAX, label_fields), (sup.TEXT_MAX, text_fields)):
        for collection, field in fields:
            refuse(
                schema, mutate(ledger, collection, field, ""), "text-length-invalid"
            )
            refuse(
                schema,
                mutate(ledger, collection, field, "x" * (bound + 1)),
                "text-length-invalid",
            )
            # The boundary itself is accepted: a bound that refuses its own
            # maximum is off by one.
            schema.validate_ledger(mutate(ledger, collection, field, "x" * bound))


def test_gv7_s_060_every_nested_list_bound_is_enforced():
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    over = [f"synthetic entry {n}" for n in range(sup.LIST_MAX + 1)]
    for collection, field in (
        ("sources", "limitations"),
        ("claims", "limitations"),
        ("relationships", "limitations"),
    ):
        refuse(schema, mutate(ledger, collection, field, over), "list-length-invalid")

    ids = [f"GV7-SRC-{n:04d}" for n in range(1, sup.LIST_MAX + 2)]
    for field in ("introduces_sources", "updates_sources"):
        refuse(schema, mutate(ledger, "batches", field, ids), "list-length-invalid")

    # `positions` carries a tighter declared bound of 2..8.
    positions = ledger["unresolved"][0]["positions"]
    refuse(
        schema,
        mutate(ledger, "unresolved", "positions", positions[:1]),
        "list-length-invalid",
    )
    refuse(
        schema,
        mutate(
            ledger,
            "unresolved",
            "positions",
            [f"synthetic position {n}" for n in range(9)],
        ),
        "list-length-invalid",
    )
    refuse(schema, mutate(ledger, "unresolved", "refs", []), "list-length-invalid")


def test_gv7_s_067_every_record_shape_refuses_a_missing_key():
    """Closed shapes were proved by extra keys, never by absent ones."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()
    for collection, keys in sorted(sup.KEYS_BY_COLLECTION.items()):
        if collection == "corrections":
            continue
        for key in sorted(keys):
            payload = json.loads(json.dumps(ledger))
            del payload[collection][0][key]
            refuse(schema, payload, "missing-key")


# --------------------------------------------- M/H: Windows path hazards, frozen


def test_gv7_s_063_hostile_path_shapes_are_refused_lexically(tmp_path):
    """Lexical refusal precedes existence: none of these need to exist."""
    validate = sup.require_validate()
    separator = chr(92)
    cases = (
        ("C:ledger.json", "path-drive-relative"),
        ("C:", "path-drive-relative"),
        (separator * 2 + "?" + separator + "C:" + separator + "ledger.json",
         "path-device-namespace"),
        (separator * 2 + "." + separator + "CON", "path-device-namespace"),
        (str(tmp_path / "CON"), "path-reserved-name"),
        (str(tmp_path / "CON.json"), "path-reserved-name"),
        (str(tmp_path / "nul.txt"), "path-reserved-name"),
        (str(tmp_path / "COM1"), "path-reserved-name"),
        (str(tmp_path / "LPT9.json"), "path-reserved-name"),
        (str(tmp_path / "CON") + ".", "path-reserved-name"),
        (str(tmp_path / "CON") + " ", "path-reserved-name"),
        (str(tmp_path / "aux" / "ledger.json"), "path-reserved-name"),
    )
    for value, token in cases:
        with pytest.raises(validate.LedgerPathError) as excinfo:
            validate.validate_ledger_file(value)
        assert excinfo.value.token == token, (value, excinfo.value.token)

    # Names that merely resemble a device must NOT be refused: a rule that
    # refuses `COMPANY` is a rule nobody can use.
    for name in ("COM0", "LPT0", "LPT10", "CONSOLE", "COMPANY", "nul_file"):
        assert not sup.component_is_reserved(name), name
        probe = tmp_path / f"{name}.json"
        probe.write_text("{}", encoding="utf-8")
        with pytest.raises(sup.require_schema().LedgerError) as excinfo:
            validate.validate_ledger_file(probe)
        assert excinfo.value.token == "missing-key", name


# ------------------------------------------------------------- O: refusal order


def test_gv7_s_064_the_earliest_applicable_refusal_stage_wins():
    """Each payload violates two stages. The earlier token must be the one."""
    schema = sup.require_schema()
    ledger = sup.require_ledger()

    # stage 4 (exact types) before stage 5 (closed shapes): a foreign key type
    # that is ALSO an undeclared key.
    payload = dict(ledger)
    payload[HookedStr(sup.MARKER_KEY)] = "synthetic"
    refuse(schema, payload, "key-not-exact-str")

    # stage 5 before stage 6: an undeclared key alongside an invalid enum.
    payload = mutate(ledger, "claims", "attribution_class", "synthetic-class")
    payload["claims"][0]["an_undeclared_nested_key"] = "synthetic"
    refuse(schema, payload, "undeclared-key")

    # stage 6 before stage 7: an invalid enum alongside a dangling reference.
    payload = mutate(ledger, "claims", "attribution_class", "synthetic-class")
    payload["claims"][0]["source_ref"] = "GV7-SRC-9999"
    refuse(schema, payload, "enum-value-invalid")

    # stage 6 before stage 7: a malformed identifier alongside a bad reference.
    payload = mutate(ledger, "claims", "claim_id", "GV7-CLM-1")
    payload["claims"][0]["source_ref"] = "GV7-SRC-9999"
    refuse(schema, payload, "identifier-malformed")

    # within stage 7: kind is decided from the segment before existence.
    payload = mutate(ledger, "claims", "source_ref", "GV7-BAT-9999")
    refuse(schema, payload, "reference-wrong-kind")


def test_gv7_s_065_input_is_decoded_strictly_and_surrogates_are_refused(tmp_path):
    """``ensure_ascii=True`` is load-bearing, and the decode must be strict."""
    schema = sup.require_schema()
    validate = sup.require_validate()

    # Raw WTF-8. `json.loads` on BYTES decodes with errors="surrogatepass" and
    # would admit this silently; a strict decode refuses it.
    wtf8 = tmp_path / "wtf8.json"
    wtf8.write_bytes(b'{"schema":"' + b"\xed\xa0\x80" + b'"}')
    with pytest.raises(validate.LedgerInputError) as excinfo:
        validate.validate_ledger_file(wtf8)
    assert excinfo.value.token == "ledger-encoding-invalid"
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True

    # A lone surrogate arriving through a legal ASCII escape.
    escaped = tmp_path / "escaped.json"
    escaped.write_text('{"schema":"\\ud800"}', encoding="utf-8")
    with pytest.raises(schema.LedgerError) as excinfo:
        validate.validate_ledger_file(escaped)
    assert excinfo.value.token == "string-not-encodable"

    # Why the flag matters: with ensure_ascii=True the canonical form does NOT
    # crash, and with ensure_ascii=False the identical value raises. The
    # refusal is defence for a flag that must never be relaxed.
    lone = json.loads('"\\ud800"')
    assert sup.has_lone_surrogate(lone)
    assert sup.canonical_bytes({"k": lone}) == b'{"k":"\\ud800"}'
    with pytest.raises(UnicodeEncodeError):
        json.dumps({"k": lone}, ensure_ascii=False).encode("utf-8")
    # A surrogate PAIR is recombined by the parser and is ordinary text.
    assert not sup.has_lone_surrogate(json.loads('"\\ud83d\\ude00"'))


def test_gv7_s_066_the_refusal_classes_and_exit_codes_are_frozen(tmp_path):
    """A content refusal must never be satisfied by a path refusal."""
    schema = sup.require_schema()
    validate = sup.require_validate()
    stage_classes = (
        validate.LedgerPathError,
        validate.LedgerCeilingError,
        validate.LedgerInputError,
    )
    assert len(set(stage_classes)) == 3
    for stage_class in stage_classes:
        assert issubclass(stage_class, schema.LedgerError), stage_class.__name__
        for other in stage_classes:
            if other is not stage_class:
                assert not issubclass(stage_class, other), (
                    stage_class.__name__,
                    other.__name__,
                )
    assert not issubclass(schema.LedgerError, AssertionError)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    assert validate.main([str(sup.LEDGER_PATH)]) == 0
    assert validate.main([str(invalid)]) == 1
    with pytest.raises(SystemExit) as systemexit:
        validate.main([])
    assert systemexit.value.code == 2
    with pytest.raises(SystemExit) as systemexit:
        validate.main([str(invalid), str(invalid)])
    assert systemexit.value.code == 2


def test_gv7_s_068_the_production_refusal_vocabulary_covers_every_named_token():
    """A token the controls demand but the implementation never defines is a
    contract the implementation did not meet."""
    schema = sup.require_schema()
    tokens = set(schema.REFUSAL_TOKENS)
    missing = sorted(set(sup.REQUIRED_REFUSAL_TOKENS) - tokens)
    assert not missing, missing
    assert len(sup.REQUIRED_REFUSAL_TOKENS) == len(set(sup.REQUIRED_REFUSAL_TOKENS))


def test_gv7_s_069_a_refusal_is_byte_identical_under_a_hostile_environment(
    tmp_path, monkeypatch, capsys
):
    """No flag, configuration or environment variable alters refusal content."""
    validate = sup.require_validate()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")

    assert validate.main([str(invalid)]) == 1
    baseline = capsys.readouterr()
    assert baseline.out == "", "a refusal emits nothing on stdout"
    assert baseline.err.count("\n") == 1, baseline.err
    assert baseline.err.strip() in set(sup.require_schema().REFUSAL_TOKENS)

    for name in ("GV7_VERBOSE", "GV7_DEBUG", "PYTHONVERBOSE", "PYTHONDEVMODE"):
        monkeypatch.setenv(name, "1")
    assert validate.main([str(invalid)]) == 1
    hostile = capsys.readouterr()
    assert hostile.out == baseline.out
    assert hostile.err == baseline.err
