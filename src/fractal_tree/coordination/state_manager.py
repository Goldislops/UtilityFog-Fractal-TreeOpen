
"""
State management for coordination protocol.

This module provides state transition management and validation
for coordination sessions in the fractal tree.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from .coordinator import CoordinationState


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


@dataclass
class StateTransition:
    """Represents a state transition event."""
    
    from_state: CoordinationState
    to_state: CoordinationState
    trigger: str
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateManager:
    """
    Manages state transitions for coordination sessions.
    
    Provides validation, logging, and callback management for
    coordination state changes.
    """
    
    def __init__(self, session_id: str):
        """
        Initialize state manager.
        
        Args:
            session_id: ID of the coordination session.
        """
        self.session_id = session_id
        self.current_state = CoordinationState.DISCONNECTED
        
        # State transition history
        self.transition_history: List[StateTransition] = []
        self.max_history_size = 100
        
        # State callbacks
        self.enter_callbacks: Dict[CoordinationState, List[Callable]] = {}
        self.exit_callbacks: Dict[CoordinationState, List[Callable]] = {}
        self.transition_callbacks: List[Callable] = []
        
        # State validation rules
        self.valid_transitions = self._build_transition_rules()
        
        # Logger
        self.logger = logging.getLogger(f"StateManager.{session_id}")
        
    def _build_transition_rules(self) -> Dict[CoordinationState, List[CoordinationState]]:
        """Build valid state transition rules."""
        return {
            CoordinationState.DISCONNECTED: [
                CoordinationState.CONNECTING
            ],
            CoordinationState.CONNECTING: [
                CoordinationState.SYNCHRONIZED,
                CoordinationState.FAILED,
                CoordinationState.DISCONNECTED
            ],
            CoordinationState.SYNCHRONIZED: [
                CoordinationState.DEGRADED,
                CoordinationState.FAILED,
                CoordinationState.DISCONNECTED
            ],
            CoordinationState.DEGRADED: [
                CoordinationState.SYNCHRONIZED,
                CoordinationState.FAILED,
                CoordinationState.DISCONNECTED
            ],
            CoordinationState.FAILED: [
                CoordinationState.DISCONNECTED,
                CoordinationState.CONNECTING  # Allow retry
            ]
        }
        
    async def transition_to(self, new_state: CoordinationState, trigger: str = "manual",
                          metadata: Dict[str, Any] = None) -> bool:
        """
        Transition to a new state.
        
        Args:
            new_state: Target state to transition to.
            trigger: What triggered this transition.
            metadata: Additional metadata for the transition.
            
        Returns:
            True if transition was successful, False otherwise.
            
        Raises:
            StateTransitionError: If transition is invalid.
        """
        if not self.is_valid_transition(self.current_state, new_state):
            error_msg = f"Invalid transition from {self.current_state.value} to {new_state.value}"
            self.logger.error(error_msg)
            raise StateTransitionError(error_msg)
            
        old_state = self.current_state
        
        try:
            # Call exit callbacks for old state
            await self._call_exit_callbacks(old_state)
            
            # Record transition
            transition = StateTransition(
                from_state=old_state,
                to_state=new_state,
                trigger=trigger,
                metadata=metadata or {}
            )
            self._add_transition_to_history(transition)
            
            # Update current state
            self.current_state = new_state
            
            # Call enter callbacks for new state
            await self._call_enter_callbacks(new_state)
            
            # Call transition callbacks
            await self._call_transition_callbacks(transition)
            
            self.logger.info(f"State transition: {old_state.value} → {new_state.value} (trigger: {trigger})")
            return True
            
        except Exception as e:
            self.logger.error(f"Error during state transition: {e}")
            # Rollback state change
            self.current_state = old_state
            return False
            
    def is_valid_transition(self, from_state: CoordinationState, to_state: CoordinationState) -> bool:
        """Check if a state transition is valid."""
        valid_next_states = self.valid_transitions.get(from_state, [])
        return to_state in valid_next_states
        
    def can_transition_to(self, target_state: CoordinationState) -> bool:
        """Check if can transition to target state from current state."""
        return self.is_valid_transition(self.current_state, target_state)
        
    def get_valid_next_states(self) -> List[CoordinationState]:
        """Get list of valid next states from current state."""
        return self.valid_transitions.get(self.current_state, [])
        
    def register_enter_callback(self, state: CoordinationState, callback: Callable) -> None:
        """Register callback for entering a state."""
        if state not in self.enter_callbacks:
            self.enter_callbacks[state] = []
        self.enter_callbacks[state].append(callback)
        
    def register_exit_callback(self, state: CoordinationState, callback: Callable) -> None:
        """Register callback for exiting a state."""
        if state not in self.exit_callbacks:
            self.exit_callbacks[state] = []
        self.exit_callbacks[state].append(callback)
        
    def register_transition_callback(self, callback: Callable) -> None:
        """Register callback for any state transition."""
        self.transition_callbacks.append(callback)
        
    async def _call_enter_callbacks(self, state: CoordinationState) -> None:
        """Call all enter callbacks for a state."""
        callbacks = self.enter_callbacks.get(state, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(state)
                else:
                    callback(state)
            except Exception as e:
                self.logger.error(f"Error in enter callback for {state.value}: {e}")
                
    async def _call_exit_callbacks(self, state: CoordinationState) -> None:
        """Call all exit callbacks for a state."""
        callbacks = self.exit_callbacks.get(state, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(state)
                else:
                    callback(state)
            except Exception as e:
                self.logger.error(f"Error in exit callback for {state.value}: {e}")
                
    async def _call_transition_callbacks(self, transition: StateTransition) -> None:
        """Call all transition callbacks."""
        for callback in self.transition_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(transition)
                else:
                    callback(transition)
            except Exception as e:
                self.logger.error(f"Error in transition callback: {e}")
                
    def _add_transition_to_history(self, transition: StateTransition) -> None:
        """Add transition to history."""
        self.transition_history.append(transition)
        
        # Limit history size
        if len(self.transition_history) > self.max_history_size:
            self.transition_history = self.transition_history[-self.max_history_size:]
            
    def get_transition_history(self) -> List[StateTransition]:
        """Get state transition history."""
        return self.transition_history.copy()
        
    def get_state_duration(self) -> float:
        """Get duration in current state."""
        if not self.transition_history:
            return 0.0
            
        last_transition = self.transition_history[-1]
        current_time = asyncio.get_event_loop().time()
        return current_time - last_transition.timestamp
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get state management statistics."""
        state_counts = {}
        for transition in self.transition_history:
            state = transition.to_state.value
            state_counts[state] = state_counts.get(state, 0) + 1
            
        return {
            "current_state": self.current_state.value,
            "state_duration": self.get_state_duration(),
            "total_transitions": len(self.transition_history),
            "state_counts": state_counts,
            "valid_next_states": [s.value for s in self.get_valid_next_states()]
        }
        
    def __str__(self) -> str:
        """String representation of state manager."""
        return f"StateManager(session={self.session_id}, state={self.current_state.value})"
