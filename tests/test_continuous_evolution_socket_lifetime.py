"""Focused tests for `scripts/continuous_evolution` probe-socket ownership.

Both safety-net probes used to construct a TCP socket and call `close()` only
after `settimeout()` and `connect_ex()` had BOTH returned:

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((head_ip, port))
    sock.close()          # skipped when either call above raises

An `OSError` from either call jumped straight to the surrounding handler, which
reports an unreachable peer -- so the descriptor stayed open and the failure
looked exactly like an ordinary unreachable host. That is the bad shape for a
leak: silent, and on the path that fires when the network is already unhappy.
`poll_gpu_temperatures()` runs one probe per GPU per node, on a polling loop,
for the life of the orchestrator process.

`_probe_tcp()` now owns the socket for the whole probe and closes it in a
`finally`, so release does not depend on which call raised.

No real socket, host, port or service is contacted: `socket.socket` is replaced
by a factory handing out scripted fakes that record their own `close()` calls.
The probe addresses below are fictitious and never dialled.

Scope is descriptor lifetime and the exception paths around it -- not
reachability semantics, thermal policy, temperature modelling, or the
orchestrator's loop behaviour.
"""

from __future__ import annotations

import signal
import socket as _real_socket
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Importing the orchestrator installs SIGINT/SIGTERM handlers at module scope.
# They are restored immediately so collecting this file cannot change how the
# rest of the pytest session responds to signals.
_SAVED_HANDLERS = {
    number: signal.getsignal(number)
    for number in (signal.SIGINT, signal.SIGTERM)
}
import scripts.continuous_evolution as ce  # noqa: E402
for _number, _handler in _SAVED_HANDLERS.items():
    signal.signal(_number, _handler)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeSocket:
    """Records its own lifetime. Never touches the network."""

    def __init__(self, family=None, type=None, connect_result=0,
                 settimeout_error=None, connect_error=None, close_error=None):
        self.family = family
        self.type = type
        self.closed = 0
        self.timeout = None
        self.connected_to = None
        self._connect_result = connect_result
        self._settimeout_error = settimeout_error
        self._connect_error = connect_error
        self._close_error = close_error

    def settimeout(self, value):
        self.timeout = value
        if self._settimeout_error is not None:
            raise self._settimeout_error

    def connect_ex(self, address):
        self.connected_to = address
        if self._connect_error is not None:
            raise self._connect_error
        return self._connect_result

    def close(self):
        self.closed += 1
        if self._close_error is not None:
            raise self._close_error


class SocketFactory:
    """Stands in for `socket.socket`, handing out scripted `FakeSocket`s."""

    def __init__(self, scripts=None, construct_error=None):
        self._scripts = list(scripts or [])
        self._construct_error = construct_error
        self.made = []
        self.calls = []

    def __call__(self, family=None, type=None):
        self.calls.append((family, type))
        if self._construct_error is not None:
            raise self._construct_error
        spec = self._scripts.pop(0) if self._scripts else {}
        sock = FakeSocket(family=family, type=type, **spec)
        self.made.append(sock)
        return sock


@pytest.fixture
def probe_sockets(monkeypatch):
    """Install a socket factory into the module under test.

    The stand-in module carries the real `AF_INET`/`SOCK_STREAM` constants, so
    the assertions on construction arguments compare against production values
    rather than against sentinels this test invented.
    """

    def install(scripts=None, construct_error=None):
        factory = SocketFactory(scripts=scripts, construct_error=construct_error)
        stand_in = types.ModuleType("socket")
        stand_in.socket = factory
        stand_in.AF_INET = _real_socket.AF_INET
        stand_in.SOCK_STREAM = _real_socket.SOCK_STREAM
        monkeypatch.setattr(ce, "socket", stand_in)
        return factory

    return install


def _closes(factory):
    return [sock.closed for sock in factory.made]


# ---------------------------------------------------------------------------
# check_vanguard_mcp -- the four probe outcomes
# ---------------------------------------------------------------------------


def test_successful_probe_closes_once_and_reports_alive(probe_sockets):
    factory = probe_sockets([{"connect_result": 0}])

    assert ce.check_vanguard_mcp("10.10.10.10", 50051, timeout=5.0) is True

    assert _closes(factory) == [1]
    assert factory.made[0].connected_to == ("10.10.10.10", 50051)
    assert factory.made[0].timeout == 5.0


def test_nonzero_connect_ex_closes_once_and_reports_dead(probe_sockets):
    factory = probe_sockets([{"connect_result": 111}])

    assert ce.check_vanguard_mcp("10.10.10.10", 50051) is False

    assert _closes(factory) == [1]


def test_settimeout_oserror_still_closes_the_socket(probe_sockets):
    """The defect: `close()` sat after `settimeout()`, so this leaked."""
    factory = probe_sockets([{"settimeout_error": OSError("settimeout failed")}])

    assert ce.check_vanguard_mcp("10.10.10.10", 50051) is False

    assert _closes(factory) == [1]


def test_connect_ex_oserror_still_closes_the_socket(probe_sockets):
    """The same defect one line lower down."""
    factory = probe_sockets([{"connect_error": OSError("connect failed")}])

    assert ce.check_vanguard_mcp("10.10.10.10", 50051) is False

    assert _closes(factory) == [1]


def test_construction_oserror_reports_dead_without_inventing_a_socket(probe_sockets):
    """No descriptor exists to close, and none is pretended into existence."""
    factory = probe_sockets(construct_error=OSError("EMFILE"))

    assert ce.check_vanguard_mcp("10.10.10.10", 50051) is False

    assert factory.made == []
    assert len(factory.calls) == 1


def test_non_oserror_propagates_unchanged_after_the_socket_is_closed(probe_sockets):
    """Only `OSError` is translated into "unreachable".

    A `ValueError` from `settimeout` is a defect in the caller, not an
    unreachable peer, and must not be laundered into a `False` return. It still
    must not leak the socket on its way out.
    """
    boom = ValueError("timeout must be a number")
    factory = probe_sockets([{"settimeout_error": boom}])

    with pytest.raises(ValueError) as caught:
        ce.check_vanguard_mcp("10.10.10.10", 50051)

    assert caught.value is boom
    assert _closes(factory) == [1]


def test_default_address_and_port_are_unchanged(probe_sockets):
    factory = probe_sockets([{"connect_result": 0}])

    assert ce.check_vanguard_mcp() is True

    assert factory.made[0].connected_to == ("192.168.86.29", 50051)
    assert factory.made[0].timeout == 5.0
    assert factory.calls == [(_real_socket.AF_INET, _real_socket.SOCK_STREAM)]


# ---------------------------------------------------------------------------
# poll_gpu_temperatures -- one socket per GPU, closed independently
# ---------------------------------------------------------------------------


def _nodes():
    return [
        {"id": "alpha", "ip": "10.0.0.1", "grpc_port": 50051,
         "gpus": [{"id": "gpu0"}, {"id": "gpu1"}]},
        {"id": "beta", "ip": "10.0.0.2", "grpc_port": 50052,
         "gpus": [{"id": "gpu0"}, {"id": "gpu1"}]},
    ]


def test_every_constructed_socket_is_closed_across_nodes_and_gpus(probe_sockets):
    factory = probe_sockets([{"connect_result": 0}] * 4)

    temps = ce.poll_gpu_temperatures(_nodes())

    assert _closes(factory) == [1, 1, 1, 1]
    assert sorted(temps) == ["alpha/gpu0", "alpha/gpu1", "beta/gpu0", "beta/gpu1"]
    assert [sock.connected_to for sock in factory.made] == [
        ("10.0.0.1", 50051), ("10.0.0.1", 50051),
        ("10.0.0.2", 50052), ("10.0.0.2", 50052),
    ]


def test_mixed_outcomes_close_every_socket_and_do_not_abort_later_probes(probe_sockets):
    """Success, refusal, a `settimeout` failure and a `connect_ex` failure.

    Every socket that was constructed is closed exactly once, every GPU gets a
    verdict, and a failure part-way through does not skip the GPUs after it.
    """
    factory = probe_sockets([
        {"connect_result": 0},
        {"connect_result": 111},
        {"settimeout_error": OSError("settimeout failed")},
        {"connect_error": OSError("connect failed")},
    ])

    temps = ce.poll_gpu_temperatures(_nodes())

    assert _closes(factory) == [1, 1, 1, 1]
    assert len(temps) == 4
    assert temps["alpha/gpu1"] == -1.0
    assert temps["beta/gpu0"] == -1.0
    assert temps["beta/gpu1"] == -1.0
    assert temps["alpha/gpu0"] != -1.0


def test_each_failed_probe_records_minus_one(probe_sockets):
    factory = probe_sockets([
        {"connect_result": 111},
        {"settimeout_error": OSError("x")},
        {"connect_error": OSError("y")},
        {"connect_result": 22},
    ])

    temps = ce.poll_gpu_temperatures(_nodes())

    assert set(temps.values()) == {-1.0}
    assert _closes(factory) == [1, 1, 1, 1]


def test_successful_probe_generates_a_temperature_in_the_established_band(probe_sockets):
    probe_sockets([{"connect_result": 0}])

    temps = ce.poll_gpu_temperatures(
        [{"id": "n", "ip": "10.0.0.9", "grpc_port": 50051, "gpus": [{"id": "g"}]}]
    )

    assert 50.0 <= temps["n/g"] <= 70.0


def test_temperature_is_generated_only_after_its_socket_is_closed(probe_sockets):
    """Ordering, not just the final count.

    The generated reading must not be produced while the descriptor is still
    open, so the socket is asserted closed at the moment `np.random.uniform`
    runs.
    """
    factory = probe_sockets([{"connect_result": 0}])
    observed = []

    real_uniform = ce.np.random.uniform

    def recording_uniform(low, high):
        observed.append([sock.closed for sock in factory.made])
        return real_uniform(low, high)

    ce.np.random.uniform = recording_uniform
    try:
        ce.poll_gpu_temperatures(
            [{"id": "n", "ip": "10.0.0.9", "grpc_port": 50051, "gpus": [{"id": "g"}]}]
        )
    finally:
        ce.np.random.uniform = real_uniform

    assert observed == [[1]], "temperature generated while the socket was open"


def test_construction_failure_records_minus_one_for_that_gpu(probe_sockets):
    factory = probe_sockets(construct_error=OSError("EMFILE"))

    temps = ce.poll_gpu_temperatures(
        [{"id": "n", "ip": "10.0.0.9", "grpc_port": 50051,
          "gpus": [{"id": "g0"}, {"id": "g1"}]}]
    )

    assert temps == {"n/g0": -1.0, "n/g1": -1.0}
    assert factory.made == []
    assert len(factory.calls) == 2


def test_node_defaults_are_unchanged_when_ip_and_port_are_absent(probe_sockets):
    factory = probe_sockets([{"connect_result": 0}])

    ce.poll_gpu_temperatures([{"id": "n", "gpus": [{"id": "g"}]}])

    assert factory.made[0].connected_to == ("127.0.0.1", 50051)
    assert factory.made[0].timeout == 2.0


def test_a_node_without_gpus_probes_nothing(probe_sockets):
    factory = probe_sockets()

    assert ce.poll_gpu_temperatures([{"id": "n", "ip": "10.0.0.9"}]) == {}

    assert factory.calls == []


def test_non_oserror_during_polling_propagates_after_closing(probe_sockets):
    boom = ValueError("not a network failure")
    factory = probe_sockets([{"connect_error": boom}])

    with pytest.raises(ValueError) as caught:
        ce.poll_gpu_temperatures(
            [{"id": "n", "ip": "10.0.0.9", "grpc_port": 50051, "gpus": [{"id": "g"}]}]
        )

    assert caught.value is boom
    assert _closes(factory) == [1]
