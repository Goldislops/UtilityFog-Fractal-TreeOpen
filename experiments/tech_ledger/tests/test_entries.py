"""Committed exemplar entries: all validate; classifications exactly as
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


def test_all_exemplars_validate_and_ids_match_filenames():
    summary = validate_directory(_ENTRIES_DIR)
    assert summary["entry_count"] == 5
    for record in summary["entries"]:
        assert record["filename"] == f"{record['entry_id']}.json"
    assert [r["entry_id"] for r in summary["entries"]] == [
        "TLV4-001",
        "TLV4-008",
        "TLV4-016",
        "TLV4-025",
        "TLV4-029",
    ]


def test_tlv4_001_topology_models():
    entry = _load("TLV4-001")
    assert entry["primary_classification"] == "E"
    assert entry["classification_qualifiers"] == ["B", "F"]
    assert entry["implementation_disposition"] == "evidence-gated"
    assert "physical evidence" in " ".join(entry["warnings"])


def test_tlv4_008_zero_point_claims():
    entry = _load("TLV4-008")
    assert entry["primary_classification"] == "F"
    assert entry["implementation_disposition"] == "prohibited"
    assert entry["implementation_seam"] is None
    assert entry["repository_placements"] == ["research-ledger"]
    assert "Casimir" in entry["classification_rationale"]


def test_tlv4_016_deterministic_execution():
    entry = _load("TLV4-016")
    assert entry["primary_classification"] == "A"
    assert entry["implementation_disposition"] == "eligible"
    assert "byte-identical" in entry["implementation_seam"]


def test_tlv4_025_conventional_explanations_first():
    entry = _load("TLV4-025")
    assert entry["primary_classification"] == "B"
    assert entry["implementation_disposition"] == "eligible"
    # The entry enforces sequence and recording -- it never encodes an
    # anomaly outcome (neither conventional nor exotic).
    text = json.dumps(entry)
    assert "never a predetermined outcome" in text
    assert "refuses anomaly escalation until" in entry["implementation_seam"]


def test_tlv4_029_v5_deferred_ingestion():
    entry = _load("TLV4-029")
    assert entry["primary_classification"] == "A"
    assert entry["classification_qualifiers"] == ["G"]
    assert entry["status"] == "v5-deferred"
    assert entry["implementation_disposition"] == "deferred"
    assert entry["implementation_seam"] is None
    assert entry["repository_placements"] == ["future-watch"]
    assert entry["provenance"]["verification_status"] == "unverified"
