
"""
Coordination protocol implementation for fractal tree.

This package provides comprehensive coordination capabilities including
state management, session lifecycle, backpressure control, and
message routing integration.
"""

from .coordinator import Coordinator, CoordinationState, CoordinationSession
from .protocol import CoordinationProtocol, CoordinationMessage, CoordinationMessageType
from .state_manager import StateManager, StateTransition, StateTransitionError
from .backpressure import BackpressureManager, BackpressureState, BackpressureConfig, QueueMetrics
from .session_manager import SessionManager, SessionEvent, SessionConfig, SessionMetrics

__all__ = [
    # Core coordination
    "Coordinator",
    "CoordinationState", 
    "CoordinationSession",
    
    # Protocol
    "CoordinationProtocol",
    "CoordinationMessage",
    "CoordinationMessageType",
    
    # State management
    "StateManager",
    "StateTransition",
    "StateTransitionError",
    
    # Backpressure
    "BackpressureManager",
    "BackpressureState",
    "BackpressureConfig",
    "QueueMetrics",
    
    # Session management
    "SessionManager",
    "SessionEvent",
    "SessionConfig",
    "SessionMetrics"
]
