from agent.evolution_engine import DefaultFitnessEvaluator
from agent.meme_structure import Meme, MemeGenes


def _neutral_meme() -> Meme:
    meme = Meme(genes=MemeGenes(
        dominance=0.0,
        virality=0.0,
        stability=0.5,
        compatibility=0.5,
        expression_threshold=0.5,
    ))
    meme.environment_fitness = {}
    meme.propagation_count = 0
    return meme


def test_entropy_bonus_rewards_heterogeneous_state_mix() -> None:
    evaluator = DefaultFitnessEvaluator()
    meme = _neutral_meme()

    monolithic_context = {
        "cell_state_counts": {
            "STRUCTURAL": 67000,
            "COMPUTE": 100,
            "ENERGY": 100,
            "SENSOR": 100,
        }
    }
    differentiated_context = {
        "cell_state_counts": {
            "STRUCTURAL": 20000,
            "COMPUTE": 17000,
            "ENERGY": 15000,
            "SENSOR": 15000,
        }
    }

    monolithic_score = evaluator.evaluate_meme(meme, monolithic_context)
    differentiated_score = evaluator.evaluate_meme(meme, differentiated_context)

    assert differentiated_score > monolithic_score


def test_structural_dominance_penalty_applies_after_target_threshold() -> None:
    evaluator = DefaultFitnessEvaluator()
    meme = _neutral_meme()

    below_target = {"cell_state_counts": {"STRUCTURAL": 54, "COMPUTE": 20, "ENERGY": 13, "SENSOR": 13}}
    above_target = {"cell_state_counts": {"STRUCTURAL": 90, "COMPUTE": 4, "ENERGY": 3, "SENSOR": 3}}

    assert evaluator.evaluate_meme(meme, below_target) > evaluator.evaluate_meme(meme, above_target)


def test_list_state_vector_is_supported() -> None:
    evaluator = DefaultFitnessEvaluator()
    meme = _neutral_meme()

    # [VOID, STRUCTURAL, COMPUTE, ENERGY, SENSOR]
    vector_context = {"cell_state_counts": [190000, 17000, 17000, 17000, 17000]}

    score = evaluator.evaluate_meme(meme, vector_context)

    assert 0.0 <= score <= 1.0
