//! Bounded Criterion comparison for the ISOLATED counter-RNG laboratory
//! (LAB-CRNG-v1; PR #315 Appendix A). CPU-only; no GPU claim anywhere.
//!
//! Groups are reported SEPARATELY and are not like-for-like proofs of a
//! production speedup:
//!   1. xoshiro_dense    — seeded Xoshiro256** (the engine's CaRng algorithm)
//!                         materializing Vec<f32> via Rng::gen::<f32>().
//!   2. counter_dense    — counter generator materializing Vec<f32>
//!                         (generator cost + allocation cost together).
//!   3. counter_direct   — counter generator consumed directly (checksum),
//!                         no intermediate vector (generator cost alone).
//!   4. counter_sparse   — counter lookups on deterministic 1%/10%/50%
//!                         index sets (skipped-work shape). Index-set
//!                         construction happens OUTSIDE the timed region.
//!
//! Memory statements are analytical, not measured: a dense Vec<f32> holds
//! len × 4 bytes; direct/sparse consumption allocates no intermediate RNG
//! vector. Allocator peak, cache behavior, memory traffic and energy are
//! unmeasured here.

use std::hint::black_box;

use criterion::{criterion_group, criterion_main, Criterion};
use rand::{Rng, SeedableRng};
use rand_xoshiro::Xoshiro256StarStar;

#[path = "support/counter_rng.rs"]
mod counter_rng;
use counter_rng::{counter_f32, materialize_dense, CounterKey};

const SEED: u64 = 424_242;
const GENERATION: u32 = 1_000_000;
const PHASE: u16 = 6;
const LANE: u16 = 0;

// 32^3, 64^3, 96^3 — bounded; no 256^3 allocation anywhere.
const SIZES: [(&str, usize); 3] = [("32c", 32_768), ("64c", 262_144), ("96c", 884_736)];

fn base_key() -> CounterKey {
    CounterKey {
        seed: SEED,
        generation: GENERATION,
        phase_id: PHASE,
        voxel_index: 0,
        draw_lane: LANE,
    }
}

fn checksum(values: impl IntoIterator<Item = f32>) -> f64 {
    values.into_iter().map(f64::from).sum()
}

fn bench_xoshiro_dense(c: &mut Criterion) {
    let mut group = c.benchmark_group("xoshiro_dense_vec_f32");
    group.sample_size(20);
    group.warm_up_time(std::time::Duration::from_secs(1));
    group.measurement_time(std::time::Duration::from_secs(2));
    for (label, n) in SIZES {
        group.bench_function(label, |b| {
            b.iter(|| {
                let mut rng = Xoshiro256StarStar::seed_from_u64(black_box(SEED));
                let v: Vec<f32> = (0..n).map(|_| rng.gen::<f32>()).collect();
                black_box(checksum(v))
            })
        });
    }
    group.finish();
}

fn bench_counter_dense(c: &mut Criterion) {
    let mut group = c.benchmark_group("counter_dense_vec_f32");
    group.sample_size(20);
    group.warm_up_time(std::time::Duration::from_secs(1));
    group.measurement_time(std::time::Duration::from_secs(2));
    for (label, n) in SIZES {
        group.bench_function(label, |b| {
            b.iter(|| {
                let v = materialize_dense(black_box(base_key()), n);
                black_box(checksum(v))
            })
        });
    }
    group.finish();
}

fn bench_counter_direct(c: &mut Criterion) {
    let mut group = c.benchmark_group("counter_direct_no_vec");
    group.sample_size(20);
    group.warm_up_time(std::time::Duration::from_secs(1));
    group.measurement_time(std::time::Duration::from_secs(2));
    for (label, n) in SIZES {
        group.bench_function(label, |b| {
            b.iter(|| {
                let base = black_box(base_key());
                let mut sum = 0.0f64;
                for i in 0..n as u64 {
                    sum += f64::from(counter_f32(CounterKey {
                        voxel_index: i,
                        ..base
                    }));
                }
                black_box(sum)
            })
        });
    }
    group.finish();
}

fn bench_counter_sparse(c: &mut Criterion) {
    let mut group = c.benchmark_group("counter_sparse_lookup");
    group.sample_size(20);
    group.warm_up_time(std::time::Duration::from_secs(1));
    group.measurement_time(std::time::Duration::from_secs(2));
    for (label, n) in SIZES {
        for (pct, step) in [("1pct", 100usize), ("10pct", 10), ("50pct", 2)] {
            // Deterministic index set, built OUTSIDE the timed region
            // (skipped-work construction reported separately from lookup).
            let indices: Vec<u64> = (0..n as u64).step_by(step).collect();
            group.bench_function(format!("{label}_{pct}"), |b| {
                b.iter(|| {
                    let base = black_box(base_key());
                    let mut sum = 0.0f64;
                    for &i in &indices {
                        sum += f64::from(counter_f32(CounterKey {
                            voxel_index: i,
                            ..base
                        }));
                    }
                    black_box(sum)
                })
            });
        }
    }
    group.finish();
}

criterion_group!(
    benches,
    bench_xoshiro_dense,
    bench_counter_dense,
    bench_counter_direct,
    bench_counter_sparse
);
criterion_main!(benches);
