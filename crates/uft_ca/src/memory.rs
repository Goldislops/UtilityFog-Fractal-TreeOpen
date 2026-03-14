//! Memory channel constants and expanded VoxelMemoryParams for Phase 10.
//!
//! 8-channel memory grid matching Python's continuous_evolution_ca.py.

use serde::Deserialize;

// ---- Memory channel indices (matching Python's index-based access) ----
pub const CH_COMPUTE_AGE: usize = 0;
pub const CH_STRUCTURAL_AGE: usize = 1;
pub const CH_MEMORY_STRENGTH: usize = 2;
pub const CH_ENERGY_RESERVE: usize = 3;
pub const CH_LAST_ACTIVE_GEN: usize = 4;
pub const CH_SIGNAL_FIELD: usize = 5;
pub const CH_WARMTH: usize = 6;
pub const CH_COMPASSION_COOLDOWN: usize = 7;
pub const MEMORY_CHANNELS: usize = 8;

// ---- Cell state constants ----
pub const VOID: u8 = 0;
pub const STRUCTURAL: u8 = 1;
pub const COMPUTE: u8 = 2;
pub const ENERGY: u8 = 3;
pub const SENSOR: u8 = 4;
pub const NUM_STATES: usize = 5;

/// Expanded VoxelMemoryParams - 64 fields covering Phase 3 through 6c.
/// All defaults match Python exactly.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct VoxelMemoryParams {
    // Phase 1+ baseline
    pub age_young_threshold: i32,
    pub age_mature_threshold: i32,
    pub resistance_max: f32,

    // Phase 1+: Reverse contagion
    pub reverse_contagion_threshold: i32,
    pub reverse_contagion_base_prob: f32,
    pub reverse_contagion_boost: f32,
    pub energy_to_compute_prob: f32,

    // Phase 1+: Forward contagion mitigation
    pub forward_contagion_threshold: i32,
    pub forward_contagion_penalty: f32,
    pub forward_contagion_floor: f32,

    // Phase 1+: RAG memory
    pub rag_query_radius: i32,
    pub rag_memory_decay: f32,
    pub rag_reinforcement_boost: f32,
    pub rag_entropy_weight: f32,

    // Phase 3: Mamba-Viking memory dynamics
    pub mamba_delta_threshold: f32,
    pub mamba_tau_base: f32,
    pub mamba_tau_scale: f32,
    pub mamba_boost_base: f32,
    pub mamba_boost_gain: f32,
    pub mamba_age_stability_gain: f32,
    pub mamba_high_delta_floor: f32,

    // Phase 3: Void Sanctuary Shield
    pub void_sanctuary_multiplier: f32,

    // Phase 3: Epsilon Buffer (Dimensional Regularization)
    pub epsilon_p_max: f32,
    pub epsilon_buffer: f32,
    pub epsilon_n_c: i32,
    pub epsilon_tau: f32,

    // Phase 4: Equanimity Shield
    pub equanimity_age_min: f32,
    pub equanimity_p_max: f32,
    pub equanimity_tau: f32,
    pub equanimity_gamma: f32,

    // Phase 6a: Loving-Kindness (metta)
    pub metta_beta: f32,
    pub metta_warmth_rate: f32,
    pub metta_warmth_decay: f32,

    // Phase 6b: Sympathetic Joy (mudita)
    pub joy_beta: f32,
    pub joy_age_scale: f32,

    // Phase 6c: Mindsight + Mycelial + Compassion
    pub mindsight_s_max: f32,
    pub mindsight_sigma_opp: f32,
    pub mindsight_sigma_dis: f32,
    pub mindsight_threshold: f32,
    pub mindsight_radius: i32,
    pub mycelial_k_iter: i32,
    pub mycelial_lambda_distress: f32,
    pub mycelial_lambda_opportunity: f32,
    pub compassion_beta: f32,
    pub compassion_gamma: f32,
    pub compassion_distance_scale: f32,
    pub compassion_age_scale_min: f32,
    pub compassion_age_scale_factor: f32,

    // Phase 6 signal interval
    pub signal_interval: i32,
}

impl Default for VoxelMemoryParams {
    fn default() -> Self {
        Self {
            // Phase 1+
            age_young_threshold: 8,
            age_mature_threshold: 40,
            resistance_max: 0.82,
            // Reverse contagion
            reverse_contagion_threshold: 4,
            reverse_contagion_base_prob: 0.20,
            reverse_contagion_boost: 0.06,
            energy_to_compute_prob: 0.20,
            // Forward contagion mitigation
            forward_contagion_threshold: 5,
            forward_contagion_penalty: 0.18,
            forward_contagion_floor: 0.40,
            // RAG
            rag_query_radius: 3,
            rag_memory_decay: 0.015,
            rag_reinforcement_boost: 1.50,
            rag_entropy_weight: 0.18,
            // Mamba-Viking
            mamba_delta_threshold: 0.12,
            mamba_tau_base: 5.0,
            mamba_tau_scale: 12.0,
            mamba_boost_base: 0.015,
            mamba_boost_gain: 0.045,
            mamba_age_stability_gain: 0.03,
            mamba_high_delta_floor: 1.15,
            // Void Sanctuary
            void_sanctuary_multiplier: 50.0,
            // Epsilon Buffer
            epsilon_p_max: 0.943,
            epsilon_buffer: 0.08,
            epsilon_n_c: 20,
            epsilon_tau: 3.0,
            // Equanimity Shield
            equanimity_age_min: 3.0,
            equanimity_p_max: 0.85,
            equanimity_tau: 5.0,
            equanimity_gamma: 0.5,
            // Metta
            metta_beta: 0.25,
            metta_warmth_rate: 0.02,
            metta_warmth_decay: 0.95,
            // Mudita
            joy_beta: 0.35,
            joy_age_scale: 15.0,
            // Nervous system
            mindsight_s_max: 1.0,
            mindsight_sigma_opp: 0.15,
            mindsight_sigma_dis: 0.10,
            mindsight_threshold: 0.3,
            mindsight_radius: 12,
            mycelial_k_iter: 3,
            mycelial_lambda_distress: 12.0,
            mycelial_lambda_opportunity: 8.0,
            compassion_beta: 0.50,
            compassion_gamma: 0.20,
            compassion_distance_scale: 15.0,
            compassion_age_scale_min: 30.0,
            compassion_age_scale_factor: 1.5,
            // Signal
            signal_interval: 10,
        }
    }
}

/// Initialize an 8-channel memory array for a single voxel.
/// Ch2 (memory_strength) = 1.0, Ch3 (energy_reserve) = 1.0, rest = 0.
pub fn init_memory() -> [f32; MEMORY_CHANNELS] {
    let mut m = [0.0f32; MEMORY_CHANNELS];
    m[CH_MEMORY_STRENGTH] = 1.0;
    m[CH_ENERGY_RESERVE] = 1.0;
    m
}
