"""
Unit tests for FailureInjector class.

Tests cover failure injection, chaos testing,
and failure simulation functionality.
"""

import pytest
import asyncio
from unittest.mock import patch
from fractal_tree import Message, MessageType
from fractal_tree.messaging import FailureInjector, FailureType, FailureRule


class TestFailureInjectorCreation:
    """Test FailureInjector creation and initialization."""
    
    def test_create_failure_injector(self):
        """Test creating a failure injector."""
        injector = FailureInjector()
        
        assert injector.enabled is False
        assert len(injector.failure_rules) == 0
        assert injector.stats["failures_injected"] == 0
        assert len(injector.message_history) == 0
        assert len(injector.duplicate_candidates) == 0
        assert len(injector.delayed_messages) == 0


class TestFailureInjectorControl:
    """Test failure injector enable/disable functionality."""
    
    @pytest.fixture
    def injector(self):
        """Create a failure injector for testing."""
        return FailureInjector()
        
    def test_enable_disable(self, injector):
        """Test enabling and disabling failure injection."""
        assert injector.enabled is False
        
        injector.enable()
        assert injector.enabled is True
        
        injector.disable()
        assert injector.enabled is False


class TestFailureRuleManagement:
    """Test failure rule management."""
    
    @pytest.fixture
    def injector(self):
        """Create a failure injector for testing."""
        return FailureInjector()
        
    def test_add_failure_rule(self, injector):
        """Test adding failure rules."""
        rule = FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=0.1
        )
        
        injector.add_failure_rule("timeout_rule", rule)
        
        assert "timeout_rule" in injector.failure_rules
        assert injector.failure_rules["timeout_rule"] == rule
        
    def test_remove_failure_rule(self, injector):
        """Test removing failure rules."""
        rule = FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=0.1
        )
        
        injector.add_failure_rule("timeout_rule", rule)
        injector.remove_failure_rule("timeout_rule")
        
        assert "timeout_rule" not in injector.failure_rules
        
    def test_clear_rules(self, injector):
        """Test clearing all failure rules."""
        rule1 = FailureRule(FailureType.NETWORK_TIMEOUT, 0.1)
        rule2 = FailureRule(FailureType.MESSAGE_CORRUPTION, 0.05)
        
        injector.add_failure_rule("rule1", rule1)
        injector.add_failure_rule("rule2", rule2)
        
        assert len(injector.failure_rules) == 2
        
        injector.clear_rules()
        
        assert len(injector.failure_rules) == 0


class TestFailureDetection:
    """Test failure detection logic."""
    
    @pytest.fixture
    def injector(self):
        """Create an enabled failure injector for testing."""
        injector = FailureInjector()
        injector.enable()
        return injector
        
    @pytest.fixture
    def test_message(self):
        """Create a test message."""
        return Message(
            message_type=MessageType.COMMAND,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
    @pytest.mark.asyncio
    async def test_should_inject_failure_disabled(self, test_message):
        """Test failure detection when injector is disabled."""
        injector = FailureInjector()  # Disabled by default
        
        rule = FailureRule(FailureType.NETWORK_TIMEOUT, 1.0)  # 100% probability
        injector.add_failure_rule("always_fail", rule)
        
        failure_type = await injector.should_inject_failure(test_message)
        assert failure_type is None
        
    @pytest.mark.asyncio
    async def test_should_inject_failure_with_probability(self, injector, test_message):
        """Test failure detection with probability."""
        # Add rule with 100% probability
        rule = FailureRule(FailureType.NETWORK_TIMEOUT, 1.0)
        injector.add_failure_rule("always_fail", rule)
        
        failure_type = await injector.should_inject_failure(test_message)
        assert failure_type == FailureType.NETWORK_TIMEOUT
        assert injector.stats["failures_injected"] == 1
        
    @pytest.mark.asyncio
    async def test_should_inject_failure_with_zero_probability(self, injector, test_message):
        """Test failure detection with zero probability."""
        # Add rule with 0% probability
        rule = FailureRule(FailureType.NETWORK_TIMEOUT, 0.0)
        injector.add_failure_rule("never_fail", rule)
        
        failure_type = await injector.should_inject_failure(test_message)
        assert failure_type is None
        
    @pytest.mark.asyncio
    async def test_should_inject_failure_with_pattern(self, injector):
        """Test failure detection with target pattern."""
        # Add rule that only matches messages with "important" in payload
        rule = FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=1.0,
            target_pattern="important"
        )
        injector.add_failure_rule("pattern_rule", rule)
        
        # Message that matches pattern
        matching_message = Message(
            MessageType.COMMAND, "important data", "sender1"
        )
        failure_type = await injector.should_inject_failure(matching_message)
        assert failure_type == FailureType.NETWORK_TIMEOUT
        
        # Message that doesn't match pattern
        non_matching_message = Message(
            MessageType.COMMAND, "regular data", "sender1"
        )
        failure_type = await injector.should_inject_failure(non_matching_message)
        assert failure_type is None
        
    @pytest.mark.asyncio
    async def test_should_inject_failure_disabled_rule(self, injector, test_message):
        """Test failure detection with disabled rule."""
        rule = FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=1.0,
            enabled=False
        )
        injector.add_failure_rule("disabled_rule", rule)
        
        failure_type = await injector.should_inject_failure(test_message)
        assert failure_type is None


class TestFailureInjection:
    """Test actual failure injection."""
    
    @pytest.fixture
    def injector(self):
        """Create a failure injector for testing."""
        return FailureInjector()
        
    @pytest.fixture
    def test_message(self):
        """Create a test message."""
        return Message(
            message_type=MessageType.COMMAND,
            payload={"data": "test"},
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
    @pytest.mark.asyncio
    async def test_inject_timeout_failure(self, injector, test_message):
        """Test injecting timeout failure."""
        should_drop = await injector.inject_failure(
            test_message, FailureType.NETWORK_TIMEOUT
        )
        
        assert should_drop is True
        assert injector.stats["timeouts_injected"] == 1
        
    @pytest.mark.asyncio
    async def test_inject_connection_lost_failure(self, injector, test_message):
        """Test injecting connection lost failure."""
        should_drop = await injector.inject_failure(
            test_message, FailureType.CONNECTION_LOST
        )
        
        assert should_drop is True
        
    @pytest.mark.asyncio
    async def test_inject_corruption_failure(self, injector, test_message):
        """Test injecting message corruption."""
        should_drop = await injector.inject_failure(
            test_message, FailureType.MESSAGE_CORRUPTION
        )
        
        assert should_drop is False  # Message continues but corrupted
        assert injector.stats["corruptions_injected"] == 1
        assert test_message.payload.get("__corrupted__") is True
        
    @pytest.mark.asyncio
    async def test_inject_slow_response_failure(self, injector, test_message):
        """Test injecting slow response."""
        start_time = asyncio.get_event_loop().time()
        
        should_drop = await injector.inject_failure(
            test_message, FailureType.SLOW_RESPONSE
        )
        
        end_time = asyncio.get_event_loop().time()
        elapsed = end_time - start_time
        
        assert should_drop is False  # Message continues after delay
        assert elapsed >= 1.0  # Should have some delay
        assert injector.stats["delays_injected"] == 1
        
    @pytest.mark.asyncio
    async def test_inject_duplicate_failure(self, injector, test_message):
        """Test injecting duplicate delivery."""
        should_drop = await injector.inject_failure(
            test_message, FailureType.DUPLICATE_DELIVERY
        )
        
        assert should_drop is False  # Original continues
        assert injector.stats["duplicates_injected"] == 1
        assert len(injector.duplicate_candidates) == 1
        assert injector.duplicate_candidates[0] == test_message
        
    @pytest.mark.asyncio
    async def test_inject_out_of_order_failure(self, injector, test_message):
        """Test injecting out-of-order delivery."""
        should_drop = await injector.inject_failure(
            test_message, FailureType.OUT_OF_ORDER
        )
        
        assert should_drop is True  # Message delayed
        assert len(injector.delayed_messages) == 1


class TestDelayedMessageProcessing:
    """Test delayed message processing."""
    
    @pytest.fixture
    def injector(self):
        """Create a failure injector for testing."""
        return FailureInjector()
        
    @pytest.mark.asyncio
    async def test_process_delayed_messages(self, injector):
        """Test processing delayed messages."""
        message1 = Message(MessageType.COMMAND, "test1", "sender1")
        message2 = Message(MessageType.COMMAND, "test2", "sender2")
        
        # Add messages with different delays
        current_time = asyncio.get_event_loop().time()
        injector.delayed_messages = [
            (message1, current_time - 1.0),  # Ready now
            (message2, current_time + 10.0)  # Not ready yet
        ]
        
        ready_messages = await injector.process_delayed_messages()
        
        assert len(ready_messages) == 1
        assert ready_messages[0] == message1
        assert len(injector.delayed_messages) == 1  # message2 still delayed
        
    @pytest.mark.asyncio
    async def test_get_duplicate_messages(self, injector):
        """Test getting duplicate messages."""
        message1 = Message(MessageType.COMMAND, "test1", "sender1")
        message2 = Message(MessageType.COMMAND, "test2", "sender2")
        
        injector.duplicate_candidates = [message1, message2]
        
        duplicates = await injector.get_duplicate_messages()
        
        assert len(duplicates) == 2
        assert message1 in duplicates
        assert message2 in duplicates
        assert len(injector.duplicate_candidates) == 0  # Should be cleared


class TestChaosMode:
    """Test chaos mode functionality."""
    
    def test_create_chaos_mode(self):
        """Test creating chaos mode configuration."""
        injector = FailureInjector()
        injector.create_chaos_mode()
        
        assert len(injector.failure_rules) == 4
        assert "chaos_timeout" in injector.failure_rules
        assert "chaos_corruption" in injector.failure_rules
        assert "chaos_slow" in injector.failure_rules
        assert "chaos_duplicate" in injector.failure_rules
        
        # Check probabilities
        assert injector.failure_rules["chaos_timeout"].probability == 0.1
        assert injector.failure_rules["chaos_corruption"].probability == 0.05
        assert injector.failure_rules["chaos_slow"].probability == 0.15
        assert injector.failure_rules["chaos_duplicate"].probability == 0.08
        
    def test_create_network_partition_mode(self):
        """Test creating network partition simulation."""
        injector = FailureInjector()
        injector.create_network_partition_mode()
        
        assert len(injector.failure_rules) == 2
        assert "partition_timeout" in injector.failure_rules
        assert "partition_connection" in injector.failure_rules
        
        # Check high failure rates for partition simulation
        assert injector.failure_rules["partition_timeout"].probability == 0.8
        assert injector.failure_rules["partition_connection"].probability == 0.3


class TestFailureInjectorStatistics:
    """Test failure injector statistics."""
    
    def test_get_statistics(self):
        """Test getting failure injection statistics."""
        injector = FailureInjector()
        injector.enable()
        
        # Add some rules
        rule1 = FailureRule(FailureType.NETWORK_TIMEOUT, 0.1)
        rule2 = FailureRule(FailureType.MESSAGE_CORRUPTION, 0.05, enabled=False)
        injector.add_failure_rule("rule1", rule1)
        injector.add_failure_rule("rule2", rule2)
        
        # Add some test data
        injector.stats["failures_injected"] = 5
        injector.delayed_messages = [("msg1", 123.0), ("msg2", 456.0)]
        injector.duplicate_candidates = [Message(MessageType.COMMAND, "dup", "sender")]
        
        stats = injector.get_statistics()
        
        assert stats["enabled"] is True
        assert stats["active_rules"] == 1  # Only enabled rules
        assert stats["failures_injected"] == 5
        assert stats["delayed_messages"] == 2
        assert stats["duplicate_candidates"] == 1
        
    def test_reset_statistics(self):
        """Test resetting failure injection statistics."""
        injector = FailureInjector()
        
        # Set some stats
        injector.stats["failures_injected"] = 10
        injector.stats["timeouts_injected"] = 5
        injector.stats["corruptions_injected"] = 3
        
        injector.reset_statistics()
        
        assert injector.stats["failures_injected"] == 0
        assert injector.stats["timeouts_injected"] == 0
        assert injector.stats["corruptions_injected"] == 0


class TestFailureInjectorStringRepresentation:
    """Test string representation of failure injector."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        injector = FailureInjector()
        injector.enable()
        
        rule = FailureRule(FailureType.NETWORK_TIMEOUT, 0.1)
        injector.add_failure_rule("test_rule", rule)
        injector.stats["failures_injected"] = 42
        
        str_repr = str(injector)
        
        assert "FailureInjector" in str_repr
        assert "enabled=True" in str_repr
        assert "rules=1" in str_repr
        assert "failures=42" in str_repr


class TestFailureRule:
    """Test FailureRule dataclass."""
    
    def test_create_failure_rule(self):
        """Test creating a failure rule."""
        rule = FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=0.2,
            target_pattern="test.*",
            delay_range=(2.0, 8.0),
            enabled=True
        )
        
        assert rule.failure_type == FailureType.NETWORK_TIMEOUT
        assert rule.probability == 0.2
        assert rule.target_pattern == "test.*"
        assert rule.delay_range == (2.0, 8.0)
        assert rule.enabled is True
        
    def test_create_failure_rule_defaults(self):
        """Test creating failure rule with defaults."""
        rule = FailureRule(
            failure_type=FailureType.MESSAGE_CORRUPTION,
            probability=0.1
        )
        
        assert rule.failure_type == FailureType.MESSAGE_CORRUPTION
        assert rule.probability == 0.1
        assert rule.target_pattern is None
        assert rule.delay_range == (1.0, 5.0)
        assert rule.enabled is True
