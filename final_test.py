#!/usr/bin/env python3
"""
Final test - start simulation, get run_id, connect immediately
"""

import asyncio
import json
import time
import requests
import websockets

async def final_test():
    """Final test with correct run_id matching."""
    
    base_url = "http://localhost:8003"
    ws_base_url = "ws://localhost:8003"
    
    try:
        # Stop any running simulation
        try:
            requests.post(f"{base_url}/api/sim/stop", timeout=5)
            time.sleep(1)
        except:
            pass
        
        # Start simulation with more steps to give us time
        config_data = {
            "num_agents": 8,
            "num_generations": 3,
            "simulation_steps": 50,
            "network_depth": 4,
            "branching_factor": 3,
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
        
        # Connect WebSocket immediately
        ws_url = f"{ws_base_url}/ws/ws?run_id={run_id}"
        print(f"🔌 Connecting to WebSocket...")
        
        websocket = await websockets.connect(ws_url)
        
        # Skip connection confirmation and start listening immediately
        received_types = set()
        message_count = 0
        
        start_time = time.time()
        timeout = 60.0  # 1 minute timeout
        
        print("📨 Listening for messages...")
        
        while time.time() - start_time < timeout:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                message_data = json.loads(response)
                message_type = message_data.get("type")
                message_count += 1
                
                print(f"   {message_count}: {message_type}")
                
                if message_type in ["init_state", "tick", "event", "stats", "done", "error"]:
                    received_types.add(message_type)
                    
                    if message_type == "done":
                        print("      ✅ Simulation completed!")
                        break
                    elif message_type == "error":
                        print(f"      ❌ Simulation error: {message_data}")
                        break
                        
            except asyncio.TimeoutError:
                # Check simulation status
                try:
                    status_response = requests.get(f"{base_url}/api/sim/status", timeout=3)
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        status = status_data.get("status")
                        step = status_data.get("current_step", 0)
                        total = status_data.get("total_steps", 0)
                        print(f"   📊 Status: {status}, Step: {step}/{total}")
                        
                        if status in ["completed", "error"]:
                            print("   Simulation finished according to status")
                            break
                except:
                    pass
                continue
            except Exception as e:
                print(f"❌ Error receiving message: {e}")
                break
        
        await websocket.close()
        
        print(f"\n📊 Final Results:")
        print(f"   Total messages: {message_count}")
        print(f"   Message types: {list(received_types)}")
        
        # Success if we got any simulation messages
        success = len(received_types) > 0 and message_count > 0
        return success
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(final_test())
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")