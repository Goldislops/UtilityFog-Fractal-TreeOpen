"""Phase 10.7: Expansive Compassion Continuum

Extends Phase 10.6 (Ice Battery + Trash Battery) with Nemo's circulatory model:
  - Semi-Porous Membranes: Elder cells continuously circulate energy (no distress trigger)
  - Thermodynamic Equanimity: Zero waste heat for equanimous cells (superconductor state)
  - Recursive Self-Tuning: KDE-based failure trajectory analysis per COMPUTE cell
  - Parasite Prevention: Anti-subsidy penalty for dependent cells
  - Graceful Hibernation: SIGTERM checkpoint serialization

Math (Nemo's blueprint):
  Elder circulation: E_circulate = excess * beta_base * exp(-lambda_mem * (age - tau_elder))
  Waste heat: 0.0 if is_equanimous else base_dissipation * energy * (1 + reactivity/sigma)
  Failure KDE: P(fail) = 1 - prod(1 - KDE_i) for i in {energy, age, density}
  Parasite check: if consecutive_receiving > 100 ticks, increase energy_stress penalty
"""

from __future__ import annotations
import math
import signal
import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
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
# Parameter dataclasses (Phase 10.6 base)
# ---------------------------------------------------------------------------
@dataclass
class EquanimityParams:
    """Phase 4 Equanimity Shield parameters (now with faster tau)."""
    p_max: float = 0.85
    tau: float = 2.0
    age_min: float = 3.0
    gamma: float = 0.5


@dataclass
class IceBatteryParams:
    """Ice Battery: COMPUTE elders burn stored energy for resistance spike."""
    k_ice: float = 2.5
    alpha: float = 0.7
    age_peak: float = 4.0
    sigma: float = 1.0
    activation_threshold: float = 0.5
    burn_rate: float = 0.20
    p_resist_max: float = 0.95


@dataclass
class TrashBatteryParams:
    """Trash Battery: STRUCTURAL cells harvest entropy from void decay."""
    harvest_efficiency: float = 0.15
    entropic_flux: float = 0.05
    max_reclaim_per_step: float = 0.05
    max_routing_distance: int = 3
    energy_decay_rate: float = 0.02
    max_energy_reserve: float = 5.0


# ---------------------------------------------------------------------------
# NEW: Expansive Compassion Continuum parameters (Nemo's blueprint)
# ---------------------------------------------------------------------------
@dataclass
class ExpansiveCompassionParams:
    """Mathematical parameters for the Expansive Compassion Continuum.
    Designed for Gen 1.15M+ stability with proactive compassion.
    """
    # Semi-Porous Membranes
    elder_age_threshold: float = 8.0       # tau_elder: age for Elder status
    elder_baseline_fraction: float = 0.15  # beta_base: baseline fraction circulated
    membrane_decay_rate: float = 0.05      # lambda_mem: decay of flow efficiency
    max_circulation_radius: int = 2        # r_max: neighborhood for distribution
    energy_sustenance_threshold: float = 1.0  # E_sustain: minimum to maintain integrity

    # Thermodynamic Equanimity (Zero Waste Heat)
    equanimity_window: int = 3             # w_eq: steps to evaluate stability
    stability_threshold: float = 0.05      # sigma_stable: max variance for stability
    reactivity_decay: float = 0.8          # gamma_react: decay rate of reactivity
    base_dissipation: float = 0.02         # standard heat loss for non-equanimous

    # Recursive Self-Tuning
    failure_memory_depth: int = 50         # N_fail: history depth
    tuning_learning_rate: float = 0.1      # eta_tune: parameter adjustment rate
    entropy_confidence_threshold: float = 0.7  # theta_conf: min confidence for tuning
    max_temperature_adjustment: float = 0.3    # delta_T_max
    kde_bandwidth: float = 0.5

    # Parasite Prevention
    max_consecutive_receiving: int = 100   # ticks before anti-subsidy kicks in
    subsidy_penalty_rate: float = 0.01     # additional energy stress per tick over limit

    # Compute Cell Bounds
    min_temperature: float = 0.1
    max_temperature: float = 2.0
    min_penalty: float = 0.0
    max_penalty: float = 1.0


@dataclass
class Phase106Params:
    """Combined Phase 10.6/10.7 thermodynamic parameters."""
    equanimity: EquanimityParams = field(default_factory=EquanimityParams)
    ice: IceBatteryParams = field(default_factory=IceBatteryParams)
    trash: TrashBatteryParams = field(default_factory=TrashBatteryParams)
    compassion: ExpansiveCompassionParams = field(default_factory=ExpansiveCompassionParams)


# ---------------------------------------------------------------------------
# Per-cell metadata (expanded for Phase 10.7)
# ---------------------------------------------------------------------------
@dataclass
class CellMeta:
    """Per-cell epigenetic state."""
    age: float = 0.0
    memory_strength: float = 1.0
    energy_reserve: float = 0.0
    # Phase 10.7 additions
    reactivity_history: List[float] = field(default_factory=list)
    consecutive_receiving: int = 0
    temperature: float = 1.0
    penalty: float = 0.0
    failure_energies: List[float] = field(default_factory=list)
    failure_ages: List[float] = field(default_factory=list)
    failure_densities: List[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure functions (used by tests and by FogSim)
# ---------------------------------------------------------------------------
def e_reclaim(n_void_neighbors: int, params: TrashBatteryParams) -> float:
    """Trash Battery: energy reclaimed from void neighbors."""
    raw = params.harvest_efficiency * n_void_neighbors * params.entropic_flux
    return min(raw, params.max_reclaim_per_step)


def e_deliver(
    source_idx: int,
    target_idx: int,
    adjacency: List[List[int]],
    max_distance: int,
) -> bool:
    """Check if source can route energy to target within max_distance hops."""
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
    """Equanimity Shield base resistance."""
    if age <= params.age_min:
        return 0.0
    return (
        params.p_max
        * (1.0 - math.exp(-(age - params.age_min) / params.tau))
        * math.tanh(params.gamma * M)
    )


def p_ice_boost(age: float, E_reserve: float, params: IceBatteryParams) -> float:
    """Ice Battery boost to Equanimity resistance."""
    if E_reserve < params.activation_threshold:
        return 0.0
    return (
        params.k_ice
        * (E_reserve ** params.alpha)
        * math.exp(-((age - params.age_peak) ** 2) / (2.0 * params.sigma ** 2))
    )


def p_resist(
    age: float, M: float, E_reserve: float, params: Phase106Params,
) -> float:
    """Total Equanimity resistance: base + ice boost, hard-capped."""
    base = p_base(age, M, params.equanimity)
    boost = p_ice_boost(age, E_reserve, params.ice)
    return min(base + boost, params.ice.p_resist_max)


# ---------------------------------------------------------------------------
# NEW: Expansive Compassion pure functions
# ---------------------------------------------------------------------------
def is_elder(age: float, energy: float, energy_mean: float,
             params: ExpansiveCompassionParams) -> bool:
    """Elder = Age exceeds threshold AND energy exceeds population mean."""
    return age >= params.elder_age_threshold and energy > energy_mean


def elder_circulation_amount(
    elder_energy: float, elder_age: float, params: ExpansiveCompassionParams,
) -> float:
    """Calculate total energy an elder will circulate this step.

    E_circulate = excess * beta_base * exp(-lambda_mem * (age - tau_elder))
    """
    excess = max(0.0, elder_energy - params.energy_sustenance_threshold)
    if excess <= 0:
        return 0.0
    permeability = params.elder_baseline_fraction * math.exp(
        -params.membrane_decay_rate * (elder_age - params.elder_age_threshold)
    )
    return excess * permeability


def calculate_reactivity(
    energy_current: float, energy_prev: float,
    neighbor_deltas: List[float],
) -> float:
    """Reactivity = |dE/dt| + sum(|neighbor_dE|)"""
    internal = abs(energy_current - energy_prev)
    external = sum(abs(d) for d in neighbor_deltas)
    return internal + external


def is_equanimous(
    reactivity_history: List[float], age: float,
    params: ExpansiveCompassionParams,
) -> bool:
    """Low reactivity for sustained window + minimum maturity age."""
    if age < params.equanimity_window:
        return False
    if len(reactivity_history) < params.equanimity_window:
        return False
    recent = reactivity_history[-params.equanimity_window:]
    avg = sum(recent) / len(recent)
    return avg < params.stability_threshold


def waste_heat(
    energy: float, reactivity: float, is_equanimous_state: bool,
    params: ExpansiveCompassionParams,
) -> float:
    """Zero waste heat when equanimous. Maps to superconductor state."""
    if is_equanimous_state:
        return 0.0
    reactivity_penalty = 1.0 + (reactivity / max(params.stability_threshold, 0.001))
    return params.base_dissipation * energy * reactivity_penalty


def kde_kernel(x: float, xi: float, bandwidth: float = 0.5) -> float:
    """Gaussian kernel for KDE."""
    return math.exp(-0.5 * ((x - xi) / bandwidth) ** 2) / (bandwidth * math.sqrt(2 * math.pi))


def predict_failure_probability(
    current_energy: float, current_age: float, current_density: float,
    meta: CellMeta, bandwidth: float = 0.5,
) -> Tuple[float, str]:
    """KDE-based failure probability prediction. Returns (prob, dominant_factor)."""
    if len(meta.failure_energies) < 5:
        return 0.5, "insufficient_data"

    n = len(meta.failure_energies)
    p_energy = sum(kde_kernel(current_energy, ef, bandwidth) for ef in meta.failure_energies) / n
    p_age = sum(kde_kernel(current_age, af, bandwidth) for af in meta.failure_ages) / n
    p_density = sum(kde_kernel(current_density, nd, bandwidth) for nd in meta.failure_densities) / n

    p_failure = 1 - (1 - p_energy) * (1 - p_age) * (1 - p_density)

    factors = {"energy_stress": p_energy, "age_degradation": p_age, "density_overload": p_density}
    dominant = max(factors, key=factors.get)

    return min(p_failure, 0.99), dominant


# ---------------------------------------------------------------------------
# Graceful Hibernation
# ---------------------------------------------------------------------------
_hibernation_callback = None

def register_hibernation(callback):
    """Register a callback to be called on SIGTERM/SIGINT for graceful shutdown."""
    global _hibernation_callback
    _hibernation_callback = callback

    def _handler(signum, frame):
        if _hibernation_callback:
            _hibernation_callback()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


# ---------------------------------------------------------------------------
# FogSim: Phase 10.7 CA stepping engine
# ---------------------------------------------------------------------------
class FogSim:
    """CA stepper with Phase 10.6 + 10.7 Expansive Compassion Continuum.

    Implements:
    - Trash Battery (energy harvest from void)
    - Ice Battery (resistance spike from stored energy)
    - Elder Circulation (continuous fountain-model energy flow)
    - Thermodynamic Equanimity (zero waste heat for stable cells)
    - Recursive Self-Tuning (KDE failure prediction)
    - Parasite Prevention (anti-subsidy penalty)
    - Graceful Hibernation (SIGTERM checkpoint)
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
        self._prev_energies = [0.0] * self.n

        # Per-cell metadata
        self.meta: List[CellMeta] = []
        for i in range(self.n):
            m = CellMeta()
            if states[i] == COMPUTE:
                m.memory_strength = 1.0
            self.meta.append(m)

        # Register hibernation checkpoint
        register_hibernation(self._hibernate)

    def step(self) -> None:
        """Advance one generation with Phase 10.7 thermodynamics."""
        neighbor_counts = self._count_neighbors()

        # Phase 10.6: Trash Battery harvest
        harvested = self._trash_battery_harvest(neighbor_counts)
        self._route_energy_to_compute(harvested)

        # Phase 10.7: Elder Circulation (continuous fountain)
        self._elder_circulation(neighbor_counts)

        # Phase 10.7: Thermodynamic Equanimity (update reactivity)
        self._update_reactivity(neighbor_counts)

        # Compute combined resistance
        resist = self._compute_resistance()

        # Apply transitions
        next_states = self._apply_transitions(neighbor_counts, resist)

        # Phase 10.7: Record failures for KDE
        self._record_failures(next_states, neighbor_counts)

        # Phase 10.7: Waste heat (zero for equanimous, penalty for reactive)
        self._apply_waste_heat()

        # Phase 10.7: Parasite prevention
        self._parasite_check()

        # Age/decay/burn
        self._update_metadata(next_states)

        self._prev_energies = [self.meta[i].energy_reserve for i in range(self.n)]
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

    def _hibernate(self) -> None:
        """Serialize state to checkpoint.fog on SIGTERM."""
        checkpoint = {
            "generation": self.generation,
            "states": self.states.tolist(),
            "meta": [
                {"age": m.age, "memory_strength": m.memory_strength,
                 "energy_reserve": m.energy_reserve,
                 "consecutive_receiving": m.consecutive_receiving,
                 "temperature": m.temperature, "penalty": m.penalty}
                for m in self.meta
            ],
        }
        path = "checkpoint.fog"
        with open(path, "w") as f:
            json.dump(checkpoint, f)
        print(f"Hibernated at gen {self.generation} -> {path}")

    # -------------------------------------------------------------------
    # Internal: Phase 10.6 mechanics
    # -------------------------------------------------------------------
    def _count_neighbors(self) -> List[List[int]]:
        counts = [[0] * 5 for _ in range(self.n)]
        for i in range(self.n):
            for j in self.adjacency[i]:
                s = min(int(self.states[j]), 4)
                counts[i][s] += 1
        return counts

    def _trash_battery_harvest(self, neighbor_counts):
        harvested = [0.0] * self.n
        tp = self.params.trash
        for i in range(self.n):
            if self.states[i] == STRUCTURAL:
                n_void = neighbor_counts[i][VOID]
                if n_void > 0:
                    harvested[i] = e_reclaim(n_void, tp)
        return harvested

    def _route_energy_to_compute(self, harvested):
        tp = self.params.trash
        compute_cells = [i for i in range(self.n) if self.states[i] == COMPUTE]
        if not compute_cells:
            return
        for i in range(self.n):
            if harvested[i] <= 0:
                continue
            reachable = [c for c in compute_cells
                         if e_deliver(i, c, self.adjacency, tp.max_routing_distance)]
            if reachable:
                share = harvested[i] / len(reachable)
                for c in reachable:
                    self.meta[c].energy_reserve = min(
                        self.meta[c].energy_reserve + share, tp.max_energy_reserve)

    def _compute_resistance(self):
        resist = [0.0] * self.n
        for i in range(self.n):
            if self.states[i] == COMPUTE:
                resist[i] = p_resist(
                    self.meta[i].age, self.meta[i].memory_strength,
                    self.meta[i].energy_reserve, self.params)
        return resist

    # -------------------------------------------------------------------
    # Internal: Phase 10.7 Expansive Compassion
    # -------------------------------------------------------------------
    def _elder_circulation(self, neighbor_counts):
        """Semi-porous membrane: Elders continuously circulate energy."""
        cp = self.params.compassion
        # Compute mean energy across COMPUTE cells
        compute_energies = [self.meta[i].energy_reserve
                           for i in range(self.n) if self.states[i] == COMPUTE]
        if not compute_energies:
            return
        energy_mean = sum(compute_energies) / len(compute_energies)

        for i in range(self.n):
            if self.states[i] != COMPUTE:
                continue
            if not is_elder(self.meta[i].age, self.meta[i].energy_reserve,
                           energy_mean, cp):
                continue

            # Calculate circulation amount
            e_circ = elder_circulation_amount(
                self.meta[i].energy_reserve, self.meta[i].age, cp)
            if e_circ <= 0:
                continue

            # Collect neighbors within r_max with energy deficit
            neighbors_in_range = []
            visited = {i}
            frontier = [i]
            for _hop in range(cp.max_circulation_radius):
                next_f = []
                for node in frontier:
                    for nb in self.adjacency[node]:
                        if nb not in visited:
                            visited.add(nb)
                            next_f.append(nb)
                            if self.states[nb] != VOID:
                                neighbors_in_range.append(nb)
                frontier = next_f

            if not neighbors_in_range:
                continue

            # Calculate deficit-weighted distribution (pull-agnostic)
            deficits = []
            total_deficit = 0.0
            for nb in neighbors_in_range:
                deficit = max(0.0, cp.energy_sustenance_threshold - self.meta[nb].energy_reserve)
                deficits.append(deficit)
                total_deficit += deficit

            if total_deficit <= 0:
                continue

            # Distribute proportional to need
            for nb, deficit in zip(neighbors_in_range, deficits):
                share = e_circ * (deficit / total_deficit)
                self.meta[nb].energy_reserve = min(
                    self.meta[nb].energy_reserve + share,
                    self.params.trash.max_energy_reserve)
                self.meta[nb].consecutive_receiving += 1

            # Deduct from elder
            self.meta[i].energy_reserve -= e_circ

    def _update_reactivity(self, neighbor_counts):
        """Track reactivity for equanimity detection."""
        cp = self.params.compassion
        for i in range(self.n):
            if self.states[i] != COMPUTE:
                continue
            # Calculate reactivity
            prev_e = self._prev_energies[i] if i < len(self._prev_energies) else 0.0
            neighbor_deltas = []
            for nb in self.adjacency[i]:
                prev_nb = self._prev_energies[nb] if nb < len(self._prev_energies) else 0.0
                neighbor_deltas.append(self.meta[nb].energy_reserve - prev_nb)

            react = calculate_reactivity(self.meta[i].energy_reserve, prev_e, neighbor_deltas)
            self.meta[i].reactivity_history.append(react)
            # Keep bounded
            if len(self.meta[i].reactivity_history) > cp.equanimity_window * 2:
                self.meta[i].reactivity_history = self.meta[i].reactivity_history[-cp.equanimity_window * 2:]

    def _apply_waste_heat(self):
        """Zero waste heat for equanimous cells, penalty for reactive."""
        cp = self.params.compassion
        for i in range(self.n):
            if self.states[i] != COMPUTE:
                continue
            eq_state = is_equanimous(self.meta[i].reactivity_history, self.meta[i].age, cp)
            if eq_state:
                pass  # Zero waste heat -- superconductor!
            else:
                react = self.meta[i].reactivity_history[-1] if self.meta[i].reactivity_history else 0.5
                heat = waste_heat(self.meta[i].energy_reserve, react, False, cp)
                self.meta[i].energy_reserve = max(0.0, self.meta[i].energy_reserve - heat)

    def _record_failures(self, next_states, neighbor_counts):
        """Record failure events for KDE self-tuning."""
        cp = self.params.compassion
        for i in range(self.n):
            if self.states[i] == COMPUTE and next_states[i] != COMPUTE:
                # This cell failed -- record context
                density = sum(neighbor_counts[i][1:]) / max(len(self.adjacency[i]), 1)
                self.meta[i].failure_energies.append(self.meta[i].energy_reserve)
                self.meta[i].failure_ages.append(self.meta[i].age)
                self.meta[i].failure_densities.append(density)
                # Trim to depth
                depth = cp.failure_memory_depth
                if len(self.meta[i].failure_energies) > depth:
                    self.meta[i].failure_energies = self.meta[i].failure_energies[-depth:]
                    self.meta[i].failure_ages = self.meta[i].failure_ages[-depth:]
                    self.meta[i].failure_densities = self.meta[i].failure_densities[-depth:]

    def _parasite_check(self):
        """Anti-subsidy: penalize cells that receive without growing."""
        cp = self.params.compassion
        for i in range(self.n):
            if self.states[i] == COMPUTE:
                if self.meta[i].consecutive_receiving > cp.max_consecutive_receiving:
                    # Increase energy stress penalty
                    extra_drain = cp.subsidy_penalty_rate * (
                        self.meta[i].consecutive_receiving - cp.max_consecutive_receiving)
                    self.meta[i].energy_reserve = max(0.0, self.meta[i].energy_reserve - extra_drain)
            # Reset counter if cell is NOT receiving this tick
            # (reset happens in elder_circulation when a cell gives, not receives)

    def _apply_transitions(self, neighbor_counts, resist):
        rng = np.random.default_rng()
        next_states = self.states.copy()
        for i in range(self.n):
            s = self.states[i]
            nc = neighbor_counts[i]
            r = rng.random()
            if s == VOID:
                non_void = sum(nc[1:])
                if non_void >= 3 and r < 0.08:
                    next_states[i] = STRUCTURAL
            elif s == STRUCTURAL:
                if r < 0.005:
                    next_states[i] = VOID
                elif r < 0.005 + 0.02:
                    next_states[i] = COMPUTE
                elif r < 0.005 + 0.02 + 0.01:
                    next_states[i] = ENERGY
            elif s == COMPUTE:
                decay_prob = 0.10
                if r < decay_prob:
                    if rng.random() < resist[i]:
                        next_states[i] = COMPUTE
                    else:
                        next_states[i] = STRUCTURAL
            elif s == ENERGY:
                if r < 0.005:
                    next_states[i] = VOID
                elif nc[COMPUTE] > 0 and r < 0.005 + 0.05:
                    next_states[i] = COMPUTE
            elif s == SENSOR:
                if r < 0.004:
                    next_states[i] = VOID
        return next_states

    def _update_metadata(self, next_states):
        tp = self.params.trash
        ip = self.params.ice
        for i in range(self.n):
            current = self.states[i]
            next_s = next_states[i]
            if next_s == COMPUTE:
                if current == COMPUTE:
                    self.meta[i].age += 1.0
                    if self.meta[i].energy_reserve >= ip.activation_threshold:
                        self.meta[i].energy_reserve *= (1.0 - ip.burn_rate)
                    self.meta[i].memory_strength = min(
                        self.meta[i].memory_strength + 0.01, 2.0)
                else:
                    self.meta[i].age = 0.0
                    self.meta[i].memory_strength = 1.0
                    self.meta[i].energy_reserve = 0.0
                    self.meta[i].reactivity_history = []
                    self.meta[i].consecutive_receiving = 0
            elif next_s == VOID:
                self.meta[i].age = 0.0
                self.meta[i].memory_strength = 1.0
                self.meta[i].energy_reserve = 0.0
                self.meta[i].reactivity_history = []
                self.meta[i].consecutive_receiving = 0
            if self.meta[i].energy_reserve > 0:
                self.meta[i].energy_reserve = max(
                    0.0, self.meta[i].energy_reserve - tp.energy_decay_rate)
