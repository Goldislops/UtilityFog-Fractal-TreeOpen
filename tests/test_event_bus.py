"""Tests for scripts/event_bus.py (Phase 18 PR 3).

Covers:
  - EventPublisher / EventSubscriber roundtrip (ZMQ PUB/SUB)
  - Topic filtering via setsockopt(SUBSCRIBE, prefix)
  - Publish after close is a silent no-op
  - Malformed payload (non-JSON-serializable) is dropped silently
  - StateWatcher: new telemetry file → telemetry.5min event
  - StateWatcher bootstrap: existing files are NOT re-announced
  - TuningState integration: commit → tuning.committed, gate denial → tuning.rejected,
    rollback → tuning.rolled_back
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

try:
    import zmq  # noqa: F401
except ImportError:
    pytest.skip("pyzmq not installed", allow_module_level=True)

from scripts.event_bus import (
    TOPIC_TELEMETRY_5MIN,
    TOPIC_TUNING_COMMITTED,
    TOPIC_TUNING_REJECTED,
    TOPIC_TUNING_ROLLED_BACK,
    EventPublisher,
    EventSubscriber,
    StateWatcher,
)
from scripts.tuning_api import MIN_GEN_BETWEEN_COMMITS_PER_PARAM, TuningState


def _unique_inproc_endpoint() -> str:
    """Unique inproc:// address per test to avoid cross-test interference."""
    return f"inproc://event-bus-test-{uuid.uuid4().hex[:12]}"


def _make_pair(topics=None):
    """Publisher + subscriber pair on a unique inproc endpoint.

    Caller is responsible for closing both. A small sleep after subscribe
    lets the subscription propagate (ZMQ's slow-joiner problem).
    """
    endpoint = _unique_inproc_endpoint()
    pub = EventPublisher(endpoint)
    sub = EventSubscriber(endpoint, topics=topics)
    time.sleep(0.05)
    return pub, sub, endpoint


# -- publish / subscribe ---------------------------------------------------


def test_publish_subscribe_roundtrip():
    pub, sub, _ = _make_pair()
    try:
        pub.publish("tuning.committed", {"proposal_id": "prop-abcd1234", "gen": 100})
        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, ts, payload = msg
        assert topic == "tuning.committed"
        assert payload == {"proposal_id": "prop-abcd1234", "gen": 100}
        assert "T" in ts  # ISO-8601
    finally:
        sub.close()
        pub.close()


def test_topic_filter_only_delivers_matching_prefix():
    pub, sub, _ = _make_pair(topics=["tuning."])
    try:
        pub.publish("telemetry.5min", {"x": 1})   # filtered OUT
        pub.publish("tuning.committed", {"x": 2}) # filtered IN
        pub.publish("tuning.rejected", {"x": 3})  # filtered IN
        received_topics = []
        for _ in range(3):
            msg = sub.recv(timeout_ms=300)
            if msg is None:
                break
            received_topics.append(msg[0])
        assert "telemetry.5min" not in received_topics
        assert "tuning.committed" in received_topics
        assert "tuning.rejected" in received_topics
    finally:
        sub.close()
        pub.close()


def test_subscriber_timeout_returns_none():
    pub, sub, _ = _make_pair()
    try:
        assert sub.recv(timeout_ms=100) is None
    finally:
        sub.close()
        pub.close()


def test_publish_after_close_is_silent():
    pub = EventPublisher(_unique_inproc_endpoint())
    pub.close()
    pub.publish("anything", {"x": 1})  # must not raise
    pub.close()  # idempotent


def test_publish_non_serializable_payload_does_not_raise():
    pub, sub, _ = _make_pair()
    try:
        # object() is not JSON-serializable; default=str will make it a
        # string repr, so it actually IS serializable. Use a cycle.
        cycle: dict = {}
        cycle["self"] = cycle
        pub.publish("t", cycle)  # should swallow ValueError silently
        # Nothing was sent, so the subscriber sees nothing.
        assert sub.recv(timeout_ms=100) is None
    finally:
        sub.close()
        pub.close()


# -- StateWatcher ----------------------------------------------------------


def test_state_watcher_publishes_for_new_telemetry_file(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TELEMETRY_5MIN])
    time.sleep(0.05)
    try:
        watcher = StateWatcher(pub, tmp_path)
        # Bootstrap pass: no files yet, nothing published.
        assert watcher.poll_once() == 0

        telemetry = {"gen": 1_500_000, "entropy": 0.78}
        (tmp_path / "telemetry_20260421T080000.json").write_text(json.dumps(telemetry))
        assert watcher.poll_once() == 1
        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, _ts, payload = msg
        assert topic == TOPIC_TELEMETRY_5MIN
        assert payload["file"] == "telemetry_20260421T080000.json"
        assert payload["telemetry"] == telemetry

        # A second poll with no new files: no event.
        assert watcher.poll_once() == 0
    finally:
        sub.close()
        pub.close()


def test_state_watcher_bootstrap_skips_existing_files(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TELEMETRY_5MIN])
    time.sleep(0.05)
    try:
        # Pre-existing file before the watcher starts — must not be announced.
        (tmp_path / "telemetry_historical.json").write_text(json.dumps({"gen": 1}))
        watcher = StateWatcher(pub, tmp_path)
        watcher.run  # initialization side-effect normally happens in run(), but
        # we need to simulate it: the Thread.run bootstraps _seen. Do it here
        # explicitly for synchronous testing.
        watcher._seen = {p.name for p in tmp_path.glob(watcher.glob_pattern)}
        assert watcher.poll_once() == 0
        assert sub.recv(timeout_ms=100) is None  # nothing published
    finally:
        sub.close()
        pub.close()


def test_state_watcher_ignores_malformed_json(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TELEMETRY_5MIN])
    time.sleep(0.05)
    try:
        watcher = StateWatcher(pub, tmp_path)
        (tmp_path / "telemetry_bad.json").write_text("{not valid json")
        # poll_once reports it as "attempted" but _seen is kept clean for retry;
        # we just verify no event leaked out.
        watcher.poll_once()
        assert sub.recv(timeout_ms=100) is None
    finally:
        sub.close()
        pub.close()


# -- TuningState integration ----------------------------------------------


class FakeGen:
    def __init__(self, start: int = 1_000_000) -> None:
        self.value = start

    def advance(self, n: int) -> None:
        self.value += n

    def __call__(self) -> int:
        return self.value


def test_tuning_commit_emits_tuning_committed(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=["tuning."])
    time.sleep(0.05)
    try:
        gen = FakeGen()
        state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=pub)
        proposal = state.propose(
            params={"signal_interval": 14},
            source="human:kevin",
            justification="test",
            mode="commit-pending",
        )
        state.commit(proposal_id=proposal["proposal_id"], approver="policy:auto")

        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, _ts, payload = msg
        assert topic == TOPIC_TUNING_COMMITTED
        assert payload["proposal_id"] == proposal["proposal_id"]
        assert payload["approver"] == "policy:auto"
        assert payload["params"] == {"signal_interval": 14}
        assert payload["effective_after"]["signal_interval"] == 14
    finally:
        sub.close()
        pub.close()


def test_tuning_gate_denial_emits_tuning_rejected(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TUNING_REJECTED])
    time.sleep(0.05)
    try:
        gen = FakeGen()
        state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=pub)
        proposal = state.propose(
            params={"magnon_coupling": 2.5},       # HUMAN_APPROVAL
            source="agent:opus",
            justification="t",
            mode="commit-pending",
        )
        # policy:auto is insufficient → TuningError + emit tuning.rejected
        from scripts.tuning_api import TuningError
        with pytest.raises(TuningError):
            state.commit(proposal_id=proposal["proposal_id"], approver="policy:auto")

        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, _ts, payload = msg
        assert topic == TOPIC_TUNING_REJECTED
        assert payload["stage"] == "commit"
        assert payload["error"] == "human_approval_required"
    finally:
        sub.close()
        pub.close()


def test_propose_validation_failure_emits_rejected(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TUNING_REJECTED])
    time.sleep(0.05)
    try:
        gen = FakeGen()
        state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=pub)
        state.propose(
            params={"signal_interval": 0},  # below min → validation fails
            source="agent:opus",
            justification="t",
            mode="dry-run",
        )
        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, _ts, payload = msg
        assert topic == TOPIC_TUNING_REJECTED
        assert payload["stage"] == "propose"
        assert "signal_interval" in payload["errors"]
    finally:
        sub.close()
        pub.close()


def test_rollback_emits_tuning_rolled_back(tmp_path):
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TUNING_ROLLED_BACK])
    time.sleep(0.05)
    try:
        gen = FakeGen()
        state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=pub)
        p1 = state.propose(
            params={"signal_interval": 15},
            source="human:kevin", justification="t", mode="commit-pending",
        )
        state.commit(proposal_id=p1["proposal_id"], approver="policy:auto")
        gen.advance(MIN_GEN_BETWEEN_COMMITS_PER_PARAM + 1)
        p2 = state.propose(
            params={"joy_beta": 0.5},
            source="human:kevin", justification="t", mode="commit-pending",
        )
        state.commit(proposal_id=p2["proposal_id"], approver="policy:auto")
        # Rollback to p1's snapshot.
        state.rollback(to_proposal_id=p1["proposal_id"])

        # Drain events; last one should be tuning.rolled_back.
        rolled_back = None
        for _ in range(5):
            msg = sub.recv(timeout_ms=300)
            if msg and msg[0] == TOPIC_TUNING_ROLLED_BACK:
                rolled_back = msg
                break
        assert rolled_back is not None
        _topic, _ts, payload = rolled_back
        assert payload["to_proposal_id"] == p1["proposal_id"]
        assert "joy_beta" in payload["changed_back"]
    finally:
        sub.close()
        pub.close()


def test_tuning_state_without_publisher_works(tmp_path):
    """Regression: TuningState with event_publisher=None must not raise."""
    gen = FakeGen()
    state = TuningState(data_dir=tmp_path, gen_getter=gen, event_publisher=None)
    prop = state.propose(
        params={"signal_interval": 15},
        source="human:kevin", justification="t", mode="commit-pending",
    )
    entry = state.commit(proposal_id=prop["proposal_id"], approver="policy:auto")
    assert entry["effective_after"]["signal_interval"] == 15
