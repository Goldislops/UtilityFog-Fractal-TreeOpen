# Experimental Phase 3 Modules (Feature-Flagged)

This document describes **hypothesis-stage** infrastructure added for experimentation.

## Hypothesis-stage modules (default OFF)

- Selective memory decay (`params.experimental.selective_memory_decay`)
  - Mamba-inspired selective decay lane for `memory_strength`.
  - Hypothesis: selective decay can improve adaptation under density shifts.
- Density-phase detector (`params.experimental.density_phase_detector`)
  - Rolling detector for density, first derivative, second derivative.
  - Hypothesis: contraction-phase detection can gate sandboxed memory stepping.
- Mini-lattice mutation harness (`run_mini_lattice_mutation_trials`)
  - 16^3 default for isolated mutation trials.
  - Hypothesis: reduced lattice can rank mutation classes quickly.

## Validated in this PR

- Config loading paths for experimental flags.
- Detector trigger logic under contraction-like density traces.
- Selective decay math behavior for high-decay vs low-decay paths.

## Not validated / not claimed

- No claim of predictive equivalence between 16^3 and production-scale lattices.
- No production mutation acceptance wiring.
- No changes to Mayfly ecology parameters, Bamboo thresholds, or existing telemetry control panel behavior.
