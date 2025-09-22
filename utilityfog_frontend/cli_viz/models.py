
"""
Data models for CLI visualization system.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class NodeState(Enum):
    """States that a tree node can be in."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PROCESSING = "processing"
    ERROR = "error"
    UNKNOWN = "unknown"


class MessageType(Enum):
    """Types of messages in the system."""
    COORDINATION = "coordination"
    DATA = "data"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    CONTROL = "control"


@dataclass
class TreeNode:
    """Represents a node in the fractal tree visualization."""
    id: str
    name: str
    state: NodeState = NodeState.UNKNOWN
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    position: tuple[float, float] = (0.0, 0.0)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)
    
    def add_child(self, child_id: str) -> None:
        """Add a child node ID."""
        if child_id not in self.children:
            self.children.append(child_id)
    
    def remove_child(self, child_id: str) -> None:
        """Remove a child node ID."""
        if child_id in self.children:
            self.children.remove(child_id)
    
    def update_state(self, new_state: NodeState) -> None:
        """Update the node state and timestamp."""
        self.state = new_state
        self.last_updated = time.time()


@dataclass
class MessageFlow:
    """Represents a message flow between nodes."""
    id: str
    source_id: str
    target_id: str
    message_type: MessageType
    content: Any
    timestamp: float = field(default_factory=time.time)
    status: str = "pending"  # pending, delivered, failed
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def mark_delivered(self) -> None:
        """Mark the message as delivered."""
        self.status = "delivered"
        self.metadata["delivered_at"] = time.time()
    
    def mark_failed(self, error: str) -> None:
        """Mark the message as failed."""
        self.status = "failed"
        self.metadata["error"] = error
        self.metadata["failed_at"] = time.time()


@dataclass
class StateTransition:
    """Represents a state transition event."""
    node_id: str
    from_state: NodeState
    to_state: NodeState
    timestamp: float = field(default_factory=time.time)
    trigger: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def duration_since(self) -> float:
        """Get duration since this transition occurred."""
        return time.time() - self.timestamp


@dataclass
class VisualizationData:
    """Container for all visualization data."""
    nodes: Dict[str, TreeNode] = field(default_factory=dict)
    messages: List[MessageFlow] = field(default_factory=list)
    transitions: List[StateTransition] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_node(self, node: TreeNode) -> None:
        """Add a node to the visualization."""
        self.nodes[node.id] = node
    
    def remove_node(self, node_id: str) -> None:
        """Remove a node from the visualization."""
        if node_id in self.nodes:
            # Remove from parent's children
            node = self.nodes[node_id]
            if node.parent_id and node.parent_id in self.nodes:
                self.nodes[node.parent_id].remove_child(node_id)
            
            # Remove children references
            for child_id in node.children:
                if child_id in self.nodes:
                    self.nodes[child_id].parent_id = None
            
            del self.nodes[node_id]
    
    def add_message(self, message: MessageFlow) -> None:
        """Add a message flow to the visualization."""
        self.messages.append(message)
        # Keep only recent messages (last 100)
        if len(self.messages) > 100:
            self.messages = self.messages[-100:]
    
    def add_transition(self, transition: StateTransition) -> None:
        """Add a state transition to the visualization."""
        self.transitions.append(transition)
        # Keep only recent transitions (last 50)
        if len(self.transitions) > 50:
            self.transitions = self.transitions[-50:]
        
        # Update node state if it exists
        if transition.node_id in self.nodes:
            self.nodes[transition.node_id].update_state(transition.to_state)
    
    def get_active_nodes(self) -> List[TreeNode]:
        """Get all nodes in active state."""
        return [node for node in self.nodes.values() if node.state == NodeState.ACTIVE]
    
    def get_recent_messages(self, seconds: float = 60.0) -> List[MessageFlow]:
        """Get messages from the last N seconds."""
        cutoff = time.time() - seconds
        return [msg for msg in self.messages if msg.timestamp >= cutoff]
    
    def get_recent_transitions(self, seconds: float = 60.0) -> List[StateTransition]:
        """Get transitions from the last N seconds."""
        cutoff = time.time() - seconds
        return [trans for trans in self.transitions if trans.timestamp >= cutoff]
    
    def get_node_hierarchy(self) -> Dict[str, List[str]]:
        """Get the hierarchical structure of nodes."""
        hierarchy = {}
        for node in self.nodes.values():
            if node.parent_id:
                if node.parent_id not in hierarchy:
                    hierarchy[node.parent_id] = []
                hierarchy[node.parent_id].append(node.id)
        return hierarchy
    
    def get_root_nodes(self) -> List[TreeNode]:
        """Get all root nodes (nodes without parents)."""
        return [node for node in self.nodes.values() if node.parent_id is None]


# Color schemes for different visualization themes
COLOR_SCHEMES = {
    "default": {
        NodeState.ACTIVE: "green",
        NodeState.INACTIVE: "gray", 
        NodeState.PROCESSING: "yellow",
        NodeState.ERROR: "red",
        NodeState.UNKNOWN: "blue"
    },
    "dark": {
        NodeState.ACTIVE: "#00ff00",
        NodeState.INACTIVE: "#666666",
        NodeState.PROCESSING: "#ffff00", 
        NodeState.ERROR: "#ff0000",
        NodeState.UNKNOWN: "#0088ff"
    },
    "colorblind": {
        NodeState.ACTIVE: "#009E73",
        NodeState.INACTIVE: "#999999",
        NodeState.PROCESSING: "#F0E442",
        NodeState.ERROR: "#D55E00", 
        NodeState.UNKNOWN: "#0072B2"
    }
}

MESSAGE_COLORS = {
    MessageType.COORDINATION: "blue",
    MessageType.DATA: "green",
    MessageType.HEARTBEAT: "orange",
    MessageType.ERROR: "red",
    MessageType.CONTROL: "purple"
}
