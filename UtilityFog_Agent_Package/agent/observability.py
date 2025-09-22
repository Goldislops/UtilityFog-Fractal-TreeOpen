
"""
FT-010: Observability System - Structured Logs + Tracing
Comprehensive observability framework for UtilityFog simulation system.
"""

import json
import logging
import time
import uuid
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from contextlib import contextmanager
from functools import wraps
from collections import defaultdict, deque
import sys
import traceback


class TraceContext:
    """Thread-local trace context for propagating trace IDs across operations."""
    
    def __init__(self):
        self._local = threading.local()
    
    def get_trace_id(self) -> Optional[str]:
        """Get current trace ID from thread-local storage."""
        return getattr(self._local, 'trace_id', None)
    
    def set_trace_id(self, trace_id: str) -> None:
        """Set trace ID in thread-local storage."""
        self._local.trace_id = trace_id
    
    def clear_trace_id(self) -> None:
        """Clear trace ID from thread-local storage."""
        if hasattr(self._local, 'trace_id'):
            delattr(self._local, 'trace_id')
    
    def generate_trace_id(self) -> str:
        """Generate a new unique trace ID."""
        return f"trace_{uuid.uuid4().hex[:16]}"


class StructuredLogger:
    """Structured JSON logger with trace ID propagation."""
    
    def __init__(self, name: str = "ufog", level: int = logging.INFO):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        
        # Remove existing handlers to avoid duplicates
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Create structured JSON formatter
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(self._create_json_formatter())
        self.logger.addHandler(handler)
        
        self.trace_context = TraceContext()
    
    def _create_json_formatter(self):
        """Create JSON formatter for structured logging."""
        class JSONFormatter(logging.Formatter):
            def format(self, record):
                log_entry = {
                    'timestamp': datetime.utcnow().isoformat() + 'Z',
                    'level': record.levelname,
                    'logger': record.name,
                    'message': record.getMessage(),
                    'module': record.module,
                    'function': record.funcName,
                    'line': record.lineno
                }
                
                # Add trace ID if available
                trace_id = getattr(record, 'trace_id', None)
                if trace_id:
                    log_entry['trace_id'] = trace_id
                
                # Add extra fields
                if hasattr(record, 'extra_fields'):
                    log_entry.update(record.extra_fields)
                
                # Add exception info if present
                if record.exc_info:
                    log_entry['exception'] = {
                        'type': record.exc_info[0].__name__,
                        'message': str(record.exc_info[1]),
                        'traceback': traceback.format_exception(*record.exc_info)
                    }
                
                return json.dumps(log_entry)
        
        return JSONFormatter()
    
    def _log_with_trace(self, level: int, message: str, **kwargs):
        """Log message with trace ID and extra fields."""
        extra = {'extra_fields': kwargs}
        
        # Add trace ID if available
        trace_id = self.trace_context.get_trace_id()
        if trace_id:
            extra['trace_id'] = trace_id
        
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log_with_trace(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log_with_trace(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self._log_with_trace(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log_with_trace(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message."""
        self._log_with_trace(logging.CRITICAL, message, **kwargs)


class RateLimitedErrorLogger:
    """Rate-limited error logging to prevent log spam."""
    
    def __init__(self, logger: StructuredLogger, max_errors_per_minute: int = 10):
        self.logger = logger
        self.max_errors_per_minute = max_errors_per_minute
        self.error_counts = defaultdict(deque)
        self.lock = threading.Lock()
    
    def log_error(self, error_key: str, message: str, **kwargs):
        """Log error with rate limiting based on error key."""
        current_time = time.time()
        
        with self.lock:
            # Clean old entries (older than 1 minute)
            error_queue = self.error_counts[error_key]
            while error_queue and current_time - error_queue[0] > 60:
                error_queue.popleft()
            
            # Check if we're under the rate limit
            if len(error_queue) < self.max_errors_per_minute:
                error_queue.append(current_time)
                self.logger.error(message, error_key=error_key, **kwargs)
                return True
            else:
                # Rate limited - log a summary instead
                if len(error_queue) == self.max_errors_per_minute:
                    self.logger.warning(
                        f"Error rate limit reached for {error_key}. Suppressing further errors for 1 minute.",
                        error_key=error_key,
                        rate_limit=self.max_errors_per_minute
                    )
                return False


class EventLogger:
    """Event logging system for tracking simulation events."""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
        self.event_counts = defaultdict(int)
        self.lock = threading.Lock()
    
    def log_event(self, event_type: str, event_data: Dict[str, Any], **kwargs):
        """Log a structured event."""
        with self.lock:
            self.event_counts[event_type] += 1
        
        self.logger.info(
            f"Event: {event_type}",
            event_type=event_type,
            event_data=event_data,
            event_count=self.event_counts[event_type],
            **kwargs
        )
    
    def get_event_counts(self) -> Dict[str, int]:
        """Get current event counts."""
        with self.lock:
            return dict(self.event_counts)


class TracingDecorator:
    """Decorator for automatic tracing of function calls."""
    
    def __init__(self, logger: StructuredLogger):
        self.logger = logger
    
    def trace_function(self, operation_name: Optional[str] = None):
        """Decorator to trace function execution."""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                op_name = operation_name or f"{func.__module__}.{func.__name__}"
                
                # Generate or propagate trace ID
                trace_id = self.logger.trace_context.get_trace_id()
                if not trace_id:
                    trace_id = self.logger.trace_context.generate_trace_id()
                    self.logger.trace_context.set_trace_id(trace_id)
                
                start_time = time.time()
                
                self.logger.info(
                    f"Starting operation: {op_name}",
                    operation=op_name,
                    operation_phase="start",
                    args_count=len(args),
                    kwargs_keys=list(kwargs.keys())
                )
                
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    self.logger.info(
                        f"Completed operation: {op_name}",
                        operation=op_name,
                        operation_phase="complete",
                        duration_seconds=duration,
                        success=True
                    )
                    
                    return result
                
                except Exception as e:
                    duration = time.time() - start_time
                    
                    self.logger.error(
                        f"Failed operation: {op_name}",
                        operation=op_name,
                        operation_phase="error",
                        duration_seconds=duration,
                        success=False,
                        error_type=type(e).__name__,
                        error_message=str(e)
                    )
                    raise
            
            return wrapper
        return decorator


class ObservabilityManager:
    """Central observability manager for the UtilityFog system."""
    
    def __init__(self, log_level: int = logging.INFO):
        self.logger = StructuredLogger("ufog.observability", log_level)
        self.rate_limited_logger = RateLimitedErrorLogger(self.logger)
        self.event_logger = EventLogger(self.logger)
        self.tracer = TracingDecorator(self.logger)
        
        # Performance metrics
        self.metrics = {
            'operations_started': 0,
            'operations_completed': 0,
            'operations_failed': 0,
            'total_duration': 0.0
        }
        self.metrics_lock = threading.Lock()
    
    @contextmanager
    def trace_operation(self, operation_name: str, **context):
        """Context manager for tracing operations."""
        trace_id = self.logger.trace_context.get_trace_id()
        if not trace_id:
            trace_id = self.logger.trace_context.generate_trace_id()
            self.logger.trace_context.set_trace_id(trace_id)
        
        start_time = time.time()
        
        with self.metrics_lock:
            self.metrics['operations_started'] += 1
        
        # Avoid keyword conflicts by filtering out 'operation' from context
        filtered_context = {k: v for k, v in context.items() if k != 'operation'}
        
        self.logger.info(
            f"Starting traced operation: {operation_name}",
            operation=operation_name,
            operation_phase="start",
            **filtered_context
        )
        
        try:
            yield trace_id
            
            duration = time.time() - start_time
            with self.metrics_lock:
                self.metrics['operations_completed'] += 1
                self.metrics['total_duration'] += duration
            
            self.logger.info(
                f"Completed traced operation: {operation_name}",
                operation=operation_name,
                operation_phase="complete",
                duration_seconds=duration,
                success=True,
                **filtered_context
            )
            
        except Exception as e:
            duration = time.time() - start_time
            with self.metrics_lock:
                self.metrics['operations_failed'] += 1
                self.metrics['total_duration'] += duration
            
            self.logger.error(
                f"Failed traced operation: {operation_name}",
                operation=operation_name,
                operation_phase="error",
                duration_seconds=duration,
                success=False,
                error_type=type(e).__name__,
                error_message=str(e),
                **filtered_context
            )
            raise
    
    def log_simulation_event(self, event_type: str, **event_data):
        """Log simulation-specific events."""
        self.event_logger.log_event(event_type, event_data)
    
    def log_rate_limited_error(self, error_key: str, message: str, **kwargs):
        """Log error with rate limiting."""
        return self.rate_limited_logger.log_error(error_key, message, **kwargs)
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get observability metrics summary."""
        with self.metrics_lock:
            avg_duration = (
                self.metrics['total_duration'] / max(1, self.metrics['operations_completed'])
                if self.metrics['operations_completed'] > 0 else 0
            )
            
            return {
                'operations': dict(self.metrics),
                'average_operation_duration': avg_duration,
                'event_counts': self.event_logger.get_event_counts(),
                'current_trace_id': self.logger.trace_context.get_trace_id()
            }
    
    def trace_function(self, operation_name: Optional[str] = None):
        """Decorator for tracing functions."""
        return self.tracer.trace_function(operation_name)


# Global observability manager instance
_observability_manager = None


def get_observability_manager() -> ObservabilityManager:
    """Get the global observability manager instance."""
    global _observability_manager
    if _observability_manager is None:
        _observability_manager = ObservabilityManager()
    return _observability_manager


def initialize_observability(log_level: int = logging.INFO) -> ObservabilityManager:
    """Initialize the global observability system."""
    global _observability_manager
    _observability_manager = ObservabilityManager(log_level)
    return _observability_manager


# Convenience functions for common operations
def trace_operation(operation_name: str, **context):
    """Context manager for tracing operations."""
    return get_observability_manager().trace_operation(operation_name, **context)


def log_simulation_event(event_type: str, **event_data):
    """Log simulation-specific events."""
    get_observability_manager().log_simulation_event(event_type, **event_data)


def log_rate_limited_error(error_key: str, message: str, **kwargs):
    """Log error with rate limiting."""
    return get_observability_manager().log_rate_limited_error(error_key, message, **kwargs)


def trace_function(operation_name: Optional[str] = None):
    """Decorator for tracing functions."""
    return get_observability_manager().trace_function(operation_name)


def get_metrics_summary() -> Dict[str, Any]:
    """Get observability metrics summary."""
    return get_observability_manager().get_metrics_summary()
