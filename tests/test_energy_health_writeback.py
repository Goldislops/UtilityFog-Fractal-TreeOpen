"""D6 ruling implementation guard (ENERGY_HEALTH_WRITEBACK_DECISION_PACKET_v1, Option B).

Entanglement must not silently tax energy by health: the quantum_myelin proxy
state is written back into energy_level alone, so the proxy must BE energy.
Pre-fix, an agent with health < 1.0 lost energy on every entanglement event
(state = energy * health round-tripped into energy).
"""
from types import SimpleNamespace
from unittest.mock import Mock

import testing_framework.simulation_runner as sr


def _skeleton_runner():
    runner = sr.SimulationRunner.__new__(sr.SimulationRunner)
    runner.quantum_logger = Mock()
    runner.simulation_logger = Mock()
    runner.all_logs = []
    runner._emit_event = lambda *a, **k: None
    runner._should_form_entanglement = lambda a, b: True
    return runner


def _agent(aid, energy, health):
    return SimpleNamespace(agent_id=aid, energy_level=energy, health=health)


def test_entanglement_writeback_preserves_energy_for_unhealthy_agents(monkeypatch):
    runner = _skeleton_runner()
    a = _agent("a", 0.8, 0.5)
    b = _agent("b", 0.6, 0.25)
    runner.agents = [a, b]

    # Identity myelin: any energy change must then come from the proxy
    # round-trip itself -- which is exactly the defect under test.
    monkeypatch.setattr(sr, "myelin_layer", lambda sa, sb, strength: None)
    monkeypatch.setattr(sr.random, "uniform", lambda lo, hi: 0.5)

    runner._process_quantum_myelin_interactions()

    assert a.energy_level == 0.8  # pre-fix: 0.8 * 0.5 = 0.4 silently drained
    assert b.energy_level == 0.6  # pre-fix: 0.6 * 0.25 = 0.15
    # health is untouched either way
    assert a.health == 0.5
    assert b.health == 0.25
