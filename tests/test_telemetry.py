"""
Comprehensive tests for telemetry system.
"""

import asyncio
import pytest

from utilityfog_frontend.telemetry import (
    TelemetryCollector,
    PrometheusAdapter,
    JSONExporter,
    Counter,
    Gauge,
    Histogram,
)
from utilityfog_frontend.telemetry.collector import (
    setup_coordination_hooks,
    setup_messaging_hooks,
    setup_health_hooks,
)


class TestMetrics:
    """Test core metric types."""

    def test_counter_basic_operations(self):
        """Test counter increment and value retrieval."""
        counter = Counter("test_counter", "Test counter")

        # Initial value should be 0
        value = counter.get_value()
        assert value.value == 0.0

        # Increment by default amount (1.0)
        counter.increment()
        value = counter.get_value()
        assert value.value == 1.0

        # Increment by custom amount
        counter.increment(5.5)
        value = counter.get_value()
        assert value.value == 6.5

        # Test negative increment raises error
        with pytest.raises(ValueError):
            counter.increment(-1.0)

    def test_gauge_operations(self):
        """Test gauge set, increment, and decrement operations."""
        gauge = Gauge("test_gauge", "Test gauge")

        # Set value
        gauge.set(10.0)
        value = gauge.get_value()
        assert value.value == 10.0

        # Increment
        gauge.increment(5.0)
        value = gauge.get_value()
        assert value.value == 15.0

        # Decrement
        gauge.decrement(3.0)
        value = gauge.get_value()
        assert value.value == 12.0

    def test_histogram_observations(self):
        """Test histogram observation recording."""
        histogram = Histogram(
            "test_histogram", "Test histogram", buckets=[0.1, 0.5, 1.0, 5.0]
        )

        # Record some observations
        histogram.observe(0.05)  # Below first bucket
        histogram.observe(0.3)  # Between first and second bucket
        histogram.observe(2.0)  # Between third and fourth bucket

        values = histogram.get_value()

        # Should have bucket values plus sum and count
        assert len(values) == 6  # 4 buckets + sum + count

        # Check count
        count_value = next(v for v in values if v.labels.get("type") == "count")
        assert count_value.value == 3

        # Check sum
        sum_value = next(v for v in values if v.labels.get("type") == "sum")
        assert sum_value.value == 2.35  # 0.05 + 0.3 + 2.0


class TestTelemetryCollector:
    """Test telemetry collector functionality."""

    @pytest.fixture
    def collector(self):
        """Create a telemetry collector for testing."""
        return TelemetryCollector(collection_interval=0.1)

    def test_metric_registration(self, collector):
        """Test metric registration and retrieval."""
        # Register different metric types
        counter = collector.register_counter("test_counter", "Test counter")
        gauge = collector.register_gauge("test_gauge", "Test gauge")
        histogram = collector.register_histogram("test_histogram", "Test histogram")

        assert isinstance(counter, Counter)
        assert isinstance(gauge, Gauge)
        assert isinstance(histogram, Histogram)

        # Test retrieval
        assert collector.get_metric("test_counter") is counter
        assert collector.get_metric("test_gauge") is gauge
        assert collector.get_metric("test_histogram") is histogram
        assert collector.get_metric("nonexistent") is None

        # Test duplicate registration raises error
        with pytest.raises(ValueError):
            collector.register_counter("test_counter", "Duplicate")

    def test_event_recording(self, collector):
        """Test event recording and retrieval."""
        # Record some events
        collector.record_event("test_event", {"key": "value"})
        collector.record_event("another_event", 42, labels={"type": "number"})

        events = collector.get_events()
        assert len(events) >= 2

        # Check event properties
        test_event = next(e for e in events if e.name == "test_event")
        assert test_event.value == {"key": "value"}

        number_event = next(e for e in events if e.name == "another_event")
        assert number_event.value == 42
        assert number_event.labels["type"] == "number"

    def test_hooks(self, collector):
        """Test hook registration and triggering."""
        hook_calls = []

        def test_hook(data):
            hook_calls.append(data)

        # Add hook
        collector.add_hook("test", test_hook)

        # Trigger hook by recording event
        collector.record_event("test", "data")

        # Hook should have been called
        assert len(hook_calls) > 0

    @pytest.mark.asyncio
    async def test_collection_lifecycle(self, collector):
        """Test starting and stopping collection."""
        assert not collector._running

        # Start collection
        await collector.start_collection()
        assert collector._running

        # Let it run briefly
        await asyncio.sleep(0.2)

        # Stop collection
        await collector.stop_collection()
        assert not collector._running

    def test_snapshot(self, collector):
        """Test telemetry snapshot generation."""
        # Register some metrics and record events
        counter = collector.register_counter("test_counter")
        counter.increment(5)

        collector.record_event("test_event", "data")

        snapshot = collector.get_snapshot()

        assert "timestamp" in snapshot
        assert "metrics" in snapshot
        assert "events_count" in snapshot
        assert "running" in snapshot

        # Check metric data
        assert "test_counter" in snapshot["metrics"]
        assert snapshot["metrics"]["test_counter"]["value"] == 5.0


class TestSystemHooks:
    """Test system integration hooks."""

    @pytest.fixture
    def collector(self):
        return TelemetryCollector()

    def test_coordination_hooks(self, collector):
        """Test coordination system hooks."""
        setup_coordination_hooks(collector)

        # Check that coordination metrics were registered
        assert collector.get_metric("coordination_messages_total") is not None
        assert collector.get_metric("coordination_active_nodes") is not None
        assert collector.get_metric("coordination_message_latency_seconds") is not None

    def test_messaging_hooks(self, collector):
        """Test messaging system hooks."""
        setup_messaging_hooks(collector)

        # Check that messaging metrics were registered
        assert collector.get_metric("messages_sent_total") is not None
        assert collector.get_metric("messages_received_total") is not None
        assert collector.get_metric("message_queue_size") is not None
        assert collector.get_metric("message_processing_duration_seconds") is not None

    def test_health_hooks(self, collector):
        """Test health monitoring hooks."""
        setup_health_hooks(collector)

        # Check that health metrics were registered
        assert collector.get_metric("health_status") is not None
        assert collector.get_metric("health_checks_total") is not None
        assert collector.get_metric("health_check_duration_seconds") is not None


class TestExporters:
    """Test metrics exporters."""

    @pytest.fixture
    def collector_with_metrics(self):
        """Create collector with sample metrics."""
        collector = TelemetryCollector()

        # Add some metrics
        counter = collector.register_counter("test_counter", "Test counter")
        counter.increment(10)

        gauge = collector.register_gauge("test_gauge", "Test gauge")
        gauge.set(42.5)

        histogram = collector.register_histogram("test_histogram", "Test histogram")
        histogram.observe(0.1)
        histogram.observe(0.5)

        return collector

    @pytest.mark.asyncio
    async def test_prometheus_exporter(self, collector_with_metrics, tmp_path):
        """Test Prometheus format export."""
        output_file = tmp_path / "metrics.prom"
        exporter = PrometheusAdapter(str(output_file))

        success = await exporter.export_metrics(collector_with_metrics)
        assert success

        # Check that file was created and contains expected content
        assert output_file.exists()
        content = output_file.read_text()

        assert "# HELP test_counter Test counter" in content
        assert "# TYPE test_counter counter" in content
        assert "test_counter 10.0" in content

        assert "# HELP test_gauge Test gauge" in content
        assert "# TYPE test_gauge gauge" in content
        assert "test_gauge 42.5" in content

    @pytest.mark.asyncio
    async def test_json_exporter(self, collector_with_metrics, tmp_path):
        """Test JSON format export."""
        output_file = tmp_path / "metrics.json"
        exporter = JSONExporter(str(output_file))

        success = await exporter.export_metrics(collector_with_metrics)
        assert success

        # Check that file was created
        assert output_file.exists()

        # Parse and validate JSON content
        import json

        with open(output_file) as f:
            data = json.load(f)

        assert "timestamp" in data
        assert "metrics" in data
        assert "test_counter" in data["metrics"]
        assert "test_gauge" in data["metrics"]
        assert data["metrics"]["test_counter"]["value"] == 10.0
        assert data["metrics"]["test_gauge"]["value"] == 42.5


class TestIntegration:
    """Integration tests for complete telemetry system."""

    @pytest.mark.asyncio
    async def test_full_telemetry_workflow(self):
        """Test complete telemetry collection and export workflow."""
        collector = TelemetryCollector(collection_interval=0.1)

        # Set up system hooks
        setup_coordination_hooks(collector)
        setup_messaging_hooks(collector)
        setup_health_hooks(collector)

        # Start collection
        await collector.start_collection()

        # Simulate some system activity
        collector.record_event("coordination_message", {"node_id": "test"})
        collector.record_event("message_sent", {"to": "node1", "size": 100})
        collector.record_event("health_check", {"status": "HEALTHY"})

        # Let collection run
        await asyncio.sleep(0.2)

        # Export metrics
        exporter = JSONExporter()
        success = await exporter.export_metrics(collector)
        assert success

        # Stop collection
        await collector.stop_collection()

        # Verify metrics were collected
        snapshot = collector.get_snapshot()
        assert len(snapshot["metrics"]) > 0
        assert snapshot["events_count"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
