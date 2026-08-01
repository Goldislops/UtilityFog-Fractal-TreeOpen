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
    try:
        if not entries_dir.exists():
            raise LedgerPathError(
                f"entries directory does not exist: {entries_dir}"
            )
        if not entries_dir.is_dir():
            raise LedgerPathError(
                f"entries path is not a directory: {entries_dir}"
            )
        candidates: list[str] = []
        for child in entries_dir.iterdir():
            if not child.name.endswith(".json"):
                continue  # only direct .json entry files are inspected
            if os.path.islink(str(child)):
                raise LedgerPathError(
                    f"{child.name}: symbolic-link entry files are refused"
                )
            if not child.is_file():
                raise LedgerPathError(
                    f"{child.name}: entry path is not a regular file"
                )
            candidates.append(child.name)
        candidates.sort()  # deterministic filename order

        # Ceilings BEFORE any parsing (cheap stat-based checks first).
        if len(candidates) > MAX_ENTRIES:
            raise LedgerCeilingError(
                f"{len(candidates)} entry files exceed the {MAX_ENTRIES}-entry "
                f"ceiling"
            )
        sizes: dict[str, int] = {}
        for name in candidates:
            size = os.lstat(str(entries_dir / name)).st_size
            if size > MAX_ENTRY_BYTES:
                raise LedgerCeilingError(
                    f"{name}: {size} bytes exceed the {MAX_ENTRY_BYTES}-byte "
                    f"per-entry ceiling"
                )
            sizes[name] = size
        total_bytes = sum(sizes.values())
        if total_bytes > MAX_TOTAL_ENTRY_BYTES:
            raise LedgerCeilingError(
                f"{total_bytes} total entry bytes exceed the "
                f"{MAX_TOTAL_ENTRY_BYTES}-byte ceiling"
            )

        entries: list[dict[str, str]] = []
        seen_ids: dict[str, str] = {}
        for name in candidates:
            # Bounded read: the stat-based ceiling above is re-enforced at
            # the read itself, so a file grown between the stat and this
            # read is refused without ever materializing more than the
            # ceiling plus one probe byte (fail closed).
            with (entries_dir / name).open("rb") as f:
                raw = f.read(MAX_ENTRY_BYTES + 1)
            if len(raw) > MAX_ENTRY_BYTES:
                raise LedgerCeilingError(
                    f"{name}: grew past the {MAX_ENTRY_BYTES}-byte per-entry "
                    f"ceiling between inspection and read"
                )
            parsed = _parse_entry_bytes(raw, name)
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

    return {
        "schema": SCHEMA_ID,
        "entry_count": len(entries),
        "total_entry_bytes": total_bytes,
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
    print(f"error: {error}", file=sys.stderr)
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
