
"""
Comprehensive tests for FT-010 Observability System
Tests structured logging, tracing, rate limiting, and telemetry integration.
"""

import pytest
import json
import time
import threading
import logging
from unittest.mock import patch, MagicMock
from io import StringIO
import sys

# Import the observability modules
sys.path.append('/home/ubuntu/github_repos/UtilityFog-Fractal-TreeOpen/UtilityFog_Agent_Package')
from agent.observability import (
    TraceContext, StructuredLogger, RateLimitedErrorLogger,
    EventLogger, TracingDecorator, ObservabilityManager,
    get_observability_manager, initialize_observability,
    trace_operation, log_simulation_event, trace_function
)
from agent.telemetry_collector import TelemetryCollector, get_telemetry_collector


class TestTraceContext:
    """Test trace context functionality."""
    
    def test_trace_id_generation(self):
        """Test trace ID generation."""
        context = TraceContext()
        trace_id = context.generate_trace_id()
        
        assert trace_id.startswith("trace_")
        assert len(trace_id) == 22  # "trace_" + 16 hex chars
    
    def test_trace_id_storage(self):
        """Test trace ID storage and retrieval."""
        context = TraceContext()
        test_trace_id = "test_trace_123"
        
        # Initially no trace ID
        assert context.get_trace_id() is None
        
        # Set and retrieve trace ID
        context.set_trace_id(test_trace_id)
        assert context.get_trace_id() == test_trace_id
        
        # Clear trace ID
        context.clear_trace_id()
        assert context.get_trace_id() is None
    
    def test_thread_isolation(self):
        """Test that trace IDs are isolated between threads."""
        context = TraceContext()
        results = {}
        
        def set_trace_in_thread(thread_id, trace_id):
            context.set_trace_id(trace_id)
            time.sleep(0.1)  # Allow other threads to run
            results[thread_id] = context.get_trace_id()
        
        # Start multiple threads with different trace IDs
        threads = []
        for i in range(3):
            thread = threading.Thread(
                target=set_trace_in_thread,
                args=(i, f"trace_{i}")
            )
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify each thread maintained its own trace ID
        assert results[0] == "trace_0"
        assert results[1] == "trace_1"
        assert results[2] == "trace_2"


class TestStructuredLogger:
    """Test structured logging functionality."""
    
    def test_json_log_format(self):
        """Test that logs are formatted as JSON."""
        # Capture log output
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        # Replace the handler to capture output
        logger.logger.handlers[0].stream = log_capture
        
        logger.info("Test message", key1="value1", key2=42)
        
        log_output = log_capture.getvalue().strip()
        log_data = json.loads(log_output)
        
        assert log_data['level'] == 'INFO'
        assert log_data['message'] == 'Test message'
        assert log_data['key1'] == 'value1'
        assert log_data['key2'] == 42
        assert 'timestamp' in log_data
    
    def test_trace_id_propagation(self):
        """Test trace ID propagation in logs."""
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        logger.logger.handlers[0].stream = log_capture
        
        # Set trace ID
        trace_id = "test_trace_123"
        logger.trace_context.set_trace_id(trace_id)
        
        logger.info("Test message with trace")
        
        log_output = log_capture.getvalue().strip()
        log_data = json.loads(log_output)
        
        assert log_data['trace_id'] == trace_id
    
    def test_exception_logging(self):
        """Test exception logging with structured format."""
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        logger.logger.handlers[0].stream = log_capture
        
        try:
            raise ValueError("Test exception")
        except ValueError:
            # Use the logger's error method with exc_info
            logger.logger.error("Error occurred", exc_info=True)
        
        log_output = log_capture.getvalue().strip()
        log_data = json.loads(log_output)
        
        assert 'exception' in log_data
        assert log_data['exception']['type'] == 'ValueError'
        assert log_data['exception']['message'] == 'Test exception'


class TestRateLimitedErrorLogger:
    """Test rate-limited error logging."""
    
    def test_rate_limiting(self):
        """Test that error logging is rate limited."""
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        logger.logger.handlers[0].stream = log_capture
        
        rate_limiter = RateLimitedErrorLogger(logger, max_errors_per_minute=2)
        
        # Log errors up to the limit
        assert rate_limiter.log_error("test_error", "Error 1") is True
        assert rate_limiter.log_error("test_error", "Error 2") is True
        
        # Further errors should be rate limited
        assert rate_limiter.log_error("test_error", "Error 3") is False
        assert rate_limiter.log_error("test_error", "Error 4") is False
        
        # Different error keys should not be affected
        assert rate_limiter.log_error("other_error", "Other error") is True
    
    def test_rate_limit_reset(self):
        """Test that rate limits reset after time window."""
        logger = StructuredLogger("test_logger")
        rate_limiter = RateLimitedErrorLogger(logger, max_errors_per_minute=1)
        
        # Log error to reach limit
        assert rate_limiter.log_error("test_error", "Error 1") is True
        assert rate_limiter.log_error("test_error", "Error 2") is False
        
        # Simulate time passage by manipulating the error queue
        with rate_limiter.lock:
            rate_limiter.error_counts["test_error"].clear()
        
        # Should be able to log again
        assert rate_limiter.log_error("test_error", "Error after reset") is True


class TestEventLogger:
    """Test event logging functionality."""
    
    def test_event_logging(self):
        """Test basic event logging."""
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        logger.logger.handlers[0].stream = log_capture
        
        event_logger = EventLogger(logger)
        
        event_data = {"param1": "value1", "param2": 42}
        event_logger.log_event("test_event", event_data)
        
        log_output = log_capture.getvalue().strip()
        log_data = json.loads(log_output)
        
        assert log_data['event_type'] == 'test_event'
        assert log_data['event_data'] == event_data
        assert log_data['event_count'] == 1
    
    def test_event_counting(self):
        """Test event counting functionality."""
        logger = StructuredLogger("test_logger")
        event_logger = EventLogger(logger)
        
        # Log multiple events of same type
        event_logger.log_event("test_event", {})
        event_logger.log_event("test_event", {})
        event_logger.log_event("other_event", {})
        
        counts = event_logger.get_event_counts()
        assert counts["test_event"] == 2
        assert counts["other_event"] == 1


class TestTracingDecorator:
    """Test function tracing decorator."""
    
    def test_function_tracing(self):
        """Test function tracing with decorator."""
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        logger.logger.handlers[0].stream = log_capture
        
        tracer = TracingDecorator(logger)
        
        @tracer.trace_function("test_operation")
        def test_function(x, y):
            return x + y
        
        result = test_function(1, 2)
        assert result == 3
        
        log_output = log_capture.getvalue()
        assert "Starting operation: test_operation" in log_output
        assert "Completed operation: test_operation" in log_output
    
    def test_function_tracing_with_exception(self):
        """Test function tracing when exception occurs."""
        log_capture = StringIO()
        
        logger = StructuredLogger("test_logger")
        logger.logger.handlers[0].stream = log_capture
        
        tracer = TracingDecorator(logger)
        
        @tracer.trace_function("failing_operation")
        def failing_function():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            failing_function()
        
        log_output = log_capture.getvalue()
        assert "Starting operation: failing_operation" in log_output
        assert "Failed operation: failing_operation" in log_output


class TestObservabilityManager:
    """Test the main observability manager."""
    
    def test_trace_operation_context(self):
        """Test trace operation context manager."""
        manager = ObservabilityManager()
        
        with manager.trace_operation("test_operation", param1="value1") as trace_id:
            assert trace_id is not None
            assert trace_id.startswith("trace_")
            
            # Trace ID should be available in context
            current_trace = manager.logger.trace_context.get_trace_id()
            assert current_trace == trace_id
    
    def test_metrics_collection(self):
        """Test metrics collection and summary."""
        manager = ObservabilityManager()
        
        # Perform some traced operations
        with manager.trace_operation("op1"):
            time.sleep(0.01)
        
        with manager.trace_operation("op2"):
            time.sleep(0.01)
        
        # Get metrics summary
        metrics = manager.get_metrics_summary()
        
        assert metrics['operations']['operations_started'] == 2
        assert metrics['operations']['operations_completed'] == 2
        assert metrics['operations']['operations_failed'] == 0
        assert metrics['average_operation_duration'] > 0
    
    def test_simulation_event_logging(self):
        """Test simulation event logging."""
        log_capture = StringIO()
        
        manager = ObservabilityManager()
        manager.logger.logger.handlers[0].stream = log_capture
        
        manager.log_simulation_event("agent_created", agent_id=123, position=[1, 2, 3])
        
        log_output = log_capture.getvalue().strip()
        log_data = json.loads(log_output)
        
        assert log_data['event_type'] == 'agent_created'
        assert log_data['event_data']['agent_id'] == 123
        assert log_data['event_data']['position'] == [1, 2, 3]


class TestTelemetryIntegration:
    """Test telemetry collector integration with observability."""
    
    def test_telemetry_collector_initialization(self):
        """Test telemetry collector initialization with observability."""
        collector = TelemetryCollector()
        
        # Should have observability manager
        assert collector.observability is not None
        
        # Should log initialization event
        metrics = collector.get_current_metrics()
        assert 'observability' in metrics
    
    def test_metric_collection_with_tracing(self):
        """Test metric collection with observability tracing."""
        log_capture = StringIO()
        
        collector = TelemetryCollector()
        collector.observability.logger.logger.handlers[0].stream = log_capture
        
        collector.collect_metric("test_metric", 42.0, source="test")
        
        # Check that metric was collected
        metrics = collector.get_current_metrics()
        assert metrics['metrics']['test_metric'] == 42.0
        
        # Check that event was logged
        log_output = log_capture.getvalue()
        assert "metric_collected" in log_output
    
    def test_performance_metric_collection(self):
        """Test performance metric collection with observability."""
        collector = TelemetryCollector()
        
        collector.collect_performance_metric("test_operation", 0.5, success=True)
        collector.collect_performance_metric("test_operation", 0.3, success=False)
        
        summary = collector.get_performance_summary()
        
        assert 'test_operation' in summary['performance_metrics']
        perf_data = summary['performance_metrics']['test_operation']
        
        assert perf_data['total_operations'] == 2
        assert perf_data['successful_operations'] == 1
        assert perf_data['failed_operations'] == 1
        assert perf_data['success_rate'] == 0.5


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_global_observability_manager(self):
        """Test global observability manager access."""
        manager1 = get_observability_manager()
        manager2 = get_observability_manager()
        
        # Should return the same instance
        assert manager1 is manager2
    
    def test_global_telemetry_collector(self):
        """Test global telemetry collector access."""
        collector1 = get_telemetry_collector()
        collector2 = get_telemetry_collector()
        
        # Should return the same instance
        assert collector1 is collector2
    
    def test_convenience_functions(self):
        """Test convenience functions."""
        log_capture = StringIO()
        
        manager = get_observability_manager()
        manager.logger.logger.handlers[0].stream = log_capture
        
        # Test trace operation
        with trace_operation("test_op"):
            pass
        
        # Test event logging
        log_simulation_event("test_event", data="test")
        
        log_output = log_capture.getvalue()
        assert "test_op" in log_output
        assert "test_event" in log_output


class TestCoverageRequirements:
    """Tests to ensure ≥90% coverage requirements."""
    
    def test_error_handling_coverage(self):
        """Test error handling paths for coverage."""
        manager = ObservabilityManager()
        
        # Test operation failure
        try:
            with manager.trace_operation("failing_op"):
                raise RuntimeError("Test error")
        except RuntimeError:
            pass
        
        metrics = manager.get_metrics_summary()
        assert metrics['operations']['operations_failed'] == 1
    
    def test_edge_cases_coverage(self):
        """Test edge cases for coverage."""
        # Test empty metric collection
        collector = TelemetryCollector()
        summary = collector.get_performance_summary()
        assert summary['performance_metrics'] == {}
        
        # Test metrics reset
        collector.collect_metric("test", 1.0)
        collector.reset_metrics()
        metrics = collector.get_current_metrics()
        assert len(metrics['metrics']) == 0
    
    def test_concurrent_access_coverage(self):
        """Test concurrent access for coverage."""
        manager = ObservabilityManager()
        results = []
        
        def concurrent_operation(op_id):
            with manager.trace_operation(f"concurrent_op_{op_id}"):
                time.sleep(0.01)
                results.append(op_id)
        
        threads = []
        for i in range(5):
            thread = threading.Thread(target=concurrent_operation, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        assert len(results) == 5
        metrics = manager.get_metrics_summary()
        assert metrics['operations']['operations_completed'] == 5
    
    def test_telemetry_collector_additional_coverage(self):
        """Test additional telemetry collector methods for coverage."""
        collector = TelemetryCollector()
        
        # Test metrics history retrieval
        collector.collect_metric("test_metric", 1.0)
        collector.collect_metric("test_metric", 2.0)
        collector.collect_metric("other_metric", 3.0)
        
        # Test filtered history
        history = collector.get_metrics_history(metric_name="test_metric")
        assert len(history) == 2
        
        # Test limited history
        history = collector.get_metrics_history(last_n=1)
        assert len(history) == 1
        
        # Test export functionality
        export_data = collector.export_metrics("json")
        assert export_data['format'] == 'json'
        assert 'current_metrics' in export_data
        assert 'performance_summary' in export_data
        assert 'full_history' in export_data
        
        # Test simulation metrics collection
        sim_data = {
            "agents_count": 100,
            "average_speed": 2.5,
            "collision_rate": 0.01,
            "non_numeric_data": "test"  # Should be ignored
        }
        collector.collect_simulation_metrics(sim_data)
        
        current_metrics = collector.get_current_metrics()
        assert current_metrics['metrics']['sim_agents_count'] == 100
        assert current_metrics['metrics']['sim_average_speed'] == 2.5
        assert current_metrics['metrics']['sim_collision_rate'] == 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
