"""Tests for QR payload/metadata source coherence in ``scripts/dandelion.py``.

Scope: ONLY that ``generate_qr()`` derives its QR payload and every reported
byte count from **one** captured read of **one** genome-file version, and that
``minified_bytes`` describes the exact canonical, ``epigenetic_snapshot``-
stripped minified UTF-8 bytes that are actually compressed into the QR.

Two defects are pinned:

* **stable-file defect** — the pre-fix ``minified_bytes`` was computed from a
  later reread that never removed ``epigenetic_snapshot``, so a snapshot-bearing
  genome reported a size describing material the QR does not contain;
* **coherence defect** — the payload came from the first read while the two size
  fields came from a second and a third read, so a source replaced between them
  produced metadata describing a different genome version than the payload.

This is deliberately NOT whole-Dandelion totality, filesystem-atomicity,
QR-capacity policy, QR-decoding totality, genome-schema validation, path
containment or concurrency work. The public ``info`` path is out of scope and
keeps its own reads.

Every test uses synthetic ASCII JSON, ``tmp_path`` and a controlled fake
``qrcode`` module — the maintained suite never requires the real optional
``qrcode`` package, and no real genome, NPZ, Medusa artifact, network, model,
engine, observer or calibration run is touched.
"""

from __future__ import annotations

import builtins
import io
import json
import sys
import types
import zlib
from pathlib import Path

import pytest

import scripts.dandelion as dandelion
from scripts.dandelion import (
    DandelionGenomeError,
    decode_qr_payload,
    generate_qr,
    genome_to_compressed_bytes,
)

_SNAPSHOT_MARKER = "SNAPSHOT-ONLY-MARKER"


# ---------------------------------------------------------------------------
# Controlled fake ``qrcode`` stack
# ---------------------------------------------------------------------------


class _QRRecorder:
    """Everything the fake QR stack observed, for behaviour locks."""

    def __init__(self) -> None:
        self.construct: dict | None = None
        self.data: list = []
        self.make_calls: list = []
        self.image_calls: list = []
        self.saves: list = []


@pytest.fixture
def fake_qrcode(monkeypatch):
    """Install a recording fake ``qrcode`` package; return the installer.

    The installer accepts optional failure injections so a QR-library error can
    be raised at a chosen seam without touching the genome-reading contract.
    """

    def install(*, version=7, fail_on_add_data=None, fail_on_make=None):
        rec = _QRRecorder()

        class _Img:
            def __init__(self, fill_color, back_color):
                self.fill_color = fill_color
                self.back_color = back_color

            def save(self, path):
                rec.saves.append(str(path))
                Path(path).write_bytes(b"PNG-fake-bytes")

        class _QRCode:
            def __init__(self, version=None, error_correction=None, box_size=None,
                         border=None):
                rec.construct = {
                    "version": version,
                    "error_correction": error_correction,
                    "box_size": box_size,
                    "border": border,
                }
                self.version = None

            def add_data(self, payload):
                if fail_on_add_data is not None:
                    raise fail_on_add_data
                rec.data.append(payload)

            def make(self, fit=True):
                if fail_on_make is not None:
                    raise fail_on_make
                rec.make_calls.append(fit)
                self.version = version

            def make_image(self, fill_color=None, back_color=None):
                rec.image_calls.append((fill_color, back_color))
                return _Img(fill_color, back_color)

        qrcode_mod = types.ModuleType("qrcode")
        constants_mod = types.ModuleType("qrcode.constants")
        constants_mod.ERROR_CORRECT_L = "EC-L"
        constants_mod.ERROR_CORRECT_M = "EC-M"
        constants_mod.ERROR_CORRECT_Q = "EC-Q"
        constants_mod.ERROR_CORRECT_H = "EC-H"
        qrcode_mod.QRCode = _QRCode
        qrcode_mod.constants = constants_mod

        monkeypatch.setitem(sys.modules, "qrcode", qrcode_mod)
        monkeypatch.setitem(sys.modules, "qrcode.constants", constants_mod)
        return rec

    return install


# ---------------------------------------------------------------------------
# Independent reference helpers (never import the module's own implementation)
# ---------------------------------------------------------------------------


def _canonical_stripped_bytes(genome: dict) -> bytes:
    """The exact material the QR must carry, computed independently."""
    stripped = dict(genome)
    stripped.pop("epigenetic_snapshot", None)
    return json.dumps(stripped, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _canonical_unstripped_bytes(genome: dict) -> bytes:
    """The pre-fix (wrong) material, kept to prove the counts really differ."""
    return json.dumps(genome, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _write_genome(path: Path, genome: dict) -> str:
    """Write ASCII-only JSON and return the text a text-mode read yields."""
    path.write_text(json.dumps(genome, indent=2))
    return path.read_text()


def _snapshot_genome() -> dict:
    return {
        "organism_id": "synthetic-0001",
        "rules": [1, 2, 3, 4],
        "epigenetic_snapshot": {"marker": _SNAPSHOT_MARKER, "blob": "x" * 4000},
    }


# ---------------------------------------------------------------------------
# 1. Snapshot-stripped metadata truth
# ---------------------------------------------------------------------------


def test_metadata_describes_the_stripped_material(fake_qrcode, tmp_path):
    rec = fake_qrcode()
    genome = _snapshot_genome()
    src = tmp_path / "genome.json"
    source_text = _write_genome(src, genome)
    out = tmp_path / "qr.png"

    meta = generate_qr(str(src), output_path=str(out))

    stripped = _canonical_stripped_bytes(genome)
    unstripped = _canonical_unstripped_bytes(genome)

    # original_json_bytes keeps its existing meaning: the complete captured text.
    assert meta["original_json_bytes"] == len(source_text.encode("utf-8"))
    # minified_bytes describes exactly what is compressed into the QR.
    assert meta["minified_bytes"] == len(stripped)
    assert meta["compressed_bytes"] == len(zlib.compress(stripped, level=9))
    # The pre-fix count described different material — prove they really differ.
    assert len(stripped) != len(unstripped)
    assert meta["minified_bytes"] != len(unstripped)

    # The payload decodes to the stripped genome, with no snapshot leakage.
    payload = rec.data[0]
    assert payload.startswith("UFG1:")
    decoded = decode_qr_payload(payload)
    expected = dict(genome)
    expected.pop("epigenetic_snapshot")
    assert decoded == expected
    assert "epigenetic_snapshot" not in decoded
    assert _SNAPSHOT_MARKER not in payload


# ---------------------------------------------------------------------------
# 2. One-read guarantee
# ---------------------------------------------------------------------------


def test_successful_generate_qr_reads_genome_exactly_once(
    fake_qrcode, tmp_path, monkeypatch
):
    fake_qrcode()
    src = tmp_path / "genome.json"
    _write_genome(src, _snapshot_genome())
    out = tmp_path / "qr.png"

    real_open = builtins.open
    genome_opens: list = []

    def counting_open(file, mode="r", *args, **kwargs):
        # Count reads of the GENOME path only; writes to the QR output are not
        # genome reads and must not be counted.
        if str(file) == str(src):
            genome_opens.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    generate_qr(str(src), output_path=str(out))
    monkeypatch.undo()

    assert genome_opens == ["r"], f"expected exactly one genome read, got {genome_opens}"


# ---------------------------------------------------------------------------
# 3. Replacement / coherence regression
# ---------------------------------------------------------------------------


def test_replacement_between_reads_cannot_mix_sources(
    fake_qrcode, tmp_path, monkeypatch
):
    """Version A is available first; any second read would expose version B.

    Against the pre-fix implementation the payload came from A while the size
    fields came from B — the exact incoherence this pins shut.
    """
    rec = fake_qrcode()
    version_a = {"organism_id": "VERSION-A", "epigenetic_snapshot": {"blob": "a" * 64}}
    version_b = {"organism_id": "VERSION-B-REPLACEMENT", "padding": "b" * 900}
    text_a = json.dumps(version_a, indent=2)
    text_b = json.dumps(version_b, indent=2)

    src = tmp_path / "genome.json"
    src.write_text(text_a)
    out = tmp_path / "qr.png"

    real_open = builtins.open
    reads: list = []

    def swapping_open(file, mode="r", *args, **kwargs):
        if str(file) == str(src) and "r" in mode and "b" not in mode:
            reads.append(len(reads) + 1)
            return io.StringIO(text_a if len(reads) == 1 else text_b)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", swapping_open)
    meta = generate_qr(str(src), output_path=str(out))
    monkeypatch.undo()

    # Only version A was ever read.
    assert reads == [1], f"expected exactly one read, got {len(reads)}"

    stripped_a = _canonical_stripped_bytes(version_a)
    # Every returned byte-count field describes A.
    assert meta["original_json_bytes"] == len(text_a.encode("utf-8"))
    assert meta["minified_bytes"] == len(stripped_a)
    assert meta["compressed_bytes"] == len(zlib.compress(stripped_a, level=9))
    # No value from B entered metadata or payload.
    assert meta["minified_bytes"] != len(_canonical_stripped_bytes(version_b))
    assert meta["original_json_bytes"] != len(text_b.encode("utf-8"))
    decoded = decode_qr_payload(rec.data[0])
    assert decoded == {"organism_id": "VERSION-A"}
    assert "VERSION-B-REPLACEMENT" not in rec.data[0]


# ---------------------------------------------------------------------------
# 4. Direct compression byte lock
# ---------------------------------------------------------------------------


def test_genome_to_compressed_bytes_is_byte_identical_to_reference(tmp_path):
    genome = _snapshot_genome()
    src = tmp_path / "genome.json"
    _write_genome(src, genome)

    produced = genome_to_compressed_bytes(str(src))
    reference = zlib.compress(_canonical_stripped_bytes(genome), level=9)

    assert produced == reference
    # And it round-trips to the stripped genome.
    expected = dict(genome)
    expected.pop("epigenetic_snapshot")
    assert json.loads(zlib.decompress(produced).decode("utf-8")) == expected


# ---------------------------------------------------------------------------
# 5. Valid QR behaviour lock
# ---------------------------------------------------------------------------


def test_valid_qr_path_behaviour_is_preserved(fake_qrcode, tmp_path):
    rec = fake_qrcode(version=11)
    genome = {"organism_id": "synthetic-lock", "rules": [7]}
    src = tmp_path / "genome.json"
    _write_genome(src, genome)
    out = tmp_path / "nested-name.png"

    meta = generate_qr(
        str(src), output_path=str(out), box_size=9, border=2, error_correction="q"
    )

    # Error-correction lookup uses .upper() against the constants map.
    assert rec.construct["error_correction"] == "EC-Q"
    assert meta["qr_error_correction"] == "Q"
    # Construction arguments are passed through unchanged.
    assert rec.construct["version"] is None
    assert rec.construct["box_size"] == 9
    assert rec.construct["border"] == 2
    # Payload, fit and image colours.
    expected_payload = "UFG1:" + dandelion.compressed_to_b85(
        zlib.compress(_canonical_stripped_bytes(genome), level=9)
    )
    assert rec.data == [expected_payload]
    assert rec.make_calls == [True]
    assert rec.image_calls == [("black", "white")]
    # Exactly one save, to the requested output path.
    assert rec.saves == [str(out)]
    assert out.exists()
    # Version metadata and single-QR verdict.
    assert meta["output_path"] == str(out)
    assert meta["qr_version"] == 11
    assert meta["fits_single_qr"] is True
    assert meta["b85_encoded_chars"] == len(expected_payload) - len("UFG1:")
    assert meta["qr_payload_chars"] == len(expected_payload)


def test_unknown_error_correction_falls_back_to_l(fake_qrcode, tmp_path):
    rec = fake_qrcode()
    src = tmp_path / "genome.json"
    _write_genome(src, {"organism_id": "fallback"})

    meta = generate_qr(
        str(src), output_path=str(tmp_path / "qr.png"), error_correction="z"
    )

    assert rec.construct["error_correction"] == "EC-L"
    assert meta["qr_error_correction"] == "Z"


# ---------------------------------------------------------------------------
# 6. Optional-dependency precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("genome_state", ["missing", "malformed"])
def test_missing_qrcode_dependency_precedes_any_genome_read(
    tmp_path, monkeypatch, genome_state
):
    # ``None`` in sys.modules makes the import raise ImportError whether or not
    # the real optional package is installed on this seat.
    monkeypatch.setitem(sys.modules, "qrcode", None)
    monkeypatch.setitem(sys.modules, "qrcode.constants", None)

    src = tmp_path / "genome.json"
    if genome_state == "malformed":
        src.write_text("{not valid json")

    real_open = builtins.open
    genome_opens: list = []

    def counting_open(file, mode="r", *args, **kwargs):
        if str(file) == str(src):
            genome_opens.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    with pytest.raises(ImportError) as excinfo:
        generate_qr(str(src), output_path=str(tmp_path / "qr.png"))
    monkeypatch.undo()

    assert not isinstance(excinfo.value, ValueError)
    assert "qrcode library required" in str(excinfo.value)
    assert "pip install qrcode[pil]" in str(excinfo.value)
    # The dependency failure happened before the genome was touched at all.
    assert genome_opens == []


# ---------------------------------------------------------------------------
# 7. Typed non-object refusal, direct and through the public CLI
# ---------------------------------------------------------------------------


def test_non_object_genome_root_refused_directly(fake_qrcode, tmp_path):
    fake_qrcode()
    src = tmp_path / "genome.json"
    src.write_text(json.dumps([1, 2, 3]))
    out = tmp_path / "qr.png"

    with pytest.raises(DandelionGenomeError) as excinfo:
        generate_qr(str(src), output_path=str(out))

    assert str(excinfo.value) == "genome must be a JSON object"
    assert not out.exists()


def test_public_qr_cli_routes_only_the_typed_refusal_to_exit_2(
    fake_qrcode, tmp_path, capsys
):
    fake_qrcode()
    src = tmp_path / "genome.json"
    src.write_text(json.dumps("a bare string root"))
    out = tmp_path / "qr.png"

    with pytest.raises(SystemExit) as excinfo:
        dandelion.main(["qr", str(src), "--output", str(out)])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "QR Code generated" not in captured.out
    assert not out.exists()


# ---------------------------------------------------------------------------
# 8. No broad catch
# ---------------------------------------------------------------------------


def test_invalid_json_is_not_caught_by_the_typed_boundary(fake_qrcode, tmp_path):
    fake_qrcode()
    src = tmp_path / "genome.json"
    src.write_text("{ this is not json")

    with pytest.raises(json.JSONDecodeError) as excinfo:
        generate_qr(str(src), output_path=str(tmp_path / "qr.png"))

    assert not isinstance(excinfo.value, DandelionGenomeError)


def test_qr_library_failure_is_not_caught(fake_qrcode, tmp_path):
    sentinel = RuntimeError("synthetic QR-library failure")
    fake_qrcode(fail_on_make=sentinel)
    src = tmp_path / "genome.json"
    _write_genome(src, {"organism_id": "sentinel"})

    with pytest.raises(RuntimeError) as excinfo:
        generate_qr(str(src), output_path=str(tmp_path / "qr.png"))

    assert excinfo.value is sentinel


def test_cli_does_not_translate_a_plain_valueerror_from_the_qr_library(
    fake_qrcode, tmp_path
):
    """Only ``DandelionGenomeError`` routes to exit 2 — not its ``ValueError`` base.

    A plain ``ValueError`` raised inside the QR library must propagate, proving
    the CLI catch was not broadened to the base class.
    """
    sentinel = ValueError("synthetic QR-library ValueError")
    fake_qrcode(fail_on_add_data=sentinel)
    src = tmp_path / "genome.json"
    _write_genome(src, {"organism_id": "sentinel"})

    with pytest.raises(ValueError) as excinfo:
        dandelion.main(["qr", str(src), "--output", str(tmp_path / "qr.png")])

    assert excinfo.value is sentinel
    assert not isinstance(excinfo.value, DandelionGenomeError)
