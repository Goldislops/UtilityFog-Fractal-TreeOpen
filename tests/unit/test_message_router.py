
"""
Unit tests for MessageRouter class.

Tests cover message routing, queuing, handling, and delivery mechanisms.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fractal_tree import TreeNode, Message, MessageType, MessagePriority, MessageRouter


class TestMessageRouterCreation:
    """Test MessageRouter creation and initialization."""
    
    def test_create_router(self):
        """Test creating a message router."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        assert router.node == node
        assert router.max_queue_size == 1000
        assert len(router.message_queues) == len(MessagePriority)
        assert not router.running
        assert router.router_task is None
        
    def test_create_router_with_custom_queue_size(self):
        """Test creating router with custom queue size."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node, max_queue_size=500)
        
        assert router.max_queue_size == 500
        
    def test_router_statistics_initialization(self):
        """Test that router statistics are properly initialized."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        stats = router.get_statistics()
        assert stats["messages_sent"] == 0
        assert stats["messages_received"] == 0
        assert stats["messages_routed"] == 0
        assert stats["messages_dropped"] == 0
        assert stats["acks_sent"] == 0
        assert stats["acks_received"] == 0
        assert "queue_sizes" in stats
        assert "pending_acks" in stats


class TestMessageRouterLifecycle:
    """Test router lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_router(self):
        """Test starting and stopping the router."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        # Start router
        await router.start()
        assert router.running
        assert router.router_task is not None
        
        # Stop router
        await router.stop()
        assert not router.running
        
    @pytest.mark.asyncio
    async def test_start_already_running_router(self):
        """Test starting an already running router."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        await router.start()
        first_task = router.router_task
        
        # Start again - should not create new task
        await router.start()
        assert router.router_task == first_task
        
        await router.stop()
        
    @pytest.mark.asyncio
    async def test_stop_not_running_router(self):
        """Test stopping a router that's not running."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        # Should not raise error
        await router.stop()
        assert not router.running


class TestMessageHandlers:
    """Test message handler registration and management."""
    
    def test_register_handler(self):
        """Test registering message handlers."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        async def test_handler(message):
            pass
            
        router.register_handler(MessageType.DATA, test_handler)
        
        assert test_handler in router.message_handlers[MessageType.DATA]
        
    def test_unregister_handler(self):
        """Test unregistering message handlers."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        async def test_handler(message):
            pass
            
        router.register_handler(MessageType.DATA, test_handler)
        router.unregister_handler(MessageType.DATA, test_handler)
        
        assert test_handler not in router.message_handlers[MessageType.DATA]
        
    def test_unregister_nonexistent_handler(self):
        """Test unregistering a handler that wasn't registered."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        async def test_handler(message):
            pass
            
        # Should not raise error
        router.unregister_handler(MessageType.DATA, test_handler)


class TestMessageSending:
    """Test message sending functionality."""
    
    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test sending a message."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
        result = await router.send_message(message)
        assert result is True
        
        stats = router.get_statistics()
        assert stats["messages_sent"] == 1
        
    @pytest.mark.asyncio
    async def test_send_to_parent(self):
        """Test sending message to parent node."""
        parent = TreeNode(node_id="parent")
        child = TreeNode(node_id="child")
        parent.add_child(child)
        
        router = MessageRouter(child)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="child"
        )
        
        result = await router.send_to_parent(message)
        assert result is True
        assert message.recipient_id == "parent"
        
    @pytest.mark.asyncio
    async def test_send_to_parent_no_parent(self):
        """Test sending to parent when node has no parent."""
        node = TreeNode(node_id="root")
        router = MessageRouter(node)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="root"
        )
        
        result = await router.send_to_parent(message)
        assert result is False
        
    @pytest.mark.asyncio
    async def test_send_to_children(self):
        """Test sending message to all children."""
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        parent.add_child(child1)
        parent.add_child(child2)
        
        router = MessageRouter(parent)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="parent"
        )
        
        sent_count = await router.send_to_children(message)
        assert sent_count == 2
        
    @pytest.mark.asyncio
    async def test_broadcast_message(self):
        """Test broadcasting message to entire subtree."""
        root = TreeNode(node_id="root")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        grandchild = TreeNode(node_id="grandchild")
        
        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(grandchild)
        
        router = MessageRouter(root)
        
        message = Message(
            message_type=MessageType.BROADCAST,
            payload="broadcast test",
            sender_id="root"
        )
        
        sent_count = await router.broadcast_message(message)
        assert sent_count == 3  # child1, child2, grandchild


class TestMessageReceiving:
    """Test message receiving and handling."""
    
    @pytest.mark.asyncio
    async def test_receive_message_for_this_node(self):
        """Test receiving a message destined for this node."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        handler_called = False
        received_message = None
        
        async def test_handler(message):
            nonlocal handler_called, received_message
            handler_called = True
            received_message = message
            
        router.register_handler(MessageType.DATA, test_handler)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="test-node"
        )
        
        await router.receive_message(message)
        
        assert handler_called
        assert received_message == message
        
        stats = router.get_statistics()
        assert stats["messages_received"] == 1
        
    @pytest.mark.asyncio
    async def test_receive_message_with_ack_required(self):
        """Test receiving message that requires acknowledgment."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        # Mock the send_message method to capture ack
        sent_messages = []
        original_send = router.send_message
        
        async def mock_send(message):
            sent_messages.append(message)
            return await original_send(message)
            
        router.send_message = mock_send
        
        message = Message(
            message_type=MessageType.REQUEST,
            payload="test request",
            sender_id="sender1",
            recipient_id="test-node",
            requires_ack=True
        )
        
        await router.receive_message(message)
        
        # Check that ack was sent
        assert len(sent_messages) == 1
        ack_message = sent_messages[0]
        assert ack_message.message_type == MessageType.RESPONSE
        assert ack_message.correlation_id == message.message_id
        
        stats = router.get_statistics()
        assert stats["acks_sent"] == 1
        
    @pytest.mark.asyncio
    async def test_receive_duplicate_message(self):
        """Test receiving duplicate message."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        handler_call_count = 0
        
        async def test_handler(message):
            nonlocal handler_call_count
            handler_call_count += 1
            
        router.register_handler(MessageType.DATA, test_handler)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="test-node",
            message_id="duplicate-test"
        )
        
        # Send same message twice
        await router.receive_message(message)
        await router.receive_message(message)
        
        # Handler should only be called once
        assert handler_call_count == 1
        
        stats = router.get_statistics()
        assert stats["messages_received"] == 2  # Both received, but one dropped as duplicate


class TestMessageRouting:
    """Test message routing functionality."""
    
    @pytest.mark.asyncio
    async def test_route_message_to_child(self):
        """Test routing message to a child node."""
        root = TreeNode(node_id="root")
        child = TreeNode(node_id="child")
        root.add_child(child)
        
        router = MessageRouter(root)
        
        # Mock send_message to capture routed messages
        routed_messages = []
        
        async def mock_send(message):
            routed_messages.append(message)
            return True
            
        router.send_message = mock_send
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="external",
            recipient_id="child",
            ttl=5
        )
        
        await router.receive_message(message)
        
        # Message should be routed
        assert len(routed_messages) == 1
        routed_message = routed_messages[0]
        assert routed_message.recipient_id == "child"
        assert routed_message.ttl == 4  # Decremented
        
    @pytest.mark.asyncio
    async def test_message_ttl_expiration(self):
        """Test that messages with TTL=0 are dropped."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        message = Message(
            message_type=MessageType.DATA,
            payload="test",
            sender_id="sender1",
            recipient_id="other-node",
            ttl=1  # Will become 0 after decrement
        )
        
        await router.receive_message(message)
        
        stats = router.get_statistics()
        assert stats["messages_dropped"] == 1


class TestMessageRouterStatistics:
    """Test router statistics and monitoring."""
    
    def test_get_statistics(self):
        """Test getting router statistics."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        stats = router.get_statistics()
        
        required_keys = [
            "messages_sent", "messages_received", "messages_routed",
            "messages_dropped", "acks_sent", "acks_received",
            "queue_sizes", "pending_acks", "history_size", "handlers_registered"
        ]
        
        for key in required_keys:
            assert key in stats
            
    def test_clear_statistics(self):
        """Test clearing router statistics."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        # Manually set some stats
        router.stats["messages_sent"] = 10
        router.stats["messages_received"] = 5
        
        router.clear_statistics()
        
        stats = router.get_statistics()
        assert stats["messages_sent"] == 0
        assert stats["messages_received"] == 0


class TestMessageRouterStringRepresentation:
    """Test string representation methods."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        str_repr = str(router)
        assert "MessageRouter" in str_repr
        assert "test-node" in str_repr
        assert "running=False" in str_repr
        
    def test_repr_representation(self):
        """Test __repr__ method."""
        node = TreeNode(node_id="test-node")
        router = MessageRouter(node)
        
        repr_str = repr(router)
        assert "MessageRouter" in repr_str
        assert "test-node" in repr_str
        assert "running=False" in repr_str
        assert "queues=" in repr_str
        assert "handlers=" in repr_str
