# Toy #3 Inception — Decaying Scent-Trail Tracking (design only, no script)

> **Status**: inception/design note only. **No script exists yet, and this note authorizes none.** The toy itself lands only in a later, separate PR after Jack/AURA/Kev review this note. Per `experiments/theory_sandbox/README.md`: one toy per PR; this is the *zeroth* brick of Toy #3 — the thinking before the toy.
>
> **NON-CANONICAL TOY (design):** a tracker finding a target faster on a toy grid proves nothing about Medusa. This explores a **falsifiable tracking mechanism**, **not radioactive physics** and **not** engine validation.

## 0. Current model seat

Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-19 (Sydney time), under Phase 2B-5H-1 (Jack-relayed, AURA-confirmed). *(Future seats editing this doc: state your seat here per model-seat hygiene.)*

## 1. Source and status

- **Source**: AURA's "Physics of the Utility Fog" master handover (2026-06-19) → the read-only **Phase 2B-5H-0** formalization audit → `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` **entry 14** (decaying scent trails: *new hypothesis; adjacent primitive exists*), marked **APPROVED FOR DESIGN-INCEPTION ONLY — no engine implementation authorized**.
- **Status**: speculative **discrete tracking metaphor** / sandbox candidate. The originating phrase was "radioactive decay scent trails"; the **preferred vocabulary here is algorithmic** — *decaying integer trail, deposit, decrement, gradient following, reacquisition*. There is no radioactivity, no half-life physics, and none is claimed.
- **Non-canonical. Not architecture evidence.** Adjacent engine primitives exist (memory `signal_field` channel 5 + `_mycelial_diffuse`, plus the decay configs in `continuous_evolution_ca.py`), but this toy deliberately does **not** import or touch them; if the toy ever validates, wiring the idea into those primitives is a **separate, later, gated** arc.

## 2. Precise hypothesis

> On an identical seeded target path, a tracker given access to a decaying integer trail will reacquire the hidden target in fewer steps, or with a higher success rate inside a fixed step budget, than an otherwise-identical tracker using the declared no-trail search policy.

The toy **must be permitted to falsify this** — the trail-reading tracker is allowed to tie, lose, or do worse, and that outcome must be reportable without any hard assertion to the contrary.

## 3. Mechanism requiring review before code (minimal v0 candidate)

A single seeded scenario, run twice — **treatment** (reads trail) and **control** (cannot read trail) — differing by **exactly one variable: trail availability**.

- **Grid**: small 2D integer grid, e.g. `N × N` with `N ≈ 24–32`. **Bounded (non-toroidal)** — *recommended* (see §9): a hard boundary keeps "hidden target", distance and reacquisition geometry interpretable and avoids wrap-around gradient artifacts.
- **Phases**: a short **visible phase** (target in a declared start cell, no trail yet), then at a fixed declared step `T_jump` the target **jumps** to a seeded destination and follows a seeded **hidden path** for the remainder.
- **Trail deposit**: deposition **begins only after the jump** (*recommended stale-trail handling*, §9): each hidden-phase step sets `trail[target_pos] = A` (deposit amplitude). Because there is no pre-jump trail, there is no stale trail pointing at the abandoned pre-jump location — both arms are identical pre-jump and the trail exists only where it is experimentally relevant.
- **Decay (integer-only, exact rounding)**: every step, for all cells, `trail = max(0, trail - D)` (constant integer **decrement**, clamp at 0). *Recommended over multiplicative decay*: integer linear decrement has unambiguous rounding (no float floor/round), gives a clean finite lifetime `≈ A / D` steps, and makes byte-identical determinism trivial. Freshly-deposited cells hold higher values than older ones → an **along-trail freshness gradient pointing toward the current target**.
- **Diffusion**: **none in v0**. The usable local gradient is the *along-trail* freshness gradient (newer deposits = higher value = toward target); a tracker standing on a trail cell can read its neighbourhood and step toward the higher (fresher) value. The known limitation — a tracker *off* the trail senses nothing locally — is examined directly in §9 (acquisition geometry) rather than papered over with diffusion. Diffusion is deferred to a possible v1 only if v0 shows the gradient is unusable.
- **Tracker (deterministic)**: starts at the target's last-seen (pre-jump) cell.
  - **Treatment**: if the current cell or a neighbour has `trail > 0`, step to the neighbour with the **highest** trail value (deterministic tie-break, e.g. lowest `(row, col)`); else fall back to the **declared control search policy**.
  - **Control**: always uses the declared search policy; never inspects `trail`.
- **Declared control search policy**: a deterministic **expanding-ring / spiral sweep** outward from the last-seen cell (fully specified, seed-independent). Both arms share it; only the treatment additionally reads the trail when on it.
- **Reacquisition**: tracker occupies the target's **current** cell (Chebyshev radius `r = 0` *recommended*; `r = 1` noted as an alternative in §9).
- **Step budget**: fixed, modest, e.g. `≈ 6 × N` steps after the jump. **Small fixed seed table** (e.g. 8–16 seeds), **not** an unbounded sweep.

## 4. Metrics

**Primary**
- **steps-to-reacquisition** (after the jump) — per seed and mean across the seed table;
- **success within the fixed budget** (fraction of seeds reacquired).

**Secondary (diagnostic only)**
- tracker path length;
- stale-trail following (steps spent moving toward decayed/abandoned cells);
- distance-to-target trajectory over time;
- remaining trail mass over time.

## 5. Determinism and fairness

- Same seed → **byte-identical textual metrics** (the toy must be fully seeded; integer-only decay makes this trivial).
- Treatment and control share the **exact** target start, jump destination, hidden path, tracker start, topology, movement rules, tie-breaking and step budget.
- **Trail availability is the sole variable.**
- Deterministic tie-breaking throughout; **no LLM and no semantic reasoning in the loop.**

## 6. Hard self-checks vs scientific outcome

**Hard self-checks may enforce only instrument correctness** (a failure here means the toy is broken, not that the hypothesis failed):
- trail values are integer dtype and **never negative**;
- trail decays by exactly the stated rule (`max(0, trail - D)` each step);
- a same-seed rerun is byte-identical;
- treatment and control use **identical** target paths / jump / start (assert equality of the generated path arrays);
- trial-count conservation (every seed runs both arms);
- no illegal moves (tracker stays in-bounds; steps to adjacent cells only).

**Do NOT hard-assert that treatment beats control.** That is the hypothesis and must be allowed to fail; treatment-vs-control outcomes are *reported*, never asserted.

## 7. Output and quarantine

- **Text / table output first** (per the house text-first posture); compact tables of (seed, treatment steps, control steps, winner) + the aggregate means.
- Optional CSV **only** under the git-ignored `experiments/theory_sandbox/out/`.
- **stdlib + NumPy only**; **no plots in v0**.
- **No engine-runtime imports**; **no `uft_ca`**; **no production data**; **no `data/` writes**; **no CI collection** (`pytest.ini` `testpaths=tests` holds); **no GPU**.
- Must print the non-canonical warning every run (*"NON-CANONICAL TOY: faster tracking on a toy grid proves nothing about Medusa; this is not radioactive physics."*).
- Header must follow README §3.6: cite ledger entry 14, status, can/cannot show, quarantine line.

## 8. Promotion boundary

The README §4 **six-step promotion gate** applies in full: (1) source verification, (2) explicit design doc, (3) tests/falsification criteria, (4) Jack/AURA/Kev review, (5) explicit separate PR, (6) no Lane A activation unless separately gated. **Even a positive result cannot alter the engine, the observer vocabulary, Vanguard, Lane A or Swarm Hunter** without a later, explicit, separately-gated design + implementation phase. A pretty reacquisition table is inspiration-grade only.

## 9. Resolved decisions and remaining questions

**Curator-confirmed (Jack + AURA, 2026-06-19) — binding for the future script PR:**
1. **Primary scenario = reacquisition after a target jump.** Before the event, tracker and target begin in declared positions; at a fixed declared step the target jumps to a seeded destination and then follows an identical seeded hidden path in *both* arms; during the hidden interval the moving target deposits the decaying integer trail; treatment reads the trail gradient, control follows the declared no-trail policy; **trail availability is the sole variable**; primary outcomes are steps-to-reacquire and success-within-budget; treatment is allowed to lose.
2. **Stale-trail fairness**: v0 **begins deposition only after the jump** (recommended), so no pre-jump trail can misdirect the tracker toward the abandoned location. (Alternative — clear the trail at the jump — is equivalent for v0; deposit-after-jump is simpler.)

**84's reasoned recommendations (open to curator override):**
- **Topology**: bounded (non-toroidal) `N×N`, `N ≈ 24–32`.
- **Integer decay**: linear decrement `max(0, trail - D)` with `A ≫ D` (lifetime ≈ `A/D`); no multiplicative/float decay in v0.
- **Control policy**: deterministic expanding-ring/spiral sweep from last-seen cell; treatment falls back to it when off-trail.
- **Reacquisition radius**: `r = 0` (exact cell).
- **Seeds / budget**: ~12 seeds; budget ≈ `6×N` post-jump steps.
- **No diffusion in v0**: rely on the along-trail freshness gradient; treat "can the tracker acquire the trail at all without diffusion?" as a first-class *measured* question — if v0 shows acquisition fails, diffusion (or a wider deposit footprint) becomes an explicit v1 design question, not a silent v0 addition.

**Genuinely-open (for Jack/Kev/AURA, if they wish to pin before the script PR):**
- exact `N`, `A`, `D`, seed count and step budget (any reasonable small values are fine; these only set scale);
- reacquisition radius `r = 0` vs `r = 1`;
- whether the jump destination is constrained to within a bounded radius of the last-seen cell (affects how often the treatment tracker can reach the fresh trail) — the one choice that materially shapes the result, and the cleanest single knob to discuss.

---

*Glass box rules apply. The hound may follow the scent; the cathedral does not move.*
