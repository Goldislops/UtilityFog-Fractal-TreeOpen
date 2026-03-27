// acoustic_hydrotropism.rs — Resource Foraging via Acoustic Signatures
// Phase 13: Vanguard MCP Consciousness Architecture
//
// Nemo's mathematical blueprint: Like plant roots seeking water through
// chemical gradients, cluster nodes forage for resources by listening
// to acoustic signatures (utilization patterns) of neighboring nodes.

use std::collections::HashMap;
use std::collections::VecDeque;
use std::time::{Duration, Instant};

// ---------------------------------------------------------------------------
// Resource Types
// ---------------------------------------------------------------------------

/// Types of resources that can be detected acoustically.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ResourceType {
    Cpu,
    Gpu,
    Memory,
    Network,
    Storage,
}

// ---------------------------------------------------------------------------
// Acoustic Signature
// ---------------------------------------------------------------------------

/// An acoustic signature representing the utilization profile of a resource.
/// Idle resources emit low-frequency, low-amplitude signals. Busy resources
/// emit high-frequency, high-amplitude signals.
#[derive(Debug, Clone)]
pub struct AcousticSignature {
    pub resource_id: String,
    pub resource_type: ResourceType,
    /// Fundamental frequency (Hz-equivalent, proportional to utilization rate).
    pub frequency: f32,
    /// Signal amplitude (0.0–1.0, proportional to load).
    pub amplitude: f32,
    /// Signal phase (0.0–2*pi, for interference calculations).
    pub phase: f32,
    /// Harmonic overtones (additional frequency components from complex workloads).
    pub harmonics: Vec<f32>,
    /// Variability: how much the signature fluctuates (bursty vs steady).
    pub variability: f32,
    /// When this signature was last detected.
    pub last_detected: Instant,
}

impl AcousticSignature {
    /// Create an idle resource signature (low freq, low amplitude).
    pub fn idle_signature(resource_id: String, resource_type: ResourceType) -> Self {
        Self {
            resource_id,
            resource_type,
            frequency: 0.1,
            amplitude: 0.1,
            phase: 0.0,
            harmonics: vec![0.05, 0.02],
            variability: 0.05,
            last_detected: Instant::now(),
        }
    }

    /// Create a busy resource signature (high freq, high amplitude).
    pub fn busy_signature(resource_id: String, resource_type: ResourceType) -> Self {
        Self {
            resource_id,
            resource_type,
            frequency: 0.9,
            amplitude: 0.85,
            phase: 0.0,
            harmonics: vec![0.7, 0.5, 0.3, 0.1],
            variability: 0.3,
            last_detected: Instant::now(),
        }
    }

    /// Calculate resonance between this signature and another.
    /// High resonance means similar utilization patterns (potential for load balancing).
    pub fn resonance(&self, other: &AcousticSignature) -> f32 {
        let freq_match = 1.0 - (self.frequency - other.frequency).abs();
        let amp_match = 1.0 - (self.amplitude - other.amplitude).abs();
        let phase_diff = (self.phase - other.phase).abs();
        let phase_match = 1.0 - (phase_diff / std::f32::consts::PI).min(1.0);

        // Harmonic overlap (compare common harmonics)
        let harmonic_match = if self.harmonics.is_empty() || other.harmonics.is_empty() {
            0.5
        } else {
            let pairs = self.harmonics.len().min(other.harmonics.len());
            let sum: f32 = self.harmonics[..pairs]
                .iter()
                .zip(&other.harmonics[..pairs])
                .map(|(a, b)| 1.0 - (a - b).abs())
                .sum();
            sum / pairs as f32
        };

        ((freq_match + amp_match + phase_match + harmonic_match) / 4.0).clamp(0.0, 1.0)
    }

    /// Is this resource idle? (amplitude below 0.3 threshold)
    pub fn is_idle(&self) -> bool {
        self.amplitude < 0.3
    }

    /// How stale is this reading?
    pub fn age(&self) -> Duration {
        self.last_detected.elapsed()
    }
}

// ---------------------------------------------------------------------------
// Acoustic Sensor
// ---------------------------------------------------------------------------

/// Listens for acoustic signatures from surrounding resources.
#[derive(Debug, Clone)]
pub struct AcousticSensor {
    /// Known signatures indexed by resource_id.
    pub signatures: HashMap<String, AcousticSignature>,
    /// Sensor sensitivity (multiplier on detection range).
    pub sensitivity: f32,
    /// Maximum age before a signature is considered stale.
    pub max_staleness: Duration,
}

impl AcousticSensor {
    pub fn new(sensitivity: f32) -> Self {
        Self {
            signatures: HashMap::new(),
            sensitivity,
            max_staleness: Duration::from_secs(30),
        }
    }

    /// Sample a resource: update or insert its acoustic signature.
    /// In production, utilization would come from OS metrics; here we accept
    /// it as a parameter for testability.
    pub fn sample(
        &mut self,
        resource_id: String,
        resource_type: ResourceType,
        utilization: f32,
        variability: f32,
    ) {
        let sig = AcousticSignature {
            resource_id: resource_id.clone(),
            resource_type,
            frequency: utilization.clamp(0.0, 1.0),
            amplitude: utilization.clamp(0.0, 1.0),
            phase: 0.0, // phase would be computed from timing in a real system
            harmonics: vec![utilization * 0.7, utilization * 0.4],
            variability: variability.clamp(0.0, 1.0),
            last_detected: Instant::now(),
        };
        self.signatures.insert(resource_id, sig);
    }

    /// Prune stale signatures.
    pub fn prune_stale(&mut self) {
        let max = self.max_staleness;
        self.signatures.retain(|_, sig| sig.age() < max);
    }

    /// Find all idle resources (amplitude < 0.3), sorted by lowest utilization.
    pub fn find_idle_resources(&self) -> Vec<&AcousticSignature> {
        let mut idle: Vec<_> = self.signatures.values().filter(|s| s.is_idle()).collect();
        idle.sort_by(|a, b| {
            a.amplitude
                .partial_cmp(&b.amplitude)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        idle
    }

    /// Find resources whose signature resonates with a target, above a threshold.
    pub fn find_resonant_resources(
        &self,
        target: &AcousticSignature,
        min_resonance: f32,
    ) -> Vec<(&AcousticSignature, f32)> {
        let mut resonant: Vec<_> = self
            .signatures
            .values()
            .filter(|s| s.resource_id != target.resource_id)
            .map(|s| (s, s.resonance(target)))
            .filter(|(_, r)| *r >= min_resonance)
            .collect();
        resonant.sort_by(|a, b| {
            b.1.partial_cmp(&a.1)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        resonant
    }
}

// ---------------------------------------------------------------------------
// Growth Vector
// ---------------------------------------------------------------------------

/// A directed growth impulse toward a resource.
#[derive(Debug, Clone)]
pub struct GrowthVector {
    /// Direction (unit-ish vector).
    pub direction: (f32, f32, f32),
    /// Strength of the growth impulse.
    pub strength: f32,
    /// Target resource ID.
    pub target_resource: String,
    /// Expected gain from reaching this resource.
    pub expected_gain: f32,
    /// Confidence in the signal (based on freshness, consistency).
    pub confidence: f32,
}

// ---------------------------------------------------------------------------
// Resource Needs
// ---------------------------------------------------------------------------

/// What a foraging sub-mind currently needs.
#[derive(Debug, Clone)]
pub struct ResourceNeeds {
    pub cpu: f32,
    pub gpu: f32,
    pub memory: f32,
    pub network: f32,
    pub storage: f32,
}

impl ResourceNeeds {
    pub fn new() -> Self {
        Self {
            cpu: 0.0,
            gpu: 0.0,
            memory: 0.0,
            network: 0.0,
            storage: 0.0,
        }
    }

    /// Get need for a specific resource type.
    pub fn need_for(&self, rt: ResourceType) -> f32 {
        match rt {
            ResourceType::Cpu => self.cpu,
            ResourceType::Gpu => self.gpu,
            ResourceType::Memory => self.memory,
            ResourceType::Network => self.network,
            ResourceType::Storage => self.storage,
        }
    }

    /// Total unmet need.
    pub fn total_need(&self) -> f32 {
        self.cpu + self.gpu + self.memory + self.network + self.storage
    }
}

impl Default for ResourceNeeds {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------------------
// Foraging Sub-Mind
// ---------------------------------------------------------------------------

/// A foraging sub-mind: an autonomous agent that grows toward resources
/// guided by acoustic signatures, like a root seeking water.
#[derive(Debug, Clone)]
pub struct ForagingSubMind {
    pub id: u64,
    pub position: (f32, f32, f32),
    pub needs: ResourceNeeds,
    /// Planned growth path (sequence of waypoints).
    pub growth_path: VecDeque<(f32, f32, f32)>,
    /// Preference weighting for acoustic vs. proximity.
    pub acoustic_preference: f32,
    /// Resources successfully foraged (lifetime counter).
    pub resources_foraged: u64,
}

impl ForagingSubMind {
    pub fn new(id: u64, position: (f32, f32, f32)) -> Self {
        Self {
            id,
            position,
            needs: ResourceNeeds::new(),
            growth_path: VecDeque::new(),
            acoustic_preference: 0.7,
            resources_foraged: 0,
        }
    }

    /// Calculate growth vectors toward idle resources detected by the sensor.
    /// Returns vectors sorted by expected gain (best first).
    pub fn calculate_growth_vectors(
        &self,
        idle_resources: &[&AcousticSignature],
        resource_positions: &HashMap<String, (f32, f32, f32)>,
    ) -> Vec<GrowthVector> {
        let mut vectors = Vec::new();

        for sig in idle_resources {
            let need = self.needs.need_for(sig.resource_type);
            if need <= 0.0 {
                continue;
            }

            let rpos = match resource_positions.get(&sig.resource_id) {
                Some(&p) => p,
                None => continue,
            };

            let dx = rpos.0 - self.position.0;
            let dy = rpos.1 - self.position.1;
            let dz = rpos.2 - self.position.2;
            let dist = (dx * dx + dy * dy + dz * dz).sqrt().max(0.001);

            // Normalize direction
            let dir = (dx / dist, dy / dist, dz / dist);

            // Expected gain: need * idle-ness * inverse-distance * acoustic preference
            let idle_factor = 1.0 - sig.amplitude;
            let proximity_factor = 1.0 / (1.0 + dist * 0.1);
            let expected_gain =
                need * (self.acoustic_preference * idle_factor + (1.0 - self.acoustic_preference) * proximity_factor);

            // Confidence based on signal freshness
            let age_secs = sig.age().as_secs_f32();
            let confidence = (1.0 - age_secs / 30.0).clamp(0.0, 1.0);

            vectors.push(GrowthVector {
                direction: dir,
                strength: expected_gain * confidence,
                target_resource: sig.resource_id.clone(),
                expected_gain,
                confidence,
            });
        }

        vectors.sort_by(|a, b| {
            b.strength
                .partial_cmp(&a.strength)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        vectors
    }

    /// Grow toward the best available resource: pick the top growth vector
    /// and add the next waypoint to the growth path.
    pub fn grow_toward(&mut self, vectors: &[GrowthVector], step_size: f32) {
        if let Some(best) = vectors.first() {
            let (dx, dy, dz) = best.direction;
            let next = (
                self.position.0 + dx * step_size * best.strength,
                self.position.1 + dy * step_size * best.strength,
                self.position.2 + dz * step_size * best.strength,
            );
            self.growth_path.push_back(next);

            // Keep path bounded
            if self.growth_path.len() > 100 {
                self.growth_path.pop_front();
            }
        }
    }

    /// Advance position to the next waypoint in the growth path.
    pub fn advance(&mut self) {
        if let Some(next) = self.growth_path.pop_front() {
            self.position = next;
        }
    }
}

// ---------------------------------------------------------------------------
// Foraging Metrics
// ---------------------------------------------------------------------------

/// Aggregate metrics for the acoustic foraging system.
#[derive(Debug, Clone)]
pub struct ForagingMetrics {
    pub known_resources: usize,
    pub idle_resources: usize,
    pub active_foragers: usize,
    pub total_foraged: u64,
    pub average_need: f32,
    pub growth_paths_active: usize,
}

// ---------------------------------------------------------------------------
// Acoustic Forager (Orchestrator)
// ---------------------------------------------------------------------------

/// Orchestrates acoustic sensing and foraging growth across all sub-minds.
#[derive(Debug, Clone)]
pub struct AcousticForager {
    pub sensor: AcousticSensor,
    pub foragers: Vec<ForagingSubMind>,
    /// Known positions of resources in the lattice.
    pub resource_positions: HashMap<String, (f32, f32, f32)>,
    /// Growth step size.
    pub step_size: f32,
    /// Total steps executed.
    pub generation: u64,
}

impl AcousticForager {
    pub fn new(sensitivity: f32, step_size: f32) -> Self {
        Self {
            sensor: AcousticSensor::new(sensitivity),
            foragers: Vec::new(),
            resource_positions: HashMap::new(),
            step_size,
            generation: 0,
        }
    }

    /// Add a foraging sub-mind.
    pub fn add_forager(&mut self, forager: ForagingSubMind) {
        self.foragers.push(forager);
    }

    /// Register a resource at a known position.
    pub fn register_resource(&mut self, resource_id: String, position: (f32, f32, f32)) {
        self.resource_positions.insert(resource_id, position);
    }

    /// Main step: listen, evaluate, grow (the "listen_and_forage" cycle).
    pub fn step(&mut self) {
        // 1. Prune stale signatures
        self.sensor.prune_stale();

        // 2. Find idle resources
        let idle: Vec<AcousticSignature> = self
            .sensor
            .find_idle_resources()
            .into_iter()
            .cloned()
            .collect();

        let idle_refs: Vec<&AcousticSignature> = idle.iter().collect();

        // 3. Each forager calculates growth vectors and grows
        for forager in &mut self.foragers {
            let vectors = forager.calculate_growth_vectors(&idle_refs, &self.resource_positions);
            forager.grow_toward(&vectors, self.step_size);
            forager.advance();
        }

        self.generation += 1;
    }

    /// Get aggregate metrics.
    pub fn get_metrics(&self) -> ForagingMetrics {
        let total_foraged: u64 = self.foragers.iter().map(|f| f.resources_foraged).sum();
        let average_need = if self.foragers.is_empty() {
            0.0
        } else {
            let sum: f32 = self.foragers.iter().map(|f| f.needs.total_need()).sum();
            sum / self.foragers.len() as f32
        };
        let growth_paths_active = self
            .foragers
            .iter()
            .filter(|f| !f.growth_path.is_empty())
            .count();

        ForagingMetrics {
            known_resources: self.sensor.signatures.len(),
            idle_resources: self.sensor.find_idle_resources().len(),
            active_foragers: self.foragers.len(),
            total_foraged,
            average_need,
            growth_paths_active,
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_idle_signature() {
        let sig = AcousticSignature::idle_signature("gpu-0".to_string(), ResourceType::Gpu);
        assert!(sig.is_idle());
        assert!(sig.amplitude < 0.3);
    }

    #[test]
    fn test_busy_signature() {
        let sig = AcousticSignature::busy_signature("cpu-0".to_string(), ResourceType::Cpu);
        assert!(!sig.is_idle());
        assert!(sig.amplitude > 0.3);
    }

    #[test]
    fn test_resonance_self() {
        let sig = AcousticSignature::idle_signature("r1".to_string(), ResourceType::Cpu);
        let r = sig.resonance(&sig);
        assert!(r > 0.9, "Self-resonance should be near 1.0, got {}", r);
    }

    #[test]
    fn test_resonance_opposite() {
        let idle = AcousticSignature::idle_signature("r1".to_string(), ResourceType::Cpu);
        let busy = AcousticSignature::busy_signature("r2".to_string(), ResourceType::Cpu);
        let r = idle.resonance(&busy);
        assert!(r < 0.5, "Idle-busy resonance should be low, got {}", r);
    }

    #[test]
    fn test_sensor_sample_and_find_idle() {
        let mut sensor = AcousticSensor::new(1.0);
        sensor.sample("gpu-0".to_string(), ResourceType::Gpu, 0.1, 0.05);
        sensor.sample("gpu-1".to_string(), ResourceType::Gpu, 0.9, 0.3);
        let idle = sensor.find_idle_resources();
        assert_eq!(idle.len(), 1);
        assert_eq!(idle[0].resource_id, "gpu-0");
    }

    #[test]
    fn test_sensor_resonant() {
        let mut sensor = AcousticSensor::new(1.0);
        sensor.sample("a".to_string(), ResourceType::Cpu, 0.5, 0.1);
        sensor.sample("b".to_string(), ResourceType::Cpu, 0.52, 0.1);
        sensor.sample("c".to_string(), ResourceType::Cpu, 0.95, 0.4);
        let target = sensor.signatures.get("a").unwrap().clone();
        let resonant = sensor.find_resonant_resources(&target, 0.8);
        assert!(!resonant.is_empty(), "b should resonate with a");
        assert_eq!(resonant[0].0.resource_id, "b");
    }

    #[test]
    fn test_growth_vector_calculation() {
        let mut forager = ForagingSubMind::new(1, (0.0, 0.0, 0.0));
        forager.needs.gpu = 1.0;

        let sig = AcousticSignature::idle_signature("gpu-0".to_string(), ResourceType::Gpu);
        let idle = vec![&sig];

        let mut positions = HashMap::new();
        positions.insert("gpu-0".to_string(), (10.0, 0.0, 0.0));

        let vectors = forager.calculate_growth_vectors(&idle, &positions);
        assert_eq!(vectors.len(), 1);
        assert!(vectors[0].direction.0 > 0.9, "Should point toward gpu-0 on x-axis");
    }

    #[test]
    fn test_forager_grow_and_advance() {
        let mut forager = ForagingSubMind::new(1, (0.0, 0.0, 0.0));
        let vector = GrowthVector {
            direction: (1.0, 0.0, 0.0),
            strength: 1.0,
            target_resource: "gpu-0".to_string(),
            expected_gain: 0.5,
            confidence: 1.0,
        };
        forager.grow_toward(&[vector], 1.0);
        assert!(!forager.growth_path.is_empty());
        forager.advance();
        assert!(forager.position.0 > 0.0, "Should have moved in +x direction");
    }

    #[test]
    fn test_acoustic_forager_step() {
        let mut af = AcousticForager::new(1.0, 1.0);
        af.sensor
            .sample("gpu-0".to_string(), ResourceType::Gpu, 0.1, 0.05);
        af.register_resource("gpu-0".to_string(), (10.0, 0.0, 0.0));

        let mut sub = ForagingSubMind::new(1, (0.0, 0.0, 0.0));
        sub.needs.gpu = 1.0;
        af.add_forager(sub);

        af.step();
        assert_eq!(af.generation, 1);
        let m = af.get_metrics();
        assert_eq!(m.active_foragers, 1);
        assert_eq!(m.known_resources, 1);
        assert_eq!(m.idle_resources, 1);
    }

    #[test]
    fn test_resource_needs_default() {
        let needs = ResourceNeeds::default();
        assert_eq!(needs.total_need(), 0.0);
    }
}
