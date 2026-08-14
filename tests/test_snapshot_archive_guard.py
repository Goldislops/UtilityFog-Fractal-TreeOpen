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
import os
import struct
import warnings
import zipfile
from pathlib import Path

import pytest

from scripts import snapshot_archive_guard as guard

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


@pytest.mark.parametrize("channels", [3, 5, 8])
def test_documented_legacy_memory_grid_depths_are_admitted(root, channels):
    """`continuous_evolution_ca._migrate_memory_grid` documents 3- and
    5-channel grids alongside the current 8, so the channel count is bounded
    by the memory-grid payload ceiling rather than pinned."""
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

    `MemoryError`, `KeyboardInterrupt`, an arbitrary `ValueError` -- NumPy's
    own "EOF: reading array data" among them -- and every programmer error must
    leave the block exactly as they were raised. Only archive transport is
    translated.
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
    assert real_resolve is not None


@pytest.mark.parametrize("digits", ["١", "٤", "۸"], ids=["arabic_one",
                                                        "arabic_four",
                                                        "extended_eight"])
def test_a_non_ascii_digit_width_is_refused(root, digits):
    """A v3.0 header is decoded as UTF-8, and `\\d` matches the whole Unicode
    decimal-digit category — as does `int()`. So `<i١` parsed as a width of 1
    and was admitted, describing a dtype no NumPy can construct."""
    members = schema_members(16)
    # A payload of exactly one byte, matching the width the non-ASCII digit
    # decodes to. Without it the archive is refused for a size mismatch and the
    # dtype rule is never reached -- which would make this test pass for the
    # wrong reason, and would have passed before the fix too.
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
    assert imported <= {"__future__", "contextlib", "dataclasses", "os", "re",
                        "stat", "struct", "zipfile", "zlib", "pathlib",
                        "typing"}


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
