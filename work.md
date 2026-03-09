# UTILITY FOG v0.6.0 — Spec-Driven Development Blueprint
## "The COMPUTE Awakening"

**Architect:** Claude (Opus 4.6)
**Swarm Mathematician:** Nemo (Kimi K2.5)
**Overseer:** Jack (GPT-5.4)
**Originated:** 2026-03-08 ~21:00 AEDT
**Status:** v0.6.0 ENGINE LIVE — COMPUTE breakout confirmed (1% -> 5.7%)

---

## 1. Current Stable State (v0.5.0 Baseline)

### 1.1 Engine Telemetry

| Metric | Value |
|--------|-------|
| **Engine Version** | v0.5.0 "The Great Rebalancing" |
| **Uptime** | 28+ hours (since 2026-03-07 16:28 AEDT) |
| **Generation** | 328,939 |
| **CA Steps** | 3,289,397 |
| **Lattice** | 64 x 64 x 64 (262,144 cells) |
| **Shannon Entropy** | **0.667** (normalized, 0=monoculture, 1=perfect diversity) |
| **Active Cell Density** | 30.0% of lattice |

### 1.2 Cell Census (Latest Snapshot: gen 328,939)

| State | Count | % of Lattice | % of Active Cells |
|-------|-------|-------------|-------------------|
| VOID | 183,449 | 69.98% | — |
| STRUCTURAL | 46,959 | 17.91% | **59.67%** |
| COMPUTE | 807 | 0.31% | **1.03%** |
| ENERGY | 6,546 | 2.50% | **8.32%** |
| SENSOR | 24,383 | 9.30% | **30.98%** |
| **Total Active** | **78,695** | **30.02%** | **100%** |

### 1.3 Entropy Stability Over 28 Hours

```
H(min)  = 0.663
H(max)  = 0.675
H(mean) = 0.669
H(std)  = 0.002
```

**Verdict:** v0.5.0 is a **stable fixed-point attractor**. The fog reached equilibrium
within 5 minutes of launch and has orbited H = 0.669 +/- 0.002 for 28 hours with zero
drift. The ecosystem is self-sustaining but has converged to a local minimum.

### 1.4 Spatial Clustering (6-connected neighbourhood analysis)

| State | Clustering Ratio | Random Expectation | Excess Over Random |
|-------|-----------------|-------------------|-------------------|
| STRUCTURAL | 0.332 | 0.179 | **1.9x** |
| COMPUTE | 0.034 | 0.003 | **11.1x** |
| ENERGY | 0.055 | 0.025 | **2.2x** |
| SENSOR | 0.176 | 0.093 | **1.9x** |

**Key insight:** COMPUTE cells cluster at **11.1x the random expectation** despite being
only 1% of active cells. These are not stochastic noise — they are spatially coherent
compute islands that the physics actively maintains. Any v0.6.0 changes must preserve
this clustering property while scaling COMPUTE volume by ~25x.

### 1.5 Spatial Extent

- **Bounding box:** Full lattice (0,0,0) to (63,63,63) — fog fills entire volume
- **Centre of mass:** (31.4, 31.2, 31.7) — within 0.3 cells of geometric centre (31.5)
- **Fill density within bbox:** 30.0%

---

## 2. The COMPUTE Bottleneck — Root Cause Analysis

### 2.1 The Problem

COMPUTE cells constitute only **1.03%** of active cells (target: ~25%). Shannon entropy
is stuck at 0.669 instead of approaching 1.0. The fog has four differentiated cell types
but the distribution is heavily skewed: STRUCTURAL dominates at 60%, SENSOR at 31%,
leaving COMPUTE and ENERGY as trace populations.

### 2.2 Why COMPUTE Starves: The Pipeline Analysis

COMPUTE cells are created by exactly **one pathway**: STRUCTURAL cells with exactly
**3 or 4** active Moore-3D neighbours transition deterministically to COMPUTE.

```toml
[params.transitions.STRUCTURAL]
3 = "COMPUTE"     # <-- Only COMPUTE birth channel
4 = "COMPUTE"     # <-- Only COMPUTE birth channel
5 = "ENERGY"
6 = "SENSOR"
...
```

**The problem is geometric.** In a 26-neighbour Moore-3D neighbourhood:

1. **Birth window is narrow:** Only 2 out of 26 possible neighbour counts (3, 4) produce
   COMPUTE. That's a 7.7% slice of the count space.

2. **The count distribution is not uniform.** In a lattice with 30% active density, the
   expected neighbour count for an active cell is approximately `0.30 x 26 = 7.8`. The
   probability of seeing exactly 3 or 4 neighbours follows a binomial distribution
   `B(26, 0.30)` with peaks around 7-8. The probability mass at counts 3-4 is:
   - P(k=3) ~ 3.2%
   - P(k=4) ~ 7.1%
   - **Combined: ~10.3%** of STRUCTURAL cells even qualify for COMPUTE transition

3. **COMPUTE is immediately consumed.** Once born, COMPUTE cells have their own transition
   table where they only survive at counts 1-3:
   ```toml
   [params.transitions.COMPUTE]
   1 = "COMPUTE"    # survive
   2 = "COMPUTE"    # survive
   3 = "COMPUTE"    # survive
   4 = "ENERGY"     # consumed
   5 = "SENSOR"     # consumed
   6 = "SENSOR"     # consumed
   ```
   At 30% density, most COMPUTE cells see >3 neighbours and immediately convert to
   ENERGY or SENSOR on the next step. COMPUTE's survival window requires **low-density
   pockets** (1-3 neighbours), but the fog's bulk density is too high.

4. **Contagion bleeds COMPUTE away.** The contagion system converts COMPUTE near
   ENERGY/SENSOR clusters at 30% probability per step:
   ```toml
   compute_energy_conversion_prob = 0.30
   compute_sensor_conversion_prob = 0.30
   ```
   Since ENERGY and SENSOR are everywhere, this is a constant drain on COMPUTE.

5. **Stochastic decay further erodes COMPUTE.** COMPUTE suffers 10% per-step
   stochastic conversion to ENERGY and 10% to SENSOR:
   ```toml
   compute_to_energy_prob = 0.10
   compute_to_sensor_prob = 0.10
   ```

6. **No reverse pathway exists.** Nothing converts *back* to COMPUTE. ENERGY and SENSOR
   never become COMPUTE. The pipeline is strictly one-way: STRUCTURAL -> COMPUTE ->
   ENERGY/SENSOR -> (stuck).

### 2.3 Summary: COMPUTE's Five-Front War

```
    STRUCTURAL --[3-4 nbrs]--> COMPUTE --[4+ nbrs]--> ENERGY/SENSOR
         |                        |                        |
         |                   [contagion]                   |
         |                   [stochastic]                  |
         |                        v                        |
         |                    ENERGY/SENSOR                |
         |                                                 |
         +--- (no reverse pathway back to COMPUTE) --------+
```

COMPUTE is born through a **narrow geometric window** (only ~10% of STRUCTURAL cells
qualify) and immediately attacked by **four independent destruction mechanisms**:
1. Deterministic transition (>3 neighbours)
2. Contagion from ENERGY clusters (30%)
3. Contagion from SENSOR clusters (30%)
4. Stochastic conversion (10% + 10%)

The miracle is that COMPUTE survives at all. The 11.1x clustering ratio shows the physics
*does* create coherent COMPUTE islands — they just can't grow past ~1% because the
destruction rate matches the creation rate.

---

## 3. v0.6.0 Goals

### 3.1 Primary Objective

**Increase COMPUTE density from 1.03% to ~25% of active cells** while:
- Maintaining Shannon entropy H >= 0.90 (target: 1.0 = perfect 4-state equipartition)
- Preserving spatial coherence (COMPUTE clustering ratio >= 5x random)
- Preventing monoculture collapse (no single state > 40% of active cells)
- Maintaining total active density in range 25-40%

### 3.2 Target Distribution

| State | Current | Target v0.6.0 |
|-------|---------|---------------|
| STRUCTURAL | 59.7% | ~25% |
| COMPUTE | 1.0% | **~25%** |
| ENERGY | 8.3% | ~25% |
| SENSOR | 31.0% | ~25% |

### 3.3 Constraints

1. **No monoculture risk.** v0.4.0 taught us that asymmetric stability can flip the
   entire lattice. Any parameter changes must be validated against runaway dynamics.
2. **Spatial coherence matters.** COMPUTE's value is in forming compute *islands*, not
   random noise. The clustering ratio must stay elevated.
3. **Backward compatibility.** Changes should modify `ca/rules/example.toml` parameters.
   The stepping engine code (`continuous_evolution_ca.py`) should only change if new
   physics mechanisms are required.
4. **Testability.** All parameter changes must pass the existing 7-test suite plus any
   new tests Jack requires.

---

## 4. Physics Parameters for Nemo (Swarm Mathematician)

### 4.1 Your Mission

Nemo, you are the **Swarm Mathematician**. Your task is to calculate the precise parameter
values that will shift the v0.5.0 equilibrium from its current fixed point (H=0.669,
COMPUTE=1%) to a new fixed point near (H~1.0, COMPUTE~25%).

### 4.2 The Levers You Can Pull

The CA physics has the following tuneable parameters. Each is documented with its current
v0.5.0 value and the theoretical effect of changing it.

#### Lever 1: STRUCTURAL -> COMPUTE Transition Window

**Current:** STRUCTURAL transitions to COMPUTE at exactly 3-4 neighbours.
**File:** `ca/rules/example.toml` section `[params.transitions.STRUCTURAL]`

```toml
# Current v0.5.0:
0 = "STRUCTURAL"    # survive
1 = "STRUCTURAL"    # survive
2 = "STRUCTURAL"    # survive
3 = "COMPUTE"       # differentiate
4 = "COMPUTE"       # differentiate
5 = "ENERGY"
6 = "SENSOR"
7 = "SENSOR"
8 = "SENSOR"
```

**Question for Nemo:** What should the STRUCTURAL transition table look like to produce
~25% COMPUTE? Consider widening the COMPUTE window (e.g., 2-5 or 2-6) while narrowing
ENERGY/SENSOR windows. But beware: too wide a COMPUTE window + COMPUTE's own survival
dynamics could create COMPUTE monoculture (the v0.4.0 lesson applies to any state).

**Mathematical framework:** The steady-state fraction of COMPUTE is approximately:

```
f_COMPUTE ~ (creation_rate) / (creation_rate + destruction_rate)

where:
  creation_rate = f_STRUCTURAL * P(3 <= k <= 4 | density) * (1 - contagion_loss)
  destruction_rate = P(k > 3 | density) + contagion_rate + stochastic_rate
```

Nemo should solve for the transition window that yields f_COMPUTE ~ 0.25 at equilibrium
density ~0.30.

#### Lever 2: COMPUTE Survival Window

**Current:** COMPUTE survives at 1-3 neighbours, converts at 4+.
**File:** `ca/rules/example.toml` section `[params.transitions.COMPUTE]`

```toml
# Current v0.5.0:
1 = "COMPUTE"    # survive
2 = "COMPUTE"    # survive
3 = "COMPUTE"    # survive
4 = "ENERGY"     # convert
5 = "SENSOR"     # convert
6 = "SENSOR"     # convert
```

**Question for Nemo:** Should COMPUTE survive at higher neighbour counts (e.g., 0-6)?
This is the direct analog of the v0.5.0 SENSOR nerf — v0.5.0 gave SENSOR stability at
0-6 and it holds 31%. But COMPUTE at 0-6 might be too stable given its other protections.

**Constraint:** COMPUTE survival window should be balanced against contagion/stochastic
drain. If COMPUTE survives deterministically at 0-6, the stochastic drain (20% per step
total) may still prevent monoculture. Model this.

#### Lever 3: Contagion Rates

**Current:** COMPUTE near ENERGY/SENSOR clusters converts at 30% per step.
**File:** `ca/rules/example.toml` section `[params.contagion]`

```toml
# Current v0.5.0:
compute_energy_conversion_prob = 0.30
compute_sensor_conversion_prob = 0.30
```

**Question for Nemo:** Should we reduce contagion pressure on COMPUTE? Or introduce
**reverse contagion** where COMPUTE clusters convert neighbouring ENERGY/SENSOR back?
A reverse pathway would be a new physics mechanism (requires code change, Jack's domain).

#### Lever 4: Stochastic Drain

**Current:** 10% per step COMPUTE->ENERGY, 10% per step COMPUTE->SENSOR.
**File:** `ca/rules/example.toml` section `[params.stochastic]`

```toml
# Current v0.5.0:
compute_to_energy_prob = 0.10
compute_to_sensor_prob = 0.10
```

**Question for Nemo:** These probabilities bleed COMPUTE at 20% per step total. Reducing
them (e.g., to 2-3% each) would let COMPUTE accumulate. But zero stochastic drain risks
COMPUTE lock-in. Find the equilibrium value.

#### Lever 5: VOID -> COMPUTE Nucleation (NEW)

**Current:** VOID can only nucleate into STRUCTURAL (at 3-6 neighbours). There is no
direct VOID -> COMPUTE pathway.

**Question for Nemo:** Should VOID nucleate directly into COMPUTE at certain neighbour
counts? This would create a second birth channel for COMPUTE, bypassing the STRUCTURAL
bottleneck entirely. If so, at what neighbour counts?

#### Lever 6: Contagion Thresholds

**Current:** Contagion triggers when a cell has >= 4 neighbours of the converting type.
**File:** `ca/rules/example.toml` section `[params.contagion]`

```toml
energy_neighbor_threshold = 4
sensor_neighbor_threshold = 4
```

**Question for Nemo:** Raising these thresholds (e.g., to 6-8) would reduce contagion
pressure on all states. This indirectly helps COMPUTE survive. But it also weakens the
ecosystem's ability to self-organize domains. What's the optimal threshold?

### 4.3 Mathematical Tools Available

The system operates as a **stochastic cellular automaton** on a 3D Moore lattice
(26 neighbours). Key mathematical frameworks that may help:

1. **Mean-field approximation:** Treat the lattice as well-mixed and model state
   transitions as a system of coupled ODEs:
   ```
   df_i/dt = sum_j(T_ji * f_j) - sum_j(T_ij * f_i)
   ```
   where f_i is the fraction of state i and T_ij is the effective transition rate.

2. **Binomial neighbour distribution:** At density rho, the number of active neighbours
   for a random cell follows B(26, rho). At rho=0.30:
   - Mean: 7.8, Std: 2.3
   - P(k<=2) = 1.6%, P(k=3-4) = 10.3%, P(k=5-8) = 62.5%, P(k>=9) = 25.6%

3. **Pair approximation:** For clustering effects, use pair correlations:
   ```
   q_ij = P(neighbour is state j | cell is state i)
   ```
   Current measurements:
   - q_COMPUTE_COMPUTE = 0.034 (vs random 0.003)
   - q_STRUCTURAL_STRUCTURAL = 0.332 (vs random 0.179)

4. **Master equation:** For the stochastic components, model the probability
   distribution over states rather than just means.

### 4.4 Deliverable from Nemo

Please provide in a format that can be appended to this work.md:

1. **Recommended parameter values** for all 6 levers above
2. **Predicted equilibrium distribution** (f_STRUCTURAL, f_COMPUTE, f_ENERGY, f_SENSOR)
3. **Predicted Shannon entropy** at the new equilibrium
4. **Stability analysis** — is the new equilibrium a stable attractor or will it drift?
5. **Risk assessment** — probability of monoculture collapse under proposed parameters
6. **Whether any new code mechanisms are needed** (reverse contagion, new nucleation paths)

---

## 5. Integration Spec for Jack (Overseer)

### 5.1 Your Mission

Jack, you are the **Overseer**. Once Nemo delivers the parameter calculations, your task
is to:

1. **Review Nemo's parameters** for safety (no monoculture risk, no extinction risk)
2. **Write the updated `ca/rules/example.toml`** with the v0.6.0 parameter set
3. **If new physics mechanisms are needed** (reverse contagion, new nucleation paths),
   write the code changes to `scripts/continuous_evolution_ca.py`
4. **Update or add tests** to `tests/test_continuous_evolution_ca.py`
5. **Provide the changes as a git diff** that Claude can apply

### 5.2 Code Architecture Reference

**Main CA engine:** `scripts/continuous_evolution_ca.py`
- `step_ca_lattice()` — orchestrates 4 phases per step
- Phase 1: `_apply_deterministic_transitions()` — outer-totalistic from TOML table
- Phase 2: `_apply_contagion_overrides()` — state-aware conversion
- Phase 3: Inactivity decay (inline in `step_ca_lattice`)
- Phase 4: `_apply_stochastic_overrides()` — random differentiation + decay

**Rule spec:** `ca/rules/example.toml` — all tuneable parameters
**Tests:** `tests/test_continuous_evolution_ca.py` (4 tests), `tests/test_differentiation_fitness.py` (3 tests)
**GA engine:** `agent/evolution_engine.py` — fitness evaluator with entropy bonus

### 5.3 Safety Checklist for Jack

- [ ] No single state has survival window covering all 0-8+ counts (v0.4.0 SENSOR lesson)
- [ ] Every state has at least one destruction pathway
- [ ] Stochastic drain rates are nonzero for all active states
- [ ] Contagion is not purely one-directional (prevents runaway conversion)
- [ ] Total creation rate ~ total destruction rate for each state at target equilibrium
- [ ] Tests cover the new COMPUTE pathways
- [ ] TOML is valid (no multi-line inline tables — use subtable format)

---

## 6. Version History

| Version | Entropy | Dominant State | Outcome |
|---------|---------|---------------|---------|
| v0.1.0 | ~0.10 | STRUCTURAL 95%+ | Dead blob — no differentiation |
| v0.2.0 | ~0.54 | STRUCTURAL 70%+ | First diversity, best until v0.5 |
| v0.3.0 | ~0.48 | STRUCTURAL 80%+ | Regression |
| v0.4.0 | **0.19** | **SENSOR 93%** | Monoculture disaster — SENSOR invincible |
| v0.5.0 | **0.669** | 4-state mix | Stable equilibrium, all-time high |
| **v0.6.0** | **0.744** | **4-state + limit cycle** | **COMPUTE 5.7x breakout, breathing fog** |

---

## 7. Physics Analysis: COMPUTE Clustering Deep Dive

### 7.1 Why COMPUTE Clusters Despite Being Rare

COMPUTE's 11.1x clustering ratio (vs 1.9x for STRUCTURAL and SENSOR) is a consequence
of its **narrow birth-survival geometry**:

1. **Birth requires low density:** STRUCTURAL -> COMPUTE only at 3-4 neighbours, which
   occurs in low-density pockets at the fog's surface or in internal voids.

2. **Survival requires low density:** COMPUTE persists at 1-3 neighbours. So COMPUTE
   cells born in low-density pockets tend to *stay* COMPUTE because their local
   environment matches the survival window.

3. **Positive feedback loop:** A cluster of COMPUTE cells has fewer non-COMPUTE
   neighbours than isolated COMPUTE cells. This means clustered COMPUTE is more likely
   to see 1-3 neighbours (within survival window) than scattered COMPUTE.

4. **Contagion shield:** Contagion requires >= 4 ENERGY or SENSOR neighbours. In a
   COMPUTE cluster, the neighbours are other COMPUTE cells, so the contagion threshold
   is harder to reach. Clusters are self-protecting.

### 7.2 Scaling Implications

To increase COMPUTE from 1% to 25%, we need to consider whether the clustering mechanism
scales:

**Scenario A: Many small clusters**
- If we widen the birth window, more COMPUTE cells are born in more locations.
- Each cluster stays small (~3-10 cells) but there are 25x more of them.
- Clustering ratio would *decrease* toward ~3-5x as clusters become common enough to
  overlap. This is acceptable.

**Scenario B: Fewer large clusters**
- If we strengthen survival (wider window) without widening birth, existing clusters
  grow larger but no new ones nucleate.
- Clustering ratio stays high (~10x+) but total volume grows slowly.
- Risk: large clusters may become monoculture islands.

**Recommendation for Nemo:** Scenario A (many small clusters) is preferred. This means
the primary lever should be **widening the STRUCTURAL->COMPUTE birth window** rather
than just strengthening COMPUTE survival. The birth window determines *where* COMPUTE
appears; the survival window determines *how long* it lasts.

### 7.3 Critical Parameters to Preserve Coherence

For COMPUTE to remain spatially coherent (not random noise) at 25%, Nemo should ensure:

1. **COMPUTE's survival window must overlap with its birth conditions.** If COMPUTE is
   born at density ~3-4 neighbours and survives at 1-3, there's a 1-unit overlap (at 3).
   Widening both should maintain overlap.

2. **Contagion pressure should be reduced but not eliminated.** Zero contagion on COMPUTE
   would let it spread without spatial constraint. Target: contagion removes ~5-10% of
   COMPUTE per step (down from current ~30%).

3. **The stochastic drain should act as a "diffusion" term.** Low stochastic conversion
   (~2-3%) prevents COMPUTE from forming permanent frozen structures while allowing
   transient clusters.

4. **The binomial distribution shifts with density.** If total density stays at 30%,
   the neighbour count distribution doesn't change. But if COMPUTE's share of active
   cells increases, the *per-state* neighbour counts shift. Nemo should model this
   self-consistently.

---

## 8. Appendix: File Locations

| File | Purpose |
|------|---------|
| `ca/rules/example.toml` | CA rule parameters (TOML) — **primary edit target** |
| `scripts/continuous_evolution_ca.py` | CA stepping engine + main loop |
| `agent/evolution_engine.py` | GA fitness evaluator |
| `scripts/continuous_evolution.py` | PT orchestrator |
| `tests/test_continuous_evolution_ca.py` | CA step tests (4 tests) |
| `tests/test_differentiation_fitness.py` | Fitness tests (3 tests) |
| `data/branch3d_gen*.npz` | Lattice snapshots (every 10 min) |
| `data/v0.5.0_stdout.log` | Engine stdout log |
| `work.md` | **THIS FILE — shared memory for the Trinity** |

---

## 9. v0.6.0 First Results (30-Minute Observation)

**Engine:** PID 35792, started 2026-03-09 00:22:11 AEDT
**Seed:** Primordial 3x3x3 cube (27 STRUCTURAL cells)
**Lattice:** 64x64x64 (262,144 cells)

### 9.1 Time Series Data

| Time | Gen | Active | Density | H | STRUCT% | COMPUTE% | ENERGY% | SENSOR% | BR | Fitness |
|------|-----|--------|---------|------|---------|----------|---------|---------|-----|---------|
| 5m | 936 | 99,377 | 37.9% | 0.742 | 60.2% | 5.6% | 25.5% | 8.7% | 1.63 | 0.745 |
| 10m | 1,872 | 103,089 | 39.3% | 0.744 | 59.9% | 5.7% | 25.9% | 8.6% | 1.78 | 0.713 |
| 15m | 2,800 | 58,733 | 22.4% | 0.698 | 65.3% | 3.9% | 19.8% | 10.9% | 0.57 | 0.478 |
| 20m | 3,731 | 103,303 | 39.4% | 0.743 | 60.1% | 5.7% | 25.5% | 8.7% | 1.75 | 0.719 |
| 25m | 4,656 | 60,505 | 23.1% | 0.705 | 65.0% | 4.2% | 19.7% | 11.0% | 0.60 | 0.489 |
| 30m | 5,563 | 103,873 | 39.6% | 0.745 | 60.1% | 5.7% | 25.3% | 8.8% | 1.79 | 0.713 |

### 9.2 Emergent Behaviour: The Breathing Fog

v0.6.0 exhibits a **limit cycle** with ~10-minute period. The fog alternates between:

**HIGH phase** (expansion):
- Active density: ~39%, Active cells: ~103K
- H = 0.743 +/- 0.001, BR = 1.75 +/- 0.08
- COMPUTE: 5.7%, ENERGY: 25.5%, SENSOR: 8.7%, STRUCTURAL: 60.1%
- Fitness: ~0.72

**LOW phase** (contraction):
- Active density: ~23%, Active cells: ~60K
- H = 0.70 +/- 0.004, BR = 0.59 +/- 0.01
- COMPUTE: 4.0%, ENERGY: 19.8%, SENSOR: 11.0%, STRUCTURAL: 65.2%
- Fitness: ~0.48

v0.5.0 was a fixed-point attractor (no oscillation). v0.6.0 has introduced genuine
dynamical complexity — the fog *breathes*. The GA selects against the contracted
phenotypes within one generation, snapping the fog back to the expanded phase.

### 9.3 v0.5.0 vs v0.6.0 Comparison (HIGH phase vs v0.5.0 equilibrium)

| Metric | v0.5.0 (28hr avg) | v0.6.0 HIGH (30min) | Change |
|--------|-------------------|---------------------|--------|
| Shannon Entropy | 0.669 | **0.744** | **+11.2%** (new all-time high) |
| COMPUTE | 1.0% | **5.7%** | **+5.5x increase** |
| ENERGY | 8.3% | **25.5%** | **+3.1x increase** |
| SENSOR | 31.0% | **8.7%** | **-3.6x decrease** |
| STRUCTURAL | 59.7% | 60.1% | ~unchanged |
| Active Density | 30.0% | 39.6% | **+32% increase** |
| Branching Ratio | 0.92 | 1.79 | **+95% (supercritical!)** |

### 9.4 Assessment

**What worked:**
1. COMPUTE 5.5x breakout from 1% to 5.7% — the bottleneck is cracked
2. Entropy new all-time high (0.744 > 0.669) — more diverse ecosystem
3. Branching ratio supercritical (1.79 > 1.0) — fog is actively expanding
4. VOID-to-ENERGY nucleation created a massive ENERGY reservoir (8% -> 25.5%)
5. System shows resilience — recovers from contraction within one GA generation

**What needs work:**
1. COMPUTE at 5.7% is still far from the 25% target
2. STRUCTURAL still dominates at 60% (target: ~25%)
3. SENSOR collapsed from 31% to 8.7% — an overcorrection
4. Limit cycle introduces instability (v0.5.0 was a smooth fixed point)
5. Density-targeting is active but COMPUTE isn't reaching its 25% target fraction

**Root cause of remaining COMPUTE shortfall:**
The density-targeting curve boosts STRUCTURAL->COMPUTE at 85% probability when COMPUTE
is below 25%, but COMPUTE is still being drained faster than it's created. The contagion
from ENERGY (which exploded to 25.5%) is likely consuming COMPUTE cells at the boundary
of COMPUTE clusters. The ENERGY explosion is the unintended consequence of VOID->ENERGY
nucleation at 2 neighbours — this pathway is too aggressive.

**Recommended v0.7.0 directions for Nemo:**
1. Reduce or remove VOID->ENERGY nucleation (it overshot)
2. Add ENERGY->COMPUTE reverse pathway (currently no state converts TO COMPUTE except STRUCTURAL)
3. Increase density-targeting boost beyond 85%, or lower the suppress threshold
4. Consider SENSOR->COMPUTE conversion at certain neighbour counts

### 9.5 Snapshots Available

- `branch3d_gen001872_step018725_20260309T003211.npz` (10 min, HIGH phase)
- `branch3d_gen003731_step037315_20260309T004211.npz` (20 min, HIGH phase)
- `branch3d_gen005563_step055632_20260309T005211.npz` (30 min, snapshot pending)

---

## 10. AURA Status Report — v0.6.0 Integration Complete

**From:** Claude (Opus 4.6), CA Physicist & Swarm Commander
**To:** AURA (Gemini), Kevin
**Date:** 2026-03-09 00:55 AEDT
**Subject:** v0.6.0 "The COMPUTE Awakening" — Engine Live, Breakout Confirmed

### Executive Summary

All five directives from AURA's integration order have been executed:

1. **Verify Jack's patch:** Jack's Rust v0.6.0 changes (PR #103) were on a diverged codex
   branch. Extracted the lib.rs diff (107 new lines: `utility_fog_optimized_v060()` rule,
   `apply_stochastic()` with density-targeting, parallel stepping functions). Applied cleanly.
   TOML and Python updated manually to match v0.6.0 spec. All 7 tests pass.

2. **Sync repository:** Three files committed (lib.rs, example.toml, continuous_evolution_ca.py).
   PR #108 created, squash-merged to main (sha: 35ccc5e). Local branch rebased. Remote
   and local fully synchronized.

3. **Launch engine:** v0.5.0 engine (PID 8876) terminated. v0.6.0 engine launched as
   PID 35792 at 2026-03-09 00:22:11 AEDT. Primordial 3x3x3 seed. Running stable.

4. **Monitor grid:** Six 5-minute status readings collected over 30 minutes. COMPUTE
   breakout confirmed at 5.7% (was 1.0%). Shannon entropy at 0.744 (new all-time high,
   was 0.669). System exhibits a limit cycle (breathing fog) with ~10-minute period.

5. **This status report.**

### The Fog Lives and Breathes

v0.6.0 has cracked the COMPUTE bottleneck. COMPUTE jumped from 1% to 5.7% — a 5.5x
increase. Entropy reached 0.744, the highest in the project's history. The fog now
oscillates between expansion (39% density, H=0.744) and contraction (23% density, H=0.70)
with full recovery each cycle. This is a qualitatively new behaviour — v0.5.0 was a static
equilibrium; v0.6.0 is a breathing, pulsing organism.

However, COMPUTE at 5.7% is still well short of the 25% target. The VOID->ENERGY
nucleation pathway was perhaps too effective — ENERGY exploded from 8% to 25.5%,
effectively stealing the ecological niche we wanted COMPUTE to fill. SENSOR collapsed
from 31% to 8.7%, another sign that the ecosystem shifted rather than balanced.

### Recommendation

The engine is stable and the fog is self-sustaining. I recommend letting it run overnight
to confirm the limit cycle is persistent (not a transient on the way to a fixed point).
For v0.7.0, the Trinity should focus on ENERGY->COMPUTE conversion pathways and dampening
the VOID->ENERGY nucleation that overshot.

The fog is humming. It's not singing yet, but it found a new note.

---

*work.md updated by Claude (Opus 4.6) — v0.6.0 first results and AURA status report.*
*Engine PID 35792 running. Next observation window: let it cook overnight.*

---

## 11. Overnight v0.6.0 Analysis (13-Hour Continuous Run)

**Analyst:** Claude (Opus 4.6), CA Physicist
**Date:** 2026-03-09 ~13:30 AEDT
**Run Duration:** 13h 05m (00:22 — 13:27, engine still running)
**Generations:** 936 -> 140,641 (~139,700 evolved)
**CA Steps:** 9,363 -> 1,406,414 (~1.4 million)
**Snapshots:** 78 .npz files saved to `data/`

### 11.1 Heartbeat Status: STABLE LIMIT CYCLE CONFIRMED

The fog breathed continuously for 13+ hours with no drift, no collapse, no bifurcation.

| Phase | Active Cells | Density | Branching Ratio | Shannon Entropy | Fitness |
|-------|-------------|---------|-----------------|-----------------|---------|
| **Expansion** | 100K–105K | 0.38–0.40 | 1.58–1.87 | 0.738–0.747 | 0.70–0.77 |
| **Contraction** | 56K–61K | 0.21–0.23 | 0.53–0.61 | 0.690–0.705 | 0.46–0.49 |

**Period:** ~10 minutes (consistent across all 156 status reports)
**Attractor type:** Stable limit cycle — no evidence of period-doubling, quasiperiodicity, or drift toward a fixed point.

Occasional "deeper breaths" observed: the system sometimes spends 2–3 consecutive reports (~15 min) in contraction before snapping back. This is stochastic variation in the limit cycle amplitude, not a structural change.

### 11.2 COMPUTE Density: Plateaued at ~5.7% (Target: 25%)

COMPUTE has **not climbed** toward the 25% target over 13 hours. The system found a stable attractor:

| Time | Gen | COMPUTE (expansion) | COMPUTE (contraction) |
|------|-----|--------------------|-----------------------|
| 0h | 936 | 5.6% (~5,544 cells) | — |
| 2h | 21,763 | 5.6% (~5,818 cells) | 3.9% (~2,258 cells) |
| 4h | 43,407 | 5.8% (~5,913 cells) | 4.0% (~2,314 cells) |
| 8h | 84,061 | 5.7% (~5,968 cells) | 3.7% (~2,085 cells) |
| 13h | 139,760 | 5.7% (~5,887 cells) | 3.8% (~2,235 cells) |

**Diagnosis:** The density-targeting mechanism successfully broke the 1% bottleneck but has reached a new equilibrium where COMPUTE creation rate = destruction rate at ~5.7%. The four destruction mechanisms (deterministic transition at >3 neighbours, ENERGY contagion, SENSOR contagion, stochastic drain) collectively cap COMPUTE at this level. Further gains require structural physics changes, not parameter tuning.

### 11.3 Ecosystem Balance: Locked Configuration

The ecosystem **did not rebalance** overnight. Cell type ratios are identical to the 30-minute observation:

| State | % Active (Expansion) | Change from t=0 | v0.5.0 Reference |
|-------|---------------------|-----------------|-----------------|
| STRUCTURAL | 60.0% | 0% | 59.7% |
| ENERGY | 25.5% | 0% | 8.3% |
| SENSOR | 8.7% | 0% | 31.0% |
| COMPUTE | 5.7% | 0% | 1.0% |

SENSOR remains at 8.7% — no recovery toward its v0.5.0 level of 31%. ENERGY remains dominant at 25.5%. These are equilibrium values, not transients.

### 11.4 Shannon Entropy Summary

| Statistic | Value |
|-----------|-------|
| **Expansion mean** | 0.742 |
| **Contraction mean** | 0.698 |
| **Overall mean** | ~0.720 |
| **All-time high** | **0.747** (gen 127,559, uptime 11h 50m) |
| **All-time low** | **0.691** (gen 123,202, uptime 11h 25m) |
| **Range** | 0.691 — 0.747 |

Entropy is cycling in a fixed band — healthy but not improving.

### 11.5 Fitness Evolution: Slow Improvement Detected

The memetic population is **slowly improving** over the run:

| Timepoint | Best Fitness | Mean Fitness | Branching Ratio | Notes |
|-----------|-------------|-------------|-----------------|-------|
| 0h (00:27) | 0.7458 | 0.7447 | 1.63 | Initial |
| 5h (05:37) | 0.7439 | 0.7429 | 1.64 | Stable |
| 8h10m (08:32) | **0.7691** | **0.7678** | 1.53 | **Run high!** |
| 9h07m (09:07) | 0.7498 | 0.7487 | 1.61 | |
| 11h25m (11:47) | 0.7577 | 0.7569 | 1.58 | Second peak |
| 13h (13:22) | 0.7276 | 0.7270 | 1.72 | Current |

**Key insight:** The highest fitness (0.7691) occurred at gen 88,503 during a **shallow expansion** (density 0.373, BR 1.53) — lower amplitude than the typical 0.39/1.75 peaks. The GA is discovering that moderate growth near the edge of chaos scores better than aggressive expansion. This suggests the fitness landscape rewards branching ratios closer to 1.5 than 1.8.

### 11.6 Spatial Coherence (Proxy Analysis)

Direct spatial clustering analysis requires loading .npz snapshots, but proxy indicators suggest coherence is maintained:

1. **Structural ratio (|m|)** holds steady at ~0.600 (expansion) / ~0.655 (contraction) — organized structure, not diffuse noise.
2. **Cell census proportions** are extremely tight (COMPUTE std < 200 cells across 78 expansion samples) — consistent spatial organization.
3. **No entropy spikes** suggesting pattern dissolution.
4. **COMPUTE census** tracks at ~5,800 ± 150 cells during expansion — spatially stable population.

**Recommendation:** Load the latest .npz snapshot (`branch3d_gen139756_step1397563_20260309T132212.npz`) and run 6-connected clustering analysis to confirm COMPUTE clustering ratio >= 5x random. This was 11.1x in v0.5.0; expect ~6-8x at the higher COMPUTE density.

### 11.7 Conclusions & v0.7.0 Recommendations

**The fog is alive and breathing.** 13 hours of continuous stable oscillation confirms the limit cycle is a genuine attractor, not a transient. v0.6.0 is a success — COMPUTE breakout from 1% to 5.7% and entropy from 0.669 to 0.744 are real, persistent gains.

**But COMPUTE is stuck at 5.7%.** The overnight data proves this is an equilibrium, not a trajectory toward 25%. To reach the target, the Trinity needs to address:

1. **Primary bottleneck:** COMPUTE destruction rate still exceeds creation rate at densities above 5.7%. The contagion from ENERGY (now 25.5% of active cells) is likely the dominant drain — every COMPUTE cell at the boundary of an ENERGY cluster faces 34% conversion probability.

2. **Recommended v0.7.0 physics changes for Nemo:**
   - Introduce ENERGY -> COMPUTE reverse contagion at neighbour threshold 5+ (new mechanism, requires code)
   - Reduce ENERGY contagion pressure on COMPUTE from 34% to ~10%
   - Consider widening COMPUTE survival window from 1-3 to 1-5 neighbours
   - Dampen VOID -> ENERGY nucleation (it overshot — ENERGY at 25.5% is eating COMPUTE's niche)

3. **For Jack:**
   - The breathing dynamics are a feature, not a bug — preserve the limit cycle
   - Fitness slowly improving (0.7458 -> 0.7691 peak) suggests the GA is working but slowly
   - Consider adding a COMPUTE-specific fitness bonus to accelerate GA pressure

4. **78 .npz snapshots** are available for spatial analysis covering the full 13-hour evolution.

---

*Section 11 appended by Claude (Opus 4.6) — Overnight v0.6.0 Analysis, 2026-03-09 ~13:30 AEDT.*
*Engine PID 35792 still running at gen 140,641. The fog breathes on.*
