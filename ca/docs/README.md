# Cellular Automata Engine

## Overview

The UtilityFog project explores multi-state cellular automata for self-organizing
"utility fog" structures. There are several CA surfaces in the tree; this document
describes which one to use for which job, and — importantly — **which are retired or
dormant** so you don't follow a dead path.

The **supported, reproducible local instrument** is
[`python -m scripts.ca.replicate`](../../scripts/ca/replicate.py): a bounded, CPU-only
deterministic **replication + provenance** wrapper around the research engine. If you want
to re-run an experiment and *prove* you got byte-identical results, that is the tool.

## Execution surfaces — what is supported, dormant, or retired

| Surface | Status | Use it for |
|---------|--------|------------|
| **`python -m scripts.ca.replicate`** (`scripts/ca/`) | **Supported** | CPU/NumPy deterministic **replication + provenance** of the research engine. The maintained local instrument. |
| **`scripts/continuous_evolution_ca.py`** | Research engine (candidate) | The multi-state CA stepper (`step_ca_lattice`) the replication wrapper drives. Its live GPU/Medusa path is **untouched** and is **not** claimed reproducible here. |
| **`crates/uft_ca`** (Rust/PyO3) | Maintained kernel | The high-performance Rust CA kernel + PyO3 bindings, in its existing tested roles. CPU-only; **not** the replication instrument and not driven by it. |
| **`src/uft_orch/ca/runner.py`** + `ca/experiments/*.yaml` + `ca/seeds/*.json` | **Dormant / legacy** | A historical experiment-runner path. **Not** the supported replication/search route; do not rely on it. (Left in place, neither repaired nor deleted.) |
| **GitHub Actions "CA Rule Search"** (`ca-search.yml`) | **Retired** | Removed from the default branch (Phase 2B-5F-1). There is no cloud/Lambda experiment-dispatch system; do not try to dispatch it. |

> CA experimentation, rule searching and branching studies remain **core research**. Only
> the broken GitHub-Actions cloud harness was retired. A future local-first
> trial/sweep/search design is a separate, explicitly-authorized phase (see *Deferred
> future work*).

## The replication instrument (`scripts.ca.replicate`)

### Scientific purpose

Run an identical-seed experiment one or more times under a pinned CPU/NumPy environment
and **verify it reproduces byte-for-byte**, with full provenance recorded. This is a
calibration/trust tool (determinism levels R1–R2 on the CPU backend), not a new science
run.

### Honest claim boundary

Bitwise reproducibility holds **only when** the recorded executed-source hashes
(engine + adapter + wrapper), the rule hash, the NumPy version, the backend (`cpu`), the
manifest and the initial state **all match**. A git commit alone does **not** prove the
executed code (a dirty working tree can differ).

**Not claimed:** CPU↔GPU identity, cross-machine identity, cross-version identity, or
fidelity to the full Medusa daemon (`run_v070_engine.py`). The live GPU RNG path is
non-reproducible and is left untouched by this instrument.

### Manifest (schema v1)

A run is described by a small JSON manifest. The example below shows every key; only
`lattice_size` (default 8), `checkpoint_every_steps` (default 1), `thread_cap` (default 1)
and `experiment_id` (default `"replicate"`) are optional — the rest are required.

```json
{
  "schema_version": 1,
  "experiment_id": "calibration-001",
  "mode": "replicate",
  "backend": "cpu",
  "seed": 42,
  "lattice_size": 8,
  "cube_size": 4,
  "steps": 5,
  "replicates": 3,
  "checkpoint_every_steps": 1,
  "thread_cap": 1
}
```

- `experiment_id` is used as a directory segment, so it must be a filesystem-safe slug
  (ASCII letters/digits/`_`/`-`, starting alphanumeric).
- The rule is carried **in code** as `engine_adapter.DEFAULT_RULE_SPEC` (a transcription of
  `ca/rules/example.toml` v0.7.5); `ca/rules/example.toml` is a provenance pointer only and
  is **not** parsed at run time.

### Run a fresh replication

```bash
python -m scripts.ca.replicate --manifest path/to/manifest.json --out results/
```

`--out` defaults to `results/` under the repository root. Each launch creates a fresh,
uniquely-named run directory (it never reuses an existing one).

### Resume an interrupted run

```bash
python -m scripts.ca.replicate --resume results/<experiment_id>/<run-id>
```

Resume skips already-completed replicates and continues a partial one from its latest
checkpoint. It **fails closed** if the recorded provenance is missing/corrupt or if the
checkpoint/result identity (executed-source hashes, rule, NumPy, manifest, backend,
replicate index, target steps) does not match the current invocation.

### Output layout

```
results/<experiment_id>/<run-id>/
  manifest.json        # the validated manifest exactly as run
  run.json             # run-level provenance + lifecycle status
  index.jsonl          # one line per replicate (final + trajectory hash, status)
  replicate_000/
    result.json        # per-replicate provenance + final/trajectory hashes
    final_state.npz    # arrays: lattice, memory_grid, inactivity_steps
    checkpoints/
      checkpoint_step_000000000.npz   # step-0 (initial) + per-interval + final
      ...
  replicate_001/
    ...
```

The **scientific hash** is a SHA-256 over the three engine-evolved arrays in a fixed order
— `lattice`, `memory_grid`, `inactivity_steps`. All writes are atomic (temp file +
`os.replace`).

### Lifecycle status (`run.json`)

`run.json` records a durable status:

- **running** — written before any compute begins.
- **completed** — finished; exit code `0` if all replicates are identical, `2` if a
  divergence is detected.
- **interrupted** — `KeyboardInterrupt` (Ctrl-C); exit code `130`.
- **failed** — any other exception; a bounded, privacy-safe error summary is recorded and
  the exception is re-raised (non-zero exit).

The original `started_utc` is preserved across resumes; each resume is appended to
`resumed_utc`.

### Resource & safety limits (high level)

Schema v1 is a deliberately bounded harness with conservative per-field, relational and
aggregate caps so a single manifest cannot accidentally consume the machine or fill the
disk (e.g. `lattice_size ≤ 64`, `cube_size ≤ lattice_size`, `steps ≤ 10000`,
`2 ≤ replicates ≤ 100`, `checkpoint_every_steps ≤ steps`, `thread_cap ≤ min(8, CPU count)`,
`seed ∈ [0, 2⁶⁴−1]`, plus aggregate compute/checkpoint-count/checkpoint-storage budgets).
There is no "unlimited" mode. **The validator is authoritative** — see
`validate_manifest` in [`scripts/ca/replicate.py`](../../scripts/ca/replicate.py) for the
exact, current values rather than relying on this prose.

## Cell states

The CA uses five fundamental cell states:

- **VOID (0)**: Empty space, no structure
- **STRUCTURAL (1)**: Physical scaffold, provides connectivity
- **COMPUTE (2)**: Processing nodes, execute logic
- **ENERGY (3)**: Power distribution, enables computation
- **SENSOR (4)**: Environmental sensing, input/output

## Neighborhoods

### Moore-3D

For regular 3D lattices, the Moore neighborhood includes all 26 adjacent cells:
- 6 face neighbors (±x, ±y, ±z)
- 12 edge neighbors
- 8 corner neighbors

Boundary conditions: Fixed (cells outside lattice are treated as VOID).

### Graph adjacency

The Rust kernel (`crates/uft_ca`) also supports arbitrary graph topologies via explicit
adjacency lists (trees, meshes, random graphs), enabling fractal branching structures.

## Stepping modes

### Synchronous

All cells update simultaneously based on the previous state: read all cell states and
neighbor counts, apply the transition rule, then update all cells atomically.

### Asynchronous (future)

Cells update in random or sequential order — more biologically realistic, can exhibit
different dynamics, and requires careful handling of update order.

## Deferred future work

These are **not** part of the current instrument and remain separate, explicitly-authorized
phases:

- Independently-seeded **trials**, **parameter sweeps** and **mutation/rule search**.
- **R3 cross-backend** (CPU↔GPU) reproducibility studies.
- Grafting this provenance onto `run_v070_engine.py` (the Medusa daemon).
- Repair-or-deprecate of the dormant `src/uft_orch/ca/runner.py` path and its semantic-seed
  loader.

Asynchronous stepping, table-driven rules, GPU acceleration, distributed simulation and
interactive visualization remain longer-horizon research directions.

## References

- Wolfram, S. (2002). *A New Kind of Science*
- Langton, C. G. (1990). "Computation at the edge of chaos"
- Wuensche, A. (2011). "Exploring Discrete Dynamics"
