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
    """The pre-open ``lstat`` of one candidate.

    A deliberately narrow, production-neutral seam: behaviour is exactly
    ``os.lstat(path, dir_fd=dir_fd)``; the capture-boundary race tests
    synchronize here.
    """
    return os.lstat(path, dir_fd=dir_fd)


#: Directory-relative descriptor support (POSIX): candidates can be
#: enumerated and opened relative to a verified directory descriptor.
#: Where unsupported (Windows), a fail-closed identity mechanism
#: re-verifies the directory before every capture instead -- the claim is
#: never silently weakened.
_DIR_FD_SUPPORTED: Final[bool] = (
    os.open in os.supports_dir_fd
    and os.lstat in os.supports_dir_fd
    and os.listdir in os.supports_fd
    and hasattr(os, "O_DIRECTORY")
)


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
    """The verified, bound entries directory.

    ``fd`` mode (POSIX): enumeration and every candidate open go through
    the held directory descriptor, so capture is inherently bound to the
    originally inspected directory; a path-identity cross-check before
    the capture phase detects rename/replacement. ``identity`` mode
    (platforms without dir_fd): the directory's ``st_dev``/``st_ino``
    identity and non-reparse status are re-verified before every capture,
    failing closed on any change. Neither mode claims protection against
    an unobservable filesystem or kernel violation.
    """

    def __init__(self, path: str, fd: int | None, identity: tuple[int, int]):
        self.path = path
        self.fd = fd
        self.identity = identity

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


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
    post = os.stat(path)
    identity = _identity_of(post, "entries directory")
    if identity != pre_identity:
        raise LedgerPathError(
            "entries directory changed between inspections (fail closed)"
        )
    return _DirBinding(path, None, identity)


def _verify_binding(binding: _DirBinding) -> None:
    """Re-verify the bound directory (rename/replacement detection).

    In ``fd`` mode the original directory object is held open, so this
    check detects a pathname now pointing elsewhere; in ``identity`` mode
    it is the per-capture fail-closed identity mechanism itself.
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
    pre-open ``lstat`` (symlinks and non-regular files refused);
    ``os.open`` without following symlinks where the platform supplies
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
        _verify_binding(binding)  # per-capture fail-closed identity check
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
            probe = os.lstat(
                name if binding.fd is not None else os.path.join(binding.path, name),
                dir_fd=binding.fd,
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
