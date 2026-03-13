# Phase 3 Experimental Modules

## Overview
Phase 3 introduces four new survival mechanisms to address the Mayfly Problem
(median STRUCTURAL lifespan of 1 step, COMPUTE lifespan of 0 steps).

## Modules

### 1. Mamba-Viking Memory Dynamics
State-space memory update with tanh-like gating:
- mamba_delta_threshold: 0.12 (density delta activation gate)
- mamba_tau_base: 5.0, mamba_tau_scale: 12.0 (time constant)
- mamba_boost_base: 0.015, mamba_boost_gain: 0.045 (boost coefficients)
- mamba_age_stability_gain: 0.03 (age-dependent stability)
- mamba_high_delta_floor: 1.15 (memory floor for high-delta events)

### 2. Cosmos Predict (Savitzky-Golay Trigger)
Polynomial density-derivative detector:
- Window size: 10, polynomial order: 3
- Trigger: d1 < -theta_c/2 AND d2 < -alpha_c
- theta_c: 0.12, alpha_c: 0.02

### 3. Void Sanctuary Shield
Isolated COMPUTE protection:
- 50x resistance multiplier for 0-neighbor COMPUTE
- Half-rate aging toggle (compute_half_step)

### 4. Dimensional Regularization (Epsilon Buffer)
Dense neighborhood survival floor:
- P_reg = P_max - epsilon * exp(-(n - n_c) / tau)
- epsilon_p_max: 0.943, epsilon_buffer: 0.08
- epsilon_n_c: 20, epsilon_tau: 3.0
- Guarantees >5.7% survival floor in packed regions

## Transition Table Rewrite
- STRUCTURAL stable at 0-2 neighbors (was only 2-3)
- COMPUTE stable at 1-3 neighbors
- ENERGY stable at 0-5 neighbors
- Addresses the dominant 72% deterministic kill pathway
