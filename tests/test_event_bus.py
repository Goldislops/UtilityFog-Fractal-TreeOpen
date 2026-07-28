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
    TIMESTAMP_DECODE_MESSAGE,
    TOPIC_DECODE_MESSAGE,
    TOPIC_TELEMETRY_5MIN,
    TOPIC_TUNING_COMMITTED,
    TOPIC_TUNING_REJECTED,
    TOPIC_TUNING_ROLLED_BACK,
    WIRE_FRAME_COUNT_MESSAGE,
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
        # A malformed file publishes nothing, is NOT counted as a published
        # event, and is left retry-eligible (kept out of _seen) so a later poll
        # can retry it once it becomes valid.
        assert watcher.poll_once() == 0
        assert sub.recv(timeout_ms=100) is None
        assert "telemetry_bad.json" not in watcher._seen
    finally:
        sub.close()
        pub.close()


def test_state_watcher_incomplete_then_completed_retries_and_emits_once(tmp_path):
    """Regression (retry + accounting): a telemetry file caught mid-write must
    not be consumed. The first poll returns 0 and leaves the name retry-eligible;
    once the file is completed a later poll emits exactly one correct event and
    marks it seen; a further poll is a no-op (no duplicate).
    """
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TELEMETRY_5MIN])
    time.sleep(0.05)
    try:
        watcher = StateWatcher(pub, tmp_path)
        name = "telemetry_20260724T090000.json"
        path = tmp_path / name

        # 1. Incomplete (mid-write) JSON: no event, count 0, name retry-eligible.
        path.write_text('{"gen": ')  # truncated → json.loads raises ValueError
        assert watcher.poll_once() == 0
        assert sub.recv(timeout_ms=100) is None
        assert name not in watcher._seen

        # 2. Complete the same file: the next poll emits exactly one event.
        telemetry = {"gen": 1_500_001, "entropy": 0.5}
        path.write_text(json.dumps(telemetry))
        assert watcher.poll_once() == 1
        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, _ts, payload = msg
        assert topic == TOPIC_TELEMETRY_5MIN
        assert payload["file"] == name
        assert payload["telemetry"] == telemetry
        assert name in watcher._seen

        # 3. A further poll: no duplicate.
        assert watcher.poll_once() == 0
        assert sub.recv(timeout_ms=100) is None
    finally:
        sub.close()
        pub.close()


def test_state_watcher_mixed_poll_counts_only_valid_and_retains_incomplete(tmp_path):
    """Regression (mixed batch): a single poll containing one valid and one
    incomplete file counts/emits only the valid one and retains the incomplete
    one for a later retry.
    """
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TELEMETRY_5MIN])
    time.sleep(0.05)
    try:
        watcher = StateWatcher(pub, tmp_path)
        good_name = "telemetry_aaa_good.json"
        bad_name = "telemetry_bbb_incomplete.json"
        good = {"gen": 7, "ok": True}
        (tmp_path / good_name).write_text(json.dumps(good))
        (tmp_path / bad_name).write_text('{"gen":')  # incomplete

        # Only the valid file is counted and emitted.
        assert watcher.poll_once() == 1
        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        _topic, _ts, payload = msg
        assert payload["file"] == good_name
        assert payload["telemetry"] == good
        assert sub.recv(timeout_ms=100) is None  # no second event

        assert good_name in watcher._seen        # valid marked seen
        assert bad_name not in watcher._seen      # incomplete retained for retry

        # Completing the incomplete file lets a later poll emit it exactly once.
        (tmp_path / bad_name).write_text(json.dumps({"gen": 8}))
        assert watcher.poll_once() == 1
        msg2 = sub.recv(timeout_ms=500)
        assert msg2 is not None
        assert msg2[2]["file"] == bad_name
        assert bad_name in watcher._seen
    finally:
        sub.close()
        pub.close()


def test_state_watcher_transient_read_failure_is_retry_eligible(tmp_path):
    """Regression (caught read-failure path): a glob-matching entry that cannot
    be read as a text file (here a directory) exercises the OSError arm of
    _publish_for. poll_once must count 0, emit nothing, and leave it
    retry-eligible rather than consuming it.
    """
    pub = EventPublisher(_unique_inproc_endpoint())
    sub = EventSubscriber(pub.endpoint, topics=[TOPIC_TELEMETRY_5MIN])
    time.sleep(0.05)
    try:
        watcher = StateWatcher(pub, tmp_path)
        # A directory whose name matches the telemetry glob: read_text() raises
        # an OSError subclass (IsADirectoryError / PermissionError).
        dir_name = "telemetry_readfail.json"
        (tmp_path / dir_name).mkdir()
        assert watcher.poll_once() == 0
        assert sub.recv(timeout_ms=100) is None
        assert dir_name not in watcher._seen
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
        # policy:auto is refused post-quarantine; a human approver commits.
        state.commit(proposal_id=proposal["proposal_id"], approver="human:kevin")

        msg = sub.recv(timeout_ms=500)
        assert msg is not None
        topic, _ts, payload = msg
        assert topic == TOPIC_TUNING_COMMITTED
        assert payload["proposal_id"] == proposal["proposal_id"]
        assert payload["approver"] == "human:kevin"
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
        # A non-human approver on a HUMAN_APPROVAL param → human_approval_required
        # + emit tuning.rejected. (Uses a neutral approver, not policy:auto, so
        # this exercises the human-approval gate rather than the Package R
        # auto-commit quarantine — both are 403 denials that emit tuning.rejected.)
        from scripts.tuning_api import TuningError
        with pytest.raises(TuningError):
            state.commit(proposal_id=proposal["proposal_id"], approver="agent:opus")

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
        state.commit(proposal_id=p1["proposal_id"], approver="human:kevin")
        gen.advance(MIN_GEN_BETWEEN_COMMITS_PER_PARAM + 1)
        p2 = state.propose(
            params={"joy_beta": 0.5},
            source="human:kevin", justification="t", mode="commit-pending",
        )
        state.commit(proposal_id=p2["proposal_id"], approver="human:kevin")
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
    entry = state.commit(proposal_id=prop["proposal_id"], approver="human:kevin")
    assert entry["effective_after"]["signal_interval"] == 15


# -- EventSubscriber.recv inbound wire-shape totality ------------------------
#
# recv() decodes frames that arrive off the network, so their structure is not
# guaranteed by anything the publisher promises. Before this package it
# tuple-unpacked the frame list directly, decoded topic/timestamp in the return
# expression outside every guard, and returned whatever json.loads produced:
#
#   - zero, one, two or four frames raised Python's own unpacking ValueError,
#     whose text reports the SUPPLIED frame count ("expected 3, got 2") rather
#     than a fixed module refusal;
#   - invalid UTF-8 in the topic or timestamp frame raised UnicodeDecodeError
#     carrying the offending byte and its position;
#   - valid JSON whose top-level value was an array, string, number, boolean or
#     null was returned as that value, contradicting the declared
#     Optional[tuple[str, str, dict]].
#
# Every case below drives the genuine recv() through a controlled fake socket:
# no ZMQ context, no socket, no endpoint, no port and no network. The existing
# in-process PUB/SUB round trips above are untouched and still cover the real
# transport.


class _FakeSocket:
    """Controlled stand-in for the SUB socket."""

    def __init__(self, frames=None, error=None):
        self.frames = frames
        self.error = error
        self.sockopts = []

    def setsockopt(self, opt, value):
        self.sockopts.append((opt, value))

    def recv_multipart(self):
        if self.error is not None:
            raise self.error
        return self.frames


def _wire_subscriber(frames=None, error=None, closed=False) -> EventSubscriber:
    """A real EventSubscriber wired to a fake socket.

    Built with `object.__new__` so no context is created, no socket opened and
    no endpoint connected -- the method under test is the genuine `recv()`, never
    a replacement.
    """
    subscriber = object.__new__(EventSubscriber)
    subscriber.sock = _FakeSocket(frames=frames, error=error)
    subscriber._closed = closed
    return subscriber


_WIRE_TOPIC = b"tuning.committed"
_WIRE_TS = b"2026-07-26T06:00:00Z"


def _wire_recv(frames=None, error=None, closed=False):
    return _wire_subscriber(frames, error, closed).recv()


# -- preserved outcomes -------------------------------------------------------


def test_wire_valid_three_frame_message_is_unchanged():
    assert _wire_recv([_WIRE_TOPIC, _WIRE_TS, b'{"a": 1, "b": [2, 3]}']) == (
        "tuning.committed",
        "2026-07-26T06:00:00Z",
        {"a": 1, "b": [2, 3]},
    )


def test_wire_topic_and_timestamp_are_exact_str():
    topic, timestamp, payload = _wire_recv([_WIRE_TOPIC, _WIRE_TS, b"{}"])
    assert type(topic) is str and type(timestamp) is str
    assert topic == "tuning.committed"
    assert timestamp == "2026-07-26T06:00:00Z"


def test_wire_valid_non_ascii_utf8_metadata_is_accepted():
    """No over-refusal: strict UTF-8 still accepts non-ASCII metadata."""
    topic, timestamp, payload = _wire_recv(
        ["tuning.check".encode("utf-8"), "2026-07-26T06:00:00Z✓".encode("utf-8"), b"{}"]
    )
    assert topic == "tuning.check"
    assert timestamp == "2026-07-26T06:00:00Z✓"


def test_wire_timeout_still_returns_none():
    assert _wire_recv(error=zmq.Again()) is None


def test_wire_closed_subscriber_still_raises_runtime_error():
    with pytest.raises(RuntimeError, match="subscriber is closed"):
        _wire_recv([_WIRE_TOPIC, _WIRE_TS, b"{}"], closed=True)


def test_wire_recv_still_applies_the_receive_timeout():
    subscriber = _wire_subscriber([_WIRE_TOPIC, _WIRE_TS, b"{}"])
    subscriber.recv(timeout_ms=250)
    assert (zmq.RCVTIMEO, 250) in subscriber.sock.sockopts


@pytest.mark.parametrize(
    "error",
    [zmq.ZMQError(), RuntimeError("boom"), OSError("boom"), MemoryError("oom")],
    ids=["zmq_error", "runtime_error", "os_error", "memory_error"],
)
def test_wire_unexpected_socket_error_still_propagates(error):
    """Only zmq.Again is absorbed; no blanket except was added."""
    with pytest.raises(type(error)):
        _wire_recv(error=error)


# -- multipart structure ------------------------------------------------------


@pytest.mark.parametrize(
    "frames",
    [
        [],
        [_WIRE_TOPIC],
        [_WIRE_TOPIC, _WIRE_TS],
        [_WIRE_TOPIC, _WIRE_TS, b"{}", b"extra"],
        [_WIRE_TOPIC, _WIRE_TS, b"{}", b"x", b"y"],
    ],
    ids=["zero_frames", "one_frame", "two_frames", "four_frames", "five_frames"],
)
def test_wire_frame_count_other_than_three_is_refused(frames):
    with pytest.raises(ValueError) as exc:
        _wire_recv(frames)
    assert type(exc.value) is ValueError
    assert str(exc.value) == WIRE_FRAME_COUNT_MESSAGE


def test_wire_frame_count_refusal_names_no_number():
    """The supplied frame count must not appear -- the fixed message has no digits."""
    assert not any(character.isdigit() for character in WIRE_FRAME_COUNT_MESSAGE)


# -- metadata UTF-8 -----------------------------------------------------------


@pytest.mark.parametrize(
    "topic_bytes",
    [b"\xff", b"\xff\xfe", b"valid\xffinvalid", b"\x80\x81\x82"],
    ids=["single_bad_byte", "bom_like", "mid_string", "continuation_bytes"],
)
def test_wire_invalid_utf8_topic_is_refused(topic_bytes):
    with pytest.raises(ValueError) as exc:
        _wire_recv([topic_bytes, _WIRE_TS, b"{}"])
    assert type(exc.value) is ValueError
    assert str(exc.value) == TOPIC_DECODE_MESSAGE


@pytest.mark.parametrize(
    "ts_bytes",
    [b"\xff", b"\xff\xfe", b"2026\xff07", b"\x80\x81\x82"],
    ids=["single_bad_byte", "bom_like", "mid_string", "continuation_bytes"],
)
def test_wire_invalid_utf8_timestamp_is_refused(ts_bytes):
    with pytest.raises(ValueError) as exc:
        _wire_recv([_WIRE_TOPIC, ts_bytes, b"{}"])
    assert type(exc.value) is ValueError
    assert str(exc.value) == TIMESTAMP_DECODE_MESSAGE


def test_wire_metadata_refusals_expose_nothing_supplied():
    """No frame bytes, frame count, decoding position, representation or
    underlying UnicodeDecodeError text may reach the caller."""
    cases = [
        ([_WIRE_TOPIC, _WIRE_TS], WIRE_FRAME_COUNT_MESSAGE),
        ([_WIRE_TOPIC, _WIRE_TS, b"{}", b"LEAKFRAME"], WIRE_FRAME_COUNT_MESSAGE),
        ([b"\xffLEAKTOPIC", _WIRE_TS, b"{}"], TOPIC_DECODE_MESSAGE),
        ([_WIRE_TOPIC, b"\xffLEAKSTAMP", b"{}"], TIMESTAMP_DECODE_MESSAGE),
    ]
    for frames, expected in cases:
        with pytest.raises(ValueError) as exc:
            _wire_recv(frames)
        message = str(exc.value)
        assert message == expected
        for token in ("LEAK", "0xff", "0x80", "position", "codec", "unpack",
                      "expected 3", "invalid start byte"):
            assert token not in message
        # The underlying decode error must not be chained into the traceback.
        assert exc.value.__cause__ is None
        assert exc.value.__context__ is None or exc.value.__suppress_context__


# -- payload result shape is always an exact dict -----------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        (b'{"a": 1}', {"a": 1}),
        (b"{}", {}),
        (b'{"a": {"b": [1, 2]}, "c": null}', {"a": {"b": [1, 2]}, "c": None}),
    ],
    ids=["object", "empty_object", "nested_object"],
)
def test_wire_json_object_payload_is_returned_unchanged(body, expected):
    topic, timestamp, payload = _wire_recv([_WIRE_TOPIC, _WIRE_TS, body])
    assert type(payload) is dict
    assert payload == expected


@pytest.mark.parametrize(
    "body",
    [b"[1, 2, 3]", b"[]", b'"text"', b'""', b"42", b"-7", b"3.14", b"0.0",
     b"true", b"false", b"null"],
    ids=["array", "empty_array", "string", "empty_string", "integer",
         "negative_integer", "float", "zero_float", "true", "false", "null"],
)
def test_wire_valid_non_object_json_becomes_an_exact_raw_dict(body):
    """Pre-fix these were returned as list/str/int/float/bool/None."""
    topic, timestamp, payload = _wire_recv([_WIRE_TOPIC, _WIRE_TS, body])
    assert type(payload) is dict
    # Built from the decoded payload TEXT, never a representation of the decoded
    # Python value: a JSON string keeps its quotes.
    assert payload == {"_raw": body.decode("utf-8")}


@pytest.mark.parametrize(
    "body",
    [b"{not json", b"", b"   ", b"{'single': 1}", b"[1,", b'{"a": }'],
    ids=["brace_text", "empty", "whitespace", "single_quotes", "unclosed_array",
         "bad_value"],
)
def test_wire_malformed_json_preserves_the_raw_fallback(body):
    topic, timestamp, payload = _wire_recv([_WIRE_TOPIC, _WIRE_TS, body])
    assert type(payload) is dict
    assert payload == {"_raw": body.decode("utf-8")}


def test_wire_invalid_utf8_payload_preserves_the_replacement_raw_fallback():
    body = b"\xff\xfe\x00"
    topic, timestamp, payload = _wire_recv([_WIRE_TOPIC, _WIRE_TS, body])
    assert type(payload) is dict
    assert payload == {"_raw": body.decode("utf-8", errors="replace")}


def test_wire_every_payload_category_returns_an_exact_dict():
    """One sweep proving the declared dict contract holds for every shape."""
    bodies = [
        b'{"a": 1}', b"{}", b'{"n": {"d": 1}}',
        b"[1, 2]", b"[]", b'"s"', b"1", b"1.5", b"true", b"false", b"null",
        b"{not json", b"", b"\xff\xfe",
    ]
    for body in bodies:
        topic, timestamp, payload = _wire_recv([_WIRE_TOPIC, _WIRE_TS, body])
        assert type(payload) is dict, body
