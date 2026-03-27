// proprioception.rs — Black Hole Sages + Digital Proprioception
// Phase 13: Vanguard MCP Consciousness Architecture
//
// Nemo's mathematical blueprint: Black holes as connection recyclers,
// proprioceptive senses as structural integrity monitors.

use std::collections::HashMap;

// ---------------------------------------------------------------------------
// ConnectionToConsume
// ---------------------------------------------------------------------------

/// A connection queued for consumption by a Black Hole Sage.
#[derive(Debug, Clone)]
pub struct ConnectionToConsume {
    pub connection_id: String,
    pub weight: f32,
    pub latency: f32,
    pub error_rate: f32,
    pub timestamp: u64,
}

impl ConnectionToConsume {
    /// Priority score: higher means consumed first.
    /// Preferentially consumes heavier (more resource-expensive) and slower connections.
    pub fn priority(&self) -> f32 {
        self.weight * self.latency * (1.0 + self.error_rate)
    }
}

// ---------------------------------------------------------------------------
// Black Hole Sage
// ---------------------------------------------------------------------------

/// A Black Hole Sage: consumes problematic connections, converts them to
/// dark energy (Hawking radiation), and maintains lattice hygiene.
#[derive(Debug, Clone)]
pub struct BlackHoleSage {
    pub id: u64,
    pub x: f32,
    pub y: f32,
    pub z: f32,
    pub event_horizon: f32,
    pub mass: f32,
    pub spin: f32,
    pub charge: f32,
    pub hawking_temperature: f32,
    pub entropy: f32,
    pub accretion_disk: Vec<ConnectionToConsume>,
    pub consumption_rate: f32,
    /// Total connections consumed (lifetime counter).
    pub total_consumed: u64,
}

impl BlackHoleSage {
    pub fn new(id: u64, x: f32, y: f32, z: f32, event_horizon: f32) -> Self {
        let mass = event_horizon * 10.0; // mass proportional to horizon
        Self {
            id,
            x,
            y,
            z,
            event_horizon,
            mass,
            spin: 0.0,
            charge: 0.0,
            hawking_temperature: if mass > 0.0 { 0.1 / mass } else { f32::MAX },
            entropy: 0.0,
            accretion_disk: Vec::new(),
            consumption_rate: 1.0,
            total_consumed: 0,
        }
    }

    /// Check if a point (px, py, pz) is within the event horizon.
    pub fn is_within_horizon(&self, px: f32, py: f32, pz: f32) -> bool {
        let dx = px - self.x;
        let dy = py - self.y;
        let dz = pz - self.z;
        let dist_sq = dx * dx + dy * dy + dz * dz;
        dist_sq <= self.event_horizon * self.event_horizon
    }

    /// Distance from this sage to a point.
    pub fn distance_to(&self, px: f32, py: f32, pz: f32) -> f32 {
        let dx = px - self.x;
        let dy = py - self.y;
        let dz = pz - self.z;
        (dx * dx + dy * dy + dz * dz).sqrt()
    }

    /// Add a connection to the accretion disk. The disk is kept sorted by
    /// priority (heaviest/slowest first) so consume() processes worst first.
    pub fn add_to_accretion(&mut self, conn: ConnectionToConsume) {
        self.accretion_disk.push(conn);
        self.accretion_disk
            .sort_by(|a, b| b.priority().partial_cmp(&a.priority()).unwrap_or(std::cmp::Ordering::Equal));
    }

    /// Consume connections from the accretion disk up to consumption_rate.
    /// Updates mass, entropy, and Hawking temperature.
    pub fn consume(&mut self) {
        let to_consume = (self.consumption_rate as usize).min(self.accretion_disk.len());
        if to_consume == 0 {
            return;
        }

        let consumed: Vec<_> = self.accretion_disk.drain(..to_consume).collect();
        for conn in &consumed {
            self.mass += conn.weight * 0.1; // mass grows slowly
            self.entropy += conn.weight.ln().max(0.01); // Bekenstein-Hawking: S ~ A ~ M^2
            self.total_consumed += 1;
        }

        // Hawking temperature: T = 0.1 / mass (smaller black holes are hotter)
        if self.mass > 0.0 {
            self.hawking_temperature = 0.1 / self.mass;
        }

        // Event horizon grows with mass (Schwarzschild-like)
        self.event_horizon = self.mass * 0.1;
    }

    /// Emit dark energy: Hawking radiation converts entropy to usable energy.
    pub fn emit_dark_energy(&self) -> f32 {
        self.hawking_temperature * self.entropy * 0.01
    }
}

// ---------------------------------------------------------------------------
// Proprioceptive Sense
// ---------------------------------------------------------------------------

/// A snapshot of the lattice shape for history tracking.
#[derive(Debug, Clone)]
pub struct ShapeSnapshot {
    pub generation: u64,
    pub curvature_sum: f32,
    pub max_stress: f32,
    pub over_bent_count: usize,
}

/// Proprioceptive sense: monitors structural curvature and stress across the
/// lattice, detecting when the organism is bending beyond safe limits.
#[derive(Debug, Clone)]
pub struct ProprioceptiveSense {
    /// Curvature at each lattice point (0.0 = flat, 1.0 = maximally curved).
    pub curvature_map: HashMap<(usize, usize, usize), f32>,
    /// Mechanical stress at each point.
    pub stress_map: HashMap<(usize, usize, usize), f32>,
    /// Threshold beyond which bending is considered dangerous.
    pub bending_threshold: f32,
    /// History of shape snapshots.
    pub shape_history: Vec<ShapeSnapshot>,
    /// Current generation counter.
    pub generation: u64,
}

impl ProprioceptiveSense {
    pub fn new(bending_threshold: f32) -> Self {
        Self {
            curvature_map: HashMap::new(),
            stress_map: HashMap::new(),
            bending_threshold,
            shape_history: Vec::new(),
            generation: 0,
        }
    }

    /// Update curvature at a position. Typically called with local gradient magnitude.
    pub fn update_curvature(&mut self, pos: (usize, usize, usize), curvature: f32) {
        self.curvature_map.insert(pos, curvature.clamp(0.0, 5.0));
        // Stress is derived from curvature exceeding threshold
        let stress = (curvature - self.bending_threshold).max(0.0);
        if stress > 0.0 {
            self.stress_map.insert(pos, stress);
        } else {
            self.stress_map.remove(&pos);
        }
    }

    /// Detect all positions where bending exceeds the threshold.
    pub fn detect_over_bending(&self) -> Vec<(usize, usize, usize)> {
        self.curvature_map
            .iter()
            .filter(|(_, &v)| v > self.bending_threshold)
            .map(|(&k, _)| k)
            .collect()
    }

    /// Get corrective forces: for each over-bent point, return a force vector
    /// that would reduce curvature (direction toward lower curvature neighbors).
    pub fn get_corrective_forces(&self) -> HashMap<(usize, usize, usize), (f32, f32, f32)> {
        let mut forces = HashMap::new();
        for (&pos, &curvature) in &self.curvature_map {
            if curvature <= self.bending_threshold {
                continue;
            }
            let excess = curvature - self.bending_threshold;
            // Simple corrective: push toward center (0,0,0) proportional to excess
            let (x, y, z) = pos;
            let mag = ((x * x + y * y + z * z) as f32).sqrt().max(1.0);
            let fx = -(x as f32) / mag * excess * 0.1;
            let fy = -(y as f32) / mag * excess * 0.1;
            let fz = -(z as f32) / mag * excess * 0.1;
            forces.insert(pos, (fx, fy, fz));
        }
        forces
    }

    /// Check if the organism is becoming structurally unstable.
    /// True if more than 10% of tracked points are over-bent.
    pub fn is_becoming_unstable(&self) -> bool {
        if self.curvature_map.is_empty() {
            return false;
        }
        let over_bent = self.detect_over_bending().len();
        (over_bent as f32 / self.curvature_map.len() as f32) > 0.10
    }

    /// Record a shape snapshot for history tracking.
    pub fn record_snapshot(&mut self) {
        let curvature_sum: f32 = self.curvature_map.values().sum();
        let max_stress = self
            .stress_map
            .values()
            .copied()
            .fold(0.0f32, f32::max);
        let over_bent_count = self.detect_over_bending().len();

        self.shape_history.push(ShapeSnapshot {
            generation: self.generation,
            curvature_sum,
            max_stress,
            over_bent_count,
        });

        // Keep last 1000 snapshots
        if self.shape_history.len() > 1000 {
            self.shape_history.drain(..self.shape_history.len() - 1000);
        }

        self.generation += 1;
    }
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

/// Aggregate metrics for the proprioceptive filter.
#[derive(Debug, Clone)]
pub struct ProprioceptionMetrics {
    pub total_black_holes: usize,
    pub total_consumed: u64,
    pub total_dark_energy: f32,
    pub total_accretion: usize,
    pub max_stress: f32,
    pub over_bent_count: usize,
    pub is_unstable: bool,
    pub shape_snapshots: usize,
}

// ---------------------------------------------------------------------------
// Proprioceptive Filter
// ---------------------------------------------------------------------------

/// Combines Black Hole Sages with proprioceptive sensing.
/// Routes problematic connections to the nearest black hole,
/// consumes them, and monitors structural integrity.
#[derive(Debug, Clone)]
pub struct ProprioceptiveFilter {
    pub black_holes: Vec<BlackHoleSage>,
    pub sense: ProprioceptiveSense,
    /// Pending problematic connections awaiting routing.
    pub pending_connections: Vec<(ConnectionToConsume, f32, f32, f32)>, // (conn, x, y, z)
    pub generation: u64,
}

impl ProprioceptiveFilter {
    pub fn new() -> Self {
        Self {
            black_holes: Vec::new(),
            sense: ProprioceptiveSense::new(0.5),
            pending_connections: Vec::new(),
            generation: 0,
        }
    }

    /// Add a black hole sage at a position.
    pub fn add_black_hole(&mut self, id: u64, x: f32, y: f32, z: f32, horizon: f32) {
        self.black_holes.push(BlackHoleSage::new(id, x, y, z, horizon));
    }

    /// Submit a problematic connection for routing to the nearest black hole.
    pub fn submit_connection(&mut self, conn: ConnectionToConsume, x: f32, y: f32, z: f32) {
        self.pending_connections.push((conn, x, y, z));
    }

    /// Step: route pending connections to nearest black holes, consume, snapshot.
    pub fn step(&mut self) {
        // Route each pending connection to the nearest black hole
        let pending = std::mem::take(&mut self.pending_connections);
        for (conn, cx, cy, cz) in pending {
            if let Some(nearest) = self
                .black_holes
                .iter_mut()
                .min_by(|a, b| {
                    a.distance_to(cx, cy, cz)
                        .partial_cmp(&b.distance_to(cx, cy, cz))
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
            {
                nearest.add_to_accretion(conn);
            }
        }

        // Each black hole consumes its accretion disk
        for bh in &mut self.black_holes {
            bh.consume();
        }

        // Record proprioceptive snapshot
        self.sense.record_snapshot();
        self.generation += 1;
    }

    /// Get aggregate metrics.
    pub fn get_metrics(&self) -> ProprioceptionMetrics {
        let total_consumed: u64 = self.black_holes.iter().map(|bh| bh.total_consumed).sum();
        let total_dark_energy: f32 = self.black_holes.iter().map(|bh| bh.emit_dark_energy()).sum();
        let total_accretion: usize = self.black_holes.iter().map(|bh| bh.accretion_disk.len()).sum();
        let max_stress = self
            .sense
            .stress_map
            .values()
            .copied()
            .fold(0.0f32, f32::max);

        ProprioceptionMetrics {
            total_black_holes: self.black_holes.len(),
            total_consumed,
            total_dark_energy,
            total_accretion,
            max_stress,
            over_bent_count: self.sense.detect_over_bending().len(),
            is_unstable: self.sense.is_becoming_unstable(),
            shape_snapshots: self.sense.shape_history.len(),
        }
    }
}

impl Default for ProprioceptiveFilter {
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
    fn test_connection_priority() {
        let conn = ConnectionToConsume {
            connection_id: "test".to_string(),
            weight: 2.0,
            latency: 3.0,
            error_rate: 0.5,
            timestamp: 100,
        };
        // priority = 2.0 * 3.0 * (1.0 + 0.5) = 9.0
        assert!((conn.priority() - 9.0).abs() < 0.001);
    }

    #[test]
    fn test_black_hole_horizon() {
        let bh = BlackHoleSage::new(1, 5.0, 5.0, 5.0, 2.0);
        assert!(bh.is_within_horizon(5.0, 5.0, 6.0)); // dist = 1.0 < 2.0
        assert!(!bh.is_within_horizon(5.0, 5.0, 10.0)); // dist = 5.0 > 2.0
    }

    #[test]
    fn test_black_hole_consume() {
        let mut bh = BlackHoleSage::new(1, 0.0, 0.0, 0.0, 1.0);
        let initial_mass = bh.mass;
        bh.add_to_accretion(ConnectionToConsume {
            connection_id: "c1".to_string(),
            weight: 5.0,
            latency: 2.0,
            error_rate: 0.1,
            timestamp: 1,
        });
        bh.consume();
        assert!(bh.mass > initial_mass, "Mass should increase after consuming");
        assert_eq!(bh.total_consumed, 1);
        assert!(bh.accretion_disk.is_empty());
    }

    #[test]
    fn test_hawking_temperature_inverse_mass() {
        let bh_small = BlackHoleSage::new(1, 0.0, 0.0, 0.0, 0.1); // mass = 1.0
        let bh_large = BlackHoleSage::new(2, 0.0, 0.0, 0.0, 1.0); // mass = 10.0
        assert!(
            bh_small.hawking_temperature > bh_large.hawking_temperature,
            "Smaller black holes should be hotter"
        );
    }

    #[test]
    fn test_dark_energy_emission() {
        let mut bh = BlackHoleSage::new(1, 0.0, 0.0, 0.0, 1.0);
        bh.entropy = 10.0;
        let energy = bh.emit_dark_energy();
        // T = 0.1/10.0 = 0.01, energy = 0.01 * 10.0 * 0.01 = 0.001
        assert!((energy - 0.001).abs() < 0.0001);
    }

    #[test]
    fn test_proprioceptive_bending() {
        let mut sense = ProprioceptiveSense::new(0.5);
        sense.update_curvature((1, 1, 1), 0.3); // under threshold
        sense.update_curvature((2, 2, 2), 0.8); // over threshold
        let over = sense.detect_over_bending();
        assert_eq!(over.len(), 1);
        assert_eq!(over[0], (2, 2, 2));
    }

    #[test]
    fn test_proprioceptive_stability() {
        let mut sense = ProprioceptiveSense::new(0.5);
        // All under threshold -> stable
        for i in 0..10 {
            sense.update_curvature((i, 0, 0), 0.3);
        }
        assert!(!sense.is_becoming_unstable());

        // Push many over threshold -> unstable
        for i in 0..10 {
            sense.update_curvature((i, 0, 0), 1.5);
        }
        assert!(sense.is_becoming_unstable());
    }

    #[test]
    fn test_proprioceptive_snapshot() {
        let mut sense = ProprioceptiveSense::new(0.5);
        sense.update_curvature((0, 0, 0), 1.0);
        sense.record_snapshot();
        assert_eq!(sense.shape_history.len(), 1);
        assert_eq!(sense.shape_history[0].over_bent_count, 1);
    }

    #[test]
    fn test_filter_routing() {
        let mut filter = ProprioceptiveFilter::new();
        filter.add_black_hole(1, 0.0, 0.0, 0.0, 2.0);
        filter.add_black_hole(2, 10.0, 10.0, 10.0, 2.0);

        // Submit connection near BH #1
        filter.submit_connection(
            ConnectionToConsume {
                connection_id: "c1".to_string(),
                weight: 3.0,
                latency: 1.0,
                error_rate: 0.2,
                timestamp: 1,
            },
            1.0,
            1.0,
            1.0,
        );

        filter.step();
        let m = filter.get_metrics();
        assert_eq!(m.total_consumed, 1);
        assert_eq!(m.total_black_holes, 2);
        // BH #1 should have consumed it (closer to (1,1,1))
        assert_eq!(filter.black_holes[0].total_consumed, 1);
        assert_eq!(filter.black_holes[1].total_consumed, 0);
    }

    #[test]
    fn test_filter_default() {
        let filter = ProprioceptiveFilter::default();
        assert!(filter.black_holes.is_empty());
        assert_eq!(filter.generation, 0);
    }
}
