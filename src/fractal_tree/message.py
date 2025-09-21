
"""
Message system for fractal tree communication.

This module provides the core Message class and related enums for
inter-node communication in the fractal tree.
"""

import time
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class MessageType(Enum):
    """Types of messages in the fractal tree system."""
    
    COMMAND = "command"
    QUERY = "query"
    RESPONSE = "response"
    EVENT = "event"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class MessagePriority(Enum):
    """Message priority levels."""
    
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Message:
    """
    Core message class for fractal tree communication.
    
    Provides structured messaging with metadata, priority, and
    acknowledgment support.
    """
    
    message_type: MessageType
    payload: Any
    sender_id: str
    recipient_id: Optional[str] = None
    priority: MessagePriority = MessagePriority.NORMAL
    requires_ack: bool = False
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Post-initialization processing."""
        # Ensure metadata is a dict
        if self.metadata is None:
            self.metadata = {}
            
        # Add message info to metadata
        self.metadata.update({
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "message_type": self.message_type.value,
            "priority": self.priority.value
        })
    
    def create_response(self, payload: Any, sender_id: str) -> 'Message':
        """Create a response message to this message."""
        return Message(
            message_type=MessageType.RESPONSE,
            payload=payload,
            sender_id=sender_id,
            recipient_id=self.sender_id,
            priority=self.priority,
            metadata={
                "response_to": self.message_id,
                "original_type": self.message_type.value
            }
        )
    
    def create_error_response(self, error: str, sender_id: str) -> 'Message':
        """Create an error response to this message."""
        return Message(
            message_type=MessageType.ERROR,
            payload={"error": error, "original_message_id": self.message_id},
            sender_id=sender_id,
            recipient_id=self.sender_id,
            priority=MessagePriority.HIGH,
            metadata={
                "response_to": self.message_id,
                "original_type": self.message_type.value
            }
        )
    
    def is_response_to(self, original_message: 'Message') -> bool:
        """Check if this message is a response to the original message."""
        return self.metadata.get("response_to") == original_message.message_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary representation."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "priority": self.priority.value,
            "requires_ack": self.requires_ack,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create message from dictionary representation."""
        return cls(
            message_type=MessageType(data["message_type"]),
            payload=data["payload"],
            sender_id=data["sender_id"],
            recipient_id=data.get("recipient_id"),
            priority=MessagePriority(data["priority"]),
            requires_ack=data.get("requires_ack", False),
            message_id=data["message_id"],
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {})
        )
    
    def __str__(self) -> str:
        """String representation of the message."""
        return f"Message({self.message_type.value}, {self.sender_id}→{self.recipient_id})"
    
    def __repr__(self) -> str:
        """Detailed string representation of the message."""
        return (f"Message(id={self.message_id[:8]}, type={self.message_type.value}, "
                f"sender={self.sender_id}, recipient={self.recipient_id}, "
                f"priority={self.priority.value})")
