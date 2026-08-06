"""Tests for `scripts/lucid_server.handle_client` top-level JSON-shape handling.

`handle_client` reads browser WebSocket frames, `json.loads` each one, and then
reaches for `.get('type')`. Valid JSON is not necessarily a JSON *object*:
`null`, booleans, numbers, strings and arrays all decode successfully but have
no `.get`, so the attribute access raised `AttributeError`, escaped the
`json.JSONDecodeError` guard, and terminated that client's handler — the
browser was disconnected by one malformed frame instead of the frame being
ignored. Construction now accepts only an exact built-in `dict` and silently
ignores every other decoded shape, continuing to read later messages exactly
as it already did for syntactically invalid JSON.

Everything here runs in-process against the real coroutine driven by a
controlled asynchronous fake socket: no real WebSocket, no browser, no network,
no snapshot files outside pytest's own `tmp_path` (the pickle-refusal
tests appended at the end write real NPZ archives there).

Scope is top-level JSON shape in `handle_client` only — not whole-server,
whole-WebSocket, authentication, authorization or payload-schema totality.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest import mock

import pytest


def _optional_dependency_stubs() -> dict:
    """Test-only stand-ins for `scripts.lucid_server`'s optional imports.

    The module imports NumPy at top level and calls `sys.exit(1)` when
    `websockets` is missing, so a minimal environment cannot import it at all.
    Only a genuinely-absent module is stubbed — where the real package is
    installed it is used untouched — and the substitution is scoped to the
    import by `patch.dict`, which restores `sys.modules` immediately afterwards.
    This keeps the malformed-frame contract executing in ordinary maintained CI
    rather than being skipped away behind an optional dependency, and changes no
    production dependency behaviour.
    """
    stubs: dict = {}
    try:
        import numpy  # noqa: F401
    except ImportError:
        stubs["numpy"] = types.ModuleType("numpy")
    try:
        import websockets  # noqa: F401
    except ImportError:
        websockets_stub = types.ModuleType("websockets")
        exceptions_stub = types.ModuleType("websockets.exceptions")

        class ConnectionClosed(Exception):
            """Stand-in for `websockets.exceptions.ConnectionClosed`."""

        exceptions_stub.ConnectionClosed = ConnectionClosed
        websockets_stub.exceptions = exceptions_stub
        stubs["websockets"] = websockets_stub
        stubs["websockets.exceptions"] = exceptions_stub
    return stubs


with mock.patch.dict(sys.modules, _optional_dependency_stubs()):
    from scripts import lucid_server

# `lucid_server` holds its own references to whatever was bound above, so the
# handler stays callable after `patch.dict` restores `sys.modules`.


PING = json.dumps({"type": "ping"})


class FakeWebSocket:
    """Async-iterable stand-in for one connected browser.

    Records what the handler actually consumed and sent, and samples the
    registration state at the moment each frame is delivered.
    """

    def __init__(self, messages):
        self.messages = list(messages)
        self.sent: list = []
        self.delivered: list = []
        self.registered_during: list = []
        self.remote_address = ("test-client", 0)

    def __aiter__(self):
        return self._deliver()

    async def _deliver(self):
        for message in self.messages:
            self.registered_during.append(self in lucid_server.connected_clients)
            self.delivered.append(message)
            yield message

    async def send(self, message):
        self.sent.append(message)


@pytest.fixture(autouse=True)
def _isolated_client_registry():
    """`connected_clients` is module state; keep every test independent."""
    lucid_server.connected_clients.clear()
    yield
    lucid_server.connected_clients.clear()


def _drive(messages, monkeypatch) -> FakeWebSocket:
    """Run the real `handle_client` over `messages`; return the fake socket.

    The initial-snapshot send is neutralised so no test depends on the real data
    directory or on external snapshots; that path is exercised separately by
    `test_initial_snapshot_frame_still_sent`.
    """
    monkeypatch.setattr(lucid_server, "find_latest_snapshot", lambda data_dir: None)
    websocket = FakeWebSocket(messages)
    asyncio.run(lucid_server.handle_client(websocket))
    return websocket


def _pongs(websocket) -> list:
    return [s for s in websocket.sent if json.loads(s).get("type") == "pong"]


def _assert_whole_stream_consumed(websocket, expected) -> None:
    """Anti-vacuity guard.

    The handler must have read EVERY frame, including the trailing ping. If it
    died on an earlier frame the generator would stop there, so without this a
    test could 'pass' merely because the stream ended before the follow-up ping.
    """
    assert websocket.delivered == list(expected)


# -- non-object top-level JSON is ignored, and the client survives ------------


_NON_OBJECT_JSON = [
    "null",
    "true",
    "false",
    "0",
    "42",
    "-17",
    "3.14",
    '""',
    '"text"',
    '"{\\"type\\": \\"ping\\"}"',
    "[]",
    "[1, 2, 3]",
    '[{"type": "ping"}]',
]
_NON_OBJECT_IDS = [
    "null",
    "true",
    "false",
    "zero",
    "int",
    "negative_int",
    "float",
    "empty_string",
    "string",
    "string_looking_like_an_event",
    "empty_array",
    "array",
    "array_of_events",
]


@pytest.mark.parametrize("payload", _NON_OBJECT_JSON, ids=_NON_OBJECT_IDS)
def test_non_object_json_is_ignored_and_client_keeps_reading(payload, monkeypatch):
    """Pre-fix each of these raised AttributeError out of the handler, so the
    trailing ping was never read and the client was disconnected."""
    websocket = _drive([payload, PING], monkeypatch)
    _assert_whole_stream_consumed(websocket, [payload, PING])
    assert len(_pongs(websocket)) == 1          # the later valid ping still answered
    assert len(websocket.sent) == 1             # the non-object frame drew no reply
    assert websocket not in lucid_server.connected_clients


@pytest.mark.parametrize("payload", _NON_OBJECT_JSON, ids=_NON_OBJECT_IDS)
def test_non_object_json_stays_registered_until_the_stream_ends(payload, monkeypatch):
    """Registration must survive the ignored frame: both frames are delivered
    while this client is still in `connected_clients`."""
    websocket = _drive([payload, PING], monkeypatch)
    assert websocket.registered_during == [True, True]


def test_many_non_object_messages_do_not_end_the_stream(monkeypatch):
    payloads = ["null", "true", "42", '"s"', "[]", "{not json", "[1]", PING]
    websocket = _drive(payloads, monkeypatch)
    _assert_whole_stream_consumed(websocket, payloads)
    assert len(_pongs(websocket)) == 1
    assert len(websocket.sent) == 1


def test_non_object_json_produces_no_event_output_and_exposes_no_value(
    monkeypatch, capsys
):
    """No reply, no event action, and nothing about the supplied value or its
    type is printed."""
    payloads = ['"LEAK-SENTINEL"', '["LEAK-SENTINEL"]', "null", "1234567", PING]
    websocket = _drive(payloads, monkeypatch)
    _assert_whole_stream_consumed(websocket, payloads)
    output = capsys.readouterr().out
    assert "LEAK-SENTINEL" not in output
    assert "1234567" not in output
    for type_name in ("NoneType", "AttributeError", "not a dict", "object has no attribute"):
        assert type_name not in output
    for event_marker in ("Click at", "Polish event", "Inject"):
        assert event_marker not in output
    assert len(_pongs(websocket)) == 1


# -- syntactically invalid JSON keeps its established handling ---------------


@pytest.mark.parametrize(
    "payload",
    ["{not json", "", "   ", "{'single': 'quotes'}", "[1, 2", '{"unterminated": '],
    ids=["brace_text", "empty", "whitespace", "single_quotes", "unclosed_array",
         "unterminated_object"],
)
def test_malformed_json_is_still_ignored_without_disconnect(payload, monkeypatch):
    websocket = _drive([payload, PING], monkeypatch)
    _assert_whole_stream_consumed(websocket, [payload, PING])
    assert len(_pongs(websocket)) == 1
    assert len(websocket.sent) == 1


# -- established valid-object behaviour is unchanged -------------------------


def test_valid_ping_receives_pong(monkeypatch):
    websocket = _drive([PING], monkeypatch)
    assert len(websocket.sent) == 1
    reply = json.loads(websocket.sent[0])
    assert reply["type"] == "pong"
    assert isinstance(reply["time"], float)


def test_repeated_pings_each_receive_a_pong(monkeypatch):
    websocket = _drive([PING, PING, PING], monkeypatch)
    _assert_whole_stream_consumed(websocket, [PING, PING, PING])
    assert len(_pongs(websocket)) == 3


def test_click_event_still_handled(monkeypatch, capsys):
    websocket = _drive(
        [json.dumps({"type": "click", "x": 1, "y": 2, "z": 3}), PING], monkeypatch
    )
    assert "Click at (1,2,3)" in capsys.readouterr().out
    assert len(_pongs(websocket)) == 1


def test_polish_event_still_handled(monkeypatch, capsys):
    websocket = _drive([json.dumps({"type": "polish"}), PING], monkeypatch)
    assert "Polish event" in capsys.readouterr().out
    assert len(_pongs(websocket)) == 1


def test_inject_event_still_handled(monkeypatch, capsys):
    websocket = _drive(
        [json.dumps({"type": "inject", "cell_type": 2, "x": 4, "y": 5, "z": 6}), PING],
        monkeypatch,
    )
    output = capsys.readouterr().out
    assert "Inject 2 at (4,5,6)" in output
    assert len(_pongs(websocket)) == 1


@pytest.mark.parametrize(
    "event",
    [{"type": "nope"}, {"type": ""}, {}, {"a": 1}, {"type": 5}, {"type": None}],
    ids=["unknown_type", "empty_type", "empty_object", "no_type_key", "numeric_type",
         "null_type"],
)
def test_unknown_object_event_is_ignored_without_reply(event, monkeypatch):
    payload = json.dumps(event)
    websocket = _drive([payload, PING], monkeypatch)
    _assert_whole_stream_consumed(websocket, [payload, PING])
    assert len(_pongs(websocket)) == 1
    assert len(websocket.sent) == 1


def test_click_with_missing_coordinates_still_uses_defaults(monkeypatch, capsys):
    """An exact object with absent keys keeps the established `.get` defaults."""
    websocket = _drive([json.dumps({"type": "click"}), PING], monkeypatch)
    assert "Click at (0,0,0)" in capsys.readouterr().out
    assert len(_pongs(websocket)) == 1


# -- registration lifecycle ---------------------------------------------------


def test_client_is_registered_while_active_and_removed_on_completion(monkeypatch):
    websocket = _drive([PING, PING], monkeypatch)
    assert websocket.registered_during == [True, True]
    assert websocket not in lucid_server.connected_clients
    assert lucid_server.connected_clients == set()


def test_client_removed_even_when_stream_is_empty(monkeypatch):
    websocket = _drive([], monkeypatch)
    assert websocket.delivered == []
    assert websocket not in lucid_server.connected_clients


# -- initial snapshot delivery (test-only stand-ins, no real snapshot) --------


def test_initial_snapshot_frame_still_sent(monkeypatch):
    monkeypatch.setattr(lucid_server, "find_latest_snapshot", lambda data_dir: "snap")
    monkeypatch.setattr(lucid_server, "extract_render_data", lambda path: {"cells": []})
    websocket = FakeWebSocket([PING])
    asyncio.run(lucid_server.handle_client(websocket))
    first = json.loads(websocket.sent[0])
    assert first["type"] == "frame"
    assert first["data"] == {"cells": []}
    assert len(_pongs(websocket)) == 1


def test_initial_snapshot_failure_does_not_block_message_handling(monkeypatch):
    """Established behaviour: a failing initial send is caught and the client
    still goes on to have its frames handled."""
    def _boom(path):
        raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr(lucid_server, "find_latest_snapshot", lambda data_dir: "snap")
    monkeypatch.setattr(lucid_server, "extract_render_data", _boom)
    websocket = FakeWebSocket(["null", PING])
    asyncio.run(lucid_server.handle_client(websocket))
    assert websocket.delivered == ["null", PING]
    assert len(_pongs(websocket)) == 1

from pathlib import Path

# This module deliberately runs without NumPy (see `_optional_dependency_stubs`
# above): the malformed-frame contract must execute in ordinary maintained CI
# rather than being skipped away behind an optional dependency. The pickle
# tests below DO need real NumPy, so it is imported defensively and only those
# tests are skipped when it is absent -- importing it unconditionally would
# fail collection of this whole file, taking the 330 lines above with it.
try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:  # pragma: no cover - exercised only in a bare environment
    np = None
    _HAVE_NUMPY = False

requires_numpy = pytest.mark.skipif(not _HAVE_NUMPY, reason="numpy not installed")


# ===========================================================================
# Pickle refusal -- lucid_server must never unpickle an NPZ member
#
# An object-dtype member is stored as a pickle, so loading one with pickle
# enabled is arbitrary code execution by construction. The payload below is
# harmless: its reduction writes ONE marker file inside pytest's own tmp_path
# and returns. `__reduce__` runs at PICKLE time and only records the callable,
# so writing the archive is inert; the call would happen at UNPICKLE time.
#
# Scope: an object-member refusal, NOT whole-archive validation.
# ===========================================================================

_LS_MARKER = "LUCID_PAYLOAD_EXECUTED"


def _create_marker_ls(directory: str) -> str:
    """Stand in for a malicious payload; deliberately inert.

    Module scope is required -- pickle stores a module-qualified reference, so
    a function defined inside a test body could not be resolved at load time.
    """
    marker = Path(directory) / _LS_MARKER
    marker.write_text("payload executed", encoding="utf-8")
    return str(marker)


class _PayloadLs:
    """Its reduction calls the marker writer when unpickled."""

    def __init__(self, directory):
        self._directory = str(directory)

    def __reduce__(self):
        return (_create_marker_ls, (self._directory,))


def _payload_array_ls(directory):
    return np.array([_PayloadLs(directory)], dtype=object)


def _marker_ls(tmp_path):
    return tmp_path / _LS_MARKER


def _write_snapshot_ls(path, compressed=False, **members):
    """A real NPZ. Object members pickle on the way in, which is harmless."""
    payload = {
        "lattice": np.ones((4, 4, 4), dtype=np.uint8),
        "memory_grid": np.zeros((8, 4, 4, 4), dtype=np.float32),
        "generation": 7,
    }
    payload.update(members)
    writer = np.savez_compressed if compressed else np.savez
    writer(path, **payload)
    return str(path)


@requires_numpy
def test_ls_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. This is the only place in this
    module that enables pickle."""
    archive = _write_snapshot_ls(
        tmp_path / "control.npz", lattice=_payload_array_ls(tmp_path)
    )
    assert not _marker_ls(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_ls(tmp_path).exists(), "the payload fixture is inert; fix it"


@requires_numpy
@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_object_payload_is_refused_by_extract_render_data(tmp_path, field):
    archive = _write_snapshot_ls(
        tmp_path / f"{field}.npz", **{field: _payload_array_ls(tmp_path)}
    )
    with pytest.raises(ValueError) as excinfo:
        lucid_server.extract_render_data(archive)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_ls(tmp_path).exists(), "the pickle payload executed"


def _structured_payload_ls(directory):
    structured = np.empty((1,), dtype=[("payload", "O"), ("n", "i4")])
    structured["payload"][0] = _PayloadLs(directory)
    structured["n"][0] = 1
    return structured


@requires_numpy
def test_the_structured_payload_also_fires_when_pickle_is_enabled(tmp_path):
    """A structured dtype takes a different path through NumPy's descriptor
    handling than a plain object array, so it needs its own control."""
    archive = _write_snapshot_ls(
        tmp_path / "sc.npz", generation=_structured_payload_ls(tmp_path)
    )
    with np.load(archive, allow_pickle=True) as snap:
        snap["generation"]
    assert _marker_ls(tmp_path).exists(), "the structured payload is inert"


@requires_numpy
def test_an_object_bearing_structured_dtype_is_refused(tmp_path):
    """`kind == 'O'` alone would miss this; NumPy's refusal covers
    `dtype.hasobject`."""
    archive = _write_snapshot_ls(
        tmp_path / "struct.npz", generation=_structured_payload_ls(tmp_path)
    )
    with pytest.raises(ValueError) as excinfo:
        lucid_server.extract_render_data(archive)
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_ls(tmp_path).exists()


@requires_numpy
def test_the_archive_is_closed_before_any_cell_iteration(tmp_path, monkeypatch):
    """`extract_render_data` had no context manager: the handle was held open
    across up to MAX_CELLS iterations of per-cell work. `np.argwhere` is the
    first downstream call, so it is the ordering witness."""
    archive = _write_snapshot_ls(tmp_path / "clean.npz")
    real_load = np.load
    opened = []

    def _tracking_load(*args, **kwargs):
        handle = real_load(*args, **kwargs)
        opened.append(handle)
        return handle

    observed = []
    real_argwhere = np.argwhere

    def _watching_argwhere(*args, **kwargs):
        handle = opened[0]
        observed.append(handle.fid is None or handle.fid.closed)
        return real_argwhere(*args, **kwargs)

    monkeypatch.setattr(lucid_server.np, "load", _tracking_load)
    monkeypatch.setattr(lucid_server.np, "argwhere", _watching_argwhere)

    lucid_server.extract_render_data(archive)

    assert observed == [True], "the archive was still open during cell iteration"


@requires_numpy
def test_a_refusal_is_never_retried_with_pickle_enabled(tmp_path, monkeypatch):
    archive = _write_snapshot_ls(
        tmp_path / "retry.npz", lattice=_payload_array_ls(tmp_path)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(lucid_server.np, "load", _recording_load)
    with pytest.raises(ValueError):
        lucid_server.extract_render_data(archive)
    assert calls == [False]


@requires_numpy
def test_a_numeric_snapshot_still_produces_cells_and_metrics(tmp_path):
    archive = _write_snapshot_ls(tmp_path / "clean.npz", generation=np.int64(5))
    data = lucid_server.extract_render_data(archive)
    assert set(data) == {"cells", "metrics"}
    assert data["metrics"]["generation"] == 5
    assert type(data["metrics"]["generation"]) is int
    assert data["cells"], "a fully non-void lattice must yield cells"
