#!/usr/bin/env python3
"""Tests for the CPU-only deterministic CA replication wrapper (Phase 2B-5G-2).

These cover the three milestone guarantees:

1. Separate-launch exact replication -- two *independent* OS process launches of the
   CLI, plus every replicate within a run, produce identical scientific hashes.
2. Checkpoint / resume equivalence -- resuming an interrupted run from its on-disk
   checkpoints reproduces exactly the same result as an uninterrupted run.
3. Safety validation -- non-replicate modes, the GPU backend, and out-of-bounds or
   unknown manifest fields are rejected; the CPU/NumPy backend is genuinely forced and
   no engine-global state leaks after the adapter context exits.

All tests are tiny and CPU-only (8^3 lattice, single digits of steps); no GPU, no large
simulation, and the live engine source is never modified.
"""

import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# These runs are tiny (8^3 lattice, single-digit steps) and finish in well under a
# second; a generous cap just guarantees a hang fails fast instead of stalling CI.
CLI_TIMEOUT = 120

from scripts.ca import engine_adapter as ea  # noqa: E402
from scripts.ca import replicate as R  # noqa: E402


def _manifest(**over):
    m = {
        "schema_version": 1,
        "experiment_id": "test",
        "mode": "replicate",
        "backend": "cpu",
        "seed": 7,
        "lattice_size": 8,
        "cube_size": 4,
        "steps": 3,
        "replicates": 3,
        "checkpoint_every_steps": 1,
        "thread_cap": 1,
    }
    m.update(over)
    return m


def _write_manifest(path, **over):
    path = Path(path)
    path.write_text(json.dumps(_manifest(**over), indent=2), encoding="utf-8")
    return path


def _run_cli(*args):
    """Run the CLI as a fresh OS process; return parsed stdout JSON."""
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ca.replicate", *map(str, args)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=CLI_TIMEOUT,
    )
    assert proc.returncode == 0, f"CLI failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


def _rep_hashes(run_dir):
    return {
        p.parent.name: json.loads(p.read_text(encoding="utf-8"))["trajectory_hash"]
        for p in Path(run_dir).glob("replicate_*/result.json")
    }


# --------------------------------------------------------------------------- #
# 1. Separate-launch exact replication
# --------------------------------------------------------------------------- #
def test_separate_launch_exact_replication(tmp_path):
    manifest = _write_manifest(tmp_path / "manifest.json", seed=42, replicates=3)

    out_a = _run_cli("--manifest", manifest, "--out", tmp_path / "a")
    out_b = _run_cli("--manifest", manifest, "--out", tmp_path / "b")

    # Each launch's replicates agree internally...
    assert out_a["all_replicates_identical"] is True
    assert out_b["all_replicates_identical"] is True
    # ...and the two independent launches agree with each other (cross-launch determinism).
    assert out_a["final_scientific_hash"] == out_b["final_scientific_hash"]

    hashes_a = _rep_hashes(out_a["run_dir"])
    assert len(hashes_a) == 3
    assert len(set(hashes_a.values())) == 1

    # The on-disk index records one row per replicate, all sharing the trajectory hash.
    index = (Path(out_a["run_dir"]) / "index.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(index) == 3
    traj = {json.loads(line)["trajectory_hash"] for line in index}
    assert len(traj) == 1


# --------------------------------------------------------------------------- #
# 2. Checkpoint / resume equivalence
# --------------------------------------------------------------------------- #
def test_checkpoint_resume_equivalence(tmp_path):
    manifest = _write_manifest(tmp_path / "manifest.json", seed=11, steps=4,
                               replicates=3, checkpoint_every_steps=1)

    out = _run_cli("--manifest", manifest, "--out", tmp_path / "run")
    run_dir = Path(out["run_dir"])
    original = _rep_hashes(run_dir)
    assert len(set(original.values())) == 1

    # Simulate an interruption:
    #  - replicate_000: leave completed (must be skipped on resume)
    #  - replicate_001: drop result + final + checkpoints after step 2 (must resume from ck)
    #  - replicate_002: wipe entirely (must be recomputed fresh during the resume pass)
    r1 = run_dir / "replicate_001"
    (r1 / "result.json").unlink()
    (r1 / "final_state.npz").unlink()
    for ck in (r1 / "checkpoints").glob("checkpoint_step_*.npz"):
        if int(ck.stem.split("_")[-1]) > 2:
            ck.unlink()
    shutil.rmtree(run_dir / "replicate_002")

    out2 = _run_cli("--resume", run_dir, "--out", tmp_path / "run")
    resumed = _rep_hashes(run_dir)

    assert out2["all_replicates_identical"] is True
    assert resumed == original
    assert len(set(resumed.values())) == 1


# --------------------------------------------------------------------------- #
# 3. Safety validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "over",
    [
        {"backend": "gpu"},            # GPU backend not permitted this milestone
        {"backend": "cuda"},
        {"mode": "trial"},             # only replicate is supported
        {"mode": "sweep"},
        {"replicates": 1},             # replicate mode needs >= 2
        {"steps": 0},                  # lower bounds
        {"lattice_size": 0},
        {"cube_size": 0},
        {"checkpoint_every_steps": 0},
        {"thread_cap": 0},
        {"seed": -1},
        {"schema_version": 2},         # forward schema not implemented
        {"mutation_rate": 0.1},        # unknown/deferred-feature key
        # --- upper caps (F2): no unlimited escape hatch ---
        {"lattice_size": R.MAX_LATTICE_SIZE + 1},
        {"steps": R.MAX_STEPS + 1},
        {"replicates": R.MAX_REPLICATES + 1},
        {"thread_cap": 10_000},        # exceeds host CPU-count ceiling
        {"checkpoint_every_steps": R.MAX_STEPS + 1},
        # --- relational bounds (F2) ---
        {"lattice_size": 8, "cube_size": 9},          # cube_size > lattice_size
        {"steps": 2, "checkpoint_every_steps": 3},     # checkpoint interval > steps
    ],
)
def test_manifest_rejected(over):
    with pytest.raises(ValueError):
        R.validate_manifest(_manifest(**over))


@pytest.mark.parametrize(
    "bad_id",
    ["../escape", "..", ".", "a/b", "a\\b", "C:evil", "with space", "", "-lead", "_lead",
     "a" * 65],
)
def test_experiment_id_rejected(bad_id):
    """experiment_id must be a conservative slug — no path traversal/separators (F1)."""
    with pytest.raises(ValueError):
        R.validate_manifest(_manifest(experiment_id=bad_id))


@pytest.mark.parametrize("good_id", ["test", "exp-1", "Run_2", "a", "9", "a" * 64])
def test_experiment_id_accepted(good_id):
    assert R.validate_manifest(_manifest(experiment_id=good_id))["experiment_id"] == good_id


def test_valid_manifest_accepted():
    m = R.validate_manifest(_manifest())
    assert m["backend"] == "cpu"
    assert m["mode"] == "replicate"
    assert m["replicates"] >= 2


def test_cap_boundaries_accepted():
    """The exact caps + relational equalities are allowed; only beyond them is rejected."""
    m = R.validate_manifest(_manifest(
        lattice_size=R.MAX_LATTICE_SIZE, cube_size=R.MAX_LATTICE_SIZE,
        steps=5, checkpoint_every_steps=5, replicates=R.MAX_REPLICATES, thread_cap=1))
    assert m["lattice_size"] == R.MAX_LATTICE_SIZE
    assert m["cube_size"] == m["lattice_size"]          # cube_size == lattice_size is OK
    assert m["checkpoint_every_steps"] == m["steps"]    # interval == steps is OK


def test_resume_rejects_checkpoint_mismatch(tmp_path):
    """A checkpoint whose embedded manifest hash differs must not be silently resumed."""
    manifest = _write_manifest(tmp_path / "manifest.json", seed=5, steps=2, replicates=2)
    out = _run_cli("--manifest", manifest, "--out", tmp_path / "run")
    run_dir = Path(out["run_dir"])

    # Corrupt the recorded manifest so the next resume's recomputed hash won't match
    # the hash embedded in the checkpoints, and remove a replicate's result to force a resume.
    r1 = run_dir / "replicate_001"
    (r1 / "result.json").unlink()
    (r1 / "final_state.npz").unlink()
    man_path = run_dir / "manifest.json"
    tampered = json.loads(man_path.read_text(encoding="utf-8"))
    tampered["seed"] = 999  # changes manifest hash AND checkpoint seed-field check
    man_path.write_text(json.dumps(tampered, indent=2), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ca.replicate", "--resume", str(run_dir),
         "--out", str(tmp_path / "run")],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=CLI_TIMEOUT,
    )
    assert proc.returncode != 0
    assert "mismatch" in (proc.stdout + proc.stderr).lower()


# --------------------------------------------------------------------------- #
# 4. CPU backend genuinely forced; no engine-global leakage
# --------------------------------------------------------------------------- #
def test_cpu_forced_and_globals_restored():
    assert "scripts.gpu_accelerator" not in sys.modules or not getattr(
        sys.modules["scripts.gpu_accelerator"], "__cpu_forced__", False
    )
    with ea.cpu_engine() as ce:
        assert ce._xp is np
        assert ce.GPU_AVAILABLE is False
        assert ce._gpu_rng is None
    # After the context exits, the injected fake must be gone (no leaked global state).
    leaked = getattr(sys.modules.get("scripts.gpu_accelerator"), "__cpu_forced__", False)
    assert leaked is False


def test_seed_and_scientific_hash_are_deterministic():
    """Two in-process runs of the bounded loop with the same seed match bytewise."""
    m = _manifest(seed=3, steps=2, replicates=2)

    def one_run(rng_seed):
        with ea.cpu_engine() as ce:
            rule = ea.default_rule_spec()
            state = ea.make_seed(m["lattice_size"], m["cube_size"])
            memory = np.array(ce.init_memory_grid(state.shape), dtype=np.float32)
            inactivity = np.zeros(state.shape, dtype=np.int16)
            rng = ea.make_rng(rng_seed)
            for gen in range(m["steps"]):
                state, inactivity, memory, _ = ea.step_once(
                    ce, state, rule, rng, inactivity, memory, current_gen=gen)
            return ea.scientific_hash(state, memory, inactivity)

    assert one_run(3) == one_run(3)


# --------------------------------------------------------------------------- #
# F3 — inactivity_steps is part of the scientific hash
# --------------------------------------------------------------------------- #
def test_inactivity_changes_scientific_and_chain_hash():
    """Changing ONLY inactivity_steps must change both hashes (else replication could be
    falsely certified). The fixed array order is lattice, memory_grid, inactivity_steps."""
    assert ea.SCIENTIFIC_ARRAY_ORDER == ("lattice", "memory_grid", "inactivity_steps")
    lat = np.zeros((4, 4, 4), dtype=np.uint8)
    mem = np.zeros((8, 4, 4, 4), dtype=np.float32)
    inact0 = np.zeros((4, 4, 4), dtype=np.int16)
    inact1 = inact0.copy()
    inact1[0, 0, 0] = 7  # the only difference

    assert ea.scientific_hash(lat, mem, inact0) != ea.scientific_hash(lat, mem, inact1)
    assert ea.chain_hash("p", 1, lat, mem, inact0) != ea.chain_hash("p", 1, lat, mem, inact1)
    # identical inputs -> identical hash (sanity)
    assert ea.scientific_hash(lat, mem, inact0) == ea.scientific_hash(lat, mem, inact0.copy())


# --------------------------------------------------------------------------- #
# F4 — adapter restores process-global state; non-reentrant
# --------------------------------------------------------------------------- #
def test_adapter_restores_sys_path():
    before = list(sys.path)
    root = str(ea.PROJECT_ROOT)
    try:
        while root in sys.path:
            sys.path.remove(root)
        assert root not in sys.path
        with ea.cpu_engine():
            assert root in sys.path           # inserted on entry
        assert root not in sys.path           # removed on exit
    finally:
        sys.path[:] = before


def test_adapter_restores_modules_verbatim():
    eng, gpu = "scripts.continuous_evolution_ca", "scripts.gpu_accelerator"
    saved = {n: sys.modules.get(n) for n in (eng, gpu)}
    sentinel_eng = types.ModuleType(eng)
    sentinel_gpu = types.ModuleType(gpu)
    try:
        sys.modules[eng] = sentinel_eng
        sys.modules[gpu] = sentinel_gpu
        with ea.cpu_engine() as ce:
            assert ce is not sentinel_eng     # a freshly forced-CPU import
            assert ce._xp is np
        # the pre-existing module objects are restored verbatim (same identity)
        assert sys.modules.get(eng) is sentinel_eng
        assert sys.modules.get(gpu) is sentinel_gpu
    finally:
        for n, v in saved.items():
            if v is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v


def test_adapter_clean_state_and_package_attrs():
    eng, gpu = "scripts.continuous_evolution_ca", "scripts.gpu_accelerator"
    saved = {n: sys.modules.get(n) for n in (eng, gpu)}
    pkg = sys.modules.get("scripts")
    attr_saved = {a: getattr(pkg, a, None) for a in ("gpu_accelerator", "continuous_evolution_ca")} \
        if pkg is not None else {}
    try:
        # nothing preloaded: drop the submodule entries + the package attrs
        sys.modules.pop(eng, None)
        sys.modules.pop(gpu, None)
        if pkg is not None:
            for a in ("gpu_accelerator", "continuous_evolution_ca"):
                if hasattr(pkg, a):
                    delattr(pkg, a)
        with ea.cpu_engine():
            pass
        # restored to the (absent) prior state
        assert eng not in sys.modules
        assert gpu not in sys.modules
        if pkg is not None:
            assert not hasattr(pkg, "gpu_accelerator")
            assert not hasattr(pkg, "continuous_evolution_ca")
    finally:
        for n, v in saved.items():
            if v is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v
        if pkg is not None:
            for a, v in attr_saved.items():
                if v is not None:
                    setattr(pkg, a, v)


def test_adapter_is_non_reentrant():
    with ea.cpu_engine() as ce1:
        assert ce1._xp is np
        with pytest.raises(RuntimeError):
            with ea.cpu_engine():
                pass
        # the first context is uncorrupted by the rejected nested attempt
        assert ce1._xp is np
    # lock released after the outer context -> a fresh context works again
    with ea.cpu_engine() as ce2:
        assert ce2._xp is np


# --------------------------------------------------------------------------- #
# F5 — fresh run directories cannot collide
# --------------------------------------------------------------------------- #
def test_fresh_run_dirs_are_unique(tmp_path):
    manifest = _write_manifest(tmp_path / "manifest.json", seed=1, steps=1, replicates=2)
    a = _run_cli("--manifest", manifest, "--out", tmp_path / "out")
    b = _run_cli("--manifest", manifest, "--out", tmp_path / "out")
    assert a["run_dir"] != b["run_dir"]           # microsecond + nonce => distinct
    assert a["all_replicates_identical"] is True
    assert b["all_replicates_identical"] is True
    # two distinct run dirs both present on disk
    assert Path(a["run_dir"]).is_dir() and Path(b["run_dir"]).is_dir()


# --------------------------------------------------------------------------- #
# F6 — resume provenance + run lifecycle
# --------------------------------------------------------------------------- #
def test_resume_preserves_start_and_records_resume_time(tmp_path):
    manifest = _write_manifest(tmp_path / "manifest.json", seed=2, steps=2,
                               replicates=2, checkpoint_every_steps=1)
    out = _run_cli("--manifest", manifest, "--out", tmp_path / "run")
    run_dir = Path(out["run_dir"])
    rj0 = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert rj0["status"] == "completed"
    assert rj0["resumed_utc"] == []
    started0 = rj0["started_utc"]

    # force a resume: drop one replicate's result+final, keep its checkpoints
    r1 = run_dir / "replicate_001"
    (r1 / "result.json").unlink()
    (r1 / "final_state.npz").unlink()

    _run_cli("--resume", run_dir, "--out", tmp_path / "run")
    rj1 = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert rj1["status"] == "completed"
    assert rj1["started_utc"] == started0            # original start preserved
    assert len(rj1["resumed_utc"]) == 1              # resume recorded separately
    assert rj1["resumed_utc"][0] != started0


def test_completed_result_identity_mismatch_rejected(tmp_path):
    """A completed replicate whose identity fields don't match the manifest is rejected
    on reuse — exactly as a mismatched checkpoint is."""
    manifest = _write_manifest(tmp_path / "manifest.json", seed=3, steps=1, replicates=2)
    out = _run_cli("--manifest", manifest, "--out", tmp_path / "run")
    run_dir = Path(out["run_dir"])

    # corrupt replicate_000's completed result identity, and force a resume pass
    r0 = run_dir / "replicate_000"
    res = json.loads((r0 / "result.json").read_text(encoding="utf-8"))
    res["manifest_sha256"] = "0" * 64
    (r0 / "result.json").write_text(json.dumps(res), encoding="utf-8")
    r1 = run_dir / "replicate_001"
    (r1 / "result.json").unlink()
    (r1 / "final_state.npz").unlink()

    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ca.replicate", "--resume", str(run_dir),
         "--out", str(tmp_path / "run")],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=CLI_TIMEOUT,
    )
    assert proc.returncode != 0
    assert "mismatch" in (proc.stdout + proc.stderr).lower()


def test_interrupted_status_recorded(tmp_path, monkeypatch):
    """A KeyboardInterrupt during a run is recorded as a durable 'interrupted' status
    with a non-zero exit code, and the original start time is still present."""
    manifest = _write_manifest(tmp_path / "manifest.json", seed=1, steps=2, replicates=2)

    def _boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(R, "run_replicate", _boom)
    rc = R.main(["--manifest", str(manifest), "--out", str(tmp_path / "out")])
    assert rc == 130

    runs = list((tmp_path / "out" / "test").glob("*"))
    assert len(runs) == 1
    rj = json.loads((runs[0] / "run.json").read_text(encoding="utf-8"))
    assert rj["status"] == "interrupted"
    assert rj["started_utc"]
    assert rj["finished_utc"]            # interruption timestamp recorded
    # the per-run lock must be released even on interrupt
    assert not (runs[0] / "run.lock").exists()
