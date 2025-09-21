"""
Telemetry collector for gathering system metrics and performance data.
"""

import asyncio
import time
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict
import logging

from .metrics import Metric, Counter, Gauge, Histogram


logger = logging.getLogger(__name__)


@dataclass
class TelemetryEvent:
    """A telemetry event with metadata."""

    name: str
    value: Any
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TelemetryCollector:
    """
    Central telemetry collector for gathering metrics and events.

    Provides hooks for coordination, messaging, and health monitoring systems.
    """

    def __init__(self, collection_interval: float = 30.0):
        self.collection_interval = collection_interval
        self._metrics: Dict[str, Metric] = {}
        self._events: List[TelemetryEvent] = []
        self._hooks: Dict[str, List[Callable]] = defaultdict(list)
        self._running = False
        self._lock = threading.RLock()
        self._collection_task: Optional[asyncio.Task] = None

        # Built-in system metrics
        self._init_system_metrics()

    def _init_system_metrics(self) -> None:
        """Initialize built-in system metrics."""
        self.register_counter(
            "telemetry_events_total", "Total number of telemetry events"
        )
        self.register_counter(
            "telemetry_collection_runs_total", "Total collection runs"
        )
        self.register_gauge("telemetry_metrics_count", "Number of registered metrics")
        self.register_histogram(
            "telemetry_collection_duration_seconds", "Collection duration"
        )

    def register_counter(
        self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None
    ) -> Counter:
        """Register a new counter metric."""
        with self._lock:
            if name in self._metrics:
                raise ValueError(f"Metric {name} already registered")

            counter = Counter(name, description, labels)
            self._metrics[name] = counter
            self._update_metrics_count()
            return counter

    def register_gauge(
        self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None
    ) -> Gauge:
        """Register a new gauge metric."""
        with self._lock:
            if name in self._metrics:
                raise ValueError(f"Metric {name} already registered")

            gauge = Gauge(name, description, labels)
            self._metrics[name] = gauge
            self._update_metrics_count()
            return gauge

    def register_histogram(
        self,
        name: str,
        description: str = "",
        buckets: Optional[List[float]] = None,
        labels: Optional[Dict[str, str]] = None,
    ) -> Histogram:
        """Register a new histogram metric."""
        with self._lock:
            if name in self._metrics:
                raise ValueError(f"Metric {name} already registered")

            histogram = Histogram(name, description, buckets, labels)
            self._metrics[name] = histogram
            self._update_metrics_count()
            return histogram

    def get_metric(self, name: str) -> Optional[Metric]:
        """Get a registered metric by name."""
        with self._lock:
            return self._metrics.get(name)

    def get_all_metrics(self) -> Dict[str, Metric]:
        """Get all registered metrics."""
        with self._lock:
            return self._metrics.copy()

    def record_event(
        self,
        name: str,
        value: Any,
        labels: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a telemetry event."""
        event = TelemetryEvent(
            name=name, value=value, labels=labels or {}, metadata=metadata or {}
        )

        with self._lock:
            self._events.append(event)
            # Keep only recent events (last 1000)
            if len(self._events) > 1000:
                self._events = self._events[-1000:]

        # Increment events counter
        if "telemetry_events_total" in self._metrics:
            metric = self._metrics["telemetry_events_total"]
            if isinstance(metric, Counter):
                metric.increment()

        # Trigger event hooks
        self._trigger_hooks(name, event)

    def get_events(self, limit: Optional[int] = None) -> List[TelemetryEvent]:
        """Get recent telemetry events."""
        with self._lock:
            events = self._events.copy()
            if limit:
                events = events[-limit:]
            return events

    def add_hook(self, hook_type: str, callback: Callable) -> None:
        """Add a hook callback for specific events."""
        with self._lock:
            self._hooks[hook_type].append(callback)

    def remove_hook(self, hook_type: str, callback: Callable) -> None:
        """Remove a hook callback."""
        with self._lock:
            if callback in self._hooks[hook_type]:
                self._hooks[hook_type].remove(callback)

    def _trigger_hooks(self, hook_type: str, data: Any) -> None:
        """Trigger all hooks of a specific type."""
        hooks = self._hooks.get(hook_type, [])
        for hook in hooks:
            try:
                hook(data)
            except Exception as e:
                logger.error(f"Error in telemetry hook {hook_type}: {e}")

    def _update_metrics_count(self) -> None:
        """Update the metrics count gauge."""
        if "telemetry_metrics_count" in self._metrics:
            metric = self._metrics["telemetry_metrics_count"]
            if isinstance(metric, Gauge):
                metric.set(len(self._metrics))

    async def start_collection(self) -> None:
        """Start periodic telemetry collection."""
        if self._running:
            return

        self._running = True
        self._collection_task = asyncio.create_task(self._collection_loop())
        logger.info(
            f"Started telemetry collection with {self.collection_interval}s interval"
        )

    async def stop_collection(self) -> None:
        """Stop periodic telemetry collection."""
        self._running = False
        if self._collection_task:
            self._collection_task.cancel()
            try:
                await self._collection_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped telemetry collection")

    async def _collection_loop(self) -> None:
        """Main collection loop."""
        while self._running:
            try:
                start_time = time.time()
                await self._collect_metrics()
                duration = time.time() - start_time

                # Record collection metrics
                if "telemetry_collection_runs_total" in self._metrics:
                    metric = self._metrics["telemetry_collection_runs_total"]
                    if isinstance(metric, Counter):
                        metric.increment()
                if "telemetry_collection_duration_seconds" in self._metrics:
                    metric = self._metrics["telemetry_collection_duration_seconds"]
                    if isinstance(metric, Histogram):
                        metric.observe(duration)

                # Trigger collection hooks
                self._trigger_hooks(
                    "collection",
                    {
                        "duration": duration,
                        "metrics_count": len(self._metrics),
                        "events_count": len(self._events),
                    },
                )

                await asyncio.sleep(self.collection_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in telemetry collection: {e}")
                await asyncio.sleep(1.0)  # Brief pause on error

    async def _collect_metrics(self) -> None:
        """Collect current metric values."""
        # This is where we would collect system metrics, but for now
        # we just trigger the collection event
        self.record_event(
            "collection_run",
            {
                "timestamp": time.time(),
                "metrics_count": len(self._metrics),
                "events_count": len(self._events),
            },
        )

    def get_snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of current telemetry state."""
        with self._lock:
            metrics_data: Dict[str, Any] = {}
            for name, metric in self._metrics.items():
                try:
                    value = metric.get_value()
                    if isinstance(value, list):
                        metrics_data[name] = [
                            {
                                "value": v.value,
                                "labels": v.labels,
                                "timestamp": v.timestamp,
                            }
                            for v in value
                        ]
                    else:
                        metrics_data[name] = {
                            "value": value.value,
                            "labels": value.labels,
                            "timestamp": value.timestamp,
                        }
                except Exception as e:
                    logger.error(f"Error getting metric {name}: {e}")
                    metrics_data[name] = {"error": str(e)}

            return {
                "timestamp": time.time(),
                "metrics": metrics_data,
                "events_count": len(self._events),
                "running": self._running,
            }

    def reset_all_metrics(self) -> None:
        """Reset all metrics to their initial state."""
        with self._lock:
            for metric in self._metrics.values():
                try:
                    metric.reset()
                except Exception as e:
                    logger.error(f"Error resetting metric {metric.name}: {e}")

            self._events.clear()
            logger.info("Reset all telemetry metrics and events")


# Coordination system hooks
def setup_coordination_hooks(collector: TelemetryCollector) -> None:
    """Set up telemetry hooks for coordination system."""
    # Register coordination metrics
    collector.register_counter(
        "coordination_messages_total", "Total coordination messages"
    )
    collector.register_gauge(
        "coordination_active_nodes", "Number of active coordination nodes"
    )
    collector.register_histogram(
        "coordination_message_latency_seconds", "Coordination message latency"
    )

    def on_coordination_message(message_data):
        collector.record_event("coordination_message", message_data)
        if "coordination_messages_total" in collector._metrics:
            collector._metrics["coordination_messages_total"].increment()

    collector.add_hook("coordination_message", on_coordination_message)


# Messaging system hooks
def setup_messaging_hooks(collector: TelemetryCollector) -> None:
    """Set up telemetry hooks for messaging system."""
    # Register messaging metrics
    collector.register_counter("messages_sent_total", "Total messages sent")
    collector.register_counter("messages_received_total", "Total messages received")
    collector.register_gauge("message_queue_size", "Current message queue size")
    collector.register_histogram(
        "message_processing_duration_seconds", "Message processing duration"
    )

    def on_message_sent(message_data):
        collector.record_event("message_sent", message_data)
        if "messages_sent_total" in collector._metrics:
            collector._metrics["messages_sent_total"].increment()

    def on_message_received(message_data):
        collector.record_event("message_received", message_data)
        if "messages_received_total" in collector._metrics:
            collector._metrics["messages_received_total"].increment()

    collector.add_hook("message_sent", on_message_sent)
    collector.add_hook("message_received", on_message_received)


# Health system hooks
def setup_health_hooks(collector: TelemetryCollector) -> None:
    """Set up telemetry hooks for health monitoring system."""
    # Register health metrics
    collector.register_gauge(
        "health_status",
        "Current health status (0=unknown, 1=healthy, 2=degraded, 3=unhealthy)",
    )
    collector.register_counter("health_checks_total", "Total health checks performed")
    collector.register_histogram(
        "health_check_duration_seconds", "Health check duration"
    )

    def on_health_check(health_data):
        collector.record_event("health_check", health_data)
        if "health_checks_total" in collector._metrics:
            collector._metrics["health_checks_total"].increment()

        # Map health status to numeric value
        status_map = {"UNKNOWN": 0, "HEALTHY": 1, "DEGRADED": 2, "UNHEALTHY": 3}
        status_value = status_map.get(health_data.get("status", "UNKNOWN"), 0)
        if "health_status" in collector._metrics:
            collector._metrics["health_status"].set(status_value)

    collector.add_hook("health_check", on_health_check)
