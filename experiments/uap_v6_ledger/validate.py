"""Read-only command-line validator for the attributed UAP V6 ledger."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import sys

from experiments.uap_v6_ledger import schema


MAX_LEDGER_BYTES = 1_048_576


class LedgerPathError(ValueError):
    def __init__(self, token: str, path: tuple[object, ...] = ()) -> None:
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


class LedgerCeilingError(RuntimeError):
    def __init__(self, token: str, path: tuple[object, ...] = ()) -> None:
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


class LedgerInputError(ValueError):
    def __init__(self, token: str, path: tuple[object, ...] = ()) -> None:
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


class _DuplicateKeyError(ValueError):
    pass


def _describe(token: str, path: tuple[object, ...]) -> str:
    if not path:
        return token
    return token + " at " + "/".join(str(part) for part in path)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    seen = set()
    result = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKeyError("duplicate key")
        seen.add(key)
        result[key] = value
    return result


def _read(path: pathlib.Path) -> bytes:
    try:
        details = os.lstat(path)
    except OSError:
        raise LedgerPathError("path-missing") from None
    if stat.S_ISLNK(details.st_mode):
        raise LedgerPathError("path-symlink-refused") from None
    if not stat.S_ISREG(details.st_mode):
        raise LedgerPathError("path-not-regular") from None
    if details.st_size > MAX_LEDGER_BYTES:
        raise LedgerCeilingError("ledger-bytes-ceiling") from None
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_LEDGER_BYTES + 1)
    except OSError:
        raise LedgerPathError("path-read-failed") from None
    if len(data) > MAX_LEDGER_BYTES:
        raise LedgerCeilingError("ledger-bytes-ceiling") from None
    return data


def _parse(data: bytes) -> dict:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise LedgerInputError("json-malformed") from None
    try:
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError:
        raise LedgerInputError("json-duplicate-key") from None
    except (json.JSONDecodeError, RecursionError, ValueError):
        raise LedgerInputError("json-malformed") from None
    try:
        schema.validate_ledger(payload)
    except schema.LedgerError as refusal:
        raise LedgerInputError(refusal.token, refusal.path) from None
    return payload


def validate_file(path: pathlib.Path) -> dict:
    """Return a deterministic summary after complete validation."""

    payload = _parse(_read(path))
    return {
        "batches": len(payload["batches"]),
        "claims": len(payload["claims"]),
        "corpus": payload["corpus"],
        "intake_state": payload["intake_state"],
        "ledger_id": payload["ledger_id"],
        "relationships": len(payload["relationships"]),
        "schema": payload["schema"],
        "sources": len(payload["sources"]),
        "unresolved": len(payload["unresolved"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        summary = validate_file(args.ledger)
    except LedgerInputError as refusal:
        print("error: " + str(refusal), file=sys.stderr)
        return 2
    except LedgerPathError as refusal:
        print("error: " + str(refusal), file=sys.stderr)
        return 4
    except LedgerCeilingError as refusal:
        print("error: " + str(refusal), file=sys.stderr)
        return 5
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
