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

# flask is an optional dependency for the tuning HTTP API. Skip this module
# when it is absent rather than erroring at collection. (#165 Tier 1)
pytest.importorskip("flask")
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


def test_commit_auto_category_via_policy_auto_is_disabled(tuning):
    """Package R quarantine: even a valid AUTO-category proposal can no longer
    be committed by the autonomous policy:auto approver. The rejection is at
    the server boundary; no engine-state mutation and no pending file result."""
    client, state, gen, tmp_path = tuning
    pid = _propose(client, {"signal_interval": 15})
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "policy:auto"},
    ))
    assert code == 403
    assert body["error"] == "auto_commit_disabled"
    # No mutation: effective params unchanged, no pending file written.
    assert state.effective_params()["signal_interval"] == PARAMS["signal_interval"].default
    assert not (tmp_path / "tuning_pending.json").exists()


def test_commit_auto_category_still_accepts_human_approver(tuning):
    """The quarantine closes only the autonomous path. A deliberate human
    approver may still commit an AUTO-category proposal (they take
    responsibility explicitly)."""
    client, state, gen, tmp_path = tuning
    pid = _propose(client, {"signal_interval": 15})
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "human:kevin"},
    ))
    assert code == 200
    assert body["status"] == "committed"
    assert state.effective_params()["signal_interval"] == 15
    pending = json.loads((tmp_path / "tuning_pending.json").read_text())
    assert pending["proposal_id"] == pid


def test_commit_human_approval_param_via_policy_auto_disabled(tuning):
    """A HUMAN_APPROVAL param committed with policy:auto is refused. Post-R the
    auto-commit quarantine fires first, so the stable reason is
    auto_commit_disabled (still 403; still rejected; still no mutation)."""
    client, state, *_ = tuning
    pid = _propose(client, {"magnon_coupling": 2.5})  # HUMAN_APPROVAL category
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": "policy:auto"},
    ))
    assert code == 403
    assert body["error"] == "auto_commit_disabled"
    assert "magnon_coupling" not in state.effective_params() or \
        state.effective_params()["magnon_coupling"] == PARAMS["magnon_coupling"].default


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
    # Rate-limit protection is unchanged by the auto-commit quarantine; proven
    # here via the still-available human-approver commit path.
    client, state, gen, _ = tuning
    # First commit succeeds.
    pid1 = _propose(client, {"signal_interval": 20})
    assert client.post("/api/tuning/commit",
                       json={"proposal_id": pid1, "approver": "human:kevin"}).status_code == 200
    # Advance less than the cooldown.
    gen.advance(MIN_GEN_BETWEEN_COMMITS_PER_PARAM - 1)
    pid2 = _propose(client, {"signal_interval": 25})
    code, body = _json(client.post("/api/tuning/commit",
                                    json={"proposal_id": pid2, "approver": "human:kevin"}))
    assert code == 429
    assert body["error"] == "rate_limited"
    # Advance past the cooldown; second commit now succeeds.
    gen.advance(2)
    pid3 = _propose(client, {"signal_interval": 30})
    assert client.post("/api/tuning/commit",
                       json={"proposal_id": pid3, "approver": "human:kevin"}).status_code == 200


def test_commit_400_when_body_incomplete(tuning):
    client, *_ = tuning
    for payload in ({}, {"proposal_id": "prop-x"}, {"approver": "human:kevin"}):
        code, body = _json(client.post("/api/tuning/commit", json=payload))
        assert code == 400
        assert body["error"] == "bad_request"


# -- Package R: auto-commit quarantine (server boundary) --------------------


def test_auto_commit_disabled_is_the_orchestrators_only_identity(tuning):
    """The legacy orchestrator's ToolRouter hard-codes approver='policy:auto'
    (see scripts/orchestrator.py) and offers the LLM no way to set it. That
    exact identity is refused here, and the refusal does not mutate state — so
    the orchestrator's whole write path is closed at the boundary."""
    client, state, *_ = tuning
    pid = _propose(client, {"signal_interval": 15})
    code, body = _json(client.post("/api/tuning/commit",
                                   json={"proposal_id": pid, "approver": "policy:auto"}))
    assert code == 403
    assert body["error"] == "auto_commit_disabled"
    assert state.effective_params()["signal_interval"] == PARAMS["signal_interval"].default


def test_auto_commit_rejection_emits_no_committed_event(tmp_path):
    """A refused policy:auto commit must not fire tuning.committed on the event
    bus (no downstream consumer should believe a commit happened)."""
    class RecordingBus:
        def __init__(self):
            self.published = []

        def publish(self, topic, payload):
            self.published.append((topic, payload))

    gen = FakeGen()
    bus = RecordingBus()
    state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=bus)
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(state))
    client = app.test_client()

    pid = _propose(client, {"signal_interval": 15})
    resp = client.post("/api/tuning/commit",
                       json={"proposal_id": pid, "approver": "policy:auto"})
    assert resp.status_code == 403
    topics = [t for t, _ in bus.published]
    assert "tuning.committed" not in topics
    # The rejection is surfaced as a rejected event (stage=commit).
    assert any(t == "tuning.rejected" for t in topics)
    # No pending file was written.
    assert not (tmp_path / "tuning_pending.json").exists()


def test_locked_and_dryrun_paths_unchanged_by_quarantine(tuning):
    """Baseline preserved: LOCKED still rejected at propose; dry-run proposal
    still accepted; proposal creation still returns an id."""
    client, *_ = tuning
    # LOCKED rejected at propose (unchanged).
    code, body = _json(client.post(
        "/api/tuning/propose",
        json={"params": {"structural_to_void_decay_prob": 0.004}},
    ))
    assert code == 422
    assert body["validation"]["errors"]["structural_to_void_decay_prob"]["error"] == "locked"
    # Dry-run proposal still accepted and recorded.
    code, body = _json(client.post(
        "/api/tuning/propose",
        json={"params": {"signal_interval": 12}, "justification": "ok", "mode": "dry-run"},
    ))
    assert code == 200
    assert body["proposal_id"].startswith("prop-")


# -- Package R amendment (Jack audit): type-guard + normalized match --------


class _RecordingBus:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def _committed_ledger_entries(tmp_path):
    p = tmp_path / "tuning_ledger.jsonl"
    if not p.exists():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("type") == "commit"
    ]


_BLOCKED_APPROVER_VARIANTS = [
    "policy:auto",
    " policy:auto ",
    "POLICY:AUTO",
    " POLICY:AUTO ",
    "\tPolicy:Auto\n",
    "policy:auto\n",
]


@pytest.mark.parametrize("approver", _BLOCKED_APPROVER_VARIANTS)
def test_commit_normalized_policy_auto_variants_all_disabled(tmp_path, approver):
    """Every whitespace/case variant of the autonomous identity is refused with
    the same stable 403 auto_commit_disabled, and none of them touches any of
    the four write surfaces: effective params, pending file, commit ledger, or
    the tuning.committed event."""
    gen = FakeGen()
    bus = _RecordingBus()
    state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=bus)
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(state))
    client = app.test_client()

    pid = _propose(client, {"signal_interval": 15})
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": approver},
    ))
    assert code == 403
    assert body["error"] == "auto_commit_disabled"
    assert state.effective_params()["signal_interval"] == PARAMS["signal_interval"].default
    assert not (tmp_path / "tuning_pending.json").exists()
    assert _committed_ledger_entries(tmp_path) == []
    assert "tuning.committed" not in [t for t, _ in bus.published]


@pytest.mark.parametrize("approver", [True, 123, 1.5, ["human:kevin"], {"who": "human:kevin"}])
def test_commit_non_string_approver_is_bad_request(tmp_path, approver):
    """A non-string approver (bool/number/list/object) is a malformed request:
    stable 400 bad_request checked before any string operation, never an
    AttributeError, and no state mutation."""
    gen = FakeGen()
    state = TuningState(data_dir=tmp_path, gen_getter=gen)
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(state))
    client = app.test_client()

    pid = _propose(client, {"signal_interval": 15})
    code, body = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": approver},
    ))
    assert code == 400
    assert body["error"] == "bad_request"
    assert state.effective_params()["signal_interval"] == PARAMS["signal_interval"].default
    assert not (tmp_path / "tuning_pending.json").exists()


def test_commit_preserves_raw_human_approver_identity(tuning):
    """The quarantine normalization is comparison-only. A human approver's raw
    identity — mixed case and trailing whitespace — is stored verbatim in the
    committed ledger entry, never stripped or lowercased."""
    client, state, gen, tmp_path = tuning
    pid = _propose(client, {"signal_interval": 15})
    raw = "human:Kevin "  # valid human prefix; capitalised name; trailing space
    code, _ = _json(client.post(
        "/api/tuning/commit",
        json={"proposal_id": pid, "approver": raw},
    ))
    assert code == 200
    commits = _committed_ledger_entries(tmp_path)
    assert commits and commits[-1]["approver"] == raw


# -- POST /api/tuning/rollback ---------------------------------------------


def test_rollback_happy_path(tuning):
    client, state, gen, tmp_path = tuning
    # Commit A
    pid_a = _propose(client, {"signal_interval": 17})
    client.post("/api/tuning/commit", json={"proposal_id": pid_a, "approver": "human:kevin"})
    # Move past rate limit for next param so we can vary state a bit
    gen.advance(MIN_GEN_BETWEEN_COMMITS_PER_PARAM + 1)
    # Commit B (different param so no rate-limit collision)
    pid_b = _propose(client, {"joy_beta": 0.5})
    client.post("/api/tuning/commit", json={"proposal_id": pid_b, "approver": "human:kevin"})
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
    client.post("/api/tuning/commit", json={"proposal_id": pid_a, "approver": "human:kevin"})

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
    client.post("/api/tuning/commit", json={"proposal_id": pid, "approver": "human:kevin"})
    # Corrupt the ledger with a bad line in the middle.
    with (tmp_path / "tuning_ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write("this-is-not-json\n")
    fresh = TuningState(data_dir=tmp_path, gen_getter=gen)
    # State from the valid lines is still restored.
    assert fresh.effective_params()["signal_interval"] == 14


# -- request-shape totality (PUBLIC / DIRECT / LEDGER lanes) ------------------
#
# The proposal/commit/rollback envelopes must be deterministic for malformed
# value shapes across three reachability lanes:
#   PUBLIC   — values obtainable through parsed JSON (str/int/float/bool/None/
#              list/dict only); a malformed envelope returns a stable
#              400 bad_request, never a 500.
#   DIRECT   — TuningState / validate_proposal called with arbitrary Python
#              objects; a malformed call terminates through a fixed typed
#              TuningError(400) rather than leaking AttributeError/TypeError.
#   LEDGER   — no refused request appends to the ledger, writes the pending
#              file, records a proposal, commits, rolls back, or emits an event.
# Refusals carry a fixed generic message that names neither the supplied value
# nor its type. Hostile instruments RECORD their hook invocations so "not
# consulted" is proven by an empty call log, not inferred from the absence of
# a crash.

import math as _math

from scripts.tuning_api import TuningError, TuningState, create_blueprint


def _fresh_state(tmp_path, bus=None):
    gen = FakeGen()
    state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=bus)
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(state))
    return state, app.test_client(), gen


def _post_raw(client, path, raw_body):
    return client.post(path, data=raw_body, content_type="application/json")


def _no_side_effects(tmp_path, state):
    """No ledger file, no pending file, no recorded proposal."""
    assert not (tmp_path / "tuning_ledger.jsonl").exists()
    assert not (tmp_path / "tuning_pending.json").exists()
    assert state._proposals == {}


# -- PUBLIC lane: non-object top-level body reaching .get --------------------


_NON_OBJECT_BODIES = ["[1, 2, 3]", "42", "3.14", "true", '"hello"']


@pytest.mark.parametrize("raw", _NON_OBJECT_BODIES)
@pytest.mark.parametrize("path", [
    "/api/tuning/propose", "/api/tuning/commit", "/api/tuning/rollback",
])
def test_public_non_object_body_is_bad_request_not_500(tmp_path, raw, path):
    state, client, _ = _fresh_state(tmp_path)
    resp = _post_raw(client, path, raw)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_request"
    _no_side_effects(tmp_path, state)


@pytest.mark.parametrize("path", [
    "/api/tuning/propose", "/api/tuning/commit", "/api/tuning/rollback",
])
def test_public_empty_and_null_body_still_bad_request(tmp_path, path):
    state, client, _ = _fresh_state(tmp_path)
    for raw in ("null", ""):
        resp = _post_raw(client, path, raw)
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_request"


# -- PUBLIC lane: unhashable / non-string ids reaching registry .get ---------


@pytest.mark.parametrize("raw_id", ["[1, 2]", '{"a": 1}', "123", "true"])
def test_public_commit_non_string_proposal_id_is_bad_request(tmp_path, raw_id):
    state, client, _ = _fresh_state(tmp_path)
    body = '{"proposal_id": ' + raw_id + ', "approver": "human:kevin"}'
    resp = _post_raw(client, "/api/tuning/commit", body)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_request"
    assert not (tmp_path / "tuning_pending.json").exists()


@pytest.mark.parametrize("raw_id", ["[1, 2]", '{"a": 1}', "123", "true"])
def test_public_rollback_non_string_to_proposal_id_is_bad_request(tmp_path, raw_id):
    state, client, _ = _fresh_state(tmp_path)
    body = '{"to_proposal_id": ' + raw_id + "}"
    resp = _post_raw(client, "/api/tuning/rollback", body)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_request"
    assert not (tmp_path / "tuning_pending.json").exists()


# -- PUBLIC lane: preserved behaviour for valid & recorded-rejection paths ----


def test_public_valid_propose_commit_rollback_unchanged(tmp_path):
    """Golden-path smoke: the whole valid envelope still behaves exactly."""
    state, client, gen = _fresh_state(tmp_path)
    pid = client.post("/api/tuning/propose", json={
        "params": {"signal_interval": 15}, "source": "human:kevin",
        "justification": "t", "mode": "commit-pending",
    }).get_json()["proposal_id"]
    assert pid.startswith("prop-")
    r = client.post("/api/tuning/commit",
                    json={"proposal_id": pid, "approver": "human:kevin"})
    assert r.status_code == 200 and r.get_json()["status"] == "committed"
    assert state.effective_params()["signal_interval"] == 15
    r = client.post("/api/tuning/rollback", json={"to_proposal_id": pid})
    assert r.status_code == 200 and r.get_json()["status"] == "rolled_back"


def test_public_container_param_value_still_records_wrong_type(tmp_path):
    """A JSON container as a param value is not a scalar, but it IS a JSON
    tree — it still reaches validation and is recorded as a wrong_type
    rejection (422), exactly as before; not refused at the envelope."""
    state, client, _ = _fresh_state(tmp_path)
    resp = _post_raw(client, "/api/tuning/propose",
                     '{"params": {"signal_interval": [1, 2]}}')
    assert resp.status_code == 422
    body = resp.get_json()
    assert body["status"] == "rejected"
    assert body["validation"]["errors"]["signal_interval"]["error"] == "wrong_type"


# -- DIRECT lane: TuningState.propose malformed envelope shapes ---------------


class _Recorder:
    """Base for hostile instruments: every hook appends its name to `calls`."""

    def __init__(self):
        self.calls = []


class _HostileKey(_Recorder):
    """A non-str dict key whose equality/str hooks record. __hash__ records too
    (dict insertion needs it) so the test measures only NEW calls after build."""

    def __hash__(self):
        self.calls.append("__hash__")
        return 0

    def __eq__(self, other):
        self.calls.append("__eq__")
        return self is other

    def __str__(self):
        self.calls.append("__str__")
        return "k"

    def __repr__(self):
        self.calls.append("__repr__")
        return "k"


class _HostileScalar(_Recorder):
    """A non-JSON, non-str value whose conversion hooks all record."""

    def __str__(self):
        self.calls.append("__str__")
        return "v"

    def __repr__(self):
        self.calls.append("__repr__")
        return "v"

    def __eq__(self, other):
        self.calls.append("__eq__")
        return False

    def __hash__(self):
        self.calls.append("__hash__")
        return 0

    def __bool__(self):
        self.calls.append("__bool__")
        return True

    def __iter__(self):
        self.calls.append("__iter__")
        return iter(())


@pytest.mark.parametrize("bad_params", [
    [1, 2], "params", 42, 3.14, True, None, ("k", "v"),
], ids=["list", "str", "int", "float", "bool", "none", "tuple"])
def test_direct_propose_non_dict_params_is_typed_bad_request(tmp_path, bad_params):
    state, _, _ = _fresh_state(tmp_path)
    with pytest.raises(TuningError) as ei:
        state.propose(params=bad_params, source="s", justification="j", mode="dry-run")
    assert ei.value.status_code == 400
    assert ei.value.code == "bad_request"
    _no_side_effects(tmp_path, state)


def test_direct_propose_non_str_key_refused_without_registry_lookup(tmp_path):
    state, _, _ = _fresh_state(tmp_path)
    key = _HostileKey()
    params = {key: 1}
    key.calls.clear()  # forget the hash from dict construction
    with pytest.raises(TuningError) as ei:
        state.propose(params=params, source="s", justification="j", mode="dry-run")
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    # No registry lookup / equality / stringify of the hostile key.
    assert key.calls == []
    _no_side_effects(tmp_path, state)


@pytest.mark.parametrize("field", ["source", "justification"])
def test_direct_propose_non_str_metadata_is_bad_request_no_ledger(tmp_path, field):
    bus = _RecordingBus()
    state, _, _ = _fresh_state(tmp_path, bus=bus)
    val = _HostileScalar()
    kw = dict(params={"signal_interval": 12}, source="s", justification="j", mode="dry-run")
    kw[field] = val
    with pytest.raises(TuningError) as ei:
        state.propose(**kw)
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    assert val.calls == []            # never stringified/serialized
    assert bus.published == []        # no event emitted
    _no_side_effects(tmp_path, state)


def test_direct_propose_non_str_mode_refused_without_equality(tmp_path):
    state, _, _ = _fresh_state(tmp_path)
    mode = _HostileScalar()
    with pytest.raises(TuningError) as ei:
        state.propose(params={"signal_interval": 12}, source="s",
                      justification="j", mode=mode)
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    assert mode.calls == []           # `mode not in VALID_MODES` never ran __eq__
    _no_side_effects(tmp_path, state)


@pytest.mark.parametrize("value_factory", [
    lambda: {1, 2, 3},           # set — not JSON serializable
    lambda: object(),            # bare object
    lambda: b"bytes",            # bytes
], ids=["set", "object", "bytes"])
def test_direct_propose_non_json_value_refused_before_ledger(tmp_path, value_factory):
    bus = _RecordingBus()
    state, _, _ = _fresh_state(tmp_path, bus=bus)
    with pytest.raises(TuningError) as ei:
        state.propose(params={"signal_interval": value_factory()},
                      source="s", justification="j", mode="dry-run")
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    assert bus.published == []
    _no_side_effects(tmp_path, state)


def test_direct_propose_refusal_message_carries_no_value_or_type(tmp_path):
    state, _, _ = _fresh_state(tmp_path)
    with pytest.raises(TuningError) as ei:
        state.propose(params={"signal_interval": {1, 2, 3}},
                      source="s", justification="j", mode="dry-run")
    msg = ei.value.message
    assert len(msg) < 120
    for leak in ("set", "{1", "signal_interval", "object", "bytes"):
        assert leak not in msg


# -- DIRECT lane: commit / rollback id shapes --------------------------------


@pytest.mark.parametrize("bad_id", [
    [1, 2], {"a": 1}, 123, 1.5, True, None, _HostileScalar,
], ids=["list", "dict", "int", "float", "bool", "none", "hostile"])
def test_direct_commit_non_str_proposal_id_is_bad_request(tmp_path, bad_id):
    state, _, _ = _fresh_state(tmp_path)
    pid = bad_id() if bad_id is _HostileScalar else bad_id
    with pytest.raises(TuningError) as ei:
        state.commit(proposal_id=pid, approver="human:kevin")
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    if isinstance(pid, _HostileScalar):
        assert pid.calls == []        # never hashed for the registry lookup
    assert not (tmp_path / "tuning_pending.json").exists()


@pytest.mark.parametrize("bad_id_factory", [
    lambda: [1, 2],            # unhashable: currently a raw TypeError (no emit)
    lambda: _HostileScalar(),  # hostile-hashable: currently emits a rejected event
], ids=["unhashable", "hostile-hash"])
def test_direct_commit_non_str_proposal_id_emits_no_event(tmp_path, bad_id_factory):
    bus = _RecordingBus()
    state, _, _ = _fresh_state(tmp_path, bus=bus)
    with pytest.raises(TuningError):
        state.commit(proposal_id=bad_id_factory(), approver="human:kevin")
    assert bus.published == []          # malformed shape → no rejected event at all


@pytest.mark.parametrize("bad_id", [
    [1, 2], {"a": 1}, 123, 1.5, True, None, _HostileScalar,
], ids=["list", "dict", "int", "float", "bool", "none", "hostile"])
def test_direct_rollback_non_str_id_is_bad_request(tmp_path, bad_id):
    state, _, _ = _fresh_state(tmp_path)
    tid = bad_id() if bad_id is _HostileScalar else bad_id
    with pytest.raises(TuningError) as ei:
        state.rollback(to_proposal_id=tid)
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    if isinstance(tid, _HostileScalar):
        assert tid.calls == []
    assert not (tmp_path / "tuning_pending.json").exists()


def test_direct_rollback_hostile_id_emits_no_event(tmp_path):
    bus = _RecordingBus()
    state, _, _ = _fresh_state(tmp_path, bus=bus)
    with pytest.raises(TuningError):
        state.rollback(to_proposal_id=_HostileScalar())
    assert bus.published == []


def test_direct_commit_str_subclass_approver_is_refused(tmp_path):
    """Exact-type gate: a str subclass approver is refused (400), not run
    through the quarantine's strip/casefold subclass methods."""
    class _SubStr(str):
        pass

    state, client, _ = _fresh_state(tmp_path)
    pid = _propose(client, {"signal_interval": 15})
    with pytest.raises(TuningError) as ei:
        state.commit(proposal_id=pid, approver=_SubStr("human:kevin"))
    assert ei.value.status_code == 400 and ei.value.code == "bad_request"
    assert state.effective_params()["signal_interval"] == PARAMS["signal_interval"].default


# -- LEDGER/EVENT lane: refused request is inert ------------------------------


def test_refused_direct_propose_writes_no_ledger_line(tmp_path):
    bus = _RecordingBus()
    state, _, _ = _fresh_state(tmp_path, bus=bus)
    for bad in ([1, 2], {"signal_interval": object()}, {object(): 1}):
        with pytest.raises(TuningError):
            state.propose(params=bad, source="s", justification="j", mode="dry-run")
    assert not (tmp_path / "tuning_ledger.jsonl").exists()
    assert bus.published == []
    assert state._proposals == {}


def test_valid_direct_propose_still_writes_serialisable_ledger(tmp_path):
    """Positive control: a well-formed proposal still appends exactly one
    JSON-serialisable ledger line and records the proposal."""
    state, _, _ = _fresh_state(tmp_path)
    entry = state.propose(params={"signal_interval": 12}, source="human:kevin",
                          justification="ok", mode="dry-run")
    assert entry["proposal_id"].startswith("prop-")
    lines = (tmp_path / "tuning_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    reparsed = json.loads(lines[0])
    assert reparsed["type"] == "propose"
    assert reparsed["params"] == {"signal_interval": 12}
