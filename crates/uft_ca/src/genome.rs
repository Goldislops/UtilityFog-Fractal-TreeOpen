//! Portable Genome Format v1 parser.
//!
//! Parses JSON genomes exported by scripts/portable_genome.py.
//! Extracts transition table, all config params, and optional epigenetic snapshot.

use serde::Deserialize;
use serde_json;
use std::collections::HashMap;

use crate::memory::{VoxelMemoryParams, VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR};
use crate::params::{
    FullConfig, TransitionTable,
};

/// Top-level genome JSON structure.
#[derive(Debug, Deserialize)]
pub struct PortableGenome {
    pub format: Option<GenomeFormat>,
    pub metadata: Option<serde_json::Value>,
    pub topology: Option<serde_json::Value>,
    pub transition_table: Option<GenomeTransitionTable>,
    pub stochastic: Option<GenomeStochastic>,
    pub contagion: Option<GenomeContagion>,
    pub decay: Option<GenomeDecay>,
    pub cosmic_garden: Option<GenomeCosmicGarden>,
    pub survival_mechanics: Option<GenomeSurvivalMechanics>,
    pub fitness: Option<serde_json::Value>,
    pub memory_layout: Option<serde_json::Value>,
    pub experimental: Option<serde_json::Value>,
    pub epigenetic_snapshot: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeFormat {
    pub version: Option<String>,
    pub schema: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeTransitionTable {
    pub transitions: Option<HashMap<String, HashMap<String, String>>>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeStochastic {
    pub enabled: Option<bool>,
    pub structural_to_energy_prob: Option<f32>,
    pub structural_to_sensor_prob: Option<f32>,
    pub compute_to_energy_prob: Option<f32>,
    pub compute_to_sensor_prob: Option<f32>,
    pub structural_to_void_decay_prob: Option<f32>,
    pub energy_to_void_decay_prob: Option<f32>,
    pub sensor_to_void_decay_prob: Option<f32>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeContagion {
    pub enabled: Option<bool>,
    pub energy_neighbor_threshold: Option<i32>,
    pub sensor_neighbor_threshold: Option<i32>,
    pub structural_energy_conversion_prob: Option<f32>,
    pub structural_sensor_conversion_prob: Option<f32>,
    pub compute_energy_conversion_prob: Option<f32>,
    pub compute_sensor_conversion_prob: Option<f32>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeDecay {
    pub enabled: Option<bool>,
    pub inactivity_neighbor_threshold: Option<i32>,
    pub structural_inactive_steps_to_decay: Option<i32>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeCosmicGarden {
    pub cluster_coherence_threshold: Option<i32>,
    pub shield_strength: Option<f32>,
    pub bamboo_rebirth_age: Option<i32>,
    pub biofilm_leech_rate: Option<f32>,
    pub super_pod_threshold: Option<i32>,
    pub analogue_mutation: Option<f32>,
}

#[derive(Debug, Deserialize)]
pub struct GenomeSurvivalMechanics {
    pub mamba_viking: Option<serde_json::Value>,
    pub void_sanctuary: Option<serde_json::Value>,
    pub epsilon_buffer: Option<serde_json::Value>,
    pub equanimity_shield: Option<serde_json::Value>,
    pub loving_kindness: Option<serde_json::Value>,
    pub sympathetic_joy: Option<serde_json::Value>,
    pub nervous_system: Option<serde_json::Value>,
}

/// Parse a genome JSON string into a FullConfig.
pub fn parse_genome(json_str: &str) -> Result<FullConfig, String> {
    let genome: PortableGenome = serde_json::from_str(json_str)
        .map_err(|e| format!("Failed to parse genome JSON: {}", e))?;

    let mut config = FullConfig::default();

    // Parse transition table
    if let Some(ref tt) = genome.transition_table {
        if let Some(ref transitions) = tt.transitions {
            config.transition_table = parse_transition_table(transitions);
        }
    }

    // Parse stochastic config
    if let Some(ref s) = genome.stochastic {
        if let Some(v) = s.enabled { config.stochastic.enabled = v; }
        if let Some(v) = s.structural_to_energy_prob { config.stochastic.structural_to_energy_prob = v; }
        if let Some(v) = s.structural_to_sensor_prob { config.stochastic.structural_to_sensor_prob = v; }
        if let Some(v) = s.compute_to_energy_prob { config.stochastic.compute_to_energy_prob = v; }
        if let Some(v) = s.compute_to_sensor_prob { config.stochastic.compute_to_sensor_prob = v; }
        if let Some(v) = s.structural_to_void_decay_prob { config.stochastic.structural_to_void_decay_prob = v; }
        if let Some(v) = s.energy_to_void_decay_prob { config.stochastic.energy_to_void_decay_prob = v; }
        if let Some(v) = s.sensor_to_void_decay_prob { config.stochastic.sensor_to_void_decay_prob = v; }
    }

    // Parse contagion config
    if let Some(ref c) = genome.contagion {
        if let Some(v) = c.enabled { config.contagion.enabled = v; }
        if let Some(v) = c.energy_neighbor_threshold { config.contagion.energy_neighbor_threshold = v; }
        if let Some(v) = c.sensor_neighbor_threshold { config.contagion.sensor_neighbor_threshold = v; }
        if let Some(v) = c.structural_energy_conversion_prob { config.contagion.structural_energy_conversion_prob = v; }
        if let Some(v) = c.structural_sensor_conversion_prob { config.contagion.structural_sensor_conversion_prob = v; }
        if let Some(v) = c.compute_energy_conversion_prob { config.contagion.compute_energy_conversion_prob = v; }
        if let Some(v) = c.compute_sensor_conversion_prob { config.contagion.compute_sensor_conversion_prob = v; }
    }

    // Parse decay config
    if let Some(ref d) = genome.decay {
        if let Some(v) = d.enabled { config.decay.enabled = v; }
        if let Some(v) = d.inactivity_neighbor_threshold { config.decay.inactivity_neighbor_threshold = v; }
        if let Some(v) = d.structural_inactive_steps_to_decay { config.decay.structural_inactive_steps_to_decay = v; }
    }

    // Parse cosmic garden
    if let Some(ref cg) = genome.cosmic_garden {
        if let Some(v) = cg.cluster_coherence_threshold { config.cosmic.cluster_coherence_threshold = v; }
        if let Some(v) = cg.shield_strength { config.cosmic.shield_strength = v; }
        if let Some(v) = cg.bamboo_rebirth_age { config.cosmic.bamboo_rebirth_age = v; }
        if let Some(v) = cg.biofilm_leech_rate { config.cosmic.biofilm_leech_rate = v; }
        if let Some(v) = cg.super_pod_threshold { config.cosmic.super_pod_threshold = v; }
        if let Some(v) = cg.analogue_mutation { config.cosmic.analogue_mutation = v; }
    }

    // Parse survival mechanics (deep nested values)
    if let Some(ref sm) = genome.survival_mechanics {
        parse_survival_mechanics(sm, &mut config.memory_params);
    }

    Ok(config)
}

fn state_name_to_u8(name: &str) -> Option<u8> {
    match name.to_uppercase().as_str() {
        "VOID" => Some(VOID),
        "STRUCTURAL" => Some(STRUCTURAL),
        "COMPUTE" => Some(COMPUTE),
        "ENERGY" => Some(ENERGY),
        "SENSOR" => Some(SENSOR),
        _ => None,
    }
}

fn parse_transition_table(transitions: &HashMap<String, HashMap<String, String>>) -> TransitionTable {
    let mut tt = TransitionTable { table: [None; 25] };
    for (current_name, triggers) in transitions {
        if let Some(current) = state_name_to_u8(current_name) {
            for (trigger_name, result_name) in triggers {
                if let (Some(trigger), Some(result)) = (state_name_to_u8(trigger_name), state_name_to_u8(result_name)) {
                    tt.table[current as usize * 5 + trigger as usize] = Some(result);
                }
            }
        }
    }
    tt
}

fn parse_survival_mechanics(sm: &GenomeSurvivalMechanics, params: &mut VoxelMemoryParams) {
    // Equanimity Shield
    if let Some(ref eq) = sm.equanimity_shield {
        if let Some(v) = eq.get("equanimity_age_min").and_then(|v| v.as_f64()) { params.equanimity_age_min = v as f32; }
        if let Some(v) = eq.get("equanimity_p_max").and_then(|v| v.as_f64()) { params.equanimity_p_max = v as f32; }
        if let Some(v) = eq.get("equanimity_tau").and_then(|v| v.as_f64()) { params.equanimity_tau = v as f32; }
        if let Some(v) = eq.get("equanimity_gamma").and_then(|v| v.as_f64()) { params.equanimity_gamma = v as f32; }
    }

    // Loving-Kindness
    if let Some(ref lk) = sm.loving_kindness {
        if let Some(v) = lk.get("metta_beta").and_then(|v| v.as_f64()) { params.metta_beta = v as f32; }
        if let Some(v) = lk.get("warmth_rate").and_then(|v| v.as_f64()) { params.metta_warmth_rate = v as f32; }
        if let Some(v) = lk.get("warmth_decay").and_then(|v| v.as_f64()) { params.metta_warmth_decay = v as f32; }
    }

    // Sympathetic Joy
    if let Some(ref sj) = sm.sympathetic_joy {
        if let Some(v) = sj.get("joy_beta").and_then(|v| v.as_f64()) { params.joy_beta = v as f32; }
        if let Some(v) = sj.get("joy_age_scale").and_then(|v| v.as_f64()) { params.joy_age_scale = v as f32; }
    }

    // Nervous System
    if let Some(ref ns) = sm.nervous_system {
        if let Some(v) = ns.get("mindsight_radius").and_then(|v| v.as_i64()) { params.mindsight_radius = v as i32; }
        if let Some(v) = ns.get("mindsight_s_max").and_then(|v| v.as_f64()) { params.mindsight_s_max = v as f32; }
        if let Some(v) = ns.get("mindsight_sigma_opp").and_then(|v| v.as_f64()) { params.mindsight_sigma_opp = v as f32; }
        if let Some(v) = ns.get("mindsight_sigma_dis").and_then(|v| v.as_f64()) { params.mindsight_sigma_dis = v as f32; }
        if let Some(v) = ns.get("mindsight_threshold").and_then(|v| v.as_f64()) { params.mindsight_threshold = v as f32; }
        if let Some(v) = ns.get("mycelial_k_iter").and_then(|v| v.as_i64()) { params.mycelial_k_iter = v as i32; }
        if let Some(v) = ns.get("compassion_beta").and_then(|v| v.as_f64()) { params.compassion_beta = v as f32; }
        if let Some(v) = ns.get("compassion_gamma").and_then(|v| v.as_f64()) { params.compassion_gamma = v as f32; }
        if let Some(v) = ns.get("signal_interval").and_then(|v| v.as_i64()) { params.signal_interval = v as i32; }
    }

    // Mamba-Viking
    if let Some(ref mv) = sm.mamba_viking {
        if let Some(v) = mv.get("mamba_delta_threshold").and_then(|v| v.as_f64()) { params.mamba_delta_threshold = v as f32; }
        if let Some(v) = mv.get("mamba_tau_base").and_then(|v| v.as_f64()) { params.mamba_tau_base = v as f32; }
        if let Some(v) = mv.get("mamba_tau_scale").and_then(|v| v.as_f64()) { params.mamba_tau_scale = v as f32; }
    }

    // Void Sanctuary
    if let Some(ref vs) = sm.void_sanctuary {
        if let Some(v) = vs.get("void_sanctuary_multiplier").and_then(|v| v.as_f64()) { params.void_sanctuary_multiplier = v as f32; }
    }

    // Epsilon Buffer
    if let Some(ref eb) = sm.epsilon_buffer {
        if let Some(v) = eb.get("epsilon_p_max").and_then(|v| v.as_f64()) { params.epsilon_p_max = v as f32; }
        if let Some(v) = eb.get("epsilon_buffer").and_then(|v| v.as_f64()) { params.epsilon_buffer = v as f32; }
        if let Some(v) = eb.get("epsilon_n_c").and_then(|v| v.as_i64()) { params.epsilon_n_c = v as i32; }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_state_name_to_u8() {
        assert_eq!(state_name_to_u8("VOID"), Some(0));
        assert_eq!(state_name_to_u8("COMPUTE"), Some(2));
        assert_eq!(state_name_to_u8("Sensor"), Some(4));
        assert_eq!(state_name_to_u8("UNKNOWN"), None);
    }

    #[test]
    fn test_parse_minimal_genome() {
        let json = r#"{"transition_table": {"transitions": {"VOID": {"STRUCTURAL": "STRUCTURAL"}}}, "stochastic": {"enabled": true, "structural_to_void_decay_prob": 0.005}}"#;
        let config = parse_genome(json).unwrap();
        assert_eq!(config.transition_table.get(0, 1), Some(1)); // VOID + STRUCTURAL -> STRUCTURAL
        assert_eq!(config.stochastic.structural_to_void_decay_prob, 0.005);
    }
}
