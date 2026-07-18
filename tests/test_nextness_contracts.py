"""NP7: cross-package contract guard - golden byte-stability + drift tripwires.

Test-owned compatibility layer over the four Nextness instruments (NP1
predictor, NP2 monitor, NP5 evaluator, NP6 replay lab). It exists to
make SILENT contract drift loud:

1. GOLDEN BYTE-STABILITY - canonical artifacts recorded from the live
   emitters are embedded below as string literals (immune to checkout
   newline translation) and every regeneration must be byte-identical.
   Any change to schemas, field sets, ordering, rounding, serialization
   or semantics of the emitters fails here first, visibly.
2. VOCABULARY / CONSTANT FREEZES - the fixed vocabularies and bounds the
   packages promise each other (token order = tie-break contract,
   abstention precedence order, reason/verdict vocabularies, size
   ceilings, rounding, mirrored constants such as the evaluator's
   SURPRISE_BITS_MAX vs the monitor's private cap) are pinned exactly.
3. EMITTER <-> VALIDATOR STRUCTURE LOCKS - live emitter output key sets
   must equal the evaluator's expected key sets, so the two sides of
   each schema cannot drift apart even in ways the goldens miss.
4. COMPATIBILITY CORPUS - the golden artifacts double as the
   backward-compatibility corpus (they must keep validating), and a
   mutation table over them checks unknown variants stay fail-closed.

The guard is discovered by the existing pytest configuration
(pytest.ini testpaths = tests); no workflow or required-check change is
needed or made. LIMITATION (honest scope): the guard runs when the test
suite runs - it detects drift at CI time, not at artifact-read time,
and it guards these four packages only, not the observer's own log
format beyond what read_dominant_sequence consumes.

If a test here fails because a contract was CHANGED DELIBERATELY,
regenerate the goldens with the documented procedure in
docs/NEXTNESS_CONTRACT_GUARD.md and say so explicitly in the PR - that
is the guard working, not the guard being wrong.
"""

from __future__ import annotations

import json
import math
import pathlib

import pytest

import scripts.nextness_evaluator as evaluator
import scripts.nextness_monitor as monitor
import scripts.nextness_predictor as predictor
import scripts.nextness_replay_lab as lab
from scripts.nextness_observer import TOKEN_NAMES

# 16 physical records: 12 accepted, 1 blank, 1 malformed, 1 duplicate
# generation, 1 unknown token - so the golden accounting is non-trivial.
GOLDEN_LOG = '''{"generation": 0, "token_counts": {"void_static": 5}}
{"generation": 1, "token_counts": {"compute_static": 4, "void_static": 1}}
{"generation": 2, "token_counts": {"void_birth": 3}}
{"generation": 3, "token_counts": {"compute_static": 6}}
{"generation": 4, "token_counts": {"void_static": 2, "energy_pulse": 7}}

{not json
{"generation": 4, "token_counts": {"void_static": 1}}
{"generation": 5, "token_counts": {"compute_static": 3}}
{"generation": 6, "token_counts": {"void_static": 4}}
{"generation": 7, "token_counts": {"compute_static": 2}}
{"generation": 8, "token_counts": {"void_static": 6}}
{"generation": 9, "token_counts": {"phase_boundary": 2, "compute_static": 1}}
{"generation": 10, "token_counts": {"void_static": 3}}
{"generation": 11, "token_counts": {"compute_static": 5}}
{"generation": 12, "token_counts": {"mystery_token": 1}}
'''

# nextness-predictor-v1, regenerated from GOLDEN_LOG by NP1.
GOLDEN_REPORT = '''{
 "config": {
  "ece_bins": 10,
  "holdout_fraction": 0.25,
  "max_line_bytes": 65536,
  "max_rows": 100000,
  "smoothing": 1.0,
  "vocabulary_size": 16
 },
 "evaluation": {
  "first_order_unseen_source_count": 1,
  "holdout_rows": 3,
  "models": {
   "empirical_prior": {
    "brier": 0.8309333333333333,
    "ece": 0.13333333333333328,
    "nll_bits": 3.203213491478937,
    "top1_accuracy": 0.3333333333333333
   },
   "first_order": {
    "brier": 0.8271012345679013,
    "ece": 0.2888888888888889,
    "nll_bits": 3.132914563979398,
    "top1_accuracy": 0.3333333333333333
   },
   "persistence": {
    "brier": 0.9480968858131488,
    "ece": 0.1176470588235294,
    "nll_bits": 4.087462841250339,
    "top1_accuracy": 0.0
   }
  },
  "split_index": 9,
  "train_rows": 9
 },
 "input": {
  "rejections": {
   "duplicate_generation": 1,
   "invalid_count_value": 0,
   "invalid_generation": 0,
   "invalid_token_counts": 0,
   "malformed_json": 1,
   "missing_generation": 0,
   "missing_token_counts": 0,
   "no_dominant_token": 0,
   "not_object": 0,
   "out_of_order_generation": 0,
   "oversized_line": 0,
   "unknown_token": 1
  },
  "rows_accepted": 12,
  "rows_read": 16,
  "rows_rejected": 3
 },
 "non_claims": [
  "Baselines only: no intelligence, awareness or performance-victory claim.",
  "A simple baseline outperforming a complex one is an expected, reported outcome."
 ],
 "schema": "nextness-predictor-v1"
}
'''

# nextness-monitor-v1, regenerated from GOLDEN_LOG by the NP2 bridge
# (first_order, MonitorConfig defaults).
GOLDEN_RECEIPT = '''{
 "abstain": true,
 "abstain_reason": "insufficient_history",
 "config": {
  "calibration_error_threshold": 0.2,
  "drift_threshold_bits": 0.15,
  "low_confidence_threshold": 0.3,
  "min_history": 30,
  "window": 50
 },
 "discarded_field_count": 0,
 "distribution_drift_bits": 0.283515,
 "input_reduced": false,
 "mean_confidence": 0.177778,
 "mean_surprise_bits": 3.132915,
 "model": "first_order",
 "non_claim": "functional-metacognition-only: no awareness, sentience or phenomenal-experience claim",
 "observation_count": 3,
 "rolling_calibration_error": 0.288889,
 "schema": "nextness-monitor-v1",
 "sufficiency": "insufficient"
}
'''

# nextness-evaluation-v1, regenerated by NP5 from the two goldens above
# (their exact bytes - the sha256 provenance inside is part of the pin).
GOLDEN_EVALUATION = '''{
 "abstention": {
  "abstention_quality": {
   "reason": "field_not_recorded",
   "requires": "per-observation outcomes during abstained spans (receipts record aggregates only, so whether an abstention was warranted cannot be established from the artifacts)",
   "status": "not_computable"
  },
  "abstention_rate": {
   "status": "computed",
   "value": 1.0
  },
  "configurations_identical": {
   "status": "computed",
   "value": true
  },
  "consistency": {
   "status": "computed",
   "value": {
    "abstain_flag_matches_reason": {
     "contradicted_indices": [],
     "contradicted_indices_truncated": false,
     "verdicts": {
      "consistent": 1,
      "contradicted": 0,
      "unverifiable": 0
     }
    },
    "higher_precedence_excluded": {
     "contradicted_indices": [],
     "contradicted_indices_truncated": false,
     "verdicts": {
      "consistent": 1,
      "contradicted": 0,
      "unverifiable": 0
     }
    },
    "stated_reason_trigger": {
     "contradicted_indices": [],
     "contradicted_indices_truncated": false,
     "verdicts": {
      "consistent": 1,
      "contradicted": 0,
      "unverifiable": 0
     }
    },
    "sufficiency_matches_history": {
     "contradicted_indices": [],
     "contradicted_indices_truncated": false,
     "verdicts": {
      "consistent": 1,
      "contradicted": 0,
      "unverifiable": 0
     }
    }
   }
  },
  "reason_counts": {
   "status": "computed",
   "value": {
    "calibration_drift": 0,
    "distribution_shift": 0,
    "insufficient_history": 1,
    "low_confidence": 0,
    "none": 0,
    "unseen_state": 0
   }
  },
  "receipt_count": {
   "status": "computed",
   "value": 1
  }
 },
 "artifacts": {
  "receipts": {
   "bytes": 636,
   "provided": true,
   "receipt_count": 1,
   "schema": "nextness-monitor-v1",
   "sha256": "51e87c7bb2ea0b24c00b9ad8838d3cb0acb3c144b338deb3c022d3072e24182f"
  },
  "report": {
   "bytes": 1428,
   "provided": true,
   "schema": "nextness-predictor-v1",
   "sha256": "2bdc0dbb755c3923374c4306972d35ccc1701c4e1128b9c8db564859d5e404ec"
  }
 },
 "assumptions": [
  "cross-check-same-source: the receipts were derived from the same log and NP1 options as the report (not recorded in either artifact)"
 ],
 "calibration": {
  "ece_bin_width": {
   "status": "computed",
   "value": 0.1
  },
  "holdout_ece_by_model": {
   "status": "computed",
   "value": {
    "empirical_prior": 0.13333333333333328,
    "first_order": 0.2888888888888889,
    "persistence": 0.1176470588235294
   }
  },
  "latest_rolling_calibration_error": {
   "status": "computed",
   "value": 0.288889
  },
  "max_rolling_calibration_error": {
   "status": "computed",
   "value": 0.288889
  },
  "miscalibration_direction": {
   "reason": "field_not_recorded",
   "requires": "signed per-bin confidence-accuracy gaps (both artifacts record absolute-gap ECE only, so over- versus under-confidence cannot be distinguished)",
   "status": "not_computable"
  }
 },
 "config": {
  "contradiction_tolerance": 2e-06,
  "cross_check_tolerance": 1e-06,
  "max_detail_items": 128,
  "max_evaluation_bytes": 65536,
  "max_input_bytes": 1048576,
  "max_series_receipts": 256
 },
 "cross_check": {
  "assumption": "cross-check-same-source: the receipts were derived from the same log and NP1 options as the report (not recorded in either artifact)",
  "ece_match": {
   "status": "computed",
   "value": {
    "covering_receipt_count": 1,
    "results": [
     {
      "model": "first_order",
      "receipt_rolling_calibration_error": 0.288889,
      "report_ece": 0.2888888888888889,
      "verdict": "consistent"
     }
    ],
    "results_truncated": false
   }
  },
  "surprise_nll_match": {
   "status": "computed",
   "value": {
    "covering_receipt_count": 1,
    "results": [
     {
      "model": "first_order",
      "receipt_mean_surprise_bits": 3.132915,
      "report_nll_bits": 3.132914563979398,
      "verdict": "consistent"
     }
    ],
    "results_truncated": false
   }
  }
 },
 "non_claims": [
  "Evaluates recorded artifacts only: observes and scores, never tunes, actuates, selects rules, invokes a model or contacts a service.",
  "No awareness, consciousness, phenomenology or biological-equivalence claim is made or implied by any value in this evaluation.",
  "A not_computable result is a statement about the artifacts' evidence, not about the underlying system."
 ],
 "prediction": {
  "ingestion": {
   "status": "computed",
   "value": {
    "first_order_unseen_source_rate": 0.3333333333333333,
    "holdout_rows": 3,
    "rejection_rate": 0.1875,
    "rows_accepted": 12,
    "rows_read": 16,
    "train_rows": 9
   }
  },
  "metric_difference_significance": {
   "reason": "field_not_recorded",
   "requires": "per-observation outcomes (the report records holdout means only, so no variance estimate or significance statement is possible)",
   "status": "not_computable"
  },
  "models": {
   "empirical_prior": {
    "brier": {
     "status": "computed",
     "value": 0.8309333333333333
    },
    "nll_bits": {
     "status": "computed",
     "value": 3.203213491478937
    },
    "nll_gap_to_uniform_bits": {
     "status": "computed",
     "value": 0.796786508521063
    },
    "top1_accuracy": {
     "status": "computed",
     "value": 0.3333333333333333
    }
   },
   "first_order": {
    "brier": {
     "status": "computed",
     "value": 0.8271012345679013
    },
    "nll_bits": {
     "status": "computed",
     "value": 3.132914563979398
    },
    "nll_gap_to_uniform_bits": {
     "status": "computed",
     "value": 0.8670854360206022
    },
    "top1_accuracy": {
     "status": "computed",
     "value": 0.3333333333333333
    }
   },
   "persistence": {
    "brier": {
     "status": "computed",
     "value": 0.9480968858131488
    },
    "nll_bits": {
     "status": "computed",
     "value": 4.087462841250339
    },
    "nll_gap_to_uniform_bits": {
     "status": "computed",
     "value": -0.0874628412503391
    },
    "top1_accuracy": {
     "status": "computed",
     "value": 0.0
    }
   }
  },
  "proper_score_rankings_agree": {
   "status": "computed",
   "value": true
  },
  "rankings": {
   "status": "computed",
   "value": {
    "by_brier": [
     "first_order",
     "empirical_prior",
     "persistence"
    ],
    "by_nll_bits": [
     "first_order",
     "empirical_prior",
     "persistence"
    ],
    "by_top1_accuracy": [
     "empirical_prior",
     "first_order",
     "persistence"
    ]
   }
  },
  "uniform_nll_bits": {
   "status": "computed",
   "value": 4.0
  }
 },
 "recovery": {
  "abstention_transitions": {
   "reason": "series_too_short",
   "requires": "at least two chronologically witnessed receipts",
   "status": "not_computable"
  },
  "chronology": {
   "status": "computed",
   "value": {
    "first_violation_index": null,
    "witnessed": true
   }
  },
  "confidence_blocks": {
   "reason": "series_too_short",
   "requires": "at least two chronologically witnessed receipts",
   "status": "not_computable"
  },
  "per_observation_recovery": {
   "reason": "field_not_recorded",
   "requires": "per-observation surprise values (receipts record cumulative means only; recovery is resolvable at receipt granularity, never at observation granularity)",
   "status": "not_computable"
  },
  "series_comparability": {
   "status": "computed",
   "value": {
    "config_stable": true,
    "model_stable": true
   }
  },
  "surprise_blocks": {
   "reason": "series_too_short",
   "requires": "at least two chronologically witnessed receipts",
   "status": "not_computable"
  }
 },
 "schema": "nextness-evaluation-v1"
}
'''

# nextness-replay-protocol-v1 (operator-authored shape).
GOLDEN_PROTOCOL = '''{
 "schema": "nextness-replay-protocol-v1",
 "model": "first_order",
 "smoothing": 1.0,
 "holdout_fraction": 0.25,
 "configurations": [
  {
   "label": "monitor-defaults",
   "min_history": 30,
   "window": 50,
   "low_confidence_threshold": 0.3,
   "calibration_error_threshold": 0.2,
   "drift_threshold_bits": 0.15
  },
  {
   "label": "drift-sensitive",
   "min_history": 5,
   "window": 7,
   "low_confidence_threshold": 0.01,
   "calibration_error_threshold": 0.85,
   "drift_threshold_bits": 0.05
  }
 ]
}
'''

# nextness-replay-lab-v1, regenerated from GOLDEN_LOG + GOLDEN_PROTOCOL by NP6.
GOLDEN_LAB = '''{
 "config": {
  "holdout_fraction": 0.25,
  "max_lab_configs": 8,
  "max_line_bytes": 65536,
  "max_replay_steps": 2000,
  "max_rows": 100000,
  "model": "first_order",
  "smoothing": 1.0
 },
 "configurations": [
  {
   "config": {
    "calibration_error_threshold": 0.2,
    "drift_threshold_bits": 0.15,
    "low_confidence_threshold": 0.3,
    "min_history": 30,
    "window": 50
   },
   "label": "monitor-defaults",
   "trajectory": {
    "abstention_onsets": 0,
    "abstention_step_rate": 1.0,
    "completed_abstention_run_lengths_steps": [],
    "final_abstain": true,
    "final_reason": "insufficient_history",
    "first_non_abstain_step": null,
    "reason_step_counts": {
     "calibration_drift": 0,
     "distribution_shift": 0,
     "insufficient_history": 3,
     "low_confidence": 0,
     "none": 0,
     "unseen_state": 0
    },
    "reorientations": 0,
    "run_lengths_truncated": false,
    "step_count": 3,
    "unresolved_trailing_abstention_steps": 3
   }
  },
  {
   "config": {
    "calibration_error_threshold": 0.85,
    "drift_threshold_bits": 0.05,
    "low_confidence_threshold": 0.01,
    "min_history": 5,
    "window": 7
   },
   "label": "drift-sensitive",
   "trajectory": {
    "abstention_onsets": 0,
    "abstention_step_rate": 1.0,
    "completed_abstention_run_lengths_steps": [],
    "final_abstain": true,
    "final_reason": "insufficient_history",
    "first_non_abstain_step": null,
    "reason_step_counts": {
     "calibration_drift": 0,
     "distribution_shift": 0,
     "insufficient_history": 3,
     "low_confidence": 0,
     "none": 0,
     "unseen_state": 0
    },
    "reorientations": 0,
    "run_lengths_truncated": false,
    "step_count": 3,
    "unresolved_trailing_abstention_steps": 3
   }
  }
 ],
 "input": {
  "holdout_steps": 3,
  "protocol_sha256": "0e293d3cd80cb3dc54304907f13738f59c579beddadbfa5c0b534e0337ada349",
  "rejections": {
   "duplicate_generation": 1,
   "invalid_count_value": 0,
   "invalid_generation": 0,
   "invalid_token_counts": 0,
   "malformed_json": 1,
   "missing_generation": 0,
   "missing_token_counts": 0,
   "no_dominant_token": 0,
   "not_object": 0,
   "out_of_order_generation": 0,
   "oversized_line": 0,
   "unknown_token": 1
  },
  "rows_accepted": 12,
  "rows_read": 16,
  "rows_rejected": 3,
  "sequence_sha256": "e8f1f9c06f06de03904a77209a042db541bdf711224e600ce704e6bc9aa01194",
  "train_rows": 9
 },
 "laboratory_observation": true,
 "non_claims": [
  "Laboratory observations over one immutable recording: comparisons are descriptive, no configuration is ranked, selected, recommended or applied.",
  "Abstention is preserved as a first-class outcome, not treated as a defect to eliminate.",
  "No engine parameter is read, searched or written; no awareness, consciousness, phenomenology or biological-equivalence claim is made or implied."
 ],
 "schema": "nextness-replay-lab-v1"
}
'''


def _write(tmp_path: pathlib.Path, name: str, content: str) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="")
    return path


def _golden_receipt_from(log: pathlib.Path) -> dict:
    observations, reference, recent = monitor.observations_from_log(log, "first_order")
    return monitor.build_receipt(
        model="first_order",
        observations=observations,
        reference_counts=reference,
        recent_counts=recent,
        config=monitor.MonitorConfig(),
    )


# ---------------------------------------------------------------------------
# 1. Golden byte-stability (each emitter pinned, repeat-emission checked)
# ---------------------------------------------------------------------------


def test_golden_report_byte_stable(tmp_path) -> None:
    log = _write(tmp_path, "log.jsonl", GOLDEN_LOG)
    emitted = {predictor.serialize_report(predictor.build_report(log)) for _ in range(2)}
    assert emitted == {GOLDEN_REPORT}


def test_golden_receipt_byte_stable(tmp_path) -> None:
    log = _write(tmp_path, "log.jsonl", GOLDEN_LOG)
    emitted = {monitor.serialize_receipt(_golden_receipt_from(log)) for _ in range(2)}
    assert emitted == {GOLDEN_RECEIPT}


def test_golden_evaluation_byte_stable(tmp_path) -> None:
    # Inputs are the golden LITERALS, not fresh emitter output, so this
    # pin isolates NP5 drift from NP1/NP2 drift (the sha256 provenance
    # inside the evaluation depends on the input bytes).
    report = _write(tmp_path, "report.json", GOLDEN_REPORT)
    receipts = _write(tmp_path, "receipt.json", GOLDEN_RECEIPT)
    emitted = {
        evaluator.serialize_evaluation(
            evaluator.build_evaluation(report_path=report, receipts_path=receipts)
        )
        for _ in range(2)
    }
    assert emitted == {GOLDEN_EVALUATION}


def test_golden_lab_report_byte_stable(tmp_path) -> None:
    log = _write(tmp_path, "log.jsonl", GOLDEN_LOG)
    protocol = _write(tmp_path, "protocol.json", GOLDEN_PROTOCOL)
    emitted = {
        lab.serialize_lab_report(lab.build_lab_report(log, protocol)) for _ in range(2)
    }
    assert emitted == {GOLDEN_LAB}


# ---------------------------------------------------------------------------
# 2. Vocabulary and constant freezes (fixed contracts between packages)
# ---------------------------------------------------------------------------


def test_schema_identifiers_frozen() -> None:
    assert predictor.REPORT_SCHEMA == "nextness-predictor-v1"
    assert monitor.RECEIPT_SCHEMA == "nextness-monitor-v1"
    assert evaluator.EVALUATION_SCHEMA == "nextness-evaluation-v1"
    assert lab.LAB_SCHEMA == "nextness-replay-lab-v1"
    assert lab.PROTOCOL_SCHEMA == "nextness-replay-protocol-v1"


def test_token_vocabulary_frozen_including_order() -> None:
    # Order is load-bearing: dominant-token ties break by TOKEN_NAMES
    # position in NP1 and NP2 alike.
    assert TOKEN_NAMES == (
        "void_static", "compute_static", "void_birth", "compute_aging",
        "compute_decay", "structural_growth", "structural_decay",
        "energy_pulse", "sensor_alert", "metta_warmth", "karuna_relief",
        "mudita_resonance", "magnon_lighthouse", "acoustic_stress",
        "phase_boundary", "unclassified",
    )


def test_abstention_vocabulary_frozen_in_precedence_order() -> None:
    # Order is load-bearing: it IS the documented decision precedence.
    assert monitor.ABSTAIN_REASONS == (
        "insufficient_history", "unseen_state", "low_confidence",
        "calibration_drift", "distribution_shift", "none",
    )
    assert monitor.MODEL_ALLOWLIST == ("empirical_prior", "persistence", "first_order")
    assert monitor.OBSERVATION_FIELDS == frozenset(
        {"confidence", "hit", "p_actual", "prev_seen"}
    )


def test_rejection_and_result_vocabularies_frozen() -> None:
    assert predictor.REJECT_REASONS == (
        "oversized_line", "malformed_json", "not_object", "missing_generation",
        "invalid_generation", "out_of_order_generation", "duplicate_generation",
        "missing_token_counts", "invalid_token_counts", "unknown_token",
        "invalid_count_value", "no_dominant_token",
    )
    assert evaluator.NOT_COMPUTABLE_REASONS == (
        "artifact_absent", "field_not_recorded", "series_too_short",
        "order_not_witnessed", "no_covering_receipt",
        "model_not_stable", "config_not_stable",
    )
    assert evaluator.VERDICTS == ("consistent", "contradicted", "unverifiable")
    assert evaluator.CONSISTENCY_CHECKS == (
        "abstain_flag_matches_reason", "sufficiency_matches_history",
        "higher_precedence_excluded", "stated_reason_trigger",
    )


def test_numeric_bounds_and_mirrors_frozen() -> None:
    assert predictor.MAX_REPORT_BYTES == 64 * 1024
    assert monitor.MAX_RECEIPT_BYTES == 64 * 1024
    assert evaluator.MAX_EVALUATION_BYTES == 64 * 1024
    assert lab.MAX_LAB_REPORT_BYTES == 64 * 1024
    assert predictor.ECE_BINS == 10
    assert predictor.MAX_ROWS_DEFAULT == 100_000
    assert predictor.MAX_ROWS_CEILING == 1_000_000
    assert predictor.MAX_LINE_BYTES_DEFAULT == 65_536
    assert predictor.SMOOTHING_MAX == 1_000.0
    assert (predictor.HOLDOUT_FRACTION_MIN, predictor.HOLDOUT_FRACTION_MAX) == (0.05, 0.5)
    assert lab.MAX_LAB_CONFIGS == 8
    assert lab.MAX_REPLAY_STEPS == 2_000
    assert evaluator.MAX_SERIES_RECEIPTS == 256
    assert evaluator.MAX_INPUT_BYTES == 1_048_576
    assert evaluator.MAX_DETAIL_ITEMS == 128
    assert lab.MAX_PROTOCOL_BYTES == 64 * 1024
    assert lab.MAX_DETAIL_ITEMS == 128
    assert lab.MAX_LABEL_CHARS == 64
    # The evaluator mirrors the monitor's private surprise cap: this is
    # the lock that keeps the "kept manually in sync" comment true.
    assert evaluator.SURPRISE_BITS_MAX == monitor._MAX_SURPRISE_BITS == 1_000.0
    assert evaluator.NLL_BITS_MAX == -math.log2(1e-300)
    # Tolerance derivation depends on the monitor's 6-dp rounding.
    assert monitor._ROUND == 6
    assert evaluator.CONTRADICTION_TOLERANCE == 2e-6
    assert evaluator.CROSS_CHECK_TOLERANCE == 1e-6


def test_monitor_default_configuration_frozen() -> None:
    cfg = monitor.MonitorConfig()
    assert (cfg.min_history, cfg.window) == (30, 50)
    assert (
        cfg.low_confidence_threshold,
        cfg.calibration_error_threshold,
        cfg.drift_threshold_bits,
    ) == (0.3, 0.2, 0.15)


# ---------------------------------------------------------------------------
# 3. Emitter <-> validator structure locks (live, beyond the goldens)
# ---------------------------------------------------------------------------


def test_live_report_key_sets_match_evaluator_expectations(tmp_path) -> None:
    log = _write(tmp_path, "log.jsonl", GOLDEN_LOG)
    report = predictor.build_report(log)
    assert set(report) == set(evaluator._REPORT_KEYS)
    assert set(report["config"]) == set(evaluator._REPORT_CONFIG_KEYS)
    assert set(report["input"]) == set(evaluator._REPORT_INPUT_KEYS)
    assert set(report["evaluation"]) == set(evaluator._REPORT_EVALUATION_KEYS)
    for metrics in report["evaluation"]["models"].values():
        assert set(metrics) == set(evaluator._MODEL_METRIC_KEYS)
    evaluator.validate_report(report)  # and the whole artifact validates


def test_live_receipt_key_sets_match_evaluator_expectations(tmp_path) -> None:
    log = _write(tmp_path, "log.jsonl", GOLDEN_LOG)
    receipt = _golden_receipt_from(log)
    assert set(receipt) == set(evaluator._RECEIPT_KEYS)
    assert set(receipt["config"]) == set(evaluator._RECEIPT_CONFIG_KEYS)
    evaluator.validate_receipt(receipt, "receipt")


# ---------------------------------------------------------------------------
# 4. Compatibility corpus: goldens keep validating; mutations fail closed
# ---------------------------------------------------------------------------


def test_golden_corpus_keeps_validating(tmp_path) -> None:
    evaluator.validate_report(json.loads(GOLDEN_REPORT))
    evaluator.validate_receipt(json.loads(GOLDEN_RECEIPT), "receipt")
    protocol = _write(tmp_path, "protocol.json", GOLDEN_PROTOCOL)
    loaded = lab.load_protocol(protocol)
    assert [label for label, _ in loaded["configs"]] == [
        "monitor-defaults", "drift-sensitive",
    ]
    assert json.loads(GOLDEN_EVALUATION)["schema"] == evaluator.EVALUATION_SCHEMA
    assert json.loads(GOLDEN_LAB)["schema"] == lab.LAB_SCHEMA


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.__setitem__("schema", "nextness-predictor-v2"),
        lambda a: a.__setitem__("future_field", 1),
        lambda a: a.__delitem__("evaluation"),
        lambda a: a["config"].__setitem__("ece_bins", 12),
        lambda a: a["input"].__setitem__("rows_read", True),
        lambda a: a["evaluation"]["models"].__setitem__("second_order", {}),
    ],
    ids=["schema-bump", "extra-key", "missing-section", "ece-bins-variant",
         "bool-count", "unknown-model"],
)
def test_mutated_golden_report_rejected_fail_closed(mutate) -> None:
    artifact = json.loads(GOLDEN_REPORT)
    mutate(artifact)
    with pytest.raises(evaluator.EvaluatorInputError):
        evaluator.validate_report(artifact)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.__setitem__("schema", "nextness-monitor-v2"),
        lambda a: a.__setitem__("internal_monologue", "..."),
        lambda a: a.__delitem__("abstain_reason"),
        lambda a: a.__setitem__("abstain_reason", "vibes"),
        lambda a: a.__setitem__("abstain", 1),
        lambda a: a["config"].__setitem__("window", 4),
    ],
    ids=["schema-bump", "extra-key", "missing-reason", "unknown-reason",
         "int-flag", "window-below-bound"],
)
def test_mutated_golden_receipt_rejected_fail_closed(mutate) -> None:
    artifact = json.loads(GOLDEN_RECEIPT)
    mutate(artifact)
    with pytest.raises(evaluator.EvaluatorInputError):
        evaluator.validate_receipt(artifact, "receipt")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.__setitem__("schema", "nextness-replay-protocol-v2"),
        lambda a: a.__setitem__("optimizer", "none"),
        lambda a: a["configurations"][0].__setitem__("min_history", 4),
        lambda a: a.__setitem__("model", "second_order"),
    ],
    ids=["schema-bump", "extra-key", "history-below-bound", "unknown-model"],
)
def test_mutated_golden_protocol_rejected_fail_closed(tmp_path, mutate) -> None:
    artifact = json.loads(GOLDEN_PROTOCOL)
    mutate(artifact)
    path = _write(tmp_path, "protocol.json", json.dumps(artifact))
    with pytest.raises(lab.LabInputError):
        lab.load_protocol(path)

# ---------------------------------------------------------------------------
# 5. Correction-semantics locks (Jack HOLD delta, 2026-07-15): the
# corrected behaviors must not silently regress to their pre-correction
# forms.
# ---------------------------------------------------------------------------


def _two_receipt_series(second_overrides: dict) -> list[dict]:
    base = json.loads(GOLDEN_RECEIPT)
    first = dict(base)
    second = dict(base)
    second["observation_count"] = base["observation_count"] + 10
    for key, value in second_overrides.items():
        if key == "config":
            second["config"] = {**base["config"], **value}
        else:
            second[key] = value
    return [evaluator.validate_receipt(first, "r0"), evaluator.validate_receipt(second, "r1")]


def test_mixed_model_recovery_cannot_silently_compute() -> None:
    other = next(m for m in monitor.MODEL_ALLOWLIST if m != json.loads(GOLDEN_RECEIPT)["model"])
    ev = evaluator.evaluate(receipts=_two_receipt_series({"model": other}))
    for key in ("surprise_blocks", "confidence_blocks", "abstention_transitions"):
        assert ev["recovery"][key]["status"] == "not_computable"
        assert ev["recovery"][key]["reason"] == "model_not_stable"


def test_changed_config_transitions_cannot_silently_compute() -> None:
    ev = evaluator.evaluate(
        receipts=_two_receipt_series({"config": {"min_history": 31}})
    )
    assert ev["recovery"]["abstention_transitions"]["status"] == "not_computable"
    assert ev["recovery"]["abstention_transitions"]["reason"] == "config_not_stable"
    assert ev["recovery"]["surprise_blocks"]["status"] == "computed"


def test_oversized_holdout_never_allocates_observations(tmp_path, monkeypatch) -> None:
    lines = [
        json.dumps({"generation": i, "token_counts": {"void_static": 1}})
        for i in range(2 * lab.MAX_REPLAY_STEPS + 2)
    ]
    log = _write(tmp_path, "big.jsonl", chr(10).join(lines) + chr(10))
    protocol_obj = json.loads(GOLDEN_PROTOCOL)
    protocol_obj["holdout_fraction"] = 0.5
    protocol = _write(tmp_path, "protocol.json", json.dumps(protocol_obj))
    invocations: list[int] = []
    real = lab.replay_observations
    monkeypatch.setattr(
        lab, "replay_observations", lambda *a, **k: invocations.append(1) or real(*a, **k)
    )
    with pytest.raises(lab.LabInputError, match="replay bound"):
        lab.build_lab_report(log, protocol)
    assert invocations == []


def test_hard_link_output_alias_refused_by_the_stack(tmp_path) -> None:
    import os

    log = _write(tmp_path, "log.jsonl", GOLDEN_LOG)
    protocol = _write(tmp_path, "protocol.json", GOLDEN_PROTOCOL)
    alias = tmp_path / "alias.json"
    os.link(log, alias)
    before = log.read_bytes()
    with pytest.raises(Exception, match="identity|overwrite"):
        lab.validate_output_path(alias, log, protocol)
    assert log.read_bytes() == before


# ---------------------------------------------------------------------------
# Producer -> consumer seam guard: observer rows must satisfy the strict
# metrics input domain (§9.4), live, end to end. Two deterministic
# synthetic snapshots run through the REAL observer process_snapshot,
# the emitted log is proven row-by-row against the metrics consumer
# contract, then fed unmodified into the merged strict
# compute_run_metrics with strict-JSON and byte-determinism proofs.
# The mutation matrix already committed in the metrics suite is NOT
# duplicated here.
# ---------------------------------------------------------------------------


def _reject_constant(name: str):
    raise AssertionError(f"non-standard JSON constant {name} in output")


def _make_guard_snapshot(np, path, generation: int, stride: int):
    from scripts.nextness_observer import MEMORY_CHANNEL_LAYOUT, STATE_COMPUTE

    state = np.zeros((16, 16, 16), dtype=np.uint8)
    state[::stride, ::stride, ::stride] = STATE_COMPUTE
    memory = np.zeros((8, 16, 16, 16), dtype=np.float32)
    memory[MEMORY_CHANNEL_LAYOUT["compute_age"]].fill(15.0)
    np.savez(
        str(path),
        lattice=state, memory_grid=memory,
        generation=np.array(generation), best_fitness=np.array(0.5),
    )
    return path


def test_observer_rows_satisfy_strict_metrics_consumer_contract(tmp_path) -> None:
    """Live producer->consumer guard (observer -> metrics seam)."""
    np = pytest.importorskip("numpy")
    from scripts.nextness_metrics import compute_run_metrics
    from scripts.nextness_observer import ObserverConfig, process_snapshot

    snap_a = _make_guard_snapshot(np, tmp_path / "v070_gen100.npz", 100, 4)
    snap_b = _make_guard_snapshot(np, tmp_path / "v070_gen101.npz", 101, 2)
    log_dir = tmp_path / "log"
    cfg = ObserverConfig(log_directory=str(log_dir),
                         uniform_grid_stride=4, budget_seconds=30.0)
    process_snapshot(snap_a, cfg, medusa_is_live=False)
    process_snapshot(snap_b, cfg, medusa_is_live=False)
    log_file = log_dir / "nextness_runs.jsonl"
    assert log_file.is_file()

    # Row-by-row consumer-contract proof: exact built-in containers,
    # non-boolean non-negative integer counts, unit fields real, finite
    # and within [0, 1].
    lines = [l for l in log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    for line in lines:
        row = json.loads(line, parse_constant=_reject_constant)
        assert type(row) is dict
        counts = row["token_counts"]
        assert type(counts) is dict
        for key, count in counts.items():
            assert type(key) is str
            assert not isinstance(count, bool)
            assert isinstance(count, int) and count >= 0
            assert math.isfinite(float(count))
        for field in ("void_compute_balance", "boundary_rate", "entropy_normalized"):
            assert field in row, field
            value = row[field]
            assert not isinstance(value, bool)
            assert isinstance(value, (int, float))
            assert math.isfinite(value) and 0.0 <= value <= 1.0, (field, value)

    # The unmodified observer log feeds the merged strict consumer.
    out_a = log_dir / "derived_a.jsonl"
    compute_run_metrics(log_file, out_a)
    derived = [l for l in out_a.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert derived  # one pair row + one aggregate row expected
    for line in derived:
        json.loads(line, parse_constant=_reject_constant)  # strict JSON

    # Deterministic byte-identical output on a second sibling destination.
    out_b = log_dir / "derived_b.jsonl"
    compute_run_metrics(log_file, out_b)
    assert out_a.read_bytes() == out_b.read_bytes()


def test_metrics_historical_absent_unit_fields_compatibility(tmp_path) -> None:
    """Compact historical-compatibility fixture: rows without unit
    fields still succeed under the strict domain (the authorized
    absent -> 0.0 policy), with strict-JSON output."""
    from scripts.nextness_metrics import compute_run_metrics

    log = tmp_path / "historical.jsonl"
    log.write_text(
        json.dumps({"generation": 1, "snapshot_file": "s1.npz",
                    "token_counts": {"void_static": 3}}, sort_keys=True) + "\n" +
        json.dumps({"generation": 2, "snapshot_file": "s2.npz",
                    "token_counts": {"compute_static": 3}}, sort_keys=True) + "\n",
        encoding="utf-8")
    out = tmp_path / "derived.jsonl"
    aggregate = compute_run_metrics(log, out)
    assert aggregate["n_snapshots"] == 2
    for line in out.read_text(encoding="utf-8").splitlines():
        if line.strip():
            json.loads(line, parse_constant=_reject_constant)
