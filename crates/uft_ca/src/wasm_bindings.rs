//! WASM bindings for the CA kernel via wasm-bindgen.
//!
//! Exports WasmLattice struct with methods for genome loading, stepping,
//! and efficient data transfer to JavaScript (zero-copy views where possible).

use wasm_bindgen::prelude::*;
use js_sys::{Uint8Array, Float32Array};

use crate::voxel_lattice::VoxelLattice;
use crate::params::FullConfig;
use crate::genome;
use crate::stepper;
use crate::metrics::StepMetrics;
use crate::rng_util;
use crate::memory::{VOID, MEMORY_CHANNELS, CH_COMPUTE_AGE};

#[wasm_bindgen]
pub struct WasmLattice {
    inner: VoxelLattice,
    config: FullConfig,
    rng: rng_util::CaRng,
    last_metrics: StepMetrics,
}

#[wasm_bindgen]
impl WasmLattice {
    /// Create a new empty lattice of given size with default config.
    #[wasm_bindgen(constructor)]
    pub fn new(size: usize) -> Self {
        Self {
            inner: VoxelLattice::new(size),
            config: FullConfig::default(),
            rng: rng_util::create_rng_from_entropy(),
            last_metrics: StepMetrics::default(),
        }
    }

    /// Create lattice from a genome JSON string.
    pub fn from_genome(json_str: &str, size: usize) -> Result<WasmLattice, JsValue> {
        let config = genome::parse_genome(json_str)
            .map_err(|e| JsValue::from_str(&e))?;

        // Initialize lattice with default structure
        let mut lattice = VoxelLattice::new(size);

        // Seed with a small initial structure (center blob)
        let center = size / 2;
        let r = size / 6;
        for z in 0..size {
            for y in 0..size {
                for x in 0..size {
                    let dx = (x as isize - center as isize).abs();
                    let dy = (y as isize - center as isize).abs();
                    let dz = (z as isize - center as isize).abs();
                    let dist = ((dx * dx + dy * dy + dz * dz) as f32).sqrt();
                    let idx = z * size * size + y * size + x;
                    if dist < r as f32 {
                        lattice.states[idx] = 1; // STRUCTURAL
                    } else if dist < (r as f32 * 1.3) {
                        lattice.states[idx] = 3; // ENERGY
                    }
                }
            }
        }
        // Place some COMPUTE and SENSOR in center
        let ci = center * size * size + center * size + center;
        lattice.states[ci] = 2; // COMPUTE
        if ci + 1 < lattice.len() { lattice.states[ci + 1] = 4; } // SENSOR

        Ok(WasmLattice {
            inner: lattice,
            config,
            rng: rng_util::create_rng_from_entropy(),
            last_metrics: StepMetrics::default(),
        })
    }

    /// Step one generation. Returns metrics JSON string.
    pub fn step(&mut self) -> String {
        self.last_metrics = stepper::step(&mut self.inner, &self.config, &mut self.rng);
        self.last_metrics.to_json()
    }

    /// Step N generations. Returns final metrics JSON string.
    pub fn step_n(&mut self, n: u32) -> String {
        self.last_metrics = stepper::step_n(&mut self.inner, &self.config, &mut self.rng, n);
        self.last_metrics.to_json()
    }

    /// Get the state buffer as Uint8Array (copy to JS).
    pub fn state_buffer(&self) -> Uint8Array {
        unsafe {
            Uint8Array::view(&self.inner.states)
        }
    }

    /// Get a memory channel as Float32Array.
    pub fn memory_channel(&self, ch: usize) -> Float32Array {
        let data: Vec<f32> = self.inner.memory.iter().map(|m| m[ch.min(7)]).collect();
        unsafe { Float32Array::view(&data) }
    }

    /// Get render data: for each non-void cell, [x, y, z, state, age].
    /// Returns a Float32Array of length 5 * num_non_void_cells.
    pub fn render_data(&self) -> Float32Array {
        let mut data = Vec::new();
        let size = self.inner.size;
        for z in 0..size {
            for y in 0..size {
                for x in 0..size {
                    let idx = z * size * size + y * size + x;
                    let state = self.inner.states[idx];
                    if state != VOID {
                        data.push(x as f32);
                        data.push(y as f32);
                        data.push(z as f32);
                        data.push(state as f32);
                        data.push(self.inner.memory[idx][CH_COMPUTE_AGE]);
                    }
                }
            }
        }
        unsafe { Float32Array::view(&data) }
    }

    /// Get the grid size.
    pub fn size(&self) -> usize {
        self.inner.size
    }

    /// Get the current generation.
    pub fn generation(&self) -> u32 {
        self.inner.generation
    }

    /// Get census as JSON string.
    pub fn census(&self) -> String {
        self.last_metrics.to_json()
    }

    /// Set a deterministic seed for reproducible runs.
    pub fn set_seed(&mut self, seed: u64) {
        self.rng = rng_util::create_rng(seed);
    }
}
