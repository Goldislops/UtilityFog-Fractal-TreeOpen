"""
UtilityFog Simulation API Endpoints

REST API endpoints for simulation control and status.
"""

import os
import asyncio
import time
import uuid
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import SimBridge 
from .sim_bridge import SimBridge

# Global sim bridge instance
sim_bridge = SimBridge()

# FastAPI app
app = FastAPI(title="UtilityFog Simulation API", version="1.0.0")

# Request models
class SimulationStartRequest(BaseModel):
    num_agents: int = 10
    num_generations: int = 3
    simulation_steps: int = 50
    network_depth: int = 3
    branching_factor: int = 3
    enable_quantum_myelin: bool = True
    mutation_rate: float = 0.1
    crossover_rate: float = 0.8
    initial_memes_per_agent: int = 2

# Response models
class SimulationStatus(BaseModel):
    run_id: Optional[str]
    status: str  # "idle", "running", "completed", "error"
    current_step: int
    total_steps: int
    start_time: Optional[float]
    duration: Optional[float]
    connected_clients: int

@app.post("/api/sim/start")
async def start_simulation(request: SimulationStartRequest, background_tasks: BackgroundTasks):
    """Start a new simulation run."""
    
    if sim_bridge.is_running():
        raise HTTPException(status_code=400, detail="Simulation already running")
    
    try:
        # Generate run ID
        run_id = str(uuid.uuid4())
        
        # Convert request to config dict
        config = {
            "test_name": f"sim_{run_id[:8]}",
            "num_agents": request.num_agents,
            "num_generations": request.num_generations,
            "simulation_steps": request.simulation_steps,
            "network_depth": request.network_depth,
            "branching_factor": request.branching_factor,
            "enable_quantum_myelin": request.enable_quantum_myelin,
            "mutation_rate": request.mutation_rate,
            "crossover_rate": request.crossover_rate,
            "initial_memes_per_agent": request.initial_memes_per_agent,
            "output_dir": f"sim_output_{run_id[:8]}"
        }
        
        # Start simulation in background
        background_tasks.add_task(sim_bridge.start_simulation, run_id, config)
        
        logger.info(f"🚀 Starting simulation {run_id} with {request.num_agents} agents")
        
        return {
            "run_id": run_id,
            "status": "starting",
            "message": "Simulation started successfully",
            "config": config
        }
        
    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start simulation: {str(e)}")

@app.post("/api/sim/stop")
async def stop_simulation():
    """Stop the current simulation."""
    
    if not sim_bridge.is_running():
        raise HTTPException(status_code=400, detail="No simulation is running")
    
    try:
        await sim_bridge.stop_simulation()
        logger.info("⏹️ Simulation stopped")
        
        return {
            "status": "stopped",
            "message": "Simulation stopped successfully"
        }
        
    except Exception as e:
        logger.error(f"Failed to stop simulation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop simulation: {str(e)}")

@app.get("/api/sim/status")
async def get_simulation_status():
    """Get current simulation status."""
    
    status_info = sim_bridge.get_status()
    
    return SimulationStatus(
        run_id=status_info.get("run_id"),
        status=status_info.get("status", "idle"),
        current_step=status_info.get("current_step", 0),
        total_steps=status_info.get("total_steps", 0),
        start_time=status_info.get("start_time"),
        duration=status_info.get("duration"),
        connected_clients=status_info.get("connected_clients", 0)
    )

@app.get("/api/sim/results/{run_id}")
async def get_simulation_results(run_id: str):
    """Get results for a completed simulation."""
    
    try:
        results = sim_bridge.get_results(run_id)
        
        if not results:
            raise HTTPException(status_code=404, detail="Simulation results not found")
        
        return {
            "run_id": run_id,
            "results": results,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Failed to get results for {run_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get results: {str(e)}")

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "sim_bridge_status": "running" if sim_bridge.is_running() else "idle"
    }