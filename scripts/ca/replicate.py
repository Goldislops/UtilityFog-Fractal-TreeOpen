"""CPU-only deterministic CA replication + provenance CLI (Phase 2B-5G-2).

Runs a *bounded* loop around the audited engine boundary ``step_ca_lattice`` (via
``engine_adapter``), with the CPU/NumPy backend forced on. For ``mode == "replicate"``
every replicate uses the identical seed and parameters, so they must produce byte-equal
scientific arrays and identical scientific hashes.

Scientific claim (this milestone only):
    Under the same repository revision, Python/NumPy environment, CPU backend, manifest,
    initial state and RNG seed, separate bounded launches of this wrapper produce exactly
    equal scientific arrays and identical scientific hashes.
NOT claimed: CPU/GPU identity, cross-machine identity, cross-version identity, faithful
continuation of the full Medusa daemon, or determinism of the live GPU path.

Usage:
    python -m scripts.ca.replicate --manifest <manifest.json> [--out <dir>]
    python -m scripts.ca.replicate --resume <results/<exp>/<run-id>>   # resume a run dir

Run dirs are uniquely named (microsecond timestamp + random nonce) and created
exclusively, so two fresh launches never collide; a per-run lock prevents two processes
from running/resuming the same run dir. ``run.json`` carries a durable status
(running → completed, or interrupted on Ctrl-C).

NOTE: numpy and the engine are imported lazily inside ``main`` *after* thread caps are
set in the environment, so a fresh process honours the requested ``thread_cap``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULE = PROJECT_ROOT / "ca" / "rules" / "example.toml"

ALLOWED_KEYS = {
    "schema_version", "experiment_id", "mode", "backend", "seed",
    "lattice_size", "cube_size", "steps", "replicates",
    "checkpoint_every_steps", "thread_cap",
}
DEFAULTS = {"lattice_size": 8, "checkpoint_every_steps": 1, "thread_cap": 1, "experiment_id": "replicate"}

# experiment_id is used as a *path segment* (results/<experiment_id>/<run_id>/...), so it
# must be a conservative filesystem-safe slug — no traversal, no separators, no drive
# syntax, no whitespace (Jack finding 1). ASCII letters/digits/_/-, starting with an
# alphanumeric, 1..64 chars. This rejects "..", ".", "../x", "a/b", "a\\b", "C:", "a b".
_EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Schema-v1 is a deliberately *bounded* CPU replication harness, not a simulation daemon.
# These conservative upper caps (with the relational + memory guards below) stop a
# manifest from accidentally commandeering the machine (Jack finding 2). There is NO
# configurable "unlimited" escape hatch in schema v1 — widening is a future schema bump.
#   lattice_size: 64 == the engine's own primordial cube edge; aux arrays at 64^3 are
#     ~34 MB (see _estimate_peak_bytes). Bigger is real-Medusa territory, out of scope.
#   steps/replicates: generous but finite ceilings on a sequential CPU loop.
#   thread_cap: capped at the host CPU count (more is pointless and antisocial).
MAX_LATTICE_SIZE = 64
MAX_STEPS = 10_000
MAX_REPLICATES = 100
MAX_ESTIMATED_BYTES = 2 * 1024 ** 3        # 2 GiB peak per single replicate
_BYTES_PER_CELL_ESTIMATE = 128             # memory(8ch*4B) + lattice(1B) + inactivity(2B) + engine temporaries, rounded up

REPRO_CLAIM = (
    "Bitwise R1/R2 on the CPU/NumPy backend within a fixed engine revision + NumPy "
    "version, for this bounded step_ca_lattice loop, given identical seed/manifest."
)
REPRO_LIMITS = (
    "NOT bitwise across CPU vs GPU/CuPy, across machines, or across "
    "NumPy/CuPy/CUDA/driver versions; NOT the full run_v070_engine/Medusa daemon "
    "(no GA cadence/telemetry/wall-clock); the live GPU RNG path remains non-reproducible "
    "and is untouched."
)

# Thread env vars to pin BEFORE numpy import.
_THREAD_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def load_manifest(path: Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _estimate_peak_bytes(lattice_size: int) -> int:
    """Rough peak host-memory estimate for ONE replicate (replicates run sequentially).

    The engine holds an 8-channel float32 memory grid (32 B/cell), the uint8 lattice
    (1 B/cell) and an int16 inactivity grid (2 B/cell), plus per-step neighbour-count /
    mask temporaries — folded into _BYTES_PER_CELL_ESTIMATE (rounded up generously).
    """
    return int(lattice_size) ** 3 * _BYTES_PER_CELL_ESTIMATE


def _thread_ceiling() -> int:
    """Safe upper bound for thread_cap: the host CPU count (more is pointless)."""
    return max(1, os.cpu_count() or 1)


def validate_manifest(m: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a schema-v1 replicate manifest; return a normalised copy or raise ValueError."""
    if not isinstance(m, Mapping):
        raise ValueError("manifest must be a JSON object")
    unknown = set(m) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"unknown manifest keys (schema v1 is narrow): {sorted(unknown)}")
    out: Dict[str, Any] = dict(DEFAULTS)
    out.update(m)
    if out.get("schema_version") != 1:
        raise ValueError(f"schema_version must be 1, got {out.get('schema_version')!r}")
    if out.get("mode") != "replicate":
        raise ValueError(f"unsupported mode {out.get('mode')!r}; only 'replicate' is supported")
    if out.get("backend") != "cpu":
        raise ValueError(f"unsupported backend {out.get('backend')!r}; only 'cpu' is supported")

    # experiment_id: conservative filesystem-safe slug (F1 — no path traversal).
    eid = out.get("experiment_id")
    if not isinstance(eid, str) or not _EXPERIMENT_ID_RE.match(eid):
        raise ValueError(
            "experiment_id must be a slug of ASCII letters/digits/_/- starting with a "
            "letter or digit (1-64 chars); no dots, slashes, backslashes, drive syntax "
            f"or whitespace. got {eid!r}"
        )

    def _bounded_int(key: str, minimum: int, maximum: int | None) -> int:
        v = out.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
            raise ValueError(f"{key} must be an int >= {minimum}, got {v!r}")
        if maximum is not None and v > maximum:
            raise ValueError(
                f"{key}={v} exceeds the schema-v1 safe cap {maximum} "
                "(schema v1 is a bounded harness; no unlimited escape hatch)"
            )
        return v

    if not isinstance(out.get("seed"), int) or isinstance(out.get("seed"), bool) or out["seed"] < 0:
        raise ValueError(f"seed must be an int >= 0, got {out.get('seed')!r}")
    _bounded_int("lattice_size", 1, MAX_LATTICE_SIZE)
    _bounded_int("cube_size", 1, MAX_LATTICE_SIZE)
    _bounded_int("steps", 1, MAX_STEPS)
    _bounded_int("replicates", 2, MAX_REPLICATES)        # replicate mode is meaningless with < 2
    _bounded_int("checkpoint_every_steps", 1, MAX_STEPS)
    _bounded_int("thread_cap", 1, _thread_ceiling())

    # Relational bounds (F2).
    if out["cube_size"] > out["lattice_size"]:
        raise ValueError(
            f"cube_size ({out['cube_size']}) must be <= lattice_size ({out['lattice_size']})"
        )
    if out["checkpoint_every_steps"] > out["steps"]:
        raise ValueError(
            f"checkpoint_every_steps ({out['checkpoint_every_steps']}) must be <= "
            f"steps ({out['steps']})"
        )

    # Belt-and-braces peak-memory guard (secondary to the lattice cap).
    est = _estimate_peak_bytes(out["lattice_size"])
    if est > MAX_ESTIMATED_BYTES:
        raise ValueError(
            f"estimated peak memory {est} bytes for lattice_size={out['lattice_size']} "
            f"exceeds the schema-v1 cap {MAX_ESTIMATED_BYTES} bytes"
        )
    return out


# --------------------------------------------------------------------------- #
# Environment / process controls (stdlib only)
# --------------------------------------------------------------------------- #
def set_thread_caps(n: int) -> None:
    """Pin BLAS/OpenMP thread counts. Must run before numpy is imported to take effect."""
    for var in _THREAD_VARS:
        os.environ[var] = str(int(n))


def best_effort_low_priority() -> str:
    """Best-effort, stdlib-only priority reduction. Never fails the run."""
    try:
        if os.name == "nt":
            import ctypes
            below_normal = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.kernel32.SetPriorityClass(handle, below_normal):
                return "below_normal"
            return "unchanged"
        os.nice(10)
        return "nice+10"
    except Exception:
        return "unchanged"


# --------------------------------------------------------------------------- #
# Provenance / atomic IO
# --------------------------------------------------------------------------- #
def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(PROJECT_ROOT), *args],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def base_provenance(manifest_sha: str, rule_sha: str, thread_cap: int, priority: str) -> Dict[str, Any]:
    import numpy as np
    return {
        "engine_module": "scripts.continuous_evolution_ca",
        "engine_boundary": "step_ca_lattice",
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),  # arch only; no hostname/username/home path
        "backend": "cpu",
        "thread_cap": int(thread_cap),
        "process_priority": priority,
        "manifest_sha256": manifest_sha,
        "rule_sha256": rule_sha,
        "reproducibility_claim": REPRO_CLAIM,
        "reproducibility_limitations": REPRO_LIMITS,
    }


def _atomic_json(path: Path, obj: Any) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_savez(path: Path, **arrays: Any) -> None:
    import numpy as np
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        np.savez_compressed(f, **arrays)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_index(path: Path, rows: list) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Run lifecycle / locking (F5, F6)
# --------------------------------------------------------------------------- #
def _utc_now() -> str:
    """UTC timestamp with microsecond precision (used for run IDs + provenance)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")


def _acquire_run_lock(run_dir: Path) -> int:
    """Exclusive per-run lock so two processes can't run/resume the same run dir.

    Uses O_CREAT|O_EXCL — fail-fast if the lock already exists. Returns the fd.
    """
    lock_path = Path(run_dir) / "run.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"run directory is locked by another process (stale lock?): {lock_path}"
        )
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
    except Exception:
        pass
    return fd


def _release_run_lock(fd: int, run_dir: Path) -> None:
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        (Path(run_dir) / "run.lock").unlink()
    except Exception:
        pass


def _validate_completed_result(res: Mapping[str, Any], manifest_sha: str,
                               m: Mapping[str, Any]) -> None:
    """Reject a reused completed replicate whose identity doesn't match the manifest —
    exactly as checkpoints are rejected (F6). Never silently trust stale results."""
    expected = {
        "manifest_sha256": manifest_sha,
        "backend": "cpu",
        "seed": int(m["seed"]),
        "lattice_size": int(m["lattice_size"]),
        "cube_size": int(m["cube_size"]),
    }
    for key, want in expected.items():
        got = res.get(key)
        ok = (int(got) == want) if key in ("seed", "lattice_size", "cube_size") and got is not None \
            else (got == want)
        if not ok:
            raise ValueError(
                f"completed result {key} mismatch (got {got!r}, expected {want!r}); "
                "refusing to reuse a stale/incompatible replicate"
            )


def _build_run_record(status: str, base_prov: Dict[str, Any], m: Mapping[str, Any],
                      run_id: str, started: str, resumed: list, rep_hashes: list,
                      all_identical, finished) -> Dict[str, Any]:
    rec = {
        **base_prov,
        "schema_version": 1,
        "experiment_id": m["experiment_id"],
        "run_id": run_id,
        "mode": "replicate",
        "status": status,
        "seed": int(m["seed"]),
        "lattice_size": int(m["lattice_size"]),
        "cube_size": int(m["cube_size"]),
        "steps": int(m["steps"]),
        "replicates": int(m["replicates"]),
        "started_utc": started,
        "resumed_utc": list(resumed),
        "finished_utc": finished,
        "replicate_trajectory_hashes": list(rep_hashes),
        "all_replicates_identical": all_identical,
    }
    return rec


# --------------------------------------------------------------------------- #
# Replicate execution
# --------------------------------------------------------------------------- #
def _write_checkpoint(ea, ckdir: Path, step: int, state, inactivity, memory,
                      rng, traj_hash: str, manifest_sha: str, m: Mapping[str, Any]) -> None:
    meta = {
        "schema_version": 1,
        "step": int(step),
        "seed": int(m["seed"]),
        "lattice_size": int(m["lattice_size"]),
        "cube_size": int(m["cube_size"]),
        "backend": "cpu",
        "manifest_sha256": manifest_sha,
        "traj_hash": traj_hash,
        "rng_state": ea.get_rng_state(rng),
    }
    import numpy as np
    _atomic_savez(
        ckdir / f"checkpoint_step_{step:09d}.npz",
        lattice=state,
        memory_grid=memory,
        inactivity_steps=inactivity,
        meta_json=np.array(json.dumps(meta)),
    )


def _latest_checkpoint(ckdir: Path):
    if not ckdir.is_dir():
        return None
    cks = sorted(ckdir.glob("checkpoint_step_*.npz"))
    return cks[-1] if cks else None


def run_replicate(ce, ea, rule_spec, rule_sha, manifest_sha, m: Mapping[str, Any],
                  rep_index: int, rep_dir: Path, base_prov: Dict[str, Any],
                  resume: bool = False) -> Dict[str, Any]:
    """Run (or resume) one replicate; write checkpoints + final_state + result.json."""
    import numpy as np
    rep_dir = Path(rep_dir)
    ckdir = rep_dir / "checkpoints"
    ckdir.mkdir(parents=True, exist_ok=True)
    target_steps = int(m["steps"])
    ck_every = int(m["checkpoint_every_steps"])
    seed = int(m["seed"])

    if resume:
        ckpath = _latest_checkpoint(ckdir)
        if ckpath is None:
            raise ValueError(f"--resume requested but no checkpoint found in {ckdir}")
        with np.load(ckpath, allow_pickle=False) as data:
            state = np.array(data["lattice"], dtype=np.uint8)
            memory = np.array(data["memory_grid"], dtype=np.float32)
            inactivity = np.array(data["inactivity_steps"], dtype=np.int16)
            meta = json.loads(data["meta_json"].item())
        # Identity checks — never silently continue an incompatible checkpoint.
        if meta.get("manifest_sha256") != manifest_sha:
            raise ValueError("checkpoint manifest hash mismatch; refusing to resume")
        if int(meta.get("seed", -1)) != seed:
            raise ValueError("checkpoint seed mismatch; refusing to resume")
        if int(meta.get("lattice_size", -1)) != int(m["lattice_size"]):
            raise ValueError("checkpoint lattice_size mismatch; refusing to resume")
        if meta.get("backend") != "cpu":
            raise ValueError("checkpoint backend is not cpu; refusing to resume")
        step = int(meta["step"])
        traj = str(meta["traj_hash"])
        rng = ea.restore_rng(seed, meta["rng_state"])
    else:
        state = ea.make_seed(m["lattice_size"], m["cube_size"])
        memory = ce.init_memory_grid(state.shape)
        memory = np.array(memory, dtype=np.float32)  # ensure host/numpy (CPU forced)
        inactivity = np.zeros(state.shape, dtype=np.int16)
        rng = ea.make_rng(seed)
        step = 0
        # Fold the initial state (incl. inactivity) into the trajectory hash.
        traj = ea.chain_hash("INIT", 0, state, memory, inactivity)
        _write_checkpoint(ea, ckdir, step, state, inactivity, memory, rng, traj, manifest_sha, m)

    while step < target_steps:
        state, inactivity, memory, _metrics = ea.step_once(
            ce, state, rule_spec, rng, inactivity, memory, current_gen=step)
        step += 1
        traj = ea.chain_hash(traj, step, state, memory, inactivity)
        if step % ck_every == 0 or step == target_steps:
            _write_checkpoint(ea, ckdir, step, state, inactivity, memory, rng, traj, manifest_sha, m)

    final_hash = ea.scientific_hash(state, memory, inactivity)
    _atomic_savez(rep_dir / "final_state.npz", lattice=state, memory_grid=memory,
                  inactivity_steps=inactivity)
    result = {
        **base_prov,
        "replicate_index": int(rep_index),
        "status": "completed",
        "seed": seed,
        "lattice_size": int(m["lattice_size"]),
        "cube_size": int(m["cube_size"]),
        "target_steps": target_steps,
        "completed_steps": int(step),
        "final_scientific_hash": final_hash,
        "trajectory_hash": traj,
    }
    _atomic_json(rep_dir / "result.json", result)
    return result


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CPU-only deterministic CA replication + provenance")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="Path to a schema-v1 replicate manifest (required for a fresh run)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "results")
    parser.add_argument("--resume", type=Path, default=None,
                        help="Path to an existing run dir to resume (skips completed replicates, "
                             "continues the partial one from its latest checkpoint)")
    args = parser.parse_args(argv)

    resuming = args.resume is not None
    if resuming:
        run_dir = Path(args.resume)
        m = validate_manifest(load_manifest(run_dir / "manifest.json"))
    else:
        if args.manifest is None:
            parser.error("--manifest is required for a fresh run")
        m = validate_manifest(load_manifest(args.manifest))

    # Pin threads BEFORE importing numpy/the engine.
    set_thread_caps(m["thread_cap"])
    priority = best_effort_low_priority()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.ca import engine_adapter as ea  # noqa: E402  (after thread caps)

    rule_spec = ea.default_rule_spec()
    rule_sha = ea.rule_spec_hash(rule_spec)
    manifest_sha = _sha256_text(json.dumps(m, sort_keys=True))
    base_prov = base_provenance(manifest_sha, rule_sha, m["thread_cap"], priority)
    base_prov["rule_name"] = rule_spec["rule"]["name"]
    base_prov["rule_source"] = str(DEFAULT_RULE.relative_to(PROJECT_ROOT)).replace("\\", "/")
    base_prov["rule_delivery"] = "in-code (DEFAULT_RULE_SPEC); source TOML not parsed at runtime"
    base_prov["scientific_hash_arrays"] = list(ea.SCIENTIFIC_ARRAY_ORDER)

    if resuming:
        run_id = run_dir.name
        # Preserve the ORIGINAL run start; record each resume separately (F6).
        prior = {}
        prior_path = run_dir / "run.json"
        if prior_path.exists():
            try:
                prior = json.loads(prior_path.read_text(encoding="utf-8"))
            except Exception:
                prior = {}
        started = prior.get("started_utc") or _utc_now()
        resumed = list(prior.get("resumed_utc", []))
        resumed.append(_utc_now())
    else:
        started = _utc_now()
        # Microsecond timestamp + random nonce → no two fresh launches can collide (F5);
        # the nonce is a directory identifier ONLY and never enters any scientific hash.
        nonce = secrets.token_hex(3)
        run_id = f"{started}__{m['experiment_id']}__s{m['seed']}__{manifest_sha[:8]}__{nonce}"
        run_dir = Path(args.out) / m["experiment_id"] / run_id
        run_dir.mkdir(parents=True, exist_ok=False)  # exclusive: never silently reuse
        _atomic_json(run_dir / "manifest.json", m)
        resumed = []

    lock_fd = _acquire_run_lock(run_dir)
    index_rows: list = []
    rep_hashes: list = []
    try:
        # Durable lifecycle status BEFORE any compute (F6).
        _atomic_json(run_dir / "run.json", _build_run_record(
            "running", base_prov, m, run_id, started, resumed, [], None, None))

        with ea.cpu_engine() as ce:
            for rep in range(int(m["replicates"])):
                rep_dir = run_dir / f"replicate_{rep:03d}"
                result_path = rep_dir / "result.json"
                if result_path.exists():
                    # Reuse a prior-launch completion — but verify its identity first (F6).
                    res = json.loads(result_path.read_text(encoding="utf-8"))
                    _validate_completed_result(res, manifest_sha, m)
                else:
                    has_ck = _latest_checkpoint(rep_dir / "checkpoints") is not None
                    res = run_replicate(ce, ea, rule_spec, rule_sha, manifest_sha, m, rep, rep_dir,
                                        base_prov, resume=has_ck)
                rep_hashes.append(res["trajectory_hash"])
                index_rows.append({
                    "run_id": run_id, "replicate_index": rep, "status": res["status"],
                    "final_scientific_hash": res["final_scientific_hash"],
                    "trajectory_hash": res["trajectory_hash"],
                    "completed_steps": res["completed_steps"], "seed": res["seed"], "backend": "cpu",
                })
                _atomic_index(run_dir / "index.jsonl", index_rows)  # rebuilt atomically each replicate

        all_identical = len(set(rep_hashes)) == 1
        finished = _utc_now()
        _atomic_json(run_dir / "run.json", _build_run_record(
            "completed", base_prov, m, run_id, started, resumed, rep_hashes, all_identical, finished))

        print(json.dumps({
            "run_id": run_id, "run_dir": str(run_dir),
            "all_replicates_identical": all_identical,
            "final_scientific_hash": index_rows[0]["final_scientific_hash"] if index_rows else None,
        }, indent=2))
        return 0 if all_identical else 2
    except KeyboardInterrupt:
        # Record a clean, durable interrupted status and exit with the conventional code.
        _atomic_json(run_dir / "run.json", _build_run_record(
            "interrupted", base_prov, m, run_id, started, resumed, rep_hashes, None, _utc_now()))
        print(json.dumps({"run_id": run_id, "run_dir": str(run_dir), "status": "interrupted"}))
        return 130
    finally:
        _release_run_lock(lock_fd, run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
