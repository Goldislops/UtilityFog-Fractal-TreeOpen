
"""
Comprehensive tests for CLI visualization system.
"""

import json
import pytest
import time

from utilityfog_frontend.cli_viz import (
    TreeRenderer, FlowRenderer, StateRenderer, InteractiveRenderer,
    HTMLExporter, SVGExporter, TextExporter, JSONExporter,
    VisualizationCLI, TreeNode, MessageFlow, StateTransition,
    VisualizationData, NodeState, MessageType
)


class TestModels:
    """Test data models."""
    
    def test_tree_node_creation(self):
        """Test TreeNode creation and methods."""
        node = TreeNode("node1", "Test Node", NodeState.ACTIVE)
        
        assert node.id == "node1"
        assert node.name == "Test Node"
        assert node.state == NodeState.ACTIVE
        assert node.children == []
        
        # Test child management
        node.add_child("child1")
        assert "child1" in node.children
        
        node.add_child("child1")  # Should not duplicate
        assert len(node.children) == 1
        
        node.remove_child("child1")
        assert "child1" not in node.children
    
    def test_message_flow_creation(self):
        """Test MessageFlow creation and status updates."""
        message = MessageFlow("msg1", "node1", "node2", MessageType.DATA, "test content")
        
        assert message.id == "msg1"
        assert message.source_id == "node1"
        assert message.target_id == "node2"
        assert message.message_type == MessageType.DATA
        assert message.status == "pending"
        
        # Test status updates
        message.mark_delivered()
        assert message.status == "delivered"
        assert "delivered_at" in message.metadata
        
        message.mark_failed("Connection timeout")
        assert message.status == "failed"
        assert message.metadata["error"] == "Connection timeout"
    
    def test_state_transition_creation(self):
        """Test StateTransition creation."""
        transition = StateTransition("node1", NodeState.INACTIVE, NodeState.ACTIVE, trigger="heartbeat")
        
        assert transition.node_id == "node1"
        assert transition.from_state == NodeState.INACTIVE
        assert transition.to_state == NodeState.ACTIVE
        assert transition.trigger == "heartbeat"
        
        # Test duration calculation
        duration = transition.duration_since()
        assert duration >= 0
    
    def test_visualization_data_management(self):
        """Test VisualizationData container."""
        data = VisualizationData()
        
        # Test node management
        node1 = TreeNode("node1", "Node 1", NodeState.ACTIVE)
        node2 = TreeNode("node2", "Node 2", NodeState.INACTIVE, parent_id="node1")
        
        data.add_node(node1)
        data.add_node(node2)
        
        assert len(data.nodes) == 2
        assert "node1" in data.nodes
        assert "node2" in data.nodes
        
        # Test hierarchy
        hierarchy = data.get_node_hierarchy()
        assert "node1" in hierarchy
        assert "node2" in hierarchy["node1"]
        
        # Test root nodes
        root_nodes = data.get_root_nodes()
        assert len(root_nodes) == 1
        assert root_nodes[0].id == "node1"
        
        # Test active nodes
        active_nodes = data.get_active_nodes()
        assert len(active_nodes) == 1
        assert active_nodes[0].id == "node1"


class TestRenderers:
    """Test rendering engines."""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample visualization data."""
        data = VisualizationData()
        
        # Add nodes
        root = TreeNode("root", "Root Node", NodeState.ACTIVE)
        child1 = TreeNode("child1", "Child 1", NodeState.PROCESSING, parent_id="root")
        child2 = TreeNode("child2", "Child 2", NodeState.INACTIVE, parent_id="root")
        
        root.add_child("child1")
        root.add_child("child2")
        
        data.add_node(root)
        data.add_node(child1)
        data.add_node(child2)
        
        # Add messages
        msg1 = MessageFlow("msg1", "root", "child1", MessageType.COORDINATION, "test")
        msg2 = MessageFlow("msg2", "child1", "child2", MessageType.DATA, "data")
        msg1.mark_delivered()
        
        data.add_message(msg1)
        data.add_message(msg2)
        
        # Add transitions
        trans1 = StateTransition("child1", NodeState.INACTIVE, NodeState.PROCESSING)
        data.add_transition(trans1)
        
        return data
    
    def test_tree_renderer(self, sample_data):
        """Test tree structure rendering."""
        renderer = TreeRenderer(width=80, height=24, show_ids=True)
        output = renderer.render(sample_data)
        
        assert "FRACTAL TREE VISUALIZATION" in output
        assert "Root Node" in output
        assert "Child 1" in output
        assert "Child 2" in output
        assert "Total Nodes: 3" in output
        assert "Active Nodes: 1" in output
    
    def test_flow_renderer(self, sample_data):
        """Test message flow rendering."""
        renderer = FlowRenderer(width=80, height=24, time_window=3600.0)
        output = renderer.render(sample_data)
        
        assert "MESSAGE FLOW VISUALIZATION" in output
        assert "COORDINATION MESSAGES" in output
        assert "DATA MESSAGES" in output
        assert "Root Node → Child 1" in output
        assert "Child 1 → Child 2" in output
    
    def test_state_renderer(self, sample_data):
        """Test state transition rendering."""
        renderer = StateRenderer(width=80, height=24, time_window=3600.0)
        output = renderer.render(sample_data)
        
        assert "STATE TRANSITION VISUALIZATION" in output
        assert "RECENT TRANSITIONS" in output
        assert "Child 1" in output
        assert "inactive → processing" in output
    
    def test_interactive_renderer(self, sample_data):
        """Test interactive renderer."""
        renderer = InteractiveRenderer(width=80, height=24)
        output = renderer.render(sample_data)
        
        assert "INTERACTIVE VISUALIZATION" in output
        assert "Commands:" in output
        assert "[t]ree, [f]low, [s]tate" in output
        
        # Test view switching
        assert renderer.switch_view("flow") == True
        assert renderer.current_view == "flow"
        
        assert renderer.switch_view("invalid") == False
        assert renderer.current_view == "flow"  # Should remain unchanged


class TestExporters:
    """Test export functionality."""
    
    @pytest.fixture
    def sample_data(self):
        """Create sample visualization data."""
        data = VisualizationData()
        
        node = TreeNode("node1", "Test Node", NodeState.ACTIVE)
        node.metadata = {"cpu": 50, "memory": 1024}
        data.add_node(node)
        
        message = MessageFlow("msg1", "node1", "node2", MessageType.DATA, "test")
        message.mark_delivered()
        data.add_message(message)
        
        transition = StateTransition("node1", NodeState.INACTIVE, NodeState.ACTIVE)
        data.add_transition(transition)
        
        return data
    
    def test_html_exporter(self, sample_data, tmp_path):
        """Test HTML export functionality."""
        exporter = HTMLExporter()
        output_file = tmp_path / "test.html"
        
        success = exporter.export(sample_data, str(output_file))
        assert success
        assert output_file.exists()
        
        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content
        assert "UtilityFog Fractal Tree Visualization" in content
        assert "Test Node" in content
        assert "tab-button" in content
    
    def test_svg_exporter(self, sample_data, tmp_path):
        """Test SVG export functionality."""
        exporter = SVGExporter(width=400, height=300)
        output_file = tmp_path / "test.svg"
        
        success = exporter.export(sample_data, str(output_file))
        assert success
        assert output_file.exists()
        
        content = output_file.read_text()
        assert "<svg" in content
        assert "width=\"400\"" in content
        assert "height=\"300\"" in content
        assert "circle" in content
    
    def test_text_exporter(self, sample_data, tmp_path):
        """Test text export functionality."""
        exporter = TextExporter()
        output_file = tmp_path / "test.txt"
        
        success = exporter.export(sample_data, str(output_file))
        assert success
        assert output_file.exists()
        
        content = output_file.read_text()
        assert "UTILITYFOG FRACTAL TREE VISUALIZATION REPORT" in content
        assert "TREE STRUCTURE" in content
        assert "MESSAGE FLOWS" in content
        assert "STATE TRANSITIONS" in content
    
    def test_json_exporter(self, sample_data, tmp_path):
        """Test JSON export functionality."""
        exporter = JSONExporter()
        output_file = tmp_path / "test.json"
        
        success = exporter.export(sample_data, str(output_file))
        assert success
        assert output_file.exists()
        
        with open(output_file) as f:
            data = json.load(f)
        
        assert "timestamp" in data
        assert "nodes" in data
        assert "messages" in data
        assert "transitions" in data
        assert "node1" in data["nodes"]
        assert data["nodes"]["node1"]["name"] == "Test Node"


class TestCLI:
    """Test command-line interface."""
    
    @pytest.fixture
    def cli(self):
        """Create CLI instance."""
        return VisualizationCLI()
    
    @pytest.fixture
    def sample_json_file(self, tmp_path):
        """Create sample JSON data file."""
        data = {
            "timestamp": time.time(),
            "nodes": {
                "node1": {
                    "id": "node1",
                    "name": "Test Node",
                    "state": "active",
                    "parent_id": None,
                    "children": ["node2"],
                    "position": [100, 100],
                    "metadata": {"cpu": 50},
                    "last_updated": time.time()
                },
                "node2": {
                    "id": "node2", 
                    "name": "Child Node",
                    "state": "inactive",
                    "parent_id": "node1",
                    "children": [],
                    "position": [200, 200],
                    "metadata": {},
                    "last_updated": time.time()
                }
            },
            "messages": [
                {
                    "id": "msg1",
                    "source_id": "node1",
                    "target_id": "node2",
                    "message_type": "data",
                    "content": "test message",
                    "timestamp": time.time(),
                    "status": "delivered",
                    "metadata": {}
                }
            ],
            "transitions": [
                {
                    "node_id": "node2",
                    "from_state": "unknown",
                    "to_state": "inactive",
                    "timestamp": time.time(),
                    "trigger": "initialization",
                    "metadata": {}
                }
            ],
            "metadata": {}
        }
        
        json_file = tmp_path / "sample.json"
        with open(json_file, 'w') as f:
            json.dump(data, f)
        
        return str(json_file)
    
    def test_load_data(self, cli, sample_json_file):
        """Test data loading from JSON file."""
        success = cli.load_data(sample_json_file)
        assert success
        
        assert len(cli.data.nodes) == 2
        assert "node1" in cli.data.nodes
        assert "node2" in cli.data.nodes
        assert len(cli.data.messages) == 1
        assert len(cli.data.transitions) == 1
    
    def test_tree_command(self, cli, sample_json_file, capsys):
        """Test tree command."""
        args = type('Args', (), {
            'input': sample_json_file,
            'width': 80,
            'height': 24,
            'color_scheme': 'default',
            'show_ids': False
        })()
        
        result = cli.cmd_tree(args)
        assert result == 0
        
        captured = capsys.readouterr()
        assert "FRACTAL TREE VISUALIZATION" in captured.out
        assert "Test Node" in captured.out
    
    def test_flow_command(self, cli, sample_json_file, capsys):
        """Test flow command."""
        args = type('Args', (), {
            'input': sample_json_file,
            'width': 80,
            'height': 24,
            'color_scheme': 'default',
            'time_window': 3600.0
        })()
        
        result = cli.cmd_flow(args)
        assert result == 0
        
        captured = capsys.readouterr()
        assert "MESSAGE FLOW VISUALIZATION" in captured.out
    
    def test_export_command(self, cli, sample_json_file, tmp_path):
        """Test export command."""
        output_file = tmp_path / "export.html"
        
        args = type('Args', (), {
            'input': sample_json_file,
            'output': str(output_file),
            'format': 'html',
            'width': 800,
            'height': 600
        })()
        
        result = cli.cmd_export(args)
        assert result == 0
        assert output_file.exists()
    
    def test_demo_command(self, cli, tmp_path):
        """Test demo data generation."""
        output_file = tmp_path / "demo.json"
        
        args = type('Args', (), {
            'nodes': 5,
            'messages': 10,
            'transitions': 8,
            'output': str(output_file)
        })()
        
        result = cli.cmd_demo(args)
        assert result == 0
        assert output_file.exists()
        
        # Verify generated data
        with open(output_file) as f:
            data = json.load(f)
        
        assert len(data['nodes']) == 5
        assert len(data['messages']) == 10
        assert len(data['transitions']) == 8
    
    def test_parser_creation(self, cli):
        """Test argument parser creation."""
        parser = cli.create_parser()
        
        # Test tree command parsing
        args = parser.parse_args(['tree', '--input', 'test.json', '--width', '100'])
        assert args.command == 'tree'
        assert args.input == 'test.json'
        assert args.width == 100
        
        # Test export command parsing
        args = parser.parse_args(['export', '--input', 'test.json', '--output', 'out.html', '--format', 'svg'])
        assert args.command == 'export'
        assert args.format == 'svg'


class TestIntegration:
    """Integration tests for complete visualization workflow."""
    
    @pytest.mark.asyncio
    async def test_full_visualization_workflow(self, tmp_path):
        """Test complete workflow from data generation to export."""
        cli = VisualizationCLI()
        
        # Generate demo data
        demo_file = tmp_path / "demo.json"
        demo_args = type('Args', (), {
            'nodes': 8,
            'messages': 15,
            'transitions': 10,
            'output': str(demo_file)
        })()
        
        result = cli.cmd_demo(demo_args)
        assert result == 0
        
        # Load and verify data
        success = cli.load_data(str(demo_file))
        assert success
        assert len(cli.data.nodes) == 8
        
        # Test all renderers
        tree_renderer = TreeRenderer()
        tree_output = tree_renderer.render(cli.data)
        assert "FRACTAL TREE VISUALIZATION" in tree_output
        
        flow_renderer = FlowRenderer()
        flow_output = flow_renderer.render(cli.data)
        assert "MESSAGE FLOW VISUALIZATION" in flow_output
        
        state_renderer = StateRenderer()
        state_output = state_renderer.render(cli.data)
        assert "STATE TRANSITION VISUALIZATION" in state_output
        
        # Test all exporters
        html_file = tmp_path / "export.html"
        html_exporter = HTMLExporter()
        assert html_exporter.export(cli.data, str(html_file))
        assert html_file.exists()
        
        svg_file = tmp_path / "export.svg"
        svg_exporter = SVGExporter()
        assert svg_exporter.export(cli.data, str(svg_file))
        assert svg_file.exists()
        
        text_file = tmp_path / "export.txt"
        text_exporter = TextExporter()
        assert text_exporter.export(cli.data, str(text_file))
        assert text_file.exists()
        
        json_file = tmp_path / "export.json"
        json_exporter = JSONExporter()
        assert json_exporter.export(cli.data, str(json_file))
        assert json_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
