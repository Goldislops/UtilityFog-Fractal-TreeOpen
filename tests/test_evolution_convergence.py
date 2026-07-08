"""Regression test: the convergence window must not leak across evolve_memes runs.

_check_convergence reads generation_history, which is appended to across
evolve_memes calls and never reset. A second run on the same engine therefore
inherited the previous run's plateau: if the new run started at (or near) the
old best-fitness level, the 10-generation improvement window was already flat
and the run "converged" at generation 0 regardless of its own progress.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.evolution_engine import EvolutionEngine, EvolutionParameters, FitnessEvaluator


class _ScriptedFitness(FitnessEvaluator):
    """Test-driven evaluator: a flat plateau, then a steady per-generation climb."""

    def __init__(self):
        self.engine = None
        self.climbing = False

    def evaluate_meme(self, meme, environment_context):
        if not self.climbing:
            return 0.5
        return min(1.0, 0.5 + 0.05 * self.engine.current_generation)

    def evaluate_agent(self, agent, environment_context):
        # Interface contract only — this test never evolves agents.
        return 0.0


def test_second_run_does_not_inherit_previous_convergence_window():
    evaluator = _ScriptedFitness()
    engine = EvolutionEngine(
        parameters=EvolutionParameters(population_size=4, convergence_threshold=0.001),
        fitness_evaluator=evaluator,
        random_seed=42,
    )
    evaluator.engine = engine
    engine.initialize_meme_population(population_size=4)

    # Run 1: flat fitness -> genuine convergence as soon as a full
    # 10-generation window exists (generation 9).
    run1 = engine.evolve_memes(generations=15)
    assert len(run1) == 10

    # Run 2: fitness now climbs 0.05 per generation, starting from the old
    # plateau value. Pre-fix, generation 0 saw a window of nine stale 0.5s
    # from run 1 plus its own 0.5 -> zero improvement -> false convergence
    # at generation 0.
    evaluator.climbing = True
    engine.initialize_meme_population(population_size=4)
    run2 = engine.evolve_memes(generations=12)

    assert len(run2) == 12
    best = [stats.best_fitness for stats in run2]
    assert best[-1] > best[0]
