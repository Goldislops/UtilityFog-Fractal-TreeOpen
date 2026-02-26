//! Cellular Automata kernel for UtilityFog
//!
//! Supports:
//! - 3D lattice with Moore neighborhood
//! - Arbitrary graph adjacency lists
//! - Synchronous and asynchronous stepping
//! - Multiple cell states (VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR)

use std::collections::HashMap;

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
        // Set center cell and some neighbors
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
        // Triangle graph: 0-1, 1-2, 2-0
        let nodes = vec![1, 1, 0];
        let adjacency = vec![
            vec![1, 2],
            vec![0, 2],
            vec![0, 1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        // Rule: birth on 2 neighbors alive, survival on 1+
        let rule = Rule::new(vec![2], vec![1, 2]);
        let next = gs.step(&rule);
        // Node 2 was 0, has 2 live neighbors (0,1) -> birth
        assert_eq!(next.nodes[2], 1);
        // Node 0 was 1, has 1 live neighbor (1) -> survives
        assert_eq!(next.nodes[0], 1);
        // Node 1 was 1, has 1 live neighbor (0) -> survives
        assert_eq!(next.nodes[1], 1);
    }

    #[test]
    fn test_graph_state_step_death() {
        // Line graph: 0-1-2
        let nodes = vec![1, 0, 0];
        let adjacency = vec![
            vec![1],
            vec![0, 2],
            vec![1],
        ];
        let gs = GraphState::new(nodes, adjacency);
        // Rule: birth on 2, survival on 2,3
        let rule = Rule::new(vec![2], vec![2, 3]);
        let next = gs.step(&rule);
        // Node 0 was 1, has 0 live neighbors -> dies
        assert_eq!(next.nodes[0], 0);
        // Node 1 was 0, has 1 live neighbor -> no birth
        assert_eq!(next.nodes[1], 0);
    }

    #[test]
    fn test_rule_apply() {
        let rule = Rule::new(vec![3], vec![2, 3]);
        assert_eq!(rule.apply(0, 3), 1); // birth
        assert_eq!(rule.apply(0, 2), 0); // no birth
        assert_eq!(rule.apply(1, 2), 1); // survive
        assert_eq!(rule.apply(1, 3), 1); // survive
        assert_eq!(rule.apply(1, 1), 0); // death
    }
}
