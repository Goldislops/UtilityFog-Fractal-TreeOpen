"""
Core metrics types and data structures for telemetry system.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union
from collections import defaultdict
import threading


class MetricType(Enum):
    """Types of metrics supported by the telemetry system."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricValue:
    """A single metric value with timestamp and labels."""

    value: Union[int, float]
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)


class Metric(ABC):
    """Abstract base class for all metrics."""

    def __init__(
        self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None
    ):
        self.name = name
        self.description = description
        self.labels = labels or {}
        self._lock = threading.RLock()

    @abstractmethod
    def get_value(self) -> Union[MetricValue, List[MetricValue]]:
        """Get the current metric value(s)."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the metric to its initial state."""
        pass


class Counter(Metric):
    """A counter metric that only increases."""

    def __init__(
        self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None
    ):
        super().__init__(name, description, labels)
        self._value = 0.0

    def increment(
        self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Increment the counter by the specified amount."""
        if amount < 0:
            raise ValueError("Counter can only be incremented by non-negative values")

        with self._lock:
            self._value += amount

    def get_value(self) -> MetricValue:
        """Get the current counter value."""
        with self._lock:
            return MetricValue(value=self._value, labels=self.labels.copy())

    def reset(self) -> None:
        """Reset the counter to zero."""
        with self._lock:
            self._value = 0.0


class Gauge(Metric):
    """A gauge metric that can increase or decrease."""

    def __init__(
        self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None
    ):
        super().__init__(name, description, labels)
        self._value = 0.0

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set the gauge to a specific value."""
        with self._lock:
            self._value = value

    def increment(
        self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Increment the gauge by the specified amount."""
        with self._lock:
            self._value += amount

    def decrement(
        self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Decrement the gauge by the specified amount."""
        with self._lock:
            self._value -= amount

    def get_value(self) -> MetricValue:
        """Get the current gauge value."""
        with self._lock:
            return MetricValue(value=self._value, labels=self.labels.copy())

    def reset(self) -> None:
        """Reset the gauge to zero."""
        with self._lock:
            self._value = 0.0


class Histogram(Metric):
    """A histogram metric for tracking distributions of values."""

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: Optional[List[float]] = None,
        labels: Optional[Dict[str, str]] = None,
    ):
        super().__init__(name, description, labels)
        self.buckets = buckets or [
            0.005,
            0.01,
            0.025,
            0.05,
            0.1,
            0.25,
            0.5,
            1.0,
            2.5,
            5.0,
            10.0,
        ]
        self._bucket_counts: Dict[float, int] = defaultdict(int)
        self._sum = 0.0
        self._count = 0

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Record an observation in the histogram."""
        with self._lock:
            self._sum += value
            self._count += 1

            # Update bucket counts
            for bucket in self.buckets:
                if value <= bucket:
                    self._bucket_counts[bucket] += 1

    def get_value(self) -> List[MetricValue]:
        """Get histogram values including buckets, sum, and count."""
        with self._lock:
            values = []

            # Bucket values
            for bucket in sorted(self.buckets):
                values.append(
                    MetricValue(
                        value=self._bucket_counts[bucket],
                        labels={**self.labels, "le": str(bucket)},
                    )
                )

            # Sum and count
            values.append(
                MetricValue(value=self._sum, labels={**self.labels, "type": "sum"})
            )
            values.append(
                MetricValue(value=self._count, labels={**self.labels, "type": "count"})
            )

            return values

    def reset(self) -> None:
        """Reset the histogram to initial state."""
        with self._lock:
            self._bucket_counts.clear()
            self._sum = 0.0
            self._count = 0
