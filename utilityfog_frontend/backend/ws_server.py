"""
UtilityFog WebSocket Server

WebSocket server for real-time simulation data streaming.
Supports room-based connections per simulation run.
"""

import asyncio
import json
import time
import logging
from typing import Dict, Set, Any, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages WebSocket connections organized by simulation runs."""
    
    def __init__(self):
        # Dictionary of run_id -> set of websockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.connection_metadata: Dict[WebSocket, Dict[str, Any]] = {}
    
    async def connect(self, websocket: WebSocket, run_id: str):
        """Accept a new WebSocket connection for a specific run."""
        await websocket.accept()
        
        if run_id not in self.active_connections:
            self.active_connections[run_id] = set()
        
        self.active_connections[run_id].add(websocket)
        self.connection_metadata[websocket] = {
            "run_id": run_id,
            "connected_at": time.time()
        }
        
        logger.info(f"🔌 Client connected to run {run_id}. Total connections: {self.get_connection_count()}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        if websocket in self.connection_metadata:
            run_id = self.connection_metadata[websocket]["run_id"]
            
            if run_id in self.active_connections:
                self.active_connections[run_id].discard(websocket)
                
                # Remove empty run rooms
                if not self.active_connections[run_id]:
                    del self.active_connections[run_id]
            
            del self.connection_metadata[websocket]
            logger.info(f"🔌 Client disconnected from run {run_id}. Total connections: {self.get_connection_count()}")
    
    async def send_to_run(self, run_id: str, message: Dict[str, Any]):
        """Send a message to all clients connected to a specific run."""
        if run_id not in self.active_connections:
            return
        
        message_text = json.dumps(message)
        disconnected = []
        
        for websocket in self.active_connections[run_id].copy():
            try:
                await websocket.send_text(message_text)
            except Exception as e:
                logger.warning(f"Failed to send message to client: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected:
            self.disconnect(websocket)
    
    async def send_to_client(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send message to client: {e}")
            self.disconnect(websocket)
    
    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(connections) for connections in self.active_connections.values())
    
    def get_run_connection_count(self, run_id: str) -> int:
        """Get connection count for a specific run."""
        return len(self.active_connections.get(run_id, set()))

# Global connection manager
connection_manager = ConnectionManager()

# WebSocket app
ws_app = FastAPI(title="UtilityFog WebSocket Server")

# Add CORS middleware
ws_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@ws_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, run_id: str = Query(...)):
    """WebSocket endpoint for real-time simulation data."""
    
    await connection_manager.connect(websocket, run_id)
    
    try:
        # Send initial connection confirmation
        await connection_manager.send_to_client(websocket, {
            "type": "connection_confirmed",
            "run_id": run_id,
            "timestamp": time.time()
        })
        
        while True:
            try:
                # Listen for client messages (ping, config updates, etc.)
                data = await websocket.receive_text()
                message = json.loads(data)
                
                await handle_client_message(websocket, run_id, message)
                
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await connection_manager.send_to_client(websocket, {
                    "type": "error",
                    "message": "Invalid JSON",
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await connection_manager.send_to_client(websocket, {
                    "type": "error",
                    "message": str(e),
                    "timestamp": time.time()
                })
                break
                
    finally:
        connection_manager.disconnect(websocket)

async def handle_client_message(websocket: WebSocket, run_id: str, message: Dict[str, Any]):
    """Handle incoming messages from WebSocket clients."""
    
    message_type = message.get("type")
    
    if message_type == "ping":
        # Respond with pong
        await connection_manager.send_to_client(websocket, {
            "type": "pong",
            "timestamp": time.time()
        })
        
    elif message_type == "subscribe":
        # Client wants to subscribe to specific event types
        event_types = message.get("event_types", [])
        # Store subscription preferences (implement as needed)
        await connection_manager.send_to_client(websocket, {
            "type": "subscription_confirmed",
            "event_types": event_types,
            "timestamp": time.time()
        })
        
    else:
        # Unknown message type
        await connection_manager.send_to_client(websocket, {
            "type": "error",
            "message": f"Unknown message type: {message_type}",
            "timestamp": time.time()
        })

# Message broadcasting functions (called by SimBridge)

async def broadcast_init_state(run_id: str, data: Dict[str, Any]):
    """Broadcast initial simulation state."""
    message = {
        "type": "init_state",
        "data": data,
        "timestamp": time.time()
    }
    await connection_manager.send_to_run(run_id, message)

async def broadcast_tick(run_id: str, data: Dict[str, Any]):
    """Broadcast simulation tick update."""
    message = {
        "type": "tick",
        "data": data,
        "timestamp": time.time()
    }
    await connection_manager.send_to_run(run_id, message)

async def broadcast_event(run_id: str, data: Dict[str, Any]):
    """Broadcast simulation event."""
    message = {
        "type": "event",
        "data": data,
        "timestamp": time.time()
    }
    await connection_manager.send_to_run(run_id, message)

async def broadcast_stats(run_id: str, data: Dict[str, Any]):
    """Broadcast simulation statistics."""
    message = {
        "type": "stats",
        "data": data,
        "timestamp": time.time()
    }
    await connection_manager.send_to_run(run_id, message)

async def broadcast_done(run_id: str, data: Dict[str, Any]):
    """Broadcast simulation completion."""
    message = {
        "type": "done",
        "data": data,
        "timestamp": time.time()
    }
    await connection_manager.send_to_run(run_id, message)

async def broadcast_error(run_id: str, data: Dict[str, Any]):
    """Broadcast simulation error."""
    message = {
        "type": "error",
        "data": data,
        "timestamp": time.time()
    }
    await connection_manager.send_to_run(run_id, message)

def get_connection_count() -> int:
    """Get total connection count (for API status)."""
    return connection_manager.get_connection_count()

def get_run_connection_count(run_id: str) -> int:
    """Get connection count for specific run."""
    return connection_manager.get_run_connection_count(run_id)