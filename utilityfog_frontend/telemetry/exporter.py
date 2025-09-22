"""
Metrics exporter with Prometheus adapter for telemetry system.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging
import json

from .collector import TelemetryCollector
from .metrics import Metric, Counter, Gauge, Histogram, MetricValue


logger = logging.getLogger(__name__)


@dataclass
class ExportedMetric:
    """A metric prepared for export."""

    name: str
    metric_type: str
    description: str
    values: List[Dict[str, Any]]
    timestamp: float


class MetricsExporter(ABC):
    """Abstract base class for metrics exporters."""

    @abstractmethod
    async def export_metrics(self, collector: TelemetryCollector) -> bool:
        """Export metrics from the collector. Returns True on success."""
        pass

    @abstractmethod
    def format_metric(self, name: str, metric: Metric) -> Optional[ExportedMetric]:
        """Format a single metric for export."""
        pass


class PrometheusAdapter(MetricsExporter):
    """
    Prometheus-compatible metrics exporter.

    Exports metrics in Prometheus text format for scraping.
    """

    def __init__(self, output_file: Optional[str] = None):
        self.output_file = output_file
        self._last_export = 0.0

    async def export_metrics(self, collector: TelemetryCollector) -> bool:
        """Export metrics in Prometheus format."""
        try:
            metrics = collector.get_all_metrics()
            exported_metrics = []

            for name, metric in metrics.items():
                exported_metric = self.format_metric(name, metric)
                if exported_metric:
                    exported_metrics.append(exported_metric)

            # Generate Prometheus format
            prometheus_text = self._generate_prometheus_text(exported_metrics)

            if self.output_file:
                with open(self.output_file, "w") as f:
                    f.write(prometheus_text)
            else:
                # Log the metrics (in production, this would be served via HTTP)
                logger.info(f"Exported {len(exported_metrics)} metrics")

            self._last_export = time.time()
            return True

        except Exception as e:
            logger.error(f"Error exporting metrics: {e}")
            return False

    def format_metric(self, name: str, metric: Metric) -> Optional[ExportedMetric]:
        """Format a metric for Prometheus export."""
        try:
            value = metric.get_value()

            if isinstance(metric, Counter):
                metric_type = "counter"
                if isinstance(value, MetricValue):
                    values = [{"value": value.value, "labels": value.labels}]
                else:
                    values = []

            elif isinstance(metric, Gauge):
                metric_type = "gauge"
                if isinstance(value, MetricValue):
                    values = [{"value": value.value, "labels": value.labels}]
                else:
                    values = []

            elif isinstance(metric, Histogram):
                metric_type = "histogram"
                if isinstance(value, list):
                    values = [{"value": v.value, "labels": v.labels} for v in value]
                else:
                    values = []

            else:
                logger.warning(f"Unknown metric type for {name}")
                return None

            return ExportedMetric(
                name=name,
                metric_type=metric_type,
                description=metric.description,
                values=values,
                timestamp=time.time(),
            )

        except Exception as e:
            logger.error(f"Error formatting metric {name}: {e}")
            return None

    def _generate_prometheus_text(self, metrics: List[ExportedMetric]) -> str:
        """Generate Prometheus text format from exported metrics."""
        lines = []

        for metric in metrics:
            # Add HELP line
            if metric.description:
                lines.append(f"# HELP {metric.name} {metric.description}")

            # Add TYPE line
            lines.append(f"# TYPE {metric.name} {metric.metric_type}")

            # Add metric values
            for value_data in metric.values:
                labels_str = ""
                if value_data["labels"]:
                    label_pairs = [
                        f'{k}="{v}"' for k, v in value_data["labels"].items()
                    ]
                    labels_str = "{" + ",".join(label_pairs) + "}"

                lines.append(f"{metric.name}{labels_str} {value_data['value']}")

            lines.append("")  # Empty line between metrics

        return "\n".join(lines)

    def get_last_export_time(self) -> float:
        """Get the timestamp of the last successful export."""
        return self._last_export


class JSONExporter(MetricsExporter):
    """JSON format metrics exporter."""

    def __init__(self, output_file: Optional[str] = None, pretty: bool = True):
        self.output_file = output_file
        self.pretty = pretty
        self._last_export = 0.0

    async def export_metrics(self, collector: TelemetryCollector) -> bool:
        """Export metrics in JSON format."""
        try:
            snapshot = collector.get_snapshot()

            if self.output_file:
                with open(self.output_file, "w") as f:
                    if self.pretty:
                        json.dump(snapshot, f, indent=2)
                    else:
                        json.dump(snapshot, f)
            else:
                logger.info(
                    f"JSON metrics snapshot: {len(snapshot.get('metrics', {}))} metrics"
                )

            self._last_export = time.time()
            return True

        except Exception as e:
            logger.error(f"Error exporting JSON metrics: {e}")
            return False

    def format_metric(self, name: str, metric: Metric) -> Optional[ExportedMetric]:
        """Format metric for JSON export (not used in this implementation)."""
        # JSON exporter uses the collector's snapshot directly
        return None


class MultiExporter(MetricsExporter):
    """Exporter that delegates to multiple other exporters."""

    def __init__(self, exporters: List[MetricsExporter]):
        self.exporters = exporters

    async def export_metrics(self, collector: TelemetryCollector) -> bool:
        """Export metrics using all configured exporters."""
        results = []

        for exporter in self.exporters:
            try:
                result = await exporter.export_metrics(collector)
                results.append(result)
            except Exception as e:
                logger.error(f"Error in exporter {type(exporter).__name__}: {e}")
                results.append(False)

        # Return True if at least one exporter succeeded
        return any(results)

    def format_metric(self, name: str, metric: Metric) -> Optional[ExportedMetric]:
        """Format metric (delegates to first exporter)."""
        if self.exporters:
            return self.exporters[0].format_metric(name, metric)
        return None


class PeriodicExporter:
    """Wrapper that exports metrics periodically."""

    def __init__(
        self,
        exporter: MetricsExporter,
        collector: TelemetryCollector,
        interval: float = 60.0,
    ):
        self.exporter = exporter
        self.collector = collector
        self.interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start periodic export."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._export_loop())
        logger.info(f"Started periodic metrics export with {self.interval}s interval")

    async def stop(self) -> None:
        """Stop periodic export."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped periodic metrics export")

    async def _export_loop(self) -> None:
        """Main export loop."""
        while self._running:
            try:
                success = await self.exporter.export_metrics(self.collector)
                if not success:
                    logger.warning("Metrics export failed")

                await asyncio.sleep(self.interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic export: {e}")
                await asyncio.sleep(1.0)  # Brief pause on error


# Convenience functions for common export scenarios
async def export_to_prometheus(
    collector: TelemetryCollector, output_file: str = "/tmp/metrics.prom"
) -> bool:
    """Export metrics to Prometheus format file."""
    exporter = PrometheusAdapter(output_file)
    return await exporter.export_metrics(collector)


async def export_to_json(
    collector: TelemetryCollector, output_file: str = "/tmp/metrics.json"
) -> bool:
    """Export metrics to JSON format file."""
    exporter = JSONExporter(output_file)
    return await exporter.export_metrics(collector)


def create_default_exporter(
    prometheus_file: Optional[str] = None, json_file: Optional[str] = None
) -> MetricsExporter:
    """Create a default multi-exporter with common formats."""
    exporters: List[MetricsExporter] = []

    if prometheus_file:
        exporters.append(PrometheusAdapter(prometheus_file))

    if json_file:
        exporters.append(JSONExporter(json_file))

    if not exporters:
        # Default to JSON exporter without file output
        exporters.append(JSONExporter())

    if len(exporters) == 1:
        return exporters[0]
    else:
        return MultiExporter(exporters)
