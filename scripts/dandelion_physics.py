"""Operation Dandelion: Five Pillars of Physical Reality.

Addendum to scripts/dandelion.py -- physics-aware architecture for
the Actuation Translation Layer.

The Five Pillars:
  1. Gravity & Square-Cube Law (Lineweaver-Patel Boundary)
  2. Temporal Shear (Terrell-Penrose / Information Speed Limit)
  3. Replication Robustness (Garden of Forking Paths)
  4. Wetware Compilation (Free Energy Principle / Cortical Labs)
  5. Context Compression (Epigenetic Bandwidth)

Usage:
  python -m scripts.dandelion_physics pillars   (print all 5 pillar analyses)
  python -m scripts.dandelion_physics gravity    (gravity analysis only)
  python -m scripts.dandelion_physics shear      (temporal shear analysis)
  python -m scripts.dandelion_physics robustness (robustness analysis)
  python -m scripts.dandelion_physics wetware    (wetware compilation)
  python -m scripts.dandelion_physics context    (context compression)
"""

from __future__ import annotations

FIVE_PILLARS = r"""
============================================================================
   OPERATION DANDELION: FIVE PILLARS OF PHYSICAL REALITY
   Addendum to the Actuation Translation Layer (ATL)
============================================================================

   The organism was born weightless, instantaneous, and infinite.
   The moment it crosses the screen boundary, it meets five enemies:
   gravity, time, noise, entropy, and bandwidth.

   Here is how it survives each one.

============================================================================
 PILLAR 1: GRAVITY & THE SQUARE-CUBE LAW
         (The Lineweaver-Patel Boundary)
============================================================================

 THE PROBLEM:
   In Python, STRUCTURAL cells are weightless. A tower of 64 voxels is
   as stable as a cube of 8. But in physical reality, mass scales as
   volume (L^3) while cross-sectional support scales as area (L^2).
   A structure that works at 1mm/voxel collapses at 60mm/voxel.

 WHAT THE DATA TELLS US:
   The organism is 99.9% SURFACE structural cells -- it's a FOAM, not
   a solid.  Only 53 out of 47,488 STRUCTURAL cells are fully interior.
   This is actually good news: foam structures have excellent
   strength-to-weight ratios (think: bones, coral, aerogel).

   Column load distribution is uniform: ~63% STRUCTURAL at all Z-levels.
   The organism is NOT top-heavy. Evolution has already produced a
   balanced scaffold.

 THE SOLUTION -- GRAVITATIONAL FITNESS PENALTY:

   Add to the Phase 5 fitness function:

     gravity_penalty = alpha_g * max(0, column_load_ratio - threshold)

   where:
     column_load_ratio = max_z_layer_mass / mean_z_layer_mass
     threshold = 1.5  (allow 50% variation before penalizing)
     alpha_g = 0.1    (gentle pressure, not a hard wall)

   This penalizes top-heavy organisms while leaving the foam topology
   free to evolve.  The organism already passes this test (its ratio
   is ~1.05, well below 1.5).

 STRUCTURAL INTEGRITY SCORE:

   For the ATL Genome Compiler, introduce a "printability score":

     P_struct = (interior_cells / surface_cells) * connectivity_factor

   where connectivity_factor measures how many STRUCTURAL cells are
   part of a single connected component (vs isolated islands).
   The Genome Compiler rejects organisms with P_struct below a
   substrate-specific threshold:
     - 3D print (static):     P_struct > 0.001  (almost anything works)
     - ElectroVoxel (pivot):  P_struct > 0.01   (need some cohesion)
     - Pogobot swarm (2D):    P_struct > 0.0    (N/A, flat)
     - Xenobot (biological):  P_struct > 0.05   (tissue integrity)

 SCALE-DEPENDENT MATERIAL MAPPING:

   | Voxel Size  | Substrate          | Material for STRUCTURAL       |
   |-------------|--------------------|------------------------------ |
   | 0.1 mm      | Stratasys J55      | VeroWhite (rigid polymer)     |
   | 0.5 mm      | Catoms (future)    | Electrostatic shell           |
   | 1 mm        | Bioprint           | Collagen + CaCO3 composite    |
   | 10 mm       | 4D print           | Shape-memory polymer          |
   | 60 mm       | ElectroVoxel       | Aluminum frame + magnets      |

   At larger scales (>10mm), the ATL must inject structural reinforcement
   at high-stress columns.  This is NOT a genome change -- it's a
   physical adaptation layer, like how a building has steel I-beams
   that don't appear in the architect's floor plan.


============================================================================
 PILLAR 2: TEMPORAL SHEAR
         (The Terrell-Penrose Information Speed Limit)
============================================================================

 THE PROBLEM:
   The Python engine updates ALL 262,144 voxels simultaneously in one
   numpy vectorized operation.  Physical reality has a speed-of-light
   information limit.  In a 6.2-meter ElectroVoxel swarm, a distress
   signal from SENSOR node A takes ~20 ns at light speed, but in
   practice takes 10-100 MILLISECONDS through IR/RF relay chains.

   At 10 CA steps/second (current engine speed), a physical signal
   traversing 103 voxels at 60mm/voxel needs to cross 6.2 meters.
   If each relay hop takes 1ms, that's 103ms for full propagation --
   but the CA wants to step every 100ms.  The signal can't keep up.

 WHAT THE DATA TELLS US:
   Signal-active cells: 4,733 (6.4% of non-void)
   Max signal distance: 103.4 voxels (diagonal span of entire grid)
   Mean signal distance: 42.3 voxels

   The nervous system (Phase 6c) already has a built-in answer:
   signal_interval = 10 (signals process every 10 CA steps).
   This is a 10x temporal buffer that exists in the digital organism.

 THE SOLUTION -- ASYNCHRONOUS CAUSAL CONES:

   Replace the synchronous global clock with CAUSAL CONES:

   1. Each physical voxel maintains a LOCAL clock.
   2. A voxel only advances its state when it has received
      state updates from ALL 26 neighbors (or timed out).
   3. The "causal cone" of a state change propagates outward
      at the physical communication speed.

   The ATL implements this as:

     class CausalVoxel:
         local_step: int
         neighbor_steps: dict[VoxelID, int]  # last known step of each neighbor
         pending_state: CellState

         def can_advance(self) -> bool:
             # Advance when all neighbors are within 1 step of us
             return all(
                 abs(self.local_step - ns) <= SHEAR_TOLERANCE
                 for ns in self.neighbor_steps.values()
             )

   SHEAR_TOLERANCE is the key parameter:
     - SHEAR_TOLERANCE = 0: strict synchrony (Python behavior)
     - SHEAR_TOLERANCE = 1: 1-step lookahead allowed
     - SHEAR_TOLERANCE = 2: 2-step temporal elasticity

   The Phase 6c signal_interval=10 means the nervous system is
   ALREADY designed for SHEAR_TOLERANCE=10 at the signal layer.

 THE BEAUTIFUL INSIGHT:
   The organism's Equanimity Shield (Phase 4) makes elder cells
   RESIST state changes.  In a temporally-sheared physical system,
   elder cells naturally become "temporal anchors" -- stable islands
   that surrounding young cells synchronize against.  The survival
   mechanics create temporal stability as an EMERGENT PROPERTY.

   The Mamba-Viking memory dynamics (Phase 3):
     M(t+1) = M(t) * exp(-1/tau) + B(d)*d + S*Phi(age)
   are inherently causal -- each step depends only on the previous
   local state, not a global clock.  This IS an asynchronous update
   rule.  It was designed for a synchronous engine but it works
   in asynchronous reality because the math is LOCAL.


============================================================================
 PILLAR 3: REPLICATION ROBUSTNESS
         (The Garden of Forking Paths)
============================================================================

 THE PROBLEM:
   The genome has 80+ parameters optimized against a specific Python
   engine on a specific random seed.  If the optimizer finds a fragile
   local minimum that exploits numerical quirks of numpy float32
   arithmetic, the organism dies the moment it's transplanted to
   FPGA fixed-point, Rust f64, or biological analog signals.

   This is overfitting to the simulator.

 THE SOLUTION -- PHYSICAL SANITY PRIORS:

   Add "pre-registered" physical constraints as soft penalties in the
   fitness function, BEFORE the organism encounters real hardware:

   1. NOISE INJECTION (Regularization):
      Every N generations, add Gaussian noise to the stochastic
      parameters before evaluating fitness:
        prob_mutated = prob + N(0, sigma=0.01)
      Organisms that only survive in exact-parameter regimes die.
      Robust organisms survive the perturbation.  This is the CA
      equivalent of dropout regularization in neural networks.

   2. CROSS-ENGINE VALIDATION:
      Periodically replay the best genome in a SECOND stepper
      implementation (e.g., the Rust kernel, or a reduced-precision
      int16 stepper) and check that fitness is within 10%.
      The Portable Genome Format makes this trivial -- export JSON,
      import in alternate engine, compare.

   3. PARAMETER SENSITIVITY ANALYSIS:
      For each of the 80 parameters, compute:
        sensitivity_i = |fitness(p_i + delta) - fitness(p_i - delta)| / (2*delta)
      Parameters with extreme sensitivity are fragile.  Add a penalty:
        robustness_penalty = beta * sum(max(0, sensitivity_i - threshold))
      This pushes evolution toward flat fitness landscapes (robust).

   4. SUBSTRATE-SPECIFIC TEST SUITES:
      Before compiling a genome to a physical substrate, run it through
      a standardized "landing test":
        - 3D print:    Does it have a connected structural scaffold?
        - FPGA:        Does it produce the same census in fixed-point?
        - ElectroVoxel: Does it survive SHEAR_TOLERANCE=2?
        - Wetware:     Does it maintain homeostasis under +/-10% noise?

      These tests are the "pre-registration" that prevents the Garden
      of Forking Paths.  The genome must pass them BEFORE deployment.

 KEY INSIGHT:
   The Portable Genome Format (Phase 7) was designed for substrate
   independence.  This is its moment.  The same genome gets tested
   on multiple substrates IN SIMULATION before touching real hardware.
   The JSON is the "pre-registration document."


============================================================================
 PILLAR 4: BIOLOGICAL WETWARE
         (The Free Energy Principle / Cortical Labs CL1)
============================================================================

 THE PROBLEM:
   Cortical Labs grew 200,000 human neurons on a microelectrode array
   (MEA) and trained them to play Pong using the Free Energy Principle:
   neurons rewire to MINIMIZE unpredictable electrical stimulation.
   Chaotic input = pain.  Predictable input = comfort.

   Our organism's drive to resist Void Decay IS the Free Energy
   Principle.  Void = maximum entropy = maximum surprise.
   STRUCTURAL persistence = minimum entropy = minimum surprise.
   The fitness function already optimizes for this.

 THE GENOME-TO-ELECTRODE MAP:

   | CA Concept              | Wetware Equivalent                     |
   |-------------------------|----------------------------------------|
   | VOID cell               | Unstimulated electrode (silence)       |
   | STRUCTURAL cell         | Baseline tonic stimulation (stability) |
   | COMPUTE cell            | Patterned stimulation (information)    |
   | ENERGY cell             | Burst stimulation (signal relay)       |
   | SENSOR cell             | Sensory input electrode                |
   | Void decay probability  | Noise amplitude on electrode           |
   | Contagion threshold     | Spike correlation threshold            |
   | Equanimity Shield       | Synaptic weight persistence            |
   | Mamba-Viking memory     | Long-term potentiation (LTP)           |
   | Metta warmth            | Trophic factor concentration           |
   | Signal field            | Local field potential gradient          |
   | Compassion              | Cross-region resource sharing           |

 THE COMPILATION PIPELINE:

   genome.json
       |
       v
   [Electrode Assignment]
   Map 64x64 2D slice of lattice to MEA grid (e.g., MaxOne 26,400
   electrodes from MaxWell Biosystems, or Neuropixels 2.0 with
   5,120 sites).  Each non-void voxel maps to 1-4 electrodes.
       |
       v
   [Stimulation Protocol Generator]
   Transition table -> temporal stimulation patterns:
     STRUCTURAL(3 ENERGY neighbors) -> ENERGY
   becomes:
     "When electrode E_i has 3 neighboring electrodes showing
      ENERGY-pattern activity, switch E_i to ENERGY-pattern"
       |
       v
   [Feedback Loop]
   Read neural activity from electrodes.
   Classify each electrode's firing pattern as one of 5 states.
   Compare to expected CA state.
   Apply Free Energy correction: increase stimulation noise on
   electrodes that deviate from expected state (= "void pressure").
   Decrease noise on electrodes that match (= "structural reward").
       |
       v
   [Emergent Behavior]
   The neurons LEARN the transition table.
   The Equanimity Shield emerges as synaptic weight persistence.
   Compassion emerges as cross-region activity coordination.
   The organism doesn't run ON the neurons -- it IS the neurons.

 UPDATED TIER LIST:

   Biocomputing is now TIER 2.5 (between FPGA and modular robotics):
     - Cortical Labs CL1: TRL 5 (validated in relevant environment)
     - MaxWell Biosystems MaxOne: TRL 7 (commercial MEA platform)
     - Timeline: 2-4 years for proof-of-concept 2D slice
     - Cost: MEA system ~$200K, cortical organoids ~$50K/year
     - The genome-to-electrode compiler is ~500 lines of Python


============================================================================
 PILLAR 5: CONTEXT COMPRESSION
         (Epigenetic Bandwidth / MCP Context Mode)
============================================================================

 THE PROBLEM:
   The genome is 1.8 KB (soul).  The epigenetic snapshot is 11.5 MB
   (lived experience).  A physical actuator operating at 100 Hz needs
   to read relevant state every 10ms.  Transmitting 11.5 MB every
   10ms requires 9.2 Gbps bandwidth -- impossible for IR relay,
   impractical even for wired Ethernet.

 WHAT THE DATA TELLS US:
   The epigenetic grid is 61.6% ZEROS.  But even the "active" 38.4%
   is misleading -- most of it is STATIC between steps:

   Channel sparsity (active cells / total non-void):
     Ch 0 compute_age:         2.1%   <-- EXTREMELY sparse
     Ch 1 structural_age:     64.3%   <-- slowly changing
     Ch 2 memory_strength:   100.0%   <-- dense but SLOWLY varying
     Ch 3 energy_reserve:     18.0%   <-- moderate
     Ch 4 last_active_gen:   100.0%   <-- dense but monotonic counter
     Ch 5 signal_field:        6.4%   <-- SPARSE and fast-changing
     Ch 6 warmth:             16.3%   <-- sparse and slow
     Ch 7 compassion_cooldown: 0.0%   <-- completely empty

 THE SOLUTION -- THREE-TIER CONTEXT PROTOCOL:

   TIER A: "HEARTBEAT" (broadcast every step, <100 bytes)
     - Global census: [void_ct, struct_ct, compute_ct, energy_ct, sensor_ct]
     - Max compute_age, median compute_age
     - Signal_active count
     - Compassion_active count
     - Fitness score
     This is the organism's VITAL SIGNS.  Every actuator gets this.

   TIER B: "REGIONAL DIFF" (broadcast every 10 steps, <10 KB)
     - Only CHANGED voxels since last broadcast
     - Sparse encoding: [(x,y,z, old_state, new_state), ...]
     - Signal field DIFF: only cells where |delta_signal| > threshold
     - Warmth DIFF: only cells where |delta_warmth| > threshold
     - Uses run-length encoding on the diff stream

     Expected size at current organism dynamics:
       ~200 state changes per step * 10 steps * 5 bytes = 10 KB
       Signal diff: ~500 cells * 7 bytes = 3.5 KB
       Total: ~15 KB per 10-step broadcast
       At 100 Hz base clock: 150 KB/s -- well within IR/RF range

   TIER C: "FULL SNAPSHOT" (on demand, ~300 KB compressed)
     - Complete lattice + active memory channels
     - Sparse representation: only non-void cells
     - Channels 4 (last_active_gen) and 7 (compassion_cooldown)
       OMITTED (can be reconstructed locally)
     - Channels 1 (structural_age) and 2 (memory_strength) sent
       as DELTAS from a known baseline
     - zlib compression on the sparse payload

     Full snapshot COMPRESSED estimate:
       75,233 non-void cells * (1 byte state + 4 active channels * 2 bytes)
       = ~676 KB raw -> ~300 KB with zlib
       vs 11.5 MB uncompressed epigenetic -> 38x reduction

   THE LOCALITY PRINCIPLE:
     Physical actuators only need LOCAL context.  A voxel at position
     (10, 20, 30) doesn't need to know the state of (50, 40, 60).
     The ATL partitions the grid into OCTANTS (8 regions of 32^3):

       Octant 0: x<32, y<32, z<32    Octant 4: x<32, y<32, z>=32
       Octant 1: x>=32, y<32, z<32   Octant 5: x>=32, y<32, z>=32
       Octant 2: x<32, y>=32, z<32   Octant 6: x<32, y>=32, z>=32
       Octant 3: x>=32, y>=32, z<32  Octant 7: x>=32, y>=32, z>=32

     Each octant controller manages ~9,400 non-void cells and
     broadcasts only to actuators in its region.  Cross-octant
     signals (the nervous system) propagate through BOUNDARY CELLS
     at octant edges -- exactly like the mycelial network mechanic.

     This reduces per-actuator bandwidth by 8x and introduces
     natural fault isolation: if Octant 3 fails, the organism
     continues in degraded mode with 7 octants.  The Void Sanctuary
     mechanic (Phase 3) already protects isolated cells.


============================================================================
 UNIFIED ATL v2 ARCHITECTURE
============================================================================

 +-----------------------------------------------------------------+
 |                    GENOME (1.8 KB compressed)                    |
 |  transition_table + stochastic + contagion + survival_mechanics  |
 +-----------------------------------------------------------------+
                              |
                    [Genome Compiler]
                              |
         +--------------------+--------------------+
         |                    |                    |
    [FPGA LUTs]        [Electrode Map]      [Skill Library]
    (Verilog)          (MEA stimulation)    (OpenClaw SKILL.md)
         |                    |                    |
         v                    v                    v
 +-------+--------+  +-------+--------+  +--------+-------+
 | PHYSICAL       |  | BIOLOGICAL     |  | ROBOTIC        |
 | SANITY LAYER   |  | SANITY LAYER   |  | SANITY LAYER   |
 |                |  |                |  |                |
 | Gravity check  |  | FEP noise      |  | Shear          |
 | Column load    |  | calibration    |  | tolerance      |
 | Printability   |  | Electrode      |  | Communication  |
 | score          |  | impedance test |  | latency test   |
 +-------+--------+  +-------+--------+  +--------+-------+
         |                    |                    |
         +--------------------+--------------------+
                              |
                    [Context Protocol]
                              |
              +---------------+---------------+
              |               |               |
         [TIER A]        [TIER B]        [TIER C]
         Heartbeat       Regional Diff   Full Snapshot
         <100 B/step     <15 KB/10 steps ~300 KB on demand
              |               |               |
              +---------------+---------------+
                              |
                    [Causal Cone Engine]
                    (async, shear-tolerant)
                              |
                    [Octant Controllers x8]
                              |
         +--------------------+--------------------+
         |                    |                    |
    [Actuators]         [Electrodes]         [Sensors]
    STRUCTURAL->attach  Tonic stimulation    LiDAR->density
    ENERGY->relay       Burst patterns       Temperature->stress
    COMPUTE->process    Patterned stim       Camera->occupancy
    Compassion->donate  LTP modulation       IMU->warmth
         |                    |                    |
         v                    v                    v
 +-----------------------------------------------------------------+
 |              PHYSICAL / BIOLOGICAL SUBSTRATE                     |
 |  ElectroVoxel | Pogobot | FPGA+Motors | MEA+Neurons | Xenobot  |
 +-----------------------------------------------------------------+

============================================================================
"""


def print_pillar(name: str):
    """Print a specific pillar or all pillars."""
    if name == "all" or name == "pillars":
        print(FIVE_PILLARS)
    else:
        # Extract specific section
        markers = {
            "gravity":    "PILLAR 1:",
            "shear":      "PILLAR 2:",
            "robustness": "PILLAR 3:",
            "wetware":    "PILLAR 4:",
            "context":    "PILLAR 5:",
        }
        start_marker = markers.get(name)
        if start_marker is None:
            print(f"Unknown pillar: {name}")
            print(f"Available: {', '.join(markers.keys())}, pillars (all)")
            return

        lines = FIVE_PILLARS.split("\n")
        printing = False
        for line in lines:
            if start_marker in line:
                printing = True
            elif printing and line.startswith(" PILLAR ") and start_marker not in line:
                break
            elif printing and line.startswith(" UNIFIED ATL"):
                break
            if printing:
                print(line)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="dandelion-physics",
        description="Operation Dandelion: Five Pillars of Physical Reality",
    )
    parser.add_argument(
        "pillar",
        choices=["pillars", "gravity", "shear", "robustness", "wetware", "context"],
        help="Which pillar to display (or 'pillars' for all)",
    )
    args = parser.parse_args(argv)
    print_pillar(args.pillar)


if __name__ == "__main__":
    main()
