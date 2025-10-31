"""
WebSocket Server for Real-time Simulation Data Streaming

Provides high-performance WebSocket endpoints for streaming live simulation
data to the 3D visualization frontend.
"""

import asyncio
import json
import time
from typing import Dict, List, Any, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .simulation_streamer import SimulationStreamer
from .data_models import (
    SimulationConfig, NetworkUpdate, AgentUpdate, 
    MemeUpdate, EntanglementEvent, SimulationState
)


class ConnectionManager:
    """Manages WebSocket connections for real-time data streaming."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.client_configs: Dict[WebSocket, SimulationConfig] = {}
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"🔌 Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove disconnected WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.client_configs:
            del self.client_configs[websocket]
        print(f"🔌 Client disconnected. Total connections: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Send message to specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            print(f"Error sending message to client: {e}")
            self.disconnect(websocket)
    
    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients."""
        if not self.active_connections:
            return
        
        message_text = json.dumps(message)
        disconnected = []
        
        for connection in self.active_connections:
            try:
                await connection.send_text(message_text)
            except Exception as e:
                print(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


class VisualizationServer:
    """Main visualization WebSocket server."""
    
    def __init__(self):
        self.app = FastAPI(title="UtilityFog Visualization Server", version="0.1.0-rc1")
        self.connection_manager = ConnectionManager()
        self.simulation_streamer = None
        self.current_simulation_task = None
        
        # Configure CORS for frontend access
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup WebSocket and HTTP routes."""
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await self.connection_manager.connect(websocket)
            
            try:
                while True:
                    # Listen for configuration updates from client
                    data = await websocket.receive_text()
                    message = json.loads(data)
                    await self._handle_client_message(message, websocket)
                    
            except WebSocketDisconnect:
                self.connection_manager.disconnect(websocket)
        
        @self.app.get("/api/status")
        async def get_status():
            """Get current server status."""
            return {
                "status": "running",
                "connected_clients": len(self.connection_manager.active_connections),
                "simulation_running": self.current_simulation_task is not None,
                "timestamp": time.time()
            }
        
        @self.app.post("/api/start_simulation")
        async def start_simulation(config: SimulationConfig):
            """Start a new simulation with given configuration."""
            return await self._start_simulation(config)
        
        @self.app.post("/api/stop_simulation")
        async def stop_simulation():
            """Stop the current simulation."""
            return await self._stop_simulation()
        
        @self.app.get("/api/simulation_state")
        async def get_simulation_state():
            """Get current simulation state."""
            if self.simulation_streamer:
                return self.simulation_streamer.get_current_state()
            return {"state": "stopped"}
    
    async def _handle_client_message(self, message: Dict[str, Any], websocket: WebSocket):
        """Handle incoming messages from clients."""
        message_type = message.get("type")
        
        if message_type == "start_simulation":
            config = SimulationConfig(**message.get("config", {}))
            await self._start_simulation(config)
            
        elif message_type == "stop_simulation":
            await self._stop_simulation()
            
        elif message_type == "update_config":
            # Update simulation parameters in real-time
            if self.simulation_streamer:
                config_updates = message.get("updates", {})
                await self.simulation_streamer.update_config(config_updates)
                
        elif message_type == "ping":
            await self.connection_manager.send_personal_message(
                {"type": "pong", "timestamp": time.time()}, websocket
            )
    
    async def _start_simulation(self, config: SimulationConfig):
        """Start new simulation with real-time streaming."""
        # Stop existing simulation
        if self.current_simulation_task:
            await self._stop_simulation()
        
        print(f"🚀 Starting simulation with {config.num_agents} agents")
        
        # Create and start simulation streamer
        self.simulation_streamer = SimulationStreamer(
            config=config,
            broadcast_callback=self.connection_manager.broadcast
        )
        
        # Start simulation in background task
        self.current_simulation_task = asyncio.create_task(
            self.simulation_streamer.run_streaming_simulation()
        )
        
        # Send confirmation to clients
        await self.connection_manager.broadcast({
            "type": "simulation_started",
            "config": config.dict(),
            "timestamp": time.time()
        })
        
        return {"status": "started", "config": config.dict()}
    
    async def _stop_simulation(self):
        """Stop current simulation."""
        if self.current_simulation_task:
            print("⏹️  Stopping simulation")
            self.current_simulation_task.cancel()
            try:
                await self.current_simulation_task
            except asyncio.CancelledError:
                pass
            
            self.current_simulation_task = None
            self.simulation_streamer = None
            
            # Notify clients
            await self.connection_manager.broadcast({
                "type": "simulation_stopped",
                "timestamp": time.time()
            })
        
        return {"status": "stopped"}
    
    def run(self, host: str = "127.0.0.1", port: int = 8002):
        """Run the visualization server."""
        print(f"🌐 Starting UtilityFog Visualization Server on {host}:{port}")
        print(f"🔗 WebSocket endpoint: ws://{host}:{port}/ws")
        print(f"📊 API endpoint: http://{host}:{port}/api")
        
        uvicorn.run(
            self.app,
            host=host,
            port=port,
            log_level="info",
            access_log=False  # Reduce noise from WebSocket pings
        )


# Global server instance
visualization_server = VisualizationServer()


if __name__ == "__main__":
    visualization_server.run()