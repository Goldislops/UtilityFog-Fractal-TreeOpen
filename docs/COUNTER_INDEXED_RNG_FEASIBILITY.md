# Counter-Indexed RNG — Feasibility & Correctness Contract (v1)

> **Status:** feasibility contract only. Nothing here changes production code, physics,
> or the live engine. The companion laboratory (PR 2, `claude/counter-rng-lab`) is an
> isolated experiment under `crates/uft_ca/benches/` and is **not** integrated into the
> stepper. **Scope: the maintained CPU `uft_ca` kernel only** — nothing in this document
> generalizes to the live Python/GPU engine, which was not read for this work.
>
> **Origin:** Kev-authorized runway (2026-07-11), derived from the AURA v3 architecture
> study as corrected by its errata (recorded in the runway authorization and the
> consolidated audit packet). This document supersedes the study's unmeasured RNG-traffic
> claims: **all performance statements below are hypotheses until measured.**

---

## A. Current consumption map (`crates/uft_ca/src/stepper.rs`, one `step()` call)

All vectors are drawn from **one sequential seeded Xoshiro256\*\* stream**
(`rng_util.rs:12`, `pub type CaRng = Xoshiro256StarStar`) in fixed program order:
`(0..n3).map(|_| rng.gen::<f32>()).collect()`. Trajectory identity is therefore defined
by the *sequence and count* of draws — every row below is alignment-critical: any change
to whether or when a vector is generated re-times all later draws.

| Vector | Generated at | Consumed by | Conditionality | Consuming cells (evidence) | Lifetime / coexistence |
|---|---|---|---|---|---|
| `rng_vals` | `stepper.rs:32` | Phase 2.5 Anti-Star (`:67`); Phase 3 equanimity mask (`phase4.rs:38`) | Generation **unconditional**; Anti-Star consumption gated by `params.antistar_enabled` (default `true`, `memory.rs:179`) | VOID cells with ≥1 COMPUTE neighbor (nucleation, `:66`); COMPUTE cells (resist check, `phase4.rs:38`) | **Function-scoped** — allocated before Phase 1, last read at `:92`, freed at end of `step()`; coexists with every later vector |
| `rng_vals2` | `:110` | Phase 5 nervous system → `apply_compassion` (`phase6c.rs:90`) | **Interval-conditional**: `signal_interval > 0 && gen % signal_interval == 0` (default interval 10, `memory.rs:177`) | Mature COMPUTE (compassion donation, `phase6c.rs:139–141`) | Block-scoped |
| `rng_vals3` | `:123` | Phase 6 `apply_stochastic` (`:211+`) | `config.stochastic.enabled` (**default `true`**, `params.rs:26`) | Per-state stochastic transitions (e.g. STRUCTURAL→ENERGY/SENSOR probs, `params.rs:14–15`) | Block-scoped |
| `rng_vals4` | `:129` | Phase 7 `apply_forward_contagion` (`:246+`) | `config.contagion.enabled` (**default `true`**, `params.rs:55`) | Contagion-eligible non-VOID cells (`:250`) | Block-scoped |
| `rng_vals5` | `:135` | Phase 8 `apply_reverse_contagion` (`:282–290`) | **Unconditional** | STRUCTURAL with COMPUTE neighbors (reclaim, `:290`) | Block-scoped |
| `rng_vals6` | `:149` | Phase 11 `apply_energy_conversion` (`:333–345`) | **Unconditional** | ENERGY/COMPUTE (biofilm leech `:340`, 5% branch `:345`) | Block-scoped |
| `rng_vals7` | `:161` | Phase 13 `apply_decay_resistance` (`:426–472`) | **Unconditional** | Non-VOID decay candidates (`decay_prob` draw, `:472`) | Block-scoped |
| `rng_vals8` | `:174` | Phase 15 `apply_analogue_mutation` (`:483–493`) | **Unconditional** | Non-VOID cells (`pre_mut[i] != VOID`, `:490`); the same value is reused for the replacement-state pick (`:493`) | Block-scoped |

**Counts (source-exact):** 5 unconditionally generated vectors (`rng_vals`, `rng_vals5`–`rng_vals8`)
+ 2 default-enabled conditional vectors (`rng_vals3`, `rng_vals4`) = **7 per ordinary
default-configuration generation**; **8 on signal generations** (default: every 10th).
Disabled stochastic/contagion configurations generate fewer. Phase 10 inactivity decay
(`:143–145`) and Phase 5's every-step `decay_cooldown` (`:119`) consume **no** RNG.

**Peak coexistence:** `rng_vals` is function-scoped and outlives its last read (Rust
frees it at end of `step()`), while each later vector is block-scoped and dropped before
the next is generated ⇒ **at most ~2 vector payloads are simultaneously allocated**,
not 7–8. Allocator capacity reuse and transient copies are **unmeasured**.

## B. Memory arithmetic

Definitions: 1 MiB = 2²⁰ bytes (binary); 1 MB = 10⁶ bytes (decimal). One f32 = 4 bytes.
256³ is **analytical only** — nothing at that size is allocated or run by this work.

| Quantity | 32³ (32,768) | 64³ (262,144) | 96³ (884,736) | 256³ (16,777,216) |
|---|---|---|---|---|
| One f32 vector | 128 KiB / 131.1 kB | 1 MiB / 1.049 MB | 3.375 MiB / 3.539 MB | **64 MiB / 67.11 MB** |
| 7-vector aggregate (generated, ordinary gen) | 896 KiB / 0.918 MB | 7 MiB / 7.34 MB | 23.625 MiB / 24.77 MB | **448 MiB / 469.8 MB** |
| 8-vector aggregate (signal gen) | 1 MiB / 1.049 MB | 8 MiB / 8.39 MB | 27 MiB / 28.31 MB | **512 MiB / 536.9 MB** |
| Peak simultaneous RNG payload (~2 vectors) | 256 KiB / 262.1 kB | 2 MiB / 2.10 MB | 6.75 MiB / 7.08 MB | 128 MiB / 134.2 MB |
| Memory grid (8 × f32 = 32 B/voxel) | 1 MiB / 1.049 MB | 8 MiB / 8.39 MB | 27 MiB / 28.31 MB | 512 MiB / 536.9 MB |
| `states` (u8) | 32 KiB | 256 KiB | 864 KiB | 16 MiB / 16.78 MB |
| `inactivity_steps` (i16) | 64 KiB | 512 KiB | 1.6875 MiB | 32 MiB / 33.55 MB |
| `age_grid` (f32) | 128 KiB | 1 MiB | 3.375 MiB | 64 MiB / 67.11 MB |
| `half_step_flags` (`Vec<bool>`, **1 B/element**) | 32 KiB | 256 KiB | 864 KiB | 16 MiB / 16.78 MB |

**`Vec<bool>` correction (direct evidence contradicts the bit-packed assumption):** in
Rust, `bool` is guaranteed 1 byte and `Vec<T>` stores contiguous `T`; unlike C++'s
`std::vector<bool>`, **Rust's `Vec<bool>` is not bit-packed**. Arithmetic above uses
1 B/element accordingly.

**Other principal per-step transients** (from `step()` source): `out` state clone
(u8, `:39`) and `pre_mut` clone (`:173`) — 16 MiB each at 256³; `neighbor_counts`
(`[i16; 5]`/cell, `:35`) — **160 MiB at 256³, the largest single transient**;
`nonvoid_counts` (i16, `:36`) — 32 MiB. Allocator behavior, capacity growth and
transient-copy effects are **unmeasured** and excluded from the totals above.

## C. Semantic contracts (five distinct properties — none implies the next)

1. **Existing Xoshiro sequential-stream determinism.** Given (seed, initial state,
   config), the current kernel replays exactly: draws come from one serial stream in
   fixed program order. *Established by construction* (`stepper.rs`, `rng_util.rs`).
2. **Dense-pre-draw / sparse-apply trajectory preservation.** If vectors continue to be
   generated **densely, in the identical order and count**, but are *consumed* sparsely,
   the existing trajectory is preserved bit-for-bit. Preservation lives in generation,
   not consumption. (Design option; not implemented here.)
3. **Counter-indexed access-order independence.** A pure function of a key tuple returns
   the same value regardless of traversal order, thread schedule, or which other keys
   are queried. *This is the property the laboratory demonstrates.*
4. **Statistical similarity.** Counter output distribution ≈ Xoshiro output distribution
   by statistical tests. **Not established by (3)** and not claimed by the laboratory.
5. **Existing-trajectory identity.** Counter-indexed draws produce a **different random
   stream** from sequential Xoshiro and therefore **different trajectories** — even with
   the same seed. **(3) does not establish (4) or (5); nothing in this contract or the
   laboratory claims the new stream preserves existing Medusa trajectories.**

## D. Counter-key proposal (proposed, not canonized)

Proposed key tuple:

```text
{ seed: u64, generation: u32, phase_id: u16, voxel_index: u64, draw_lane: u16 }
```

Requirements any implementation must meet:

- **Domain separation:** fields folded in a fixed, documented order through a mixing
  chain, with a stream-version constant folded first, so no two distinct tuples collapse
  by field-boundary aliasing.
- **Stable integer widths:** exactly the widths above; widening or reordering is a
  stream-version change.
- **No dependence on traversal order or thread scheduling:** output is a pure function
  of the tuple; no global mutable state.
- **Deterministic mapping to `[0,1)`:** upper 24 bits of the mixed u64, scaled by 2⁻²⁴ —
  yields at most (2²⁴−1)/2²⁴ < 1.0; can never produce 1.0.
- **Versioning:** a `LAB_STREAM_VERSION` constant participates in mixing; any algorithm
  or constant change must bump it so replay identity cannot silently drift (golden-vector
  tests make drift visible).
- **No cryptographic-security claim** — the mixer is a statistical utility, never a
  security primitive.
- **No collision-freedom claim:** with a 64-bit output space, output coincidences across
  large key populations are expected (birthday behavior) and acceptable for f32 use;
  key→output determinism is what matters, and nothing more is claimed.

## E. Sparse / quiescence analysis (per-phase inventory)

Phases able to **create a non-VOID state**: Phase 2 transition table (VOID + dominant
neighbor — requires a non-VOID cell in the 26-Moore shell, `:44`); Phase 2.5 Anti-Star
(VOID with ≥1 COMPUTE neighbor, `:66`). **No other phase writes a non-VOID state into a
VOID cell**: stochastic/contagion/energy/decay/mutation all gate on non-VOID sources
(mutation explicitly `pre_mut[i] != VOID`, `:490`).

Phases that **mutate states probabilistically**: 2.5, 6, 7, 8, 11, 13, 15 (table in §A).
Phases that **update memory/counters in otherwise state-unchanged regions**:
`decay_cooldown` every step (`:119`, memory-wide); memory aging (Phase 12, `:154`);
metta warmth (Phase 9, `:140`); inactivity counters (Phase 10, `:144`); signal-generation
nervous system (Phase 5) including mycelial signal-field iteration.
Phases that **reach beyond the 26-neighbor Moore shell**: Phase 5 only — mindsight radius
12, mycelial `k_iter` 3 (iterative diffusion), compassion `distance_scale` 15
(`memory.rs:87–99`); all others are r ≤ 1.

**Certification result:** an **all-VOID block whose 1-cell halo is also all-VOID cannot
gain a non-VOID state in one tick** — state-quiescence is certifiable from the gating
above, k ticks requiring a width-k all-VOID halo (states only, r = 1 growth). **Exact
preconditions for full (state + memory) quiescence:**

1. Block + width-k halo all-VOID for k ticks (state channel), **and**
2. every memory channel in the block sits at a per-channel fixed point of the
   memory-wide operations (`decay_cooldown`, aging) — zero-valued channels are fixed
   points only if those operations are multiplicative/floor-clamped, which requires a
   dedicated one-file verification of `phase6c::decay_cooldown` and
   `apply_memory_aging` before any use, **and**
3. no signal generation occurs in the window (default: gen % 10 ≠ 0), **or** the
   signal-field/mycelial influx is separately bounded away from the halo, **and**
4. RNG draw alignment is preserved by dense pre-draw or counter indexing (§C.2/C.3) —
   under the current sequential stream, skipping *generation* of any vector changes the
   trajectory globally.

Nothing here implements skipping; this section only states what a future implementation
would have to prove.

## F. Experiment contract (locked questions for the PR 2 laboratory)

The laboratory answers exactly these questions, on CPU toy workloads only:

1. Is counter access **repeatable**? (same tuple → same output, across runs)
2. Is it **independent of lookup order**? (forward / reverse / sparse traversals agree
   per index)
3. Does **dense counter materialization reproduce direct counter lookup** for the same
   indices?
4. What is the **CPU throughput** of: sequential Xoshiro materialization into `Vec<f32>`;
   counter materialization into `Vec<f32>`; direct dense counter consumption (no
   intermediate vector); sparse counter lookup?
5. How do results vary across bounded toy sizes (32³, 64³, optionally 96³) and access
   densities (1%, 10%, 50%)?

**What the experiment cannot prove:** statistical adequacy for Medusa physics;
trajectory equivalence with the existing Xoshiro stream (§C.5 — explicitly different);
any GPU speedup; physics stability under a different stream; or that production
integration is safe. Production integration is out of scope until Jack audits both PRs
and AURA reviews the corrected semantics, and would in any case be a separate
engine/kernel gate.
