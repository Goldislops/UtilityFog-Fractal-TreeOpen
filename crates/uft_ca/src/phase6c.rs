//! Phase 6c: Mindsight + Mycelial Network + Compassion
//!
//! Runs every signal_interval steps (default=10).
//! 1. Mindsight: SENSOR density gradient sensing via R=12 box filter
//! 2. Mycelial Network: SENSOR->ENERGY handoff, K=3 masked diffusion
//! 3. Compassion: Mature COMPUTE donates resources for remote resistance buff

use crate::memory::{
    VoxelMemoryParams, COMPUTE, ENERGY, SENSOR,
    CH_COMPUTE_AGE, CH_MEMORY_STRENGTH, CH_ENERGY_RESERVE,
    CH_SIGNAL_FIELD, CH_COMPASSION_COOLDOWN,
};
use crate::filters;

/// Full Phase 6c nervous system pass.
/// Only called when generation % signal_interval == 0.
pub fn nervous_system_step(
    states: &[u8],
    memory: &mut [[f32; 8]],
    size: usize,
    params: &VoxelMemoryParams,
    compute_max_age: f32,
    rng_vals: &[f32],
) -> (u32, u32) {
    let n3 = size * size * size;

    // --- 1. Mindsight: SENSOR density gradient ---
    let sensor_density = compute_sensor_density(states, size, params);
    let gradient = compute_gradient(&sensor_density, size);

    // Compute signal values: S_0 = S_max * tanh(grad / sigma)
    let mut signal = vec![0.0f32; n3];
    let s_max = params.mindsight_s_max;
    let sigma_opp = params.mindsight_sigma_opp;
    let sigma_dis = params.mindsight_sigma_dis;
    let threshold = params.mindsight_threshold;

    for i in 0..n3 {
        if states[i] != SENSOR {
            continue;
        }
        let g = gradient[i];
        let sigma = if g >= 0.0 { sigma_opp } else { sigma_dis };
        let s = s_max * (g / sigma).tanh();
        if s.abs() > threshold {
            signal[i] = s;
        }
    }

    // --- 2. Mycelial Network: SENSOR->ENERGY handoff + diffusion ---
    // Handoff: deliver SENSOR signal to ENERGY neighbors via max
    let sensor_mask: Vec<bool> = states.iter().map(|&s| s == SENSOR).collect();
    let mut delivered = filters::deliver_to_neighbors(&signal, &sensor_mask, size);

    // Only propagate through ENERGY cells
    let energy_mask: Vec<bool> = states.iter().map(|&s| s == ENERGY).collect();

    // Asymmetric decay based on signal sign
    let lambda_dis = params.mycelial_lambda_distress;
    let lambda_opp = params.mycelial_lambda_opportunity;

    // Apply exponential decay before diffusion
    for i in 0..n3 {
        if delivered[i] != 0.0 {
            let lambda = if delivered[i] < 0.0 { lambda_dis } else { lambda_opp };
            delivered[i] *= (-1.0 / lambda).exp();
        }
    }

    // K iterations of masked diffusion through ENERGY
    let k_iter = params.mycelial_k_iter as usize;
    let decay = (-1.0 / lambda_dis).exp(); // use distress decay for diffusion
    filters::mycelial_diffuse(&mut delivered, &energy_mask, size, k_iter, decay);

    // Deliver diffused signal to ALL neighbors (including COMPUTE)
    let _all_mask = vec![true; n3];
    let final_signal = filters::deliver_to_neighbors(&delivered, &energy_mask, size);

    // Store signal in memory channel 5
    let mut signal_active = 0u32;
    for i in 0..n3 {
        memory[i][CH_SIGNAL_FIELD] = final_signal[i];
        if final_signal[i].abs() > threshold {
            signal_active += 1;
        }
    }

    // --- 3. Compassion: mature COMPUTE donates for remote resistance ---
    let compassion_active = apply_compassion(
        states, memory, &final_signal, size, params, compute_max_age, rng_vals,
    );

    (signal_active, compassion_active)
}

/// Compute smoothed SENSOR density using R=12 separable box filter.
fn compute_sensor_density(states: &[u8], size: usize, params: &VoxelMemoryParams) -> Vec<f32> {
    let _n3 = size * size * size;
    let sensor_field: Vec<f32> = states.iter().map(|&s| if s == SENSOR { 1.0 } else { 0.0 }).collect();
    filters::box_filter_3d(&sensor_field, size, params.mindsight_radius as usize)
}

/// Compute gradient magnitude of smoothed density field.
fn compute_gradient(field: &[f32], size: usize) -> Vec<f32> {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;
    let mut grad = vec![0.0f32; n3];

    for z in 0..n {
        for y in 0..n {
            for x in 0..n {
                let idx = z * n2 + y * n + x;
                // Central differences with periodic wrapping
                let xp = ((x as i32 + 1).rem_euclid(n as i32)) as usize;
                let xm = ((x as i32 - 1).rem_euclid(n as i32)) as usize;
                let yp = ((y as i32 + 1).rem_euclid(n as i32)) as usize;
                let ym = ((y as i32 - 1).rem_euclid(n as i32)) as usize;
                let zp = ((z as i32 + 1).rem_euclid(n as i32)) as usize;
                let zm = ((z as i32 - 1).rem_euclid(n as i32)) as usize;

                let dx = field[z * n2 + y * n + xp] - field[z * n2 + y * n + xm];
                let dy = field[z * n2 + yp * n + x] - field[z * n2 + ym * n + x];
                let dz = field[zp * n2 + y * n + x] - field[zm * n2 + y * n + x];

                grad[idx] = (dx * dx + dy * dy + dz * dz).sqrt();
            }
        }
    }
    grad
}

/// Compassion: mature COMPUTE cells donate energy/memory for remote resistance buff.
fn apply_compassion(
    states: &[u8],
    memory: &mut [[f32; 8]],
    signal: &[f32],
    size: usize,
    params: &VoxelMemoryParams,
    compute_max_age: f32,
    rng_vals: &[f32],
) -> u32 {
    let n3 = size * size * size;
    let mut compassion_count = 0u32;

    let beta = params.compassion_beta;
    let gamma = params.compassion_gamma;
    let a_scale = params.compassion_age_scale_min.max(compute_max_age * params.compassion_age_scale_factor);

    // Identify distress zones (negative signal below threshold)
    let threshold = params.mindsight_threshold;

    for i in 0..n3 {
        if states[i] != COMPUTE {
            continue;
        }
        // Must be mature (age > equanimity_age_min) and not on cooldown
        let age = memory[i][CH_COMPUTE_AGE];
        if age <= params.equanimity_age_min {
            continue;
        }
        if memory[i][CH_COMPASSION_COOLDOWN] > 0.0 {
            continue;
        }

        // Check if there is distress signal
        let sig = signal[i];
        if sig > -threshold {
            continue;
        }

        // Phi_compassion = |S| * (a_self / a_compassion_scale)
        let phi = sig.abs() * (age / a_scale);

        // Stochastic activation
        if rng_vals[i] >= phi {
            continue;
        }

        // Donate: local cost
        memory[i][CH_ENERGY_RESERVE] *= 1.0 - gamma;
        memory[i][CH_MEMORY_STRENGTH] *= 1.0 - gamma;
        memory[i][CH_COMPASSION_COOLDOWN] = 5.0; // 5-step cooldown

        // Remote buff: boost memory_strength in distress neighborhood
        // Apply to 26 neighbors
        let (x, y, z) = idx_to_coords(i, size);
        for dz in [-1i32, 0, 1] {
            for dy in [-1i32, 0, 1] {
                for dx in [-1i32, 0, 1] {
                    if dx == 0 && dy == 0 && dz == 0 {
                        continue;
                    }
                    let nx = ((x as i32 + dx).rem_euclid(size as i32)) as usize;
                    let ny = ((y as i32 + dy).rem_euclid(size as i32)) as usize;
                    let nz = ((z as i32 + dz).rem_euclid(size as i32)) as usize;
                    let ni = nz * size * size + ny * size + nx;
                    memory[ni][CH_MEMORY_STRENGTH] = (memory[ni][CH_MEMORY_STRENGTH] * (1.0 + beta)).min(2.0);
                }
            }
        }
        compassion_count += 1;
    }

    compassion_count
}

/// Decay compassion cooldown (runs EVERY step, not just at signal_interval).
pub fn decay_cooldown(memory: &mut [[f32; 8]]) {
    for m in memory.iter_mut() {
        if m[CH_COMPASSION_COOLDOWN] > 0.0 {
            m[CH_COMPASSION_COOLDOWN] -= 1.0;
            if m[CH_COMPASSION_COOLDOWN] < 0.0 {
                m[CH_COMPASSION_COOLDOWN] = 0.0;
            }
        }
    }
}

#[inline]
fn idx_to_coords(idx: usize, size: usize) -> (usize, usize, usize) {
    let z = idx / (size * size);
    let rem = idx % (size * size);
    let y = rem / size;
    let x = rem % size;
    (x, y, z)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cooldown_decay() {
        let mut memory = vec![[0.0f32; 8]; 3];
        memory[0][CH_COMPASSION_COOLDOWN] = 5.0;
        memory[1][CH_COMPASSION_COOLDOWN] = 1.0;
        memory[2][CH_COMPASSION_COOLDOWN] = 0.0;

        decay_cooldown(&mut memory);

        assert_eq!(memory[0][CH_COMPASSION_COOLDOWN], 4.0);
        assert_eq!(memory[1][CH_COMPASSION_COOLDOWN], 0.0);
        assert_eq!(memory[2][CH_COMPASSION_COOLDOWN], 0.0);
    }

    #[test]
    fn test_sensor_density_uniform() {
        let size = 4;
        let states = vec![SENSOR; 64];
        let params = VoxelMemoryParams::default();
        let density = compute_sensor_density(&states, size, &params);
        for v in &density {
            assert!((v - 1.0).abs() < 1e-4, "Uniform SENSOR should have density ~1.0");
        }
    }
}
