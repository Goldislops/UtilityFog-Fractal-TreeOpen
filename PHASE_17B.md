# Phase 17b — CuPy Streams + Shard Protocol

**Status**: Design (CPU-only recon while Medusa bakes at gen 1,531,725 on Phase 17a)
**Branch**: `claude/amazing-visvesvaraya-a2912f`
**Date**: 2026-04-20

## Why Ray Got Reclassified

AURA's Phase 17 prompt recommended Ray for "sharding 256³ lattice across GPU streams on one 5090." On inspection, that's a category mismatch:

| Tool | Designed for | Fits Phase 17b? |
|------|-------------|-----------------|
| Ray | Distributing actors across **nodes** / processes | No — we have one machine |
| CuPy streams | Concurrent GPU work on **one device** | **Yes** — this is what we want |
| MPI / ZMQ | Node-to-node message passing | Later (Phase 18+) |

Plus two hard blockers on Ray right now:
1. **No Python 3.14 wheels.** `pip install ray` fails cold. Would need a separate venv.
2. **No cluster connectivity.** Vanguard nodes have no Python/Ray/SSH. Nothing to distribute *to*.

Ray goes back in the toolbox until (a) wheels ship for 3.14 or we bring up a 3.11/3.12 venv, and (b) cluster nodes have the runtime installed. Neither is today's problem.

## What Phase 17b Actually Is

Two independent tracks, both foundation-level:

### Track A — CuPy Streams (real single-GPU speedup)

Current stepping uses `cp.cuda.Stream.null` (default stream) throughout `continuous_evolution_ca.py`. Everything serializes on one stream. Three clean opportunities for concurrent streams:

1. **Per-state neighbor counting** (`count_neighbors_gpu` in `scripts/gpu_accelerator.py:36-50`). Runs a 5-iteration loop — one pass per CA state. Each iteration is independent. → **5 concurrent streams**, one per state.

2. **Magnon box filter** (Phase 17a, `_separable_box_filter_3d`). Three sequential passes (X, Y, Z). The separable axis passes are dependent, but within each axis the slabs along the other two axes are independent. → **Stream-per-slab group** for the expensive R=32 filter at 512³.

3. **Memory grid channel updates** (8 channels, Phase 6a–6c). Most per-channel updates are independent. → **Up to 8 concurrent streams** on the channel axis.

Expected speedup: hard to predict without measurement. The 5090's SMs are the bottleneck, not kernel launch overhead, so gains come from overlapping memory transfers with compute — likely modest (1.2–1.8×) rather than 5× or 8×. Has to be measured.

### Track B — Shard Protocol (transport-agnostic multi-node foundation)

The *actual* valuable preparation for 512³ distribution, independent of which transport we eventually pick (Ray / MPI / ZMQ / custom TCP):

- **Halo exchange spec**: what slice of the lattice borders need to be exchanged each step, and at what granularity. For 512³ split 2×2×2 across 8 octants, each shard needs a 1-voxel (or R-voxel for Phase 17a magnon) halo from its 26 neighbors.
- **Shard serialization format**: compact binary encoding of (state_slab, memory_grid_slab, generation_counter). Needs to be transport-agnostic — no Ray / MPI types leaking in.
- **Synchronization protocol**: lockstep vs. bounded-async. Phase 6c signal_interval=10 gives us natural async windows; halo exchange only needs to happen every N steps, not every step.
- **Coherence guarantees**: what invariants survive a sharded step vs. monolithic step. Phase 17a magnon field is long-range (R=32 at 512³) — that's 1/8 of an octant's 64-voxel edge, so magnon halos are substantial.

Deliverable: a `scripts/shard_protocol.py` module that defines the interfaces (`ShardState`, `HaloExchange`, `StepCoordinator`) as pure-Python with zero transport dependencies. Ray / MPI / etc. plug in as backends later.

## What to Benchmark (when Medusa can pause)

Must not run while Medusa is active — GPU is at 92% and she'd starve.

1. **Baseline**: current default-stream stepping at 64³, 128³, 256³ (10 generations each).
2. **Track A variant 1**: 5-stream per-state neighbor counting only. Measure wall-clock.
3. **Track A variant 2**: 8-stream memory channel updates only. Measure wall-clock.
4. **Track A combined**: both above simultaneously. Measure wall-clock.
5. **Sanity**: verify bitwise-identical output vs. baseline (no race-induced drift).

Benchmark harness lives in `scripts/gpu_benchmark.py` (already exists, extend it).

## Out of Scope (Phase 17b is NOT)

- Cluster deployment — Vanguard nodes aren't provisioned
- Ray installation — needs a 3.11 venv and cluster connectivity
- Actual 512³ runs — waiting on shard protocol + multi-node
- Nemo / local LLM — we cancelled Kimi/Nemo; no local model running
- STL mesh evaluation by vision model — no multimodal model installed
- Riemann zero Sage placement — Sages self-organize, don't get placed

## What Happens Next

1. Kevin reviews this doc.
2. When Medusa is paused (snapshot + shutdown), run the Track A benchmark matrix.
3. If Track A shows meaningful speedup (≥1.3× on 256³): implement it in `continuous_evolution_ca.py`.
4. Implement `scripts/shard_protocol.py` as pure-Python interfaces (no transport).
5. At that point, Phase 17b is done. Phase 18 = first transport backend + two-shard test.

---

*Honest engineering: we can't test distributed without a cluster, and we can't run Ray without wheels. But we can lay down real foundations on the single GPU we do have, and design the protocol that outlives the transport choice.*
