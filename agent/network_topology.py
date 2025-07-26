"""
Network Topology Module for UtilityFog-Fractal-TreeOpen Agent Simulation

This module implements the fractal tree-based communication network structure
for the utility fog system. It manages agent connectivity, message routing,
and network dynamics in a hierarchical fractal topology.

Author: UtilityFog-Fractal-TreeOpen Project
License: MIT
"""

from typing import Dict, List, Any, Optional, Tuple, Set, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
import random
import math
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
import networkx as nx
import numpy as np

from foglet_agent import FogletAgent


class NodeType(Enum):
    """Enumeration of node types in the fractal network."""
    ROOT = "root"
    BRANCH = "branch"
    LEAF = "leaf"
    RELAY = "relay"
    BRIDGE = "bridge"


class ConnectionType(Enum):
    """Enumeration of connection types between nodes."""
    PARENT_CHILD = "parent_child"
    SIBLING = "sibling"
    CROSS_BRANCH = "cross_branch"
    EMERGENCY = "emergency"
    TEMPORARY = "temporary"


class MessagePriority(Enum):
    """Enumeration of message priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"


@dataclass
class NetworkNode:
    """Represents a node in the fractal network topology."""
    node_id: str
    agent: Optional[FogletAgent] = None
    node_type: NodeType = NodeType.LEAF
    level: int = 0
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    parent_id: Optional[str] = None
    children_ids: Set[str] = field(default_factory=set)
    sibling_ids: Set[str] = field(default_factory=set)
    connection_capacity: int = 10
    current_load: float = 0.0
    last_activity: float = field(default_factory=time.time)


@dataclass
class NetworkConnection:
    """Represents a connection between two nodes in the network."""
    connection_id: str
    source_id: str
    target_id: str
    connection_type: ConnectionType = ConnectionType.PARENT_CHILD
    bandwidth: float = 1.0
    latency: float = 1.0
    reliability: float = 0.95
    energy_cost: float = 0.01
    established_time: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    message_count: int = 0


@dataclass
class NetworkMessage:
    """Represents a message being transmitted through the network."""
    message_id: str
    source_id: str
    target_id: str
    content: Dict[str, Any]
    priority: MessagePriority = MessagePriority.NORMAL
    ttl: int = 10
    route: List[str] = field(default_factory=list)
    created_time: float = field(default_factory=time.time)
    size: int = 1
    requires_ack: bool = False


class RoutingStrategy(ABC):
    """Abstract base class for network routing strategies."""
    
    @abstractmethod
    def find_route(
        self,
        source_id: str,
        target_id: str,
        network: 'FractalNetwork'
    ) -> Optional[List[str]]:
        pass


class TreeRoutingStrategy(RoutingStrategy):
    """Routing strategy that follows the fractal tree structure."""
    
    def find_route(
        self,
        source_id: str,
        target_id: str,
        network: 'FractalNetwork'
    ) -> Optional[List[str]]:
        if source_id == target_id:
            return [source_id]
        
        source_node = network.get_node(source_id)
        target_node = network.get_node(target_id)
        
        if not source_node or not target_node:
            return None
        
        # Simple tree routing implementation
        route = [source_id]
        # TODO: Implement full tree routing algorithm
        route.append(target_id)
        return route


class FractalNetwork:
    """Core fractal network topology implementation."""
    
    def __init__(
        self,
        max_depth: int = 5,
        branching_factor: int = 3,
        routing_strategy: Optional[RoutingStrategy] = None
    ):
        self.max_depth = max_depth
        self.branching_factor = branching_factor
        self.routing_strategy = routing_strategy or TreeRoutingStrategy()
        
        self.nodes: Dict[str, NetworkNode] = {}
        self.connections: Dict[str, NetworkConnection] = {}
        self.root_id: Optional[str] = None
        
        self.message_queue: deque = deque()
        self.active_messages: Dict[str, NetworkMessage] = {}
        self.message_history: List[Dict[str, Any]] = []
        
        self.total_messages_sent: int = 0
        self.total_messages_delivered: int = 0
        self.total_messages_dropped: int = 0
        self.average_latency: float = 0.0
        
        self.reconfiguration_callbacks: List[Callable[['FractalNetwork'], None]] = []
        self.failure_handlers: List[Callable[[str, str], None]] = []
        
        self.graph = nx.DiGraph()
    
    def add_node(
        self,
        node_id: str,
        agent: Optional[FogletAgent] = None,
        parent_id: Optional[str] = None,
        position: Optional[Tuple[float, float, float]] = None
    ) -> bool:
        """Add a new node to the network."""
        if node_id in self.nodes:
            return False
        
        if parent_id is None:
            node_type = NodeType.ROOT
            level = 0
            self.root_id = node_id
        else:
            parent_node = self.nodes.get(parent_id)
            if not parent_node:
                return False
            
            level = parent_node.level + 1
            if level >= self.max_depth:
                node_type = NodeType.LEAF
            else:
                node_type = NodeType.BRANCH
        
        if position is None:
            position = self._calculate_fractal_position(node_id, parent_id, level)
        
        node = NetworkNode(
            node_id=node_id,
            agent=agent,
            node_type=node_type,
            level=level,
            position=position,
            parent_id=parent_id
        )
        
        self.nodes[node_id] = node
        self.graph.add_node(node_id)
        
        if parent_id:
            self._create_connection(parent_id, node_id, ConnectionType.PARENT_CHILD)
            parent_node.children_ids.add(node_id)
        
        return True
    
    def get_node(self, node_id: str) -> Optional[NetworkNode]:
        """Get a node by its ID."""
        return self.nodes.get(node_id)
    
    def send_message(
        self,
        source_id: str,
        target_id: str,
        content: Dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> Optional[str]:
        """Send a message from source to target node."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return None
        
        route = self.routing_strategy.find_route(source_id, target_id, self)
        if not route:
            return None
        
        message_id = str(uuid.uuid4())
        message = NetworkMessage(
            message_id=message_id,
            source_id=source_id,
            target_id=target_id,
            content=content,
            priority=priority,
            route=route
        )
        
        self.message_queue.append(message)
        self.active_messages[message_id] = message
        
        return message_id
    
    def get_network_stats(self) -> Dict[str, Any]:
        """Get comprehensive network statistics."""
        stats = {
            'total_nodes': len(self.nodes),
            'total_connections': len(self.connections),
            'max_depth': self.max_depth,
            'branching_factor': self.branching_factor,
            'total_messages_sent': self.total_messages_sent,
            'total_messages_delivered': self.total_messages_delivered,
            'total_messages_dropped': self.total_messages_dropped,
            'average_latency': self.average_latency,
            'active_messages': len(self.active_messages),
            'queued_messages': len(self.message_queue)
        }
        
        node_types = defaultdict(int)
        node_levels = defaultdict(int)
        
        for node in self.nodes.values():
            node_types[node.node_type.value] += 1
            node_levels[node.level] += 1
        
        stats['node_types'] = dict(node_types)
        stats['node_levels'] = dict(node_levels)
        
        return stats
    
    def _calculate_fractal_position(
        self,
        node_id: str,
        parent_id: Optional[str],
        level: int
    ) -> Tuple[float, float, float]:
        """Calculate position for a node based on fractal geometry."""
        if parent_id is None:
            return (0.0, 0.0, 0.0)
        
        parent_pos = self.nodes[parent_id].position
        angle = random.uniform(0, 2 * math.pi)
        radius = 10.0 / (level + 1)
        
        x = parent_pos[0] + radius * math.cos(angle)
        y = parent_pos[1] + radius * math.sin(angle)
        z = parent_pos[2] + random.uniform(-radius/2, radius/2)
        
        return (x, y, z)
    
    def _create_connection(
        self,
        source_id: str,
        target_id: str,
        connection_type: ConnectionType
    ) -> Optional[str]:
        """Create a connection between two nodes."""
        if source_id not in self.nodes or target_id not in self.nodes:
            return None
        
        connection_id = f"{source_id}-{target_id}"
        
        connection = NetworkConnection(
            connection_id=connection_id,
            source_id=source_id,
            target_id=target_id,
            connection_type=connection_type
        )
        
        self.connections[connection_id] = connection
        self.graph.add_edge(source_id, target_id)
        
        return connection_id
