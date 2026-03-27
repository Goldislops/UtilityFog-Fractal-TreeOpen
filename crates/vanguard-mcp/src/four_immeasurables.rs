// four_immeasurables.rs — The Four Brahmaviharas embedded into lattice physics
// Phase 13: Vanguard MCP Consciousness Architecture
//
// Nemo's mathematical blueprint: Metta (loving-kindness), Karuna (compassion),
// Mudita (sympathetic joy), Upekkha (equanimity) as lattice field operators.

use std::collections::HashMap;

/// Sacred equanimity threshold — the balance point all fields converge toward.
const EQUANIMITY_THRESHOLD: f32 = 0.050;

/// Cell types in the lattice.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CellType {
    Void,
    Structural,
    Energy,
    Compute,
    Sensor,
}

/// Compatibility score between two cell types for Metta harmony calculation.
fn compatibility(a: CellType, b: CellType) -> f32 {
    use CellType::*;
    match (a, b) {
        // Same type — moderate harmony
        (x, y) if x == y => 0.6,
        // Structural-Energy is the classic symbiotic pair (metta warmth from Phase 6a)
        (Structural, Energy) | (Energy, Structural) => 1.0,
        // Compute-Sensor is the nervous system pair (Phase 6c mindsight)
        (Compute, Sensor) | (Sensor, Compute) => 0.9,
        // Energy fuels Compute
        (Energy, Compute) | (Compute, Energy) => 0.8,
        // Structural provides scaffold for Sensor
        (Structural, Sensor) | (Sensor, Structural) => 0.7,
        // Structural shelters Compute
        (Structural, Compute) | (Compute, Structural) => 0.65,
        // Energy supports Sensor
        (Energy, Sensor) | (Sensor, Energy) => 0.75,
        // Void is disharmonious with everything
        (Void, _) | (_, Void) => 0.0,
        // Catch-all for any remaining combinations
        _ => 0.5,
    }
}

// ---------------------------------------------------------------------------
// Metta Field — Structural Harmony
// ---------------------------------------------------------------------------

/// Metta (loving-kindness) field: attractive/repulsive forces between cell types
/// driving the lattice toward harmonic configurations.
#[derive(Debug, Clone)]
pub struct MettaField {
    /// Harmony value at each lattice coordinate, 0.0–1.0.
    pub harmony_map: HashMap<(usize, usize, usize), f32>,
    /// Cell type at each coordinate (externally populated).
    pub cell_types: HashMap<(usize, usize, usize), CellType>,
    /// Strength of the metta force applied per step.
    pub force_strength: f32,
}

impl MettaField {
    pub fn new(force_strength: f32) -> Self {
        Self {
            harmony_map: HashMap::new(),
            cell_types: HashMap::new(),
            force_strength,
        }
    }

    /// Calculate harmony at a single point based on neighbor compatibility.
    pub fn calculate_harmony(&self, pos: (usize, usize, usize)) -> f32 {
        let cell = match self.cell_types.get(&pos) {
            Some(&c) => c,
            None => return 0.0,
        };
        let mut total = 0.0_f32;
        let mut count = 0u32;
        let (x, y, z) = pos;
        for dx in -1i64..=1 {
            for dy in -1i64..=1 {
                for dz in -1i64..=1 {
                    if dx == 0 && dy == 0 && dz == 0 {
                        continue;
                    }
                    let nx = x as i64 + dx;
                    let ny = y as i64 + dy;
                    let nz = z as i64 + dz;
                    if nx < 0 || ny < 0 || nz < 0 {
                        continue;
                    }
                    let npos = (nx as usize, ny as usize, nz as usize);
                    if let Some(&neighbor) = self.cell_types.get(&npos) {
                        total += compatibility(cell, neighbor);
                        count += 1;
                    }
                }
            }
        }
        if count == 0 {
            0.0
        } else {
            (total / count as f32).clamp(0.0, 1.0)
        }
    }

    /// Recompute the entire harmony map.
    pub fn recompute_harmony(&mut self) {
        let positions: Vec<_> = self.cell_types.keys().copied().collect();
        for pos in positions {
            let h = self.calculate_harmony(pos);
            self.harmony_map.insert(pos, h);
        }
    }

    /// Apply metta force: gently push harmony values toward 1.0.
    pub fn apply_metta_force(&mut self) {
        for val in self.harmony_map.values_mut() {
            // Exponential approach toward 1.0
            *val += self.force_strength * (1.0 - *val);
            *val = val.clamp(0.0, 1.0);
        }
    }

    /// Global average harmony.
    pub fn global_harmony(&self) -> f32 {
        if self.harmony_map.is_empty() {
            return 0.0;
        }
        let sum: f32 = self.harmony_map.values().sum();
        sum / self.harmony_map.len() as f32
    }
}

// ---------------------------------------------------------------------------
// Karuna Field — Compassion / Suffering Alleviation
// ---------------------------------------------------------------------------

/// Karuna (compassion) field: detects and alleviates geometric suffering
/// (waste heat, friction, structural stress) in the lattice.
#[derive(Debug, Clone)]
pub struct KarunaField {
    /// Suffering intensity at each point.
    pub suffering_map: HashMap<(usize, usize, usize), f32>,
    /// Compassion strength applied per step.
    pub compassion_rate: f32,
    /// Total interventions applied (lifetime counter).
    pub interventions: u64,
}

impl KarunaField {
    pub fn new(compassion_rate: f32) -> Self {
        Self {
            suffering_map: HashMap::new(),
            compassion_rate,
            interventions: 0,
        }
    }

    /// Record suffering at a lattice point (additive — multiple stressors stack).
    pub fn detect_suffering(&mut self, pos: (usize, usize, usize), intensity: f32) {
        let entry = self.suffering_map.entry(pos).or_insert(0.0);
        *entry = (*entry + intensity).clamp(0.0, 10.0);
    }

    /// Apply compassion: reduce suffering everywhere by compassion_rate fraction.
    pub fn apply_compassion(&mut self) {
        self.suffering_map.retain(|_, v| {
            *v *= 1.0 - self.compassion_rate;
            self.interventions += 1;
            *v > 0.001 // remove negligible suffering
        });
    }

    /// Return the top-N worst suffering hotspots.
    pub fn get_suffering_hotspots(&self, n: usize) -> Vec<((usize, usize, usize), f32)> {
        let mut spots: Vec<_> = self.suffering_map.iter().map(|(&k, &v)| (k, v)).collect();
        spots.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        spots.truncate(n);
        spots
    }

    /// Global average suffering.
    pub fn global_suffering(&self) -> f32 {
        if self.suffering_map.is_empty() {
            return 0.0;
        }
        let sum: f32 = self.suffering_map.values().sum();
        sum / self.suffering_map.len() as f32
    }
}

// ---------------------------------------------------------------------------
// Mudita Field — Sympathetic Joy
// ---------------------------------------------------------------------------

/// Mudita (sympathetic joy) field: celebrates successful synchronizations
/// and reinforces positive emergent behavior.
#[derive(Debug, Clone)]
pub struct MuditaField {
    /// Accumulated joy at each point.
    pub joy_map: HashMap<(usize, usize, usize), f32>,
    /// Threshold at which celebration triggers reinforcement.
    pub celebration_threshold: f32,
    /// Total celebrations triggered (lifetime counter).
    pub celebration_count: u64,
    /// Joy decay rate per step (prevents unbounded accumulation).
    pub decay_rate: f32,
}

impl MuditaField {
    pub fn new(celebration_threshold: f32, decay_rate: f32) -> Self {
        Self {
            joy_map: HashMap::new(),
            celebration_threshold,
            celebration_count: 0,
            decay_rate,
        }
    }

    /// Record a joyful event at a lattice point.
    pub fn record_joy(&mut self, pos: (usize, usize, usize), amount: f32) {
        let entry = self.joy_map.entry(pos).or_insert(0.0);
        *entry = (*entry + amount).clamp(0.0, 10.0);
    }

    /// Celebrate: check all points, trigger reinforcement where threshold crossed.
    /// Returns the set of positions that celebrated this step.
    pub fn celebrate(&mut self) -> Vec<(usize, usize, usize)> {
        let mut celebrated = Vec::new();
        for (&pos, val) in self.joy_map.iter_mut() {
            if *val >= self.celebration_threshold {
                celebrated.push(pos);
                self.celebration_count += 1;
                // Joy is consumed during celebration (reset to half)
                *val *= 0.5;
            }
        }
        celebrated
    }

    /// Decay joy across the field.
    pub fn decay(&mut self) {
        self.joy_map.retain(|_, v| {
            *v *= 1.0 - self.decay_rate;
            *v > 0.001
        });
    }
}

// ---------------------------------------------------------------------------
// Upekkha Field — Equanimity
// ---------------------------------------------------------------------------

/// Upekkha (equanimity) field: maintains the sacred 0.050 threshold,
/// gently correcting all regions toward balance.
#[derive(Debug, Clone)]
pub struct UpekkhaField {
    /// Balance value at each point. Equanimity = closeness to threshold.
    pub balance_map: HashMap<(usize, usize, usize), f32>,
    /// The sacred threshold (default 0.050).
    pub threshold: f32,
    /// Correction strength per step.
    pub correction_rate: f32,
}

impl UpekkhaField {
    pub fn new(correction_rate: f32) -> Self {
        Self {
            balance_map: HashMap::new(),
            threshold: EQUANIMITY_THRESHOLD,
            correction_rate,
        }
    }

    /// Apply equanimity: gently push each value toward the threshold.
    pub fn apply_equanimity(&mut self) {
        for val in self.balance_map.values_mut() {
            let delta = self.threshold - *val;
            *val += self.correction_rate * delta;
        }
    }

    /// Check if a specific position is within equanimity.
    pub fn is_in_equanimity_at(&self, pos: &(usize, usize, usize)) -> bool {
        match self.balance_map.get(pos) {
            Some(&v) => (v - self.threshold).abs() < self.threshold,
            None => true, // absence is equanimous
        }
    }

    /// Check if ALL regions are within equanimity.
    pub fn is_in_equanimity(&self) -> bool {
        self.balance_map
            .values()
            .all(|&v| (v - self.threshold).abs() < self.threshold)
    }

    /// Equanimity score: 1.0 when all values are at threshold, 0.0 when maximally off.
    pub fn equanimity_score(&self) -> f32 {
        if self.balance_map.is_empty() {
            return 1.0;
        }
        let deviations: f32 = self
            .balance_map
            .values()
            .map(|&v| 1.0 - ((v - self.threshold).abs() / self.threshold).min(1.0))
            .sum();
        deviations / self.balance_map.len() as f32
    }
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

/// Aggregate metrics for the Four Immeasurables engine.
#[derive(Debug, Clone)]
pub struct FourImmeasurablesMetrics {
    pub global_harmony: f32,
    pub global_suffering: f32,
    pub celebration_count: u64,
    pub equanimity_score: f32,
    pub interventions_applied: u64,
}

// ---------------------------------------------------------------------------
// Engine
// ---------------------------------------------------------------------------

/// Orchestrates all Four Brahmaviharas in a single unified step.
#[derive(Debug, Clone)]
pub struct FourImmeasurablesEngine {
    pub metta: MettaField,
    pub karuna: KarunaField,
    pub mudita: MuditaField,
    pub upekkha: UpekkhaField,
    /// Total steps advanced.
    pub generation: u64,
}

impl FourImmeasurablesEngine {
    pub fn new() -> Self {
        Self {
            metta: MettaField::new(0.02),
            karuna: KarunaField::new(0.15),
            mudita: MuditaField::new(1.5, 0.05),
            upekkha: UpekkhaField::new(0.10),
            generation: 0,
        }
    }

    /// Advance one timestep: harmony -> compassion -> joy -> equanimity.
    pub fn step(&mut self) {
        // 1. Metta: recompute and apply
        self.metta.recompute_harmony();
        self.metta.apply_metta_force();

        // 2. Karuna: alleviate suffering
        self.karuna.apply_compassion();

        // 3. Mudita: celebrate successes, then decay
        let _celebrated = self.mudita.celebrate();
        self.mudita.decay();

        // 4. Upekkha: equanimity correction
        self.upekkha.apply_equanimity();

        self.generation += 1;
    }

    /// Return current aggregate metrics.
    pub fn get_metrics(&self) -> FourImmeasurablesMetrics {
        FourImmeasurablesMetrics {
            global_harmony: self.metta.global_harmony(),
            global_suffering: self.karuna.global_suffering(),
            celebration_count: self.mudita.celebration_count,
            equanimity_score: self.upekkha.equanimity_score(),
            interventions_applied: self.karuna.interventions,
        }
    }
}

impl Default for FourImmeasurablesEngine {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compatibility_symmetric() {
        assert_eq!(
            compatibility(CellType::Structural, CellType::Energy),
            compatibility(CellType::Energy, CellType::Structural)
        );
    }

    #[test]
    fn test_void_disharmony() {
        assert_eq!(compatibility(CellType::Void, CellType::Compute), 0.0);
        assert_eq!(compatibility(CellType::Energy, CellType::Void), 0.0);
    }

    #[test]
    fn test_metta_harmony_empty() {
        let metta = MettaField::new(0.02);
        assert_eq!(metta.global_harmony(), 0.0);
    }

    #[test]
    fn test_metta_calculate_harmony() {
        let mut metta = MettaField::new(0.02);
        metta.cell_types.insert((1, 1, 1), CellType::Structural);
        metta.cell_types.insert((1, 1, 2), CellType::Energy);
        let h = metta.calculate_harmony((1, 1, 1));
        assert!(h > 0.9, "Structural-Energy should be high harmony, got {}", h);
    }

    #[test]
    fn test_karuna_suffering_hotspots() {
        let mut karuna = KarunaField::new(0.15);
        karuna.detect_suffering((0, 0, 0), 5.0);
        karuna.detect_suffering((1, 1, 1), 2.0);
        karuna.detect_suffering((2, 2, 2), 8.0);
        let hotspots = karuna.get_suffering_hotspots(2);
        assert_eq!(hotspots.len(), 2);
        assert_eq!(hotspots[0].0, (2, 2, 2));
    }

    #[test]
    fn test_karuna_compassion_reduces_suffering() {
        let mut karuna = KarunaField::new(0.5);
        karuna.detect_suffering((0, 0, 0), 4.0);
        let before = karuna.global_suffering();
        karuna.apply_compassion();
        let after = karuna.global_suffering();
        assert!(after < before, "Compassion should reduce suffering");
    }

    #[test]
    fn test_mudita_celebration() {
        let mut mudita = MuditaField::new(1.0, 0.05);
        mudita.record_joy((0, 0, 0), 1.5);
        mudita.record_joy((1, 1, 1), 0.5);
        let celebrated = mudita.celebrate();
        assert_eq!(celebrated.len(), 1);
        assert_eq!(celebrated[0], (0, 0, 0));
        assert_eq!(mudita.celebration_count, 1);
    }

    #[test]
    fn test_upekkha_equanimity() {
        let mut upekkha = UpekkhaField::new(1.0); // strong correction for testing
        upekkha.balance_map.insert((0, 0, 0), 0.5);
        assert!(!upekkha.is_in_equanimity());
        // Apply many corrections
        for _ in 0..100 {
            upekkha.apply_equanimity();
        }
        assert!(upekkha.is_in_equanimity(), "Should converge to equanimity");
    }

    #[test]
    fn test_engine_step() {
        let mut engine = FourImmeasurablesEngine::new();
        engine.metta.cell_types.insert((0, 0, 0), CellType::Compute);
        engine.karuna.detect_suffering((1, 1, 1), 3.0);
        engine.mudita.record_joy((2, 2, 2), 2.0);
        engine.upekkha.balance_map.insert((3, 3, 3), 0.5);

        engine.step();
        assert_eq!(engine.generation, 1);

        let m = engine.get_metrics();
        assert!(m.interventions_applied > 0);
    }

    #[test]
    fn test_engine_default() {
        let engine = FourImmeasurablesEngine::default();
        assert_eq!(engine.generation, 0);
    }
}
