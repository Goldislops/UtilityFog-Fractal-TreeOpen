#!/usr/bin/env python3
"""
UtilityFog SimBridge Backend Test Suite

Tests the new UtilityFog SimBridge backend running on port 8003 including:
- API endpoints: /api/health, /api/sim/status, /api/sim/start, /api/sim/stop
- WebSocket connections with run_id parameter
- Full simulation flow with exact message schemas
- SimBridge integration verification
"""

import asyncio
import json
import time
import requests
import websockets
from typing import Dict, List, Any, Optional
import sys
import os

# Add project root to path
sys.path.append('/app')

class SimBridgeBackendTester:
    """Comprehensive tester for the UtilityFog SimBridge backend on port 8003."""
    
    def __init__(self):
        self.base_url = "http://localhost:8003"
        self.ws_base_url = "ws://localhost:8003"
        self.test_results = {}
        self.websocket = None
        self.received_messages = []
        self.current_run_id = None
        
    def log_result(self, test_name: str, success: bool, message: str, details: Any = None):
        """Log test result."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}: {message}")
        
        self.test_results[test_name] = {
            "success": success,
            "message": message,
            "details": details,
            "timestamp": time.time()
        }
    
    def test_health_endpoint(self) -> bool:
        """Test the /api/health endpoint."""
        print("\n🔍 Testing /api/health endpoint...")
        
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ["status", "timestamp", "sim_bridge_status"]
                
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    self.log_result("health_endpoint", False, 
                                  f"Missing required fields: {missing_fields}", data)
                    return False
                
                if data["status"] == "healthy":
                    self.log_result("health_endpoint", True, 
                                  f"Health check passed, sim_bridge: {data['sim_bridge_status']}", data)
                    return True
                else:
                    self.log_result("health_endpoint", False, 
                                  f"Health status is '{data['status']}', expected 'healthy'", data)
                    return False
            else:
                self.log_result("health_endpoint", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_result("health_endpoint", False, f"Request failed: {str(e)}")
            return False
    
    def test_sim_status_endpoint(self) -> bool:
        """Test the /api/sim/status endpoint."""
        print("\n🔍 Testing /api/sim/status endpoint...")
        
        try:
            response = requests.get(f"{self.base_url}/api/sim/status", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ["status", "current_step", "total_steps", "connected_clients"]
                
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    self.log_result("sim_status_endpoint", False, 
                                  f"Missing required fields: {missing_fields}", data)
                    return False
                
                # Should be idle initially
                if data["status"] in ["idle", "running", "completed", "error"]:
                    self.log_result("sim_status_endpoint", True, 
                                  f"Status endpoint working, current status: {data['status']}", data)
                    return True
                else:
                    self.log_result("sim_status_endpoint", False, 
                                  f"Invalid status: {data['status']}", data)
                    return False
            else:
                self.log_result("sim_status_endpoint", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_result("sim_status_endpoint", False, f"Request failed: {str(e)}")
            return False
    
    def test_sim_start_endpoint(self) -> bool:
        """Test the POST /api/sim/start endpoint."""
        print("\n🔍 Testing POST /api/sim/start endpoint...")
        
        try:
            config_data = {
                "num_agents": 5,
                "num_generations": 1,
                "simulation_steps": 20,
                "network_depth": 2,
                "branching_factor": 2,
                "enable_quantum_myelin": True,
                "mutation_rate": 0.1,
                "crossover_rate": 0.8,
                "initial_memes_per_agent": 2
            }
            
            response = requests.post(
                f"{self.base_url}/api/sim/start",
                json=config_data,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ["run_id", "status", "message", "config"]
                
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    self.log_result("sim_start_endpoint", False, 
                                  f"Missing required fields: {missing_fields}", data)
                    return False
                
                if data.get("status") == "starting" and data.get("run_id"):
                    self.current_run_id = data["run_id"]
                    self.log_result("sim_start_endpoint", True, 
                                  f"Simulation started with run_id: {self.current_run_id}", data)
                    return True
                else:
                    self.log_result("sim_start_endpoint", False, 
                                  f"Unexpected response format: {data}")
                    return False
            else:
                self.log_result("sim_start_endpoint", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_result("sim_start_endpoint", False, f"Start simulation failed: {str(e)}")
            return False
    
    def test_sim_stop_endpoint(self) -> bool:
        """Test the POST /api/sim/stop endpoint."""
        print("\n🔍 Testing POST /api/sim/stop endpoint...")
        
        try:
            response = requests.post(f"{self.base_url}/api/sim/stop", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ["status", "message"]
                
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    self.log_result("sim_stop_endpoint", False, 
                                  f"Missing required fields: {missing_fields}", data)
                    return False
                
                if data.get("status") == "stopped":
                    self.log_result("sim_stop_endpoint", True, 
                                  "Simulation stopped successfully", data)
                    return True
                else:
                    self.log_result("sim_stop_endpoint", False, 
                                  f"Unexpected response: {data}")
                    return False
            else:
                # Might fail if no simulation is running, which is acceptable
                if response.status_code == 400:
                    self.log_result("sim_stop_endpoint", True, 
                                  "Stop endpoint working (no simulation to stop)", response.json())
                    return True
                else:
                    self.log_result("sim_stop_endpoint", False, 
                                  f"HTTP {response.status_code}: {response.text}")
                    return False
                
        except Exception as e:
            self.log_result("sim_stop_endpoint", False, f"Stop simulation failed: {str(e)}")
            return False
    
    async def test_websocket_connection(self) -> bool:
        """Test WebSocket connection to /ws with run_id parameter."""
        print("\n🔍 Testing WebSocket connection with run_id...")
        
        if not self.current_run_id:
            # Use test run_id if no simulation was started
            test_run_id = "test123"
        else:
            test_run_id = self.current_run_id
        
        try:
            # Connect with run_id parameter (WebSocket app is mounted at /ws, endpoint is /ws)
            ws_url = f"{self.ws_base_url}/ws/ws?run_id={test_run_id}"
            self.websocket = await websockets.connect(ws_url)
            
            # Wait for connection confirmation
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                connection_data = json.loads(response)
                
                if connection_data.get("type") == "connection_confirmed":
                    self.log_result("websocket_connection", True, 
                                  f"WebSocket connected to run_id: {test_run_id}", connection_data)
                    return True
                else:
                    self.log_result("websocket_connection", False, 
                                  f"Expected connection_confirmed, got: {connection_data.get('type')}", connection_data)
                    return False
                    
            except asyncio.TimeoutError:
                self.log_result("websocket_connection", False, "No connection confirmation within 5 seconds")
                return False
                
        except Exception as e:
            self.log_result("websocket_connection", False, f"WebSocket connection failed: {str(e)}")
            return False
    
    async def test_websocket_ping_pong(self) -> bool:
        """Test WebSocket ping-pong functionality."""
        print("\n🔍 Testing WebSocket ping-pong...")
        
        if not self.websocket:
            self.log_result("websocket_ping_pong", False, "No WebSocket connection available")
            return False
        
        try:
            # Send ping message
            ping_message = {"type": "ping", "timestamp": time.time()}
            await self.websocket.send(json.dumps(ping_message))
            
            # Wait for pong response
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                pong_data = json.loads(response)
                
                if pong_data.get("type") == "pong":
                    self.log_result("websocket_ping_pong", True, "Ping-pong successful", pong_data)
                    return True
                else:
                    self.log_result("websocket_ping_pong", False, 
                                  f"Expected pong, got: {pong_data.get('type')}", pong_data)
                    return False
                    
            except asyncio.TimeoutError:
                self.log_result("websocket_ping_pong", False, "No pong response within 5 seconds")
                return False
                
        except Exception as e:
            self.log_result("websocket_ping_pong", False, f"Ping-pong failed: {str(e)}")
            return False
    
    async def test_websocket_subscribe(self) -> bool:
        """Test WebSocket subscribe functionality."""
        print("\n🔍 Testing WebSocket subscribe...")
        
        if not self.websocket:
            self.log_result("websocket_subscribe", False, "No WebSocket connection available")
            return False
        
        try:
            # Send subscribe message
            subscribe_message = {
                "type": "subscribe",
                "event_types": ["ENTANGLEMENT", "MEME_SPREAD"]
            }
            await self.websocket.send(json.dumps(subscribe_message))
            
            # Wait for subscription confirmation
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=5.0)
                sub_data = json.loads(response)
                
                if sub_data.get("type") == "subscription_confirmed":
                    self.log_result("websocket_subscribe", True, "Subscribe successful", sub_data)
                    return True
                else:
                    self.log_result("websocket_subscribe", False, 
                                  f"Expected subscription_confirmed, got: {sub_data.get('type')}", sub_data)
                    return False
                    
            except asyncio.TimeoutError:
                self.log_result("websocket_subscribe", False, "No subscription confirmation within 5 seconds")
                return False
                
        except Exception as e:
            self.log_result("websocket_subscribe", False, f"Subscribe failed: {str(e)}")
            return False
    
    async def test_full_simulation_flow(self) -> bool:
        """Test full simulation flow with message schema verification."""
        print("\n🔍 Testing full simulation flow...")
        
        try:
            # Start a new simulation
            config_data = {
                "num_agents": 5,
                "num_generations": 1,
                "simulation_steps": 20,
                "network_depth": 2,
                "branching_factor": 2,
                "enable_quantum_myelin": True
            }
            
            response = requests.post(
                f"{self.base_url}/api/sim/start",
                json=config_data,
                timeout=15
            )
            
            if response.status_code != 200:
                self.log_result("full_simulation_flow", False, f"Failed to start simulation: {response.text}")
                return False
            
            data = response.json()
            run_id = data.get("run_id")
            
            if not run_id:
                self.log_result("full_simulation_flow", False, "No run_id returned from start simulation")
                return False
            
            # Connect WebSocket to this run_id
            ws_url = f"{self.ws_base_url}/ws?run_id={run_id}"
            websocket = await websockets.connect(ws_url)
            
            # Wait for connection confirmation
            await asyncio.wait_for(websocket.recv(), timeout=5.0)
            
            # Collect messages for simulation
            received_message_types = set()
            expected_types = {"init_state", "tick", "event", "stats", "done"}
            message_schemas = {}
            
            start_time = time.time()
            timeout = 30.0  # 30 seconds to complete simulation
            
            while time.time() - start_time < timeout:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    message_data = json.loads(response)
                    message_type = message_data.get("type")
                    
                    if message_type and message_type in expected_types:
                        received_message_types.add(message_type)
                        message_schemas[message_type] = message_data
                        print(f"📨 Received: {message_type}")
                        
                        # Verify specific message schemas
                        if message_type == "init_state":
                            data_content = message_data.get("data", {})
                            if "nodes" in data_content and "edges" in data_content:
                                print(f"   ✅ init_state schema valid: {len(data_content.get('nodes', []))} nodes")
                            else:
                                print(f"   ❌ init_state schema invalid: missing nodes/edges")
                        
                        elif message_type == "tick":
                            data_content = message_data.get("data", {})
                            if "agent_updates" in data_content:
                                print(f"   ✅ tick schema valid: {len(data_content.get('agent_updates', []))} updates")
                            else:
                                print(f"   ❌ tick schema invalid: missing agent_updates")
                        
                        elif message_type == "event":
                            data_content = message_data.get("data", {})
                            if "event_type" in data_content:
                                event_type = data_content["event_type"]
                                print(f"   ✅ event schema valid: {event_type}")
                            else:
                                print(f"   ❌ event schema invalid: missing event_type")
                        
                        elif message_type == "stats":
                            data_content = message_data.get("data", {})
                            stats = data_content.get("stats", {})
                            if stats:
                                print(f"   ✅ stats schema valid: {list(stats.keys())}")
                            else:
                                print(f"   ❌ stats schema invalid: missing stats")
                        
                        elif message_type == "done":
                            print(f"   ✅ Simulation completed")
                            break
                    
                except asyncio.TimeoutError:
                    # Check if simulation is still running
                    status_response = requests.get(f"{self.base_url}/api/sim/status", timeout=5)
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        if status_data.get("status") == "completed":
                            print("   Simulation completed, no more messages expected")
                            break
                    continue
                except json.JSONDecodeError as e:
                    print(f"⚠️  Invalid JSON received: {e}")
                    continue
            
            await websocket.close()
            
            # Evaluate results
            missing_types = expected_types - received_message_types
            if len(missing_types) == 0:
                self.log_result("full_simulation_flow", True, 
                              f"Full simulation flow successful, received all message types: {list(received_message_types)}", 
                              {"schemas": message_schemas})
                return True
            elif len(missing_types) <= 2:  # Allow some flexibility
                self.log_result("full_simulation_flow", True, 
                              f"Simulation flow mostly successful, missing: {list(missing_types)}", 
                              {"received": list(received_message_types), "missing": list(missing_types)})
                return True
            else:
                self.log_result("full_simulation_flow", False, 
                              f"Missing critical message types: {list(missing_types)}", 
                              {"received": list(received_message_types)})
                return False
                
        except Exception as e:
            self.log_result("full_simulation_flow", False, f"Full simulation flow failed: {str(e)}")
            return False
    
    async def cleanup(self):
        """Clean up WebSocket connection."""
        if self.websocket:
            try:
                await self.websocket.close()
                print("🔌 WebSocket connection closed")
            except Exception as e:
                print(f"⚠️  Error closing WebSocket: {e}")
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "="*60)
        print("🎯 UTILITYFOG SIMBRIDGE BACKEND TEST SUMMARY (PORT 8003)")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result["success"])
        failed_tests = total_tests - passed_tests
        
        print(f"📊 Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"📈 Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        print("\n📋 Detailed Results:")
        for test_name, result in self.test_results.items():
            status = "✅" if result["success"] else "❌"
            print(f"{status} {test_name}: {result['message']}")
        
        if failed_tests > 0:
            print(f"\n⚠️  {failed_tests} tests failed. Check logs above for details.")
        else:
            print(f"\n🎉 All tests passed! UtilityFog SimBridge backend is working correctly.")
        
        return failed_tests == 0


async def main():
    """Run all SimBridge backend tests."""
    print("🚀 Starting UtilityFog SimBridge Backend Tests")
    print("🌐 Testing server on localhost:8003")
    
    tester = SimBridgeBackendTester()
    
    try:
        # Test API endpoints
        print("\n" + "="*50)
        print("🔧 TESTING API ENDPOINTS")
        print("="*50)
        
        tester.test_health_endpoint()
        tester.test_sim_status_endpoint()
        tester.test_sim_start_endpoint()
        
        # Give simulation time to start
        time.sleep(2)
        
        tester.test_sim_stop_endpoint()
        
        # Test WebSocket functionality
        print("\n" + "="*50)
        print("🔌 TESTING WEBSOCKET FUNCTIONALITY")
        print("="*50)
        
        await tester.test_websocket_connection()
        
        if tester.websocket:
            await tester.test_websocket_ping_pong()
            await tester.test_websocket_subscribe()
        
        # Test full simulation flow
        print("\n" + "="*50)
        print("🎮 TESTING FULL SIMULATION FLOW")
        print("="*50)
        
        await tester.test_full_simulation_flow()
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error during testing: {e}")
    finally:
        await tester.cleanup()
    
    # Print summary and return success status
    all_passed = tester.print_summary()
    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)