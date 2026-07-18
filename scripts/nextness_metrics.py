"""Across-snapshots metrics pipeline for the Nextness Observer (Phase 19 PR #3).

Consumes a ``nextness_runs.jsonl`` log written by ``scripts.nextness_observer.
process_snapshot()`` and emits a derived ``nextness_run_metrics.jsonl`` with
one row per snapshot pair plus a final aggregate row.

Reference: ``PHASE_19_PR3_METRICS_PIPELINE.md`` (design doc, merged as
``3dfc67d``). All metric formulas live there with full justification; this
module just implements them.

Scope guarantees (carried forward from PR #138 / PR #140):
    - No engine touch.
    - **No writes outside ``log_path.parent``** — the output ``--out`` path
      must resolve to a location inside the same directory as the input
      JSONL log. Enforced via :class:`WriteOutsideLogDirError` reused
      from ``scripts.nextness_observer``; the safety vocabulary is
      unified across modules.
    - **No writes onto the input log itself** — an ``--out`` that names or
      aliases ``log_path`` (direct path, lexical variant, symlink, hard
      link) is refused by resolved path and by file identity
      (``os.path.samefile`` on resolved paths), failing closed when an
      existing output's identity cannot be verified. Identity is checked
      at validation time, before the log is read or any metric computed;
      the later write does not re-verify (documented residual race, same
      statement as the Nextness NP6/NP8 guards).
    - **Byte-exact output** — the derived JSONL is written in binary mode:
      each row is its canonical ``json.dumps(..., sort_keys=True,
      default=str)`` serialization encoded as UTF-8 plus a single LF
      byte, streamed row by row, immune to platform newline translation.
    - No HTTP, ZMQ, or network of any kind.
    - CPU-only.
    - allow_pickle=False (no .npz reads here; JSONL only).
    - Bounded compute: O(N * K) where N = snapshots, K = vocabulary size —
      and N is now ENFORCED per invocation (``max_rows``, ceiling
      ``MAX_ROWS_CEILING``) rather than assumed small: raw physical JSONL
      records (blank and rejected included) are counted against
      ``max_rows``, each record's content is capped at ``max_line_bytes``
      raw bytes (LF/CRLF terminator excluded) via bounded binary reads
      that never materialize an oversized record in full, and an input
      exceeding ``max_rows`` is a typed refusal — never a silent prefix
      summary. No output-size ceiling is added: the derived JSONL remains
      un-ceilinged by documented contract.

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
        [--max-rows INT] [--max-line-bytes INT]

    Exit codes: 0 success · 1 missing log (``error:``) · 2 data/validation
    failure (``error:``; argparse usage errors also exit 2) · 3 pre-write
    containment/identity/directory safety refusal (``safety error:``) ·
    4 operational output-write failure (``error:``). Expected failures
    print one concise line, never a traceback. The exit-2 catch set is
    the typed ``MetricsInputError`` plus the ``FileNotFoundError``
    validation-to-read race lane; exceptions outside the documented
    catch set — including plain ``ValueError`` and read-side OSErrors —
    propagate rather than being reclassified.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from scripts.nextness_observer import (
    TOKEN_NAMES,
    WriteOutsideLogDirError,
    boundary_rate as _boundary_rate,
    entropy_normalized as _entropy_normalized,
    shannon_entropy_bits as _shannon_entropy_bits,
    void_compute_balance as _void_compute_balance,
)


class MetricsOutputWriteError(RuntimeError):
    """Operational failure in the derived output's write region.

    Raised only from the OUTPUT region of :func:`compute_run_metrics` —
    output-parent creation plus the binary open/write/close — never for
    read-side or computation errors, which stay loud. The CLI maps this
    to its own exit code (4) so callers can distinguish "the output
    could not be produced operationally" from a pre-write safety refusal
    (exit 3, ``WriteOutsideLogDirError``), a data error (exit 2), and a
    missing input log (exit 1).

    Destination-preservation contract, stated precisely: a failure at or
    before the binary open (e.g. a read-only destination, or a failed
    parent mkdir) leaves any existing destination byte-identical —
    nothing was truncated. Once the binary open has succeeded, output is
    direct, streamed and non-atomic, so a later write or close failure
    may leave a truncated or partial destination. In the exercised
    failure lanes, and absent the documented validation-to-write
    replacement race, the input log remains unchanged. This repair adds
    no stronger input-log guarantee: a concurrent actor may still
    redirect the later direct write, as the existing TOCTOU non-claim
    states. No atomic-write behavior is provided or claimed.
    """


class MetricsInputError(ValueError):
    """Genuine input/configuration failure (typed input boundary).

    Subclasses ``ValueError`` so direct-Python callers catching the base
    class remain compatible; the CLI's exit-2 catch names exactly this
    class (plus the ``FileNotFoundError`` validation-to-read race lane),
    so a plain internal ``ValueError`` propagates instead of
    masquerading as a data failure (metrics typed-boundary pilot).
    """


# ---------------------------------------------------------------------------
# Input-work bounds (Jack policy decision 2026-07-18). The values mirror
# the shared predictor reader's established constants; the enforcement
# policy deliberately does NOT: metrics summarizes a COMPLETE run, so an
# input with more physical records than ``max_rows`` is a typed refusal,
# never a silent prefix truncation — metrics computed from a prefix would
# misrepresent a complete-run result. Line size is raw record content in
# bytes (LF or CRLF terminator excluded), enforced with bounded binary
# ``readline(max_line_bytes + 2)`` probes so an oversized record is never
# materialized in full and never drained past.
# ---------------------------------------------------------------------------

#: Default cap on physical JSONL records (blank and rejected included).
MAX_ROWS_DEFAULT = 100_000

#: Hard ceiling on the ``max_rows`` parameter itself.
MAX_ROWS_CEILING = 1_000_000

#: Default cap on one record's content bytes (terminator excluded).
MAX_LINE_BYTES_DEFAULT = 65_536


# ---------------------------------------------------------------------------
# Write-boundary guard (Lane B safety contract; mirrors the helper in
# nextness_observer.py without coupling to its private name)
# ---------------------------------------------------------------------------


def _validate_metrics_output_path(
    out_path: pathlib.Path,
    log_path: pathlib.Path,
) -> None:
    """Refuse output paths that resolve outside the input log's directory.

    The Lane B safety contract requires that derived metrics output land
    only inside ``log_path.parent``. This catches both literal mismatches
    (``--out /tmp/other.jsonl``) and traversal/symlink escapes
    (``--out ../somewhere_else/out.jsonl``). Resolves both paths to
    canonical absolute form before comparing — symlink-aware.

    Per Jack's audit on PR #142: the PR body and module docstring claim
    "no writes outside log_directory," and this function makes that
    claim true rather than aspirational. Raises
    :class:`WriteOutsideLogDirError` (reused from
    ``scripts.nextness_observer``) so the safety vocabulary stays
    unified across both modules.

    Directory-target guard: an ``out_path`` that resolves to an existing
    directory (including through a symlink) is refused here in the same
    boundary lane — the binary open would otherwise raise
    ``IsADirectoryError``/``PermissionError`` as an uncaught traceback
    only after the log had been read and every metric computed.

    Input-identity guard (Nextness NP6/NP8 convention): the output may
    also never BE the input log — refused by resolved path (which
    covers the direct path, lexical variants like ``sub/../log.jsonl``
    and symlink aliases: resolution targets are compared, not link or
    segment names) and by file identity (``os.path.samefile`` on the
    RESOLVED paths: device + inode / file ID, covering existing hard
    links whose paths differ). Any failure to verify an existing
    output's identity is itself a refusal — fail closed, never a
    fall-through.

    Residual filesystem race, stated precisely: identity is verified at
    validation time; the later write does not re-verify. A concurrent
    actor replacing the output path between validation and write can
    still redirect the write. This guard defends against aliases that
    exist when it validates — it does not claim to eliminate the
    validation-to-write (TOCTOU) interval.
    """
    log_resolved = log_path.resolve()
    log_dir_resolved = log_resolved.parent
    out_resolved = out_path.resolve()
    try:
        out_resolved.relative_to(log_dir_resolved)
    except ValueError as e:
        raise WriteOutsideLogDirError(
            f"refusing to write metrics output outside log_path's directory: "
            f"{out_resolved} is not inside {log_dir_resolved}"
        ) from e
    # An existing directory (or a symlink resolving to one) can never be
    # a metrics output file. Refuse here, in the established boundary
    # lane, rather than letting the later binary open escape as an
    # IsADirectoryError/PermissionError traceback after computation.
    if out_resolved.is_dir():
        raise WriteOutsideLogDirError(
            f"refusing to write metrics output onto a directory: {out_resolved}"
        )
    if out_resolved == log_resolved:
        raise WriteOutsideLogDirError(
            f"refusing to overwrite the input log file: {out_resolved}"
        )
    # Hard links share identity while having distinct paths. Only an
    # EXISTING output can alias the input; stat runs on the resolved
    # paths and any failure to verify is itself a refusal (fail closed),
    # never a fall-through.
    if out_resolved.exists():
        try:
            same = os.path.samefile(out_resolved, log_resolved)
        except OSError as e:
            raise WriteOutsideLogDirError(
                f"cannot verify output file identity against the input log "
                f"file: {out_resolved}"
            ) from e
        if same:
            raise WriteOutsideLogDirError(
                f"refusing to overwrite the input log file (shared file "
                f"identity): {out_resolved}"
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
    if (isinstance(smoothing, bool) or not isinstance(smoothing, (int, float))
            or _finite_float(smoothing) is None or smoothing < 0):
        raise MetricsInputError(
            f"smoothing must be finite and non-negative, got {smoothing!r}"
        )
    try:
        raw = [counts.get(tok, 0) + smoothing for tok in TOKEN_NAMES]
    except OverflowError as e:
        raise MetricsInputError(
            "token counts are too large for finite arithmetic"
        ) from e
    total = sum(raw)
    if any(_finite_float(v) is None for v in raw) or _finite_float(total) is None:
        raise MetricsInputError(
            "token counts and smoothing produce non-finite arithmetic"
        )
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
    for i, (p_i, q_i) in enumerate(zip(p, q)):
        if p_i > 0.0:
            if q_i == 0.0:
                # Zero smoothing keeps its authorized non-negative
                # policy, but KL is mathematically undefined here.
                raise MetricsInputError(
                    f"KL divergence is undefined for token "
                    f"{TOKEN_NAMES[i]!r}: positive support in P with "
                    f"zero support in Q; positive smoothing is required"
                )
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

    Raises ``MetricsInputError`` (a ``ValueError`` subclass) for
    out-of-type or out-of-domain rates and invalid deltas (§9.4 strict
    input domain: real non-boolean numbers, finite, rates in [0, 1],
    delta finite and strictly positive).
    """
    r_prev = _require_rate(r_prev, "r_prev")
    r_curr = _require_rate(r_curr, "r_curr")
    delta = _require_delta(delta)
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
    delta = _require_delta(delta)
    rates = [_require_rate(r, f"rates[{i}]") for i, r in enumerate(rates)]
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
    delta = _require_delta(delta)
    rates = [_require_rate(r, f"rates[{i}]") for i, r in enumerate(rates)]
    if len(rates) < 2:
        return 1.0
    # Explicit two-sided clamp: with the §9.4 domain (rates in [0, 1],
    # delta > 0) the CV is non-negative so the upper clamp is a no-op
    # for valid input — it makes the documented bound structural.
    return min(1.0, max(0.0, 1.0 - boundary_cv(rates, delta)))


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
    """Best-effort float extraction. Used to defend against malformed log entries.

    Legacy permissive surface: with the strict input domain (§9.4) every
    present unit field is validated BEFORE this runs, so on the CLI path
    this now only realizes the documented absent-field -> 0.0 policy.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Strict input domain (design doc §9.4; Kev-authorized policy)
# ---------------------------------------------------------------------------

_UNIT_FIELDS = ("boundary_rate", "entropy_normalized", "void_compute_balance")


def _finite_float(value: Any) -> float | None:
    """Finite-computability conversion for an already type-accepted
    int/float (§9.4 totality — NOT a semantic magnitude cap): returns
    the finite float, or ``None`` when the value cannot participate in
    finite float arithmetic (conversion overflow, e.g. an integer of
    magnitude 10**400, or a non-finite result). Catches ONLY the
    expected conversion ``OverflowError``."""
    try:
        converted = float(value)
    except OverflowError:
        return None
    return converted if math.isfinite(converted) else None


def _reject_json_constant(name: str) -> float:
    """json.loads parse_constant hook: NaN/Infinity/-Infinity are refused."""
    raise MetricsInputError(f"non-standard JSON constant {name} is not allowed")


def _require_rate(value: Any, name: str) -> float:
    """A rate/unit value must be a real, non-boolean JSON number, finite
    and within [0, 1] (finite-computability totality: an oversized
    integer is a typed rejection, never a raw ``OverflowError``)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsInputError(
            f"{name} must be a JSON number in [0, 1], got {value!r}"
        )
    v = _finite_float(value)
    if v is None or not 0.0 <= v <= 1.0:
        raise MetricsInputError(
            f"{name} must be finite and within [0, 1], got {value!r}"
        )
    return v


def _require_delta(delta: Any) -> float:
    """delta must be a real, non-boolean, finite, strictly positive
    number (finite-computability totality on oversized integers)."""
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        raise MetricsInputError(f"delta must be positive and finite, got {delta!r}")
    v = _finite_float(delta)
    if v is None or v <= 0:
        raise MetricsInputError(f"delta must be positive and finite, got {delta!r}")
    return v


def _validate_entry(entry: Any, log_path: pathlib.Path, line_no: int) -> None:
    """Strict per-entry domain validation (fail closed, typed).

    Present unit fields must be real JSON numbers (no booleans, strings
    or null), finite, within [0, 1]. An ABSENT unit field remains the
    explicitly chosen 0.0 compatibility policy (established in §9.4, not
    historical proof from PR #141). token_counts, when the key is
    present, must be a JSON object of non-boolean, non-negative integer
    counts (the shape the canonical distributions consume).
    """
    if type(entry) is not dict:
        raise MetricsInputError(
            f"log entry must be a JSON object at {log_path}:{line_no}"
        )
    for field in _UNIT_FIELDS:
        if field not in entry:
            continue
        value = entry[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MetricsInputError(
                f"{field} must be a JSON number in [0, 1], "
                f"got {value!r} at {log_path}:{line_no}"
            )
        converted = _finite_float(value)
        if converted is None or not 0.0 <= converted <= 1.0:
            raise MetricsInputError(
                f"{field} must be finite and within [0, 1], "
                f"got {value!r} at {log_path}:{line_no}"
            )
    if "token_counts" in entry:
        counts = entry["token_counts"]
        if type(counts) is not dict:
            raise MetricsInputError(
                f"token_counts must be a JSON object at {log_path}:{line_no}"
            )
        for key, count in counts.items():
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise MetricsInputError(
                    f"token_counts[{key!r}] must be a non-negative, "
                    f"non-boolean integer, got {count!r} at {log_path}:{line_no}"
                )
            # Finite-computability constraint (not an arbitrary semantic
            # cap): the count must participate in finite float
            # arithmetic for the canonical distributions.
            try:
                as_float = float(count)
            except OverflowError as e:
                raise MetricsInputError(
                    f"token_counts[{key!r}] is too large for finite "
                    f"arithmetic at {log_path}:{line_no}"
                ) from e
            if not math.isfinite(as_float):
                raise MetricsInputError(
                    f"token_counts[{key!r}] is too large for finite "
                    f"arithmetic at {log_path}:{line_no}"
                )


def _require_finite_tree(value: Any, location: str) -> None:
    """RECURSIVE pre-write invariant: no non-finite float may reach the
    serialized output anywhere — top level or nested inside built-in
    containers (covers computed AND pass-through fields; runs before any
    destination is touched, so it can never truncate or partially write).

    Hook-safe by construction: only exact built-in ``dict``/``list``/
    ``tuple`` containers are traversed and only exact built-in ``float``
    values are inspected — no subclass hooks (``__iter__``/``keys``/
    ``__float__``) are ever invoked.
    """
    if type(value) is float:
        if not math.isfinite(value):
            raise MetricsInputError(
                f"non-finite value in derived output: {location}={value!r}"
            )
    elif type(value) is dict:
        for key, item in value.items():
            _require_finite_tree(item, f"{location}.{key}" if location else str(key))
    elif type(value) in (list, tuple):
        for index, item in enumerate(value):
            _require_finite_tree(item, f"{location}[{index}]")


def _require_finite_row(row: dict[str, Any]) -> None:
    """Recursive whole-row finiteness (see :func:`_require_finite_tree`)."""
    for key, value in row.items():
        _require_finite_tree(value, str(key))


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
    max_rows: int = MAX_ROWS_DEFAULT,
    max_line_bytes: int = MAX_LINE_BYTES_DEFAULT,
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

    # Lane B safety contract (Jack's audit on PR #142): out_path must
    # resolve under log_path.parent. Validate BEFORE any disk side effects
    # — no parent-mkdir, no file open, no writes — happen.
    _validate_metrics_output_path(out_path, log_path)

    # §9.4 strict numeric parameters (typed, before any read work).
    if (isinstance(smoothing, bool) or not isinstance(smoothing, (int, float))
            or _finite_float(smoothing) is None or smoothing < 0):
        raise MetricsInputError(
            f"smoothing must be finite and non-negative, got {smoothing!r}"
        )
    if (isinstance(boundary_delta, bool)
            or not isinstance(boundary_delta, (int, float))
            or _finite_float(boundary_delta) is None or boundary_delta <= 0):
        raise MetricsInputError(
            f"boundary_delta must be finite and positive, got {boundary_delta!r}"
        )

    # Input-work bounds: validated typed BEFORE any input reading (the
    # log is never opened for an invalid bound).
    if (isinstance(max_rows, bool) or not isinstance(max_rows, int)
            or not 0 < max_rows <= MAX_ROWS_CEILING):
        raise MetricsInputError(
            f"max_rows must be a non-boolean integer in "
            f"(0, {MAX_ROWS_CEILING}], got {max_rows!r}"
        )
    if (isinstance(max_line_bytes, bool) or not isinstance(max_line_bytes, int)
            or max_line_bytes <= 0):
        raise MetricsInputError(
            f"max_line_bytes must be a positive non-boolean integer, "
            f"got {max_line_bytes!r}"
        )

    # Load and sort. The UnicodeDecodeError wrap restores the pre-typed
    # public contract for an undecodable log (genuine bad input, concise
    # exit 2): it is caught EXACTLY — never UnicodeError/ValueError/
    # OSError — and re-raised as MetricsInputError(str(e)) so the stderr
    # bytes match the pre-#381 lane while read-side OSErrors keep
    # propagating.
    entries: list[dict[str, Any]] = []
    try:
        with log_path.open("rb") as f:
            line_no = 0
            while True:
                # Pre-allocation bound: at most max_line_bytes + 2 bytes
                # are ever probed per record (content + LF/CRLF), so an
                # oversized record is never materialized in full.
                chunk = f.readline(max_line_bytes + 2)
                if not chunk:
                    break  # EOF
                line_no += 1
                if line_no > max_rows:
                    # Fail closed on excess input: metrics summarizes a
                    # COMPLETE run, so more physical records than
                    # max_rows is a located typed refusal — deliberately
                    # NOT the predictor's truncating row budget, because
                    # metrics silently computed from a prefix would
                    # misrepresent a complete-run result.
                    raise MetricsInputError(
                        f"more than {max_rows} physical records "
                        f"(max_rows) at {log_path}:{line_no}; refusing "
                        f"to summarize a prefix"
                    )
                if chunk.endswith(b"\n"):
                    # LF or CRLF terminator — excluded from the content
                    # bound (a record of exactly max_line_bytes content
                    # plus either terminator fits the probe).
                    content = (chunk[:-2] if chunk.endswith(b"\r\n")
                               else chunk[:-1])
                else:
                    # EOF-unterminated record, or a probe that hit the
                    # read limit mid-record (already past the bound
                    # either way).
                    content = chunk
                if len(content) > max_line_bytes:
                    # Never drained past: the refusal is fatal-typed
                    # (unlike the reader's counted terminal skip).
                    raise MetricsInputError(
                        f"line exceeds {max_line_bytes} bytes at "
                        f"{log_path}:{line_no}"
                    )
                stripped = content.decode("utf-8").strip()
                if not stripped:
                    # Blank records are not observations, but they still
                    # consume physical-row budget (bounded work).
                    continue
                try:
                    entry = json.loads(
                        stripped, parse_constant=_reject_json_constant
                    )
                except json.JSONDecodeError as e:
                    raise MetricsInputError(
                        f"malformed JSONL at {log_path}:{line_no}: {e}"
                    ) from e
                except MetricsInputError as e:
                    # A valid JSON extension token (NaN/Infinity) refused
                    # by policy — locate it precisely without mislabeling
                    # it an ordinary JSONDecodeError; cause preserved.
                    raise MetricsInputError(
                        f"invalid JSON value at {log_path}:{line_no}: {e}"
                    ) from e
                except ValueError as e:
                    # Decoder-originated ValueError scoped to THIS
                    # json.loads call only (e.g. Python's int-conversion
                    # digit limit on a valid JSON integer literal) —
                    # translated to a located typed rejection. main()'s
                    # catch set and the computation catches are NOT
                    # broadened; an internal post-validation plain
                    # ValueError still propagates (sentinel-pinned).
                    raise MetricsInputError(
                        f"malformed JSONL at {log_path}:{line_no}: {e}"
                    ) from e
                except RecursionError as e:
                    # Parser depth limit hit inside the byte ceiling —
                    # metrics is fatal-typed (not row-contained), so this
                    # decode-boundary RecursionError becomes a located
                    # typed rejection. RecursionError outside this seam
                    # is not swallowed anywhere and still propagates.
                    raise MetricsInputError(
                        f"malformed JSONL at {log_path}:{line_no}: "
                        f"nesting exceeds the parser's depth limit"
                    ) from e
                _validate_entry(entry, log_path, line_no)
                entries.append(entry)
    except UnicodeDecodeError as e:
        raise MetricsInputError(str(e)) from e
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
    # Binary mode, streamed row by row: each line is the canonical
    # serialization encoded as UTF-8 plus a single LF byte, so the
    # derived file's bytes never depend on platform newline translation.
    #
    # The OSError catch is deliberately confined to the OUTPUT region —
    # parent-directory creation plus the binary open/write/close: an
    # operational failure anywhere in it (unwritable parent, read-only
    # destination, mid-stream device error) becomes the typed
    # MetricsOutputWriteError, while read-side or computation errors
    # above are NEVER reclassified as output failures and stay loud.
    # Failures at or before open leave an existing destination
    # byte-identical; after a successful open, streamed non-atomic
    # output may be truncated/partial if a later write or close fails.
    # §9.4 pre-write invariant: every float in every row (computed AND
    # pass-through) must be finite. This runs BEFORE parent-mkdir/open,
    # so a rejection preserves any existing destination byte-identically
    # and creates nothing — it adds no partial-output claim and leaves
    # the streamed, non-atomic write contract below unchanged.
    for row in (*pair_rows, aggregate):
        _require_finite_row(row)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("wb") as f:
            # allow_nan=False: strict-JSON serialization backstop. With
            # the invariant above it is unreachable; a ValueError here
            # would be an internal contract failure and propagates
            # loudly (it is not an OSError).
            for row in pair_rows:
                f.write(json.dumps(row, sort_keys=True, default=str,
                                   allow_nan=False).encode("utf-8") + b"\n")
            f.write(json.dumps(aggregate, sort_keys=True, default=str,
                               allow_nan=False).encode("utf-8") + b"\n")
    except OSError as e:
        raise MetricsOutputWriteError(
            f"cannot write metrics output to {out_path}: {e}"
        ) from e

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
    parser.add_argument(
        "--max-rows",
        type=int,
        default=MAX_ROWS_DEFAULT,
        help=(
            f"Cap on physical JSONL records, blank and rejected included "
            f"(default: {MAX_ROWS_DEFAULT}; ceiling {MAX_ROWS_CEILING}). "
            f"An input with more records is a typed refusal, never a "
            f"silent prefix summary."
        ),
    )
    parser.add_argument(
        "--max-line-bytes",
        type=int,
        default=MAX_LINE_BYTES_DEFAULT,
        help=(
            f"Cap on one record's content bytes, LF/CRLF terminator "
            f"excluded (default: {MAX_LINE_BYTES_DEFAULT}). Enforced "
            f"with bounded reads before any record is materialized "
            f"in full."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Exit-code contract (complete map; each expected failure prints one
    concise prefixed line to stderr, never a traceback):

    - ``0`` success (multi-line summary on stdout; derived JSONL written)
    - ``1`` missing input log (``error:``)
    - ``2`` data/validation failure — malformed JSONL or out-of-bounds
      configuration (``error:``; argparse's own usage errors also exit 2)
    - ``3`` pre-write containment/identity/directory safety refusal
      (``safety error:``, ``WriteOutsideLogDirError``) — the guard runs
      before the log is read or any metric computed
    - ``4`` operational output-write failure (``error:``,
      ``MetricsOutputWriteError``) — an OSError in the output region:
      parent creation, binary open, streamed writes, or close. In the
      exercised failure lanes, and absent the documented
      validation-to-write replacement race, the input log remains
      unchanged; this repair adds no stronger input-log guarantee — a
      concurrent actor may still redirect the later direct write, as
      the existing TOCTOU non-claim states. Destination preservation is
      guaranteed only for failures at or before the binary open (a
      read-only destination is never truncated); once open succeeds,
      direct streamed non-atomic output may be truncated or partial if
      a later write/close fails — no atomic-write claim is made.

    The documented catch set is exactly ``MetricsOutputWriteError``
    (exit 4), ``WriteOutsideLogDirError`` (exit 3, ``safety error:``)
    and the typed ``MetricsInputError`` plus ``FileNotFoundError`` (exit
    2 — the data lane and the validation-to-read race lane). Exceptions
    outside it — including plain ``ValueError`` — propagate (metrics
    typed-boundary pilot; test-pinned), and read-side ``OSError``
    exceptions in particular are never reclassified as output failures
    (test-pinned). Direct-Python note: callers catching ``ValueError``
    remain compatible because ``MetricsInputError`` subclasses it, but
    the exact exception type at the five reclassified sites (malformed
    JSONL, negative smoothing, the existing negative-rate guard in
    ``boundary_persistence_pairwise``, non-positive pairwise delta,
    non-positive CV delta) is now ``MetricsInputError``.
    """
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
            max_rows=args.max_rows,
            max_line_bytes=args.max_line_bytes,
        )
    except MetricsOutputWriteError as e:
        # Operational write failure: the output could not be written
        # even though every pre-write safety check passed.
        print(f"error: {e}", file=sys.stderr)
        return 4
    except WriteOutsideLogDirError as e:
        # Lane B safety violation: --out points outside the log file's
        # directory. Return distinct non-zero code so callers can
        # distinguish safety refusals from data errors.
        print(f"safety error: {e}", file=sys.stderr)
        return 3
    except (MetricsInputError, FileNotFoundError) as e:
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
    "MetricsInputError",
    "MetricsOutputWriteError",
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
