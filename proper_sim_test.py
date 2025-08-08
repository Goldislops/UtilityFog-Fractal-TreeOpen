#!/usr/bin/env python3
"""
Test simulation flow by connecting WebSocket first, then starting simulation
"""

import asyncio
import json
import time
import requests
import websockets
import uuid

async def test_simulation_flow_proper():
    """Test full simulation flow with proper timing."""
    
    base_url = "http://localhost:8003"
    ws_base_url = "ws://localhost:8003"
    
    try:
        # Stop any running simulation first
        try:
            requests.post(f"{base_url}/api/sim/stop", timeout=5)
            time.sleep(1)
        except:
            pass
        
        # Generate a run_id for the simulation
        run_id = str(uuid.uuid4())
        
        # Connect WebSocket FIRST (before starting simulation)
        ws_url = f"{ws_base_url}/ws/ws?run_id={run_id}"
        print(f"🔌 Connecting to WebSocket: {ws_url}")
        
        websocket = await websockets.connect(ws_url)
        
        # Wait for connection confirmation
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        conn_data = json.loads(response)
        print(f"✅ Connection confirmed: {conn_data.get('type')}")
        
        # NOW start the simulation with longer parameters
        config_data = {
            "num_agents": 5,
            "num_generations": 2,
            "simulation_steps": 30,  # More steps
            "network_depth": 3,
            "branching_factor": 3,
            "enable_quantum_myelin": True
        }
        
        print("🚀 Starting simulation...")
        
        # Start simulation in background
        async def start_simulation():
            await asyncio.sleep(0.1)  # Small delay to ensure WebSocket is ready
            response = requests.post(f"{base_url}/api/sim/start", json=config_data, timeout=15)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Simulation started with run_id: {data.get('run_id')}")
            else:
                print(f"❌ Failed to start simulation: {response.text}")
        
        # Start simulation task
        sim_task = asyncio.create_task(start_simulation())
        
        # Collect messages
        received_types = set()
        message_count = 0
        
        start_time = time.time()
        timeout = 45.0
        
        print("📨 Listening for messages...")
        
        while time.time() - start_time < timeout:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                message_data = json.loads(response)
                message_type = message_data.get("type")
                message_count += 1
                
                print(f"   {message_count}: {message_type}")
                
                if message_type in ["init_state", "tick", "event", "stats", "done"]:
                    received_types.add(message_type)
                    
                    # Show some details for key message types
                    if message_type == "init_state":
                        data_content = message_data.get("data", {})
                        nodes = len(data_content.get("nodes", []))
                        edges = len(data_content.get("edges", []))
                        print(f"      📊 {nodes} nodes, {edges} edges")
                    
                    elif message_type == "tick":
                        data_content = message_data.get("data", {})
                        updates = len(data_content.get("agent_updates", []))
                        step = data_content.get("step", "?")
                        print(f"      🎯 Step {step}, {updates} updates")
                    
                    elif message_type == "event":
                        data_content = message_data.get("data", {})
                        event_type = data_content.get("event_type", "unknown")
                        print(f"      ⚡ Event: {event_type}")
                    
                    elif message_type == "stats":
                        data_content = message_data.get("data", {})
                        stats = data_content.get("stats", {})
                        print(f"      📈 Stats: {list(stats.keys())}")
                    
                    elif message_type == "done":
                        print("      ✅ Simulation completed!")
                        break
                        
            except asyncio.TimeoutError:
                print("   ⏰ Timeout, checking status...")
                status_response = requests.get(f"{base_url}/api/sim/status", timeout=5)
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get("status")
                    step = status_data.get("current_step", 0)
                    total = status_data.get("total_steps", 0)
                    print(f"   Status: {status}, Step: {step}/{total}")
                    if status in ["completed", "error"]:
                        break
                continue
            except Exception as e:
                print(f"❌ Error: {e}")
                break
        
        await websocket.close()
        
        print(f"\n📊 Results:")
        print(f"   Messages received: {message_count}")
        print(f"   Message types: {list(received_types)}")
        
        # Success if we got at least tick and done messages
        success = "tick" in received_types and "done" in received_types
        return success, received_types
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False, set()

if __name__ == "__main__":
    success, types = asyncio.run(test_simulation_flow_proper())
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")
    print(f"Received types: {list(types)}")