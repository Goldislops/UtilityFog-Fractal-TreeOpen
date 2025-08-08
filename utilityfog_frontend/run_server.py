#!/usr/bin/env python3
"""
UtilityFog Simulation Server

Combined API and WebSocket server for the UtilityFog simulation system.
"""

import uvicorn
import asyncio
import signal
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import our API and WebSocket apps
from backend.api import app as api_app
from backend.ws_server import ws_app

def create_combined_app():
    """Create combined FastAPI app with both API and WebSocket endpoints."""
    
    # Use the API app as the main app
    main_app = api_app
    
    # Mount the WebSocket app
    main_app.mount("/ws", ws_app)
    
    # Add CORS middleware to main app
    main_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    return main_app

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print(f"\n🛑 Received signal {signum}, shutting down server...")
    sys.exit(0)

def main():
    """Main server entry point."""
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("🚀 Starting UtilityFog Simulation Server")
    print("📊 API endpoints: http://localhost:8003/api/")
    print("🔌 WebSocket: ws://localhost:8003/ws?run_id=<run_id>")
    print("📚 API docs: http://localhost:8003/docs")
    
    # Create combined app
    app = create_combined_app()
    
    # Run server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8003,
        log_level="info",
        access_log=True
    )

if __name__ == "__main__":
    main()