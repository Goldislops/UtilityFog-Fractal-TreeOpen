
"""
Coordination module for Parent↔Child communication protocols.

This module provides the coordination infrastructure for managing
hierarchical communication and state synchronization in the fractal tree.
"""

from .coordinator import Coordinator, CoordinationState
from .protocol import CoordinationProtocol, CoordinationMessage
from .state_manager import StateManager, StateTransition

__all__ = [
    "Coordinator",
    "CoordinationState", 
    "CoordinationProtocol",
    "CoordinationMessage",
    "StateManager",
    "StateTransition",
]
