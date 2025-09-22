
"""
Command-line interface for visualization system.
"""

import argparse
import asyncio
import json
import sys
import time
from typing import Dict, Any

from .models import (
    VisualizationData, TreeNode, MessageFlow, StateTransition,
    NodeState, MessageType
)
from .renderer import TreeRenderer, FlowRenderer, StateRenderer, InteractiveRenderer
from .exporters import HTMLExporter, SVGExporter, TextExporter, JSONExporter


class VisualizationCLI:
    """Command-line interface for fractal tree visualization."""
    
    def __init__(self):
        self.data = VisualizationData()
        self.interactive_renderer = InteractiveRenderer()
        self.running = False
    
    def create_parser(self) -> argparse.ArgumentParser:
        """Create command-line argument parser."""
        parser = argparse.ArgumentParser(
            description="UtilityFog Fractal Tree Visualization CLI",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Show tree structure
  python -m utilityfog_frontend.cli_viz tree --input data.json
  
  # Show message flows
  python -m utilityfog_frontend.cli_viz flow --input data.json --time-window 60
  
  # Show state transitions
  python -m utilityfog_frontend.cli_viz state --input data.json
  
  # Interactive mode
  python -m utilityfog_frontend.cli_viz interactive --input data.json
  
  # Export HTML report
  python -m utilityfog_frontend.cli_viz export --input data.json --output report.html --format html
  
  # Generate sample data
  python -m utilityfog_frontend.cli_viz demo --nodes 10 --output sample.json
            """
        )
        
        subparsers = parser.add_subparsers(dest='command', help='Available commands')
        
        # Tree command
        tree_parser = subparsers.add_parser('tree', help='Display tree structure')
        tree_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
        tree_parser.add_argument('--width', '-w', type=int, default=80, help='Display width')
        tree_parser.add_argument('--height', '-h', type=int, default=24, help='Display height')
        tree_parser.add_argument('--color-scheme', choices=['default', 'dark', 'colorblind'], 
                               default='default', help='Color scheme')
        tree_parser.add_argument('--show-ids', action='store_true', help='Show node IDs')
        
        # Flow command
        flow_parser = subparsers.add_parser('flow', help='Display message flows')
        flow_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
        flow_parser.add_argument('--width', '-w', type=int, default=80, help='Display width')
        flow_parser.add_argument('--height', '-h', type=int, default=24, help='Display height')
        flow_parser.add_argument('--time-window', '-t', type=float, default=60.0, 
                               help='Time window in seconds')
        flow_parser.add_argument('--color-scheme', choices=['default', 'dark', 'colorblind'], 
                               default='default', help='Color scheme')
        
        # State command
        state_parser = subparsers.add_parser('state', help='Display state transitions')
        state_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
        state_parser.add_argument('--width', '-w', type=int, default=80, help='Display width')
        state_parser.add_argument('--height', '-h', type=int, default=24, help='Display height')
        state_parser.add_argument('--time-window', '-t', type=float, default=300.0, 
                               help='Time window in seconds')
        state_parser.add_argument('--color-scheme', choices=['default', 'dark', 'colorblind'], 
                               default='default', help='Color scheme')
        
        # Interactive command
        interactive_parser = subparsers.add_parser('interactive', help='Interactive visualization')
        interactive_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
        interactive_parser.add_argument('--width', '-w', type=int, default=80, help='Display width')
        interactive_parser.add_argument('--height', '-h', type=int, default=24, help='Display height')
        interactive_parser.add_argument('--refresh-rate', '-r', type=float, default=1.0, 
                                      help='Refresh rate in seconds')
        interactive_parser.add_argument('--color-scheme', choices=['default', 'dark', 'colorblind'], 
                                      default='default', help='Color scheme')
        
        # Export command
        export_parser = subparsers.add_parser('export', help='Export visualization')
        export_parser.add_argument('--input', '-i', required=True, help='Input JSON file')
        export_parser.add_argument('--output', '-o', required=True, help='Output file')
        export_parser.add_argument('--format', '-f', choices=['html', 'svg', 'text', 'json'], 
                                 default='html', help='Export format')
        export_parser.add_argument('--width', type=int, default=800, help='SVG width')
        export_parser.add_argument('--height', type=int, default=600, help='SVG height')
        
        # Demo command
        demo_parser = subparsers.add_parser('demo', help='Generate demo data')
        demo_parser.add_argument('--nodes', '-n', type=int, default=10, help='Number of nodes')
        demo_parser.add_argument('--messages', '-m', type=int, default=20, help='Number of messages')
        demo_parser.add_argument('--transitions', '-t', type=int, default=15, help='Number of transitions')
        demo_parser.add_argument('--output', '-o', required=True, help='Output JSON file')
        
        return parser
    
    def load_data(self, input_file: str) -> bool:
        """Load visualization data from JSON file."""
        try:
            with open(input_file, 'r') as f:
                json_data = json.load(f)
            
            # Load nodes
            for node_id, node_data in json_data.get('nodes', {}).items():
                node = TreeNode(
                    id=node_data['id'],
                    name=node_data['name'],
                    state=NodeState(node_data['state']),
                    parent_id=node_data.get('parent_id'),
                    children=node_data.get('children', []),
                    position=tuple(node_data.get('position', [0.0, 0.0])),
                    metadata=node_data.get('metadata', {}),
                    last_updated=node_data.get('last_updated', time.time())
                )
                self.data.add_node(node)
            
            # Load messages
            for msg_data in json_data.get('messages', []):
                message = MessageFlow(
                    id=msg_data['id'],
                    source_id=msg_data['source_id'],
                    target_id=msg_data['target_id'],
                    message_type=MessageType(msg_data['message_type']),
                    content=msg_data['content'],
                    timestamp=msg_data['timestamp'],
                    status=msg_data['status'],
                    metadata=msg_data.get('metadata', {})
                )
                self.data.add_message(message)
            
            # Load transitions
            for trans_data in json_data.get('transitions', []):
                transition = StateTransition(
                    node_id=trans_data['node_id'],
                    from_state=NodeState(trans_data['from_state']),
                    to_state=NodeState(trans_data['to_state']),
                    timestamp=trans_data['timestamp'],
                    trigger=trans_data.get('trigger', 'unknown'),
                    metadata=trans_data.get('metadata', {})
                )
                self.data.add_transition(transition)
            
            # Load metadata
            self.data.metadata = json_data.get('metadata', {})
            
            return True
        except Exception as e:
            print(f"Error loading data: {e}")
            return False
    
    def cmd_tree(self, args) -> int:
        """Handle tree command."""
        if not self.load_data(args.input):
            return 1
        
        renderer = TreeRenderer(
            width=args.width,
            height=args.height,
            color_scheme=args.color_scheme,
            show_ids=args.show_ids
        )
        
        output = renderer.render(self.data)
        print(output)
        return 0
    
    def cmd_flow(self, args) -> int:
        """Handle flow command."""
        if not self.load_data(args.input):
            return 1
        
        renderer = FlowRenderer(
            width=args.width,
            height=args.height,
            color_scheme=args.color_scheme,
            time_window=args.time_window
        )
        
        output = renderer.render(self.data)
        print(output)
        return 0
    
    def cmd_state(self, args) -> int:
        """Handle state command."""
        if not self.load_data(args.input):
            return 1
        
        renderer = StateRenderer(
            width=args.width,
            height=args.height,
            color_scheme=args.color_scheme,
            time_window=args.time_window
        )
        
        output = renderer.render(self.data)
        print(output)
        return 0
    
    async def cmd_interactive(self, args) -> int:
        """Handle interactive command."""
        if not self.load_data(args.input):
            return 1
        
        self.interactive_renderer = InteractiveRenderer(
            width=args.width,
            height=args.height,
            color_scheme=args.color_scheme,
            refresh_rate=args.refresh_rate
        )
        
        self.running = True
        
        try:
            import termios
            import tty
            import select
            
            # Save terminal settings
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
            
            while self.running:
                # Clear screen and render
                print('\033[2J\033[H', end='')  # Clear screen and move cursor to top
                output = self.interactive_renderer.render(self.data)
                print(output)
                
                # Check for input
                if select.select([sys.stdin], [], [], args.refresh_rate)[0]:
                    key = sys.stdin.read(1)
                    
                    if key.lower() == 'q':
                        self.running = False
                    elif key.lower() == 't':
                        self.interactive_renderer.switch_view('tree')
                    elif key.lower() == 'f':
                        self.interactive_renderer.switch_view('flow')
                    elif key.lower() == 's':
                        self.interactive_renderer.switch_view('state')
                    elif key.lower() == 'r':
                        # Reload data
                        self.load_data(args.input)
                
                await asyncio.sleep(0.1)  # Small delay to prevent excessive CPU usage
        
        except KeyboardInterrupt:
            pass
        except ImportError:
            print("Interactive mode requires Unix-like system with termios support")
            return 1
        finally:
            try:
                # Restore terminal settings
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            except:
                pass
        
        return 0
    
    def cmd_export(self, args) -> int:
        """Handle export command."""
        if not self.load_data(args.input):
            return 1
        
        exporters = {
            'html': HTMLExporter(),
            'svg': SVGExporter(args.width, args.height),
            'text': TextExporter(),
            'json': JSONExporter()
        }
        
        exporter = exporters[args.format]
        success = exporter.export(self.data, args.output)
        
        if success:
            print(f"Exported visualization to {args.output}")
            return 0
        else:
            print("Failed to export visualization")
            return 1
    
    def cmd_demo(self, args) -> int:
        """Handle demo command."""
        
        # Generate demo data
        demo_data = self._generate_demo_data(args.nodes, args.messages, args.transitions)
        
        try:
            with open(args.output, 'w') as f:
                json.dump(demo_data, f, indent=2)
            
            print(f"Generated demo data with {args.nodes} nodes, {args.messages} messages, {args.transitions} transitions")
            print(f"Saved to {args.output}")
            return 0
        except Exception as e:
            print(f"Error saving demo data: {e}")
            return 1
    
    def _generate_demo_data(self, num_nodes: int, num_messages: int, num_transitions: int) -> Dict[str, Any]:
        """Generate demo visualization data."""
        import random
        
        nodes = {}
        messages = []
        transitions = []
        
        # Generate nodes
        states = list(NodeState)
        msg_types = list(MessageType)
        
        for i in range(num_nodes):
            node_id = f"node_{i:03d}"
            parent_id = None
            
            # Create hierarchy - some nodes have parents
            if i > 0 and random.random() < 0.7:
                parent_id = f"node_{random.randint(0, i-1):03d}"
                if parent_id in nodes:
                    nodes[parent_id]['children'].append(node_id)
            
            nodes[node_id] = {
                'id': node_id,
                'name': f"Node {i}",
                'state': random.choice(states).value,
                'parent_id': parent_id,
                'children': [],
                'position': [random.uniform(0, 800), random.uniform(0, 600)],
                'metadata': {
                    'cpu_usage': random.uniform(0, 100),
                    'memory_mb': random.randint(100, 1000)
                },
                'last_updated': time.time() - random.uniform(0, 3600)
            }
        
        # Generate messages
        node_ids = list(nodes.keys())
        for i in range(num_messages):
            source_id = random.choice(node_ids)
            target_id = random.choice([nid for nid in node_ids if nid != source_id])
            
            messages.append({
                'id': f"msg_{i:03d}",
                'source_id': source_id,
                'target_id': target_id,
                'message_type': random.choice(msg_types).value,
                'content': f"Message content {i}",
                'timestamp': time.time() - random.uniform(0, 300),
                'status': random.choice(['pending', 'delivered', 'failed']),
                'metadata': {
                    'size_bytes': random.randint(100, 10000)
                }
            })
        
        # Generate transitions
        for i in range(num_transitions):
            node_id = random.choice(node_ids)
            from_state = random.choice(states)
            to_state = random.choice([s for s in states if s != from_state])
            
            transitions.append({
                'node_id': node_id,
                'from_state': from_state.value,
                'to_state': to_state.value,
                'timestamp': time.time() - random.uniform(0, 600),
                'trigger': random.choice(['heartbeat', 'error', 'user_action', 'timeout']),
                'metadata': {
                    'duration_ms': random.randint(10, 1000)
                }
            })
        
        return {
            'timestamp': time.time(),
            'nodes': nodes,
            'messages': messages,
            'transitions': transitions,
            'metadata': {
                'generated': True,
                'generator_version': '1.0'
            }
        }
    
    async def run(self, args=None) -> int:
        """Run the CLI with given arguments."""
        parser = self.create_parser()
        parsed_args = parser.parse_args(args)
        
        if not parsed_args.command:
            parser.print_help()
            return 1
        
        # Dispatch to command handlers
        if parsed_args.command == 'tree':
            return self.cmd_tree(parsed_args)
        elif parsed_args.command == 'flow':
            return self.cmd_flow(parsed_args)
        elif parsed_args.command == 'state':
            return self.cmd_state(parsed_args)
        elif parsed_args.command == 'interactive':
            return await self.cmd_interactive(parsed_args)
        elif parsed_args.command == 'export':
            return self.cmd_export(parsed_args)
        elif parsed_args.command == 'demo':
            return self.cmd_demo(parsed_args)
        else:
            parser.print_help()
            return 1


def main():
    """Main entry point for CLI."""
    cli = VisualizationCLI()
    
    # Check if we need async (interactive mode)
    if len(sys.argv) > 1 and sys.argv[1] == 'interactive':
        return asyncio.run(cli.run())
    else:
        return asyncio.run(cli.run())


if __name__ == '__main__':
    sys.exit(main())
