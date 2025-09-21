"""
Fractal Tree MVP - Core Tree Structure Implementation

This package provides the foundational components for self-organizing,
hierarchical structures within the UtilityFog ecosystem.
"""

__version__ = "0.1.0"
__author__ = "UtilityFog Team"

from .exceptions import CircularReferenceError, InvalidNodeError, NodeNotFoundError, TreeNodeError
from .message import Message, MessagePriority, MessageType
from .message_router import MessageRouter
from .tree_node import TreeNode

# Coordination protocol components
from .coordination import (
    Coordinator,
    CoordinationState,
    CoordinationSession,
    CoordinationProtocol,
    CoordinationMessage,
    CoordinationMessageType,
    StateManager,
    StateTransition,
    StateTransitionError,
    BackpressureManager,
    BackpressureState,
    BackpressureConfig,
    QueueMetrics,
    SessionManager,
    SessionEvent,
    SessionConfig,
    SessionMetrics
)

__all__ = [
    # Core components
    "TreeNode",
    "Message",
    "MessageType",
    "MessagePriority",
    "MessageRouter",
    "TreeNodeError",
    "CircularReferenceError",
    "InvalidNodeError",
    "NodeNotFoundError",
    
    # Coordination protocol
    "Coordinator",
    "CoordinationState",
    "CoordinationSession",
    "CoordinationProtocol",
    "CoordinationMessage",
    "CoordinationMessageType",
    "StateManager",
    "StateTransition",
    "StateTransitionError",
    "BackpressureManager",
    "BackpressureState",
    "BackpressureConfig",
    "QueueMetrics",
    "SessionManager",
    "SessionEvent",
    "SessionConfig",
    "SessionMetrics"
]
