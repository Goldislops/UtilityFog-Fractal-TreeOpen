"""Swarm Hunter detector (proposed) — S1 toy-only offline lab.

This package is the S1 stage of the promotion ladder in
``docs/SWARM_HUNTER_V1_PREFLIGHT.md`` (merged S0 canon): a deterministic,
read-only, connected-component persistence detector operating on SYNTHETIC
in-memory arrays only.  It is entirely distinct from the legacy tuning
orchestrator (quarantined) in ``scripts/`` — the two share vocabulary only,
and this lab imports nothing from ``scripts/`` (enforced by tests in both
directions).

Hard scope (S0 §11): synthetic arrays only; no file, network, API, or
``data/`` access; cubic lattices <= 64^3; NumPy plus the standard library
only; rollback is deletion of this directory.
"""

from .detector import (
    DETECTOR_NAME,
    DETECTOR_VERSION,
    SCHEMA_ID,
    DetectorConfig,
    FindingsArtifact,
    compute_sha256_triple,
    detect_structures,
    leanctx_summary,
    lp,
)

__all__ = [
    "DETECTOR_NAME",
    "DETECTOR_VERSION",
    "SCHEMA_ID",
    "DetectorConfig",
    "FindingsArtifact",
    "compute_sha256_triple",
    "detect_structures",
    "leanctx_summary",
    "lp",
]
