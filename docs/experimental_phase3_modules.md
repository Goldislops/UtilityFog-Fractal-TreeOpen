# Phase 3 NVIDIA Architecture Rewrite (Targeted)

This note summarizes the **newly wired equations** and what is still hypothesis-stage.

## Implemented mechanisms

1. **Mamba-Viking memory update (Rust)**
   - `memory_strength` now follows a delta-prioritized state-space update:
     - `M(t+1) = M(t) exp(-1/tau(delta)) + B(delta) delta + S Phi(age)`
   - Low-delta sequential noise is pruned; high-delta events preserve a minimum memory floor.

2. **Cosmos Predict trigger (Python)**
   - Rolling density detector now computes **Savitzky-Golay-like** first/second derivatives
     from a windowed polynomial fit (default `N=10`).
   - PRE-CONTRACTION trigger condition:
     - `d rho / dt < -theta_c/2`
     - `d^2 rho / dt^2 < -alpha_c`
   - When enabled, this gates `contraction_phase=True` into sandboxed memory protection.

3. **Void Sanctuary shield (Rust)**
   - Isolated COMPUTE (`n=0`) receives a `Lambda_void = 50.0` resistance multiplier.
   - Isolated COMPUTE aging is slowed to half-rate (effective +0.5 step/step).

4. **Dimensional regularization epsilon-buffer (Rust)**
   - For dense neighborhoods (`n >= 20`), death probability is regularized:
     - `P_reg = P_max - epsilon * exp(-(n - n_c)/tau_epsilon)`
   - `P_max` is capped at `0.943`, preserving a >5% survival floor.

## Validation scope in this PR

- Added focused tests for selective-decay behavior, detector triggering, void-aging slowdown,
  and epsilon survival cap invariants.

## Non-claims

- No claim that reduced lattices are predictive of full-scale dynamics.
- No claim that these changes alone solve all long-run mortality regimes.
