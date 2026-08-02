"""Directory validator CLI for ``tech-ledger-v1`` entries.

Usage::

    python -m experiments.tech_ledger.validate <entries-directory>

Inspects the DIRECT ``.json`` files of one directory (no recursion), in
deterministic filename order, with duplicate-key-rejecting JSON parsing,
symlink refusal, and hard ceilings applied BEFORE any parsing. On success
it prints one canonical sorted-key, LF-terminated, timestamp-free JSON
summary carrying relative filenames and entry ids only. It writes
nothing, and it performs no network access.

Exit map (this lab's own; argparse usage errors keep argparse's ordinary
``SystemExit(2)``):

* 0 -- all entries valid
* 2 -- malformed JSON, duplicate JSON key, schema or cross-entry
  validation refusal (typed ``LedgerInputError`` / ``LedgerEntryError``)
* 4 -- missing path, wrong path type, symlink, traversal or
  filesystem-inspection failure (typed ``LedgerPathError``)
* 5 -- entry-count, per-entry-byte or total-byte ceiling breach (typed
  ``LedgerCeilingError``)

Plain unrelated programming exceptions are deliberately NOT caught and
propagate loudly. Schema validity is not scientific validity, endorsement,
implementation authority or evidence that a claim is true.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat as stat_module
import sys
from typing import Any, Final

from experiments.tech_ledger.schema import (
    SCHEMA_ID,
    LedgerEntryError,
    validate_entry,
)

#: Hard bounds, enforced before any JSON parsing (fail closed).
MAX_ENTRIES: Final[int] = 256
MAX_ENTRY_BYTES: Final[int] = 128 * 1024
MAX_TOTAL_ENTRY_BYTES: Final[int] = 4 * 1024 * 1024


class LedgerInputError(ValueError):
    """Malformed JSON, duplicate JSON key or cross-entry refusal (exit 2)."""


class LedgerPathError(ValueError):
    """Missing path, wrong path type, symlink or inspection failure (exit 4)."""


class LedgerCeilingError(RuntimeError):
    """Entry-count, per-entry or total byte-ceiling breach (exit 5)."""


def _pre_open_inspect(path: str, dir_fd: int | None = None) -> os.stat_result:
    """The pre-open no-follow inspection of one candidate.

    A deliberately narrow, production-neutral seam: behaviour is exactly
    ``os.stat(path, dir_fd=dir_fd, follow_symlinks=False)`` -- the
    documented equivalent of ``os.lstat`` -- expressed through ``os.stat``
    because that is the function whose ``dir_fd`` capability CPython
    registers in ``os.supports_dir_fd``; the capture-boundary race tests
    synchronize here.
    """
    return os.stat(path, dir_fd=dir_fd, follow_symlinks=False)


def _dir_fd_binding_supported(
    supports_dir_fd: frozenset | set,
    supports_fd: frozenset | set,
    supports_follow_symlinks: frozenset | set,
    has_o_directory: bool,
) -> bool:
    """Whether every capability the descriptor-bound lane actually needs
    is available: ``os.open(..., dir_fd=...)``, ``os.stat(..., dir_fd=...,
    follow_symlinks=False)`` and ``os.listdir(fd)``, plus ``O_DIRECTORY``.

    Membership is tested for exactly the functions this module calls with
    those parameters, in the registries the documentation assigns to each
    parameter: ``supports_dir_fd`` governs ``dir_fd`` and
    ``supports_follow_symlinks`` governs ``follow_symlinks=False`` -- an
    unsupported ``follow_symlinks=False`` raises ``NotImplementedError``,
    which is not an ``OSError`` and would propagate loudly instead of
    failing closed, so BOTH halves of the inspection call must be
    registered before the lane may be selected.  ``os.lstat`` must NOT be
    consulted here: CPython never registers it in ``os.supports_dir_fd``
    on any build (its ``dir_fd`` support is clinic-gated on the same
    ``fstatat`` capability that registers ``os.stat``), so requiring its
    membership is False everywhere -- including Linux, where all of these
    primitives work.  Pure and injectable so other platforms' capability
    shapes are testable anywhere.
    """
    return (
        os.open in supports_dir_fd
        and os.stat in supports_dir_fd
        and os.stat in supports_follow_symlinks
        and os.listdir in supports_fd
        and has_o_directory
    )


#: Directory-relative descriptor support (POSIX): candidates are
#: enumerated and opened relative to a verified directory descriptor, so
#: the inspected directory object -- not a re-resolved pathname -- is what
#: every operation acts on.
_DIR_FD_SUPPORTED: Final[bool] = _dir_fd_binding_supported(
    os.supports_dir_fd,
    os.supports_fd,
    os.supports_follow_symlinks,
    hasattr(os, "O_DIRECTORY"),
)

try:  # Windows-only standard-library primitives (absent elsewhere)
    import _winapi
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows
    _winapi = None  # type: ignore[assignment]
    msvcrt = None  # type: ignore[assignment]

#: Fallback directory BINDING for platforms without directory-relative
#: descriptors. A Windows directory handle opened without
#: ``FILE_SHARE_DELETE`` denies rename/delete of that directory for as
#: long as it is held, which is a genuine binding over the whole
#: enumeration-to-capture interval -- not an identity recheck. Identity
#: rechecks alone cannot see a swap-and-restore window, so where no
#: binding primitive exists the validator fails closed instead.
_FALLBACK_BINDING_SUPPORTED: Final[bool] = (
    _winapi is not None
    and msvcrt is not None
    and hasattr(_winapi, "CreateFile")
    and hasattr(msvcrt, "open_osfhandle")
)

#: Win32 constants not re-exported by ``_winapi`` (documented values).
_FILE_SHARE_READ: Final[int] = 0x00000001
_FILE_SHARE_WRITE: Final[int] = 0x00000002  # FILE_SHARE_DELETE deliberately absent
_FILE_FLAG_BACKUP_SEMANTICS: Final[int] = 0x02000000  # required to open a directory


def _identity_of(probe: os.stat_result, what: str) -> tuple[int, int]:
    identity = (probe.st_dev, probe.st_ino)
    if identity == (0, 0):
        raise LedgerPathError(
            f"{what}: filesystem identity could not be established (fail closed)"
        )
    return identity


def _refuse_reparse_dir(probe: os.stat_result, what: str) -> None:
    """Refuse a symbolic-link or reparse-point (junction) directory."""
    if stat_module.S_ISLNK(probe.st_mode):
        raise LedgerPathError(f"{what} is a symbolic link (refused)")
    attributes = getattr(probe, "st_file_attributes", 0)
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if attributes & reparse_flag:
        raise LedgerPathError(
            f"{what} is a reparse point (junction or equivalent; refused)"
        )


class _DirBinding:
    """The verified, BOUND entries directory.

    ``fd`` mode (POSIX): enumeration and every candidate open go through
    the held directory descriptor, so every operation acts on the
    inspected directory object itself. ``hold`` mode (Windows): a
    directory handle that denies delete/rename sharing is held for the
    whole interval from before enumeration until after the last capture,
    so the directory cannot be renamed or replaced meanwhile -- including
    during a transient swap-and-restore that no before/after identity
    check could observe. Exactly one of ``fd`` / ``hold_fd`` is set, and
    each is closed exactly once. Neither mode claims protection against a
    genuinely unobservable filesystem or kernel violation.
    """

    def __init__(
        self,
        path: str,
        fd: int | None,
        identity: tuple[int, int],
        hold_fd: int | None = None,
    ):
        self.path = path
        self.fd = fd
        self.identity = identity
        self.hold_fd = hold_fd

    def close(self) -> None:
        for attribute in ("fd", "hold_fd"):
            descriptor = getattr(self, attribute)
            if descriptor is not None:
                setattr(self, attribute, None)  # never close twice
                os.close(descriptor)


def _acquire_fallback_binding(path: str, pre_identity: tuple[int, int]) -> int:
    """Hold the inspected directory open with delete/rename sharing denied.

    Returns a file descriptor owning the directory handle (closing the
    descriptor closes the handle exactly once). The bound object's own
    identity is read via ``os.fstat`` on that descriptor -- not by
    re-resolving the pathname -- and must equal the inspected identity;
    the pathname is then re-inspected once so a reparse point swapped in
    between inspection and acquisition is refused.
    """
    try:
        handle = _winapi.CreateFile(
            path,
            _winapi.GENERIC_READ,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            0,
            _winapi.OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS,
            0,
        )
    except OSError as e:
        raise LedgerPathError(
            f"entries directory could not be bound (fail closed): {e}"
        ) from e
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except OSError as e:  # pragma: no cover - handle ownership not transferred
        _winapi.CloseHandle(handle)
        raise LedgerPathError(
            f"entries directory binding could not be retained (fail closed): {e}"
        ) from e
    try:
        bound = os.fstat(fd)
        if not stat_module.S_ISDIR(bound.st_mode):
            raise LedgerPathError(
                "bound entries handle is not a directory (fail closed)"
            )
        if _identity_of(bound, "entries directory") != pre_identity:
            raise LedgerPathError(
                "entries directory changed between inspection and binding "
                "(fail closed)"
            )
        post = os.lstat(path)
        _refuse_reparse_dir(post, "entries directory")
        if _identity_of(post, "entries directory") != pre_identity:
            raise LedgerPathError(
                "entries directory changed between inspection and binding "
                "(fail closed)"
            )
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_entries_dir(entries_dir: pathlib.Path) -> _DirBinding:
    path = str(entries_dir)
    if not entries_dir.exists():
        raise LedgerPathError(f"entries directory does not exist: {entries_dir}")
    pre = os.lstat(path)
    _refuse_reparse_dir(pre, "entries directory")
    if not stat_module.S_ISDIR(pre.st_mode):
        raise LedgerPathError(f"entries path is not a directory: {entries_dir}")
    pre_identity = _identity_of(pre, "entries directory")
    if _DIR_FD_SUPPORTED:
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if not stat_module.S_ISDIR(opened.st_mode):
                raise LedgerPathError(
                    "entries directory descriptor is not a directory (fail closed)"
                )
            identity = _identity_of(opened, "entries directory")
            if identity != pre_identity:
                raise LedgerPathError(
                    "entries directory changed between inspection and open "
                    "(fail closed)"
                )
        except BaseException:
            os.close(fd)
            raise
        return _DirBinding(path, fd, identity)
    if not _FALLBACK_BINDING_SUPPORTED:
        # No directory-relative descriptors and no fallback binding
        # primitive: refuse BEFORE enumeration rather than presenting
        # identity-only rechecks as a binding they cannot provide.
        raise LedgerPathError(
            "no directory-binding primitive is available on this platform; "
            "refusing to enumerate (fail closed)"
        )
    hold_fd = _acquire_fallback_binding(path, pre_identity)
    return _DirBinding(path, None, pre_identity, hold_fd=hold_fd)


def _verify_binding(binding: _DirBinding) -> None:
    """Cross-check that the bound directory is still the inspected one.

    Defence in depth in BOTH modes: the binding itself (held descriptor
    or held delete-denying handle) is what prevents rename/replacement;
    this check merely surfaces a pathname that no longer resolves to the
    bound object. It is not, and must not be presented as, the binding.
    """
    probe = os.lstat(binding.path)
    _refuse_reparse_dir(probe, "entries directory")
    if not stat_module.S_ISDIR(probe.st_mode):
        raise LedgerPathError(
            "entries directory was replaced by a non-directory (fail closed)"
        )
    if _identity_of(probe, "entries directory") != binding.identity:
        raise LedgerPathError(
            "entries directory was renamed or replaced between enumeration "
            "and capture (fail closed)"
        )


_READ_CHUNK_BYTES: Final[int] = 64 * 1024


def _capture_entry(binding: _DirBinding, name: str) -> bytes:
    """Capture one candidate through a verified descriptor (fail closed),
    bound to the inspected entries directory.

    In ``fd`` mode the candidate is inspected and opened RELATIVE to the
    held directory descriptor (``dir_fd``), never by reconstructing
    ``entries_dir / name``; in ``identity`` mode the directory's identity
    is re-verified immediately before the capture. Then, per entry:
    pre-open no-follow inspection (symlinks and non-regular files
    refused); ``os.open`` without following symlinks where the platform supplies
    ``O_NOFOLLOW``; ``fstat`` of the opened descriptor must be a regular
    file; post-open ``lstat`` must still be a regular non-link path; and
    the three inspections must agree on stable filesystem identity
    (``st_dev``/``st_ino``). Any mismatch, replacement, symlink or
    incomplete identity inspection is a ``LedgerPathError`` (exit 4).
    Bytes are read ONLY through the verified descriptor, bounded by the
    per-entry ceiling plus one probe byte; the pathname is never reopened.
    No protection is claimed against an unobservable filesystem or kernel
    violation.
    """
    if binding.fd is not None:
        dir_fd: int | None = binding.fd
        probe_path = name
    else:
        # The held delete-denying handle is the binding; this cross-check
        # is defence in depth, not the guarantee.
        _verify_binding(binding)
        dir_fd = None
        probe_path = os.path.join(binding.path, name)
    pre = _pre_open_inspect(probe_path, dir_fd=dir_fd)
    if stat_module.S_ISLNK(pre.st_mode):
        raise LedgerPathError(f"{name}: symbolic-link entry files are refused")
    if not stat_module.S_ISREG(pre.st_mode):
        raise LedgerPathError(f"{name}: entry path is not a regular file")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        if dir_fd is not None:
            fd = os.open(name, flags, dir_fd=dir_fd)
        else:
            fd = os.open(probe_path, flags)
    except OSError as e:
        # Under O_NOFOLLOW a symlink swapped in after the pre-open lstat
        # surfaces here (ELOOP); any other open failure is equally a
        # failed capture -- refuse, never fall through.
        raise LedgerPathError(
            f"{name}: entry could not be opened for verified capture "
            f"(fail closed): {e}"
        ) from e
    try:
        opened = os.fstat(fd)
        if not stat_module.S_ISREG(opened.st_mode):
            raise LedgerPathError(
                f"{name}: opened descriptor is not a regular file"
            )
        post = _pre_open_inspect(probe_path, dir_fd=dir_fd)
        if stat_module.S_ISLNK(post.st_mode) or not stat_module.S_ISREG(post.st_mode):
            raise LedgerPathError(
                f"{name}: entry was replaced by a non-regular path during capture"
            )
        identities = {
            (probe.st_dev, probe.st_ino) for probe in (pre, opened, post)
        }
        if len(identities) != 1:
            raise LedgerPathError(
                f"{name}: filesystem identity changed between inspection and "
                f"capture (fail closed)"
            )
        if opened.st_ino == 0 and opened.st_dev == 0:
            # Identity fields unavailable on this filesystem: identity
            # verification would be vacuous, so the capture fails closed
            # rather than silently weakening the symlink refusal.
            raise LedgerPathError(
                f"{name}: filesystem identity could not be established "
                f"(fail closed)"
            )
        chunks: list[bytes] = []
        remaining = MAX_ENTRY_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if len(raw) > MAX_ENTRY_BYTES:
        raise LedgerCeilingError(
            f"{name}: grew past the {MAX_ENTRY_BYTES}-byte per-entry "
            f"ceiling between inspection and read"
        )
    return raw


def _parse_entry_bytes(raw: bytes, filename: str) -> Any:
    """Duplicate-key-rejecting, bounded JSON parse of one entry file."""

    def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise LedgerInputError(
                    f"{filename}: duplicate JSON key {key!r}"
                )
            out[key] = value
        return out

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise LedgerInputError(f"{filename}: not valid UTF-8") from e
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except LedgerInputError:
        raise  # keep the precise duplicate-key message
    except (json.JSONDecodeError, ValueError) as e:
        raise LedgerInputError(f"{filename}: not valid JSON: {e}") from e
    except RecursionError as e:
        raise LedgerInputError(
            f"{filename}: nesting exceeds the parser's depth limit"
        ) from e


def validate_directory(entries_dir: pathlib.Path) -> dict[str, Any]:
    """Validate every direct ``.json`` entry of ``entries_dir``.

    Returns the deterministic summary dict on success; raises the typed
    refusal classes documented in the module docstring. Performs no
    writes and no network access; reads nothing outside ``entries_dir``.
    """
    binding: _DirBinding | None = None
    try:
        # Verify and BIND the entries directory itself: a symbolic-link,
        # junction or equivalent reparse-path directory is refused, and
        # the inspected directory stays bound throughout enumeration and
        # capture (descriptor-relative on platforms that support it,
        # fail-closed identity re-verification elsewhere).
        binding = _open_entries_dir(entries_dir)

        candidates = []
        if binding.fd is not None:
            names = os.listdir(binding.fd)
        else:
            names = os.listdir(binding.path)
        for name in names:
            if not name.endswith(".json"):
                continue  # only direct .json entry files are inspected
            probe = os.stat(
                name if binding.fd is not None else os.path.join(binding.path, name),
                dir_fd=binding.fd,
                follow_symlinks=False,
            )
            if stat_module.S_ISLNK(probe.st_mode):
                raise LedgerPathError(
                    f"{name}: symbolic-link entry files are refused"
                )
            if not stat_module.S_ISREG(probe.st_mode):
                raise LedgerPathError(
                    f"{name}: entry path is not a regular file"
                )
            candidates.append((name, probe.st_size))
        candidates.sort()  # deterministic filename order

        # Ceilings BEFORE any parsing (cheap stat-based checks first).
        if len(candidates) > MAX_ENTRIES:
            raise LedgerCeilingError(
                f"{len(candidates)} entry files exceed the {MAX_ENTRIES}-entry "
                f"ceiling"
            )
        for name, size in candidates:
            if size > MAX_ENTRY_BYTES:
                raise LedgerCeilingError(
                    f"{name}: {size} bytes exceed the {MAX_ENTRY_BYTES}-byte "
                    f"per-entry ceiling"
                )
        total_bytes = sum(size for _, size in candidates)
        if total_bytes > MAX_TOTAL_ENTRY_BYTES:
            raise LedgerCeilingError(
                f"{total_bytes} total entry bytes exceed the "
                f"{MAX_TOTAL_ENTRY_BYTES}-byte ceiling"
            )

        # Rename/replacement detection between enumeration and capture:
        # the bound directory must still be exactly the inspected one.
        _verify_binding(binding)

        # Capture phase: every candidate is captured through the verified
        # descriptor boundary with its EXACT byte count recorded, and the
        # captured aggregate is enforced as it accumulates -- reading
        # stops at the first file whose capture necessarily breaches the
        # total ceiling. Memory stays bounded by the total ceiling plus at
        # most one bounded probe read. NO JSON is parsed until every
        # candidate has been captured and every actual-byte ceiling has
        # passed.
        captured: dict[str, bytes] = {}
        captured_total = 0
        for name, _size in candidates:
            raw = _capture_entry(binding, name)
            captured_total += len(raw)
            if captured_total > MAX_TOTAL_ENTRY_BYTES:
                raise LedgerCeilingError(
                    f"{captured_total} captured total entry bytes exceed the "
                    f"{MAX_TOTAL_ENTRY_BYTES}-byte ceiling"
                )
            captured[name] = raw

        # Parse phase: captured bytes only; the summary's byte totals are
        # the exact captured counts, never the earlier stat sizes.
        entries: list[dict[str, str]] = []
        seen_ids: dict[str, str] = {}
        for name, _size in candidates:
            parsed = _parse_entry_bytes(captured[name], name)
            if type(parsed) is not dict:
                raise LedgerInputError(
                    f"{name}: entry root must be a JSON object"
                )
            validate_entry(parsed)
            entry_id = parsed["entry_id"]
            if entry_id in seen_ids:
                raise LedgerInputError(
                    f"{name}: duplicate entry_id {entry_id!r} (already used "
                    f"by {seen_ids[entry_id]})"
                )
            seen_ids[entry_id] = name
            entries.append(
                {
                    "entry_id": entry_id,
                    "filename": name,
                    "primary_classification": parsed["primary_classification"],
                }
            )
    except (LedgerInputError, LedgerPathError, LedgerCeilingError, LedgerEntryError):
        raise
    except OSError as e:
        raise LedgerPathError(
            f"filesystem inspection could not complete (fail closed): {e}"
        ) from e
    finally:
        if binding is not None:
            binding.close()

    return {
        "schema": SCHEMA_ID,
        "entry_count": len(entries),
        "total_entry_bytes": captured_total,
        "entries": entries,
    }


def serialize_summary(summary: dict[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, LF newline,
    no timestamp, no absolute path."""
    return (
        json.dumps(summary, sort_keys=True, separators=(",", ": "), indent=1)
        + "\n"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tech_ledger.validate",
        description=(
            "Validate tech-ledger-v1 entry files (record structure only; "
            "schema validity is not scientific validity or endorsement). "
            "Argparse usage errors also exit 2."
        ),
    )
    parser.add_argument(
        "entries_dir",
        help="directory whose direct .json files are the entries to validate",
    )
    return parser


def _fail(error: BaseException, code: int) -> int:
    """Exactly ONE physical stderr line per expected failure: carriage
    returns and newlines inside the message (for example from a hostile
    filename) are rendered as visible escapes, then a single terminal
    newline is printed."""
    text = str(error).replace("\r", "\\r").replace("\n", "\\n")
    print(f"error: {text}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        summary = validate_directory(pathlib.Path(args.entries_dir))
    except (LedgerInputError, LedgerEntryError) as e:
        return _fail(e, 2)
    except LedgerPathError as e:
        return _fail(e, 4)
    except LedgerCeilingError as e:
        return _fail(e, 5)
    sys.stdout.write(serialize_summary(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
