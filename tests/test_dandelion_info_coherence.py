"""Tests for source coherence of the public Dandelion ``info`` command.

Scope: ONLY that every value printed by one successful ``info`` invocation
derives from **one** authoritative captured read of **one** genome-file version.

Before the correction, ``info`` read the genome twice: the first read (through
``genome_to_compressed_bytes``) supplied the compressed / Base85 / QR-payload /
fit figures, while a second read supplied the original and minified byte counts.
With a stable file the arithmetic was already correct — this is **not** a
stable-file arithmetic defect. The defect is that a replacement between those
two reads produces a single report whose values describe different genome
versions.

This is deliberately NOT whole-Dandelion totality, atomic file snapshotting,
general race prevention, locking, retry logic or filesystem identity
verification. The full QR metadata contract lives in
``tests/test_dandelion_qr_metadata.py`` and is not duplicated here; this file
carries only a smoke guard that the ``qr`` path is unchanged.

Every test uses synthetic ASCII JSON, ``tmp_path`` and in-process
``dandelion.main()`` invocation. No real genome, QR library, NPZ, Medusa
artifact, network, model, engine, observer or calibration run is touched.
"""

from __future__ import annotations

import base64
import builtins
import contextlib
import io
import json
import sys
import types
import zlib
from pathlib import Path

import pytest

import scripts.dandelion as dandelion
from scripts.dandelion import DandelionGenomeError


# ---------------------------------------------------------------------------
# Independent reference helpers (never reuse the module's own implementation)
# ---------------------------------------------------------------------------


def _stripped_minified(genome: dict) -> bytes:
    stripped = dict(genome)
    stripped.pop("epigenetic_snapshot", None)
    return json.dumps(stripped, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _expected_numbers(source_text: str, genome: dict) -> dict:
    mini = _stripped_minified(genome)
    comp = zlib.compress(mini, level=9)
    b85 = base64.b85encode(comp).decode("ascii")
    return {
        "original": len(source_text.encode("utf-8")),
        "minified": len(mini),
        "compressed": len(comp),
        "base85": len(b85),
        "payload": len(b85) + 5,
    }


def _snapshot_genome() -> dict:
    return {
        "organism_id": "synthetic-info-1",
        "rules": [1, 2, 3, 4],
        "epigenetic_snapshot": {"blob": "x" * 3000},
    }


def _write_genome(path: Path, genome: dict) -> str:
    path.write_text(json.dumps(genome, indent=2))
    return path.read_text()


def _run_info(path: Path) -> str:
    """Invoke the public ``info`` command in-process and return stdout."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dandelion.main(["info", str(path)])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Successful one-read guarantee
# ---------------------------------------------------------------------------


def test_successful_info_reads_genome_exactly_once(tmp_path, monkeypatch):
    src = tmp_path / "genome.json"
    _write_genome(src, _snapshot_genome())

    real_open = builtins.open
    genome_opens: list = []

    def counting_open(file, mode="r", *args, **kwargs):
        if str(file) == str(src):
            genome_opens.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    _run_info(src)
    monkeypatch.undo()

    assert genome_opens == ["r"], f"expected exactly one genome read, got {genome_opens}"


# ---------------------------------------------------------------------------
# 2. Controlled replacement coherence
# ---------------------------------------------------------------------------


def test_controlled_replacement_cannot_mix_the_report(tmp_path, monkeypatch):
    """Version A is available first; any later read would expose version B.

    Pre-fix, the compressed/Base85 figures came from A while the original and
    minified counts came from B — one report describing two genome versions.
    """
    version_a = {"organism_id": "VERSION-A", "epigenetic_snapshot": {"blob": "a" * 40}}
    version_b = {"organism_id": "VERSION-B-REPLACEMENT", "pad": "b" * 700}
    text_a = json.dumps(version_a, indent=2)
    text_b = json.dumps(version_b, indent=2)

    src = tmp_path / "genome.json"
    src.write_text(text_a)

    real_open = builtins.open
    reads: list = []

    def swapping_open(file, mode="r", *args, **kwargs):
        if str(file) == str(src) and "r" in mode and "b" not in mode:
            reads.append(len(reads) + 1)
            return io.StringIO(text_a if len(reads) == 1 else text_b)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", swapping_open)
    out = _run_info(src)
    monkeypatch.undo()

    assert reads == [1], f"expected exactly one read, got {len(reads)}"

    want_a = _expected_numbers(text_a, version_a)
    assert f"Original:   {want_a['original']:,} bytes" in out
    assert f"Minified:   {want_a['minified']:,} bytes" in out
    assert f"Compressed: {want_a['compressed']:,} bytes" in out
    assert f"Base85:     {want_a['base85']:,} chars" in out
    assert f"QR payload: {want_a['payload']:,} chars" in out
    assert "Fits single QR code:    YES" in out

    # No measurement derived from version B may appear anywhere in the report.
    want_b = _expected_numbers(text_b, version_b)
    for label, value in want_b.items():
        assert value != want_a[label], "fixture must make A and B distinguishable"
        assert f"{value:,}" not in out, f"version-B {label} ({value:,}) leaked into the report"


# ---------------------------------------------------------------------------
# 3. Stable-file independent output lock (passes before and after)
# ---------------------------------------------------------------------------


def test_stable_file_numbers_are_independently_correct(tmp_path):
    genome = _snapshot_genome()
    src = tmp_path / "genome.json"
    source_text = _write_genome(src, genome)

    out = _run_info(src)
    want = _expected_numbers(source_text, genome)

    assert f"Genome: {src}" in out
    assert f"Original:   {want['original']:,} bytes" in out
    assert f"Minified:   {want['minified']:,} bytes" in out
    assert f"Compressed: {want['compressed']:,} bytes" in out
    assert f"Base85:     {want['base85']:,} chars" in out
    assert f"QR payload: {want['payload']:,} chars (with UFG1: header)" in out
    assert "QR V40 capacity (EC-L): 2,953 bytes binary / 4,296 alphanumeric" in out
    assert "Fits single QR code:    YES" in out
    assert "QR codes needed:" not in out
    # The blank line before the capacity block is part of the format.
    assert "\n\n  QR V40 capacity" in out


# ---------------------------------------------------------------------------
# 4. Exact capacity boundary and code-count formula
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "b85_len, expect_fit, expect_codes",
    [
        pytest.param(4291, True, None, id="payload-4296-fits"),
        pytest.param(4292, False, 2, id="payload-4297-does-not-fit"),
    ],
)
def test_capacity_boundary_and_code_count(
    tmp_path, monkeypatch, b85_len, expect_fit, expect_codes
):
    """Drive the boundary through a controlled Base85 seam.

    Only the Base85 encoding is controlled; the capacity statement, the 4,296
    boundary and the ceiling-division formula are the module's own.
    """
    src = tmp_path / "genome.json"
    _write_genome(src, {"organism_id": "boundary"})

    monkeypatch.setattr(dandelion, "compressed_to_b85", lambda _c: "A" * b85_len)
    out = _run_info(src)

    payload = b85_len + 5
    assert f"Base85:     {b85_len:,} chars" in out
    assert f"QR payload: {payload:,} chars (with UFG1: header)" in out
    assert f"Fits single QR code:    {'YES' if expect_fit else 'NO'}" in out
    if expect_codes is None:
        assert "QR codes needed:" not in out
    else:
        assert expect_codes == (payload + 4295) // 4296
        assert f"QR codes needed:        {expect_codes}" in out


# ---------------------------------------------------------------------------
# 5. Typed non-object refusal through the public CLI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "root", [json.dumps([1, 2, 3]), json.dumps("a bare string"), json.dumps(7)]
)
def test_non_object_root_refused_with_exit_2(tmp_path, capsys, root):
    src = tmp_path / "genome.json"
    src.write_text(root)

    with pytest.raises(SystemExit) as excinfo:
        dandelion.main(["info", str(src)])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "genome must be a JSON object" in captured.err
    for leaked in ("Genome:", "Minified:", "Compressed:", "Fits single QR code:"):
        assert leaked not in captured.out


def test_non_object_root_raises_the_exact_typed_error_directly(tmp_path):
    src = tmp_path / "genome.json"
    src.write_text(json.dumps([1, 2, 3]))

    with pytest.raises(DandelionGenomeError) as excinfo:
        dandelion._capture_genome(str(src))

    assert str(excinfo.value) == "genome must be a JSON object"


# ---------------------------------------------------------------------------
# 6. No broad catch — only DandelionGenomeError is translated
# ---------------------------------------------------------------------------


def test_invalid_json_propagates_and_is_not_exit_2(tmp_path):
    src = tmp_path / "genome.json"
    src.write_text("{ this is not json")

    with pytest.raises(json.JSONDecodeError) as excinfo:
        dandelion.main(["info", str(src)])

    assert not isinstance(excinfo.value, DandelionGenomeError)


def test_missing_file_propagates_and_is_not_exit_2(tmp_path):
    missing = tmp_path / "absent.json"

    with pytest.raises(OSError) as excinfo:
        dandelion.main(["info", str(missing)])

    assert not isinstance(excinfo.value, SystemExit)


def test_sentinel_valueerror_from_the_capture_seam_propagates(tmp_path, monkeypatch):
    src = tmp_path / "genome.json"
    _write_genome(src, {"organism_id": "sentinel"})
    sentinel = ValueError("synthetic capture failure")

    def _boom(_path):
        raise sentinel

    monkeypatch.setattr(dandelion, "_capture_genome", _boom)
    with pytest.raises(ValueError) as excinfo:
        dandelion.main(["info", str(src)])

    assert excinfo.value is sentinel
    assert not isinstance(excinfo.value, DandelionGenomeError)


def test_sentinel_runtimeerror_from_the_base85_seam_propagates(tmp_path, monkeypatch):
    src = tmp_path / "genome.json"
    _write_genome(src, {"organism_id": "sentinel"})
    sentinel = RuntimeError("synthetic base85 failure")

    def _boom(_compressed):
        raise sentinel

    monkeypatch.setattr(dandelion, "compressed_to_b85", _boom)
    with pytest.raises(RuntimeError) as excinfo:
        dandelion.main(["info", str(src)])

    assert excinfo.value is sentinel


# ---------------------------------------------------------------------------
# 7. QR-path non-regression smoke guard
# ---------------------------------------------------------------------------


def test_qr_path_smoke_guard_unchanged(tmp_path, monkeypatch):
    """Smoke check only — the full QR contract lives in the #423 suite."""
    qrcode_mod = types.ModuleType("qrcode")
    constants_mod = types.ModuleType("qrcode.constants")
    for name in ("ERROR_CORRECT_L", "ERROR_CORRECT_M", "ERROR_CORRECT_Q", "ERROR_CORRECT_H"):
        setattr(constants_mod, name, name)
    captured: dict = {}

    class _Img:
        def save(self, path):
            Path(path).write_bytes(b"PNG-fake")

    class _QRCode:
        def __init__(self, **kwargs):
            self.version = 5

        def add_data(self, payload):
            captured["payload"] = payload

        def make(self, fit=True):
            pass

        def make_image(self, fill_color=None, back_color=None):
            return _Img()

    qrcode_mod.QRCode = _QRCode
    qrcode_mod.constants = constants_mod
    monkeypatch.setitem(sys.modules, "qrcode", qrcode_mod)
    monkeypatch.setitem(sys.modules, "qrcode.constants", constants_mod)

    genome = _snapshot_genome()
    src = tmp_path / "genome.json"
    source_text = _write_genome(src, genome)

    meta = dandelion.generate_qr(str(src), output_path=str(tmp_path / "qr.png"))
    want = _expected_numbers(source_text, genome)

    assert meta["original_json_bytes"] == want["original"]
    assert meta["minified_bytes"] == want["minified"]
    assert meta["compressed_bytes"] == want["compressed"]
    assert captured["payload"].startswith("UFG1:")
