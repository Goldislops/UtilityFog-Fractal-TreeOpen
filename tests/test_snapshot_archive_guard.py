"""Tests for `scripts/snapshot_archive_guard.admit_snapshot()`.

The guard decides whether a file in the watched data directory is allowed to
reach `np.load` at all. Everything it refuses, it must refuse from bounded
reads of the ZIP central directory and the members' NPY headers -- never by
extracting anything, never by allocating in proportion to what the archive
claims, and never by disclosing what it saw.

Fixture policy, stated once. The hostile archives here are built with the
standard library rather than NumPy, for two reasons: NumPy cannot write a
duplicate member, a corrupt magic, an encrypted entry or a lying shape, and
the stdlib half of this module then runs in an environment with no NumPy at
all. Nothing is hostile in SIZE -- the oversized cases lie in their headers
while occupying a few kilobytes on disk, and the resource ceilings are driven
by tiny injected policies. No test allocates, decompresses or writes a
production-sized archive.

Scope is structural and resource admission for the `v070_gen` snapshot schema.
Not authentication, not atomic writing, not semantic state validation, not
numeric-value validation, not arbitrary NPZ compatibility.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import os
import re
import struct
import sys
import time
import warnings
import zipfile
import zlib
from pathlib import Path
from unittest import mock

import pytest

# The opt-in benchmark at the end of this file is documented as
# `python tests/test_snapshot_archive_guard.py --case all`, which leaves the
# repository root off `sys.path` and would break the guard import below.
# Appended, not prepended, for the same reason the three consumers append:
# this must not be able to shadow a standard library module with a repository
# file of the same name. Under pytest the root is already present and this is
# a no-op.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.append(_PROJECT_ROOT)

from scripts import snapshot_archive_guard as guard  # noqa: E402

try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover - exercised only in a bare environment
    np = None
    _HAVE_NUMPY = False

requires_numpy = pytest.mark.skipif(not _HAVE_NUMPY, reason="numpy not installed")


# ---------------------------------------------------------------------------
# Standard-library NPY / NPZ construction
# ---------------------------------------------------------------------------

_NPY_MAGIC = b"\x93NUMPY"


def npy_bytes(descr, shape, *, fortran=False, payload=None, header=None,
              version=(1, 0)):
    """One `.npy` member as raw bytes, every field independently forgeable."""
    if header is None:
        if not shape:
            shape_text = "()"
        elif len(shape) == 1:
            shape_text = "(%d,)" % shape[0]
        else:
            shape_text = "(" + ", ".join(str(dim) for dim in shape) + ")"
        header = "{'descr': '%s', 'fortran_order': %s, 'shape': %s, }" % (
            descr, fortran, shape_text)
    # v3.0 headers are UTF-8 by specification; v1.0 and v2.0 are latin-1.
    # Encoding v3 as latin-1 would make a non-ASCII descriptor unbuildable, and
    # a non-ASCII descriptor is exactly what the digit-class tests need.
    body = header.encode("utf-8" if version == (3, 0) else "latin1")
    prelude = 10 if version == (1, 0) else 12
    body += b" " * ((-(prelude + len(body) + 1)) % 64) + b"\n"
    out = bytearray(_NPY_MAGIC) + bytes(version)
    out += (struct.pack("<H", len(body)) if version == (1, 0)
            else struct.pack("<I", len(body)))
    out += body
    if payload is None:
        digits = descr[2:] if descr[0] in "<>|=" else descr[1:]
        itemsize = int(digits) if digits else 0
        count = 1
        for dim in shape:
            count *= dim
        payload = b"\x00" * (count * itemsize)
    return bytes(out) + payload


def schema_members(edge=16, channels=8):
    """The five members a `v070_gen` snapshot carries, at an admissible edge.

    Real payloads, so keep `edge` small: at 256 the memory grid alone is
    512 MiB, which no test may allocate. Use :func:`declared_members` for
    anything that only needs an archive to CLAIM a large shape.
    """
    return {
        "lattice.npy": npy_bytes("|u1", (edge, edge, edge)),
        "memory_grid.npy": npy_bytes("<f4", (channels, edge, edge, edge)),
        "generation.npy": npy_bytes("<i8", ()),
        "ca_step.npy": npy_bytes("<i8", ()),
        "best_fitness.npy": npy_bytes("<f8", ()),
    }


def declared_members(edge, channels=8):
    """The same five members, DECLARING `edge` but carrying no payload.

    The guard checks geometry (pass two) before size arithmetic (pass three),
    so an archive that lies about its shape is refused on the geometry rule
    without ever needing the bytes to exist. That is what lets a 512-edge case
    cost a few kilobytes instead of four gigabytes.
    """
    members = schema_members(16, channels)
    members["lattice.npy"] = npy_bytes(
        "|u1", (edge, edge, edge), payload=b"",
        header="{'descr': '|u1', 'fortran_order': False, 'shape': "
               "(%d, %d, %d), }" % (edge, edge, edge))
    members["memory_grid.npy"] = npy_bytes(
        "<f4", (channels, edge, edge, edge), payload=b"",
        header="{'descr': '<f4', 'fortran_order': False, 'shape': "
               "(%d, %d, %d, %d), }" % (channels, edge, edge, edge))
    return members


def write_npz(path, members, *, compression=zipfile.ZIP_DEFLATED, duplicate=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a duplicate name is deliberate here
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, blob in members.items():
                archive.writestr(name, blob)
            if duplicate is not None:
                archive.writestr(duplicate, members[duplicate])
    return Path(path)


def header_length(blob):
    """The NPY header size a member declares, read the way the guard reads it."""
    if blob[8:10] and blob[6:8] == b"\x01\x00":
        return 10 + struct.unpack("<H", blob[8:10])[0]
    return 12 + struct.unpack("<I", blob[8:12])[0]


def set_encrypted_flag(path):
    """Set the ZIP general-purpose encryption bit on the last directory entry.

    `zipfile` will not write an encrypted entry, and `ZipInfo.flag_bits` is
    read from the central directory, so the bit is set there directly.
    """
    data = bytearray(Path(path).read_bytes())
    index = data.rfind(b"PK\x01\x02")
    assert index > 0, "no central-directory header found in the fixture"
    struct.pack_into("<H", data, index + 8, 0x0001)
    Path(path).write_bytes(bytes(data))
    return Path(path)


@pytest.fixture
def root(tmp_path):
    """The confined data directory every admissible snapshot must live in."""
    directory = tmp_path / "data"
    directory.mkdir()
    return directory


def admit(path, data_dir, policy=None, *, read=True):
    """Run the real guard; return None if admitted, else the reason code."""
    policy = policy or guard.PRODUCTION_POLICY
    try:
        with guard.admit_snapshot(path, data_dir=data_dir, policy=policy) as handle:
            if read:
                assert handle.tell() == 0, "the descriptor was not rewound"
                assert handle.read(4) == b"PK\x03\x04"
        return None
    except guard.SnapshotArchiveRejected as exc:
        # The message IS the code: asserted on every single refusal in this
        # module, not once in a dedicated test.
        assert str(exc) == exc.reason
        return exc.reason


# ---------------------------------------------------------------------------
# Valid archives are admitted
# ---------------------------------------------------------------------------

def test_a_producer_shaped_archive_is_admitted(root):
    path = write_npz(root / "v070_gen000064.npz", schema_members(64))
    assert admit(path, root) is None


def test_an_uncompressed_archive_is_admitted(root):
    path = write_npz(root / "v070_stored.npz", schema_members(32),
                     compression=zipfile.ZIP_STORED)
    assert admit(path, root) is None


@pytest.mark.parametrize("edge", [16, 32, 48, 64])
def test_admissible_edges_are_admitted(root, edge):
    """Real payloads, so this stops at 64 -- the producer's own edge. The
    policy's upper end is exercised structurally instead: a real 256-edge
    archive is 528 MiB, and no test may allocate one."""
    path = write_npz(root / ("v070_e%d.npz" % edge), schema_members(edge))
    assert admit(path, root) is None


@pytest.mark.parametrize("channels", [7, 8, 16, 64])
def test_memory_grid_depths_the_consumers_can_read_are_admitted(root, channels):
    """The channel rule is a FLOOR at what the consumers index, not a pin.

    Anything at or above seven is admitted and bounded above only by the
    memory-grid payload ceiling. The documented 3- and 5-channel legacy forms
    are below the floor and are refused — no consumer migrates them, so they
    could only ever have raised `IndexError` downstream.
    """
    path = write_npz(root / ("v070_c%d.npz" % channels),
                     schema_members(16, channels))
    assert admit(path, root) is None


@pytest.mark.parametrize("descr", ["|u1", "<u2", ">u4"])
def test_the_lattice_dtype_is_a_family_not_an_exact_width(root, descr):
    members = schema_members(16)
    members["lattice.npy"] = npy_bytes(descr, (16, 16, 16))
    path = write_npz(root / "v070_family.npz", members)
    assert admit(path, root) is None


def test_a_version_2_npy_header_is_admitted(root):
    members = schema_members(16)
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 16), version=(2, 0))
    path = write_npz(root / "v070_v2.npz", members)
    assert admit(path, root) is None


# ---------------------------------------------------------------------------
# Every refusal, one case per reason code
# ---------------------------------------------------------------------------

def _case_path_not_confined(root, tmp_path):
    outside = tmp_path / "v070_outside.npz"
    write_npz(outside, schema_members())
    return outside, None


def _case_path_not_regular_file(root, tmp_path):
    directory = root / "v070_dir.npz"
    directory.mkdir()
    return directory, None


def _case_path_suffix_not_npz(root, tmp_path):
    path = root / "v070_wrong.npy"
    write_npz(path, schema_members())
    return path, None


def _case_archive_too_large(root, tmp_path):
    path = write_npz(root / "v070_big.npz", schema_members())
    return path, dataclasses.replace(guard.PRODUCTION_POLICY,
                                     max_physical_bytes=64)


def _case_archive_truncated(root, tmp_path):
    path = root / "v070_stub.npz"
    path.write_bytes(b"PK\x03\x04")
    return path, None


def _case_not_zip_archive(root, tmp_path):
    path = root / "v070_renamed.npz"
    path.write_bytes(npy_bytes("|u1", (16, 16, 16)))
    return path, None


def _set_extract_version(path, version):
    """Set 'version needed to extract' on every central-directory entry."""
    data = bytearray(Path(path).read_bytes())
    offset = 0
    patched = 0
    while True:
        index = data.find(b"PK\x01\x02", offset)
        if index < 0:
            break
        struct.pack_into("<H", data, index + 6, version)
        patched += 1
        offset = index + 4
    assert patched, "no central-directory header found in the fixture"
    Path(path).write_bytes(bytes(data))
    return Path(path)


def _case_unsupported_extract_version(root, tmp_path):
    """One byte per entry, and the archive is otherwise schema-perfect.

    `ZipFile()`'s constructor refuses an entry whose "version needed to
    extract" exceeds MAX_EXTRACT_VERSION (63) with `NotImplementedError` —
    which subclasses `RuntimeError`, so the BadZipFile/OSError/ValueError
    clause did not catch it and the exception left `admit_snapshot` untyped.
    """
    path = write_npz(root / "v070_extver.npz", schema_members(16))
    return _set_extract_version(path, 255), None


def _zip64_entry_bomb(path, entries):
    """A file whose 32-bit EOCD lies and whose ZIP64 record tells the truth.

    `zipfile._EndRecData` consults the ZIP64 locator whenever it is present and
    takes the entry count and directory size from the ZIP64 record, WITHOUT
    requiring the 0xFFFF sentinels. So a bounded-looking 32-bit record ("five
    entries, a 300-byte directory") is advisory, and `ZipFile` goes on to build
    one `ZipInfo` per real entry. Measured before the fix: 60,000 entries from
    a 2.7 MB file cost 2.5s and 23 MB of heap, and the archive was only refused
    afterwards, on its member names.
    """
    directory = bytearray()
    for _ in range(entries):
        directory += struct.pack("<4s4B4HL2L5H2L", b"PK\x01\x02", 20, 0, 20, 0,
                                 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    cd_offset = 4
    zip64_offset = cd_offset + len(directory)
    zip64_eocd = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                             entries, entries, len(directory), cd_offset)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, zip64_offset, 1)
    eocd = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 5, 5, 300, cd_offset, 0)
    Path(path).write_bytes(b"PK\x03\x04" + bytes(directory) + zip64_eocd
                           + locator + eocd)
    return Path(path)


def _case_zip64_unsupported(root, tmp_path):
    # Small on purpose: 64 entries is enough to prove the refusal, and the
    # point of the fix is that the count never gets to matter.
    return _zip64_entry_bomb(root / "v070_zip64.npz", 64), None


def _case_central_directory_too_large(root, tmp_path):
    path = write_npz(root / "v070_cd.npz", schema_members())
    return path, dataclasses.replace(guard.PRODUCTION_POLICY,
                                     central_directory_max_bytes=8)


def _case_archive_payload_total_too_large(root, tmp_path):
    path = write_npz(root / "v070_total.npz", schema_members())
    return path, dataclasses.replace(guard.PRODUCTION_POLICY,
                                     max_total_declared_bytes=1024)


def _case_member_count(root, tmp_path):
    path = root / "v070_many.npz"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(guard.PRODUCTION_POLICY.max_members
                           + guard._COUNT_PARSE_SLACK + 1):
            archive.writestr("m%d.npy" % index, b"x")
    return path, None


def _case_member_name_unsafe(root, tmp_path):
    members = schema_members()
    members["../../escape.npy"] = npy_bytes("|u1", (1,))
    return write_npz(root / "v070_trav.npz", members), None


def _case_member_is_directory(root, tmp_path):
    members = schema_members()
    members["subdir/"] = b""
    return write_npz(root / "v070_subdir.npz", members), None


def _case_member_duplicate(root, tmp_path):
    return write_npz(root / "v070_dup.npz", schema_members(),
                     duplicate="lattice.npy"), None


def _case_member_unexpected(root, tmp_path):
    members = schema_members()
    members["surprise.npy"] = npy_bytes("|u1", (1,))
    return write_npz(root / "v070_extra.npz", members), None


def _case_member_missing(root, tmp_path):
    members = schema_members()
    members.pop("ca_step.npy")
    return write_npz(root / "v070_missing.npz", members), None


def _case_member_encrypted(root, tmp_path):
    path = write_npz(root / "v070_enc.npz", schema_members())
    return set_encrypted_flag(path), None


def _set_central_flag_bits(path, bits):
    """Set general-purpose flag bits on every central-directory entry."""
    data = bytearray(Path(path).read_bytes())
    offset = 0
    patched = 0
    while True:
        index = data.find(b"PK\x01\x02", offset)
        if index < 0:
            break
        current = struct.unpack_from("<H", data, index + 8)[0]
        struct.pack_into("<H", data, index + 8, current | bits)
        patched += 1
        offset = index + 4
    assert patched, "no central-directory header found in the fixture"
    Path(path).write_bytes(bytes(data))
    return Path(path)


def _case_member_flags_unsupported(root, tmp_path):
    # Bit 5, Zip 2.7 compressed patched data. Bit 6 is covered separately.
    path = write_npz(root / "v070_patched.npz", schema_members(16))
    return _set_central_flag_bits(path, 0x0020), None


def _case_member_compression_unsupported(root, tmp_path):
    return write_npz(root / "v070_bz2.npz", schema_members(),
                     compression=zipfile.ZIP_BZIP2), None


def _case_member_payload_too_large(root, tmp_path):
    members = schema_members()
    members["memory_grid.npy"] = npy_bytes(
        "<f4", (65536, 16, 16, 16), payload=b"",
        header="{'descr': '<f4', 'fortran_order': False, "
               "'shape': (65536, 16, 16, 16), }")
    return write_npz(root / "v070_wide.npz", members), None


def _case_member_header_unreadable(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = b"\x93NUM"
    return write_npz(root / "v070_stubhdr.npz", members), None


def _case_member_npy_magic_invalid(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = b"XXXXXX" + members["lattice.npy"][6:]
    return write_npz(root / "v070_magic.npz", members), None


def _case_member_npy_version_unsupported(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 16), version=(4, 0))
    return write_npz(root / "v070_ver.npz", members), None


def _case_member_header_too_large(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16),
        header="{'descr': '|u1', 'fortran_order': False, "
               "'shape': (16, 16, 16), }" + " " * 5000)
    return write_npz(root / "v070_hdrbig.npz", members), None


def _case_member_header_malformed(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16),
        header="{'descr': '|u1', 'shape': (16, 16, 16), }")
    return write_npz(root / "v070_hdrbad.npz", members), None


def _case_member_dtype_object(root, tmp_path):
    members = schema_members()
    members["generation.npy"] = npy_bytes("|O", (), payload=b"")
    return write_npz(root / "v070_obj.npz", members), None


def _case_member_dtype_structured(root, tmp_path):
    members = schema_members()
    members["generation.npy"] = npy_bytes(
        "<i8", (), payload=b"",
        header="{'descr': [('payload', '|O'), ('n', '<i4')], "
               "'fortran_order': False, 'shape': (1,), }")
    return write_npz(root / "v070_struct.npz", members), None


def _case_member_dtype_subarray(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16), payload=b"",
        header="{'descr': ('|u1', (2, 2)), 'fortran_order': False, "
               "'shape': (16, 16, 16), }")
    return write_npz(root / "v070_sub.npz", members), None


def _case_member_dtype_zero_itemsize(root, tmp_path):
    members = schema_members()
    members["best_fitness.npy"] = npy_bytes("|U0", (), payload=b"")
    return write_npz(root / "v070_zero.npz", members), None


def _case_member_dtype_unsupported(root, tmp_path):
    members = schema_members()
    members["generation.npy"] = npy_bytes(
        "<i8", (), payload=b"",
        header="{'descr': '<M8[ns]', 'fortran_order': False, 'shape': (), }")
    return write_npz(root / "v070_datetime.npz", members), None


def _case_member_dtype_family(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes("<f4", (16, 16, 16))
    return write_npz(root / "v070_family.npz", members), None


def _case_member_fortran_order(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 16), fortran=True)
    return write_npz(root / "v070_fortran.npz", members), None


def _case_member_rank(root, tmp_path):
    members = schema_members()
    members["generation.npy"] = npy_bytes("<i8", (3,))
    return write_npz(root / "v070_rank.npz", members), None


def _case_member_shape_invalid(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16), payload=b"",
        header="{'descr': '|u1', 'fortran_order': False, "
               "'shape': (16, 16, 999999999999999999), }")
    return write_npz(root / "v070_absurd.npz", members), None


def _case_member_size_inconsistent(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 16)) + b"\x00" * 64
    return write_npz(root / "v070_incon.npz", members), None


def _case_lattice_not_cubic(root, tmp_path):
    members = schema_members()
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 32))
    return write_npz(root / "v070_oblong.npz", members), None


def _case_edge_out_of_range(root, tmp_path):
    return write_npz(root / "v070_512.npz", declared_members(512)), None


def _case_edge_not_multiple(root, tmp_path):
    return write_npz(root / "v070_24.npz", declared_members(24)), None


def _case_spatial_disagreement(root, tmp_path):
    members = schema_members(16)
    members["memory_grid.npy"] = npy_bytes("<f4", (8, 32, 32, 32))
    return write_npz(root / "v070_spatial.npz", members), None


#: One reproducible case per declared reason code. The mapping is asserted to
#: be exactly the declared roster below, so a code can neither be added
#: without a case nor left in place after the check that produced it is gone.
REFUSAL_CASES = {
    "path_not_confined": _case_path_not_confined,
    "path_not_regular_file": _case_path_not_regular_file,
    "path_suffix_not_npz": _case_path_suffix_not_npz,
    "archive_too_large": _case_archive_too_large,
    "archive_truncated": _case_archive_truncated,
    "not_zip_archive": _case_not_zip_archive,
    "zip64_unsupported": _case_zip64_unsupported,
    "central_directory_too_large": _case_central_directory_too_large,
    "archive_payload_total_too_large": _case_archive_payload_total_too_large,
    "member_count": _case_member_count,
    "member_name_unsafe": _case_member_name_unsafe,
    "member_is_directory": _case_member_is_directory,
    "member_duplicate": _case_member_duplicate,
    "member_unexpected": _case_member_unexpected,
    "member_missing": _case_member_missing,
    "member_encrypted": _case_member_encrypted,
    "member_flags_unsupported": _case_member_flags_unsupported,
    "member_compression_unsupported": _case_member_compression_unsupported,
    "member_payload_too_large": _case_member_payload_too_large,
    "member_header_unreadable": _case_member_header_unreadable,
    "member_npy_magic_invalid": _case_member_npy_magic_invalid,
    "member_npy_version_unsupported": _case_member_npy_version_unsupported,
    "member_header_too_large": _case_member_header_too_large,
    "member_header_malformed": _case_member_header_malformed,
    "member_dtype_object": _case_member_dtype_object,
    "member_dtype_structured": _case_member_dtype_structured,
    "member_dtype_subarray": _case_member_dtype_subarray,
    "member_dtype_zero_itemsize": _case_member_dtype_zero_itemsize,
    "member_dtype_unsupported": _case_member_dtype_unsupported,
    "member_dtype_family": _case_member_dtype_family,
    "member_fortran_order": _case_member_fortran_order,
    "member_rank": _case_member_rank,
    "member_shape_invalid": _case_member_shape_invalid,
    "member_size_inconsistent": _case_member_size_inconsistent,
    "lattice_not_cubic": _case_lattice_not_cubic,
    "edge_out_of_range": _case_edge_out_of_range,
    "edge_not_multiple": _case_edge_not_multiple,
    "spatial_disagreement": _case_spatial_disagreement,
}


def _case_member_payload_unreadable(root, tmp_path):
    """A member whose CRC is wrong: a valid header over a corrupt body.

    Preflight cannot see this. It reads each member's HEADER, and a payload can
    only be checked by decompressing it -- which is exactly the work the guard
    exists to avoid doing before admission. So the archive is admitted, and the
    failure surfaces during the caller's extraction.
    """
    path = write_npz(root / "v070_crc.npz", schema_members(16))
    data = bytearray(path.read_bytes())
    index = data.find(b"PK\x01\x02")
    assert index > 0, "no central-directory header in the fixture"
    struct.pack_into("<I", data, index + 16, 0xDEADBEEF)  # CRC-32 field
    path.write_bytes(bytes(data))
    return path, None


def _read_a_member(handle):
    """Stand in for what a consumer's `np.load` does with the descriptor.

    Reading a member decompresses it and verifies its CRC, which is the step
    that raises `zipfile.BadZipFile` -- the exact class NumPy's own extraction
    raises, through the same `zipfile` machinery.
    """
    with zipfile.ZipFile(handle) as archive:
        archive.read("lattice.npy")


#: Reason codes raised from INSIDE the caller's block rather than during
#: preflight. Kept in their own table because they need a body to run, not
#: merely an archive to open -- and because the distinction is the point: these
#: are the failures preflight structurally cannot reach.
BLOCK_REFUSAL_CASES = {
    "member_payload_unreadable": (_case_member_payload_unreadable, _read_a_member),
}


def test_every_declared_reason_code_has_a_reproducible_case():
    """Anti-vacuity for the roster itself: no unreachable code may be declared,
    and no case may name a code the module does not declare."""
    assert set(REFUSAL_CASES) | set(BLOCK_REFUSAL_CASES) == set(guard.REASON_CODES)
    assert not (set(REFUSAL_CASES) & set(BLOCK_REFUSAL_CASES))
    assert len(guard.REASON_CODES) == len(set(guard.REASON_CODES))


@pytest.mark.parametrize("reason", sorted(BLOCK_REFUSAL_CASES))
def test_each_block_reason_code_is_produced_by_its_case(reason, root, tmp_path):
    build, body = BLOCK_REFUSAL_CASES[reason]
    path, policy = build(root, tmp_path)
    with pytest.raises(guard.SnapshotArchiveRejected) as excinfo:
        with guard.admit_snapshot(path, data_dir=root,
                                  policy=policy or guard.PRODUCTION_POLICY) as fh:
            body(fh)
    assert excinfo.value.reason == reason
    assert str(excinfo.value) == reason


def test_a_corrupt_payload_is_admitted_then_refused_not_refused_early(root,
                                                                      tmp_path):
    """The ordering claim, made explicit: this archive PASSES preflight.

    Without this, the CRC case could be passing because some earlier structural
    check happened to catch it, and the block-boundary translation would be
    untested.
    """
    path, _ = _case_member_payload_unreadable(root, tmp_path)
    with guard.admit_snapshot(path, data_dir=root) as fh:
        assert fh.read(4) == b"PK\x03\x04"  # admitted; no refusal raised here


@pytest.mark.parametrize("modname,expected", [
    ("numpy.lib.format", True),           # NumPy < 2.1
    ("numpy.lib._format_impl", True),     # NumPy >= 2.1
    ("numpy.lib.npyio", False),           # NumPy, but not the reader
    ("my.own.module", False),             # a consumer imitating the message
])
def test_the_numpy_eof_classifier_matches_on_module_not_filename(modname,
                                                                  expected):
    """The previous check compared FILESYSTEM PATH COMPONENTS against
    `("numpy", "lib", "format")` and was dead on every NumPy version: the file
    is `format.py`, so `format` is never a path component. NumPy 2.1 then moved
    the implementation to `_format_impl.py`, which the same check would also
    have missed. Matching on the frame's `__name__` fixes both, and both module
    names are listed explicitly so a rename fails a test rather than silently
    widening a prefix rule.
    """
    namespace = {"__name__": modname}
    exec(compile("def _read_bytes():\n"
                 "    raise ValueError('EOF: reading array data, expected 512"
                 " bytes got 100')\n", "irrelevant_filename.py", "exec"),
         namespace)
    try:
        namespace["_read_bytes"]()
    except ValueError as exc:
        assert guard._is_numpy_array_data_eof(exc) is expected


def test_the_numpy_eof_classifier_still_requires_the_message():
    """Module and function alone are not enough: an unrelated `ValueError`
    from the same reader must not be translated."""
    namespace = {"__name__": "numpy.lib.format"}
    exec(compile("def _read_bytes():\n    raise ValueError('bad magic')\n",
                 "f.py", "exec"), namespace)
    try:
        namespace["_read_bytes"]()
    except ValueError as exc:
        assert guard._is_numpy_array_data_eof(exc) is False


def test_a_memory_error_from_the_syntax_gate_propagates(monkeypatch):
    """`MemoryError` is a statement about the MACHINE, not about the archive.

    By the time the gate runs, the custom parser has already bounded the header
    bytes, the nesting depth, the integer digit runs and the token count, so
    running out of memory there is a system failure. Translating it would
    report that as a bad snapshot -- and in the geometry daemon would record
    the file in the retry memory so it is never reconsidered.
    """
    def _oom(*args, **kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr(guard.ast, "parse", _oom)
    with pytest.raises(MemoryError) as excinfo:
        guard._parse_literal("{'descr': '|u1', 'fortran_order': False, "
                             "'shape': (1,), }")
    assert str(excinfo.value) == "out of memory"


def test_the_syntax_gate_still_translates_a_real_syntax_error(monkeypatch):
    """Anti-vacuity for the boundary above: the gate has not simply stopped
    catching things."""
    with pytest.raises(guard._HeaderSyntaxError):
        guard._parse_literal("{'descr': '|u1', 'fortran_order': False, "
                             "'shape': (016,), }")


@pytest.mark.parametrize("raised", [
    MemoryError("oom"),
    KeyboardInterrupt(),
    ValueError("EOF: reading array data"),
    RuntimeError("programmer error"),
    KeyError("lattice"),
    AttributeError("nope"),
], ids=["memory", "keyboard_interrupt", "value_error", "runtime", "key",
        "attribute"])
def test_the_block_boundary_translates_nothing_else(root, raised):
    """The narrowness of the translation IS the contract.

    `MemoryError`, `KeyboardInterrupt`, a non-matching `ValueError` and every
    programmer error must leave the block exactly as they were raised.

    The `value_error` case carries NumPy's array-data EOF TEXT but is raised
    here, by hand -- it is not NumPy's own `_read_bytes` exception, and that is
    the point of including it. A genuine classified NumPy array-data EOF IS
    translated, by the `except ValueError` clause that runs before this one;
    `_is_numpy_array_data_eof` tells the two apart by the raising frame and its
    module, not by the message. So this parameter proves the classifier cannot
    be fooled by the words alone, and
    `test_a_truncated_payload_becomes_member_payload_unreadable` covers the
    real thing.
    """
    path = write_npz(root / "v070_passthrough.npz", schema_members(16))
    with pytest.raises(type(raised)) as excinfo:
        with guard.admit_snapshot(path, data_dir=root):
            raise raised
    assert type(excinfo.value) is type(raised)
    assert str(excinfo.value) == str(raised)


def test_a_refusal_raised_inside_the_block_keeps_its_own_reason(root):
    """A `SnapshotArchiveRejected` from the caller's own code is re-raised
    unchanged rather than re-coded as a payload failure."""
    path = write_npz(root / "v070_inner.npz", schema_members(16))
    with pytest.raises(guard.SnapshotArchiveRejected) as excinfo:
        with guard.admit_snapshot(path, data_dir=root):
            raise guard.SnapshotArchiveRejected("member_missing")
    assert excinfo.value.reason == "member_missing"


def test_the_descriptor_is_closed_after_a_block_boundary_refusal(root, tmp_path,
                                                                 opened_files):
    path, _ = _case_member_payload_unreadable(root, tmp_path)
    with pytest.raises(guard.SnapshotArchiveRejected):
        with guard.admit_snapshot(path, data_dir=root) as fh:
            _read_a_member(fh)
    assert opened_files, "the guard never opened the archive"
    assert all(handle.closed for handle in opened_files)


@pytest.mark.parametrize("reason", sorted(REFUSAL_CASES))
def test_each_reason_code_is_produced_by_its_case(reason, root, tmp_path):
    path, policy = REFUSAL_CASES[reason](root, tmp_path)
    assert admit(path, root, policy) == reason


@pytest.mark.parametrize("reason", sorted(REFUSAL_CASES))
def test_no_refusal_discloses_archive_content(reason, root, tmp_path):
    """These messages are logged unattended and translated for unauthenticated
    HTTP callers, so they must carry nothing an attacker chose."""
    path, policy = REFUSAL_CASES[reason](root, tmp_path)
    with pytest.raises(guard.SnapshotArchiveRejected) as excinfo:
        with guard.admit_snapshot(path, data_dir=root,
                                  policy=policy or guard.PRODUCTION_POLICY):
            pass
    message = str(excinfo.value)
    assert message == reason
    assert str(tmp_path) not in message
    assert Path(path).name not in message
    for leaked in (".npy", "descr", "escape", "surprise", "v070", "\n", "  "):
        assert leaked not in message


@pytest.mark.parametrize("name", [
    "../escape.npy", "../../etc/passwd.npy", "/etc/passwd.npy",
    "C:\\windows\\x.npy", "sub\\lattice.npy", "nested/lattice.npy",
    "lattice.npy/../x.npy",
])
def test_every_hostile_member_name_shape_is_refused(root, name):
    members = schema_members()
    members[name] = npy_bytes("|u1", (1,))
    path = write_npz(root / "v070_names.npz", members)
    assert admit(path, root) == "member_name_unsafe"


def test_a_symlink_out_of_the_data_directory_is_refused(root, tmp_path):
    """Containment is decided after symlink resolution, so a link inside the
    watched directory cannot smuggle in a file from outside it."""
    target = tmp_path / "v070_target.npz"
    write_npz(target, schema_members())
    link = root / "v070_link.npz"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform gate
        pytest.skip("symlink creation is not permitted in this environment")
    assert admit(link, root) == "path_not_confined"


def test_an_unsupported_extract_version_is_refused_not_escaped(root, tmp_path):
    """The archive is schema-perfect; one byte per central entry is changed.

    `NotImplementedError` subclasses `RuntimeError`, so the constructor's
    refusal escaped `admit_snapshot` untyped — turning every Medusa snapshot
    route into a 500 rather than the sanitized 503, and wedging the geometry
    daemon, which records only typed refusals in its retry memory.
    """
    path, policy = _case_unsupported_extract_version(root, tmp_path)
    assert admit(path, root, policy) == "not_zip_archive"


def test_the_same_archive_is_admitted_at_a_supported_extract_version(root):
    """Control: the fixture differs from an admitted archive in that field
    alone, so the refusal above is about the version and nothing else."""
    path = write_npz(root / "v070_extver_ok.npz", schema_members(16))
    assert admit(path, root) is None
    _set_extract_version(path, 255)
    assert admit(path, root) == "not_zip_archive"


@pytest.mark.parametrize("version", [64, 100, 255])
def test_every_extract_version_above_the_ceiling_is_typed(root, version):
    path = write_npz(root / ("v070_ev%d.npz" % version), schema_members(16))
    _set_extract_version(path, version)
    assert admit(path, root) == "not_zip_archive"


def test_a_raw_member_name_differing_from_the_sanitised_one_is_refused(root):
    """`ZipInfo.filename` is post-`_sanitize_filename` and can additionally be
    overridden by a 0x7075 extra field, so an entry can present a schema name
    while `orig_filename` holds something else — which CPython quotes verbatim
    in its "Overlapped entries" warning, putting attacker-chosen text on an
    unattended daemon's stderr from an ADMITTED archive."""
    path = write_npz(root / "v070_rawname.npz", schema_members(16))
    assert admit(path, root) is None, "the fixture must be admissible first"

    # Injected rather than hand-forged. `ZipInfo.__init__` truncates a NUL on
    # CONSTRUCTION, so `writestr` cannot store a name that diverges, and a
    # crafted central entry would additionally have to keep the local header,
    # the directory size and the EOCD offsets all consistent -- surgery whose
    # failure mode would be a DIFFERENT refusal, making the test say nothing
    # about this check. Divergence is what is under test, so divergence is what
    # is injected.
    real_infolist = zipfile.ZipFile.infolist

    def _diverging_infolist(self):
        entries = real_infolist(self)
        for entry in entries:
            if entry.filename == "lattice.npy":
                entry.orig_filename = "lattice.npy\x00../../etc/passwd"
        return entries

    with mock.patch.object(zipfile.ZipFile, "infolist", _diverging_infolist):
        reason = admit(path, root)
    assert reason == "member_name_unsafe"


@pytest.mark.parametrize("descr", ["<i000004", "<f00008", "|u01"])
def test_a_zero_padded_width_is_refused(root, descr):
    """`<i000004` normalises to a width of 4 and would pass the allowlist, but
    NumPy is handed the descriptor STRING, not the normalised width."""
    members = schema_members(16)
    members["generation.npy"] = npy_bytes(
        "<i8", (), payload=b"\x00" * 4,
        header="{'descr': '%s', 'fortran_order': False, 'shape': (), }" % descr)
    path = write_npz(root / "v070_padded.npz", members)
    assert admit(path, root) == "member_dtype_unsupported"


@pytest.mark.parametrize("names,expected", [
    # The digit-count boundary: text order says 999999 > 1000000, the numbers
    # say otherwise, and the numbers are what a generation IS.
    (["v070_gen999999_step1_a.npz", "v070_gen1000000_step1_a.npz"],
     ["v070_gen1000000_step1_a.npz", "v070_gen999999_step1_a.npz"]),
    # Ordinary same-width generations, where text and number agree -- so the
    # numeric rule must not have broken the common case to fix the rare one.
    (["v070_gen000010_step000001_a.npz", "v070_gen000002_step000001_a.npz"],
     ["v070_gen000010_step000001_a.npz", "v070_gen000002_step000001_a.npz"]),
    # Same generation: the step decides.
    (["v070_gen000007_step000002_a.npz", "v070_gen000007_step000011_a.npz"],
     ["v070_gen000007_step000011_a.npz", "v070_gen000007_step000002_a.npz"]),
    # Step across its own digit-count boundary.
    (["v070_gen000007_step999999_a.npz", "v070_gen000007_step1000000_a.npz"],
     ["v070_gen000007_step1000000_a.npz", "v070_gen000007_step999999_a.npz"]),
], ids=["generation_boundary", "same_width_generations", "step_decides",
        "step_boundary"])
def test_equal_mtime_ties_order_by_sequence_not_by_text(root, names, expected):
    """Equal modification times are broken by the snapshot's own sequence.

    Ties are only reachable on coarse-grained storage, but when they happen the
    answer should be the newer SNAPSHOT, not the alphabetically later filename.
    """
    for name in names:
        _touch(root / name, 7_000_000_000)
    ordered = guard.newest_first([root / name for name in names])
    assert [p.name for p in ordered] == expected


def test_modification_time_still_outranks_the_sequence(root):
    """The sequence is a TIE-BREAK, not the primary key. A genuinely newer
    file wins even if its generation number is lower."""
    low_but_new = _touch(root / "v070_gen000001_step1_a.npz", 9_000_000_000)
    high_but_old = _touch(root / "v070_gen999999_step1_a.npz", 1_000_000_000)
    assert guard.newest_first([high_but_old, low_but_new]) == [low_but_new,
                                                               high_but_old]


def test_an_unparseable_name_never_displaces_a_numbered_one(root):
    """Names are attacker-influenced, so the sequence read is total: a name
    that carries no sequence sorts below every name that does."""
    numbered = _touch(root / "v070_gen000001_step1_a.npz", 7_000_000_000)
    junk = _touch(root / "v070_gen_notanumber.npz", 7_000_000_000)
    assert guard.newest_first([junk, numbered]) == [numbered, junk]
    assert guard._sequence_of(junk) == guard._NO_SEQUENCE


def test_an_absurdly_long_digit_run_carries_no_sequence(root):
    """Bounded: an 80-digit 'generation' is not parsed into an integer."""
    absurd = root / ("v070_gen" + "9" * 80 + "_step1.npz")
    assert guard._sequence_of(absurd) == guard._NO_SEQUENCE


def test_order_candidates_separates_empty_from_unreadable(root):
    """`[]` means two very different things, and discovery must say which."""
    empty = guard.order_candidates([])
    assert empty.ordered == [] and empty.unreadable == 0
    assert not empty.had_candidates

    ghosts = [root / ("v070_ghost%d.npz" % i) for i in range(3)]
    blind = guard.order_candidates(ghosts)
    assert blind.ordered == [] and blind.unreadable == 3
    assert blind.had_candidates, (
        "a directory of unreadable candidates is not an empty directory")


# ---------------------------------------------------------------------------
# Bounded newest-first admission fallback
# ---------------------------------------------------------------------------

def test_first_admissible_skips_an_unusable_newest_candidate(root):
    good = write_npz(root / "v070_gen000001_good.npz", schema_members(16))
    poison = write_npz(root / "v070_gen000002_bad.npz", declared_members(512))
    assert guard.first_admissible([poison, good], data_dir=root) == good


def test_first_admissible_returns_the_newest_when_none_is_admissible(root):
    """Not `None`: the caller then runs its ordinary load and reports the typed
    refusal through the path it already has. Returning `None` would turn
    "every recent snapshot is broken" into "there are no snapshots"."""
    first = write_npz(root / "v070_gen000002_bad.npz", declared_members(512))
    second = write_npz(root / "v070_gen000001_bad.npz", declared_members(512))
    assert guard.first_admissible([first, second], data_dir=root) == first


def test_first_admissible_is_bounded_by_the_depth(root):
    depth = guard.PRODUCTION_POLICY.selection_depth
    poisons = [write_npz(root / ("v070_gen%06d_bad.npz" % i),
                         declared_members(512))
               for i in range(depth + 2)]
    good = write_npz(root / "v070_gen999_good.npz", schema_members(16))
    probed = []
    real_admit = guard.admit_snapshot

    def _counting_admit(path, **kwargs):
        probed.append(path)
        return real_admit(path, **kwargs)

    with mock.patch.object(guard, "admit_snapshot", _counting_admit):
        selected = guard.first_admissible(poisons + [good], data_dir=root)

    assert len(probed) == depth, "the search was not bounded to the window"
    assert selected == poisons[0], (
        "a candidate outside the window must not be found")


def test_first_admissible_on_an_empty_list_is_none(root):
    assert guard.first_admissible([], data_dir=root) is None


@pytest.mark.parametrize("header,label", [
    ("{'descr':\xa0'|u1', 'fortran_order': False, 'shape': (16, 16, 16), }",
     "NBSP after a key"),
    ("{'descr': '|u1',\xa0'fortran_order': False, 'shape': (16, 16, 16), }",
     "NBSP between entries"),
    ("\xa0{'descr': '|u1', 'fortran_order': False, 'shape': (16, 16, 16), }",
     "leading NBSP"),
], ids=["after_key", "between_entries", "leading"])
def test_non_ascii_whitespace_in_a_header_is_refused(root, header, label):
    """`str.strip()` removes every Unicode whitespace character, NBSP among
    them, so a header padded with NBSP was silently normalised and accepted
    while NumPy's own reader saw the NBSP and refused. The guard must not be
    more permissive than the loader it protects."""
    members = schema_members(16)
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 16), version=(3, 0),
                                       header=header)
    path = write_npz(root / "v070_nbsp.npz", members)
    assert admit(path, root) == "member_header_malformed", label


@pytest.mark.parametrize("shape_text", ["(016, 16, 16)", "(16, 0016, 16)",
                                        "(00016, 16, 16)"])
def test_a_zero_padded_dimension_is_refused(root, shape_text):
    """Python rejects a leading-zero integer literal outright, so a header
    carrying one is not a Python expression at all — and NumPy, which parses it
    as one, would refuse it. The custom parser accepted it."""
    members = schema_members(16)
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16),
        header="{'descr': '|u1', 'fortran_order': False, 'shape': %s, }"
               % shape_text)
    path = write_npz(root / "v070_padded_dim.npz", members)
    assert admit(path, root) == "member_header_malformed"


def test_a_descriptor_with_a_raw_newline_is_refused(root):
    """A real newline inside the quoted descriptor.

    Refused as malformed rather than as an unsupported dtype, and the reason
    is worth stating: a raw newline inside a single-quoted literal is not a
    Python expression, so the syntax gate refuses the header before the
    descriptor rule is reached. Both barriers now exist; this fixture proves
    the outer one.
    """
    members = schema_members(16)
    members["memory_grid.npy"] = npy_bytes(
        "<f4", (8, 16, 16, 16), payload=b"",
        header="{'descr': '<f4\n', 'fortran_order': False, "
               "'shape': (8, 16, 16, 16), }")
    path = write_npz(root / "v070_descrnl.npz", members)
    assert admit(path, root) == "member_header_malformed"


def test_the_descriptor_pattern_is_anchored_at_both_ends():
    """The inner barrier, tested where it lives.

    `$` also matches just before a trailing newline, so `match` accepted
    `'<f4\\n'` — the guard checked one descriptor while NumPy would have
    received another. `fullmatch` cannot. Asserted directly because the syntax
    gate now refuses such a header first, and a test that could only ever be
    satisfied by the outer barrier would say nothing about this one.
    """
    assert guard._DESCR_RE.match("<f4\n") is not None, (
        "the pattern no longer reproduces the laxity being guarded against")
    assert guard._DESCR_RE.fullmatch("<f4\n") is None
    assert guard._DESCR_RE.fullmatch("<f4") is not None


def test_the_syntax_gate_runs_after_the_resource_bounds(root):
    """Ordering, and it is the whole point: `ast.parse` has no depth or size
    limits of its own, so it must only ever see text the capped parser has
    already bounded."""
    source = Path(guard.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    body = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_parse_literal")
    calls = [node.func.id for node in ast.walk(body)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert "_syntax_gate" in calls
    # The capped parser is constructed before the gate is called.
    lines = ast.unparse(body).splitlines()
    parser_at = next(i for i, l in enumerate(lines) if "_LiteralParser(" in l)
    gate_at = next(i for i, l in enumerate(lines) if "_syntax_gate(" in l)
    assert parser_at < gate_at


def test_the_syntax_gate_does_not_evaluate():
    """It parses. A header that would have an effect if evaluated must not."""
    with pytest.raises(guard._HeaderSyntaxError):
        guard._parse_literal("__import__('os').environ")
    # And the accepted grammar is still the narrow one: a call is refused by
    # the capped parser before the gate ever sees it.
    with pytest.raises(guard._HeaderSyntaxError):
        guard._parse_literal("dict(descr='|u1')")


def test_every_producer_shaped_header_still_parses(root):
    """Anti-vacuity for the whole tightening: the exact header text NumPy
    writes, with its trailing comma and space padding, must still be admitted
    after the strip removal, the syntax gate and `fullmatch`."""
    path = write_npz(root / "v070_producer_hdr.npz", schema_members(16))
    assert admit(path, root) is None


# ---------------------------------------------------------------------------
# Per-entry ZIP64 extra fields
# ---------------------------------------------------------------------------

def _rewrite_central_extra(path, extra):
    """Replace every central entry's extra field with `extra`.

    Rebuilt rather than patched in place: the entry's extra length, the
    directory size and the EOCD offsets all have to stay consistent, and a
    half-consistent archive would be refused for a different reason and prove
    nothing.
    """
    source = Path(path)
    with zipfile.ZipFile(source) as archive:
        members = {info.filename: archive.read(info.filename)
                   for info in archive.infolist()}
    rebuilt = source.with_name("rebuilt_" + source.name)
    with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.extra = extra
            archive.writestr(info, blob)
    return rebuilt


def _zip64_extra(*, size=0, redundant=False):
    """A ZIP64 extended-information TLV, optionally repeated."""
    payload = b"\x00" * size
    tlv = struct.pack("<HH", 0x0001, len(payload)) + payload
    return tlv * (2 if redundant else 1)


@pytest.mark.parametrize("extra,label", [
    (_zip64_extra(size=8), "one 8-byte field"),
    (_zip64_extra(size=16), "size and compressed size"),
    (_zip64_extra(size=24), "sizes and header offset"),
    (_zip64_extra(size=0), "zero-length, tag only"),
    (_zip64_extra(size=8, redundant=True), "repeated"),
    (struct.pack("<HH", 0x5455, 1) + b"\x00" + _zip64_extra(size=8),
     "after an unrelated field"),
], ids=["eight", "sixteen", "twentyfour", "empty", "redundant", "trailing"])
def test_a_per_entry_zip64_extra_field_is_refused(root, extra, label):
    """The EOCD checks catch an archive that is ZIP64 as a WHOLE. They say
    nothing about a single entry carrying a ZIP64 extended-information field —
    which is exactly where a per-entry 64-bit size or header offset lives, and
    exactly what `zipfile` reads to decide an entry's real sizes."""
    base = write_npz(root / "v070_z64extra.npz", schema_members(16))
    path = _rewrite_central_extra(base, extra)
    assert admit(path, root) == "zip64_unsupported", label


def test_a_valid_per_entry_zip64_archive_is_refused(root):
    """Not merely a forged tag: an archive `zipfile` itself considers a
    well-formed ZIP64 entry."""
    base = write_npz(root / "v070_z64real.npz", schema_members(16))
    extra = struct.pack("<HHQQ", 0x0001, 16, 0xFFFFFFFF, 0xFFFFFFFF)
    path = _rewrite_central_extra(base, extra)
    assert admit(path, root) == "zip64_unsupported"


@pytest.mark.parametrize("extra", [
    b"\x01",                                  # a fragment, too short for a TLV
    struct.pack("<HH", 0x5455, 40),           # declared length runs past the end
    struct.pack("<HH", 0x5455, 1),            # declares 1 byte, supplies none
], ids=["fragment", "overlong", "truncated_payload"])
def test_a_malformed_extra_field_is_refused(root, extra):
    """Bounded and total: a truncated or malformed TLV run is refused rather
    than guessed at.

    Either code is correct here. CPython's own `_decodeExtra` rejects some
    malformed runs while building the directory, which surfaces as
    `not_zip_archive` before this guard's walk is reached; the rest reach the
    walk and are refused as `zip64_unsupported`. What matters is that no
    malformed extra field is ADMITTED, and that the refusal is typed either
    way.
    """
    base = write_npz(root / "v070_badextra.npz", schema_members(16))
    path = _rewrite_central_extra(base, extra)
    assert admit(path, root) in {"zip64_unsupported", "not_zip_archive"}


def test_an_ordinary_extra_field_is_still_admitted(root):
    """Anti-vacuity: extra fields as such are not banned, only ZIP64 ones."""
    base = write_npz(root / "v070_okextra.npz", schema_members(16))
    extra = struct.pack("<HH", 0x5455, 5) + b"\x03\x00\x00\x00\x00"
    path = _rewrite_central_extra(base, extra)
    assert admit(path, root) is None


# ---------------------------------------------------------------------------
# Per-member compressed-source budget
# ---------------------------------------------------------------------------

def _empty_block_padding(count):
    """`count` empty non-final DEFLATE blocks: input consumed, no output.

    This is the shape that makes an output-bounded header read unbounded in
    INPUT — `read(4096)` keeps pulling source while the output counter never
    moves.
    """
    # A non-final stored block with a zero length: 3 header bits then LEN/NLEN.
    return b"\x00\x00\x00\xff\xff" * count


def _member_with_leading_empty_blocks(blob, count):
    """A raw-DEFLATE member prefixed with `count` empty blocks."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    tail = compressor.compress(blob) + compressor.flush()
    return _empty_block_padding(count) + tail


def _zip_with_raw_members(path, members):
    """A minimal ZIP writer that stores each member's compressed bytes VERBATIM.

    `zipfile` recompresses whatever it is given, which would discard the empty
    blocks that make this fixture interesting. `members` maps name -> (raw
    compressed bytes, uncompressed bytes, method).
    """
    out = bytearray()
    directory = []
    for name, spec in members.items():
        raw, plain, method = spec[0], spec[1], spec[2]
        override_crc = spec[3] if len(spec) > 3 else None
        encoded = name.encode("ascii")
        offset = len(out)
        crc = (zlib.crc32(plain) & 0xFFFFFFFF if override_crc is None
               else override_crc)
        out += struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 0, method, 0, 0,
                           crc, len(raw), len(plain), len(encoded), 0)
        out += encoded
        out += raw
        directory.append((encoded, method, crc, len(raw), len(plain), offset))

    start = len(out)
    for encoded, method, crc, csize, usize, offset in directory:
        out += struct.pack("<4s6H3L5H2L", b"PK\x01\x02", 20, 20, 0, method,
                           0, 0, crc, csize, usize, len(encoded), 0, 0, 0, 0,
                           0, offset)
        out += encoded
    out += struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, len(directory),
                       len(directory), len(out) - start, start, 0)
    Path(path).write_bytes(bytes(out))
    return Path(path)


def _archive_with_padded_lattice(path, padding_blocks):
    """A schema-valid archive whose lattice carries `padding_blocks` empty
    DEFLATE blocks before its NPY header."""
    plain = schema_members(16)
    built = {}
    for name, blob in plain.items():
        if name == "lattice.npy":
            raw = _member_with_leading_empty_blocks(blob, padding_blocks)
            built[name] = (raw, blob, zipfile.ZIP_DEFLATED)
        else:
            built[name] = (blob, blob, zipfile.ZIP_STORED)
    return _zip_with_raw_members(path, built)


def _peak_source_consumption(path, root):
    """How many source bytes the worst member actually costs for its header.

    Measured rather than guessed, so the boundary cases below sit exactly on
    the real threshold instead of on an assumption about `zipfile`'s chunk
    size.
    """
    peak = 0
    real_meter = guard._SourceMeter

    class _Recording(real_meter):
        def read(self, size=-1):
            data = super().read(size)
            nonlocal peak
            peak = max(peak, self.consumed)
            return data

    huge = dataclasses.replace(guard.PRODUCTION_POLICY,
                               max_header_source_bytes=1 << 30)
    with mock.patch.object(guard, "_SourceMeter", _Recording):
        admit(path, root, huge)
    return peak


def test_empty_deflate_blocks_are_bounded_by_the_source_budget(root):
    """Output-bounded is not input-bounded.

    A DEFLATE stream can emit empty non-final blocks indefinitely: each
    consumes compressed bytes and produces nothing, so the header read's
    OUTPUT ceiling never trips while the source read runs on. The budget
    meters what is actually read.

    The limit is calibrated to the fixture's measured consumption, so below /
    at / above are exact rather than approximate.
    """
    path = _archive_with_padded_lattice(root / "v070_padded.npz", 4000)
    needed = _peak_source_consumption(path, root)
    assert needed > 4096, "the padded fixture is not costly enough to bound"

    below = dataclasses.replace(guard.PRODUCTION_POLICY,
                                max_header_source_bytes=needed + 4096)
    exact = dataclasses.replace(guard.PRODUCTION_POLICY,
                                max_header_source_bytes=needed)
    above = dataclasses.replace(guard.PRODUCTION_POLICY,
                                max_header_source_bytes=needed - 1)

    assert admit(path, root, below) is None
    assert admit(path, root, exact) is None, "the budget is off by one"
    assert admit(path, root, above) == "member_header_unreadable"


def test_a_longer_empty_block_run_costs_more_source(root):
    """The meter tracks the padding, so the refusal is about the empty blocks
    and not about the hand-built archive costing a fixed amount."""
    short = _archive_with_padded_lattice(root / "v070_pad_short.npz", 1000)
    long = _archive_with_padded_lattice(root / "v070_pad_long.npz", 20000)
    assert (_peak_source_consumption(long, root)
            > _peak_source_consumption(short, root))


def test_a_far_oversized_empty_block_run_is_refused_at_the_production_limit(root):
    """No injected policy: the shipped 512 KiB budget refuses it."""
    path = _archive_with_padded_lattice(root / "v070_pad_huge.npz", 200_000)
    assert admit(path, root) == "member_header_unreadable"


def test_the_padded_fixture_is_otherwise_admissible(root):
    """Anti-vacuity: with no padding the same construction is admitted, so the
    refusals above are about the empty blocks and not about the hand-built
    archive being malformed."""
    path = _archive_with_padded_lattice(root / "v070_nopad.npz", 0)
    assert admit(path, root) is None


def test_the_source_budget_is_a_per_member_reset(root):
    """The budget is a per-member property, so it must not accumulate across
    members — five ordinary members must not exhaust one shared allowance."""
    path = write_npz(root / "v070_budget_ok.npz", schema_members(16))
    tiny = dataclasses.replace(guard.PRODUCTION_POLICY,
                               max_header_source_bytes=4096)
    assert admit(path, root, tiny) is None


def test_a_large_payload_with_an_early_header_stays_admissible(root):
    """The budget must NOT be compared against the member's `compress_size`.

    A legitimate high-entropy grid has a large compressed size and its NPY
    header in the first few hundred bytes; charging it for a payload it has not
    read would refuse exactly the archives that are fine.
    """
    members = schema_members(16)
    members["memory_grid.npy"] = npy_bytes(
        "<f4", (8, 16, 16, 16), payload=os.urandom(8 * 16 ** 3 * 4))
    path = write_npz(root / "v070_bigpayload.npz", members)
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("memory_grid.npy")
        assert info.compress_size > 128 * 1024, "the control is not large"
    policy = dataclasses.replace(guard.PRODUCTION_POLICY,
                                 max_header_source_bytes=64 * 1024)
    assert info.compress_size > policy.max_header_source_bytes
    assert admit(path, root, policy) is None, (
        "the budget was charged for payload the header read never touched")


def test_the_meter_counts_source_not_output(root):
    """The property in one line: output is bounded by the header ceiling, so
    only a SOURCE meter can bound a stream that emits nothing."""
    meter = guard._SourceMeter(io.BytesIO(b"x" * 100))
    meter.start(10)
    with pytest.raises(guard._SourceBudgetExceeded):
        meter.read(50)
    meter.release()
    meter._raw.seek(0)
    assert len(meter.read(50)) == 50, "the budget was not released"


def test_a_zip64_entry_bomb_is_refused_before_zipfile_builds_the_directory(root):
    """The refusal must arrive at the ZIP64 check, not later on the names.

    Before the fix this archive was refused as `member_name_unsafe` — a
    verdict reached only AFTER `ZipFile` had materialised every entry, which
    is the cost the bound exists to prevent. The reason code is therefore the
    load-bearing assertion here, not merely that something was refused.
    """
    bomb = _zip64_entry_bomb(root / "v070_bomb.npz", 512)
    assert admit(bomb, root) == "zip64_unsupported"


@pytest.mark.parametrize("entries", [1, 5, 64])
def test_the_zip64_refusal_does_not_depend_on_the_entry_count(root, entries):
    bomb = _zip64_entry_bomb(root / ("v070_b%d.npz" % entries), entries)
    assert admit(bomb, root) == "zip64_unsupported"


@pytest.mark.parametrize("descr,member,shape", [
    ("|u3", "lattice.npy", (16, 16, 16)),
    ("<u5", "lattice.npy", (16, 16, 16)),
    ("<f5", "memory_grid.npy", (8, 16, 16, 16)),
    ("<f3", "memory_grid.npy", (8, 16, 16, 16)),
    ("<i1000", "generation.npy", ()),
    ("<i3", "ca_step.npy", ()),
], ids=["u3", "u5", "f5", "f3", "i1000", "i3"])
def test_a_width_numpy_cannot_construct_is_refused(root, descr, member, shape):
    """`np.dtype('|u3')` raises TypeError, and its message quotes the
    descriptor verbatim — from a call site downstream of every
    `except SnapshotArchiveRejected`. A family rule alone admitted all of
    these."""
    members = schema_members(16)
    itemsize = int(descr[2:]) if descr[0] in "<>|=" else int(descr[1:])
    count = 1
    for dim in shape:
        count *= dim
    members[member] = npy_bytes(descr, shape,
                                payload=b"\x00" * (count * itemsize))
    path = write_npz(root / "v070_width.npz", members)
    assert admit(path, root) == "member_dtype_unsupported"


@pytest.mark.parametrize("descr,member,shape", [
    ("|u1", "lattice.npy", (16, 16, 16)),
    ("<u2", "lattice.npy", (16, 16, 16)),
    ("<f2", "memory_grid.npy", (8, 16, 16, 16)),
    ("<f8", "memory_grid.npy", (8, 16, 16, 16)),
    ("<i4", "generation.npy", ()),
    ("<i8", "ca_step.npy", ()),
], ids=["u1", "u2", "f2", "f8", "i4", "i8"])
def test_every_width_numpy_can_construct_is_still_admitted(root, descr, member,
                                                           shape):
    """The counterpart control: the width rule must not have quietly become a
    single pinned dtype, which would refuse legacy widths."""
    members = schema_members(16)
    itemsize = int(descr[2:]) if descr[0] in "<>|=" else int(descr[1:])
    count = 1
    for dim in shape:
        count *= dim
    members[member] = npy_bytes(descr, shape,
                                payload=b"\x00" * (count * itemsize))
    path = write_npz(root / "v070_okwidth.npz", members)
    assert admit(path, root) is None


@pytest.mark.parametrize("dimension", ["\xb2", "\xb3", "¹"], ids=[
    "superscript_two", "superscript_three", "superscript_one"])
def test_a_unicode_digit_dimension_is_refused_and_not_leaked(root, dimension):
    """`str.isdigit()` is true for the whole Unicode digit property; `int()`
    accepts only ASCII decimals. The parser used the former, so a header
    declaring a shape of `(\\xb2,)` raised a bare ValueError carrying the
    attacker's character out of the guard entirely."""
    members = schema_members(16)
    members["generation.npy"] = npy_bytes(
        "<i8", (), payload=b"",
        header="{'descr': '<i8', 'fortran_order': False, 'shape': (%s,), }"
               % dimension)
    path = write_npz(root / "v070_unicode.npz", members)
    assert admit(path, root) == "member_header_malformed"


def test_no_input_makes_the_guard_raise_an_untyped_error(root, tmp_path):
    """The module's central promise, asserted over every case at once: nothing
    derived from an archive's contents may leave `admit_snapshot` except as a
    reason code."""
    for reason, build in sorted(REFUSAL_CASES.items()):
        path, policy = build(root, tmp_path)
        try:
            with guard.admit_snapshot(path, data_dir=root,
                                      policy=policy or guard.PRODUCTION_POLICY):
                pass
        except guard.SnapshotArchiveRejected as exc:
            assert exc.reason in guard.REASON_CODES
        except Exception as exc:  # noqa: BLE001 - the escape IS the defect
            raise AssertionError(
                "%s escaped as %s: %s" % (reason, type(exc).__name__, exc))


def test_an_empty_header_is_a_syntax_error_not_a_depth_overflow():
    """`_peek()` returns "" at end of input and "" is a substring of every
    string, so the value dispatch treated end-of-input as an opening bracket
    and recursed to the depth cap instead of reporting the real problem."""
    with pytest.raises(guard._HeaderSyntaxError) as excinfo:
        guard._parse_literal("")
    assert "deep" not in str(excinfo.value)
    with pytest.raises(guard._HeaderSyntaxError) as excinfo:
        guard._parse_literal("{")
    assert "deep" not in str(excinfo.value)


@pytest.mark.parametrize("bits,label", [
    (0x0020, "compressed patched data (bit 5)"),
    (0x0040, "strong encryption (bit 6)"),
    (0x0060, "both"),
])
def test_unsupported_general_purpose_flag_bits_are_refused(root, bits, label):
    """Refused from the central directory, before the member is opened."""
    path = write_npz(root / "v070_flags.npz", schema_members(16))
    _set_central_flag_bits(path, bits)
    assert admit(path, root) == "member_flags_unsupported", label


def test_the_flag_check_refuses_before_the_member_is_ever_opened(root,
                                                                 monkeypatch):
    """Ordering, which the reason code alone cannot pin.

    CPython raises `NotImplementedError` for bits 5/6 from `ZipFile.open`, and
    this guard translates that to the SAME reason code — so deleting the
    central-directory check entirely would leave every other flag-bit test
    passing. What distinguishes the two is whether the member is opened at
    all, so that is what is counted here.
    """
    path = write_npz(root / "v070_flagorder.npz", schema_members(16))
    _set_central_flag_bits(path, 0x0020)

    opens = []
    real_open = zipfile.ZipFile.open

    def _counting_open(self, name, *args, **kwargs):
        opens.append(getattr(name, "filename", name))
        return real_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", _counting_open)
    assert admit(path, root) == "member_flags_unsupported"
    assert opens == [], (
        "the refusal came from ZipFile.open, not from the central directory")


def test_the_flag_check_does_not_stop_a_clean_archive_being_opened(root,
                                                                   monkeypatch):
    """Anti-vacuity for the counter above: an admissible archive DOES open its
    members, so `opens == []` means something."""
    path = write_npz(root / "v070_flagorder_ok.npz", schema_members(16))
    opens = []
    real_open = zipfile.ZipFile.open

    def _counting_open(self, name, *args, **kwargs):
        opens.append(getattr(name, "filename", name))
        return real_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", _counting_open)
    assert admit(path, root) is None
    assert len(opens) == 5


def test_a_non_ascii_member_name_is_refused(root):
    """The schema's five names are ASCII; anything else is a different name or
    an encoding trick, and both are refusals."""
    members = schema_members(16)
    members["latticeİ.npy"] = npy_bytes("|u1", (1,))
    path = write_npz(root / "v070_nonascii.npz", members)
    assert admit(path, root) == "member_name_unsafe"


@pytest.mark.skipif(not hasattr(os, "mkfifo"),
                    reason="FIFOs are a POSIX construct")
def test_a_fifo_named_like_a_snapshot_does_not_hang_the_guard(root):
    """`S_ISREG` cannot protect the OPEN itself.

    A plain `open()` of a FIFO blocks until a writer appears, so an attacker
    able to write to the watched directory could `mkfifo` a `v070_gen*.npz`
    and hang Lucid's whole asyncio server, or park one Medusa request thread
    per attempt. `O_NONBLOCK` makes the open return so `S_ISREG` can refuse.

    If this ever regresses it HANGS rather than fails, which is exactly why it
    is worth having: a hang in CI is a louder signal than a wrong reason code.
    """
    fifo = root / "v070_fifo.npz"
    os.mkfifo(fifo)
    assert admit(fifo, root) == "path_not_regular_file"


def test_a_not_implemented_error_from_zipfile_is_translated(root, monkeypatch):
    """The defensive half of the flag-bit handling.

    CPython 3.13 reads bits 5 and 6 from the CENTRAL directory
    (`zipfile.ZipFile.open` tests `zinfo.flag_bits`), so the check above
    normally wins and this branch is not reached through a crafted archive.
    It still matters: `NotImplementedError` subclasses `RuntimeError`, so
    without an explicit clause it would be swallowed by the broad handler and
    reported as an unreadable header, and its message names the flag. Injected
    directly, because inventing an archive that reaches it would be inventing
    a CPython that does not exist.
    """
    path = write_npz(root / "v070_notimpl.npz", schema_members(16))
    real_open = zipfile.ZipFile.open

    def _raising_open(self, name, *args, **kwargs):
        raise NotImplementedError("strong encryption (flag bit 6)")

    monkeypatch.setattr(zipfile.ZipFile, "open", _raising_open)
    with pytest.raises(guard.SnapshotArchiveRejected) as excinfo:
        with guard.admit_snapshot(path, data_dir=root):
            pass
    assert excinfo.value.reason == "member_flags_unsupported"
    assert "flag bit" not in str(excinfo.value)
    assert "encryption" not in str(excinfo.value)
    assert real_open is not None  # the real one is restored by monkeypatch


def test_malformed_deflate_data_during_the_header_read_is_refused(root):
    """`zlib.error` inherits from `Exception`, not `OSError`.

    The header read is bounded, but for a DEFLATED member those bounded bytes
    still go through the decompressor. Corrupt compressed data therefore raised
    `zlib.error`, which no other clause caught, and it escaped the guard with
    its own message.
    """
    members = schema_members(16)
    path = root / "v070_deflate.npz"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in members.items():
            archive.writestr(name, blob)

    # Corrupt the first member's compressed bytes in place, leaving every
    # directory structure intact so the failure lands in the decompressor.
    data = bytearray(path.read_bytes())
    local = data.find(b"PK\x03\x04")
    name_len = struct.unpack_from("<H", data, local + 26)[0]
    extra_len = struct.unpack_from("<H", data, local + 28)[0]
    body = local + 30 + name_len + extra_len
    data[body:body + 24] = b"\xff" * 24
    path.write_bytes(bytes(data))

    assert admit(path, root) == "member_header_unreadable"


def test_a_resolve_failure_is_refused_inside_the_typed_boundary(root, tmp_path):
    """`Path.resolve()` is not total: a symlink loop raises OSError(ELOOP).

    Uncaught it left the guard by a route with no reason code and with the path
    in the message. If the real path cannot be determined then confinement
    cannot be proved, so the fail-closed answer is the confinement refusal.
    """
    loop = root / "v070_loop.npz"
    other = root / "v070_loop_b.npz"
    try:
        loop.symlink_to(other)
        other.symlink_to(loop)
    except (OSError, NotImplementedError):  # pragma: no cover - platform gate
        pytest.skip("symlink creation is not permitted in this environment")

    reason = admit(loop, root)
    assert reason in {"path_not_confined", "path_not_regular_file"}
    assert str(tmp_path) not in reason


def test_a_resolve_failure_is_typed_even_when_injected(root, monkeypatch):
    """Platform-independent proof of the same boundary, so the contract is
    pinned on Windows runners too."""
    path = write_npz(root / "v070_resolve.npz", schema_members(16))
    real_resolve = Path.resolve

    def _failing_resolve(self, *args, **kwargs):
        raise OSError(40, "Too many levels of symbolic links", str(self))

    monkeypatch.setattr(Path, "resolve", _failing_resolve)
    with pytest.raises(guard.SnapshotArchiveRejected) as excinfo:
        with guard.admit_snapshot(path, data_dir=root):
            pass
    assert excinfo.value.reason == "path_not_confined"
    assert "symbolic" not in str(excinfo.value)
    assert "v070_resolve" not in str(excinfo.value)


@pytest.mark.parametrize("digits", ["١", "٤", "۸"], ids=["arabic_one",
                                                        "arabic_four",
                                                        "extended_eight"])
def test_a_non_ascii_digit_width_is_refused(root, digits):
    """A v3.0 header is decoded as UTF-8, and `\\d` matches the whole Unicode
    decimal-digit category — as does `int()`. So `<i١` parsed as a width of 1
    and was admitted, describing a dtype no NumPy can construct."""
    members = schema_members(16)
    # A one-byte payload. For `١` (=1) that makes the archive size-consistent,
    # so ONLY the dtype rule can refuse it -- and reverting the rule admits the
    # archive outright, which is what makes this case load-bearing. For `٤`
    # (=4) and `۸` (=8) the sizes do not line up and the refusal arrives as a
    # size mismatch instead; those two are breadth over the digit class, not
    # independent proofs of the rule.
    members["generation.npy"] = npy_bytes(
        "<i8", (), payload=b"\x00", version=(3, 0),
        header="{'descr': '<i%s', 'fortran_order': False, 'shape': (), }"
               % digits)
    path = write_npz(root / "v070_digit.npz", members)
    assert admit(path, root) == "member_dtype_unsupported"


def test_a_sixteen_byte_float_is_refused_portably(root):
    """`float128`/`longdouble` is not portable — NumPy 2.3.5 on Windows refuses
    `<f16` outright — and no snapshot member has ever used one. Admitting it
    would push the failure past the guard onto whichever consumer's NumPy
    cannot build it."""
    members = schema_members(16)
    members["best_fitness.npy"] = npy_bytes("<f16", (), payload=b"\x00" * 16)
    path = write_npz(root / "v070_f16.npz", members)
    assert admit(path, root) == "member_dtype_unsupported"
    assert 16 not in guard._FLOAT_WIDTHS


def test_the_zip64_central_directory_offset_sentinel_is_refused(root):
    """The offset field says "the real value is in the ZIP64 record" just as
    loudly as the counts do, so an archive can carry honest-looking counts and
    still redirect `zipfile` through ZIP64."""
    path = write_npz(root / "v070_z64off.npz", schema_members(16))
    data = bytearray(path.read_bytes())
    index = data.rfind(b"PK\x05\x06")
    struct.pack_into("<I", data, index + 16, 0xFFFFFFFF)
    path.write_bytes(bytes(data))
    assert admit(path, root) == "zip64_unsupported"


@pytest.mark.parametrize("field,offset", [
    ("entries_here", 8), ("entries_total", 10), ("directory_size", 12),
])
def test_every_central_zip64_sentinel_is_refused_as_zip64(root, field, offset):
    """All four report the same thing and now share one reason code; they used
    to be split between `member_count` and `zip64_unsupported`."""
    path = write_npz(root / ("v070_z64_%s.npz" % field), schema_members(16))
    data = bytearray(path.read_bytes())
    index = data.rfind(b"PK\x05\x06")
    if offset == 12:
        struct.pack_into("<I", data, index + offset, 0xFFFFFFFF)
    else:
        struct.pack_into("<H", data, index + offset, 0xFFFF)
    path.write_bytes(bytes(data))
    assert admit(path, root) == "zip64_unsupported"


@pytest.mark.parametrize("channels", [1, 2, 3, 4, 5, 6])
def test_a_memory_grid_below_seven_channels_is_refused(root, channels):
    """A floor, set at what the consumers actually read.

    Lucid indexes channel 6 and all three index channel 3, so a grid with
    fewer was admitted here and then raised `IndexError` downstream — inside
    the watcher, inside a route — which is the failure this guard exists to
    move forward of `np.load`. The documented 3- and 5-channel legacy forms are
    refused by this floor, and that is the right answer: no consumer migrates
    them, so those archives could only ever have crashed.
    """
    path = write_npz(root / ("v070_ch%d.npz" % channels),
                     schema_members(16, channels))
    assert admit(path, root) == "member_shape_invalid"


@pytest.mark.parametrize("channels", [7, 8])
def test_seven_and_eight_channel_grids_are_admitted(root, channels):
    """Seven, not exactly eight: requiring eight would refuse a grid every
    consumer could read."""
    path = write_npz(root / ("v070_ok%d.npz" % channels),
                     schema_members(16, channels))
    assert admit(path, root) is None


def test_the_channel_floor_matches_the_highest_index_any_consumer_reads():
    """Derivation, not a magic number: channel 6 is the highest index touched
    by any of the three consumers, so seven channels is the minimum."""
    assert guard.PRODUCTION_POLICY.min_memory_channels == 7
    sources = {
        "lucid_server": Path(guard.__file__).with_name("lucid_server.py"),
        "medusa_api": Path(guard.__file__).with_name("medusa_api.py"),
        "geometry_daemon": Path(guard.__file__).with_name("geometry_daemon.py"),
    }
    highest = -1
    for source in sources.values():
        for match in re.finditer(r"m(?:g|emory_grid)\[(\d+)",
                                 source.read_text(encoding="utf-8")):
            highest = max(highest, int(match.group(1)))
    assert highest == 6, "a consumer's channel indexing changed"
    assert guard.PRODUCTION_POLICY.min_memory_channels == highest + 1


def test_a_zero_channel_memory_grid_is_refused(root):
    members = schema_members(16)
    members["memory_grid.npy"] = npy_bytes("<f4", (0, 16, 16, 16))
    path = write_npz(root / "v070_nochan.npz", members)
    assert admit(path, root) == "member_shape_invalid"


def test_a_negative_dimension_is_refused(root):
    members = schema_members(16)
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16), payload=b"",
        header="{'descr': '|u1', 'fortran_order': False, "
               "'shape': (16, 16, -1), }")
    path = write_npz(root / "v070_neg.npz", members)
    assert admit(path, root) == "member_shape_invalid"


@pytest.mark.parametrize("header", [
    "{'descr': __import__('os').system, 'fortran_order': False, 'shape': (), }",
    "{'descr': '|u1', 'fortran_order': False, 'shape': (16, 16, 16)",
    "[]",
    "{'descr': '|u1', 'fortran_order': 0, 'shape': (16, 16, 16), }",
    "{'descr': '|u1', 'fortran_order': False, 'shape': 4096, }",
    "{'descr': '|u1', 'fortran_order': False, 'shape': (16, 16, 16), 'x': 1, }",
], ids=["call_expression", "unterminated", "not_a_dict", "non_bool_order",
        "non_tuple_shape", "extra_key"])
def test_header_texts_outside_the_accepted_grammar_are_refused(root, header):
    members = schema_members()
    members["lattice.npy"] = npy_bytes("|u1", (16, 16, 16), payload=b"",
                                       header=header)
    path = write_npz(root / "v070_grammar.npz", members)
    assert admit(path, root) == "member_header_malformed"


def test_a_deeply_nested_header_is_refused_without_recursion(root):
    """The literal parser caps depth itself rather than relying on the
    interpreter's recursion limit."""
    members = schema_members()
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16), payload=b"",
        header="{'descr': " + "(" * 200 + ")" * 200 + ", "
               "'fortran_order': False, 'shape': (16, 16, 16), }")
    path = write_npz(root / "v070_deep.npz", members)
    assert admit(path, root) == "member_header_malformed"


# ---------------------------------------------------------------------------
# Boundaries: limit-1, exactly the limit, limit+1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("edge,expected", [
    (0, "edge_out_of_range"),
    (8, "edge_out_of_range"),
    (15, "edge_out_of_range"),
    (24, "edge_not_multiple"),
    (40, "edge_not_multiple"),
    (257, "edge_out_of_range"),
    (272, "edge_out_of_range"),
    (512, "edge_out_of_range"),
])
def test_edge_rejections(root, edge, expected):
    """Declared-only fixtures: the geometry rule runs before the size
    arithmetic, so a 512-edge refusal costs kilobytes, not gigabytes."""
    path = write_npz(root / ("v070_edge%d.npz" % edge), declared_members(edge))
    assert admit(path, root) == expected


@pytest.mark.parametrize("edge,expected", [
    (2, "edge_out_of_range"),
    (4, None),
    (6, "edge_not_multiple"),
    (8, None),
    (12, "edge_out_of_range"),
])
def test_the_edge_rule_at_its_own_ceiling_under_a_scaled_policy(root, edge,
                                                                expected):
    """The production ceiling of 256 cannot be ADMITTED with a real archive
    without allocating 528 MiB. The identical rule is therefore exercised at a
    scaled ceiling, where minimum, maximum and multiple are all real
    boundaries and every fixture is a few hundred bytes."""
    policy = dataclasses.replace(guard.PRODUCTION_POLICY,
                                 min_edge=4, max_edge=8, edge_multiple=4)
    path = write_npz(root / ("v070_scaled%d.npz" % edge), schema_members(edge))
    assert admit(path, root, policy) == expected


def test_physical_ceiling_boundary(root):
    path = write_npz(root / "v070_phys.npz", schema_members(16))
    size = path.stat().st_size
    for limit, expected in ((size - 1, "archive_too_large"), (size, None),
                            (size + 1, None)):
        policy = dataclasses.replace(guard.PRODUCTION_POLICY,
                                     max_physical_bytes=limit)
        assert admit(path, root, policy) == expected, limit


def test_declared_aggregate_boundary(root):
    members = schema_members(16)
    path = write_npz(root / "v070_agg.npz", members)
    with zipfile.ZipFile(path) as archive:
        total = sum(info.file_size for info in archive.infolist())
    for limit, expected in ((total - 1, "archive_payload_total_too_large"),
                            (total, None), (total + 1, None)):
        policy = dataclasses.replace(guard.PRODUCTION_POLICY,
                                     max_total_declared_bytes=limit)
        assert admit(path, root, policy) == expected, limit


def test_member_payload_ceiling_boundary(root):
    """The lattice payload at edge 16 is exactly 4096 bytes. The ceiling is
    compared against the PAYLOAD, not the member's declared uncompressed size,
    which also covers the NPY header -- an archive sitting exactly on the limit
    must be admitted."""
    path = write_npz(root / "v070_pay.npz", schema_members(16))
    payload = 16 ** 3
    for limit, expected in ((payload - 1, "member_payload_too_large"),
                            (payload, None), (payload + 1, None)):
        policy = dataclasses.replace(
            guard.PRODUCTION_POLICY,
            members=tuple(
                dataclasses.replace(spec, max_payload_bytes=limit)
                if spec.role == guard.ROLE_LATTICE else spec
                for spec in guard.PRODUCTION_POLICY.members))
        assert admit(path, root, policy) == expected, limit


def test_header_ceiling_boundary(root):
    members = schema_members(16)
    path = write_npz(root / "v070_hdr.npz", members)
    longest = max(header_length(blob) for blob in members.values())
    for limit, expected in ((longest - 1, "member_header_too_large"),
                            (longest, None), (longest + 1, None)):
        policy = dataclasses.replace(guard.PRODUCTION_POLICY,
                                     max_header_bytes=limit)
        assert admit(path, root, policy) == expected, limit


def test_central_directory_ceiling_boundary(root):
    path = write_npz(root / "v070_cd.npz", schema_members(16))
    data = path.read_bytes()
    index = data.rfind(b"PK\x05\x06")
    directory_size = struct.unpack("<I", data[index + 12:index + 16])[0]
    for limit, expected in ((directory_size - 1, "central_directory_too_large"),
                            (directory_size, None), (directory_size + 1, None)):
        policy = dataclasses.replace(guard.PRODUCTION_POLICY,
                                     central_directory_max_bytes=limit)
        assert admit(path, root, policy) == expected, limit


@pytest.mark.parametrize("count,expected", [
    (guard.PRODUCTION_POLICY.max_members + guard._COUNT_PARSE_SLACK - 1,
     "member_unexpected"),
    (guard.PRODUCTION_POLICY.max_members + guard._COUNT_PARSE_SLACK,
     "member_unexpected"),
    (guard.PRODUCTION_POLICY.max_members + guard._COUNT_PARSE_SLACK + 1,
     "member_count"),
])
def test_entry_count_parse_bound_boundary(root, count, expected):
    """At the bound the archive still reaches the schema check and is refused
    for what it actually is; one entry beyond it, the coarse bound fires first
    and `ZipFile` is never asked to build the list."""
    members = schema_members(16)
    for index in range(count - len(members)):
        members["filler%d.npy" % index] = npy_bytes("|u1", (1,))
    path = write_npz(root / "v070_count.npz", members)
    assert admit(path, root) == expected


# ---------------------------------------------------------------------------
# One descriptor, opened once, rewound, closed on every path
# ---------------------------------------------------------------------------

@pytest.fixture
def opened_files(monkeypatch):
    """Record every file object the guard opens.

    Hooked on `os.fdopen`, not `builtins.open`: the guard opens through
    `os.open` so it can pass O_NONBLOCK and O_NOFOLLOW, which a plain `open()`
    cannot express. `os.fdopen` is what turns that descriptor into the file
    object the guard yields, so it is the exact seam.
    """
    records = []
    real_fdopen = os.fdopen

    def _tracking_fdopen(*args, **kwargs):
        handle = real_fdopen(*args, **kwargs)
        records.append(handle)
        return handle

    monkeypatch.setattr(os, "fdopen", _tracking_fdopen)
    return records


def test_the_archive_is_opened_exactly_once(root, opened_files):
    path = write_npz(root / "v070_once.npz", schema_members(16))
    with guard.admit_snapshot(path, data_dir=root) as handle:
        assert opened_files == [handle], (
            "a pathname must never be validated and then reopened for loading")


def test_the_yielded_descriptor_is_rewound_and_readable(root):
    path = write_npz(root / "v070_rewind.npz", schema_members(16))
    with guard.admit_snapshot(path, data_dir=root) as handle:
        assert handle.tell() == 0
        assert handle.readable() and not handle.closed
        assert handle.read(4) == b"PK\x03\x04"


def test_the_descriptor_is_closed_after_a_successful_block(root):
    path = write_npz(root / "v070_closed.npz", schema_members(16))
    with guard.admit_snapshot(path, data_dir=root) as handle:
        captured = handle
    assert captured.closed


def test_the_descriptor_is_closed_when_the_consumer_body_raises(root):
    path = write_npz(root / "v070_boom.npz", schema_members(16))
    captured = []

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with guard.admit_snapshot(path, data_dir=root) as handle:
            captured.append(handle)
            raise Boom
    assert captured[0].closed


@pytest.mark.parametrize("reason", ["member_missing", "member_dtype_object",
                                    "member_size_inconsistent"])
def test_the_descriptor_is_closed_when_preflight_refuses(root, tmp_path,
                                                         opened_files, reason):
    """Refusal happens after the open, so the handle must not be left behind."""
    path, policy = REFUSAL_CASES[reason](root, tmp_path)
    with pytest.raises(guard.SnapshotArchiveRejected):
        with guard.admit_snapshot(path, data_dir=root,
                                  policy=policy or guard.PRODUCTION_POLICY):
            pass
    assert opened_files, "the guard never opened the archive"
    assert all(handle.closed for handle in opened_files)


def test_nothing_is_opened_when_the_path_is_refused_before_the_open(root,
                                                                    tmp_path,
                                                                    opened_files):
    outside = tmp_path / "v070_outside.npz"
    write_npz(outside, schema_members())
    with pytest.raises(guard.SnapshotArchiveRejected):
        with guard.admit_snapshot(outside, data_dir=root):
            pass
    assert opened_files == []


# ---------------------------------------------------------------------------
# Safe candidate discovery
# ---------------------------------------------------------------------------

def _touch(path, mtime_ns):
    path.write_bytes(b"x")
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def test_newest_first_orders_by_modification_time(root):
    older = _touch(root / "v070_a.npz", 1_000_000_000)
    newer = _touch(root / "v070_b.npz", 3_000_000_000)
    middle = _touch(root / "v070_c.npz", 2_000_000_000)
    assert guard.newest_first([older, newer, middle]) == [newer, middle, older]


def test_newest_first_breaks_ties_deterministically(root):
    first = _touch(root / "v070_a.npz", 5_000_000_000)
    second = _touch(root / "v070_b.npz", 5_000_000_000)
    forward = guard.newest_first([first, second])
    backward = guard.newest_first([second, first])
    assert forward == backward, "the order depends on how the glob happened to yield"
    assert set(forward) == {first, second}


def test_newest_first_silently_skips_an_entry_that_disappeared(root):
    present = _touch(root / "v070_here.npz", 1_000_000_000)
    missing = root / "v070_gone.npz"
    assert not missing.exists()
    assert guard.newest_first([missing, present]) == [present]


def test_newest_first_skips_a_whole_directory_of_vanished_entries(root):
    """No exception, no partial result, nothing printed — there is nothing to
    report about an entry that is simply gone."""
    ghosts = [root / ("v070_ghost%d.npz" % i) for i in range(5)]
    assert guard.newest_first(ghosts) == []


def test_newest_first_keeps_a_broken_symlink_as_a_candidate(root):
    """`lstat` succeeds on a dangling link, and that is the point: it reaches
    the guard and is refused with a typed reason instead of vanishing from
    selection and letting an older archive be served with no record of why."""
    dangling = root / "v070_dangling.npz"
    try:
        dangling.symlink_to(root / "v070_absent_target.npz")
    except (OSError, NotImplementedError):  # pragma: no cover - platform gate
        pytest.skip("symlink creation is not permitted in this environment")
    assert guard.newest_first([dangling]) == [dangling]
    assert admit(dangling, root) == "path_not_regular_file"


def test_newest_first_does_not_follow_a_symlink_for_its_ordering(root, tmp_path):
    """A link must not be able to borrow its target's modification time to
    promote itself to "newest" — that is ordering deciding admission's question
    before admission is asked."""
    target = tmp_path / "outside_target.npz"
    _touch(target, 9_000_000_000)
    link = root / "v070_link.npz"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform gate
        pytest.skip("symlink creation is not permitted in this environment")
    os.utime(link, ns=(1_000_000_000, 1_000_000_000), follow_symlinks=False)

    real = _touch(root / "v070_real.npz", 5_000_000_000)
    ordered = guard.newest_first([link, real])
    assert ordered[0] == real, "the link borrowed its target's mtime"


def test_entry_fingerprint_describes_the_entry_and_raises_when_gone(root):
    present = _touch(root / "v070_fp.npz", 4_000_000_000)
    name, size, mtime = guard.entry_fingerprint(present)
    assert name == os.fspath(present)
    assert size == 1 and mtime == 4_000_000_000

    with pytest.raises(OSError):
        guard.entry_fingerprint(root / "v070_never_existed.npz")


def test_entry_fingerprint_is_non_following(root, tmp_path):
    target = tmp_path / "fp_target.npz"
    target.write_bytes(b"much larger contents")
    link = root / "v070_fplink.npz"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # pragma: no cover - platform gate
        pytest.skip("symlink creation is not permitted in this environment")
    assert guard.entry_fingerprint(link)[1] != target.stat().st_size, (
        "the fingerprint described the target, so touching the target would "
        "make a rejected link look changed and be retried every poll")


# ---------------------------------------------------------------------------
# Policy shape
# ---------------------------------------------------------------------------

def test_the_production_policy_is_immutable_and_named():
    with pytest.raises(dataclasses.FrozenInstanceError):
        guard.PRODUCTION_POLICY.max_members = 6
    with pytest.raises(dataclasses.FrozenInstanceError):
        guard.PRODUCTION_POLICY.members[0].max_payload_bytes = 1


def test_the_production_limits_are_the_calibrated_ones():
    policy = guard.PRODUCTION_POLICY
    assert policy.max_members == 5
    assert policy.max_header_bytes == 4 * 1024
    assert policy.max_total_declared_bytes == 529 * 1024 * 1024
    assert policy.max_physical_bytes == 544 * 1024 * 1024
    assert (policy.min_edge, policy.max_edge, policy.edge_multiple) == (16, 256, 16)
    caps = {spec.name: spec.max_payload_bytes for spec in policy.members}
    assert caps["lattice"] == 16 * 1024 * 1024
    assert caps["memory_grid"] == 512 * 1024 * 1024
    assert set(caps) == {"lattice", "memory_grid", "generation", "ca_step",
                         "best_fitness"}


def test_the_limits_are_calibrated_to_the_compatibility_ceiling():
    """256³ uint8 is exactly the lattice ceiling and 8 x 256³ float32 is
    exactly the memory-grid ceiling, so the numbers are derived rather than
    guessed -- and their sum is below the aggregate ceiling, which is why the
    aggregate can only bind under a widened policy."""
    policy = guard.PRODUCTION_POLICY
    caps = {spec.name: spec.max_payload_bytes for spec in policy.members}
    assert caps["lattice"] == policy.max_edge ** 3 * 1
    assert caps["memory_grid"] == 8 * policy.max_edge ** 3 * 4
    assert (caps["lattice"] + caps["memory_grid"]
            < policy.max_total_declared_bytes < policy.max_physical_bytes)


def test_no_compression_ratio_threshold_exists(root):
    """A legitimate snapshot is mostly void and compresses enormously. A ratio
    rule would refuse real inputs, so there must not be one -- witnessed by a
    genuinely extreme ratio being admitted."""
    path = write_npz(root / "v070_sparse.npz", schema_members(64))
    with zipfile.ZipFile(path) as archive:
        declared = sum(info.file_size for info in archive.infolist())
        physical = sum(info.compress_size for info in archive.infolist())
    assert declared / max(physical, 1) > 100, "the sparse control is not sparse"
    assert admit(path, root) is None


def test_a_high_entropy_archive_is_admitted_too(root):
    """The mirror control: an archive that does not compress at all is equally
    admissible, so admission is not keyed on compressibility in either
    direction."""
    members = schema_members(16)
    members["lattice.npy"] = npy_bytes(
        "|u1", (16, 16, 16), payload=os.urandom(16 ** 3))
    path = write_npz(root / "v070_entropy.npz", members)
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("lattice.npy")
        assert info.compress_size > info.file_size * 0.9, "not high-entropy"
    assert admit(path, root) is None


# ---------------------------------------------------------------------------
# The module's own construction
# ---------------------------------------------------------------------------

def _guard_source():
    return Path(guard.__file__).read_text(encoding="utf-8")


def _called_attribute_names(tree):
    return {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _called_plain_names(tree):
    return {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize("banned", ["extract", "extractall", "testzip"])
def test_the_guard_never_extracts(banned):
    """Extraction would write attacker-named paths and materialise payloads;
    the guard reads bounded prefixes of member streams instead."""
    assert banned not in _called_attribute_names(ast.parse(_guard_source()))


@pytest.mark.parametrize("banned", ["eval", "exec", "compile", "literal_eval"])
def test_the_guard_never_evaluates_header_text_by_bare_name(banned):
    assert banned not in _called_plain_names(ast.parse(_guard_source()))


@pytest.mark.parametrize("banned", ["eval", "exec", "literal_eval"])
def test_the_guard_never_evaluates_header_text_through_a_module(banned):
    """`re.compile` is legitimate and deliberately not on this list; what is
    banned is anything that would turn header text into code."""
    assert banned not in _called_attribute_names(ast.parse(_guard_source()))


def test_the_construction_scanners_can_see_a_planted_call():
    """Anti-vacuity: the two scanners above would catch what they claim to."""
    planted = ast.parse("import ast\nz.extractall('x')\nast.literal_eval('1')\n"
                        "eval('1')\n")
    assert "extractall" in _called_attribute_names(planted)
    assert "literal_eval" in _called_attribute_names(planted)
    assert "eval" in _called_plain_names(planted)


def test_the_guard_uses_no_numpy_and_no_private_numpy_parser():
    """It runs before NumPy is involved at all, so it must not import NumPy or
    reach into its private format helpers."""
    source = _guard_source()
    assert "import numpy" not in source and "__import__" not in source
    assert "read_magic" not in source and "read_array_header" not in source
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    # `threading` and `time` are the shared discovery cache's lock and its
    # monotonic clock. Both are standard library, neither pulls in NumPy, and
    # the property this control exists for -- the guard runs before NumPy is
    # involved at all -- is unchanged.
    assert imported <= {"__future__", "ast", "contextlib", "dataclasses",
                        "enum", "fnmatch", "os", "re", "stat", "struct",
                        "threading", "time", "zipfile", "zlib", "pathlib",
                        "typing"}
    # `ast` is imported for `ast.parse` only — a syntax gate, never an
    # evaluator. The bans on eval/exec/literal_eval are asserted separately.


# ---------------------------------------------------------------------------
# Real NumPy archives: compatibility of admitted inputs
# ---------------------------------------------------------------------------

def _numpy_snapshot(path, edge=16, channels=8, compressed=True):
    writer = np.savez_compressed if compressed else np.savez
    writer(
        path,
        lattice=np.zeros((edge, edge, edge), dtype=np.uint8),
        memory_grid=np.zeros((channels, edge, edge, edge), dtype=np.float32),
        generation=np.int64(1234),
        ca_step=np.int64(99),
        best_fitness=np.float64(0.875),
    )
    return Path(str(path) + ".npz") if not str(path).endswith(".npz") else Path(path)


@requires_numpy
@pytest.mark.parametrize("compressed", [True, False], ids=["compressed", "stored"])
def test_a_real_numpy_snapshot_is_admitted_and_loads(root, compressed):
    path = _numpy_snapshot(root / "v070_gen001234.npz", 64, compressed=compressed)
    with guard.admit_snapshot(path, data_dir=root) as handle:
        with np.load(handle, allow_pickle=False) as archive:
            assert archive["lattice"].shape == (64, 64, 64)
            assert archive["memory_grid"].shape == (8, 64, 64, 64)
            assert int(archive["generation"]) == 1234
            assert int(archive["ca_step"]) == 99
            assert float(archive["best_fitness"]) == 0.875


@requires_numpy
def test_numpy_loads_from_the_very_descriptor_that_was_preflighted(root):
    """Not an equivalent path, not a reopen: the same object.

    `NpzFile` keeps the file it was handed on its `ZipFile`, so identity is
    observable rather than inferred.
    """
    path = _numpy_snapshot(root / "v070_identity.npz")
    with guard.admit_snapshot(path, data_dir=root) as handle:
        with np.load(handle, allow_pickle=False) as archive:
            assert archive.zip.fp is handle


@requires_numpy
def test_the_descriptor_survives_the_archive_close_and_is_closed_after(root):
    """The archive's close must not take the guard's descriptor with it while
    the block is still running, and the descriptor must be gone afterwards."""
    path = _numpy_snapshot(root / "v070_lifetime.npz")
    with guard.admit_snapshot(path, data_dir=root) as handle:
        with np.load(handle, allow_pickle=False) as archive:
            archive["lattice"]
        assert archive.zip is None, "the archive was not closed"
        assert not handle.closed, "the archive's close took the descriptor with it"
    assert handle.closed


@requires_numpy
def test_a_missing_key_after_admission_still_fails_the_way_it_always_did(root):
    """Admission does not take over downstream failures."""
    path = _numpy_snapshot(root / "v070_key.npz")
    with pytest.raises(KeyError):
        with guard.admit_snapshot(path, data_dir=root) as handle:
            with np.load(handle, allow_pickle=False) as archive:
                archive["not_a_member"]


@requires_numpy
def test_the_descriptor_is_closed_when_a_load_inside_the_block_raises(root):
    path = _numpy_snapshot(root / "v070_loadfail.npz")
    captured = []
    with pytest.raises(KeyError):
        with guard.admit_snapshot(path, data_dir=root) as handle:
            captured.append(handle)
            with np.load(handle, allow_pickle=False) as archive:
                archive["absent"]
    assert captured[0].closed


@requires_numpy
def test_a_pickled_member_cannot_even_reach_numpy(root, tmp_path):
    """The pickle refusal in each consumer stays in place, but an object member
    no longer gets that far: admission refuses it from the header."""
    class _Payload:
        def __reduce__(self):
            raise AssertionError("this must never be pickled or unpickled")

    members = schema_members(16)
    members["generation.npy"] = npy_bytes("|O", (), payload=b"")
    path = write_npz(root / "v070_pickled.npz", members)
    assert admit(path, root) == "member_dtype_object"


def _archive_with_short_payload(path, member, drop):
    """A schema-perfect archive whose `member` stores fewer bytes than it declares.

    Built rather than cut. Deleting bytes from a finished archive would shift
    every offset after them and leave the central directory pointing at the
    wrong places, so the archive would be refused as malformed and the test
    would prove nothing.

    Here the member's declared uncompressed size stays FULL while its stored
    bytes are short, and its CRC matches the bytes actually present -- so
    `zipfile` has nothing to object to, preflight admits it (preflight reads
    headers, not payloads, and the header's arithmetic still agrees with the
    declared `file_size`), and the shortfall only surfaces when NumPy
    materialises the array and reads past the end.
    """
    plain = schema_members(16)
    built = {}
    for name, blob in plain.items():
        if name == member:
            short = blob[:-drop]
            built[name] = (short, blob, zipfile.ZIP_STORED,
                           zlib.crc32(short) & 0xFFFFFFFF)
        else:
            built[name] = (blob, blob, zipfile.ZIP_STORED)
    return _zip_with_raw_members(path, built)


@requires_numpy
def test_a_truncated_payload_becomes_member_payload_unreadable(root):
    """The real NumPy path, end to end.

    An otherwise schema-perfect, CRC-correct archive whose stored payload ends
    early. Preflight admits it — it reads headers, not payloads — and NumPy
    raises its truncated-read `ValueError` from `_read_bytes` during array
    materialisation. That must arrive as the typed refusal, not as a raw
    `ValueError` past every consumer's handler.
    """
    path = _archive_with_short_payload(root / "v070_truncated.npz",
                                       "memory_grid.npy", 4096)
    assert admit(path, root) is None, "the fixture must preflight clean"

    with pytest.raises(guard.SnapshotArchiveRejected) as excinfo:
        with guard.admit_snapshot(path, data_dir=root) as handle:
            with np.load(handle, allow_pickle=False) as archive:
                archive["memory_grid"]
    assert excinfo.value.reason == "member_payload_unreadable"
    assert str(excinfo.value) == "member_payload_unreadable"


@requires_numpy
def test_the_descriptor_is_closed_after_a_truncated_payload_refusal(root,
                                                                    opened_files):
    path = _archive_with_short_payload(root / "v070_trunc_close.npz",
                                       "memory_grid.npy", 4096)
    with pytest.raises(guard.SnapshotArchiveRejected):
        with guard.admit_snapshot(path, data_dir=root) as handle:
            with np.load(handle, allow_pickle=False) as archive:
                archive["memory_grid"]
    assert opened_files, "the guard never opened the archive"
    assert all(handle.closed for handle in opened_files)


@requires_numpy
def test_a_manual_value_error_with_the_identical_message_is_not_translated(root):
    """The control that makes the translation meaningful: the same words, from
    a frame that is not NumPy's reader, must pass straight through."""
    path = write_npz(root / "v070_manual.npz", schema_members(16))
    message = "EOF: reading array data, expected 512 bytes got 100"
    with pytest.raises(ValueError) as excinfo:
        with guard.admit_snapshot(path, data_dir=root):
            raise ValueError(message)
    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == message


@requires_numpy
def test_a_numpy_scalar_conversion_failure_is_not_translated(root):
    """An ordinary downstream conversion failure keeps its own identity.

    Stated exactly, because the obvious guess is wrong: `int()` on a
    multi-element array raises `TypeError` ("only 0-dimensional arrays can be
    converted to Python scalars"), not `ValueError`. The property under test is
    that it passes through untouched, whatever its type -- so the assertion
    names the type NumPy actually raises rather than the one that would have
    been convenient.
    """
    path = write_npz(root / "v070_scalar.npz", schema_members(16))
    with pytest.raises(TypeError) as excinfo:
        with guard.admit_snapshot(path, data_dir=root) as handle:
            with np.load(handle, allow_pickle=False) as archive:
                int(archive["lattice"])
    assert type(excinfo.value) is TypeError
    assert not isinstance(excinfo.value, guard.SnapshotArchiveRejected)


@requires_numpy
def test_a_value_error_from_the_consumers_own_conversion_is_not_translated(root):
    """The `ValueError` half of the same property, on the lane that matters.

    `member_payload_unreadable` is reached through a `ValueError` clause, so a
    `ValueError` raised by the caller's own conversion code inside the block is
    the case most at risk of being swallowed.
    """
    path = write_npz(root / "v070_convert.npz", schema_members(16))
    with pytest.raises(ValueError) as excinfo:
        with guard.admit_snapshot(path, data_dir=root) as handle:
            with np.load(handle, allow_pickle=False) as archive:
                archive["generation"]
                int("not a number")
    assert type(excinfo.value) is ValueError
    assert not isinstance(excinfo.value, guard.SnapshotArchiveRejected)


@requires_numpy
def test_admitted_producer_shapes_match_what_the_engine_writes(root):
    """The schema this guard admits is the schema `_save_snapshot` emits:
    five members, those five names, those five forms."""
    path = _numpy_snapshot(root / "v070_producer.npz", 64)
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == [
            "best_fitness.npy", "ca_step.npy", "generation.npy",
            "lattice.npy", "memory_grid.npy",
        ]
    assert admit(path, root) is None


# ===========================================================================
# Bounded snapshot-discovery primitive
#
# `discover_snapshot_candidates` owns its own `os.scandir` so that the work of
# LOOKING for candidates is bounded, which nothing downstream can do: by the
# time `order_candidates` receives an iterable the whole directory has already
# been materialised -- `glob.glob` is `list(iglob(...))`, and even `iglob`
# reaches `_listdir`, which is `return list(it)`.
#
# The primitive itself stays calibration-free: it has no policy default, and
# every test in THIS section injects tiny explicit limits, which is what makes
# the boundary work independent of whatever production later chooses.
# `SnapshotArchivePolicy` / `PRODUCTION_POLICY` remain untouched by it.
#
# Production now consumes it through the one calibrated
# `PRODUCTION_DISCOVERY_POLICY` and the shared single-flight cache; both are
# pinned in their own section further down.
#
# Directory contents come from a deterministic fake `scandir` context manager
# yielding proxy entries. Built-in `os.DirEntry.stat` is deliberately not
# patched: a proxy keeps the metadata-call count and failure point explicit.
# ===========================================================================


class _ProxyStat:
    def __init__(self, mtime_ns, size):
        self.st_mtime_ns = mtime_ns
        self.st_size = size


class _ProxyEntry:
    """One directory entry, with recorded metadata access."""

    def __init__(self, name, mtime_ns=1000, size=64, stat_error=None):
        self.name = name
        self._stat = _ProxyStat(mtime_ns, size)
        self._stat_error = stat_error
        self._recorder = None

    def stat(self, *, follow_symlinks=True):
        if self._recorder is not None:
            self._recorder.stat_calls.append((self.name, follow_symlinks))
        if self._stat_error is not None:
            raise self._stat_error
        return self._stat


class _FakeScandir:
    """A recording stand-in for `os.scandir`.

    Records every entry YIELDED -- distinct from processed -- every `stat` call
    with its `follow_symlinks` argument, and whether the iterator was closed.
    """

    def __init__(self, entries, open_error=None, iteration_error_after=None,
                 iteration_error=None):
        self.entries = list(entries)
        self.open_error = open_error
        self.iteration_error_after = iteration_error_after
        self.iteration_error = iteration_error or OSError(
            5, "Input/output error")
        self.yielded = []
        self.stat_calls = []
        self.closed = 0
        self.opened_with = []
        for entry in self.entries:
            entry._recorder = self

    def __call__(self, directory):
        self.opened_with.append(directory)
        if self.open_error is not None:
            raise self.open_error
        return self

    def __enter__(self):
        return self._iterate()

    def __exit__(self, *exc):
        self.closed += 1
        return False

    def _iterate(self):
        for index, entry in enumerate(self.entries):
            if (self.iteration_error_after is not None
                    and index == self.iteration_error_after):
                raise self.iteration_error
            self.yielded.append(entry.name)
            yield entry


def _entries(count, start=0, stat_error=None):
    return [_ProxyEntry("v070_gen%06d_step000001_x.npz" % (start + i),
                        stat_error=stat_error)
            for i in range(count)]


def _install(monkeypatch, fake):
    monkeypatch.setattr(guard.os, "scandir", fake)
    return fake


def _policy(entries, candidates):
    return guard.CandidateDiscoveryPolicy(max_directory_entries=entries,
                                          max_candidates=candidates)


def _discover(directory, policy):
    return guard.discover_snapshot_candidates(directory, policy=policy)


# -- policy validation --------------------------------------------------------

@pytest.mark.parametrize("field", ["max_directory_entries", "max_candidates"])
@pytest.mark.parametrize("value", [0, -1, -100, 1.5, "8", None, True, False],
                         ids=["zero", "minus_one", "minus_hundred", "float",
                              "str", "none", "true", "false"])
def test_an_invalid_discovery_cap_is_refused(field, value):
    """`True` is an `int` to Python and would silently become a cap of 1, so
    booleans are rejected explicitly rather than by an `isinstance` that
    happens to accept them."""
    kwargs = {"max_directory_entries": 10, "max_candidates": 5}
    kwargs[field] = value
    with pytest.raises(ValueError):
        guard.CandidateDiscoveryPolicy(**kwargs)


def test_a_valid_discovery_policy_is_frozen():
    policy = _policy(10, 5)
    assert policy.max_directory_entries == 10 and policy.max_candidates == 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.max_candidates = 6


def test_the_discovery_policy_is_separate_from_the_archive_policy():
    """This tranche must not alter admission: `SnapshotArchivePolicy` and
    `PRODUCTION_POLICY` keep exactly the fields they had."""
    assert not hasattr(guard.PRODUCTION_POLICY, "max_directory_entries")
    assert not hasattr(guard.PRODUCTION_POLICY, "max_candidates")
    assert guard.CandidateDiscoveryPolicy is not guard.SnapshotArchivePolicy


def test_discovery_requires_an_explicit_policy(root):
    """Group 1 must not smuggle in an uncalibrated production default."""
    with pytest.raises(TypeError):
        guard.discover_snapshot_candidates(root)


# -- caps: boundary and one beyond -------------------------------------------

def test_exactly_the_entry_cap_succeeds(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(10)))
    result = _discover(root, _policy(10, 100))
    assert isinstance(result, guard.DiscoverySucceeded)
    assert result.processed == 10 and result.matched == 10
    assert len(result.ordered) == 10


def test_one_past_the_entry_cap_fails_closed(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(11)))
    result = _discover(root, _policy(10, 100))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED
    assert result.processed == 10
    assert not hasattr(result, "ordered"), (
        "a failure must not carry a partial prefix at all")


def test_exactly_the_candidate_cap_succeeds(root, monkeypatch):
    entries = _entries(5) + [_ProxyEntry("noise%d.txt" % i) for i in range(5)]
    _install(monkeypatch, _FakeScandir(entries))
    result = _discover(root, _policy(100, 5))
    assert isinstance(result, guard.DiscoverySucceeded)
    assert result.matched == 5 and result.processed == 10


def test_one_past_the_candidate_cap_fails_closed(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(6)))
    result = _discover(root, _policy(100, 5))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED
    assert result.matched_so_far == 5


def test_entry_limit_precedes_candidate_limit_when_both_are_exhausted(
        root, monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_entries(2)))
    result = _discover(root, _policy(1, 1))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED
    assert result.processed == 1 and result.matched_so_far == 1
    assert len(fake.yielded) == 2 and len(fake.stat_calls) == 1


# -- processed versus yielded, and the unstatted overflow entry --------------

def test_processed_is_bounded_and_yields_allow_one_look_ahead(root, monkeypatch):
    """Exact-boundary admission has to SEE the entry that would exceed the cap
    in order to refuse at exactly the cap, so the iterator yields at most one
    more than it processes. Both bounds are asserted, because conflating them
    would hide either an off-by-one or an unbounded scan."""
    fake = _install(monkeypatch, _FakeScandir(_entries(50)))
    result = _discover(root, _policy(10, 100))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.processed == 10
    assert len(fake.yielded) <= 10 + 1
    assert len(fake.yielded) == 11, "expected exactly one look-ahead"


def test_the_overflow_causing_entry_is_never_statted(root, monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_entries(6)))
    result = _discover(root, _policy(100, 5))
    assert isinstance(result, guard.DiscoveryFailed)
    assert len(fake.stat_calls) == 5
    statted = set(name for name, _ in fake.stat_calls)
    assert fake.yielded[5] not in statted


def test_the_entry_limit_look_ahead_is_never_statted(root, monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_entries(11)))
    result = _discover(root, _policy(10, 100))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED
    assert len(fake.stat_calls) == 10
    statted = set(name for name, _ in fake.stat_calls)
    assert fake.yielded[10] not in statted


def test_metadata_calls_are_bounded_by_the_candidate_cap(root, monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_entries(500)))
    result = _discover(root, _policy(10000, 20))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED
    assert len(fake.stat_calls) == 20


# -- floods -------------------------------------------------------------------

def test_a_flood_of_matching_names_bounds_metadata_calls(root, monkeypatch):
    fake = _install(monkeypatch, _FakeScandir(_entries(5000)))
    result = _discover(root, _policy(100000, 25))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED
    assert len(fake.stat_calls) == 25


def test_a_flood_of_nonmatching_names_cannot_make_the_scan_unbounded(root,
                                                                     monkeypatch):
    """The refutation of "just take the first N matches", made executable:
    non-matching entries are cheap individually and unbounded in aggregate, so
    the ENTRY cap must exist independently of the candidate cap. Zero metadata
    calls, because nothing matched."""
    noise = [_ProxyEntry("unrelated-%d.log" % i) for i in range(5000)]
    fake = _install(monkeypatch, _FakeScandir(noise))
    result = _discover(root, _policy(64, 25))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED
    assert result.processed == 64
    assert len(fake.stat_calls) == 0


# -- failure modes ------------------------------------------------------------

def test_a_missing_directory_is_successful_empty_discovery(root, monkeypatch):
    """Preserved from current behaviour: `Path.glob` on a missing directory
    yields nothing rather than raising, and consumers answer "no snapshots".
    Turning that into a fault would change a 404 into a 503."""
    _install(monkeypatch, _FakeScandir(
        [], open_error=FileNotFoundError(2, "No such file or directory")))
    result = _discover(root, _policy(10, 5))
    assert isinstance(result, guard.DiscoverySucceeded)
    assert result.ordered == () and result.matched == 0


def test_a_not_a_directory_error_is_also_successful_empty(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(
        [], open_error=NotADirectoryError(20, "Not a directory")))
    assert isinstance(_discover(root, _policy(10, 5)), guard.DiscoverySucceeded)


def test_another_open_error_is_a_directory_open_failure(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(
        [], open_error=PermissionError(13, "Permission denied")))
    result = _discover(root, _policy(10, 5))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.DIRECTORY_OPEN_FAILED


def test_an_error_after_iteration_begins_is_an_iteration_failure(root,
                                                                 monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(10), iteration_error_after=4))
    result = _discover(root, _policy(100, 100))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.ITERATION_FAILED
    assert result.processed == 4


@pytest.mark.parametrize("error", [
    FileNotFoundError(2, "gone during iteration"),
    NotADirectoryError(20, "changed during iteration"),
])
def test_missing_or_changed_mid_iteration_is_not_successful_empty(
        root, monkeypatch, error):
    _install(monkeypatch, _FakeScandir(
        _entries(5), iteration_error_after=2, iteration_error=error))
    result = _discover(root, _policy(100, 100))
    assert isinstance(result, guard.DiscoveryFailed)
    assert result.reason is guard.DiscoveryFailureReason.ITERATION_FAILED
    assert result.processed == 2


def test_a_reason_carries_no_path_or_exception_text(root, monkeypatch):
    _install(monkeypatch, _FakeScandir([], open_error=PermissionError(
        13, "Permission denied", "/attacker/chosen/LEAKNAME")))
    result = _discover(root, _policy(10, 5))
    text = result.reason.value + " " + repr(result)
    assert "LEAKNAME" not in text and "Permission" not in text


@pytest.mark.parametrize("lane", ["iteration", "metadata"])
def test_iteration_and_metadata_oserrors_are_also_sanitized(root, monkeypatch,
                                                             lane):
    error = OSError(5, "LEAKNAME /attacker/chosen/path")
    if lane == "iteration":
        fake = _FakeScandir(
            _entries(2), iteration_error_after=1, iteration_error=error)
    else:
        fake = _FakeScandir([_ProxyEntry(
            "v070_gen000001_LEAKNAME.npz", stat_error=error)])
    _install(monkeypatch, fake)
    result = _discover(root, _policy(10, 5))
    assert "LEAKNAME" not in repr(result)
    assert "/attacker/chosen/path" not in repr(result)


@pytest.mark.parametrize("error_type", [
    MemoryError, KeyboardInterrupt, RuntimeError, TypeError,
])
@pytest.mark.parametrize("lane", ["open", "iteration", "metadata"])
def test_non_oserrors_propagate_unchanged(root, monkeypatch, lane, error_type):
    error = error_type("programmer-or-system-fault")
    if lane == "open":
        fake = _FakeScandir([], open_error=error)
    elif lane == "iteration":
        fake = _FakeScandir(
            _entries(2), iteration_error_after=1, iteration_error=error)
    else:
        fake = _FakeScandir([_ProxyEntry(
            "v070_gen000001_step1_x.npz", stat_error=error)])
    _install(monkeypatch, fake)
    with pytest.raises(error_type, match="programmer-or-system-fault"):
        _discover(root, _policy(10, 5))


# -- partial discard and closure ---------------------------------------------

@pytest.mark.parametrize("build", [
    lambda: _FakeScandir([
        _ProxyEntry("noise-%d.txt" % i) for i in range(11)]),
    lambda: _FakeScandir(_entries(20)),
    lambda: _FakeScandir(_entries(10), iteration_error_after=6),
], ids=["entry_overflow", "candidate_overflow", "iteration_error"])
def test_every_failure_discards_the_partial_prefix(root, monkeypatch, build):
    _install(monkeypatch, build())
    result = _discover(root, _policy(10, 8))
    assert isinstance(result, guard.DiscoveryFailed)
    assert not hasattr(result, "ordered")
    retained = [v for v in dataclasses.asdict(result).values()
                if isinstance(v, (list, tuple)) and v]
    assert retained == [], "a failure must not retain candidates in any field"


def test_a_failure_has_only_fixed_reason_and_integer_counters(root,
                                                              monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(6)))
    result = _discover(root, _policy(100, 5))
    assert tuple(field.name for field in dataclasses.fields(result)) == (
        "reason", "processed", "matched_so_far", "unreadable")
    assert isinstance(result.reason, guard.DiscoveryFailureReason)
    assert all(type(value) is int for value in (
        result.processed, result.matched_so_far, result.unreadable))
    assert not any(isinstance(value, (Path, list, tuple, set, dict, BaseException))
                   for value in dataclasses.asdict(result).values())


def test_impossible_success_results_are_refused(root):
    valid = dict(ordered=(root / "v070_gen1.npz",), unreadable=0,
                 processed=1, matched=1)
    invalid = [
        {**valid, "ordered": [root / "v070_gen1.npz"]},
        {**valid, "ordered": (str(root / "v070_gen1.npz"),)},
        {**valid, "unreadable": -1},
        {**valid, "processed": 0},
        {**valid, "matched": 2},
        {**valid, "processed": True},
    ]
    for kwargs in invalid:
        with pytest.raises(ValueError):
            guard.DiscoverySucceeded(**kwargs)


def test_impossible_failure_results_are_refused():
    reason = guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED
    valid = dict(reason=reason, processed=2, matched_so_far=1,
                 unreadable=0)
    invalid = [
        {**valid, "reason": "entry_limit_exceeded"},
        {**valid, "processed": -1},
        {**valid, "matched_so_far": 3},
        {**valid, "unreadable": 2},
        {**valid, "unreadable": False},
    ]
    for kwargs in invalid:
        with pytest.raises(ValueError):
            guard.DiscoveryFailed(**kwargs)


@pytest.mark.parametrize("build", [
    lambda: _FakeScandir(_entries(3)),
    lambda: _FakeScandir(_entries(50)),
    lambda: _FakeScandir(_entries(10), iteration_error_after=2),
], ids=["success", "overflow", "iteration_error"])
def test_the_iterator_is_closed_on_every_exit(root, monkeypatch, build):
    fake = _install(monkeypatch, build())
    _discover(root, _policy(10, 8))
    assert fake.closed == 1


# -- unreadable entries -------------------------------------------------------

def test_an_unreadable_candidate_is_counted_and_skipped(root, monkeypatch):
    entries = _entries(3) + [_ProxyEntry(
        "v070_gen000009_step1_x.npz",
        stat_error=FileNotFoundError(2, "gone"))]
    _install(monkeypatch, _FakeScandir(entries))
    result = _discover(root, _policy(100, 100))
    assert isinstance(result, guard.DiscoverySucceeded)
    assert result.unreadable == 1
    assert result.matched == 4 and len(result.ordered) == 3


def test_all_matching_candidates_unreadable_is_an_explicit_property(root,
                                                                    monkeypatch):
    entries = _entries(4, stat_error=FileNotFoundError(2, "gone"))
    _install(monkeypatch, _FakeScandir(entries))
    result = _discover(root, _policy(100, 100))
    assert isinstance(result, guard.DiscoverySucceeded)
    assert result.ordered == ()
    assert result.all_matching_unreadable is True


def test_a_genuinely_empty_directory_is_not_all_unreadable(root, monkeypatch):
    """The distinction a consumer needs: nothing to read is not the same as
    nothing being readable."""
    _install(monkeypatch, _FakeScandir([]))
    result = _discover(root, _policy(10, 5))
    assert result.ordered == () and result.all_matching_unreadable is False


# -- input normalisation, output type ----------------------------------------

def test_a_string_and_a_path_directory_are_equivalent(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(3)))
    from_path = _discover(root, _policy(100, 100))
    _install(monkeypatch, _FakeScandir(_entries(3)))
    from_str = _discover(str(root), _policy(100, 100))
    assert ([p.name for p in from_path.ordered]
            == [p.name for p in from_str.ordered])
    assert all(isinstance(p, Path) for p in from_str.ordered)


def test_every_candidate_is_a_path_under_the_requested_directory(root,
                                                                  monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(3)))
    result = _discover(str(root), _policy(100, 100))
    for candidate in result.ordered:
        assert isinstance(candidate, Path)
        assert candidate.parent == Path(root)


def test_the_ordered_candidates_are_immutable(root, monkeypatch):
    _install(monkeypatch, _FakeScandir(_entries(3)))
    result = _discover(root, _policy(100, 100))
    assert isinstance(result.ordered, tuple)


def test_real_scandir_smoke_and_handle_closure(root):
    data_dir = root / "real-scandir"
    data_dir.mkdir()
    first = data_dir / "v070_gen000001_step1_x.npz"
    second = data_dir / "v070_gen000002_step1_x.npz"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    (data_dir / "noise.txt").write_bytes(b"noise")

    result = _discover(data_dir, _policy(10, 5))
    assert isinstance(result, guard.DiscoverySucceeded)
    assert result.matched == 2 and result.processed == 3
    assert all(isinstance(path, Path) for path in result.ordered)

    # Windows refuses to rename a directory while its scandir handle remains
    # open, so this also exercises real context-manager closure.
    moved = root / "real-scandir-moved"
    data_dir.rename(moved)
    assert moved.is_dir()


# -- ordering parity with the existing rules ---------------------------------

def test_ordering_matches_order_candidates_exactly(root, monkeypatch):
    """Within policy the primitive must not change selection at all, so its
    order is compared against the existing implementation over the same set."""
    names = ["v070_gen999999_step000001_a.npz",
             "v070_gen1000000_step000001_a.npz",
             "v070_gen000007_step000011_a.npz",
             "v070_gen000007_step000002_a.npz"]
    for name in names:
        _touch(root / name, 7000000000)
    entries = [_ProxyEntry(name, mtime_ns=7000000000) for name in names]
    _install(monkeypatch, _FakeScandir(entries))
    discovered = _discover(root, _policy(100, 100))

    monkeypatch.undo()
    expected = guard.order_candidates([root / name for name in names]).ordered
    assert ([p.name for p in discovered.ordered]
            == [p.name for p in expected])


def test_newer_modification_time_still_outranks_the_sequence(root, monkeypatch):
    entries = [_ProxyEntry("v070_gen999999_step1_a.npz", mtime_ns=1000),
               _ProxyEntry("v070_gen000001_step1_a.npz", mtime_ns=9000)]
    _install(monkeypatch, _FakeScandir(entries))
    result = _discover(root, _policy(100, 100))
    assert result.ordered[0].name == "v070_gen000001_step1_a.npz"


# -- metadata is requested without following symlinks ------------------------

def test_metadata_is_requested_without_following_symlinks(root, monkeypatch):
    """A link must not be able to borrow its target's modification time to
    promote itself to "newest" -- ordering deciding admission's question before
    admission is asked."""
    fake = _install(monkeypatch, _FakeScandir(_entries(3)))
    _discover(root, _policy(100, 100))
    assert fake.stat_calls, "no metadata was read"
    assert all(follow is False for _, follow in fake.stat_calls)


# -- matching parity with the production glob pattern ------------------------

@pytest.mark.parametrize("name,matches", [
    ("v070_gen000001_step000001_x.npz", True),
    ("v070_gen.npz", True),
    ("v070_ge000001.npz", False),
    ("xv070_gen000001.npz", False),
    ("v070_gen000001.npz.bak", False),
    ("v070_gen000001.np", False),
    ("telemetry_000001.json", False),
    ("acoustic_map_step000001.json", False),
])
def test_matching_agrees_with_the_production_glob_pattern(root, monkeypatch,
                                                          name, matches):
    """Parity with `v070_gen*.npz` as the consumers spell it, checked against
    `Path.glob` itself rather than against an assumption."""
    (root / name).write_bytes(b"x")
    globbed = set(p.name for p in Path(root).glob("v070_gen*.npz"))
    assert (name in globbed) is matches, "the fixture disagrees with Path.glob"

    _install(monkeypatch, _FakeScandir([_ProxyEntry(name)]))
    result = _discover(root, _policy(100, 100))
    assert (len(result.ordered) == 1) is matches


def test_matching_follows_the_platform_case_rule(root, monkeypatch):
    """`Path.glob` is case-insensitive on Windows and case-sensitive on POSIX.
    The primitive must agree with whichever platform it runs on rather than
    inventing a third behaviour."""
    upper = "V070_GEN000001_STEP1.NPZ"
    (root / upper).write_bytes(b"x")
    glob_matches = upper in set(p.name for p in Path(root).glob("v070_gen*.npz"))

    _install(monkeypatch, _FakeScandir([_ProxyEntry(upper)]))
    result = _discover(root, _policy(100, 100))
    assert (len(result.ordered) == 1) is glob_matches


# ===========================================================================
# The calibrated production policy and the shared single-flight cache
#
# The primitive above is deliberately caller-agnostic: it takes an explicit
# policy and has no default. This section pins the ONE production instance the
# three consumers share, and the process-local cache that makes those caps
# survivable in Medusa's threaded request topology -- where, without
# single-flight, N simultaneous requests meant N simultaneous cap-level
# discoveries and N times the discovery heap.
#
# Nothing here touches the filesystem. Populations are injected: the cache
# takes its scanner and its clock, so the state machine is exercised exactly
# and deterministically rather than by sleeping. The one cap-level population
# that DOES need real allocation lives in the opt-in benchmark at the end of
# this file, which pytest never runs.
# ===========================================================================


class _ManualClock:
    """A monotonic clock that only moves when a test moves it."""

    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)
        return self.now


def _succeeded(count=1, *, unreadable=0, start=0, extra_processed=0):
    """A complete listing, built the way the primitive builds one."""
    ordered = tuple(
        Path("data") / ("v070_gen%06d_step000001_x.npz" % (start + index))
        for index in range(count)
    )
    matched = count + unreadable
    return guard.DiscoverySucceeded(ordered, unreadable,
                                    matched + extra_processed, matched)


def _failed(reason=None, processed=7, matched=3, unreadable=0):
    reason = reason or guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED
    return guard.DiscoveryFailed(reason, processed, matched, unreadable)


class _RecordingScanner:
    """A deterministic stand-in for `discover_snapshot_candidates`.

    Returns (or raises) the next outcome, repeating the last one forever, and
    records every call. `gate` holds a refresh IN FLIGHT so a second caller's
    behaviour while the outcome is unknown is observable without any sleep.
    """

    def __init__(self, outcomes, clock=None, elapsed=0.0):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.policies = []
        self.gate = None
        self.entered = None
        self._clock = clock
        self._elapsed = elapsed

    def __call__(self, directory, *, policy):
        self.calls += 1
        self.policies.append(policy)
        if self.entered is not None:
            self.entered.set()
        if self.gate is not None and not self.gate.wait(timeout=10):
            raise AssertionError("scanner gate never opened")
        if self._clock is not None and self._elapsed:
            # A slow refresh. The TTL is measured from COMPLETION, so this
            # must not be able to publish an already-expired result.
            self._clock.advance(self._elapsed)
        index = min(self.calls - 1, len(self.outcomes) - 1)
        outcome = self.outcomes[index]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _cache(scanner, *, clock=None, ttl=10.0, directory="data", policy=None):
    clock = clock if clock is not None else _ManualClock()
    return guard.SnapshotDiscoveryCache(
        directory=directory,
        policy=policy or guard.PRODUCTION_DISCOVERY_POLICY,
        ttl=ttl,
        scanner=scanner,
        clock=clock,
    )


# -- the one production policy ------------------------------------------------

def test_the_production_discovery_policy_is_the_calibrated_pair():
    """The audited caps, exactly. 196,608 total entries and 65,536 candidates
    are the V2 calibration; a drift here is a silent capacity change."""
    policy = guard.PRODUCTION_DISCOVERY_POLICY
    assert isinstance(policy, guard.CandidateDiscoveryPolicy)
    assert policy.max_directory_entries == 196_608
    assert policy.max_candidates == 65_536


def test_the_production_discovery_policy_is_frozen_and_shared():
    """One instance, not a factory: every consumer must import the same object
    so there is no mixed bounded/unbounded or mixed-cap production state."""
    policy = guard.PRODUCTION_DISCOVERY_POLICY
    assert policy is guard.PRODUCTION_DISCOVERY_POLICY
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.max_candidates = 1


def test_the_primitive_still_has_no_policy_default():
    """Calibration lives in ONE named constant, never hidden in the callee's
    signature where a caller cannot see which caps it got."""
    import inspect
    parameter = inspect.signature(
        guard.discover_snapshot_candidates).parameters["policy"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_the_production_policy_is_not_the_archive_policy():
    assert guard.PRODUCTION_DISCOVERY_POLICY is not guard.PRODUCTION_POLICY
    assert not hasattr(guard.PRODUCTION_DISCOVERY_POLICY, "selection_depth")


@pytest.mark.parametrize("name", [
    "PRODUCTION_DISCOVERY_POLICY",
    "SnapshotDiscoveryCache",
    "DiscoveryLease",
    "DISCOVERY_CACHE_TTL_SECONDS",
])
def test_the_new_shared_names_are_exported(name):
    assert name in guard.__all__
    assert hasattr(guard, name)


def test_the_refresh_budget_is_ten_seconds():
    """A soft observed threshold, not an interruptible filesystem deadline."""
    assert guard.DISCOVERY_CACHE_TTL_SECONDS == 10.0


# -- the cache serves one completed immutable result --------------------------

def test_a_completed_success_is_borrowed_without_rescanning():
    scanner = _RecordingScanner([_succeeded(3)])
    cache = _cache(scanner)
    with cache.borrow() as first:
        assert first.available is True
        assert len(first.ordered) == 3
        held = first.result
    with cache.borrow() as second:
        assert second.result is held  # the same immutable object
    assert scanner.calls == 1


def test_the_borrowed_listing_is_an_immutable_tuple_of_paths():
    scanner = _RecordingScanner([_succeeded(2)])
    with _cache(scanner).borrow() as lease:
        assert type(lease.ordered) is tuple
        assert all(isinstance(entry, Path) for entry in lease.ordered)
        with pytest.raises(TypeError):
            lease.ordered[0] = Path("x")


def test_the_cache_passes_the_production_policy_to_the_scanner():
    scanner = _RecordingScanner([_succeeded(1)])
    with _cache(scanner).borrow():
        pass
    assert scanner.policies == [guard.PRODUCTION_DISCOVERY_POLICY]


def test_an_expired_success_is_refreshed_exactly_once():
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(1), _succeeded(2)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow():
        pass
    clock.advance(10.0)  # age == ttl is EXPIRED, not fresh
    with cache.borrow() as lease:
        assert len(lease.ordered) == 2
    assert scanner.calls == 2


def test_a_success_one_tick_inside_the_ttl_is_not_refreshed():
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(1), _succeeded(2)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow():
        pass
    clock.advance(9.999)
    with cache.borrow() as lease:
        assert len(lease.ordered) == 1
    assert scanner.calls == 1


def test_the_ttl_is_measured_from_completion_not_from_refresh_start():
    """A slow refresh must not publish an already-expired result: a 30-second
    scan followed by a 5-second-later borrow is a CACHE HIT, not a rescan."""
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(1), _succeeded(2)],
                                clock=clock, elapsed=30.0)
    cache = _cache(scanner, clock=clock)
    with cache.borrow():
        pass
    assert scanner.calls == 1
    clock.advance(5.0)
    with cache.borrow() as lease:
        assert len(lease.ordered) == 1
    assert scanner.calls == 1


# -- single flight ------------------------------------------------------------

def test_a_concurrent_burst_performs_exactly_one_refresh():
    import threading
    scanner = _RecordingScanner([_succeeded(4)])
    scanner.gate = threading.Event()
    scanner.entered = threading.Event()
    cache = _cache(scanner)

    outcomes = []
    barrier = threading.Barrier(8)

    def caller():
        barrier.wait(timeout=10)
        with cache.borrow() as lease:
            outcomes.append(bool(lease.available))

    threads = [threading.Thread(target=caller) for _ in range(8)]
    for thread in threads:
        thread.start()
    assert scanner.entered.wait(timeout=10)
    scanner.gate.set()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert scanner.calls == 1
    assert len(outcomes) == 8


def test_callers_without_a_prior_success_do_not_wait_for_the_refresh():
    """The expensive scan is outside the state lock and nobody queues on it."""
    import threading
    scanner = _RecordingScanner([_succeeded(1)])
    scanner.gate = threading.Event()
    scanner.entered = threading.Event()
    cache = _cache(scanner)

    owner = threading.Thread(target=lambda: cache.borrow().__enter__())
    owner.start()
    assert scanner.entered.wait(timeout=10)

    # The refresh is still in flight and its outcome is unknown.
    with cache.borrow() as lease:
        assert lease.available is False
        assert lease.reason is None
    assert scanner.calls == 1

    scanner.gate.set()
    owner.join(timeout=10)


def test_a_prior_success_is_served_stale_while_the_outcome_is_unknown():
    import threading
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(1), _succeeded(9)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow():
        pass

    scanner.gate = threading.Event()
    scanner.entered = threading.Event()
    clock.advance(10.0)

    owner = threading.Thread(target=lambda: cache.borrow().__enter__())
    owner.start()
    assert scanner.entered.wait(timeout=10)

    with cache.borrow() as lease:
        assert lease.available is True
        assert lease.stale is True
        assert len(lease.ordered) == 1  # the PRIOR completed listing
    assert scanner.calls == 2  # still just the owner's

    scanner.gate.set()
    owner.join(timeout=10)


def test_the_scan_runs_outside_the_state_lock():
    """If the lock were held across the scan, this borrow would deadlock."""
    import threading
    scanner = _RecordingScanner([_succeeded(1)])
    scanner.gate = threading.Event()
    scanner.entered = threading.Event()
    cache = _cache(scanner)

    owner = threading.Thread(target=lambda: cache.borrow().__enter__())
    owner.start()
    assert scanner.entered.wait(timeout=10)

    finished = threading.Event()

    def probe():
        with cache.borrow():
            pass
        finished.set()

    threading.Thread(target=probe).start()
    assert finished.wait(timeout=5), "state lock was held across the scan"
    scanner.gate.set()
    owner.join(timeout=10)


# -- fail closed --------------------------------------------------------------

@pytest.mark.parametrize("reason", [
    guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED,
    guard.DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED,
    guard.DiscoveryFailureReason.DIRECTORY_OPEN_FAILED,
    guard.DiscoveryFailureReason.ITERATION_FAILED,
], ids=lambda reason: reason.value)
def test_a_known_failure_atomically_invalidates_a_prior_success(reason):
    """V2.2: no bounded failure may coexist with a visible completed success
    once the outcome is known. Overflow AFTER a good listing is the case that
    matters -- the old listing is exactly what a stale-serving cache would
    keep handing out while the directory is over its cap."""
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3), _failed(reason)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow() as good:
        assert good.available is True

    clock.advance(10.0)
    with cache.borrow() as lease:
        assert lease.available is False
        assert lease.reason is reason

    # And no new caller may borrow the retired listing.
    with cache.borrow() as later:
        assert later.available is False
        assert later.reason is reason
    assert cache.diagnostics().has_success is False


def test_the_failure_ttl_blocks_every_new_refresh_until_expiry():
    clock = _ManualClock()
    scanner = _RecordingScanner([_failed(), _succeeded(2)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow() as lease:
        assert lease.available is False
    assert scanner.calls == 1

    for _ in range(5):
        clock.advance(1.0)
        with cache.borrow() as lease:
            assert lease.available is False
    assert scanner.calls == 1, "a new refresh started inside the failure TTL"


def test_at_failure_ttl_expiry_exactly_one_retry_starts():
    import threading
    clock = _ManualClock()
    scanner = _RecordingScanner([_failed(), _succeeded(2)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow():
        pass

    scanner.gate = threading.Event()
    scanner.entered = threading.Event()
    clock.advance(10.0)

    owner = threading.Thread(target=lambda: cache.borrow().__enter__())
    owner.start()
    assert scanner.entered.wait(timeout=10)

    # Everyone else stays immediately unavailable -- no second retry, no wait.
    with cache.borrow() as lease:
        assert lease.available is False
    assert scanner.calls == 2

    scanner.gate.set()
    owner.join(timeout=10)


def test_a_successful_retry_atomically_restores_a_completed_success():
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(1), _failed(), _succeeded(5)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow():
        pass
    clock.advance(10.0)
    with cache.borrow() as lease:
        assert lease.available is False
    clock.advance(10.0)
    with cache.borrow() as lease:
        assert lease.available is True
        assert len(lease.ordered) == 5
    assert cache.diagnostics().failure_reason is None


# -- ownership is always released ---------------------------------------------

class _ScannerBoom(Exception):
    """Distinct so its propagation can be asserted exactly."""


@pytest.mark.parametrize("raised", [
    _ScannerBoom("scan failed"),
    KeyboardInterrupt(),
    MemoryError(),
], ids=["exception", "keyboard_interrupt", "memory_error"])
def test_every_exit_path_releases_refresh_ownership(raised):
    """A wedged ownership token is a permanent outage: nobody could ever
    refresh again. Release is `finally`-equivalent for BaseException too."""
    scanner = _RecordingScanner([raised, _succeeded(2)])
    cache = _cache(scanner)

    with pytest.raises(type(raised)):
        with cache.borrow():
            pass

    assert cache.diagnostics().refresh_in_flight is False
    with cache.borrow() as lease:
        assert lease.available is True
    assert scanner.calls == 2


def test_a_failed_refresh_publishes_nothing_from_the_exception():
    scanner = _RecordingScanner([_ScannerBoom("boom"), _succeeded(1)])
    cache = _cache(scanner)
    with pytest.raises(_ScannerBoom):
        with cache.borrow():
            pass
    state = cache.diagnostics()
    assert state.has_success is False and state.failure_reason is None


def test_a_lease_is_released_when_the_consumer_body_raises():
    scanner = _RecordingScanner([_succeeded(1)])
    cache = _cache(scanner)
    with pytest.raises(_ScannerBoom):
        with cache.borrow():
            raise _ScannerBoom("consumer failed")
    assert cache.diagnostics().live_borrowers == 0


# -- what the cache may never store -------------------------------------------

def _generator_result():
    yield Path("data/v070_gen000001_step1_x.npz")


class _NotAResult:
    ordered = [Path("data/v070_gen000001_step1_x.npz")]
    unreadable = 0


@pytest.mark.parametrize("payload", [
    [Path("data/v070_gen000001_step1_x.npz")],
    (Path("data/v070_gen000001_step1_x.npz"),),
    _generator_result(),
    _NotAResult(),
    None,
    "v070_gen000001_step1_x.npz",
], ids=["list", "bare_tuple", "generator", "duck_type", "none", "str"])
def test_the_cache_refuses_to_publish_anything_but_a_completed_result(payload):
    """A mutable collection, a generator, a partial prefix or a look-alike is
    refused rather than published: a borrower must never be able to mutate,
    exhaust or half-consume what the cache handed it."""
    scanner = _RecordingScanner([payload])
    cache = _cache(scanner)
    with pytest.raises(ValueError):
        with cache.borrow():
            pass
    state = cache.diagnostics()
    assert state.has_success is False
    assert state.refresh_in_flight is False


def test_the_cache_stores_no_selected_path_or_descriptor():
    """The cache's whole visible state is counters, flags and clocks. Anything
    path-shaped in it is a leak of exactly the kind the closed diagnostic
    vocabulary forbids."""
    scanner = _RecordingScanner([_succeeded(2)])
    cache = _cache(scanner)
    with cache.borrow():
        pass
    state = cache.diagnostics()
    for field in dataclasses.fields(state):
        value = getattr(state, field.name)
        assert not isinstance(value, (str, bytes, Path)), field.name


def test_the_diagnostics_repr_carries_no_path_or_filename():
    scanner = _RecordingScanner([_succeeded(2)])
    cache = _cache(scanner)
    with cache.borrow():
        pass
    text = repr(cache.diagnostics())
    for leak in ("v070_gen", ".npz", "/", "\\"):
        assert leak not in text


def test_the_failure_diagnostic_is_a_fixed_code_only():
    scanner = _RecordingScanner([_failed(
        guard.DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED)])
    cache = _cache(scanner)
    with cache.borrow():
        pass
    state = cache.diagnostics()
    assert state.failure_reason is guard.DiscoveryFailureReason.CANDIDATE_LIMIT_EXCEEDED
    assert state.failure_reason.value == "candidate_limit_exceeded"


# -- borrower accounting and the third generation -----------------------------

def test_a_non_refreshing_borrower_never_starts_a_scan():
    """Lucid's clients. Zero client-triggered directory work, by construction."""
    scanner = _RecordingScanner([_succeeded(1)])
    cache = _cache(scanner)
    for _ in range(10):
        with cache.borrow(allow_refresh=False) as lease:
            assert lease.available is False
    assert scanner.calls == 0


def test_a_non_refreshing_borrower_uses_a_fresh_completed_result():
    """A client may consume the watcher's listing while it is FRESH."""
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow(allow_refresh=True):
        pass
    clock.advance(9.999)
    with cache.borrow(allow_refresh=False) as lease:
        assert lease.available is True
        assert lease.stale is False
        assert len(lease.ordered) == 3
    assert scanner.calls == 1


def test_an_expired_listing_is_not_served_when_nothing_is_refreshing():
    """The predecessor of this control asserted the opposite, and was wrong.

    V2.2 is explicit: a prior completed success may be served stale ONLY while
    exactly one refresh is actively in flight and that refresh's outcome is
    still unknown. Handing an expired listing to a non-refreshing borrower
    satisfies none of that -- nothing is in flight, no outcome is unknown, and
    no third-generation deferral is holding a refresh back. It is simply an
    unbounded-age listing with nobody responsible for replacing it, which is
    exactly the stale-forever failure mode the lifetime exists to prevent.

    The correct answer is immediate unavailability, and still no scan: a
    non-refreshing borrower never starts directory work under any condition.
    """
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow(allow_refresh=True):
        pass
    clock.advance(10.0)

    state = cache.diagnostics()
    assert state.refresh_in_flight is False
    assert state.retired_borrowers == 0

    with cache.borrow(allow_refresh=False) as lease:
        assert lease.available is False
        assert lease.stale is False
        assert lease.reason is None       # not a failure -- just nothing usable
    assert scanner.calls == 1, "a non-refreshing borrower started a scan"


def test_a_long_expired_listing_is_never_resurrected_for_a_client():
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow(allow_refresh=True):
        pass
    clock.advance(1000.0)
    for _ in range(5):
        with cache.borrow(allow_refresh=False) as lease:
            assert lease.available is False
    assert scanner.calls == 1


def test_a_non_refreshing_borrower_may_use_a_success_while_a_refresh_is_unknown():
    """The one authorized stale window: a refresh IS in flight and its outcome
    is not yet known."""
    import threading
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3), _succeeded(4)])
    cache = _cache(scanner, clock=clock)
    with cache.borrow(allow_refresh=True):
        pass

    scanner.gate = threading.Event()
    scanner.entered = threading.Event()
    clock.advance(10.0)

    owner = threading.Thread(target=lambda: cache.borrow().__enter__())
    owner.start()
    assert scanner.entered.wait(timeout=10)

    with cache.borrow(allow_refresh=False) as lease:
        assert lease.available is True
        assert lease.stale is True
        assert len(lease.ordered) == 3
    assert scanner.calls == 2

    scanner.gate.set()
    owner.join(timeout=10)


def test_a_non_refreshing_borrower_may_use_a_deferred_listing():
    """The other authorized stale window: a refresh is being held back to stop
    a third cap-level generation existing. The listing is deliberately kept
    live for that reason, so a client may still consume it."""
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3), _failed(), _succeeded(5)])
    cache = _cache(scanner, clock=clock)

    holder = cache.borrow(allow_refresh=True)
    holder.__enter__()
    clock.advance(10.0)
    with cache.borrow(allow_refresh=True) as lease:
        assert lease.available is False        # failure published, gen retired
    clock.advance(10.0)
    with cache.borrow(allow_refresh=True) as lease:
        assert len(lease.ordered) == 5         # recovery published
    clock.advance(10.0)                        # a refresh WOULD be a third gen

    state = cache.diagnostics()
    assert state.retired_borrowers == 1
    assert state.refresh_in_flight is False

    with cache.borrow(allow_refresh=False) as lease:
        assert lease.available is True
        assert lease.stale is True
        assert len(lease.ordered) == 5
    assert scanner.calls == 3

    holder.__exit__(None, None, None)


def test_a_known_failure_stays_unavailable_for_a_non_refreshing_borrower():
    clock = _ManualClock()
    scanner = _RecordingScanner([_failed()])
    cache = _cache(scanner, clock=clock)
    with cache.borrow(allow_refresh=True) as lease:
        assert lease.available is False
    for advance in (1.0, 10.0, 1000.0):
        clock.advance(advance)
        with cache.borrow(allow_refresh=False) as lease:
            assert lease.available is False
            assert lease.stale is False
    assert scanner.calls == 1


def test_a_held_borrower_finishes_after_its_listing_is_retired():
    """V2.2: a synchronous borrower that already holds the old immutable
    listing may finish its selection; the CACHE keeps no reference to it."""
    clock = _ManualClock()
    scanner = _RecordingScanner([_succeeded(3), _failed()])
    cache = _cache(scanner, clock=clock)

    holder = cache.borrow()
    held = holder.__enter__()
    assert len(held.ordered) == 3

    clock.advance(10.0)
    with cache.borrow() as lease:
        assert lease.available is False

    state = cache.diagnostics()
    assert state.has_success is False
    assert state.retired_borrowers == 1
    assert len(held.ordered) == 3  # the borrower's own object is intact

    holder.__exit__(None, None, None)
    assert cache.diagnostics().retired_borrowers == 0


def test_a_third_listing_generation_is_deferred_until_borrowers_release():
    """At most two cap-level footprints: one retired listing still held, and
    one in-flight or newly published replacement. A refresh that would make a
    third is deferred rather than run."""
    clock = _ManualClock()
    scanner = _RecordingScanner([
        _succeeded(3), _failed(), _succeeded(5), _succeeded(7)])
    cache = _cache(scanner, clock=clock)

    holder = cache.borrow()
    holder.__enter__()

    clock.advance(10.0)                      # -> failure published, gen 1 retired
    with cache.borrow() as lease:
        assert lease.available is False
    clock.advance(10.0)                      # -> retry succeeds, a new listing
    with cache.borrow() as lease:
        assert lease.available is True
        assert len(lease.ordered) == 5
    assert scanner.calls == 3

    state = cache.diagnostics()
    assert state.retired_borrowers == 1

    clock.advance(10.0)                      # a fourth scan WOULD be a third listing
    with cache.borrow() as lease:
        assert lease.available is True
        assert lease.stale is True
        assert len(lease.ordered) == 5       # still the live generation
    assert scanner.calls == 3, "a third listing generation was allowed"

    holder.__exit__(None, None, None)
    assert cache.diagnostics().retired_borrowers == 0

    clock.advance(10.0)
    with cache.borrow() as lease:
        assert len(lease.ordered) == 7
    assert scanner.calls == 4


def test_borrower_accounting_is_aggregate_counts_only():
    scanner = _RecordingScanner([_succeeded(2)])
    cache = _cache(scanner)
    first = cache.borrow()
    first.__enter__()
    second = cache.borrow()
    second.__enter__()
    state = cache.diagnostics()
    assert state.live_borrowers == 2
    assert type(state.live_borrowers) is int
    first.__exit__(None, None, None)
    second.__exit__(None, None, None)
    assert cache.diagnostics().live_borrowers == 0


# -- the four states stay distinct --------------------------------------------

def test_clean_empty_is_a_success_not_a_failure():
    scanner = _RecordingScanner([_succeeded(0)])
    with _cache(scanner).borrow() as lease:
        assert lease.available is True
        assert lease.ordered == ()
        assert lease.matched == 0
        assert lease.all_matching_unreadable is False
        assert lease.reason is None


def test_all_matching_unreadable_is_a_success_with_its_own_flag():
    scanner = _RecordingScanner([_succeeded(0, unreadable=4)])
    with _cache(scanner).borrow() as lease:
        assert lease.available is True
        assert lease.ordered == ()
        assert lease.matched == 4
        assert lease.unreadable == 4
        assert lease.all_matching_unreadable is True
        assert lease.reason is None


def test_discovery_failure_is_neither_empty_nor_unreadable():
    scanner = _RecordingScanner([_failed()])
    with _cache(scanner).borrow() as lease:
        assert lease.available is False
        assert lease.all_matching_unreadable is False
        assert lease.reason is guard.DiscoveryFailureReason.ENTRY_LIMIT_EXCEEDED


def test_an_archive_refusal_never_reaches_the_discovery_cache():
    """`SnapshotArchiveRejected` is downstream of a SUCCESSFUL discovery. It
    must not poison, invalidate or relabel the completed listing."""
    scanner = _RecordingScanner([_succeeded(2)])
    cache = _cache(scanner)
    with pytest.raises(guard.SnapshotArchiveRejected):
        with cache.borrow() as lease:
            assert lease.available is True
            raise guard.SnapshotArchiveRejected("path_not_confined")
    state = cache.diagnostics()
    assert state.has_success is True
    assert state.failure_reason is None
    assert state.live_borrowers == 0
    with cache.borrow() as lease:
        assert lease.available is True
    assert scanner.calls == 1


# ===========================================================================
# Opt-in cap-level benchmark -- NOT part of the pytest suite
#
# The acceptance gate for the 224 MiB incremental overlap budget and the
# 10-second soft refresh budget needs REAL cap-level allocation: 196,608
# synthetic directory entries and 65,536 retained candidate rows, sorted and
# frozen into a tuple, with a prior cap-level listing still held. That is far
# too much work for the ordinary suite, so it lives behind an explicit
# entrypoint that pytest never runs.
#
# It is opt-in, not skipped. `pytest` collects nothing from this section
# except the two tiny controls at the bottom, which prove the harness itself
# still works -- so it cannot rot silently while reporting a green suite.
#
# Run it, from the repository root:
#
#     python  tests/test_snapshot_archive_guard.py --case all
#     python -O tests/test_snapshot_archive_guard.py --case all
#
# Every record is one JSON object on stdout with fixed keys: interpreter,
# optimization mode, population, elapsed seconds, incremental peak, result
# count or fixed refusal code, and whether an old completed listing was held
# across the refresh. No path, filename, drive, environment value or
# exception text is emitted, by construction: the synthetic names are
# generated here and never printed.
#
# The FINAL target-host execution on Area 51 is deliberately pending and
# needs separate authority. Nothing below reaches a real directory.
# ===========================================================================

#: The V2 one-year projection and the calibrated caps.
BENCHMARK_PROJECTED_POPULATION = (168_631, 56_147)
BENCHMARK_CAP_POPULATION = (196_608, 65_536)

#: V2.1 section 4: an incremental discovery/cache OVERLAP budget, per process.
#: Not a whole-process RSS budget and not a NumPy-load budget.
BENCHMARK_HEAP_BUDGET_BYTES = 224 * 1024 * 1024

#: V2 section "Sort and latency": a soft OBSERVED acceptance threshold. A
#: blocking directory call cannot be interrupted by an elapsed-time check, so
#: this is never a deadline and is never enforced at runtime.
BENCHMARK_SOFT_REFRESH_SECONDS = 10.0

BENCHMARK_CASES = ("projected", "cap", "overlap", "failure_recovery")


class _BenchStat:
    __slots__ = ("st_mtime_ns", "st_size")

    def __init__(self, mtime_ns):
        self.st_mtime_ns = mtime_ns
        self.st_size = 64


class _BenchEntry:
    __slots__ = ("name", "_mtime_ns")

    def __init__(self, name, mtime_ns):
        self.name = name
        self._mtime_ns = mtime_ns

    def stat(self, *, follow_symlinks=True):
        return _BenchStat(self._mtime_ns)


class _BenchScandir:
    """A synthetic directory of `total` entries, `matching` of them snapshots.

    Entries are generated lazily and never retained by the fixture, so the
    measured incremental peak is the DISCOVERY footprint -- the retained rows,
    the `Path` objects, the sort and the final tuple -- rather than the cost of
    holding a fake directory in memory.

    Matching entries are distributed evenly across the whole enumeration
    rather than bunched at the front, so the candidate counter and the entry
    counter advance together the way they do in a real mixed directory. The
    modification times are a fixed multiplicative sequence: deterministic, and
    deliberately NOT already sorted, so the production sort does real work.
    """

    def __init__(self, total, matching):
        if matching > total:
            raise ValueError("benchmark_population_invalid")
        self.total = int(total)
        self.matching = int(matching)

    def __call__(self, directory):
        return self

    def __enter__(self):
        return self._iterate()

    def __exit__(self, *exc):
        return False

    def _iterate(self):
        total = self.total
        matching = self.matching
        emitted = 0
        for index in range(total):
            wanted = ((index + 1) * matching) // total
            if wanted > emitted:
                emitted += 1
                name = "v070_gen%06d_step%06d_bench.npz" % (emitted, emitted * 10)
            else:
                name = "telemetry_%06d.json" % index
            yield _BenchEntry(name, (index * 2654435761) % 2147483647)


def _bench_policy(total, matching):
    """The caps this population is measured against.

    At either calibrated population it is the real shared production instance,
    which is the whole point of the acceptance run. An INJECTED smaller
    population gets a policy scaled to it, so the boundary cases stay boundary
    cases: the tiny controls below would otherwise sit 196,000 entries below
    the cap and prove nothing about overflow.
    """
    if (total, matching) in (BENCHMARK_PROJECTED_POPULATION,
                             BENCHMARK_CAP_POPULATION):
        return guard.PRODUCTION_DISCOVERY_POLICY
    return guard.CandidateDiscoveryPolicy(
        max_directory_entries=max(int(total), 1),
        max_candidates=max(int(matching), 1),
    )


class _BenchPlan:
    """A scanner that runs the REAL primitive over successive populations.

    Each step is one `(total, matching)` pair; the last step repeats. A step
    whose `total` exceeds the policy's entry cap produces a genuine
    `entry_limit_exceeded`, so the failure lifecycle is exercised by the
    production refusal rather than by a fabricated one.

    Each call is timed individually and recorded in `durations`. That is what
    the soft budget is actually about -- one refresh being survivable -- and it
    cannot be recovered from a total afterwards.
    """

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = 0
        self.durations = []

    def __call__(self, directory, *, policy):
        step = self.steps[min(self.calls, len(self.steps) - 1)]
        self.calls += 1
        started = time.perf_counter()
        with mock.patch.object(guard.os, "scandir", _BenchScandir(*step)):
            result = guard.discover_snapshot_candidates(directory,
                                                        policy=policy)
        self.durations.append(time.perf_counter() - started)
        return result


def _bench_outcome(result):
    """A result count, or a fixed refusal code. Never a path."""
    if isinstance(result, guard.DiscoveryFailed):
        return {"refusal_code": result.reason.value, "candidates": None}
    return {"refusal_code": None, "candidates": len(result.ordered)}


def _bench_record(case, total, matching, elapsed, peak, outcome, retained,
                  durations):
    """One record with fixed keys and no locator of any kind.

    The soft budget is a per-REFRESH threshold, so it is measured against the
    WORST individual refresh, never against a mean. Dividing a total by the
    scan count let a fast retry pay for a slow one: a 15-second refresh beside
    a 1-second refresh averages to 8 seconds and would have passed a 10-second
    threshold it plainly breached. `max_refresh_seconds` is the figure the
    threshold applies to; `elapsed_seconds`, `refresh_seconds_total` and
    `scans` are retained beside it so the shape of a multi-refresh case stays
    readable rather than being reduced to one number.
    """
    import platform
    policy = _bench_policy(total, matching)
    durations = [float(value) for value in durations] or [float(elapsed)]
    worst = max(durations)
    record = {
        "case": case,
        "max_directory_entries": policy.max_directory_entries,
        "max_candidates": policy.max_candidates,
        "interpreter": platform.python_implementation(),
        "python_version": "%d.%d.%d" % sys.version_info[:3],
        "optimize_level": sys.flags.optimize,
        "total_entries": int(total),
        "matching_entries": int(matching),
        "scans": len(durations),
        "elapsed_seconds": round(float(elapsed), 6),
        "refresh_seconds_total": round(sum(durations), 6),
        "max_refresh_seconds": round(worst, 6),
        "incremental_peak_bytes": int(peak),
        "incremental_peak_mib": round(peak / 1024 / 1024, 3),
        "heap_budget_bytes": BENCHMARK_HEAP_BUDGET_BYTES,
        "within_heap_budget": bool(peak <= BENCHMARK_HEAP_BUDGET_BYTES),
        "soft_refresh_seconds": BENCHMARK_SOFT_REFRESH_SECONDS,
        "within_soft_refresh_budget": bool(
            worst <= BENCHMARK_SOFT_REFRESH_SECONDS),
        "old_listing_retained": bool(retained),
    }
    record.update(outcome)
    return record


def _bench_timed(work):
    """Timing WITHOUT tracemalloc, then the peak WITH it, in two passes.

    `tracemalloc` perturbs allocation-heavy timing badly enough that a single
    instrumented pass would report a duration the production path never has, so
    every duration reported -- the total AND each individual refresh -- comes
    from the first, uninstrumented pass. The V2 calibration separated the two
    passes for the same reason.

    `work` returns ``(payload, durations)``. The payload is a small summary,
    never a listing, so nothing cap-sized survives into the allocation pass and
    inflates its peak.
    """
    import tracemalloc
    started = time.perf_counter()
    payload, durations = work()
    elapsed = time.perf_counter() - started
    durations = list(durations)

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        traced = work()
        peak = tracemalloc.get_traced_memory()[1]
        del traced
    finally:
        tracemalloc.stop()
    return payload, durations, elapsed, peak


def _bench_single(case, total, matching):
    """One bounded discovery at the given population."""
    policy = _bench_policy(total, matching)

    def work():
        scandir = _BenchScandir(total, matching)
        started = time.perf_counter()
        with mock.patch.object(guard.os, "scandir", scandir):
            result = guard.discover_snapshot_candidates(Path("bench"),
                                                        policy=policy)
        duration = time.perf_counter() - started
        return _bench_outcome(result), [duration]

    outcome, durations, elapsed, peak = _bench_timed(work)
    return _bench_record(case, total, matching, elapsed, peak, outcome,
                         retained=False, durations=durations)


def _bench_overlap(total, matching):
    """One cap-level listing held while its replacement is built and published.

    This is the V2.1 section 4 overlap case: the combined incremental peak must
    cover the retained old listing AND the in-flight replacement.
    """
    def work():
        clock = _ManualClock()
        plan = _BenchPlan([(total, matching)])
        cache = guard.SnapshotDiscoveryCache(
            directory=Path("bench"),
            policy=_bench_policy(total, matching),
            ttl=guard.DISCOVERY_CACHE_TTL_SECONDS,
            scanner=plan,
            clock=clock,
        )
        holder = cache.borrow()
        held = holder.__enter__()
        try:
            clock.advance(guard.DISCOVERY_CACHE_TTL_SECONDS)
            with cache.borrow() as replacement:
                summary = {"refusal_code": None,
                           "candidates": len(replacement.ordered),
                           "held": len(held.ordered)}
            return summary, plan.durations
        finally:
            holder.__exit__(None, None, None)

    summary, durations, elapsed, peak = _bench_timed(work)
    outcome = {"refusal_code": None, "candidates": summary["candidates"]}
    return _bench_record("overlap", total, matching, elapsed, peak, outcome,
                         retained=True, durations=durations)


def _bench_failure_recovery(total, matching):
    """The V2.2 fail-closed lifecycle with the old borrower deliberately held.

    One cap-level success is borrowed and HELD; the next refresh overflows the
    entry cap and publishes the sanitized failure, dropping the cache's own
    reference to the old listing; the borrower finishes; the failure TTL
    expires and one retry publishes a new cap-level success. At no point may a
    third cap-level listing exist.
    """
    def work():
        clock = _ManualClock()
        plan = _BenchPlan([
            (total, matching),           # first success
            (total + 1, matching),       # entry_limit_exceeded
            (total, matching),           # recovery
        ])
        cache = guard.SnapshotDiscoveryCache(
            directory=Path("bench"),
            policy=_bench_policy(total, matching),
            ttl=guard.DISCOVERY_CACHE_TTL_SECONDS,
            scanner=plan,
            clock=clock,
        )
        holder = cache.borrow()
        held = holder.__enter__()
        try:
            clock.advance(guard.DISCOVERY_CACHE_TTL_SECONDS)
            with cache.borrow() as failed:
                refusal = failed.reason
            retired = cache.diagnostics().retired_borrowers
            clock.advance(guard.DISCOVERY_CACHE_TTL_SECONDS)
            with cache.borrow() as recovered:
                summary = {
                    "refusal_code": (refusal.value if refusal is not None
                                     else None),
                    "candidates": len(recovered.ordered),
                    "retired_borrowers_at_failure": retired,
                    "held": len(held.ordered),
                }
            return summary, plan.durations
        finally:
            holder.__exit__(None, None, None)

    summary, durations, elapsed, peak = _bench_timed(work)
    outcome = {
        "refusal_code": summary["refusal_code"],
        "candidates": summary["candidates"],
        "retired_borrowers_at_failure": summary["retired_borrowers_at_failure"],
    }
    return _bench_record("failure_recovery", total, matching, elapsed, peak,
                         outcome, retained=True, durations=durations)


def run_benchmark_case(case, *, total=None, matching=None):
    """One benchmark record. `total`/`matching` override the population."""
    if case not in BENCHMARK_CASES:
        raise ValueError("benchmark_case_unknown")
    if case == "projected":
        population = BENCHMARK_PROJECTED_POPULATION
    else:
        population = BENCHMARK_CAP_POPULATION
    total = population[0] if total is None else int(total)
    matching = population[1] if matching is None else int(matching)

    if case in ("projected", "cap"):
        return _bench_single(case, total, matching)
    if case == "overlap":
        return _bench_overlap(total, matching)
    return _bench_failure_recovery(total, matching)


def _benchmark_status(records):
    """The entrypoint's exit status: nonzero if EITHER budget was breached.

    It used to consider only the heap. A latency breach printed
    `"within_soft_refresh_budget": false` into the record and then exited zero,
    so an acceptance run whose refreshes were over the threshold looked like a
    pass to anything reading the status -- a CI step, a wrapper, or a person
    skimming. Both budgets are gates, so both decide the status.
    """
    for record in records:
        if not record["within_heap_budget"]:
            return 1
        if not record["within_soft_refresh_budget"]:
            return 1
    return 0


def _benchmark_main(argv=None):
    """The opt-in entrypoint. Returns a process exit status."""
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        description=("Cap-level bounded-discovery benchmark. Deterministic, "
                     "filesystem-free and path-free; prints one JSON record "
                     "per case."))
    parser.add_argument("--case", required=True,
                        choices=BENCHMARK_CASES + ("all",),
                        help="which acceptance case to run")
    parser.add_argument("--total", type=int, default=None,
                        help="override the synthetic total-entry population")
    parser.add_argument("--matching", type=int, default=None,
                        help="override the synthetic matching population")
    args = parser.parse_args(argv)

    cases = BENCHMARK_CASES if args.case == "all" else (args.case,)
    records = []
    for case in cases:
        record = run_benchmark_case(case, total=args.total,
                                    matching=args.matching)
        print(_json.dumps(record, sort_keys=True))
        records.append(record)
    return _benchmark_status(records)


# -- the two controls that keep the benchmark from rotting silently ----------

def test_the_benchmark_harness_runs_at_a_tiny_population():
    """Not the cap-level run -- that is the Area 51 gate. This proves the
    harness, the record schema and all four cases still execute, so the
    entrypoint cannot rot behind a green suite."""
    for case in BENCHMARK_CASES:
        record = run_benchmark_case(case, total=90, matching=30)
        assert record["case"] == case
        assert record["total_entries"] == 90
        assert record["matching_entries"] == 30
        assert record["optimize_level"] == sys.flags.optimize
        assert record["heap_budget_bytes"] == 224 * 1024 * 1024
        assert record["max_directory_entries"] == 90
        assert record["max_candidates"] == 30
        assert record["incremental_peak_bytes"] > 0
        assert record["elapsed_seconds"] >= 0.0
        assert record["old_listing_retained"] is (
            case in ("overlap", "failure_recovery"))
        assert record["scans"] == {"projected": 1, "cap": 1, "overlap": 2,
                                   "failure_recovery": 3}[case]
        # The soft budget is per REFRESH, measured on the WORST one, so a case
        # that runs a retry can neither be judged on its total nor let a fast
        # refresh pay for a slow one.
        assert record["max_refresh_seconds"] > 0.0
        assert record["max_refresh_seconds"] <= record["refresh_seconds_total"]
        assert record["refresh_seconds_total"] <= record["elapsed_seconds"] + 1e-6
        assert record["within_soft_refresh_budget"] is True
        if case == "failure_recovery":
            assert record["refusal_code"] == "entry_limit_exceeded"
            assert record["retired_borrowers_at_failure"] == 1
        else:
            assert record["refusal_code"] is None
            assert record["candidates"] == 30


def test_the_benchmark_population_is_exact_and_deterministic():
    """`matching` entries, not approximately that many: the acceptance run
    claims an exact cap-level population and must actually produce one."""
    for total, matching in ((90, 30), (168_631 % 997, 7), (1000, 999)):
        names = [entry.name for entry in _BenchScandir(total, matching)._iterate()]
        assert len(names) == total
        assert sum(name.startswith("v070_gen") for name in names) == matching
        again = [entry.name for entry in _BenchScandir(total, matching)._iterate()]
        assert names == again


def test_the_benchmark_record_carries_no_locator():
    record = run_benchmark_case("cap", total=60, matching=20)
    text = repr(sorted(record.items()))
    for leak in ("v070_gen", ".npz", "bench/", "Traceback", "Users", "tmp"):
        assert leak not in text


def test_the_benchmark_entrypoint_is_not_collected_by_pytest():
    """It must be run deliberately, never swept into the ordinary suite and
    never silently skipped away."""
    assert not _benchmark_main.__name__.startswith("test")
    assert not run_benchmark_case.__name__.startswith("test")
    with pytest.raises(SystemExit):
        _benchmark_main(["--case", "nonsense"])



# -- the soft budget is a MAXIMUM, never an average ---------------------------
#
# Averaging was a real hole in the acceptance harness. The overlap and
# failure/recovery cases run two and three refreshes, and dividing the total by
# the count reports a mean -- so a 15-second refresh beside a 1-second refresh
# became 8 seconds and passed a 10-second per-refresh threshold that it plainly
# breached. The threshold is about ONE refresh being survivable; a fast retry
# must never be able to pay for a slow one.


def test_the_soft_budget_is_measured_on_the_worst_refresh_not_the_mean():
    """15 s + 1 s must FAIL, and the same durations must pass as a mean --
    otherwise this control would not distinguish the two rules at all."""
    record = _bench_record("overlap", 90, 30, elapsed=0.5, peak=1024,
                           outcome={"refusal_code": None, "candidates": 30},
                           retained=True, durations=[15.0, 1.0])
    assert record["scans"] == 2
    assert record["max_refresh_seconds"] == 15.0
    assert record["within_soft_refresh_budget"] is False

    mean = record["refresh_seconds_total"] / record["scans"]
    assert mean == 8.0
    assert mean <= record["soft_refresh_seconds"], (
        "the fixture must be one the DISCARDED averaging rule would pass, or "
        "this control proves nothing")


def test_a_single_slow_refresh_fails_the_soft_budget():
    record = _bench_record("cap", 90, 30, elapsed=11.0, peak=1024,
                           outcome={"refusal_code": None, "candidates": 30},
                           retained=False, durations=[11.0])
    assert record["max_refresh_seconds"] == 11.0
    assert record["within_soft_refresh_budget"] is False


def test_every_refresh_inside_the_budget_passes():
    record = _bench_record("failure_recovery", 90, 30, elapsed=9.0, peak=1024,
                           outcome={"refusal_code": "entry_limit_exceeded",
                                    "candidates": 30},
                           retained=True, durations=[3.0, 3.0, 3.0])
    assert record["max_refresh_seconds"] == 3.0
    assert record["refresh_seconds_total"] == 9.0
    assert record["within_soft_refresh_budget"] is True


def test_the_record_reports_individual_refresh_accounting():
    """Total elapsed and scan count are retained honestly beside the maximum;
    the discarded per-scan average is gone rather than left to be misread."""
    record = run_benchmark_case("overlap", total=90, matching=30)
    assert "seconds_per_scan" not in record
    assert record["scans"] == 2
    assert record["max_refresh_seconds"] > 0.0
    assert record["max_refresh_seconds"] <= record["refresh_seconds_total"]
    assert record["refresh_seconds_total"] <= record["elapsed_seconds"] + 1e-6


def test_the_refresh_durations_come_from_the_uninstrumented_pass():
    """`tracemalloc` perturbs allocation-heavy timing badly. A duration taken
    from the traced pass would report a latency the production path never
    has, so the timing pass runs first and alone."""
    record = run_benchmark_case("cap", total=90, matching=30)
    assert record["scans"] == 1
    assert record["max_refresh_seconds"] <= record["elapsed_seconds"] + 1e-6


# -- the entrypoint must fail on EITHER budget --------------------------------

def test_the_entrypoint_status_fails_on_a_latency_breach():
    passing = _bench_record("cap", 90, 30, 1.0, 1024,
                            {"refusal_code": None, "candidates": 30},
                            False, [1.0])
    slow = _bench_record("cap", 90, 30, 11.0, 1024,
                         {"refusal_code": None, "candidates": 30},
                         False, [11.0])
    fat = _bench_record("cap", 90, 30, 1.0, BENCHMARK_HEAP_BUDGET_BYTES + 1,
                        {"refusal_code": None, "candidates": 30},
                        False, [1.0])
    assert _benchmark_status([passing]) == 0
    assert _benchmark_status([slow]) == 1
    assert _benchmark_status([fat]) == 1
    assert _benchmark_status([passing, slow]) == 1


def test_the_entrypoint_returns_nonzero_when_a_refresh_breaches_the_budget(
        monkeypatch, capsys):
    """End to end through the real entrypoint. The threshold is lowered rather
    than the work slowed, so this is deterministic and instant."""
    monkeypatch.setitem(globals(), "BENCHMARK_SOFT_REFRESH_SECONDS", 0.0)
    status = _benchmark_main(["--case", "cap", "--total", "90",
                              "--matching", "30"])
    assert status == 1
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == 1
    import json as _json
    record = _json.loads(printed[0])
    assert record["within_soft_refresh_budget"] is False
    assert record["soft_refresh_seconds"] == 0.0


def test_the_entrypoint_returns_zero_when_every_budget_holds(capsys):
    status = _benchmark_main(["--case", "all", "--total", "90",
                              "--matching", "30"])
    assert status == 0
    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == len(BENCHMARK_CASES)
    import json as _json
    for line in printed:
        record = _json.loads(line)
        assert record["within_heap_budget"] is True
        assert record["within_soft_refresh_budget"] is True


def test_the_benchmark_record_still_carries_no_locator_after_the_correction():
    record = run_benchmark_case("failure_recovery", total=60, matching=20)
    text = repr(sorted(record.items()))
    for leak in ("v070_gen", ".npz", "bench/", "Traceback", "Users", "tmp"):
        assert leak not in text


if __name__ == "__main__":  # pragma: no cover - opt-in entrypoint only
    raise SystemExit(_benchmark_main())
