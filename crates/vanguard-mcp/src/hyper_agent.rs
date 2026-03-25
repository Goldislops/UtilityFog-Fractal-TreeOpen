//! Hyper-Agent Plasticity - Self-Modifying Learning
//! Phase 13 Principle 3: Agents rewrite their own reward functions

use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct HyperAgent {
    pub id: u32,
    pub plasticity_rate: f32,
    pub attention_sparsity: f32,
    pub reward_weights: [f32; 8],
    pub genesis_level: u8,
    pub parent_id: Option<u32>,
    pub self_recognition: f32,
    pub total_tasks: u64,
    pub successful_tasks: u64,
}

impl HyperAgent {
    pub fn new(id: u32) -> Self {
        Self {
            id, plasticity_rate: 0.5, attention_sparsity: 0.25,
            reward_weights: [0.125; 8], genesis_level: 0,
            parent_id: None, self_recognition: 0.0,
            total_tasks: 0, successful_tasks: 0,
        }
    }

    pub fn fitness(&self) -> f32 {
        if self.total_tasks == 0 { return 0.0; }
        self.successful_tasks as f32 / self.total_tasks as f32
    }

    /// Self-modify reward function based on performance
    pub fn adapt(&mut self, task_success: bool, hebbian_signal: &[f32; 8]) {
        self.total_tasks += 1;
        if task_success { self.successful_tasks += 1; }

        if self.self_recognition > 0.49 {
            self.plasticity_rate *= 1.01;  // Learning effectively
            self.genesis_level = self.genesis_level.saturating_add(1);
        } else {
            self.plasticity_rate *= 0.99;  // Explore different strategies
        }
        self.plasticity_rate = self.plasticity_rate.clamp(0.01, 2.0);

        for i in 0..8 {
            if hebbian_signal[i].abs() > self.attention_sparsity {
                let delta = self.plasticity_rate * hebbian_signal[i];
                self.reward_weights[i] = (self.reward_weights[i] + delta).clamp(-1.0, 1.0);
            }
        }
    }

    /// Spawn a child agent with mutated parameters (Genesis)
    pub fn spawn(&self, child_id: u32) -> HyperAgent {
        let mut child = self.clone();
        child.id = child_id;
        child.parent_id = Some(self.id);
        child.plasticity_rate *= 1.0 + (rand::random::<f32>() - 0.5) * 0.1;
        child.genesis_level = 0;
        child.total_tasks = 0;
        child.successful_tasks = 0;
        child
    }
}

pub struct HyperAgentManager {
    agents: Vec<HyperAgent>,
    next_id: u32,
}

impl HyperAgentManager {
    pub fn new() -> Self {
        let agents: Vec<HyperAgent> = (0..1725).map(|i| HyperAgent::new(i)).collect();
        Self { agents, next_id: 1725 }
    }

    pub async fn step(&self, _inputs: HashMap<u32, [f32; 8]>, _timestep: u64) {
        // Would process all agents in parallel
    }

    pub async fn get_stats(&self) -> HyperAgentStats {
        let avg_sr = self.agents.iter().map(|a| a.self_recognition).sum::<f32>()
            / self.agents.len().max(1) as f32;
        HyperAgentStats {
            population_size: self.agents.len(),
            avg_self_recognition: avg_sr,
            max_genesis_level: self.agents.iter().map(|a| a.genesis_level).max().unwrap_or(0),
        }
    }
}

pub struct HyperAgentStats {
    pub population_size: usize,
    pub avg_self_recognition: f32,
    pub max_genesis_level: u8,
}
