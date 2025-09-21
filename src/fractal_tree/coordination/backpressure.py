
"""
Backpressure management for coordination protocol.

This module provides queue watermark monitoring, PAUSE/RESUME signals,
and flow control for coordination sessions.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from ..message import Message, MessageType, MessagePriority


class BackpressureState(Enum):
    """Backpressure states."""
    
    NORMAL = "normal"
    WARNING = "warning"
    PAUSED = "paused"
    CRITICAL = "critical"


@dataclass
class QueueMetrics:
    """Queue metrics for backpressure monitoring."""
    
    queue_size: int
    max_size: int
    utilization: float
    enqueue_rate: float = 0.0
    dequeue_rate: float = 0.0
    avg_wait_time: float = 0.0


@dataclass
class BackpressureConfig:
    """Configuration for backpressure management."""
    
    warning_threshold: float = 0.7      # 70% queue utilization
    pause_threshold: float = 0.9        # 90% queue utilization
    critical_threshold: float = 0.95    # 95% queue utilization
    resume_threshold: float = 0.5       # 50% queue utilization
    
    # Rate limiting
    max_enqueue_rate: float = 1000.0    # messages per second
    rate_window: float = 1.0            # rate calculation window
    
    # Monitoring
    check_interval: float = 1.0         # backpressure check interval


class BackpressureManager:
    """
    Manages backpressure and flow control for coordination sessions.
    
    Monitors queue watermarks, sends PAUSE/RESUME signals, and
    implements rate limiting to prevent system overload.
    """
    
    def __init__(self, session_id: str, config: Optional[BackpressureConfig] = None):
        """
        Initialize backpressure manager.
        
        Args:
            session_id: ID of the coordination session.
            config: Backpressure configuration.
        """
        self.session_id = session_id
        self.config = config or BackpressureConfig()
        
        # Current state
        self.current_state = BackpressureState.NORMAL
        self.is_paused = False
        
        # Queue monitoring
        self.monitored_queues: Dict[str, asyncio.Queue] = {}
        self.queue_metrics: Dict[str, QueueMetrics] = {}
        
        # Rate tracking
        self.enqueue_times: List[float] = []
        self.dequeue_times: List[float] = []
        
        # Callbacks
        self.state_callbacks: Dict[BackpressureState, List[Callable]] = {}
        self.pause_callbacks: List[Callable] = []
        self.resume_callbacks: List[Callable] = []
        
        # Background tasks
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            "state_changes": 0,
            "pause_events": 0,
            "resume_events": 0,
            "messages_dropped": 0,
            "rate_limit_hits": 0
        }
        
        # Logger
        self.logger = logging.getLogger(f"BackpressureManager.{session_id}")
    
    async def start(self) -> None:
        """Start backpressure monitoring."""
        if self.running:
            return
            
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        
        self.logger.info(f"Backpressure manager started for session {self.session_id}")
    
    async def stop(self) -> None:
        """Stop backpressure monitoring."""
        if not self.running:
            return
            
        self.running = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
                
        self.logger.info(f"Backpressure manager stopped for session {self.session_id}")
    
    def register_queue(self, queue_name: str, queue: asyncio.Queue, max_size: int) -> None:
        """Register a queue for backpressure monitoring."""
        self.monitored_queues[queue_name] = queue
        self.queue_metrics[queue_name] = QueueMetrics(
            queue_size=0,
            max_size=max_size,
            utilization=0.0
        )
        
        self.logger.debug(f"Registered queue '{queue_name}' for monitoring")
    
    def unregister_queue(self, queue_name: str) -> None:
        """Unregister a queue from monitoring."""
        self.monitored_queues.pop(queue_name, None)
        self.queue_metrics.pop(queue_name, None)
        
        self.logger.debug(f"Unregistered queue '{queue_name}' from monitoring")
    
    async def check_enqueue_allowed(self, queue_name: str) -> bool:
        """
        Check if enqueueing is allowed for a queue.
        
        Args:
            queue_name: Name of the queue to check.
            
        Returns:
            True if enqueueing is allowed, False otherwise.
        """
        if self.is_paused:
            return False
            
        # Check rate limits
        if not self._check_rate_limit():
            self.stats["rate_limit_hits"] += 1
            return False
            
        # Check queue-specific limits
        metrics = self.queue_metrics.get(queue_name)
        if metrics and metrics.utilization >= self.config.critical_threshold:
            return False
            
        return True
    
    async def record_enqueue(self, queue_name: str) -> None:
        """Record an enqueue operation."""
        current_time = asyncio.get_event_loop().time()
        self.enqueue_times.append(current_time)
        
        # Limit history size
        cutoff_time = current_time - self.config.rate_window
        self.enqueue_times = [t for t in self.enqueue_times if t > cutoff_time]
    
    async def record_dequeue(self, queue_name: str) -> None:
        """Record a dequeue operation."""
        current_time = asyncio.get_event_loop().time()
        self.dequeue_times.append(current_time)
        
        # Limit history size
        cutoff_time = current_time - self.config.rate_window
        self.dequeue_times = [t for t in self.dequeue_times if t > cutoff_time]
    
    def create_pause_message(self, sender_id: str, recipient_id: str) -> Message:
        """Create a PAUSE signal message."""
        return Message(
            message_type=MessageType.COMMAND,
            payload={"action": "PAUSE", "reason": "backpressure"},
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.HIGH,
            metadata={
                "backpressure_signal": True,
                "session_id": self.session_id,
                "state": self.current_state.value
            }
        )
    
    def create_resume_message(self, sender_id: str, recipient_id: str) -> Message:
        """Create a RESUME signal message."""
        return Message(
            message_type=MessageType.COMMAND,
            payload={"action": "RESUME", "reason": "backpressure_relieved"},
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.HIGH,
            metadata={
                "backpressure_signal": True,
                "session_id": self.session_id,
                "state": self.current_state.value
            }
        )
    
    async def handle_backpressure_message(self, message: Message) -> None:
        """Handle incoming backpressure signal."""
        if not message.metadata.get("backpressure_signal"):
            return
            
        action = message.payload.get("action")
        
        if action == "PAUSE":
            await self._handle_pause_signal(message)
        elif action == "RESUME":
            await self._handle_resume_signal(message)
        else:
            self.logger.warning(f"Unknown backpressure action: {action}")
    
    async def _handle_pause_signal(self, message: Message) -> None:
        """Handle PAUSE signal."""
        if not self.is_paused:
            self.is_paused = True
            self.stats["pause_events"] += 1
            
            self.logger.info(f"Received PAUSE signal from {message.sender_id}")
            
            # Call pause callbacks
            for callback in self.pause_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(message)
                    else:
                        callback(message)
                except Exception as e:
                    self.logger.error(f"Error in pause callback: {e}")
    
    async def _handle_resume_signal(self, message: Message) -> None:
        """Handle RESUME signal."""
        if self.is_paused:
            self.is_paused = False
            self.stats["resume_events"] += 1
            
            self.logger.info(f"Received RESUME signal from {message.sender_id}")
            
            # Call resume callbacks
            for callback in self.resume_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(message)
                    else:
                        callback(message)
                except Exception as e:
                    self.logger.error(f"Error in resume callback: {e}")
    
    def register_state_callback(self, state: BackpressureState, callback: Callable) -> None:
        """Register callback for state changes."""
        if state not in self.state_callbacks:
            self.state_callbacks[state] = []
        self.state_callbacks[state].append(callback)
    
    def register_pause_callback(self, callback: Callable) -> None:
        """Register callback for pause events."""
        self.pause_callbacks.append(callback)
    
    def register_resume_callback(self, callback: Callable) -> None:
        """Register callback for resume events."""
        self.resume_callbacks.append(callback)
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self.running:
            try:
                await self._update_metrics()
                await self._check_backpressure()
                await asyncio.sleep(self.config.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _update_metrics(self) -> None:
        """Update queue metrics."""
        current_time = asyncio.get_event_loop().time()
        
        for queue_name, queue in self.monitored_queues.items():
            metrics = self.queue_metrics[queue_name]
            
            # Update basic metrics
            metrics.queue_size = queue.qsize()
            metrics.utilization = metrics.queue_size / metrics.max_size if metrics.max_size > 0 else 0.0
            
            # Calculate rates
            cutoff_time = current_time - self.config.rate_window
            recent_enqueues = [t for t in self.enqueue_times if t > cutoff_time]
            recent_dequeues = [t for t in self.dequeue_times if t > cutoff_time]
            
            metrics.enqueue_rate = len(recent_enqueues) / self.config.rate_window
            metrics.dequeue_rate = len(recent_dequeues) / self.config.rate_window
    
    async def _check_backpressure(self) -> None:
        """Check and update backpressure state."""
        max_utilization = 0.0
        
        for metrics in self.queue_metrics.values():
            max_utilization = max(max_utilization, metrics.utilization)
        
        # Determine new state
        new_state = self._calculate_backpressure_state(max_utilization)
        
        if new_state != self.current_state:
            await self._transition_state(new_state)
    
    def _calculate_backpressure_state(self, utilization: float) -> BackpressureState:
        """Calculate backpressure state based on utilization."""
        if utilization >= self.config.critical_threshold:
            return BackpressureState.CRITICAL
        elif utilization >= self.config.pause_threshold:
            return BackpressureState.PAUSED
        elif utilization >= self.config.warning_threshold:
            return BackpressureState.WARNING
        else:
            return BackpressureState.NORMAL
    
    async def _transition_state(self, new_state: BackpressureState) -> None:
        """Transition to new backpressure state."""
        old_state = self.current_state
        self.current_state = new_state
        self.stats["state_changes"] += 1
        
        self.logger.info(f"Backpressure state transition: {old_state.value} → {new_state.value}")
        
        # Call state callbacks
        callbacks = self.state_callbacks.get(new_state, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(old_state, new_state)
                else:
                    callback(old_state, new_state)
            except Exception as e:
                self.logger.error(f"Error in state callback: {e}")
    
    def _check_rate_limit(self) -> bool:
        """Check if current enqueue rate is within limits."""
        if not self.enqueue_times:
            return True
            
        current_time = asyncio.get_event_loop().time()
        cutoff_time = current_time - self.config.rate_window
        recent_enqueues = [t for t in self.enqueue_times if t > cutoff_time]
        
        current_rate = len(recent_enqueues) / self.config.rate_window
        return current_rate <= self.config.max_enqueue_rate
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current backpressure metrics."""
        return {
            "state": self.current_state.value,
            "is_paused": self.is_paused,
            "queue_metrics": {
                name: {
                    "size": metrics.queue_size,
                    "max_size": metrics.max_size,
                    "utilization": metrics.utilization,
                    "enqueue_rate": metrics.enqueue_rate,
                    "dequeue_rate": metrics.dequeue_rate
                }
                for name, metrics in self.queue_metrics.items()
            },
            "statistics": self.stats
        }
    
    def __str__(self) -> str:
        """String representation of backpressure manager."""
        return f"BackpressureManager(session={self.session_id}, state={self.current_state.value})"
