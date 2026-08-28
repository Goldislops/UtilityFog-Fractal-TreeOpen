"""Directory validator CLI for ``source-record-v1``.

Phase 0 captures all three data directories through a held directory binding
before anything is parsed: records-root shape, reparse-point refusal, binding
acquisition, directory shape, sorted enumeration, and the resource ceilings
over captured bytes. Phase 1 validates each record in the frozen per-record
order, interleaving the filename and directory checks at their contract
position. Phase 2 applies the set-level rules in the frozen order, deciding
supersession acyclicity before comparing any digest. Phase 3 emits one
deterministic, register-partitioned summary with no combined total.

The validator writes nothing on any path and performs no network access.
Refusals carry exactly a token and a schema-declared path; no input content,
no input path, and no rejected value ever reaches an output channel.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import stat
import sys

from experiments.source_record import schema

try:
    import _winapi
except ImportError:
    _winapi = None

REGISTER_DIRS = ("register-a", "register-b", "bridge")
MAX_RECORDS_PER_DIR = 256
MAX_RECORD_BYTES = 65536
MAX_TOTAL_BYTES = 4194304

_EXPECTED_DIR_SET = frozenset(REGISTER_DIRS)
_REGISTER_BY_SEGMENT = {"A": "register-a", "B": "register-b", "X": "bridge"}

# Win32 constants for the delete- and rename-denying directory hold. Literal
# values, so the hold does not depend on which names a given _winapi build
# exports.
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000


def _describe(token, path):
    if path:
        return token + " at " + "/".join(str(part) for part in path)
    return token


class RecordsPathError(ValueError):
    """A path or binding refusal. Exit class 4."""

    def __init__(self, token, path=()):
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


class RecordsCeilingError(RuntimeError):
    """A resource-ceiling refusal. Exit class 5."""

    def __init__(self, token, path=()):
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


class RecordsInputError(ValueError):
    """A parse, schema, or record refusal. Exit class 2."""

    def __init__(self, token, path=()):
        self.token = token
        self.path = tuple(path)
        super().__init__(_describe(token, self.path))


class _DuplicateKeyError(ValueError):
    pass


def _is_reparse(details):
    if stat.S_ISLNK(details.st_mode):
        return True
    attributes = getattr(details, "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class _DirectoryBinding:
    """A read-only directory binding held across enumeration and capture.

    POSIX: a directory file descriptor; enumeration and every per-entry open
    go through it (``dir_fd``), so the bound directory cannot be swapped
    between enumeration and capture. Windows: a directory handle opened with a
    share mode that denies delete and rename, held for the binding's whole
    lifetime. Where neither primitive exists, construction raises ``OSError``
    and the validator fails closed; an identity re-check is never presented as
    a binding.
    """

    def __init__(self, path):
        self._path = os.fspath(path)
        self.closed = False
        if hasattr(os, "O_DIRECTORY"):
            self._mode = "descriptor"
            self._fd = os.open(
                self._path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
        elif _winapi is not None:
            self._mode = "hold"
            self._handle = _winapi.CreateFile(
                self._path,
                _GENERIC_READ,
                _FILE_SHARE_READ,
                0,
                _OPEN_EXISTING,
                _FILE_FLAG_BACKUP_SEMANTICS,
                0,
            )
        else:
            raise OSError("no directory binding primitive is available")

    def entries(self):
        if self._mode == "descriptor":
            names = os.listdir(self._fd)
        else:
            names = os.listdir(self._path)
        return tuple(sorted(names))

    def read(self, name):
        if self._mode == "descriptor":
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=self._fd,
            )
        else:
            full = os.path.join(self._path, name)
            if _is_reparse(os.lstat(full)):
                raise OSError("reparse-point entry")
            fd = os.open(full, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        try:
            details = os.fstat(fd)
            if not stat.S_ISREG(details.st_mode):
                raise OSError("not a regular file")
            chunks = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(fd)
        return b"".join(chunks)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._mode == "descriptor":
            os.close(self._fd)
        else:
            _winapi.CloseHandle(self._handle)


def _acquire_directory_binding(path):
    # Frozen private seam (CONTRACT.md section 4c): no public configuration,
    # no environment variable, no other mode. When this raises OSError the
    # validator refuses with `path-binding-failed`.
    return _DirectoryBinding(path)


def _reject_duplicate_keys(pairs):
    seen = set()
    for key, _unused in pairs:
        if key in seen:
            raise _DuplicateKeyError("duplicate object key")
        seen.add(key)
    return dict(pairs)


def _parse_record(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise RecordsInputError("json-malformed", ()) from None
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError:
        raise RecordsInputError("json-duplicate-key", ()) from None
    except (json.JSONDecodeError, RecursionError):
        raise RecordsInputError("json-malformed", ()) from None


def _capture(root_path):
    """Phase 0: shape, binding, enumeration, and byte capture, all three
    directories, before any parsing."""
    try:
        details = os.lstat(root_path)
    except OSError:
        raise RecordsPathError("path-missing", ()) from None
    if _is_reparse(details):
        raise RecordsPathError("path-symlink-refused", ()) from None
    if not stat.S_ISDIR(details.st_mode):
        raise RecordsPathError("path-not-directory", ()) from None
    children = os.listdir(root_path)
    for name in sorted(children):
        if name not in _EXPECTED_DIR_SET:
            raise RecordsPathError("records-root-unexpected-entry", ()) from None
    present = set(children)
    for name in REGISTER_DIRS:
        if name not in present:
            raise RecordsPathError(
                "records-root-missing-directory", ()
            ) from None
    captured = []
    running_total = 0
    for dir_name in REGISTER_DIRS:
        dir_path = root_path / dir_name
        try:
            dir_details = os.lstat(dir_path)
        except OSError:
            raise RecordsPathError(
                "records-root-missing-directory", (dir_name,)
            ) from None
        if _is_reparse(dir_details):
            raise RecordsPathError(
                "path-symlink-refused", (dir_name,)
            ) from None
        if not stat.S_ISDIR(dir_details.st_mode):
            raise RecordsPathError(
                "records-root-missing-directory", (dir_name,)
            ) from None
        try:
            binding = _acquire_directory_binding(dir_path)
        except OSError:
            raise RecordsPathError(
                "path-binding-failed", (dir_name,)
            ) from None
        files = []
        try:
            names = tuple(binding.entries())
            for name in names:
                if not name.endswith(".json"):
                    raise RecordsPathError(
                        "record-directory-unexpected-entry", (dir_name,)
                    ) from None
            if len(names) > MAX_RECORDS_PER_DIR:
                raise RecordsCeilingError(
                    "record-count-ceiling", (dir_name,)
                ) from None
            for name in sorted(names):
                try:
                    data = binding.read(name)
                except OSError:
                    raise RecordsPathError(
                        "record-directory-unexpected-entry", (dir_name,)
                    ) from None
                if len(data) > MAX_RECORD_BYTES:
                    raise RecordsCeilingError(
                        "record-bytes-ceiling", (dir_name,)
                    ) from None
                running_total += len(data)
                if running_total > MAX_TOTAL_BYTES:
                    raise RecordsCeilingError(
                        "total-bytes-ceiling", (dir_name,)
                    ) from None
                files.append((name, data))
        finally:
            binding.close()
        captured.append((dir_name, files))
    return captured


def _validate_captured(captured):
    """Phase 1: per-record validation in the frozen order, with the filename
    and directory checks at their contract position."""
    per_register = {}
    for dir_name, files in captured:
        records = {}
        for filename, data in files:
            payload = _parse_record(data)
            try:
                record_id = schema._precheck(payload)
            except schema.SourceRecordError as refusal:
                raise RecordsInputError(refusal.token, refusal.path) from None
            if filename != record_id + ".json":
                raise RecordsInputError(
                    "record-id-filename-mismatch", ("record_id",)
                ) from None
            if _REGISTER_BY_SEGMENT[record_id[3]] != dir_name:
                raise RecordsInputError(
                    "record-id-directory-mismatch", ("record_id",)
                ) from None
            try:
                schema._validate_body(payload, record_id)
            except schema.SourceRecordError as refusal:
                raise RecordsInputError(refusal.token, refusal.path) from None
            records[record_id] = payload
        per_register[dir_name] = records
    return per_register


def _resolve(records, target, path):
    if target not in records:
        raise RecordsInputError("reference-not-found", path) from None


def _refuse_link_cycle(records):
    outgoing = {}
    incoming_degree = {}
    for record_id in sorted(records):
        record = records[record_id]
        if record["record_type"] != "link":
            continue
        left = record["left_ref"]
        right = record["right_ref"]
        outgoing.setdefault(left, []).append(right)
        incoming_degree.setdefault(left, 0)
        incoming_degree[right] = incoming_degree.get(right, 0) + 1
    ready = sorted(
        node for node in incoming_degree if incoming_degree[node] == 0
    )
    remaining = len(incoming_degree)
    while ready:
        node = ready.pop()
        remaining -= 1
        for target in outgoing.get(node, ()):
            incoming_degree[target] -= 1
            if incoming_degree[target] == 0:
                ready.append(target)
    if remaining:
        raise RecordsInputError("reference-cycle", ("left_ref",)) from None


def _validate_set(per_register):
    """Phase 2, in the frozen order. Reference register, reference type, and
    self-reference are enforced per record by the schema and cannot reach this
    phase; the remaining steps run here."""
    for dir_name in REGISTER_DIRS:
        records = per_register[dir_name]
        for record_id in sorted(records):
            record = records[record_id]
            record_type = record["record_type"]
            if record_type == "assertion":
                _resolve(records, record["message_ref"], ("message_ref",))
                _resolve(records, record["subject_ref"], ("subject_ref",))
                derived = record["derived_from"]
                if derived is not None:
                    for position, target in enumerate(derived):
                        _resolve(records, target, ("derived_from", position))
            elif record_type == "link":
                _resolve(records, record["left_ref"], ("left_ref",))
                _resolve(records, record["right_ref"], ("right_ref",))
            elif record_type == "bridge":
                _resolve(
                    per_register["register-a"], record["side_a"], ("side_a",)
                )
                _resolve(
                    per_register["register-b"], record["side_b"], ("side_b",)
                )
            elif record_type == "contradiction":
                _resolve(
                    records,
                    record["left_assertion_ref"],
                    ("left_assertion_ref",),
                )
                _resolve(
                    records,
                    record["right_assertion_ref"],
                    ("right_assertion_ref",),
                )
    for dir_name in ("register-a", "register-b"):
        _refuse_link_cycle(per_register[dir_name])
    seen_pairs = set()
    bridge_records = per_register["bridge"]
    for record_id in sorted(bridge_records):
        record = bridge_records[record_id]
        pair = (record["side_a"], record["side_b"])
        if pair in seen_pairs:
            raise RecordsInputError(
                "bridge-duplicate-pair", ("side_a",)
            ) from None
        seen_pairs.add(pair)
    for dir_name in REGISTER_DIRS:
        records = per_register[dir_name]
        for record_id in sorted(records):
            block = records[record_id]["supersedes"]
            if block is not None and block["record_id"] not in records:
                raise RecordsInputError(
                    "supersedes-target-missing", ("supersedes", "record_id")
                ) from None
    for dir_name in REGISTER_DIRS:
        records = per_register[dir_name]
        successor_by_target = {}
        for record_id in sorted(records):
            block = records[record_id]["supersedes"]
            if block is None:
                continue
            target = block["record_id"]
            if target in successor_by_target:
                raise RecordsInputError(
                    "supersedes-fork-refused", ("supersedes", "record_id")
                ) from None
            successor_by_target[target] = record_id
    # Acyclicity is decided BEFORE any digest is compared: a supersession
    # cycle can never be digest-consistent, so the other order would make
    # `supersedes-cycle` unreachable (CONTRACT.md section 9).
    for dir_name in REGISTER_DIRS:
        records = per_register[dir_name]
        predecessor_of = {}
        for record_id in sorted(records):
            block = records[record_id]["supersedes"]
            if block is not None:
                predecessor_of[record_id] = block["record_id"]
        finished = set()
        for start in sorted(predecessor_of):
            if start in finished:
                continue
            trail = []
            trail_set = set()
            node = start
            while node in predecessor_of and node not in finished:
                if node in trail_set:
                    raise RecordsInputError(
                        "supersedes-cycle", ("supersedes", "record_id")
                    ) from None
                trail.append(node)
                trail_set.add(node)
                node = predecessor_of[node]
            finished.update(trail)
    for dir_name in REGISTER_DIRS:
        records = per_register[dir_name]
        for record_id in sorted(records):
            block = records[record_id]["supersedes"]
            if block is None:
                continue
            predecessor = records[block["record_id"]]
            if schema.digest(predecessor) != block["content_digest"]:
                raise RecordsInputError(
                    "supersedes-digest-mismatch",
                    ("supersedes", "content_digest"),
                ) from None


def validate_records_root(root):
    """Validate one records root; return the register-partitioned summary."""
    root_path = pathlib.Path(os.fspath(root))
    captured = _capture(root_path)
    per_register = _validate_captured(captured)
    _validate_set(per_register)
    return {
        "schema": schema.SCHEMA_ID,
        "registers": {
            dir_name: {
                "record_count": len(per_register[dir_name]),
                "record_ids": sorted(per_register[dir_name]),
            }
            for dir_name in REGISTER_DIRS
        },
    }


def serialize_summary(summary):
    """Canonical serialization of the summary plus exactly one line feed."""
    return (
        json.dumps(
            summary, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        )
        + "\n"
    )


def _report(refusal, exit_class):
    sys.stderr.write("error: " + _describe(refusal.token, refusal.path) + "\n")
    return exit_class


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="source-record-validate",
        description="Validate a source-record records tree.",
    )
    parser.add_argument("root", help="the records root directory")
    namespace = parser.parse_args(argv)
    try:
        summary = validate_records_root(namespace.root)
    except RecordsPathError as refusal:
        return _report(refusal, 4)
    except RecordsCeilingError as refusal:
        return _report(refusal, 5)
    except RecordsInputError as refusal:
        return _report(refusal, 2)
    sys.stdout.write(serialize_summary(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
