"""Tests for scripts/nextness_metrics.py — Phase 19 PR #3.

Locks down each metric formula plus the orchestrator's determinism
contracts (no fresh ``generated_at``, deterministic sort across input
orderings, byte-identical idempotent re-run).

Per the design doc (PHASE_19_PR3_METRICS_PIPELINE.md §6): unit tests
per metric with reference values, integration tests for the orchestrator,
and a self-contained "golden" test pinning the arithmetic against
silent regressions.
"""
from __future__ import annotations

import json
import math
import os
import pathlib

import pytest

from scripts.nextness_observer import TOKEN_NAMES, WriteOutsideLogDirError
from scripts.nextness_metrics import (
    boundary_cv,
    boundary_persistence_aggregate_clamped,
    boundary_persistence_pairwise,
    cci,
    compute_run_metrics,
    js_divergence,
    kl_divergence,
    main,
    smoothed_distribution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    generation: int,
    snapshot_file: str,
    ts: str = "2026-05-18T00:00:00Z",
    token_counts: dict[str, int] | None = None,
    void_compute_balance: float = 0.5,
    boundary_rate: float = 0.3,
    entropy_normalized: float = 0.4,
    shannon_entropy_bits: float = 1.6,
    vocabulary_occupancy: float = 0.125,
) -> dict:
    """Build a minimally-valid log entry for tests."""
    return {
        "generation": generation,
        "snapshot_file": snapshot_file,
        "ts": ts,
        "token_counts": token_counts or {"karuna_relief": 100, "phase_boundary": 50},
        "void_compute_balance": void_compute_balance,
        "boundary_rate": boundary_rate,
        "entropy_normalized": entropy_normalized,
        "shannon_entropy_bits": shannon_entropy_bits,
        "vocabulary_occupancy": vocabulary_occupancy,
        "lattice_shape": [256, 256, 256],
    }


def _write_log(path: pathlib.Path, entries: list[dict]) -> None:
    """Write a list of log entries to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# smoothed_distribution — Jack's canonical-ordering spec (§4.1)
# ---------------------------------------------------------------------------


def test_smoothed_distribution_sums_to_one():
    """Result always sums to 1.0 (within float precision)."""
    p = smoothed_distribution({"karuna_relief": 100, "phase_boundary": 50})
    assert sum(p) == pytest.approx(1.0)


def test_smoothed_distribution_length_matches_vocabulary():
    """Result has exactly len(TOKEN_NAMES) entries, one per canonical token."""
    p = smoothed_distribution({"karuna_relief": 100})
    assert len(p) == len(TOKEN_NAMES)


def test_smoothed_distribution_canonical_order_independent_of_input_order():
    """Two semantically equivalent count dicts produce identical vectors."""
    # Python dicts preserve insertion order; we want the result to be
    # independent of that order. Build two dicts with different insertion
    # orders but the same content.
    counts_a = {"karuna_relief": 100, "phase_boundary": 50, "void_static": 10}
    counts_b = {"void_static": 10, "phase_boundary": 50, "karuna_relief": 100}
    assert smoothed_distribution(counts_a) == smoothed_distribution(counts_b)


def test_smoothed_distribution_empty_input_uniform_with_zero_smoothing():
    """Empty + zero smoothing → uniform (defensive against div-by-zero)."""
    p = smoothed_distribution({}, smoothing=0.0)
    expected = 1.0 / len(TOKEN_NAMES)
    assert all(v == pytest.approx(expected) for v in p)


def test_smoothed_distribution_negative_smoothing_raises():
    """Smoothing must be non-negative."""
    with pytest.raises(ValueError):
        smoothed_distribution({"a": 1}, smoothing=-0.1)


# ---------------------------------------------------------------------------
# KL divergence (§4.1)
# ---------------------------------------------------------------------------


def test_kl_divergence_identical_distributions_zero():
    """D_KL(P || P) = 0 by definition."""
    counts = {"karuna_relief": 100, "phase_boundary": 50}
    assert kl_divergence(counts, counts) == pytest.approx(0.0, abs=1e-9)


def test_kl_divergence_asymmetric():
    """D_KL(P || Q) != D_KL(Q || P) in general (asymmetry).

    Care needed in test fixture: mirror-image distributions like
    ({a:100, b:1}, {a:1, b:100}) give *symmetric* KL because the two
    fall on the same orbit under the token-label swap. Non-mirror
    fixtures expose the asymmetry properly.
    """
    p = {"karuna_relief": 100, "phase_boundary": 10}   # 10:1 ratio
    q = {"karuna_relief": 50, "phase_boundary": 50}    # uniform between the two
    forward = kl_divergence(p, q)
    reverse = kl_divergence(q, p)
    assert forward != reverse
    # Both should be positive (the distributions are different)
    assert forward > 0.01
    assert reverse > 0.01


def test_kl_divergence_with_smoothing_finite_for_disjoint_supports():
    """Smoothing prevents infinity when a token fires in one but not the other."""
    p = {"karuna_relief": 100}        # only this token
    q = {"phase_boundary": 100}       # only this OTHER token
    val = kl_divergence(p, q, smoothing=1e-6)
    assert math.isfinite(val)
    assert val > 0.0


# ---------------------------------------------------------------------------
# Jensen-Shannon divergence (§4.2)
# ---------------------------------------------------------------------------


def test_js_divergence_identical_distributions_zero():
    """D_JS(P, P) = 0."""
    counts = {"karuna_relief": 100, "phase_boundary": 50}
    assert js_divergence(counts, counts) == pytest.approx(0.0, abs=1e-9)


def test_js_divergence_symmetric():
    """D_JS(P, Q) == D_JS(Q, P) by construction."""
    p = {"karuna_relief": 100, "phase_boundary": 1}
    q = {"karuna_relief": 1, "phase_boundary": 100}
    assert js_divergence(p, q) == pytest.approx(js_divergence(q, p))


def test_js_divergence_bounded_in_zero_one():
    """D_JS in bits is bounded [0, 1] for any pair of distributions."""
    # Maximum case: disjoint supports
    p = {"karuna_relief": 1_000_000}
    q = {"phase_boundary": 1_000_000}
    val = js_divergence(p, q, smoothing=1e-9)
    assert 0.0 <= val <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# Boundary persistence pairwise (§4.3)
# ---------------------------------------------------------------------------


def test_boundary_persistence_pairwise_identical_rates_one():
    """Identical rates → persistence = 1.0."""
    assert boundary_persistence_pairwise(0.42, 0.42) == pytest.approx(1.0)
    assert boundary_persistence_pairwise(0.0, 0.0) == pytest.approx(1.0)


def test_boundary_persistence_pairwise_max_drop_zero():
    """Rate dropping from r to 0 → persistence = 0 (full inversion)."""
    assert boundary_persistence_pairwise(0.42, 0.0) == pytest.approx(0.0)
    assert boundary_persistence_pairwise(0.0, 0.42) == pytest.approx(0.0)


def test_boundary_persistence_pairwise_bounded_in_zero_one():
    """Always in [0, 1] regardless of inputs."""
    for r_prev, r_curr in [(0.1, 0.2), (0.5, 0.1), (0.9, 0.9), (0.0, 0.001)]:
        val = boundary_persistence_pairwise(r_prev, r_curr)
        assert 0.0 <= val <= 1.0, f"out of range for ({r_prev}, {r_curr}): {val}"


def test_boundary_persistence_pairwise_negative_rate_raises():
    """Negative rates are an input contract violation."""
    with pytest.raises(ValueError):
        boundary_persistence_pairwise(-0.1, 0.2)
    with pytest.raises(ValueError):
        boundary_persistence_pairwise(0.1, -0.2)


# ---------------------------------------------------------------------------
# Boundary CV + clamped aggregate persistence (§4.3)
# ---------------------------------------------------------------------------


def test_boundary_cv_constant_series_zero():
    """Constant series → CV = 0."""
    assert boundary_cv([0.42, 0.42, 0.42, 0.42]) == pytest.approx(0.0, abs=1e-9)


def test_boundary_cv_high_variance_exceeds_one():
    """The original-formula failure case (rates [0, 0.5, 0, 0.5, 0]) gives CV >= 1."""
    # Population stats: mean = 0.2, var = 0.06, std ≈ 0.2449
    # CV ≈ 0.2449 / 0.201 ≈ 1.218 — exceeds 1, which is exactly why the
    # original 1-CV formula went negative (issue caught by Jack's audit).
    cv = boundary_cv([0.0, 0.5, 0.0, 0.5, 0.0])
    assert cv > 1.0


def test_boundary_cv_empty_or_single_element_zero():
    """No variance defined → CV = 0 (sane default for degenerate input)."""
    assert boundary_cv([]) == 0.0
    assert boundary_cv([0.42]) == 0.0


def test_boundary_persistence_aggregate_clamped_corners():
    """Constant → 1.0; high-variance → 0.0 (clamp engages)."""
    # Constant series: CV=0, score=1.0
    assert boundary_persistence_aggregate_clamped(
        [0.42, 0.42, 0.42]
    ) == pytest.approx(1.0)
    # High variance: CV>1, clamp to 0
    assert boundary_persistence_aggregate_clamped(
        [0.0, 0.5, 0.0, 0.5, 0.0]
    ) == pytest.approx(0.0)


def test_boundary_persistence_aggregate_clamped_intermediate_matches_one_minus_cv():
    """For 0 < CV < 1, clamped score equals 1 - CV exactly (no clamp)."""
    # Pick rates with moderate variance: mean=0.4, low std
    rates = [0.38, 0.42, 0.40, 0.40, 0.40]
    expected = 1.0 - boundary_cv(rates)
    assert 0.0 < expected < 1.0  # genuinely in the un-clamped regime
    assert boundary_persistence_aggregate_clamped(rates) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# CCI (§4.4)
# ---------------------------------------------------------------------------


def test_cci_corners():
    """CCI = 0 iff any factor is 0; CCI = 1 iff all factors are 1."""
    assert cci(0.0, 0.5, 0.5) == 0.0  # balance zero
    assert cci(0.5, 0.0, 0.5) == 0.0  # boundary zero
    assert cci(0.5, 0.5, 1.0) == 0.0  # H_norm = 1 → (1-H) = 0
    assert cci(1.0, 1.0, 0.0) == pytest.approx(1.0)  # all max


def test_cci_gen_1_6m_reference():
    """Gen-1.6M reference values (design doc §4.4)."""
    # B_VC = 0.988, R_boundary = 0.422, H_norm = 0.246
    # CCI = 0.988 * 0.422 * (1 - 0.246) = 0.988 * 0.422 * 0.754 ≈ 0.3144
    val = cci(0.988, 0.422, 0.246)
    assert 0.31 < val < 0.32


def test_cci_monotonicity():
    """CCI increases with balance and boundary; decreases with entropy_norm."""
    base = cci(0.5, 0.5, 0.5)
    assert cci(0.6, 0.5, 0.5) > base   # higher balance
    assert cci(0.5, 0.6, 0.5) > base   # higher boundary
    assert cci(0.5, 0.5, 0.4) > base   # LOWER entropy → higher CCI


# ---------------------------------------------------------------------------
# compute_run_metrics — integration + determinism contracts (§4.5, §10 Q4)
# ---------------------------------------------------------------------------


def test_compute_run_metrics_two_snapshots(tmp_path):
    """Minimal 2-snapshot run → one pair row + one aggregate row."""
    log_path = tmp_path / "nextness_runs.jsonl"
    out_path = tmp_path / "nextness_run_metrics.jsonl"
    _write_log(log_path, [
        _make_entry(generation=100, snapshot_file="v070_gen100.npz",
                    boundary_rate=0.40),
        _make_entry(generation=101, snapshot_file="v070_gen101.npz",
                    boundary_rate=0.42),
    ])

    agg = compute_run_metrics(log_path, out_path)

    lines = out_path.read_text().splitlines()
    assert len(lines) == 2  # 1 pair + 1 aggregate

    pair = json.loads(lines[0])
    assert pair["summary_type"] == "pair"
    assert pair["prev_generation"] == 100
    assert pair["curr_generation"] == 101
    assert "js_divergence_bits" in pair
    assert "kl_divergence_bits" in pair
    assert "boundary_persistence_pairwise" in pair

    aggr = json.loads(lines[1])
    assert aggr["summary_type"] == "run_aggregate"
    assert aggr["n_snapshots"] == 2
    assert aggr["n_pairs"] == 1
    assert aggr == agg


def test_compute_run_metrics_identical_snapshots_zero_drift(tmp_path):
    """Two identical entries → JS=0, boundary persistence=1, CCIs equal."""
    log_path = tmp_path / "log.jsonl"
    out_path = tmp_path / "out.jsonl"
    entry_a = _make_entry(generation=100, snapshot_file="a.npz", boundary_rate=0.40)
    entry_b = _make_entry(generation=101, snapshot_file="b.npz", boundary_rate=0.40)
    # Identical token_counts means identical distributions
    _write_log(log_path, [entry_a, entry_b])

    compute_run_metrics(log_path, out_path)
    lines = out_path.read_text().splitlines()
    pair = json.loads(lines[0])

    assert pair["js_divergence_bits"] == pytest.approx(0.0, abs=1e-9)
    assert pair["boundary_persistence_pairwise"] == pytest.approx(1.0)
    assert pair["cci_prev"] == pytest.approx(pair["cci_curr"])


def test_compute_run_metrics_idempotent_byte_identical(tmp_path):
    """Re-running on the same input produces byte-identical output.

    This is the canonical determinism contract — no fresh generated_at,
    deterministic sort, sort_keys=True in JSON serialization.
    """
    log_path = tmp_path / "log.jsonl"
    out_path_a = tmp_path / "out_a.jsonl"
    out_path_b = tmp_path / "out_b.jsonl"
    _write_log(log_path, [
        _make_entry(generation=10, snapshot_file="a.npz", boundary_rate=0.40),
        _make_entry(generation=11, snapshot_file="b.npz", boundary_rate=0.41),
        _make_entry(generation=12, snapshot_file="c.npz", boundary_rate=0.39),
    ])

    compute_run_metrics(log_path, out_path_a)
    compute_run_metrics(log_path, out_path_b)
    assert out_path_a.read_bytes() == out_path_b.read_bytes()


def test_compute_run_metrics_no_generated_at_field(tmp_path):
    """Output must NOT contain any 'generated_at' field anywhere.

    Required for byte-identical re-run. Locks in §10 Q4 of the design doc.
    """
    log_path = tmp_path / "log.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])
    compute_run_metrics(log_path, out_path)
    content = out_path.read_text()
    assert "generated_at" not in content


def test_compute_run_metrics_deterministic_sort_across_input_orderings(tmp_path):
    """Same snapshots in three different write-orders → byte-identical output.

    Locks in the sort-key contract: output depends only on the data, not
    on how the input happened to be ordered in the JSONL file.
    """
    entries = [
        _make_entry(generation=10, snapshot_file="a.npz", boundary_rate=0.40),
        _make_entry(generation=11, snapshot_file="b.npz", boundary_rate=0.41),
        _make_entry(generation=12, snapshot_file="c.npz", boundary_rate=0.39),
        _make_entry(generation=13, snapshot_file="d.npz", boundary_rate=0.43),
    ]

    log_asc = tmp_path / "log_asc.jsonl"
    log_desc = tmp_path / "log_desc.jsonl"
    log_shuffled = tmp_path / "log_shuffled.jsonl"
    out_asc = tmp_path / "out_asc.jsonl"
    out_desc = tmp_path / "out_desc.jsonl"
    out_shuffled = tmp_path / "out_shuffled.jsonl"

    _write_log(log_asc, entries)
    _write_log(log_desc, list(reversed(entries)))
    _write_log(log_shuffled, [entries[2], entries[0], entries[3], entries[1]])

    compute_run_metrics(log_asc, out_asc)
    compute_run_metrics(log_desc, out_desc)
    compute_run_metrics(log_shuffled, out_shuffled)

    assert out_asc.read_bytes() == out_desc.read_bytes()
    assert out_asc.read_bytes() == out_shuffled.read_bytes()


def test_compute_run_metrics_one_snapshot_only(tmp_path):
    """Single snapshot → no pairs, single aggregate row, no crash."""
    log_path = tmp_path / "log.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_log(log_path, [
        _make_entry(generation=42, snapshot_file="lonely.npz"),
    ])

    agg = compute_run_metrics(log_path, out_path)
    lines = out_path.read_text().splitlines()
    assert len(lines) == 1  # only the aggregate; no pair rows
    aggr_line = json.loads(lines[0])
    assert aggr_line["summary_type"] == "run_aggregate"
    assert aggr_line["n_snapshots"] == 1
    assert aggr_line["n_pairs"] == 0
    assert agg == aggr_line


def test_compute_run_metrics_missing_log_raises(tmp_path):
    """FileNotFoundError surfaces cleanly for missing input."""
    with pytest.raises(FileNotFoundError):
        compute_run_metrics(tmp_path / "does_not_exist.jsonl", tmp_path / "out.jsonl")


def test_compute_run_metrics_malformed_jsonl_raises(tmp_path):
    """Malformed JSONL surfaces as ValueError with line context."""
    log_path = tmp_path / "log.jsonl"
    log_path.write_text('{"generation": 1}\nthis is not json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="malformed JSONL"):
        compute_run_metrics(log_path, tmp_path / "out.jsonl")


# ---------------------------------------------------------------------------
# Golden self-contained: known input → analytically-computed expected output
# ---------------------------------------------------------------------------


def test_compute_run_metrics_golden_three_snapshots(tmp_path):
    """Three known snapshots → assert key aggregate values against hand-computed expectations.

    Inputs constructed so the expected outputs can be computed by hand
    and locked in. Acts as the regression-fence test for the orchestrator
    arithmetic (design doc §6 "Golden-file test", self-contained variant).
    """
    log_path = tmp_path / "log.jsonl"
    out_path = tmp_path / "out.jsonl"
    # Three identical distributions → JS=0 between adjacent pairs, but
    # varying boundary_rate so we can verify boundary metrics
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz",
                    boundary_rate=0.40, void_compute_balance=0.99,
                    entropy_normalized=0.25),
        _make_entry(generation=2, snapshot_file="b.npz",
                    boundary_rate=0.42, void_compute_balance=0.99,
                    entropy_normalized=0.25),
        _make_entry(generation=3, snapshot_file="c.npz",
                    boundary_rate=0.44, void_compute_balance=0.99,
                    entropy_normalized=0.25),
    ])

    agg = compute_run_metrics(log_path, out_path)

    # Identical token_counts (default in _make_entry) → all pair JS = 0
    assert agg["mean_js_divergence_bits"] == pytest.approx(0.0, abs=1e-9)

    # CCI for each entry: 0.99 * boundary_rate * (1 - 0.25) = 0.7425 * boundary
    expected_ccis = [0.7425 * 0.40, 0.7425 * 0.42, 0.7425 * 0.44]
    expected_mean_cci = sum(expected_ccis) / 3
    assert agg["mean_cci"] == pytest.approx(expected_mean_cci)
    assert agg["min_cci"] == pytest.approx(expected_ccis[0])
    assert agg["max_cci"] == pytest.approx(expected_ccis[2])
    assert agg["argmin_cci_snapshot"] == "a.npz"
    assert agg["argmax_cci_snapshot"] == "c.npz"

    # Boundary CV: mean = 0.42, population variance =
    #   ((0.40-0.42)^2 + (0.42-0.42)^2 + (0.44-0.42)^2) / 3
    #   = (0.0004 + 0 + 0.0004) / 3 = 0.000267
    # std ≈ 0.01633; CV ≈ 0.01633 / 0.421 ≈ 0.0388
    expected_cv = math.sqrt(0.0008 / 3) / (0.42 + 1e-3)
    assert agg["boundary_cv"] == pytest.approx(expected_cv, rel=1e-6)
    assert agg["boundary_persistence_aggregate_clamped"] == pytest.approx(
        max(0.0, 1.0 - expected_cv), rel=1e-6
    )


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_main_runs_on_real_input(tmp_path, capsys):
    """CLI runs end-to-end on a valid log, returns 0, prints summary."""
    log_path = tmp_path / "log.jsonl"
    out_path = tmp_path / "out.jsonl"
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])

    rc = main(["--log", str(log_path), "--out", str(out_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert str(out_path) in captured.out
    assert "n_snapshots: 2" in captured.out
    assert "mean_cci:" in captured.out


def test_cli_main_missing_log_returns_nonzero(tmp_path, capsys):
    """CLI surfaces a missing log as EXACTLY exit 1 (its documented lane).

    Upgraded from a nonzero-only assertion: exit 1 is metrics' distinct
    missing-input code, and pinning it exactly keeps it distinguishable
    from the exit-4 operational write-failure lane."""
    rc = main(["--log", str(tmp_path / "missing.jsonl"),
               "--out", str(tmp_path / "out.jsonl")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()
    assert captured.err.count("error:") == 1
    assert "Traceback" not in captured.err


def test_cli_malformed_data_exits_2_exactly(tmp_path, capsys):
    """Malformed JSONL rows are a data error: EXACTLY exit 2, one concise
    error: line, no traceback."""
    bad = tmp_path / "nextness_runs.jsonl"
    bad.write_text("{not json at all\n", encoding="utf-8")
    rc = main(["--log", str(bad), "--out", str(tmp_path / "out.jsonl")])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.count("error:") == 1
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# Write-boundary safety contract (Jack's PR #142 audit)
# ---------------------------------------------------------------------------


def test_compute_run_metrics_accepts_output_inside_log_directory(tmp_path):
    """Sibling output path (same directory as log) succeeds — happy path
    for the Lane B safety contract.
    """
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out_path = log_dir / "nextness_run_metrics.jsonl"  # sibling of log_path
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])

    # Should not raise
    agg = compute_run_metrics(log_path, out_path)
    assert out_path.is_file()
    assert agg["n_snapshots"] == 2


def test_compute_run_metrics_rejects_output_outside_log_directory(tmp_path):
    """Output path outside log_path.parent raises WriteOutsideLogDirError.

    Lane B contract: derived metrics output must land inside the same
    directory as the input JSONL log. Per Jack's PR #142 audit; before
    this fix, the function would happily write anywhere on disk.
    """
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    # Output path is a sibling of log_dir, not inside it — outside the boundary
    out_path = tmp_path / "outside_dir" / "out.jsonl"
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])

    with pytest.raises(WriteOutsideLogDirError, match="outside log_path"):
        compute_run_metrics(log_path, out_path)

    # And the parent directory of the rejected out_path must NOT have been
    # created — validation happens before any disk side effects.
    assert not (tmp_path / "outside_dir").exists()


def test_compute_run_metrics_rejects_traversal_escape(tmp_path):
    """``..`` traversal must also be rejected, not just literal mismatch.

    Defensive: ensures the validation resolves paths to canonical absolute
    form rather than doing literal string comparison.
    """
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    # Looks-inside but actually escapes via ..
    out_path = log_dir / ".." / ".." / "escape.jsonl"
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])

    with pytest.raises(WriteOutsideLogDirError):
        compute_run_metrics(log_path, out_path)


def test_cli_main_returns_nonzero_for_outside_log_dir_output(tmp_path, capsys):
    """CLI propagates WriteOutsideLogDirError as a non-zero exit code.

    Distinct exit code from the data-error path so external callers can
    distinguish a safety refusal from a malformed-input error.
    """
    log_dir = tmp_path / "data" / "nextness_log"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "nextness_runs.jsonl"
    out_path = tmp_path / "elsewhere" / "out.jsonl"  # outside log_dir
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])

    rc = main(["--log", str(log_path), "--out", str(out_path)])
    assert rc == 3  # upgraded from nonzero-only: the exact safety-refusal code
    captured = capsys.readouterr()
    assert "safety error" in captured.err.lower()
    assert "outside log_path" in captured.err.lower()
    # No side effects: the outside-of-boundary parent dir must not exist
    assert not (tmp_path / "elsewhere").exists()


# ---------------------------------------------------------------------------
# Operational output-write failure lane (exit 4): an OSError anywhere in
# the OUTPUT region — parent-directory creation, binary open, streamed
# writes, close — is an EXPECTED operational failure: one concise error:
# line, exit 4, no traceback, input log byte-identical. Destination
# preservation is guaranteed ONLY for failures at or before binary open
# (a read-only destination is never truncated); once open succeeds,
# direct streamed non-atomic output may be truncated or partial if a
# later write/close fails. The lane must never be produced by READ-side
# errors, and is distinct from exit 3 (pre-write safety refusal) and
# exit 1 (missing log).
# ---------------------------------------------------------------------------


def _patch_binary_write_open(monkeypatch, victim_resolved: pathlib.Path, exc: OSError):
    """Make Path.open raise ``exc`` only for the victim path's BINARY WRITE.

    Reads and every other path stay untouched, so the failure is pinned to
    the output file's open and nothing else."""
    real_open = pathlib.Path.open

    def patched(self, mode="r", *args, **kwargs):
        if "w" in mode and "b" in mode and self.resolve() == victim_resolved:
            raise exc
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", patched)


def _write_two_row_log(tmp_path: pathlib.Path) -> pathlib.Path:
    log_path = tmp_path / "nextness_runs.jsonl"
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])
    return log_path


def _expect_exit4_receipt(capsys) -> None:
    captured = capsys.readouterr()
    err_lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("error:")
    assert "Traceback" not in captured.err


def test_cli_output_open_permission_error_is_concise_exit_4(tmp_path, capsys, monkeypatch):
    """OUTPUT-OPEN failure (deterministic, cross-platform): a
    PermissionError raised by the output file's binary open — i.e.
    BEFORE any truncation — reaches main() as the typed output-write
    failure. Exit 4, one error: line, no traceback, input log untouched,
    and the pre-existing destination byte-identical: destination
    preservation IS guaranteed at open time, because open never
    succeeded."""
    log_path = _write_two_row_log(tmp_path)
    out_path = tmp_path / "out.jsonl"
    out_path.write_text("stale pre-existing content\n", encoding="utf-8")
    log_before = log_path.read_bytes()
    dest_before = out_path.read_bytes()

    _patch_binary_write_open(monkeypatch, out_path.resolve(),
                             PermissionError(13, "write denied"))

    assert main(["--log", str(log_path), "--out", str(out_path)]) == 4
    _expect_exit4_receipt(capsys)
    assert log_path.read_bytes() == log_before
    assert out_path.read_bytes() == dest_before


def test_cli_output_parent_mkdir_permission_error_is_concise_exit_4(
    tmp_path, capsys, monkeypatch
):
    """OUTPUT-PARENT-CREATION failure: parent mkdir is part of the output
    region, so a PermissionError there must land in the same typed exit-4
    lane — not escape as a traceback. Log untouched; no output created."""
    log_path = _write_two_row_log(tmp_path)
    out_path = tmp_path / "newsub" / "out.jsonl"  # inside containment; parent absent
    victim = (tmp_path / "newsub").resolve()
    log_before = log_path.read_bytes()
    real_mkdir = pathlib.Path.mkdir

    def patched(self, *args, **kwargs):
        if self.resolve() == victim:
            raise PermissionError(13, "mkdir denied")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "mkdir", patched)

    assert main(["--log", str(log_path), "--out", str(out_path)]) == 4
    _expect_exit4_receipt(capsys)
    assert log_path.read_bytes() == log_before
    assert not (tmp_path / "newsub").exists()  # no output, no partial scaffolding


def test_cli_mid_write_oserror_is_concise_exit_4(tmp_path, capsys, monkeypatch):
    """MID-WRITE failure: after binary open succeeds and one row has been
    written, a later write raising OSError must still land in the typed
    exit-4 lane — one error: line, no traceback, input log untouched.

    Deliberately NO destination-integrity assertion: output is direct,
    streamed and non-atomic, so a mid-write failure may leave a truncated
    or partial destination. That is the documented contract."""
    log_path = _write_two_row_log(tmp_path)  # 2 rows -> 1 pair row + aggregate
    out_path = tmp_path / "out.jsonl"
    log_before = log_path.read_bytes()
    out_resolved = out_path.resolve()
    real_open = pathlib.Path.open
    writes = {"n": 0}

    class _FailAfterFirstWrite:
        def __init__(self, raw):
            self._raw = raw

        def write(self, data):
            writes["n"] += 1
            if writes["n"] > 1:
                raise OSError(28, "device full mid-stream")
            return self._raw.write(data)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._raw.__exit__(*exc)

        def __getattr__(self, name):
            return getattr(self._raw, name)

    def patched(self, mode="r", *args, **kwargs):
        raw = real_open(self, mode, *args, **kwargs)
        if "w" in mode and "b" in mode and self.resolve() == out_resolved:
            return _FailAfterFirstWrite(raw)
        return raw

    monkeypatch.setattr(pathlib.Path, "open", patched)

    assert main(["--log", str(log_path), "--out", str(out_path)]) == 4
    _expect_exit4_receipt(capsys)
    assert writes["n"] > 1  # the failure genuinely occurred mid-stream
    assert log_path.read_bytes() == log_before


def test_read_side_unexpected_oserror_is_not_reclassified(tmp_path, monkeypatch):
    """Scope precision: an unexpected OSError on the LOG READ must not be
    converted into exit 4 by an over-broad handler — it stays loud."""
    log_path = _write_two_row_log(tmp_path)
    out_path = tmp_path / "out.jsonl"
    victim = log_path.resolve()
    real_open = pathlib.Path.open

    def patched(self, mode="r", *args, **kwargs):
        if "r" in mode and "b" not in mode and self.resolve() == victim:
            raise PermissionError(13, "read denied")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", patched)
    with pytest.raises(PermissionError, match="read denied"):
        main(["--log", str(log_path), "--out", str(out_path)])


# ---------------------------------------------------------------------------
# Input-identity guard: --out must never name or alias the input log —
# by resolved path and by file identity (os.path.samefile on resolved
# paths; fail closed when identity cannot be verified). Refusals keep
# the existing metrics boundary-failure convention: exit code 3, one
# "safety error:" line, WriteOutsideLogDirError vocabulary, no
# traceback — and happen BEFORE any metrics computation, output-parent
# creation or derived-output write.
# ---------------------------------------------------------------------------


def _two_entry_log(tmp_path: pathlib.Path) -> pathlib.Path:
    log_path = tmp_path / "nextness_runs.jsonl"
    _write_log(log_path, [
        _make_entry(generation=1, snapshot_file="a.npz"),
        _make_entry(generation=2, snapshot_file="b.npz"),
    ])
    return log_path


def _make_hardlink_or_skip(target: pathlib.Path, link: pathlib.Path) -> None:
    try:
        os.link(target, link)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hard links unsupported on this filesystem")


def _make_symlink_or_skip(target: pathlib.Path, link: pathlib.Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported here (e.g. Windows w/o privilege)")


def _expect_alias_refusal(capsys, tmp_path, log_path, out_arg) -> None:
    """Full refusal contract: exit 3 · one safety-error line · no
    traceback · input byte-identical · no derived output or new entry."""
    input_before = log_path.read_bytes()
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    rc = main(["--log", str(log_path), "--out", str(out_arg)])
    assert rc == 3
    captured = capsys.readouterr()
    assert captured.err.count("safety error:") == 1
    assert "Traceback" not in captured.err
    assert log_path.read_bytes() == input_before
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


def test_cli_out_naming_input_log_is_refused(tmp_path, capsys):
    log_path = _two_entry_log(tmp_path)
    _expect_alias_refusal(capsys, tmp_path, log_path, log_path)


def test_cli_out_lexical_alias_of_log_is_refused(tmp_path, capsys):
    # Distinct lexically, identical once resolved; 'sub' does not exist
    # and must not be created (refusal precedes any parent mkdir).
    log_path = _two_entry_log(tmp_path)
    alias = tmp_path / "sub" / ".." / "nextness_runs.jsonl"
    assert str(alias) != str(log_path)
    _expect_alias_refusal(capsys, tmp_path, log_path, alias)
    assert not (tmp_path / "sub").exists()


def test_cli_out_symlink_alias_of_log_is_refused(tmp_path, capsys):
    log_path = _two_entry_log(tmp_path)
    link = tmp_path / "out.jsonl"
    _make_symlink_or_skip(log_path, link)
    _expect_alias_refusal(capsys, tmp_path, log_path, link)


def test_cli_out_hardlink_alias_of_log_is_refused(tmp_path, capsys):
    log_path = _two_entry_log(tmp_path)
    link = tmp_path / "out.jsonl"
    _make_hardlink_or_skip(log_path, link)
    input_before = log_path.read_bytes()
    rc = main(["--log", str(log_path), "--out", str(link)])
    assert rc == 3
    captured = capsys.readouterr()
    assert captured.err.count("safety error:") == 1
    assert "Traceback" not in captured.err
    assert log_path.read_bytes() == input_before
    assert link.read_bytes() == input_before  # shared identity: still the log


def test_compute_run_metrics_refuses_alias_directly(tmp_path):
    log_path = _two_entry_log(tmp_path)
    with pytest.raises(WriteOutsideLogDirError):
        compute_run_metrics(log_path, log_path)
    with pytest.raises(WriteOutsideLogDirError):
        compute_run_metrics(log_path, tmp_path / "sub" / ".." / "nextness_runs.jsonl")


def test_alias_refusal_precedes_metrics_computation(tmp_path, capsys, monkeypatch):
    import scripts.nextness_metrics as metrics_module

    log_path = _two_entry_log(tmp_path)

    def spy(*args, **kwargs):
        raise AssertionError("metrics computation ran despite alias refusal")

    # kl_divergence is on the per-pair computation path for this
    # two-entry log; a refused invocation must never reach it.
    monkeypatch.setattr(metrics_module, "kl_divergence", spy)
    assert main(["--log", str(log_path), "--out", str(log_path)]) == 3
    err = capsys.readouterr().err
    assert "Traceback" not in err


def test_cli_out_ordinary_siblings_remain_allowed(tmp_path, capsys):
    log_path = _two_entry_log(tmp_path)
    input_before = log_path.read_bytes()

    fresh = tmp_path / "out.jsonl"                 # nonexistent sibling
    assert main(["--log", str(log_path), "--out", str(fresh)]) == 0
    assert fresh.is_file()

    stale = tmp_path / "stale.jsonl"               # existing non-alias sibling
    stale.write_text("previous content\n", encoding="utf-8")
    assert main(["--log", str(log_path), "--out", str(stale)]) == 0
    assert stale.read_bytes() == fresh.read_bytes()

    assert log_path.read_bytes() == input_before
    capsys.readouterr()  # drain summaries


# ---------------------------------------------------------------------------
# Directory-target failure lane: an existing directory inside the log
# directory must be refused in the established exit-3 boundary lane —
# never escape as an IsADirectoryError/PermissionError traceback from
# the binary open.
# ---------------------------------------------------------------------------


def _snapshot_tree(root: pathlib.Path) -> list[tuple[str, bytes | None]]:
    out = []
    for p in sorted(root.rglob("*")):
        out.append((str(p.relative_to(root)), p.read_bytes() if p.is_file() else None))
    return out


def test_cli_out_naming_existing_directory_is_refused_exit_3(tmp_path, capsys):
    log_path = _two_entry_log(tmp_path)
    target_dir = tmp_path / "already_here"
    target_dir.mkdir()
    (target_dir / "keep.txt").write_text("keep me\n", encoding="utf-8")
    input_before = log_path.read_bytes()
    tree_before = _snapshot_tree(tmp_path)

    rc = main(["--log", str(log_path), "--out", str(target_dir)])

    assert rc == 3
    captured = capsys.readouterr()
    assert captured.err.count("safety error:") == 1
    assert "Traceback" not in captured.err
    assert log_path.read_bytes() == input_before
    assert _snapshot_tree(tmp_path) == tree_before  # dir + contents unchanged


def test_directory_refusal_precedes_metrics_computation(tmp_path, capsys, monkeypatch):
    import scripts.nextness_metrics as metrics_module

    log_path = _two_entry_log(tmp_path)
    target_dir = tmp_path / "already_here"
    target_dir.mkdir()

    def spy(*args, **kwargs):
        raise AssertionError("metrics computation ran despite directory refusal")

    monkeypatch.setattr(metrics_module, "kl_divergence", spy)
    assert main(["--log", str(log_path), "--out", str(target_dir)]) == 3
    assert "Traceback" not in capsys.readouterr().err


def test_cli_out_symlink_to_directory_is_refused_exit_3(tmp_path, capsys):
    log_path = _two_entry_log(tmp_path)
    target_dir = tmp_path / "real_dir"
    target_dir.mkdir()
    link = tmp_path / "out.jsonl"
    try:
        link.symlink_to(target_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported here (e.g. Windows w/o privilege)")
    input_before = log_path.read_bytes()
    rc = main(["--log", str(log_path), "--out", str(link)])
    assert rc == 3
    captured = capsys.readouterr()
    assert captured.err.count("safety error:") == 1
    assert "Traceback" not in captured.err
    assert log_path.read_bytes() == input_before
    assert target_dir.is_dir()


# ---------------------------------------------------------------------------
# Output byte contract: canonical per-row JSON, UTF-8, LF bytes only —
# no platform newline translation, byte-identical rewrite.
# ---------------------------------------------------------------------------


def test_output_bytes_are_canonical_utf8_lf_only(tmp_path):
    log_path = _two_entry_log(tmp_path)
    out_path = tmp_path / "out.jsonl"
    assert main(["--log", str(log_path), "--out", str(out_path)]) == 0
    raw = out_path.read_bytes()
    assert b"\r" not in raw                        # no CRLF translation
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    # Every line is exactly its canonical serialization re-encoded.
    lines = raw.split(b"\n")[:-1]
    rebuilt = b"".join(
        json.dumps(json.loads(line), sort_keys=True, default=str).encode("utf-8")
        + b"\n"
        for line in lines
    )
    assert raw == rebuilt
    # Byte-identical idempotent rewrite.
    assert main(["--log", str(log_path), "--out", str(out_path)]) == 0
    assert out_path.read_bytes() == raw


# ---------------------------------------------------------------------------
# Cross-module CLI failure-contract pins (Candidate C; see
# docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md). Pins of ESTABLISHED behavior:
# argparse usage lane (SystemExit(2), multi-line usage:, outside main()'s
# return path);
# identity-inspection failure fails closed (exit 3, safety error:)
# ---------------------------------------------------------------------------


def test_cli_argparse_usage_error_exits_2(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "Traceback" not in err


def test_cli_identity_inspection_failure_fails_closed_exit_3(
    tmp_path, capsys, monkeypatch
) -> None:
    """A PermissionError from the guard's identity comparison must be a
    safety refusal in metrics' own lane — exit 3, one 'safety error:'
    line, no traceback, everything untouched."""
    log_path = _two_entry_log(tmp_path)
    out = tmp_path / "out.jsonl"
    out.write_text("stale existing non-alias output\n", encoding="utf-8")
    log_before, out_before = log_path.read_bytes(), out.read_bytes()
    entries_before = sorted(p.name for p in tmp_path.iterdir())
    out_resolved = out.resolve()
    real_samefile = os.path.samefile

    def probed(a, b):
        if pathlib.Path(a).resolve() == out_resolved:
            raise PermissionError(13, "identity probe denied")
        return real_samefile(a, b)

    monkeypatch.setattr(os.path, "samefile", probed)
    assert main(["--log", str(log_path), "--out", str(out)]) == 3
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("safety error:")
    assert "Traceback" not in captured.err
    assert log_path.read_bytes() == log_before
    assert out.read_bytes() == out_before
    assert sorted(p.name for p in tmp_path.iterdir()) == entries_before


# ---------------------------------------------------------------------------
# Output-write STAGE pins (see docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md and the
# 2026-07-17 output-write audit). INJECTED deterministic branch exercises of
# the expected exit-4 operational-write lane — distinct from PUBLIC
# filesystem behavior and never a public-reachability claim. Stage counters
# assert the intended operation (open/write/close) actually fired, so no pin
# can pass by triggering the wrong stage.
# ---------------------------------------------------------------------------


class _StageProxy:
    def __init__(self, raw, fail_write_at=None, fail_close=False):
        self._raw = raw
        self._fail_at = fail_write_at
        self._fail_close = fail_close
        self.writes_ok = 0
        self.close_attempted = False

    def write(self, data):
        if self._fail_at is not None and self.writes_ok + 1 >= self._fail_at:
            raise OSError(28, "injected write failure")
        n = self._raw.write(data)
        self.writes_ok += 1
        return n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close_attempted = True
        self._raw.__exit__(*exc)
        if self._fail_close and exc[0] is None:
            raise OSError(5, "injected close failure")

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _patch_output_stage(monkeypatch, victim_resolved, *, deny_open=False,
                        fail_write_at=None, fail_close=False):
    """Patch ONLY the victim path's binary-write open; returns stage state."""
    state = {"opens": 0, "proxy": None}
    real_open = pathlib.Path.open

    def patched(self, mode="r", *args, **kwargs):
        if "w" in mode and "b" in mode and self.resolve() == victim_resolved:
            state["opens"] += 1
            if deny_open:
                raise PermissionError(13, "injected open denial")
            raw = real_open(self, mode, *args, **kwargs)
            state["proxy"] = _StageProxy(raw, fail_write_at, fail_close)
            return state["proxy"]
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", patched)
    return state


def _stage_exit4_receipt(capsys):
    captured = capsys.readouterr()
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in captured.err


def test_cli_close_time_failure_pinned(tmp_path, capsys, monkeypatch) -> None:
    """Close-time failure (streamed writer): every streamed row write
    succeeds, only the context exit raises — the destination equals the
    canonical successful output byte-for-byte although the CLI returns 4."""
    log_path = _two_entry_log(tmp_path)
    canon = tmp_path / "canonical.out"
    assert main(["--log", str(log_path), "--out", str(canon)]) == 0
    capsys.readouterr()
    canonical = canon.read_bytes()
    out = tmp_path / "stage_pin.out"
    log_before = log_path.read_bytes()
    state = _patch_output_stage(monkeypatch, out.resolve(), fail_close=True)
    assert main(["--log", str(log_path), "--out", str(out)]) == 4
    _stage_exit4_receipt(capsys)
    assert state["opens"] == 1 and state["proxy"] is not None
    assert state["proxy"].writes_ok == 2          # 1 pair row + 1 aggregate row
    assert state["proxy"].close_attempted          # failure was AT close, not write
    assert out.read_bytes() == canonical           # complete canonical stream
    assert log_path.read_bytes() == log_before


# ---------------------------------------------------------------------------
# Metrics typed-input-boundary pilot (gated; docs/NEXTNESS_CLI_FAILURE_CONTRACTS.md).
# Failing-first target: a sentinel plain ValueError escaping a
# post-validation metrics core call must PROPAGATE, never convert to the
# documented exit-2 data lane. Preservation controls pin every public
# lane byte-for-byte, plus the FileNotFoundError race lane, the exit-3
# safety lane, the typed exit-4 write lane and output determinism.
# ---------------------------------------------------------------------------


def _expect_single_error_line(capsys, expected: str) -> str:
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert lines == [expected]
    assert "Traceback" not in err
    return err


def test_cli_internal_plain_valueerror_propagates(tmp_path, monkeypatch) -> None:
    """Pilot pin: an internal plain ValueError from the post-validation
    computation core (js_divergence, called per pair after log parse and
    pre-write safety validation) is an unexpected programming error and
    must propagate — not masquerade as a concise exit-2 data failure."""
    import scripts.nextness_metrics as metrics_module

    log = tmp_path / "nextness_runs.jsonl"
    _write_log(log, [_make_entry(generation=1, snapshot_file="a.npz"),
                     _make_entry(generation=2, snapshot_file="b.npz")])
    before = log.read_bytes()
    out = tmp_path / "derived.jsonl"

    def boom(*args, **kwargs):
        raise ValueError("sentinel plain ValueError probe")

    monkeypatch.setattr(metrics_module, "js_divergence", boom)
    with pytest.raises(ValueError, match="sentinel plain ValueError probe"):
        main(["--log", str(log), "--out", str(out)])
    assert log.read_bytes() == before
    assert not out.exists()


def test_cli_five_input_lanes_exact_public_behavior(tmp_path, capsys) -> None:
    """The five reclassified lanes keep their public behavior
    byte-for-byte: exact message, single stderr line, exit 2, no
    traceback, input untouched, no output created."""
    two = tmp_path / "two.jsonl"
    _write_log(two, [_make_entry(generation=1, snapshot_file="a.npz"),
                     _make_entry(generation=2, snapshot_file="b.npz")])
    neg_rate = tmp_path / "negrate.jsonl"
    _write_log(neg_rate, [_make_entry(generation=1, snapshot_file="a.npz"),
                          _make_entry(generation=2, snapshot_file="b.npz",
                                      boundary_rate=-0.5)])
    one = tmp_path / "one.jsonl"
    _write_log(one, [_make_entry(generation=1, snapshot_file="a.npz")])
    bad = tmp_path / "malformed.jsonl"
    bad_payload = "{not json"
    bad.write_text(
        json.dumps(_make_entry(generation=1, snapshot_file="a.npz"),
                   sort_keys=True) + "\n" + bad_payload + "\n",
        encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as exc_info:
        json.loads(bad_payload)
    json_err = str(exc_info.value)
    # §9.4 strict-input-domain note: these lanes now originate at the
    # ingestion/parameter validation seam, so their messages carry the
    # strict-domain wording (the old pairwise/helper-origin messages are
    # subsumed; exit codes and one-concise-line shape unchanged).
    cases = (
        (bad, [], f"error: malformed JSONL at {bad}:2: {json_err}"),
        (two, ["--smoothing", "-1"],
         "error: smoothing must be finite and non-negative, got -1.0"),
        (neg_rate, [],
         f"error: boundary_rate must be finite and within [0, 1], "
         f"got -0.5 at {neg_rate}:2"),
        (two, ["--boundary-delta", "0"],
         "error: boundary_delta must be finite and positive, got 0.0"),
        (one, ["--boundary-delta", "0"],
         "error: boundary_delta must be finite and positive, got 0.0"),
    )
    for log, extra, expected in cases:
        before = log.read_bytes()
        out = tmp_path / "derived.jsonl"
        assert main(["--log", str(log), "--out", str(out), *extra]) == 2
        _expect_single_error_line(capsys, expected)
        assert log.read_bytes() == before
        assert not out.exists()


def test_cli_filenotfound_race_lane_still_exit_2(tmp_path, monkeypatch, capsys) -> None:
    """The validation-to-read race lane: a FileNotFoundError escaping
    compute_run_metrics keeps the documented exit-2 clause (injected
    exercise of the clause; the pre-check missing-log lane is exit 1)."""
    import scripts.nextness_metrics as metrics_module

    log = _two_entry_log(tmp_path)

    def race(*args, **kwargs):
        raise FileNotFoundError(f"log file not found: {log}")

    monkeypatch.setattr(metrics_module, "compute_run_metrics", race)
    assert main(["--log", str(log), "--out", str(tmp_path / "d.jsonl")]) == 2
    _expect_single_error_line(capsys, f"error: log file not found: {log}")


def test_cli_missing_log_still_exit_1(tmp_path, capsys) -> None:
    missing = tmp_path / "absent.jsonl"
    assert main(["--log", str(missing), "--out", str(tmp_path / "d.jsonl")]) == 1
    _expect_single_error_line(capsys, f"error: log file not found: {missing}")


def test_cli_safety_refusal_still_exit_3(tmp_path, capsys) -> None:
    log = _two_entry_log(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}_outside.jsonl"
    assert main(["--log", str(log), "--out", str(outside)]) == 3
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("safety error:")
    assert "Traceback" not in err
    assert not outside.exists()


def test_cli_output_write_failure_still_exit_4(tmp_path, monkeypatch, capsys) -> None:
    log = _two_entry_log(tmp_path)
    out = tmp_path / "denied.jsonl"
    _patch_binary_write_open(monkeypatch, out.resolve(),
                             PermissionError(13, "injected open denial"))
    assert main(["--log", str(log), "--out", str(out)]) == 4
    _expect_exit4_receipt(capsys)


def test_cli_successful_output_byte_identical(tmp_path, capsys) -> None:
    log = _two_entry_log(tmp_path)
    out1 = tmp_path / "d1.jsonl"
    out2 = tmp_path / "d2.jsonl"
    assert main(["--log", str(log), "--out", str(out1)]) == 0
    assert main(["--log", str(log), "--out", str(out2)]) == 0
    capsys.readouterr()
    assert out1.read_bytes() == out2.read_bytes()


def test_typed_identity_at_the_five_reclassified_sites(tmp_path) -> None:
    """Direct-API pin: typed identity at the five reclassified sites
    (a ValueError subclass — base-class catchers remain compatible)."""
    from scripts.nextness_metrics import (
        MetricsInputError,
        boundary_cv,
        boundary_persistence_pairwise,
        compute_run_metrics,
        smoothed_distribution,
    )

    assert issubclass(MetricsInputError, ValueError)
    with pytest.raises(MetricsInputError):
        smoothed_distribution({"karuna_relief": 1}, smoothing=-1.0)
    with pytest.raises(MetricsInputError):
        boundary_persistence_pairwise(-1.0, 0.3)
    with pytest.raises(MetricsInputError):
        boundary_persistence_pairwise(0.1, 0.2, delta=0.0)
    with pytest.raises(MetricsInputError):
        boundary_cv([0.1, 0.2], delta=0.0)
    bad = tmp_path / "malformed.jsonl"
    bad.write_text("{not json" + chr(10), encoding="utf-8")
    with pytest.raises(MetricsInputError, match="malformed JSONL"):
        compute_run_metrics(bad, tmp_path / "d.jsonl")


# ---------------------------------------------------------------------------
# Invalid-UTF-8 input lane (regression vs the pre-#381 contract; see the
# late review thread on merged #381). An undecodable log is genuine bad
# input: pre-#381 the broad catch reported it as concise exit 2; the typed
# narrowing let UnicodeDecodeError (a ValueError subclass) escape. Restored
# by a narrow UnicodeDecodeError wrapping boundary around the text-reading
# region only — message preserved byte-for-byte via str(e).
# ---------------------------------------------------------------------------

_BAD_UTF8 = b'\xff\xfe{"generation": 1}\n'


def test_cli_invalid_utf8_log_is_concise_exit_2(tmp_path, capsys) -> None:
    """Regression pin: invalid-UTF-8 log -> exit 2 with the exact
    pre-#381 stderr bytes, one line, no traceback, input untouched,
    no output created."""
    log = tmp_path / "bad_utf8.jsonl"
    log.write_bytes(_BAD_UTF8)
    before = log.read_bytes()
    out = tmp_path / "derived.jsonl"
    with pytest.raises(UnicodeDecodeError) as exc_info:
        _BAD_UTF8.decode("utf-8")
    expected = f"error: {exc_info.value}"
    assert main(["--log", str(log), "--out", str(out)]) == 2
    err = capsys.readouterr().err
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert lines == [expected]
    assert "Traceback" not in err
    assert log.read_bytes() == before
    assert not out.exists()


def test_invalid_utf8_direct_api_typed_with_cause(tmp_path) -> None:
    """Direct-API pin: compute_run_metrics raises MetricsInputError whose
    __cause__ is the original UnicodeDecodeError; message equals str(e)
    with no added inner prefix."""
    from scripts.nextness_metrics import MetricsInputError

    log = tmp_path / "bad_utf8.jsonl"
    log.write_bytes(_BAD_UTF8)
    with pytest.raises(MetricsInputError) as exc_info:
        compute_run_metrics(log, tmp_path / "d.jsonl")
    assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)
    assert str(exc_info.value) == str(exc_info.value.__cause__)


# ---------------------------------------------------------------------------
# Strict input domain (Kev-authorized policy; PHASE_19_PR3 §9.4).
# Failing-first: every confirmed public divergence from the documented
# [0,1] domain must become a typed exit-2 rejection. The absent-field
# 0.0 policy is pinned separately as the explicitly chosen compatibility
# behavior established by this change.
# ---------------------------------------------------------------------------


def _entry_line(br=0.3, gen=1, extra=""):
    core = (f'{{"generation": {gen}, "snapshot_file": "s{gen}.npz", '
            f'"token_counts": {{"void_static": 3}}, "void_compute_balance": 0.5, '
            f'"entropy_normalized": 0.4{extra}')
    if br is not None:
        core += f', "boundary_rate": {br}'
    return core + "}"


def _run_strict(tmp_path, capsys, lines, extra_argv=(), out_name="derived.jsonl"):
    log = tmp_path / "strict.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / out_name
    rc = main(["--log", str(log), "--out", str(out), *extra_argv])
    err = capsys.readouterr().err
    return rc, err, log.read_bytes() == before, out.exists()


def _assert_rejected(rc, err, unchanged, out_exists):
    assert rc == 2
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert unchanged
    assert not out_exists


def test_cli_strict_domain_rejections(tmp_path, capsys) -> None:
    """Failing-first: the eight confirmed public divergences each become
    typed exit 2 — one line, no traceback, input untouched, no output."""
    cases = (
        [_entry_line(br=-0.5)],                       # single-entry negative
        [_entry_line(br=1.5), _entry_line(br=2.5, gen=2)],  # above one
        [_entry_line(br="NaN")],                      # JSON NaN constant
        [_entry_line(br="Infinity")],                 # JSON Infinity constant
        [_entry_line(br="true")],                     # boolean
        [_entry_line(br='"0.7"')],                    # numeric string
        [_entry_line(br='"high"')],                   # garbage string
        [_entry_line(br="null")],                     # explicit JSON null
    )
    for i, lines in enumerate(cases):
        rc, err, unchanged, out_exists = _run_strict(
            tmp_path, capsys, lines, out_name=f"d{i}.jsonl")
        _assert_rejected(rc, err, unchanged, out_exists)


def test_cli_absent_unit_field_accepted_as_zero(tmp_path, capsys) -> None:
    """The absent-field 0.0 policy (explicitly chosen compatibility,
    established here — not historical proof from PR #141): success,
    deterministic bytes."""
    lines = [_entry_line(br=None), _entry_line(br=0.3, gen=2)]
    rc, err, unchanged, out_exists = _run_strict(tmp_path, capsys, lines)
    assert rc == 0 and unchanged and out_exists
    rc2, _, _, _ = _run_strict(tmp_path, capsys, lines, out_name="d2.jsonl")
    assert rc2 == 0
    assert (tmp_path / "derived.jsonl").read_bytes() == (tmp_path / "d2.jsonl").read_bytes()


def test_helper_totality_typed(tmp_path) -> None:
    """Direct-helper totality: out-of-type and out-of-domain values raise
    the typed MetricsInputError — before single-element early returns —
    and the aggregate is genuinely bounded for valid input."""
    from scripts.nextness_metrics import MetricsInputError

    for bad_call in (
        lambda: boundary_persistence_pairwise("0.5", 0.3),
        lambda: boundary_persistence_pairwise(None, 0.3),
        lambda: boundary_persistence_pairwise(float("nan"), 0.3),
        lambda: boundary_persistence_pairwise(True, 0.3),
        lambda: boundary_persistence_pairwise(1.5, 0.3),
        lambda: boundary_persistence_pairwise(0.3, 0.3, delta=float("nan")),
        lambda: boundary_cv([-0.5, -0.7]),
        lambda: boundary_cv([-0.002, 0.0]),          # old ZeroDivisionError lane
        lambda: boundary_cv([-0.5]),                 # BEFORE single-element return
        lambda: boundary_cv([1.5, 2.5]),
        lambda: boundary_cv([0.3, 0.4], delta=float("inf")),
        lambda: boundary_persistence_aggregate_clamped([float("nan")]),
        lambda: boundary_persistence_aggregate_clamped([-0.5, -0.7]),
    ):
        with pytest.raises(MetricsInputError):
            bad_call()
    for rates in ([0.0, 0.0], [0.0, 1.0], [0.5, 0.5, 0.5], [1.0], []):
        v = boundary_persistence_aggregate_clamped(rates)
        assert 0.0 <= v <= 1.0


def test_cli_numeric_params_strict(tmp_path, capsys) -> None:
    """--smoothing must be finite and non-negative; --boundary-delta
    finite and strictly positive."""
    good = [_entry_line(), _entry_line(gen=2)]
    for extra in (["--smoothing", "inf"], ["--smoothing", "nan"],
                  ["--boundary-delta", "inf"], ["--boundary-delta", "nan"]):
        rc, err, unchanged, out_exists = _run_strict(
            tmp_path, capsys, good, extra_argv=extra,
            out_name=f"p_{extra[0][2:4]}{extra[1]}.jsonl")
        _assert_rejected(rc, err, unchanged, out_exists)


def test_cli_token_counts_strict(tmp_path, capsys) -> None:
    """token_counts, when present, must be a mapping of non-boolean,
    non-negative integer counts."""
    cases = (
        '{"generation": 1, "snapshot_file": "s1.npz", "token_counts": '
        '{"void_static": true}, "boundary_rate": 0.3}',
        '{"generation": 1, "snapshot_file": "s1.npz", "token_counts": '
        '{"void_static": -3}, "boundary_rate": 0.3}',
        '{"generation": 1, "snapshot_file": "s1.npz", "token_counts": '
        '[1, 2], "boundary_rate": 0.3}',
        '{"generation": 1, "snapshot_file": "s1.npz", "token_counts": '
        'null, "boundary_rate": 0.3}',
    )
    for i, line in enumerate(cases):
        rc, err, unchanged, out_exists = _run_strict(
            tmp_path, capsys, [line], out_name=f"t{i}.jsonl")
        _assert_rejected(rc, err, unchanged, out_exists)


def test_cli_prewrite_finiteness_rejects_passthrough_overflow(tmp_path, capsys) -> None:
    """The pre-write invariant closes pass-through lanes: a numeric-
    overflow generation (1e400 -> inf, no constant token involved) is
    rejected before any destination is touched — including a
    pre-existing destination, byte-identically preserved."""
    log = tmp_path / "of.jsonl"
    log.write_text(_entry_line(gen="1e400") + "\n" + _entry_line(gen=2) + "\n",
                   encoding="utf-8")
    out = tmp_path / "of_out.jsonl"
    out.write_text("pre-existing destination\n", encoding="utf-8")
    dest_before = out.read_bytes()
    rc = main(["--log", str(log), "--out", str(out)])
    err = capsys.readouterr().err
    assert rc == 2
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert out.read_bytes() == dest_before


# ---------------------------------------------------------------------------
# §9.4 hardening round (Jack audit of draft #385): recursive finiteness,
# huge-count arithmetic, zero-smoothing KL, and located constant messages.
# ---------------------------------------------------------------------------


def test_cli_nested_overflow_rejected_prewrite_destination_preserved(tmp_path, capsys) -> None:
    """A nested non-finite float inside a pass-through container (a
    snapshot_file LIST holding 1e400 -> inf) must be caught by the
    RECURSIVE pre-write invariant — typed exit 2 with a useful key
    location, BEFORE any open, so a pre-existing destination stays
    byte-identical (the shallow check let allow_nan=False raise only
    after the destination had been truncated)."""
    log = tmp_path / "nested.jsonl"
    log.write_text(
        '{"generation": 1, "snapshot_file": [1e400], '
        '"token_counts": {"void_static": 3}, "boundary_rate": 0.3}' + "\n" +
        '{"generation": 2, "snapshot_file": "s2.npz", '
        '"token_counts": {"void_static": 3}, "boundary_rate": 0.3}' + "\n",
        encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / "nested_out.jsonl"
    out.write_text("pre-existing destination" + "\n", encoding="utf-8")
    dest_before = out.read_bytes()
    rc = main(["--log", str(log), "--out", str(out)])
    err = capsys.readouterr().err
    assert rc == 2
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "snapshot_file" in lines[0]  # useful output key location
    assert "Traceback" not in err
    assert log.read_bytes() == before
    assert out.read_bytes() == dest_before  # NEVER truncated


def test_cli_huge_token_count_rejected_typed(tmp_path, capsys) -> None:
    """A valid JSON non-negative integer too large for finite float
    arithmetic must be a typed rejection, not an OverflowError escape.
    No arbitrary semantic cap — the constraint is finite computability."""
    huge = str(10 ** 400)
    log = tmp_path / "huge.jsonl"
    log.write_text(
        '{"generation": 1, "snapshot_file": "s1.npz", '
        '"token_counts": {"void_static": ' + huge + '}, "boundary_rate": 0.3}' + "\n" +
        '{"generation": 2, "snapshot_file": "s2.npz", '
        '"token_counts": {"void_static": 3}, "boundary_rate": 0.3}' + "\n",
        encoding="utf-8")
    out = tmp_path / "huge_out.jsonl"
    rc = main(["--log", str(log), "--out", str(out)])
    err = capsys.readouterr().err
    assert rc == 2
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "Traceback" not in err
    assert not out.exists()


def test_zero_smoothing_disjoint_support_typed(tmp_path, capsys) -> None:
    """smoothing=0 stays authorized; but KL with positive p_i and zero
    q_i is mathematically undefined — typed MetricsInputError (direct
    and public), never a ZeroDivisionError escape."""
    from scripts.nextness_metrics import MetricsInputError

    with pytest.raises(MetricsInputError, match="positive smoothing"):
        kl_divergence({"void_static": 3}, {"compute_static": 3}, smoothing=0.0)
    log = tmp_path / "disjoint.jsonl"
    log.write_text(
        '{"generation": 1, "snapshot_file": "s1.npz", '
        '"token_counts": {"void_static": 3}, "boundary_rate": 0.3}' + "\n" +
        '{"generation": 2, "snapshot_file": "s2.npz", '
        '"token_counts": {"compute_static": 3}, "boundary_rate": 0.3}' + "\n",
        encoding="utf-8")
    out = tmp_path / "disjoint_out.jsonl"
    rc = main(["--log", str(log), "--out", str(out), "--smoothing", "0"])
    err = capsys.readouterr().err
    assert rc == 2
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert "positive smoothing" in lines[0]
    assert "Traceback" not in err
    assert not out.exists()


def test_cli_json_constant_message_carries_location(tmp_path, capsys) -> None:
    """The typed NaN/Infinity rejection must carry the exact log path
    and line number (wrapped at the json.loads call site, cause
    preserved) — labelled as an invalid JSON value, not mislabelled a
    JSONDecodeError."""
    log = tmp_path / "const.jsonl"
    log.write_text(
        '{"generation": 1, "snapshot_file": "s1.npz", '
        '"token_counts": {"void_static": 3}, "boundary_rate": 0.3}' + "\n" +
        '{"generation": 2, "snapshot_file": "s2.npz", '
        '"token_counts": {"void_static": 3}, "boundary_rate": NaN}' + "\n",
        encoding="utf-8")
    rc = main(["--log", str(log), "--out", str(tmp_path / "c.jsonl")])
    err = capsys.readouterr().err
    assert rc == 2
    lines = [l for l in err.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("error: invalid JSON value at ")
    assert f"{log}:2" in lines[0]
    assert "non-standard JSON constant NaN" in lines[0]


# ---------------------------------------------------------------------------
# §9.4 huge-integer totality (the late Codex finding on merged #385): a
# raw oversized INTEGER on unit-field / helper / parameter surfaces
# reached float()/math.isfinite() and escaped as OverflowError. The
# repair is one narrow finite-computability conversion path — never an
# arbitrary magnitude cap.
# ---------------------------------------------------------------------------

_HUGE = 10 ** 400


def test_cli_huge_integer_unit_fields_rejected_typed(tmp_path, capsys) -> None:
    """Public CLI: each unit field with +/- 10**400 -> typed exit 2,
    empty stdout, one concise error: line, no traceback, input
    byte-identical, supplied pre-existing destination byte-identical
    (and an absent destination stays absent)."""
    for field in ("boundary_rate", "entropy_normalized", "void_compute_balance"):
        for sign, magnitude in (("+", _HUGE), ("-", -_HUGE)):
            log = tmp_path / f"huge_{field}_{sign}.jsonl"
            log.write_text(
                '{"generation": 1, "snapshot_file": "s1.npz", '
                '"token_counts": {"void_static": 3}, '
                '"' + field + '": ' + str(magnitude) + '}' + "\n",
                encoding="utf-8")
            before = log.read_bytes()
            out = tmp_path / f"out_{field}_{sign}.jsonl"
            out.write_text("pre-existing destination\n", encoding="utf-8")
            dest_before = out.read_bytes()
            rc = main(["--log", str(log), "--out", str(out)])
            captured = capsys.readouterr()
            assert rc == 2, (field, sign)
            assert captured.out == ""
            lines = [l for l in captured.err.strip().splitlines() if l.strip()]
            assert len(lines) == 1 and lines[0].startswith("error:"), (field, sign)
            assert "Traceback" not in captured.err
            assert log.read_bytes() == before
            assert out.read_bytes() == dest_before
            absent_out = tmp_path / f"absent_{field}_{sign}.jsonl"
            rc2 = main(["--log", str(log), "--out", str(absent_out)])
            capsys.readouterr()
            assert rc2 == 2 and not absent_out.exists()


def test_direct_helpers_huge_integer_totality() -> None:
    """Direct exported numerical APIs: oversized integers raise exactly
    MetricsInputError, never raw OverflowError."""
    from scripts.nextness_metrics import MetricsInputError

    for bad_call in (
        lambda: boundary_persistence_pairwise(_HUGE, 0.3),
        lambda: boundary_persistence_pairwise(0.3, _HUGE),
        lambda: boundary_cv([_HUGE, 0.3]),
        lambda: boundary_persistence_aggregate_clamped([_HUGE, 0.3]),
        lambda: boundary_persistence_pairwise(0.3, 0.3, delta=_HUGE),
        lambda: boundary_persistence_pairwise(0.3, 0.3, delta=-_HUGE),
        lambda: boundary_cv([0.3, 0.4], delta=_HUGE),
        lambda: smoothed_distribution({"void_static": 3}, smoothing=_HUGE),
        lambda: smoothed_distribution({"void_static": _HUGE}, smoothing=0),
        lambda: kl_divergence({"void_static": _HUGE}, {"void_static": 3}, smoothing=0),
        lambda: boundary_persistence_pairwise(-_HUGE, 0.3),
        lambda: smoothed_distribution({"void_static": 3}, smoothing=-_HUGE),
        lambda: boundary_cv([0.3, 0.4], delta=-_HUGE),
    ):
        with pytest.raises(MetricsInputError) as excinfo:
            bad_call()
        assert type(excinfo.value) is MetricsInputError


def test_compute_run_metrics_huge_parameters_typed_prewrite(tmp_path) -> None:
    """compute_run_metrics with oversized smoothing / boundary_delta:
    typed MetricsInputError BEFORE any destination modification; input
    unchanged."""
    from scripts.nextness_metrics import MetricsInputError

    log = tmp_path / "ok.jsonl"
    _write_log(log, [_make_entry(generation=1, snapshot_file="a.npz"),
                     _make_entry(generation=2, snapshot_file="b.npz")])
    before = log.read_bytes()
    out = tmp_path / "d.jsonl"
    out.write_text("pre-existing destination\n", encoding="utf-8")
    dest_before = out.read_bytes()
    for kwargs in ({"smoothing": _HUGE}, {"smoothing": -_HUGE},
                   {"boundary_delta": _HUGE}, {"boundary_delta": -_HUGE}):
        with pytest.raises(MetricsInputError) as excinfo:
            compute_run_metrics(log, out, **kwargs)
        assert type(excinfo.value) is MetricsInputError
    assert log.read_bytes() == before
    assert out.read_bytes() == dest_before


# ---------------------------------------------------------------------------
# Decoder conversion-limit hole (distinct from materialized huge integers,
# which _finite_float repairs): a VALID JSON integer literal of >= 5000
# decimal digits makes the DECODER itself raise ValueError (Python's
# int-conversion digit limit) before any value exists to validate. The
# repair translates decoder-originated ValueError at the narrow
# json.loads boundary only — main() and computation catches unchanged.
# ---------------------------------------------------------------------------


def test_cli_decoder_digit_limit_rejected_located(tmp_path, capsys) -> None:
    """Public 5,000-digit valid-JSON regression: typed exit 2, empty
    stdout, exactly one located error: line, no traceback, input and
    pre-existing destination byte-identical, absent destination stays
    absent."""
    huge_literal = "1" + "0" * 4999
    log = tmp_path / "digits.jsonl"
    log.write_text(
        '{"generation": 1, "snapshot_file": "s1.npz", '
        '"token_counts": {"void_static": ' + huge_literal + '}, '
        '"boundary_rate": 0.3}' + "\n",
        encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / "digits_out.jsonl"
    out.write_text("pre-existing destination" + "\n", encoding="utf-8")
    dest_before = out.read_bytes()
    rc = main(["--log", str(log), "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert f"{log}:1" in lines[0]
    assert "Traceback" not in captured.err
    assert log.read_bytes() == before
    assert out.read_bytes() == dest_before
    absent = tmp_path / "absent_out.jsonl"
    rc2 = main(["--log", str(log), "--out", str(absent)])
    capsys.readouterr()
    assert rc2 == 2 and not absent.exists()


def test_decoder_valueerror_seam_translated(tmp_path, monkeypatch) -> None:
    """Runtime-independent seam pin: a sentinel plain ValueError raised
    by the module-local json.loads for one marked line becomes exactly
    MetricsInputError with the original as __cause__ and the log
    path/line in the message; inputs preserved, no destination created.
    (The post-validation internal plain-ValueError sentinel test above
    separately proves propagation is untouched.)"""
    import scripts.nextness_metrics as metrics_module
    from scripts.nextness_metrics import MetricsInputError

    marker = '{"generation": 1, "snapshot_file": "SEAM-MARKER.npz"}'
    log = tmp_path / "seam.jsonl"
    log.write_text(marker + "\n", encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / "seam_out.jsonl"
    real_loads = metrics_module.json.loads

    def patched(s, *args, **kwargs):
        if isinstance(s, str) and "SEAM-MARKER" in s:
            raise ValueError("sentinel decoder limit probe")
        return real_loads(s, *args, **kwargs)

    monkeypatch.setattr(metrics_module.json, "loads", patched)
    with pytest.raises(MetricsInputError) as excinfo:
        compute_run_metrics(log, out)
    monkeypatch.undo()
    assert type(excinfo.value) is MetricsInputError
    assert type(excinfo.value.__cause__) is ValueError
    assert "sentinel decoder limit probe" in str(excinfo.value)
    assert f"{log}:1" in str(excinfo.value)
    assert log.read_bytes() == before
    assert not out.exists()


# ---------------------------------------------------------------------------
# Parser deep-nesting (RecursionError) decoder totality: metrics is
# fatal located-typed at the decode boundary — a row nested deeper than
# the parser's recursion limit (while inside the byte ceilings) is a
# located typed rejection, exit 2, one concise line, no traceback; the
# run does NOT continue. Per-row containment (counted, run continues)
# is the predictor's shared reader's policy alone — metrics never
# contains a malformed row.
# ---------------------------------------------------------------------------

_DEEP_NEST_ROW = ('{"generation": 1, "token_counts": {"void_static": '
                  + "[" * 20000 + "]" * 20000 + '}}')


def test_cli_deeply_nested_row_rejected_located_typed(tmp_path, capsys) -> None:
    """Metrics is fatal-typed (not row-contained): parser RecursionError
    at the decode boundary becomes a located typed exit 2 — one line, no
    traceback, input unchanged, absent destination stays absent."""
    log = tmp_path / "nest.jsonl"
    log.write_text(_DEEP_NEST_ROW + "\n", encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / "nest_out.jsonl"
    rc = main(["--log", str(log), "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert f"{log}:1" in lines[0]
    assert "depth" in lines[0] or "nesting" in lines[0]
    assert "Traceback" not in captured.err
    assert log.read_bytes() == before
    assert not out.exists()


def test_cli_deeply_nested_row_preexisting_destination_untouched(
    tmp_path, capsys
) -> None:
    """The natural deep-nesting rejection with a PRE-EXISTING destination:
    same located typed exit 2, no traceback, input unchanged and the
    destination byte-identical (the rejection fires before any
    destination open)."""
    log = tmp_path / "nest.jsonl"
    log.write_text(_DEEP_NEST_ROW + "\n", encoding="utf-8")
    out = tmp_path / "nest_out.jsonl"
    out.write_bytes(b'{"pre-existing": true}\n')
    before = {p: p.read_bytes() for p in (log, out)}
    rc = main(["--log", str(log), "--out", str(out)])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.out == ""
    lines = [l for l in captured.err.strip().splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].startswith("error:")
    assert f"{log}:1" in lines[0]
    assert "Traceback" not in captured.err
    for p, b in before.items():
        assert p.read_bytes() == b


def test_decoder_recursionerror_seam_translated(tmp_path, monkeypatch) -> None:
    """Runtime-independent seam pin: a sentinel RecursionError raised by
    the module-local json.loads for one marked line becomes exactly
    MetricsInputError — the RecursionError is __cause__ with the exact
    sentinel message retained there, and the log path/line appears in
    the typed message; input preserved, absent destination stays
    absent. Proves the identity/cause chain of the new decode-boundary
    catch independent of any real parser depth limit."""
    import scripts.nextness_metrics as metrics_module
    from scripts.nextness_metrics import MetricsInputError

    marker = '{"generation": 1, "snapshot_file": "SEAM-MARKER.npz"}'
    log = tmp_path / "seam.jsonl"
    log.write_text(marker + "\n", encoding="utf-8")
    before = log.read_bytes()
    out = tmp_path / "seam_out.jsonl"
    real_loads = metrics_module.json.loads

    def patched(s, *args, **kwargs):
        if isinstance(s, str) and "SEAM-MARKER" in s:
            raise RecursionError("sentinel parser depth probe")
        return real_loads(s, *args, **kwargs)

    monkeypatch.setattr(metrics_module.json, "loads", patched)
    with pytest.raises(MetricsInputError) as excinfo:
        compute_run_metrics(log, out)
    monkeypatch.undo()
    assert type(excinfo.value) is MetricsInputError
    assert type(excinfo.value.__cause__) is RecursionError
    assert str(excinfo.value.__cause__) == "sentinel parser depth probe"
    assert f"{log}:1" in str(excinfo.value)
    assert "nesting exceeds the parser's depth limit" in str(excinfo.value)
    assert log.read_bytes() == before
    assert not out.exists()


def test_post_decode_recursionerror_propagates(
    tmp_path, monkeypatch, capsys
) -> None:
    """Outside-seam pin: the new decode-boundary catch is decode-call-
    local, not broad swallowing. A sentinel RecursionError raised by
    _validate_entry AFTER a successful decode propagates exactly — no
    typed conversion, no stdout/stderr output, input and pre-existing
    destination byte-identical."""
    import scripts.nextness_metrics as metrics_module

    log = tmp_path / "post.jsonl"
    log.write_text(
        '{"generation": 1, "snapshot_file": "POST-SEAM-MARKER.npz"}\n',
        encoding="utf-8",
    )
    out = tmp_path / "post_out.jsonl"
    out.write_bytes(b'{"pre-existing": true}\n')
    before = {p: p.read_bytes() for p in (log, out)}
    real_validate = metrics_module._validate_entry

    def patched(entry, log_path, line_no):
        if (type(entry) is dict
                and entry.get("snapshot_file") == "POST-SEAM-MARKER.npz"):
            raise RecursionError("sentinel post-decode recursion")
        return real_validate(entry, log_path, line_no)

    monkeypatch.setattr(metrics_module, "_validate_entry", patched)
    with pytest.raises(RecursionError) as excinfo:
        main(["--log", str(log), "--out", str(out)])
    monkeypatch.undo()
    assert type(excinfo.value) is RecursionError
    assert str(excinfo.value) == "sentinel post-decode recursion"
    captured = capsys.readouterr()
    assert captured.out == ""  # the CLI emitted nothing
    assert captured.err == ""  # no misleading concise conversion
    for p, b in before.items():
        assert p.read_bytes() == b
