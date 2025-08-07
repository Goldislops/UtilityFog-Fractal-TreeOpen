#!/usr/bin/env python3
"""
Simple demonstration script for the UtilityFog testing framework.

This script runs a basic test to demonstrate the system capabilities.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Run a simple demonstration test."""
    print("🔬 UtilityFog Testing Framework Demo")
    print("=" * 40)
    
    try:
        # Import the testing framework
        from testing_framework import TestRunner, TestConfiguration
        
        print("✅ Testing framework imported successfully")
        
        # Create a simple test configuration
        config = TestConfiguration(
            test_name="demo_test",
            num_agents=5,
            num_generations=2,
            simulation_steps=20,
            enable_quantum_myelin=True
        )
        
        print(f"✅ Test configuration created: {config.test_name}")
        print(f"   - {config.num_agents} agents")
        print(f"   - {config.num_generations} generations") 
        print(f"   - {config.simulation_steps} steps")
        print(f"   - Quantum myelin: {'enabled' if config.enable_quantum_myelin else 'disabled'}")
        
        # Initialize test runner
        test_runner = TestRunner(base_output_dir="demo_results")
        print("✅ Test runner initialized")
        
        # Run the test
        print("\n🚀 Starting demo simulation...")
        result = test_runner.run_single_test(config)
        
        # Display results
        print("\n📊 DEMO RESULTS")
        print("=" * 40)
        
        if result.success:
            print("✅ Demo test completed successfully!")
            print(f"Duration: {result.duration:.2f} seconds")
            
            # Agent metrics
            agent_metrics = result.agent_metrics
            print(f"\n👥 Agent Metrics:")
            print(f"   - Total agents: {agent_metrics.get('total_agents', 'N/A')}")
            print(f"   - Average energy: {agent_metrics.get('average_energy', 0):.3f}")
            print(f"   - Average health: {agent_metrics.get('average_health', 0):.3f}")
            print(f"   - Active memes: {agent_metrics.get('total_active_memes', 0)}")
            
            # Quantum myelin metrics
            quantum_metrics = result.quantum_myelin_metrics
            print(f"\n🔗 Quantum Myelin Metrics:")
            print(f"   - Total entanglements: {quantum_metrics.get('total_entanglements', 0)}")
            print(f"   - Total infections: {quantum_metrics.get('total_infections', 0)}")
            print(f"   - Total propagations: {quantum_metrics.get('total_propagations', 0)}")
            print(f"   - Avg entanglement strength: {quantum_metrics.get('average_entanglement_strength', 0):.3f}")
            
            # Meme metrics
            meme_metrics = result.meme_metrics
            print(f"\n🧠 Meme Metrics:")
            print(f"   - Total memes: {meme_metrics.get('total_memes', 0)}")
            print(f"   - Average fitness: {meme_metrics.get('average_fitness', 0):.3f}")
            print(f"   - Total propagations: {meme_metrics.get('total_propagations', 0)}")
            
            # Network metrics
            network_metrics = result.network_metrics
            print(f"\n🌐 Network Metrics:")
            print(f"   - Total nodes: {network_metrics.get('total_nodes', 0)}")
            print(f"   - Total connections: {network_metrics.get('total_connections', 0)}")
            print(f"   - Network depth: {network_metrics.get('max_depth', 0)}")
            
            print(f"\n📁 Detailed results saved in: demo_results/")
            print(f"📄 Logs: {len(result.logs)} log entries recorded")
            
        else:
            print("❌ Demo test failed!")
            print(f"Error: {result.error_message}")
        
        print("\n🎯 Demo completed!")
        return 0
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure all required modules are available")
        return 1
    except Exception as e:
        print(f"❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())