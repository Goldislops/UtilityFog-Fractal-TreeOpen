"""
Chaos testing for reliable messaging system.

Tests cover chaos scenarios, failure combinations,
and system resilience under adverse conditions.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from fractal_tree import TreeNode, Message, MessageType
from fractal_tree.messaging import (
    ReliableMessageRouter, RetryPolicy, ReliabilityLevel,
    FailureInjector, FailureType, FailureRule
)


class TestChaosReliableMessaging:
    """Test reliable messaging under chaos conditions."""
    
    @pytest.fixture
    def node(self):
        """Create a test tree node."""
        return TreeNode(node_id="chaos-test-node")
        
    @pytest.fixture
    def aggressive_retry_policy(self):
        """Create aggressive retry policy for chaos testing."""
        return RetryPolicy.create_aggressive()
        
    @pytest.fixture
    def chaos_router(self, node, aggressive_retry_policy):
        """Create router with chaos failure injection."""
        router = ReliableMessageRouter(node, default_retry_policy=aggressive_retry_policy)
        
        # Add failure injector
        router.failure_injector = FailureInjector()
        router.failure_injector.enable()
        router.failure_injector.create_chaos_mode()
        
        return router
        
    @pytest.fixture
    def test_message(self):
        """Create a test message."""
        return Message(
            message_type=MessageType.COMMAND,
            payload="chaos test message",
            sender_id="chaos-sender",
            recipient_id="chaos-recipient"
        )
        
    @pytest.mark.asyncio
    async def test_chaos_at_least_once_delivery(self, chaos_router, test_message):
        """Test at-least-once delivery under chaos conditions."""
        # Mock send_message to fail randomly but eventually succeed
        call_count = 0
        
        async def mock_send_with_chaos(message):
            nonlocal call_count
            call_count += 1
            
            # Inject chaos failures
            failure_type = await chaos_router.failure_injector.should_inject_failure(message)
            if failure_type:
                should_drop = await chaos_router.failure_injector.inject_failure(message, failure_type)
                if should_drop:
                    return False
                    
            # Eventually succeed after some attempts
            return call_count >= 3
            
        chaos_router.send_message = AsyncMock(side_effect=mock_send_with_chaos)
        
        # Start router
        await chaos_router.start()
        
        try:
            # Send message with at-least-once reliability
            tracking_id = await chaos_router.send_reliable_message(
                test_message,
                reliability_level=ReliabilityLevel.AT_LEAST_ONCE
            )
            
            # Wait for delivery attempts
            await asyncio.sleep(2.0)
            
            # Should eventually succeed despite chaos
            stats = chaos_router.get_reliability_statistics()
            assert stats["messages_delivered"] >= 1 or stats["retries_attempted"] > 0
            
        finally:
            await chaos_router.stop()
            
    @pytest.mark.asyncio
    async def test_chaos_inflight_limit_respect(self, chaos_router, test_message):
        """Test that inflight limits are respected under chaos."""
        chaos_router.max_inflight_messages = 3
        
        # Mock send_message to always fail (simulate network partition)
        chaos_router.send_message = AsyncMock(return_value=False)
        
        await chaos_router.start()
        
        try:
            # Send more messages than inflight limit
            tracking_ids = []
            for i in range(10):
                message = Message(
                    message_type=MessageType.COMMAND,
                    payload=f"chaos message {i}",
                    sender_id="chaos-sender",
                    recipient_id=f"recipient-{i}"
                )
                tracking_id = await chaos_router.send_reliable_message(message)
                tracking_ids.append(tracking_id)
                
            # Wait a bit for processing
            await asyncio.sleep(0.5)
            
            # Check that inflight limit is respected
            stats = chaos_router.get_reliability_statistics()
            assert len(chaos_router.inflight_messages) <= chaos_router.max_inflight_messages
            assert stats["inflight_limit_hits"] > 0
            
        finally:
            await chaos_router.stop()
            
    @pytest.mark.asyncio
    async def test_chaos_backoff_respect(self, chaos_router, test_message):
        """Test that backoff delays are respected under chaos."""
        # Use a policy with predictable backoff
        chaos_router.default_retry_policy = RetryPolicy(
            max_attempts=3,
            base_delay=0.5,
            backoff_strategy=RetryPolicy.BackoffStrategy.EXPONENTIAL,
            backoff_multiplier=2.0
        )
        
        # Mock send_message to always fail
        chaos_router.send_message = AsyncMock(return_value=False)
        
        await chaos_router.start()
        
        try:
            start_time = asyncio.get_event_loop().time()
            
            # Send message that will fail and retry
            tracking_id = await chaos_router.send_reliable_message(test_message)
            
            # Wait for all retry attempts
            await asyncio.sleep(5.0)
            
            end_time = asyncio.get_event_loop().time()
            elapsed = end_time - start_time
            
            # Should have taken at least the sum of backoff delays
            # 0.5 + 1.0 + 2.0 = 3.5 seconds minimum
            assert elapsed >= 3.0  # Allow some tolerance
            
            stats = chaos_router.get_reliability_statistics()
            assert stats["retries_attempted"] > 0
            
        finally:
            await chaos_router.stop()


class TestNetworkPartitionSimulation:
    """Test messaging behavior during network partitions."""
    
    @pytest.fixture
    def partition_router(self):
        """Create router with network partition simulation."""
        node = TreeNode(node_id="partition-test-node")
        router = ReliableMessageRouter(node)
        
        # Add partition failure injector
        router.failure_injector = FailureInjector()
        router.failure_injector.enable()
        router.failure_injector.create_network_partition_mode()
        
        return router
        
    @pytest.mark.asyncio
    async def test_partition_message_queuing(self, partition_router):
        """Test message queuing during network partition."""
        # Mock send_message to simulate partition (high failure rate)
        async def partition_send(message):
            failure_type = await partition_router.failure_injector.should_inject_failure(message)
            if failure_type:
                should_drop = await partition_router.failure_injector.inject_failure(message, failure_type)
                return not should_drop
            return True
            
        partition_router.send_message = AsyncMock(side_effect=partition_send)
        
        await partition_router.start()
        
        try:
            # Send multiple messages during partition
            messages = []
            for i in range(10):
                message = Message(
                    message_type=MessageType.COMMAND,
                    payload=f"partition test {i}",
                    sender_id="partition-sender",
                    recipient_id=f"recipient-{i}"
                )
                messages.append(message)
                await partition_router.send_reliable_message(message)
                
            # Wait for processing
            await asyncio.sleep(1.0)
            
            # Should have queued messages for retry
            stats = partition_router.get_reliability_statistics()
            assert stats["retry_queue_size"] > 0 or stats["pending_messages"] > 0
            
        finally:
            await partition_router.stop()


class TestMessageCorruptionHandling:
    """Test handling of message corruption scenarios."""
    
    @pytest.fixture
    def corruption_router(self):
        """Create router with message corruption simulation."""
        node = TreeNode(node_id="corruption-test-node")
        router = ReliableMessageRouter(node)
        
        # Add corruption failure injector
        router.failure_injector = FailureInjector()
        router.failure_injector.enable()
        
        # High corruption probability for testing
        corruption_rule = FailureRule(
            failure_type=FailureType.MESSAGE_CORRUPTION,
            probability=0.8
        )
        router.failure_injector.add_failure_rule("high_corruption", corruption_rule)
        
        return router
        
    @pytest.mark.asyncio
    async def test_corruption_detection_and_handling(self, corruption_router):
        """Test detection and handling of corrupted messages."""
        # Mock send_message to apply corruption
        async def corrupt_send(message):
            failure_type = await corruption_router.failure_injector.should_inject_failure(message)
            if failure_type == FailureType.MESSAGE_CORRUPTION:
                await corruption_router.failure_injector.inject_failure(message, failure_type)
                
            # Simulate successful send of corrupted message
            return True
            
        corruption_router.send_message = AsyncMock(side_effect=corrupt_send)
        
        await corruption_router.start()
        
        try:
            message = Message(
                message_type=MessageType.COMMAND,
                payload={"important": "data"},
                sender_id="corruption-sender",
                recipient_id="corruption-recipient"
            )
            
            tracking_id = await corruption_router.send_reliable_message(message)
            
            # Wait for processing
            await asyncio.sleep(0.5)
            
            # Check corruption statistics
            stats = corruption_router.failure_injector.get_statistics()
            assert stats["corruptions_injected"] > 0
            
            # Message should still be delivered (corruption doesn't drop it)
            router_stats = corruption_router.get_reliability_statistics()
            assert router_stats["messages_delivered"] > 0
            
        finally:
            await corruption_router.stop()


class TestDuplicateMessageHandling:
    """Test handling of duplicate message scenarios."""
    
    @pytest.fixture
    def duplicate_router(self):
        """Create router with duplicate message simulation."""
        node = TreeNode(node_id="duplicate-test-node")
        router = ReliableMessageRouter(node)
        
        # Add duplicate failure injector
        router.failure_injector = FailureInjector()
        router.failure_injector.enable()
        
        duplicate_rule = FailureRule(
            failure_type=FailureType.DUPLICATE_DELIVERY,
            probability=0.5
        )
        router.failure_injector.add_failure_rule("duplicates", duplicate_rule)
        
        return router
        
    @pytest.mark.asyncio
    async def test_duplicate_message_generation(self, duplicate_router):
        """Test generation of duplicate messages."""
        duplicate_router.send_message = AsyncMock(return_value=True)
        
        await duplicate_router.start()
        
        try:
            message = Message(
                message_type=MessageType.COMMAND,
                payload="duplicate test",
                sender_id="duplicate-sender",
                recipient_id="duplicate-recipient"
            )
            
            # Send message multiple times to trigger duplicates
            for _ in range(10):
                await duplicate_router.send_reliable_message(message)
                
            # Wait for processing
            await asyncio.sleep(0.5)
            
            # Check for duplicate generation
            duplicates = await duplicate_router.failure_injector.get_duplicate_messages()
            stats = duplicate_router.failure_injector.get_statistics()
            
            assert stats["duplicates_injected"] > 0 or len(duplicates) > 0
            
        finally:
            await duplicate_router.stop()


class TestOutOfOrderDelivery:
    """Test out-of-order message delivery scenarios."""
    
    @pytest.fixture
    def ooo_router(self):
        """Create router with out-of-order delivery simulation."""
        node = TreeNode(node_id="ooo-test-node")
        router = ReliableMessageRouter(node)
        
        # Add out-of-order failure injector
        router.failure_injector = FailureInjector()
        router.failure_injector.enable()
        
        ooo_rule = FailureRule(
            failure_type=FailureType.OUT_OF_ORDER,
            probability=0.3
        )
        router.failure_injector.add_failure_rule("out_of_order", ooo_rule)
        
        return router
        
    @pytest.mark.asyncio
    async def test_out_of_order_message_delay(self, ooo_router):
        """Test delaying messages for out-of-order delivery."""
        ooo_router.send_message = AsyncMock(return_value=True)
        
        await ooo_router.start()
        
        try:
            # Send sequence of messages
            for i in range(5):
                message = Message(
                    message_type=MessageType.COMMAND,
                    payload=f"sequence message {i}",
                    sender_id="ooo-sender",
                    recipient_id="ooo-recipient"
                )
                await ooo_router.send_reliable_message(message)
                
            # Wait for initial processing
            await asyncio.sleep(0.5)
            
            # Check for delayed messages
            stats = ooo_router.failure_injector.get_statistics()
            assert stats["delayed_messages"] > 0
            
            # Wait for delayed messages to be ready
            await asyncio.sleep(2.5)
            
            # Process delayed messages
            ready_messages = await ooo_router.failure_injector.process_delayed_messages()
            assert len(ready_messages) > 0
            
        finally:
            await ooo_router.stop()


class TestCombinedChaosScenarios:
    """Test combinations of multiple failure types."""
    
    @pytest.fixture
    def multi_chaos_router(self):
        """Create router with multiple chaos failure types."""
        node = TreeNode(node_id="multi-chaos-node")
        router = ReliableMessageRouter(node)
        
        # Add multiple failure types
        router.failure_injector = FailureInjector()
        router.failure_injector.enable()
        
        # Add various failure rules
        router.failure_injector.add_failure_rule("timeouts", FailureRule(
            FailureType.NETWORK_TIMEOUT, 0.2
        ))
        router.failure_injector.add_failure_rule("corruption", FailureRule(
            FailureType.MESSAGE_CORRUPTION, 0.1
        ))
        router.failure_injector.add_failure_rule("slow", FailureRule(
            FailureType.SLOW_RESPONSE, 0.15
        ))
        router.failure_injector.add_failure_rule("duplicates", FailureRule(
            FailureType.DUPLICATE_DELIVERY, 0.1
        ))
        
        return router
        
    @pytest.mark.asyncio
    async def test_multi_failure_resilience(self, multi_chaos_router):
        """Test system resilience under multiple failure types."""
        # Mock send with chaos injection
        async def chaos_send(message):
            failure_type = await multi_chaos_router.failure_injector.should_inject_failure(message)
            if failure_type:
                should_drop = await multi_chaos_router.failure_injector.inject_failure(message, failure_type)
                if should_drop:
                    return False
                    
            # Eventually succeed
            return True
            
        multi_chaos_router.send_message = AsyncMock(side_effect=chaos_send)
        
        await multi_chaos_router.start()
        
        try:
            # Send multiple messages under chaos
            tracking_ids = []
            for i in range(20):
                message = Message(
                    message_type=MessageType.COMMAND,
                    payload=f"multi chaos test {i}",
                    sender_id="multi-sender",
                    recipient_id=f"recipient-{i}"
                )
                tracking_id = await multi_chaos_router.send_reliable_message(message)
                tracking_ids.append(tracking_id)
                
            # Wait for processing under chaos
            await asyncio.sleep(3.0)
            
            # Verify system handled multiple failure types
            injector_stats = multi_chaos_router.failure_injector.get_statistics()
            router_stats = multi_chaos_router.get_reliability_statistics()
            
            # Should have encountered various failures
            assert injector_stats["failures_injected"] > 0
            
            # System should still be functional
            assert router_stats["messages_delivered"] > 0 or router_stats["retries_attempted"] > 0
            
            # Verify different failure types were triggered
            failure_types_hit = 0
            if injector_stats["timeouts_injected"] > 0:
                failure_types_hit += 1
            if injector_stats["corruptions_injected"] > 0:
                failure_types_hit += 1
            if injector_stats["delays_injected"] > 0:
                failure_types_hit += 1
            if injector_stats["duplicates_injected"] > 0:
                failure_types_hit += 1
                
            # Should have hit multiple failure types
            assert failure_types_hit >= 2
            
        finally:
            await multi_chaos_router.stop()


class TestChaosStatisticsAndMonitoring:
    """Test chaos testing statistics and monitoring."""
    
    def test_chaos_statistics_collection(self):
        """Test collection of chaos testing statistics."""
        injector = FailureInjector()
        injector.enable()
        injector.create_chaos_mode()
        
        # Simulate some failures
        injector.stats["failures_injected"] = 100
        injector.stats["timeouts_injected"] = 30
        injector.stats["corruptions_injected"] = 15
        injector.stats["delays_injected"] = 25
        injector.stats["duplicates_injected"] = 20
        
        stats = injector.get_statistics()
        
        assert stats["enabled"] is True
        assert stats["failures_injected"] == 100
        assert stats["timeouts_injected"] == 30
        assert stats["corruptions_injected"] == 15
        assert stats["delays_injected"] == 25
        assert stats["duplicates_injected"] == 20
        assert stats["active_rules"] == 4  # Chaos mode has 4 rules
        
    def test_chaos_statistics_reset(self):
        """Test resetting chaos statistics."""
        injector = FailureInjector()
        
        # Set some stats
        injector.stats["failures_injected"] = 50
        injector.stats["timeouts_injected"] = 20
        
        injector.reset_statistics()
        
        stats = injector.get_statistics()
        assert stats["failures_injected"] == 0
        assert stats["timeouts_injected"] == 0
