"""Tests for scripts/tuning_api.py (Phase 18 PR 2).

Covers:
  - GET  /api/params             default effective params from registry
  - GET  /api/params/schema      full schema round-trip
  - POST /api/tuning/propose     accept / reject (validation failures)
  - POST /api/tuning/commit      auto vs human approval, rate-limit, invalid
                                  proposal, unknown proposal
  - POST /api/tuning/rollback    unknown + happy-path
  - Ledger persistence: replay across TuningState restart
  - Pending-tuning file written with atomic rename semantics
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

from scripts.tuning_api import (
    MIN_GEN_BETWEEN_COMMITS_PER_PARAM,
    TuningState,
    create_blueprint,
)
from scripts.params_schema import PARAMS, Category


# -- fixtures ---------------------------------------------------------------


class FakeGen:
    """Drop-in replacement for gen_getter; tests bump the value explicitly."""

    def __init__(self, start: int = 1_000_000) -> None:
        self.value = start

    def advance(self, n: int) -> None:
        self.value += n

    def __call__(self) -> int:
        return self.value


@pytest.fixture
def tuning(tmp_path: Path):
    gen = FakeGen()
    state = TuningState(data_dir=tmp_path, gen_getter=gen)
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(state))
    client = app.test_client()
    return client, state, gen, tmp_path


def _json(resp):
    return resp.status_code, resp.get_json()


# -- GET endpoints ----------------------------------------------------------


def test_get_params_returns_registry_defaults(tuning):
    client, state, gen, _ = tuning
    code, body = _json(client.get("/api/params"))
    assert code == 200
    eff = body["effective_params"]
    for name, param in PARAMS.items():
        assert eff[name] == param.default
    assert body["current_gen"] == gen.value


def test_get_schema_round_trips_json(tuning):
    client, *_ = tuning
    code, body = _json(client.get("/api/params/schema"))
    assert code == 200
    assert body["version"] == 1
    assert "signal_interval" in body["params"]
    assert body["params"]["signal_interval"]["category"] == "auto"


# -- POST /api/tuning/propose ----------------------------------------------


def test_propose_accepts_valid(tuning):
    client, *_ = tuning
    code, body = _json(client.post(
        "/api/tuning/propose",
        json={"params": {"signal_interval": 12}, "source": "human:kevin", "justification": "test"},
    ))
    assert code == 200
    assert body["status"] == "accepted"
    assert body["mode"] == "dry-run"  # default
    assert body["proposal_id"].startswith("prop-")
    assert body["validation"]["ok"] is True


def test_propose_rejects_invalid_but_records(tuning):
    client, state, *_ = tuning
    code, body = _json(client.post(
        "/api/tuning/propose",
        json={"params": {"signal_interval": 0}},  # below min
    ))
    assert code == 422
    assert body["status"] == "rejected"
    assert body["validation"]["ok"] is False
    assert body["validation"]["errors"]["signal_interval"]["error"] == "below_min"
    # Rejected proposals still get a proposal_id and are recorded.
    assert body["proposal_id"].startswith("prop-")


def test_propose_rejects_locked(tuning):
    client, *_ = tuning
    code, body = _json(client.post(
        "/api/tuning/propose",
        json={"params": {"structural_to_void_decay_prob": 0.004}},
    ))
    assert code == 422
    assert body["validation"]["errors"]["structural_to_void_decay_prob"]["error"] == "locked"


def test_propose_400_when_params_missing(tuning):
    client, *_ = tuning
    code, body = _json(client.post("/api/tuning/propose", json={}))
    assert code == 400
    assert body["error"] == "bad_request"


def test_propose_400_when_mode_invalid(tuning):
    client, *_ = tuning
    code, body = _json(client.post(
        "/api/tuning/propose",
        json={"params": {"signal_interval": 12}, "mode": "go-wild"},
    ))
    assert code == 400


# -- POST /api/tuning/commit -----------------------------------------------


def _propose(client, params, source="human:kevin", mode="commit-pending"):
    resp = client.post(
        "/api/tuning/propose",
        json={"params": params, "source": source, "justification": "t", "mode": mode},
    )
    return resp.get_json()["proposal_id"]


def test_commit_auto_category_accepts_policy_auto(tuning):
    client, state, gen, tmp_path = tuning
    pid = _propose(client, {"signal_interval": 15})
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "policy:auto"},
    ))
    assert code == 200
    assert body["status"] == "committed"
    assert body["applied_at_gen"] == gen.value
    assert body["effective_after"]["signal_interval"] == 15
    # Pending file was written.
    pending = json.loads((tmp_path / "tuning_pending.json").read_text())
    assert pending["effective_params"]["signal_interval"] == 15
    assert pending["proposal_id"] == pid
    # Effective state updated.
    assert state.effective_params()["signal_interval"] == 15


def test_commit_human_approval_required_rejects_policy_auto(tuning):
    client, *_ = tuning
    pid = _propose(client, {"magnon_coupling": 2.5})  # HUMAN_APPROVAL category
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "policy:auto"},
    ))
    assert code == 403
    assert body["error"] == "human_approval_required"


def test_commit_human_approval_accepts_human_prefix(tuning):
    client, *_ = tuning
    pid = _propose(client, {"magnon_coupling": 2.5})
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "human:kevin"},
    ))
    assert code == 200
    assert body["status"] == "committed"


def test_commit_unknown_proposal_returns_404(tuning):
    client, *_ = tuning
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": "prop-deadbeef", "approver": "human:kevin"},
    ))
    assert code == 404
    assert body["error"] == "unknown_proposal"


def test_commit_invalid_proposal_rejected_even_with_human(tuning):
    client, *_ = tuning
    # Proposal fails validation (below min), but is recorded.
    resp = client.post(
        "/api/tuning/propose",
        json={"params": {"signal_interval": -5}, "source": "human:kevin"},
    )
    pid = resp.get_json()["proposal_id"]
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "human:kevin"},
    ))
    assert code == 409
    assert body["error"] == "invalid_proposal"


def test_commit_rate_limit_rejects_quick_repeat(tuning):
    client, state, gen, _ = tuning
    # First commit succeeds.
    pid1 = _propose(client, {"signal_interval": 20})
    assert client.post("/api/tuning/commit",
                       json={"proposal_id": pid1, "approver": "policy:auto"}).status_code == 200
    # Advance less than the cooldown.
    gen.advance(MIN_GEN_BETWEEN_COMMITS_PER_PARAM - 1)
    pid2 = _propose(client, {"signal_interval": 25})
    code, body = _json(client.post("/api/tuning/commit",
                                    json={"proposal_id": pid2, "approver": "policy:auto"}))
    assert code == 429
    assert body["error"] == "rate_limited"
    # Advance past the cooldown; second commit now succeeds.
    gen.advance(2)
    pid3 = _propose(client, {"signal_interval": 30})
    assert client.post("/api/tuning/commit",
                       json={"proposal_id": pid3, "approver": "policy:auto"}).status_code == 200


def test_commit_400_when_body_incomplete(tuning):
    client, *_ = tuning
    for payload in ({}, {"proposal_id": "prop-x"}, {"approver": "human:kevin"}):
        code, body = _json(client.post("/api/tuning/commit", json=payload))
        assert code == 400
        assert body["error"] == "bad_request"


# -- POST /api/tuning/rollback ---------------------------------------------


def test_rollback_happy_path(tuning):
    client, state, gen, tmp_path = tuning
    # Commit A
    pid_a = _propose(client, {"signal_interval": 17})
    client.post("/api/tuning/commit", json={"proposal_id": pid_a, "approver": "policy:auto"})
    # Move past rate limit for next param so we can vary state a bit
    gen.advance(MIN_GEN_BETWEEN_COMMITS_PER_PARAM + 1)
    # Commit B (different param so no rate-limit collision)
    pid_b = _propose(client, {"joy_beta": 0.5})
    client.post("/api/tuning/commit", json={"proposal_id": pid_b, "approver": "policy:auto"})
    assert state.effective_params()["signal_interval"] == 17
    assert state.effective_params()["joy_beta"] == 0.5
    # Rollback to the snapshot after A — joy_beta should return to its default.
    code, body = _json(client.post("/api/tuning/rollback", json={"to_proposal_id": pid_a}))
    assert code == 200
    assert body["status"] == "rolled_back"
    assert state.effective_params()["signal_interval"] == 17     # A's change preserved
    assert state.effective_params()["joy_beta"] == PARAMS["joy_beta"].default  # B reverted
    # Pending file reflects the rollback.
    pending = json.loads((tmp_path / "tuning_pending.json").read_text())
    assert pending["kind"] == "rollback"
    assert pending["rollback_to"] == pid_a


def test_rollback_unknown_proposal_returns_404(tuning):
    client, *_ = tuning
    code, body = _json(client.post("/api/tuning/rollback", json={"to_proposal_id": "prop-none"}))
    assert code == 404


def test_rollback_400_when_missing(tuning):
    client, *_ = tuning
    code, _body = _json(client.post("/api/tuning/rollback", json={}))
    assert code == 400


# -- ledger persistence -----------------------------------------------------


def test_ledger_replay_restores_state_across_restart(tuning):
    client, state, gen, tmp_path = tuning
    # Propose + commit + rollback, then build a fresh TuningState from the same dir.
    pid_a = _propose(client, {"signal_interval": 22})
    client.post("/api/tuning/commit", json={"proposal_id": pid_a, "approver": "policy:auto"})

    fresh = TuningState(data_dir=tmp_path, gen_getter=gen)
    assert fresh.effective_params()["signal_interval"] == 22
    # Ledger file exists and has 2 entries (propose + commit).
    lines = (tmp_path / "tuning_ledger.jsonl").read_text().splitlines()
    assert len(lines) == 2
    kinds = [json.loads(ln)["type"] for ln in lines]
    assert kinds == ["propose", "commit"]


def test_ledger_survives_corrupt_line(tuning):
    client, state, gen, tmp_path = tuning
    pid = _propose(client, {"signal_interval": 14})
    client.post("/api/tuning/commit", json={"proposal_id": pid, "approver": "policy:auto"})
    # Corrupt the ledger with a bad line in the middle.
    with (tmp_path / "tuning_ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write("this-is-not-json\n")
    fresh = TuningState(data_dir=tmp_path, gen_getter=gen)
    # State from the valid lines is still restored.
    assert fresh.effective_params()["signal_interval"] == 14
