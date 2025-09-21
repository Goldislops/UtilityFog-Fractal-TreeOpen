
"""
Rendering engines for different visualization types.
"""

import time
from typing import Dict, List
from abc import ABC, abstractmethod

from .models import (
    VisualizationData, TreeNode, NodeState, MessageType, COLOR_SCHEMES, MESSAGE_COLORS
)


class BaseRenderer(ABC):
    """Abstract base class for all renderers."""
    
    def __init__(self, width: int = 80, height: int = 24, color_scheme: str = "default"):
        self.width = width
        self.height = height
        self.color_scheme = color_scheme
        self.colors = COLOR_SCHEMES.get(color_scheme, COLOR_SCHEMES["default"])
    
    @abstractmethod
    def render(self, data: VisualizationData) -> str:
        """Render the visualization data to a string."""
        pass
    
    def _get_node_color(self, state: NodeState) -> str:
        """Get color for a node state."""
        return self.colors.get(state, self.colors[NodeState.UNKNOWN])
    
    def _get_message_color(self, msg_type: MessageType) -> str:
        """Get color for a message type."""
        return MESSAGE_COLORS.get(msg_type, "white")


class TreeRenderer(BaseRenderer):
    """Renders the fractal tree structure."""
    
    def __init__(self, width: int = 80, height: int = 24, 
                 color_scheme: str = "default", show_ids: bool = False):
        super().__init__(width, height, color_scheme)
        self.show_ids = show_ids
    
    def render(self, data: VisualizationData) -> str:
        """Render the tree structure as ASCII art."""
        if not data.nodes:
            return "No nodes to display"
        
        lines = []
        lines.append("=" * self.width)
        lines.append("FRACTAL TREE VISUALIZATION")
        lines.append("=" * self.width)
        lines.append("")
        
        # Get root nodes and render each tree
        root_nodes = data.get_root_nodes()
        hierarchy = data.get_node_hierarchy()
        
        for root in root_nodes:
            tree_lines = self._render_node_tree(root, hierarchy, data.nodes, "", True)
            lines.extend(tree_lines)
            lines.append("")
        
        # Add summary statistics
        lines.append("-" * self.width)
        lines.append(f"Total Nodes: {len(data.nodes)}")
        lines.append(f"Active Nodes: {len(data.get_active_nodes())}")
        lines.append(f"Recent Messages: {len(data.get_recent_messages())}")
        lines.append(f"Recent Transitions: {len(data.get_recent_transitions())}")
        
        return "\n".join(lines)
    
    def _render_node_tree(self, node: TreeNode, hierarchy: Dict[str, List[str]], 
                         all_nodes: Dict[str, TreeNode], prefix: str, is_last: bool) -> List[str]:
        """Recursively render a node and its children."""
        lines = []
        
        # Node connector
        connector = "└── " if is_last else "├── "
        
        # Node representation
        state_symbol = self._get_state_symbol(node.state)
        node_name = f"{node.id}: {node.name}" if self.show_ids else node.name
        
        lines.append(f"{prefix}{connector}{state_symbol} {node_name}")
        
        # Add metadata if present
        if node.metadata:
            meta_info = ", ".join([f"{k}={v}" for k, v in node.metadata.items()])
            meta_prefix = prefix + ("    " if is_last else "│   ")
            lines.append(f"{meta_prefix}└─ [{meta_info}]")
        
        # Render children
        children_ids = hierarchy.get(node.id, [])
        for i, child_id in enumerate(children_ids):
            if child_id in all_nodes:
                child_node = all_nodes[child_id]
                child_prefix = prefix + ("    " if is_last else "│   ")
                child_is_last = (i == len(children_ids) - 1)
                
                child_lines = self._render_node_tree(
                    child_node, hierarchy, all_nodes, child_prefix, child_is_last
                )
                lines.extend(child_lines)
        
        return lines
    
    def _get_state_symbol(self, state: NodeState) -> str:
        """Get symbol representation for node state."""
        symbols = {
            NodeState.ACTIVE: "●",
            NodeState.INACTIVE: "○", 
            NodeState.PROCESSING: "◐",
            NodeState.ERROR: "✗",
            NodeState.UNKNOWN: "?"
        }
        return symbols.get(state, "?")


class FlowRenderer(BaseRenderer):
    """Renders message flows between nodes."""
    
    def __init__(self, width: int = 80, height: int = 24, 
                 color_scheme: str = "default", time_window: float = 60.0):
        super().__init__(width, height, color_scheme)
        self.time_window = time_window
    
    def render(self, data: VisualizationData) -> str:
        """Render message flows as a flow diagram."""
        lines = []
        lines.append("=" * self.width)
        lines.append("MESSAGE FLOW VISUALIZATION")
        lines.append("=" * self.width)
        lines.append("")
        
        # Get recent messages
        recent_messages = data.get_recent_messages(self.time_window)
        
        if not recent_messages:
            lines.append("No recent message flows to display")
            return "\n".join(lines)
        
        # Group messages by type
        by_type = {}
        for msg in recent_messages:
            if msg.message_type not in by_type:
                by_type[msg.message_type] = []
            by_type[msg.message_type].append(msg)
        
        # Render each message type
        for msg_type, messages in by_type.items():
            lines.append(f"{msg_type.value.upper()} MESSAGES:")
            lines.append("-" * 40)
            
            for msg in sorted(messages, key=lambda m: m.timestamp, reverse=True):
                age = time.time() - msg.timestamp
                status_symbol = self._get_status_symbol(msg.status)
                
                source_name = self._get_node_name(msg.source_id, data.nodes)
                target_name = self._get_node_name(msg.target_id, data.nodes)
                
                lines.append(f"{status_symbol} {source_name} → {target_name} ({age:.1f}s ago)")
                
                # Add content preview if available
                if hasattr(msg.content, '__str__') and len(str(msg.content)) < 50:
                    lines.append(f"    Content: {msg.content}")
            
            lines.append("")
        
        # Add flow statistics
        lines.append("-" * self.width)
        lines.append(f"Total Flows: {len(recent_messages)}")
        lines.append(f"Time Window: {self.time_window}s")
        
        # Message type breakdown
        for msg_type, messages in by_type.items():
            lines.append(f"{msg_type.value}: {len(messages)}")
        
        return "\n".join(lines)
    
    def _get_status_symbol(self, status: str) -> str:
        """Get symbol for message status."""
        symbols = {
            "pending": "⏳",
            "delivered": "✓",
            "failed": "✗"
        }
        return symbols.get(status, "?")
    
    def _get_node_name(self, node_id: str, nodes: Dict[str, TreeNode]) -> str:
        """Get display name for a node."""
        if node_id in nodes:
            return nodes[node_id].name
        return node_id


class StateRenderer(BaseRenderer):
    """Renders state transitions over time."""
    
    def __init__(self, width: int = 80, height: int = 24, 
                 color_scheme: str = "default", time_window: float = 300.0):
        super().__init__(width, height, color_scheme)
        self.time_window = time_window
    
    def render(self, data: VisualizationData) -> str:
        """Render state transitions as a timeline."""
        lines = []
        lines.append("=" * self.width)
        lines.append("STATE TRANSITION VISUALIZATION")
        lines.append("=" * self.width)
        lines.append("")
        
        # Get recent transitions
        recent_transitions = data.get_recent_transitions(self.time_window)
        
        if not recent_transitions:
            lines.append("No recent state transitions to display")
            return "\n".join(lines)
        
        # Sort by timestamp (most recent first)
        transitions = sorted(recent_transitions, key=lambda t: t.timestamp, reverse=True)
        
        lines.append("RECENT TRANSITIONS:")
        lines.append("-" * 60)
        
        for trans in transitions:
            age = time.time() - trans.timestamp
            node_name = self._get_node_name(trans.node_id, data.nodes)
            
            from_symbol = self._get_state_symbol(trans.from_state)
            to_symbol = self._get_state_symbol(trans.to_state)
            
            lines.append(f"{age:6.1f}s ago: {node_name}")
            lines.append(f"           {from_symbol} {trans.from_state.value} → {to_symbol} {trans.to_state.value}")
            
            if trans.trigger != "unknown":
                lines.append(f"           Trigger: {trans.trigger}")
            
            lines.append("")
        
        # Add transition statistics
        lines.append("-" * self.width)
        lines.append(f"Total Transitions: {len(transitions)}")
        lines.append(f"Time Window: {self.time_window}s")
        
        # State change breakdown
        state_changes = {}
        for trans in transitions:
            change = f"{trans.from_state.value} → {trans.to_state.value}"
            state_changes[change] = state_changes.get(change, 0) + 1
        
        lines.append("Transition Types:")
        for change, count in sorted(state_changes.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {change}: {count}")
        
        return "\n".join(lines)
    
    def _get_state_symbol(self, state: NodeState) -> str:
        """Get symbol representation for node state."""
        symbols = {
            NodeState.ACTIVE: "●",
            NodeState.INACTIVE: "○",
            NodeState.PROCESSING: "◐", 
            NodeState.ERROR: "✗",
            NodeState.UNKNOWN: "?"
        }
        return symbols.get(state, "?")
    
    def _get_node_name(self, node_id: str, nodes: Dict[str, TreeNode]) -> str:
        """Get display name for a node."""
        if node_id in nodes:
            return nodes[node_id].name
        return node_id


class InteractiveRenderer(BaseRenderer):
    """Interactive renderer with real-time updates."""
    
    def __init__(self, width: int = 80, height: int = 24, 
                 color_scheme: str = "default", refresh_rate: float = 1.0):
        super().__init__(width, height, color_scheme)
        self.refresh_rate = refresh_rate
        self.current_view = "tree"  # tree, flow, state
        self.renderers = {
            "tree": TreeRenderer(width, height, color_scheme),
            "flow": FlowRenderer(width, height, color_scheme),
            "state": StateRenderer(width, height, color_scheme)
        }
    
    def render(self, data: VisualizationData) -> str:
        """Render the current view with navigation help."""
        lines = []
        
        # Header with navigation
        lines.append("=" * self.width)
        lines.append(f"INTERACTIVE VISUALIZATION - {self.current_view.upper()} VIEW")
        lines.append("Commands: [t]ree, [f]low, [s]tate, [q]uit, [r]efresh")
        lines.append("=" * self.width)
        lines.append("")
        
        # Render current view
        renderer = self.renderers[self.current_view]
        view_content = renderer.render(data)
        lines.append(view_content)
        
        # Footer with timestamp
        lines.append("")
        lines.append("-" * self.width)
        lines.append(f"Last updated: {time.strftime('%H:%M:%S')}")
        lines.append(f"Refresh rate: {self.refresh_rate}s")
        
        return "\n".join(lines)
    
    def switch_view(self, view: str) -> bool:
        """Switch to a different view."""
        if view in self.renderers:
            self.current_view = view
            return True
        return False
    
    def get_available_views(self) -> List[str]:
        """Get list of available views."""
        return list(self.renderers.keys())
