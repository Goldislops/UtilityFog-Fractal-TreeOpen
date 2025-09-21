
"""
Unit tests for ReliableMessageRouter class.

Tests cover reliable message delivery, retry policies,
and failure handling mechanisms.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fractal_tree import TreeNode, Message, MessageType, MessagePriority
from fractal_tree.messaging import ReliableMessageRouter, RetryPolicy, BackoffStrategy, ReliabilityLevel


class TestReliableMessageRouterCreation:
    """Test ReliableMessageRouter creation and initialization."""
    
    def test_create_reliable_router(self):
        """Test creating a reliable message router."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        assert router.node == node
        assert router.max_queue_size == 1000
        assert router.default_retry_policy is not None
        assert router.max_inflight_messages == 100
        assert len(router.pending_messages) == 0
        assert len(router.inflight_messages) == 0
        
    def test_create_reliable_router_with_custom_policy(self):
        """Test creating router with custom retry policy."""
        node = TreeNode(node_id="test-node")
        custom_policy = RetryPolicy(max_attempts=5, base_delay=2.0)
        router = ReliableMessageRouter(node, default_retry_policy=custom_policy)
        
        assert router.default_retry_policy == custom_policy


class TestReliableMessageRouterLifecycle:
    """Test reliable router lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_reliable_router(self):
        """Test starting and stopping the reliable router."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        # Start router
        await router.start()
        assert router.running
        assert router.retry_task is not None
        
        # Stop router
        await router.stop()
        assert not router.running


class TestReliableMessageDelivery:
    """Test reliable message delivery functionality."""
    
    @pytest.mark.asyncio
    async def test_send_reliable_message_best_effort(self):
        """Test sending message with best effort reliability."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        # Mock the base send_message method
        router.send_message = AsyncMock(return_value=True)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        tracking_id = await router.send_reliable_message(
            message, 
            reliability_level=ReliabilityLevel.BEST_EFFORT
        )
        
        assert tracking_id.startswith("reliable-")
        assert router.reliability_stats["messages_delivered"] == 1
        
    @pytest.mark.asyncio
    async def test_send_reliable_message_at_least_once(self):
        """Test sending message with at-least-once reliability."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        # Mock the base send_message method to fail first, then succeed
        router.send_message = AsyncMock(side_effect=[False, True])
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        tracking_id = await router.send_reliable_message(
            message,
            reliability_level=ReliabilityLevel.AT_LEAST_ONCE
        )
        
        assert tracking_id in router.pending_messages
        
    @pytest.mark.asyncio
    async def test_inflight_message_limit(self):
        """Test inflight message limit enforcement."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        router.max_inflight_messages = 2
        
        # Mock send_message to always succeed
        router.send_message = AsyncMock(return_value=True)
        
        messages = []
        for i in range(3):
            message = Message(
                message_type=MessageType.DATA,
                payload=f"test{i}",
                sender_id="sender1",
                recipient_id="recipient1"
            )
            messages.append(message)
            
        # Send messages
        tracking_ids = []
        for message in messages:
            tracking_id = await router.send_reliable_message(message)
            tracking_ids.append(tracking_id)
            
        # Third message should hit the limit
        assert router.reliability_stats["inflight_limit_hits"] >= 1


class TestRetryMechanisms:
    """Test retry mechanisms and backoff strategies."""
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test message retry on delivery failure."""
        node = TreeNode(node_id="test-node")
        retry_policy = RetryPolicy(max_attempts=3, base_delay=0.1)
        router = ReliableMessageRouter(node, default_retry_policy=retry_policy)
        
        # Mock send_message to always fail
        router.send_message = AsyncMock(return_value=False)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        tracking_id = await router.send_reliable_message(message)
        
        # Should be in pending messages for retry
        assert tracking_id in router.pending_messages
        
    def test_should_retry_logic(self):
        """Test retry decision logic."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        from fractal_tree.messaging.reliable_router import ReliableMessage
        
        # Create test message
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1"
        )
        
        reliable_msg = ReliableMessage(
            message=message,
            retry_policy=RetryPolicy(max_attempts=3)
        )
        
        # Should retry when under attempt limit
        reliable_msg.attempt_count = 1
        assert router._should_retry(reliable_msg) is True
        
        # Should not retry when at attempt limit
        reliable_msg.attempt_count = 3
        assert router._should_retry(reliable_msg) is False
        
        # Should not retry for best effort
        reliable_msg.reliability_level = ReliabilityLevel.BEST_EFFORT
        reliable_msg.attempt_count = 1
        assert router._should_retry(reliable_msg) is False


class TestAcknowledgmentHandling:
    """Test acknowledgment handling."""
    
    @pytest.mark.asyncio
    async def test_handle_acknowledgment(self):
        """Test handling acknowledgment messages."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        # Create a pending message
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        tracking_id = f"reliable-{message.message_id}"
        from fractal_tree.messaging.reliable_router import ReliableMessage
        reliable_msg = ReliableMessage(message=message)
        
        router.pending_messages[tracking_id] = reliable_msg
        router.inflight_messages.add(tracking_id)
        
        # Create acknowledgment
        ack_message = Message(
            message_type=MessageType.RESPONSE,
            payload={"ack": True},
            sender_id="recipient1",
            recipient_id="sender1",
            correlation_id=message.message_id
        )
        
        # Handle acknowledgment
        await router.handle_acknowledgment(ack_message)
        
        # Message should be removed from pending
        assert tracking_id not in router.pending_messages
        assert tracking_id not in router.inflight_messages
        assert router.reliability_stats["messages_delivered"] == 1


class TestDeduplication:
    """Test message deduplication."""
    
    @pytest.mark.asyncio
    async def test_duplicate_detection(self):
        """Test duplicate message detection."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        # Mock the base receive_message method
        router.MessageRouter.receive_message = AsyncMock()
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="test-node",
            requires_ack=True
        )
        
        # Mock duplicate detection to return True
        router._is_duplicate_message = MagicMock(return_value=True)
        router.send_message = AsyncMock(return_value=True)
        
        await router.receive_message(message)
        
        # Should detect duplicate and increment counter
        assert router.reliability_stats["duplicates_detected"] == 1


class TestReliabilityStatistics:
    """Test reliability statistics and monitoring."""
    
    def test_get_reliability_statistics(self):
        """Test getting reliability statistics."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        stats = router.get_reliability_statistics()
        
        required_keys = [
            "messages_delivered", "messages_failed", "retries_attempted",
            "duplicates_detected", "inflight_limit_hits", "pending_messages",
            "inflight_messages", "retry_queue_size", "delivery_tracker_stats"
        ]
        
        for key in required_keys:
            assert key in stats


class TestReliableRouterStringRepresentation:
    """Test string representation methods."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        node = TreeNode(node_id="test-node")
        router = ReliableMessageRouter(node)
        
        str_repr = str(router)
        assert "ReliableMessageRouter" in str_repr
        assert "test-node" in str_repr
        assert "pending=0" in str_repr
        assert "inflight=0" in str_repr
