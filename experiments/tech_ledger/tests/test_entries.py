"""Committed technology-ledger entries: all validate; classifications exactly as
authorised. Validation here proves record structure only -- never the
truth of any claim.
"""

from __future__ import annotations

import json
import pathlib

from experiments.tech_ledger.validate import validate_directory

_ENTRIES_DIR = pathlib.Path(__file__).resolve().parent.parent / "entries"


def _load(entry_id):
    return json.loads(
        (_ENTRIES_DIR / f"{entry_id}.json").read_text(encoding="utf-8")
    )


def test_all_committed_entries_validate_and_ids_match_filenames():
    summary = validate_directory(_ENTRIES_DIR)
    assert summary["entry_count"] == 20
    for record in summary["entries"]:
        assert record["filename"] == f"{record['entry_id']}.json"
    assert [r["entry_id"] for r in summary["entries"]] == [
        "TLV4-001",
        "TLV4-002",
        "TLV4-003",
        "TLV4-004",
        "TLV4-005",
        "TLV4-006",
        "TLV4-008",
        "TLV4-009",
        "TLV4-010",
        "TLV4-011",
        "TLV4-012",
        "TLV4-016",
        "TLV4-017",
        "TLV4-019",
        "TLV4-023",
        "TLV4-024",
        "TLV4-025",
        "TLV4-027",
        "TLV4-028",
        "TLV4-029",
    ]


def test_tlv4_001_topology_models():
    entry = _load("TLV4-001")
    assert entry["primary_classification"] == "E"
    assert entry["classification_qualifiers"] == ["B", "F"]
    assert entry["implementation_disposition"] == "evidence-gated"
    assert "physical evidence" in " ".join(entry["warnings"])


def test_tlv4_002_wkb_tunnelling_models():
    entry = _load("TLV4-002")
    assert entry["entry_id"] == "TLV4-002"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "evidence-gated"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "WKB transmission coefficient checked against the exact "
        "rectangular-barrier solution to stated tolerance"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["experiment", "research-ledger"]
    warnings = " ".join(entry["warnings"])
    assert "regime-bounded" in warnings


def test_tlv4_003_gaussian_wave_packets():
    entry = _load("TLV4-003")
    assert entry["entry_id"] == "TLV4-003"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Free-packet variance growth checked against the analytic formula"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["experiment"]
    warnings = " ".join(entry["warnings"])
    assert "beyond the toy" in warnings


def test_tlv4_004_page_wootters_relational_time():
    entry = _load("TLV4-004")
    assert entry["entry_id"] == "TLV4-004"
    assert entry["primary_classification"] == "C"
    assert entry["classification_qualifiers"] == ["E", "G"]
    assert entry["implementation_disposition"] == "evidence-gated"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Two-qubit clock/system conditional-state toy reproducing the "
        "finite two-photon conditional-state experiment of Moreva et al., "
        "Phys. Rev. A 89, 052122 (2014), including its finite-clock "
        "visibility reduction; separately, the exact ordinary-evolution "
        "equivalence theorem (Page-Wootters 1983 Sec. III; "
        "Giovannetti-Lloyd-Maccone, Phys. Rev. D 92, 045033 (2015)) applies "
        "only to a non-interacting clock, ideal in the continuous-clock "
        "limit; no device capability or physical validation is implied"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["research-ledger", "experiment"]
    warnings = " ".join(entry["warnings"])
    assert "no time-mechanism truth claim" in warnings


def test_tlv4_005_landau_lifshitz_pseudotensor():
    entry = _load("TLV4-005")
    assert entry["entry_id"] == "TLV4-005"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == ["F"]
    assert entry["implementation_disposition"] == "evidence-gated"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Numerical quadrupole-formula check against the analytic "
        "binary-inspiral leading order"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["research-ledger", "experiment"]
    warnings = " ".join(entry["warnings"])
    assert "coordinate-dependence caveat must travel" in warnings


def test_tlv4_006_effective_field_theory_scale_separation():
    entry = _load("TLV4-006")
    assert entry["entry_id"] == "TLV4-006"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == ["D"]
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Schema-level requirement that physics-model records carry a "
        "non-empty scales-and-validity field (presence, never truth)"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["schema", "research-ledger"]
    warnings = " ".join(entry["warnings"])
    assert "The schema enforces declaration" in warnings


def test_tlv4_008_zero_point_claims():
    entry = _load("TLV4-008")
    assert entry["primary_classification"] == "F"
    assert entry["implementation_disposition"] == "prohibited"
    assert entry["implementation_seam"] is None
    assert entry["repository_placements"] == ["research-ledger"]
    # Conservative-substance pins: the F label is an evidence and
    # engineering disposition for THIS repository, never a physical
    # theorem or a categorical scientific verdict.
    rationale = entry["classification_rationale"]
    assert "no independently replicated demonstration" in rationale
    assert "does not by itself demonstrate a cyclic net-work source" in rationale
    assert "full-cycle energy accounting" in rationale
    assert "not a declaration" in rationale
    warnings = " ".join(entry["warnings"])
    assert "separately audited reclassification" in warnings
    assert "not a physical theorem" in warnings
    # Categorical wording stays out.
    assert "contradicts thermodynamics" not in rationale
    assert "none known" not in " ".join(
        entry["minimal_evidence_before_implementation"]
    )


def test_tlv4_009_laplace_spectral_tooling():
    entry = _load("TLV4-009")
    assert entry["entry_id"] == "TLV4-009"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Transform-pair round-trip tests against known analytic pairs"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["executable-code", "experiment"]
    warnings = " ".join(entry["warnings"])
    assert "no physics claim attaches to its use" in warnings


def test_tlv4_010_conventional_baseline_models():
    entry = _load("TLV4-010")
    assert entry["entry_id"] == "TLV4-010"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Schema-level requirement that anomaly-type records carry non-empty "
        "baseline-model and conventional-explanation fields"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["schema", "research-ledger"]
    warnings = " ".join(entry["warnings"])
    assert "Enforce process and recording" in warnings


def test_tlv4_011_stateless_protocol_boundaries():
    entry = _load("TLV4-011")
    assert entry["entry_id"] == "TLV4-011"
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Contract tests on a request/response schema"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["executable-code"]
    warnings = " ".join(entry["warnings"])
    assert "Offline verification paths must stay network-free" in warnings


def test_tlv4_012_agent_orchestration_patterns():
    entry = _load("TLV4-012")
    assert entry["entry_id"] == "TLV4-012"
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Provenance-field validation for machine-authored ledger entries"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == [
        "executable-code",
        "research-ledger",
    ]
    warnings = " ".join(entry["warnings"])
    assert "Agent output is never evidence by itself" in warnings


def test_tlv4_016_deterministic_execution():
    entry = _load("TLV4-016")
    assert entry["primary_classification"] == "A"
    assert entry["implementation_disposition"] == "eligible"
    assert "byte-identical" in entry["implementation_seam"]


def test_tlv4_017_local_first_air_gapped_operation():
    entry = _load("TLV4-017")
    assert entry["entry_id"] == "TLV4-017"
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Socket-guard test fixtures asserting no network access in "
        "offline paths"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == [
        "executable-code",
        "research-ledger",
    ]
    warnings = " ".join(entry["warnings"])
    assert "Offline claims are verified by tests" in warnings


def test_tlv4_019_hardware_aware_resource_budgeting():
    entry = _load("TLV4-019")
    assert entry["entry_id"] == "TLV4-019"
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Budget-configuration schema validation"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["executable-code"]
    warnings = " ".join(entry["warnings"])
    assert "Budgets describe machines, not truths" in warnings


def test_tlv4_023_timestamp_uncertainty_propagation():
    entry = _load("TLV4-023")
    assert entry["entry_id"] == "TLV4-023"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Uncertainty-propagation unit tests on simple composition cases"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["schema", "executable-code"]
    warnings = " ".join(entry["warnings"])
    assert "A missing uncertainty field is a refusal" in warnings


def test_tlv4_024_cross_sensor_artefact_rejection():
    entry = _load("TLV4-024")
    assert entry["entry_id"] == "TLV4-024"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Validator requiring artefact-review status on observation records"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["schema", "research-ledger"]
    warnings = " ".join(entry["warnings"])
    assert "Enforce recording and sequence" in warnings


def test_tlv4_025_conventional_explanations_first():
    entry = _load("TLV4-025")
    assert entry["primary_classification"] == "B"
    assert entry["implementation_disposition"] == "eligible"
    # The entry enforces sequence and recording -- it never encodes an
    # anomaly outcome (neither conventional nor exotic).
    text = json.dumps(entry)
    assert "never a predetermined outcome" in text
    assert "refuses anomaly escalation until" in entry["implementation_seam"]


def test_tlv4_027_provenance_chain_of_custody():
    entry = _load("TLV4-027")
    assert entry["entry_id"] == "TLV4-027"
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Append-only custody-event list with hash-chain verification tests"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["schema", "executable-code"]
    warnings = " ".join(entry["warnings"])
    assert "Say provenance-recorded" in warnings


def test_tlv4_028_confidence_calibration_competing_hypotheses():
    entry = _load("TLV4-028")
    assert entry["entry_id"] == "TLV4-028"
    assert entry["primary_classification"] == "B"
    assert entry["classification_qualifiers"] == []
    assert entry["implementation_disposition"] == "eligible"
    assert entry["status"] == "active"
    assert entry["implementation_seam"] == (
        "Schema requiring at least two recorded hypotheses (including a "
        "conventional one) before comparative fields validate"
    )
    assert entry["provenance"]["verification_status"] == "unverified"
    assert entry["repository_placements"] == ["schema", "research-ledger"]
    warnings = " ".join(entry["warnings"])
    assert "The ledger compares records" in warnings


def test_tlv4_029_v5_deferred_ingestion():
    entry = _load("TLV4-029")
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == ["G"]
    assert entry["status"] == "v5-deferred"
    assert entry["implementation_disposition"] == "deferred"
    assert entry["implementation_seam"] is None
    assert entry["repository_placements"] == ["future-watch"]
    assert entry["provenance"]["verification_status"] == "unverified"
