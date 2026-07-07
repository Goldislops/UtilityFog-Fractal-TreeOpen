"""Tests for agent/ising_tempering.py — exchange pairing follows the beta ladder.

Separate file from test_ising_tempering.py so this branch shares no test-file
region with other open PRs.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.ising_tempering import IsingConfig, ParallelTempering


class PairRecordingPT(ParallelTempering):
    """Records the beta pair of every proposed swap."""

    def __init__(self, config):
        super().__init__(config)
        self.proposed_beta_pairs = []

    def attempt_swap(self, i, j):
        pair = tuple(sorted((self.replicas[i].beta, self.replicas[j].beta)))
        self.proposed_beta_pairs.append(pair)
        return super().attempt_swap(i, j)


def _ladder_adjacent_pairs(betas):
    ladder = sorted(betas)
    return {tuple(sorted(pair)) for pair in zip(ladder, ladder[1:])}


class TestExchangePairsLadderNeighbors:

    def test_proposals_are_ladder_adjacent_after_beta_migration(self):
        # Regression: exchange_step paired replicas by fixed list index while
        # attempt_swap migrates betas between list slots, so after any
        # accepted swap the proposals stopped being between neighboring
        # temperatures (e.g. pairing the coldest with the hottest replica).
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=1,
                             sweeps_per_exchange=1, seed=0)
        pt = PairRecordingPT(config)

        # Simulate prior accepted swaps: betas of replicas 0 and 2 migrated.
        pt.replicas[0].beta, pt.replicas[2].beta = (
            pt.replicas[2].beta, pt.replicas[0].beta
        )
        allowed = _ladder_adjacent_pairs(r.beta for r in pt.replicas)

        pt.exchange_step(step=0, even=True)

        assert pt.proposed_beta_pairs, "expected at least one proposed swap"
        for pair in pt.proposed_beta_pairs:
            assert pair in allowed, (
                f"proposed swap between non-adjacent temperatures {pair}; "
                f"ladder-adjacent pairs are {sorted(allowed)}"
            )

    def test_full_run_conserves_the_beta_ladder(self):
        # Swaps exchange betas, never create or destroy them: after a full
        # run the multiset of replica betas is the original ladder.
        config = IsingConfig(lattice_size=8, num_replicas=4, total_exchanges=10,
                             sweeps_per_exchange=2, seed=7)
        pt = ParallelTempering(config)
        original = sorted(r.beta for r in pt.replicas)

        pt.run()

        assert sorted(r.beta for r in pt.replicas) == original
