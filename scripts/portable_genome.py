#!/usr/bin/env python3
"""Phase 7: Portable Genome Format -- Substrate Independence.

Exports and imports the complete specification of a UtilityFog CA organism
as a single JSON file. This genome captures everything needed to reconstruct
the organism on any compatible substrate.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

from scripts.continuous_evolution_ca import (
    COMPUTE, ENERGY, MEMORY_CHANNELS, NUM_STATES, SENSOR,
    STATE_NAME_TO_ID, STRUCTURAL, VOID,
    CAConfig, ContagionConfig, CosmicGardenConfig, DecayConfig,
    DensityPhaseDetectorConfig, ExperimentalConfig, StochasticConfig,
    VoxelMemoryParams,
    _load_contagion_config, _load_cosmic_config, _load_decay_config,
    _load_experimental_config, _load_stochastic_config, _load_transition_table,
    init_memory_grid,
)

STATE_ID_TO_NAME = {v: k for k, v in STATE_NAME_TO_ID.items()}
_STATE_NAMES = ["VOID", "STRUCTURAL", "COMPUTE", "ENERGY", "SENSOR"]

MEMORY_CHANNEL_DEFS = [
    {"index": 0, "name": "compute_age", "description": "Age of COMPUTE cells", "default": 0.0},
    {"index": 1, "name": "structural_age", "description": "Age of STRUCTURAL cells", "default": 0.0},
    {"index": 2, "name": "memory_strength", "description": "Mamba-Viking memory M(t)", "default": 1.0},
    {"index": 3, "name": "energy_reserve", "description": "Cellular energy reserve", "default": 1.0},
    {"index": 4, "name": "last_active_gen", "description": "Last active generation", "default": 0.0},
    {"index": 5, "name": "signal_field", "description": "Phase 6c Mindsight signal", "default": 0.0},
    {"index": 6, "name": "warmth", "description": "Phase 6a Metta warmth", "default": 0.0},
    {"index": 7, "name": "compassion_cooldown", "description": "Phase 6c Compassion cooldown", "default": 0.0},
]


def export_genome(filepath, rule_spec, generation=0, ca_step=0, best_fitness=0.0,
                  lattice=None, memory_grid=None, include_epigenetic=False, pretty=True):
    """Export the organism complete genome to a portable JSON file."""
    filepath = Path(filepath)

    stoch = _load_stochastic_config(rule_spec)
    contagion = _load_contagion_config(rule_spec)
    decay = _load_decay_config(rule_spec)
    cosmic = _load_cosmic_config(rule_spec)
    experimental = _load_experimental_config(rule_spec)
    table = _load_transition_table(rule_spec)
    mem = VoxelMemoryParams()

    params = rule_spec.get("params", {})
    meta_section = params.get("meta", {})
    rule_section = rule_spec.get("rule", {})

    tt_export = {}
    for src_id, mappings in table.items():
        src_name = STATE_ID_TO_NAME[src_id]
        tt_export[src_name] = {}
        for neighbor_count, target_id in sorted(mappings.items()):
            tt_export[src_name][str(neighbor_count)] = STATE_ID_TO_NAME[target_id]

    genome = {
        "format": {"schema_version": "1.0.0", "format_id": "utilityfog-portable-genome"},
        "metadata": {
            "name": rule_section.get("name", meta_section.get("name", "unknown")),
            "version": meta_section.get("version", "0.0.0"),
            "author": meta_section.get("author", "UtilityFog Team"),
            "description": meta_section.get("description", ""),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_generation": generation,
            "source_ca_step": ca_step,
            "best_fitness": round(best_fitness, 6),
            "target_lambda": float(meta_section.get("target_lambda", 1.7)),
        },
        "topology": {
            "states": list(rule_section.get("states", _STATE_NAMES)),
            "neighborhood": rule_section.get("neighborhood", "moore-3d"),
            "transition_mode": rule_section.get("transition", "outer-totalistic"),
        },
        "transition_table": tt_export,
        "stochastic": {
            "enabled": stoch.enabled,
            "baseline_transition_prob": stoch.baseline_transition_prob,
            "structural_to_energy_prob": stoch.structural_to_energy_prob,
            "structural_to_sensor_prob": stoch.structural_to_sensor_prob,
            "compute_to_energy_prob": stoch.compute_to_energy_prob,
            "compute_to_sensor_prob": stoch.compute_to_sensor_prob,
            "structural_to_void_decay_prob": stoch.structural_to_void_decay_prob,
            "energy_to_void_decay_prob": stoch.energy_to_void_decay_prob,
            "sensor_to_void_decay_prob": stoch.sensor_to_void_decay_prob,
        },
        "contagion": {
            "enabled": contagion.enabled,
            "energy_neighbor_threshold": contagion.energy_neighbor_threshold,
            "sensor_neighbor_threshold": contagion.sensor_neighbor_threshold,
            "structural_energy_conversion_prob": contagion.structural_energy_conversion_prob,
            "structural_sensor_conversion_prob": contagion.structural_sensor_conversion_prob,
            "compute_energy_conversion_prob": contagion.compute_energy_conversion_prob,
            "compute_sensor_conversion_prob": contagion.compute_sensor_conversion_prob,
        },
        "decay": {
            "enabled": decay.enabled,
            "inactivity_neighbor_threshold": decay.inactivity_neighbor_threshold,
            "structural_inactive_steps_to_decay": decay.structural_inactive_steps_to_decay,
        },
        "cosmic_garden": {
            "cluster_coherence_threshold": cosmic.cluster_coherence_threshold,
            "shield_strength": cosmic.shield_strength,
            "cluster_shield_bonus": cosmic.cluster_shield_bonus,
            "halbach_recuperation_rate": cosmic.halbach_recuperation_rate,
            "temporal_dilation": cosmic.temporal_dilation,
            "bamboo_initial_growth": cosmic.bamboo_initial_growth,
            "bamboo_max_length": cosmic.bamboo_max_length,
            "bamboo_rebirth_age": cosmic.bamboo_rebirth_age,
            "biofilm_leech_rate": cosmic.biofilm_leech_rate,
            "super_pod_threshold": cosmic.super_pod_threshold,
            "analogue_mutation": cosmic.analogue_mutation,
            "otolith_vector": cosmic.otolith_vector,
            "damping_radius": cosmic.damping_radius,
        },
        "survival_mechanics": {
            "age_thresholds": {
                "age_young_threshold": mem.age_young_threshold,
                "age_mature_threshold": mem.age_mature_threshold,
            },
            "reverse_contagion": {
                "resistance_max": mem.resistance_max,
                "reverse_contagion_threshold": mem.reverse_contagion_threshold,
                "reverse_contagion_base_prob": mem.reverse_contagion_base_prob,
                "reverse_contagion_boost": mem.reverse_contagion_boost,
                "energy_to_compute_prob": mem.energy_to_compute_prob,
            },
            "forward_contagion_mitigation": {
                "forward_contagion_threshold": mem.forward_contagion_threshold,
                "forward_contagion_penalty": mem.forward_contagion_penalty,
                "forward_contagion_floor": mem.forward_contagion_floor,
            },
            "rag_memory": {
                "rag_query_radius": mem.rag_query_radius,
                "rag_memory_decay": mem.rag_memory_decay,
                "rag_reinforcement_boost": mem.rag_reinforcement_boost,
                "rag_entropy_weight": mem.rag_entropy_weight,
            },
            "phase3_mamba_viking": {
                "mamba_delta_threshold": mem.mamba_delta_threshold,
                "mamba_tau_base": mem.mamba_tau_base,
                "mamba_tau_scale": mem.mamba_tau_scale,
                "mamba_boost_base": mem.mamba_boost_base,
                "mamba_boost_gain": mem.mamba_boost_gain,
                "mamba_age_stability_gain": mem.mamba_age_stability_gain,
                "mamba_high_delta_floor": mem.mamba_high_delta_floor,
            },
            "phase3_void_sanctuary": {
                "void_sanctuary_multiplier": mem.void_sanctuary_multiplier,
            },
            "phase3_epsilon_buffer": {
                "epsilon_p_max": mem.epsilon_p_max,
                "epsilon_buffer": mem.epsilon_buffer,
                "epsilon_n_c": mem.epsilon_n_c,
                "epsilon_tau": mem.epsilon_tau,
            },
            "phase4_equanimity": {
                "equanimity_age_min": mem.equanimity_age_min,
                "equanimity_p_max": mem.equanimity_p_max,
                "equanimity_tau": mem.equanimity_tau,
                "equanimity_gamma": mem.equanimity_gamma,
            },
            "phase6a_metta": {
                "metta_beta": mem.metta_beta,
                "metta_warmth_rate": mem.metta_warmth_rate,
                "metta_warmth_decay": mem.metta_warmth_decay,
            },
            "phase6b_mudita": {
                "joy_beta": mem.joy_beta,
                "joy_age_scale": mem.joy_age_scale,
            },
            "phase6c_nervous_system": {
                "mindsight_s_max": mem.mindsight_s_max,
                "mindsight_sigma_opp": mem.mindsight_sigma_opp,
                "mindsight_sigma_dis": mem.mindsight_sigma_dis,
                "mindsight_threshold": mem.mindsight_threshold,
                "mindsight_radius": mem.mindsight_radius,
                "mycelial_k_iter": mem.mycelial_k_iter,
                "mycelial_lambda_distress": mem.mycelial_lambda_distress,
                "mycelial_lambda_opportunity": mem.mycelial_lambda_opportunity,
                "compassion_beta": mem.compassion_beta,
                "compassion_gamma": mem.compassion_gamma,
                "compassion_distance_scale": mem.compassion_distance_scale,
                "compassion_age_scale_min": mem.compassion_age_scale_min,
                "compassion_age_scale_factor": mem.compassion_age_scale_factor,
                "signal_interval": mem.signal_interval,
            },
        },
        "fitness": {
            "target_median_age": 10.0,
            "gene_weights": {"dominance": 0.3, "virality": 0.2, "stability": 0.3, "compat": 0.1, "thresh": 0.1},
            "formula_weights": {"differentiation_weight": 0.4, "longevity_weight": 0.6},
            "ga_params": {"population_size": 120, "mutation_rate": 0.10, "crossover_rate": 0.80, "elitism_rate": 0.10, "tournament_k": 3},
        },
        "memory_layout": {"num_channels": MEMORY_CHANNELS, "channels": MEMORY_CHANNEL_DEFS},
        "experimental": asdict(experimental),
    }

    if include_epigenetic and lattice is not None:
        epi = {
            "included": True,
            "lattice_shape": list(lattice.shape),
            "lattice_b64": base64.b64encode(lattice.astype(np.uint8).tobytes()).decode("ascii"),
            "snapshot_generation": generation,
            "snapshot_ca_step": ca_step,
        }
        if memory_grid is not None:
            epi["memory_grid_b64"] = base64.b64encode(memory_grid.astype(np.float32).tobytes()).decode("ascii")
        genome["epigenetic_snapshot"] = epi
    else:
        genome["epigenetic_snapshot"] = {"included": False}

    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(genome, f, indent=2 if pretty else None, ensure_ascii=False)

    return filepath


def import_genome(filepath):
    """Import a portable genome and reconstruct the rule_spec and CAConfig."""
    filepath = Path(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        genome = json.load(f)

    fmt = genome.get("format", {})
    if fmt.get("format_id") != "utilityfog-portable-genome":
        raise ValueError(f"Unknown genome format: {fmt.get('format_id')}")

    tt_raw = genome.get("transition_table", {})
    transitions = {}
    for src_name, mappings in tt_raw.items():
        transitions[src_name] = {}
        for count_str, target_name in mappings.items():
            transitions[src_name][count_str] = target_name

    stoch_section = genome.get("stochastic", {})
    contagion_section = genome.get("contagion", {})
    decay_section = genome.get("decay", {})
    cosmic_section = genome.get("cosmic_garden", {})
    exp_section = genome.get("experimental", {})
    meta = genome.get("metadata", {})
    topo = genome.get("topology", {})

    rule_spec = {
        "rule": {
            "name": meta.get("name", "imported-genome"),
            "states": topo.get("states", _STATE_NAMES),
            "neighborhood": topo.get("neighborhood", "moore-3d"),
            "transition": topo.get("transition_mode", "outer-totalistic"),
        },
        "params": {
            "transitions": transitions,
            "stochastic": stoch_section,
            "contagion": contagion_section,
            "decay": decay_section,
            "cosmic_garden": cosmic_section,
            "experimental": {
                "selective_memory_decay": {
                    "enabled": exp_section.get("selective_memory_decay_enabled", False),
                    "memory_strength_threshold": exp_section.get("selective_memory_decay_threshold", 0.75),
                    "compute_neighbor_threshold": exp_section.get("selective_compute_neighbor_threshold", 6),
                    "low_decay_rate": exp_section.get("selective_low_decay_rate", 0.015),
                    "high_decay_rate": exp_section.get("selective_high_decay_rate", 0.045),
                },
            },
            "meta": {
                "description": meta.get("description", ""),
                "author": meta.get("author", ""),
                "version": meta.get("version", "0.0.0"),
                "target_lambda": meta.get("target_lambda", 1.7),
            },
        },
    }

    stoch_cfg = StochasticConfig(
        enabled=stoch_section.get("enabled", True),
        baseline_transition_prob=stoch_section.get("baseline_transition_prob", 0.08),
        structural_to_energy_prob=stoch_section.get("structural_to_energy_prob", 0.08),
        structural_to_sensor_prob=stoch_section.get("structural_to_sensor_prob", 0.08),
        compute_to_energy_prob=stoch_section.get("compute_to_energy_prob", 0.10),
        compute_to_sensor_prob=stoch_section.get("compute_to_sensor_prob", 0.10),
        structural_to_void_decay_prob=stoch_section.get("structural_to_void_decay_prob", 0.005),
        energy_to_void_decay_prob=stoch_section.get("energy_to_void_decay_prob", 0.005),
        sensor_to_void_decay_prob=stoch_section.get("sensor_to_void_decay_prob", 0.004),
    )
    contagion_cfg = ContagionConfig(
        enabled=contagion_section.get("enabled", True),
        energy_neighbor_threshold=contagion_section.get("energy_neighbor_threshold", 4),
        sensor_neighbor_threshold=contagion_section.get("sensor_neighbor_threshold", 4),
        structural_energy_conversion_prob=contagion_section.get("structural_energy_conversion_prob", 0.40),
        structural_sensor_conversion_prob=contagion_section.get("structural_sensor_conversion_prob", 0.30),
        compute_energy_conversion_prob=contagion_section.get("compute_energy_conversion_prob", 0.15),
        compute_sensor_conversion_prob=contagion_section.get("compute_sensor_conversion_prob", 0.25),
    )
    decay_cfg = DecayConfig(
        enabled=decay_section.get("enabled", True),
        inactivity_neighbor_threshold=decay_section.get("inactivity_neighbor_threshold", 1),
        structural_inactive_steps_to_decay=decay_section.get("structural_inactive_steps_to_decay", 6),
    )
    cosmic_cfg = CosmicGardenConfig(
        cluster_coherence_threshold=cosmic_section.get("cluster_coherence_threshold", 3),
        shield_strength=cosmic_section.get("shield_strength", 0.85),
        cluster_shield_bonus=cosmic_section.get("cluster_shield_bonus", 0.15),
        halbach_recuperation_rate=cosmic_section.get("halbach_recuperation_rate", 0.40),
        temporal_dilation=cosmic_section.get("temporal_dilation", 0.15),
        bamboo_initial_growth=cosmic_section.get("bamboo_initial_growth", 100),
        bamboo_max_length=cosmic_section.get("bamboo_max_length", 500),
        bamboo_rebirth_age=cosmic_section.get("bamboo_rebirth_age", 488),
        biofilm_leech_rate=cosmic_section.get("biofilm_leech_rate", 0.10),
        super_pod_threshold=cosmic_section.get("super_pod_threshold", 8),
        analogue_mutation=cosmic_section.get("analogue_mutation", 0.03),
        otolith_vector=cosmic_section.get("otolith_vector", 0.05),
        damping_radius=cosmic_section.get("damping_radius", 2),
    )
    exp_cfg = ExperimentalConfig(
        mamba_d_model=exp_section.get("mamba_d_model", 64),
        mamba_d_state=exp_section.get("mamba_d_state", 16),
        mamba_enabled=exp_section.get("mamba_enabled", False),
        void_sanctuary_enabled=exp_section.get("void_sanctuary_enabled", False),
        void_sanctuary_radius=exp_section.get("void_sanctuary_radius", 2),
        epsilon=exp_section.get("epsilon", 1e-8),
        selective_memory_decay_enabled=exp_section.get("selective_memory_decay_enabled", False),
        selective_memory_decay_threshold=exp_section.get("selective_memory_decay_threshold", 0.75),
        selective_compute_neighbor_threshold=exp_section.get("selective_compute_neighbor_threshold", 6),
        selective_low_decay_rate=exp_section.get("selective_low_decay_rate", 0.015),
        selective_high_decay_rate=exp_section.get("selective_high_decay_rate", 0.045),
    )

    int_table = {}
    for src_name, mappings in transitions.items():
        src_id = STATE_NAME_TO_ID[src_name.upper()]
        int_table[src_id] = {}
        for count_str, target_name in mappings.items():
            int_table[src_id][int(count_str)] = STATE_NAME_TO_ID[target_name.upper()]

    ca_config = CAConfig(
        stochastic=stoch_cfg, contagion=contagion_cfg, decay=decay_cfg,
        detector=DensityPhaseDetectorConfig(), cosmic=cosmic_cfg,
        experimental=exp_cfg, voxel_memory=VoxelMemoryParams(),
        transition_table=int_table,
    )

    metadata = dict(meta)
    metadata["topology"] = topo
    metadata["fitness"] = genome.get("fitness", {})
    metadata["memory_layout"] = genome.get("memory_layout", {})
    return rule_spec, ca_config, metadata


def extract_epigenetic_snapshot(filepath):
    """Extract lattice and memory_grid from a genome epigenetic snapshot."""
    filepath = Path(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        genome = json.load(f)
    epi = genome.get("epigenetic_snapshot", {})
    if not epi.get("included", False):
        return None
    shape = tuple(epi["lattice_shape"])
    lattice_bytes = base64.b64decode(epi["lattice_b64"])
    lattice = np.frombuffer(lattice_bytes, dtype=np.uint8).reshape(shape)
    memory_grid = None
    if "memory_grid_b64" in epi:
        mg_bytes = base64.b64decode(epi["memory_grid_b64"])
        num_channels = genome.get("memory_layout", {}).get("num_channels", MEMORY_CHANNELS)
        memory_grid = np.frombuffer(mg_bytes, dtype=np.float32).reshape((num_channels,) + shape)
    snapshot_meta = {"generation": epi.get("snapshot_generation", 0), "ca_step": epi.get("snapshot_ca_step", 0)}
    return lattice.copy(), memory_grid.copy() if memory_grid is not None else None, snapshot_meta


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="UtilityFog Portable Genome")
    sub = parser.add_subparsers(dest="command")
    exp_p = sub.add_parser("export")
    exp_p.add_argument("--rule-file", required=True)
    exp_p.add_argument("--snapshot", default=None)
    exp_p.add_argument("--output", required=True)
    exp_p.add_argument("--include-epigenetic", action="store_true")
    info_p = sub.add_parser("info")
    info_p.add_argument("genome")
    args = parser.parse_args()
    if args.command == "export":
        try:
            import tomli
        except ImportError:
            import tomllib as tomli
        with open(args.rule_file, "rb") as f:
            rule_spec = tomli.load(f)
        lattice = memory_grid = None
        gen = ca_step_count = 0
        best_fit = 0.0
        if args.snapshot:
            snap = np.load(args.snapshot, allow_pickle=True)
            lattice, memory_grid = snap["lattice"], snap["memory_grid"]
            gen, ca_step_count = int(snap.get("generation", 0)), int(snap.get("ca_step", 0))
            best_fit = float(snap.get("best_fitness", 0.0))
        path = export_genome(args.output, rule_spec=rule_spec, generation=gen,
                             ca_step=ca_step_count, best_fitness=best_fit,
                             lattice=lattice, memory_grid=memory_grid,
                             include_epigenetic=args.include_epigenetic)
        print(f"Genome exported to: {path} ({path.stat().st_size:,} bytes)")
    elif args.command == "info":
        _, config, md = import_genome(args.genome)
        for k in ["name", "version", "author", "exported_at", "source_generation", "source_ca_step", "best_fitness"]:
            print(f"  {k}: {md.get(k, '?')}")
        print(f"  states: {len(config.transition_table)} with transitions")
    else:
        parser.print_help()
