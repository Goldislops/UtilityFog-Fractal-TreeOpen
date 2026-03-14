//! Metrics computation: entropy, census, longevity stats.
//!
//! Computed at the end of each step, returned as StepMetrics.

use crate::memory::{COMPUTE, CH_COMPUTE_AGE};

/// Census of cell states.
#[derive(Debug, Clone, Default)]
pub struct Census {
    pub void_count: u32,
    pub structural: u32,
    pub compute: u32,
    pub energy: u32,
    pub sensor: u32,
    pub total: u32,
}

impl Census {
    pub fn from_states(states: &[u8]) -> Self {
        let mut c = Census { total: states.len() as u32, ..Default::default() };
        for &s in states {
            match s {
                0 => c.void_count += 1,
                1 => c.structural += 1,
                2 => c.compute += 1,
                3 => c.energy += 1,
                4 => c.sensor += 1,
                _ => c.void_count += 1,
            }
        }
        c
    }

    /// Compute Shannon entropy of state distribution (excluding VOID).
    pub fn entropy(&self) -> f32 {
        let non_void = self.structural + self.compute + self.energy + self.sensor;
        if non_void == 0 {
            return 0.0;
        }
        let n = non_void as f32;
        let mut h = 0.0f32;
        for &count in &[self.structural, self.compute, self.energy, self.sensor] {
            if count > 0 {
                let p = count as f32 / n;
                h -= p * p.ln();
            }
        }
        // Normalize to [0, 1] by dividing by ln(4)
        h / (4.0f32).ln()
    }

    /// State ratios as [structural, compute, energy, sensor] (fraction of non-void).
    pub fn ratios(&self) -> [f32; 4] {
        let non_void = (self.structural + self.compute + self.energy + self.sensor) as f32;
        if non_void == 0.0 {
            return [0.0; 4];
        }
        [
            self.structural as f32 / non_void,
            self.compute as f32 / non_void,
            self.energy as f32 / non_void,
            self.sensor as f32 / non_void,
        ]
    }
}

/// Comprehensive step metrics.
#[derive(Debug, Clone, Default)]
pub struct StepMetrics {
    pub generation: u32,
    pub entropy: f32,
    pub census: Census,
    pub compute_max_age: f32,
    pub compute_median_age: f32,
    pub compute_mean_age: f32,
    pub signal_active: u32,
    pub compassion_active: u32,
}

impl StepMetrics {
    /// Compute metrics from current lattice state.
    pub fn compute(
        states: &[u8],
        memory: &[[f32; 8]],
        generation: u32,
        signal_active: u32,
        compassion_active: u32,
    ) -> Self {
        let census = Census::from_states(states);
        let entropy = census.entropy();

        // COMPUTE age statistics
        let mut ages: Vec<f32> = Vec::new();
        for i in 0..states.len() {
            if states[i] == COMPUTE {
                ages.push(memory[i][CH_COMPUTE_AGE]);
            }
        }

        let (max_age, median_age, mean_age) = if ages.is_empty() {
            (0.0, 0.0, 0.0)
        } else {
            ages.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            let max = *ages.last().unwrap();
            let mean = ages.iter().sum::<f32>() / ages.len() as f32;
            let median = if ages.len() % 2 == 0 {
                (ages[ages.len() / 2 - 1] + ages[ages.len() / 2]) / 2.0
            } else {
                ages[ages.len() / 2]
            };
            (max, median, mean)
        };

        StepMetrics {
            generation,
            entropy,
            census,
            compute_max_age: max_age,
            compute_median_age: median_age,
            compute_mean_age: mean_age,
            signal_active,
            compassion_active,
        }
    }

    /// Serialize to JSON string for WASM export.
    pub fn to_json(&self) -> String {
        let ratios = self.census.ratios();
        format!(
            r#"{{"generation":{},"entropy":{:.4},"compute_max_age":{:.1},"compute_median_age":{:.1},"compute_mean_age":{:.1},"signal_active":{},"compassion_active":{},"structural":{},"compute":{},"energy":{},"sensor":{},"void":{},"ratios":[{:.4},{:.4},{:.4},{:.4}]}}"#,
            self.generation,
            self.entropy,
            self.compute_max_age,
            self.compute_median_age,
            self.compute_mean_age,
            self.signal_active,
            self.compassion_active,
            self.census.structural,
            self.census.compute,
            self.census.energy,
            self.census.sensor,
            self.census.void_count,
            ratios[0], ratios[1], ratios[2], ratios[3],
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_entropy_uniform() {
        // Equal distribution of 4 states -> entropy should be 1.0
        let states = vec![1u8, 2, 3, 4, 1, 2, 3, 4];
        let census = Census::from_states(&states);
        let e = census.entropy();
        assert!((e - 1.0).abs() < 0.01, "Uniform 4-state should have entropy ~1.0, got {}", e);
    }

    #[test]
    fn test_entropy_single_state() {
        let states = vec![1u8; 100];
        let census = Census::from_states(&states);
        let e = census.entropy();
        assert!(e < 0.01, "Single state should have entropy ~0.0");
    }

    #[test]
    fn test_metrics_json() {
        let states = vec![1u8, 2, 3, 4];
        let memory = vec![[0.0f32; 8]; 4];
        let m = StepMetrics::compute(&states, &memory, 42, 10, 2);
        let json = m.to_json();
        assert!(json.contains("\"generation\":42"));
        assert!(json.contains("\"signal_active\":10"));
    }
}
