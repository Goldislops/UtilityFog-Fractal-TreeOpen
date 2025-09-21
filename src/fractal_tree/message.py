
"""
Message implementation for the Fractal Tree MVP.

This module provides the Message class and related infrastructure for
communication between tree nodes in the fractal tree system.
"""

import uuid
import time
import asyncio
from typing import Any, Dict, Optional, List, Union
from enum import Enum
from dataclasses import dataclass, field
from .exceptions import InvalidNodeError


class MessageType(Enum):
    """Enumeration of message types in the fractal tree system."""
    
    # Basic communication
    PING = "ping"
    PONG = "pong"
    
    # Data messages
    DATA = "data"
    REQUEST = "request"
    RESPONSE = "response"
    
    # Control messages
    COMMAND = "command"
    STATUS = "status"
    ERROR = "error"
    
    # Tree structure messages
    JOIN = "join"
    LEAVE = "leave"
    RESTRUCTURE = "restructure"
    
    # Broadcast messages
    BROADCAST = "broadcast"
    MULTICAST = "multicast"


class MessagePriority(Enum):
    """Message priority levels."""
    
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Message:
    """
    A message in the fractal tree communication system.
    
    Messages are used for communication between tree nodes and contain
    routing information, payload data, and metadata for delivery guarantees.
    """
    
    message_type: MessageType
    payload: Any
    sender_id: str
    recipient_id: Optional[str] = None
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    priority: MessagePriority = MessagePriority.NORMAL
    ttl: int = 10  # Time to live (hops)
    requires_ack: bool = False
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate message after initialization."""
        if not self.sender_id:
            raise InvalidNodeError("Message must have a sender_id")
        if self.ttl < 0:
            raise InvalidNodeError("Message TTL must be non-negative")
            
    def is_expired(self, max_age: float = 300.0) -> bool:
        """Check if message has expired based on timestamp."""
        return time.time() - self.timestamp > max_age
        
    def decrement_ttl(self) -> bool:
        """
        Decrement TTL and return True if message is still valid.
        
        Returns:
            True if message should continue routing, False if expired.
        """
        self.ttl -= 1
        return self.ttl > 0
        
    def create_ack(self, ack_sender_id: str) -> 'Message':
        """Create an acknowledgment message for this message."""
        return Message(
            message_type=MessageType.RESPONSE,
            payload={"ack": True, "original_message_id": self.message_id},
            sender_id=ack_sender_id,
            recipient_id=self.sender_id,
            correlation_id=self.message_id,
            priority=MessagePriority.HIGH
        )
        
    def create_error_response(self, error_sender_id: str, error_msg: str) -> 'Message':
        """Create an error response message for this message."""
        return Message(
            message_type=MessageType.ERROR,
            payload={"error": error_msg, "original_message_id": self.message_id},
            sender_id=error_sender_id,
            recipient_id=self.sender_id,
            correlation_id=self.message_id,
            priority=MessagePriority.HIGH
        )
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for serialization."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "timestamp": self.timestamp,
            "priority": self.priority.value,
            "ttl": self.ttl,
            "requires_ack": self.requires_ack,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """Create message from dictionary."""
        return cls(
            message_id=data["message_id"],
            message_type=MessageType(data["message_type"]),
            payload=data["payload"],
            sender_id=data["sender_id"],
            recipient_id=data.get("recipient_id"),
            timestamp=data["timestamp"],
            priority=MessagePriority(data["priority"]),
            ttl=data["ttl"],
            requires_ack=data["requires_ack"],
            correlation_id=data.get("correlation_id"),
            metadata=data.get("metadata", {})
        )
        
    def __str__(self) -> str:
        """String representation of the message."""
        return (f"Message({self.message_type.value}, "
                f"{self.sender_id}->{self.recipient_id}, "
                f"id={self.message_id[:8]})")
        
    def __repr__(self) -> str:
        """Detailed string representation of the message."""
        return (f"Message(type={self.message_type.value}, "
                f"sender={self.sender_id}, recipient={self.recipient_id}, "
                f"id={self.message_id}, priority={self.priority.value})")
