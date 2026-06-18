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
    python -m scripts.ca.replicate --manifest <manifest.json> [--out <dir>] \
        [--resume <results/.../replicate_000>]

NOTE: numpy and the engine are imported lazily inside ``main`` *after* thread caps are
set in the environment, so a fresh process honours the requested ``thread_cap``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
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
    def _pos_int(key: str, minimum: int) -> int:
        v = out.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
            raise ValueError(f"{key} must be an int >= {minimum}, got {v!r}")
        return v
    if not isinstance(out.get("seed"), int) or isinstance(out.get("seed"), bool) or out["seed"] < 0:
        raise ValueError(f"seed must be an int >= 0, got {out.get('seed')!r}")
    _pos_int("lattice_size", 1)
    _pos_int("cube_size", 1)
    _pos_int("steps", 1)
    _pos_int("replicates", 2)        # replicate mode is meaningless with < 2
    _pos_int("checkpoint_every_steps", 1)
    _pos_int("thread_cap", 1)
    if not isinstance(out.get("experiment_id"), str) or not out["experiment_id"]:
        raise ValueError("experiment_id must be a non-empty string")
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


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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
            meta = json.loads(str(data["meta_json"]))
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
        # Fold the initial state into the trajectory hash.
        traj = ea.chain_hash("INIT", 0, state, memory)
        _write_checkpoint(ea, ckdir, step, state, inactivity, memory, rng, traj, manifest_sha, m)

    while step < target_steps:
        state, inactivity, memory, _metrics = ea.step_once(
            ce, state, rule_spec, rng, inactivity, memory, current_gen=step)
        step += 1
        traj = ea.chain_hash(traj, step, state, memory)
        if step % ck_every == 0 or step == target_steps:
            _write_checkpoint(ea, ckdir, step, state, inactivity, memory, rng, traj, manifest_sha, m)

    final_hash = ea.scientific_hash(state, memory)
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

    manifest_sha = _sha256_text(json.dumps(m, sort_keys=True))
    rule_sha = _sha256_file(DEFAULT_RULE)
    base_prov = base_provenance(manifest_sha, rule_sha, m["thread_cap"], priority)
    base_prov["rule_path"] = str(DEFAULT_RULE.relative_to(PROJECT_ROOT)).replace("\\", "/")

    if resuming:
        run_id = run_dir.name
        started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    else:
        started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{started}__{m['experiment_id']}__s{m['seed']}__{manifest_sha[:8]}"
        run_dir = Path(args.out) / m["experiment_id"] / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(run_dir / "manifest.json", m)

    index_rows = []
    rep_hashes = []
    with ea.cpu_engine() as ce:
        rule_spec = ce.load_rule_spec(DEFAULT_RULE)
        for rep in range(int(m["replicates"])):
            rep_dir = run_dir / f"replicate_{rep:03d}"
            result_path = rep_dir / "result.json"
            if result_path.exists():
                # Already completed in a prior launch — skip recompute, reuse result.
                res = json.loads(result_path.read_text(encoding="utf-8"))
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
    finished = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_record = {
        **base_prov,
        "schema_version": 1,
        "experiment_id": m["experiment_id"],
        "run_id": run_id,
        "mode": "replicate",
        "status": "completed",
        "seed": int(m["seed"]),
        "lattice_size": int(m["lattice_size"]),
        "cube_size": int(m["cube_size"]),
        "steps": int(m["steps"]),
        "replicates": int(m["replicates"]),
        "started_utc": started,
        "finished_utc": finished,
        "replicate_trajectory_hashes": rep_hashes,
        "all_replicates_identical": all_identical,
    }
    _atomic_json(run_dir / "run.json", run_record)

    print(json.dumps({
        "run_id": run_id, "run_dir": str(run_dir),
        "all_replicates_identical": all_identical,
        "final_scientific_hash": index_rows[0]["final_scientific_hash"] if index_rows else None,
    }, indent=2))
    return 0 if all_identical else 2


if __name__ == "__main__":
    raise SystemExit(main())
