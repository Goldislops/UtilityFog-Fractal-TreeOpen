//! Golden-vector and correctness suite for the ISOLATED counter-RNG
//! laboratory (LAB-CRNG-v1; docs/COUNTER_INDEXED_RNG_FEASIBILITY.md, PR #315
//! Appendix A). Golden fixtures below are the ten AUDITED vectors from that
//! appendix — independently dual-formulation derived (Node BigInt + .NET
//! BigInteger); they were NOT regenerated from this Rust implementation.
//!
//! Scope note (binding): this laboratory proves the integer generator and
//! its f32 projection against the locked specification. It does NOT prove
//! cross-platform full-physics trajectory identity — the production kernel
//! contains floating-point operations, so full replay remains
//! target/build-sensitive. No injectivity is claimed: distinct keys may
//! legitimately collide in 64 (and especially 24) output bits.

#[path = "../benches/support/counter_rng.rs"]
mod counter_rng;

use counter_rng::{
    counter_f32, counter_u64, materialize_dense, mix64, CounterKey, LAB_STREAM_VERSION,
};

/// (id, seed, generation, phase_id, voxel_index, draw_lane, u64, top24, f32_bits)
const GOLDENS: [(&str, u64, u32, u16, u64, u16, u64, u64, u32); 10] = [
    (
        "T1 zero",
        0,
        0,
        0,
        0,
        0,
        0x966C_920F_E8E9_DA97,
        9_858_194,
        0x3F16_6C92,
    ),
    (
        "T2 max seed",
        u64::MAX,
        0,
        0,
        0,
        0,
        0x9BBC_F84A_6EBF_14FD,
        10_206_456,
        0x3F1B_BCF8,
    ),
    (
        "T3 all max",
        u64::MAX,
        u32::MAX,
        u16::MAX,
        u64::MAX,
        u16::MAX,
        0x88D7_2CB6_D8EE_6248,
        8_967_980,
        0x3F08_D72C,
    ),
    (
        "T4 gen boundary",
        42,
        u32::MAX,
        6,
        137,
        0,
        0x9E74_7B63_04BB_FFF3,
        10_384_507,
        0x3F1E_747B,
    ),
    (
        "T5 base",
        42,
        1000,
        6,
        137,
        0,
        0xAF38_00A6_97FA_60B3,
        11_483_136,
        0x3F2F_3800,
    ),
    (
        "T6 adjacent index",
        42,
        1000,
        6,
        138,
        0,
        0x5371_121A_AAE8_0CA2,
        5_468_434,
        0x3EA6_E224,
    ),
    (
        "T7 adjacent phase",
        42,
        1000,
        7,
        137,
        0,
        0x38BD_0EC2_2AA0_2C6C,
        3_718_414,
        0x3E62_F438,
    ),
    (
        "T8 adjacent lane",
        42,
        1000,
        6,
        137,
        1,
        0x98A8_A9BC_D1C8_26C9,
        10_004_649,
        0x3F18_A8A9,
    ),
    (
        "T9 realistic",
        424_242,
        1_000_000,
        6,
        8_421_376,
        0,
        0xA76D_5375_0315_95F3,
        10_972_499,
        0x3F27_6D53,
    ),
    (
        "T10 wrap boundary",
        1 << 63,
        1 << 31,
        1 << 15,
        1 << 63,
        1 << 15,
        0x43AF_ED72_9359_3EAF,
        4_435_949,
        0x3E87_5FDA,
    ),
];

fn key(seed: u64, generation: u32, phase_id: u16, voxel_index: u64, draw_lane: u16) -> CounterKey {
    CounterKey {
        seed,
        generation,
        phase_id,
        voxel_index,
        draw_lane,
    }
}

/// FAIL-CLOSED GOLDEN LADDER — checked strictly in the audited order:
/// (1) exact u64 equality, (2) exact top-24 equality, (3) exact
/// f32::to_bits equality. Any mismatch is a specification-or-implementation
/// defect and stops the laboratory; never "close enough".
#[test]
fn t00_golden_vectors_fail_closed() {
    // Step 1: exact u64 equality for all ten.
    for (id, s, g, p, i, l, u, _, _) in GOLDENS {
        assert_eq!(counter_u64(key(s, g, p, i, l)), u, "u64 mismatch at {id}");
    }
    // Step 2: exact top-24 equality for all ten.
    for (id, s, g, p, i, l, _, top24, _) in GOLDENS {
        assert_eq!(
            counter_u64(key(s, g, p, i, l)) >> 40,
            top24,
            "top24 mismatch at {id}"
        );
    }
    // Step 3: exact f32 bit-pattern equality for all ten.
    for (id, s, g, p, i, l, _, _, bits) in GOLDENS {
        assert_eq!(
            counter_f32(key(s, g, p, i, l)).to_bits(),
            bits,
            "f32 bits mismatch at {id}"
        );
    }
}

#[test]
fn same_key_repeats_identically() {
    let k = key(424_242, 1_000_000, 6, 8_421_376, 0);
    for _ in 0..8 {
        assert_eq!(counter_u64(k), 0xA76D_5375_0315_95F3);
        assert_eq!(counter_f32(k).to_bits(), 0x3F27_6D53);
    }
}

#[test]
fn version_constant_is_locked() {
    assert_eq!(LAB_STREAM_VERSION, 1);
}

#[test]
fn mix64_zero_is_spec_initial_state_component() {
    // mix64 is deterministic and total; boundary inputs must not panic.
    let _ = mix64(0);
    let _ = mix64(u64::MAX);
    let _ = mix64(1 << 63);
}

#[test]
fn boundary_keys_do_not_panic_and_map_to_unit_interval() {
    let boundary = [
        key(0, 0, 0, 0, 0),
        key(u64::MAX, u32::MAX, u16::MAX, u64::MAX, u16::MAX),
        key(1 << 63, 1 << 31, 1 << 15, 1 << 63, 1 << 15),
        key(u64::MAX, 0, u16::MAX, 0, u16::MAX),
        key(0, u32::MAX, 0, u64::MAX, 0),
    ];
    for k in boundary {
        let v = counter_f32(k);
        assert!((0.0..1.0).contains(&v), "out of [0,1) at {k:?}: {v}");
    }
}

#[test]
fn outputs_always_in_unit_interval_across_a_sweep() {
    for n in 0..10_000u64 {
        let v = counter_f32(key(
            n.wrapping_mul(0x9E37_79B9),
            (n as u32) << 7,
            (n % 9) as u16,
            n * 31,
            (n % 3) as u16,
        ));
        assert!((0.0..1.0).contains(&v));
    }
}

#[test]
fn dense_materialization_empty_singleton_ordinary() {
    let base = key(42, 1000, 6, 0, 0);
    assert!(materialize_dense(base, 0).is_empty());

    let one = materialize_dense(base, 1);
    assert_eq!(one.len(), 1);
    assert_eq!(
        one[0].to_bits(),
        counter_f32(key(42, 1000, 6, 0, 0)).to_bits()
    );

    let n = 4096;
    let dense = materialize_dense(base, n);
    assert_eq!(dense.len(), n);
    for (i, v) in dense.iter().enumerate() {
        assert_eq!(
            v.to_bits(),
            counter_f32(key(42, 1000, 6, i as u64, 0)).to_bits(),
            "dense[{i}] != counter_f32(key with index {i})"
        );
    }
}

#[test]
fn forward_and_reverse_lookup_agree() {
    let base = key(7, 77, 2, 0, 1);
    let dense = materialize_dense(base, 1024);
    for i in (0..1024usize).rev() {
        assert_eq!(
            dense[i].to_bits(),
            counter_f32(key(7, 77, 2, i as u64, 1)).to_bits()
        );
    }
}

#[test]
fn stride_7_traversal_is_deterministic() {
    let base = key(99, 5, 3, 0, 0);
    let pass = |()| -> Vec<u32> {
        (0..4096u64)
            .step_by(7)
            .map(|i| counter_f32(key(99, 5, 3, i, 0)).to_bits())
            .collect()
    };
    assert_eq!(pass(()), pass(()));
    // And each strided element agrees with dense materialization.
    let dense = materialize_dense(base, 4096);
    for i in (0..4096usize).step_by(7) {
        assert_eq!(
            dense[i].to_bits(),
            counter_f32(key(99, 5, 3, i as u64, 0)).to_bits()
        );
    }
}

#[test]
fn fixed_permutation_lookup_matches_direct() {
    // One fixed permutation of 0..16 (hardcoded; not generated at runtime).
    let perm: [u64; 16] = [9, 3, 15, 0, 12, 7, 1, 14, 5, 11, 2, 8, 13, 4, 10, 6];
    let dense = materialize_dense(key(1234, 9, 4, 0, 0), 16);
    for &i in &perm {
        assert_eq!(
            dense[i as usize].to_bits(),
            counter_f32(key(1234, 9, 4, i, 0)).to_bits()
        );
    }
}

#[test]
fn sparse_sets_match_dense_at_1_10_50_percent() {
    let base = key(55, 123, 6, 0, 0);
    let n = 10_000usize;
    let dense = materialize_dense(base, n);
    for step in [100usize, 10, 2] {
        // Deterministic sparse index sets: every `step`-th index.
        for i in (0..n).step_by(step) {
            assert_eq!(
                dense[i].to_bits(),
                counter_f32(key(55, 123, 6, i as u64, 0)).to_bits(),
                "sparse(step {step}) mismatch at {i}"
            );
        }
    }
}

#[test]
fn field_adjacency_smoke_only() {
    // SMOKE ONLY: the audited adjacent fixtures (T5-T8) differ from each
    // other. No injectivity claim — distinct keys MAY collide in general.
    let t5 = counter_u64(key(42, 1000, 6, 137, 0));
    let t6 = counter_u64(key(42, 1000, 6, 138, 0));
    let t7 = counter_u64(key(42, 1000, 7, 137, 0));
    let t8 = counter_u64(key(42, 1000, 6, 137, 1));
    assert_ne!(t5, t6);
    assert_ne!(t5, t7);
    assert_ne!(t5, t8);
}

#[test]
fn no_global_mutable_state_interleaving() {
    // Interleaving two logical "streams" cannot perturb either: the
    // generator is a pure function of its key (no statics, no RNG state).
    let a = key(1, 1, 1, 0, 0);
    let b = key(2, 2, 2, 0, 1);
    let a_alone: Vec<u64> = (0..64)
        .map(|i| {
            counter_u64(CounterKey {
                voxel_index: i,
                ..a
            })
        })
        .collect();
    let b_alone: Vec<u64> = (0..64)
        .map(|i| {
            counter_u64(CounterKey {
                voxel_index: i,
                ..b
            })
        })
        .collect();
    let mut a_mixed = Vec::new();
    let mut b_mixed = Vec::new();
    for i in 0..64 {
        a_mixed.push(counter_u64(CounterKey {
            voxel_index: i,
            ..a
        }));
        b_mixed.push(counter_u64(CounterKey {
            voxel_index: i,
            ..b
        }));
    }
    assert_eq!(a_alone, a_mixed);
    assert_eq!(b_alone, b_mixed);
}
