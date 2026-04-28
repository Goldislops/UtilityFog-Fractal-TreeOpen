
"""
Unit tests for Message class.

Tests cover message creation, validation, serialization,
and message lifecycle operations.
"""

import pytest
import time
from fractal_tree import Message, MessageType, MessagePriority, InvalidNodeError


class TestMessageCreation:
    """Test Message creation and basic properties."""
    
    def test_create_basic_message(self):
        """Test creating a basic message."""
        message = Message(
            message_type=MessageType.DATA,
            payload={"key": "value"},
            sender_id="sender1"
        )
        
        assert message.message_type == MessageType.DATA
        assert message.payload == {"key": "value"}
        assert message.sender_id == "sender1"
        assert message.recipient_id is None
        assert message.message_id is not None
        assert len(message.message_id) > 0
        assert message.timestamp > 0
        assert message.priority == MessagePriority.NORMAL
        assert message.ttl == 10
        assert not message.requires_ack
        assert message.correlation_id is None
        assert message.metadata == {}
        
    def test_create_message_with_all_fields(self):
        """Test creating a message with all fields specified."""
        metadata = {"custom": "data"}
        message = Message(
            message_type=MessageType.COMMAND,
            payload="test payload",
            sender_id="sender1",
            recipient_id="recipient1",
            message_id="custom-id",
            timestamp=1234567890.0,
            priority=MessagePriority.HIGH,
            ttl=5,
            requires_ack=True,
            correlation_id="corr-id",
            metadata=metadata
        )
        
        assert message.message_type == MessageType.COMMAND
        assert message.payload == "test payload"
        assert message.sender_id == "sender1"
        assert message.recipient_id == "recipient1"
        assert message.message_id == "custom-id"
        assert message.timestamp == 1234567890.0
        assert message.priority == MessagePriority.HIGH
        assert message.ttl == 5
        assert message.requires_ack
        assert message.correlation_id == "corr-id"
        assert message.metadata == metadata
        
    def test_create_message_without_sender_raises_error(self):
        """Test that creating message without sender raises error."""
        with pytest.raises(InvalidNodeError):
            Message(
                message_type=MessageType.DATA,
                payload="test",
                sender_id=""
            )
            
    def test_create_message_with_negative_ttl_raises_error(self):
        """Test that negative TTL raises error."""
        with pytest.raises(InvalidNodeError):
            Message(
                message_type=MessageType.DATA,
                payload="test",
                sender_id="sender1",
                ttl=-1
            )


class TestMessageValidation:
    """Test message validation and lifecycle."""
    
    def test_message_expiration(self):
        """Test message expiration checking."""
        # Create message with old timestamp
        old_message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            timestamp=time.time() - 400  # 400 seconds ago
        )
        
        # Create recent message
        recent_message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1"
        )
        
        assert old_message.is_expired(max_age=300)  # 5 minutes
        assert not recent_message.is_expired(max_age=300)
        
    def test_ttl_decrement(self):
        """Test TTL decrement functionality."""
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            ttl=3
        )
        
        assert message.decrement_ttl()  # TTL = 2
        assert message.ttl == 2
        
        assert message.decrement_ttl()  # TTL = 1
        assert message.ttl == 1
        
        assert not message.decrement_ttl()  # TTL = 0
        assert message.ttl == 0
        
        assert not message.decrement_ttl()  # TTL = -1
        assert message.ttl == -1


class TestMessageResponses:
    """Test message response creation."""
    
    def test_create_ack_message(self):
        """Test creating acknowledgment message."""
        original = Message(
            message_type=MessageType.REQUEST,
            payload="test request",
            sender_id="sender1",
            recipient_id="recipient1",
            requires_ack=True
        )
        
        ack = original.create_ack("recipient1")
        
        assert ack.message_type == MessageType.RESPONSE
        assert ack.payload["ack"] is True
        assert ack.payload["original_message_id"] == original.message_id
        assert ack.sender_id == "recipient1"
        assert ack.recipient_id == "sender1"
        assert ack.correlation_id == original.message_id
        assert ack.priority == MessagePriority.HIGH
        
    def test_create_error_response(self):
        """Test creating error response message."""
        original = Message(
            message_type=MessageType.COMMAND,
            payload="test command",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        error_msg = "Command failed"
        error_response = original.create_error_response("recipient1", error_msg)
        
        assert error_response.message_type == MessageType.ERROR
        assert error_response.payload["error"] == error_msg
        assert error_response.payload["original_message_id"] == original.message_id
        assert error_response.sender_id == "recipient1"
        assert error_response.recipient_id == "sender1"
        assert error_response.correlation_id == original.message_id
        assert error_response.priority == MessagePriority.HIGH


class TestMessageSerialization:
    """Test message serialization and deserialization."""
    
    def test_to_dict_and_from_dict(self):
        """Test dictionary serialization."""
        original = Message(
            message_type=MessageType.BROADCAST,
            payload={"data": [1, 2, 3]},
            sender_id="sender1",
            recipient_id="recipient1",
            priority=MessagePriority.HIGH,
            ttl=7,
            requires_ack=True,
            correlation_id="corr-123",
            metadata={"custom": "value"}
        )
        
        # Serialize to dict
        data = original.to_dict()
        
        assert data["message_id"] == original.message_id
        assert data["message_type"] == MessageType.BROADCAST.value
        assert data["payload"] == {"data": [1, 2, 3]}
        assert data["sender_id"] == "sender1"
        assert data["recipient_id"] == "recipient1"
        assert data["priority"] == MessagePriority.HIGH.value
        assert data["ttl"] == 7
        assert data["requires_ack"] is True
        assert data["correlation_id"] == "corr-123"
        assert data["metadata"] == {"custom": "value"}
        
        # Deserialize from dict
        restored = Message.from_dict(data)
        
        assert restored.message_id == original.message_id
        assert restored.message_type == original.message_type
        assert restored.payload == original.payload
        assert restored.sender_id == original.sender_id
        assert restored.recipient_id == original.recipient_id
        assert restored.timestamp == original.timestamp
        assert restored.priority == original.priority
        assert restored.ttl == original.ttl
        assert restored.requires_ack == original.requires_ack
        assert restored.correlation_id == original.correlation_id
        assert restored.metadata == original.metadata
        
    def test_serialization_with_none_values(self):
        """Test serialization with None values."""
        message = Message(
            message_type=MessageType.PING,
            payload=None,
            sender_id="sender1"
        )
        
        data = message.to_dict()
        restored = Message.from_dict(data)
        
        assert restored.payload is None
        assert restored.recipient_id is None
        assert restored.correlation_id is None


class TestMessageTypes:
    """Test different message types."""
    
    def test_all_message_types(self):
        """Test that all message types can be used."""
        for msg_type in MessageType:
            message = Message(
                message_type=msg_type,
                payload=f"test {msg_type.value}",
                sender_id="sender1"
            )
            assert message.message_type == msg_type
            
    def test_all_priority_levels(self):
        """Test that all priority levels can be used."""
        for priority in MessagePriority:
            message = Message(
                message_type=MessageType.DATA,
                payload="test",
                sender_id="sender1",
                priority=priority
            )
            assert message.priority == priority


class TestMessageStringRepresentation:
    """Test string representation methods."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        str_repr = str(message)
        assert "Message" in str_repr
        assert "data" in str_repr
        assert "sender1" in str_repr
        assert "recipient1" in str_repr
        assert message.message_id[:8] in str_repr
        
    def test_repr_representation(self):
        """Test __repr__ method."""
        message = Message(
            message_type=MessageType.COMMAND,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1",
            priority=MessagePriority.HIGH
        )
        
        repr_str = repr(message)
        assert "Message" in repr_str
        assert "command" in repr_str
        assert "sender1" in repr_str
        assert "recipient1" in repr_str
        assert str(MessagePriority.HIGH.value) in repr_str
