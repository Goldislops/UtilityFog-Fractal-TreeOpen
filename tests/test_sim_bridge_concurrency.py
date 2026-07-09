"""Concurrency contract for SimBridge (SIM_BRIDGE_CONCURRENCY_OPTIONS_v1, Option A,
amended per #304 audit: start-blocking and stoppability are separate questions).

Skips when fastapi is absent (sim_bridge imports ws_server, which needs
fastapi) -- the same verification limit disclosed on #286/#287.
"""
import asyncio
import threading

import pytest

pytest.importorskip("fastapi")

from utilityfog_frontend.backend.sim_bridge import SimBridge


def _bridge(status, thread_alive):
    bridge = SimBridge()
    bridge.status = status
    release = threading.Event()
    if thread_alive:
        bridge.simulation_thread = threading.Thread(target=release.wait, daemon=True)
        bridge.simulation_thread.start()
    else:
        dead = threading.Thread(target=lambda: None, daemon=True)
        dead.start()
        dead.join(timeout=5)
        bridge.simulation_thread = dead
    return bridge, release


def _drain(bridge, release):
    release.set()
    if bridge.simulation_thread is not None:
        bridge.simulation_thread.join(timeout=5)


def test_draining_thread_blocks_start():
    bridge, release = _bridge("stopped", thread_alive=True)
    try:
        assert not bridge.can_start()
        with pytest.raises(RuntimeError, match="already running"):
            asyncio.run(bridge.start_simulation("run-2", {"simulation_steps": 1}))
    finally:
        _drain(bridge, release)
    assert bridge.can_start()


def test_terminal_status_with_live_thread_blocks_start_but_is_not_stoppable():
    # Codex P2: worker wrote "completed" but is still cleaning up/broadcasting.
    bridge, release = _bridge("completed", thread_alive=True)
    try:
        assert not bridge.can_start()      # still draining: no new run yet
        assert not bridge.is_running()     # not stoppable: stop must not overwrite terminal status
    finally:
        _drain(bridge, release)


def test_stale_running_status_with_dead_thread_does_not_block_start():
    # Gemini: a crashed worker that left status "running" must not block forever.
    bridge, _ = _bridge("running", thread_alive=False)
    assert bridge.can_start()
    assert not bridge.is_running()


def test_live_running_worker_is_running_and_blocks_start():
    bridge, release = _bridge("running", thread_alive=True)
    try:
        assert bridge.is_running()
        assert not bridge.can_start()
    finally:
        _drain(bridge, release)
