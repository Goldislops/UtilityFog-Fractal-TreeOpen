"""
Foglet Agent Module for UtilityFog-Fractal-TreeOpen Agent Simulation

This module defines the core FogletAgent class that represents individual agents
in the utility fog network. Agents are influenced by memes, make decisions based
on their internal state and environment, and participate in the fractal network.

Author: UtilityFog-Fractal-TreeOpen Project
License: MIT
"""

from typing import Dict, List, Any, Optional, Tuple, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
import random
import uuid
import time
import math
from abc import ABC, abstractmethod

from meme_structure import Meme, MemeType, MemePool


class AgentState(Enum):
    """Enumeration of possible agent states."""
    IDLE = "idle"
    ACTIVE = "active"
    COMMUNICATING = "communicating"
    PROCESSING = "processing"
    LEARNING = "learning"
    REPRODUCING = "reproducing"
    MAINTENANCE = "maintenance"


class AgentRole(Enum):
    """Enumeration of agent roles in the network."""
    WORKER = "worker"
    COORDINATOR = "coordinator"
    SENSOR = "sensor"
    ACTUATOR = "actuator"
    RELAY = "relay"
    SPECIALIST = "specialist"


@dataclass
class AgentCapabilities:
    """
    Defines the capabilities and limitations of an agent.
    
    Attributes:
        processing_power: Computational capacity (0.0-1.0)
        memory_capacity: Information storage capacity
        communication_range: Maximum communication distance
        energy_efficiency: Energy consumption efficiency (0.0-1.0)
        learning_rate: Speed of adaptation and learning (0.0-1.0)
        cooperation_tendency: Willingness to cooperate (0.0-1.0)
    """
    processing_power: float = field(default_factory=lambda: random.uniform(0.3, 0.9))
    memory_capacity: int = field(default_factory=lambda: random.randint(50, 200))
    communication_range: float = field(default_factory=lambda: random.uniform(5.0, 15.0))
    energy_efficiency: float = field(default_factory=lambda: random.uniform(0.4, 0.9))
    learning_rate: float = field(default_factory=lambda: random.uniform(0.1, 0.7))
    cooperation_tendency: float = field(default_factory=lambda: random.uniform(0.2, 0.8))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert capabilities to dictionary representation."""
        return {
            'processing_power': self.processing_power,
            'memory_capacity': self.memory_capacity,
            'communication_range': self.communication_range,
            'energy_efficiency': self.energy_efficiency,
            'learning_rate': self.learning_rate,
            'cooperation_tendency': self.cooperation_tendency
        }


@dataclass
class AgentMemory:
    """
    Agent's memory system for storing experiences and knowledge.
    
    Attributes:
        experiences: List of past experiences and their outcomes
        knowledge_base: Accumulated knowledge and learned patterns
        meme_history: History of meme infections and their effects
        social_connections: Information about other agents
    """
    experiences: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_base: Dict[str, Any] = field(default_factory=dict)
    meme_history: List[Dict[str, Any]] = field(default_factory=list)
    social_connections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def add_experience(self, experience: Dict[str, Any]) -> None:
        """Add a new experience to memory."""
        experience['timestamp'] = time.time()
        self.experiences.append(experience)
        
        # TODO: Implement memory consolidation and forgetting
        # TODO: Add experience categorization and indexing
    
    def retrieve_similar_experiences(self, context: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve experiences similar to the current context.
        
        Args:
            context: Current situation context
            limit: Maximum number of experiences to return
            
        Returns:
            List of similar experiences
            
        TODO: Implement sophisticated similarity matching:
        - Context vector similarity
        - Temporal relevance weighting
        - Outcome-based filtering
        """
        # Simple implementation - return most recent experiences
        return self.experiences[-limit:] if self.experiences else []


class FogletAgent:
    """
    Core agent class representing an individual foglet in the utility fog network.
    
    Agents are autonomous entities that:
    - Process information and make decisions
    - Communicate with other agents
    - Are influenced by memes
    - Adapt and learn from experiences
    - Participate in collective behaviors
    """
    
    def __init__(
        self,
        agent_id: Optional[str] = None,
        position: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        role: AgentRole = AgentRole.WORKER,
        capabilities: Optional[AgentCapabilities] = None,
        initial_memes: Optional[List[Meme]] = None
    ):
        """
        Initialize a new foglet agent.
        
        Args:
            agent_id: Unique identifier for this agent
            position: 3D position in the network space
            role: Agent's role in the network
            capabilities: Agent's capabilities and limitations
            initial_memes: Starting set of memes
        """
        self.agent_id = agent_id or str(uuid.uuid4())
        self.position = position
        self.role = role
        self.capabilities = capabilities or AgentCapabilities()
        
        # State management
        self.state = AgentState.IDLE
        self.energy_level: float = 1.0
        self.health: float = 1.0
        self.age: int = 0
        
        # Memory and learning
        self.memory = AgentMemory()
        self.learning_progress: Dict[str, float] = {}
        
        # Meme system
        self.active_memes: Dict[str, Meme] = {}
        self.meme_resistances: Dict[MemeType, float] = {
            meme_type: random.uniform(0.1, 0.9) for meme_type in MemeType
        }
        
        # Initialize with starting memes
        if initial_memes:
            for meme in initial_memes:
                self.infect_with_meme(meme)
        
        # Communication and networking
        self.neighbors: Set[str] = set()
        self.communication_history: List[Dict[str, Any]] = []
        self.trust_network: Dict[str, float] = {}
        
        # Decision making
        self.decision_weights: Dict[str, float] = {
            'self_interest': 0.4,
            'group_benefit': 0.3,
            'meme_influence': 0.2,
            'random_exploration': 0.1
        }
        
        # Performance tracking
        self.performance_metrics: Dict[str, float] = {
            'tasks_completed': 0,
            'successful_communications': 0,
            'memes_propagated': 0,
            'cooperation_events': 0
        }
        
        # Task and goal management
        self.current_task: Optional[Dict[str, Any]] = None
        self.task_queue: List[Dict[str, Any]] = []
        self.goals: List[Dict[str, Any]] = []
    
    def update(self, dt: float, environment_context: Dict[str, Any]) -> None:
        """
        Update agent state for one simulation timestep.
        
        Args:
            dt: Time delta for this update
            environment_context: Current environment state and conditions
            
        TODO: Implement comprehensive update cycle:
        - Energy consumption and recovery
        - Meme activation and influence
        - Task processing and completion
        - Learning and adaptation
        - Health and aging effects
        """
        self.age += 1
        
        # Update energy based on activity and efficiency
        energy_consumption = self._calculate_energy_consumption(dt)
        self.energy_level = max(0.0, self.energy_level - energy_consumption)
        
        # Process active memes and their influences
        self._process_meme_influences(environment_context)
        
        # Update current task if any
        if self.current_task:
            self._process_current_task(dt, environment_context)
        
        # Make decisions about new actions
        self._make_decisions(environment_context)
        
        # Update learning and adaptation
        self._update_learning(environment_context)
        
        # Maintain health and perform maintenance
        self._perform_maintenance(dt)
    
    def infect_with_meme(self, meme: Meme, infection_strength: float = 1.0) -> bool:
        """
        Attempt to infect this agent with a meme.
        
        Args:
            meme: The meme attempting to infect this agent
            infection_strength: Strength of the infection attempt (0.0-1.0)
            
        Returns:
            True if infection was successful, False otherwise
            
        TODO: Implement sophisticated infection mechanics:
        - Resistance based on meme type and agent characteristics
        - Compatibility with existing memes
        - Environmental factors affecting infection
        - Mutation during transmission
        """
        # Check resistance
        resistance = self.meme_resistances.get(meme.meme_type, 0.5)
        infection_probability = infection_strength * (1.0 - resistance) * meme.genes.virality
        
        if random.random() > infection_probability:
            return False
        
        # Check for conflicts with existing memes
        for existing_meme in self.active_memes.values():
            if existing_meme.meme_type == meme.meme_type:
                # Competition between memes of same type
                if existing_meme.genes.dominance > meme.genes.dominance:
                    return False
                else:
                    # Replace weaker meme
                    del self.active_memes[existing_meme.meme_id]
                    break
        
        # Successful infection
        self.active_memes[meme.meme_id] = meme.copy()
        meme.propagation_count += 1
        
        # Record in memory
        infection_record = {
            'meme_id': meme.meme_id,
            'meme_type': meme.meme_type.value,
            'infection_time': time.time(),
            'infection_strength': infection_strength,
            'source': 'external'  # TODO: Track infection source
        }
        self.memory.meme_history.append(infection_record)
        
        return True
    
    def propagate_memes(self, target_agents: List['FogletAgent']) -> Dict[str, int]:
        """
        Attempt to propagate active memes to target agents.
        
        Args:
            target_agents: List of agents to propagate memes to
            
        Returns:
            Dictionary mapping meme IDs to successful propagation counts
            
        TODO: Implement advanced propagation strategies:
        - Selective propagation based on meme fitness
        - Target agent compatibility assessment
        - Network topology considerations
        - Propagation timing optimization
        """
        propagation_results = {}
        
        for meme in self.active_memes.values():
            successful_propagations = 0
            
            for target_agent in target_agents:
                # Check if propagation is possible
                if not meme.can_propagate_to(target_agent.get_context()):
                    continue
                
                # Calculate propagation strength based on relationship
                trust_factor = self.trust_network.get(target_agent.agent_id, 0.5)
                propagation_strength = meme.genes.virality * trust_factor
                
                # Attempt infection
                if target_agent.infect_with_meme(meme, propagation_strength):
                    successful_propagations += 1
                    self.performance_metrics['memes_propagated'] += 1
            
            propagation_results[meme.meme_id] = successful_propagations
        
        return propagation_results
    
    def make_decision(self, decision_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make a decision based on current state, memes, and context.
        
        Args:
            decision_context: Information about the decision situation
            
        Returns:
            Dictionary containing the decision and reasoning
            
        TODO: Implement sophisticated decision-making:
        - Multi-criteria decision analysis
        - Meme-influenced preference weighting
        - Learning from past decisions
        - Uncertainty handling
        - Group decision participation
        """
        decision = {
            'action': 'idle',
            'confidence': 0.5,
            'reasoning': [],
            'meme_influences': {}
        }
        
        # Gather meme influences
        meme_modifications = {}
        for meme in self.active_memes.values():
            activation_strength = self._calculate_meme_activation(meme, decision_context)
            if activation_strength > 0:
                modifications = meme.activate(self.agent_id, activation_strength)
                meme_modifications[meme.meme_id] = modifications
                decision['meme_influences'][meme.meme_id] = activation_strength
        
        # Apply decision weights and meme influences
        available_actions = decision_context.get('available_actions', ['idle', 'communicate', 'work'])
        action_scores = {}
        
        for action in available_actions:
            score = 0.0
            
            # Base preference
            score += self.decision_weights.get('self_interest', 0.4) * self._evaluate_self_interest(action, decision_context)
            score += self.decision_weights.get('group_benefit', 0.3) * self._evaluate_group_benefit(action, decision_context)
            score += self.decision_weights.get('random_exploration', 0.1) * random.random()
            
            # Apply meme influences
            meme_influence_total = 0.0
            for meme_id, modifications in meme_modifications.items():
                action_bias = modifications.get('action_bias', {})
                if action in action_bias:
                    meme_influence_total += action_bias[action]
            
            score += self.decision_weights.get('meme_influence', 0.2) * meme_influence_total
            action_scores[action] = score
        
        # Select best action
        best_action = max(action_scores.keys(), key=lambda a: action_scores[a])
        decision['action'] = best_action
        decision['confidence'] = action_scores[best_action] / max(action_scores.values()) if action_scores else 0.5
        
        return decision
    
    def communicate_with(self, target_agent: 'FogletAgent', message: Dict[str, Any]) -> bool:
        """
        Communicate with another agent.
        
        Args:
            target_agent: The agent to communicate with
            message: Message content and metadata
            
        Returns:
            True if communication was successful, False otherwise
            
        TODO: Implement communication protocols:
        - Message encoding and decoding
        - Reliability and error handling
        - Bandwidth and latency simulation
        - Security and authentication
        - Protocol negotiation
        """
        # Check if target is within communication range
        distance = self._calculate_distance(target_agent.position)
        if distance > self.capabilities.communication_range:
            return False
        
        # Check energy requirements
        energy_cost = self._calculate_communication_cost(message, distance)
        if self.energy_level < energy_cost:
            return False
        
        # Consume energy
        self.energy_level -= energy_cost
        
        # Record communication
        comm_record = {
            'target_id': target_agent.agent_id,
            'message_type': message.get('type', 'general'),
            'timestamp': time.time(),
            'success': True,
            'energy_cost': energy_cost
        }
        self.communication_history.append(comm_record)
        
        # Update trust network
        if target_agent.agent_id not in self.trust_network:
            self.trust_network[target_agent.agent_id] = 0.5
        
        # TODO: Implement message delivery and response handling
        
        self.performance_metrics['successful_communications'] += 1
        return True
    
    def learn_from_experience(self, experience: Dict[str, Any]) -> None:
        """
        Learn and adapt from a new experience.
        
        Args:
            experience: Experience data including context, action, and outcome
            
        TODO: Implement learning mechanisms:
        - Reinforcement learning from outcomes
        - Pattern recognition in experiences
        - Skill development and improvement
        - Meme evolution based on success
        - Social learning from other agents
        """
        # Add to memory
        self.memory.add_experience(experience)
        
        # Update learning progress
        skill_type = experience.get('skill_type', 'general')
        outcome_quality = experience.get('outcome_quality', 0.5)
        
        if skill_type not in self.learning_progress:
            self.learning_progress[skill_type] = 0.0
        
        # Simple learning update
        learning_delta = self.capabilities.learning_rate * outcome_quality
        self.learning_progress[skill_type] += learning_delta
        
        # TODO: Implement more sophisticated learning algorithms
        # TODO: Update decision weights based on experience
        # TODO: Evolve memes based on their contribution to success
    
    def get_context(self) -> Dict[str, Any]:
        """
        Get current agent context for decision making and meme propagation.
        
        Returns:
            Dictionary containing agent's current context
        """
        return {
            'agent_id': self.agent_id,
            'position': self.position,
            'state': self.state.value,
            'role': self.role.value,
            'energy_level': self.energy_level,
            'health': self.health,
            'capabilities': self.capabilities.to_dict(),
            'active_memes': list(self.active_memes.keys()),
            'neighbors': list(self.neighbors),
            'performance_metrics': self.performance_metrics.copy()
        }
    
    def _process_meme_influences(self, environment_context: Dict[str, Any]) -> None:
        """Process the influence of active memes on agent behavior."""
        for meme in self.active_memes.values():
            activation_strength = self._calculate_meme_activation(meme, environment_context)
            if activation_strength > 0:
                modifications = meme.activate(self.agent_id, activation_strength)
                self._apply_behavioral_modifications(modifications)
    
    def _calculate_meme_activation(self, meme: Meme, context: Dict[str, Any]) -> float:
        """Calculate how strongly a meme should be activated in the current context."""
        base_activation = 0.5
        
        # Factor in meme dominance
        base_activation *= meme.genes.dominance
        
        # Factor in environmental suitability
        # TODO: Implement context-based activation modulation
        
        return min(1.0, base_activation)
    
    def _apply_behavioral_modifications(self, modifications: Dict[str, Any]) -> None:
        """Apply behavioral modifications from meme activation."""
        # TODO: Implement behavioral modification application
        # This could modify decision weights, capabilities, or other agent properties
        pass
    
    def _calculate_energy_consumption(self, dt: float) -> float:
        """Calculate energy consumption for this timestep."""
        base_consumption = 0.01 * dt  # Base metabolic cost
        
        # Activity-based consumption
        if self.state == AgentState.ACTIVE:
            base_consumption *= 2.0
        elif self.state == AgentState.COMMUNICATING:
            base_consumption *= 1.5
        elif self.state == AgentState.PROCESSING:
            base_consumption *= 3.0
        
        # Efficiency factor
        return base_consumption / self.capabilities.energy_efficiency
    
    def _process_current_task(self, dt: float, environment_context: Dict[str, Any]) -> None:
        """Process the current task if any."""
        if not self.current_task:
            return
        
        # TODO: Implement task processing logic
        # This should update task progress and handle completion
        pass
    
    def _make_decisions(self, environment_context: Dict[str, Any]) -> None:
        """Make decisions about new actions to take."""
        if self.state == AgentState.IDLE and self.energy_level > 0.3:
            # TODO: Implement decision-making for new actions
            pass
    
    def _update_learning(self, environment_context: Dict[str, Any]) -> None:
        """Update learning and adaptation processes."""
        # TODO: Implement continuous learning updates
        pass
    
    def _perform_maintenance(self, dt: float) -> None:
        """Perform maintenance activities and health updates."""
        # Gradual health degradation
        self.health -= 0.001 * dt
        
        # Recovery when idle
        if self.state == AgentState.IDLE and self.energy_level > 0.8:
            self.health = min(1.0, self.health + 0.01 * dt)
    
    def _evaluate_self_interest(self, action: str, context: Dict[str, Any]) -> float:
        """Evaluate how much an action serves self-interest."""
        # TODO: Implement self-interest evaluation
        return random.uniform(0.0, 1.0)
    
    def _evaluate_group_benefit(self, action: str, context: Dict[str, Any]) -> float:
        """Evaluate how much an action benefits the group."""
        # TODO: Implement group benefit evaluation
        return random.uniform(0.0, 1.0)
    
    def _calculate_distance(self, other_position: Tuple[float, float, float]) -> float:
        """Calculate Euclidean distance to another position."""
        return math.sqrt(
            sum((a - b) ** 2 for a, b in zip(self.position, other_position))
        )
    
    def _calculate_communication_cost(self, message: Dict[str, Any], distance: float) -> float:
        """Calculate energy cost of communication."""
        base_cost = 0.01
        distance_factor = distance / self.capabilities.communication_range
        message_size_factor = len(str(message)) / 1000.0  # Rough size estimate
        
        return base_cost * (1.0 + distance_factor + message_size_factor)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert agent to dictionary representation for serialization."""
        return {
            'agent_id': self.agent_id,
            'position': self.position,
            'role': self.role.value,
            'state': self.state.value,
            'capabilities': self.capabilities.to_dict(),
            'energy_level': self.energy_level,
            'health': self.health,
            'age': self.age,
            'active_memes': [meme.to_dict() for meme in self.active_memes.values()],
            'performance_metrics': self.performance_metrics,
            'decision_weights': self.decision_weights
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FogletAgent':
        """Create agent instance from dictionary representation."""
        # TODO: Implement complete deserialization
        agent = cls(
            agent_id=data['agent_id'],
            position=tuple(data['position']),
            role=AgentRole(data['role'])
        )
        # TODO: Restore all agent state from data
        return agent


# TODO: Implement additional classes:
# - AgentSwarm: Collection management for multiple agents
# - AgentBehaviorTree: Hierarchical behavior system
# - AgentCommunicationProtocol: Standardized communication framework
# - AgentLearningSystem: Advanced learning and adaptation mechanisms
