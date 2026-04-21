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
  - HUMAN_APPROVAL params require `approver` starting with `human:` at commit.
  - Per-parameter rate limit (MIN_GEN_BETWEEN_COMMITS_PER_PARAM generations).
  - Invalid proposals cannot be committed even if approver is otherwise sufficient.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from flask import Blueprint, Response, jsonify, request

from scripts.params_schema import (
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


# -- helpers ----------------------------------------------------------------


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
                except json.JSONDecodeError:
                    continue  # skip corrupt lines; don't let a bad append poison startup
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
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")


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
        body = request.get_json(silent=True) or {}
        params = body.get("params")
        if not isinstance(params, dict) or not params:
            return jsonify({
                "error": "bad_request",
                "message": "'params' (non-empty object) is required",
            }), 400
        source = str(body.get("source", "unspecified"))
        justification = str(body.get("justification", ""))
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
        body = request.get_json(silent=True) or {}
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
        body = request.get_json(silent=True) or {}
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
    "TuningError",
    "TuningState",
    "create_blueprint",
]
