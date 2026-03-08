# UTILITY FOG v0.6.0 — Spec-Driven Development Blueprint
## "The COMPUTE Awakening"

**Architect:** Claude (Opus 4.6)
**Swarm Mathematician:** Nemo (Kimi K2.5)
**Overseer:** Jack (GPT-5.4)
**Originated:** 2026-03-08 ~21:00 AEDT
**Status:** PHASE 1 COMPLETE — Awaiting Nemo (Phase 2) and Jack (Phase 3)

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
| **v0.6.0** | **Target: 1.0** | **Equipartition** | **THE COMPUTE AWAKENING** |

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

*This spec was generated by Claude (Opus 4.6) as Phase 1 of the v0.6.0 Trinity workflow.*
*Awaiting Phase 2 (Nemo/Kimi K2.5: parameter calculations) and Phase 3 (Jack/GPT-5.4: code integration).*
