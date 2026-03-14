//! Phase 6b: Sympathetic Joy (Mudita)
//!
//! R_joy = 1 + joy_beta * tanh((a_max_neighbor - equanimity_age_min) / joy_age_scale)
//! Cells near mature COMPUTE neighbors get memory_strength boost.
//! memory_strength capped at 2.0 (positive-sum: elders uplift neighborhood).

use crate::memory::{
    VoxelMemoryParams, CH_COMPUTE_AGE, CH_MEMORY_STRENGTH, COMPUTE,
};
use crate::filters;

/// Apply sympathetic joy: boost memory_strength for cells near mature COMPUTE.
/// Uses max_neighbor_value on compute_age field.
pub fn apply_sympathetic_joy(
    states: &[u8],
    memory: &mut [[f32; 8]],
    size: usize,
    params: &VoxelMemoryParams,
) {
    let n3 = size * size * size;

    // Extract compute_age field (0 for non-COMPUTE cells)
    let mut age_field = vec![0.0f32; n3];
    for i in 0..n3 {
        if states[i] == COMPUTE {
            age_field[i] = memory[i][CH_COMPUTE_AGE];
        }
    }

    // Find max neighbor age for each cell
    let max_ages = filters::max_neighbor_value(&age_field, size);

    let a_m = params.equanimity_age_min;
    let beta = params.joy_beta;
    let scale = params.joy_age_scale;

    for i in 0..n3 {
        let a_max = max_ages[i];
        if a_max > a_m {
            let r_joy = 1.0 + beta * ((a_max - a_m) / scale).tanh();
            memory[i][CH_MEMORY_STRENGTH] = (memory[i][CH_MEMORY_STRENGTH] * r_joy).min(2.0);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::init_memory;

    #[test]
    fn test_joy_boost_near_elder() {
        // 3x3x3 lattice, center is STRUCTURAL, one neighbor is mature COMPUTE
        let size = 3;
        let n3 = 27;
        let mut states = vec![0u8; n3]; // all VOID
        states[13] = 1; // center = STRUCTURAL
        states[14] = COMPUTE; // neighbor = COMPUTE
        let mut memory = vec![init_memory(); n3];
        memory[14][CH_COMPUTE_AGE] = 20.0; // mature
        let old_strength = memory[13][CH_MEMORY_STRENGTH];

        let params = VoxelMemoryParams::default();
        apply_sympathetic_joy(&states, &mut memory, size, &params);

        assert!(memory[13][CH_MEMORY_STRENGTH] > old_strength,
            "Cell near mature COMPUTE should get boosted");
    }

    #[test]
    fn test_joy_cap_at_2() {
        let size = 3;
        let n3 = 27;
        let mut states = vec![COMPUTE; n3];
        let mut memory = vec![init_memory(); n3];
        for i in 0..n3 {
            memory[i][CH_COMPUTE_AGE] = 100.0; // very mature
            memory[i][CH_MEMORY_STRENGTH] = 1.9;
        }
        let params = VoxelMemoryParams::default();
        apply_sympathetic_joy(&states, &mut memory, size, &params);
        for i in 0..n3 {
            assert!(memory[i][CH_MEMORY_STRENGTH] <= 2.0, "Should cap at 2.0");
        }
    }
}
