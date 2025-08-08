"""
Data Models for Visualization System

Defines shared data structures between backend and frontend for
consistent real-time communication.
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import Enum
import time


@dataclass
class SimulationConfig:
    """Configuration for real-time simulation visualization."""
    
    # Agent and network parameters
    num_agents: int = 10
    num_generations: int = 3
    max_steps: int = 100
    
    # Evolution parameters
    mutation_rate: float = 0.1
    crossover_rate: float = 0.8
    
    # Network topology
    network_depth: int = 3
    branching_factor: int = 3
    
    # Meme parameters
    initial_memes_per_agent: int = 2
    
    # Quantum myelin settings
    enable_quantum_myelin: bool = True
    entanglement_threshold: float = 0.2
    
    # Visualization settings
    step_delay: float = 0.1  # Seconds between simulation steps
    show_entanglement_arcs: bool = True
    show_meme_propagation: bool = True
    
    # Performance settings
    max_entanglements_displayed: int = 50
    max_meme_events_displayed: int = 20
    
    def dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "num_agents": self.num_agents,
            "num_generations": self.num_generations,
            "max_steps": self.max_steps,
            "mutation_rate": self.mutation_rate,
            "crossover_rate": self.crossover_rate,
            "network_depth": self.network_depth,
            "branching_factor": self.branching_factor,
            "initial_memes_per_agent": self.initial_memes_per_agent,
            "enable_quantum_myelin": self.enable_quantum_myelin,
            "entanglement_threshold": self.entanglement_threshold,
            "step_delay": self.step_delay,
            "show_entanglement_arcs": self.show_entanglement_arcs,
            "show_meme_propagation": self.show_meme_propagation,
            "max_entanglements_displayed": self.max_entanglements_displayed,
            "max_meme_events_displayed": self.max_meme_events_displayed
        }


@dataclass
class AgentUpdate:
    """Real-time agent state update."""
    id: str
    energy: float
    health: float
    active_memes: int
    position: Dict[str, float]  # x, y, z coordinates
    performance_metrics: Dict[str, Any]
    timestamp: float
    
    @classmethod
    def from_agent(cls, agent, position: Dict[str, float]):
        """Create from agent object."""
        return cls(
            id=agent.agent_id,
            energy=agent.energy_level,
            health=agent.health,
            active_memes=len(getattr(agent, 'active_memes', {})),
            position=position,
            performance_metrics=getattr(agent, 'performance_metrics', {}),
            timestamp=time.time()
        )


@dataclass
class EntanglementEvent:
    """Quantum entanglement event for visualization."""
    source: str
    target: str
    strength: float
    timestamp: float
    duration: float = 2.0  # How long to display the arc
    data: Optional[Dict[str, Any]] = None
    
    def is_expired(self, current_time: float) -> bool:
        """Check if entanglement arc should be removed."""
        return current_time - self.timestamp > self.duration


@dataclass
class MemeUpdate:
    """Meme propagation event update."""
    type: str  # "infection", "propagation", "mutation"
    meme_id: str
    agent_id: Optional[str] = None
    source_agent: Optional[str] = None
    target_agents: Optional[List[str]] = None
    strength: float = 0.0
    timestamp: float = 0.0
    data: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class NetworkUpdate:
    """Network topology update."""
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    stats: Dict[str, Any]
    timestamp: float
    
    def __post_init__(self):
        if not hasattr(self, 'timestamp') or self.timestamp == 0.0:
            self.timestamp = time.time()


class SimulationState(Enum):
    """Current simulation state."""
    STOPPED = "stopped"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class VisualizationMessage:
    """Base message structure for WebSocket communication."""
    type: str
    timestamp: float
    data: Any
    
    def __post_init__(self):
        if not hasattr(self, 'timestamp') or self.timestamp == 0.0:
            self.timestamp = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "data": self.data
        }


# Message type constants
MESSAGE_TYPES = {
    "INITIAL_STATE": "initial_state",
    "STEP_UPDATE": "step_update",
    "AGENT_UPDATE": "agent_update",
    "ENTANGLEMENT_EVENT": "entanglement_event",
    "MEME_EVENT": "meme_event",
    "NETWORK_UPDATE": "network_update",
    "CONFIG_UPDATE": "config_update",
    "SIMULATION_STARTED": "simulation_started",
    "SIMULATION_STOPPED": "simulation_stopped",
    "SIMULATION_COMPLETE": "simulation_complete",
    "ERROR": "error",
    "PING": "ping",
    "PONG": "pong"
}


# Utility functions for data conversion
def agent_to_dict(agent) -> Dict[str, Any]:
    """Convert agent object to dictionary."""
    return {
        "id": getattr(agent, 'agent_id', 'unknown'),
        "role": str(getattr(agent, 'role', 'unknown')),
        "energy": getattr(agent, 'energy_level', 0.0),
        "health": getattr(agent, 'health', 1.0),
        "active_memes": len(getattr(agent, 'active_memes', {})),
        "capabilities": getattr(agent, 'capabilities', {}),
        "performance_metrics": getattr(agent, 'performance_metrics', {})
    }


def meme_to_dict(meme) -> Dict[str, Any]:
    """Convert meme object to dictionary."""
    return {
        "id": getattr(meme, 'meme_id', 'unknown'),
        "type": str(getattr(meme, 'meme_type', 'unknown')),
        "fitness": getattr(meme, 'fitness_score', 0.0),
        "propagation_count": getattr(meme, 'propagation_count', 0),
        "payload": getattr(meme, 'payload', {})
    }


def network_stats_to_dict(network) -> Dict[str, Any]:
    """Convert network statistics to dictionary."""
    if not network:
        return {"total_nodes": 0, "total_connections": 0}
    
    try:
        stats = network.get_network_stats()
        return stats if isinstance(stats, dict) else {"total_nodes": 0, "total_connections": 0}
    except:
        return {"total_nodes": 0, "total_connections": 0}