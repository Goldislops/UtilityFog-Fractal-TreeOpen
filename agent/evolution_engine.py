"""
Evolution Engine Module for UtilityFog-Fractal-TreeOpen Agent Simulation

This module implements the genetic algorithm framework for evolving memes and
agent behaviors. It handles selection, crossover, mutation, and population
management for the memetic evolution system.

Author: UtilityFog-Fractal-TreeOpen Project
License: MIT
"""

from typing import Dict, List, Any, Optional, Tuple, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
import random
import numpy as np
import time
import statistics
from abc import ABC, abstractmethod

from meme_structure import Meme, MemeType, MemePool
from foglet_agent import FogletAgent


class SelectionMethod(Enum):
    """Enumeration of selection methods for genetic algorithms."""
    TOURNAMENT = "tournament"
    ROULETTE_WHEEL = "roulette_wheel"
    RANK_BASED = "rank_based"
    ELITIST = "elitist"
    STOCHASTIC_UNIVERSAL = "stochastic_universal"


class CrossoverMethod(Enum):
    """Enumeration of crossover methods."""
    UNIFORM = "uniform"
    SINGLE_POINT = "single_point"
    TWO_POINT = "two_point"
    ARITHMETIC = "arithmetic"
    BLEND = "blend"


class MutationMethod(Enum):
    """Enumeration of mutation methods."""
    GAUSSIAN = "gaussian"
    UNIFORM = "uniform"
    POLYNOMIAL = "polynomial"
    ADAPTIVE = "adaptive"
    CREEP = "creep"


@dataclass
class EvolutionParameters:
    """Configuration parameters for the evolution engine."""
    population_size: int = 100
    selection_pressure: float = 0.2
    mutation_rate: float = 0.1
    crossover_rate: float = 0.8
    elitism_rate: float = 0.1
    selection_method: SelectionMethod = SelectionMethod.TOURNAMENT
    crossover_method: CrossoverMethod = CrossoverMethod.UNIFORM
    mutation_method: MutationMethod = MutationMethod.GAUSSIAN
    max_generations: int = 1000
    convergence_threshold: float = 0.001


@dataclass
class GenerationStats:
    """Statistics for a single generation of evolution."""
    generation: int
    population_size: int
    best_fitness: float
    average_fitness: float
    worst_fitness: float
    fitness_std: float
    diversity_measure: float
    selection_time: float = 0.0
    crossover_time: float = 0.0
    mutation_time: float = 0.0
    evaluation_time: float = 0.0


class FitnessEvaluator(ABC):
    """Abstract base class for fitness evaluation strategies."""
    
    @abstractmethod
    def evaluate_meme(self, meme: Meme, environment_context: Dict[str, Any]) -> float:
        pass
    
    @abstractmethod
    def evaluate_agent(self, agent: FogletAgent, environment_context: Dict[str, Any]) -> float:
        pass


class DefaultFitnessEvaluator(FitnessEvaluator):
    """Default fitness evaluator implementation."""
    
    def evaluate_meme(self, meme: Meme, environment_context: Dict[str, Any]) -> float:
        base_fitness = meme.calculate_fitness(environment_context)
        propagation_bonus = min(0.2, meme.propagation_count * 0.01)
        env_fitness = sum(meme.environment_fitness.values()) / max(1, len(meme.environment_fitness))
        env_bonus = env_fitness * 0.1
        total_fitness = base_fitness + propagation_bonus + env_bonus
        return max(0.0, min(1.0, total_fitness))
    
    def evaluate_agent(self, agent: FogletAgent, environment_context: Dict[str, Any]) -> float:
        performance_score = 0.0
        metrics = agent.performance_metrics
        tasks_completed = metrics.get('tasks_completed', 0)
        performance_score += min(0.3, tasks_completed * 0.01)
        comm_success = metrics.get('successful_communications', 0)
        performance_score += min(0.2, comm_success * 0.005)
        cooperation = metrics.get('cooperation_events', 0)
        performance_score += min(0.2, cooperation * 0.01)
        health_score = agent.health * 0.15
        energy_score = agent.energy_level * 0.15
        total_fitness = performance_score + health_score + energy_score
        return max(0.0, min(1.0, total_fitness))


class EvolutionEngine:
    """Core evolution engine implementing genetic algorithms for meme and agent evolution."""
    
    def __init__(
        self,
        parameters: Optional[EvolutionParameters] = None,
        fitness_evaluator: Optional[FitnessEvaluator] = None,
        random_seed: Optional[int] = None
    ):
        self.parameters = parameters or EvolutionParameters()
        self.fitness_evaluator = fitness_evaluator or DefaultFitnessEvaluator()
        
        if random_seed is not None:
            random.seed(random_seed)
            np.random.seed(random_seed)
        
        self.meme_population: List[Meme] = []
        self.agent_population: List[FogletAgent] = []
        self.current_generation: int = 0
        self.generation_history: List[GenerationStats] = []
        self.best_individuals: List[Union[Meme, FogletAgent]] = []
        self.evolution_start_time: float = 0.0
        self.total_evaluations: int = 0
        self.generation_callbacks: List[Callable[[int, GenerationStats], None]] = []
        self.convergence_callbacks: List[Callable[[GenerationStats], None]] = []
    
    def initialize_meme_population(
        self,
        initial_memes: Optional[List[Meme]] = None,
        population_size: Optional[int] = None
    ) -> None:
        """Initialize the meme population for evolution."""
        pop_size = population_size or self.parameters.population_size
        
        if initial_memes:
            self.meme_population = initial_memes[:pop_size]
        else:
            self.meme_population = []
        
        while len(self.meme_population) < pop_size:
            random_meme = self._create_random_meme()
            self.meme_population.append(random_meme)
        
        self.meme_population = self.meme_population[:pop_size]
    
    def evolve_memes(
        self,
        generations: Optional[int] = None,
        environment_context: Optional[Dict[str, Any]] = None
    ) -> List[GenerationStats]:
        """Evolve the meme population for the specified number of generations."""
        max_gens = generations or self.parameters.max_generations
        env_context = environment_context or {}
        
        self.evolution_start_time = time.time()
        generation_stats = []
        
        for generation in range(max_gens):
            self.current_generation = generation
            
            start_time = time.time()
            fitness_scores = self._evaluate_meme_population(env_context)
            eval_time = time.time() - start_time
            
            stats = self._calculate_generation_stats(generation, fitness_scores, eval_time)
            generation_stats.append(stats)
            self.generation_history.append(stats)
            
            if self._check_convergence(stats):
                print(f"Convergence reached at generation {generation}")
                break
            
            self._apply_genetic_operators_memes(fitness_scores, stats)
            
            for callback in self.generation_callbacks:
                callback(generation, stats)
        
        return generation_stats
    
    def _create_random_meme(self) -> Meme:
        """Create a random meme for population initialization."""
        meme_type = random.choice(list(MemeType))
        payload = {
            'action_preferences': {
                'communicate': random.uniform(0.0, 1.0),
                'cooperate': random.uniform(0.0, 1.0),
                'explore': random.uniform(0.0, 1.0)
            },
            'decision_rules': {
                'risk_tolerance': random.uniform(0.0, 1.0),
                'social_weight': random.uniform(0.0, 1.0)
            }
        }
        return Meme(meme_type=meme_type, payload=payload)
    
    def _evaluate_meme_population(self, environment_context: Dict[str, Any]) -> List[float]:
        """Evaluate fitness for the entire meme population."""
        fitness_scores = []
        for meme in self.meme_population:
            fitness = self.fitness_evaluator.evaluate_meme(meme, environment_context)
            fitness_scores.append(fitness)
            self.total_evaluations += 1
        return fitness_scores
    
    def _calculate_generation_stats(
        self,
        generation: int,
        fitness_scores: List[float],
        evaluation_time: float
    ) -> GenerationStats:
        """Calculate statistics for the current generation."""
        if not fitness_scores:
            return GenerationStats(
                generation=generation,
                population_size=0,
                best_fitness=0.0,
                average_fitness=0.0,
                worst_fitness=0.0,
                fitness_std=0.0,
                diversity_measure=0.0,
                evaluation_time=evaluation_time
            )
        
        best_fitness = max(fitness_scores)
        average_fitness = statistics.mean(fitness_scores)
        worst_fitness = min(fitness_scores)
        fitness_std = statistics.stdev(fitness_scores) if len(fitness_scores) > 1 else 0.0
        diversity_measure = fitness_std / max(average_fitness, 0.001)
        
        return GenerationStats(
            generation=generation,
            population_size=len(fitness_scores),
            best_fitness=best_fitness,
            average_fitness=average_fitness,
            worst_fitness=worst_fitness,
            fitness_std=fitness_std,
            diversity_measure=diversity_measure,
            evaluation_time=evaluation_time
        )
    
    def _check_convergence(self, stats: GenerationStats) -> bool:
        """Check if the population has converged."""
        if len(self.generation_history) < 10:
            return False
        
        recent_best = [s.best_fitness for s in self.generation_history[-10:]]
        improvement = max(recent_best) - min(recent_best)
        
        return improvement < self.parameters.convergence_threshold
    
    def _apply_genetic_operators_memes(
        self,
        fitness_scores: List[float],
        stats: GenerationStats
    ) -> None:
        """Apply genetic operators to create the next generation of memes."""
        new_population = []
        
        # Elitism: preserve best individuals
        num_elites = int(self.parameters.elitism_rate * len(self.meme_population))
        if num_elites > 0:
            elite_indices = sorted(
                range(len(fitness_scores)),
                key=lambda i: fitness_scores[i],
                reverse=True
            )[:num_elites]
            elites = [self.meme_population[i].copy() for i in elite_indices]
            new_population.extend(elites)
        
        # Generate offspring through crossover and mutation
        while len(new_population) < len(self.meme_population):
            parents = self._tournament_selection(self.meme_population, fitness_scores, 2)
            
            if len(parents) >= 2:
                if random.random() < self.parameters.crossover_rate:
                    offspring1, offspring2 = parents[0].crossover(parents[1])
                else:
                    offspring1, offspring2 = parents[0].copy(), parents[1].copy()
                
                offspring1 = offspring1.mutate(self.parameters.mutation_rate)
                offspring2 = offspring2.mutate(self.parameters.mutation_rate)
                
                new_population.extend([offspring1, offspring2])
            else:
                individual = random.choice(self.meme_population)
                mutated = individual.mutate(self.parameters.mutation_rate)
                new_population.append(mutated)
        
        self.meme_population = new_population[:len(self.meme_population)]
    
    def _tournament_selection(
        self,
        population: List[Union[Meme, FogletAgent]],
        fitness_scores: List[float],
        num_parents: int,
        tournament_size: int = 3
    ) -> List[Union[Meme, FogletAgent]]:
        """Perform tournament selection."""
        selected = []
        for _ in range(num_parents):
            tournament_indices = random.sample(range(len(population)), min(tournament_size, len(population)))
            best_index = max(tournament_indices, key=lambda i: fitness_scores[i])
            selected.append(population[best_index])
        return selected
