"""Tests for the non-object-genome refusal in ``scripts/dandelion.py``.

Scope: ONLY the verified non-object-genome-root refusal on the genome
compression path (``genome_to_compressed_bytes``) and the public ``info`` / ``qr``
CLI paths. This is deliberately NOT a claim of whole-module or whole-pipeline
totality — other malformed shapes, and the separate empty-GLB-mesh residual,
are out of scope and unexercised here.

Reachability is checked on two separate surfaces:
  * DIRECT — ``genome_to_compressed_bytes()`` raises ``DandelionGenomeError``
    with an exact, value-free message.
  * PUBLIC — ``python -m scripts.dandelion info <file>`` (and ``qr``) route a
    ``DandelionGenomeError`` through argparse's ordinary error path (exit code 2)
    with no successful-output leakage, and do NOT broadly catch JSON syntax
    errors, filesystem errors, or the optional-``qrcode`` ImportError.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from scripts.dandelion import DandelionGenomeError, genome_to_compressed_bytes

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, obj) -> Path:
    p = tmp_path / "genome.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _write_raw(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "genome.json"
    p.write_text(text, encoding="utf-8")
    return p


def _run(*cli_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "scripts.dandelion", *cli_args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )


_NON_OBJECT_ROOTS = [None, [1, 2, 3], "a string", 42, 3.14, True, False]


# --------------------------------------------------------------------------
# DIRECT refusals — genome_to_compressed_bytes() raises DandelionGenomeError
# --------------------------------------------------------------------------


def test_error_type_is_valueerror_subclass():
    assert issubclass(DandelionGenomeError, ValueError)


def test_direct_non_object_roots_refused(tmp_path):
    for root in _NON_OBJECT_ROOTS:
        p = _write(tmp_path, root)
        with pytest.raises(DandelionGenomeError) as exc:
            genome_to_compressed_bytes(str(p))
        assert str(exc.value) == "genome must be a JSON object"


def test_direct_message_leaks_no_supplied_value(tmp_path):
    p = _write(tmp_path, ["SUPERSECRETVALUE"])
    with pytest.raises(DandelionGenomeError) as exc:
        genome_to_compressed_bytes(str(p))
    assert "SUPERSECRETVALUE" not in str(exc.value)


# --------------------------------------------------------------------------
# Behavior locks — valid object genomes are byte-for-byte unchanged
# --------------------------------------------------------------------------


def _expected_compressed(genome_obj: dict) -> bytes:
    """Independent reference for the exact compressed-bytes contract."""
    stripped = {k: v for k, v in genome_obj.items() if k != "epigenetic_snapshot"}
    minified = json.dumps(stripped, separators=(",", ":"), sort_keys=True)
    return zlib.compress(minified.encode("utf-8"), level=9)


def test_valid_object_compressed_bytes_byte_for_byte(tmp_path):
    genome = {"format": {"format_id": "utilityfog-portable-genome"},
              "metadata": {"name": "demo", "version": "1.0"},
              "b": 2, "a": 1}
    p = _write(tmp_path, genome)
    out = genome_to_compressed_bytes(str(p))
    assert out == _expected_compressed(genome)


def test_epigenetic_snapshot_stripped_exactly(tmp_path):
    core = {"format": {"format_id": "utilityfog-portable-genome"}, "metadata": {"name": "x"}}
    with_snapshot = dict(core)
    with_snapshot["epigenetic_snapshot"] = {"lattice_b64": "AAAA" * 1000, "included": True}
    p_with = tmp_path / "with.json"
    p_with.write_text(json.dumps(with_snapshot), encoding="utf-8")
    p_without = tmp_path / "without.json"
    p_without.write_text(json.dumps(core), encoding="utf-8")
    # Stripping is exact: the snapshot is removed, so both compress identically.
    assert genome_to_compressed_bytes(str(p_with)) == genome_to_compressed_bytes(str(p_without))
    # And identical to the reference for the stripped core.
    assert genome_to_compressed_bytes(str(p_with)) == _expected_compressed(core)


# --------------------------------------------------------------------------
# PUBLIC CLI — info exit codes and output
# --------------------------------------------------------------------------


def test_public_info_non_object_exits_2_no_output_leak(tmp_path):
    p = _write(tmp_path, [1, 2, 3])
    res = _run("info", str(p))
    assert res.returncode == 2
    assert "genome must be a JSON object" in res.stderr
    # No successful info output leaked to stdout.
    assert "Minified:" not in res.stdout
    assert "Fits single QR code" not in res.stdout


def test_public_info_valid_genome_success_output_unchanged(tmp_path):
    genome = {"format": {"format_id": "utilityfog-portable-genome"}, "metadata": {"name": "demo"}}
    p = _write(tmp_path, genome)
    res = _run("info", str(p))
    assert res.returncode == 0
    assert f"Genome: {p}" in res.stdout
    assert "Minified:" in res.stdout
    assert "Compressed:" in res.stdout
    assert "Fits single QR code" in res.stdout


def test_public_info_does_not_broadly_catch_json_syntax_error(tmp_path):
    p = _write_raw(tmp_path, "{not valid json")
    res = _run("info", str(p))
    assert res.returncode != 2
    assert "Minified:" not in res.stdout


def test_public_info_does_not_broadly_catch_missing_file(tmp_path):
    missing = tmp_path / "nope.json"
    res = _run("info", str(missing))
    assert res.returncode != 2
    assert "Minified:" not in res.stdout


# --------------------------------------------------------------------------
# PUBLIC CLI — qr routes only DandelionGenomeError through argparse
# --------------------------------------------------------------------------


def test_public_qr_non_object_routes_dandelion_error_exit_2(tmp_path):
    # Requires the optional qrcode dependency: only then does the genome load
    # (and its refusal) run — the qrcode check is deliberately first.
    pytest.importorskip("qrcode")
    p = _write(tmp_path, "not-an-object")
    out_png = tmp_path / "out.png"
    res = _run("qr", str(p), "--output", str(out_png))
    assert res.returncode == 2
    assert "genome must be a JSON object" in res.stderr
    # No QR file written and no success output.
    assert not out_png.exists()
    assert "QR Code generated" not in res.stdout
