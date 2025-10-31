# Telemetry System (FT-008)

The UtilityFog telemetry system provides comprehensive metrics collection with real-time monitoring capabilities.

## Quick Start

```python
from utilityfog_frontend.telemetry import TelemetryCollector, PrometheusAdapter

# Create collector
collector = TelemetryCollector(collection_interval=30.0)

# Register metrics
requests = collector.register_counter("http_requests_total", "Total HTTP requests")
memory = collector.register_gauge("memory_usage_bytes", "Memory usage")
latency = collector.register_histogram("request_duration_seconds", "Request latency")

# Start collection
await collector.start_collection()

# Export metrics
exporter = PrometheusAdapter("/tmp/metrics.prom")
await exporter.export_metrics(collector)
```

## Features

- **Real-time Metrics**: Counter, Gauge, and Histogram types
- **Multiple Exports**: Prometheus and JSON formats
- **System Integration**: Coordination, messaging, and health hooks
- **Thread-Safe**: Concurrent access with proper locking
- **75% Test Coverage**: Comprehensive validation

For complete documentation, see the telemetry module source code.
