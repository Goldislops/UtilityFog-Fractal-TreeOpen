//! Cellular Automata kernel for UtilityFog
//!
//! Supports:
//! - 3D lattice with Moore neighborhood
//! - Arbitrary graph adjacency lists
//! - Synchronous and asynchronous stepping
//! - Multiple cell states (VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR)
//! - Multi-state transition rules for utility fog physics
//! - Parallel stepping via Rayon

use std::collections::HashMap;
use rayon::prelude::*;

#[cfg(feature = "python")]
use pyo3::prelude::*;

/// Cell states for the CA
#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CellState {
    Void = 0,
    Structural = 1,
    Compute = 2,
    Energy = 3,
    Sensor = 4,
}

impl From<u8> for CellState {
    fn from(value: u8) -> Self {
        match value {
            0 => CellState::Void,
            1 => CellState::Structural,
            2 => CellState::Compute,
            3 => CellState::Energy,
            4 => CellState::Sensor,
            _ => CellState::Void,
        }
    }
}

impl From<CellState> for u8 {
    fn from(state: CellState) -> Self {
        state as u8
    }
}

/// Tally of each CellState type in a node's neighborhood
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NeighborCount {
    pub void_n: usize,
    pub structural: usize,
    pub compute: usize,
    pub energy: usize,
    pub sensor: usize,
}

impl NeighborCount {
    pub fn get(&self, state: CellState) -> usize {
        match state {
            CellState::Void => self.void_n,
            CellState::Structural => self.structural,
            CellState::Compute => self.compute,
            CellState::Energy => self.energy,
            CellState::Sensor => self.sensor,
        }
    }

    pub fn total_non_void(&self) -> usize {
        self.structural + self.compute + self.energy + self.sensor
    }
}

/// A single transition condition: if (min <= neighbor_count_of[watch_state] <= max) then become target_state
#[derive(Debug, Clone)]
pub struct Transition {
    pub watch_state: CellState,
    pub min: usize,
    pub max: usize,
    pub target: CellState,
}

impl Transition {
    pub fn new(watch_state: CellState, min: usize, max: usize, target: CellState) -> Self {
        Self { watch_state, min, max, target }
    }

    pub fn matches(&self, counts: &NeighborCount) -> bool {
        let n = counts.get(self.watch_state);
        n >= self.min && n <= self.max
    }
}

/// Multi-state transition rule: maps each CellState to an ordered list of transitions (first match wins)
#[derive(Debug, Clone)]
pub struct MultiStateRule {
    pub transitions: HashMap<CellState, Vec<Transition>>,
    pub defaults: HashMap<CellState, CellState>,
}

impl MultiStateRule {
    pub fn new() -> Self {
        Self {
            transitions: HashMap::new(),
            defaults: HashMap::new(),
        }
    }

    pub fn add_transition(
        &mut self,
        from: CellState,
        watch: CellState,
        min: usize,
        max: usize,
        target: CellState,
    ) {
        self.transitions
            .entry(from)
            .or_insert_with(Vec::new)
            .push(Transition::new(watch, min, max, target));
    }

    pub fn set_default(&mut self, from: CellState, default: CellState) {
        self.defaults.insert(from, default);
    }

    pub fn apply(&self, current: CellState, counts: &NeighborCount) -> CellState {
        if let Some(trans_list) = self.transitions.get(&current) {
            for t in trans_list {
                if t.matches(counts) {
                    return t.target;
                }
            }
        }
        *self.defaults.get(&current).unwrap_or(&CellState::Void)
    }

    pub fn utility_fog_default() -> Self {
        let mut rule = MultiStateRule::new();

        // Void transitions
        rule.add_transition(CellState::Void, CellState::Energy, 2, usize::MAX, CellState::Energy);
        rule.add_transition(CellState::Void, CellState::Structural, 3, usize::MAX, CellState::Structural);
        rule.set_default(CellState::Void, CellState::Void);

        // Energy transitions
        rule.add_transition(CellState::Energy, CellState::Compute, 1, usize::MAX, CellState::Compute);
        rule.add_transition(CellState::Energy, CellState::Energy, 1, usize::MAX, CellState::Energy);
        rule.set_default(CellState::Energy, CellState::Void);

        // Compute transitions
        rule.add_transition(CellState::Compute, CellState::Energy, 1, usize::MAX, CellState::Compute);
        rule.set_default(CellState::Compute, CellState::Void);

        // Structural transitions
        rule.add_transition(CellState::Structural, CellState::Structural, 1, usize::MAX, CellState::Structural);
        rule.set_default(CellState::Structural, CellState::Void);

        // Sensor transitions
        rule.add_transition(CellState::Sensor, CellState::Compute, 2, usize::MAX, CellState::Compute);
        rule.set_default(CellState::Sensor, CellState::Sensor);

        rule
    }
}

/// 3D lattice dimensions
#[derive(Debug, Clone, Copy)]
pub struct Lattice3D {
    pub width: usize,
    pub height: usize,
    pub depth: usize,
}

impl Lattice3D {
    pub fn new(width: usize, height: usize, depth: usize) -> Self {
        Self { width, height, depth }
    }

    pub fn size(&self) -> usize {
        self.width * self.height * self.depth
    }

    pub fn index(&self, x: usize, y: usize, z: usize) -> usize {
        z * (self.width * self.height) + y * self.width + x
    }

    /// Get Moore neighborhood (26 neighbors in 3D)
    pub fn moore_neighbors(&self, x: usize, y: usize, z: usize) -> Vec<usize> {
        let mut neighbors = Vec::with_capacity(26);
        for dz in -1..=1 {
            for dy in -1..=1 {
                for dx in -1..=1 {
                    if dx == 0 && dy == 0 && dz == 0 {
                        continue;
                    }
                    let nx = x as isize + dx;
                    let ny = y as isize + dy;
                    let nz = z as isize + dz;
                    if nx >= 0 && nx < self.width as isize
                        && ny >= 0 && ny < self.height as isize
                        && nz >= 0 && nz < self.depth as isize
                    {
                        neighbors.push(self.index(nx as usize, ny as usize, nz as usize));
                    }
                }
            }
        }
        neighbors
    }
}

/// Graph-based CA using adjacency lists
pub struct GraphCA {
    pub adjacency: HashMap<usize, Vec<usize>>,
    pub states: Vec<u8>,
}

impl GraphCA {
    pub fn new(num_nodes: usize) -> Self {
        Self {
            adjacency: HashMap::new(),
            states: vec![0; num_nodes],
        }
    }

    pub fn add_edge(&mut self, from: usize, to: usize) {
        self.adjacency.entry(from).or_insert_with(Vec::new).push(to);
    }

    pub fn get_neighbors(&self, node: usize) -> &[usize] {
        self.adjacency.get(&node).map(|v| v.as_slice()).unwrap_or(&[])
    }
}

/// Birth/survival rule specification
#[derive(Debug, Clone)]
pub struct Rule {
    pub birth: Vec<usize>,
    pub survival: Vec<usize>,
}

impl Rule {
    pub fn new(birth: Vec<usize>, survival: Vec<usize>) -> Self {
        Self { birth, survival }
    }

    pub fn apply(&self, current: u8, live_neighbor_count: usize) -> u8 {
        if current == 0 {
            if self.birth.contains(&live_neighbor_count) { 1 } else { 0 }
        } else {
            if self.survival.contains(&live_neighbor_count) { 1 } else { 0 }
        }
    }
}

/// Graph state for adjacency-based stepping
#[derive(Debug, Clone)]
pub struct GraphState {
    pub nodes: Vec<u8>,
    pub adjacency: Vec<Vec<usize>>,
}

impl GraphState {
    pub fn new(nodes: Vec<u8>, adjacency: Vec<Vec<usize>>) -> Self {
        Self { nodes, adjacency }
    }

    pub fn step(&self, rule: &Rule) -> GraphState {
        let mut next_nodes = vec![0u8; self.nodes.len()];
        for i in 0..self.nodes.len() {
            let live_count = self.adjacency[i]
                .iter()
                .filter(|&&neighbor| neighbor < self.nodes.len() && self.nodes[neighbor] == 1)
                .count();
            next_nodes[i] = rule.apply(self.nodes[i], live_count);
        }
        GraphState {
            nodes: next_nodes,
            adjacency: self.adjacency.clone(),
        }
    }

    fn count_neighbors(&self, node_index: usize) -> NeighborCount {
        let mut counts = NeighborCount::default();
        for &neighbor in &self.adjacency[node_index] {
            if neighbor < self.nodes.len() {
                match CellState::from(self.nodes[neighbor]) {
                    CellState::Void => counts.void_n += 1,
                    CellState::Structural => counts.structural += 1,
                    CellState::Compute => counts.compute += 1,
                    CellState::Energy => counts.energy += 1,
                    CellState::Sensor => counts.sensor += 1,
                }
            }
        }
        counts
    }

    pub fn step_multi(&self, rule: &MultiStateRule) -> GraphState {
        let mut next_nodes = vec![0u8; self.nodes.len()];
        for i in 0..self.nodes.len() {
            let current = CellState::from(self.nodes[i]);
            let counts = self.count_neighbors(i);
            let next = rule.apply(current, &counts);
            next_nodes[i] = u8::from(next);
        }
        GraphState {
            nodes: next_nodes,
            adjacency: self.adjacency.clone(),
        }
    }

    pub fn step_multi_par(&self, rule: &MultiStateRule) -> GraphState {
        let next_nodes: Vec<u8> = (0..self.nodes.len())
            .into_par_iter()
            .map(|i| {
                let current = CellState::from(self.nodes[i]);
                let counts = self.count_neighbors(i);
                u8::from(rule.apply(current, &counts))
            })
            .collect();
        GraphState {
            nodes: next_nodes,
            adjacency: self.adjacency.clone(),
        }
    }
}

/// Outer-totalistic rule: next state depends on current state and neighbor count
pub type OuterTotalisticRule = fn(u8, usize) -> u8;

/// Step the CA on a 3D lattice with Moore neighborhood
pub fn step_lattice_3d(
    lattice: &Lattice3D,
    states: &[u8],
    rule: OuterTotalisticRule,
) -> Vec<u8> {
    let mut next_states = vec![0; states.len()];
    for z in 0..lattice.depth {
        for y in 0..lattice.height {
            for x in 0..lattice.width {
                let idx = lattice.index(x, y, z);
                let neighbors = lattice.moore_neighbors(x, y, z);
                let neighbor_count = neighbors.iter()
                    .filter(|&&n| states[n] != 0)
                    .count();
                next_states[idx] = rule(states[idx], neighbor_count);
            }
        }
    }
    next_states
}

/// Step the CA on an arbitrary graph
pub fn step_graph(
    graph: &GraphCA,
    rule: OuterTotalisticRule,
) -> Vec<u8> {
    let mut next_states = vec![0; graph.states.len()];
    for node in 0..graph.states.len() {
        let neighbors = graph.get_neighbors(node);
        let neighbor_count = neighbors.iter()
            .filter(|&&n| graph.states[n] != 0)
            .count();
        next_states[node] = rule(graph.states[node], neighbor_count);
    }
    next_states
}

/// Example rule: Conway's Game of Life adapted for 3D
pub fn conway_3d_rule(current: u8, neighbor_count: usize) -> u8 {
    match (current, neighbor_count) {
        (0, 4..=7) => 1,  // Birth
        (1, 4..=7) => 1,  // Survival
        _ => 0,            // Death
    }
}

#[cfg(feature = "python")]
#[pyclass]
pub struct GraphLattice {
    state: GraphState,
}

#[cfg(feature = "python")]
#[pymethods]
impl GraphLattice {
    #[new]
    fn new(states: Vec<u8>, adjacency: Vec<Vec<usize>>) -> Self {
        Self {
            state: GraphState::new(states, adjacency),
        }
    }

    fn step(&self, rule: HashMap<String, Vec<usize>>) -> Vec<u8> {
        let birth = rule.get("birth").cloned().unwrap_or_default();
        let survival = rule.get("survival").cloned().unwrap_or_default();
        let r = Rule::new(birth, survival);
        let next = self.state.step(&r);
        next.nodes
    }

    fn get_states(&self) -> Vec<u8> {
        self.state.nodes.clone()
    }
}

#[cfg(feature = "python")]
#[pyclass]
pub struct MultiStateGraphLattice {
    state: GraphState,
    rule: MultiStateRule,
}

#[cfg(feature = "python")]
#[pymethods]
impl MultiStateGraphLattice {
    #[new]
    fn new(states: Vec<u8>, adjacency: Vec<Vec<usize>>, transitions: Vec<(u8, u8, usize, usize, u8)>, defaults: Vec<(u8, u8)>) -> Self {
        let mut rule = MultiStateRule::new();
        for (from, watch, min, max, target) in transitions {
            rule.add_transition(
                CellState::from(from),
                CellState::from(watch),
                min,
                max,
                CellState::from(target),
            );
        }
        for (from, default) in defaults {
            rule.set_default(CellState::from(from), CellState::from(default));
        }
        Self {
            state: GraphState::new(states, adjacency),
            rule,
        }
    }

    #[staticmethod]
    fn with_fog_rules(states: Vec<u8>, adjacency: Vec<Vec<usize>>) -> Self {
        Self {
            state: GraphState::new(states, adjacency),
            rule: MultiStateRule::utility_fog_default(),
        }
    }

    fn step(&mut self) -> Vec<u8> {
        let next = self.state.step_multi(&self.rule);
        self.state = next;
        self.state.nodes.clone()
    }

    fn get_states(&self) -> Vec<u8> {
        self.state.nodes.clone()
    }

    fn step_n(&mut self, n: usize) -> Vec<u8> {
        for _ in 0..n {
            let next = self.state.step_multi(&self.rule);
            self.state = next;
        }
        self.state.nodes.clone()
    }

    fn step_par(&mut self) -> Vec<u8> {
        let next = self.state.step_multi_par(&self.rule);
        self.state = next;
        self.state.nodes.clone()
    }

    fn step_par_n(&mut self, n: usize) -> Vec<u8> {
        for _ in 0..n {
            let next = self.state.step_multi_par(&self.rule);
            self.state = next;
        }
        self.state.nodes.clone()
    }
}

#[cfg(feature = "python")]
#[pymodule]
fn uft_ca(_py: Python, m: &PyModule) -> PyResult<()> {
    /// Step a 3D lattice CA
    #[pyfn(m)]
    fn step_lattice_py(
        width: usize,
        height: usize,
        depth: usize,
        states: Vec<u8>,
    ) -> PyResult<Vec<u8>> {
        let lattice = Lattice3D::new(width, height, depth);
        Ok(step_lattice_3d(&lattice, &states, conway_3d_rule))
    }

    /// Create a graph CA
    #[pyfn(m)]
    fn create_graph(num_nodes: usize) -> PyResult<Vec<u8>> {
        Ok(vec![0; num_nodes])
    }

    m.add_class::<GraphLattice>()?;
    m.add_class::<MultiStateGraphLattice>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lattice_creation() {
        let lattice = Lattice3D::new(10, 10, 10);
        assert_eq!(lattice.size(), 1000);
    }

    #[test]
    fn test_moore_neighbors() {
        let lattice = Lattice3D::new(3, 3, 3);
        let neighbors = lattice.moore_neighbors(1, 1, 1);
        assert_eq!(neighbors.len(), 26);
    }

    #[test]
    fn test_moore_neighbors_corner() {
        let lattice = Lattice3D::new(3, 3, 3);
        let neighbors = lattice.moore_neighbors(0, 0, 0);
        assert_eq!(neighbors.len(), 7);
    }

    #[test]
    fn test_step_lattice() {
        let lattice = Lattice3D::new(3, 3, 3);
        let mut states = vec![0; lattice.size()];
        states[lattice.index(1, 1, 1)] = 1;
        states[lattice.index(0, 1, 1)] = 1;
        states[lattice.index(2, 1, 1)] = 1;
        states[lattice.index(1, 0, 1)] = 1;
        states[lattice.index(1, 2, 1)] = 1;
        let next = step_lattice_3d(&lattice, &states, conway_3d_rule);
        assert_eq!(next.len(), states.len());
    }

    #[test]
    fn test_graph_ca() {
        let mut graph = GraphCA::new(5);
        graph.add_edge(0, 1);
        graph.add_edge(0, 2);
        graph.add_edge(1, 2);
        graph.add_edge(2, 3);
        graph.add_edge(3, 4);
        graph.states[0] = 1;
        graph.states[1] = 1;
        let next = step_graph(&graph, conway_3d_rule);
        assert_eq!(next.len(), 5);
    }

    #[test]
    fn test_cell_state_conversion() {
        assert_eq!(CellState::from(0), CellState::Void);
        assert_eq!(CellState::from(1), CellState::Structural);
        assert_eq!(u8::from(CellState::Compute), 2);
    }

    #[test]
    fn test_graph_state_step_birth() {
        let nodes = vec![1, 1, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let rule = Rule::new(vec![2], vec![1, 2]);
        let next = gs.step(&rule);
        assert_eq!(next.nodes[2], 1);
        assert_eq!(next.nodes[0], 1);
        assert_eq!(next.nodes[1], 1);
    }

    #[test]
    fn test_graph_state_step_death() {
        let nodes = vec![1, 0, 0];
        let adjacency = vec![
            vec![1],
            vec![0, 2],
            vec![1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let rule = Rule::new(vec![2], vec![2, 3]);
        let next = gs.step(&rule);
        assert_eq!(next.nodes[0], 0);
        assert_eq!(next.nodes[1], 0);
    }

    #[test]
    fn test_rule_apply() {
        let rule = Rule::new(vec![3], vec![2, 3]);
        assert_eq!(rule.apply(0, 3), 1);
        assert_eq!(rule.apply(0, 2), 0);
        assert_eq!(rule.apply(1, 2), 1);
        assert_eq!(rule.apply(1, 3), 1);
        assert_eq!(rule.apply(1, 1), 0);
    }

    #[test]
    fn test_neighbor_count() {
        let nodes = vec![3, 2, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let c0 = gs.count_neighbors(0);
        assert_eq!(c0.compute, 1);
        assert_eq!(c0.void_n, 1);
        assert_eq!(c0.energy, 0);
        let c2 = gs.count_neighbors(2);
        assert_eq!(c2.energy, 1);
        assert_eq!(c2.compute, 1);
        assert_eq!(c2.void_n, 0);
    }

    #[test]
    fn test_multi_state_energy_powers_compute() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 2, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Compute);
        assert_eq!(CellState::from(next.nodes[1]), CellState::Compute);
        assert_eq!(CellState::from(next.nodes[2]), CellState::Void);
    }

    #[test]
    fn test_multi_state_energy_dissipates() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 0, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Void);
    }

    #[test]
    fn test_multi_state_energy_chain() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 3, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Energy);
        assert_eq!(CellState::from(next.nodes[1]), CellState::Energy);
        assert_eq!(CellState::from(next.nodes[2]), CellState::Energy);
    }

    #[test]
    fn test_multi_state_structural_crystallization() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![0, 1, 1, 1];
        let adjacency = vec![
            vec![1, 2, 3],
            vec![0, 2, 3],
            vec![0, 1, 3],
            vec![0, 1, 2],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Structural);
        assert_eq!(CellState::from(next.nodes[1]), CellState::Structural);
        assert_eq!(CellState::from(next.nodes[2]), CellState::Structural);
        assert_eq!(CellState::from(next.nodes[3]), CellState::Structural);
    }

    #[test]
    fn test_multi_state_unpowered_compute_dies() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![2, 0, 1];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Void);
    }

    #[test]
    fn test_multi_state_sensor_fires() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![4, 2, 2];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Compute);
    }

    #[test]
    fn test_multi_state_sensor_waits() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![4, 2, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Sensor);
    }

    #[test]
    fn test_multi_state_custom_rule() {
        let mut rule = MultiStateRule::new();
        rule.add_transition(CellState::Energy, CellState::Sensor, 1, usize::MAX, CellState::Sensor);
        rule.set_default(CellState::Energy, CellState::Void);
        rule.set_default(CellState::Sensor, CellState::Sensor);
        let nodes = vec![3, 4];
        let adjacency = vec![vec![1], vec![0]];
        let gs = GraphState::new(nodes, adjacency);
        let next = gs.step_multi(&rule);
        assert_eq!(CellState::from(next.nodes[0]), CellState::Sensor);
        assert_eq!(CellState::from(next.nodes[1]), CellState::Sensor);
    }

    #[test]
    fn test_step_multi_preserves_adjacency() {
        let rule = MultiStateRule::utility_fog_default();
        let adjacency = vec![vec![1], vec![0]];
        let gs = GraphState::new(vec![0, 0], adjacency.clone());
        let next = gs.step_multi(&rule);
        assert_eq!(next.adjacency, adjacency);
    }

    #[test]
    fn test_multi_step_convergence() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 3, 3];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let step1 = gs.step_multi(&rule);
        let step2 = step1.step_multi(&rule);
        let step3 = step2.step_multi(&rule);
        for i in 0..3 {
            assert_eq!(CellState::from(step3.nodes[i]), CellState::Energy);
        }
    }

    #[test]
    fn test_par_matches_sequential_triangle() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 2, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let seq = gs.step_multi(&rule);
        let par = gs.step_multi_par(&rule);
        assert_eq!(seq.nodes, par.nodes);
    }

    #[test]
    fn test_par_matches_sequential_energy_chain() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 3, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let seq = gs.step_multi(&rule);
        let par = gs.step_multi_par(&rule);
        assert_eq!(seq.nodes, par.nodes);
    }

    #[test]
    fn test_par_matches_sequential_structural_crystal() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![0, 1, 1, 1];
        let adjacency = vec![
            vec![1, 2, 3],
            vec![0, 2, 3],
            vec![0, 1, 3],
            vec![0, 1, 2],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let seq = gs.step_multi(&rule);
        let par = gs.step_multi_par(&rule);
        assert_eq!(seq.nodes, par.nodes);
    }

    #[test]
    fn test_par_matches_sequential_sensor_fires() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![4, 2, 2];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let seq = gs.step_multi(&rule);
        let par = gs.step_multi_par(&rule);
        assert_eq!(seq.nodes, par.nodes);
    }

    #[test]
    fn test_par_matches_sequential_all_states() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![0, 1, 2, 3, 4];
        let adjacency = vec![
            vec![1, 2, 3, 4],
            vec![0, 2, 3, 4],
            vec![0, 1, 3, 4],
            vec![0, 1, 2, 4],
            vec![0, 1, 2, 3],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let seq = gs.step_multi(&rule);
        let par = gs.step_multi_par(&rule);
        assert_eq!(seq.nodes, par.nodes);
    }

    #[test]
    fn test_par_matches_sequential_multi_step() {
        let rule = MultiStateRule::utility_fog_default();
        let nodes = vec![3, 3, 3];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        let mut seq = gs.clone();
        let mut par = gs;
        for _ in 0..10 {
            seq = seq.step_multi(&rule);
            par = par.step_multi_par(&rule);
            assert_eq!(seq.nodes, par.nodes);
        }
    }

    #[test]
    fn test_par_large_graph_correctness() {
        let rule = MultiStateRule::utility_fog_default();
        let n = 1000;
        let mut nodes = vec![0u8; n];
        for i in 0..n {
            nodes[i] = (i % 5) as u8;
        }
        let mut adjacency = Vec::with_capacity(n);
        for i in 0..n {
            let mut neighbors = Vec::new();
            if i > 0 { neighbors.push(i - 1); }
            if i + 1 < n { neighbors.push(i + 1); }
            if i + 10 < n { neighbors.push(i + 10); }
            if i >= 10 { neighbors.push(i - 10); }
            adjacency.push(neighbors);
        }
        let gs = GraphState::new(nodes, adjacency);
        let seq = gs.step_multi(&rule);
        let par = gs.step_multi_par(&rule);
        assert_eq!(seq.nodes, par.nodes);
    }

    #[test]
    fn test_par_preserves_adjacency() {
        let rule = MultiStateRule::utility_fog_default();
        let adjacency = vec![vec![1], vec![0]];
        let gs = GraphState::new(vec![3, 3], adjacency.clone());
        let par = gs.step_multi_par(&rule);
        assert_eq!(par.adjacency, adjacency);
    }
}
