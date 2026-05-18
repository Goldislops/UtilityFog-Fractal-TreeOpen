"""Across-snapshots metrics pipeline for the Nextness Observer (Phase 19 PR #3).

Consumes a ``nextness_runs.jsonl`` log written by ``scripts.nextness_observer.
process_snapshot()`` and emits a derived ``nextness_run_metrics.jsonl`` with
one row per snapshot pair plus a final aggregate row.

Reference: ``PHASE_19_PR3_METRICS_PIPELINE.md`` (design doc, merged as
``3dfc67d``). All metric formulas live there with full justification; this
module just implements them.

Scope guarantees (carried forward from PR #138 / PR #140):
    - No engine touch.
    - No writes outside the resolved output path's directory.
    - No HTTP, ZMQ, or network of any kind.
    - CPU-only.
    - allow_pickle=False (no .npz reads here; JSONL only).
    - Bounded compute: O(N * K) where N = snapshots, K = vocabulary size.

Determinism contract (per Jack's audit on PR #141):
    - Snapshots are sorted by (generation, snapshot_file, ts) before any
      pair-wise computation runs. This makes the output independent of the
      order entries happened to be written to the log file.
    - No fresh ``generated_at`` field is added to the output. Source-data
      timestamps and generations only. Re-running on the same input
      produces byte-identical output.
    - Smoothing-and-normalization for KL / JS iterates over ``TOKEN_NAMES``
      in its canonical declaration order (not whatever dict iteration order
      the caller happened to pass in).

CLI:
    python -m scripts.nextness_metrics --log <jsonl-in> --out <jsonl-out>
        [--smoothing FLOAT] [--boundary-delta FLOAT]
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.nextness_observer import (
    TOKEN_NAMES,
    boundary_rate as _boundary_rate,
    entropy_normalized as _entropy_normalized,
    shannon_entropy_bits as _shannon_entropy_bits,
    void_compute_balance as _void_compute_balance,
)


# ---------------------------------------------------------------------------
# Distribution smoothing + KL / JS divergence (design doc §4.1, §4.2)
# ---------------------------------------------------------------------------


def smoothed_distribution(
    counts: Mapping[str, int],
    smoothing: float = 1e-6,
) -> list[float]:
    """Smoothed probability vector over ``TOKEN_NAMES`` in canonical order.

    Adds ``smoothing`` to every token (whether the token fired or not),
    then divides by the resulting sum. This makes the output independent
    of caller-supplied dict iteration order and avoids divide-by-zero in
    the KL formula's log-of-ratio when a token never fires in one of the
    two distributions being compared.

    Per Jack's audit on PR #141 / design doc §4.1: this is the canonical
    algorithm; the result vector always has length ``len(TOKEN_NAMES)``
    and sums to 1.0 (within float precision).
    """
    if smoothing < 0:
        raise ValueError(f"smoothing must be non-negative, got {smoothing}")
    raw = [counts.get(tok, 0) + smoothing for tok in TOKEN_NAMES]
    total = sum(raw)
    if total <= 0:
        # Pathological: empty counts AND zero smoothing. Return uniform
        # rather than raise — divergence against uniform is well-defined
        # and tells the caller the input was effectively empty.
        return [1.0 / len(TOKEN_NAMES)] * len(TOKEN_NAMES)
    return [v / total for v in raw]


def kl_divergence(
    counts_p: Mapping[str, int],
    counts_q: Mapping[str, int],
    smoothing: float = 1e-6,
) -> float:
    """Kullback-Leibler divergence (bits) from ``p`` to ``q``.

    Computes :math:`D_{KL}(P || Q) = \\sum_i p_i \\log_2(p_i / q_i)` over
    smoothed distributions (per :func:`smoothed_distribution`). Asymmetric
    by construction; if you want a symmetric distance use
    :func:`js_divergence` instead.

    Returns 0.0 iff ``counts_p == counts_q`` after smoothing.
    """
    p = smoothed_distribution(counts_p, smoothing)
    q = smoothed_distribution(counts_q, smoothing)
    total = 0.0
    for p_i, q_i in zip(p, q):
        if p_i > 0.0:
            total += p_i * math.log2(p_i / q_i)
    return total


def js_divergence(
    counts_p: Mapping[str, int],
    counts_q: Mapping[str, int],
    smoothing: float = 1e-6,
) -> float:
    """Jensen-Shannon divergence (bits) — symmetric, bounded [0, 1].

    Computes :math:`D_{JS}(P, Q) = 0.5 D_{KL}(P || M) + 0.5 D_{KL}(Q || M)`
    where :math:`M = (P + Q) / 2`. With base-2 logarithms the output is
    bounded in [0, 1] bits, with 0 iff ``P == Q``.

    This is the **primary** drift metric for cross-snapshot comparison
    per design doc §4.2.
    """
    p = smoothed_distribution(counts_p, smoothing)
    q = smoothed_distribution(counts_q, smoothing)
    m = [(p_i + q_i) / 2.0 for p_i, q_i in zip(p, q)]
    kl_pm = 0.0
    kl_qm = 0.0
    for p_i, q_i, m_i in zip(p, q, m):
        if p_i > 0.0:
            kl_pm += p_i * math.log2(p_i / m_i)
        if q_i > 0.0:
            kl_qm += q_i * math.log2(q_i / m_i)
    return 0.5 * kl_pm + 0.5 * kl_qm


# ---------------------------------------------------------------------------
# Boundary persistence (design doc §4.3) — pairwise + raw CV + clamped score
# ---------------------------------------------------------------------------


def boundary_persistence_pairwise(
    r_prev: float,
    r_curr: float,
    delta: float = 1e-3,
) -> float:
    """Pairwise boundary-rate persistence score.

    :math:`\\pi = 1 - |r_{t} - r_{t-1}| / \\max(r_{t-1}, r_{t}, \\delta)`

    Bounded in [0, 1]: equals 1 when the two rates are identical; equals 0
    when one rate is much larger than the other AND larger than ``delta``;
    near 1 when both rates are near zero (saturated by ``delta`` in the
    denominator, so the score doesn't whipsaw on noise).

    Raises ``ValueError`` if either rate is negative.
    """
    if r_prev < 0 or r_curr < 0:
        raise ValueError(
            f"boundary rates must be non-negative; got r_prev={r_prev}, r_curr={r_curr}"
        )
    if delta <= 0:
        raise ValueError(f"delta must be positive, got {delta}")
    diff = abs(r_curr - r_prev)
    denom = max(r_prev, r_curr, delta)
    return 1.0 - diff / denom


def boundary_cv(rates: Sequence[float], delta: float = 1e-3) -> float:
    """Coefficient of variation of a sequence of boundary rates.

    :math:`\\text{CV} = \\sigma(rates) / (\\mu(rates) + \\delta)`

    Range: [0, ∞). 0 means constant rate; ≥ 1 means the standard
    deviation exceeds the mean (the failure case the original
    persistence formula had — see design doc §4.3 audit notes).

    Returns 0.0 for empty or single-element sequences (no variance
    defined).
    """
    if delta <= 0:
        raise ValueError(f"delta must be positive, got {delta}")
    if len(rates) < 2:
        return 0.0
    mean = sum(rates) / len(rates)
    var = sum((r - mean) ** 2 for r in rates) / len(rates)  # population variance
    std = math.sqrt(var)
    return std / (mean + delta)


def boundary_persistence_aggregate_clamped(
    rates: Sequence[float],
    delta: float = 1e-3,
) -> float:
    """Clamped aggregate boundary-rate persistence score.

    :math:`\\Pi = \\max(0, 1 - \\text{CV}(rates))`

    Bounded in [0, 1] by construction (per Jack's audit fix on the
    original ``1 - sigma/mu`` formula, which could go negative). High
    score = sustained rate; low score = drift or volatility.

    Returns 1.0 for empty or single-element sequences (no variation
    possible, treated as "perfectly persistent"). The aggregate is
    most meaningful for runs with N ≥ 3 snapshots.
    """
    if len(rates) < 2:
        return 1.0
    return max(0.0, 1.0 - boundary_cv(rates, delta))


# ---------------------------------------------------------------------------
# Coexistence-Crystallization Index (design doc §4.4)
# ---------------------------------------------------------------------------


def cci(balance: float, boundary: float, entropy_norm: float) -> float:
    """Coexistence-Crystallization Index.

    :math:`\\text{CCI} = B_{V/C} \\cdot R_{\\text{boundary}} \\cdot
    (1 - H_{\\text{norm}})`

    A **scoring function**, not a regime classifier. Range [0, 1] assuming
    all three inputs are in [0, 1] (the per-snapshot fields they're
    derived from are guaranteed to be).

    Interpretation guide (per design doc §4.4, post-hoc empirical):
        - High CCI: balanced VOID/COMPUTE + high boundary rate +
          concentrated token distribution. Candidate "stable coexistence."
        - Low CCI from low entropy + low boundary rate: distribution
          concentrated but boundaries collapsed. Candidate "crystallized."
        - Low CCI from high entropy: distribution spread across many
          tokens. Candidate "mixing / soup."

    PR #4 will calibrate regime thresholds; this function is just the
    score, not a binning.
    """
    return balance * boundary * (1.0 - entropy_norm)


# ---------------------------------------------------------------------------
# Orchestrator: read JSONL log → emit derived metrics JSONL (design doc §4.5)
# ---------------------------------------------------------------------------


def _sort_key(entry: dict[str, Any]) -> tuple:
    """Deterministic sort key per design doc §10 question 4.

    Priority order: ``generation`` (primary, monotonic, embedded), then
    ``snapshot_file`` (deterministic tiebreaker), then ``ts`` (final
    fallback from the snapshot itself, not a fresh datetime.now()).
    """
    return (
        entry.get("generation", 0),
        entry.get("snapshot_file", ""),
        entry.get("ts", ""),
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float extraction. Used to defend against malformed log entries."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _entry_cci(entry: dict[str, Any]) -> float:
    """CCI computed from a JSONL entry's three component fields."""
    return cci(
        _safe_float(entry.get("void_compute_balance", 0.0)),
        _safe_float(entry.get("boundary_rate", 0.0)),
        _safe_float(entry.get("entropy_normalized", 0.0)),
    )


def compute_run_metrics(
    log_path: str | pathlib.Path,
    out_path: str | pathlib.Path,
    smoothing: float = 1e-6,
    boundary_delta: float = 1e-3,
) -> dict[str, Any]:
    """Read a ``nextness_runs.jsonl`` log, emit a derived metrics JSONL.

    Produces one row per snapshot pair (in sorted order) plus a final
    ``run_aggregate`` row. Returns the aggregate summary dict for
    callers (tests, CLI) that want to inspect it without re-reading
    the output file.

    Output is byte-identical across re-runs on the same input
    (no fresh timestamps; deterministic ordering; canonical token
    iteration order in KL / JS).
    """
    log_path = pathlib.Path(log_path)
    out_path = pathlib.Path(out_path)
    if not log_path.is_file():
        raise FileNotFoundError(f"log file not found: {log_path}")

    # Load and sort
    entries: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"malformed JSONL at {log_path}:{line_no}: {e}"
                ) from e
            entries.append(entry)
    entries.sort(key=_sort_key)

    # Per-snapshot CCI values (used by both pair rows and the aggregate)
    cci_values = [_entry_cci(e) for e in entries]
    boundary_rates = [_safe_float(e.get("boundary_rate", 0.0)) for e in entries]

    # Pairwise rows
    pair_rows: list[dict[str, Any]] = []
    js_values: list[float] = []
    for i in range(1, len(entries)):
        prev_e = entries[i - 1]
        curr_e = entries[i]
        prev_counts = prev_e.get("token_counts", {}) or {}
        curr_counts = curr_e.get("token_counts", {}) or {}
        kl_val = kl_divergence(prev_counts, curr_counts, smoothing)
        js_val = js_divergence(prev_counts, curr_counts, smoothing)
        bp_val = boundary_persistence_pairwise(
            _safe_float(prev_e.get("boundary_rate", 0.0)),
            _safe_float(curr_e.get("boundary_rate", 0.0)),
            boundary_delta,
        )
        pair_rows.append({
            "summary_type": "pair",
            "prev_generation": prev_e.get("generation"),
            "curr_generation": curr_e.get("generation"),
            "prev_snapshot_file": prev_e.get("snapshot_file"),
            "curr_snapshot_file": curr_e.get("snapshot_file"),
            "kl_divergence_bits": kl_val,
            "js_divergence_bits": js_val,
            "boundary_persistence_pairwise": bp_val,
            "cci_prev": cci_values[i - 1],
            "cci_curr": cci_values[i],
        })
        js_values.append(js_val)

    # Aggregate
    n = len(entries)
    n_pairs = len(pair_rows)
    if cci_values:
        mean_cci = sum(cci_values) / n
        var_cci = sum((c - mean_cci) ** 2 for c in cci_values) / n
        std_cci = math.sqrt(var_cci)
        min_cci = min(cci_values)
        max_cci = max(cci_values)
        argmin_idx = cci_values.index(min_cci)
        argmax_idx = cci_values.index(max_cci)
        argmin_file = entries[argmin_idx].get("snapshot_file")
        argmax_file = entries[argmax_idx].get("snapshot_file")
    else:
        mean_cci = std_cci = min_cci = max_cci = 0.0
        argmin_file = argmax_file = None

    if js_values:
        mean_js = sum(js_values) / n_pairs
        var_js = sum((j - mean_js) ** 2 for j in js_values) / n_pairs
        std_js = math.sqrt(var_js)
    else:
        mean_js = std_js = 0.0

    aggregate: dict[str, Any] = {
        "summary_type": "run_aggregate",
        "n_snapshots": n,
        "n_pairs": n_pairs,
        "mean_js_divergence_bits": mean_js,
        "std_js_divergence_bits": std_js,
        "mean_cci": mean_cci,
        "std_cci": std_cci,
        "min_cci": min_cci,
        "max_cci": max_cci,
        "argmin_cci_snapshot": argmin_file,
        "argmax_cci_snapshot": argmax_file,
        "boundary_cv": boundary_cv(boundary_rates, boundary_delta),
        "boundary_persistence_aggregate_clamped": boundary_persistence_aggregate_clamped(
            boundary_rates, boundary_delta
        ),
    }

    # Write output deterministically. Note: NO ``generated_at`` field.
    # ``sort_keys=True`` makes the JSON field order deterministic too.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in pair_rows:
            f.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        f.write(json.dumps(aggregate, sort_keys=True, default=str) + "\n")

    return aggregate


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.nextness_metrics",
        description=(
            "Compute across-snapshots metrics on a Nextness Observer "
            "JSONL log. Emits a derived JSONL with one row per snapshot "
            "pair plus a final aggregate row. Deterministic: re-running "
            "on the same input produces byte-identical output."
        ),
    )
    parser.add_argument(
        "--log",
        required=True,
        help="Path to input nextness_runs.jsonl",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path for output nextness_run_metrics.jsonl",
    )
    parser.add_argument(
        "--smoothing",
        type=float,
        default=1e-6,
        help="Laplace smoothing constant for KL/JS (default: 1e-6)",
    )
    parser.add_argument(
        "--boundary-delta",
        type=float,
        default=1e-3,
        help="Stabilization constant for boundary metrics (default: 1e-3)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on success, non-zero on error."""
    args = _build_parser().parse_args(argv)
    log_path = pathlib.Path(args.log)
    out_path = pathlib.Path(args.out)
    if not log_path.is_file():
        print(f"error: log file not found: {log_path}", file=sys.stderr)
        return 1
    try:
        agg = compute_run_metrics(
            log_path, out_path,
            smoothing=args.smoothing,
            boundary_delta=args.boundary_delta,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    # Compact stdout summary
    print(f"Wrote {out_path}")
    print(f"  n_snapshots: {agg['n_snapshots']}")
    print(f"  n_pairs: {agg['n_pairs']}")
    print(f"  mean_cci: {agg['mean_cci']:.4f}  (std: {agg['std_cci']:.4f})")
    print(f"  mean_js_divergence_bits: {agg['mean_js_divergence_bits']:.4f}  "
          f"(std: {agg['std_js_divergence_bits']:.4f})")
    print(f"  boundary_cv: {agg['boundary_cv']:.4f}")
    print(f"  boundary_persistence_aggregate_clamped: "
          f"{agg['boundary_persistence_aggregate_clamped']:.4f}")
    return 0


__all__ = [
    "smoothed_distribution",
    "kl_divergence",
    "js_divergence",
    "boundary_persistence_pairwise",
    "boundary_cv",
    "boundary_persistence_aggregate_clamped",
    "cci",
    "compute_run_metrics",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
