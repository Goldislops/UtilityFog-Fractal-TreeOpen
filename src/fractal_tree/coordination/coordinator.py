
"""
Coordinator implementation for Parent↔Child coordination protocol.

This module provides the main Coordinator class that manages coordination
sessions between parent and child nodes in the fractal tree.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Callable
from enum import Enum
from dataclasses import dataclass, field
from ..message import Message, MessageType, MessagePriority
from ..tree_node import TreeNode


class CoordinationState(Enum):
    """Coordination states for parent-child relationships."""
    
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    SYNCHRONIZED = "synchronized"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass
class CoordinationSession:
    """Represents an active coordination session."""
    
    session_id: str
    parent_id: Optional[str]
    child_ids: Set[str] = field(default_factory=set)
    state: CoordinationState = CoordinationState.DISCONNECTED
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    last_heartbeat: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    metadata: Dict[str, Any] = field(default_factory=dict)


class Coordinator:
    """
    Manages coordination between parent and child nodes.
    
    The Coordinator handles the lifecycle of coordination sessions,
    state transitions, and message routing for hierarchical coordination.
    """
    
    def __init__(self, node: TreeNode, heartbeat_interval: float = 30.0):
        """
        Initialize the coordinator.
        
        Args:
            node: The tree node this coordinator manages.
            heartbeat_interval: Interval between heartbeat messages in seconds.
        """
        self.node = node
        self.heartbeat_interval = heartbeat_interval
        
        # Active coordination sessions
        self.sessions: Dict[str, CoordinationSession] = {}
        
        # State management
        self.current_state = CoordinationState.DISCONNECTED
        self.state_callbacks: Dict[CoordinationState, List[Callable]] = {}
        
        # Coordination statistics
        self.stats = {
            "sessions_created": 0,
            "sessions_completed": 0,
            "sessions_failed": 0,
            "commands_executed": 0,
            "heartbeats_sent": 0,
            "heartbeats_received": 0,
        }
        
        # Background tasks
        self.running = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        
        # Logger
        self.logger = logging.getLogger(f"Coordinator.{node.id}")
        
    async def start(self) -> None:
        """Start the coordinator."""
        if self.running:
            return
            
        self.running = True
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.logger.info(f"Coordinator started for node {self.node.id}")
        
    async def stop(self) -> None:
        """Stop the coordinator."""
        if not self.running:
            return
            
        self.running = False
        
        # Cancel heartbeat task
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
                
        # Clean up active sessions
        for session in list(self.sessions.values()):
            await self._cleanup_session(session.session_id)
            
        self.logger.info(f"Coordinator stopped for node {self.node.id}")
        
    async def initiate_coordination(self, child_ids: Optional[List[str]] = None) -> str:
        """
        Initiate coordination with child nodes.
        
        Args:
            child_ids: Specific child IDs to coordinate with. If None, uses all children.
            
        Returns:
            Session ID for the coordination session.
        """
        # Determine target children
        if child_ids is None:
            target_children = {child.id for child in self.node.children}
        else:
            target_children = set(child_ids)
            
        # Create coordination session
        session_id = f"coord-{self.node.id}-{len(self.sessions)}"
        session = CoordinationSession(
            session_id=session_id,
            parent_id=self.node.id,
            child_ids=target_children,
            state=CoordinationState.CONNECTING
        )
        
        self.sessions[session_id] = session
        self.stats["sessions_created"] += 1
        
        # Transition to connecting state
        await self._transition_state(CoordinationState.CONNECTING)
        
        self.logger.info(f"Initiated coordination session {session_id} with {len(target_children)} children")
        return session_id
        
    async def execute_command(self, session_id: str, command: str, params: Dict[str, Any]) -> bool:
        """
        Execute a coordination command.
        
        Args:
            session_id: ID of the coordination session.
            command: Command to execute.
            params: Command parameters.
            
        Returns:
            True if command was successfully initiated, False otherwise.
        """
        session = self.sessions.get(session_id)
        if not session:
            self.logger.error(f"Session {session_id} not found")
            return False
            
        if session.state != CoordinationState.SYNCHRONIZED:
            self.logger.error(f"Session {session_id} not in synchronized state")
            return False
            
        self.stats["commands_executed"] += 1
        self.logger.info(f"Executing command '{command}' in session {session_id}")
        
        # This is a skeleton implementation
        # Full implementation would send command messages to children
        return True
        
    async def handle_coordination_message(self, message: Message) -> None:
        """
        Handle incoming coordination messages.
        
        Args:
            message: Coordination message to handle.
        """
        # Extract coordination info from message
        coord_type = message.metadata.get("coordination_type")
        session_id = message.metadata.get("session_id")
        
        if not coord_type or not session_id:
            self.logger.warning(f"Invalid coordination message: {message}")
            return
            
        session = self.sessions.get(session_id)
        if not session:
            self.logger.warning(f"Received message for unknown session {session_id}")
            return
            
        # Handle different coordination message types
        if coord_type == "COORD_READY":
            await self._handle_ready_message(session, message)
        elif coord_type == "COORD_COMPLETE":
            await self._handle_complete_message(session, message)
        elif coord_type == "COORD_ERROR":
            await self._handle_error_message(session, message)
        elif coord_type == "COORD_HEARTBEAT":
            await self._handle_heartbeat_message(session, message)
        else:
            self.logger.warning(f"Unknown coordination message type: {coord_type}")
            
    async def _handle_ready_message(self, session: CoordinationSession, message: Message) -> None:
        """Handle COORD_READY message from child."""
        self.logger.debug(f"Child {message.sender_id} ready in session {session.session_id}")
        
        # Check if all children are ready
        # This is a skeleton - full implementation would track ready children
        if session.state == CoordinationState.CONNECTING:
            await self._transition_session_state(session, CoordinationState.SYNCHRONIZED)
            
    async def _handle_complete_message(self, session: CoordinationSession, message: Message) -> None:
        """Handle COORD_COMPLETE message from child."""
        self.logger.debug(f"Child {message.sender_id} completed command in session {session.session_id}")
        
    async def _handle_error_message(self, session: CoordinationSession, message: Message) -> None:
        """Handle COORD_ERROR message from child."""
        error_info = message.payload.get("error", "Unknown error")
        self.logger.warning(f"Child {message.sender_id} reported error in session {session.session_id}: {error_info}")
        
        # Transition to degraded state if not already failed
        if session.state == CoordinationState.SYNCHRONIZED:
            await self._transition_session_state(session, CoordinationState.DEGRADED)
            
    async def _handle_heartbeat_message(self, session: CoordinationSession, message: Message) -> None:
        """Handle COORD_HEARTBEAT message."""
        session.last_heartbeat = asyncio.get_event_loop().time()
        self.stats["heartbeats_received"] += 1
        
    async def _transition_state(self, new_state: CoordinationState) -> None:
        """Transition coordinator to new state."""
        old_state = self.current_state
        self.current_state = new_state
        
        self.logger.info(f"Coordinator state transition: {old_state.value} → {new_state.value}")
        
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
                
    async def _transition_session_state(self, session: CoordinationSession, new_state: CoordinationState) -> None:
        """Transition session to new state."""
        old_state = session.state
        session.state = new_state
        
        self.logger.info(f"Session {session.session_id} state transition: {old_state.value} → {new_state.value}")
        
    async def _heartbeat_loop(self) -> None:
        """Background heartbeat loop."""
        while self.running:
            try:
                await self._send_heartbeats()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(1.0)
                
    async def _send_heartbeats(self) -> None:
        """Send heartbeat messages to active sessions."""
        current_time = asyncio.get_event_loop().time()
        
        for session in self.sessions.values():
            if session.state in [CoordinationState.SYNCHRONIZED, CoordinationState.DEGRADED]:
                # This is a skeleton - full implementation would send actual heartbeat messages
                self.stats["heartbeats_sent"] += 1
                self.logger.debug(f"Sent heartbeat for session {session.session_id}")
                
    async def _cleanup_session(self, session_id: str) -> None:
        """Clean up a coordination session."""
        session = self.sessions.pop(session_id, None)
        if session:
            self.logger.info(f"Cleaned up coordination session {session_id}")
            
            if session.state == CoordinationState.FAILED:
                self.stats["sessions_failed"] += 1
            else:
                self.stats["sessions_completed"] += 1
                
    def register_state_callback(self, state: CoordinationState, callback: Callable) -> None:
        """Register a callback for state transitions."""
        if state not in self.state_callbacks:
            self.state_callbacks[state] = []
        self.state_callbacks[state].append(callback)
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get coordination statistics."""
        return {
            **self.stats,
            "active_sessions": len(self.sessions),
            "current_state": self.current_state.value,
            "heartbeat_interval": self.heartbeat_interval,
        }
        
    def __str__(self) -> str:
        """String representation of the coordinator."""
        return f"Coordinator(node={self.node.id}, state={self.current_state.value}, sessions={len(self.sessions)})"
