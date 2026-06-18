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
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

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
        {"steps": 0},                  # bounds
        {"lattice_size": 0},
        {"cube_size": 0},
        {"checkpoint_every_steps": 0},
        {"thread_cap": 0},
        {"seed": -1},
        {"schema_version": 2},         # forward schema not implemented
        {"mutation_rate": 0.1},        # unknown/deferred-feature key
    ],
)
def test_manifest_rejected(over):
    with pytest.raises(ValueError):
        R.validate_manifest(_manifest(**over))


def test_valid_manifest_accepted():
    m = R.validate_manifest(_manifest())
    assert m["backend"] == "cpu"
    assert m["mode"] == "replicate"
    assert m["replicates"] >= 2


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
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
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
            return ea.scientific_hash(state, memory)

    assert one_run(3) == one_run(3)
