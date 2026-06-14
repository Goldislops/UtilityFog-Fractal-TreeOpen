
"""
Health monitoring system for fractal tree nodes.

This module provides comprehensive health monitoring with periodic
heartbeats, timeout detection, and health snapshot APIs.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from ..tree_node import TreeNode


class HealthStatus(Enum):
    """Health status of a node."""
    
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthSnapshot:
    """Snapshot of node health at a point in time."""
    
    node_id: str
    status: HealthStatus
    timestamp: float
    last_heartbeat: Optional[float] = None
    response_time: Optional[float] = None
    error_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class HealthMonitor:
    """
    Monitors health of fractal tree nodes.
    
    Provides periodic health checks, heartbeat monitoring,
    timeout detection, and health snapshot APIs.
    """
    
    def __init__(self, node: TreeNode, heartbeat_interval: float = 30.0,
                 timeout_threshold: float = 90.0):
        """
        Initialize health monitor.
        
        Args:
            node: The tree node to monitor.
            heartbeat_interval: Interval between heartbeats in seconds.
            timeout_threshold: Timeout threshold for considering node unhealthy.
        """
        self.node = node
        self.heartbeat_interval = heartbeat_interval
        self.timeout_threshold = timeout_threshold
        
        # Health state
        self.current_status = HealthStatus.UNKNOWN
        self.last_heartbeat = 0.0
        self.error_count = 0
        
        # Health history
        self.health_history: List[HealthSnapshot] = []
        self.max_history_size = 1000
        
        # Monitoring tasks
        self.running = False
        self.monitor_task: Optional[asyncio.Task] = None
        
        # Health callbacks
        self.status_callbacks: Dict[HealthStatus, List[Callable]] = {}
        
        # Statistics
        self.stats = {
            "heartbeats_sent": 0,
            "heartbeats_received": 0,
            "health_checks": 0,
            "status_changes": 0,
        }
        
        # Logger
        self.logger = logging.getLogger(f"HealthMonitor.{node.id}")
        
    async def start(self) -> None:
        """Start health monitoring."""
        if self.running:
            return
            
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        self.current_status = HealthStatus.HEALTHY
        
        self.logger.info(f"Health monitor started for node {self.node.id}")
        
    async def stop(self) -> None:
        """Stop health monitoring."""
        if not self.running:
            return
            
        self.running = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
                
        self.logger.info(f"Health monitor stopped for node {self.node.id}")
        
    async def record_heartbeat(self, from_node: str) -> None:
        """Record heartbeat from another node."""
        self.last_heartbeat = asyncio.get_event_loop().time()
        self.stats["heartbeats_received"] += 1
        
        # Reset error count on successful heartbeat
        self.error_count = 0
        
        # Update status if needed
        if self.current_status != HealthStatus.HEALTHY:
            await self._update_status(HealthStatus.HEALTHY)
            
    async def record_error(self, error: str) -> None:
        """Record a health error."""
        self.error_count += 1
        self.logger.warning(f"Health error recorded: {error}")
        
        # Update status based on error count
        if self.error_count >= 3:
            await self._update_status(HealthStatus.UNHEALTHY)
        elif self.error_count >= 1:
            await self._update_status(HealthStatus.DEGRADED)
            
    def get_health_snapshot(self) -> HealthSnapshot:
        """Get current health snapshot."""
        current_time = asyncio.get_event_loop().time()
        response_time = None
        
        if self.last_heartbeat > 0:
            response_time = current_time - self.last_heartbeat
            
        return HealthSnapshot(
            node_id=self.node.id,
            status=self.current_status,
            timestamp=current_time,
            last_heartbeat=self.last_heartbeat if self.last_heartbeat > 0 else None,
            response_time=response_time,
            error_count=self.error_count,
            metadata={
                "heartbeat_interval": self.heartbeat_interval,
                "timeout_threshold": self.timeout_threshold,
            }
        )
        
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self.running:
            try:
                await self._perform_health_check()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1.0)
                
    async def _perform_health_check(self) -> None:
        """Perform periodic health check."""
        current_time = asyncio.get_event_loop().time()
        self.stats["health_checks"] += 1
        
        # Check for timeout
        if self.last_heartbeat > 0:
            time_since_heartbeat = current_time - self.last_heartbeat
            if time_since_heartbeat > self.timeout_threshold:
                await self._update_status(HealthStatus.UNHEALTHY)
                return
                
        # Record health snapshot
        snapshot = self.get_health_snapshot()
        self._add_to_history(snapshot)
        
    async def _update_status(self, new_status: HealthStatus) -> None:
        """Update health status."""
        if new_status == self.current_status:
            return
            
        old_status = self.current_status
        self.current_status = new_status
        self.stats["status_changes"] += 1
        
        self.logger.info(f"Health status changed: {old_status.value} → {new_status.value}")
        
        # Call status callbacks
        callbacks = self.status_callbacks.get(new_status, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(old_status, new_status)
                else:
                    callback(old_status, new_status)
            except Exception as e:
                self.logger.error(f"Error in status callback: {e}")
                
    def _add_to_history(self, snapshot: HealthSnapshot) -> None:
        """Add snapshot to health history."""
        self.health_history.append(snapshot)
        
        # Limit history size
        if len(self.health_history) > self.max_history_size:
            self.health_history = self.health_history[-self.max_history_size:]
            
    def register_status_callback(self, status: HealthStatus, callback: Callable) -> None:
        """Register callback for status changes."""
        if status not in self.status_callbacks:
            self.status_callbacks[status] = []
        self.status_callbacks[status].append(callback)
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get health monitoring statistics."""
        return {
            **self.stats,
            "current_status": self.current_status.value,
            "error_count": self.error_count,
            "history_size": len(self.health_history),
            "last_heartbeat": self.last_heartbeat,
        }
        
    def __str__(self) -> str:
        """String representation of health monitor."""
        return f"HealthMonitor(node={self.node.id}, status={self.current_status.value})"
