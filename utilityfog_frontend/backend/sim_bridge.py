"""
UtilityFog Simulation Bridge

Glue code that runs SimulationRunner and forwards callback payloads
to WebSocket clients and logs.
"""

import asyncio
import time
import logging
import threading
from typing import Dict, Any, Optional, Callable
from pathlib import Path
import sys

# Add project paths
sys.path.append('/app')
sys.path.append('/app/testing_framework')

from testing_framework.simulation_runner import SimulationRunner
from testing_framework.test_runner import TestConfiguration
from testing_framework.loggers import QuantumMyelinLogger, SimulationLogger

# Import WebSocket broadcast functions
from . import ws_server

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SimBridge:
    """Bridge between simulation runner and WebSocket server."""
    
    def __init__(self):
        self.current_simulation: Optional[SimulationRunner] = None
        self.current_run_id: Optional[str] = None
        self.current_config: Optional[Dict[str, Any]] = None
        self.simulation_thread: Optional[threading.Thread] = None
        self.simulation_results: Dict[str, Dict[str, Any]] = {}  # run_id -> results
        self.status = "idle"  # "idle", "running", "completed", "error"
        self.start_time: Optional[float] = None
        self.current_step = 0
        self.total_steps = 0
        
        logger.info("🌉 SimBridge initialized")
    
    def is_running(self) -> bool:
        """Check if simulation is currently running."""
        return self.status == "running"
    
    def get_status(self) -> Dict[str, Any]:
        """Get current simulation status."""
        duration = None
        if self.start_time:
            duration = time.time() - self.start_time
        
        return {
            "run_id": self.current_run_id,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "start_time": self.start_time,
            "duration": duration,
            "connected_clients": ws_server.get_run_connection_count(self.current_run_id) if self.current_run_id else 0
        }
    
    def get_results(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get results for a completed simulation."""
        return self.simulation_results.get(run_id)
    
    async def start_simulation(self, run_id: str, config: Dict[str, Any]):
        """Start a new simulation run."""
        
        if self.is_running():
            raise RuntimeError("Simulation already running")
        
        logger.info(f"🚀 Starting simulation {run_id}")
        
        self.current_run_id = run_id
        self.current_config = config
        self.status = "running"
        self.start_time = time.time()
        self.current_step = 0
        self.total_steps = config.get("simulation_steps", 50)
        
        # Run simulation in background thread to avoid blocking
        self.simulation_thread = threading.Thread(
            target=self._run_simulation_thread,
            args=(run_id, config),
            daemon=True
        )
        self.simulation_thread.start()
    
    async def stop_simulation(self):
        """Stop the current simulation."""
        
        if not self.is_running():
            return
        
        logger.info("⏹️ Stopping simulation")
        
        self.status = "stopped"
        
        # Note: In a production system, you'd want more graceful shutdown
        # For now, we'll let the thread complete naturally
        
        if self.current_run_id:
            await ws_server.broadcast_done(self.current_run_id, {
                "message": "Simulation stopped by user",
                "final_step": self.current_step
            })
    
    def _run_simulation_thread(self, run_id: str, config: Dict[str, Any]):
        """Run simulation in a separate thread."""
        
        try:
            # Create test configuration
            test_config = TestConfiguration(
                test_name=config.get("test_name", f"sim_{run_id[:8]}"),
                num_agents=config.get("num_agents", 10),
                num_generations=config.get("num_generations", 3),
                simulation_steps=config.get("simulation_steps", 50),
                network_depth=config.get("network_depth", 3),
                branching_factor=config.get("branching_factor", 3),
                enable_quantum_myelin=config.get("enable_quantum_myelin", True),
                mutation_rate=config.get("mutation_rate", 0.1),
                crossover_rate=config.get("crossover_rate", 0.8),
                initial_memes_per_agent=config.get("initial_memes_per_agent", 2)
            )
            
            # Create simulation runner with callbacks
            simulation_runner = SimulationRunner(
                config=test_config,
                quantum_logger=QuantumMyelinLogger(),
                simulation_logger=SimulationLogger(),
                output_dir=config.get("output_dir", f"sim_output_{run_id[:8]}"),
                # SimBridge callbacks
                on_init=lambda data: self._on_init(run_id, data),
                on_tick=lambda data: self._on_tick(run_id, data),
                on_event=lambda data: self._on_event(run_id, data),
                on_stats=lambda data: self._on_stats(run_id, data),
                on_done=lambda data: self._on_done(run_id, data),
                on_error=lambda data: self._on_error(run_id, data)
            )
            
            self.current_simulation = simulation_runner
            
            # Run the simulation
            results = simulation_runner.run_simulation()
            
            # Store results
            self.simulation_results[run_id] = results
            
            # Update status
            self.status = "completed"
            
            logger.info(f"✅ Simulation {run_id} completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Simulation {run_id} failed: {e}")
            
            self.status = "error"
            
            # Broadcast error
            asyncio.run(ws_server.broadcast_error(run_id, {
                "error": str(e),
                "step": self.current_step
            }))
        
        finally:
            self.current_simulation = None
    
    def _on_init(self, run_id: str, data: Dict[str, Any]):
        """Handle simulation initialization callback."""
        logger.info(f"📊 Simulation {run_id} initialized with {len(data.get('nodes', []))} agents")
        
        # Broadcast to WebSocket clients
        asyncio.run(ws_server.broadcast_init_state(run_id, data))
    
    def _on_tick(self, run_id: str, data: Dict[str, Any]):
        """Handle simulation tick callback."""
        self.current_step = data.get("step", 0)
        
        if self.current_step % 10 == 0:  # Log every 10 steps
            logger.info(f"🎯 Simulation {run_id} step {self.current_step}")
        
        # Broadcast to WebSocket clients (only if there are agent updates)
        if data.get("agent_updates"):
            asyncio.run(ws_server.broadcast_tick(run_id, data))
    
    def _on_event(self, run_id: str, data: Dict[str, Any]):
        """Handle simulation event callback."""
        event_type = data.get("event_type", "unknown")
        logger.debug(f"⚡ Simulation {run_id} event: {event_type}")
        
        # Broadcast to WebSocket clients
        asyncio.run(ws_server.broadcast_event(run_id, data))
    
    def _on_stats(self, run_id: str, data: Dict[str, Any]):
        """Handle simulation statistics callback."""
        stats = data.get("stats", {})
        logger.debug(f"📈 Simulation {run_id} stats: {stats.get('active_agents', 0)} agents")
        
        # Broadcast to WebSocket clients
        asyncio.run(ws_server.broadcast_stats(run_id, data))
    
    def _on_done(self, run_id: str, data: Dict[str, Any]):
        """Handle simulation completion callback."""
        logger.info(f"🎉 Simulation {run_id} completed in {data.get('duration', 0):.2f}s")
        
        self.status = "completed"
        
        # Broadcast to WebSocket clients
        asyncio.run(ws_server.broadcast_done(run_id, data))
    
    def _on_error(self, run_id: str, data: Dict[str, Any]):
        """Handle simulation error callback."""
        error = data.get("error", "Unknown error")
        logger.error(f"❌ Simulation {run_id} error: {error}")
        
        self.status = "error"
        
        # Broadcast to WebSocket clients
        asyncio.run(ws_server.broadcast_error(run_id, data))