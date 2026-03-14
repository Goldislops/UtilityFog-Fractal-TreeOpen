//! Master stepper: 17-phase pipeline matching Python's exact execution order.
//!
//! This is the heart of the CA engine - one call to step() advances the lattice
//! by exactly one generation, applying all Phase 3-6c mechanics.

use rand::Rng;

use crate::memory::{
    VoxelMemoryParams, VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR, NUM_STATES,
    CH_COMPUTE_AGE, CH_STRUCTURAL_AGE, CH_MEMORY_STRENGTH, CH_ENERGY_RESERVE,
    CH_LAST_ACTIVE_GEN,
    MEMORY_CHANNELS,
};
use crate::params::FullConfig;
use crate::rng_util::CaRng;
use crate::voxel_lattice::VoxelLattice;
use crate::filters;
use crate::phase4;
use crate::phase6a;
use crate::phase6b;
use crate::phase6c;
use crate::metrics::StepMetrics;

/// Advance the lattice by one generation. Returns step metrics.
pub fn step(lattice: &mut VoxelLattice, config: &FullConfig, rng: &mut CaRng) -> StepMetrics {
    let n = lattice.size;
    let n3 = lattice.len();
    let gen = lattice.generation;
    let params = &config.memory_params;

    // Pre-generate random values for this step
    let rng_vals: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();

    // ---- Phase 1: Count neighbors (26 Moore, all 5 states) ----
    let neighbor_counts = filters::count_neighbors_3d(&lattice.states, n);
    let nonvoid_counts = filters::count_nonvoid_neighbors(&lattice.states, n);

    // ---- Phase 2: Deterministic transitions (lookup table) ----
    let mut out = lattice.states.clone();
    for i in 0..n3 {
        let current = lattice.states[i];
        if current == VOID {
            // VOID + dominant neighbor -> transition
            let dominant = dominant_neighbor(&neighbor_counts[i]);
            if let Some(new_state) = config.transition_table.get(current, dominant) {
                out[i] = new_state;
            }
        } else {
            // Non-void: check for isolation death (but Phase 4 COMPUTE(0)->COMPUTE overrides)
            if current == COMPUTE && nonvoid_counts[i] == 0 {
                // Phase 4: COMPUTE(0) -> COMPUTE (contemplative isolation, no death)
                out[i] = COMPUTE;
            } else {
                let dominant = dominant_neighbor(&neighbor_counts[i]);
                if let Some(new_state) = config.transition_table.get(current, dominant) {
                    out[i] = new_state;
                }
            }
        }
    }

    // ---- Phase 3: Equanimity mask (store for later restoration) ----
    let (equanimity_mask, equanimity_saved) =
        phase4::compute_equanimity_mask(&out, &lattice.memory, params, &rng_vals);

    // ---- Phase 4: Sympathetic Joy (boost memory_strength) ----
    phase6b::apply_sympathetic_joy(&out, &mut lattice.memory, n, params);

    // ---- Phase 5: Nervous system (if gen % signal_interval == 0) ----
    let mut signal_active = 0u32;
    let mut compassion_active = 0u32;
    let signal_interval = params.signal_interval as u32;

    // Compute max age for compassion scaling
    let compute_max_age = lattice.memory.iter()
        .enumerate()
        .filter(|(i, _)| out[*i] == COMPUTE)
        .map(|(_, m)| m[CH_COMPUTE_AGE])
        .fold(0.0f32, f32::max);

    if signal_interval > 0 && gen % signal_interval == 0 {
        let rng_vals2: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        let (sa, ca) = phase6c::nervous_system_step(
            &out, &mut lattice.memory, n, params, compute_max_age, &rng_vals2,
        );
        signal_active = sa;
        compassion_active = ca;
    }

    // Cooldown decay happens EVERY step
    phase6c::decay_cooldown(&mut lattice.memory);

    // ---- Phase 6: Stochastic transitions ----
    if config.stochastic.enabled {
        let rng_vals3: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        apply_stochastic(&mut out, &neighbor_counts, &config, &rng_vals3);
    }

    // ---- Phase 7: Forward contagion ----
    if config.contagion.enabled {
        let rng_vals4: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        apply_forward_contagion(&mut out, &neighbor_counts, &config, params, &rng_vals4);
    }

    // ---- Phase 8: Reverse contagion (COMPUTE reclaims STRUCTURAL) ----
    {
        let rng_vals5: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        apply_reverse_contagion(&mut out, &neighbor_counts, params, &rng_vals5);
    }

    // ---- Phase 9: Metta warmth + survival floor ----
    phase6a::apply_metta_warmth(&out, &mut lattice.memory, &neighbor_counts, params);

    // ---- Phase 10: Inactivity decay ----
    if config.decay.enabled {
        apply_inactivity_decay(&mut out, &mut lattice.inactivity_steps, &neighbor_counts, &config);
    }

    // ---- Phase 11: Energy->Compute conversion (biofilm, super-pod) ----
    {
        let rng_vals6: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        apply_energy_conversion(&mut out, &neighbor_counts, &config, &rng_vals6);
    }

    // ---- Phase 12: Memory reinforcement + aging ----
    apply_memory_aging(
        &out, &lattice.states, &mut lattice.memory,
        &nonvoid_counts, gen, params, &config.cosmic,
    );

    // ---- Phase 13: Decay resistance ----
    {
        let rng_vals7: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        apply_decay_resistance(
            &mut out, &lattice.memory, &nonvoid_counts, &neighbor_counts,
            params, &config.stochastic, &rng_vals7,
        );
    }

    // ---- Phase 14: Equanimity restoration ----
    phase4::restore_equanimity(&mut out, &equanimity_mask, &equanimity_saved);

    // ---- Phase 15: Analogue mutation (3%, pre_mut snapshot critical) ----
    {
        let pre_mut = out.clone();
        let rng_vals8: Vec<f32> = (0..n3).map(|_| rng.gen::<f32>()).collect();
        apply_analogue_mutation(&mut out, &pre_mut, &config.cosmic, &rng_vals8);
    }

    // ---- Phase 16: Age grid update ----
    for i in 0..n3 {
        if out[i] == COMPUTE {
            lattice.age_grid[i] = lattice.memory[i][CH_COMPUTE_AGE];
        } else {
            lattice.age_grid[i] = 0.0;
        }
    }

    // ---- Phase 17: Metrics computation ----
    let metrics = StepMetrics::compute(&out, &lattice.memory, gen, signal_active, compassion_active);

    // Commit state
    lattice.states = out;
    lattice.generation += 1;

    metrics
}

/// Find dominant (most frequent non-void) neighbor state.
fn dominant_neighbor(counts: &[i16; NUM_STATES]) -> u8 {
    let mut best = 0u8;
    let mut best_count = 0i16;
    for s in 1..NUM_STATES {
        if counts[s] > best_count {
            best_count = counts[s];
            best = s as u8;
        }
    }
    best
}

/// Phase 6: Stochastic transitions.
fn apply_stochastic(
    states: &mut [u8],
    _counts: &[[i16; NUM_STATES]],
    config: &FullConfig,
    rng_vals: &[f32],
) {
    let s = &config.stochastic;
    for i in 0..states.len() {
        let r = rng_vals[i];
        match states[i] {
            STRUCTURAL => {
                if r < s.structural_to_energy_prob {
                    states[i] = ENERGY;
                } else if r < s.structural_to_energy_prob + s.structural_to_sensor_prob {
                    states[i] = SENSOR;
                }
            }
            COMPUTE => {
                if r < s.compute_to_energy_prob {
                    states[i] = ENERGY;
                } else if r < s.compute_to_energy_prob + s.compute_to_sensor_prob {
                    states[i] = SENSOR;
                }
            }
            _ => {}
        }
    }
}

/// Phase 7: Forward contagion.
fn apply_forward_contagion(
    states: &mut [u8],
    counts: &[[i16; NUM_STATES]],
    config: &FullConfig,
    params: &VoxelMemoryParams,
    rng_vals: &[f32],
) {
    let c = &config.contagion;
    for i in 0..states.len() {
        let r = rng_vals[i];
        match states[i] {
            STRUCTURAL => {
                if counts[i][ENERGY as usize] >= c.energy_neighbor_threshold as i16 {
                    // Forward contagion mitigation
                    let n_compute = counts[i][COMPUTE as usize];
                    let mut prob = c.structural_energy_conversion_prob;
                    if n_compute >= params.forward_contagion_threshold as i16 {
                        prob = (prob - params.forward_contagion_penalty).max(params.forward_contagion_floor);
                    }
                    if r < prob { states[i] = ENERGY; }
                } else if counts[i][SENSOR as usize] >= c.sensor_neighbor_threshold as i16 {
                    if r < c.structural_sensor_conversion_prob { states[i] = SENSOR; }
                }
            }
            COMPUTE => {
                if counts[i][ENERGY as usize] >= c.energy_neighbor_threshold as i16 {
                    if r < c.compute_energy_conversion_prob { states[i] = ENERGY; }
                } else if counts[i][SENSOR as usize] >= c.sensor_neighbor_threshold as i16 {
                    if r < c.compute_sensor_conversion_prob { states[i] = SENSOR; }
                }
            }
            _ => {}
        }
    }
}

/// Phase 8: Reverse contagion (COMPUTE reclaims STRUCTURAL).
fn apply_reverse_contagion(
    states: &mut [u8],
    counts: &[[i16; NUM_STATES]],
    params: &VoxelMemoryParams,
    rng_vals: &[f32],
) {
    for i in 0..states.len() {
        if states[i] == STRUCTURAL {
            let n_compute = counts[i][COMPUTE as usize];
            if n_compute >= params.reverse_contagion_threshold as i16 {
                let prob = params.reverse_contagion_base_prob
                    + params.reverse_contagion_boost * (n_compute as f32 - params.reverse_contagion_threshold as f32);
                if rng_vals[i] < prob {
                    states[i] = COMPUTE;
                }
            }
        }
    }
}

/// Phase 10: Inactivity decay.
fn apply_inactivity_decay(
    states: &mut [u8],
    inactivity: &mut [i16],
    counts: &[[i16; NUM_STATES]],
    config: &FullConfig,
) {
    let d = &config.decay;
    for i in 0..states.len() {
        if states[i] == STRUCTURAL {
            // Count active (non-void) neighbors
            let active = counts[i][STRUCTURAL as usize]
                + counts[i][COMPUTE as usize]
                + counts[i][ENERGY as usize]
                + counts[i][SENSOR as usize];
            if active <= d.inactivity_neighbor_threshold as i16 {
                inactivity[i] += 1;
                if inactivity[i] >= d.structural_inactive_steps_to_decay as i16 {
                    states[i] = VOID;
                    inactivity[i] = 0;
                }
            } else {
                inactivity[i] = 0;
            }
        } else {
            inactivity[i] = 0;
        }
    }
}

/// Phase 11: Energy->Compute conversion (biofilm leech, super-pod).
fn apply_energy_conversion(
    states: &mut [u8],
    counts: &[[i16; NUM_STATES]],
    config: &FullConfig,
    rng_vals: &[f32],
) {
    let cosmic = &config.cosmic;
    for i in 0..states.len() {
        if states[i] == ENERGY {
            let n_compute = counts[i][COMPUTE as usize];
            // Biofilm leech: ENERGY near COMPUTE -> COMPUTE
            if n_compute > 0 && rng_vals[i] < cosmic.biofilm_leech_rate {
                states[i] = COMPUTE;
            }
            // Super-pod: dense ENERGY clusters -> COMPUTE
            else if counts[i][ENERGY as usize] >= cosmic.super_pod_threshold as i16 {
                if rng_vals[i] < 0.05 {
                    states[i] = COMPUTE;
                }
            }
        }
    }
}

/// Phase 12: Memory reinforcement + aging.
fn apply_memory_aging(
    out: &[u8],
    prev: &[u8],
    memory: &mut [[f32; MEMORY_CHANNELS]],
    nonvoid_counts: &[i16],
    gen: u32,
    params: &VoxelMemoryParams,
    cosmic: &crate::params::CosmicGardenConfig,
) {
    for i in 0..out.len() {
        let state = out[i];
        let is_isolated = nonvoid_counts[i] == 0;

        match state {
            COMPUTE => {
                // Half-rate aging for isolated COMPUTE
                let age_rate = if is_isolated { 0.5 } else { 1.0 };
                memory[i][CH_COMPUTE_AGE] += age_rate;

                // Bamboo rebirth: if age >= bamboo_rebirth_age, reset
                if memory[i][CH_COMPUTE_AGE] >= cosmic.bamboo_rebirth_age as f32 {
                    memory[i][CH_COMPUTE_AGE] = 0.0;
                    memory[i][CH_MEMORY_STRENGTH] = 1.0;
                }

                // Memory reinforcement (Mamba-Viking dynamics)
                let delta = if prev[i] != out[i] { 1.0 } else { 0.0 };
                let tau = params.mamba_tau_base + params.mamba_tau_scale * (1.0 - delta);
                let boost = params.mamba_boost_base + params.mamba_boost_gain * delta;
                let age_stability = params.mamba_age_stability_gain * (memory[i][CH_COMPUTE_AGE] / 10.0).min(1.0);

                memory[i][CH_MEMORY_STRENGTH] = memory[i][CH_MEMORY_STRENGTH]
                    * (-1.0 / tau).exp()
                    + boost * delta
                    + age_stability;

                // Clamp
                memory[i][CH_MEMORY_STRENGTH] = memory[i][CH_MEMORY_STRENGTH].clamp(0.01, 2.0);

                // High delta floor
                if delta > params.mamba_delta_threshold {
                    memory[i][CH_MEMORY_STRENGTH] = memory[i][CH_MEMORY_STRENGTH].max(params.mamba_high_delta_floor);
                }

                memory[i][CH_LAST_ACTIVE_GEN] = gen as f32;
            }
            STRUCTURAL => {
                memory[i][CH_STRUCTURAL_AGE] += 1.0;
                memory[i][CH_LAST_ACTIVE_GEN] = gen as f32;
            }
            VOID => {
                // Reset memory on void
                memory[i][CH_COMPUTE_AGE] = 0.0;
                memory[i][CH_STRUCTURAL_AGE] = 0.0;
                memory[i][CH_MEMORY_STRENGTH] = 1.0;
                memory[i][CH_ENERGY_RESERVE] = 1.0;
            }
            _ => {
                memory[i][CH_LAST_ACTIVE_GEN] = gen as f32;
            }
        }
    }
}

/// Phase 13: Decay resistance (age curve x memory x Void Sanctuary x Epsilon Buffer).
fn apply_decay_resistance(
    states: &mut [u8],
    memory: &[[f32; MEMORY_CHANNELS]],
    nonvoid_counts: &[i16],
    neighbor_counts: &[[i16; NUM_STATES]],
    params: &VoxelMemoryParams,
    stochastic: &crate::params::StochasticConfig,
    rng_vals: &[f32],
) {
    for i in 0..states.len() {
        let base_decay = match states[i] {
            STRUCTURAL => stochastic.structural_to_void_decay_prob,
            ENERGY => stochastic.energy_to_void_decay_prob,
            SENSOR => stochastic.sensor_to_void_decay_prob,
            COMPUTE => 0.0, // COMPUTE uses equanimity shield, not generic decay
            _ => continue,
        };

        if base_decay <= 0.0 || states[i] == COMPUTE {
            continue;
        }

        let mut decay_prob = base_decay;

        // Metta survival floor
        if states[i] == STRUCTURAL {
            let n_energy = neighbor_counts[i][ENERGY as usize];
            let floor = phase6a::metta_survival_floor(n_energy, params);
            if floor > decay_prob {
                decay_prob = 0.0; // Protected by metta warmth
                continue;
            }
        }

        // Void Sanctuary: isolated cells get 50x resistance
        let is_isolated = nonvoid_counts[i] == 0;
        if is_isolated {
            decay_prob /= params.void_sanctuary_multiplier;
        }

        // Epsilon Buffer: packed cells (20+ neighbors) get survival floor
        if nonvoid_counts[i] >= params.epsilon_n_c as i16 {
            let epsilon_resist = params.epsilon_p_max
                * (1.0 - (-((nonvoid_counts[i] as f32 - params.epsilon_n_c as f32) / params.epsilon_tau)).exp());
            if epsilon_resist > 0.0 {
                decay_prob *= 1.0 - epsilon_resist;
            }
        }

        // Memory strength modulation
        let mem_strength = memory[i][CH_MEMORY_STRENGTH];
        decay_prob /= mem_strength.max(0.01);

        if rng_vals[i] < decay_prob {
            states[i] = VOID;
        }
    }
}

/// Phase 15: Analogue mutation (3%).
fn apply_analogue_mutation(
    states: &mut [u8],
    pre_mut: &[u8],
    cosmic: &crate::params::CosmicGardenConfig,
    rng_vals: &[f32],
) {
    let mutation_rate = cosmic.analogue_mutation;
    if mutation_rate <= 0.0 {
        return;
    }
    for i in 0..states.len() {
        if pre_mut[i] != VOID && rng_vals[i] < mutation_rate {
            // Mutate to a random non-void state different from current
            let current = pre_mut[i];
            let new_state = match (rng_vals[i] * 100.0) as u32 % 4 {
                0 => STRUCTURAL,
                1 => COMPUTE,
                2 => ENERGY,
                3 => SENSOR,
                _ => current,
            };
            if new_state != current {
                states[i] = new_state;
            }
        }
    }
}

/// Step N generations, returning final metrics.
pub fn step_n(lattice: &mut VoxelLattice, config: &FullConfig, rng: &mut CaRng, n: u32) -> StepMetrics {
    let mut metrics = StepMetrics::default();
    for _ in 0..n {
        metrics = step(lattice, config, rng);
    }
    metrics
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng_util::create_rng;

    #[test]
    fn test_single_step_no_crash() {
        let mut lattice = VoxelLattice::new(4);
        // Place some non-void cells
        lattice.states[0] = STRUCTURAL;
        lattice.states[1] = COMPUTE;
        lattice.states[2] = ENERGY;
        lattice.states[3] = SENSOR;

        let config = FullConfig::default();
        let mut rng = create_rng(42);
        let metrics = step(&mut lattice, &config, &mut rng);

        assert_eq!(metrics.generation, 0);
        assert!(lattice.generation == 1);
    }

    #[test]
    fn test_10_steps_stable() {
        let mut lattice = VoxelLattice::new(8);
        // Initialize with some structure
        for i in 0..lattice.len() {
            lattice.states[i] = (i % 5) as u8;
        }
        let config = FullConfig::default();
        let mut rng = create_rng(42);
        let metrics = step_n(&mut lattice, &config, &mut rng, 10);
        assert_eq!(lattice.generation, 10);
        assert!(metrics.entropy >= 0.0);
    }

    #[test]
    fn test_dominant_neighbor() {
        let counts = [0i16, 5, 3, 10, 2]; // ENERGY=10 is dominant
        assert_eq!(dominant_neighbor(&counts), ENERGY);
    }
}
