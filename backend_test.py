#!/usr/bin/env python3
"""
UtilityFog Visualization Backend Test Suite

Tests the WebSocket server running on port 8002 including:
- HTTP API endpoints
- WebSocket connections
- Real-time simulation streaming
- Simulation control functionality
"""

import asyncio
import json
import time
import requests
import websockets
from typing import Dict, List, Any
import sys
import os

# Add project root to path
sys.path.append('/app')

class VisualizationBackendTester:
    """Comprehensive tester for the UtilityFog visualization backend."""
    
    def __init__(self):
        self.base_url = "http://localhost:8002"
        self.ws_url = "ws://localhost:8002/ws"
        self.test_results = {}
        self.websocket = None
        self.received_messages = []
        
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
    
    def test_status_endpoint(self) -> bool:
        """Test the /api/status endpoint."""
        print("\n🔍 Testing /api/status endpoint...")
        
        try:
            response = requests.get(f"{self.base_url}/api/status", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                required_fields = ["status", "connected_clients", "simulation_running", "timestamp"]
                
                missing_fields = [field for field in required_fields if field not in data]
                if missing_fields:
                    self.log_result("status_endpoint", False, 
                                  f"Missing required fields: {missing_fields}", data)
                    return False
                
                if data["status"] == "running":
                    self.log_result("status_endpoint", True, 
                                  f"Server running with {data['connected_clients']} clients", data)
                    return True
                else:
                    self.log_result("status_endpoint", False, 
                                  f"Server status is '{data['status']}', expected 'running'", data)
                    return False
            else:
                self.log_result("status_endpoint", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            self.log_result("status_endpoint", False, f"Request failed: {str(e)}")
            return False
        except json.JSONDecodeError as e:
            self.log_result("status_endpoint", False, f"Invalid JSON response: {str(e)}")
            return False
        except Exception as e:
            self.log_result("status_endpoint", False, f"Unexpected error: {str(e)}")
            return False
    
    async def test_websocket_connection(self) -> bool:
        """Test WebSocket connection to /ws endpoint."""
        print("\n🔍 Testing WebSocket connection...")
        
        try:
            # Test connection
            self.websocket = await websockets.connect(self.ws_url)
            self.log_result("websocket_connection", True, "WebSocket connection established")
            
            # Test ping-pong
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
            self.log_result("websocket_connection", False, f"WebSocket connection failed: {str(e)}")
            return False
    
    async def test_simulation_start_websocket(self) -> bool:
        """Test starting simulation via WebSocket message."""
        print("\n🔍 Testing simulation start via WebSocket...")
        
        if not self.websocket:
            self.log_result("simulation_start_ws", False, "No WebSocket connection available")
            return False
        
        try:
            # Send start simulation message
            start_message = {
                "type": "start_simulation",
                "config": {
                    "num_agents": 5,
                    "num_generations": 2,
                    "max_steps": 10,
                    "step_delay": 0.1,
                    "enable_quantum_myelin": True
                }
            }
            
            await self.websocket.send(json.dumps(start_message))
            print("📤 Sent start simulation message")
            
            # Wait for simulation_started response
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=15.0)
                response_data = json.loads(response)
                
                if response_data.get("type") == "simulation_started":
                    config = response_data.get("config", {})
                    if config.get("num_agents") == 5 and config.get("num_generations") == 2:
                        self.log_result("simulation_start_ws", True, 
                                      "Simulation started successfully via WebSocket", response_data)
                        return True
                    else:
                        self.log_result("simulation_start_ws", False, 
                                      f"Config mismatch: {config}", response_data)
                        return False
                else:
                    self.log_result("simulation_start_ws", False, 
                                  f"Expected simulation_started, got: {response_data.get('type')}", response_data)
                    return False
                    
            except asyncio.TimeoutError:
                self.log_result("simulation_start_ws", False, "No simulation_started response within 15 seconds")
                return False
                
        except Exception as e:
            self.log_result("simulation_start_ws", False, f"Simulation start failed: {str(e)}")
            return False
    
    async def test_simulation_data_streaming(self) -> bool:
        """Test real-time simulation data streaming."""
        print("\n🔍 Testing simulation data streaming...")
        
        if not self.websocket:
            self.log_result("simulation_streaming", False, "No WebSocket connection available")
            return False
        
        try:
            received_message_types = set()
            expected_types = {"initial_state", "step_update"}
            
            # Collect messages for 10 seconds
            start_time = time.time()
            timeout = 10.0
            
            while time.time() - start_time < timeout:
                try:
                    response = await asyncio.wait_for(self.websocket.recv(), timeout=2.0)
                    message_data = json.loads(response)
                    message_type = message_data.get("type")
                    
                    if message_type:
                        received_message_types.add(message_type)
                        self.received_messages.append(message_data)
                        print(f"📨 Received: {message_type}")
                        
                        # Check for specific data in step updates
                        if message_type == "step_update":
                            data = message_data.get("data", {})
                            if "agent_updates" in data and "step" in data:
                                print(f"   Step {data['step']} with {len(data.get('agent_updates', []))} agent updates")
                        
                        # Check for initial state
                        elif message_type == "initial_state":
                            if "agents" in message_data and "network" in message_data:
                                agent_count = len(message_data.get("agents", []))
                                print(f"   Initial state with {agent_count} agents")
                    
                except asyncio.TimeoutError:
                    # No message received in 2 seconds, continue
                    continue
                except json.JSONDecodeError as e:
                    print(f"⚠️  Invalid JSON received: {e}")
                    continue
            
            # Evaluate streaming results
            if expected_types.issubset(received_message_types):
                additional_types = received_message_types - expected_types
                self.log_result("simulation_streaming", True, 
                              f"Received expected message types: {list(received_message_types)}", 
                              {"message_count": len(self.received_messages), 
                               "types": list(received_message_types)})
                return True
            else:
                missing_types = expected_types - received_message_types
                self.log_result("simulation_streaming", False, 
                              f"Missing message types: {list(missing_types)}", 
                              {"received_types": list(received_message_types)})
                return False
                
        except Exception as e:
            self.log_result("simulation_streaming", False, f"Streaming test failed: {str(e)}")
            return False
    
    async def test_simulation_stop_websocket(self) -> bool:
        """Test stopping simulation via WebSocket message."""
        print("\n🔍 Testing simulation stop via WebSocket...")
        
        if not self.websocket:
            self.log_result("simulation_stop_ws", False, "No WebSocket connection available")
            return False
        
        try:
            # Send stop simulation message
            stop_message = {"type": "stop_simulation"}
            await self.websocket.send(json.dumps(stop_message))
            print("📤 Sent stop simulation message")
            
            # Wait for simulation_stopped response
            try:
                response = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
                response_data = json.loads(response)
                
                if response_data.get("type") == "simulation_stopped":
                    self.log_result("simulation_stop_ws", True, 
                                  "Simulation stopped successfully via WebSocket", response_data)
                    return True
                else:
                    self.log_result("simulation_stop_ws", False, 
                                  f"Expected simulation_stopped, got: {response_data.get('type')}", response_data)
                    return False
                    
            except asyncio.TimeoutError:
                self.log_result("simulation_stop_ws", False, "No simulation_stopped response within 10 seconds")
                return False
                
        except Exception as e:
            self.log_result("simulation_stop_ws", False, f"Simulation stop failed: {str(e)}")
            return False
    
    def test_start_simulation_http(self) -> bool:
        """Test POST /api/start_simulation endpoint."""
        print("\n🔍 Testing POST /api/start_simulation...")
        
        try:
            config_data = {
                "num_agents": 3,
                "num_generations": 1,
                "max_steps": 5,
                "step_delay": 0.2,
                "enable_quantum_myelin": True
            }
            
            response = requests.post(
                f"{self.base_url}/api/start_simulation",
                json=config_data,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "started" and "config" in data:
                    self.log_result("start_simulation_http", True, 
                                  "Simulation started via HTTP POST", data)
                    return True
                else:
                    self.log_result("start_simulation_http", False, 
                                  f"Unexpected response format: {data}")
                    return False
            else:
                self.log_result("start_simulation_http", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_result("start_simulation_http", False, f"HTTP start simulation failed: {str(e)}")
            return False
    
    def test_stop_simulation_http(self) -> bool:
        """Test POST /api/stop_simulation endpoint."""
        print("\n🔍 Testing POST /api/stop_simulation...")
        
        try:
            response = requests.post(f"{self.base_url}/api/stop_simulation", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "stopped":
                    self.log_result("stop_simulation_http", True, 
                                  "Simulation stopped via HTTP POST", data)
                    return True
                else:
                    self.log_result("stop_simulation_http", False, 
                                  f"Unexpected response: {data}")
                    return False
            else:
                self.log_result("stop_simulation_http", False, 
                              f"HTTP {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            self.log_result("stop_simulation_http", False, f"HTTP stop simulation failed: {str(e)}")
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
        print("🎯 UTILITYFOG VISUALIZATION BACKEND TEST SUMMARY")
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
            print(f"\n🎉 All tests passed! UtilityFog visualization backend is working correctly.")
        
        return failed_tests == 0


async def main():
    """Run all backend tests."""
    print("🚀 Starting UtilityFog Visualization Backend Tests")
    print("🌐 Testing server on localhost:8002")
    
    tester = VisualizationBackendTester()
    
    try:
        # Test HTTP endpoints first
        tester.test_status_endpoint()
        
        # Test WebSocket functionality
        await tester.test_websocket_connection()
        
        if tester.websocket:
            # Test simulation control via WebSocket
            await tester.test_simulation_start_websocket()
            await tester.test_simulation_data_streaming()
            await tester.test_simulation_stop_websocket()
        
        # Test HTTP simulation endpoints
        tester.test_start_simulation_http()
        time.sleep(2)  # Let simulation run briefly
        tester.test_stop_simulation_http()
        
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