"""Deterministic evidence packet over recorded Nextness artifacts (NP8).

Builds one compact, offline AUDIT MANIFEST over up to eight recorded
artifacts from the Nextness stack — NP1 reports, NP2 receipt series,
NP5 evaluations, NP6 lab reports/protocols and the underlying JSONL
log — recording for each its schema, byte length and SHA-256, and
verifying the provenance links the schemas themselves record (an NP5
evaluation carries the sha256 of the report/receipts it evaluated; an
NP6 lab report carries the sha256 of its protocol bytes and of the
accepted dominant-token sequence).

This is packaging and provenance verification — NOT a new prediction
metric. Nothing here scores, ranks, recommends, tunes, acts, invokes a
model or contacts a service, and no consciousness, awareness,
phenomenology or biological-equivalence claim is made or implied.

Honesty contract:

- Artifacts are validated through the EXISTING validators: NP5's
  ``validate_report`` / ``validate_receipt_series``, NP6's
  ``load_protocol``, and — for the evaluation and lab-report roles —
  NP9's public structural validators
  (``scripts.nextness_artifact_validation``), so every JSON role is
  now fully structurally validated and its manifest entry records
  ``validation: "full"`` honestly. The emitted packet is itself
  checked against NP9's packet validator before serialization.
  Structural validation is still not provenance verification: the
  hash links below remain independently recomputed by this module.
- A provenance link whose counterpart artifact was not provided is a
  typed ``not_computable`` result, never a failure and never invented.
- A link that IS checkable is reported ``verified`` or ``broken`` by
  byte-level hash comparison. The sequence link recomputes the
  dominant-token sequence through NP1's own bounded reader using the
  LAB'S OWN RECORDED ``max_rows`` / ``max_line_bytes`` (exact-type
  validated against NP1/NP6's acceptance ranges and echoed in the link
  as ``reader_bounds``) — never default bounds, which would report a
  genuine non-default pair broken; when no lab is provided, no bounds
  are invented.
- ``evaluation.artifacts.<role>.provided`` is an EXACT builtin bool:
  ``true`` requires and verifies the recorded sha256, ``false`` is
  typed ``link_not_recorded``, and any other value is malformed input
  (fail closed) — a truthy non-bool can never suppress verification.
- Each JSON artifact is parsed exactly once (spy-tested); the log is
  size-checked via stat BEFORE any read and hashed in fixed-size
  chunks under its own ``MAX_LOG_BYTES`` ceiling — never materialized
  whole.

Safety contract (Lane B, mirrors NP5/NP6):

- Offline only; reads only the artifact files named on the command
  line, each through a hard pre-parse size bound; duplicate JSON keys
  and hostile container subclasses are rejected fail-closed.
- At most ``MAX_PACKET_ARTIFACTS`` artifacts; output checked against a
  64 KiB fail-closed ceiling.
- ``--output`` is confined to the primary input's directory, never the
  repository ``data/`` tree, and never a path aliasing ANY input (by
  resolved path and by file identity — hard links included; the same
  validation-time semantics and documented residual race as NP6).
- Deterministic: sorted keys, fixed schema, no timestamps, no random
  identifiers, no absolute paths; byte-identical across repeated runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from collections.abc import Mapping
from typing import Any, Final

from scripts.nextness_evaluator import (
    EVALUATION_SCHEMA,
    MAX_INPUT_BYTES,
    EvaluatorInputError,
    validate_receipt_series,
    validate_report,
)
from scripts.nextness_monitor import RECEIPT_SCHEMA
from scripts.nextness_observer import WriteOutsideLogDirError
from scripts.nextness_predictor import (
    MAX_LINE_BYTES_CEILING,
    MAX_LINE_BYTES_DEFAULT,
    MAX_ROWS_CEILING,
    MAX_ROWS_DEFAULT,
    REPORT_SCHEMA,
    read_dominant_sequence,
)
from scripts.nextness_replay_lab import (
    LAB_SCHEMA,
    PROTOCOL_SCHEMA,
    LabInputError,
    load_protocol,
)

# ---------------------------------------------------------------------------
# Fixed contract constants
# ---------------------------------------------------------------------------

PACKET_SCHEMA: Final[str] = "nextness-evidence-packet-v1"

#: One artifact per role, fixed role order (also the manifest order).
ROLES: Final[tuple[str, ...]] = (
    "report", "receipts", "evaluation", "lab", "protocol", "log",
)

#: Hard bound on artifacts per packet (the role set caps this at six
#: today; the bound is the documented contract either way).
MAX_PACKET_ARTIFACTS: Final[int] = 8

#: Output ceiling — fail closed (same convention as the whole stack).
MAX_PACKET_BYTES: Final[int] = 64 * 1024

#: Role-specific ceiling for the raw log (JSON artifacts keep the 1 MiB
#: MAX_INPUT_BYTES). This is NP8's OWN explicit packaging/work ceiling,
#: chosen so the chunked hash and the bounded sequence read stay cheap
#: and testable. It is NOT derived as coverage of NP1's defaults:
#: observer rows carry more than a generation and token counts
#: (timestamps, filenames, lattice shape, sampling information,
#: metrics, diagnostics, a nested budget block), so no claim is made
#: about what fraction of real or default-configuration logs fit until
#: that is measured. An otherwise-valid larger log is refused
#: fail-closed. The size is checked via stat BEFORE any read,
#: re-enforced during the chunked read, and the log is hashed in
#: fixed-size chunks — never materialized whole.
MAX_LOG_BYTES: Final[int] = 16 * 1024 * 1024
_HASH_CHUNK_BYTES: Final[int] = 64 * 1024

#: Provenance links the v1 schemas record (fixed vocabulary).
LINK_KINDS: Final[tuple[str, ...]] = (
    "evaluation_report_sha256",    # evaluation.artifacts.report.sha256   -> report bytes
    "evaluation_receipts_sha256",  # evaluation.artifacts.receipts.sha256 -> receipts bytes
    "lab_protocol_sha256",         # lab.input.protocol_sha256            -> protocol bytes
    "lab_sequence_sha256",         # lab.input.sequence_sha256            -> log's accepted sequence
)

#: Typed not-computable vocabulary for links.
LINK_NOT_COMPUTABLE_REASONS: Final[tuple[str, ...]] = (
    "counterpart_absent",   # the artifact on one end was not provided
    "link_not_recorded",    # the recording artifact did not embed the hash
)

NON_CLAIMS: Final[tuple[str, ...]] = (
    "Packaging and provenance verification only: nothing here scores, "
    "ranks, recommends, tunes, acts, invokes a model or contacts a "
    "service.",
    "A not_computable link is a statement about which artifacts were "
    "provided, not about the artifacts' integrity.",
    "No awareness, consciousness, phenomenology or biological-equivalence "
    "claim is made or implied.",
)

_SCHEMA_BY_ROLE: Final[dict[str, str]] = {
    "report": REPORT_SCHEMA,
    "receipts": RECEIPT_SCHEMA,
    "evaluation": EVALUATION_SCHEMA,
    "lab": LAB_SCHEMA,
    "protocol": PROTOCOL_SCHEMA,
}

_HEX64: Final[frozenset[str]] = frozenset("0123456789abcdef")


class PacketInputError(ValueError):
    """A malformed, hostile or unknown-variant packet input (fail closed)."""


class PacketTooLargeError(RuntimeError):
    """Serialized packet exceeded MAX_PACKET_BYTES (fail closed)."""


# ---------------------------------------------------------------------------
# Bounded loading (duplicate keys rejected; exact types on touched fields)
# ---------------------------------------------------------------------------


def _load_bounded_json(path: pathlib.Path) -> tuple[Any, str, int]:
    """Bounded read + duplicate-key-rejecting parse.

    Returns ``(parsed, sha256_hex, byte_count)``; at most
    ``MAX_INPUT_BYTES + 1`` bytes are ever materialized.
    """
    with path.open("rb") as f:
        raw = f.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise PacketInputError(f"artifact exceeds {MAX_INPUT_BYTES} bytes; refusing to parse")

    def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise PacketInputError(f"artifact: duplicate JSON key {key!r}")
            out[key] = value
        return out

    try:
        parsed = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_no_duplicate_keys)
    except PacketInputError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        raise PacketInputError(f"artifact is not valid UTF-8 JSON: {e}") from e
    except RecursionError as e:
        raise PacketInputError("artifact nesting exceeds the parser's depth limit") from e
    return parsed, hashlib.sha256(raw).hexdigest(), len(raw)


_BUILTIN_TYPE_NAMES: Final[tuple[tuple[type, str], ...]] = (
    (bool, "bool"),  # before int: bool is an int subclass
    (int, "int"),
    (float, "float"),
    (str, "str"),
    (list, "list"),
    (dict, "dict"),
    (tuple, "tuple"),
    (set, "set"),
    (bytes, "bytes"),
    (type(None), "NoneType"),
)


def _describe_type(value: Any) -> str:
    """Hook-free type description for error messages.

    ``type(value).__name__`` consults the metaclass — a hostile class can
    override ``__name__`` so that reading it raises from inside error
    formatting, escaping the validator's typed-error promise. Identity
    comparison against builtin types runs no user code, and anything that
    is not one of these builtins is described generically instead of
    executing a hook merely to improve a message.
    """
    value_type = type(value)
    for builtin, name in _BUILTIN_TYPE_NAMES:
        if value_type is builtin:
            return name
    return "non-builtin value"


def _exact_dict_field(container: Any, field: str, context: str) -> Any:
    """Fetch ``field`` from a proven-exact builtin dict, hook-free.

    The container is proven an exact builtin ``dict`` first, then traversed
    by ITEM ITERATION only: an unproven key is never hashed, compared,
    stringified or represented, and only exact builtin ``str`` keys are
    compared against ``field``. The matched value comes straight out of the
    iteration — never from a second subscript, which would re-enter the hash
    table and could meet a colliding hostile key.

    This is a soundness boundary, not only a hook boundary. Previously
    ``field not in container`` hashed ``field`` and compared it against
    whatever shared its bucket, so a non-str key whose ``__hash__`` collided
    with a required name had its ``__eq__`` invoked — and an ``__eq__``
    returning True let that hostile key SATISFY the required field and
    supply its own value as the field's content.
    """
    if type(container) is not dict:
        raise PacketInputError(f"{context}: expected builtin dict, got {_describe_type(container)}")
    for key, value in container.items():
        # Identity test first: a foreign key short-circuits before any
        # comparison, so no caller-controlled hook can run.
        if type(key) is str and key == field:
            return value
    raise PacketInputError(f"{context}: missing field {field!r}")


def _exact_role_map(mapping: Any) -> dict[str, Any]:
    """Normalize the TOP-LEVEL role map once, at the DIRECT-API boundary.

    The public CLI always builds this map itself with exact builtin ``str``
    roles, so every hazard below is DIRECT-API-only. A direct caller,
    however, may pass any mapping, and the outer map used to be consumed
    with ``set(paths)``, ``role in paths``, ``paths[role]`` and
    ``inputs[role]`` — each of which hashes and compares caller-controlled
    keys, while the unknown-roles message rendered them inside a list and
    therefore ``repr``'d them.

    Three things could follow: a foreign key's ``__hash__``/``__eq__``/
    ``__repr__`` could execute and escape; a foreign key colliding with a
    real role and comparing equal could SATISFY that role and supply its
    own value as the artifact (or as the primary input); and a ``dict``
    subclass could interpose its own iteration hooks.

    This boundary refuses anything that is not an exact builtin ``dict``
    without inspecting it beyond that identity test, traverses by item
    iteration only, admits a key only on exact builtin ``str`` identity —
    never hashing, comparing, stringifying or representing a foreign key —
    and returns a FRESH exact dict. Every later membership test, lookup,
    ``.get()`` and primary-role selection uses only that normalized dict.
    A foreign key is rejected even when a genuine role is also present; it
    is never silently dropped.

    This boundary enforces the COMPLETE role-map grammar, in order: exact
    builtin ``dict`` identity · emptiness · the artifact-count ceiling
    (both decided with exact-dict operations BEFORE any key is traversed)
    · item iteration admitting exact builtin ``str`` keys only · unknown
    exact-string roles · a fresh dict containing only proven known roles.
    Both public entry points rely on it exclusively and repeat none of it.

    DIRECT-API behavior is therefore deliberately CHANGED, not preserved:
    a direct caller that previously got an unknown-role listing for an
    oversized map now gets the short ceiling refusal, and one that
    previously reached ``StopIteration`` (or silently skipped an unknown
    role while validating an output path) now gets a typed refusal. The
    PUBLIC CLI is unaffected — it builds this map itself from known roles.
    """
    if type(mapping) is not dict:
        raise PacketInputError("artifact role map: expected a builtin dict")
    # Emptiness and the artifact ceiling are decided with exact-dict
    # operations BEFORE any key is traversed, so an oversized map can
    # never be iterated, rendered, or reach a hostile key's hooks — and
    # its diagnostic stays short instead of listing every supplied key.
    if not mapping:
        raise PacketInputError("no artifacts provided: nothing to package")
    if len(mapping) > MAX_PACKET_ARTIFACTS:
        raise PacketInputError(
            f"{len(mapping)} artifacts exceed the {MAX_PACKET_ARTIFACTS} bound"
        )
    normalized: dict[str, Any] = {}
    foreign = False
    for key, value in mapping.items():
        if type(key) is str:
            normalized[key] = value
        else:
            foreign = True
    if foreign:
        raise PacketInputError("artifact role map: role keys must be builtin strings")
    # Unknown roles are decided on proven exact strings only.
    unknown = sorted(set(normalized) - set(ROLES))
    if unknown:
        raise PacketInputError(f"unknown artifact roles: {unknown}")
    return normalized


def _exact_sha256(value: Any, context: str) -> str:
    if type(value) is not str or len(value) != 64 or not set(value) <= _HEX64:
        raise PacketInputError(f"{context}: expected a 64-char lowercase hex sha256")
    return value


def _schema_of(parsed: Any, role: str) -> str:
    schema = _exact_dict_field(parsed, "schema", role)
    if type(schema) is not str:
        raise PacketInputError(f"{role}.schema: expected builtin str")
    expected = _SCHEMA_BY_ROLE[role]
    if schema != expected:
        raise PacketInputError(
            f"{role}.schema: unknown variant {schema!r} (expected {expected!r})"
        )
    return schema


# ---------------------------------------------------------------------------
# Per-role validation (existing validators where they exist)
# ---------------------------------------------------------------------------


def _validate_role(role: str, path: pathlib.Path) -> tuple[dict[str, Any], Any]:
    """One manifest entry plus the parsed object (``None`` for the log).

    Each JSON artifact is parsed exactly ONCE — the parsed object is
    returned so the link stage never re-reads the file. ``validation``
    records the honest depth.
    """
    if role == "log":
        # The log is not JSON; it enters the stack only through NP1's
        # bounded reader. Size is checked BEFORE any read, re-enforced
        # during the chunked hash (the file could grow in between), and
        # the log is never materialized whole. The manifest records the
        # raw-byte hash plus the accepted-sequence hash under NP1's
        # DEFAULT reader bounds (echoed for reproducibility); the lab
        # sequence LINK recomputes with the lab's own recorded bounds.
        size = path.stat().st_size
        if size > MAX_LOG_BYTES:
            raise PacketInputError(f"log exceeds {MAX_LOG_BYTES} bytes; refusing to process")
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as f:
            while True:
                chunk = f.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_LOG_BYTES:
                    raise PacketInputError(
                        f"log exceeds {MAX_LOG_BYTES} bytes; refusing to process"
                    )
                digest.update(chunk)
        sequence, _rejections, _rows = read_dominant_sequence(path)
        entry = {
            "role": "log",
            "schema": "jsonl-nextness-runs",
            "bytes": total,
            "sha256": digest.hexdigest(),
            "sequence_sha256": hashlib.sha256("\n".join(sequence).encode("utf-8")).hexdigest(),
            "sequence_bounds": {
                "max_rows": MAX_ROWS_DEFAULT,
                "max_line_bytes": MAX_LINE_BYTES_DEFAULT,
            },
            "rows_accepted": len(sequence),
            "validation": "sequence_reader",
        }
        return entry, None

    parsed, digest, size = _load_bounded_json(path)
    entry: dict[str, Any] = {
        "role": role,
        "bytes": size,
        "sha256": digest,
    }
    try:
        if role == "report":
            entry["schema"] = _schema_of(parsed, role)
            validate_report(parsed)
            entry["validation"] = "full"
        elif role == "receipts":
            # A receipts artifact may be one receipt or a JSON array of
            # receipts; an array has no top-level schema field, so the
            # schema check is the series validator's own per-receipt
            # check, not _schema_of.
            series = validate_receipt_series(parsed)
            entry["schema"] = RECEIPT_SCHEMA
            entry["receipt_count"] = len(series)
            entry["validation"] = "full"
        elif role == "protocol":
            entry["schema"] = _schema_of(parsed, role)
            load_protocol(path)  # bounded re-read through NP6's own loader
            entry["validation"] = "full"
        else:
            # evaluation / lab: full structural validation through the
            # NP9 public validators (resolved lazily at call time — the
            # NP9 module imports this module's constants, so a
            # top-level import here would be a cycle).
            validation = _np9()
            entry["schema"] = _schema_of(parsed, role)
            try:
                if role == "evaluation":
                    validation.validate_evaluation_artifact(parsed)
                else:
                    validation.validate_lab_artifact(parsed)
            except validation.ArtifactValidationError as e:
                raise PacketInputError(f"{role}: {e}") from e
            entry["validation"] = "full"
    except (EvaluatorInputError, LabInputError) as e:
        raise PacketInputError(f"{role}: {e}") from e
    return entry, parsed


def _np9():
    """The NP9 validation module, imported lazily to avoid the import
    cycle (NP9 imports this module's constants). Resolution happens at
    call time so tests can monkeypatch the NP9 module's attributes."""
    import scripts.nextness_artifact_validation as validation

    return validation


# ---------------------------------------------------------------------------
# Provenance links (verified / broken / typed not-computable)
# ---------------------------------------------------------------------------


def _link(status: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, **extra}


def _not_computable_link(reason: str, requires: str) -> dict[str, Any]:
    if reason not in LINK_NOT_COMPUTABLE_REASONS:  # internal invariant
        raise ValueError(f"unknown link reason: {reason!r}")
    return {"status": "not_computable", "reason": reason, "requires": requires}


def _evaluation_link(
    evaluation: Mapping[str, Any] | None,
    counterpart_role: str,
    counterpart_entry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if evaluation is None:
        return _not_computable_link("counterpart_absent", "an evaluation artifact")
    artifacts = _exact_dict_field(evaluation, "artifacts", "evaluation")
    slot = _exact_dict_field(artifacts, counterpart_role, "evaluation.artifacts")
    provided = _exact_dict_field(slot, "provided", f"evaluation.artifacts.{counterpart_role}")
    # EXACT builtin bool only. A truthy or falsy non-bool (1, "true",
    # [], ...) must never silently suppress verification by sliding into
    # the not-recorded branch — it is malformed input, fail closed.
    if type(provided) is not bool:
        raise PacketInputError(
            f"evaluation.artifacts.{counterpart_role}.provided: expected "
            f"builtin bool, got {_describe_type(provided)}"
        )
    if provided is False:
        return _not_computable_link(
            "link_not_recorded",
            f"an evaluation produced WITH a {counterpart_role} artifact "
            f"(this one records provided: false)",
        )
    recorded = _exact_sha256(
        _exact_dict_field(slot, "sha256", f"evaluation.artifacts.{counterpart_role}"),
        f"evaluation.artifacts.{counterpart_role}.sha256",
    )
    if counterpart_entry is None:
        return _not_computable_link("counterpart_absent", f"the {counterpart_role} artifact itself")
    actual = counterpart_entry["sha256"]
    return _link(
        "verified" if recorded == actual else "broken",
        recorded_sha256=recorded,
        actual_sha256=actual,
    )


def _recorded_reader_bounds(lab: Mapping[str, Any]) -> tuple[int, int]:
    """The lab's recorded ingestion bounds, exact-type validated against
    the same acceptance ranges NP1/NP6 enforce (fail closed on bool,
    float, string, negative, zero or out-of-range values)."""
    cfg = _exact_dict_field(lab, "config", "lab")
    max_rows = _exact_dict_field(cfg, "max_rows", "lab.config")
    if type(max_rows) is not int:
        raise PacketInputError(
            f"lab.config.max_rows: expected builtin int, got {_describe_type(max_rows)}"
        )
    if not 0 < max_rows <= MAX_ROWS_CEILING:
        raise PacketInputError(
            f"lab.config.max_rows: {max_rows} outside (0, {MAX_ROWS_CEILING}]"
        )
    max_line_bytes = _exact_dict_field(cfg, "max_line_bytes", "lab.config")
    if type(max_line_bytes) is not int:
        raise PacketInputError(
            f"lab.config.max_line_bytes: expected builtin int, got {_describe_type(max_line_bytes)}"
        )
    if not 1 <= max_line_bytes <= MAX_LINE_BYTES_CEILING:
        # Defensive ceiling: enforced here at extraction even if
        # upstream validation changes later, so the reader replay below
        # can never receive an index-overflowing bound.
        raise PacketInputError(
            f"lab.config.max_line_bytes: {max_line_bytes} outside "
            f"[1, {MAX_LINE_BYTES_CEILING}]"
        )
    return max_rows, max_line_bytes


def _lab_protocol_link(
    lab: Mapping[str, Any] | None,
    protocol_entry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if lab is None:
        return _not_computable_link("counterpart_absent", "a lab-report artifact")
    inp = _exact_dict_field(lab, "input", "lab")
    recorded = _exact_sha256(
        _exact_dict_field(inp, "protocol_sha256", "lab.input"), "lab.input.protocol_sha256"
    )
    if protocol_entry is None:
        return _not_computable_link("counterpart_absent", "the protocol artifact")
    actual = protocol_entry["sha256"]
    return _link(
        "verified" if recorded == actual else "broken",
        recorded_sha256=recorded,
        actual_sha256=actual,
    )


def _lab_sequence_link(
    lab: Mapping[str, Any] | None,
    log_path: pathlib.Path | None,
) -> dict[str, Any]:
    """The sequence link recomputes the accepted dominant-token sequence
    with the LAB'S OWN RECORDED reader bounds — a lab produced under
    non-default ``max_rows`` / ``max_line_bytes`` accepted a different
    sequence than the defaults would, and comparing against a
    default-bounds recomputation would report a genuine pair broken.
    When no lab is provided, no bounds are invented."""
    if lab is None:
        return _not_computable_link("counterpart_absent", "a lab-report artifact")
    max_rows, max_line_bytes = _recorded_reader_bounds(lab)
    inp = _exact_dict_field(lab, "input", "lab")
    recorded = _exact_sha256(
        _exact_dict_field(inp, "sequence_sha256", "lab.input"), "lab.input.sequence_sha256"
    )
    if log_path is None:
        return _not_computable_link("counterpart_absent", "the log artifact")
    sequence, _rejections, _rows = read_dominant_sequence(
        log_path, max_rows=max_rows, max_line_bytes=max_line_bytes
    )
    actual = hashlib.sha256("\n".join(sequence).encode("utf-8")).hexdigest()
    return _link(
        "verified" if recorded == actual else "broken",
        recorded_sha256=recorded,
        actual_sha256=actual,
        reader_bounds={"max_rows": max_rows, "max_line_bytes": max_line_bytes},
    )


# ---------------------------------------------------------------------------
# End-to-end packet
# ---------------------------------------------------------------------------


def build_packet(paths: dict[str, pathlib.Path]) -> dict[str, Any]:
    """One deterministic ``nextness-evidence-packet-v1`` manifest.

    ``paths`` must be an EXACT builtin ``dict`` mapping known roles
    (subset of ROLES, at least one, at most ``MAX_PACKET_ARTIFACTS``) to
    files. Manifest order is the fixed ROLES order regardless of
    invocation order — determinism over convenience.

    The whole role-map grammar — exact-dict identity, emptiness, the
    artifact ceiling, exact-string keys and known roles — is enforced by
    ``_exact_role_map`` and is NOT repeated here.
    """
    paths = _exact_role_map(paths)

    entries: dict[str, dict[str, Any]] = {}
    parsed_by_role: dict[str, Any] = {}
    for role in ROLES:
        if role not in paths:
            continue
        # Exactly one parse per JSON artifact: the parsed object comes
        # back with the manifest entry and is reused for the links.
        entries[role], parsed_by_role[role] = _validate_role(role, paths[role])
    parsed_evaluation = parsed_by_role.get("evaluation")
    parsed_lab = parsed_by_role.get("lab")

    links = {
        "evaluation_report_sha256": _evaluation_link(
            parsed_evaluation, "report", entries.get("report")
        ),
        "evaluation_receipts_sha256": _evaluation_link(
            parsed_evaluation, "receipts", entries.get("receipts")
        ),
        "lab_protocol_sha256": _lab_protocol_link(parsed_lab, entries.get("protocol")),
        "lab_sequence_sha256": _lab_sequence_link(parsed_lab, paths.get("log")),
    }

    packet: dict[str, Any] = {
        "schema": PACKET_SCHEMA,
        "config": {
            "max_packet_artifacts": MAX_PACKET_ARTIFACTS,
            "max_input_bytes": MAX_INPUT_BYTES,
            "max_packet_bytes": MAX_PACKET_BYTES,
        },
        "artifacts": [entries[role] for role in ROLES if role in entries],
        "links": links,
        "non_claims": list(NON_CLAIMS),
    }
    # Self-check: the emitted packet must satisfy its own public
    # structural validator before serialization. A failure here is an
    # internal programming/contract failure, NOT malformed user input.
    # The explicit conversion to a plain RuntimeError is retained as a
    # stable internal-failure classification independent of exception
    # ancestry: both a raw ArtifactValidationError and the converted
    # RuntimeError lie outside main()'s typed PacketInputError catch,
    # so the internal failure propagates loudly either way.
    validation = _np9()
    try:
        validation.validate_evidence_packet(packet)
    except validation.ArtifactValidationError as e:
        raise RuntimeError(
            f"internal: emitted packet failed self-validation: {e}"
        ) from e
    serialized = serialize_packet(packet)
    if len(serialized.encode("utf-8")) > MAX_PACKET_BYTES:
        raise PacketTooLargeError(
            f"packet would exceed {MAX_PACKET_BYTES} bytes; refusing to emit"
        )
    return packet


def serialize_packet(packet: Mapping[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, newline."""
    return json.dumps(packet, sort_keys=True, separators=(",", ": "), indent=1) + "\n"


# ---------------------------------------------------------------------------
# Write boundary (corrected-NP6 semantics: identity-aware, race documented)
# ---------------------------------------------------------------------------


def _repo_data_dir() -> pathlib.Path:
    return (pathlib.Path(__file__).resolve().parent.parent / "data").resolve()


def validate_output_path(
    out_path: pathlib.Path, inputs: dict[str, pathlib.Path]
) -> None:
    """--output must resolve inside the primary input's directory (first
    provided role in ROLES order), never inside the repository data/
    tree, and never on a path aliasing ANY input — by resolved path or
    by file identity (hard links included). Identity is verified at
    validation time only; the same residual filesystem race as the NP6
    lab applies and no stronger claim is made.

    ``inputs`` must be an EXACT builtin ``dict`` of known roles: the same
    complete grammar ``build_packet`` uses. That matters here beyond hook
    safety — the alias sweep below only walks ROLES, so an UNKNOWN role
    key used to be skipped entirely and could name the output path
    itself, defeating the alias boundary; and a map with no known role
    used to fall out of the primary-role selection as ``StopIteration``.
    Both are now typed refusals from the shared boundary."""
    # Same complete normalization as build_packet: primary-role selection
    # below must never hash, compare or render a caller-controlled key,
    # and no unknown or foreign key may reach the alias sweep.
    inputs = _exact_role_map(inputs)
    primary = next(inputs[role] for role in ROLES if role in inputs)
    primary_dir = primary.resolve().parent
    out_resolved = out_path.resolve()
    try:
        out_resolved.relative_to(primary_dir)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write packet outside the primary input's directory: "
            f"{out_resolved} is not inside {primary_dir}"
        ) from e
    for role in ROLES:
        if role not in inputs:
            continue
        input_path = inputs[role]
        if out_resolved == input_path.resolve():
            raise WriteOutsideLogDirError(
                f"refusing to overwrite the input {role} file: {out_resolved}"
            )
        if out_resolved.exists():
            try:
                same = os.path.samefile(out_resolved, input_path)
            except OSError as e:
                raise WriteOutsideLogDirError(
                    f"cannot verify output file identity against the input "
                    f"{role} file: {out_resolved}"
                ) from e
            if same:
                raise WriteOutsideLogDirError(
                    f"refusing to overwrite the input {role} file (shared "
                    f"file identity): {out_resolved}"
                )
    data_dir = _repo_data_dir()
    if out_resolved == data_dir or data_dir in out_resolved.parents:
        raise WriteOutsideLogDirError(
            f"refusing to write packet inside the repository data/ tree: {out_resolved}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic evidence packet over recorded Nextness artifacts "
            "(packaging and provenance verification only; see module "
            "docstring for the full contract)."
        )
    )
    for role in ROLES:
        parser.add_argument(
            f"--{role}", type=pathlib.Path, default=None,
            help=f"path to a recorded {role} artifact",
        )
    parser.add_argument(
        "--output", type=pathlib.Path, default=None,
        help=(
            "optional packet path; must resolve inside the primary input's "
            "directory, outside the repository data/ tree, and must not "
            "alias any input (default: stdout)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit-code contract (mirrors NP5): ``0`` success · ``2`` validation
    failure (missing/oversized/malformed/unknown-variant artifact, or
    none provided) · ``4`` output-path failure · ``5`` packet over the
    ceiling. One concise ``error:`` line per expected failure — never a
    traceback. The documented catch set is exactly
    ``WriteOutsideLogDirError``, ``PacketTooLargeError``, the typed
    ``PacketInputError`` (the exit-2 lane — every wrapped validator
    error arrives as ``PacketInputError`` at the existing wrapping
    boundaries) and the write-lane ``OSError``. Exceptions outside it —
    including plain ``ValueError`` — propagate (evidence-packet
    typed-boundary pilot; test-pinned), consistent with
    ``build_packet``'s self-check deliberately re-raising its internal
    validation failure as ``RuntimeError``. Direct-Python note:
    ``build_packet`` and its existing typed failures are unchanged; no
    raise was retyped and no new exception class was introduced.
    """
    args = _build_parser().parse_args(argv)
    paths = {
        role: getattr(args, role) for role in ROLES if getattr(args, role) is not None
    }
    if not paths:
        print("error: provide at least one artifact (--report/--receipts/"
              "--evaluation/--lab/--protocol/--log)", file=sys.stderr)
        return 2
    for role, path in paths.items():
        if not path.is_file():
            print(f"error: {role} artifact not found: {path}", file=sys.stderr)
            return 2
    try:
        if args.output is not None:
            validate_output_path(args.output, paths)
        packet = build_packet(paths)
    except WriteOutsideLogDirError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except PacketTooLargeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 5
    except PacketInputError as e:  # wrapped validators arrive as PacketInputError
        print(f"error: {e}", file=sys.stderr)
        return 2
    serialized = serialize_packet(packet)
    if args.output is not None:
        try:
            args.output.write_bytes(serialized.encode("utf-8"))
        except OSError as e:
            print(f"error: cannot write packet to {args.output}: {e}", file=sys.stderr)
            return 4
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
