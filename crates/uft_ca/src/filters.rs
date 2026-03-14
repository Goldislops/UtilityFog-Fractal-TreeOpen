//! Performance-critical neighbor operations for 3D voxel lattices.
//!
//! All functions operate on flat arrays with periodic boundary conditions.
//! The box filter uses separable prefix-sum for O(N^3) regardless of radius.

use crate::memory::NUM_STATES;

/// Count 26 Moore neighbors for each voxel, returning per-state counts.
/// Output: Vec of [void, structural, compute, energy, sensor] counts.
pub fn count_neighbors_3d(states: &[u8], size: usize) -> Vec<[i16; NUM_STATES]> {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;
    let mut counts = vec![[0i16; NUM_STATES]; n3];

    for z in 0..n {
        for y in 0..n {
            for x in 0..n {
                let mut c = [0i16; NUM_STATES];
                for dz in [-1i32, 0, 1] {
                    for dy in [-1i32, 0, 1] {
                        for dx in [-1i32, 0, 1] {
                            if dx == 0 && dy == 0 && dz == 0 {
                                continue;
                            }
                            let nx = ((x as i32 + dx).rem_euclid(n as i32)) as usize;
                            let ny = ((y as i32 + dy).rem_euclid(n as i32)) as usize;
                            let nz = ((z as i32 + dz).rem_euclid(n as i32)) as usize;
                            let ni = nz * n2 + ny * n + nx;
                            let s = states[ni].min(4) as usize;
                            c[s] += 1;
                        }
                    }
                }
                counts[z * n2 + y * n + x] = c;
            }
        }
    }
    counts
}

/// Maximum value among 26 Moore neighbors for a scalar field.
/// Used by Phase 6b (max neighbor age) and Phase 6c (signal handoff).
pub fn max_neighbor_value(field: &[f32], size: usize) -> Vec<f32> {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;
    let mut result = vec![0.0f32; n3];

    for z in 0..n {
        for y in 0..n {
            for x in 0..n {
                let mut mx = f32::NEG_INFINITY;
                for dz in [-1i32, 0, 1] {
                    for dy in [-1i32, 0, 1] {
                        for dx in [-1i32, 0, 1] {
                            if dx == 0 && dy == 0 && dz == 0 {
                                continue;
                            }
                            let nx = ((x as i32 + dx).rem_euclid(n as i32)) as usize;
                            let ny = ((y as i32 + dy).rem_euclid(n as i32)) as usize;
                            let nz = ((z as i32 + dz).rem_euclid(n as i32)) as usize;
                            let ni = nz * n2 + ny * n + nx;
                            if field[ni] > mx {
                                mx = field[ni];
                            }
                        }
                    }
                }
                result[z * n2 + y * n + x] = if mx == f32::NEG_INFINITY { 0.0 } else { mx };
            }
        }
    }
    result
}

/// Separable 3D box filter using prefix sums -- O(N^3) regardless of radius.
/// Matches Python cumsum trick for SENSOR density smoothing (mindsight R=12).
pub fn box_filter_3d(field: &[f32], size: usize, radius: usize) -> Vec<f32> {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;

    let mut buf_a = field.to_vec();
    let mut buf_b = vec![0.0f32; n3];

    // Pass 1: filter along X
    for z in 0..n {
        for y in 0..n {
            let row_start = z * n2 + y * n;
            let ext_len = n + 2 * radius;
            let mut ext = vec![0.0f32; ext_len + 1];
            for i in 0..ext_len {
                let xi = ((i as isize - radius as isize).rem_euclid(n as isize)) as usize;
                ext[i + 1] = ext[i] + buf_a[row_start + xi];
            }
            let width = (2 * radius + 1) as f32;
            for x in 0..n {
                buf_b[row_start + x] = (ext[x + 2 * radius + 1] - ext[x]) / width;
            }
        }
    }

    // Pass 2: filter along Y
    buf_a.copy_from_slice(&buf_b);
    for z in 0..n {
        for x in 0..n {
            let ext_len = n + 2 * radius;
            let mut ext = vec![0.0f32; ext_len + 1];
            for i in 0..ext_len {
                let yi = ((i as isize - radius as isize).rem_euclid(n as isize)) as usize;
                ext[i + 1] = ext[i] + buf_a[z * n2 + yi * n + x];
            }
            let width = (2 * radius + 1) as f32;
            for y in 0..n {
                buf_b[z * n2 + y * n + x] = (ext[y + 2 * radius + 1] - ext[y]) / width;
            }
        }
    }

    // Pass 3: filter along Z
    buf_a.copy_from_slice(&buf_b);
    for y in 0..n {
        for x in 0..n {
            let ext_len = n + 2 * radius;
            let mut ext = vec![0.0f32; ext_len + 1];
            for i in 0..ext_len {
                let zi = ((i as isize - radius as isize).rem_euclid(n as isize)) as usize;
                ext[i + 1] = ext[i] + buf_a[zi * n2 + y * n + x];
            }
            let width = (2 * radius + 1) as f32;
            for z in 0..n {
                buf_b[z * n2 + y * n + x] = (ext[z + 2 * radius + 1] - ext[z]) / width;
            }
        }
    }

    buf_b
}

/// Mycelial diffusion: K iterations of masked 3x3x3 averaging through ENERGY cells.
/// Signal propagates only where energy_mask is true, with per-iteration decay.
pub fn mycelial_diffuse(
    signal: &mut [f32],
    energy_mask: &[bool],
    size: usize,
    k_iter: usize,
    decay: f32,
) {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;
    let mut buf = vec![0.0f32; n3];

    for _ in 0..k_iter {
        for z in 0..n {
            for y in 0..n {
                for x in 0..n {
                    let idx = z * n2 + y * n + x;
                    if !energy_mask[idx] {
                        buf[idx] = 0.0;
                        continue;
                    }
                    let mut sum = 0.0f32;
                    let mut cnt = 0u32;
                    for dz in [-1i32, 0, 1] {
                        for dy in [-1i32, 0, 1] {
                            for dx in [-1i32, 0, 1] {
                                let nx = ((x as i32 + dx).rem_euclid(n as i32)) as usize;
                                let ny = ((y as i32 + dy).rem_euclid(n as i32)) as usize;
                                let nz = ((z as i32 + dz).rem_euclid(n as i32)) as usize;
                                let ni = nz * n2 + ny * n + nx;
                                sum += signal[ni];
                                cnt += 1;
                            }
                        }
                    }
                    buf[idx] = (sum / cnt as f32) * decay;
                }
            }
        }
        signal.copy_from_slice(&buf);
    }
}

/// Count non-void neighbors for each voxel (used for isolation detection).
pub fn count_nonvoid_neighbors(states: &[u8], size: usize) -> Vec<i16> {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;
    let mut counts = vec![0i16; n3];

    for z in 0..n {
        for y in 0..n {
            for x in 0..n {
                let mut c = 0i16;
                for dz in [-1i32, 0, 1] {
                    for dy in [-1i32, 0, 1] {
                        for dx in [-1i32, 0, 1] {
                            if dx == 0 && dy == 0 && dz == 0 {
                                continue;
                            }
                            let nx = ((x as i32 + dx).rem_euclid(n as i32)) as usize;
                            let ny = ((y as i32 + dy).rem_euclid(n as i32)) as usize;
                            let nz = ((z as i32 + dz).rem_euclid(n as i32)) as usize;
                            let ni = nz * n2 + ny * n + nx;
                            if states[ni] != 0 {
                                c += 1;
                            }
                        }
                    }
                }
                counts[z * n2 + y * n + x] = c;
            }
        }
    }
    counts
}

/// Deliver signal from source cells to all their neighbors (max-based).
/// Used for SENSOR->ENERGY handoff in mycelial network.
pub fn deliver_to_neighbors(signal: &[f32], source_mask: &[bool], size: usize) -> Vec<f32> {
    let n = size;
    let n2 = n * n;
    let n3 = n * n * n;
    let mut delivered = vec![0.0f32; n3];

    for z in 0..n {
        for y in 0..n {
            for x in 0..n {
                let idx = z * n2 + y * n + x;
                if !source_mask[idx] || signal[idx] == 0.0 {
                    continue;
                }
                let val = signal[idx];
                for dz in [-1i32, 0, 1] {
                    for dy in [-1i32, 0, 1] {
                        for dx in [-1i32, 0, 1] {
                            if dx == 0 && dy == 0 && dz == 0 {
                                continue;
                            }
                            let nx = ((x as i32 + dx).rem_euclid(n as i32)) as usize;
                            let ny = ((y as i32 + dy).rem_euclid(n as i32)) as usize;
                            let nz = ((z as i32 + dz).rem_euclid(n as i32)) as usize;
                            let ni = nz * n2 + ny * n + nx;
                            if val > delivered[ni] {
                                delivered[ni] = val;
                            }
                        }
                    }
                }
            }
        }
    }
    delivered
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_neighbors_center() {
        let mut states = vec![1u8; 27];
        states[13] = 0;
        let counts = count_neighbors_3d(&states, 3);
        assert_eq!(counts[13][1], 26);
    }

    #[test]
    fn test_box_filter_uniform() {
        let field = vec![1.0f32; 64];
        let filtered = box_filter_3d(&field, 4, 1);
        for v in &filtered {
            assert!((v - 1.0).abs() < 1e-5, "Uniform field should stay uniform");
        }
    }

    #[test]
    fn test_periodic_wrapping() {
        let mut states = vec![0u8; 64];
        states[63] = 2;
        let counts = count_neighbors_3d(&states, 4);
        assert_eq!(counts[0][2], 1, "Should see wrapped COMPUTE neighbor");
    }
}
