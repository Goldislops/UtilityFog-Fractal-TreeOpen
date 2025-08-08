#!/usr/bin/env python3
"""
Quick test of full simulation flow
"""

import asyncio
import json
import time
import requests
import websockets

async def test_simulation_flow():
    """Test full simulation flow."""
    
    base_url = "http://localhost:8003"
    ws_base_url = "ws://localhost:8003"
    
    try:
        # Stop any running simulation first
        try:
            requests.post(f"{base_url}/api/sim/stop", timeout=5)
            time.sleep(1)
        except:
            pass
        
        # Start a new simulation
        config_data = {
            "num_agents": 3,
            "num_generations": 1,
            "simulation_steps": 10,
            "network_depth": 2,
            "branching_factor": 2,
            "enable_quantum_myelin": True
        }
        
        print("🚀 Starting simulation...")
        response = requests.post(f"{base_url}/api/sim/start", json=config_data, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Failed to start simulation: {response.text}")
            return False
        
        data = response.json()
        run_id = data.get("run_id")
        print(f"✅ Simulation started with run_id: {run_id}")
        
        # Connect WebSocket
        ws_url = f"{ws_base_url}/ws/ws?run_id={run_id}"
        print(f"🔌 Connecting to WebSocket: {ws_url}")
        
        websocket = await websockets.connect(ws_url)
        
        # Wait for connection confirmation
        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
        conn_data = json.loads(response)
        print(f"✅ Connection confirmed: {conn_data.get('type')}")
        
        # Collect messages
        received_types = set()
        message_count = 0
        
        start_time = time.time()
        timeout = 30.0
        
        print("📨 Listening for messages...")
        
        while time.time() - start_time < timeout:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message_data = json.loads(response)
                message_type = message_data.get("type")
                message_count += 1
                
                print(f"   {message_count}: {message_type}")
                
                if message_type in ["init_state", "tick", "event", "stats", "done"]:
                    received_types.add(message_type)
                    
                    if message_type == "done":
                        print("✅ Simulation completed!")
                        break
                        
            except asyncio.TimeoutError:
                print("   ⏰ Timeout, checking status...")
                status_response = requests.get(f"{base_url}/api/sim/status", timeout=5)
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    print(f"   Status: {status_data.get('status')}")
                    if status_data.get("status") in ["completed", "error"]:
                        break
                continue
            except Exception as e:
                print(f"❌ Error: {e}")
                break
        
        await websocket.close()
        
        print(f"\n📊 Results:")
        print(f"   Messages received: {message_count}")
        print(f"   Message types: {list(received_types)}")
        
        return len(received_types) >= 3  # At least tick, event, done
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_simulation_flow())
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")