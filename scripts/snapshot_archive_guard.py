"""Structural and resource admission for unattended snapshot archives.

Three services load ``v070_gen*.npz`` snapshots with nobody watching: the
Medusa REST API (four routes, on a process that binds ``0.0.0.0``), the Lucid
WebSocket server (a directory watcher plus every client connect) and the
geometry export daemon (a directory watcher plus ``--once``). Each already
refuses pickled members, and each already closes its archive deterministically.
Neither property says anything about the archive's *structure* or its *cost*:
a file dropped into ``data/`` could still declare absurd shapes, name members
outside the schema, carry traversal-bearing entries, or expand into hundreds of
gigabytes of allocation before a single value was read.

This module adds the missing admission step. It inspects the ZIP central
directory and each member's NPY header — bounded reads only, no extraction —
and either refuses the archive with a typed, sanitized error or yields the
already-open descriptor for the consumer's own load.

What it does NOT claim
----------------------
Not authentication, not authorization, not atomic writing, not semantic state
validation, not numeric-value validation, not arbitrary NPZ compatibility, and
not protection for any consumer that does not call it. It admits archives that
match one schema — the ``v070_gen`` snapshot contract — and refuses everything
else. An archive that passes admission can still fail downstream on a missing
key or a conversion; those failures are deliberately untouched.

Design notes that matter
------------------------
*One descriptor.* The file is opened exactly once, preflighted on that
descriptor, rewound, and handed to the consumer. A pathname is never validated
and then reopened for loading, so there is no window between the check and the
use.

*Sanitized refusals.* Every refusal carries a fixed reason code from
:data:`REASON_CODES` and nothing else. No path, filename, member name, header
text or underlying exception string ever reaches the message, because these
messages are logged by unattended services and returned (in translated form) to
unauthenticated HTTP callers. The cost is diagnostic granularity: a refusal
says *what kind* of defect was found, never *which member* carried it.

*No compression-ratio threshold.* A legitimate snapshot is mostly void cells
and compresses extremely well; a ratio rule would refuse real inputs. The
controlling resource envelope is absolute and header-derived: declared payload
per member, declared payload in aggregate, and physical archive size.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import re
import stat
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Dict, Iterator, Tuple

__all__ = [
    "SnapshotArchiveRejected",
    "SnapshotArchivePolicy",
    "MemberSpec",
    "PRODUCTION_POLICY",
    "REASON_CODES",
    "admit_snapshot",
    "newest_first",
    "entry_fingerprint",
]


# ---------------------------------------------------------------------------
# Refusal type
# ---------------------------------------------------------------------------

class SnapshotArchiveRejected(ValueError):
    """A snapshot archive was refused before any array was loaded.

    Derives from ``ValueError`` deliberately: the consumers' established
    failure mode for an unloadable archive is already a ``ValueError`` (that is
    what NumPy raises for a pickled member), so callers that only distinguish
    "the snapshot was unusable" keep working unchanged, while the three
    services in this package catch the exact type.

    ``str(exc)`` is exactly ``exc.reason`` — a fixed code, never derived from
    the archive's contents.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


#: Every code :func:`admit_snapshot` can raise. Enumerated so a test can assert
#: that no refusal message outside this set is ever produced, and so a log
#: consumer has a closed vocabulary.
REASON_CODES: Tuple[str, ...] = (
    # selection / containment
    "path_not_confined",
    "path_not_regular_file",
    "path_suffix_not_npz",
    # whole-archive resource envelope
    "archive_too_large",
    "archive_truncated",
    "not_zip_archive",
    "zip64_unsupported",
    "central_directory_too_large",
    "archive_payload_total_too_large",
    # membership
    "member_count",
    "member_name_unsafe",
    "member_is_directory",
    "member_duplicate",
    "member_unexpected",
    "member_missing",
    "member_encrypted",
    "member_flags_unsupported",
    "member_compression_unsupported",
    "member_payload_too_large",
    "member_payload_unreadable",
    # NPY header
    "member_header_unreadable",
    "member_npy_magic_invalid",
    "member_npy_version_unsupported",
    "member_header_too_large",
    "member_header_malformed",
    "member_dtype_object",
    "member_dtype_structured",
    "member_dtype_subarray",
    "member_dtype_zero_itemsize",
    "member_dtype_unsupported",
    "member_dtype_family",
    "member_fortran_order",
    "member_rank",
    "member_shape_invalid",
    "member_size_inconsistent",
    # snapshot geometry
    "lattice_not_cubic",
    "edge_out_of_range",
    "edge_not_multiple",
    "spatial_disagreement",
)


def _reject(reason: str) -> "SnapshotArchiveRejected":
    """Build a refusal, refusing in turn to invent a code outside the roster."""
    if reason not in REASON_CODES:  # pragma: no cover - programmer error only
        raise AssertionError("undeclared snapshot refusal reason")
    return SnapshotArchiveRejected(reason)


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

_KIB = 1024
_MIB = 1024 * 1024

#: Roles, used to attach the cross-member geometry rules to the right members.
ROLE_LATTICE = "lattice"
ROLE_MEMORY_GRID = "memory_grid"
ROLE_SCALAR = "scalar"


@dataclasses.dataclass(frozen=True)
class MemberSpec:
    """The admissible form of one archive member.

    ``kinds`` are NumPy dtype *family* characters, not exact dtypes: the
    producer writes ``uint8``/``float32``/platform ``int``, and documented
    legacy snapshots differ in width, so pinning one exact dtype would refuse
    valid history.

    ``itemsizes`` bounds that freedom to widths NumPy can actually construct.
    The descriptor grammar accepts any letter followed by any digits, so
    ``|u3``, ``<f5`` and ``<i1000`` all parse and all satisfy a family rule --
    and each of them makes ``np.dtype()`` raise a ``TypeError`` whose message
    quotes the attacker's descriptor verbatim, from a call site downstream of
    every ``except SnapshotArchiveRejected``. Admitting a width that cannot
    exist is the same defect as admitting a wrong family, so it is refused
    here rather than by NumPy.
    """

    name: str
    rank: int
    kinds: Tuple[str, ...]
    max_payload_bytes: int
    role: str
    #: Default excludes 16 for the same portability reason as
    #: :data:`_FLOAT_WIDTHS`. Every production spec passes an explicit tuple,
    #: so this only governs a spec built without one — but leaving 16 here
    #: would have quietly readmitted `<f16` through any such spec.
    itemsizes: Tuple[int, ...] = (1, 2, 4, 8)

    @property
    def archive_name(self) -> str:
        return self.name + ".npy"


@dataclasses.dataclass(frozen=True)
class SnapshotArchivePolicy:
    """Immutable admission limits.

    Calibration, so the numbers are auditable rather than arbitrary. The
    compatibility ceiling for this tranche is an edge of 256 cells:

    * lattice at 256³ × 1 byte (``uint8``)            = 16 MiB
    * memory grid at 8 × 256³ × 4 bytes (``float32``) = 512 MiB
    * three scalars, generously                       = 1 MiB
    * aggregate declared uncompressed                 = 529 MiB
    * physical archive, with ZIP framing headroom     = 544 MiB

    A 512³ archive is outside this tranche by construction and is refused.

    Stated rather than implied: under these production numbers the aggregate
    ceiling cannot be the binding constraint. The accumulator sums
    ``ZipInfo.file_size``, which covers each member's NPY header as well as its
    payload, so the true worst case is

        528 MiB + 3 KiB + 5 x 4 KiB = 553,671,680 bytes

    against a ceiling of 554,696,704 — leaving 1,025,024 bytes, exactly
    1001 KiB. It is kept because it is the
    envelope that would otherwise widen silently if a future policy raised one
    member's ceiling, and it is exercised by tests through an injected policy
    rather than by pretending a production archive reaches it.

    ``central_directory_max_bytes`` is a bounded-parsing safeguard rather than
    a production capacity: a five-member snapshot's central directory is a few
    hundred bytes, so 64 KiB is enormous headroom, while it stops a 544 MiB
    file made entirely of central-directory entries from being materialised as
    millions of ``ZipInfo`` objects before any other check could run.

    Tests build tiny variants with :func:`dataclasses.replace`, which is why
    hostile-size behaviour never requires allocating a hostile-sized file.
    """

    members: Tuple[MemberSpec, ...]
    max_members: int = 5
    max_header_bytes: int = 4 * _KIB
    max_total_declared_bytes: int = 529 * _MIB
    max_physical_bytes: int = 544 * _MIB
    central_directory_max_bytes: int = 64 * _KIB
    min_edge: int = 16
    max_edge: int = 256
    edge_multiple: int = 16
    #: Per-dimension sanity bound applied before any multiplication, so a
    #: header declaring 10**300 cells is refused rather than multiplied out.
    max_dimension: int = 2 ** 32

    @property
    def by_archive_name(self) -> Dict[str, MemberSpec]:
        return {spec.archive_name: spec for spec in self.members}


#: Widths NumPy can construct portably, per family.
_INTEGER_WIDTHS = (1, 2, 4, 8)
#: 16-byte floats are deliberately absent. ``float128``/``longdouble`` is not
#: portable -- NumPy 2.3.5 on Windows refuses ``<f16`` outright -- and no
#: snapshot member has ever used one. Admitting a width that a consumer's own
#: NumPy cannot construct would push the failure past the guard, which is the
#: defect the width allowlist exists to prevent.
_FLOAT_WIDTHS = (2, 4, 8)

PRODUCTION_MEMBERS: Tuple[MemberSpec, ...] = (
    MemberSpec("lattice", 3, ("u",), 16 * _MIB, ROLE_LATTICE, _INTEGER_WIDTHS),
    MemberSpec("memory_grid", 4, ("f",), 512 * _MIB, ROLE_MEMORY_GRID,
               _FLOAT_WIDTHS),
    MemberSpec("generation", 0, ("i",), 1 * _KIB, ROLE_SCALAR, _INTEGER_WIDTHS),
    MemberSpec("ca_step", 0, ("i",), 1 * _KIB, ROLE_SCALAR, _INTEGER_WIDTHS),
    MemberSpec("best_fitness", 0, ("f",), 1 * _KIB, ROLE_SCALAR, _FLOAT_WIDTHS),
)

#: The named policy the three services use.
PRODUCTION_POLICY = SnapshotArchivePolicy(members=PRODUCTION_MEMBERS)


# ---------------------------------------------------------------------------
# Bounded NPY header parsing
# ---------------------------------------------------------------------------

_NPY_MAGIC = b"\x93NUMPY"
_SUPPORTED_NPY_VERSIONS = frozenset({(1, 0), (2, 0), (3, 0)})

#: Enough digits for any width in :attr:`MemberSpec.itemsizes`, far short of
#: CPython's integer-string conversion limit.
_MAX_ITEMSIZE_DIGITS = 6

#: ``<f4``, ``|u1``, ``>i8`` ... byte order optional, size digits required.
#: A descriptor NumPy would write for a plain numeric array always matches.
#: ``[0-9]`` rather than ``\d``: a v3.0 NPY header is decoded as UTF-8, and
#: ``\d`` matches the whole Unicode decimal-digit category. A descriptor of
#: ``<i١`` (Arabic-Indic digit one) therefore matched, and ``int()`` -- which
#: also accepts that category -- turned it into a width of 1, admitting a
#: descriptor string no NumPy can construct.
_DESCR_RE = re.compile(r"^(?P<order>[<>|=])?(?P<kind>[a-zA-Z])(?P<size>[0-9]*)$")


class _HeaderSyntaxError(Exception):
    """Internal: the header text is not the restricted literal we accept."""


def _parse_literal(text: str) -> object:
    """Parse the restricted Python-literal subset an NPY header may contain.

    Deliberately *not* :func:`ast.literal_eval` and emphatically not ``eval``.
    The accepted grammar is exactly: dict, tuple, list, single-quoted or
    double-quoted string, decimal integer, ``True``/``False``/``None``. Depth
    and token count are both capped, so a header made of ten thousand nested
    brackets is refused by this parser rather than by the interpreter's
    recursion limit.

    Raises :class:`_HeaderSyntaxError` for anything else, including trailing
    content after the value.
    """
    parser = _LiteralParser(text)
    value = parser.parse_value()
    parser.skip_space()
    if parser.pos != len(parser.text):
        raise _HeaderSyntaxError("trailing content")
    return value


class _LiteralParser:
    MAX_DEPTH = 4
    MAX_TOKENS = 512
    MAX_INT_DIGITS = 20

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.depth = 0
        self.tokens = 0

    # -- helpers -----------------------------------------------------------
    def skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def _peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _expect(self, char: str) -> None:
        if self._peek() != char:
            raise _HeaderSyntaxError("expected " + char)
        self.pos += 1

    def _count(self) -> None:
        self.tokens += 1
        if self.tokens > self.MAX_TOKENS:
            raise _HeaderSyntaxError("too many tokens")

    # -- grammar -----------------------------------------------------------
    def parse_value(self) -> object:
        self._count()
        self.skip_space()
        char = self._peek()
        if not char:
            # `_peek` returns "" at end of input, and "" is a substring of
            # every string -- so without this the dispatch below would treat
            # end-of-input as an opening bracket and recurse until the depth
            # cap fired.
            raise _HeaderSyntaxError("end of input")
        if char == "{":
            return self._parse_dict()
        if char in "([":
            return self._parse_sequence(char)
        if char in "'\"":
            return self._parse_string()
        if self.text.startswith("True", self.pos):
            self.pos += 4
            return True
        if self.text.startswith("False", self.pos):
            self.pos += 5
            return False
        if self.text.startswith("None", self.pos):
            self.pos += 4
            return None
        return self._parse_int()

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > self.MAX_DEPTH:
            raise _HeaderSyntaxError("too deep")

    def _parse_dict(self) -> dict:
        self._enter()
        self._expect("{")
        result: dict = {}
        while True:
            self.skip_space()
            if self._peek() == "}":
                self.pos += 1
                break
            key = self.parse_value()
            if not isinstance(key, str):
                raise _HeaderSyntaxError("non-string key")
            self.skip_space()
            self._expect(":")
            result[key] = self.parse_value()
            self.skip_space()
            if self._peek() == ",":
                self.pos += 1
                continue
            self.skip_space()
            self._expect("}")
            break
        self.depth -= 1
        return result

    def _parse_sequence(self, opener: str) -> object:
        closer = ")" if opener == "(" else "]"
        self._enter()
        self._expect(opener)
        items: list = []
        while True:
            self.skip_space()
            if self._peek() == closer:
                self.pos += 1
                break
            items.append(self.parse_value())
            self.skip_space()
            if self._peek() == ",":
                self.pos += 1
                continue
            self.skip_space()
            self._expect(closer)
            break
        self.depth -= 1
        return tuple(items) if opener == "(" else items

    def _parse_string(self) -> str:
        quote = self._peek()
        self.pos += 1
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] != quote:
            # No escape handling: a descriptor NumPy writes never needs one,
            # and accepting escapes would widen this parser for nothing.
            if self.text[self.pos] == "\\":
                raise _HeaderSyntaxError("escape in string")
            self.pos += 1
        if self.pos >= len(self.text):
            raise _HeaderSyntaxError("unterminated string")
        value = self.text[start:self.pos]
        self.pos += 1
        return value

    #: ASCII decimal digits, spelled out. ``str.isdigit()`` is TRUE for the
    #: whole Unicode digit property -- superscripts, circled numerals and so
    #: on -- while ``int()`` accepts only these ten, so a shape of ``(\xb2,)``
    #: reached ``int()`` and raised a bare ``ValueError``.
    #:
    #: Stated precisely, because the obvious reading overclaims: the ``except``
    #: clause in :func:`_read_member_header` now also covers ``ValueError``, so
    #: that escape is closed twice over and no test can separate the two.
    #: What this line buys on its own is that the parser refuses the input
    #: rather than relying on the conversion to fail -- defence in depth, not
    #: the sole barrier.
    DECIMAL_DIGITS = "0123456789"

    def _parse_int(self) -> int:
        start = self.pos
        if self._peek() == "-":
            self.pos += 1
        digits = 0
        while self._peek() in self.DECIMAL_DIGITS and self._peek():
            self.pos += 1
            digits += 1
            if digits > self.MAX_INT_DIGITS:
                raise _HeaderSyntaxError("integer too long")
        if digits == 0:
            raise _HeaderSyntaxError("not a value")
        return int(self.text[start:self.pos])


@dataclasses.dataclass(frozen=True)
class _MemberHeader:
    """What a member's NPY header declares, once validated as well-formed."""

    kind: str
    itemsize: int
    shape: Tuple[int, ...]
    fortran_order: bool
    header_bytes: int


def _read_member_header(stream, policy: SnapshotArchivePolicy) -> _MemberHeader:
    """Read and validate one member's NPY header from an open member stream.

    Bounded on every axis: at most ``12 + max_header_bytes`` bytes are read,
    the descriptor is matched against a fixed pattern, and the shape is parsed
    by the capped literal parser above. Nothing is decompressed beyond the
    header, and no array is materialised.
    """
    prefix = stream.read(10)
    if len(prefix) < 10:
        raise _reject("member_header_unreadable")
    if prefix[:6] != _NPY_MAGIC:
        raise _reject("member_npy_magic_invalid")

    version = (prefix[6], prefix[7])
    if version not in _SUPPORTED_NPY_VERSIONS:
        raise _reject("member_npy_version_unsupported")

    if version == (1, 0):
        header_len = struct.unpack("<H", prefix[8:10])[0]
        prelude = 10
    else:
        extra = stream.read(2)
        if len(extra) < 2:
            raise _reject("member_header_unreadable")
        header_len = struct.unpack("<I", prefix[8:10] + extra)[0]
        prelude = 12

    if prelude + header_len > policy.max_header_bytes:
        raise _reject("member_header_too_large")

    raw = stream.read(header_len)
    if len(raw) < header_len:
        raise _reject("member_header_unreadable")

    try:
        text = raw.decode("utf-8" if version == (3, 0) else "latin1")
        parsed = _parse_literal(text.strip())
    except (UnicodeDecodeError, _HeaderSyntaxError, ValueError, RecursionError):
        # ``ValueError`` and ``RecursionError`` are belt-and-braces: the parser
        # is written not to raise either, but a header is attacker-controlled
        # and an escape from here would carry its bytes past every
        # ``except SnapshotArchiveRejected`` in the consumers. Nothing derived
        # from the archive may leave this function untyped.
        raise _reject("member_header_malformed") from None

    if not isinstance(parsed, dict) or set(parsed) != {
        "descr", "fortran_order", "shape"
    }:
        raise _reject("member_header_malformed")

    descr = parsed["descr"]
    if isinstance(descr, (list, dict)):
        # A list of field tuples is a structured dtype; a dict is the mapping
        # spelling of one. Either way the member is a record array, which no
        # snapshot member ever is, and which can carry object fields.
        raise _reject("member_dtype_structured")
    if isinstance(descr, tuple):
        # ('<f4', (2, 2)) — a subarray dtype: the declared shape then understates
        # the real element count, so payload arithmetic would be wrong.
        raise _reject("member_dtype_subarray")
    if not isinstance(descr, str):
        raise _reject("member_header_malformed")

    match = _DESCR_RE.match(descr)
    if match is None:
        raise _reject("member_dtype_unsupported")
    kind = match.group("kind")
    if kind == "O":
        raise _reject("member_dtype_object")
    if kind == "V":
        # Void: opaque bytes or an unnamed structured slot. Refused outright
        # rather than sized, because it carries no numeric meaning here.
        raise _reject("member_dtype_structured")
    size_text = match.group("size")
    if not size_text:
        raise _reject("member_dtype_unsupported")
    if len(size_text) > 1 and size_text[0] == "0":
        # `<i000004` normalises to a width of 4 and would pass the allowlist,
        # but NumPy is handed the DESCRIPTOR STRING, not the normalised width.
        # Refusing padded forms keeps the thing checked and the thing used the
        # same thing; NumPy never writes one.
        raise _reject("member_dtype_unsupported")
    if len(size_text) > _MAX_ITEMSIZE_DIGITS:
        # ``int()`` refuses very long decimal strings outright (CPython's
        # integer-string limit), and the header ceiling alone does not bound
        # this below that limit. Refused here so the conversion below cannot
        # raise.
        raise _reject("member_dtype_unsupported")
    itemsize = int(size_text)
    if kind == "U":
        itemsize *= 4  # UCS-4 code points, per the NPY descriptor convention
    if itemsize == 0:
        raise _reject("member_dtype_zero_itemsize")

    fortran_order = parsed["fortran_order"]
    if not isinstance(fortran_order, bool):
        raise _reject("member_header_malformed")

    shape = parsed["shape"]
    if not isinstance(shape, tuple):
        raise _reject("member_header_malformed")
    for dim in shape:
        if not isinstance(dim, int) or isinstance(dim, bool):
            raise _reject("member_header_malformed")
        if dim < 0 or dim > policy.max_dimension:
            raise _reject("member_shape_invalid")

    return _MemberHeader(
        kind=kind,
        itemsize=itemsize,
        shape=shape,
        fortran_order=fortran_order,
        header_bytes=prelude + header_len,
    )


def _declared_payload(header: _MemberHeader, limit: int) -> int:
    """Element count × itemsize, accumulated with an early ceiling.

    Python integers do not overflow, so the hazard is not wraparound but
    unbounded work and unbounded magnitude. Each dimension is already capped by
    :attr:`SnapshotArchivePolicy.max_dimension`; the running product is capped
    here, so the arithmetic stops the moment it exceeds what could ever be
    admitted rather than computing a 300-digit number first.
    """
    total = header.itemsize
    for dim in header.shape:
        total *= dim
        if total > limit:
            return limit + 1
    return total


# ---------------------------------------------------------------------------
# Central-directory inspection
# ---------------------------------------------------------------------------

_EOCD_SIGNATURE = b"PK\x05\x06"
_EOCD_SIZE = 22
_MAX_EOCD_COMMENT = 0xFFFF
_LOCAL_FILE_SIGNATURE = b"PK\x03\x04"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_LOCATOR_SIZE = 20

#: ZIP general-purpose flag bits this guard understands.
_FLAG_ENCRYPTED = 0x0001          # bit 0
_FLAG_COMPRESSED_PATCH = 0x0020   # bit 5, Zip 2.7 compressed patched data
_FLAG_STRONG_ENCRYPTION = 0x0040  # bit 6

_UNSAFE_NAME_RE = re.compile(r"(^/)|(^[A-Za-z]:)|(\\)|(^\.\.$)|(^\.\./)|(/\.\./)|(/\.\.$)|(/)")


#: Slack above the schema's member count that the pre-parse bound tolerates.
#: Its only job is to keep ``ZipFile`` construction bounded; the exact "five
#: members, these five names, each once" rule is enforced afterwards by
#: :func:`_check_member_names`, which is total over the name multiset.
_COUNT_PARSE_SLACK = 8


def _preflight_eocd(fh, size: int, policy: SnapshotArchivePolicy) -> None:
    """Bound the central directory before ``zipfile`` is allowed near it.

    ``ZipFile`` builds one ``ZipInfo`` per central-directory entry as soon as
    it is constructed. On a hostile 544 MiB file made entirely of entries that
    is millions of objects, allocated before any later check could refuse the
    archive. Reading the end-of-central-directory record first — 22 bytes, in a
    window of at most 64 KiB + 22 — gives the declared entry count and
    directory size, both of which are bounded here.

    This is deliberately a *bound*, not the schema check: an archive with four
    members must reach :func:`_check_member_names` and be refused as missing a
    member, not swallowed here as a bad count.
    """
    window = min(size, _EOCD_SIZE + _MAX_EOCD_COMMENT)
    fh.seek(size - window)
    tail = fh.read(window)
    index = tail.rfind(_EOCD_SIGNATURE)
    if index < 0 or len(tail) - index < _EOCD_SIZE:
        raise _reject("not_zip_archive")

    # A ZIP64 end-of-central-directory locator sitting immediately before the
    # 32-bit record makes every field below ADVISORY. CPython's
    # ``zipfile._EndRecData`` looks for that locator and, when it is present,
    # takes the entry count, directory size and directory offset from the
    # ZIP64 record instead -- without requiring the 0xFFFF/0xFFFFFFFF
    # sentinels this function refuses further down. A crafted archive can
    # therefore declare "five entries, a 300-byte directory" here while
    # ``ZipFile`` goes on to build one ``ZipInfo`` per entry from a directory
    # that is orders of magnitude larger; measured at 60,000 entries from a
    # 2.7 MB file, and the physical ceiling permits far more.
    #
    # The condition below is exactly the one ``_EndRecData`` uses, read from
    # the file rather than from the tail window so it cannot be pushed out of
    # range by a comment. A five-member snapshot inside a 544 MiB ceiling
    # never needs ZIP64 -- NumPy's ``force_zip64`` affects only LOCAL headers,
    # and the central directory it writes stays 32-bit -- so the whole
    # extension is refused rather than parsed.
    eocd_offset = size - window + index
    if eocd_offset >= _ZIP64_LOCATOR_SIZE:
        fh.seek(eocd_offset - _ZIP64_LOCATOR_SIZE)
        if fh.read(len(_ZIP64_LOCATOR_SIGNATURE)) == _ZIP64_LOCATOR_SIGNATURE:
            raise _reject("zip64_unsupported")

    record = tail[index:index + _EOCD_SIZE]
    entries_here, entries_total, directory_size, directory_offset = struct.unpack(
        "<HHII", record[8:20])
    if (entries_here == 0xFFFF or entries_total == 0xFFFF
            or directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF):
        # Every CENTRAL ZIP64 sentinel, the directory offset included. The
        # offset one matters as much as the counts: it is the field that says
        # "the real value is in the ZIP64 record", so an archive can carry
        # honest-looking counts and still redirect `zipfile` through ZIP64.
        #
        # This refuses CENTRAL-DIRECTORY ZIP64 structures only. The
        # LOCAL-header ZIP64 length form stays supported and must: NumPy's
        # `savez` opens each member with `force_zip64=True`, which reserves
        # ZIP64 sizes in the local header while the central directory it
        # writes remains 32-bit. Refusing that would refuse every real
        # snapshot. Nothing here inspects local headers.
        raise _reject("zip64_unsupported")
    if entries_here != entries_total:
        raise _reject("member_count")
    if entries_total > policy.max_members + _COUNT_PARSE_SLACK:
        raise _reject("member_count")
    if directory_size > policy.central_directory_max_bytes:
        raise _reject("central_directory_too_large")


def _check_member_names(names: Tuple[str, ...], policy: SnapshotArchivePolicy) -> None:
    """Name safety first, then exact schema membership.

    Name safety runs before the schema comparison on purpose. A traversal- or
    backslash-bearing name would also fail the schema test, but it deserves its
    own code: the schema test alone would report the archive as merely having
    the wrong members, which understates what was found.

    The three membership rules together are exactly "five members, these five
    names, each once": no duplicates, nothing outside the schema, nothing from
    the schema absent. A separate count equality would be unreachable, so none
    is written.
    """
    for name in names:
        if not name or _UNSAFE_NAME_RE.search(name):
            raise _reject("member_name_unsafe")
        if not name.isascii():
            # The schema's five names are ASCII. Anything else is either a
            # different name or an encoding trick, and both are refusals.
            raise _reject("member_name_unsafe")

    seen = set()
    for name in names:
        if name in seen:
            raise _reject("member_duplicate")
        seen.add(name)

    expected = set(policy.by_archive_name)
    if seen - expected:
        raise _reject("member_unexpected")
    if expected - seen:
        raise _reject("member_missing")


def _check_geometry(
    headers: Dict[str, _MemberHeader], policy: SnapshotArchivePolicy
) -> None:
    """Cross-member rules: cubic lattice, admissible edge, agreeing spatial shape."""
    lattice_spec = next(s for s in policy.members if s.role == ROLE_LATTICE)
    grid_spec = next(s for s in policy.members if s.role == ROLE_MEMORY_GRID)
    lattice = headers[lattice_spec.archive_name]
    grid = headers[grid_spec.archive_name]

    edges = lattice.shape
    if len(set(edges)) != 1:
        raise _reject("lattice_not_cubic")
    edge = edges[0]
    if edge < policy.min_edge or edge > policy.max_edge:
        raise _reject("edge_out_of_range")
    if edge % policy.edge_multiple:
        # /api/acoustic reshapes the lattice into 16³ sectors, so an edge that
        # is not a multiple of the sector size cannot be served at all.
        raise _reject("edge_not_multiple")

    if grid.shape[1:] != edges:
        raise _reject("spatial_disagreement")
    if grid.shape[0] < 1:
        # The channel count is bounded by the memory-grid payload ceiling
        # rather than pinned. Stated precisely, because the obvious reading is
        # wrong: this is NOT a claim that a legacy grid is usable. The current
        # producer writes 8 channels; migration for the documented 3- and
        # 5-channel forms lives in `continuous_evolution_ca._migrate_memory_grid`
        # and NONE of the three consumers calls it. Lucid indexes channel 6 and
        # all three index channel 3, so a grid with fewer channels is admitted
        # here and then raises IndexError downstream — exactly as it did before
        # this guard existed. Admission neither introduces that failure nor
        # repairs it; pinning the count would be a new restriction, and
        # refusing every legacy form would be a new policy. Both are out of
        # scope, and the gap is recorded rather than papered over.
        raise _reject("member_shape_invalid")


# ---------------------------------------------------------------------------
# Safe candidate discovery
# ---------------------------------------------------------------------------

def newest_first(paths):
    """Order snapshot candidates newest-first, safely.

    Discovery runs before admission, over a directory an attacker may be able
    to write to, so it has to survive that directory changing underneath it and
    must not itself become a way in. Three properties, each deliberate:

    *Non-following metadata.* ``os.lstat`` describes the directory entry, not
    whatever it points at. Sorting on ``stat`` meant a symlink could borrow its
    target's modification time to promote itself to "newest", and it meant a
    link out of the data directory was followed during ORDERING -- before
    ``admit_snapshot`` had any say.

    *Entries that vanish are skipped silently.* A snapshot rotated or deleted
    between the glob and this call raises ``OSError`` here. Every caller was
    reading that metadata inside a loop whose only handler printed the
    exception, and ``OSError``'s message carries the full path -- a name the
    attacker chose. There is nothing to report: the entry is simply gone.

    *A broken link is still a candidate.* ``lstat`` succeeds on a dangling
    symlink and on a symlink loop, so those are ORDERED rather than filtered.
    That is the point: they reach :func:`admit_snapshot` and are refused with a
    typed reason, instead of disappearing from selection and letting an older
    archive be served with no record of why.

    Ties break on the path so the order is total and reproducible.
    """
    described = []
    for candidate in paths:
        try:
            info = os.lstat(candidate)
        except OSError:
            continue
        described.append((info.st_mtime_ns, os.fspath(candidate), candidate))
    # Newest first, and on a tie the LOWEST path first -- not `reverse=True`
    # over the whole key, which would order tied paths descending. The
    # producer's filenames are `v070_gen{n:06d}_step{m:06d}_{ts}.npz`, and
    # `:06d` is a minimum width that production has already outgrown, so
    # lexicographic order inverts across a digit-count boundary: descending
    # ties would prefer `v070_gen999999...` over `v070_gen1000000...`, i.e.
    # the OLDER snapshot. Ties are only reachable on coarse-granularity
    # storage, but the direction should not be an accident either way.
    described.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in described]


def entry_fingerprint(path):
    """Identify a directory entry by what changes when it changes.

    ``(path, size, mtime_ns)`` from ``os.lstat``, so a symlink is fingerprinted
    as itself rather than as its target -- otherwise a rejected link could be
    made to look "changed" by touching something else entirely, and be retried
    on every poll. Raises ``OSError`` if the entry is gone; callers treat that
    as "look again next time".
    """
    info = os.lstat(path)
    return (os.fspath(path), info.st_size, info.st_mtime_ns)


# ---------------------------------------------------------------------------
# The admission context manager
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def admit_snapshot(
    path,
    *,
    data_dir,
    policy: SnapshotArchivePolicy = PRODUCTION_POLICY,
) -> Iterator:
    """Admit ``path`` as a snapshot archive and yield its open descriptor.

    On success the yielded object is a binary file positioned at 0, already
    preflighted. The caller performs its own load from that same descriptor —
    ``np.load(descriptor, allow_pickle=False)`` — so the bytes that were
    inspected are exactly the bytes that are read. The descriptor is closed
    when the block exits, on success and on every exceptional path; the
    caller's own ``with`` around the returned archive closes the NumPy side,
    which is the arrangement each consumer uses and each consumer's tests pin
    structurally.

    Raises :class:`SnapshotArchiveRejected` — never anything else derived from
    the archive's contents — for every refusal. That includes failures raised
    by the caller's own load out of the yielded descriptor, where they are
    narrowly identifiable as archive transport: see the translation around the
    ``yield`` below.
    """
    try:
        root = Path(os.fspath(data_dir)).resolve()
        candidate = Path(os.fspath(path)).resolve()
    except (OSError, RuntimeError):
        # `resolve()` is not total. A symlink loop raises OSError(ELOOP) on
        # POSIX and RuntimeError on some paths; a path too long or a
        # disappearing component raises OSError too. Uncaught, that left the
        # guard by a route with no reason code and, worse, with the path in the
        # exception message. If the real path cannot be determined then
        # confinement cannot be proved, so the fail-closed answer is the
        # confinement refusal.
        raise _reject("path_not_confined") from None

    if candidate.suffix.lower() != ".npz":
        raise _reject("path_suffix_not_npz")
    if not candidate.is_relative_to(root):
        # Resolution has already followed symlinks, so a link inside the data
        # directory pointing anywhere else is refused here.
        raise _reject("path_not_confined")

    # Opened through os.open with O_NONBLOCK and O_NOFOLLOW where the platform
    # has them (POSIX; both are absent on Windows and default to 0).
    #
    # The regular-file test below cannot protect the OPEN itself, and a plain
    # open() of a FIFO blocks until a writer appears. An attacker who can
    # write to the watched directory could therefore `mkfifo` a
    # `v070_gen*.npz` and hang the caller indefinitely -- which for Lucid means
    # the whole asyncio server, since extraction is synchronous inside the
    # event loop, and for Medusa means one request thread per attempt.
    # O_NONBLOCK makes that open return immediately so S_ISREG can refuse it.
    #
    # O_NOFOLLOW closes the window between resolving the path and opening it:
    # confinement is decided on the resolved path, and without this a symlink
    # swapped in afterwards would still be followed.
    _flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    _flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, _flags)
    except OSError:
        raise _reject("path_not_regular_file") from None

    try:
        fh = os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)
        raise _reject("path_not_regular_file") from None

    try:
        info = os.fstat(fh.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise _reject("path_not_regular_file")
        size = info.st_size
        if size > policy.max_physical_bytes:
            raise _reject("archive_too_large")
        if size < _EOCD_SIZE + len(_LOCAL_FILE_SIGNATURE):
            raise _reject("archive_truncated")
        if fh.read(len(_LOCAL_FILE_SIGNATURE)) != _LOCAL_FILE_SIGNATURE:
            raise _reject("not_zip_archive")

        _preflight_eocd(fh, size, policy)
        _preflight_members(fh, policy)

        fh.seek(0)
        try:
            yield fh
        except SnapshotArchiveRejected:
            # Already typed. Re-raised unchanged so a refusal decided anywhere
            # inside the caller's block keeps its own reason code.
            raise
        except (zipfile.BadZipFile, zlib.error, EOFError):
            # Archive TRANSPORT failures, and only those.
            #
            # Preflight reads each member's header but cannot read its payload
            # without decompressing it, so a valid header over a corrupt body
            # or a wrong CRC is undetectable until NumPy extracts. Left
            # untranslated it surfaced as a raw `zipfile.BadZipFile` -- which
            # is not a `ValueError`, so it sailed past every consumer's typed
            # handler into a 500 with a traceback naming the member.
            #
            # The list is deliberately short. `zipfile.BadZipFile` covers a bad
            # CRC and a malformed local header; `zlib.error` covers corrupt
            # DEFLATE data; `EOFError` covers a stream that ends early. A
            # `MemoryError`, a `KeyboardInterrupt`, an arbitrary `ValueError`
            # -- including NumPy's own "EOF: reading array data" -- and every
            # programmer error stay outside this lane and propagate unchanged.
            # Nothing from the exception's message reaches the reason.
            raise _reject("member_payload_unreadable") from None
    finally:
        fh.close()


def _preflight_members(fh, policy: SnapshotArchivePolicy) -> None:
    """Validate every member's directory entry and NPY header, then geometry.

    Three passes, in this order for a reason. Pass one does only work whose
    cost is independent of what the archive *declares*: directory flags and a
    bounded header read per member. Pass two applies the cross-member geometry
    rules, so a 512³ archive is reported as an out-of-range edge rather than as
    a large payload — both are true, and the edge is the useful one. Pass three
    applies the size arithmetic. Deferring the size verdicts costs nothing,
    because nothing before pass three allocates or reads in proportion to a
    declared size.
    """
    fh.seek(0)
    try:
        archive = zipfile.ZipFile(fh)
    except SnapshotArchiveRejected:
        # Re-raised ahead of the bare ValueError below, which would otherwise
        # silently re-code a refusal raised from within this call as
        # "not_zip_archive". Nothing raises one today; this keeps that true
        # if anything is ever moved inside the try.
        raise
    except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError,
            zlib.error):
        # `NotImplementedError` is the one that had to be added rather than
        # assumed. `ZipFile()`'s constructor reads the central directory, and
        # `_RealGetContents` refuses an entry whose "version needed to
        # extract" exceeds MAX_EXTRACT_VERSION (63) by raising it. Because it
        # subclasses `RuntimeError`, none of the other three clauses caught it,
        # so a single byte set to 255 in each central header made a
        # schema-perfect archive escape the guard untyped -- turning every
        # Medusa snapshot route into a 500 instead of the promised sanitized
        # 503, and wedging the geometry daemon in a retry loop because the
        # broad handler there never records a non-refusal as rejected.
        raise _reject("not_zip_archive") from None

    with archive:
        infos = archive.infolist()
        for entry in infos:
            if entry.is_dir():
                raise _reject("member_is_directory")

        # BOTH the sanitised name and the raw one. `ZipInfo.filename` has
        # already been through `_sanitize_filename` (NUL truncation, backslash
        # folding) and may additionally have been overridden by a 0x7075
        # Unicode-Path extra field, so an entry can present a schema name here
        # while `orig_filename` holds something else entirely -- which CPython
        # then quotes verbatim in its "Overlapped entries" warning, putting
        # attacker-chosen text on an unattended daemon's stderr from an
        # ADMITTED archive.
        _check_member_names(tuple(entry.filename for entry in infos), policy)
        for entry in infos:
            if entry.orig_filename != entry.filename:
                raise _reject("member_name_unsafe")

        specs = policy.by_archive_name
        headers: Dict[str, _MemberHeader] = {}

        # -- pass one: directory entry and bounded header, per member --------
        for entry in infos:
            spec = specs[entry.filename]
            if entry.flag_bits & _FLAG_ENCRYPTED:
                raise _reject("member_encrypted")
            if entry.flag_bits & (_FLAG_COMPRESSED_PATCH | _FLAG_STRONG_ENCRYPTION):
                # Bit 5 is Zip 2.7 "compressed patched data"; bit 6 is strong
                # encryption. Neither can be read, and both are refused HERE,
                # from the central directory, before the member is opened --
                # `zipfile` checks them too, but only once it is already
                # materialising the entry.
                raise _reject("member_flags_unsupported")
            if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise _reject("member_compression_unsupported")

            try:
                member = archive.open(entry)
            except SnapshotArchiveRejected:
                raise  # never re-coded by the broad clause below
            except NotImplementedError:
                # Defensive, and stated as such. `ZipFile.open` raises this for
                # flag bits 5 and 6 -- but it tests `zinfo.flag_bits`, which for
                # `open(ZipInfo)` is the CENTRAL value, so the check above
                # always wins and no crafted archive reaches here. Local-header
                # flag bits are used by CPython only to pick the filename
                # codec, and are ignored by both zipfile and this guard.
                #
                # The clause is kept because `NotImplementedError` subclasses
                # `RuntimeError`: without it, any future CPython that raises it
                # from this call would be reported as an unreadable header, and
                # its message names the flag. Discarded with `from None`.
                raise _reject("member_flags_unsupported") from None
            except (zipfile.BadZipFile, OSError, ValueError, RuntimeError,
                    zlib.error):
                raise _reject("member_header_unreadable") from None
            with member:
                try:
                    header = _read_member_header(member, policy)
                except SnapshotArchiveRejected:
                    raise  # the refusal _read_member_header already decided
                except (zipfile.BadZipFile, OSError, EOFError, zlib.error):
                    # `zlib.error` is the one that is easy to miss: the header
                    # read is bounded, but for a DEFLATED member those bounded
                    # bytes still go through the decompressor, and malformed
                    # compressed data raises `zlib.error` -- which inherits
                    # from `Exception`, not `OSError`, so no other clause here
                    # catches it. Untranslated it escaped the guard entirely.
                    raise _reject("member_header_unreadable") from None

            if header.fortran_order:
                # Fortran order changes the element traversal every consumer
                # assumes, and the producer never writes it.
                raise _reject("member_fortran_order")
            if len(header.shape) != spec.rank:
                raise _reject("member_rank")
            if header.kind not in spec.kinds:
                raise _reject("member_dtype_family")
            if header.itemsize not in spec.itemsizes:
                raise _reject("member_dtype_unsupported")

            headers[entry.filename] = header

        # -- pass two: cross-member geometry ---------------------------------
        _check_geometry(headers, policy)

        # -- pass three: size arithmetic -------------------------------------
        declared_total = 0
        for entry in infos:
            spec = specs[entry.filename]
            header = headers[entry.filename]

            payload = _declared_payload(header, spec.max_payload_bytes)
            if payload > spec.max_payload_bytes:
                raise _reject("member_payload_too_large")
            # ``file_size`` is the member's declared UNCOMPRESSED size, which
            # covers the NPY header as well as the payload — comparing it
            # against a payload ceiling would refuse a snapshot sitting exactly
            # on the limit.
            if header.header_bytes + payload != entry.file_size:
                # The directory's declared uncompressed size and the header's
                # own arithmetic must agree exactly. A mismatch means one of
                # them is lying, and the loader would trust the other.
                raise _reject("member_size_inconsistent")

            declared_total += entry.file_size
            if declared_total > policy.max_total_declared_bytes:
                raise _reject("archive_payload_total_too_large")
