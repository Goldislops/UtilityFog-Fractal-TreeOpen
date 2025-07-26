"""
Simulation Metrics Module for UtilityFog-Fractal-TreeOpen Agent Simulation

This module provides comprehensive metrics collection, analysis, and visualization
capabilities for monitoring the agent-based memetic evolution simulation system.
It tracks performance, behavior patterns, and evolutionary dynamics.

Author: UtilityFog-Fractal-TreeOpen Project
License: MIT
"""

from typing import Dict, List, Any, Optional, Tuple, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
import time
import statistics
import json
import csv
from collections import defaultdict, deque
from abc import ABC, abstractmethod
import numpy as np
import pandas as pd

from meme_structure import Meme, MemeType
from foglet_agent import FogletAgent, AgentState
from evolution_engine import GenerationStats
from network_topology import FractalNetwork, NetworkNode


class MetricType(Enum):
    """Enumeration of different metric categories."""
    PERFORMANCE = "performance"
    BEHAVIORAL = "behavioral"
    EVOLUTIONARY = "evolutionary"
    NETWORK = "network"
    ENERGY = "energy"
    SOCIAL = "social"
    TEMPORAL = "temporal"


class AggregationType(Enum):
    """Enumeration of metric aggregation methods."""
    SUM = "sum"
    AVERAGE = "average"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    STD = "std"
    COUNT = "count"
    RATE = "rate"


@dataclass
class MetricDefinition:
    """Definition of a metric to be collected and analyzed."""
    name: str
    metric_type: MetricType
    description: str
    unit: str = "count"
    aggregation: AggregationType = AggregationType.AVERAGE
    collection_frequency: float = 1.0
    retention_period: float = 3600.0
    thresholds: Dict[str, float] = field(default_factory=dict)


@dataclass
class MetricDataPoint:
    """A single data point for a metric."""
    timestamp: float
    value: Union[int, float, str, bool]
    tags: Dict[str, str] = field(default_factory=dict)
    source_id: Optional[str] = None


class MetricCollector(ABC):
    """Abstract base class for metric collectors."""
    
    @abstractmethod
    def collect_metrics(
        self,
        entities: List[Any],
        timestamp: float
    ) -> List[Tuple[str, MetricDataPoint]]:
        pass


class AgentMetricCollector(MetricCollector):
    """Collector for agent-related metrics."""
    
    def collect_metrics(
        self,
        entities: List[FogletAgent],
        timestamp: float
    ) -> List[Tuple[str, MetricDataPoint]]:
        metrics = []
        
        for agent in entities:
            agent_id = agent.agent_id
            
            metrics.append((
                "agent_energy_level",
                MetricDataPoint(timestamp, agent.energy_level, source_id=agent_id)
            ))
            
            metrics.append((
                "agent_health",
                MetricDataPoint(timestamp, agent.health, source_id=agent_id)
            ))
            
            metrics.append((
                "agent_age",
                MetricDataPoint(timestamp, agent.age, source_id=agent_id)
            ))
            
            for metric_name, value in agent.performance_metrics.items():
                metrics.append((
                    f"agent_{metric_name}",
                    MetricDataPoint(timestamp, value, source_id=agent_id)
                ))
            
            metrics.append((
                "agent_active_memes_count",
                MetricDataPoint(timestamp, len(agent.active_memes), source_id=agent_id)
            ))
        
        return metrics


class MemeMetricCollector(MetricCollector):
    """Collector for meme-related metrics."""
    
    def collect_metrics(
        self,
        entities: List[Meme],
        timestamp: float
    ) -> List[Tuple[str, MetricDataPoint]]:
        metrics = []
        
        for meme in entities:
            meme_id = meme.meme_id
            
            metrics.append((
                "meme_fitness_score",
                MetricDataPoint(
                    timestamp,
                    meme.fitness_score,
                    tags={"meme_type": meme.meme_type.value},
                    source_id=meme_id
                )
            ))
            
            metrics.append((
                "meme_propagation_count",
                MetricDataPoint(timestamp, meme.propagation_count, source_id=meme_id)
            ))
            
            metrics.append((
                "meme_generation",
                MetricDataPoint(timestamp, meme.generation, source_id=meme_id)
            ))
        
        return metrics


class SimulationMetrics:
    """Core metrics collection and analysis system for the simulation."""
    
    def __init__(
        self,
        collection_interval: float = 1.0,
        max_data_points: int = 10000,
        auto_cleanup: bool = True
    ):
        self.collection_interval = collection_interval
        self.max_data_points = max_data_points
        self.auto_cleanup = auto_cleanup
        
        self.metric_definitions: Dict[str, MetricDefinition] = {}
        self.metric_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_data_points))
        
        self.collectors: List[MetricCollector] = []
        self.entity_sources: Dict[str, List[Any]] = {}
        
        self.last_collection_time: float = 0.0
        self.collection_count: int = 0
        self.is_collecting: bool = False
        
        self.alert_callbacks: List[Callable[[str, MetricDataPoint, Dict[str, float]], None]] = []
        self.analysis_results: Dict[str, Dict[str, Any]] = {}
        
        self._initialize_default_metrics()
    
    def register_metric(self, metric_def: MetricDefinition) -> None:
        """Register a new metric definition."""
        self.metric_definitions[metric_def.name] = metric_def
        
        if metric_def.name not in self.metric_data:
            self.metric_data[metric_def.name] = deque(maxlen=self.max_data_points)
    
    def add_collector(self, collector: MetricCollector, entity_source_name: str) -> None:
        """Add a metric collector with its associated entity source."""
        self.collectors.append(collector)
        if entity_source_name not in self.entity_sources:
            self.entity_sources[entity_source_name] = []
    
    def collect_all_metrics(self, timestamp: Optional[float] = None) -> int:
        """Collect metrics from all registered collectors."""
        if timestamp is None:
            timestamp = time.time()
        
        if timestamp - self.last_collection_time < self.collection_interval:
            return 0
        
        self.is_collecting = True
        total_collected = 0
        
        try:
            for i, collector in enumerate(self.collectors):
                source_names = list(self.entity_sources.keys())
                if i < len(source_names):
                    entities = self.entity_sources[source_names[i]]
                    
                    collected_metrics = collector.collect_metrics(entities, timestamp)
                    
                    for metric_name, data_point in collected_metrics:
                        self._store_metric_data(metric_name, data_point)
                        total_collected += 1
            
            self.last_collection_time = timestamp
            self.collection_count += 1
        
        finally:
            self.is_collecting = False
        
        return total_collected
    
    def get_metric_data(
        self,
        metric_name: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[MetricDataPoint]:
        """Retrieve metric data for analysis or visualization."""
        if metric_name not in self.metric_data:
            return []
        
        data_points = list(self.metric_data[metric_name])
        
        if start_time is not None:
            data_points = [dp for dp in data_points if dp.timestamp >= start_time]
        
        if end_time is not None:
            data_points = [dp for dp in data_points if dp.timestamp <= end_time]
        
        return data_points
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive metrics report."""
        current_time = time.time()
        
        report = {
            'generated_at': current_time,
            'metrics': {},
            'summary': {
                'total_metrics': len(self.metric_definitions),
                'collection_count': self.collection_count,
                'last_collection': self.last_collection_time
            }
        }
        
        for metric_name in self.metric_definitions.keys():
            data_points = self.get_metric_data(metric_name)
            
            if data_points:
                report['metrics'][metric_name] = {
                    'data_points': len(data_points),
                    'latest_value': data_points[-1].value if data_points else None,
                    'latest_timestamp': data_points[-1].timestamp if data_points else None
                }
        
        return report
    
    def _initialize_default_metrics(self) -> None:
        """Initialize default metric definitions."""
        self.register_metric(MetricDefinition(
            name="agent_energy_level",
            metric_type=MetricType.PERFORMANCE,
            description="Energy level of agents",
            unit="percentage",
            thresholds={"warning": 0.3, "critical": 0.1}
        ))
        
        self.register_metric(MetricDefinition(
            name="meme_fitness_score",
            metric_type=MetricType.EVOLUTIONARY,
            description="Fitness score of memes",
            unit="score",
            aggregation=AggregationType.AVERAGE
        ))
    
    def _store_metric_data(self, metric_name: str, data_point: MetricDataPoint) -> None:
        """Store a metric data point."""
        self.metric_data[metric_name].append(data_point)
