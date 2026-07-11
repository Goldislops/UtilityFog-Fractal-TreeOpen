//! LAB-CRNG-v1 — ISOLATED LABORATORY implementation of the counter-indexed
//! RNG specified in `docs/COUNTER_INDEXED_RNG_FEASIBILITY.md` (PR #315),
//! Appendix A.1, implemented verbatim.
//!
//! LABORATORY-ONLY: non-cryptographic, carries no statistical-quality claim,
//! and is NOT approved for production physics. Nothing under `src/` consumes
//! this module. Any algorithm or constant change must bump
//! `LAB_STREAM_VERSION` so replay identity cannot silently drift.
//!
//! This module is shared by the golden/correctness test target and the
//! Criterion benchmark; it lives under `benches/support/` deliberately so
//! Cargo target auto-discovery does not treat it as an independent
//! benchmark target.
#![allow(dead_code)]

/// Version constant folded into the stream (spec: VERSION = 1).
pub const LAB_STREAM_VERSION: u64 = 1;

/// First 64 fractional bits of pi (spec: DOMAIN).
pub const DOMAIN: u64 = 0x243F_6A88_85A3_08D3;

/// Stafford variant-13 multipliers (spec: M1, M2).
const M1: u64 = 0xBF58_476D_1CE4_E5B9;
const M2: u64 = 0x94D0_49BB_1331_11EB;

/// Exact 2^-24 as f32 (power of two — exactly representable).
const F32_SCALE: f32 = 1.0 / ((1u32 << 24) as f32);

/// The full deterministic draw coordinate.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct CounterKey {
    pub seed: u64,
    pub generation: u32,
    pub phase_id: u16,
    pub voxel_index: u64,
    pub draw_lane: u16,
}

/// Spec A.1 `mix64` — all arithmetic u64 mod 2^64, explicit wrapping
/// multiplication, logical right shifts.
#[inline]
pub fn mix64(mut z: u64) -> u64 {
    z = (z ^ (z >> 30)).wrapping_mul(M1);
    z = (z ^ (z >> 27)).wrapping_mul(M2);
    z ^ (z >> 31)
}

/// Spec A.1 `counter_u64` — fixed fold order: version-domain, seed,
/// generation, phase/lane pack, voxel index. Narrow fields zero-extend.
#[inline]
pub fn counter_u64(key: CounterKey) -> u64 {
    let g = u64::from(key.generation);
    let pl = (u64::from(key.phase_id) << 16) | u64::from(key.draw_lane);
    let mut acc = mix64(DOMAIN ^ LAB_STREAM_VERSION);
    acc = mix64(acc ^ key.seed);
    acc = mix64(acc ^ g);
    acc = mix64(acc ^ pl);
    acc = mix64(acc ^ key.voxel_index);
    acc
}

/// Spec A.1 `counter_f32` — top 24 bits scaled by exactly 2^-24; the result
/// lies in [0, 1) and can never equal 1.0.
#[inline]
pub fn counter_f32(key: CounterKey) -> f32 {
    let top24 = counter_u64(key) >> 40;
    (top24 as f32) * F32_SCALE
}

/// Dense materialization: element `i` equals `counter_f32` of `base` with
/// `voxel_index = i` (row-major flat index semantics; other fields fixed).
pub fn materialize_dense(base: CounterKey, len: usize) -> Vec<f32> {
    (0..len as u64)
        .map(|i| {
            counter_f32(CounterKey {
                voxel_index: i,
                ..base
            })
        })
        .collect()
}
