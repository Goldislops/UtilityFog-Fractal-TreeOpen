//! Phase 6a: Loving-Kindness (Metta)
//!
//! STRUCTURAL cells touching ENERGY accumulate warmth (Ch6).
//! Warmth provides a survival floor: floor = beta * (1 - exp(-n_E / 3))
//! which reduces void-decay probability.

use crate::memory::{
    VoxelMemoryParams, STRUCTURAL, ENERGY, NUM_STATES,
    CH_WARMTH,
};

/// Apply metta warmth accumulation.
/// STRUCTURAL cells adjacent to ENERGY cells gain warmth on channel 6.
/// Warmth decays each step and accumulates from nearby ENERGY.
pub fn apply_metta_warmth(
    states: &[u8],
    memory: &mut [[f32; 8]],
    neighbor_counts: &[[i16; NUM_STATES]],
    params: &VoxelMemoryParams,
) {
    let warmth_rate = params.metta_warmth_rate;
    let warmth_decay = params.metta_warmth_decay;

    for i in 0..states.len() {
        // Decay existing warmth for all cells
        memory[i][CH_WARMTH] *= warmth_decay;

        // Accumulate for STRUCTURAL touching ENERGY
        if states[i] == STRUCTURAL {
            let n_energy = neighbor_counts[i][ENERGY as usize] as f32;
            if n_energy > 0.0 {
                memory[i][CH_WARMTH] += warmth_rate * n_energy;
            }
        }
    }
}

/// Compute metta survival floor for a cell.
/// floor = beta * (1 - exp(-n_E / 3))
/// If floor > decay_prob, the cell survives (decay prob effectively zero).
pub fn metta_survival_floor(
    n_energy_neighbors: i16,
    params: &VoxelMemoryParams,
) -> f32 {
    let n_e = n_energy_neighbors as f32;
    params.metta_beta * (1.0 - (-n_e / 3.0).exp())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::init_memory;

    #[test]
    fn test_metta_floor_no_energy() {
        let params = VoxelMemoryParams::default();
        let floor = metta_survival_floor(0, &params);
        assert!(floor < 0.001, "No energy neighbors -> no floor");
    }

    #[test]
    fn test_metta_floor_with_energy() {
        let params = VoxelMemoryParams::default();
        let floor = metta_survival_floor(3, &params);
        // beta=0.25 * (1 - exp(-1)) = 0.25 * 0.632 = 0.158
        assert!(floor > 0.05, "Should have meaningful floor with 3 ENERGY neighbors");
        assert!(floor > 0.005, "Floor should exceed structural_to_void_decay_prob");
    }

    #[test]
    fn test_warmth_accumulation() {
        let states = vec![STRUCTURAL, ENERGY];
        let mut memory = vec![init_memory(); 2];
        let counts = vec![
            [0i16, 0, 0, 1, 0], // STRUCTURAL has 1 ENERGY neighbor
            [0, 1, 0, 0, 0],    // ENERGY has 1 STRUCTURAL neighbor
        ];
        let params = VoxelMemoryParams::default();
        apply_metta_warmth(&states, &mut memory, &counts, &params);
        assert!(memory[0][CH_WARMTH] > 0.0, "STRUCTURAL should gain warmth");
    }
}
