#!/usr/bin/env python3
"""Phase 7: Portable Genome Format -- Substrate Independence.

Exports and imports the complete specification of a UtilityFog CA organism
as a single JSON file. This genome captures everything needed to reconstruct
the organism on any compatible substrate.
"""

from __future__ import annotations

import base64
import binascii
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


class PortableGenomeError(ValueError):
    """Structural refusal for malformed portable-genome shapes.

    Raised by :func:`import_genome` for the narrow set of structural shapes it
    validates: the genome root, ``format``, ``transition_table``, each
    source-state mapping, each source/target state name and neighbor-count key,
    and the container shape of the seven configuration sections
    ``stochastic``, ``contagion``, ``decay``, ``cosmic_garden``,
    ``experimental``, ``metadata`` and ``topology``.

    Also raised by :func:`extract_epigenetic_snapshot` for the shapes IT
    dereferences: the genome root, ``epigenetic_snapshot``, ``memory_layout``,
    ``lattice_shape``, the two base64 payload fields, ``num_channels`` and the
    two snapshot-metadata counters.

    Subclasses :class:`ValueError` so existing callers that catch ``ValueError``
    keep working; the public ``info`` CLI catches this type specifically.

    This does NOT make the module total. Still outside its structural boundary,
    and still surfacing as their original exceptions: individual field values
    *inside* an otherwise correctly shaped section, ``fitness``, schema
    completeness, cross-field consistency, and any semantic or numeric range
    validation. (Base64 validity, payload lengths and dimension positivity ARE
    now covered, by the epigenetic-snapshot wire-integrity checks.)
    """


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


def _require_json_object_section(genome: dict, section_name: str) -> dict:
    """Return ``genome[section_name]`` only when it is a JSON object.

    A missing section yields a fresh empty ``dict`` (the established default).
    An exact built-in ``dict`` is returned by identity. Every other JSON value
    -- array, string, number, Boolean, ``null`` -- and every ``dict`` subclass
    is refused with :class:`PortableGenomeError`.

    The refusal message is built from ``section_name`` alone: the supplied value
    is never rendered, and none of its methods (``get``, ``__repr__``,
    ``__str__``, ``__eq__``, ``__hash__``) is invoked while producing it.
    """
    section = genome.get(section_name, {})
    if type(section) is not dict:
        raise PortableGenomeError(f"{section_name} must be a JSON object")
    return section


# Wire-integrity constants for the epigenetic snapshot payload.
_LATTICE_RANK = 3
_UINT8_BYTES = 1
_FLOAT32_BYTES = 4


def _require_json_boolean(section: dict, field_name: str, default: bool = False) -> bool:
    """Return ``section[field_name]`` only when it is an actual JSON Boolean.

    Absent yields ``default``. Truthiness is deliberately not accepted: a
    string, number or array would otherwise silently enable or disable a code
    path the exporter never wrote.
    """
    if field_name not in section:
        return default
    value = section[field_name]
    if type(value) is not bool:
        raise PortableGenomeError(f"{field_name} must be a JSON boolean")
    return value


def _decode_base64_strict(section: dict, field_name: str) -> bytes:
    """Return the strictly decoded base64 payload of ``section[field_name]``.

    ``base64.b64decode`` defaults to ``validate=False``, which silently DISCARDS
    every character outside the alphabet and tolerates excess padding -- so
    ``"!!!!!!!!"`` decodes to ``b""`` and ``"AAAA="`` to three bytes. Both then
    fail much later, as a NumPy reshape mismatch, if at all. Strict decoding
    refuses them deterministically at the field that owns them.

    ``ValueError`` is the caught type, not merely ``binascii.Error``: for a
    non-ASCII string ``b64decode`` fails in ``_bytes_from_decode_data`` and
    raises a plain ``ValueError`` whose message quotes the argument, so
    catching only ``binascii.Error`` would let a value-bearing message escape.
    ``binascii.Error`` subclasses ``ValueError``, so one clause covers both,
    and the scope is a single call on already-validated string input.
    """
    text = _require_json_string(section, field_name)
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise PortableGenomeError(f"{field_name} is not valid base64") from exc


def _require_payload_length(payload: bytes, expected: int, field_name: str) -> None:
    """Refuse a payload whose decoded length disagrees with the declared shape.

    ``expected`` is computed with unbounded Python integers, so an enormous
    declared dimension is compared exactly instead of reaching NumPy and
    raising ``OverflowError`` -- and neither the expected nor the actual count
    appears in the message.
    """
    if len(payload) != expected:
        raise PortableGenomeError(
            f"{field_name} payload length does not match the declared shape"
        )


def _require_json_string(section: dict, field_name: str) -> str:
    """Return ``section[field_name]`` only when it is a JSON string.

    A missing key still raises ``KeyError`` exactly as before -- absence is not
    this helper's concern, shape is. Every non-string JSON value is refused,
    because ``base64.b64decode`` raises an ambient ``TypeError`` on a number,
    array, Boolean or ``null`` instead of a structural refusal.

    The message is built from ``field_name`` alone; the supplied value is never
    rendered and none of its methods is invoked.
    """
    value = section[field_name]
    if type(value) is not str:
        raise PortableGenomeError(f"{field_name} must be a JSON string")
    return value


def _require_lattice_shape(section: dict) -> Tuple[int, ...]:
    """Return ``section['lattice_shape']`` only when it is a JSON array of ints.

    ``tuple()`` and the later ``reshape`` both dereference this value, so a
    scalar, ``null`` or a non-integer entry raises an ambient ``TypeError``
    from inside ``tuple``/NumPy rather than a structural refusal.

    ``bool`` is excluded because the check is ``type(dim) is int``, matching the
    exact-type convention used elsewhere in this module. That is a deliberate
    narrowing, NOT the removal of a ``TypeError``: ``bool`` implements
    ``__index__``, so NumPy would have accepted ``True`` as the dimension ``1``.
    No exporter emits Booleans here.

    The lattice is a 3-D volume by construction, so the rank is fixed at three
    and every dimension must be positive. Previously any rank was accepted --
    a rank-2 or rank-4 array decoded silently into a non-3D lattice that broke
    much later inside a consumer -- and a zero, negative or enormous dimension
    was left for NumPy, surfacing as a ``ValueError`` echoing the supplied
    values or, past the platform index range, an untranslatable
    ``OverflowError``.

    A missing key still raises ``KeyError``. Dimension magnitudes beyond
    positivity are not checked here: the payload-length check that follows is
    what bounds them, and it does so with exact Python integer arithmetic.
    """
    raw = section["lattice_shape"]
    if type(raw) is not list:
        raise PortableGenomeError("lattice_shape must be a JSON array")
    if len(raw) != _LATTICE_RANK:
        raise PortableGenomeError("lattice_shape must have exactly three dimensions")
    for dim in raw:
        if type(dim) is not int:
            raise PortableGenomeError("lattice_shape entries must be integers")
        if dim <= 0:
            raise PortableGenomeError("lattice_shape entries must be positive")
    return tuple(raw)


def _require_counter(section: dict, field_name: str) -> int:
    """Return ``section[field_name]`` only when it is a JSON integer.

    Absent yields ``0``, the established default. These counters are carried
    into the returned snapshot metadata and are formatted with ``:,`` by
    consumers, so a string yields ``ValueError: Cannot specify ',' with 's'``
    and ``null``/array/object yield ``TypeError`` -- ambient defect signals
    raised far from this file. Validating the shape here keeps the refusal
    where the value is read.
    """
    if field_name not in section:
        return 0
    value = section[field_name]
    if type(value) is not int:
        raise PortableGenomeError(f"{field_name} must be an integer")
    return value


def _require_channel_count(layout: dict) -> int:
    """Return ``layout['num_channels']`` only when it is a JSON integer.

    Absent yields the established ``MEMORY_CHANNELS`` default. The value is
    dereferenced by ``reshape``, so a string, array or ``null`` would otherwise
    surface as an ambient ``TypeError``.

    ``bool`` is excluded because the check is ``type(value) is int``, matching
    the exact-type convention used elsewhere in this module. That is a
    deliberate narrowing, NOT the removal of a ``TypeError``: ``bool``
    implements ``__index__``, so NumPy would have accepted ``True`` as the
    dimension ``1``. No exporter emits a Boolean here.

    A count of zero or less is refused: it cannot describe a memory grid, and
    it previously reached NumPy as a degenerate or negative dimension. Which
    POSITIVE counts the Observatory can actually consume is a separate,
    downstream question -- see ``vis.observatory.loader``, which owns channel
    compatibility. This function only guarantees the wire value is a usable
    positive integer.
    """
    if "num_channels" not in layout:
        return MEMORY_CHANNELS
    value = layout["num_channels"]
    if type(value) is not int:
        raise PortableGenomeError("num_channels must be an integer")
    if value <= 0:
        raise PortableGenomeError("num_channels must be positive")
    return value


def import_genome(filepath):
    """Import a portable genome and reconstruct the rule_spec and CAConfig.

    Structural refusals raise :class:`PortableGenomeError` with an exact,
    value-free message: the genome root, ``format``, the transition table and
    its source mappings, and the container shape of the seven configuration
    sections ``stochastic``, ``contagion``, ``decay``, ``cosmic_garden``,
    ``experimental``, ``metadata`` and ``topology`` -- validated in that order,
    each at its retrieval site, before any of its keys is read. Field values
    *within* a correctly shaped section are not validated here.
    """
    filepath = Path(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        genome = json.load(f)

    if type(genome) is not dict:
        raise PortableGenomeError("genome must be a JSON object")

    fmt = genome.get("format", {})
    if type(fmt) is not dict:
        raise PortableGenomeError("format must be a JSON object")
    if fmt.get("format_id") != "utilityfog-portable-genome":
        raise PortableGenomeError("unknown genome format")

    tt_raw = genome.get("transition_table", {})
    if type(tt_raw) is not dict:
        raise PortableGenomeError("transition_table must be a JSON object")
    transitions = {}
    for src_name, mappings in tt_raw.items():
        if type(mappings) is not dict:
            raise PortableGenomeError("transition mappings must be a JSON object")
        transitions[src_name] = {}
        for count_str, target_name in mappings.items():
            transitions[src_name][count_str] = target_name

    stoch_section = _require_json_object_section(genome, "stochastic")
    contagion_section = _require_json_object_section(genome, "contagion")
    decay_section = _require_json_object_section(genome, "decay")
    cosmic_section = _require_json_object_section(genome, "cosmic_garden")
    exp_section = _require_json_object_section(genome, "experimental")
    meta = _require_json_object_section(genome, "metadata")
    topo = _require_json_object_section(genome, "topology")

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
        if type(src_name) is not str or src_name.upper() not in STATE_NAME_TO_ID:
            raise PortableGenomeError("transition source state must be a known state name")
        src_id = STATE_NAME_TO_ID[src_name.upper()]
        int_table[src_id] = {}
        for count_str, target_name in mappings.items():
            if type(count_str) is not str:
                raise PortableGenomeError("transition neighbor count must be an integer string")
            try:
                neighbor_count = int(count_str)
            except ValueError:
                raise PortableGenomeError("transition neighbor count must be an integer string") from None
            if type(target_name) is not str or target_name.upper() not in STATE_NAME_TO_ID:
                raise PortableGenomeError("transition target state must be a known state name")
            int_table[src_id][neighbor_count] = STATE_NAME_TO_ID[target_name.upper()]

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
    """Extract lattice and memory_grid from a genome epigenetic snapshot.

    Structural refusals raise :class:`PortableGenomeError` -- a ``ValueError``
    subclass -- with an exact, value-free message, each validated at the site
    that dereferences it and before any of its contents is read:

      - the genome root, ``epigenetic_snapshot`` and (when a memory grid is
        present) ``memory_layout`` must be JSON objects. Previously each was
        dereferenced with ``.get()``, so any other JSON root -- an array,
        string, number, Boolean or ``null`` -- raised an ambient
        ``AttributeError``;
      - ``lattice_shape`` must be a JSON array of integers, because ``tuple()``
        and ``reshape`` dereference it;
      - ``lattice_b64`` / ``memory_grid_b64`` must be JSON strings, because
        ``base64.b64decode`` raises ``TypeError`` on other types;
      - ``num_channels`` must be an integer when present, because ``reshape``
        dereferences it;
      - ``snapshot_generation`` / ``snapshot_ca_step`` must be integers when
        present, because consumers format them with ``:,``.

    Every check now runs before ANY NumPy call: the wire-integrity package
    moved both `frombuffer`/`reshape` pairs to the end of the function, so a
    hostile shape can neither allocate nor overflow ahead of validation.

    Those ambient ``AttributeError`` and ``TypeError`` classes are programming
    -defect signals, so a caller that translates malformed input cannot catch
    them without also masking real bugs. Raising the module's existing domain
    error instead lets an ordinary ``ValueError`` handler translate a bad file
    while genuine defects keep propagating.

    Unchanged: an absent ``epigenetic_snapshot`` and one with
    ``included`` false both return ``None``; an absent ``memory_layout`` still
    yields the ``MEMORY_CHANNELS`` default; a missing required key still raises
    ``KeyError``; and a validly shaped genome decodes exactly as before.

    Wire integrity is settled in Python BEFORE NumPy is asked for anything:

      - ``included`` must be an actual JSON Boolean when present;
      - ``lattice_shape`` must be exactly three positive integers;
      - both base64 payloads decode strictly, so an out-of-alphabet character
        or bad padding is refused instead of being silently discarded;
      - each decoded payload length must equal exactly what the declared shape
        implies -- one byte per cell for the lattice, and
        ``num_channels x cells x 4`` for the memory grid -- computed with
        unbounded Python integers, so an enormous declared dimension is
        rejected by comparison rather than reaching NumPy and raising
        ``OverflowError``;
      - ``num_channels`` must be a positive integer when a grid is present.

    A deeply nested JSON document is translated at the single ``json.load``
    call, because CPython's scanner raises ``RecursionError`` -- a
    ``RuntimeError`` -- which no reasonable caller translates.

    This does NOT make the extractor total, and it makes no claim about which
    channel counts the Observatory can render: that is
    ``vis.observatory.loader``'s boundary. Scientific value ranges, dimension
    plausibility and cross-field semantics remain unvalidated.
    """
    filepath = Path(filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            genome = json.load(f)
        except RecursionError as exc:
            # Scoped to this one decode call and to this input: CPython's JSON
            # scanner recurses per nesting level, so a deeply nested document
            # exhausts the stack. `RecursionError` is a `RuntimeError`, outside
            # every sane translated set, so it would otherwise escape as a
            # traceback for what is purely malformed input. Nothing else in
            # this function is inside the handler.
            raise PortableGenomeError("genome JSON is nested too deeply") from exc

    if type(genome) is not dict:
        raise PortableGenomeError("genome must be a JSON object")

    epi = _require_json_object_section(genome, "epigenetic_snapshot")
    if not _require_json_boolean(epi, "included"):
        return None

    # Wire integrity is settled entirely in Python before NumPy is asked for
    # anything, so a hostile shape can neither allocate nor overflow first.
    shape = _require_lattice_shape(epi)
    cells = shape[0] * shape[1] * shape[2]
    lattice_bytes = _decode_base64_strict(epi, "lattice_b64")
    _require_payload_length(lattice_bytes, cells * _UINT8_BYTES, "lattice_b64")

    memory_grid = None
    mg_bytes = None
    num_channels = None
    if "memory_grid_b64" in epi:
        mg_bytes = _decode_base64_strict(epi, "memory_grid_b64")
        num_channels = _require_channel_count(
            _require_json_object_section(genome, "memory_layout")
        )
        _require_payload_length(
            mg_bytes, num_channels * cells * _FLOAT32_BYTES, "memory_grid_b64"
        )

    snapshot_meta = {
        "generation": _require_counter(epi, "snapshot_generation"),
        "ca_step": _require_counter(epi, "snapshot_ca_step"),
    }

    lattice = np.frombuffer(lattice_bytes, dtype=np.uint8).reshape(shape)
    if mg_bytes is not None:
        memory_grid = np.frombuffer(mg_bytes, dtype=np.float32).reshape(
            (num_channels,) + shape
        )
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
            # An NPZ member of object dtype IS a pickle, so loading one with
            # pickle enabled is arbitrary code execution by construction, and
            # this path takes its archive straight from the command line.
            # NumPy now refuses such a member with a ValueError instead of
            # reconstructing it. `allow_pickle=False` is passed EXPLICITLY
            # although it is already NumPy's default: a default makes the
            # property invisible at the call site and silently reversible by an
            # upstream change. There is no fallback retry and no override.
            # This is an object-member refusal, not archive validation.
            #
            # The context manager closes the archive before `export_genome`
            # begins -- deterministically, not left to garbage collection.
            # Every member this CLI reads is materialised inside the block
            # (an unread member is never touched at all), so the base64
            # encoding downstream reads real in-memory arrays.
            with np.load(args.snapshot, allow_pickle=False) as snap:
                lattice, memory_grid = snap["lattice"], snap["memory_grid"]
                gen, ca_step_count = int(snap.get("generation", 0)), int(snap.get("ca_step", 0))
                best_fit = float(snap.get("best_fitness", 0.0))
        path = export_genome(args.output, rule_spec=rule_spec, generation=gen,
                             ca_step=ca_step_count, best_fitness=best_fit,
                             lattice=lattice, memory_grid=memory_grid,
                             include_epigenetic=args.include_epigenetic)
        print(f"Genome exported to: {path} ({path.stat().st_size:,} bytes)")
    elif args.command == "info":
        try:
            _, config, md = import_genome(args.genome)
        except PortableGenomeError as exc:
            # Only structural refusals route through argparse's ordinary error
            # path (exit code 2). JSON syntax errors, filesystem errors,
            # MemoryError and unrelated exceptions are deliberately NOT caught.
            parser.error(str(exc))
        for k in ["name", "version", "author", "exported_at", "source_generation", "source_ca_step", "best_fitness"]:
            print(f"  {k}: {md.get(k, '?')}")
        print(f"  states: {len(config.transition_table)} with transitions")
    else:
        parser.print_help()
