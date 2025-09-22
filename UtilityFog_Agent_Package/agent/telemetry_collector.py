
"""
Enhanced TelemetryCollector with Observability Integration
Integrates with FT-010 observability system for comprehensive monitoring.
"""

import time
import threading
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from .observability import get_observability_manager, trace_operation, log_simulation_event


class TelemetryCollector:
    """Enhanced telemetry collector with observability integration."""
    
    def __init__(self, max_history_size: int = 1000):
        self.max_history_size = max_history_size
        self.metrics_history = deque(maxlen=max_history_size)
        self.current_metrics = defaultdict(float)
        self.counters = defaultdict(int)
        self.lock = threading.Lock()
        
        # Integration with observability system
        self.observability = get_observability_manager()
        
        # Initialize telemetry
        self._initialize_telemetry()
    
    def _initialize_telemetry(self):
        """Initialize telemetry system with observability."""
        with trace_operation("telemetry_initialization"):
            log_simulation_event(
                "telemetry_initialized",
                max_history_size=self.max_history_size,
                component="TelemetryCollector"
            )
    
    def collect_metric(self, metric_name: str, value: float, **metadata):
        """Collect a metric with observability tracing."""
        with self.lock:
            self.current_metrics[metric_name] = value
            self.counters[f"{metric_name}_count"] += 1
            
            # Add to history with timestamp
            metric_entry = {
                'timestamp': time.time(),
                'metric_name': metric_name,
                'value': value,
                'metadata': metadata
            }
            self.metrics_history.append(metric_entry)
        
        # Log metric collection event
        log_simulation_event(
            "metric_collected",
            metric_name=metric_name,
            value=value,
            metadata=metadata
        )
    
    def collect_performance_metric(self, operation: str, duration: float, success: bool = True):
        """Collect performance metrics with observability."""
        with trace_operation("performance_metric_collection", operation=operation):
            metric_name = f"performance_{operation}"
            
            with self.lock:
                # Update current metrics
                self.current_metrics[f"{metric_name}_duration"] = duration
                self.current_metrics[f"{metric_name}_success_rate"] = (
                    1.0 if success else 0.0
                )
                
                # Update counters
                self.counters[f"{metric_name}_total"] += 1
                if success:
                    self.counters[f"{metric_name}_success"] += 1
                else:
                    self.counters[f"{metric_name}_failure"] += 1
                
                # Add to history
                perf_entry = {
                    'timestamp': time.time(),
                    'metric_name': metric_name,
                    'duration': duration,
                    'success': success,
                    'operation': operation
                }
                self.metrics_history.append(perf_entry)
            
            # Log performance event
            log_simulation_event(
                "performance_metric",
                operation=operation,
                duration=duration,
                success=success
            )
    
    def collect_simulation_metrics(self, simulation_data: Dict[str, Any]):
        """Collect simulation-specific metrics."""
        with trace_operation("simulation_metrics_collection"):
            timestamp = time.time()
            
            with self.lock:
                # Process simulation metrics
                for key, value in simulation_data.items():
                    if isinstance(value, (int, float)):
                        self.current_metrics[f"sim_{key}"] = value
                        
                        # Add to history
                        sim_entry = {
                            'timestamp': timestamp,
                            'metric_name': f"sim_{key}",
                            'value': value,
                            'type': 'simulation'
                        }
                        self.metrics_history.append(sim_entry)
            
            # Log simulation metrics event
            log_simulation_event(
                "simulation_metrics_collected",
                metrics_count=len(simulation_data),
                simulation_data=simulation_data
            )
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Get current metrics with observability context."""
        with trace_operation("get_current_metrics"):
            with self.lock:
                metrics = {
                    'metrics': dict(self.current_metrics),
                    'counters': dict(self.counters),
                    'history_size': len(self.metrics_history),
                    'timestamp': time.time()
                }
            
            # Add observability metrics
            obs_metrics = self.observability.get_metrics_summary()
            metrics['observability'] = obs_metrics
            
            return metrics
    
    def get_metrics_history(self, metric_name: Optional[str] = None, 
                          last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get metrics history with optional filtering."""
        with trace_operation("get_metrics_history", metric_name=metric_name, last_n=last_n):
            with self.lock:
                history = list(self.metrics_history)
            
            # Filter by metric name if specified
            if metric_name:
                history = [entry for entry in history 
                          if entry.get('metric_name') == metric_name]
            
            # Limit to last N entries if specified
            if last_n:
                history = history[-last_n:]
            
            log_simulation_event(
                "metrics_history_retrieved",
                total_entries=len(history),
                metric_name=metric_name,
                last_n=last_n
            )
            
            return history
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary."""
        with trace_operation("get_performance_summary"):
            with self.lock:
                perf_metrics = {}
                
                # Calculate performance summaries
                for counter_name, count in self.counters.items():
                    if counter_name.endswith('_total'):
                        operation = counter_name.replace('_total', '').replace('performance_', '')
                        success_count = self.counters.get(f"performance_{operation}_success", 0)
                        failure_count = self.counters.get(f"performance_{operation}_failure", 0)
                        
                        success_rate = success_count / max(1, count)
                        
                        perf_metrics[operation] = {
                            'total_operations': count,
                            'successful_operations': success_count,
                            'failed_operations': failure_count,
                            'success_rate': success_rate,
                            'current_duration': self.current_metrics.get(
                                f"performance_{operation}_duration", 0.0
                            )
                        }
                
                summary = {
                    'performance_metrics': perf_metrics,
                    'total_metrics_collected': len(self.metrics_history),
                    'observability_summary': self.observability.get_metrics_summary()
                }
            
            log_simulation_event(
                "performance_summary_generated",
                operations_count=len(perf_metrics)
            )
            
            return summary
    
    def reset_metrics(self):
        """Reset all metrics and counters."""
        with trace_operation("reset_metrics"):
            with self.lock:
                self.current_metrics.clear()
                self.counters.clear()
                self.metrics_history.clear()
            
            log_simulation_event("metrics_reset")
    
    def export_metrics(self, format_type: str = "json") -> Dict[str, Any]:
        """Export metrics in specified format."""
        with trace_operation("export_metrics", format_type=format_type):
            export_data = {
                'export_timestamp': time.time(),
                'format': format_type,
                'current_metrics': self.get_current_metrics(),
                'performance_summary': self.get_performance_summary(),
                'full_history': list(self.metrics_history)
            }
            
            log_simulation_event(
                "metrics_exported",
                format_type=format_type,
                total_entries=len(self.metrics_history)
            )
            
            return export_data


# Global telemetry collector instance
_telemetry_collector = None


def get_telemetry_collector() -> TelemetryCollector:
    """Get the global telemetry collector instance."""
    global _telemetry_collector
    if _telemetry_collector is None:
        _telemetry_collector = TelemetryCollector()
    return _telemetry_collector


def initialize_telemetry(max_history_size: int = 1000) -> TelemetryCollector:
    """Initialize the global telemetry system."""
    global _telemetry_collector
    _telemetry_collector = TelemetryCollector(max_history_size)
    return _telemetry_collector
