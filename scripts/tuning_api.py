"""Phase 18 PR 2 — Tuning API Blueprint.

Adds write-side tuning endpoints on top of the Phase 16 REST surface:

  GET  /api/params            — current effective params (dict)
  GET  /api/params/schema     — full registry schema from params_schema
  POST /api/tuning/propose    — validate + append to ledger; dry-run by default
  POST /api/tuning/commit     — gated commit; writes tuning_pending.json
  POST /api/tuning/rollback   — revert to a prior proposal's snapshot

Persists an append-only JSONL ledger at `data/tuning_ledger.jsonl` and a
single-file pending-tuning at `data/tuning_pending.json`. The engine-side
reload consumer (that actually reads tuning_pending.json and applies the
parameters to the running CA) is a later PR in the Phase 18 roadmap.
For now, the pending file is an authoritative promise waiting to be picked up.

Safety contract enforced here:
  - LOCKED params always rejected at `propose` (via params_schema.validate_proposal).
  - The autonomous ``policy:auto`` commit approver is rejected at the commit
    boundary (``AUTO_COMMIT_APPROVER`` / ``auto_commit_disabled``). This closes
    the legacy orchestrator's only write identity: it commits with
    ``approver="policy:auto"`` (see ``scripts/orchestrator.py`` ToolRouter),
    so with this path shut, no LLM-facing tool call can mutate a parameter —
    the protection lives at the server boundary, not in a prompt or tool list.
    A deliberate human commit (``approver="human:<name>"``) is unaffected.
  - HUMAN_APPROVAL params require `approver` starting with `human:` at commit.
  - Per-parameter rate limit (MIN_GEN_BETWEEN_COMMITS_PER_PARAM generations).
  - Invalid proposals cannot be committed even if approver is otherwise sufficient.

Scope note: this module does NOT authenticate callers or make the tuning API
generally secure. It closes exactly the proven ``policy:auto`` auto-commit path;
propose/dry-run, reads, and human-approved commits are intentionally unchanged.
"""

from __future__ import annotations

import json
import math
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from flask import Blueprint, Response, jsonify, request

from scripts.params_schema import (
    MAX_TUNING_INT_BITS,
    PARAMS,
    Category,
    get_param,
    schema_as_dict,
    validate_proposal,
)


MIN_GEN_BETWEEN_COMMITS_PER_PARAM = 1000
"""Minimum generations between successive commits touching the same parameter.
Prevents an LLM in a tight loop from oscillating a tunable."""

VALID_MODES = ("dry-run", "commit-pending")

AUTO_COMMIT_APPROVER = "policy:auto"
"""The autonomous approver identity the legacy orchestrator commits with.

Stored lowercase; the commit boundary compares against ``approver.strip()
.casefold()`` so whitespace- and case-variant spellings of the same autonomous
identity are all rejected (``auto_commit_disabled``). Re-enabling autonomous
commits must be a reviewed code change here — there is deliberately no env flag,
query param, header, or alternate route that turns it back on."""

BAD_REQUEST_MESSAGE = "request envelope has a malformed value shape."
"""Fixed generic refusal for a malformed request envelope. It reports neither
the supplied value nor its type name, so no proposed object's ``__str__`` /
``__repr__`` is executed and no attacker-chosen text enters a response, the
ledger, or an event payload."""

_MAX_REQUEST_VALUE_DEPTH = 64
"""Container-nesting depth accepted while proving a proposed parameter VALUE is
a builtin JSON tree. This bounds the recursion so a cyclic DIRECT value cannot
loop; it is not a limit on scalar content. Values obtainable through parsed
JSON are far shallower, so no valid public request is affected (recorded as a
residual — see docs/LEGACY_ORCHESTRATOR_QUARANTINE.md)."""

_MAX_REQUEST_NODES = 100_000
"""Proposal-wide cap on nodes VISITED while proving the parameter values of
ONE complete proposal are JSON trees — a single budget charged across every
value, not restarted per parameter entry (multiple entries sharing repeated
structure would otherwise multiply the cap). The depth bound alone stops
cycles/recursion but not a shared-reference DAG (a DIRECT value where a node
is referenced repeatedly), which would otherwise be traversed — and later
``json.dumps``-expanded — an exponential number of times. Counting visits per
occurrence mirrors that serialisation cost and refuses such a proposal before
the ledger write. Set far above any realistic parsed-JSON request (JSON cannot
express sharing, so PUBLIC bodies are self-limiting), so no valid request is
affected; recorded as a residual bound — see
docs/LEGACY_ORCHESTRATOR_QUARANTINE.md."""


# -- helpers ----------------------------------------------------------------


def _is_exact_json_tree(value: Any, depth: int, budget: list) -> bool:
    """True when ``value`` is EXACTLY a builtin standard-JSON tree: exact
    ``str``, exact ``bool``, exact ``int`` within ``MAX_TUNING_INT_BITS``,
    exact FINITE ``float``, ``None``, or an exact ``list`` / exact ``dict``
    (with exact-``str`` keys) recursively within ``depth`` and within the
    ``budget`` node-visit count (``budget`` is ``[remaining]``, mutated in
    place and shared across every value of one proposal). Decided by ``type``
    identity — a refused value's methods are never invoked, only confirmed
    exact builtin containers are traversed, and the int width check runs only
    after the exact-``int`` proof (bool is accepted separately, never routed
    through ``bit_length``). A proposed parameter value that passes is
    guaranteed ``json.dumps``-serialisable to STANDARD JSON tokens for the
    ledger, independent of ``sys.get_int_max_str_digits()`` (an accepted int
    renders to at most 617 digits, below the smallest settable limit).
    Anything else (a set, bytes, a custom object, a hostile mapping, an int
    wider than the ceiling, a NaN/Infinity float, a cyclic or exponentially-
    shared structure) is a malformed value shape. NOTE: this proof bounds
    nodes, depth, and integer width — NOT serialized byte size; scalar
    strings and the total encoded length are unbounded (recorded residual —
    see docs/LEGACY_ORCHESTRATOR_QUARANTINE.md)."""
    budget[0] -= 1
    if budget[0] < 0:
        return False
    t = type(value)
    if t is str or t is bool or value is None:
        return True
    if t is int:
        return value.bit_length() <= MAX_TUNING_INT_BITS
    if t is float:
        return math.isfinite(value)
    if t is list:
        if depth <= 0:
            return False
        return all(_is_exact_json_tree(item, depth - 1, budget) for item in value)
    if t is dict:
        if depth <= 0:
            return False
        return all(
            type(k) is str and _is_exact_json_tree(v, depth - 1, budget)
            for k, v in value.items()
        )
    return False


def _require_exact_str(value: Any) -> None:
    """Raise a fixed ``400 bad_request`` unless ``value`` is EXACTLY a builtin
    ``str`` (str subclasses, whose methods may be overridden, are refused). No
    method of a refused value is invoked."""
    if type(value) is not str:
        raise TuningError(400, "bad_request", BAD_REQUEST_MESSAGE)


def _require_valid_proposal_shape(
    params: Any, source: Any, justification: Any, mode: Any
) -> None:
    """Prove a propose envelope has exact builtin shapes BEFORE any supplied
    value is hashed, looked up, compared, stringified, validated, serialised,
    or emitted. ``params`` must be an exact ``dict`` whose keys are exact
    ``str`` and whose values are exact standard-JSON trees (ledger-
    serialisable: finite floats, ints within the width ceiling) proven against
    ONE shared node-visit budget for the whole proposal; ``source`` /
    ``justification`` / ``mode`` must be exact ``str``. Any deviation is a
    fixed ``400 bad_request`` — refused requests create no proposal, ledger
    append, pending file, or event."""
    _require_exact_str(source)
    _require_exact_str(justification)
    _require_exact_str(mode)
    if type(params) is not dict:
        raise TuningError(400, "bad_request", BAD_REQUEST_MESSAGE)
    budget = [_MAX_REQUEST_NODES]
    for name, value in params.items():
        if type(name) is not str or not _is_exact_json_tree(
            value, _MAX_REQUEST_VALUE_DEPTH, budget
        ):
            raise TuningError(400, "bad_request", BAD_REQUEST_MESSAGE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_proposal_id() -> str:
    return "prop-" + secrets.token_hex(4)


def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# -- typed error ------------------------------------------------------------


class TuningError(Exception):
    """Raised by TuningState methods to signal a policy or lookup failure."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# -- state ------------------------------------------------------------------


class TuningState:
    """Authoritative in-memory view of the tuning ledger. Writes through to disk.

    Rebuilds its state on startup by replaying the JSONL ledger. Thread-safe
    (Flask's threaded request handling can drive it from multiple workers).
    """

    def __init__(
        self,
        data_dir: Path,
        gen_getter: Optional[Callable[[], int]] = None,
        event_publisher: Optional[Any] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.ledger_path = self.data_dir / "tuning_ledger.jsonl"
        self.pending_path = self.data_dir / "tuning_pending.json"
        self._gen_getter: Callable[[], int] = gen_getter or (lambda: 0)
        # Duck-typed: anything with .publish(topic, payload). Kept optional so
        # unit tests can skip the event bus entirely.
        self._event_publisher = event_publisher
        self._lock = threading.Lock()

        self._effective: dict[str, Any] = {name: p.default for name, p in PARAMS.items()}
        self._last_commit_gen: dict[str, int] = {}
        self._proposals: dict[str, dict[str, Any]] = {}
        self._snapshots_after_commit: dict[str, dict[str, Any]] = {}
        self._replay_ledger()

    def _emit(self, topic: str, payload: dict) -> None:
        """Fire-and-forget publish. Never raises."""
        pub = self._event_publisher
        if pub is None:
            return
        try:
            pub.publish(topic, payload)
        except Exception:
            pass  # the ledger is the source of truth; don't fail callers on event bus issues

    # ---- read ----

    def effective_params(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._effective)

    def current_gen(self) -> int:
        try:
            return int(self._gen_getter())
        except Exception:
            return 0

    # ---- write: propose ----

    def propose(
        self,
        params: dict[str, Any],
        source: str,
        justification: str,
        mode: str,
    ) -> dict[str, Any]:
        # Prove exact envelope shapes before any supplied value is validated,
        # hashed, serialised, or emitted. A malformed shape is a fixed
        # 400 bad_request that leaves no proposal, ledger line, or event.
        _require_valid_proposal_shape(params, source, justification, mode)
        if mode not in VALID_MODES:
            raise TuningError(400, "bad_mode", f"mode must be one of {VALID_MODES}")
        with self._lock:
            validation = validate_proposal(params)
            proposal_id = _new_proposal_id()
            entry: dict[str, Any] = {
                "ts": _now_iso(),
                "type": "propose",
                "proposal_id": proposal_id,
                "source": source,
                "justification": justification,
                "mode": mode,
                "params": dict(params),
                "validation": {
                    "ok": validation.ok,
                    "errors": {
                        name: {
                            "error": r.error.value if r.error else None,
                            "message": r.message,
                        }
                        for name, r in validation.errors.items()
                    },
                },
            }
            self._append_ledger(entry)
            self._proposals[proposal_id] = entry
        # Emit after lock release — safety-rail denial is event-worthy.
        if not validation.ok:
            self._emit("tuning.rejected", {
                "stage": "propose",
                "proposal_id": proposal_id,
                "source": source,
                "params": dict(params),
                "errors": entry["validation"]["errors"],
            })
        return entry

    # ---- write: commit ----

    def commit(self, proposal_id: str, approver: str) -> dict[str, Any]:
        # Exact-string shape proof BEFORE the registry lookup (which hashes
        # proposal_id) and before the try/emit block, so a malformed-shape
        # commit is a fixed 400 bad_request with no proposal lookup, no state
        # mutation, and no rejected event carrying a supplied object.
        _require_exact_str(proposal_id)
        _require_exact_str(approver)
        try:
            entry = self._commit_locked(proposal_id, approver)
        except TuningError as e:
            self._emit("tuning.rejected", {
                "stage": "commit",
                "proposal_id": proposal_id,
                "approver": approver,
                "error": e.code,
                "message": e.message,
            })
            raise
        self._emit("tuning.committed", {
            "proposal_id": proposal_id,
            "approver": approver,
            "applied_at_gen": entry["applied_at_gen"],
            "params": dict(entry["params"]),
            "effective_after": entry["effective_after"],
        })
        return entry

    def _commit_locked(self, proposal_id: str, approver: str) -> dict[str, Any]:
        with self._lock:
            # `proposal_id` and `approver` are already proven EXACTLY str by
            # commit() before this lock is taken, so the registry lookup below
            # and the quarantine / human-approval string operations run no
            # supplied object's code.
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                raise TuningError(
                    404, "unknown_proposal",
                    f"No proposal with id {proposal_id}.",
                )
            if not proposal["validation"]["ok"]:
                raise TuningError(
                    409, "invalid_proposal",
                    "Proposal failed validation; cannot commit.",
                )
            params: dict[str, Any] = proposal["params"]

            # Auto-commit quarantine: the autonomous policy:auto approver is
            # refused at the write boundary regardless of parameter category.
            # This is the legacy orchestrator's only commit identity, so with
            # it shut, no LLM-facing tool call can mutate a parameter. Checked
            # before the human-approval branch so policy:auto yields one stable
            # reason. A human commit (approver="human:<name>") is unaffected.
            #
            # The match is stripped + case-insensitive so surface variants of
            # the same autonomous identity — " POLICY:AUTO ", tab/newline
            # padding, mixed case — cannot slip a mutation through. This
            # normalization is used ONLY for the quarantine comparison; the
            # human approver identity is never stripped or rewritten (the
            # startswith check below and the ledger entry both keep the raw
            # value, preserving existing human semantics exactly).
            if approver.strip().casefold() == AUTO_COMMIT_APPROVER:
                raise TuningError(
                    403, "auto_commit_disabled",
                    "approver='policy:auto' is disabled at the server boundary "
                    "for otherwise-valid proposals. For AUTO-category "
                    "parameters, other caller-supplied strings pass the "
                    "approver gate; HUMAN_APPROVAL-category parameters require "
                    "approver='human:<name>' (an unauthenticated label).",
                )

            # Approver policy.
            if _contains_human_approval_param(params) and not approver.startswith("human:"):
                offender = _first_param_in_category(params, Category.HUMAN_APPROVAL)
                raise TuningError(
                    403, "human_approval_required",
                    f"Proposal touches {offender} which requires approver='human:<name>'.",
                )

            # Rate limit.
            current_gen = self.current_gen()
            for name in params:
                last = self._last_commit_gen.get(name)
                if last is not None and (current_gen - last) < MIN_GEN_BETWEEN_COMMITS_PER_PARAM:
                    next_ok = last + MIN_GEN_BETWEEN_COMMITS_PER_PARAM
                    raise TuningError(
                        429, "rate_limited",
                        f"{name} last committed at gen {last}; next allowed at gen {next_ok} (current {current_gen}).",
                    )

            # Apply.
            self._effective.update(params)
            for name in params:
                self._last_commit_gen[name] = current_gen
            snapshot = dict(self._effective)
            self._snapshots_after_commit[proposal_id] = snapshot

            entry = {
                "ts": _now_iso(),
                "type": "commit",
                "proposal_id": proposal_id,
                "approver": approver,
                "applied_at_gen": current_gen,
                "params": dict(params),
                "effective_after": snapshot,
            }
            self._append_ledger(entry)
            _atomic_write_json(
                self.pending_path,
                {
                    "applied_at_gen": current_gen,
                    "effective_params": snapshot,
                    "proposal_id": proposal_id,
                    "kind": "commit",
                },
            )
            return entry

    # ---- write: rollback ----

    def rollback(self, to_proposal_id: str) -> dict[str, Any]:
        # Exact-string shape proof BEFORE the snapshot lookup (which hashes
        # to_proposal_id) and before the try/emit block, so a malformed-shape
        # rollback is a fixed 400 bad_request with no lookup, no mutation, and
        # no rejected event carrying a supplied object.
        _require_exact_str(to_proposal_id)
        try:
            entry = self._rollback_locked(to_proposal_id)
        except TuningError as e:
            self._emit("tuning.rejected", {
                "stage": "rollback",
                "to_proposal_id": to_proposal_id,
                "error": e.code,
                "message": e.message,
            })
            raise
        self._emit("tuning.rolled_back", {
            "to_proposal_id": to_proposal_id,
            "applied_at_gen": entry["applied_at_gen"],
            "reverted_params": dict(entry["reverted_params"]),
            "changed_back": list(entry["changed_back"]),
        })
        return entry

    def _rollback_locked(self, to_proposal_id: str) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshots_after_commit.get(to_proposal_id)
            if snapshot is None:
                raise TuningError(
                    404, "unknown_proposal",
                    f"No committed snapshot for proposal {to_proposal_id}; cannot rollback.",
                )
            current_gen = self.current_gen()
            changed = [k for k, v in snapshot.items() if self._effective.get(k) != v]
            self._effective = dict(snapshot)
            for name in changed:
                self._last_commit_gen[name] = current_gen
            entry = {
                "ts": _now_iso(),
                "type": "rollback",
                "to_proposal_id": to_proposal_id,
                "applied_at_gen": current_gen,
                "reverted_params": dict(snapshot),
                "changed_back": changed,
            }
            self._append_ledger(entry)
            _atomic_write_json(
                self.pending_path,
                {
                    "applied_at_gen": current_gen,
                    "effective_params": dict(snapshot),
                    "rollback_to": to_proposal_id,
                    "kind": "rollback",
                },
            )
            return entry

    # ---- internal ----

    def _replay_ledger(self) -> None:
        if not self.ledger_path.exists():
            return
        with self.ledger_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    # Skip corrupt lines; don't let a bad append poison
                    # startup. ValueError, not its JSONDecodeError subclass:
                    # a LEGACY line holding an int wider than the runtime
                    # sys.get_int_max_str_digits() limit (writable before the
                    # width ceiling existed) raises the plain-ValueError digit
                    # guard from json.loads, which previously escaped and
                    # crashed replay. The gated writer no longer produces such
                    # lines (accepted ints render to <= 617 digits, below the
                    # smallest settable limit).
                    continue
                etype = entry.get("type")
                if etype == "propose":
                    self._proposals[entry["proposal_id"]] = entry
                elif etype == "commit":
                    pid = entry.get("proposal_id")
                    params = entry.get("params", {})
                    gen = entry.get("applied_at_gen", 0)
                    self._effective.update(params)
                    for name in params:
                        self._last_commit_gen[name] = gen
                    self._snapshots_after_commit[pid] = dict(
                        entry.get("effective_after", self._effective)
                    )
                elif etype == "rollback":
                    reverted = entry.get("reverted_params", {})
                    gen = entry.get("applied_at_gen", 0)
                    self._effective = dict(reverted)
                    for name in entry.get("changed_back", []):
                        self._last_commit_gen[name] = gen

    def _append_ledger(self, entry: dict[str, Any]) -> None:
        # Serialize BEFORE touching the filesystem: opening in append mode
        # creates the file, so a json.dumps failure after open would leave a
        # zero-byte ledger behind. With the line built first, a serialization
        # failure performs no filesystem operation at all.
        line = json.dumps(entry, sort_keys=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _contains_human_approval_param(params: dict[str, Any]) -> bool:
    for name in params:
        p = get_param(name)
        if p and p.category is Category.HUMAN_APPROVAL:
            return True
    return False


def _first_param_in_category(params: dict[str, Any], category: Category) -> str:
    for name in params:
        p = get_param(name)
        if p and p.category is category:
            return name
    return "unknown"


# -- blueprint --------------------------------------------------------------


def _json_object_body() -> dict:
    """Return the request body only when it is EXACTLY a JSON object.

    ``request.get_json(silent=True) or {}`` swapped in ``{}`` for *falsy*
    bodies only, so a truthy non-object body (a JSON array, number, string, or
    ``true``) survived and reached ``body.get(...)`` — an AttributeError /
    HTTP 500. Guarding for an exact ``dict`` here turns every non-object body
    into a stable 400 bad_request. Raises TuningError(400) on a non-object."""
    body = request.get_json(silent=True)
    if type(body) is not dict:
        raise TuningError(400, "bad_request", BAD_REQUEST_MESSAGE)
    return body


def create_blueprint(state: TuningState) -> Blueprint:
    bp = Blueprint("tuning", __name__, url_prefix="/api")

    @bp.route("/params", methods=["GET"])
    def get_current_params() -> Response:
        return jsonify({"effective_params": state.effective_params(),
                        "current_gen": state.current_gen()})

    @bp.route("/params/schema", methods=["GET"])
    def get_schema() -> Response:
        return jsonify(schema_as_dict())

    @bp.route("/tuning/propose", methods=["POST"])
    def propose() -> Response:
        try:
            body = _json_object_body()
        except TuningError as e:
            return jsonify({"error": e.code, "message": e.message}), e.status_code
        params = body.get("params")
        if not isinstance(params, dict) or not params:
            return jsonify({
                "error": "bad_request",
                "message": "'params' (non-empty object) is required",
            }), 400
        # No str() coercion: a SUPPLIED source/justification must already be
        # an exact builtin str (proven inside state.propose — anything else is
        # the fixed 400), so a JSON list/number/object can no longer enter the
        # ledger as its Python repr. A MISSING field keeps its documented
        # default; a valid string is stored byte-for-byte.
        source = body.get("source", "unspecified")
        justification = body.get("justification", "")
        mode = body.get("mode", "dry-run")  # default to safe
        try:
            entry = state.propose(
                params=params, source=source, justification=justification, mode=mode,
            )
        except TuningError as e:
            return jsonify({"error": e.code, "message": e.message}), e.status_code
        status = 200 if entry["validation"]["ok"] else 422
        return jsonify({
            "proposal_id": entry["proposal_id"],
            "status": "accepted" if entry["validation"]["ok"] else "rejected",
            "mode": mode,
            "validation": entry["validation"],
        }), status

    @bp.route("/tuning/commit", methods=["POST"])
    def commit() -> Response:
        try:
            body = _json_object_body()
        except TuningError as e:
            return jsonify({"error": e.code, "message": e.message}), e.status_code
        proposal_id = body.get("proposal_id")
        approver = body.get("approver")
        if not proposal_id or not approver:
            return jsonify({
                "error": "bad_request",
                "message": "proposal_id and approver are required",
            }), 400
        try:
            entry = state.commit(proposal_id=proposal_id, approver=approver)
        except TuningError as e:
            return jsonify({"error": e.code, "message": e.message}), e.status_code
        return jsonify({
            "proposal_id": proposal_id,
            "status": "committed",
            "applied_at_gen": entry["applied_at_gen"],
            "approver": approver,
            "effective_after": entry["effective_after"],
        })

    @bp.route("/tuning/rollback", methods=["POST"])
    def rollback() -> Response:
        try:
            body = _json_object_body()
        except TuningError as e:
            return jsonify({"error": e.code, "message": e.message}), e.status_code
        to_proposal_id = body.get("to_proposal_id")
        if not to_proposal_id:
            return jsonify({
                "error": "bad_request",
                "message": "to_proposal_id is required",
            }), 400
        try:
            entry = state.rollback(to_proposal_id=to_proposal_id)
        except TuningError as e:
            return jsonify({"error": e.code, "message": e.message}), e.status_code
        return jsonify({
            "status": "rolled_back",
            "to_proposal_id": to_proposal_id,
            "applied_at_gen": entry["applied_at_gen"],
            "effective_params": entry["reverted_params"],
        })

    return bp


__all__ = [
    "MIN_GEN_BETWEEN_COMMITS_PER_PARAM",
    "VALID_MODES",
    "AUTO_COMMIT_APPROVER",
    "BAD_REQUEST_MESSAGE",
    "TuningError",
    "TuningState",
    "create_blueprint",
]
