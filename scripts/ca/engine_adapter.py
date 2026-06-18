"""CPU-only adapter around the audited CA engine (``scripts.continuous_evolution_ca``).

The engine selects its array backend at *import time*: it does
``from scripts.gpu_accelerator import ... GPU_AVAILABLE`` and, if a CuPy/RTX GPU is
present, sets its internal ``_xp`` to CuPy and creates a module-global GPU RNG seeded
once at import. On Kevin's box CuPy 14.x + an RTX 5090 are live, so the *default*
engine path is GPU and is **not** reproducible run-to-run (audit 2B-5G-1).

This adapter forces the CPU/NumPy path **without editing the engine**, by injecting a
stand-in ``scripts.gpu_accelerator`` whose ``GPU_AVAILABLE`` is ``False`` *before* the
engine is (re)imported, then restoring ``sys.modules`` afterwards. On the CPU path the
engine's ``_xp_random`` consumes the explicit ``numpy.random.Generator`` we pass in, so
the run is deterministic given (engine revision, NumPy, seed, rule, lattice, steps).

Nothing here mutates the engine source, the dormant ``src/uft_orch/ca/runner.py``, the
``ca/seeds/*.json`` loader, or any GPU/Medusa runtime. It NEVER imports CuPy.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Tuple

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULE = PROJECT_ROOT / "ca" / "rules" / "example.toml"
STRUCTURAL = 1  # STATE_NAME_TO_ID["STRUCTURAL"] in the engine

_ENGINE_NAME = "scripts.continuous_evolution_ca"
_GPU_NAME = "scripts.gpu_accelerator"


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
    """Import the CA engine with the GPU backend forced OFF; restore sys.modules after.

    Yields the imported ``continuous_evolution_ca`` module with ``_xp is numpy`` and
    ``GPU_AVAILABLE is False``. Encapsulated, single-shot, and fully restored in a
    ``finally`` block so no modified engine-global state leaks to the rest of the
    process. Raises RuntimeError if the CPU backend cannot be verified.
    """
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    # Snapshot anything we are about to displace so we can restore it verbatim.
    watched = (_GPU_NAME, _ENGINE_NAME, "cupy")
    saved = {name: sys.modules.get(name, _MISSING) for name in watched}
    try:
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
        for name, mod in saved.items():
            if mod is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


class _Missing:
    pass


_MISSING = _Missing()


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
# RNG state (serialisable)
# --------------------------------------------------------------------------- #
def make_rng(seed: int) -> "np.random.Generator":
    return np.random.default_rng(int(seed))


def get_rng_state(rng: "np.random.Generator") -> Dict[str, Any]:
    """Return the bit-generator state as a JSON-round-trippable dict."""
    return json.loads(json.dumps(rng.bit_generator.state))


def restore_rng(seed: int, state: Mapping[str, Any]) -> "np.random.Generator":
    """Rebuild a Generator and restore an exact stream position from get_rng_state()."""
    rng = np.random.default_rng(int(seed))
    rng.bit_generator.state = json.loads(json.dumps(state))
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


def scientific_hash(lattice: np.ndarray, memory: np.ndarray) -> str:
    """sha256 over ONLY the ordered scientific arrays (lattice, then memory_grid).

    Each array contributes its dtype tag, shape, and C-contiguous bytes — in that
    fixed order. No timestamps, paths, run-ids, or metrics enter the hash.
    """
    h = hashlib.sha256()
    _hash_array(h, lattice)
    _hash_array(h, memory)
    return h.hexdigest()


def chain_hash(prev_hex: str, step_index: int, lattice: np.ndarray, memory: np.ndarray) -> str:
    """Fold one step's scientific state into a running trajectory hash."""
    h = hashlib.sha256()
    h.update(prev_hex.encode("ascii"))
    h.update(str(int(step_index)).encode("ascii"))
    _hash_array(h, lattice)
    _hash_array(h, memory)
    return h.hexdigest()
