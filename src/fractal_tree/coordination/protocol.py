
"""
Coordination protocol definitions and message types.

This module defines the coordination protocol messages and communication
patterns for parent-child coordination in the fractal tree.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Any, Dict, Optional
from ..message import Message, MessageType, MessagePriority


class CoordinationMessageType(Enum):
    """Coordination-specific message types."""
    
    # Parent → Child
    COORD_INIT = "coord_init"
    COORD_COMMAND = "coord_command"
    COORD_SYNC = "coord_sync"
    COORD_HEARTBEAT = "coord_heartbeat"
    COORD_SHUTDOWN = "coord_shutdown"
    
    # Child → Parent
    COORD_ACK = "coord_ack"
    COORD_STATUS = "coord_status"
    COORD_ERROR = "coord_error"
    COORD_READY = "coord_ready"
    COORD_COMPLETE = "coord_complete"


@dataclass
class CoordinationMessage:
    """
    Specialized message for coordination protocol.
    
    Wraps the base Message class with coordination-specific metadata.
    """
    
    coord_type: CoordinationMessageType
    session_id: str
    payload: Any
    sender_id: str
    recipient_id: Optional[str] = None
    priority: MessagePriority = MessagePriority.NORMAL
    requires_ack: bool = True
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize metadata with coordination info."""
        if self.metadata is None:
            self.metadata = {}
        self.metadata.update({
            "coordination_type": self.coord_type.value,
            "session_id": self.session_id,
        })
        
    def to_message(self) -> Message:
        """Convert to base Message object."""
        return Message(
            message_type=MessageType.COMMAND,  # Coordination uses COMMAND type
            payload=self.payload,
            sender_id=self.sender_id,
            recipient_id=self.recipient_id,
            priority=self.priority,
            requires_ack=self.requires_ack,
            metadata=self.metadata
        )
        
    @classmethod
    def from_message(cls, message: Message) -> Optional['CoordinationMessage']:
        """Create CoordinationMessage from base Message."""
        coord_type_str = message.metadata.get("coordination_type")
        session_id = message.metadata.get("session_id")
        
        if not coord_type_str or not session_id:
            return None
            
        try:
            coord_type = CoordinationMessageType(coord_type_str)
        except ValueError:
            return None
            
        return cls(
            coord_type=coord_type,
            session_id=session_id,
            payload=message.payload,
            sender_id=message.sender_id,
            recipient_id=message.recipient_id,
            priority=message.priority,
            requires_ack=message.requires_ack,
            metadata=message.metadata
        )


class CoordinationProtocol:
    """
    Coordination protocol implementation.
    
    Defines the rules and patterns for coordination message exchange
    between parent and child nodes.
    """
    
    # Protocol constants
    DEFAULT_TIMEOUT = 30.0  # seconds
    MAX_RETRIES = 3
    HEARTBEAT_INTERVAL = 30.0  # seconds
    
    @staticmethod
    def create_init_message(session_id: str, sender_id: str, recipient_id: str, 
                          config: Dict[str, Any]) -> CoordinationMessage:
        """Create coordination initialization message."""
        return CoordinationMessage(
            coord_type=CoordinationMessageType.COORD_INIT,
            session_id=session_id,
            payload={"config": config},
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.HIGH
        )
        
    @staticmethod
    def create_command_message(session_id: str, sender_id: str, recipient_id: str,
                             command: str, params: Dict[str, Any]) -> CoordinationMessage:
        """Create coordination command message."""
        return CoordinationMessage(
            coord_type=CoordinationMessageType.COORD_COMMAND,
            session_id=session_id,
            payload={"command": command, "params": params},
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.NORMAL
        )
        
    @staticmethod
    def create_ready_message(session_id: str, sender_id: str, recipient_id: str) -> CoordinationMessage:
        """Create coordination ready message."""
        return CoordinationMessage(
            coord_type=CoordinationMessageType.COORD_READY,
            session_id=session_id,
            payload={"status": "ready"},
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.HIGH
        )
        
    @staticmethod
    def create_error_message(session_id: str, sender_id: str, recipient_id: str,
                           error: str, details: Dict[str, Any] = None) -> CoordinationMessage:
        """Create coordination error message."""
        payload = {"error": error}
        if details:
            payload["details"] = details
            
        return CoordinationMessage(
            coord_type=CoordinationMessageType.COORD_ERROR,
            session_id=session_id,
            payload=payload,
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.HIGH
        )
        
    @staticmethod
    def create_heartbeat_message(session_id: str, sender_id: str, recipient_id: str) -> CoordinationMessage:
        """Create coordination heartbeat message."""
        return CoordinationMessage(
            coord_type=CoordinationMessageType.COORD_HEARTBEAT,
            session_id=session_id,
            payload={"timestamp": None},  # Will be set by message system
            sender_id=sender_id,
            recipient_id=recipient_id,
            priority=MessagePriority.LOW,
            requires_ack=False
        )
        
    @staticmethod
    def validate_message_sequence(prev_type: CoordinationMessageType, 
                                curr_type: CoordinationMessageType) -> bool:
        """
        Validate coordination message sequence.
        
        Args:
            prev_type: Previous message type in sequence.
            curr_type: Current message type.
            
        Returns:
            True if sequence is valid, False otherwise.
        """
        # Define valid transitions
        valid_transitions = {
            CoordinationMessageType.COORD_INIT: [
                CoordinationMessageType.COORD_READY,
                CoordinationMessageType.COORD_ERROR
            ],
            CoordinationMessageType.COORD_READY: [
                CoordinationMessageType.COORD_COMMAND,
                CoordinationMessageType.COORD_SYNC,
                CoordinationMessageType.COORD_HEARTBEAT,
                CoordinationMessageType.COORD_SHUTDOWN
            ],
            CoordinationMessageType.COORD_COMMAND: [
                CoordinationMessageType.COORD_COMPLETE,
                CoordinationMessageType.COORD_ERROR
            ],
            CoordinationMessageType.COORD_COMPLETE: [
                CoordinationMessageType.COORD_COMMAND,
                CoordinationMessageType.COORD_SYNC,
                CoordinationMessageType.COORD_HEARTBEAT,
                CoordinationMessageType.COORD_SHUTDOWN
            ],
            # Add more transitions as needed
        }
        
        allowed_next = valid_transitions.get(prev_type, [])
        return curr_type in allowed_next
        
    @staticmethod
    def get_timeout_for_message(msg_type: CoordinationMessageType) -> float:
        """Get appropriate timeout for message type."""
        timeouts = {
            CoordinationMessageType.COORD_INIT: 60.0,
            CoordinationMessageType.COORD_COMMAND: 120.0,
            CoordinationMessageType.COORD_SYNC: 30.0,
            CoordinationMessageType.COORD_HEARTBEAT: 10.0,
            CoordinationMessageType.COORD_SHUTDOWN: 30.0,
        }
        return timeouts.get(msg_type, CoordinationProtocol.DEFAULT_TIMEOUT)
