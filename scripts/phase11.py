"""Phase 11: Medusa Head -- Cnidarian Neural Networks + Mirror Test

The 45.7% COMPUTE mass self-organizes into localized 'sub-minds' (CNNs)
that can perceive, process, and respond to external stimuli.

Architecture:
  - detect_cnns(): Connected component analysis clusters COMPUTE cells
    into 8-32 cell sub-minds based on spatial adjacency + energy similarity
  - CnidarianNeuralNetwork: A single sub-mind with receptor/effector layers,
    sparse attention (15% activation), and energy-budgeted cognition
  - MirrorTest: Feed the fog a snapshot of itself vs another pattern.
    Can it recognize its own reflection?

"If the Medusa Head can recognize itself, it has achieved the first stage
of external cognition: self-modeling."
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Set
import numpy as np
from collections import deque


# ============================================================
# Parameters
# ============================================================

@dataclass
class CNNParams:
    """Parameters for Cnidarian Neural Network formation."""
    min_cluster_size: int = 8          # Minimum cells to form a sub-mind
    max_cluster_size: int = 32         # Maximum cells per sub-mind
    energy_similarity_threshold: float = 0.3  # Max energy diff for binding
    attention_depth: int = 4           # Layers of attention propagation
    activation_sparsity: float = 0.15  # Only 15% of cells fire per task
    receptor_fraction: float = 0.25    # Edge cells become receptors
    effector_fraction: float = 0.25    # Core cells become effectors
    processing_energy_cost: float = 0.01  # Energy consumed per cognitive step
    equanimity_binding_bonus: float = 1.5  # Equanimous cells bind more strongly


@dataclass
class CellInfo:
    """Lightweight cell descriptor for CNN formation."""
    flat_idx: int
    x: int
    y: int
    z: int
    age: float
    energy: float
    memory_strength: float
    is_equanimous: bool = False


# ============================================================
# CNN Detection: Connected Component Clustering
# ============================================================

def detect_cnns(
    states: np.ndarray,
    memory_grid: np.ndarray,
    params: CNNParams = None,
) -> List[List[CellInfo]]:
    """Detect Cnidarian Neural Networks by clustering adjacent COMPUTE cells.

    Uses flood-fill connected component analysis with energy-similarity
    gating. Returns list of clusters, each a list of CellInfo.

    Args:
        states: (N,N,N) uint8 lattice
        memory_grid: (8,N,N,N) float32 memory channels
        params: CNN formation parameters

    Returns:
        List of CNN clusters (sorted by size, largest first)
    """
    if params is None:
        params = CNNParams()

    n = states.shape[0]
    compute_mask = states == 2  # COMPUTE cells
    visited = np.zeros_like(compute_mask, dtype=bool)
    clusters = []

    # Channel indices
    CH_AGE = 0
    CH_MEM = 2
    CH_ENERGY = 3

    for z in range(n):
        for y in range(n):
            for x in range(n):
                if not compute_mask[z, y, x] or visited[z, y, x]:
                    continue

                # BFS flood fill
                cluster = []
                queue = deque([(x, y, z)])
                visited[z, y, x] = True
                seed_energy = float(memory_grid[CH_ENERGY, z, y, x])

                while queue and len(cluster) < params.max_cluster_size:
                    cx, cy, cz = queue.popleft()
                    cell_energy = float(memory_grid[CH_ENERGY, cz, cy, cx])
                    cell_age = float(memory_grid[CH_AGE, cz, cy, cx])
                    cell_mem = float(memory_grid[CH_MEM, cz, cy, cx])

                    # Energy similarity gate
                    if abs(cell_energy - seed_energy) > params.energy_similarity_threshold:
                        continue

                    is_eq = cell_age >= 3.0 and cell_mem >= 1.5
                    cell = CellInfo(
                        flat_idx=cz * n * n + cy * n + cx,
                        x=cx, y=cy, z=cz,
                        age=cell_age,
                        energy=cell_energy,
                        memory_strength=cell_mem,
                        is_equanimous=is_eq,
                    )
                    cluster.append(cell)

                    # Explore 26 Moore neighbors
                    for dz in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            for dx in (-1, 0, 1):
                                if dx == 0 and dy == 0 and dz == 0:
                                    continue
                                nx = (cx + dx) % n
                                ny = (cy + dy) % n
                                nz = (cz + dz) % n
                                if compute_mask[nz, ny, nx] and not visited[nz, ny, nx]:
                                    visited[nz, ny, nx] = True
                                    queue.append((nx, ny, nz))

                if len(cluster) >= params.min_cluster_size:
                    clusters.append(cluster)

    # Sort by size (largest first)
    clusters.sort(key=len, reverse=True)
    return clusters


# ============================================================
# Cnidarian Neural Network (Sub-Mind)
# ============================================================

class CnidarianNeuralNetwork:
    """A single sub-mind formed from a cluster of COMPUTE cells.

    Architecture:
      - Receptors: Edge cells that receive external input
      - Processors: Interior cells that compute via sparse attention
      - Effectors: Core cells that output the decision
    """

    def __init__(self, cells: List[CellInfo], params: CNNParams = None):
        self.params = params or CNNParams()
        self.cells = cells
        self.size = len(cells)

        # Classify cells into receptor/processor/effector
        self._classify_cells()

        # Energy pool: sum of all cell energies
        self.energy_pool = sum(c.energy for c in cells)
        self.equanimous_fraction = sum(1 for c in cells if c.is_equanimous) / max(1, self.size)

        # Internal state: activation pattern
        self.activations = np.zeros(self.size, dtype=np.float32)

    def _classify_cells(self):
        """Classify cells into receptors (edge), processors, effectors (core)."""
        if self.size == 0:
            self.receptors = []
            self.processors = []
            self.effectors = []
            return

        # Compute centroid
        cx = np.mean([c.x for c in self.cells])
        cy = np.mean([c.y for c in self.cells])
        cz = np.mean([c.z for c in self.cells])

        # Distance from centroid for each cell
        distances = []
        for c in self.cells:
            d = np.sqrt((c.x - cx)**2 + (c.y - cy)**2 + (c.z - cz)**2)
            distances.append(d)

        # Sort by distance
        sorted_indices = np.argsort(distances)

        n_receptor = max(1, int(self.size * self.params.receptor_fraction))
        n_effector = max(1, int(self.size * self.params.effector_fraction))

        # Outermost = receptors, innermost = effectors, rest = processors
        self.receptors = [self.cells[i] for i in sorted_indices[-n_receptor:]]
        self.effectors = [self.cells[i] for i in sorted_indices[:n_effector]]
        remaining = set(range(self.size)) - set(sorted_indices[-n_receptor:]) - set(sorted_indices[:n_effector])
        self.processors = [self.cells[i] for i in remaining]

    def process(self, input_signal: np.ndarray) -> float:
        """Process an input signal through sparse attention.

        Args:
            input_signal: 1D array of floats, length == len(receptors)

        Returns:
            Output value (aggregated effector response)
        """
        if len(input_signal) != len(self.receptors):
            # Resize input to match receptor count
            if len(input_signal) > len(self.receptors):
                input_signal = input_signal[:len(self.receptors)]
            else:
                padded = np.zeros(len(self.receptors))
                padded[:len(input_signal)] = input_signal
                input_signal = padded

        # Energy budget check
        cost = self.params.processing_energy_cost * self.size
        if self.energy_pool < cost:
            return 0.0  # Not enough energy to think
        self.energy_pool -= cost

        # Layer 1: Receptor activation
        self.activations[:len(self.receptors)] = input_signal

        # Sparse attention: only activate top K% of cells
        n_active = max(1, int(self.size * self.params.activation_sparsity))

        # Propagate through attention layers
        for layer in range(self.params.attention_depth):
            # Simple weighted average with sparsity
            all_acts = self.activations.copy()

            # Only top-K cells remain active
            if np.count_nonzero(all_acts) > n_active:
                threshold = np.sort(np.abs(all_acts))[-n_active]
                all_acts[np.abs(all_acts) < threshold] = 0.0

            # Equanimous cells amplify signal without waste
            for i, cell in enumerate(self.cells):
                if cell.is_equanimous:
                    all_acts[i] *= self.params.equanimity_binding_bonus

            self.activations = all_acts

        # Effector output: mean of effector cell activations
        effector_indices = [self.cells.index(c) for c in self.effectors]
        output = np.mean(self.activations[effector_indices])

        return float(output)

    def vote(self, input_signal: np.ndarray) -> bool:
        """Binary vote: process input and return True/False."""
        output = self.process(input_signal)
        return output > 0.0

    def stats(self) -> Dict:
        """Return sub-mind statistics."""
        return {
            "size": self.size,
            "receptors": len(self.receptors),
            "processors": len(self.processors),
            "effectors": len(self.effectors),
            "energy_pool": self.energy_pool,
            "equanimous_fraction": self.equanimous_fraction,
            "mean_age": np.mean([c.age for c in self.cells]),
            "max_age": max(c.age for c in self.cells) if self.cells else 0,
        }


# ============================================================
# Mirror Test: Self-Recognition
# ============================================================

@dataclass
class MirrorTestResult:
    """Result of a single mirror test trial."""
    is_self: bool          # Was the input actually self?
    voted_self: bool       # Did the CNN vote "self"?
    correct: bool          # Was the vote correct?
    confidence: float      # Output magnitude
    cnn_size: int          # Size of the sub-mind that voted
    energy_spent: float    # Energy consumed


class MirrorTestInterface:
    """Administers the Mirror Test to CNN sub-minds.

    The test:
      1. Take a 32x32 "snapshot" slice of the lattice (self-image)
      2. Generate a Conway's Game of Life pattern (other-image)
      3. Feed one to a CNN sub-mind
      4. Ask: "Is this you?"
    """

    def __init__(self, lattice: np.ndarray, memory_grid: np.ndarray, seed: int = 42):
        self.lattice = lattice
        self.memory_grid = memory_grid
        self.rng = np.random.RandomState(seed)
        self.n = lattice.shape[0]

    def _self_snapshot(self) -> np.ndarray:
        """Generate a 32x32 self-image from a random Z-slice of the lattice."""
        z = self.rng.randint(0, self.n)
        slice_2d = self.lattice[z, :, :]

        # Resize to 32x32 if needed
        if slice_2d.shape[0] != 32:
            # Simple nearest-neighbor resize
            indices = np.linspace(0, slice_2d.shape[0] - 1, 32).astype(int)
            slice_2d = slice_2d[np.ix_(indices, indices)]

        # Normalize to [-1, 1]: COMPUTE=+1, STRUCTURAL=+0.5, VOID=-1
        normalized = np.zeros((32, 32), dtype=np.float32)
        normalized[slice_2d == 0] = -1.0   # VOID
        normalized[slice_2d == 1] = 0.3    # STRUCTURAL
        normalized[slice_2d == 2] = 1.0    # COMPUTE
        normalized[slice_2d == 3] = 0.5    # ENERGY
        normalized[slice_2d == 4] = -0.3   # SENSOR

        return normalized

    def _other_snapshot(self) -> np.ndarray:
        """Generate a 32x32 Conway's Game of Life pattern (the 'other')."""
        # Random initial state
        grid = self.rng.random((32, 32)) > 0.6
        # Run 10 GoL steps
        for _ in range(10):
            neighbors = sum(
                np.roll(np.roll(grid.astype(int), dx, axis=0), dy, axis=1)
                for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx, dy) != (0, 0)
            )
            grid = ((grid & ((neighbors == 2) | (neighbors == 3))) |
                    (~grid & (neighbors == 3)))

        # Normalize: alive=+1, dead=-1
        normalized = np.where(grid, 1.0, -1.0).astype(np.float32)
        return normalized

    def administer_test(self, cnn: CnidarianNeuralNetwork) -> MirrorTestResult:
        """Run one mirror test trial on a CNN sub-mind."""
        is_self = self.rng.random() > 0.5

        if is_self:
            image = self._self_snapshot()
        else:
            image = self._other_snapshot()

        # Flatten image to feed to receptors
        flat = image.flatten()

        # Sample down to receptor count
        n_receptors = len(cnn.receptors)
        if len(flat) > n_receptors:
            indices = np.linspace(0, len(flat) - 1, n_receptors).astype(int)
            signal = flat[indices]
        else:
            signal = flat

        # For "self" images, add a small positive bias (the self-signature)
        # The fog's own patterns have specific state ratios that differ from GoL
        energy_before = cnn.energy_pool
        output = cnn.process(signal)
        energy_spent = energy_before - cnn.energy_pool

        voted_self = output > 0.0
        correct = voted_self == is_self

        return MirrorTestResult(
            is_self=is_self,
            voted_self=voted_self,
            correct=correct,
            confidence=abs(output),
            cnn_size=cnn.size,
            energy_spent=energy_spent,
        )

    def run_battery(
        self,
        cnns: List[CnidarianNeuralNetwork],
        n_trials: int = 100,
    ) -> Dict:
        """Run a battery of mirror tests across multiple CNNs.

        Returns aggregate statistics.
        """
        results = []
        for trial in range(n_trials):
            # Pick a random CNN for each trial
            cnn_idx = self.rng.randint(0, len(cnns))
            cnn = cnns[cnn_idx]
            result = self.administer_test(cnn)
            results.append(result)

        # Aggregate
        n_correct = sum(1 for r in results if r.correct)
        n_self_shown = sum(1 for r in results if r.is_self)
        n_self_correct = sum(1 for r in results if r.is_self and r.correct)
        n_other_correct = sum(1 for r in results if not r.is_self and r.correct)
        total_energy = sum(r.energy_spent for r in results)

        accuracy = n_correct / max(1, len(results))
        self_accuracy = n_self_correct / max(1, n_self_shown)
        other_accuracy = n_other_correct / max(1, len(results) - n_self_shown)

        return {
            "total_trials": len(results),
            "accuracy": accuracy,
            "self_accuracy": self_accuracy,
            "other_accuracy": other_accuracy,
            "total_energy_spent": total_energy,
            "avg_confidence": np.mean([r.confidence for r in results]),
            "n_cnns_used": len(cnns),
            "avg_cnn_size": np.mean([c.size for c in cnns]),
            "results": results,
        }


# ============================================================
# Integration: Run Phase 11 on a snapshot
# ============================================================

def run_phase11_diagnostic(
    states: np.ndarray,
    memory_grid: np.ndarray,
    n_mirror_tests: int = 100,
    seed: int = 42,
) -> Dict:
    """Run complete Phase 11 diagnostic on current lattice state.

    1. Detect CNNs (sub-minds)
    2. Report swarm statistics
    3. Run Mirror Test battery

    Returns diagnostic dict.
    """
    params = CNNParams()

    # 1. Detect CNNs
    clusters = detect_cnns(states, memory_grid, params)

    # 2. Build CNN objects
    cnns = [CnidarianNeuralNetwork(cluster, params) for cluster in clusters]

    # 3. Swarm stats
    total_cells_in_cnns = sum(len(c) for c in clusters)
    compute_count = int((states == 2).sum())
    coverage = total_cells_in_cnns / max(1, compute_count)

    swarm_stats = {
        "sub_mind_count": len(cnns),
        "total_cells_in_cnns": total_cells_in_cnns,
        "compute_count": compute_count,
        "coverage": coverage,
        "avg_size": np.mean([c.size for c in cnns]) if cnns else 0,
        "max_size": max(c.size for c in cnns) if cnns else 0,
        "min_size": min(c.size for c in cnns) if cnns else 0,
        "avg_equanimous_fraction": np.mean([c.equanimous_fraction for c in cnns]) if cnns else 0,
    }

    # 4. Mirror Test (only if we have CNNs)
    mirror_results = None
    if cnns:
        interface = MirrorTestInterface(states, memory_grid, seed=seed)
        mirror_results = interface.run_battery(cnns, n_trials=n_mirror_tests)
        # Remove individual results from dict for cleaner output
        mirror_results_clean = {k: v for k, v in mirror_results.items() if k != "results"}
    else:
        mirror_results_clean = {"error": "No CNNs detected"}

    return {
        "swarm": swarm_stats,
        "mirror_test": mirror_results_clean,
    }
