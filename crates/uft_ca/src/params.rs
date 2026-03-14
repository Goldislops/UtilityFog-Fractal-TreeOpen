//! Configuration structs for CA physics.
//!
//! Matches Python dataclasses: StochasticConfig, ContagionConfig, DecayConfig, CosmicGardenConfig.

use serde::Deserialize;
use crate::memory::VoxelMemoryParams;

/// Stochastic transition probabilities (matches Python StochasticConfig).
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct StochasticConfig {
    pub enabled: bool,
    pub baseline_transition_prob: f32,
    pub structural_to_energy_prob: f32,
    pub structural_to_sensor_prob: f32,
    pub compute_to_energy_prob: f32,
    pub compute_to_sensor_prob: f32,
    pub structural_to_void_decay_prob: f32,
    pub energy_to_void_decay_prob: f32,
    pub sensor_to_void_decay_prob: f32,
}

impl Default for StochasticConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            baseline_transition_prob: 0.08,
            structural_to_energy_prob: 0.08,
            structural_to_sensor_prob: 0.08,
            compute_to_energy_prob: 0.10,
            compute_to_sensor_prob: 0.10,
            structural_to_void_decay_prob: 0.005,  // CRITICAL: NOT 0.04
            energy_to_void_decay_prob: 0.005,
            sensor_to_void_decay_prob: 0.004,
        }
    }
}

/// Forward contagion thresholds (matches Python ContagionConfig).
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct ContagionConfig {
    pub enabled: bool,
    pub energy_neighbor_threshold: i32,
    pub sensor_neighbor_threshold: i32,
    pub structural_energy_conversion_prob: f32,
    pub structural_sensor_conversion_prob: f32,
    pub compute_energy_conversion_prob: f32,
    pub compute_sensor_conversion_prob: f32,
}

impl Default for ContagionConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            energy_neighbor_threshold: 4,
            sensor_neighbor_threshold: 4,
            structural_energy_conversion_prob: 0.40,
            structural_sensor_conversion_prob: 0.30,
            compute_energy_conversion_prob: 0.15,
            compute_sensor_conversion_prob: 0.25,
        }
    }
}

/// Inactivity decay config (matches Python DecayConfig).
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct DecayConfig {
    pub enabled: bool,
    pub inactivity_neighbor_threshold: i32,
    pub structural_inactive_steps_to_decay: i32,
}

impl Default for DecayConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            inactivity_neighbor_threshold: 1,
            structural_inactive_steps_to_decay: 6,
        }
    }
}

/// Cosmic Garden mechanisms (matches Python CosmicGardenConfig).
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct CosmicGardenConfig {
    pub cluster_coherence_threshold: i32,
    pub shield_strength: f32,
    pub cluster_shield_bonus: f32,
    pub halbach_recuperation_rate: f32,
    pub temporal_dilation: f32,
    pub bamboo_initial_growth: i32,
    pub bamboo_max_length: i32,
    pub bamboo_rebirth_age: i32,
    pub biofilm_leech_rate: f32,
    pub super_pod_threshold: i32,
    pub analogue_mutation: f32,
    pub otolith_vector: f32,
    pub damping_radius: i32,
}

impl Default for CosmicGardenConfig {
    fn default() -> Self {
        Self {
            cluster_coherence_threshold: 3,
            shield_strength: 0.85,
            cluster_shield_bonus: 0.15,
            halbach_recuperation_rate: 0.40,
            temporal_dilation: 0.15,
            bamboo_initial_growth: 100,
            bamboo_max_length: 500,
            bamboo_rebirth_age: 488,
            biofilm_leech_rate: 0.10,
            super_pod_threshold: 8,
            analogue_mutation: 0.03,
            otolith_vector: 0.05,
            damping_radius: 2,
        }
    }
}

/// Deterministic transition table: (current_state, neighbor_state) -> new_state.
/// Stored as a flat 5x5 array (current * 5 + trigger).
#[derive(Debug, Clone)]
pub struct TransitionTable {
    /// table[current * NUM_STATES + trigger] = Some(new_state) or None (no transition).
    pub table: [Option<u8>; 25],
}

impl Default for TransitionTable {
    fn default() -> Self {
        use crate::memory::{VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR};
        let mut t = [None; 25];
        // Default UF transitions from example.toml:
        // VOID + STRUCTURAL -> STRUCTURAL
        t[VOID as usize * 5 + STRUCTURAL as usize] = Some(STRUCTURAL);
        // STRUCTURAL + COMPUTE -> COMPUTE
        t[STRUCTURAL as usize * 5 + COMPUTE as usize] = Some(COMPUTE);
        // STRUCTURAL + ENERGY -> ENERGY
        t[STRUCTURAL as usize * 5 + ENERGY as usize] = Some(ENERGY);
        // COMPUTE + VOID -> VOID  (isolation death - but Equanimity overrides)
        // NOTE: Phase 4 changed COMPUTE(0)->COMPUTE, so this is NOT in default table
        t[COMPUTE as usize * 5 + VOID as usize] = None; // Phase 4: contemplative isolation
        // ENERGY + VOID -> VOID
        t[ENERGY as usize * 5 + VOID as usize] = Some(VOID);
        // SENSOR + VOID -> VOID
        t[SENSOR as usize * 5 + VOID as usize] = Some(VOID);
        Self { table: t }
    }
}

impl TransitionTable {
    /// Look up transition: given current state and dominant neighbor state.
    pub fn get(&self, current: u8, trigger: u8) -> Option<u8> {
        if current < 5 && trigger < 5 {
            self.table[current as usize * 5 + trigger as usize]
        } else {
            None
        }
    }
}

/// Full configuration aggregating all sub-configs.
#[derive(Debug, Clone)]
pub struct FullConfig {
    pub transition_table: TransitionTable,
    pub stochastic: StochasticConfig,
    pub contagion: ContagionConfig,
    pub decay: DecayConfig,
    pub cosmic: CosmicGardenConfig,
    pub memory_params: VoxelMemoryParams,
}

impl Default for FullConfig {
    fn default() -> Self {
        Self {
            transition_table: TransitionTable::default(),
            stochastic: StochasticConfig::default(),
            contagion: ContagionConfig::default(),
            decay: DecayConfig::default(),
            cosmic: CosmicGardenConfig::default(),
            memory_params: VoxelMemoryParams::default(),
        }
    }
}
