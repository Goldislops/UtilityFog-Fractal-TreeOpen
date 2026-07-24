"""Tests for the transition-table structural-refusal package in
``scripts/portable_genome.py`` (``import_genome`` + the public ``info`` CLI).

Scope: this module tests ONLY the narrow structural refusals introduced for the
genome root, ``format``, ``transition_table``, each source-state mapping, and
each source/target state name and neighbor-count key. It deliberately does NOT
assert whole-importer totality — malformed shapes elsewhere in the genome
(config sections, metadata, epigenetic snapshot) are out of scope and are not
exercised here.

Reachability is checked on two separate surfaces:
  * DIRECT — ``import_genome()`` raises ``PortableGenomeError`` with an exact,
    value-free message.
  * PUBLIC — ``python -m scripts.portable_genome info <file>`` routes a
    ``PortableGenomeError`` through argparse's ordinary error path (exit code 2)
    with no successful-output leakage, and does NOT broadly catch JSON syntax
    errors or filesystem errors.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.portable_genome import (
    STATE_NAME_TO_ID,
    PortableGenomeError,
    import_genome,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_VALID_FMT = {"format_id": "utilityfog-portable-genome"}


def _write(tmp_path: Path, obj) -> Path:
    """Write ``obj`` as JSON to a genome file and return its path."""
    p = tmp_path / "genome.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _write_raw(tmp_path: Path, text: str) -> Path:
    """Write raw text (possibly invalid JSON) to a genome file."""
    p = tmp_path / "genome.json"
    p.write_text(text, encoding="utf-8")
    return p


def _info(genome_path: Path) -> subprocess.CompletedProcess:
    """Run the PUBLIC ``info`` CLI on a genome path and capture the result."""
    return subprocess.run(
        [sys.executable, "-m", "scripts.portable_genome", "info", str(genome_path)],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------
# DIRECT refusals — import_genome() raises PortableGenomeError, exact message
# --------------------------------------------------------------------------


def test_error_type_is_valueerror_subclass():
    # Backward compatibility: existing callers that catch ValueError still work.
    assert issubclass(PortableGenomeError, ValueError)


def test_non_object_genome_root(tmp_path):
    for root in ([], "x", 5, True, None):
        p = _write(tmp_path, root)
        with pytest.raises(PortableGenomeError) as exc:
            import_genome(p)
        assert str(exc.value) == "genome must be a JSON object"


def test_non_object_format(tmp_path):
    p = _write(tmp_path, {"format": []})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "format must be a JSON object"


def test_wrong_format_identifier(tmp_path):
    p = _write(tmp_path, {"format": {"format_id": "some-other-format"}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "unknown genome format"


def test_missing_format_identifier_is_unknown_format(tmp_path):
    # Absent format defaults to {} (a dict) and falls through to the format-id
    # check, preserving the original "unknown format" outcome.
    p = _write(tmp_path, {"metadata": {"name": "x"}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "unknown genome format"


def test_non_object_transition_table(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": []})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition_table must be a JSON object"


def test_non_object_source_mapping(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": []}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition mappings must be a JSON object"


def test_unknown_source_state(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"BOGUS": {"0": "VOID"}}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition source state must be a known state name"


def test_malformed_neighbor_count_string(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": {"notanum": "VOID"}}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition neighbor count must be an integer string"


def test_numeric_non_string_target(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": {"0": 5}}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition target state must be a known state name"


def test_unknown_target_state(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": {"0": "BOGUS"}}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert str(exc.value) == "transition target state must be a known state name"


def test_messages_leak_no_supplied_value(tmp_path):
    # The refusal message must not echo the offending value/representation.
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"SUPERSECRETSTATE": {"0": "VOID"}}})
    with pytest.raises(PortableGenomeError) as exc:
        import_genome(p)
    assert "SUPERSECRETSTATE" not in str(exc.value)


# --------------------------------------------------------------------------
# Behavior locks — valid genomes still import exactly as before
# --------------------------------------------------------------------------


def test_minimal_wellformed_genome_imports(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT})
    rule_spec, ca_config, metadata = import_genome(p)
    assert isinstance(rule_spec, dict)
    assert ca_config.transition_table == {}
    assert isinstance(metadata, dict)


def test_all_previously_accepted_integer_spellings(tmp_path):
    # Whitespace, signs and leading zeros are preserved via int()'s own semantics.
    spellings = {"  4  ": "STRUCTURAL", "+1": "COMPUTE", "007": "ENERGY", "0": "VOID"}
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": spellings}})
    _rs, ca_config, _md = import_genome(p)
    void_id = STATE_NAME_TO_ID["VOID"]
    assert ca_config.transition_table[void_id] == {
        4: STATE_NAME_TO_ID["STRUCTURAL"],
        1: STATE_NAME_TO_ID["COMPUTE"],
        7: STATE_NAME_TO_ID["ENERGY"],
        0: STATE_NAME_TO_ID["VOID"],
    }


def test_duplicate_after_conversion_last_wins(tmp_path):
    # "5" and "05" both convert to 5; last mapping wins (unchanged behavior).
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": {"5": "COMPUTE", "05": "ENERGY"}}})
    _rs, ca_config, _md = import_genome(p)
    void_id = STATE_NAME_TO_ID["VOID"]
    assert ca_config.transition_table[void_id] == {5: STATE_NAME_TO_ID["ENERGY"]}


def test_valid_metadata_and_transition_reconstruction(tmp_path):
    genome = {
        "format": _VALID_FMT,
        "metadata": {"name": "demo-organism", "version": "1.2.3"},
        "transition_table": {"VOID": {"3": "STRUCTURAL"}, "ENERGY": {"2": "COMPUTE"}},
    }
    p = _write(tmp_path, genome)
    rule_spec, ca_config, metadata = import_genome(p)
    # Metadata carried through.
    assert metadata["name"] == "demo-organism"
    assert metadata["version"] == "1.2.3"
    # Int-keyed reconstruction is exact.
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {3: STATE_NAME_TO_ID["STRUCTURAL"]}
    assert ca_config.transition_table[STATE_NAME_TO_ID["ENERGY"]] == {2: STATE_NAME_TO_ID["COMPUTE"]}
    # String-keyed transitions preserved on the rule_spec side.
    assert rule_spec["params"]["transitions"]["VOID"]["3"] == "STRUCTURAL"


def test_case_insensitive_state_names_preserved(tmp_path):
    # The importer upper-cases names; lowercase names remain acceptable.
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"void": {"1": "structural"}}})
    _rs, ca_config, _md = import_genome(p)
    assert ca_config.transition_table[STATE_NAME_TO_ID["VOID"]] == {1: STATE_NAME_TO_ID["STRUCTURAL"]}


# --------------------------------------------------------------------------
# PUBLIC CLI reachability — info exit codes and output
# --------------------------------------------------------------------------


def test_public_info_malformed_exits_2_no_output_leak(tmp_path):
    p = _write(tmp_path, {"format": _VALID_FMT, "transition_table": {"VOID": {"0": "BOGUS"}}})
    res = _info(p)
    assert res.returncode == 2
    # Routed through argparse's error path — the generic message is on stderr.
    assert "transition target state must be a known state name" in res.stderr
    # No successful info output leaked to stdout.
    assert "with transitions" not in res.stdout


def test_public_info_valid_genome_success_output_unchanged(tmp_path):
    genome = {
        "format": _VALID_FMT,
        "metadata": {"name": "demo-organism"},
        "transition_table": {"VOID": {"1": "STRUCTURAL"}},
    }
    p = _write(tmp_path, genome)
    res = _info(p)
    assert res.returncode == 0
    assert "with transitions" in res.stdout
    assert "name: demo-organism" in res.stdout


def test_public_info_does_not_broadly_catch_json_syntax_error(tmp_path):
    # Invalid JSON is a syntax error, NOT a PortableGenomeError — it must not be
    # caught and turned into an exit-2; it propagates (non-2 exit).
    p = _write_raw(tmp_path, "{not valid json")
    res = _info(p)
    assert res.returncode != 2
    assert "with transitions" not in res.stdout


def test_public_info_does_not_broadly_catch_missing_file(tmp_path):
    # A filesystem error must not be caught and turned into an exit-2.
    missing = tmp_path / "does_not_exist.json"
    res = _info(missing)
    assert res.returncode != 2
    assert "with transitions" not in res.stdout
