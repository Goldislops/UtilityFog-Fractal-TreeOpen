"""CPU-only adapter around the audited CA engine (``scripts.continuous_evolution_ca``).

The engine selects its array backend at *import time*: it does
``from scripts.gpu_accelerator import ... GPU_AVAILABLE`` and, if a CuPy/RTX GPU is
present, sets its internal ``_xp`` to CuPy and creates a module-global GPU RNG seeded
once at import. On Kevin's box CuPy 14.x + an RTX 5090 are live, so the *default*
engine path is GPU and is **not** reproducible run-to-run (audit 2B-5G-1).

This adapter forces the CPU/NumPy path **without editing the engine**, by injecting a
stand-in ``scripts.gpu_accelerator`` whose ``GPU_AVAILABLE`` is ``False`` *before* the
engine is (re)imported, then fully restoring the process import state afterwards
(``sys.modules`` entries, the leaf attributes bound on the ``scripts`` package, and any
``sys.path`` entry it inserted). It is non-reentrant (a module-level lock fail-fasts on a
second concurrent/nested context). On the CPU path the engine's ``_xp_random`` consumes
the explicit ``numpy.random.Generator`` we pass in, so the run is deterministic given
(engine revision, NumPy, seed, rule, lattice, steps).

Nothing here mutates the engine source, the dormant ``src/uft_orch/ca/runner.py``, the
``ca/seeds/*.json`` loader, or any GPU/Medusa runtime. It NEVER imports CuPy.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import json
import sys
import threading
import types
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Source-of-record for the canonical rule. NOTE: it is *not parsed at runtime* —
# `ca/rules/example.toml` uses multi-line inline tables, which the stdlib `tomllib`
# (the engine's fallback parser when no third-party `tomli` is installed, e.g. on CI)
# rejects. We therefore carry the rule as an in-code dict (DEFAULT_RULE_SPEC), which
# is exactly how the engine's own test-suite drives `step_ca_lattice`. This constant
# stays only as a provenance pointer to where the values came from.
DEFAULT_RULE = PROJECT_ROOT / "ca" / "rules" / "example.toml"
STRUCTURAL = 1  # STATE_NAME_TO_ID["STRUCTURAL"] in the engine

# The actual executed sources, hashed for resume identity. A git SHA alone is NOT
# sufficient (a dirty working tree can run code different from the commit), so we pin the
# scientific implementation by hashing these three files + the in-code rule + NumPy.
ENGINE_SOURCE = PROJECT_ROOT / "scripts" / "continuous_evolution_ca.py"
ADAPTER_SOURCE = Path(__file__).resolve()
WRAPPER_SOURCE = PROJECT_ROOT / "scripts" / "ca" / "replicate.py"

# In-code transcription of ca/rules/example.toml (v0.7.5) — the four sections the
# bounded stepper actually consumes. Stochastic/contagion/decay are kept ENABLED so
# the engine genuinely draws from the explicit RNG (otherwise the RNG-state
# checkpoint/resume guarantee would be vacuous). The remaining example.toml sections
# (cosmic_garden/equanimity/ice_battery/trash_battery/experimental) are optional and
# default gracefully inside the engine — verified empirically.
DEFAULT_RULE_SPEC: Dict[str, Any] = {
    "rule": {
        "name": "branching-growth-v0.7.5",
        "states": ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"],
        "neighborhood": "moore-3d",
        "transition": "outer-totalistic",
    },
    "params": {
        "transitions": {
            "VOID": {3: "STRUCTURAL", 4: "STRUCTURAL", 5: "STRUCTURAL", 6: "STRUCTURAL"},
            "STRUCTURAL": {0: "STRUCTURAL", 1: "STRUCTURAL", 2: "STRUCTURAL", 3: "COMPUTE",
                           4: "COMPUTE", 5: "ENERGY", 6: "SENSOR", 7: "SENSOR", 8: "SENSOR"},
            "COMPUTE": {0: "COMPUTE", 1: "COMPUTE", 2: "COMPUTE", 3: "COMPUTE", 4: "COMPUTE",
                        5: "COMPUTE", 6: "ENERGY", 7: "SENSOR"},
            "ENERGY": {0: "ENERGY", 1: "ENERGY", 2: "ENERGY", 3: "ENERGY", 4: "ENERGY",
                       5: "ENERGY", 6: "SENSOR", 7: "SENSOR", 8: "SENSOR"},
            "SENSOR": {0: "SENSOR", 1: "SENSOR", 2: "SENSOR", 3: "SENSOR", 4: "SENSOR",
                       5: "SENSOR", 6: "SENSOR"},
        },
        "contagion": {
            "enabled": True,
            "energy_neighbor_threshold": 4, "sensor_neighbor_threshold": 4,
            "structural_energy_conversion_prob": 0.34, "structural_sensor_conversion_prob": 0.34,
            "compute_energy_conversion_prob": 0.08, "compute_sensor_conversion_prob": 0.15,
        },
        "stochastic": {
            "enabled": True,
            "baseline_transition_prob": 0.08,
            "structural_to_energy_prob": 0.08, "structural_to_sensor_prob": 0.08,
            "compute_to_energy_prob": 0.05, "compute_to_sensor_prob": 0.05,
            "structural_to_void_decay_prob": 0.005, "energy_to_void_decay_prob": 0.004,
            "sensor_to_void_decay_prob": 0.003,
        },
        "decay": {
            "enabled": True,
            "inactivity_neighbor_threshold": 1, "structural_inactive_steps_to_decay": 6,
        },
        "meta": {
            "description": "v0.7.5 cosmic garden lock (in-code transcription for CPU replication)",
            "author": "UtilityFog Team", "version": "0.7.5", "target_lambda": 1.7,
        },
    },
}

_ENGINE_NAME = "scripts.continuous_evolution_ca"
_GPU_NAME = "scripts.gpu_accelerator"
_PKG_NAME = "scripts"  # the (namespace) parent package
# Leaf attribute names the import machinery binds onto the `scripts` package object.
_PKG_ATTRS = ("gpu_accelerator", "continuous_evolution_ca")

# Fixed, documented order of the scientific arrays that enter every hash (F3).
SCIENTIFIC_ARRAY_ORDER = ("lattice", "memory_grid", "inactivity_steps")


class _Missing:
    """Sentinel: a watched name/attribute was absent before we entered the context."""


_MISSING = _Missing()

# A single forced-CPU import may be in flight at a time. cpu_engine() mutates
# process-global import state (sys.modules / scripts package attrs / sys.path), so two
# overlapping contexts would corrupt each other's snapshot. Non-reentrant by design.
_CPU_ENGINE_LOCK = threading.Lock()


def _fake_gpu_accelerator() -> types.ModuleType:
    """A stand-in for scripts.gpu_accelerator that reports CPU-only.

    Provides exactly the names the engine imports (``gpu, to_gpu, to_cpu, sync,
    is_gpu_available, GPU_AVAILABLE``). No CUDA probe, no banner, no os.environ edits.
    """
    mod = types.ModuleType(_GPU_NAME)
    mod.GPU_AVAILABLE = False
    mod.gpu = np
    mod.is_gpu_available = lambda: False
    mod.to_gpu = lambda a: a
    mod.to_cpu = lambda a: a
    mod.sync = lambda: None
    mod.__cpu_forced__ = True  # marker for assertions/tests
    return mod


@contextlib.contextmanager
def cpu_engine() -> Iterator[types.ModuleType]:
    """Import the CA engine with the GPU backend forced OFF; fully restore process state.

    Yields the imported ``continuous_evolution_ca`` module with ``_xp is numpy`` and
    ``GPU_AVAILABLE is False``. Single-shot and **non-reentrant**: a module-level lock
    fail-fasts if a second (concurrent or nested) context is opened, so the two cannot
    corrupt each other's snapshot.

    Everything it touches is snapshotted and restored in ``finally`` (including on
    exceptional exit): the watched ``sys.modules`` entries, the leaf attributes the
    import machinery binds onto the ``scripts`` package object, and the ``sys.path``
    entry it may insert. Raises RuntimeError if the CPU backend cannot be verified.
    Never edits the engine source.
    """
    if not _CPU_ENGINE_LOCK.acquire(blocking=False):
        raise RuntimeError(
            "cpu_engine() is already active in this process; it is single-shot and "
            "non-reentrant (do not nest or run two concurrently)."
        )

    # Snapshot every piece of global state we may displace, BEFORE mutating anything.
    watched = (_PKG_NAME, _GPU_NAME, _ENGINE_NAME, "cupy")
    saved_modules = {name: sys.modules.get(name, _MISSING) for name in watched}
    pre_pkg = sys.modules.get(_PKG_NAME, _MISSING)
    saved_attrs = (
        {a: getattr(pre_pkg, a, _MISSING) for a in _PKG_ATTRS}
        if pre_pkg is not _MISSING else {}
    )
    inserted_path = str(PROJECT_ROOT) not in sys.path

    try:
        if inserted_path:
            sys.path.insert(0, str(PROJECT_ROOT))
        sys.modules[_GPU_NAME] = _fake_gpu_accelerator()
        # Drop any cached engine so it re-binds _xp/_gpu_rng against the fake.
        sys.modules.pop(_ENGINE_NAME, None)
        ce = importlib.import_module(_ENGINE_NAME)
        if getattr(ce, "GPU_AVAILABLE", True) is not False or ce._xp is not np:
            raise RuntimeError(
                "CPU backend could not be forced "
                f"(GPU_AVAILABLE={getattr(ce, 'GPU_AVAILABLE', None)!r}, _xp={ce._xp!r})"
            )
        if getattr(ce, "_gpu_rng", "x") is not None:
            raise RuntimeError("engine _gpu_rng is not None under forced-CPU import")
        yield ce
    finally:
        # Restore submodule entries first, then the package object, then sys.path.
        for name in (_ENGINE_NAME, _GPU_NAME, "cupy"):
            prev = saved_modules[name]
            if prev is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev
        if saved_modules[_PKG_NAME] is _MISSING:
            # We (transitively) created the `scripts` package; remove it wholesale.
            sys.modules.pop(_PKG_NAME, None)
        else:
            pkg = saved_modules[_PKG_NAME]
            sys.modules[_PKG_NAME] = pkg
            for attr, val in saved_attrs.items():
                if val is _MISSING:
                    if hasattr(pkg, attr):
                        delattr(pkg, attr)
                else:
                    setattr(pkg, attr, val)
        if inserted_path:
            try:
                sys.path.remove(str(PROJECT_ROOT))
            except ValueError:
                pass
        _CPU_ENGINE_LOCK.release()


# --------------------------------------------------------------------------- #
# Deterministic initial state (CPU-only)
# --------------------------------------------------------------------------- #
def make_seed(lattice_size: int, cube_size: int) -> np.ndarray:
    """Deterministic seed: a ``cube_size``^3 STRUCTURAL block centred in a
    ``lattice_size``^3 VOID lattice. No RNG.

    This is the ``scripts.run_v070_engine.generate_primordial_seed_cube`` recipe,
    parameterised by lattice size (the engine's own helper hardwires 64^3, which is
    too heavy for the tiny replication smoke tests). It deliberately does NOT use the
    broken ``ca/seeds/*.json`` loader (audit 2B-5G-0).
    """
    L = int(lattice_size)
    c = int(cube_size)
    if L < 1:
        raise ValueError(f"lattice_size must be >= 1, got {L}")
    if c < 1:
        raise ValueError(f"cube_size must be >= 1, got {c}")
    arr = np.zeros((L, L, L), dtype=np.uint8)
    ctr = L // 2
    if c < 2:
        arr[ctr, ctr, ctr] = STRUCTURAL
        return arr
    half = c // 2
    lo = max(0, ctr - half)
    hi = min(L, lo + c)
    arr[lo:hi, lo:hi, lo:hi] = STRUCTURAL
    return arr


# --------------------------------------------------------------------------- #
# Rule spec (in-code; see DEFAULT_RULE_SPEC note above)
# --------------------------------------------------------------------------- #
def default_rule_spec() -> Dict[str, Any]:
    """Return a fresh deep copy of the canonical rule spec (engine never mutates it,
    but copy defensively so callers can record/serialise without aliasing)."""
    return copy.deepcopy(DEFAULT_RULE_SPEC)


def rule_spec_hash(spec: Mapping[str, Any]) -> str:
    """Stable sha256 over the rule's canonical JSON form (for provenance)."""
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    """sha256 of a file's raw bytes (for executed-source provenance)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def source_identity() -> Dict[str, str]:
    """sha256 of the three executed source files (engine + adapter + wrapper).

    These pin the actual code path so a later engine/adapter/wrapper change cannot be
    silently resumed against an old checkpoint/result and called one continuous run.
    """
    return {
        "engine_source_sha256": file_sha256(ENGINE_SOURCE),
        "adapter_source_sha256": file_sha256(ADAPTER_SOURCE),
        "wrapper_source_sha256": file_sha256(WRAPPER_SOURCE),
    }


# --------------------------------------------------------------------------- #
# RNG state (serialisable)
# --------------------------------------------------------------------------- #
def make_rng(seed: int) -> "np.random.Generator":
    return np.random.default_rng(int(seed))


def get_rng_state(rng: "np.random.Generator") -> Dict[str, Any]:
    """Return the bit-generator state as a JSON-round-trippable dict."""
    return json.loads(json.dumps(rng.bit_generator.state))


def restore_rng(seed: int, state: Mapping[str, Any]) -> "np.random.Generator":
    """Rebuild a Generator and restore an exact stream position from get_rng_state().

    ``state`` is already a plain dict (parsed from checkpoint JSON), so it can be
    assigned directly; ``dict(state)`` only guards against an aliased Mapping arg.
    """
    rng = np.random.default_rng(int(seed))
    rng.bit_generator.state = dict(state)
    return rng


# --------------------------------------------------------------------------- #
# One bounded step + scientific hashing
# --------------------------------------------------------------------------- #
def step_once(
    ce: types.ModuleType,
    state: np.ndarray,
    rule_spec: Mapping[str, Any],
    rng: "np.random.Generator",
    inactivity: np.ndarray,
    memory: np.ndarray,
    current_gen: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, float]]:
    """Advance the bounded CA core one step via the engine's stable boundary.

    Returns (state, inactivity, memory, metrics). The engine mutates ``memory`` and
    ``inactivity`` in place and also returns them; callers must feed the returned
    arrays forward (and not reuse stale references).
    """
    return ce.step_ca_lattice(
        state,
        rule_spec,
        rng,
        inactivity_steps=inactivity,
        memory_grid=memory,
        current_gen=int(current_gen),
    )


def _hash_array(h: "hashlib._Hash", arr: np.ndarray) -> None:
    a = np.ascontiguousarray(arr)
    h.update(a.dtype.str.encode("ascii"))
    h.update(repr(a.shape).encode("ascii"))
    h.update(a.tobytes())


def scientific_hash(lattice: np.ndarray, memory: np.ndarray, inactivity: np.ndarray) -> str:
    """sha256 over the THREE ordered scientific arrays the engine evolves.

    Fixed order = ``SCIENTIFIC_ARRAY_ORDER`` = (lattice, memory_grid, inactivity_steps).
    ``inactivity_steps`` drives future decay transitions and is checkpointed, so it MUST
    enter the hash — otherwise two scientifically different states could collide and the
    wrapper would falsely certify replication (Jack finding 3). Each array contributes
    its dtype tag, shape, and C-contiguous bytes, in that order. No timestamps, paths,
    run-ids, or (deterministically-derived) metrics enter the hash.
    """
    h = hashlib.sha256()
    _hash_array(h, lattice)
    _hash_array(h, memory)
    _hash_array(h, inactivity)
    return h.hexdigest()


def chain_hash(prev_hex: str, step_index: int, lattice: np.ndarray, memory: np.ndarray,
               inactivity: np.ndarray) -> str:
    """Fold one step's scientific state (lattice, memory_grid, inactivity_steps) into a
    running trajectory hash — same fixed array order as ``scientific_hash``."""
    h = hashlib.sha256()
    h.update(prev_hex.encode("ascii"))
    h.update(str(int(step_index)).encode("ascii"))
    _hash_array(h, lattice)
    _hash_array(h, memory)
    _hash_array(h, inactivity)
    return h.hexdigest()
