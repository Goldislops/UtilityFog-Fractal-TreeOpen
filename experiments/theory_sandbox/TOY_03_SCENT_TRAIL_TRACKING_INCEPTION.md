# Toy #3 Inception — Decaying Scent-Trail Tracking (design only, no script)

> **Status**: inception/design note only. **No script exists yet, and this note authorizes none.** The toy itself lands only in a later, separate PR after Jack/AURA/Kev review this note. Per `experiments/theory_sandbox/README.md`: one toy per PR; this is the *zeroth* brick of Toy #3 — the thinking before the toy.
>
> **NON-CANONICAL TOY (design):** a wayfinder reaching a faded endpoint faster on a toy grid proves nothing about Medusa. This is an **algorithmic trail-following toy** — *not radioactive physics, not a hunt, and not engine validation*. (Image: following one's own fading footprints back to a spot, not chasing prey.)

## 0. Current model seat

Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-19 (Sydney time), under Phase 2B-5H-1 (Jack-relayed, AURA-confirmed; corrected after Jack's live review of PR #244 + three valid Gemini threads). *(Future seats editing this doc: state your seat here per model-seat hygiene.)*

## 1. Source and status

- **Source**: AURA's "Physics of the Utility Fog" master handover (2026-06-19) → the read-only **Phase 2B-5H-0** formalization audit → `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` **entry 14** (decaying trails: *new hypothesis; adjacent primitive exists*), marked **APPROVED FOR DESIGN-INCEPTION ONLY — no engine implementation authorized**.
- **Status**: speculative **discrete wayfinding metaphor** / sandbox candidate. The originating phrase was "radioactive decay scent trails"; the **preferred vocabulary here is algorithmic** — *decaying integer trail, deposit, decrement, gradient ascent, reacquisition*. There is no radioactivity and no half-life physics, and none is claimed. The "tracker/target/reacquisition" terms below are the team's agreed technical vocabulary, not a hunting frame.
- **Non-canonical. Not architecture evidence.** Adjacent engine primitives exist (memory `signal_field` channel 5 + `_mycelial_diffuse`, plus the decay configs in `continuous_evolution_ca.py`), but this toy deliberately does **not** import or touch them; if the toy ever validates, wiring the idea into those primitives is a **separate, later, gated** arc.

## 2. Precise hypothesis (curator-corrected)

> Given an identical seeded hidden target path and endpoint, a tracker with access to the resulting decaying integer trail will reacquire the **stationary** hidden target in fewer steps, or more often inside the fixed budget, than the otherwise-identical tracker using only the declared no-trail search policy.

The toy **must be permitted to falsify this** — the trail-reading tracker may tie, lose, or do worse, and that outcome must be reportable without any hard assertion to the contrary. This tests whether a *finite, decaying historical path* assists reacquisition of a **now-stationary** endpoint; it does **not** claim to test pursuit of a continuously moving target (an equal-speed chase can be structurally impossible for reasons unrelated to trail usefulness — Jack Correction 4).

## 3. Mechanism (pinned v0 — review before any code)

**Trail laying and reacquisition are deliberately separated** so the only thing under test is whether a *decayed historical trail* helps relocate a stationary endpoint.

### 3.1 Geometry (Jack Correction 4 — pinned)
- bounded **32 × 32** grid (non-toroidal);
- tracker and target initially **share the declared last-seen cell**;
- **jump destination**: a cell at Chebyshev distance **3–5** from the last-seen cell, chosen by the seed, and far enough from the boundary to permit the hidden path;
- the target then follows a **seeded, precomputed, self-avoiding cardinal path of 12 moves**; if no unvisited legal cardinal move exists, the path ends early and **that realised path is used identically in both arms**;
- the tracker is **stationary while the trail is laid**;
- after laying, the target **remains stationary at its endpoint**;
- treatment and control then begin reacquisition from the **same** last-seen tracker position;
- **exact-cell reacquisition: `r = 0`**;
- fixed post-laying **search budget: 192 tracker moves**;
- fixed **seed table: 12 declared seeds**.

### 3.2 Trail parameters (Jack Correction 2 — pinned)
- deposit amplitude **`A = 64`**; per-step decrement **`D = 1`**;
- trail dtype **signed `int16`** (lifetime ≈ `A/D` = 64 steps);
- **no diffusion** in v0.

### 3.3 Signed, saturating integer decay (Jack Correction 2)
Every relevant tick, decay the whole trail with **saturating subtraction in signed arithmetic** (so no unsigned wraparound can occur):

```
trail[:] = maximum(trail - D, 0)        # int16; clamps at 0, never wraps
```

### 3.4 Treatment rule — strict ascent (Jack Correction 1; fixes the oscillation thread)
At each reacquisition move the treatment tracker reads its **4 cardinal neighbours**:
- **If at least one neighbour has a trail value strictly greater than the tracker's current-cell trail value**, move to the neighbour with the **highest** value, breaking ties by lowest `(row, col)`.
- **Otherwise**, take exactly one step of the shared no-trail fallback policy (§3.6).

A positive but **lower-or-equal**-valued neighbour must never pull the tracker backwards — this prevents oscillation between the newest and second-newest trail cells. The **control** tracker never inspects the trail; it always uses §3.6.

### 3.5 Exact update order (Jack Correction 3 — identical across both arms)

**Initial jump**
1. Tracker remains at the last-seen cell.
2. Target jumps to its precomputed seeded destination.
3. Deposit `A` at the jump destination.

**Each hidden trail-laying tick**
1. Apply signed saturating decay to the whole trail.
2. Move the target to the next precomputed legal path cell.
3. Deposit/overwrite `A` at the target's new cell.
4. The tracker remains stationary.

**Each reacquisition tick**
1. Check whether the tracker already occupies the stationary target endpoint (if so, end).
2. Apply signed saturating decay.
3. Target remains stationary and makes **no further deposit**.
4. Treatment **or** control makes exactly **one** legal tracker move (§3.4 / §3.6).
5. **Check reacquisition immediately after the move**; if the tracker now occupies the target cell, the run ends **before** any later fallback movement.

### 3.6 Shared fallback search — fully specified (Jack Correction 5)
A deterministic expanding-ring sweep, identical for both arms (treatment uses it only when no strict ascent exists):
- construct an ordered list of all in-bounds cells by **increasing Chebyshev distance** from the last-seen cell. **Note: the first entry is the last-seen cell itself (distance 0), which is also the tracker's starting cell.**
- **tie-break cells lexicographically by `(row, column)`**;
- each arm maintains **its own** next-unvisited waypoint index into this shared ordering;
- **Pre-advance before moving (erratum fix — Codex P2 r3441709727):** *before* each fallback movement, skip any already-reached waypoint — `while idx < len(waypoints) and tracker_pos == waypoints[idx]: idx += 1` (the `idx < len(waypoints)` bound prevents an out-of-range read once every waypoint has been reached; on a 1024-cell grid with a 192-move budget the list cannot actually exhaust, so the bound is defensive). This discards the distance-0 last-seen/start cell on the very first fallback tick, and any waypoint the tracker is already standing on when treatment resumes fallback after strict-ascent mode, so the fallback never stalls or emits a zero-length "move";
- then, **only when `idx < len(waypoints)`**, move **one cardinal cell toward `waypoints[idx]`**; when both row and column differ, resolve the axis by a **fixed rule**: *if `|Δrow| ≥ |Δcol|` step along the row, else step along the column* (never diagonal). This yields **exactly one non-zero legal cardinal move per reacquisition tick**, unless reacquisition has already ended the run;
- **`idx == len(waypoints)` (waypoint list exhausted) is unreachable under pinned v0** — a 32×32 grid yields 1024 waypoints while the budget is only 192 moves — so if it is ever reached it is an **instrument-contract failure: fail closed (raise/abort)**, *not* a zero-length move and *not* a scientific outcome (Codex thread r3442612649);
- advance the waypoint index when the waypoint cell is reached (the pre-advance rule above also covers this on the following tick);
- the treatment tracker **pauses** the fallback while following a strictly-ascending trail and **resumes deterministically** (same per-arm waypoint index + same pre-advance rule) when no ascent exists.

Both arms apply the **identical** pre-advance rule and maintain their own waypoint index.

The waypoint ordering and the target path are **generated once and shared identically** between arms. **Trail visibility remains the sole experimental variable.**

## 4. Metrics (Jack Correction 6)

**Primary**
- steps to reacquisition (per seed + mean across the 12-seed table);
- success within the 192-move budget (fraction of seeds reacquired).

**Diagnostics only (no success claim asserted)**
- whether and **when** the treatment tracker first acquired any trail cell (`trail > 0`);
- number of strict-ascent (trail-following) moves;
- number of fallback-search moves;
- whether the trail had **fully decayed** before reacquisition;
- realised hidden-path length (if it terminated early).

## 5. Determinism and fairness

- Same seed → **byte-identical textual metrics** (integer-only decay makes this trivial).
- Treatment and control share the **exact** target start, jump destination, realised hidden path, endpoint, tracker start, topology, movement rules, tie-breaking, fallback waypoint ordering and step budget.
- **Trail availability is the sole variable.**
- Deterministic tie-breaking and a fixed fallback axis rule throughout; **no LLM and no semantic reasoning in the loop.**

## 6. Hard self-checks vs scientific outcome

**Hard self-checks may enforce only instrument correctness** (a failure means the toy is broken, not that the hypothesis failed):
- trail dtype is **`int16`**; trail **min is never negative**; trail **max never exceeds `A`**;
- on each decay tick, every **non-deposited** cell changes by exactly `-D` **or** reaches `0` (saturating);
- a same-seed rerun is **byte-identical**;
- treatment and control use **identical** target path / jump destination / endpoint / tracker start / fallback waypoint ordering (assert array equality);
- trial-count conservation (every seed runs both arms);
- no illegal moves (tracker stays in-bounds; one **cardinal** step per move);
- every reacquisition tick performs **exactly one non-zero** cardinal move (no zero-length "stall" move), unless reacquisition has already ended the run — i.e. the §3.6 pre-advance correctly skipped the distance-0 start cell and any already-reached waypoint;
- a fallback move is only attempted with `idx < len(waypoints)`; reaching `idx == len(waypoints)` is a **fail-closed instrument-contract violation** (raise/abort), never a result — and is unreachable under pinned v0 (1024 waypoints ≫ 192-move budget);
- reacquisition is checked **immediately after every tracker move**.

**Do NOT hard-assert that treatment beats control.** That is the hypothesis and must be allowed to fail; treatment-vs-control outcomes are *reported*, never asserted.

## 7. Output and quarantine

- **Text / table output first**; compact tables of (seed, treatment steps, control steps, winner) + aggregate means + the §4 diagnostics.
- Optional CSV **only** under the git-ignored `experiments/theory_sandbox/out/`.
- **stdlib + NumPy only**; **no plots in v0**.
- **No engine-runtime imports**; **no `uft_ca`**; **no production data**; **no `data/` writes**; **no CI collection** (`pytest.ini` `testpaths=tests` holds); **no GPU**.
- Must print the non-canonical warning every run (*"NON-CANONICAL TOY: a wayfinder reaching a faded endpoint on a toy grid proves nothing about Medusa; not radioactive physics, not a hunt."*).
- Header must follow README §3.6: cite ledger entry 14, status, can/cannot show, quarantine line.

## 8. Promotion boundary

The README §4 **six-step promotion gate** applies in full: (1) source verification, (2) explicit design doc, (3) tests/falsification criteria, (4) Jack/AURA/Kev review, (5) explicit separate PR, (6) no Lane A activation unless separately gated. **Even a positive result cannot alter the engine, the observer vocabulary, Vanguard, Lane A or Swarm Hunter** without a later, explicit, separately-gated design + implementation phase. A pretty reacquisition table is inspiration-grade only.

## 9. Resolved decisions and remaining questions

**Pinned by Jack (2026-06-19, binding for the future script PR):** grid 32×32 bounded · shared last-seen start · jump destination Chebyshev 3–5 (boundary-safe) · seeded self-avoiding cardinal hidden path of 12 moves (early-end allowed, realised path shared) · tracker stationary during laying · target stationary at endpoint · reacquire from same start · `r = 0` · budget 192 moves · 12 seeds · `A = 64`, `D = 1`, signed `int16`, no diffusion · **strict-ascent** treatment rule · explicit update order · signed saturating decay · fully-specified shared fallback · trail-laying separated from reacquisition · treatment may tie/lose.

**84's pinned implementation details (filling Jack's "document a fixed rule" requirements):** 4-cardinal-neighbour trail reading + movement; strict-ascent tie-break = lowest `(row, col)`; fallback axis rule = *`|Δrow| ≥ |Δcol|` → row, else column*; fallback **pre-advances past already-reached waypoints before moving** (§3.6 erratum fix, Codex P2 r3441709727) so the distance-0 start cell never stalls the first fallback tick; reacquisition checked at tick start and immediately after each move.

**Genuinely-open (implementer's choice, declared in the eventual script; not blocking):**
- the literal 12 seed integers (any fixed declared set);
- nothing else material remains — the geometry, trail mechanics, ordering and budget are all pinned above.

---

*Glass box rules apply. A wayfinder may follow fading footprints home; the cathedral does not move.*
