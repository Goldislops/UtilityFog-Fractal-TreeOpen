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

The malformed-frame tests run in-process against the real coroutine driven by
a controlled asynchronous fake socket; the pickle-refusal tests appended at
the end call `extract_render_data` directly, with no coroutine and no fake
socket. Neither uses a real WebSocket, browser or network, and neither writes
a snapshot file outside pytest's own `tmp_path`.

Scope is top-level JSON shape in `handle_client`, plus `extract_render_data`'s
object-member refusal and archive lifetime — not whole-server, whole-WebSocket,
whole-archive validation, authentication, authorization or payload-schema
totality.
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
    """A real NPZ. Object members pickle on the way in, which is harmless.

    The edge is 16 and all five schema members are present, because the
    archive now has to be ADMISSIBLE before its member dtypes matter: a 4-cube
    with three members would be refused for its shape and its membership, and
    the pickle property below would never be reached.
    """
    payload = {
        "lattice": np.ones((16, 16, 16), dtype=np.uint8),
        "memory_grid": np.zeros((8, 16, 16, 16), dtype=np.float32),
        "generation": 7,
        "ca_step": 11,
        "best_fitness": 0.5,
    }
    payload.update(members)
    writer = np.savez_compressed if compressed else np.savez
    writer(path, **payload)
    return str(path)


@pytest.fixture
def confined(tmp_path, monkeypatch):
    """Point the server's data directory at pytest's own tmp_path.

    Admission confines the archive to the configured data directory, so a
    fixture written anywhere else is refused for CONTAINMENT before the
    property under test is reached.
    """
    monkeypatch.setattr(lucid_server, "DATA_DIR", str(tmp_path))
    return tmp_path


@requires_numpy
def test_ls_payload_fixture_actually_fires_when_pickle_is_enabled(tmp_path):
    """Control. Without it, every "marker is absent" assertion below could
    pass against a payload that never worked. Pickle is enabled here and in the
    structured-dtype control below, and nowhere else in this module."""
    archive = _write_snapshot_ls(
        tmp_path / "control.npz", lattice=_payload_array_ls(tmp_path)
    )
    assert not _marker_ls(tmp_path).exists()

    with np.load(archive, allow_pickle=True) as snap:
        snap["lattice"]

    assert _marker_ls(tmp_path).exists(), "the payload fixture is inert; fix it"


@requires_numpy
@pytest.mark.parametrize("field", ["lattice", "memory_grid", "generation"])
def test_object_payload_is_refused_by_extract_render_data(confined, field):
    """The refusal moved EARLIER, and the code says so.

    An object member used to be caught by NumPy at `np.load`. It is now caught
    by admission from the member's NPY header, before NumPy is involved at
    all -- so the assertion is the typed reason code, not NumPy's message. The
    property that matters is unchanged and stronger: the payload never runs.
    """
    archive = _write_snapshot_ls(
        confined / f"v070_{field}.npz", **{field: _payload_array_ls(confined)}
    )
    with pytest.raises(lucid_server.SnapshotArchiveRejected) as excinfo:
        lucid_server.extract_render_data(archive)
    assert excinfo.value.reason == "member_dtype_object"
    assert not _marker_ls(confined).exists(), "the pickle payload executed"


@requires_numpy
def test_numpys_own_pickle_refusal_is_still_in_place_behind_admission(confined):
    """Second line of defence, kept non-vacuous.

    Admission now stops an object member first, so the load-site refusal would
    otherwise never be observed again. Calling NumPy directly on the same
    archive shows it is still exactly as it was.
    """
    archive = _write_snapshot_ls(
        confined / "v070_direct.npz", lattice=_payload_array_ls(confined)
    )
    with pytest.raises(ValueError) as excinfo:
        with np.load(archive, allow_pickle=False) as snap:
            snap["lattice"]
    assert "allow_pickle=False" in str(excinfo.value)
    assert not _marker_ls(confined).exists()


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
def test_an_object_bearing_structured_dtype_is_refused(confined):
    """`kind == 'O'` alone would miss this. Admission refuses a structured
    descriptor outright, without needing to reason about which fields carry
    objects."""
    archive = _write_snapshot_ls(
        confined / "v070_struct.npz", generation=_structured_payload_ls(confined)
    )
    with pytest.raises(lucid_server.SnapshotArchiveRejected) as excinfo:
        lucid_server.extract_render_data(archive)
    assert excinfo.value.reason == "member_dtype_structured"
    assert not _marker_ls(confined).exists()


@requires_numpy
def test_the_archive_is_closed_before_any_cell_iteration(confined, monkeypatch):
    """`extract_render_data` had no context manager: the handle was held open
    across up to MAX_CELLS iterations of per-cell work. `np.argwhere` is the
    first downstream call, so it is the ordering witness."""
    archive = _write_snapshot_ls(confined / "v070_clean.npz")
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
        # `close()` drops `zip` unconditionally; `fid` is a class attribute
        # defaulting to None, so it cannot carry this claim on its own.
        observed.append(handle.zip is None)
        return real_argwhere(*args, **kwargs)

    monkeypatch.setattr(lucid_server.np, "load", _tracking_load)
    monkeypatch.setattr(lucid_server.np, "argwhere", _watching_argwhere)

    lucid_server.extract_render_data(archive)

    assert observed == [True], "the archive was still open during cell iteration"


@requires_numpy
def test_the_descriptor_is_closed_after_a_refusal(confined, monkeypatch):
    """Closure on the exceptional path, witnessed on the real file object the
    guard opened -- a NumPy handle is never created for a refused archive."""
    archive = _write_snapshot_ls(
        confined / "v070_refused.npz", lattice=_payload_array_ls(confined)
    )
    # Hooked on `os.fdopen`, not `builtins.open`: the guard opens through
    # `os.open` so it can pass O_NONBLOCK and O_NOFOLLOW, and `os.fdopen` is
    # what turns that descriptor into the file object it yields.
    import os as _os
    opened = []
    real_fdopen = _os.fdopen

    def _tracking_fdopen(*args, **kwargs):
        handle = real_fdopen(*args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(_os, "fdopen", _tracking_fdopen)
    with pytest.raises(lucid_server.SnapshotArchiveRejected):
        lucid_server.extract_render_data(str(archive))

    assert len(opened) == 1, "the archive was opened more than once, or not at all"
    assert opened[0].closed, "the descriptor survived the refusal"


@requires_numpy
def test_a_refused_archive_never_reaches_np_load_at_all(confined, monkeypatch):
    """Stronger than "it was not retried with pickle enabled": NumPy is not
    asked to open the archive even once."""
    archive = _write_snapshot_ls(
        confined / "v070_retry.npz", lattice=_payload_array_ls(confined)
    )
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(lucid_server.np, "load", _recording_load)
    with pytest.raises(lucid_server.SnapshotArchiveRejected):
        lucid_server.extract_render_data(archive)
    assert calls == []


@requires_numpy
def test_a_valid_archive_is_loaded_with_pickle_explicitly_disabled(confined,
                                                                   monkeypatch):
    """The counterpart control: on the admitted path the explicit literal is
    still what NumPy receives, so the assertion above is about ordering rather
    than about the flag having quietly disappeared."""
    archive = _write_snapshot_ls(confined / "v070_ok.npz", compressed=True)
    real_load = np.load
    calls = []

    def _recording_load(*args, **kwargs):
        calls.append(kwargs.get("allow_pickle"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(lucid_server.np, "load", _recording_load)
    lucid_server.extract_render_data(archive)
    assert calls == [False]


def _legacy_npy_error_class_ls():
    """The exception class an ordinary numeric `.npy` produced BEFORE this branch.

    Derived, never hard-coded. At the base commit `extract_render_data` did
    `snap = np.load(...)` and then immediately `snap['lattice']`. For a non-zip
    input `np.load` returns a plain ndarray rather than an `NpzFile`, so the
    legacy failure is whatever a constant-string subscript on an ndarray raises
    in the installed NumPy.
    """
    probe = np.zeros(2)
    try:
        probe["lattice"]
    except Exception as exc:  # noqa: BLE001 - the class IS the thing under test
        return type(exc)
    raise AssertionError(
        "a constant-string subscript on a plain ndarray no longer raises; "
        "the legacy contract this test pins no longer exists"
    )


#: The exact legacy class, named rather than only derived, so the contract is
#: readable without running anything. Cross-checked against a live probe below.
_LEGACY_NPY_ERROR_LS = IndexError


@requires_numpy
def test_the_named_legacy_npy_class_is_what_numpy_actually_raises():
    """Keeps the named class and the derived one from drifting apart."""
    derived = _legacy_npy_error_class_ls()
    assert derived is _LEGACY_NPY_ERROR_LS, (
        f"the legacy class is actually {derived.__name__}, not "
        f"{_LEGACY_NPY_ERROR_LS.__name__}; update _LEGACY_NPY_ERROR_LS"
    )
    # Non-vacuity: the regression raised TypeError from the context-manager
    # protocol. If the legacy class were TypeError too, this suite could not
    # tell the broken state from the correct one.
    assert derived is not TypeError


@requires_numpy
def test_a_renamed_numeric_npy_now_receives_a_typed_refusal(confined,
                                                            monkeypatch):
    """An explicitly authorized behaviour change, recorded rather than glossed.

    A numeric `.npy` renamed `.npz` used to reach `np.load`, come back as a
    plain ndarray, and fail at the `snap['lattice']` subscript with an
    incidental `IndexError`. It is now refused by admission as not being a ZIP
    archive, before NumPy sees it. The old class is still derived below and
    asserted to be a DIFFERENT class from the new failure, so the change
    cannot be mistaken for the old behaviour surviving.
    """
    npy_source = confined / "v070_renamed.npy"
    np.save(npy_source, np.zeros((16, 16, 16), dtype=np.uint8))
    not_an_archive = confined / "v070_renamed.npz"
    not_an_archive.write_bytes(npy_source.read_bytes())

    reached = []
    monkeypatch.setattr(
        lucid_server.np, "argwhere", lambda *a, **k: reached.append("argwhere")
    )

    with pytest.raises(lucid_server.SnapshotArchiveRejected) as excinfo:
        lucid_server.extract_render_data(str(not_an_archive))

    assert excinfo.value.reason == "not_zip_archive"
    assert reached == [], "downstream processing ran on a non-archive input"
    assert not isinstance(excinfo.value, _legacy_npy_error_class_ls()), (
        "the new refusal is the old incidental IndexError after all")


@requires_numpy
def test_a_numeric_snapshot_still_produces_cells_and_metrics(confined):
    archive = _write_snapshot_ls(confined / "v070_clean.npz",
                                 generation=np.int64(5))
    data = lucid_server.extract_render_data(archive)
    assert set(data) == {"cells", "metrics"}
    assert data["metrics"]["generation"] == 5
    assert type(data["metrics"]["generation"]) is int
    assert data["cells"], "a fully non-void lattice must yield cells"
    assert data["metrics"]["grid_size"] == 16


@requires_numpy
def test_the_watcher_survives_a_rejected_snapshot_and_recovers(confined,
                                                               monkeypatch):
    """One poll over a poisoned directory, then one over a repaired one.

    The watcher must log one bounded reason and broadcast nothing, then pick
    up the next valid snapshot without a restart.
    """
    poison = confined / "v070_gen000001.npz"
    _zip_ls(poison, _schema_ls(edge=24))  # admissible-looking, wrong edge

    broadcasts = []

    async def _record(message):
        broadcasts.append(message)

    monkeypatch.setattr(lucid_server, "broadcast", _record)
    monkeypatch.setattr(lucid_server, "last_snapshot_path", None)
    monkeypatch.setattr(lucid_server, "last_snapshot_mtime", 0)

    with pytest.raises(lucid_server.SnapshotArchiveRejected):
        lucid_server.extract_render_data(str(poison))
    assert broadcasts == []

    valid = _write_snapshot_ls(confined / "v070_gen000002.npz", compressed=True)
    data = lucid_server.extract_render_data(valid)
    assert data["metrics"]["generation"] == 7, (
        "a later valid snapshot must still be accepted")


# ===========================================================================
# Structural admission -- a hostile archive must be refused BEFORE np.load
#
# `extract_render_data` is reached from the watched directory on every change
# and from every client connect, with nobody present. Pickle refusal and
# archive lifetime say nothing about an archive's shape or its cost: an
# archive could still name members outside the schema, carry traversal-bearing
# entries, declare a payload of hundreds of gigabytes, or lie about its own
# sizes, and every one of those reached `np.load` and the allocation behind it.
#
# The fixtures are built with the standard library, because NumPy cannot write
# a duplicate member, a corrupt NPY magic or a lying shape. None is hostile in
# SIZE: each is a few kilobytes, and the oversized cases lie in their headers
# rather than on disk.
# ===========================================================================

import struct  # noqa: E402
import warnings  # noqa: E402
import zipfile  # noqa: E402

_NPY_MAGIC = b"\x93NUMPY"


def _npy_ls(descr, shape, *, fortran=False, payload=None, header=None,
            version=(1, 0)):
    """One `.npy` member as raw bytes, with every field independently forgeable."""
    if header is None:
        if not shape:
            shape_text = "()"
        elif len(shape) == 1:
            shape_text = "(%d,)" % shape[0]
        else:
            shape_text = "(" + ", ".join(str(d) for d in shape) + ")"
        header = "{'descr': '%s', 'fortran_order': %s, 'shape': %s, }" % (
            descr, fortran, shape_text)
    body = header.encode("latin1")
    prelude = 10 if version == (1, 0) else 12
    body += b" " * ((-(prelude + len(body) + 1)) % 64) + b"\n"
    out = bytearray(_NPY_MAGIC) + bytes(version)
    out += (struct.pack("<H", len(body)) if version == (1, 0)
            else struct.pack("<I", len(body)))
    out += body
    if payload is None:
        digits = descr[2:] if descr[0] in "<>|=" else descr[1:]
        itemsize = int(digits) if digits else 0
        count = 1
        for dim in shape:
            count *= dim
        payload = b"\x00" * (count * itemsize)
    return bytes(out) + payload


def _schema_ls(edge=16, channels=8):
    """The five members a `v070_gen` snapshot carries, at a valid edge."""
    return {
        "lattice.npy": _npy_ls("|u1", (edge, edge, edge)),
        "memory_grid.npy": _npy_ls("<f4", (channels, edge, edge, edge)),
        "generation.npy": _npy_ls("<i8", ()),
        "ca_step.npy": _npy_ls("<i8", ()),
        "best_fitness.npy": _npy_ls("<f8", ()),
    }


def _zip_ls(path, members, *, compressed=True, duplicate=None):
    mode = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a duplicate name is the point here
        with zipfile.ZipFile(path, "w", compression=mode) as archive:
            for name, blob in members.items():
                archive.writestr(name, blob)
            if duplicate is not None:
                archive.writestr(duplicate, members[duplicate])
    return str(path)


def _hostile_ls(kind, path):
    """Build one hostile archive of the named kind at `path`."""
    members = _schema_ls()
    if kind == "duplicate_member":
        return _zip_ls(path, members, duplicate="lattice.npy")
    if kind == "traversal_name":
        members["../../escape.npy"] = _npy_ls("|u1", (1,))
        return _zip_ls(path, members)
    if kind == "backslash_name":
        members["sub\\escape.npy"] = _npy_ls("|u1", (1,))
        return _zip_ls(path, members)
    if kind == "missing_member":
        members.pop("ca_step.npy")
        return _zip_ls(path, members)
    if kind == "extra_member":
        members["surprise.npy"] = _npy_ls("|u1", (1,))
        return _zip_ls(path, members)
    if kind == "oversized_declared_payload":
        members["lattice.npy"] = _npy_ls(
            "|u8", (256, 256, 256), payload=b"",
            header="{'descr': '|u8', 'fortran_order': False, "
                   "'shape': (256, 256, 256), }")
        members["memory_grid.npy"] = _npy_ls(
            "<f4", (8, 256, 256, 256), payload=b"",
            header="{'descr': '<f4', 'fortran_order': False, "
                   "'shape': (8, 256, 256, 256), }")
        return _zip_ls(path, members)
    if kind == "oversized_edge":
        return _zip_ls(path, _schema_ls(edge=512))
    if kind == "header_payload_mismatch":
        members["lattice.npy"] = _npy_ls("|u1", (16, 16, 16)) + b"\x00" * 64
        return _zip_ls(path, members)
    if kind == "invalid_magic":
        members["lattice.npy"] = b"XXXXXX" + members["lattice.npy"][6:]
        return _zip_ls(path, members)
    if kind == "invalid_version":
        blob = bytearray(members["lattice.npy"])
        blob[6] = 9
        members["lattice.npy"] = bytes(blob)
        return _zip_ls(path, members)
    if kind == "invalid_header":
        members["lattice.npy"] = _npy_ls(
            "|u1", (16, 16, 16), header="{'descr': '|u1', 'shape': (1,), }")
        return _zip_ls(path, members)
    if kind == "object_dtype":
        members["generation.npy"] = _npy_ls("|O", (), payload=b"")
        return _zip_ls(path, members)
    if kind == "structured_dtype":
        members["generation.npy"] = _npy_ls(
            "<i8", (), payload=b"",
            header="{'descr': [('payload', '|O'), ('n', '<i4')], "
                   "'fortran_order': False, 'shape': (1,), }")
        return _zip_ls(path, members)
    if kind == "wrong_rank":
        members["lattice.npy"] = _npy_ls("|u1", (16, 16))
        return _zip_ls(path, members)
    if kind == "spatial_mismatch":
        members["memory_grid.npy"] = _npy_ls("<f4", (8, 32, 32, 32))
        return _zip_ls(path, members)
    if kind == "fortran_order":
        members["lattice.npy"] = _npy_ls("|u1", (16, 16, 16), fortran=True)
        return _zip_ls(path, members)
    if kind == "not_an_npz":
        Path(path).write_bytes(_npy_ls("|u1", (16, 16, 16)))
        return str(path)
    raise AssertionError("unknown hostile archive kind: " + kind)


_HOSTILE_KINDS = [
    "duplicate_member", "traversal_name", "backslash_name", "missing_member",
    "extra_member", "oversized_declared_payload", "oversized_edge",
    "header_payload_mismatch", "invalid_magic", "invalid_version",
    "invalid_header", "object_dtype", "structured_dtype", "wrong_rank",
    "spatial_mismatch", "fortran_order", "not_an_npz",
]


@requires_numpy
@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_hostile_archive_is_refused_before_np_load(kind, tmp_path, monkeypatch):
    """The load-reached recorder is the whole point.

    Asserting only that something was raised would pass on code that let
    `np.load` open, decompress and allocate first and then failed downstream --
    which is exactly the behaviour this replaces.
    """
    archive = _hostile_ls(kind, tmp_path / "v070_gen000001.npz")
    monkeypatch.setattr(lucid_server, "DATA_DIR", str(tmp_path))

    reached = []
    real_load = np.load

    def _recording_load(*args, **kwargs):
        reached.append(args[:1])
        return real_load(*args, **kwargs)

    monkeypatch.setattr(lucid_server.np, "load", _recording_load)

    with pytest.raises(ValueError):
        lucid_server.extract_render_data(archive)
    assert reached == [], "np.load was reached on a hostile archive"


@requires_numpy
@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_hostile_refusal_names_no_path_member_or_header(kind, tmp_path, monkeypatch):
    """The refusal reaches unattended logs, so it must carry no archive content."""
    archive = _hostile_ls(kind, tmp_path / "v070_gen000002.npz")
    monkeypatch.setattr(lucid_server, "DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError) as excinfo:
        lucid_server.extract_render_data(archive)
    message = str(excinfo.value)
    assert str(tmp_path) not in message
    assert "v070_gen000002" not in message
    assert ".npy" not in message
    assert "descr" not in message and "escape" not in message
    assert message == message.strip() and "\n" not in message


@requires_numpy
@pytest.mark.parametrize("kind", _HOSTILE_KINDS)
def test_a_rejected_snapshot_sends_no_frame_and_keeps_the_server_alive(
    kind, tmp_path, monkeypatch
):
    """The watcher must survive a poisoned directory: no frame, no broadcast,
    no crash, and the poll loop keeps running."""
    archive = _hostile_ls(kind, tmp_path / "v070_gen000003.npz")
    monkeypatch.setattr(lucid_server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(lucid_server, "find_latest_snapshot",
                        lambda data_dir: archive)

    sent = []

    async def _record_broadcast(message):
        sent.append(message)

    monkeypatch.setattr(lucid_server, "broadcast", _record_broadcast)

    websocket = FakeWebSocket([PING])
    asyncio.run(lucid_server.handle_client(websocket))

    assert sent == []
    assert [json.loads(s)["type"] for s in websocket.sent] == ["pong"], (
        "a rejected initial snapshot must send no frame, and must not stop the "
        "client from being served"
    )
    assert websocket not in lucid_server.connected_clients
