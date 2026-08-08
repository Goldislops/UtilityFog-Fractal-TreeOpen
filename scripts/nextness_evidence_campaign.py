"""Nextness Offline Evidence Campaign runner (v1).

Implements the frozen design contract in
``docs/NEXTNESS_EVIDENCE_CAMPAIGN_CONTRACT.md``: the deterministic, offline
processing of ONE already-recorded Nextness Observer log into a single
provenance-checked NP1 -> NP2 -> NP5 -> NP6 -> NP8 artifact chain, published --
together with the outer campaign manifest (schema
``nextness-evidence-campaign-v1``) -- as exactly eight files in one final
directory.

The campaign is a MODULE-LEVEL COMPOSITION of the existing instruments: it
calls each instrument's public builders, loaders and canonical serializers
in-process (``build_report``; ``observations_from_log`` + ``build_receipt``;
``build_evaluation``; ``load_protocol`` + ``build_lab_report``;
``build_packet``; each with its own ``serialize_*``). It never shells out to
the standalone CLIs, never re-implements an instrument's semantics or
serializers, introduces no new metric, selects no winning configuration, and
executes no observer, calibration, engine, tuning, orchestration, network or
model activity.

Staged-snapshot input authority (contract section 3.1): before any instrument
runs, the log and the operator protocol are copied byte-for-byte into a unique
staging directory that shares the final output directory's parent; every
subsequent read -- the completeness preflight, the size preflights and every
instrument call -- uses those staged copies. The originals are never mutated
and never reopened after the copy; the authoritative campaign inputs are the
bytes captured in staging, whose hashes the manifest records. A concurrent
actor that replaces a source WHILE its copy is being taken is a residual the
runner cannot exclude (the manifest describes the captured bytes, not the
originals' later state).

Failure contract (contract section 3.9; a fifth distinct exit-code set on a
seventh CLI -- the family's maps are deliberately not harmonised):

* 0 success (one concise line naming the published final directory)
* 2 validation / campaign refusal -- typed ``CampaignInputError``, plus NP6's
  ``LabInputError`` caught DIRECTLY (never translated; message and
  ``__cause__`` exactly as NP6 supplied them)
* 3 insufficient history (``InsufficientHistoryError`` surfaced from
  NP1 / NP2 / NP6, never re-typed)
* 4 containment (``CampaignContainmentError``: workspace existence, resolved
  path containment, the repository ``data/`` exclusion applied INDEPENDENTLY
  to every applicable campaign path (log, protocol, final directory, staging
  parent, and -- defensively -- the created staging directory; an
  ancestor-of-``data/`` workspace confers no exemption), final-directory
  absence, and input aliasing via resolved-path comparison plus
  ``os.path.samefile`` where both ends exist; a containment or identity
  inspection that cannot complete is itself a refusal)
* 5 named byte-ceiling breach only (the five instrument ``*TooLargeError``
  serialization ceilings; the campaign's own size preflight confirming a
  JSON artifact over NP5/NP8 ``MAX_INPUT_BYTES`` or a staged log over NP8
  ``MAX_LOG_BYTES``; or the campaign manifest over
  ``MAX_CAMPAIGN_MANIFEST_BYTES`` -- typed ``CampaignCeilingError``)
* 6 staging (``CampaignStagingError``: staging-directory creation, input
  copy, artifact write)
* 7 publication (``CampaignPublicationError``: the staging -> final rename
  fails or the OS reports a destination collision)

``EvaluatorInputError`` and ``PacketInputError`` are DELIBERATELY EXCLUDED
from the catch set: the campaign's own size preflight settles the input half
of the exit-5 lane before those loaders are ever called (no
exception-message parsing anywhere), and after a passed preflight such an
error on a campaign-GENERATED artifact is a loud internal invariant failure
that propagates. NP8's emitted-packet self-validation ``RuntimeError`` and a
plain ``ValueError`` likewise propagate: only the exact ``LabInputError``
subclass is caught, never its ``ValueError`` base. Argparse usage errors exit
2 via argparse's own ``SystemExit(2)`` -- the standard family carve-out.

Residual non-claims (contract sections 3.7 and 3.11): a handled failure
removes its staging directory, but a hard kill or power loss mid-run may
leave an unpublished staging directory behind -- uncatchable termination
cleanup is NOT guaranteed. No fsync-level durability and no atomicity
stronger than one same-directory rename is claimed; the
validation-to-rename destination race is a standing non-claim (exit 7 exactly
when the OS reports the collision or rename failure; an unobservable
replacement of an empty directory is not claimed to be detected or
prevented). See ``NON_CLAIMS`` below for the full published statement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
from collections.abc import Mapping
from typing import Any, Final

from scripts.nextness_evaluator import (
    MAX_INPUT_BYTES,
    EvaluationTooLargeError,
    build_evaluation,
    serialize_evaluation,
)
from scripts.nextness_evidence_packet import (
    LINK_KINDS,
    MAX_LOG_BYTES,
    PacketTooLargeError,
    build_packet,
    serialize_packet,
)
from scripts.nextness_monitor import (
    ReceiptTooLargeError,
    build_receipt,
    observations_from_log,
    serialize_receipt,
)
from scripts.nextness_predictor import (
    MAX_LINE_BYTES_CEILING,
    MAX_LINE_BYTES_DEFAULT,
    MAX_ROWS_CEILING,
    MAX_ROWS_DEFAULT,
    InsufficientHistoryError,
    ReportTooLargeError,
    build_report,
    serialize_report,
)
from scripts.nextness_replay_lab import (
    LabInputError,
    LabReportTooLargeError,
    build_lab_report,
    load_protocol,
    serialize_lab_report,
)

# ---------------------------------------------------------------------------
# Fixed contract constants
# ---------------------------------------------------------------------------

CAMPAIGN_SCHEMA: Final[str] = "nextness-evidence-campaign-v1"

#: The campaign manifest's own serialized ceiling (fail closed; contract
#: section 3.8, ceiling family 4 -- never conflated with the instrument
#: serialization ceilings, the JSON/log input ceilings, or NP6's protocol
#: input ceiling).
MAX_CAMPAIGN_MANIFEST_BYTES: Final[int] = 64 * 1024

#: The frozen final directory: exactly these eight files, relative names
#: only, no more and no fewer (contract section 3.2).
LOG_FILENAME: Final[str] = "nextness_runs.jsonl"
PROTOCOL_FILENAME: Final[str] = "nextness_replay_protocol.json"
REPORT_FILENAME: Final[str] = "nextness_predictor_report.json"
RECEIPT_FILENAME: Final[str] = "nextness_monitor_receipt.json"
EVALUATION_FILENAME: Final[str] = "nextness_evaluation.json"
LAB_FILENAME: Final[str] = "nextness_replay_lab.json"
PACKET_FILENAME: Final[str] = "nextness_evidence_packet.json"
MANIFEST_FILENAME: Final[str] = "nextness_evidence_campaign.json"

PUBLICATION_FILENAMES: Final[tuple[str, ...]] = (
    LOG_FILENAME,
    PROTOCOL_FILENAME,
    REPORT_FILENAME,
    RECEIPT_FILENAME,
    EVALUATION_FILENAME,
    LAB_FILENAME,
    PACKET_FILENAME,
    MANIFEST_FILENAME,
)

_COPY_CHUNK_BYTES: Final[int] = 64 * 1024

NON_CLAIMS: Final[tuple[str, ...]] = (
    "Deterministic offline composition of recorded artifacts only: no "
    "observer, calibration, engine, tuning, orchestration, network, HTTP, "
    "ZMQ or model activity, and no real Medusa artifact is required or "
    "assumed.",
    "No configuration is ranked, selected as best, recommended or applied; "
    "the receipt configuration is the operator's explicit, named act, every "
    "protocol configuration is retained descriptively, and NP5's "
    "descriptive model rankings are carried unchanged.",
    "A handled failure removes its staging directory, but a hard kill or "
    "power loss mid-run may leave an unpublished staging directory behind; "
    "no fsync-level durability and no atomicity stronger than one "
    "same-directory rename is claimed, and an unobservable "
    "destination-replacement race is not claimed to be detected.",
    "No consciousness, awareness, phenomenology or biological-equivalence "
    "claim is made or implied: the campaign is bookkeeping over recorded "
    "counting-model artifacts, nothing more.",
)


class CampaignInputError(ValueError):
    """The campaign's own validation and refusal lanes (exit 2)."""


class CampaignContainmentError(ValueError):
    """Workspace / path existence, containment, ``data/`` exclusion or
    input-alias refusal; a failed inspection is itself a refusal (exit 4)."""


class CampaignCeilingError(RuntimeError):
    """A campaign-owned named byte-ceiling breach: a size-preflight-confirmed
    input over NP5/NP8 ``MAX_INPUT_BYTES`` or NP8 ``MAX_LOG_BYTES``, or the
    manifest over ``MAX_CAMPAIGN_MANIFEST_BYTES`` (exit 5)."""


class CampaignStagingError(RuntimeError):
    """Staging-directory creation, input copy or artifact write failed
    (exit 6)."""


class CampaignPublicationError(RuntimeError):
    """The staging -> final promotion failed with the OS reporting the
    collision or rename failure (exit 7)."""


# ---------------------------------------------------------------------------
# Containment (resolved paths, fail-closed identity discipline)
# ---------------------------------------------------------------------------


def _repo_data_dir() -> pathlib.Path:
    return (pathlib.Path(__file__).resolve().parent.parent / "data").resolve()


def _is_within(child: str, root: str) -> bool:
    """``child`` equals ``root`` or lies under it (both already resolved).

    Comparison is on ``os.path.normcase`` forms so case-insensitive
    filesystems cannot smuggle a path out of the workspace by case games.
    """
    child_n = os.path.normcase(child)
    root_n = os.path.normcase(root)
    return child_n == root_n or child_n.startswith(root_n.rstrip(os.sep) + os.sep)


def _refuse_under_data(resolved: str, name: str) -> None:
    """No campaign path may be equal to or beneath the repository ``data/``
    root -- checked INDEPENDENTLY for every applicable resolved path, so a
    workspace that is an ANCESTOR of ``data/`` (the repository root, for
    example) cannot smuggle an individual path under ``data/`` through
    ordinary workspace containment."""
    if _is_within(resolved, str(_repo_data_dir())):
        raise CampaignContainmentError(
            f"{name} resolves inside the repository data/ tree; no campaign "
            f"path may lie under data/"
        )


def _paths_alias(candidate_given: pathlib.Path, candidate_resolved: str, input_resolved: str) -> bool:
    """Fail-closed identity between a campaign output path and an input:
    resolved-path comparison always applies; where BOTH ends exist,
    ``os.path.samefile`` is consulted as well (it sees hard-link aliases
    that no path-string comparison can). An inspection that raises is
    handled by the caller's fail-closed ``OSError`` boundary -- a refusal,
    never a fall-through."""
    if os.path.normcase(candidate_resolved) == os.path.normcase(input_resolved):
        return True
    if os.path.exists(str(candidate_given)) and os.path.exists(input_resolved):
        return os.path.samefile(str(candidate_given), input_resolved)
    return False


def _resolve_campaign_paths(
    log_path: pathlib.Path,
    protocol_path: pathlib.Path,
    workspace_dir: pathlib.Path,
    output_dir: pathlib.Path,
) -> tuple[str, str, str, str, str]:
    """Contract section 3.1 containment, all fail closed.

    Returns ``(workspace_root, log_resolved, protocol_resolved,
    final_resolved, staging_parent)``. Any ``OSError`` during an
    inspection -- including an ``os.path.samefile`` identity probe that
    cannot complete -- is itself a refusal (the established fail-closed
    identity discipline), never a fall-through. The repository ``data/``
    exclusion is enforced per-path: a workspace that is an ancestor of
    ``data/`` does not exempt the paths beneath it.
    """
    try:
        if not workspace_dir.is_dir():
            raise CampaignContainmentError(
                f"--workspace-dir is not an existing directory: {workspace_dir}"
            )
        workspace_root = os.path.realpath(str(workspace_dir))
        data_root = str(_repo_data_dir())
        if _is_within(workspace_root, data_root):
            raise CampaignContainmentError(
                "workspace resolves inside the repository data/ tree; no "
                "campaign path may lie under data/"
            )
        for name, path in (("log", log_path), ("protocol", protocol_path)):
            if not path.is_file():
                raise CampaignContainmentError(
                    f"{name} path is not an existing file: {path}"
                )
            resolved = os.path.realpath(str(path))
            if not _is_within(resolved, workspace_root):
                raise CampaignContainmentError(
                    f"{name} path resolves outside the workspace: {path}"
                )
            _refuse_under_data(resolved, f"{name} path")
        log_resolved = os.path.realpath(str(log_path))
        protocol_resolved = os.path.realpath(str(protocol_path))
        final_resolved = os.path.realpath(str(output_dir))
        if not _is_within(final_resolved, workspace_root):
            raise CampaignContainmentError(
                f"--output-dir resolves outside the workspace: {output_dir}"
            )
        _refuse_under_data(final_resolved, "--output-dir")
        # Identity BEFORE absence, so an existing alias of an input is
        # refused on the identity lane (resolved-path + os.path.samefile,
        # fail-closed) rather than falling through to the generic
        # absent-final rule.
        for name, resolved in (
            ("log", log_resolved),
            ("protocol", protocol_resolved),
        ):
            if _paths_alias(output_dir, final_resolved, resolved):
                raise CampaignContainmentError(
                    f"--output-dir aliases the {name} input path"
                )
        if os.path.lexists(str(output_dir)) or os.path.lexists(final_resolved):
            raise CampaignContainmentError(
                f"--output-dir already exists at validation time: {output_dir}"
            )
        staging_parent = os.path.dirname(final_resolved)
        if not _is_within(staging_parent, workspace_root):
            raise CampaignContainmentError(
                "the staging parent resolves outside the workspace"
            )
        _refuse_under_data(staging_parent, "the staging parent")
    except (CampaignContainmentError, CampaignInputError):
        raise
    except OSError as e:
        raise CampaignContainmentError(
            f"containment inspection could not complete (fail closed): {e}"
        ) from e
    return (
        workspace_root,
        log_resolved,
        protocol_resolved,
        final_resolved,
        staging_parent,
    )


# ---------------------------------------------------------------------------
# Staging (byte-for-byte capture; the staged bytes are authoritative)
# ---------------------------------------------------------------------------


def _read_source_chunk(handle: Any) -> bytes:
    """One bounded read at the staged-copy boundary.

    A deliberately narrow, production-neutral seam: behaviour is exactly
    ``handle.read(_COPY_CHUNK_BYTES)``; the during-copy replacement test
    synchronizes here to exercise the captured-bytes residual without any
    timing dependence."""
    return handle.read(_COPY_CHUNK_BYTES)


def _stage_copy(source: str, destination: pathlib.Path) -> tuple[int, str]:
    """Copy ``source`` into staging byte-for-byte, hashing the bytes as
    captured. Returns ``(byte_count, sha256_hex)`` of exactly the bytes
    written -- the manifest describes these captured bytes, not the
    original's later state."""
    digest = hashlib.sha256()
    total = 0
    try:
        # Unbuffered source handle: the copy loop does its own chunking, so
        # interposing a prefetching buffer would only blur which bytes were
        # actually read when -- the captured-bytes statement is exactly the
        # OS-level read sequence this loop hashes.
        with open(source, "rb", buffering=0) as src, destination.open("wb") as dst:
            while True:
                chunk = _read_source_chunk(src)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
                dst.write(chunk)
    except OSError as e:
        raise CampaignStagingError(
            f"staging failed: could not copy input into staging: {e}"
        ) from e
    return total, digest.hexdigest()


def _write_artifact(directory: pathlib.Path, filename: str, serialized: str) -> tuple[int, str]:
    """Write one canonical artifact into staging; returns (bytes, sha256)."""
    raw = serialized.encode("utf-8")
    try:
        (directory / filename).write_bytes(raw)
    except OSError as e:
        raise CampaignStagingError(
            f"staging failed: could not write {filename}: {e}"
        ) from e
    return len(raw), hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# The campaign-owned completeness preflight (contract section 3.6)
# ---------------------------------------------------------------------------


def _completeness_preflight(
    staged_log: pathlib.Path, *, max_rows: int, max_line_bytes: int
) -> tuple[int, bool, bool]:
    """Streaming byte-level scan of the staged log, framing records exactly
    as NP1's reader frames them: LF-delimited, bounded
    ``readline(max_line_bytes + 2)`` probes, content = chunk minus a
    trailing CRLF (two bytes) or LF (one byte), an unterminated or
    probe-limited chunk taken as content in full. Every physical record
    counts -- accepted, rejected and blank alike -- matching NP1's
    ``rows_read`` accounting.

    Answers exactly two byte-level questions and nothing else: is there a
    physical record beyond ``max_rows``, and is there a record whose content
    exceeds ``max_line_bytes``? No JSON parsing, no rejection
    classification, no accepted-row judgement -- the 12 NP1 REJECT_REASONS
    remain entirely NP1's. Reads at most ``max_rows + 1`` records, so it
    works at every permitted bound including ``max_rows = MAX_ROWS_CEILING``
    (where NP1's reader could not be asked to probe further).

    Returns ``(records_observed, beyond_max_rows, oversized_record)`` with
    ``records_observed`` at most ``max_rows``.
    """
    rows = 0
    with staged_log.open("rb") as f:
        while True:
            chunk = f.readline(max_line_bytes + 2)
            if not chunk:
                return rows, False, False
            if rows >= max_rows:
                # A physical record beyond max_rows exists; the question is
                # answered, stop immediately.
                return rows, True, False
            rows += 1
            if chunk.endswith(b"\n"):
                content = chunk[:-2] if chunk.endswith(b"\r\n") else chunk[:-1]
            else:
                content = chunk
            if len(content) > max_line_bytes:
                return rows, False, True


# ---------------------------------------------------------------------------
# The campaign-owned size preflight (contract section 3.9)
# ---------------------------------------------------------------------------


def _size_preflight(path: pathlib.Path, ceiling: int, description: str) -> None:
    """Confirm a named input byte-ceiling BEFORE the owning loader runs.

    This -- never the interpretation of an instrument's typed exception,
    and never exception-message parsing -- is how the input half of the
    exit-5 lane is decided. Anything this preflight passes goes to the
    existing typed loader unchanged; an ``EvaluatorInputError`` /
    ``PacketInputError`` raised afterwards on a campaign-generated artifact
    is a loud internal invariant failure, not a campaign lane.
    """
    try:
        size = path.stat().st_size
    except OSError as e:
        raise CampaignStagingError(
            f"staging failed: could not inspect staged {description}: {e}"
        ) from e
    if size > ceiling:
        raise CampaignCeilingError(
            f"{description} is {size} bytes, exceeding the {ceiling}-byte "
            f"ceiling (campaign size preflight, fail closed)"
        )


# ---------------------------------------------------------------------------
# Gates (contract sections 3.3 and 3.4)
# ---------------------------------------------------------------------------


def _verify_provenance_links(packet: Mapping[str, Any]) -> None:
    """All four NP8 provenance checks must be ``verified`` (contract
    section 3.3); any other status is a fail-closed campaign refusal."""
    for kind in LINK_KINDS:
        status = packet["links"][kind]["status"]
        if status != "verified":
            raise CampaignInputError(
                f"provenance not verified: NP8 link {kind} is {status!r}"
            )


def _coherence_gate(evaluation: Mapping[str, Any]) -> None:
    """Verdict-level cross-artifact coherence gate (contract section 3.4).

    A ``computed`` result carrying a verdict of exactly ``contradicted``
    refuses publication; ``consistent``, ``unverifiable`` and a typed
    ``not_computable`` envelope are evidence outcomes that publish, carried
    into the manifest exactly as NP5 recorded them. The campaign invents no
    verdict and never recasts one.
    """
    cross = evaluation["cross_check"]
    for check_name in ("ece_match", "surprise_nll_match"):
        envelope = cross[check_name]
        if envelope["status"] != "computed":
            continue
        for result in envelope["value"]["results"]:
            if result["verdict"] == "contradicted":
                raise CampaignInputError(
                    f"cross-artifact coherence refusal: {check_name} verdict "
                    f"for model {result['model']!r} is 'contradicted'"
                )


# ---------------------------------------------------------------------------
# The campaign
# ---------------------------------------------------------------------------


def _validate_options(
    receipt_config_label: Any, max_rows: Any, max_line_bytes: Any
) -> None:
    """The campaign's own CLI-option validation lane (exit 2).

    Bounds mirror NP1's ranges exactly so every instrument receives
    already-valid bounds; exact builtin ``int`` only (bool is an ``int``
    subclass and is refused).
    """
    if type(receipt_config_label) is not str or not receipt_config_label:
        raise CampaignInputError(
            "receipt_config_label must be a non-empty builtin str"
        )
    if type(max_rows) is not int:
        raise CampaignInputError("max_rows must be a builtin int")
    if not 1 <= max_rows <= MAX_ROWS_CEILING:
        raise CampaignInputError(
            f"max_rows must be in [1, {MAX_ROWS_CEILING}], got {max_rows}"
        )
    if type(max_line_bytes) is not int:
        raise CampaignInputError("max_line_bytes must be a builtin int")
    if not 1 <= max_line_bytes <= MAX_LINE_BYTES_CEILING:
        raise CampaignInputError(
            f"max_line_bytes must be in [1, {MAX_LINE_BYTES_CEILING}], "
            f"got {max_line_bytes}"
        )


def _publish(staging_dir: str, final_resolved: str) -> None:
    """Promote staging to final via one same-directory rename.

    Exit 7 applies exactly when the OS reports the collision or the rename
    failure; an unobservable replacement of a concurrently created empty
    directory remains an explicit non-claim.
    """
    try:
        os.rename(staging_dir, final_resolved)
    except OSError as e:
        raise CampaignPublicationError(
            f"publication failed: could not promote staging to the final "
            f"directory: {e}"
        ) from e


def serialize_manifest(manifest: Mapping[str, Any]) -> str:
    """Canonical serialization: sorted keys, fixed separators, newline
    (identical convention to every instrument serializer)."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ": "), indent=1) + "\n"


def run_campaign(
    log_path: pathlib.Path,
    protocol_path: pathlib.Path,
    *,
    workspace_dir: pathlib.Path,
    output_dir: pathlib.Path,
    receipt_config_label: str,
    max_rows: int = MAX_ROWS_DEFAULT,
    max_line_bytes: int = MAX_LINE_BYTES_DEFAULT,
) -> pathlib.Path:
    """Run one campaign; returns the published final directory.

    See the module docstring for the full contract. Raises the typed
    campaign classes (and surfaces ``LabInputError`` /
    ``InsufficientHistoryError`` / the instrument ``*TooLargeError``
    classes) exactly as the exit map documents.
    """
    _validate_options(receipt_config_label, max_rows, max_line_bytes)
    (
        workspace_root,
        log_resolved,
        protocol_resolved,
        final_resolved,
        staging_parent,
    ) = _resolve_campaign_paths(log_path, protocol_path, workspace_dir, output_dir)

    try:
        staging_dir = tempfile.mkdtemp(
            prefix=".nextness-campaign-staging-", dir=staging_parent
        )
    except OSError as e:
        raise CampaignStagingError(
            f"staging failed: could not create the staging directory: {e}"
        ) from e

    try:
        # Defensive invariant: the just-created staging directory itself
        # must not resolve under the repository data/ tree (its parent was
        # already checked; this closes any resolution surprise between the
        # check and the creation, fail closed).
        try:
            _refuse_under_data(
                os.path.realpath(staging_dir), "the staging directory"
            )
        except OSError as e:
            raise CampaignContainmentError(
                f"containment inspection could not complete (fail closed): {e}"
            ) from e
        staging = pathlib.Path(staging_dir)
        staged_log = staging / LOG_FILENAME
        staged_protocol = staging / PROTOCOL_FILENAME

        # -- capture (contract section 3.1): after these copies the
        # originals are never reopened; staged bytes are authoritative.
        log_bytes, log_sha = _stage_copy(log_resolved, staged_log)
        protocol_bytes, protocol_sha = _stage_copy(protocol_resolved, staged_protocol)

        # -- completeness preflight (contract section 3.6), before any
        # instrument runs.
        records_observed, beyond, oversized = _completeness_preflight(
            staged_log, max_rows=max_rows, max_line_bytes=max_line_bytes
        )
        if beyond:
            raise CampaignInputError(
                f"complete-log refusal: the staged log has a physical record "
                f"beyond max_rows={max_rows}; the campaign processes only "
                f"whole logs, never a prefix"
            )
        if oversized:
            raise CampaignInputError(
                f"complete-log refusal: a record's content exceeds "
                f"max_line_bytes={max_line_bytes} (the oversized record that "
                f"would terminate NP1 ingestion)"
            )

        # -- operator protocol through NP6's own typed boundary
        # (LabInputError -> exit 2, caught directly by main, never
        # translated).
        protocol_data = load_protocol(staged_protocol)
        selected_config = None
        for label, config in protocol_data["configs"]:
            if label == receipt_config_label:
                selected_config = config
                break
        if selected_config is None:
            raise CampaignInputError(
                f"receipt_config_label {receipt_config_label!r} does not "
                f"match any configuration label in the protocol"
            )

        # -- NP1 predictor report (protocol smoothing / holdout_fraction
        # drive NP1; campaign reader bounds applied).
        report = build_report(
            staged_log,
            smoothing=protocol_data["smoothing"],
            holdout_fraction=protocol_data["holdout_fraction"],
            max_rows=max_rows,
            max_line_bytes=max_line_bytes,
        )
        report_bytes, report_sha = _write_artifact(
            staging, REPORT_FILENAME, serialize_report(report)
        )

        # -- NP2 checkpoint receipt for the single labelled configuration,
        # module-level by necessity (NP2's CLI can express neither a
        # labelled configuration nor reader bounds). The labelled
        # configuration's window is passed to observations_from_log AS WELL
        # AS to build_receipt's config -- the campaign owns that lineage
        # (contract section 3.4).
        observations, reference_counts, recent_counts = observations_from_log(
            staged_log,
            protocol_data["model"],
            smoothing=protocol_data["smoothing"],
            holdout_fraction=protocol_data["holdout_fraction"],
            max_rows=max_rows,
            max_line_bytes=max_line_bytes,
            window=selected_config.window,
        )
        receipt = build_receipt(
            model=protocol_data["model"],
            observations=observations,
            reference_counts=reference_counts,
            recent_counts=recent_counts,
            config=selected_config,
        )
        receipt_bytes, receipt_sha = _write_artifact(
            staging, RECEIPT_FILENAME, serialize_receipt(receipt)
        )

        # -- NP5 evaluation over the two staged artifacts; the campaign's
        # size preflight settles the input-ceiling lane BEFORE NP5's loader
        # runs (contract section 3.9).
        _size_preflight(staging / REPORT_FILENAME, MAX_INPUT_BYTES, "NP1 report")
        _size_preflight(staging / RECEIPT_FILENAME, MAX_INPUT_BYTES, "NP2 receipt")
        evaluation = build_evaluation(
            report_path=staging / REPORT_FILENAME,
            receipts_path=staging / RECEIPT_FILENAME,
        )
        _coherence_gate(evaluation)
        evaluation_bytes, evaluation_sha = _write_artifact(
            staging, EVALUATION_FILENAME, serialize_evaluation(evaluation)
        )

        # -- NP6 replay-lab report over the staged log and protocol,
        # retaining every configuration in operator order (identical
        # campaign reader bounds -- contract section 3.4).
        lab = build_lab_report(
            staged_log,
            staged_protocol,
            max_rows=max_rows,
            max_line_bytes=max_line_bytes,
        )
        lab_bytes, lab_sha = _write_artifact(
            staging, LAB_FILENAME, serialize_lab_report(lab)
        )

        # -- NP8 evidence packet over the six existing roles; size
        # preflights first (JSON artifacts at MAX_INPUT_BYTES, the staged
        # log at MAX_LOG_BYTES), then the packet's own four provenance
        # checks, all of which must be verified (contract section 3.3).
        for filename, description in (
            (REPORT_FILENAME, "NP1 report"),
            (RECEIPT_FILENAME, "NP2 receipt"),
            (EVALUATION_FILENAME, "NP5 evaluation"),
            (LAB_FILENAME, "NP6 lab report"),
            (PROTOCOL_FILENAME, "staged protocol"),
        ):
            _size_preflight(staging / filename, MAX_INPUT_BYTES, description)
        _size_preflight(staged_log, MAX_LOG_BYTES, "staged log")
        packet = build_packet(
            {
                "report": staging / REPORT_FILENAME,
                "receipts": staging / RECEIPT_FILENAME,
                "evaluation": staging / EVALUATION_FILENAME,
                "lab": staging / LAB_FILENAME,
                "protocol": staged_protocol,
                "log": staged_log,
            }
        )
        _verify_provenance_links(packet)
        packet_bytes, packet_sha = _write_artifact(
            staging, PACKET_FILENAME, serialize_packet(packet)
        )

        # -- the outer campaign manifest (contract section 3.2): the final
        # campaign artifact, not an NP8 role; records the seven non-manifest
        # files and cannot record its own hash. Relative filenames only; no
        # timestamp, no randomness, no absolute path.
        manifest: dict[str, Any] = {
            "schema": CAMPAIGN_SCHEMA,
            "config": {
                "max_campaign_manifest_bytes": MAX_CAMPAIGN_MANIFEST_BYTES,
                "max_rows": max_rows,
                "max_line_bytes": max_line_bytes,
            },
            "inputs": {
                "log": {
                    "filename": LOG_FILENAME,
                    "bytes": log_bytes,
                    "sha256": log_sha,
                },
                "protocol": {
                    "filename": PROTOCOL_FILENAME,
                    "bytes": protocol_bytes,
                    "sha256": protocol_sha,
                },
            },
            "receipt_config_label": receipt_config_label,
            "receipt_config": {
                "min_history": selected_config.min_history,
                "window": selected_config.window,
                "low_confidence_threshold": selected_config.low_confidence_threshold,
                "calibration_error_threshold": selected_config.calibration_error_threshold,
                "drift_threshold_bits": selected_config.drift_threshold_bits,
            },
            "completeness": {
                "max_rows": max_rows,
                "max_line_bytes": max_line_bytes,
                "records_observed": records_observed,
                "no_record_beyond_max_rows": True,
                "no_oversized_record": True,
            },
            "artifacts": {
                "report": {
                    "filename": REPORT_FILENAME,
                    "bytes": report_bytes,
                    "sha256": report_sha,
                },
                "receipt": {
                    "filename": RECEIPT_FILENAME,
                    "bytes": receipt_bytes,
                    "sha256": receipt_sha,
                },
                "evaluation": {
                    "filename": EVALUATION_FILENAME,
                    "bytes": evaluation_bytes,
                    "sha256": evaluation_sha,
                },
                "lab": {
                    "filename": LAB_FILENAME,
                    "bytes": lab_bytes,
                    "sha256": lab_sha,
                },
                "packet": {
                    "filename": PACKET_FILENAME,
                    "bytes": packet_bytes,
                    "sha256": packet_sha,
                },
            },
            "cross_check": {
                "ece_match": evaluation["cross_check"]["ece_match"],
                "surprise_nll_match": evaluation["cross_check"]["surprise_nll_match"],
            },
            "np8_links": {
                kind: packet["links"][kind]["status"] for kind in LINK_KINDS
            },
            "non_claims": list(NON_CLAIMS),
        }
        serialized_manifest = serialize_manifest(manifest)
        if len(serialized_manifest.encode("utf-8")) > MAX_CAMPAIGN_MANIFEST_BYTES:
            raise CampaignCeilingError(
                f"campaign manifest would exceed "
                f"{MAX_CAMPAIGN_MANIFEST_BYTES} bytes; refusing to emit"
            )
        _write_artifact(staging, MANIFEST_FILENAME, serialized_manifest)

        # Internal publication-set invariant: exactly the eight files. A
        # mismatch is an internal programming failure, never an input lane.
        present = sorted(p.name for p in staging.iterdir())
        if present != sorted(PUBLICATION_FILENAMES):
            raise RuntimeError(
                f"internal: staging does not contain exactly the eight "
                f"publication files (found {present})"
            )

        _publish(staging_dir, final_resolved)
    except BaseException:
        # A handled failure cleans its staging directory (best effort; an
        # uncatchable termination is not guaranteed to -- documented
        # residual). Loud internal failures are cleaned too before they
        # propagate; the raise below re-raises the original.
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return pathlib.Path(final_resolved)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nextness_evidence_campaign",
        description=(
            "Deterministic offline evidence campaign: compose the recorded "
            "NP1->NP2->NP5->NP6->NP8 chain over one staged log and one "
            "operator protocol, publishing exactly eight files. Argparse "
            "usage errors also exit 2 (argparse's own SystemExit)."
        ),
    )
    parser.add_argument("log_path", help="recorded nextness_runs.jsonl log")
    parser.add_argument("protocol_path", help="operator NP6 replay protocol")
    parser.add_argument(
        "--workspace-dir",
        required=True,
        help="existing directory that must contain every campaign path",
    )
    parser.add_argument(
        "--receipt-config-label",
        required=True,
        help="exact label of ONE protocol configuration (no implicit winner)",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="final campaign directory (absent before the run, inside the workspace)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=MAX_ROWS_DEFAULT,
        help=f"reader bound, default {MAX_ROWS_DEFAULT}, ceiling {MAX_ROWS_CEILING}",
    )
    parser.add_argument(
        "--max-line-bytes",
        type=int,
        default=MAX_LINE_BYTES_DEFAULT,
        help=(
            f"reader bound, default {MAX_LINE_BYTES_DEFAULT}, "
            f"ceiling {MAX_LINE_BYTES_CEILING}"
        ),
    )
    return parser


def _fail(error: BaseException, code: int) -> int:
    print(f"error: {error}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        final_dir = run_campaign(
            pathlib.Path(args.log_path),
            pathlib.Path(args.protocol_path),
            workspace_dir=pathlib.Path(args.workspace_dir),
            output_dir=pathlib.Path(args.output_dir),
            receipt_config_label=args.receipt_config_label,
            max_rows=args.max_rows,
            max_line_bytes=args.max_line_bytes,
        )
    except CampaignInputError as e:
        return _fail(e, 2)
    except LabInputError as e:
        # Caught directly, never translated: message and __cause__ are
        # exactly what NP6 supplied. Only this exact subclass -- a plain
        # ValueError still propagates.
        return _fail(e, 2)
    except InsufficientHistoryError as e:
        return _fail(e, 3)
    except CampaignContainmentError as e:
        return _fail(e, 4)
    except (
        ReportTooLargeError,
        ReceiptTooLargeError,
        EvaluationTooLargeError,
        LabReportTooLargeError,
        PacketTooLargeError,
        CampaignCeilingError,
    ) as e:
        return _fail(e, 5)
    except CampaignStagingError as e:
        return _fail(e, 6)
    except CampaignPublicationError as e:
        return _fail(e, 7)
    print(f"published: {final_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
