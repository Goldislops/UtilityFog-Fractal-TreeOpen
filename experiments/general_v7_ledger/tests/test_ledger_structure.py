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


def test_gv7_s_019_input_is_file_only_and_path_confined(tmp_path):
    validate = sup.require_validate()
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path)
    assert excinfo.value.token == "path-not-file"
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(tmp_path / "absent.json")
    assert excinfo.value.token == "path-missing"


def test_gv7_s_020_a_reparse_point_input_is_refused(tmp_path):
    validate = sup.require_validate()
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "linked.json"
    made = False
    try:
        os.symlink(real, link)
        made = True
    except (OSError, NotImplementedError, AttributeError):
        completed = subprocess.run(
            ["cmd", "/c", "mklink", str(link), str(real)],
            capture_output=True,
            text=True,
        )
        made = completed.returncode == 0 and link.exists()
    assert made, (
        "no deterministic link mechanism is available; the path-security "
        "control cannot be constructed and must not be skipped"
    )
    with pytest.raises(validate.LedgerPathError) as excinfo:
        validate.validate_ledger_file(link)
    assert excinfo.value.token == "path-symlink-refused"


def test_gv7_s_021_no_environment_variable_or_cwd_locates_the_input(
    tmp_path, monkeypatch
):
    validate = sup.require_validate()
    monkeypatch.chdir(tmp_path)
    for name in ("LEDGER", "LEDGER_PATH", "GV7_LEDGER", "PWD"):
        monkeypatch.setenv(name, str(tmp_path))
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
