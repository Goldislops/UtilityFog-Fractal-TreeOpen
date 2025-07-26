"""
Meme Structure Module for UtilityFog-Fractal-TreeOpen Agent Simulation

This module defines the core Meme class that represents units of cultural/behavioral
information that can evolve, mutate, and propagate through the agent network.
Memes influence agent decision-making and undergo genetic-like operations.

Author: UtilityFog-Fractal-TreeOpen Project
License: MIT
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import random
import uuid
import json
from abc import ABC, abstractmethod


class MemeType(Enum):
    """Enumeration of different meme categories for classification."""
    BEHAVIORAL = "behavioral"
    COGNITIVE = "cognitive"
    SOCIAL = "social"
    RESOURCE = "resource"
    COMMUNICATION = "communication"


@dataclass
class MemeGenes:
    """
    Genetic representation of meme characteristics.
    
    Attributes:
        dominance: How strongly this meme influences agent behavior (0.0-1.0)
        virality: Probability of successful transmission (0.0-1.0)
        stability: Resistance to mutation (0.0-1.0)
        compatibility: How well this meme works with others (0.0-1.0)
        expression_threshold: Minimum activation level needed (0.0-1.0)
    """
    dominance: float = field(default_factory=lambda: random.uniform(0.1, 0.9))
    virality: float = field(default_factory=lambda: random.uniform(0.1, 0.9))
    stability: float = field(default_factory=lambda: random.uniform(0.1, 0.9))
    compatibility: float = field(default_factory=lambda: random.uniform(0.1, 0.9))
    expression_threshold: float = field(default_factory=lambda: random.uniform(0.1, 0.9))
    
    def to_dict(self) -> Dict[str, float]:
        """Convert genes to dictionary representation."""
        return {
            'dominance': self.dominance,
            'virality': self.virality,
            'stability': self.stability,
            'compatibility': self.compatibility,
            'expression_threshold': self.expression_threshold
        }


class Meme:
    """
    Core meme class representing a unit of cultural/behavioral information.
    
    Memes can mutate, reproduce, and influence agent behavior. They contain
    both genetic information (MemeGenes) and behavioral payload data.
    """
    
    def __init__(
        self,
        meme_id: Optional[str] = None,
        meme_type: MemeType = MemeType.BEHAVIORAL,
        payload: Optional[Dict[str, Any]] = None,
        genes: Optional[MemeGenes] = None,
        generation: int = 0,
        parent_ids: Optional[List[str]] = None
    ):
        """
        Initialize a new meme.
        
        Args:
            meme_id: Unique identifier for this meme
            meme_type: Category of meme behavior
            payload: Behavioral data and parameters
            genes: Genetic characteristics affecting meme behavior
            generation: Evolutionary generation number
            parent_ids: List of parent meme IDs for lineage tracking
        """
        self.meme_id = meme_id or str(uuid.uuid4())
        self.meme_type = meme_type
        self.payload = payload or {}
        self.genes = genes or MemeGenes()
        self.generation = generation
        self.parent_ids = parent_ids or []
        
        # Fitness and propagation tracking
        self.fitness_score: float = 0.0
        self.propagation_count: int = 0
        self.activation_history: List[Tuple[str, float]] = []  # (agent_id, timestamp)
        self.mutation_history: List[Dict[str, Any]] = []
        
        # Environmental adaptation
        self.environment_fitness: Dict[str, float] = {}
        self.last_evaluation_time: float = 0.0
    
    def calculate_fitness(self, environment_context: Dict[str, Any]) -> float:
        """
        Calculate fitness score based on meme performance and environment.
        
        Args:
            environment_context: Current environmental conditions and metrics
            
        Returns:
            Calculated fitness score (0.0-1.0)
            
        TODO: Implement sophisticated fitness calculation considering:
        - Propagation success rate
        - Agent performance improvement
        - Environmental adaptation
        - Meme interaction effects
        """
        base_fitness = 0.5  # Neutral starting point
        
        # Factor in propagation success
        if self.propagation_count > 0:
            propagation_bonus = min(0.3, self.propagation_count * 0.05)
            base_fitness += propagation_bonus
        
        # Factor in genetic advantages
        genetic_bonus = (self.genes.dominance + self.genes.virality) * 0.1
        base_fitness += genetic_bonus
        
        # Environmental adaptation bonus
        env_bonus = sum(self.environment_fitness.values()) * 0.1
        base_fitness += env_bonus
        
        self.fitness_score = max(0.0, min(1.0, base_fitness))
        return self.fitness_score
    
    def mutate(self, mutation_rate: float = 0.1) -> 'Meme':
        """
        Create a mutated copy of this meme.
        
        Args:
            mutation_rate: Probability of mutation occurring (0.0-1.0)
            
        Returns:
            New mutated meme instance
            
        TODO: Implement various mutation types:
        - Point mutations in genes
        - Payload parameter modifications
        - Structural changes to behavior
        - Adaptive mutations based on environment
        """
        if random.random() > mutation_rate:
            return self.copy()
        
        # Create mutated copy
        mutated_meme = self.copy()
        mutated_meme.generation += 1
        mutated_meme.parent_ids = [self.meme_id]
        
        # Mutate genes based on stability
        stability_factor = 1.0 - self.genes.stability
        
        if random.random() < stability_factor:
            # Mutate genetic characteristics
            gene_mutations = {}
            for attr in ['dominance', 'virality', 'stability', 'compatibility', 'expression_threshold']:
                if random.random() < 0.3:  # 30% chance per gene
                    old_value = getattr(mutated_meme.genes, attr)
                    mutation_delta = random.gauss(0, 0.1)  # Normal distribution
                    new_value = max(0.0, min(1.0, old_value + mutation_delta))
                    setattr(mutated_meme.genes, attr, new_value)
                    gene_mutations[attr] = {'old': old_value, 'new': new_value}
            
            # Record mutation
            mutation_record = {
                'type': 'genetic',
                'generation': mutated_meme.generation,
                'mutations': gene_mutations,
                'parent_id': self.meme_id
            }
            mutated_meme.mutation_history.append(mutation_record)
        
        # TODO: Implement payload mutations
        # TODO: Implement structural mutations
        
        return mutated_meme
    
    def crossover(self, other_meme: 'Meme') -> Tuple['Meme', 'Meme']:
        """
        Perform genetic crossover with another meme to create offspring.
        
        Args:
            other_meme: The other parent meme
            
        Returns:
            Tuple of two offspring memes
            
        TODO: Implement sophisticated crossover mechanisms:
        - Uniform crossover for genes
        - Payload feature mixing
        - Compatibility-based crossover success
        - Multi-point crossover strategies
        """
        # Create two offspring
        offspring1 = Meme(
            meme_type=self.meme_type,
            generation=max(self.generation, other_meme.generation) + 1,
            parent_ids=[self.meme_id, other_meme.meme_id]
        )
        
        offspring2 = Meme(
            meme_type=other_meme.meme_type,
            generation=max(self.generation, other_meme.generation) + 1,
            parent_ids=[self.meme_id, other_meme.meme_id]
        )
        
        # Simple uniform crossover for genes
        for attr in ['dominance', 'virality', 'stability', 'compatibility', 'expression_threshold']:
            if random.random() < 0.5:
                setattr(offspring1.genes, attr, getattr(self.genes, attr))
                setattr(offspring2.genes, attr, getattr(other_meme.genes, attr))
            else:
                setattr(offspring1.genes, attr, getattr(other_meme.genes, attr))
                setattr(offspring2.genes, attr, getattr(self.genes, attr))
        
        # TODO: Implement payload crossover
        # TODO: Add compatibility checks
        
        return offspring1, offspring2
    
    def can_propagate_to(self, target_agent_context: Dict[str, Any]) -> bool:
        """
        Determine if this meme can successfully propagate to a target agent.
        
        Args:
            target_agent_context: Information about the target agent
            
        Returns:
            True if propagation is possible, False otherwise
            
        TODO: Implement propagation rules based on:
        - Agent compatibility
        - Meme virality
        - Environmental conditions
        - Network topology constraints
        """
        # Basic virality check
        if random.random() > self.genes.virality:
            return False
        
        # TODO: Add agent compatibility checks
        # TODO: Add environmental suitability checks
        # TODO: Add network distance considerations
        
        return True
    
    def activate(self, agent_id: str, activation_strength: float) -> Dict[str, Any]:
        """
        Activate this meme's influence on an agent's behavior.
        
        Args:
            agent_id: ID of the agent being influenced
            activation_strength: Strength of activation (0.0-1.0)
            
        Returns:
            Dictionary of behavioral modifications to apply
            
        TODO: Implement activation logic based on:
        - Meme type and payload
        - Activation strength vs expression threshold
        - Agent's current state and context
        - Interaction with other active memes
        """
        import time
        
        # Check if activation meets threshold
        if activation_strength < self.genes.expression_threshold:
            return {}
        
        # Record activation
        self.activation_history.append((agent_id, time.time()))
        
        # Generate behavioral modifications based on meme type
        modifications = {}
        
        if self.meme_type == MemeType.BEHAVIORAL:
            modifications = {
                'behavior_weight': activation_strength * self.genes.dominance,
                'action_bias': self.payload.get('action_preferences', {}),
                'decision_modifier': self.payload.get('decision_rules', {})
            }
        elif self.meme_type == MemeType.SOCIAL:
            modifications = {
                'communication_style': self.payload.get('comm_style', 'default'),
                'cooperation_tendency': activation_strength * self.genes.compatibility,
                'trust_modifier': self.payload.get('trust_bias', 0.0)
            }
        # TODO: Implement other meme types
        
        return modifications
    
    def copy(self) -> 'Meme':
        """Create a deep copy of this meme."""
        return Meme(
            meme_type=self.meme_type,
            payload=self.payload.copy(),
            genes=MemeGenes(**self.genes.to_dict()),
            generation=self.generation,
            parent_ids=self.parent_ids.copy()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert meme to dictionary representation for serialization."""
        return {
            'meme_id': self.meme_id,
            'meme_type': self.meme_type.value,
            'payload': self.payload,
            'genes': self.genes.to_dict(),
            'generation': self.generation,
            'parent_ids': self.parent_ids,
            'fitness_score': self.fitness_score,
            'propagation_count': self.propagation_count,
            'environment_fitness': self.environment_fitness
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Meme':
        """Create meme instance from dictionary representation."""
        genes = MemeGenes(**data['genes'])
        meme = cls(
            meme_id=data['meme_id'],
            meme_type=MemeType(data['meme_type']),
            payload=data['payload'],
            genes=genes,
            generation=data['generation'],
            parent_ids=data['parent_ids']
        )
        meme.fitness_score = data.get('fitness_score', 0.0)
        meme.propagation_count = data.get('propagation_count', 0)
        meme.environment_fitness = data.get('environment_fitness', {})
        return meme


class MemePool:
    """
    Collection and management system for memes in the simulation.
    
    Handles meme storage, retrieval, evolution tracking, and population dynamics.
    """
    
    def __init__(self, max_population: int = 1000):
        """
        Initialize meme pool.
        
        Args:
            max_population: Maximum number of memes to maintain
        """
        self.memes: Dict[str, Meme] = {}
        self.max_population = max_population
        self.generation_stats: Dict[int, Dict[str, Any]] = {}
        
    def add_meme(self, meme: Meme) -> bool:
        """
        Add a meme to the pool.
        
        Args:
            meme: Meme instance to add
            
        Returns:
            True if successfully added, False if pool is full
            
        TODO: Implement population control strategies:
        - Fitness-based selection when at capacity
        - Diversity maintenance
        - Generation balancing
        """
        if len(self.memes) >= self.max_population:
            # TODO: Implement selection pressure
            return False
        
        self.memes[meme.meme_id] = meme
        return True
    
    def get_fittest_memes(self, count: int) -> List[Meme]:
        """
        Retrieve the fittest memes from the pool.
        
        Args:
            count: Number of memes to retrieve
            
        Returns:
            List of fittest memes
        """
        sorted_memes = sorted(
            self.memes.values(),
            key=lambda m: m.fitness_score,
            reverse=True
        )
        return sorted_memes[:count]
    
    def evolve_population(self, selection_pressure: float = 0.1) -> None:
        """
        Evolve the meme population through selection and reproduction.
        
        Args:
            selection_pressure: Fraction of population to select for reproduction
            
        TODO: Implement complete evolutionary cycle:
        - Selection based on fitness
        - Crossover and mutation
        - Population replacement strategies
        - Diversity maintenance
        """
        # TODO: Implement evolutionary algorithms
        pass


# TODO: Implement additional classes:
# - MemeNetwork: Graph structure for meme relationships
# - MemeEcosystem: Environmental context for meme evolution
# - MemeAnalyzer: Tools for analyzing meme populations and evolution
