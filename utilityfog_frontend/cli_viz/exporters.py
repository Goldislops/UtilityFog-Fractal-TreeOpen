
"""
Export functionality for visualization artifacts.
"""

import json
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

from .models import VisualizationData, TreeNode, NodeState


class BaseExporter(ABC):
    """Abstract base class for all exporters."""
    
    @abstractmethod
    def export(self, data: VisualizationData, output_path: str) -> bool:
        """Export visualization data to the specified path."""
        pass


class HTMLExporter(BaseExporter):
    """Exports visualization as interactive HTML report."""
    
    def __init__(self, include_css: bool = True, include_js: bool = True):
        self.include_css = include_css
        self.include_js = include_js
    
    def export(self, data: VisualizationData, output_path: str) -> bool:
        """Export as HTML report with interactive features."""
        try:
            html_content = self._generate_html(data)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return True
        except Exception as e:
            print(f"Error exporting HTML: {e}")
            return False
    
    def _generate_html(self, data: VisualizationData) -> str:
        """Generate complete HTML document."""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UtilityFog Fractal Tree Visualization</title>
    {self._get_css() if self.include_css else ''}
</head>
<body>
    <div class="container">
        <header>
            <h1>UtilityFog Fractal Tree Visualization</h1>
            <p>Generated: {timestamp}</p>
        </header>
        
        <nav class="tabs">
            <button class="tab-button active" onclick="showTab('tree')">Tree Structure</button>
            <button class="tab-button" onclick="showTab('flows')">Message Flows</button>
            <button class="tab-button" onclick="showTab('transitions')">State Transitions</button>
            <button class="tab-button" onclick="showTab('stats')">Statistics</button>
        </nav>
        
        <main>
            <div id="tree" class="tab-content active">
                {self._generate_tree_html(data)}
            </div>
            
            <div id="flows" class="tab-content">
                {self._generate_flows_html(data)}
            </div>
            
            <div id="transitions" class="tab-content">
                {self._generate_transitions_html(data)}
            </div>
            
            <div id="stats" class="tab-content">
                {self._generate_stats_html(data)}
            </div>
        </main>
    </div>
    
    {self._get_javascript() if self.include_js else ''}
</body>
</html>"""
        return html
    
    def _generate_tree_html(self, data: VisualizationData) -> str:
        """Generate HTML for tree structure."""
        if not data.nodes:
            return "<p>No nodes to display</p>"
        
        html = ["<div class='tree-container'>"]
        
        # Get root nodes and render each tree
        root_nodes = data.get_root_nodes()
        hierarchy = data.get_node_hierarchy()
        
        for root in root_nodes:
            html.append("<div class='tree-root'>")
            html.extend(self._render_node_html(root, hierarchy, data.nodes, 0))
            html.append("</div>")
        
        html.append("</div>")
        return "\n".join(html)
    
    def _render_node_html(self, node: TreeNode, hierarchy: Dict[str, List[str]], 
                         all_nodes: Dict[str, TreeNode], depth: int) -> List[str]:
        """Recursively render a node and its children as HTML."""
        html = []
        
        state_class = f"node-{node.state.value}"
        indent = "  " * depth
        
        html.append(f'{indent}<div class="node {state_class}" data-node-id="{node.id}">')
        html.append(f'{indent}  <div class="node-header">')
        html.append(f'{indent}    <span class="node-state"></span>')
        html.append(f'{indent}    <span class="node-name">{node.name}</span>')
        html.append(f'{indent}    <span class="node-id">({node.id})</span>')
        html.append(f'{indent}  </div>')
        
        # Add metadata
        if node.metadata:
            html.append(f'{indent}  <div class="node-metadata">')
            for key, value in node.metadata.items():
                html.append(f'{indent}    <span class="metadata-item">{key}: {value}</span>')
            html.append(f'{indent}  </div>')
        
        # Add children
        children_ids = hierarchy.get(node.id, [])
        if children_ids:
            html.append(f'{indent}  <div class="node-children">')
            for child_id in children_ids:
                if child_id in all_nodes:
                    child_node = all_nodes[child_id]
                    html.extend(self._render_node_html(child_node, hierarchy, all_nodes, depth + 2))
            html.append(f'{indent}  </div>')
        
        html.append(f'{indent}</div>')
        return html
    
    def _generate_flows_html(self, data: VisualizationData) -> str:
        """Generate HTML for message flows."""
        recent_messages = data.get_recent_messages(300.0)  # Last 5 minutes
        
        if not recent_messages:
            return "<p>No recent message flows to display</p>"
        
        html = ["<div class='flows-container'>"]
        
        # Group by message type
        by_type = {}
        for msg in recent_messages:
            if msg.message_type not in by_type:
                by_type[msg.message_type] = []
            by_type[msg.message_type].append(msg)
        
        for msg_type, messages in by_type.items():
            html.append("<div class='message-type-section'>")
            html.append(f"<h3>{msg_type.value.title()} Messages ({len(messages)})</h3>")
            html.append("<div class='messages-list'>")
            
            for msg in sorted(messages, key=lambda m: m.timestamp, reverse=True):
                age = time.time() - msg.timestamp
                status_class = f"status-{msg.status}"
                
                source_name = self._get_node_name(msg.source_id, data.nodes)
                target_name = self._get_node_name(msg.target_id, data.nodes)
                
                html.append(f"<div class='message-item {status_class}'>")
                html.append("  <div class='message-flow'>")
                html.append(f"    <span class='source'>{source_name}</span>")
                html.append("    <span class='arrow'>→</span>")
                html.append(f"    <span class='target'>{target_name}</span>")
                html.append("  </div>")
                html.append("  <div class='message-meta'>")
                html.append(f"    <span class='age'>{age:.1f}s ago</span>")
                html.append(f"    <span class='status'>{msg.status}</span>")
                html.append("  </div>")
                html.append("</div>")
            
            html.append("</div>")
            html.append("</div>")
        
        html.append("</div>")
        return "\n".join(html)
    
    def _generate_transitions_html(self, data: VisualizationData) -> str:
        """Generate HTML for state transitions."""
        recent_transitions = data.get_recent_transitions(300.0)  # Last 5 minutes
        
        if not recent_transitions:
            return "<p>No recent state transitions to display</p>"
        
        html = ["<div class='transitions-container'>"]
        
        transitions = sorted(recent_transitions, key=lambda t: t.timestamp, reverse=True)
        
        html.append("<div class='transitions-list'>")
        for trans in transitions:
            age = time.time() - trans.timestamp
            node_name = self._get_node_name(trans.node_id, data.nodes)
            
            from_class = f"state-{trans.from_state.value}"
            to_class = f"state-{trans.to_state.value}"
            
            html.append("<div class='transition-item'>")
            html.append("  <div class='transition-header'>")
            html.append(f"    <span class='node-name'>{node_name}</span>")
            html.append(f"    <span class='age'>{age:.1f}s ago</span>")
            html.append("  </div>")
            html.append("  <div class='transition-flow'>")
            html.append(f"    <span class='state {from_class}'>{trans.from_state.value}</span>")
            html.append("    <span class='arrow'>→</span>")
            html.append(f"    <span class='state {to_class}'>{trans.to_state.value}</span>")
            html.append("  </div>")
            if trans.trigger != "unknown":
                html.append(f"  <div class='trigger'>Trigger: {trans.trigger}</div>")
            html.append("</div>")
        
        html.append("</div>")
        html.append("</div>")
        return "\n".join(html)
    
    def _generate_stats_html(self, data: VisualizationData) -> str:
        """Generate HTML for statistics."""
        html = ["<div class='stats-container'>"]
        
        # Node statistics
        html.append("<div class='stats-section'>")
        html.append("<h3>Node Statistics</h3>")
        html.append(f"<div class='stat-item'>Total Nodes: <span>{len(data.nodes)}</span></div>")
        html.append(f"<div class='stat-item'>Active Nodes: <span>{len(data.get_active_nodes())}</span></div>")
        html.append(f"<div class='stat-item'>Root Nodes: <span>{len(data.get_root_nodes())}</span></div>")
        
        # State breakdown
        state_counts = {}
        for node in data.nodes.values():
            state_counts[node.state] = state_counts.get(node.state, 0) + 1
        
        html.append("<h4>State Distribution</h4>")
        for state, count in state_counts.items():
            html.append(f"<div class='stat-item'>{state.value.title()}: <span>{count}</span></div>")
        
        html.append("</div>")
        
        # Message statistics
        html.append("<div class='stats-section'>")
        html.append("<h3>Message Statistics</h3>")
        recent_messages = data.get_recent_messages(300.0)
        html.append(f"<div class='stat-item'>Recent Messages (5min): <span>{len(recent_messages)}</span></div>")
        
        # Message type breakdown
        msg_type_counts = {}
        for msg in recent_messages:
            msg_type_counts[msg.message_type] = msg_type_counts.get(msg.message_type, 0) + 1
        
        html.append("<h4>Message Type Distribution</h4>")
        for msg_type, count in msg_type_counts.items():
            html.append(f"<div class='stat-item'>{msg_type.value.title()}: <span>{count}</span></div>")
        
        html.append("</div>")
        
        # Transition statistics
        html.append("<div class='stats-section'>")
        html.append("<h3>Transition Statistics</h3>")
        recent_transitions = data.get_recent_transitions(300.0)
        html.append(f"<div class='stat-item'>Recent Transitions (5min): <span>{len(recent_transitions)}</span></div>")
        
        html.append("</div>")
        html.append("</div>")
        
        return "\n".join(html)
    
    def _get_node_name(self, node_id: str, nodes: Dict[str, TreeNode]) -> str:
        """Get display name for a node."""
        if node_id in nodes:
            return nodes[node_id].name
        return node_id
    
    def _get_css(self) -> str:
        """Get embedded CSS styles."""
        return """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f5f5f5;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        header h1 {
            color: #2c3e50;
            margin-bottom: 10px;
        }
        
        .tabs {
            display: flex;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        .tab-button {
            flex: 1;
            padding: 15px;
            border: none;
            background: white;
            cursor: pointer;
            transition: background 0.3s;
        }
        
        .tab-button:hover {
            background: #f8f9fa;
        }
        
        .tab-button.active {
            background: #3498db;
            color: white;
        }
        
        .tab-content {
            display: none;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .tab-content.active {
            display: block;
        }
        
        /* Tree styles */
        .tree-container {
            font-family: monospace;
        }
        
        .node {
            margin: 5px 0;
            padding: 8px;
            border-left: 3px solid #ddd;
            background: #f9f9f9;
        }
        
        .node-active { border-left-color: #27ae60; }
        .node-inactive { border-left-color: #95a5a6; }
        .node-processing { border-left-color: #f39c12; }
        .node-error { border-left-color: #e74c3c; }
        .node-unknown { border-left-color: #3498db; }
        
        .node-header {
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .node-state::before {
            content: "●";
            margin-right: 8px;
        }
        
        .node-active .node-state::before { color: #27ae60; }
        .node-inactive .node-state::before { color: #95a5a6; }
        .node-processing .node-state::before { color: #f39c12; }
        .node-error .node-state::before { color: #e74c3c; }
        .node-unknown .node-state::before { color: #3498db; }
        
        .node-id {
            color: #666;
            font-size: 0.9em;
        }
        
        .node-metadata {
            font-size: 0.8em;
            color: #666;
            margin-top: 5px;
        }
        
        .metadata-item {
            margin-right: 15px;
        }
        
        .node-children {
            margin-left: 20px;
            margin-top: 10px;
        }
        
        /* Flow styles */
        .flows-container {
            max-height: 600px;
            overflow-y: auto;
        }
        
        .message-type-section {
            margin-bottom: 30px;
        }
        
        .message-type-section h3 {
            color: #2c3e50;
            margin-bottom: 15px;
            padding-bottom: 5px;
            border-bottom: 2px solid #3498db;
        }
        
        .message-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            margin: 5px 0;
            border-radius: 4px;
            background: #f8f9fa;
        }
        
        .status-delivered { border-left: 4px solid #27ae60; }
        .status-pending { border-left: 4px solid #f39c12; }
        .status-failed { border-left: 4px solid #e74c3c; }
        
        .message-flow {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .arrow {
            color: #3498db;
            font-weight: bold;
        }
        
        .message-meta {
            display: flex;
            gap: 15px;
            font-size: 0.9em;
            color: #666;
        }
        
        /* Transition styles */
        .transitions-container {
            max-height: 600px;
            overflow-y: auto;
        }
        
        .transition-item {
            padding: 15px;
            margin: 10px 0;
            border-radius: 4px;
            background: #f8f9fa;
            border-left: 4px solid #3498db;
        }
        
        .transition-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            font-weight: bold;
        }
        
        .transition-flow {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 5px;
        }
        
        .state {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.9em;
            font-weight: bold;
        }
        
        .state-active { background: #27ae60; color: white; }
        .state-inactive { background: #95a5a6; color: white; }
        .state-processing { background: #f39c12; color: white; }
        .state-error { background: #e74c3c; color: white; }
        .state-unknown { background: #3498db; color: white; }
        
        .trigger {
            font-size: 0.9em;
            color: #666;
            font-style: italic;
        }
        
        /* Stats styles */
        .stats-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        
        .stats-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
        }
        
        .stats-section h3 {
            color: #2c3e50;
            margin-bottom: 15px;
            padding-bottom: 5px;
            border-bottom: 2px solid #3498db;
        }
        
        .stats-section h4 {
            color: #34495e;
            margin: 15px 0 10px 0;
        }
        
        .stat-item {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }
        
        .stat-item span {
            font-weight: bold;
            color: #3498db;
        }
    </style>
        """
    
    def _get_javascript(self) -> str:
        """Get embedded JavaScript."""
        return """
    <script>
        function showTab(tabName) {
            // Hide all tab contents
            const contents = document.querySelectorAll('.tab-content');
            contents.forEach(content => content.classList.remove('active'));
            
            // Remove active class from all buttons
            const buttons = document.querySelectorAll('.tab-button');
            buttons.forEach(button => button.classList.remove('active'));
            
            // Show selected tab content
            document.getElementById(tabName).classList.add('active');
            
            // Add active class to clicked button
            event.target.classList.add('active');
        }
        
        // Add click handlers for node expansion (future enhancement)
        document.addEventListener('DOMContentLoaded', function() {
            const nodes = document.querySelectorAll('.node');
            nodes.forEach(node => {
                node.addEventListener('click', function(e) {
                    e.stopPropagation();
                    // Future: toggle node expansion
                });
            });
        });
    </script>
        """


class SVGExporter(BaseExporter):
    """Exports visualization as SVG diagram."""
    
    def __init__(self, width: int = 800, height: int = 600):
        self.width = width
        self.height = height
    
    def export(self, data: VisualizationData, output_path: str) -> bool:
        """Export as SVG diagram."""
        try:
            svg_content = self._generate_svg(data)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(svg_content)
            
            return True
        except Exception as e:
            print(f"Error exporting SVG: {e}")
            return False
    
    def _generate_svg(self, data: VisualizationData) -> str:
        """Generate SVG content."""
        # Calculate node positions using a simple layout algorithm
        positions = self._calculate_positions(data)
        
        svg_elements = []
        svg_elements.append(f'<svg width="{self.width}" height="{self.height}" xmlns="http://www.w3.org/2000/svg">')
        svg_elements.append('<defs>')
        svg_elements.append(self._get_svg_styles())
        svg_elements.append('</defs>')
        
        # Draw connections first (so they appear behind nodes)
        hierarchy = data.get_node_hierarchy()
        for parent_id, children_ids in hierarchy.items():
            if parent_id in positions:
                parent_pos = positions[parent_id]
                for child_id in children_ids:
                    if child_id in positions:
                        child_pos = positions[child_id]
                        svg_elements.append(
                            f'<line x1="{parent_pos[0]}" y1="{parent_pos[1]}" '
                            f'x2="{child_pos[0]}" y2="{child_pos[1]}" '
                            f'class="connection" />'
                        )
        
        # Draw nodes
        for node_id, (x, y) in positions.items():
            if node_id in data.nodes:
                node = data.nodes[node_id]
                svg_elements.append(self._create_node_svg(node, x, y))
        
        svg_elements.append('</svg>')
        return '\n'.join(svg_elements)
    
    def _calculate_positions(self, data: VisualizationData) -> Dict[str, Tuple[float, float]]:
        """Calculate positions for nodes using a simple tree layout."""
        positions = {}
        
        if not data.nodes:
            return positions
        
        # Get root nodes
        root_nodes = data.get_root_nodes()
        hierarchy = data.get_node_hierarchy()
        
        # Simple vertical layout
        y_offset = 50
        x_center = self.width // 2
        
        for i, root in enumerate(root_nodes):
            root_x = x_center + (i - len(root_nodes) // 2) * 200
            self._position_subtree(root, hierarchy, data.nodes, positions, root_x, y_offset, 0)
        
        return positions
    
    def _position_subtree(self, node: TreeNode, hierarchy: Dict[str, List[str]], 
                         all_nodes: Dict[str, TreeNode], positions: Dict[str, Tuple[float, float]], 
                         x: float, y: float, depth: int) -> None:
        """Recursively position a subtree."""
        positions[node.id] = (x, y)
        
        children_ids = hierarchy.get(node.id, [])
        if children_ids:
            child_y = y + 100
            child_spacing = max(100, 400 // (len(children_ids) + 1))
            start_x = x - (len(children_ids) - 1) * child_spacing // 2
            
            for i, child_id in enumerate(children_ids):
                if child_id in all_nodes:
                    child_x = start_x + i * child_spacing
                    child_node = all_nodes[child_id]
                    self._position_subtree(child_node, hierarchy, all_nodes, positions, child_x, child_y, depth + 1)
    
    def _create_node_svg(self, node: TreeNode, x: float, y: float) -> str:
        """Create SVG elements for a node."""
        state_colors = {
            NodeState.ACTIVE: "#27ae60",
            NodeState.INACTIVE: "#95a5a6",
            NodeState.PROCESSING: "#f39c12",
            NodeState.ERROR: "#e74c3c",
            NodeState.UNKNOWN: "#3498db"
        }
        
        color = state_colors.get(node.state, "#3498db")
        
        elements = []
        elements.append(f'<circle cx="{x}" cy="{y}" r="20" fill="{color}" class="node" />')
        elements.append(f'<text x="{x}" y="{y + 35}" text-anchor="middle" class="node-label">{node.name}</text>')
        
        return '\n'.join(elements)
    
    def _get_svg_styles(self) -> str:
        """Get SVG styles."""
        return """
        <style>
            .connection {
                stroke: #bdc3c7;
                stroke-width: 2;
            }
            .node {
                stroke: white;
                stroke-width: 2;
            }
            .node-label {
                font-family: Arial, sans-serif;
                font-size: 12px;
                fill: #2c3e50;
            }
        </style>
        """


class TextExporter(BaseExporter):
    """Exports visualization as plain text report."""
    
    def export(self, data: VisualizationData, output_path: str) -> bool:
        """Export as plain text report."""
        try:
            from .renderer import TreeRenderer, FlowRenderer, StateRenderer
            
            content = []
            content.append("UTILITYFOG FRACTAL TREE VISUALIZATION REPORT")
            content.append("=" * 60)
            content.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            content.append("")
            
            # Tree structure
            tree_renderer = TreeRenderer(width=80, height=50)
            content.append("TREE STRUCTURE")
            content.append("-" * 30)
            content.append(tree_renderer.render(data))
            content.append("")
            
            # Message flows
            flow_renderer = FlowRenderer(width=80, height=50)
            content.append("MESSAGE FLOWS")
            content.append("-" * 30)
            content.append(flow_renderer.render(data))
            content.append("")
            
            # State transitions
            state_renderer = StateRenderer(width=80, height=50)
            content.append("STATE TRANSITIONS")
            content.append("-" * 30)
            content.append(state_renderer.render(data))
            content.append("")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))
            
            return True
        except Exception as e:
            print(f"Error exporting text: {e}")
            return False


class JSONExporter(BaseExporter):
    """Exports visualization data as JSON."""
    
    def export(self, data: VisualizationData, output_path: str) -> bool:
        """Export as JSON data."""
        try:
            json_data = {
                "timestamp": time.time(),
                "nodes": {
                    node_id: {
                        "id": node.id,
                        "name": node.name,
                        "state": node.state.value,
                        "parent_id": node.parent_id,
                        "children": node.children,
                        "position": node.position,
                        "metadata": node.metadata,
                        "last_updated": node.last_updated
                    }
                    for node_id, node in data.nodes.items()
                },
                "messages": [
                    {
                        "id": msg.id,
                        "source_id": msg.source_id,
                        "target_id": msg.target_id,
                        "message_type": msg.message_type.value,
                        "content": str(msg.content),
                        "timestamp": msg.timestamp,
                        "status": msg.status,
                        "metadata": msg.metadata
                    }
                    for msg in data.messages
                ],
                "transitions": [
                    {
                        "node_id": trans.node_id,
                        "from_state": trans.from_state.value,
                        "to_state": trans.to_state.value,
                        "timestamp": trans.timestamp,
                        "trigger": trans.trigger,
                        "metadata": trans.metadata
                    }
                    for trans in data.transitions
                ],
                "metadata": data.metadata
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2)
            
            return True
        except Exception as e:
            print(f"Error exporting JSON: {e}")
            return False
