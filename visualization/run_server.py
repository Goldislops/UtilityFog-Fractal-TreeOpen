#!/usr/bin/env python3
"""
UtilityFog Visualization Server Runner

Starts the WebSocket server for real-time simulation visualization.
This script integrates with the existing testing framework to provide
live streaming of simulation data to the 3D frontend.
"""

import asyncio
import sys
import os
import signal
import logging
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from visualization.backend.websocket_server import visualization_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)

def main():
    """Main entry point for the visualization server."""
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("🚀 Starting UtilityFog Visualization Server")
    logger.info("📊 Real-time 3D simulation visualization")
    logger.info("🌐 WebSocket streaming for live agent interactions")
    
    # Server configuration
    host = os.environ.get('VISUALIZATION_HOST', '0.0.0.0')
    port = int(os.environ.get('VISUALIZATION_PORT', 8002))
    
    try:
        # Start the visualization server
        visualization_server.run(host=host, port=port)
        
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()