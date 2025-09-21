
"""
Session lifecycle management for coordination protocol.

This module provides session join/leave, rejoin, backoff, and
heartbeat management for coordination sessions.
"""

import asyncio
import logging
import random
from typing import Dict, List, Optional, Set, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from .coordinator import CoordinationState, CoordinationSession
from .backpressure import BackpressureManager, BackpressureConfig
from ..message import Message, MessageType, MessagePriority


class SessionEvent(Enum):
    """Session lifecycle events."""
    
    JOIN_REQUEST = "join_request"
    JOIN_ACCEPTED = "join_accepted"
    JOIN_REJECTED = "join_rejected"
    LEAVE_REQUEST = "leave_request"
    LEAVE_CONFIRMED = "leave_confirmed"
    REJOIN_REQUEST = "rejoin_request"
    HEARTBEAT_TIMEOUT = "heartbeat_timeout"
    SESSION_EXPIRED = "session_expired"


@dataclass
class SessionConfig:
    """Configuration for session management."""
    
    # Timeouts
    join_timeout: float = 30.0
    heartbeat_interval: float = 30.0
    heartbeat_timeout: float = 90.0
    session_ttl: float = 3600.0  # 1 hour
    
    # Backoff
    initial_backoff: float = 1.0
    max_backoff: float = 60.0
    backoff_multiplier: float = 2.0
    backoff_jitter: float = 0.1
    
    # Limits
    max_rejoin_attempts: int = 5
    max_concurrent_sessions: int = 100


@dataclass
class SessionMetrics:
    """Metrics for a coordination session."""
    
    session_id: str
    join_time: float
    last_heartbeat: float
    heartbeat_count: int = 0
    message_count: int = 0
    error_count: int = 0
    rejoin_attempts: int = 0
    lag_ms: float = 0.0
    drops: int = 0
    requeues: int = 0


class SessionManager:
    """
    Manages coordination session lifecycle.
    
    Handles session join/leave, rejoin with backoff, heartbeat
    monitoring, and per-session metrics tracking.
    """
    
    def __init__(self, node_id: str, config: Optional[SessionConfig] = None):
        """
        Initialize session manager.
        
        Args:
            node_id: ID of the node this manager serves.
            config: Session configuration.
        """
        self.node_id = node_id
        self.config = config or SessionConfig()
        
        # Active sessions
        self.sessions: Dict[str, CoordinationSession] = {}
        self.session_metrics: Dict[str, SessionMetrics] = {}
        
        # Backpressure managers per session
        self.backpressure_managers: Dict[str, BackpressureManager] = {}
        
        # Backoff tracking
        self.backoff_delays: Dict[str, float] = {}
        self.rejoin_attempts: Dict[str, int] = {}
        
        # Event callbacks
        self.event_callbacks: Dict[SessionEvent, List[Callable]] = {}
        
        # Background tasks
        self.running = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            "sessions_created": 0,
            "sessions_joined": 0,
            "sessions_left": 0,
            "sessions_expired": 0,
            "rejoin_attempts": 0,
            "heartbeat_timeouts": 0
        }
        
        # Logger
        self.logger = logging.getLogger(f"SessionManager.{node_id}")
    
    async def start(self) -> None:
        """Start session manager."""
        if self.running:
            return
            
        self.running = True
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        self.logger.info(f"Session manager started for node {self.node_id}")
    
    async def stop(self) -> None:
        """Stop session manager."""
        if not self.running:
            return
            
        self.running = False
        
        # Cancel background tasks
        for task in [self.heartbeat_task, self.cleanup_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Stop all backpressure managers
        for bp_manager in self.backpressure_managers.values():
            await bp_manager.stop()
        
        self.logger.info(f"Session manager stopped for node {self.node_id}")
    
    async def request_join(self, parent_id: str, session_config: Dict[str, Any] = None) -> Optional[str]:
        """
        Request to join a coordination session.
        
        Args:
            parent_id: ID of the parent node to join.
            session_config: Optional session configuration.
            
        Returns:
            Session ID if join was successful, None otherwise.
        """
        # Check session limits
        if len(self.sessions) >= self.config.max_concurrent_sessions:
            self.logger.warning("Maximum concurrent sessions reached")
            return None
        
        # Create session
        session_id = f"session-{self.node_id}-{len(self.sessions)}"
        current_time = asyncio.get_event_loop().time()
        
        session = CoordinationSession(
            session_id=session_id,
            parent_id=parent_id,
            child_ids={self.node_id},
            state=CoordinationState.CONNECTING,
            created_at=current_time,
            last_heartbeat=current_time,
            metadata=session_config or {}
        )
        
        # Create session metrics
        metrics = SessionMetrics(
            session_id=session_id,
            join_time=current_time,
            last_heartbeat=current_time
        )
        
        # Create backpressure manager
        bp_manager = BackpressureManager(session_id, BackpressureConfig())
        
        # Store session data
        self.sessions[session_id] = session
        self.session_metrics[session_id] = metrics
        self.backpressure_managers[session_id] = bp_manager
        
        # Start backpressure manager
        await bp_manager.start()
        
        self.stats["sessions_created"] += 1
        self.stats["sessions_joined"] += 1
        
        # Fire join event
        await self._fire_event(SessionEvent.JOIN_REQUEST, session_id, {"parent_id": parent_id})
        
        self.logger.info(f"Requested to join session {session_id} with parent {parent_id}")
        return session_id
    
    async def leave_session(self, session_id: str, reason: str = "voluntary") -> bool:
        """
        Leave a coordination session.
        
        Args:
            session_id: ID of the session to leave.
            reason: Reason for leaving.
            
        Returns:
            True if leave was successful, False otherwise.
        """
        session = self.sessions.get(session_id)
        if not session:
            return False
        
        # Update session state
        session.state = CoordinationState.DISCONNECTED
        
        # Fire leave event
        await self._fire_event(SessionEvent.LEAVE_REQUEST, session_id, {"reason": reason})
        
        # Clean up session
        await self._cleanup_session(session_id)
        
        self.stats["sessions_left"] += 1
        self.logger.info(f"Left session {session_id} (reason: {reason})")
        return True
    
    async def request_rejoin(self, session_id: str) -> bool:
        """
        Request to rejoin a session after disconnection.
        
        Args:
            session_id: ID of the session to rejoin.
            
        Returns:
            True if rejoin was initiated, False otherwise.
        """
        # Check rejoin attempts
        attempts = self.rejoin_attempts.get(session_id, 0)
        if attempts >= self.config.max_rejoin_attempts:
            self.logger.warning(f"Maximum rejoin attempts reached for session {session_id}")
            return False
        
        # Calculate backoff delay
        backoff_delay = self._calculate_backoff_delay(session_id)
        
        # Wait for backoff
        if backoff_delay > 0:
            self.logger.info(f"Waiting {backoff_delay:.2f}s before rejoin attempt for session {session_id}")
            await asyncio.sleep(backoff_delay)
        
        # Update attempt count
        self.rejoin_attempts[session_id] = attempts + 1
        self.stats["rejoin_attempts"] += 1
        
        # Fire rejoin event
        await self._fire_event(SessionEvent.REJOIN_REQUEST, session_id, {"attempt": attempts + 1})
        
        self.logger.info(f"Requesting rejoin for session {session_id} (attempt {attempts + 1})")
        return True
    
    async def handle_heartbeat(self, session_id: str, sender_id: str) -> None:
        """
        Handle incoming heartbeat.
        
        Args:
            session_id: ID of the session.
            sender_id: ID of the sender.
        """
        session = self.sessions.get(session_id)
        metrics = self.session_metrics.get(session_id)
        
        if not session or not metrics:
            return
        
        current_time = asyncio.get_event_loop().time()
        
        # Update session and metrics
        session.last_heartbeat = current_time
        metrics.last_heartbeat = current_time
        metrics.heartbeat_count += 1
        
        # Calculate lag
        if session.metadata.get("last_sent_heartbeat"):
            lag_ms = (current_time - session.metadata["last_sent_heartbeat"]) * 1000
            metrics.lag_ms = lag_ms
        
        self.logger.debug(f"Received heartbeat for session {session_id} from {sender_id}")
    
    async def record_message(self, session_id: str, message: Message) -> None:
        """
        Record a message for session metrics.
        
        Args:
            session_id: ID of the session.
            message: The message to record.
        """
        metrics = self.session_metrics.get(session_id)
        if metrics:
            metrics.message_count += 1
    
    async def record_error(self, session_id: str, error: str) -> None:
        """
        Record an error for session metrics.
        
        Args:
            session_id: ID of the session.
            error: Error description.
        """
        metrics = self.session_metrics.get(session_id)
        if metrics:
            metrics.error_count += 1
        
        self.logger.warning(f"Error recorded for session {session_id}: {error}")
    
    async def record_drop(self, session_id: str) -> None:
        """Record a message drop for session metrics."""
        metrics = self.session_metrics.get(session_id)
        if metrics:
            metrics.drops += 1
    
    async def record_requeue(self, session_id: str) -> None:
        """Record a message requeue for session metrics."""
        metrics = self.session_metrics.get(session_id)
        if metrics:
            metrics.requeues += 1
    
    def get_session_metrics(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific session."""
        metrics = self.session_metrics.get(session_id)
        session = self.sessions.get(session_id)
        
        if not metrics or not session:
            return None
        
        return {
            "session_id": session_id,
            "state": session.state.value,
            "join_time": metrics.join_time,
            "last_heartbeat": metrics.last_heartbeat,
            "heartbeat_count": metrics.heartbeat_count,
            "message_count": metrics.message_count,
            "error_count": metrics.error_count,
            "rejoin_attempts": metrics.rejoin_attempts,
            "lag_ms": metrics.lag_ms,
            "drops": metrics.drops,
            "requeues": metrics.requeues,
            "uptime": asyncio.get_event_loop().time() - metrics.join_time
        }
    
    def get_all_session_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all sessions."""
        return {
            session_id: self.get_session_metrics(session_id)
            for session_id in self.sessions.keys()
        }
    
    def register_event_callback(self, event: SessionEvent, callback: Callable) -> None:
        """Register callback for session events."""
        if event not in self.event_callbacks:
            self.event_callbacks[event] = []
        self.event_callbacks[event].append(callback)
    
    async def _heartbeat_loop(self) -> None:
        """Background heartbeat monitoring loop."""
        while self.running:
            try:
                await self._check_heartbeat_timeouts()
                await asyncio.sleep(self.config.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _cleanup_loop(self) -> None:
        """Background session cleanup loop."""
        while self.running:
            try:
                await self._cleanup_expired_sessions()
                await asyncio.sleep(60.0)  # Check every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(1.0)
    
    async def _check_heartbeat_timeouts(self) -> None:
        """Check for heartbeat timeouts."""
        current_time = asyncio.get_event_loop().time()
        timeout_threshold = current_time - self.config.heartbeat_timeout
        
        for session_id, session in list(self.sessions.items()):
            if session.last_heartbeat < timeout_threshold:
                self.stats["heartbeat_timeouts"] += 1
                await self._fire_event(SessionEvent.HEARTBEAT_TIMEOUT, session_id, {})
                
                # Mark session as failed
                session.state = CoordinationState.FAILED
                self.logger.warning(f"Heartbeat timeout for session {session_id}")
    
    async def _cleanup_expired_sessions(self) -> None:
        """Clean up expired sessions."""
        current_time = asyncio.get_event_loop().time()
        
        for session_id, session in list(self.sessions.items()):
            session_age = current_time - session.created_at
            
            if session_age > self.config.session_ttl:
                await self._fire_event(SessionEvent.SESSION_EXPIRED, session_id, {})
                await self._cleanup_session(session_id)
                self.stats["sessions_expired"] += 1
                self.logger.info(f"Expired session {session_id}")
    
    async def _cleanup_session(self, session_id: str) -> None:
        """Clean up a session and its resources."""
        # Stop backpressure manager
        bp_manager = self.backpressure_managers.pop(session_id, None)
        if bp_manager:
            await bp_manager.stop()
        
        # Remove session data
        self.sessions.pop(session_id, None)
        self.session_metrics.pop(session_id, None)
        self.backoff_delays.pop(session_id, None)
        self.rejoin_attempts.pop(session_id, None)
        
        self.logger.debug(f"Cleaned up session {session_id}")
    
    def _calculate_backoff_delay(self, session_id: str) -> float:
        """Calculate backoff delay for rejoin attempts."""
        attempts = self.rejoin_attempts.get(session_id, 0)
        
        # Exponential backoff with jitter
        delay = min(
            self.config.initial_backoff * (self.config.backoff_multiplier ** attempts),
            self.config.max_backoff
        )
        
        # Add jitter
        jitter = delay * self.config.backoff_jitter * (2 * random.random() - 1)
        delay += jitter
        
        # Store for tracking
        self.backoff_delays[session_id] = delay
        
        return max(0, delay)
    
    async def _fire_event(self, event: SessionEvent, session_id: str, data: Dict[str, Any]) -> None:
        """Fire a session event."""
        callbacks = self.event_callbacks.get(event, [])
        
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event, session_id, data)
                else:
                    callback(event, session_id, data)
            except Exception as e:
                self.logger.error(f"Error in event callback for {event.value}: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get session manager statistics."""
        return {
            **self.stats,
            "active_sessions": len(self.sessions),
            "total_rejoin_attempts": sum(self.rejoin_attempts.values()),
            "average_session_age": self._calculate_average_session_age(),
            "session_states": self._get_session_state_counts()
        }
    
    def _calculate_average_session_age(self) -> float:
        """Calculate average age of active sessions."""
        if not self.sessions:
            return 0.0
        
        current_time = asyncio.get_event_loop().time()
        total_age = sum(current_time - session.created_at for session in self.sessions.values())
        return total_age / len(self.sessions)
    
    def _get_session_state_counts(self) -> Dict[str, int]:
        """Get count of sessions by state."""
        state_counts = {}
        for session in self.sessions.values():
            state = session.state.value
            state_counts[state] = state_counts.get(state, 0) + 1
        return state_counts
    
    def __str__(self) -> str:
        """String representation of session manager."""
        return f"SessionManager(node={self.node_id}, sessions={len(self.sessions)})"
