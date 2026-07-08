"""Concurrency contract for SimBridge (SIM_BRIDGE_CONCURRENCY_OPTIONS_v1, Option A).

Skips when fastapi is absent (sim_bridge imports ws_server, which needs
fastapi) -- the same verification limit disclosed on #286/#287.
"""
import asyncio
import threading

import pytest

pytest.importorskip("fastapi")

from utilityfog_frontend.backend.sim_bridge import SimBridge


def _draining_bridge():
    """Bridge in the post-stop state with its worker thread still alive."""
    bridge = SimBridge()
    release = threading.Event()
    bridge.status = "stopped"
    bridge.simulation_thread = threading.Thread(target=release.wait, daemon=True)
    bridge.simulation_thread.start()
    return bridge, release


def test_is_running_true_while_thread_drains():
    bridge, release = _draining_bridge()
    try:
        assert bridge.is_running()
    finally:
        release.set()
        bridge.simulation_thread.join(timeout=5)
    assert not bridge.is_running()


def test_start_refused_while_prior_thread_alive():
    bridge, release = _draining_bridge()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            asyncio.run(bridge.start_simulation("run-2", {"simulation_steps": 1}))
    finally:
        release.set()
        bridge.simulation_thread.join(timeout=5)
