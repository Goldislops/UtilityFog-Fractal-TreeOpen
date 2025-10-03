# Cellular Automata Engine

## Overview

The UtilityFog CA engine supports graph-based cellular automata on both regular 3D lattices and arbitrary graph structures. This enables modeling of self-organizing utility fog systems with complex spatial relationships.

## Architecture

### Core Components

1. **uft_ca (Rust)**: High-performance CA kernel
   - 3D lattice with Moore neighborhood (26 neighbors)
   - Arbitrary graph adjacency lists
   - Synchronous and asynchronous stepping
   - PyO3 bindings for Python integration

2. **uft_orch.ca (Python)**: Orchestration layer
   - Rule specification loading (TOML)
   - Experiment configuration (YAML)
   - Metrics computation and tracking
   - Artifact generation (CSV, NPY)

3. **CI/Lambda Integration**: Distributed rule search
   - GitHub Actions workflow for experiment dispatch
   - Matrix parallelization across parameter space
   - Artifact collection and analysis

## Cell States

The CA supports five fundamental cell states:

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

Boundary conditions: Fixed (cells outside lattice are treated as VOID)

### Graph Adjacency

For arbitrary graphs, neighborhoods are defined by explicit adjacency lists:
- Each node maintains a list of connected neighbors
- Supports irregular topologies (trees, meshes, random graphs)
- Enables modeling of fractal branching structures

## Stepping Modes

### Synchronous

All cells update simultaneously based on the previous state:
1. Read all cell states and neighbor counts
2. Apply transition rule to compute next states
3. Update all cells atomically

### Asynchronous (Future)

Cells update in random or sequential order:
- More biologically realistic
- Can exhibit different dynamics than synchronous
- Requires careful handling of update order

## Rule Specification

Rules are defined in TOML format (see `rulespec.md` for details):

```toml
[rule]
name = "branching-growth"
states = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
neighborhood = "moore-3d"
transition = "outer-totalistic"

[params]
# Outer-totalistic: next state depends on current state + neighbor count
birth_range = [4, 7]
survival_range = [4, 7]
```

## Experiment Configuration

Experiments are defined in YAML:

```yaml
experiment:
  name: "branching-3"
  rule: "ca/rules/example.toml"
  seed: "ca/seeds/single-cell.json"
  steps: 500
  lattice_size: [64, 64, 64]
  metrics:
    - branching_factor
    - connectivity
    - survival
  output_dir: "artifacts/branching-3"
```

## Metrics

### Branching Factor

Ratio of active cells at step t+1 to step t:
```
branching_factor = active_cells(t+1) / active_cells(t)
```

Target: 1.0 < λ < 2.0 (edge of chaos)

### Connectivity

Fraction of cells that form connected components:
```
connectivity = connected_cells / total_active_cells
```

Target: > 0.8 (highly connected)

### Survival

Fraction of cells that remain active over time:
```
survival = persistent_cells / initial_cells
```

Target: > 0.5 (stable structures)

## Usage

### Running Experiments Locally

```bash
# Build the Rust crate
cd crates/uft_ca
cargo build --release

# Install Python dependencies
pip install -r src/uft_orch/ca/requirements.txt

# Run an experiment
python -m uft_orch.ca.runner ca/experiments/branching-3.yaml
```

### Running via CI

```bash
# Trigger workflow via GitHub CLI
gh workflow run ca-search.yml \
  -f experiment_path=ca/experiments/branching-3.yaml \
  -f repeats=10 \
  -f parallelism=5
```

## Development

### Adding New Rules

1. Create TOML file in `ca/rules/`
2. Define states, neighborhood, and transition logic
3. Add corresponding Rust implementation if needed
4. Create experiment config in `ca/experiments/`
5. Test locally before CI deployment

### Adding New Metrics

1. Implement metric computation in `runner.py`
2. Add to experiment config `metrics` list
3. Update CSV output schema
4. Document in this README

### Testing

```bash
# Rust tests
cd crates/uft_ca
cargo test

# Python tests (future)
pytest tests/ca/
```

## References

- Wolfram, S. (2002). *A New Kind of Science*
- Langton, C. G. (1990). "Computation at the edge of chaos"
- Wuensche, A. (2011). "Exploring Discrete Dynamics"

## Future Work

- [ ] Asynchronous stepping
- [ ] Table-driven rules (arbitrary transition tables)
- [ ] GPU acceleration via CUDA/Metal
- [ ] Distributed simulation across multiple nodes
- [ ] Interactive visualization (WebGL)
- [ ] Genetic algorithm for rule discovery
