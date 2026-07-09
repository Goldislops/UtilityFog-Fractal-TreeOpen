# PACKAGE STATUS — read before importing or editing anything here

**Tombstone marker (D7 disposition, chosen 2026-07-08, implemented 2026-07-09).**
This package is a MIXED zone: three live, gate-imported modules sitting beside five
corrupted stub files that duplicate — and could be mistaken for — the real code.

## LIVE — gate-imported, maintained (edit here when fixing these modules)
| Module | Why it is live |
|---|---|
| `agent/feature_flags.py` | imported by CI-gated `tests/test_feature_flags.py` (sys.path append; "canonical package" per its comment) |
| `agent/observability.py` | imported by CI-gated `tests/test_observability.py`; fixed in place by PR #282 (utcnow deprecation) |
| `agent/telemetry_collector.py` | imported by `tests/test_observability.py` alongside observability |

The root-level `agent/` package does NOT contain these three modules — this package is
their only source. Plain removal of this directory breaks the pytest gate.

## CORRUPTED STUBS — DO NOT USE, DO NOT "FIX" IN PLACE
`evolution_engine.py` · `foglet_agent.py` · `meme_structure.py` · `network_topology.py` ·
`simulation_metrics.py` — padding files of repeated `class X: pass` lines. **The real
implementations live in the ROOT `agent/` package** (e.g. PR #300 fixed
`agent/evolution_engine.py` at the root; PRs #285/#290 likewise landed at the root).
Tests that import these names resolve to the root package, so the stubs are
import-shadowed in CI — harmless there, hazardous to anyone reading or editing this
directory directly.

## UNVERIFIED
`agent/main_simulation.py` (1001 lines, not stub-patterned, not gate-imported) and
`config.yaml` — status not audited; treat as unknown, not as live.

## Disposition history
Remove / tombstone / relocate was decision line D7 (`OPEN_DECISION_LINES_2026-07-08.md`,
ops-dir): **tombstone chosen** — removal breaks the gate; relocating the three live
modules is possible future work behind its own decision. This marker changes no code
and no behavior; it exists so nobody mistakes the stubs for the project again.
