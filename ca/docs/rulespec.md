# CA Rule Specification Format

## Overview

Rules are defined in TOML format to enable human-readable, version-controlled rule definitions. The format supports both outer-totalistic rules (state + neighbor count) and table-driven rules (arbitrary transition tables).

## Schema

### Basic Structure

```toml
[rule]
name = "rule-name"
states = ["STATE1", "STATE2", ...]
neighborhood = "moore-3d" | "graph"
transition = "outer-totalistic" | "table"

[params]
# Rule-specific parameters
```

## Rule Types

### Outer-Totalistic Rules

Next state depends only on:
1. Current cell state
2. Count of active neighbors (any non-VOID state)

**Example: Conway-3D**

```toml
[rule]
name = "conway-3d"
states = ["VOID", "ALIVE"]
neighborhood = "moore-3d"
transition = "outer-totalistic"

[params]
birth_range = [4, 7]      # Birth if 4-7 neighbors
survival_range = [4, 7]   # Survive if 4-7 neighbors
```

**Example: Multi-State Growth**

```toml
[rule]
name = "branching-growth"
states = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
neighborhood = "moore-3d"
transition = "outer-totalistic"

[params]
# State transitions based on neighbor count
[params.transitions]
VOID = { 4 = "STRUCTURAL", 5 = "STRUCTURAL", 6 = "STRUCTURAL" }
STRUCTURAL = { 2 = "STRUCTURAL", 3 = "STRUCTURAL", 4 = "COMPUTE" }
COMPUTE = { 2 = "COMPUTE", 3 = "ENERGY", 4 = "SENSOR" }
ENERGY = { 2 = "ENERGY", 3 = "ENERGY" }
SENSOR = { 2 = "SENSOR", 3 = "SENSOR" }
```

### Table-Driven Rules

Next state defined by explicit lookup table:
- Key: (current_state, neighbor_state_counts)
- Value: next_state

**Example: Custom Transition Table**

```toml
[rule]
name = "custom-table"
states = ["VOID", "STRUCTURAL", "COMPUTE"]
neighborhood = "moore-3d"
transition = "table"

[params.table]
# Format: "current_state:neighbor_counts" = "next_state"
# neighbor_counts is a tuple of (VOID, STRUCTURAL, COMPUTE) counts
"VOID:0,4,0" = "STRUCTURAL"
"VOID:0,5,0" = "STRUCTURAL"
"STRUCTURAL:0,2,1" = "COMPUTE"
"STRUCTURAL:0,3,0" = "STRUCTURAL"
"COMPUTE:0,1,2" = "COMPUTE"
```

## State Definitions

### Standard States

```toml
states = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]
```

- **VOID**: Empty space (always state 0)
- **STRUCTURAL**: Physical scaffold
- **COMPUTE**: Processing nodes
- **ENERGY**: Power distribution
- **SENSOR**: I/O nodes

### Custom States

You can define custom states for specific experiments:

```toml
states = ["VOID", "SEED", "BRANCH", "LEAF", "DEAD"]
```

States are mapped to u8 values in order (VOID=0, SEED=1, etc.)

## Neighborhood Types

### moore-3d

26-neighbor Moore neighborhood in 3D:
- Suitable for regular lattices
- Fixed boundary conditions (outside = VOID)

### graph

Arbitrary graph adjacency:
- Defined by explicit edge lists
- Supports irregular topologies
- Enables fractal branching structures

## Transition Types

### outer-totalistic

Simplified rule based on neighbor count:
- Fast to compute
- Easy to understand and tune
- Limited expressiveness

**Parameters:**
- `birth_range`: [min, max] neighbors for VOID → ALIVE
- `survival_range`: [min, max] neighbors for ALIVE → ALIVE
- `transitions`: Map of state → neighbor_count → next_state

### table

Full transition table:
- Maximum expressiveness
- Can encode arbitrary logic
- Larger memory footprint
- Harder to design manually

**Parameters:**
- `table`: Map of (state, neighbor_counts) → next_state

## Validation

Rules are validated on load:

1. **State consistency**: All referenced states must be in `states` list
2. **Neighbor count bounds**: Must be ≤ max_neighbors for neighborhood
3. **Transition completeness**: All reachable (state, count) pairs must have transitions
4. **Type safety**: Neighbor counts must be integers, states must be strings

## Examples

### Example 1: Simple Growth

```toml
[rule]
name = "simple-growth"
states = ["VOID", "ALIVE"]
neighborhood = "moore-3d"
transition = "outer-totalistic"

[params]
birth_range = [3, 5]
survival_range = [2, 4]
```

### Example 2: Fractal Branching

```toml
[rule]
name = "fractal-branch"
states = ["VOID", "STRUCTURAL", "COMPUTE"]
neighborhood = "graph"
transition = "outer-totalistic"

[params]
[params.transitions]
VOID = { 1 = "STRUCTURAL", 2 = "STRUCTURAL" }
STRUCTURAL = { 1 = "COMPUTE", 2 = "STRUCTURAL" }
COMPUTE = { 1 = "COMPUTE" }
```

### Example 3: Energy Flow

```toml
[rule]
name = "energy-flow"
states = ["VOID", "STRUCTURAL", "ENERGY"]
neighborhood = "moore-3d"
transition = "table"

[params.table]
"VOID:0,1,0" = "STRUCTURAL"
"STRUCTURAL:0,1,1" = "ENERGY"
"STRUCTURAL:0,2,0" = "STRUCTURAL"
"ENERGY:0,1,1" = "ENERGY"
"ENERGY:0,0,2" = "ENERGY"
```

## Implementation Notes

### Rust Side

Rules are parsed from TOML and compiled to efficient transition functions:

```rust
pub type OuterTotalisticRule = fn(u8, usize) -> u8;
pub type TableRule = HashMap<(u8, Vec<usize>), u8>;
```

### Python Side

Rules are loaded via `RuleSpec.from_toml()` and passed to the Rust kernel:

```python
rule = RuleSpec.from_toml(Path("ca/rules/example.toml"))
runner = CARunner(config)
runner.run()
```

## Future Extensions

- [ ] Probabilistic transitions (stochastic rules)
- [ ] Time-varying rules (rule evolution)
- [ ] Multi-scale rules (hierarchical CA)
- [ ] Continuous-state CA (reaction-diffusion)
- [ ] Rule composition (combine multiple rules)
