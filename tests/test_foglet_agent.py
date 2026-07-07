"""Tests for agent/foglet_agent.py — meme infection and same-type replacement."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.foglet_agent import FogletAgent
from agent.meme_structure import Meme, MemeGenes, MemeType


def _agent_with_no_resistance():
    agent = FogletAgent()
    agent.active_memes.clear()
    # Zero resistance + virality 1.0 makes infection_probability exactly 1.0,
    # so random.random() > 1.0 is always False and infection is deterministic.
    agent.meme_resistances = {meme_type: 0.0 for meme_type in MemeType}
    return agent


def _behavioral_meme(dominance, marker):
    return Meme(
        meme_type=MemeType.BEHAVIORAL,
        payload={"marker": marker},
        genes=MemeGenes(dominance=dominance, virality=1.0),
    )


class TestSameTypeMemeReplacement:

    def test_stronger_meme_replaces_weaker_same_type(self):
        agent = _agent_with_no_resistance()

        assert agent.infect_with_meme(_behavioral_meme(0.2, "weak"), infection_strength=1.0)
        assert agent.infect_with_meme(_behavioral_meme(0.9, "strong"), infection_strength=1.0)

        assert len(agent.active_memes) == 1
        (stored,) = agent.active_memes.values()
        assert stored.payload["marker"] == "strong"

    def test_weaker_meme_is_rejected_by_dominant_incumbent(self):
        agent = _agent_with_no_resistance()

        assert agent.infect_with_meme(_behavioral_meme(0.9, "strong"), infection_strength=1.0)
        assert not agent.infect_with_meme(_behavioral_meme(0.2, "weak"), infection_strength=1.0)

        assert len(agent.active_memes) == 1
        (stored,) = agent.active_memes.values()
        assert stored.payload["marker"] == "strong"

    def test_repeated_replacement_never_raises(self):
        # Regression: stored memes carry regenerated meme_ids (Meme.copy()
        # assigns a new uuid), so replacement must delete by dict key —
        # deleting by the stored meme's id raises KeyError on every
        # same-type takeover.
        agent = _agent_with_no_resistance()

        for dominance in (0.1, 0.5, 0.9):
            assert agent.infect_with_meme(
                _behavioral_meme(dominance, dominance), infection_strength=1.0
            )

        assert len(agent.active_memes) == 1
        (stored,) = agent.active_memes.values()
        assert stored.payload["marker"] == 0.9
