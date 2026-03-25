//! Lucid Dreaming UI Server - WebSocket interface for Phase 13
//! Principle 5: Real-time interactive 3D visualization

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LucidInteraction {
    pub mode: String,
    pub cursor_x: f32, pub cursor_y: f32, pub cursor_z: f32,
    pub brush_radius: f32, pub brush_strength: f32,
    pub target_cell_type: Option<u8>,
    pub user_id: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemMetrics {
    pub self_recognition: f32,
    pub equanimity: f32,
    pub engram_hit_rate: f32,
    pub dark_energy_pressure: f32,
    pub temperature: f32,
    pub overfitting_index: f32,
    pub prediction_accuracy: f32,
    pub genesis_level: f32,
    pub active_agents: usize,
    pub fps: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CellUpdate {
    pub index: usize,
    pub x: usize, pub y: usize, pub z: usize,
    pub cell_type: u8,
    pub equanimity: f32,
    pub energy: f32,
    pub self_recognition: f32,
    pub highlight: u8,
}
