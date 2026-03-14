//! Phase 4: Equanimity Shield
//!
//! P_resist(a, M) = P_max * (1 - exp(-(a - a_m) / tau)) * tanh(gamma * M)
//! Computed BEFORE all kills, restored AFTER all kills (exact Python ordering).

use crate::memory::{VoxelMemoryParams, COMPUTE, CH_COMPUTE_AGE, CH_MEMORY_STRENGTH};

/// Compute equanimity mask: which COMPUTE cells resist state transitions.
/// Returns a Vec<bool> where true = cell resists (should be restored after kills).
/// Also returns the saved states for restoration.
pub fn compute_equanimity_mask(
    states: &[u8],
    memory: &[[f32; 8]],
    params: &VoxelMemoryParams,
    rng_val: &[f32],  // pre-generated uniform random values [0,1) per cell
) -> (Vec<bool>, Vec<u8>) {
    let n = states.len();
    let mut resist_mask = vec![false; n];
    let mut saved_states = vec![0u8; n];

    let a_m = params.equanimity_age_min;
    let p_max = params.equanimity_p_max;
    let tau = params.equanimity_tau;
    let gamma = params.equanimity_gamma;

    for i in 0..n {
        if states[i] != COMPUTE {
            continue;
        }
        let age = memory[i][CH_COMPUTE_AGE];
        if age <= a_m {
            continue;
        }
        let mem_strength = memory[i][CH_MEMORY_STRENGTH];
        let p_resist = p_max
            * (1.0 - (-(age - a_m) / tau).exp())
            * (gamma * mem_strength).tanh();
        if rng_val[i] < p_resist {
            resist_mask[i] = true;
            saved_states[i] = COMPUTE;
        }
    }
    (resist_mask, saved_states)
}

/// Restore equanimity-shielded cells after all kill phases.
/// Any cell that was marked as resisting gets its state restored to COMPUTE.
pub fn restore_equanimity(
    states: &mut [u8],
    resist_mask: &[bool],
    saved_states: &[u8],
) {
    for i in 0..states.len() {
        if resist_mask[i] {
            states[i] = saved_states[i];
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::init_memory;

    #[test]
    fn test_young_compute_no_resist() {
        let states = vec![COMPUTE; 1];
        let mut mem = vec![init_memory(); 1];
        mem[0][CH_COMPUTE_AGE] = 1.0; // below equanimity_age_min=3.0
        let params = VoxelMemoryParams::default();
        let rng = vec![0.0f32; 1]; // would always resist if eligible
        let (mask, _) = compute_equanimity_mask(&states, &mem, &params, &rng);
        assert!(!mask[0], "Young COMPUTE should not resist");
    }

    #[test]
    fn test_mature_compute_resists() {
        let states = vec![COMPUTE; 1];
        let mut mem = vec![init_memory(); 1];
        mem[0][CH_COMPUTE_AGE] = 20.0; // well above equanimity_age_min
        mem[0][CH_MEMORY_STRENGTH] = 1.5;
        let params = VoxelMemoryParams::default();
        let rng = vec![0.0f32; 1]; // rng < p_resist guaranteed
        let (mask, saved) = compute_equanimity_mask(&states, &mem, &params, &rng);
        assert!(mask[0], "Mature COMPUTE should resist");
        assert_eq!(saved[0], COMPUTE);
    }
}
