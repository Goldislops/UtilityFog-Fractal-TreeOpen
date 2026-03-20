"""Phase 10.6: Thermodynamic Overhaul -- Ice Battery + Trash Battery

Nemo's exact mathematical blueprint for elder COMPUTE survival:
  - Trash Battery: STRUCTURAL cells harvest entropy from void neighbors
  - Ice Battery: COMPUTE elders burn stored energy for massive Equanimity spike
  - Combined P_resist hard-capped at 0.95

Math:
  E_reclaim = min(harvest_efficiency * N_void * entropic_flux, max_reclaim_per_step)
  P_base = p_max * (1 - exp(-(age - age_min)/tau)) * tanh(gamma * M)
  P_ice_boost = k_ice * E_reserve^alpha * exp(-((age - age_peak)^2) / (2 * sigma^2))
  P_resist_total = min(P_base + P_ice_boost, p_resist_max)
  Burn rate: 20% of E_reserve consumed per step when boost is active
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np


# ---------------------------------------------------------------------------
# Cell states
# ---------------------------------------------------------------------------
VOID = 0
STRUCTURAL = 1
COMPUTE = 2
ENERGY = 3
SENSOR = 4


# ---------------------------------------------------------------------------
# Parameter dataclasses
# ---------------------------------------------------------------------------
@dataclass
class EquanimityParams:
    """Phase 4 Equanimity Shield parameters (now with faster tau)."""
    p_max: float = 0.85
    tau: float = 2.0          # Was 5.0 in Phase 4, reduced for faster ramp
    age_min: float = 3.0
    gamma: float = 0.5        # Memory strength scaling in tanh


@dataclass
class IceBatteryParams:
    """Ice Battery: COMPUTE elders burn stored energy for resistance spike."""
    k_ice: float = 2.5        # Boost amplitude
    alpha: float = 0.7        # Energy exponent (sublinear -- diminishing returns)
    age_peak: float = 4.0     # Gaussian peak age for max boost
    sigma: float = 1.0        # Gaussian width
    activation_threshold: float = 0.5   # Min E_reserve to activate
    burn_rate: float = 0.20   # Fraction of E_reserve consumed per step
    p_resist_max: float = 0.95  # Hard cap on total resistance


@dataclass
class TrashBatteryParams:
    """Trash Battery: STRUCTURAL cells harvest entropy from void decay."""
    harvest_efficiency: float = 0.15    # Base harvest rate
    entropic_flux: float = 0.05         # Energy per void neighbor
    max_reclaim_per_step: float = 0.05  # Cap on energy harvested per step
    max_routing_distance: int = 3       # Max hops to route energy to COMPUTE
    energy_decay_rate: float = 0.02     # Natural energy dissipation per step
    max_energy_reserve: float = 5.0     # Cap on stored energy


@dataclass
class Phase106Params:
    """Combined Phase 10.6 thermodynamic parameters."""
    equanimity: EquanimityParams = field(default_factory=EquanimityParams)
    ice: IceBatteryParams = field(default_factory=IceBatteryParams)
    trash: TrashBatteryParams = field(default_factory=TrashBatteryParams)


# ---------------------------------------------------------------------------
# Per-cell metadata
# ---------------------------------------------------------------------------
@dataclass
class CellMeta:
    """Per-cell epigenetic state."""
    age: float = 0.0
    memory_strength: float = 1.0
    energy_reserve: float = 0.0


# ---------------------------------------------------------------------------
# Pure functions (used by tests and by FogSim)
# ---------------------------------------------------------------------------
def e_reclaim(n_void_neighbors: int, params: TrashBatteryParams) -> float:
    """Trash Battery: energy reclaimed from void neighbors.

    E_reclaim = min(harvest_efficiency * N_void * entropic_flux, max_reclaim_per_step)
    """
    raw = params.harvest_efficiency * n_void_neighbors * params.entropic_flux
    return min(raw, params.max_reclaim_per_step)


def e_deliver(
    source_idx: int,
    target_idx: int,
    adjacency: List[List[int]],
    max_distance: int,
) -> bool:
    """Check if source can route energy to target within max_distance hops.

    Simple BFS-based reachability check.
    """
    if max_distance <= 0:
        return source_idx == target_idx
    visited = {source_idx}
    frontier = [source_idx]
    for _hop in range(max_distance):
        next_frontier = []
        for node in frontier:
            for neighbor in adjacency[node]:
                if neighbor == target_idx:
                    return True
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    return False


def p_base(age: float, M: float, params: EquanimityParams) -> float:
    """Equanimity Shield base resistance.

    P_base = p_max * (1 - exp(-(age - age_min)/tau)) * tanh(gamma * M)
    Returns 0.0 if age <= age_min.
    """
    if age <= params.age_min:
        return 0.0
    return (
        params.p_max
        * (1.0 - math.exp(-(age - params.age_min) / params.tau))
        * math.tanh(params.gamma * M)
    )


def p_ice_boost(age: float, E_reserve: float, params: IceBatteryParams) -> float:
    """Ice Battery boost to Equanimity resistance.

    P_ice_boost = k_ice * E_reserve^alpha * exp(-((age - age_peak)^2) / (2 * sigma^2))
    Returns 0.0 if E_reserve < activation_threshold.
    """
    if E_reserve < params.activation_threshold:
        return 0.0
    return (
        params.k_ice
        * (E_reserve ** params.alpha)
        * math.exp(-((age - params.age_peak) ** 2) / (2.0 * params.sigma ** 2))
    )


def p_resist(
    age: float,
    M: float,
    E_reserve: float,
    params: Phase106Params,
) -> float:
    """Total Equanimity resistance: base + ice boost, hard-capped.

    P_resist_total = min(P_base + P_ice_boost, p_resist_max)
    """
    base = p_base(age, M, params.equanimity)
    boost = p_ice_boost(age, E_reserve, params.ice)
    return min(base + boost, params.ice.p_resist_max)


# ---------------------------------------------------------------------------
# FogSim: Phase 10.6 CA stepping engine
# ---------------------------------------------------------------------------
class FogSim:
    """Simplified CA stepper with Phase 10.6 thermodynamics.

    Wraps a flat state array with per-cell metadata and adjacency list.
    Implements Trash Battery energy harvesting, Ice Battery resistance boost,
    and basic state transitions with Equanimity shielding.
    """

    def __init__(
        self,
        states: np.ndarray,
        adjacency: List[List[int]],
        params: Phase106Params,
    ):
        self.states = states.copy().astype(np.uint8)
        self.adjacency = adjacency
        self.params = params
        self.generation: int = 0
        self.n = len(states)

        # Per-cell metadata
        self.meta: List[CellMeta] = []
        for i in range(self.n):
            m = CellMeta()
            if states[i] == COMPUTE:
                m.memory_strength = 1.0
            self.meta.append(m)

    def step(self) -> None:
        """Advance one generation with Phase 10.6 thermodynamics."""
        # 1. Count neighbors per state for each cell
        neighbor_counts = self._count_neighbors()

        # 2. Trash Battery: STRUCTURAL cells harvest void entropy
        harvested_energy = self._trash_battery_harvest(neighbor_counts)

        # 3. Route harvested energy to nearby COMPUTE cells
        self._route_energy_to_compute(harvested_energy)

        # 4. Compute Equanimity resistance for COMPUTE cells
        resist = self._compute_resistance()

        # 5. Apply state transitions with resistance
        next_states = self._apply_transitions(neighbor_counts, resist)

        # 6. Age COMPUTE cells, decay energy, burn Ice Battery fuel
        self._update_metadata(next_states)

        self.states = next_states
        self.generation += 1

    def step_n(self, n: int) -> None:
        """Step n generations."""
        for _ in range(n):
            self.step()

    def census(self) -> Dict[int, int]:
        """Count cells per state."""
        unique, counts = np.unique(self.states, return_counts=True)
        return {int(s): int(c) for s, c in zip(unique, counts)}

    def max_compute_age(self) -> float:
        """Max age among COMPUTE cells."""
        max_age = 0.0
        for i in range(self.n):
            if self.states[i] == COMPUTE and self.meta[i].age > max_age:
                max_age = self.meta[i].age
        return max_age

    def avg_compute_energy(self) -> float:
        """Average energy_reserve among COMPUTE cells."""
        total = 0.0
        count = 0
        for i in range(self.n):
            if self.states[i] == COMPUTE:
                total += self.meta[i].energy_reserve
                count += 1
        return total / max(count, 1)

    # -------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------
    def _count_neighbors(self) -> List[List[int]]:
        """Count neighbors by state for each cell. Returns [n][5] counts."""
        counts = [[0] * 5 for _ in range(self.n)]
        for i in range(self.n):
            for j in self.adjacency[i]:
                s = min(int(self.states[j]), 4)
                counts[i][s] += 1
        return counts

    def _trash_battery_harvest(self, neighbor_counts: List[List[int]]) -> List[float]:
        """STRUCTURAL cells harvest entropy from void neighbors.

        E_reclaim = min(harvest_efficiency * N_void * entropic_flux, max_reclaim)
        """
        harvested = [0.0] * self.n
        tp = self.params.trash
        for i in range(self.n):
            if self.states[i] == STRUCTURAL:
                n_void = neighbor_counts[i][VOID]
                if n_void > 0:
                    harvested[i] = e_reclaim(n_void, tp)
        return harvested

    def _route_energy_to_compute(self, harvested: List[float]) -> None:
        """Route harvested energy from STRUCTURAL to nearby COMPUTE cells.

        Uses simple nearest-neighbor delivery within max_routing_distance.
        Energy is distributed equally among reachable COMPUTE cells.
        """
        tp = self.params.trash

        # Find all COMPUTE cell indices
        compute_cells = [i for i in range(self.n) if self.states[i] == COMPUTE]
        if not compute_cells:
            return

        for i in range(self.n):
            if harvested[i] <= 0:
                continue

            # Find reachable COMPUTE cells within routing distance
            reachable = []
            for c in compute_cells:
                if e_deliver(i, c, self.adjacency, tp.max_routing_distance):
                    reachable.append(c)

            if reachable:
                share = harvested[i] / len(reachable)
                for c in reachable:
                    self.meta[c].energy_reserve = min(
                        self.meta[c].energy_reserve + share,
                        tp.max_energy_reserve,
                    )

    def _compute_resistance(self) -> List[float]:
        """Compute total Equanimity + Ice Battery resistance per cell."""
        resist = [0.0] * self.n
        for i in range(self.n):
            if self.states[i] == COMPUTE:
                resist[i] = p_resist(
                    self.meta[i].age,
                    self.meta[i].memory_strength,
                    self.meta[i].energy_reserve,
                    self.params,
                )
        return resist

    def _apply_transitions(
        self,
        neighbor_counts: List[List[int]],
        resist: List[float],
    ) -> np.ndarray:
        """Apply simplified state transitions with Equanimity resistance.

        - VOID cells with many non-void neighbors become STRUCTURAL
        - STRUCTURAL cells can spontaneously become COMPUTE, ENERGY, SENSOR
        - COMPUTE cells resist state changes via Equanimity + Ice Battery
        - All non-void cells have a small void decay chance
        """
        rng = np.random.default_rng()
        next_states = self.states.copy()

        for i in range(self.n):
            s = self.states[i]
            nc = neighbor_counts[i]
            r = rng.random()

            if s == VOID:
                # Recruit: VOID with 3+ non-void neighbors becomes STRUCTURAL
                non_void = sum(nc[1:])
                if non_void >= 3 and r < 0.08:
                    next_states[i] = STRUCTURAL

            elif s == STRUCTURAL:
                # Void decay (trash battery partially offsets this)
                if r < 0.005:
                    next_states[i] = VOID
                # Spontaneous differentiation
                elif r < 0.005 + 0.02:
                    next_states[i] = COMPUTE
                elif r < 0.005 + 0.02 + 0.01:
                    next_states[i] = ENERGY

            elif s == COMPUTE:
                # Equanimity: resist state change with probability p_resist
                decay_prob = 0.10  # Base kill rate for COMPUTE
                if r < decay_prob:
                    # Roll again against resistance
                    if rng.random() < resist[i]:
                        next_states[i] = COMPUTE  # Resisted!
                    else:
                        next_states[i] = STRUCTURAL  # Demoted

            elif s == ENERGY:
                if r < 0.005:
                    next_states[i] = VOID
                elif nc[COMPUTE] > 0 and r < 0.005 + 0.05:
                    next_states[i] = COMPUTE  # Biofilm leech

            elif s == SENSOR:
                if r < 0.004:
                    next_states[i] = VOID

        return next_states

    def _update_metadata(self, next_states: np.ndarray) -> None:
        """Age COMPUTE cells, decay energy reserves, burn Ice Battery fuel."""
        tp = self.params.trash
        ip = self.params.ice

        for i in range(self.n):
            current = self.states[i]
            next_s = next_states[i]

            if next_s == COMPUTE:
                if current == COMPUTE:
                    # Surviving COMPUTE: age +1, maybe burn ice battery
                    self.meta[i].age += 1.0

                    # Ice Battery burn: consume energy when boost is active
                    if self.meta[i].energy_reserve >= ip.activation_threshold:
                        self.meta[i].energy_reserve *= (1.0 - ip.burn_rate)

                    # Memory strength slowly increases with age
                    self.meta[i].memory_strength = min(
                        self.meta[i].memory_strength + 0.01,
                        2.0,
                    )
                else:
                    # Newly born COMPUTE
                    self.meta[i].age = 0.0
                    self.meta[i].memory_strength = 1.0
                    self.meta[i].energy_reserve = 0.0

            elif next_s == VOID:
                # Reset on void
                self.meta[i].age = 0.0
                self.meta[i].memory_strength = 1.0
                self.meta[i].energy_reserve = 0.0

            # Natural energy decay for all cells
            if self.meta[i].energy_reserve > 0:
                self.meta[i].energy_reserve = max(
                    0.0,
                    self.meta[i].energy_reserve - tp.energy_decay_rate,
                )
