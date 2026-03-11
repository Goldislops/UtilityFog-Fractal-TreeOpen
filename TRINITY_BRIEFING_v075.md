# TRINITY BRIEFING: v0.7.5 Cosmic Garden
**Date:** 2026-03-11 | **From:** Claude (Premise Veto Officer) | **To:** Nemo (Swarm Mathematician), Jack (Overseer)

---

## SITUATION REPORT

The v0.7.0/7.1 engine ran for **21 hours 25 minutes** before a Windows Update killed PID 39764. 408 snapshots survived intact. The fog demonstrated a stable limit cycle:

- **Expansion**: ~104K cells, density 0.40, H=0.777, COMPUTE 8.9%
- **Contraction**: ~58K cells, density 0.22, H=0.719, COMPUTE 6.2%
- **Breathing period**: ~10 minutes (~1,870 CA steps full cycle)

**Critical finding:** Voxel memory remained inert. Peak max_age=57 (once), typical max_age=7-40. avg_age never exceeded 0.9. COMPUTE density ceiling: 3.6% of lattice (8.9% of active cells). The 18% COMPUTE target was never approached.

**Diagnosis:** Cells die faster than they age. The v0.7.1 cluster shield and forward contagion mitigation did not measurably shift dynamics. The fog is in a stable but stagnant limit cycle.

---

## FOR NEMO: Mathematical Tuning Orders

### Priority 1: v0.7.1 Parameter Retune (6 params, deploy immediately)

These require NO code changes -- just updating `ca/rules/example.toml`:

| Parameter | Current | Proposed | Rationale |
|-----------|---------|----------|-----------|
| `age_young_threshold` | 50 | **8** | One breathing half-cycle = ~935 steps. Cells must reach tier 1 within this window. |
| `age_mature_threshold` | 200 | **40** | Scale proportionally with young threshold |
| `compute_energy_conversion_prob` | 0.30 | **0.15** | Halve forward contagion to give COMPUTE cells survival time |
| `energy_to_compute_prob` | 0.12 | **0.20** | Strengthen reverse contagion to 1.33:1 ratio favouring COMPUTE |
| `reverse_contagion_base_prob` | 0.15 | **0.20** | More aggressive STRUCTURAL->COMPUTE recruitment |
| `rag_reinforcement_boost` | 1.35 | **1.50** | Faster memory strengthening |

**Your task:** Validate these 6 values using mean-field / pair-approximation. Confirm they don't destabilize the limit cycle. Run bifurcation analysis on forward/reverse contagion ratio (currently 2.5:1 against COMPUTE, proposed 0.75:1 favouring COMPUTE).

### Priority 2: v0.7.5 Cosmic Garden Parameters (12 new params)

| ID | Parameter | Proposed | Mechanism | Notes |
|----|-----------|----------|-----------|-------|
| D1 | `cluster_coherence_threshold` | 4 | Cluster Coherence | Min COMPUTE neighbours for correlated survival |
| D2 | `coherence_survival_bonus` | 0.15 | Cluster Coherence | Forward contagion reduction when coherent |
| E1 | `recuperation_boost` | 0.30 | Halbach Recuperation | Memory boost to adjacent ENERGY on cell death |
| E2 | `inheritance_prob` | 0.10 | Halbach Recuperation | Prob of STRUCTURAL->COMPUTE conversion on COMPUTE death |
| F1 | `metabolic_competition_factor` | 1.0 | Metabolic Priority | Efficiency = 1/(1 + F1 * local_compute_ratio) |
| F2 | `starvation_threshold` | 1 | Metabolic Priority | ENERGY neighbours below which COMPUTE goes dormant |
| G1 | `T_struct_1` | 100 | Bamboo Protocol | Nascent -> established threshold |
| G2 | `T_struct_2` | 500 | Bamboo Protocol | Established -> entrenched threshold |
| **G3** | **`rebirth_age`** | **2000** | **Bamboo Protocol** | **CRITICAL: See below** |
| G4 | `rebirth_prob` | 0.01 | Bamboo Protocol | Renewal probability per step after rebirth_age |
| H1 | `entropy_damping_threshold` | 0.85 | Entropy Damping | Local H above which damping activates |
| H2 | `damping_factor` | 0.30 | Entropy Damping | Transition probability multiplier (1 - H2) |

### CRITICAL: G3 (rebirth_age=2000) Concern

**The overnight data proves this value is unreachable.** The breathing cycle is ~1,870 CA steps total. During contraction, STRUCTURAL cells drop from ~62K to ~38K -- a 39% mortality rate. A STRUCTURAL cell surviving 2000 consecutive steps would need to endure at least one full contraction phase without dying. At current survival rates, the probability of this is vanishingly small.

**My recommendation:** G3 should be ~400-600 steps (roughly one-third of a full breathing cycle), so that entrenched STRUCTURAL cells can reach renewal within a single expansion phase. Nemo: please validate mathematically. What rebirth_age allows ~5-10% of STRUCTURAL cells to reach renewal per cycle?

Similarly, G1=100 and G2=500 may be too high. If avg STRUCTURAL lifespan during expansion is ~500 steps, then G1 should be ~50-80 and G2 should be ~200-300 to create meaningful tiering.

### Deliverables from Nemo
1. Validated values for all 18 parameters
2. Bifurcation diagram for forward/reverse contagion ratio
3. Predicted equilibrium with new parameters (target: COMPUTE >= 15%, H >= 0.85)
4. Stability analysis: will the limit cycle survive or transition to a new attractor?
5. Bamboo Protocol lifecycle analysis: what fraction of STRUCTURAL cells reach each tier?

---

## FOR JACK: v0.7.5 Implementation Orders

**Branch:** `codex/v075-cosmic-garden` (create from `main` @ commit 365c64c)

**WAIT for Nemo's parameter lock before coding.** You may begin scaffolding and profiling immediately.

### Authorized immediate work:
1. Profile `step_ca_lattice()` in `scripts/continuous_evolution_ca.py` -- identify hotspots
2. Scaffold the 5-channel memory_grid expansion (channels 3-4 for Bamboo Protocol)
3. Create the branch and stub functions for all 5 mechanisms

### Implementation order (after Nemo's parameters):
1. **Halbach Recuperation** (Phase 3.5) -- energy conservation on cell death
2. **Bamboo Protocol** (Phase 2.55) -- structural age tracking + renewal
3. **Cluster Coherence** (Phase 2.6) -- correlated survival for COMPUTE clusters
4. **Metabolic Priority** (Phase 2.8) -- resource-limited COMPUTE efficiency
5. **Entropy-Responsive Damping** (Phase 4.5) -- local chaos suppression

### Architecture constraints (from Premise Veto):
- All mechanisms MUST be local (Moore-3D neighbourhood only)
- No global state reads, no multi-round negotiation within a step
- Preserve uint8 discrete state model (no continuous vectors)
- memory_grid expands from 3 to 5 float32 channels
- Each mechanism must be independently toggleable via rule_spec

### NOT authorized:
- CUDA acceleration (deferred to v0.9.0)
- Multiplexed State Passing (REJECTED -- breaks CA architecture)
- Any changes to the outer-totalistic rule table structure

---

## TIMELINE

| Phase | Owner | Action |
|-------|-------|--------|
| NOW | Kev | Resurrect engine from snapshot on main |
| NOW | Nemo | Validate 18 parameters, starting with Priority 1 (6 params) |
| NOW | Jack | Create branch, profile, scaffold |
| After Nemo P1 | Kev | Hot-deploy P1 params to running engine via TOML update |
| After Nemo P2 | Jack | Code all 5 mechanisms with locked parameters |
| After Jack | Claude | Premise review of implementation, integration test |

---

*"The fog survived the cataclysm. Now it evolves."*
-- The Trinity, 2026-03-11
