"""S1 toy-only offline connected-component persistence detector.

Implements the frozen S1 contract (S0 = merged docs/SWARM_HUNTER_V1_PREFLIGHT.md,
plus the audited amendment freeze under Jack's controlling S0 reconciliation):

- pure function over SYNTHETIC in-memory NumPy arrays; zero I/O of any kind;
- 6-face periodic connectivity on cubic lattices (N <= 64), non-VOID membership;
- deterministic minimum-member labels; toroidal largest-gap bounding boxes;
- exact rational density; fixed "1".."4" state-count keys including zeros;
- persistence chains by exact state-labelled occupied-cell-set equality;
- component-cap exhaustion  -> deterministic prefix + header truncation record;
- op-budget exhaustion      -> preflight, header-only truncated artifact;
- malformed input           -> fatal structured refusal, no findings;
- canonical little-endian, length-prefixed hashing; safe identifier grammar;
- authoritative immutable JSONL bytes; byte-identical replay.

Nothing here observes, proposes, tunes, commands, or communicates: the output
is a bounded description of synthetic arrays, and the import quarantine to and
from ``scripts/`` is asserted by tests in both directions.
"""

import dataclasses
import hashlib
import json
import struct
from typing import Mapping, Optional, Sequence

import numpy as np

from . import schema

DETECTOR_NAME = "cc_persistence"
DETECTOR_VERSION = "s1.0.0"
SCHEMA_ID = schema.SCHEMA_ID

MAX_N = 64
MAX_GENERATION = 2 ** 64 - 1
LEANCTX_MAX_BYTES = 64 * 1024
LEANCTX_MAX_RECORDS = 200

_ALLOWED_SNAPSHOT_KEYS = {"states", "memory", "inactivity_steps", "provenance"}
_PROVENANCE_KEYS = {
    "snapshot_id", "sha256_triple", "generation", "lattice_size",
    "num_states", "channel_layout_version", "source",
}


def lp(value) -> bytes:
    """Length-prefixed field: uint32-LE byte length, then the bytes.

    Kills delimiter-concatenation preimage ambiguity: LP("ab")+LP("c") can
    never equal LP("a")+LP("bc").
    """
    raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    return struct.pack("<I", len(raw)) + raw


def _array_digest(name: str, arr: Optional[np.ndarray], canonical_dtype: str) -> str:
    if arr is None:
        return hashlib.sha256(lp("uft-lab-absent-v1") + lp(name)).hexdigest()
    canon = np.ascontiguousarray(arr, dtype=np.dtype(canonical_dtype))
    shape_csv = ",".join(str(d) for d in canon.shape)
    preimage = (lp("uft-lab-arr-v1") + lp(name) + lp(canonical_dtype)
                + lp(shape_csv) + lp("LE") + canon.tobytes(order="C"))
    return hashlib.sha256(preimage).hexdigest()


def compute_sha256_triple(states, memory=None, inactivity_steps=None):
    """Canonical named-key sha256 mapping over the (possibly absent) triple."""
    return {
        "states": _array_digest("states", states, "uint8"),
        "memory": _array_digest("memory", memory, "<f4"),
        "inactivity_steps": _array_digest("inactivity_steps", inactivity_steps, "<i2"),
    }


@dataclasses.dataclass(frozen=True)
class DetectorConfig:
    """Closed, immutable configuration. Validated inside detect_structures
    (stage 1 of the frozen first-failure order), not in __post_init__, so an
    invalid configuration yields a structured refusal artifact."""
    min_component_size: int = 2
    component_cap: int = 4096
    op_budget_multiplier: int = 16


_CONFIG_BOUNDS = {
    "min_component_size": (1, MAX_N ** 3),
    "component_cap": (1, 4096),
    "op_budget_multiplier": (1, 1024),
}


@dataclasses.dataclass(frozen=True)
class FindingsArtifact:
    """The authoritative canonical result is the immutable ``jsonl`` bytes.
    ``records()`` returns freshly decoded copies on every call; mutating them
    cannot affect the canonical artifact."""
    jsonl: bytes

    def records(self):
        return tuple(json.loads(line)
                     for line in self.jsonl.decode("utf-8").splitlines())


class _Refusal(Exception):
    def __init__(self, reason: str, snapshot_id: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.snapshot_id = snapshot_id


# ---------------------------------------------------------------------------
# validation (frozen first-failure order)
# ---------------------------------------------------------------------------

def _validate_config(config) -> None:
    if type(config) is not DetectorConfig:
        raise _Refusal("invalid_config")
    for name, (lo, hi) in _CONFIG_BOUNDS.items():
        value = getattr(config, name)
        if isinstance(value, bool) or type(value) is not int:
            raise _Refusal("invalid_config")
        if not lo <= value <= hi:
            raise _Refusal("invalid_config")


def _validate_identifier(value) -> str:
    # schema.is_safe_id: exact-str + fullmatch (trailing newline, non-str,
    # and any grammar violation all yield the frozen structured refusal).
    if not schema.is_safe_id(value):
        raise _Refusal("invalid_identifier")
    return value


def _validate_states(arr, sid: Optional[str]) -> int:
    if type(arr) is not np.ndarray or arr.dtype != np.uint8 or arr.ndim != 3:
        raise _Refusal("invalid_input", sid)
    n = arr.shape[0]
    if arr.shape != (n, n, n) or n < 1:
        raise _Refusal("invalid_input", sid)
    if n > MAX_N:
        raise _Refusal("lattice_too_large", sid)
    return n


def _validate_snapshot(item, ctx):
    """Stages 3a-3h for one snapshot. Returns the validated snapshot dict."""
    if not isinstance(item, Mapping):
        raise _Refusal("invalid_input")
    keys = set(item.keys())
    if not keys <= _ALLOWED_SNAPSHOT_KEYS or "states" not in keys or "provenance" not in keys:
        raise _Refusal("invalid_input")

    prov = item["provenance"]
    if not isinstance(prov, Mapping) or set(prov.keys()) != _PROVENANCE_KEYS:
        raise _Refusal("invalid_provenance")

    sid = _validate_identifier(prov["snapshot_id"])
    ctx["ids_seen"].append(sid)
    clv = _validate_identifier(prov["channel_layout_version"])

    if prov["source"] != "synthetic":
        raise _Refusal("s2_gated", sid)

    states = item["states"]
    n = _validate_states(states, sid)

    lattice_size = prov["lattice_size"]
    if isinstance(lattice_size, bool) or type(lattice_size) is not int or lattice_size != n:
        raise _Refusal("invalid_provenance", sid)
    num_states = prov["num_states"]
    if isinstance(num_states, bool) or type(num_states) is not int:
        raise _Refusal("invalid_provenance", sid)
    if num_states != 5:
        raise _Refusal("unsupported_num_states", sid)
    generation = prov["generation"]
    if isinstance(generation, bool) or type(generation) is not int \
            or not 0 <= generation <= MAX_GENERATION:
        raise _Refusal("invalid_provenance", sid)
    ctx["gens_seen"].append(generation)

    if int(states.max()) > 4:
        raise _Refusal("invalid_state_value", sid)

    memory = item.get("memory")
    if memory is not None:
        if (type(memory) is not np.ndarray or memory.dtype != np.float32
                or memory.shape != (8, n, n, n)):
            raise _Refusal("invalid_optional_data", sid)
        if not bool(np.isfinite(memory).all()):
            raise _Refusal("invalid_optional_data", sid)
    inactivity = item.get("inactivity_steps")
    if inactivity is not None:
        if (type(inactivity) is not np.ndarray or inactivity.dtype != np.int16
                or inactivity.shape != (n, n, n)):
            raise _Refusal("invalid_optional_data", sid)

    supplied = prov["sha256_triple"]
    if (not isinstance(supplied, Mapping)
            or set(supplied.keys()) != schema.SHA256_TRIPLE_KEYS):
        raise _Refusal("invalid_sha256_format", sid)
    for slot in sorted(schema.SHA256_TRIPLE_KEYS):
        if not schema.is_hex64(supplied[slot]):
            raise _Refusal("invalid_sha256_format", sid)
    computed = compute_sha256_triple(states, memory, inactivity)
    if {k: supplied[k] for k in computed} != computed:
        raise _Refusal("provenance_hash_mismatch", sid)

    return {
        "snapshot_id": sid,
        "generation": generation,
        "channel_layout_version": clv,
        "n": n,
        "states": states,
        "sha256_triple": computed,  # emit verified values, never caller prose
    }


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def _find(parent, i):
    root = i
    while parent[root] != root:
        root = parent[root]
    while parent[i] != root:
        parent[i], i = root, parent[i]
    return root


def _components(states: np.ndarray, n: int):
    """6-face periodic connected components of non-VOID cells.

    Returns a list of ascending member-index lists, one per component,
    ordered by minimum member (== label) ascending. Flat index convention is
    the source-exact z*N*N + y*N + x (C-order ravel of a [z][y][x] array).
    """
    flat = states.reshape(-1)
    occupied = np.flatnonzero(flat)
    occ_set = set(int(i) for i in occupied)
    parent = {i: i for i in occ_set}
    size = {i: 1 for i in occ_set}
    nn = n * n
    for f in sorted(occ_set):
        x = f % n
        y = (f // n) % n
        z = f // nn
        for nb in ((z * nn + y * n + (x + 1) % n),
                   (z * nn + ((y + 1) % n) * n + x),
                   (((z + 1) % n) * nn + y * n + x)):
            if nb in occ_set and nb != f:
                ra, rb = _find(parent, f), _find(parent, nb)
                if ra != rb:
                    # union by size; ties -> smaller root index wins
                    if size[ra] < size[rb] or (size[ra] == size[rb] and rb < ra):
                        ra, rb = rb, ra
                    parent[rb] = ra
                    size[ra] += size[rb]
    groups = {}
    for f in sorted(occ_set):
        groups.setdefault(_find(parent, f), []).append(f)
    return sorted(groups.values(), key=lambda members: members[0])


def _axis_interval(coords, n):
    """Canonical minimal cyclic covering interval for one axis.

    Largest-gap complement; ties broken by smallest resulting bbox_min
    (total, because distinct gaps yield distinct interval starts)."""
    occ = sorted(set(coords))
    if len(occ) == n:
        return 0, n - 1, False
    if len(occ) == 1:
        return occ[0], occ[0], False
    best = None  # (start, end, gap_len)
    count = len(occ)
    for i in range(count):
        prev_c = occ[i]
        next_c = occ[(i + 1) % count]
        if i < count - 1:
            gap_len = next_c - prev_c - 1
        else:  # cyclic gap across the seam, from occ[-1] up to occ[0]
            gap_len = occ[0] + n - occ[-1] - 1
        if gap_len <= 0:
            continue
        start, end = next_c, prev_c  # complement of this gap
        if (best is None or gap_len > best[2]
                or (gap_len == best[2] and start < best[0])):
            best = (start, end, gap_len)
    start, end, _ = best
    return start, end, start > end


def _region(members, n):
    xs = [f % n for f in members]
    ys = [(f // n) % n for f in members]
    zs = [f // (n * n) for f in members]
    mins, maxs, wraps = [], [], []
    for coords in (xs, ys, zs):
        lo, hi, wrapped = _axis_interval(coords, n)
        mins.append(lo)
        maxs.append(hi)
        wraps.append(wrapped)
    return {"bbox_min": mins, "bbox_max": maxs, "wraps": wraps}


def _region_encoding(members, flat_states, n) -> bytes:
    body = b"".join(struct.pack("<IB", f, int(flat_states[f])) for f in members)
    return (lp("uft-lab-region-v1") + struct.pack("<I", n)
            + struct.pack("<I", len(members)) + body)


def _hex16(domain: str, *parts) -> str:
    preimage = lp(domain)
    for part in parts:
        preimage += part if isinstance(part, bytes) else lp(part)
    return hashlib.sha256(preimage).hexdigest()[:16]


# ---------------------------------------------------------------------------
# artifact assembly
# ---------------------------------------------------------------------------

def _params_dict(config):
    return {
        "min_component_size": config.min_component_size,
        "component_cap": config.component_cap,
        "op_budget_multiplier": config.op_budget_multiplier,
        "connectivity": schema.CONNECTIVITY,
        "state_map": dict(schema.STATE_MAP),
    }


def _header(params, ids, gens, discovered, emitted, findings, refusals,
            truncated=False, truncation=None):
    return {
        "kind": "header",
        "schema": SCHEMA_ID,
        "detector": {"name": DETECTOR_NAME, "version": DETECTOR_VERSION},
        "run": {"snapshot_count": len(ids), "snapshot_ids": list(ids),
                "generations": list(gens)},
        "params": params,
        "counts": {"components_discovered": discovered,
                   "components_emitted": emitted,
                   "findings": findings, "refusals": refusals},
        "empty": findings == 0,
        "truncated": truncated,
        "truncation": truncation,
    }


def _observation(snap):
    return {
        "snapshot_id": snap["snapshot_id"],
        "generation": snap["generation"],
        "channel_layout_version": snap["channel_layout_version"],
        "source": "synthetic",
        "sha256_triple": dict(snap["sha256_triple"]),
    }


def _finalize(records) -> FindingsArtifact:
    errors = schema.validate_records(records)
    if errors:  # internal invariant; a conforming build never reaches this
        raise AssertionError("schema self-check failed: " + "; ".join(errors))
    return FindingsArtifact(b"".join(schema.canonical_line(r) for r in records))


def _refusal_artifact(refusal, config_valid, config, ids, gens) -> FindingsArtifact:
    params = _params_dict(config) if config_valid else None
    header = _header(params, ids, gens, 0, 0, 0, 1)
    record = {
        "kind": "refusal",
        "reason": refusal.reason,
        "message": schema.REFUSAL_MESSAGES[refusal.reason],
        "evidence_class": "SRC",
    }
    if refusal.snapshot_id is not None:
        record["snapshot_id"] = refusal.snapshot_id
    return _finalize([header, record])


def detect_structures(snapshots, config: DetectorConfig = DetectorConfig()) -> FindingsArtifact:
    """Analyze an ordered sequence of synthetic snapshots. Pure and
    deterministic: identical inputs yield byte-identical ``jsonl``."""
    ctx = {"ids_seen": [], "gens_seen": []}
    config_valid = False
    try:
        _validate_config(config)                                   # stage 1
        config_valid = True
        if (isinstance(snapshots, (str, bytes, Mapping))
                or not isinstance(snapshots, Sequence) or len(snapshots) == 0):
            raise _Refusal("invalid_input")                        # stage 2
        validated = [_validate_snapshot(item, ctx) for item in snapshots]  # 3

        ids = [s["snapshot_id"] for s in validated]                # stage 4
        if len(set(ids)) != len(ids):
            raise _Refusal("duplicate_snapshot_id")
        gens = [s["generation"] for s in validated]
        if any(b <= a for a, b in zip(gens, gens[1:])):
            raise _Refusal("nonmonotonic_generation")
        n = validated[0]["n"]
        if any(s["n"] != n for s in validated):
            raise _Refusal("inconsistent_lattice_size")

        if config.min_component_size > n ** 3:                     # stage 5
            raise _Refusal("invalid_config_for_volume")
    except _Refusal as refusal:
        return _refusal_artifact(refusal, config_valid, config,
                                 ctx["ids_seen"], ctx["gens_seen"])

    params = _params_dict(config)

    # stage 6 — deterministic preflight operation budget (input-determined:
    # one classification per voxel plus three positive-direction neighbor
    # examinations per occupied voxel; union-find internals, hashing, and
    # serialization are deliberately outside the counter; not a wall-clock
    # or adversarial-runtime security bound).
    volume = n ** 3
    required_ops = sum(volume + 3 * int(np.count_nonzero(s["states"]))
                       for s in validated)
    op_budget = config.op_budget_multiplier * volume * len(validated)
    ids = [s["snapshot_id"] for s in validated]
    gens = [s["generation"] for s in validated]
    if required_ops > op_budget:
        header = _header(params, ids, gens, 0, 0, 0, 0, truncated=True,
                         truncation={"kind": "op_budget_preflight",
                                     "required_ops": required_ops,
                                     "op_budget": op_budget})
        return _finalize([header])

    # stage 7 — discovery, chains, filter, deterministic cap prefix.
    discovered = 0
    chains = {}  # region_encoding bytes -> chain dict
    for idx, snap in enumerate(validated):
        flat = snap["states"].reshape(-1)
        for members in _components(snap["states"], n):
            discovered += 1
            enc = _region_encoding(members, flat, n)
            chain = chains.get(enc)
            if chain is None:
                chains[enc] = {
                    "enc": enc, "members": members, "first_idx": idx,
                    "obs_idx": [idx],
                    "label": members[0],
                    "flat_states": [int(flat[f]) for f in members],
                }
            else:
                chain["obs_idx"].append(idx)

    eligible = [c for c in chains.values()
                if len(c["members"]) >= config.min_component_size]
    for chain in eligible:
        first = validated[chain["first_idx"]]
        chain["chain_id"] = _hex16("uft-lab-chain-v1", DETECTOR_VERSION, chain["enc"])
        chain["first_gen"] = first["generation"]
    eligible.sort(key=lambda c: (c["label"], c["first_gen"], c["chain_id"]))

    truncated = len(eligible) > config.component_cap
    emitted_chains = eligible[:config.component_cap]
    truncation = None
    if truncated:
        truncation = {"kind": "component_cap",
                      "components_after_filter": len(eligible),
                      "component_cap": config.component_cap}

    findings = []
    emitted_instances = 0
    for chain in emitted_chains:
        first = validated[chain["first_idx"]]
        members = chain["members"]
        counts = {key: 0 for key in schema.STATE_KEYS}
        for state in chain["flat_states"]:
            counts[str(state)] += 1
        emitted_instances += len(chain["obs_idx"])
        findings.append({
            "kind": "finding",
            "finding_id": _hex16("uft-lab-finding-v1", DETECTOR_VERSION,
                                 first["snapshot_id"], chain["enc"]),
            "chain_id": chain["chain_id"],
            "component_id": _hex16("uft-lab-component-v1", DETECTOR_VERSION,
                                   first["snapshot_id"], chain["enc"]),
            "label": chain["label"],
            "region": _region(members, n),
            "periodic_interpretation": schema.PERIODIC_INTERPRETATION,
            "cell_count": len(members),
            "state_counts": counts,
            "density": {"num": len(members), "den": volume},
            "snapshot": _observation(first),
            "observations": [_observation(validated[i]) for i in chain["obs_idx"]],
            "persistence": {"seen_in_snapshots": len(chain["obs_idx"]),
                            "chain_id": chain["chain_id"]},
            "reasons": [{"predicate": "cell_count>=min_component_size",
                         "threshold": config.min_component_size,
                         "measured": len(members)}],
            "evidence_class": "CALC",
            "truncated": False,
        })

    header = _header(params, ids, gens, discovered, emitted_instances,
                     len(findings), 0, truncated=truncated, truncation=truncation)
    return _finalize([header] + findings)


# ---------------------------------------------------------------------------
# bounded human audit handoff (S0 §8) — timestamps deliberately excluded from
# canonical detector bytes; the human packet assembler adds them outside.
# ---------------------------------------------------------------------------

def leanctx_summary(artifact: FindingsArtifact, run_label: str) -> bytes:
    if not schema.is_safe_id(run_label):
        raise ValueError("run_label must satisfy the safe identifier grammar")
    records = artifact.records()
    if not records:
        raise ValueError("artifact contains no records")
    # Conformance gate before any header/record indexing: a JSON-decodable but
    # non-conforming artifact (e.g. a hand-built FindingsArtifact whose header
    # lacks "counts") must fail as a deterministic ValueError here, never as a
    # KeyError deeper in this function. schema.validate_records is already total
    # (returns a list, never raises) on any JSON-decodable input. The exception
    # carries a fixed message only — the validator's error detail is not exposed
    # through this public surface. Valid detector-produced artifacts validate
    # clean (detect_structures self-checks the same records in _finalize), so
    # their LeanCTX output is byte-identical.
    if schema.validate_records(records):
        raise ValueError("artifact is not a conforming findings artifact")
    header = records[0]
    rows = [{"kind": "leanctx-row", "finding_id": r["finding_id"],
             "label": r["label"], "cell_count": r["cell_count"],
             "seen_in_snapshots": r["persistence"]["seen_in_snapshots"]}
            for r in records[1:] if r["kind"] == "finding"]
    kept = rows[:LEANCTX_MAX_RECORDS - 1]
    while True:
        summary = {
            "kind": "leanctx-header", "schema": schema.LEANCTX_SCHEMA_ID,
            "run_label": run_label,
            "artifact_sha256": hashlib.sha256(artifact.jsonl).hexdigest(),
            "source_counts": dict(header["counts"]),
            "source_truncated": header["truncated"],
            "rows_included": len(kept), "rows_omitted": len(rows) - len(kept),
            "truncated": len(kept) < len(rows),
        }
        payload = b"".join(schema.canonical_line(r) for r in [summary] + kept)
        if len(payload) <= LEANCTX_MAX_BYTES or not kept:
            return payload
        kept = kept[:-1]
