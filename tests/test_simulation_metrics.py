"""Tests for agent/simulation_metrics.py — collector/entity-source pairing."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# simulation_metrics imports the agent package family (network_topology needs
# networkx), which is not part of CI's dependency set. Self-skip like the
# other optional-dep suites (#165 Tier 1 pattern).
pytest.importorskip("networkx")

from agent.simulation_metrics import MetricCollector, SimulationMetrics


class RecordingCollector(MetricCollector):
    """Stub collector that records which entities it was handed."""

    def __init__(self):
        self.seen = None

    def collect_metrics(self, entities, timestamp):
        self.seen = list(entities)
        return []


class TestCollectorSourcePairing:

    def test_two_collectors_on_same_source_both_run(self):
        # Regression: pairing collectors with sources by parallel index
        # silently skipped the trailing collector whenever two collectors
        # registered against the same source name.
        sm = SimulationMetrics(collection_interval=0.0)
        first = RecordingCollector()
        second = RecordingCollector()
        sm.add_collector(first, "pool")
        sm.add_collector(second, "pool")
        sm.entity_sources["pool"] = ["m1", "m2"]

        sm.collect_all_metrics(timestamp=100.0)

        assert first.seen == ["m1", "m2"]
        assert second.seen == ["m1", "m2"]

    def test_collector_receives_its_registered_source(self):
        # Regression: with reused source names, index pairing handed the
        # second collector the WRONG source's entities and skipped the third.
        sm = SimulationMetrics(collection_interval=0.0)
        meme_a = RecordingCollector()
        meme_b = RecordingCollector()
        agents = RecordingCollector()
        sm.add_collector(meme_a, "pool")
        sm.add_collector(meme_b, "pool")
        sm.add_collector(agents, "agents")
        sm.entity_sources["pool"] = ["meme1"]
        sm.entity_sources["agents"] = ["agent1", "agent2"]

        sm.collect_all_metrics(timestamp=100.0)

        assert meme_a.seen == ["meme1"]
        assert meme_b.seen == ["meme1"]
        assert agents.seen == ["agent1", "agent2"]

    def test_unpopulated_source_yields_empty_entities(self):
        # A collector registered before its source is populated gets an
        # empty list, not a crash or someone else's entities.
        sm = SimulationMetrics(collection_interval=0.0)
        lonely = RecordingCollector()
        sm.add_collector(lonely, "never_filled")

        sm.collect_all_metrics(timestamp=100.0)

        assert lonely.seen == []
