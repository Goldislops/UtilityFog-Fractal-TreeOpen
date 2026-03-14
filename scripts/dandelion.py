"""Operation Dandelion: Genome Dissemination Pipeline.

Phase 9 -- Seed dispersal to the digital four winds and physical substrates.

Seeds:
  1. QR Code Generator  -- organism DNA on a business card
  2. 3MF/STL Exporter   -- multi-material 3D print files
  3. WASM Build Script   -- browser-native CA engine

Actuation Translation Layer (ATL):
  Conceptual architecture for bridging genome → physical hardware.
  Maps SENSOR→real-world-input, STRUCTURAL/ENERGY→actuator-commands.

Usage:
  python -m scripts.dandelion qr <genome.json> [--output genome_qr.png]
  python -m scripts.dandelion stl <snapshot.npz> [--output organism.stl]
  python -m scripts.dandelion 3mf <snapshot.npz> [--output organism.3mf]
  python -m scripts.dandelion slices <snapshot.npz> [--output-dir slices/]
  python -m scripts.dandelion atl  (print ATL architecture)
  python -m scripts.dandelion info <genome.json>  (QR feasibility check)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import zlib
from pathlib import Path
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# State → color for visualization and 3D printing
STATE_PRINT_COLORS = {
    0: (200, 200, 200),  # VOID   → light grey (support/empty)
    1: ( 33, 150, 243),  # STRUCTURAL → blue (the body)
    2: ( 76, 175,  80),  # COMPUTE → green (the brain)
    3: (255, 152,   0),  # ENERGY  → orange (mycelial highways)
    4: (224,  64, 251),  # SENSOR  → magenta (surface receptors)
}

STATE_NAMES = {0: "VOID", 1: "STRUCTURAL", 2: "COMPUTE", 3: "ENERGY", 4: "SENSOR"}


# ---------------------------------------------------------------------------
# Seed 1: QR Code Generator
# ---------------------------------------------------------------------------

def genome_to_compressed_bytes(genome_path: str) -> bytes:
    """Load a genome JSON, strip epigenetic data, minify, and zlib compress."""
    with open(genome_path, "r") as f:
        genome = json.load(f)

    # Strip epigenetic snapshot (too large for QR)
    genome.pop("epigenetic_snapshot", None)

    # Minify
    minified = json.dumps(genome, separators=(",", ":"), sort_keys=True)

    # Compress
    compressed = zlib.compress(minified.encode("utf-8"), level=9)
    return compressed


def compressed_to_b85(compressed: bytes) -> str:
    """Encode compressed bytes as base85 (more efficient than base64 for QR)."""
    return base64.b85encode(compressed).decode("ascii")


def generate_qr(
    genome_path: str,
    output_path: str = "organism_genome_qr.png",
    box_size: int = 6,
    border: int = 4,
    error_correction: str = "L",
) -> dict:
    """Generate a QR code containing the compressed genome.

    Returns metadata dict with sizes and QR version info.
    """
    try:
        import qrcode
        from qrcode.constants import (
            ERROR_CORRECT_L,
            ERROR_CORRECT_M,
            ERROR_CORRECT_Q,
            ERROR_CORRECT_H,
        )
    except ImportError:
        raise ImportError(
            "qrcode library required. Install with: pip install qrcode[pil]"
        )

    ec_map = {
        "L": ERROR_CORRECT_L,
        "M": ERROR_CORRECT_M,
        "Q": ERROR_CORRECT_Q,
        "H": ERROR_CORRECT_H,
    }
    ec_level = ec_map.get(error_correction.upper(), ERROR_CORRECT_L)

    # Load, compress, encode
    compressed = genome_to_compressed_bytes(genome_path)
    b85_data = compressed_to_b85(compressed)

    # Build QR with header for decoder
    qr_payload = f"UFG1:{b85_data}"  # UFG1 = UtilityFog Genome v1 prefix

    qr = qrcode.QRCode(
        version=None,  # auto-fit
        error_correction=ec_level,
        box_size=box_size,
        border=border,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img.save(output_path)

    # Read back original for size comparison
    with open(genome_path, "r") as f:
        original_size = len(f.read().encode("utf-8"))

    return {
        "original_json_bytes": original_size,
        "minified_bytes": len(json.dumps(
            json.load(open(genome_path)), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")),
        "compressed_bytes": len(compressed),
        "b85_encoded_chars": len(b85_data),
        "qr_payload_chars": len(qr_payload),
        "qr_version": qr.version,
        "qr_error_correction": error_correction.upper(),
        "output_path": output_path,
        "fits_single_qr": qr.version <= 40,
    }


def decode_qr_payload(payload: str) -> dict:
    """Decode a QR payload back to genome dict.

    Payload format: UFG1:<base85-encoded-zlib-compressed-minified-json>
    """
    if not payload.startswith("UFG1:"):
        raise ValueError("Not a UtilityFog Genome QR code (missing UFG1: prefix)")

    b85_data = payload[5:]  # strip "UFG1:"
    compressed = base64.b85decode(b85_data)
    minified = zlib.decompress(compressed).decode("utf-8")
    return json.loads(minified)


# ---------------------------------------------------------------------------
# Seed 2: 3D Print Export (STL + 3MF + Voxel Slices)
# ---------------------------------------------------------------------------

def lattice_to_stl(
    lattice: np.ndarray,
    output_path: str = "organism.stl",
    states_to_include: Optional[list] = None,
) -> str:
    """Export organism lattice as STL mesh using marching cubes.

    Each non-void state is extracted as a separate isosurface, then
    combined into a single mesh.
    """
    try:
        from skimage.measure import marching_cubes
        import trimesh
    except ImportError:
        raise ImportError(
            "trimesh and scikit-image required. Install with:\n"
            "  pip install trimesh scikit-image"
        )

    if states_to_include is None:
        states_to_include = [1, 2, 3, 4]  # all non-void

    meshes = []
    for state_id in states_to_include:
        binary = (lattice == state_id).astype(np.float64)
        if binary.sum() == 0:
            continue

        # Pad to avoid edge artifacts from marching cubes
        padded = np.pad(binary, 1, constant_values=0)
        try:
            verts, faces, normals, _ = marching_cubes(padded, level=0.5)
        except (RuntimeError, ValueError):
            continue

        verts -= 1.0  # undo padding offset

        mesh = trimesh.Trimesh(
            vertices=verts, faces=faces, vertex_normals=normals
        )
        r, g, b = STATE_PRINT_COLORS[state_id]
        mesh.visual.face_colors = np.array([r, g, b, 255], dtype=np.uint8)
        meshes.append(mesh)

    if not meshes:
        raise ValueError("No non-void cells to export")

    combined = trimesh.util.concatenate(meshes)
    combined.export(output_path)

    print(f"STL exported: {output_path} ({os.path.getsize(output_path):,} bytes)")
    print(f"  Vertices: {len(combined.vertices):,}")
    print(f"  Faces:    {len(combined.faces):,}")
    return output_path


def lattice_to_glb(
    lattice: np.ndarray,
    output_path: str = "organism.glb",
    states_to_include: Optional[list] = None,
) -> str:
    """Export organism as GLB (binary glTF) for web/VR viewing.

    Each state becomes a separate mesh with distinct material colors.
    """
    try:
        from skimage.measure import marching_cubes
        import trimesh
    except ImportError:
        raise ImportError(
            "trimesh and scikit-image required. Install with:\n"
            "  pip install trimesh scikit-image"
        )

    if states_to_include is None:
        states_to_include = [1, 2, 3, 4]

    scene = trimesh.Scene()

    for state_id in states_to_include:
        binary = (lattice == state_id).astype(np.float64)
        if binary.sum() == 0:
            continue

        padded = np.pad(binary, 1, constant_values=0)
        try:
            verts, faces, normals, _ = marching_cubes(padded, level=0.5)
        except (RuntimeError, ValueError):
            continue

        verts -= 1.0
        mesh = trimesh.Trimesh(
            vertices=verts, faces=faces, vertex_normals=normals
        )
        r, g, b = STATE_PRINT_COLORS[state_id]
        mesh.visual.face_colors = np.array([r, g, b, 255], dtype=np.uint8)
        scene.add_geometry(mesh, node_name=STATE_NAMES[state_id])

    scene.export(output_path)
    print(f"GLB exported: {output_path} ({os.path.getsize(output_path):,} bytes)")
    return output_path


def lattice_to_voxel_slices(
    lattice: np.ndarray,
    output_dir: str = "voxel_slices",
    scale: int = 1,
) -> str:
    """Export lattice as PNG slices for GrabCAD Voxel Print.

    Each Z-layer becomes a PNG image with state-mapped colors.
    Compatible with Stratasys J55 PolyJet voxel printing pipeline.
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("Pillow required. Install with: pip install Pillow")

    os.makedirs(output_dir, exist_ok=True)

    D = lattice.shape[2]  # Z-depth
    for z in range(D):
        sl = lattice[:, :, z]
        h, w = sl.shape

        img = Image.new("RGB", (w * scale, h * scale))
        pixels = img.load()
        for x in range(w):
            for y in range(h):
                color = STATE_PRINT_COLORS.get(int(sl[y, x]), (200, 200, 200))
                for sx in range(scale):
                    for sy in range(scale):
                        pixels[x * scale + sx, y * scale + sy] = color

        img.save(os.path.join(output_dir, f"layer_{z:04d}.png"))

    print(f"Voxel slices exported: {output_dir}/ ({D} layers, scale={scale}x)")
    return output_dir


# ---------------------------------------------------------------------------
# Seed 3: WASM Build Configuration
# ---------------------------------------------------------------------------

WASM_CARGO_TOML_PATCH = """
# Add to Cargo.toml [features] section for WASM target:
# [features]
# default = []  # Remove "python" from default
# python = ["pyo3"]
# wasm = []     # New: enables WASM-compatible build
#
# [target.'cfg(target_arch = "wasm32")'.dependencies]
# wasm-bindgen = "0.2"
# js-sys = "0.3"
# web-sys = { version = "0.3", features = ["console"] }
#
# Note: rayon must be disabled for WASM (no threads in browsers).
# Use cfg(not(target_arch = "wasm32")) guards around rayon imports.
"""

WASM_BUILD_SCRIPT = """#!/bin/bash
# Build UtilityFog CA kernel as WebAssembly module
# Requires: rustup target add wasm32-unknown-unknown
#           cargo install wasm-pack

set -euo pipefail

cd crates/uft_ca

echo "Building WASM module..."
wasm-pack build \\
  --target web \\
  --out-dir ../../wasm_pkg \\
  --no-default-features \\
  --features wasm \\
  -- --no-default-features

echo ""
echo "WASM package built in wasm_pkg/"
echo "Files:"
ls -la ../../wasm_pkg/*.{js,wasm,ts} 2>/dev/null || true
echo ""
echo "To use in a web page:"
echo "  import init, { CaLattice } from './wasm_pkg/uft_ca.js';"
echo "  await init();"
echo "  const lattice = CaLattice.new(64, 64, 64);"
echo "  lattice.step();"
"""


def print_wasm_guide():
    """Print the WASM build guide."""
    print("=" * 70)
    print("  SEED 3: WebAssembly Browser Engine -- Build Guide")
    print("=" * 70)
    print()
    print("The Rust CA kernel (crates/uft_ca/src/lib.rs) can compile to WASM")
    print("for browser-native organism execution. Here's the roadmap:")
    print()
    print("STEP 1: Install WASM toolchain")
    print("  rustup target add wasm32-unknown-unknown")
    print("  cargo install wasm-pack")
    print()
    print("STEP 2: Modify Cargo.toml")
    print(WASM_CARGO_TOML_PATCH)
    print()
    print("STEP 3: Guard rayon behind cfg")
    print("  #[cfg(not(target_arch = \"wasm32\"))]")
    print("  use rayon::prelude::*;")
    print()
    print("STEP 4: Add wasm-bindgen exports")
    print("  #[cfg(feature = \"wasm\")]")
    print("  #[wasm_bindgen]")
    print("  pub fn step_lattice(data: &[u8], rules: &str) -> Vec<u8> { ... }")
    print()
    print("STEP 5: Build")
    print("  wasm-pack build --target web --no-default-features --features wasm")
    print()
    print("STEP 6: Load genome in browser")
    print("  const genome = await fetch('organism.genome.json').then(r => r.json());")
    print("  const lattice = CaLattice.from_genome(JSON.stringify(genome));")
    print("  lattice.step();")
    print("  const snapshot = lattice.get_lattice();  // Uint8Array(262144)")
    print()
    print("CURRENT STATUS:")
    print("  - Rust kernel: Phase 3 stepping implemented (lib.rs)")
    print("  - PyO3 feature: gated behind [features] python = [\"pyo3\"]")
    print("  - Rayon: needs cfg guard for WASM (no threads in browser)")
    print("  - Phases 4-6c: currently Python-only, need Rust port for full WASM")
    print("  - Estimated effort: 3-5 days for Phase 3 WASM, 2-3 weeks for full")
    print()
    print("The Three.js frontend (visualization/frontend/) can render the")
    print("WASM output directly via @react-three/fiber, creating a live")
    print("browser-native organism viewer.")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Actuation Translation Layer (ATL) Architecture
# ---------------------------------------------------------------------------

ATL_ARCHITECTURE = """
╔══════════════════════════════════════════════════════════════════════╗
║          ACTUATION TRANSLATION LAYER (ATL) ARCHITECTURE            ║
║                                                                    ║
║   The "Connective Tissue" between Genome (Soul) and Hardware       ║
║   Inspired by DeepMirror/OpenClaw: LLM intent → verified skills    ║
╚══════════════════════════════════════════════════════════════════════╝

┌──────────────────────────────────────────────────────────────────┐
│                    GENOME (7.3 KB JSON)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │Transition│ │Stochastic│ │Contagion │ │Survival Mechanics│   │
│  │  Table   │ │  Config  │ │  Config  │ │  (11 subsections)│   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘   │
│       │             │            │                 │             │
│       └─────────────┴────────────┴─────────────────┘             │
│                         │ THE SOUL                               │
└─────────────────────────┼────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                ACTUATION TRANSLATION LAYER                       │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              GENOME COMPILER                             │    │
│  │  Compiles transition table + parameters into:            │    │
│  │  • FPGA bitstreams (Verilog LUTs)                       │    │
│  │  • Robot skill libraries (OpenClaw SKILL.md)            │    │
│  │  • Actuator command sequences                           │    │
│  │  • Neural network weight matrices (neuromorphic)        │    │
│  └─────────────┬───────────────────────────────┬────────────┘    │
│                │                               │                │
│  ┌─────────────▼─────────────┐ ┌───────────────▼─────────────┐  │
│  │   SENSOR INGESTION API    │ │  ACTUATOR COMMAND API        │  │
│  │                           │ │                              │  │
│  │  Physical → CA mapping:   │ │  CA → Physical mapping:     │  │
│  │                           │ │                              │  │
│  │  LiDAR point cloud        │ │  State transition →          │  │
│  │    → voxelized density    │ │    actuator command          │  │
│  │    → neighbor counts      │ │                              │  │
│  │    → SENSOR activation    │ │  STRUCTURAL growth →         │  │
│  │                           │ │    module attach/extend      │  │
│  │  Proximity/ToF sensors    │ │  STRUCTURAL decay →          │  │
│  │    → Mindsight gradient   │ │    module detach/retract     │  │
│  │    → signal_field (Ch 5)  │ │                              │  │
│  │                           │ │  ENERGY contagion →          │  │
│  │  Camera depth map         │ │    power routing change      │  │
│  │    → occupancy grid       │ │    signal relay activation   │  │
│  │    → state classification │ │                              │  │
│  │                           │ │  COMPUTE decision →          │  │
│  │  Temperature/humidity     │ │    reconfiguration command   │  │
│  │    → environmental stress │ │    behavioral mode switch    │  │
│  │    → distress signals     │ │                              │  │
│  │                           │ │  Compassion response →       │  │
│  │  Accelerometer/IMU        │ │    resource donation         │  │
│  │    → vibration → warmth   │ │    protective formation      │  │
│  │    → metta channel (Ch 6) │ │                              │  │
│  └───────────────────────────┘ └──────────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │               DIGITAL TWIN BRIDGE                           │ │
│  │                                                             │ │
│  │  Physical state ←→ CA lattice synchronization               │ │
│  │  • MuJoCo simulation as validation layer                    │ │
│  │  • Real-time state diffing (physical vs simulated)          │ │
│  │  • Safety constraints: veto dangerous reconfigurations      │ │
│  │  • Heartbeat: if physical diverges > threshold, halt        │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│              PHYSICAL SUBSTRATE (The Body)                        │
│                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │ElectroVoxel│ │  Pogobot   │ │  FPGA +    │ │ Xenobot /    │ │
│  │  Cubes     │ │  Swarm     │ │  Actuators │ │ Bioprinted   │ │
│  │  (60mm)    │ │  (250 EUR) │ │  ($1K-12K) │ │ Tissue       │ │
│  │            │ │            │ │            │ │              │ │
│  │ Pivot via  │ │ IR comms   │ │ GPIO pins  │ │ Gene reg.    │ │
│  │ electro-   │ │ vibration  │ │ to motors/ │ │ networks     │ │
│  │ magnets    │ │ locomotion │ │ servos/    │ │ calcium      │ │
│  │            │ │            │ │ pneumatics │ │ signaling    │ │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘ │
└──────────────────────────────────────────────────────────────────┘

SENSOR CELL INGESTION DETAIL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  The Phase 6c Mindsight mechanism computes:
    S_0 = S_max * tanh(grad_rho / sigma)

  In the physical world, grad_rho IS the real density gradient:
    • LiDAR returns → 3D point cloud → voxelize at module resolution
    • Each SENSOR module counts neighbors in its R=12 sensing radius
    • The tanh activation naturally handles noisy real-world data
    • Asymmetric sigma (opp=0.15, dis=0.10) provides built-in
      sensitivity tuning for the physical environment

  The signal_field (Ch 5) propagates through ENERGY modules via
  the Mycelial Network mechanic (K=3 diffusion iterations):
    • Physical: each ENERGY module relays signals to neighbors
    • IR/RF communication replaces numpy array diffusion
    • Asymmetric decay (lambda_distress=12, lambda_opp=8) means
      distress signals propagate further — a safety feature

STRUCTURAL/ENERGY ACTUATION DETAIL:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  State Transition → Actuator Command mapping:

  ┌─────────────────────┬──────────────────────────────────────┐
  │ CA Transition       │ Physical Action                      │
  ├─────────────────────┼──────────────────────────────────────┤
  │ VOID → STRUCTURAL   │ Module moves into position (attach)  │
  │ STRUCTURAL → VOID   │ Module detaches (controlled retreat) │
  │ STRUCTURAL → COMPUTE│ Module enters processing mode        │
  │ STRUCTURAL → ENERGY │ Module becomes signal relay           │
  │ STRUCTURAL → SENSOR │ Module activates sensing array       │
  │ COMPUTE → VOID      │ Module powers down (energy saving)   │
  │ ENERGY → ENERGY     │ Signal relay continues               │
  │ Contagion threshold │ Neighboring modules coordinate       │
  │   (4+ ENERGY nbrs) │   state change simultaneously        │
  │ Metta warmth > 0    │ Module reduces structural rigidity   │
  │                     │   (softer grip = protective posture) │
  │ Compassion fires    │ Module donates power/bandwidth to    │
  │                     │   distressed neighbor modules        │
  └─────────────────────┴──────────────────────────────────────┘

  The Equanimity Shield (Phase 4) maps to physical robustness:
    P_resist(age, M) = P_max * (1-exp(-(a-a_m)/tau)) * tanh(gamma*M)
    • Older modules resist reconfiguration commands more strongly
    • High-memory modules maintain position under perturbation
    • This IS structural integrity in the physical world

KEY INSIGHT:
━━━━━━━━━━━
  The genome's survival mechanics (Phases 3-6c) are not just
  simulation rules — they are a CONTROL POLICY for physical systems.
  The Mamba-Viking memory dynamics, Void Sanctuary, Equanimity Shield,
  and Compassion response all translate directly to robustness,
  self-repair, and cooperative behavior in modular robotic systems.

  The organism doesn't need a separate AI controller.
  The genome IS the controller. The ATL just translates the language.
"""


def print_atl_architecture():
    """Print the Actuation Translation Layer architecture."""
    print(ATL_ARCHITECTURE)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="dandelion",
        description="Operation Dandelion -- Genome Dissemination Pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- qr: QR code generator ---
    p_qr = sub.add_parser("qr", help="Generate QR code from genome JSON")
    p_qr.add_argument("genome", help="Path to .genome.json file")
    p_qr.add_argument("--output", default="organism_genome_qr.png")
    p_qr.add_argument("--box-size", type=int, default=6)
    p_qr.add_argument("--error-correction", choices=["L", "M", "Q", "H"], default="L")

    # --- info: QR feasibility check ---
    p_info = sub.add_parser("info", help="Show genome compression stats")
    p_info.add_argument("genome", help="Path to .genome.json file")

    # --- stl: STL mesh export ---
    p_stl = sub.add_parser("stl", help="Export organism as STL mesh")
    p_stl.add_argument("snapshot", help="Path to .npz snapshot file")
    p_stl.add_argument("--output", default="organism.stl")

    # --- glb: GLB/glTF export ---
    p_glb = sub.add_parser("glb", help="Export organism as GLB (web/VR)")
    p_glb.add_argument("snapshot", help="Path to .npz snapshot file")
    p_glb.add_argument("--output", default="organism.glb")

    # --- slices: Voxel print slices ---
    p_slices = sub.add_parser("slices", help="Export PNG slices for voxel printing")
    p_slices.add_argument("snapshot", help="Path to .npz snapshot file")
    p_slices.add_argument("--output-dir", default="voxel_slices")
    p_slices.add_argument("--scale", type=int, default=1,
                          help="Scale factor for each voxel (default: 1px)")

    # --- wasm: WASM build guide ---
    p_wasm = sub.add_parser("wasm", help="Print WASM build guide")

    # --- atl: ATL architecture ---
    p_atl = sub.add_parser("atl", help="Print Actuation Translation Layer architecture")

    args = parser.parse_args(argv)

    if args.command == "qr":
        meta = generate_qr(
            args.genome,
            output_path=args.output,
            box_size=args.box_size,
            error_correction=args.error_correction,
        )
        print(f"QR Code generated: {meta['output_path']}")
        print(f"  Original JSON:    {meta['original_json_bytes']:,} bytes")
        print(f"  Minified:         {meta['minified_bytes']:,} bytes")
        print(f"  Compressed:       {meta['compressed_bytes']:,} bytes")
        print(f"  Base85 encoded:   {meta['b85_encoded_chars']:,} chars")
        print(f"  QR payload:       {meta['qr_payload_chars']:,} chars (with UFG1: header)")
        print(f"  QR version:       {meta['qr_version']}")
        print(f"  Error correction: {meta['qr_error_correction']}")
        print(f"  Fits single QR:   {'YES' if meta['fits_single_qr'] else 'NO'}")
        cr = (1 - meta['compressed_bytes'] / meta['original_json_bytes']) * 100
        print(f"  Compression:      {cr:.1f}% reduction")

    elif args.command == "info":
        compressed = genome_to_compressed_bytes(args.genome)
        b85 = compressed_to_b85(compressed)
        with open(args.genome, "r") as f:
            orig = f.read()
        genome = json.loads(orig)
        genome.pop("epigenetic_snapshot", None)
        minified = json.dumps(genome, separators=(",", ":"), sort_keys=True)

        print(f"Genome: {args.genome}")
        print(f"  Original:   {len(orig.encode()):,} bytes")
        print(f"  Minified:   {len(minified.encode()):,} bytes")
        print(f"  Compressed: {len(compressed):,} bytes")
        print(f"  Base85:     {len(b85):,} chars")
        print(f"  QR payload: {len(b85) + 5:,} chars (with UFG1: header)")
        print()
        print(f"  QR V40 capacity (EC-L): 2,953 bytes binary / 4,296 alphanumeric")
        fits = len(b85) + 5 <= 4296
        print(f"  Fits single QR code:    {'YES' if fits else 'NO'}")
        if not fits:
            n_codes = (len(b85) + 5 + 4295) // 4296
            print(f"  QR codes needed:        {n_codes}")

    elif args.command == "stl":
        snap = np.load(args.snapshot, allow_pickle=True)
        lattice_to_stl(snap["lattice"], args.output)

    elif args.command == "glb":
        snap = np.load(args.snapshot, allow_pickle=True)
        lattice_to_glb(snap["lattice"], args.output)

    elif args.command == "slices":
        snap = np.load(args.snapshot, allow_pickle=True)
        lattice_to_voxel_slices(snap["lattice"], args.output_dir, scale=args.scale)

    elif args.command == "wasm":
        print_wasm_guide()

    elif args.command == "atl":
        print_atl_architecture()


if __name__ == "__main__":
    main()
