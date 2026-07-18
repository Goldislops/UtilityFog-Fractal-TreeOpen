# Swarm Hunter detector (proposed) — S1 toy-only offline lab

This directory is the **S1 stage** of the promotion ladder in
[`docs/SWARM_HUNTER_V1_PREFLIGHT.md`](../../docs/SWARM_HUNTER_V1_PREFLIGHT.md)
(merged S0 canon). It contains a deterministic, read-only
**connected-component persistence detector** for **synthetic** in-memory
arrays, plus its complete lab-local test suite.

Naming, per the S0 Option-C qualifiers: this is the *Swarm Hunter detector
(proposed)* — entirely distinct from the *legacy tuning orchestrator
(quarantined)* in `scripts/` (historical self-description: "the Swarm
Hunter's brain"). The two share vocabulary only; the import quarantine is
asserted by tests **in both directions**.

## Contract (frozen)

- Input: an ordered sequence of snapshots — `states: uint8 (N,N,N)`
  (`[z][y][x]`, flat convention `z·N²+y·N+x`), optional
  `memory: float32 (8,N,N,N)`, optional `inactivity_steps: int16 (N,N,N)`,
  and a closed provenance dict (`source="synthetic"` only; caller-supplied
  `sha256_triple` is always recomputed and verified).
- Output: `FindingsArtifact.jsonl` — canonical, immutable JSONL bytes
  (`header` / `finding` / `refusal` records; schema
  `swarm-hunter-lab-findings-v1`). Identical inputs give byte-identical
  output. `records()` returns fresh decoded copies.
- Semantics: non-VOID membership; **6-face periodic** connectivity;
  minimum-member labels; toroidal largest-gap bounding boxes; exact rational
  density; fixed `"1"–"4"` state-count keys including zeros; persistence
  chains by exact state-labelled cell-set equality (no motion or object
  tracking); component-cap exhaustion → deterministic prefix +
  `header.truncation`; op-budget exhaustion → preflight, header-only
  truncated artifact; malformed input → fatal structured refusal.
- Config: `DetectorConfig(min_component_size=2, component_cap=4096,
  op_budget_multiplier=16)` — closed, immutable, validated first.

## Running the tests

The maintained CI floor does **not** collect this lab (`pytest.ini` scopes
collection to `tests/`). The non-required `swarm-hunter-lab` workflow runs
`python -m pytest experiments/swarm_hunter_lab/tests -q` on any PR touching
this directory. Dependencies: NumPy + pytest only.

## Rollback

Delete this directory. No state, no migrations, no other file references it.

## Non-claims

No engine, `data/`, network, filesystem, model, or service access; no
actuation, tuning suggestions, parameter recommendations, or approval
language in any output (structurally closed schema); no consciousness,
intent, or agency claims; no motion/object tracking; runtime and memory
figures in test output are measured observations, not promises. S2+ (real
snapshots) remains separately gated.
