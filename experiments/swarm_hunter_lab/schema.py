"""Closed output schema for the S1 findings artifact (swarm-hunter-lab-findings-v1).

Forbidden-content closure is structural, not a token denylist: every emitted
key belongs to a closed per-kind key set, every string value is either a
fixed literal from the enums below, a grammar-validated identifier, or
hex digest text, and validation rejects extra keys recursively.  The output
therefore cannot carry actions, endpoints, tuning suggestions, approval
language, or parameter recommendations by construction.  (Copying the
production ``params_schema`` vocabulary into a denylist would both cross the
import quarantine and go stale; the closed generated vocabulary is auditable
by reading this file alone.)
"""

import json
import re

SCHEMA_ID = "swarm-hunter-lab-findings-v1"
LEANCTX_SCHEMA_ID = "leanctx-swarm-hunter-lab-v1"

# Unanchored bodies validated exclusively through fullmatch(): `$`-anchored
# .match() accepts a trailing newline in Python, so anchors are banned here.
_ID_BODY = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_HEX64_BODY = re.compile(r"[0-9a-f]{64}")
_HEX16_BODY = re.compile(r"[0-9a-f]{16}")


def is_safe_id(value) -> bool:
    """Exact ``str`` + fullmatch — no coercion, trailing newline fails."""
    return type(value) is str and _ID_BODY.fullmatch(value) is not None


def is_hex64(value) -> bool:
    return type(value) is str and _HEX64_BODY.fullmatch(value) is not None


def is_hex16(value) -> bool:
    return type(value) is str and _HEX16_BODY.fullmatch(value) is not None

STATE_MAP = {"1": "structural", "2": "compute", "3": "energy", "4": "sensor"}
STATE_KEYS = ("1", "2", "3", "4")

CONNECTIVITY = "face-6"
PERIODIC_INTERPRETATION = "torus"
EVIDENCE_CLASSES = ("SRC", "CALC", "HYP")

# Fatal refusal reasons (first-failure order is frozen in detector.py).
# Cap/budget exhaustion are NOT refusals: per the controlling S0
# reconciliation they are reported truncations (header.truncation).
REFUSAL_MESSAGES = {
    "invalid_config": "config must be a DetectorConfig with int fields within bounds",
    "invalid_config_for_volume": "min_component_size exceeds the lattice volume",
    "invalid_input": "input is not a well-formed synthetic snapshot sequence",
    "invalid_provenance": "provenance must contain exactly the required fields",
    "invalid_identifier": "identifier fails the safe grammar ^[a-z0-9][a-z0-9._-]{0,63}$",
    "s2_gated": "source must be 'synthetic' in S1; real snapshots are S2-gated",
    "lattice_too_large": "lattice exceeds the supported 64^3 bound",
    "unsupported_num_states": "num_states must equal 5",
    "invalid_state_value": "states contains a value outside 0..4",
    "invalid_optional_data": "optional array has wrong dtype/shape or non-finite values",
    "invalid_sha256_format": "sha256_triple must map states/memory/inactivity_steps to 64-hex",
    "provenance_hash_mismatch": "caller-supplied sha256 does not match canonical array bytes",
    "duplicate_snapshot_id": "snapshot_id appears more than once",
    "nonmonotonic_generation": "generations must be strictly increasing",
    "inconsistent_lattice_size": "all snapshots in one call must share the same N",
}

TRUNCATION_KINDS = ("component_cap", "op_budget_preflight")

HEADER_KEYS = {
    "kind", "schema", "detector", "run", "params", "counts",
    "empty", "truncated", "truncation",
}
DETECTOR_KEYS = {"name", "version"}
RUN_KEYS = {"snapshot_count", "snapshot_ids", "generations"}
PARAMS_KEYS = {
    "min_component_size", "component_cap", "op_budget_multiplier",
    "connectivity", "state_map",
}
COUNTS_KEYS = {"components_discovered", "components_emitted", "findings", "refusals"}
TRUNCATION_CAP_KEYS = {"kind", "components_after_filter", "component_cap"}
TRUNCATION_BUDGET_KEYS = {"kind", "required_ops", "op_budget"}

FINDING_KEYS = {
    "kind", "finding_id", "chain_id", "component_id", "label", "region",
    "periodic_interpretation", "cell_count", "state_counts", "density",
    "snapshot", "observations", "persistence", "reasons", "evidence_class",
    "truncated",
}
REGION_KEYS = {"bbox_min", "bbox_max", "wraps"}
DENSITY_KEYS = {"num", "den"}
OBSERVATION_KEYS = {
    "snapshot_id", "generation", "channel_layout_version", "source",
    "sha256_triple",
}
SHA256_TRIPLE_KEYS = {"states", "memory", "inactivity_steps"}
PERSISTENCE_KEYS = {"seen_in_snapshots", "chain_id"}
REASON_KEYS = {"predicate", "threshold", "measured"}
REASON_PREDICATES = ("cell_count>=min_component_size",)

REFUSAL_KEYS_REQUIRED = {"kind", "reason", "message", "evidence_class"}
REFUSAL_KEYS_OPTIONAL = {"snapshot_id"}


def canonical_line(record):
    """The frozen canonical serialization of one record."""
    return (json.dumps(record, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def _is_uint(value):
    return type(value) is int and value >= 0


def _fail(errors, path, why):
    errors.append(f"{path}: {why}")


def _check_keys(errors, path, mapping, required, optional=frozenset()):
    if not isinstance(mapping, dict):
        _fail(errors, path, "not an object")
        return False
    keys = set(mapping)
    extra = keys - required - set(optional)
    missing = required - keys
    if extra:
        _fail(errors, path, f"extra keys {sorted(extra)}")
    if missing:
        _fail(errors, path, f"missing keys {sorted(missing)}")
    return not extra and not missing


def _validate_observation(errors, path, obs):
    if not _check_keys(errors, path, obs, OBSERVATION_KEYS):
        return
    if not is_safe_id(obs["snapshot_id"]):
        _fail(errors, path, "snapshot_id grammar")
    if not _is_uint(obs["generation"]):
        _fail(errors, path, "generation not uint")
    if not is_safe_id(obs["channel_layout_version"]):
        _fail(errors, path, "channel_layout_version grammar")
    if obs["source"] != "synthetic":
        _fail(errors, path, "source must be 'synthetic' in S1")
    triple = obs["sha256_triple"]
    if _check_keys(errors, path + ".sha256_triple", triple, SHA256_TRIPLE_KEYS):
        for slot in sorted(SHA256_TRIPLE_KEYS):
            if not is_hex64(triple[slot]):
                _fail(errors, path, f"sha256_triple.{slot} not 64-hex")


def _validate_header(errors, rec):
    _check_keys(errors, "header", rec, HEADER_KEYS)
    if rec.get("schema") != SCHEMA_ID:
        _fail(errors, "header", "bad schema id")
    det = rec.get("detector", {})
    if _check_keys(errors, "header.detector", det, DETECTOR_KEYS):
        if not is_safe_id(det["name"]) or not is_safe_id(det["version"]):
            _fail(errors, "header.detector", "name/version grammar")
    run = rec.get("run", {})
    if _check_keys(errors, "header.run", run, RUN_KEYS):
        if not _is_uint(run["snapshot_count"]):
            _fail(errors, "header.run", "snapshot_count not uint")
        for sid in run["snapshot_ids"]:
            if not is_safe_id(sid):
                _fail(errors, "header.run", "snapshot id grammar")
        for gen in run["generations"]:
            if not _is_uint(gen):
                _fail(errors, "header.run", "generation not uint")
    params = rec.get("params")
    if params is not None and _check_keys(errors, "header.params", params, PARAMS_KEYS):
        if params["connectivity"] != CONNECTIVITY:
            _fail(errors, "header.params", "connectivity literal")
        if params["state_map"] != STATE_MAP:
            _fail(errors, "header.params", "state_map literal")
        for key in ("min_component_size", "component_cap", "op_budget_multiplier"):
            if not _is_uint(params[key]):
                _fail(errors, "header.params", f"{key} not uint")
    counts = rec.get("counts", {})
    if _check_keys(errors, "header.counts", counts, COUNTS_KEYS):
        for key in sorted(COUNTS_KEYS):
            if not _is_uint(counts[key]):
                _fail(errors, "header.counts", f"{key} not uint")
    if type(rec.get("empty")) is not bool or type(rec.get("truncated")) is not bool:
        _fail(errors, "header", "empty/truncated not bool")
    trunc = rec.get("truncation")
    if trunc is not None:
        if not isinstance(trunc, dict) or trunc.get("kind") not in TRUNCATION_KINDS:
            _fail(errors, "header.truncation", "bad kind")
        elif trunc["kind"] == "component_cap":
            if _check_keys(errors, "header.truncation", trunc, TRUNCATION_CAP_KEYS):
                for key in ("components_after_filter", "component_cap"):
                    if not _is_uint(trunc[key]):
                        _fail(errors, "header.truncation", f"{key} not uint")
        else:
            if _check_keys(errors, "header.truncation", trunc, TRUNCATION_BUDGET_KEYS):
                for key in ("required_ops", "op_budget"):
                    if not _is_uint(trunc[key]):
                        _fail(errors, "header.truncation", f"{key} not uint")
        if rec.get("truncated") is not True:
            _fail(errors, "header", "truncation present but truncated is not true")


def _validate_finding(errors, idx, rec):
    path = f"finding[{idx}]"
    if not _check_keys(errors, path, rec, FINDING_KEYS):
        return
    for key in ("finding_id", "chain_id", "component_id"):
        if not is_hex16(rec[key]):
            _fail(errors, path, f"{key} not 16-hex")
    if not _is_uint(rec["label"]):
        _fail(errors, path, "label not uint")
    region = rec["region"]
    if _check_keys(errors, path + ".region", region, REGION_KEYS):
        for key in ("bbox_min", "bbox_max"):
            box = region[key]
            if (not isinstance(box, list) or len(box) != 3
                    or not all(_is_uint(v) for v in box)):
                _fail(errors, path, f"region.{key} malformed")
        wraps = region["wraps"]
        if (not isinstance(wraps, list) or len(wraps) != 3
                or not all(type(w) is bool for w in wraps)):
            _fail(errors, path, "region.wraps malformed")
    if rec["periodic_interpretation"] != PERIODIC_INTERPRETATION:
        _fail(errors, path, "periodic_interpretation literal")
    if not _is_uint(rec["cell_count"]) or rec["cell_count"] < 1:
        _fail(errors, path, "cell_count")
    sc = rec["state_counts"]
    if not isinstance(sc, dict) or tuple(sorted(sc)) != STATE_KEYS:
        _fail(errors, path, "state_counts must have exactly keys 1..4")
    elif not all(_is_uint(v) for v in sc.values()):
        _fail(errors, path, "state_counts values not uint")
    dens = rec["density"]
    if _check_keys(errors, path + ".density", dens, DENSITY_KEYS):
        if not _is_uint(dens["num"]) or not _is_uint(dens["den"]) or dens["den"] == 0:
            _fail(errors, path, "density rational malformed")
    _validate_observation(errors, path + ".snapshot", rec["snapshot"])
    obs_list = rec["observations"]
    if not isinstance(obs_list, list) or not obs_list:
        _fail(errors, path, "observations must be a non-empty list")
    else:
        for j, obs in enumerate(obs_list):
            _validate_observation(errors, f"{path}.observations[{j}]", obs)
    pers = rec["persistence"]
    if _check_keys(errors, path + ".persistence", pers, PERSISTENCE_KEYS):
        if not _is_uint(pers["seen_in_snapshots"]) or pers["seen_in_snapshots"] < 1:
            _fail(errors, path, "persistence.seen_in_snapshots")
        if pers["chain_id"] != rec["chain_id"]:
            _fail(errors, path, "persistence.chain_id must equal chain_id")
    reasons = rec["reasons"]
    if not isinstance(reasons, list) or not reasons:
        _fail(errors, path, "reasons must be a non-empty list")
    else:
        for j, reason in enumerate(reasons):
            if _check_keys(errors, f"{path}.reasons[{j}]", reason, REASON_KEYS):
                if reason["predicate"] not in REASON_PREDICATES:
                    _fail(errors, path, "reason predicate not in closed set")
                if not _is_uint(reason["threshold"]) or not _is_uint(reason["measured"]):
                    _fail(errors, path, "reason numbers not uint")
    if rec["evidence_class"] not in EVIDENCE_CLASSES:
        _fail(errors, path, "evidence_class")
    if rec["truncated"] is not False:
        _fail(errors, path, "finding.truncated must be false in S1")


def _validate_refusal(errors, idx, rec):
    path = f"refusal[{idx}]"
    if not _check_keys(errors, path, rec, REFUSAL_KEYS_REQUIRED,
                       REFUSAL_KEYS_OPTIONAL):
        return
    reason = rec["reason"]
    if reason not in REFUSAL_MESSAGES:
        _fail(errors, path, "reason not in closed enum")
    elif rec["message"] != REFUSAL_MESSAGES[reason]:
        _fail(errors, path, "message must be the fixed table entry")
    if rec["evidence_class"] != "SRC":
        _fail(errors, path, "refusal evidence_class must be SRC")
    if "snapshot_id" in rec and not is_safe_id(rec["snapshot_id"]):
        _fail(errors, path, "snapshot_id grammar")


def validate_records(records):
    """Recursively validate a full artifact record list.

    Returns a list of error strings; empty means the artifact conforms to
    the closed schema (structural forbidden-content closure).
    """
    errors = []
    if not records:
        return ["artifact: empty (header required)"]
    first = records[0]
    if not isinstance(first, dict):
        _fail(errors, "artifact", "first record is not an object")
        return errors
    if first.get("kind") != "header":
        _fail(errors, "artifact", "first record must be the header")
        return errors
    _validate_header(errors, first)
    finding_idx = refusal_count = 0
    seen_refusal = False
    for index, rec in enumerate(records[1:], start=1):
        if not isinstance(rec, dict):
            _fail(errors, "artifact", f"record[{index}] is not an object")
            continue
        kind = rec.get("kind")
        if kind == "finding":
            if seen_refusal:
                _fail(errors, "artifact", "finding after refusal")
            _validate_finding(errors, finding_idx, rec)
            finding_idx += 1
        elif kind == "refusal":
            seen_refusal = True
            _validate_refusal(errors, refusal_count, rec)
            refusal_count += 1
        else:
            _fail(errors, "artifact", f"unknown kind {kind!r}")
    if refusal_count > 1:
        _fail(errors, "artifact", "at most one refusal record")
    if refusal_count == 1 and finding_idx > 0:
        _fail(errors, "artifact", "refusal artifacts carry no findings")
    header = records[0]
    counts = header.get("counts", {})
    if counts.get("findings") != finding_idx or counts.get("refusals") != refusal_count:
        _fail(errors, "artifact", "header counts disagree with records")
    if header.get("empty") is not (finding_idx == 0):
        _fail(errors, "artifact", "header.empty disagrees with findings")
    return errors
