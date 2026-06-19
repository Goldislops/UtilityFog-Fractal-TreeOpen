"""Phase 2B-5G-2 — local-first, CPU-only deterministic CA replication + provenance.

This package is a thin wrapper *around* the audited engine
``scripts.continuous_evolution_ca`` (the real multi-state CA stepper). It does NOT
modify the engine, and it forces the CPU/NumPy backend so that runs are bitwise
reproducible within a fixed environment.

Scope (deliberately narrow): mode == "replicate" only — rerun an identical seed to
verify determinism, with full provenance and resumable checkpoints. It makes NO
claim about GPU determinism, the full Medusa daemon (``run_v070_engine.py``), or
cross-backend / cross-machine / cross-version reproduction.
"""

__all__ = ["engine_adapter", "replicate"]
