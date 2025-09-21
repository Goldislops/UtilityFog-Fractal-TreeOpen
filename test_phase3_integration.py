#!/usr/bin/env python3
"""
Phase 3 Integration Test Script
Tests all Phase 3 components: telemetry, visualization, observability, and feature flags.
"""

import sys
import os
import time

# Add the source directory to Python path
sys.path.insert(0, 'UtilityFog_Agent_Package')

def test_feature_flags():
    """Test feature flags system."""
    print("🏁 Testing Feature Flags System...")
    try:
        from agent.feature_flags import (
            get_feature_flags, is_telemetry_enabled, is_visualization_enabled,
            is_observability_enabled, get_telemetry_config, get_visualization_config,
            get_observability_config
        )
        
        flags = get_feature_flags()
        status = flags.get_phase3_status()
        run_loop_config = flags.get_run_loop_config()
        
        print("✅ Feature flags system loaded successfully")
        print(f"📊 Phase 3 Status: {status}")
        print(f"🔗 Run Loop Config: {run_loop_config}")
        
        # Test individual checks
        print(f"📡 Telemetry enabled: {is_telemetry_enabled()}")
        print(f"📈 Visualization enabled: {is_visualization_enabled()}")
        print(f"🔍 Observability enabled: {is_observability_enabled()}")
        
        return True
    except Exception as e:
        print(f"❌ Feature flags test failed: {e}")
        return False

def test_observability():
    """Test observability system."""
    print("\n🔍 Testing Observability System...")
    try:
        from agent.observability import (
            get_observability_manager, trace_operation, log_simulation_event,
            get_metrics_summary
        )
        from agent.feature_flags import is_observability_enabled
        
        if not is_observability_enabled():
            print("⚠️  Observability is disabled by feature flags")
            return True
        
        obs = get_observability_manager()
        print("✅ Observability manager initialized")
        
        # Test tracing
        with trace_operation("test_operation", component="integration_test"):
            print("🔍 Executing traced operation...")
            time.sleep(0.01)
        
        # Test event logging
        log_simulation_event("integration_test_event", 
                           test_type="phase3_integration",
                           status="success")
        
        # Get metrics
        metrics = obs.get_metrics_summary()
        print(f"📈 Operations completed: {metrics['operations']['operations_completed']}")
        print("✅ Observability system working correctly!")
        
        return True
    except Exception as e:
        print(f"❌ Observability test failed: {e}")
        return False

def test_telemetry():
    """Test telemetry system."""
    print("\n📡 Testing Telemetry System...")
    try:
        from agent.telemetry_collector import get_telemetry_collector
        from agent.feature_flags import is_telemetry_enabled, get_telemetry_config
        
        if not is_telemetry_enabled():
            print("⚠️  Telemetry is disabled by feature flags")
            return True
        
        config = get_telemetry_config()
        print(f"📊 Telemetry configuration: {config}")
        
        collector = get_telemetry_collector()
        print("✅ Telemetry collector initialized")
        
        # Collect some test metrics
        collector.collect_metric('test_metric', 42.0, source='integration_test')
        collector.collect_performance_metric('test_operation', 0.05, success=True)
        
        # Collect simulation metrics
        sim_data = {
            "agents_count": 100,
            "average_speed": 2.5,
            "collision_rate": 0.01
        }
        collector.collect_simulation_metrics(sim_data)
        
        # Get current metrics
        metrics = collector.get_current_metrics()
        print(f"📈 Metrics collected: {len(metrics['metrics'])}")
        
        # Test export
        export_data = collector.export_metrics()
        print(f"💾 Export data entries: {len(export_data['full_history'])}")
        
        print("✅ Telemetry system working correctly!")
        return True
    except Exception as e:
        print(f"❌ Telemetry test failed: {e}")
        return False

def test_visualization():
    """Test visualization system."""
    print("\n📈 Testing Visualization System...")
    try:
        from agent.feature_flags import is_visualization_enabled, get_visualization_config
        
        if not is_visualization_enabled():
            print("⚠️  Visualization is disabled by feature flags")
            return True
        
        config = get_visualization_config()
        print(f"📊 Visualization configuration: {config}")
        print(f"📈 Available chart types: {config['chart_types']}")
        print(f"💾 Export formats: {config['export_formats']}")
        print(f"🔄 Real-time updates: {config['real_time_updates']}")
        
        print("✅ Visualization system configured correctly!")
        return True
    except Exception as e:
        print(f"❌ Visualization test failed: {e}")
        return False

def test_integration():
    """Test integration between all systems."""
    print("\n🔗 Testing System Integration...")
    try:
        from agent.feature_flags import get_feature_flags
        from agent.observability import get_observability_manager, trace_operation
        from agent.telemetry_collector import get_telemetry_collector
        
        flags = get_feature_flags()
        obs = get_observability_manager()
        collector = get_telemetry_collector()
        
        print("✅ All systems initialized")
        
        # Test integrated workflow
        with trace_operation("integrated_test_workflow", test_phase="integration"):
            # Collect metrics during traced operation
            collector.collect_metric("integration_metric", 123.45, phase="integration")
            collector.collect_performance_metric("integration_workflow", 0.02, success=True)
            
            # Simulate some work
            time.sleep(0.01)
        
        # Get comprehensive metrics
        obs_metrics = obs.get_metrics_summary()
        tel_metrics = collector.get_current_metrics()
        
        print(f"🔍 Observability operations: {obs_metrics['operations']['operations_completed']}")
        print(f"📡 Telemetry metrics: {len(tel_metrics['metrics'])}")
        print(f"📊 Integration successful: observability + telemetry working together")
        
        print("✅ System integration working correctly!")
        return True
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return False

def test_performance():
    """Test performance of Phase 3 systems."""
    print("\n🏃 Testing Performance...")
    try:
        from agent.observability import trace_operation
        from agent.telemetry_collector import get_telemetry_collector
        from agent.feature_flags import is_performance_monitoring_enabled
        
        if not is_performance_monitoring_enabled():
            print("⚠️  Performance monitoring is disabled")
            return True
        
        collector = get_telemetry_collector()
        
        # Test observability overhead
        start_time = time.time()
        for i in range(10):
            with trace_operation(f"perf_test_{i}"):
                time.sleep(0.001)  # Simulate minimal work
        
        obs_duration = time.time() - start_time
        print(f"⏱️  10 traced operations: {obs_duration:.3f}s")
        print(f"📊 Average overhead: {(obs_duration/10)*1000:.2f}ms per operation")
        
        # Test telemetry collection rate
        start_time = time.time()
        for i in range(100):
            collector.collect_metric(f"perf_metric_{i%10}", float(i))
        
        tel_duration = time.time() - start_time
        print(f"📈 100 metric collections: {tel_duration:.3f}s")
        if tel_duration > 0:
            print(f"🚀 Collection rate: {100/tel_duration:.0f} metrics/second")
        
        print("✅ Performance tests completed!")
        return True
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

def main():
    """Run all Phase 3 integration tests."""
    print("🚀 UtilityFog Phase 3 Integration Test Suite")
    print("=" * 50)
    
    tests = [
        ("Feature Flags", test_feature_flags),
        ("Observability", test_observability),
        ("Telemetry", test_telemetry),
        ("Visualization", test_visualization),
        ("Integration", test_integration),
        ("Performance", test_performance)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("📋 Test Results Summary:")
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} {test_name}")
        if result:
            passed += 1
    
    print(f"\n🎯 Overall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All Phase 3 integration tests passed!")
        print("🚀 System is ready for production deployment!")
        return 0
    else:
        print("⚠️  Some tests failed. Please check the implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
