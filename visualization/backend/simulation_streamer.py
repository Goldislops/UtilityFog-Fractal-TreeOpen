"""
Real-time Simulation Streaming Engine

Integrates with the testing framework to provide live simulation data
streaming for the 3D visualization frontend.
"""

import asyncio
import time
import json
from typing import Dict, List, Any, Callable, Optional
from dataclasses import asdict

# Import our existing testing framework
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from testing_framework.simulation_runner import SimulationRunner
from testing_framework.test_runner import TestConfiguration
from testing_framework.loggers import QuantumMyelinLogger, SimulationLogger

from .data_models import (
    SimulationConfig, NetworkUpdate, AgentUpdate,
    MemeUpdate, EntanglementEvent, SimulationState
)


class SimulationStreamer:
    """Streams real-time simulation data for visualization."""
    
    def __init__(self, config: SimulationConfig, broadcast_callback: Callable):
        """Initialize the simulation streamer."""
        self.config = config
        self.broadcast_callback = broadcast_callback
        
        # Convert visualization config to test configuration
        self.test_config = TestConfiguration(
            test_name="live_visualization",
            num_agents=config.num_agents,
            num_generations=config.num_generations,
            simulation_steps=config.max_steps,
            mutation_rate=config.mutation_rate,
            crossover_rate=config.crossover_rate,
            enable_quantum_myelin=config.enable_quantum_myelin,
            network_depth=config.network_depth,
            branching_factor=config.branching_factor,
            initial_memes_per_agent=config.initial_memes_per_agent
        )
        
        # Initialize simulation components
        self.simulation_runner = None
        self.quantum_logger = QuantumMyelinLogger()
        self.simulation_logger = SimulationLogger()
        
        # Streaming state
        self.current_step = 0
        self.is_running = False
        self.start_time = 0
        
        # Data for client updates
        self.agent_positions = {}
        self.network_structure = {}
        self.active_entanglements = []
        self.meme_timeline = []
        
        print(f"🔧 SimulationStreamer initialized for {config.num_agents} agents")
    
    async def run_streaming_simulation(self):
        """Run simulation with real-time data streaming."""
        print("⚡ Starting streaming simulation")
        self.is_running = True
        self.start_time = time.time()
        
        try:
            # Initialize simulation
            await self._initialize_simulation()
            
            # Stream initial state
            await self._broadcast_initial_state()
            
            # Main simulation loop with streaming
            for step in range(self.config.max_steps):
                if not self.is_running:
                    break
                
                self.current_step = step
                
                # Run simulation step
                step_data = await self._run_simulation_step()
                
                # Stream updates to clients
                await self._broadcast_step_update(step_data)
                
                # Control simulation speed for visualization
                await asyncio.sleep(self.config.step_delay)
            
            # Send completion notification
            await self._broadcast_simulation_complete()
            
        except asyncio.CancelledError:
            print("⏹️  Simulation cancelled")
            raise
        except Exception as e:
            print(f"❌ Simulation error: {e}")
            await self._broadcast_error(str(e))
        finally:
            self.is_running = False
    
    async def _initialize_simulation(self):
        """Initialize simulation components."""
        print("🏗️  Initializing streaming simulation")
        
        # Create simulation runner
        self.simulation_runner = SimulationRunner(
            config=self.test_config,
            quantum_logger=self.quantum_logger,
            simulation_logger=self.simulation_logger,
            output_dir="visualization_temp"
        )
        
        # Initialize simulation components
        await asyncio.get_event_loop().run_in_executor(
            None, self.simulation_runner._initialize_simulation
        )
        
        # Build initial network structure and positions
        self._build_network_structure()
        self._generate_agent_positions()
        
        print(f"✅ Simulation initialized with {len(self.simulation_runner.agents)} agents")
    
    def _build_network_structure(self):
        """Build network structure for visualization."""
        if not self.simulation_runner.network:
            return
        
        # Extract network topology
        nodes = []
        edges = []
        
        for agent in self.simulation_runner.agents:
            node_data = {
                "id": agent.agent_id,
                "role": agent.role.value if hasattr(agent.role, 'value') else str(agent.role),
                "capabilities": agent.capabilities.__dict__ if hasattr(agent, 'capabilities') else {},
                "energy": agent.energy_level,
                "health": agent.health,
                "active_memes": len(getattr(agent, 'active_memes', {}))
            }
            nodes.append(node_data)
        
        # Build edges from network structure
        network_stats = self.simulation_runner.network.get_network_stats()
        
        # For now, create a simple hierarchy based on agent IDs
        # This can be enhanced with actual network topology later
        root_agent = self.simulation_runner.agents[0]
        for i, agent in enumerate(self.simulation_runner.agents[1:], 1):
            parent_id = root_agent.agent_id if i < 4 else f"agent_{(i-1)//3}"
            edges.append({
                "source": parent_id,
                "target": agent.agent_id,
                "type": "network_connection"
            })
        
        self.network_structure = {
            "nodes": nodes,
            "edges": edges,
            "stats": network_stats
        }
    
    def _generate_agent_positions(self):
        """Generate 3D positions for agents in fractal pattern."""
        import math
        
        positions = {}
        num_agents = len(self.simulation_runner.agents)
        
        if num_agents == 0:
            return
        
        # Place root agent at center
        root_agent = self.simulation_runner.agents[0]
        positions[root_agent.agent_id] = {"x": 0, "y": 0, "z": 0}
        
        # Generate fractal positions for other agents
        for i, agent in enumerate(self.simulation_runner.agents[1:], 1):
            # Create fractal spiral pattern
            angle = (i * 2.4) % (2 * math.pi)  # Golden angle approximation
            level = int(math.log(i + 1, 3)) + 1  # Fractal level
            radius = level * 50  # Distance from center
            
            # 3D spiral with fractal depth
            x = radius * math.cos(angle) * math.cos(i * 0.5)
            y = radius * math.sin(angle) * math.cos(i * 0.5)
            z = radius * math.sin(i * 0.5) * 0.3  # Flatten Z slightly
            
            positions[agent.agent_id] = {"x": x, "y": y, "z": z}
        
        self.agent_positions = positions
    
    async def _run_simulation_step(self) -> Dict[str, Any]:
        """Run single simulation step and collect data."""
        step_start_time = time.time()
        
        # Clear previous step data
        step_entanglements = []
        step_meme_events = []
        agent_updates = []
        
        try:
            # Run actual simulation step (in executor to avoid blocking)
            await asyncio.get_event_loop().run_in_executor(
                None, self._execute_simulation_step
            )
            
            # Collect step data
            step_entanglements = self._get_recent_entanglements()
            step_meme_events = self._get_recent_meme_events()
            agent_updates = self._get_agent_updates()
            
        except Exception as e:
            print(f"⚠️  Error in simulation step {self.current_step}: {e}")
        
        step_duration = time.time() - step_start_time
        
        return {
            "step": self.current_step,
            "timestamp": time.time(),
            "duration": step_duration,
            "entanglements": step_entanglements,
            "meme_events": step_meme_events,
            "agent_updates": agent_updates,
            "network_stats": self.simulation_runner.network.get_network_stats() if self.simulation_runner.network else {}
        }
    
    def _execute_simulation_step(self):
        """Execute single simulation step (runs in thread executor)."""
        if not self.simulation_runner:
            return
        
        dt = 1.0
        environment_context = {
            "step": self.current_step,
            "total_agents": len(self.simulation_runner.agents),
            "visualization_mode": True
        }
        
        # Update agents
        for agent in self.simulation_runner.agents:
            try:
                agent.update(dt, environment_context)
            except Exception as e:
                print(f"Agent {agent.agent_id} update failed: {e}")
        
        # Process quantum myelin interactions
        if self.config.enable_quantum_myelin:
            self.simulation_runner._process_quantum_myelin_interactions()
        
        # Process meme propagation
        self.simulation_runner._process_meme_propagation()
    
    def _get_recent_entanglements(self) -> List[Dict[str, Any]]:
        """Get entanglement events from the current step."""
        entanglements = []
        
        # Get recent entanglement events (last few seconds)
        recent_events = [
            event for event in self.quantum_logger.entanglement_events
            if time.time() - event.get("timestamp", 0) < 2.0
        ]
        
        for event in recent_events[-10:]:  # Limit to last 10 for performance
            entanglements.append({
                "source": event["agent_a"],
                "target": event["agent_b"],
                "strength": event["entanglement_strength"],
                "timestamp": event["timestamp"],
                "data": event.get("additional_data", {})
            })
        
        return entanglements
    
    def _get_recent_meme_events(self) -> List[Dict[str, Any]]:
        """Get meme propagation events from the current step."""
        meme_events = []
        
        # Get recent meme events
        recent_infections = [
            event for event in self.quantum_logger.meme_infection_events
            if time.time() - event.get("timestamp", 0) < 2.0
        ]
        
        recent_propagations = [
            event for event in self.quantum_logger.meme_propagation_events
            if time.time() - event.get("timestamp", 0) < 2.0
        ]
        
        for event in recent_infections[-5:]:
            meme_events.append({
                "type": "infection",
                "agent_id": event["agent_id"],
                "meme_id": event["meme_id"],
                "strength": event["infection_strength"],
                "timestamp": event["timestamp"]
            })
        
        for event in recent_propagations[-5:]:
            meme_events.append({
                "type": "propagation",
                "source_agent": event["source_agent"],
                "target_agents": event["target_agents"],
                "meme_id": event["meme_id"],
                "successful_propagations": event["successful_propagations"],
                "timestamp": event["timestamp"]
            })
        
        return meme_events
    
    def _get_agent_updates(self) -> List[Dict[str, Any]]:
        """Get current agent states for updates."""
        agent_updates = []
        
        for agent in self.simulation_runner.agents:
            agent_updates.append({
                "id": agent.agent_id,
                "energy": agent.energy_level,
                "health": agent.health,
                "active_memes": len(getattr(agent, 'active_memes', {})),
                "performance_metrics": getattr(agent, 'performance_metrics', {})
            })
        
        return agent_updates
    
    async def _broadcast_initial_state(self):
        """Send initial simulation state to clients."""
        initial_state = {
            "type": "initial_state",
            "timestamp": time.time(),
            "step": 0,
            "config": asdict(self.config),
            "network": self.network_structure,
            "positions": self.agent_positions,
            "agents": self._get_agent_updates()
        }
        
        await self.broadcast_callback(initial_state)
        print("📡 Initial state broadcast to clients")
    
    async def _broadcast_step_update(self, step_data: Dict[str, Any]):
        """Broadcast step update to clients."""
        update_message = {
            "type": "step_update",
            "timestamp": time.time(),
            "data": step_data
        }
        
        await self.broadcast_callback(update_message)
    
    async def _broadcast_simulation_complete(self):
        """Send simulation completion message."""
        completion_message = {
            "type": "simulation_complete",
            "timestamp": time.time(),
            "total_steps": self.current_step,
            "duration": time.time() - self.start_time,
            "final_stats": self.quantum_logger.get_summary_statistics()
        }
        
        await self.broadcast_callback(completion_message)
        print("🎯 Simulation completed, final state broadcast")
    
    async def _broadcast_error(self, error_message: str):
        """Send error message to clients."""
        error_msg = {
            "type": "error",
            "timestamp": time.time(),
            "message": error_message,
            "step": self.current_step
        }
        
        await self.broadcast_callback(error_msg)
    
    async def update_config(self, config_updates: Dict[str, Any]):
        """Update simulation configuration in real-time."""
        print(f"🔧 Updating simulation config: {config_updates}")
        
        # Update configuration
        for key, value in config_updates.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        
        # Notify clients of config change
        await self.broadcast_callback({
            "type": "config_updated",
            "timestamp": time.time(),
            "updates": config_updates
        })
    
    def get_current_state(self) -> Dict[str, Any]:
        """Get current simulation state."""
        return {
            "is_running": self.is_running,
            "current_step": self.current_step,
            "config": asdict(self.config),
            "start_time": self.start_time,
            "agent_count": len(self.simulation_runner.agents) if self.simulation_runner else 0,
            "network_structure": self.network_structure,
            "positions": self.agent_positions
        }