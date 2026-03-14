//! Dense 3D voxel lattice with periodic boundaries.
//!
//! Replaces graph-based adjacency for dense grids - much faster for N- stepping.
//! Flat row-major layout: idx = z*N*N + y*N + x

use crate::memory::{self, MEMORY_CHANNELS, VOID};

/// A dense N-N-N voxel lattice with 8-channel memory per voxel.
#[derive(Debug, Clone)]
pub struct VoxelLattice {
    /// Grid dimension (N for N-N-N)
    pub size: usize,
    /// Cell states, flat row-major: z*N*N + y*N + x
    pub states: Vec<u8>,
    /// 8-channel memory per voxel
    pub memory: Vec<[f32; MEMORY_CHANNELS]>,
    /// Inactivity step counter per voxel
    pub inactivity_steps: Vec<i16>,
    /// Age grid (continuous age for COMPUTE cells)
    pub age_grid: Vec<f32>,
    /// Current generation
    pub generation: u32,
    /// Half-step flags for isolated COMPUTE cells
    pub half_step_flags: Vec<bool>,
}

impl VoxelLattice {
    /// Create a new lattice of given size, initialized to VOID with default memory.
    pub fn new(size: usize) -> Self {
        let n3 = size * size * size;
        Self {
            size,
            states: vec![VOID; n3],
            memory: vec![memory::init_memory(); n3],
            inactivity_steps: vec![0i16; n3],
            age_grid: vec![0.0f32; n3],
            generation: 0,
            half_step_flags: vec![false; n3],
        }
    }

    /// Total number of voxels.
    #[inline]
    pub fn len(&self) -> usize {
        self.size * self.size * self.size
    }

    /// Check if lattice is empty (0-sized).
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.size == 0
    }

    /// Convert (x, y, z) to flat index with periodic wrapping.
    #[inline]
    pub fn idx(&self, x: isize, y: isize, z: isize) -> usize {
        let n = self.size as isize;
        let wx = ((x % n) + n) % n;
        let wy = ((y % n) + n) % n;
        let wz = ((z % n) + n) % n;
        (wz as usize) * self.size * self.size + (wy as usize) * self.size + (wx as usize)
    }

    /// Convert flat index to (x, y, z).
    #[inline]
    pub fn coords(&self, idx: usize) -> (usize, usize, usize) {
        let z = idx / (self.size * self.size);
        let rem = idx % (self.size * self.size);
        let y = rem / self.size;
        let x = rem % self.size;
        (x, y, z)
    }

    /// Get state at (x, y, z) with periodic wrapping.
    #[inline]
    pub fn get_state(&self, x: isize, y: isize, z: isize) -> u8 {
        self.states[self.idx(x, y, z)]
    }

    /// Set state at (x, y, z) with periodic wrapping.
    #[inline]
    pub fn set_state(&mut self, x: isize, y: isize, z: isize, state: u8) {
        let i = self.idx(x, y, z);
        self.states[i] = state;
    }

    /// Initialize from flat state array and optional memory grid.
    pub fn from_arrays(
        size: usize,
        states: Vec<u8>,
        memory_grid: Option<Vec<[f32; MEMORY_CHANNELS]>>,
    ) -> Self {
        let n3 = size * size * size;
        assert_eq!(states.len(), n3, "states length must be size^3");
        let mem = memory_grid.unwrap_or_else(|| vec![memory::init_memory(); n3]);
        assert_eq!(mem.len(), n3, "memory length must be size^3");
        Self {
            size,
            states,
            memory: mem,
            inactivity_steps: vec![0i16; n3],
            age_grid: vec![0.0f32; n3],
            generation: 0,
            half_step_flags: vec![false; n3],
        }
    }
}
