"""NP9: public artifact validators — contract + adversarial tests.

Canonical live-producer artifacts must pass; every single-field mutation
in the table-driven corpora must fail at its expected boundary; the
caller's object is never mutated; repeated validation is deterministic.
"""

from __future__ import annotations

import copy
import json
import math
import pathlib
import random

import pytest

from scripts.nextness_artifact_validation import (
    MAX_ARTIFACT_BYTES,
    ArtifactValidationError,
    load_evaluation_artifact,
    load_evidence_packet,
    load_lab_artifact,
    validate_evaluation_artifact,
    validate_evidence_packet,
    validate_lab_artifact,
)
from scripts.nextness_evaluator import build_evaluation, serialize_evaluation
from scripts.nextness_evidence_packet import build_packet, serialize_packet
from scripts.nextness_monitor import (
    MonitorConfig,
    build_receipt,
    observations_from_log,
    serialize_receipt,
)
from scripts.nextness_predictor import build_report, serialize_report
from scripts.nextness_replay_lab import build_lab_report, serialize_lab_report

A = "void_static"
B = "compute_static"


# ---------------------------------------------------------------------------
# Live producer chain (one per module, session-scoped for speed)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    root = tmp_path_factory.mktemp("np9chain")
    log = root / "nextness_runs.jsonl"
    log.write_bytes(
        ("\n".join(
            json.dumps({"generation": i, "token_counts": {(A if i % 2 == 0 else B): 3}})
            for i in range(60)
        ) + "\n").encode()
    )
    report = root / "report.json"
    report.write_bytes(serialize_report(build_report(log)).encode())
    observations, reference, recent = observations_from_log(log, "first_order")
    receipts = root / "receipt.json"
    receipts.write_bytes(
        serialize_receipt(
            build_receipt(
                model="first_order", observations=observations,
                reference_counts=reference, recent_counts=recent,
                config=MonitorConfig(),
            )
        ).encode()
    )
    evaluation_file = root / "evaluation.json"
    evaluation_file.write_bytes(
        serialize_evaluation(build_evaluation(report_path=report, receipts_path=receipts)).encode()
    )
    protocol = root / "protocol.json"
    protocol.write_bytes(
        (json.dumps({
            "schema": "nextness-replay-protocol-v1", "model": "first_order",
            "smoothing": 1.0, "holdout_fraction": 0.25,
            "configurations": [
                {"label": "defaults", "min_history": 30, "window": 50,
                 "low_confidence_threshold": 0.3,
                 "calibration_error_threshold": 0.2,
                 "drift_threshold_bits": 0.15},
                {"label": "loose", "min_history": 5, "window": 7,
                 "low_confidence_threshold": 0.01,
                 "calibration_error_threshold": 0.9,
                 "drift_threshold_bits": 0.9},
            ],
        }) + "\n").encode()
    )
    lab_file = root / "lab.json"
    lab_file.write_bytes(serialize_lab_report(build_lab_report(log, protocol)).encode())
    packet = build_packet({
        "report": report, "receipts": receipts, "evaluation": evaluation_file,
        "lab": lab_file, "protocol": protocol, "log": log,
    })
    return {
        "evaluation": json.loads(evaluation_file.read_text(encoding="utf-8")),
        "lab": json.loads(lab_file.read_text(encoding="utf-8")),
        "packet": json.loads(serialize_packet(packet)),
        "paths": {"evaluation": evaluation_file, "lab": lab_file,
                  "report": report, "receipts": receipts, "log": log},
    }


def _eval(live) -> dict:
    return copy.deepcopy(live["evaluation"])


def _lab(live) -> dict:
    return copy.deepcopy(live["lab"])


def _packet(live) -> dict:
    return copy.deepcopy(live["packet"])


# ---------------------------------------------------------------------------
# Canonical artifacts pass; sanitized copy; no caller mutation; determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["evaluation", "lab", "packet"])
def test_canonical_artifact_passes_without_mutation(live, name) -> None:
    validator = {
        "evaluation": validate_evaluation_artifact,
        "lab": validate_lab_artifact,
        "packet": validate_evidence_packet,
    }[name]
    artifact = copy.deepcopy(live[name])
    before = copy.deepcopy(artifact)
    validated = validator(artifact)
    assert artifact == before          # caller object untouched
    assert validated == artifact       # sanitized copy, semantically equal
    assert validated is not artifact   # and genuinely a copy
    again = validator(artifact)
    assert again == validated          # deterministic output
    assert json.dumps(again, sort_keys=True) == json.dumps(validated, sort_keys=True)


def test_partial_evaluations_pass(live) -> None:
    report = live["paths"]["report"]
    receipts = live["paths"]["receipts"]
    report_only = json.loads(serialize_evaluation(build_evaluation(report_path=report)))
    assert validate_evaluation_artifact(report_only) == report_only
    receipts_only = json.loads(serialize_evaluation(build_evaluation(receipts_path=receipts)))
    assert validate_evaluation_artifact(receipts_only) == receipts_only


#: A small hand-written INDEPENDENT golden packet (log-only manifest,
#: every link typed not_computable) — not derived from the emitters.
GOLDEN_INDEPENDENT_PACKET = {
    "schema": "nextness-evidence-packet-v1",
    "config": {"max_packet_artifacts": 8, "max_input_bytes": 1048576,
               "max_packet_bytes": 65536},
    "artifacts": [
        {"role": "log", "schema": "jsonl-nextness-runs", "bytes": 847,
         "sha256": "a" * 64, "sequence_sha256": "b" * 64,
         "sequence_bounds": {"max_rows": 100000, "max_line_bytes": 65536},
         "rows_accepted": 12, "validation": "sequence_reader"},
    ],
    "links": {
        kind: {"status": "not_computable", "reason": "counterpart_absent",
               "requires": "a lab-report artifact"}
        for kind in ("evaluation_report_sha256", "evaluation_receipts_sha256",
                     "lab_protocol_sha256", "lab_sequence_sha256")
    },
    "non_claims": [
        "Packaging and provenance verification only: nothing here scores, "
        "ranks, recommends, tunes, acts, invokes a model or contacts a "
        "service.",
        "A not_computable link is a statement about which artifacts were "
        "provided, not about the artifacts' integrity.",
        "No awareness, consciousness, phenomenology or biological-equivalence "
        "claim is made or implied.",
    ],
}


def test_independent_golden_packet_passes() -> None:
    golden = copy.deepcopy(GOLDEN_INDEPENDENT_PACKET)
    assert validate_evidence_packet(golden) == GOLDEN_INDEPENDENT_PACKET


# ---------------------------------------------------------------------------
# Table-driven mutation corpora: every mutation fails at its boundary
# ---------------------------------------------------------------------------

EVALUATION_MUTATIONS = [
    ("extra-top-key", lambda a: a.__setitem__("surprise", 1), "key set mismatch"),
    ("missing-section", lambda a: a.__delitem__("recovery"), "key set mismatch"),
    ("schema-bump", lambda a: a.__setitem__("schema", "nextness-evaluation-v2"), "v1 constant"),
    ("config-variant", lambda a: a["config"].__setitem__("max_detail_items", 64), "v1 constant"),
    ("envelope-unknown-status", lambda a: a["prediction"]["uniform_nll_bits"].__setitem__("status", "maybe"), "unknown variant"),
    ("envelope-extra-key", lambda a: a["prediction"]["rankings"].__setitem__("note", "x"), "key set mismatch"),
    ("nc-reason-unknown", lambda a: a["prediction"]["metric_difference_significance"].__setitem__("reason", "vibes"), "unknown variant"),
    ("never-computed-computed", lambda a: a["prediction"].__setitem__(
        "metric_difference_significance", {"status": "computed", "value": 1}), "never computes"),
    ("reason-counts-sum", lambda a: a["abstention"]["reason_counts"]["value"].__setitem__("none", 99), "outside"),
    ("reason-counts-unknown-key", lambda a: a["abstention"]["reason_counts"]["value"].__setitem__("vibes", 0), "key set mismatch"),
    ("verdict-tallies-sum", lambda a: a["abstention"]["consistency"]["value"]["stated_reason_trigger"]["verdicts"].__setitem__("consistent", 0), "do not sum"),
    ("indices-not-increasing", lambda a: a["abstention"]["consistency"]["value"]["abstain_flag_matches_reason"].__setitem__("contradicted_indices", [0, 0]), "length contradicts|not strictly increasing"),
    ("truncation-contradiction", lambda a: a["abstention"]["consistency"]["value"]["abstain_flag_matches_reason"].__setitem__("contradicted_indices_truncated", True), "truncation flag contradicts"),
    ("witness-with-violation", lambda a: a["recovery"]["chronology"]["value"].__setitem__("first_violation_index", 1), "witnessed with a violation"),
    ("gate-violation", lambda a: a["recovery"]["chronology"]["value"].update(
        {"witnessed": False, "first_violation_index": 1}), "order_not_witnessed|without a chronology witness"),
    ("assumptions-mismatch", lambda a: a.__setitem__("assumptions", []), "does not match the computed sections"),
    ("ranking-not-permutation", lambda a: a["prediction"]["rankings"]["value"].__setitem__(
        "by_nll_bits", ["first_order", "first_order", "persistence"]), "not a permutation"),
    ("agree-contradiction", lambda a: a["prediction"].__setitem__(
        "proper_score_rankings_agree",
        {"status": "computed", "value": not a["prediction"]["proper_score_rankings_agree"]["value"]}),
     "contradicts the recorded rankings"),
    ("provided-bool-as-int", lambda a: a["artifacts"]["report"].__setitem__("provided", 1), "expected builtin bool"),
    ("sha-uppercase", lambda a: a["artifacts"]["report"].__setitem__("sha256", "A" * 64), "lowercase hex"),
    ("nan-rate", lambda a: a["abstention"]["abstention_rate"].__setitem__("value", float("nan")), "not finite"),
    ("huge-receipt-count", lambda a: a["abstention"]["receipt_count"].__setitem__("value", 10**7), "outside"),
    ("count-slot-mismatch", lambda a: a["artifacts"]["receipts"].__setitem__("receipt_count", 7), "contradicts artifacts.receipts"),
    ("ingestion-identity", lambda a: a["prediction"]["ingestion"]["value"].__setitem__("train_rows", 44), "train_rows"),
    ("bytes-bool", lambda a: a["artifacts"]["report"].__setitem__("bytes", True), "builtin int"),
    ("non-claims-edited", lambda a: a["non_claims"].__setitem__(0, "we promise things"), "v1 constant"),
]


@pytest.mark.parametrize("name,mutate,match", EVALUATION_MUTATIONS,
                         ids=[m[0] for m in EVALUATION_MUTATIONS])
def test_evaluation_mutation_rejected(live, name, mutate, match) -> None:
    artifact = _eval(live)
    mutate(artifact)
    with pytest.raises(ArtifactValidationError, match=match):
        validate_evaluation_artifact(artifact)


LAB_MUTATIONS = [
    ("extra-top-key", lambda a: a.__setitem__("winner", "x"), "key set mismatch"),
    ("missing-input-field", lambda a: a["input"].__delitem__("sequence_sha256"), "key set mismatch"),
    ("not-a-lab-observation", lambda a: a.__setitem__("laboratory_observation", False), "v1 constant"),
    ("unknown-model", lambda a: a["config"].__setitem__("model", "second_order"), "unknown variant"),
    ("smoothing-zero", lambda a: a["config"].__setitem__("smoothing", 0), "outside the documented range"),
    ("holdout-fraction-out", lambda a: a["config"].__setitem__("holdout_fraction", 0.6), "outside the documented range"),
    ("rejections-sum", lambda a: a["input"]["rejections"].__setitem__("malformed_json", 5), "do not sum"),
    ("accounting-identity", lambda a: a["input"].__setitem__("train_rows", 40), "train_rows \\+ holdout_steps"),
    ("duplicate-labels", lambda a: a["configurations"][1].__setitem__("label", a["configurations"][0]["label"]), "duplicate"),
    ("label-too-long", lambda a: a["configurations"][0].__setitem__("label", "x" * 65), "length must be"),
    ("reason-counts-sum", lambda a: a["configurations"][0]["trajectory"]["reason_step_counts"].__setitem__("unseen_state", 1), "do not sum"),
    ("rate-contradiction", lambda a: a["configurations"][0]["trajectory"].__setitem__("abstention_step_rate", 0.5), "contradicts the reason counts"),
    ("final-coherence", lambda a: a["configurations"][0]["trajectory"].__setitem__("final_abstain",
        not a["configurations"][0]["trajectory"]["final_abstain"]), "final_abstain contradicts final_reason|recorded although|null although"),
    ("threshold-at-one", lambda a: a["configurations"][0]["config"].__setitem__("low_confidence_threshold", 1.0), "outside the documented range"),
    ("min-history-bool", lambda a: a["configurations"][0]["config"].__setitem__("min_history", True), "builtin int"),
    ("step-count-mismatch", lambda a: a["configurations"][0]["trajectory"].__setitem__("step_count", 14), "contradicts input.holdout_steps"),
    ("truncation-contradiction", lambda a: a["configurations"][0]["trajectory"].__setitem__("run_lengths_truncated", True), "contradicts reorientations"),
    ("sha-short", lambda a: a["input"].__setitem__("protocol_sha256", "ab"), "lowercase hex"),
    ("non-claims-edited", lambda a: a["non_claims"].__setitem__(1, "improved!"), "v1 constant"),
]


@pytest.mark.parametrize("name,mutate,match", LAB_MUTATIONS,
                         ids=[m[0] for m in LAB_MUTATIONS])
def test_lab_mutation_rejected(live, name, mutate, match) -> None:
    artifact = _lab(live)
    mutate(artifact)
    with pytest.raises(ArtifactValidationError, match=match):
        validate_lab_artifact(artifact)


def _reorder_packet_roles(a: dict) -> None:
    a["artifacts"] = list(reversed(a["artifacts"]))


PACKET_MUTATIONS = [
    ("schema-bump", lambda a: a.__setitem__("schema", "nextness-evidence-packet-v2"), "v1 constant"),
    ("config-variant", lambda a: a["config"].__setitem__("max_packet_artifacts", 9), "v1 constant"),
    ("duplicate-role", lambda a: a["artifacts"].append(dict(a["artifacts"][0])), "duplicate role"),
    ("out-of-order-roles", _reorder_packet_roles, "canonical order"),
    ("unknown-role", lambda a: a["artifacts"][0].__setitem__("role", "telemetry"), "unknown variant"),
    ("depth-wrong-for-report", lambda a: a["artifacts"][0].__setitem__("validation", "schema_identifier_only"), "entries are full"),
    ("log-bounds-non-default", lambda a: a["artifacts"][-1]["sequence_bounds"].__setitem__("max_rows", 10), "v1 constant"),
    ("link-status-unknown", lambda a: a["links"].__setitem__("lab_protocol_sha256", {"status": "maybe"}), "unknown variant"),
    ("verified-unequal-hashes", lambda a: a["links"]["lab_protocol_sha256"].__setitem__("actual_sha256", "f" * 64), "status contradicts the recorded hashes"),
    ("nc-reason-unknown", lambda a: a["links"].__setitem__("evaluation_report_sha256",
        {"status": "not_computable", "reason": "vibes", "requires": "x"}), "unknown variant"),
    ("sequence-link-missing-bounds", lambda a: a["links"]["lab_sequence_sha256"].__delitem__("reader_bounds"), "key set mismatch"),
    ("reader-bounds-zero", lambda a: a["links"]["lab_sequence_sha256"]["reader_bounds"].__setitem__("max_rows", 0), "outside"),
    ("bytes-negative", lambda a: a["artifacts"][0].__setitem__("bytes", -1), "outside"),
    ("empty-artifacts", lambda a: a.__setitem__("artifacts", []), "empty"),
    ("non-claims-edited", lambda a: a["non_claims"].__setitem__(0, "ranked and scored"), "v1 constant"),
]


@pytest.mark.parametrize("name,mutate,match", PACKET_MUTATIONS,
                         ids=[m[0] for m in PACKET_MUTATIONS])
def test_packet_mutation_rejected(live, name, mutate, match) -> None:
    artifact = _packet(live)
    mutate(artifact)
    with pytest.raises(ArtifactValidationError, match=match):
        validate_evidence_packet(artifact)


def test_broken_link_form_is_valid_and_stays_broken(live) -> None:
    # Structural validation must not convert a broken statement into
    # success: a well-formed broken link (unequal hashes) passes
    # validation AND remains status=broken in the sanitized copy.
    artifact = _packet(live)
    link = artifact["links"]["lab_protocol_sha256"]
    assert link["status"] == "verified"
    link["status"] = "broken"
    link["actual_sha256"] = "f" * 64
    validated = validate_evidence_packet(artifact)
    assert validated["links"]["lab_protocol_sha256"]["status"] == "broken"


# ---------------------------------------------------------------------------
# Hostile containers, mutation determinism, seeded corruption
# ---------------------------------------------------------------------------


def test_hostile_container_subclasses_rejected_before_iteration(live) -> None:
    class EvilDict(dict):
        def keys(self):  # pragma: no cover - must never be consulted
            raise AssertionError("hostile keys() was consulted")

    class EvilList(list):
        def __iter__(self):  # pragma: no cover - must never be consulted
            raise AssertionError("hostile __iter__ was consulted")

    class EvilStr(str):
        def __eq__(self, other):  # pragma: no cover - must never be consulted
            raise AssertionError("hostile __eq__ was consulted")
        __hash__ = str.__hash__

    with pytest.raises(ArtifactValidationError, match="builtin dict"):
        validate_evaluation_artifact(EvilDict(_eval(live)))
    lab = _lab(live)
    lab["configurations"] = EvilList(lab["configurations"])
    with pytest.raises(ArtifactValidationError, match="builtin list"):
        validate_lab_artifact(lab)
    packet = _packet(live)
    packet["schema"] = EvilStr("nextness-evidence-packet-v1")
    with pytest.raises(ArtifactValidationError, match="v1 constant"):
        validate_evidence_packet(packet)
    # Envelope/link statuses are exact-type-checked BEFORE any equality
    # comparison, so a hostile str subclass's __eq__ never executes.
    evaluation = _eval(live)
    evaluation["prediction"]["uniform_nll_bits"]["status"] = EvilStr("computed")
    with pytest.raises(ArtifactValidationError, match="builtin str"):
        validate_evaluation_artifact(evaluation)
    packet2 = _packet(live)
    packet2["links"]["lab_protocol_sha256"]["status"] = EvilStr("verified")
    with pytest.raises(ArtifactValidationError, match="builtin str"):
        validate_evidence_packet(packet2)


def test_error_messages_deterministic(live) -> None:
    artifact = _eval(live)
    artifact["abstention"]["reason_counts"]["value"]["none"] = 99
    messages = set()
    for _ in range(3):
        with pytest.raises(ArtifactValidationError) as exc:
            validate_evaluation_artifact(copy.deepcopy(artifact))
        messages.add(str(exc.value))
    assert len(messages) == 1


_JUNK = [None, float("nan"), float("inf"), 10**400, True, "junk", [], {}, -1e308]


@pytest.mark.parametrize("seed", [7, 77, 777])
def test_seeded_random_corruption_never_escapes_the_typed_error(live, seed) -> None:
    # Corrupt a random leaf with junk: the validator must either raise
    # ArtifactValidationError or (never) accept silently — no other
    # exception type may escape, and valid artifacts must keep passing.
    rng = random.Random(seed)
    for name, validator in (
        ("evaluation", validate_evaluation_artifact),
        ("lab", validate_lab_artifact),
        ("packet", validate_evidence_packet),
    ):
        for _ in range(40):
            artifact = copy.deepcopy(live[name])
            node = artifact
            path = []
            # walk to a random leaf
            while True:
                if isinstance(node, dict) and node:
                    key = rng.choice(sorted(node, key=str))
                    path.append(key)
                    if isinstance(node[key], (dict, list)) and node[key] and rng.random() < 0.7:
                        node = node[key]
                        continue
                    node[key] = rng.choice(_JUNK)
                    break
                elif isinstance(node, list) and node:
                    idx = rng.randrange(len(node))
                    path.append(idx)
                    if isinstance(node[idx], (dict, list)) and node[idx] and rng.random() < 0.7:
                        node = node[idx]
                        continue
                    node[idx] = rng.choice(_JUNK)
                    break
                else:
                    break
            try:
                validator(artifact)
            except ArtifactValidationError:
                pass  # the only acceptable failure mode
        # the pristine artifact still passes after all that
        assert validator(copy.deepcopy(live[name])) == live[name]


# ---------------------------------------------------------------------------
# Bounded file loaders
# ---------------------------------------------------------------------------


def test_file_loaders_load_and_validate(live, tmp_path) -> None:
    assert load_evaluation_artifact(live["paths"]["evaluation"]) == live["evaluation"]
    assert load_lab_artifact(live["paths"]["lab"]) == live["lab"]
    packet_file = tmp_path / "packet.json"
    packet_file.write_bytes((json.dumps(live["packet"]) + "\n").encode())
    assert load_evidence_packet(packet_file) == live["packet"]


def test_file_loader_bounds_fail_closed(tmp_path) -> None:
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 10))
    with pytest.raises(ArtifactValidationError, match="exceeds"):
        load_evaluation_artifact(big)
    dup = tmp_path / "dup.json"
    dup.write_bytes(b'{"schema": "x", "schema": "y"}')
    with pytest.raises(ArtifactValidationError, match="duplicate JSON key"):
        load_lab_artifact(dup)
    deep = tmp_path / "deep.json"
    deep.write_bytes(b"[" * 200_000)
    with pytest.raises(ArtifactValidationError, match="depth limit|not valid"):
        load_evidence_packet(deep)


def test_math_constants_still_pinned() -> None:
    # The evaluation validator's numeric ceiling mirrors NP5's; keep the
    # derivation visible so drift is loud here too.
    from scripts.nextness_artifact_validation import _NLL_BITS_MAX

    assert _NLL_BITS_MAX == -math.log2(1e-300) + 1e-6
