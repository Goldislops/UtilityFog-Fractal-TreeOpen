
"""
Failure injection for testing reliable messaging.

This module provides controlled failure injection to test
reliability mechanisms and error handling.
"""

import random
import asyncio
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from dataclasses import dataclass
from ..message import Message


class FailureType(Enum):
    """Types of failures that can be injected."""
    
    NETWORK_TIMEOUT = "network_timeout"
    CONNECTION_LOST = "connection_lost"
    MESSAGE_CORRUPTION = "message_corruption"
    PARTIAL_FAILURE = "partial_failure"
    SLOW_RESPONSE = "slow_response"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    OUT_OF_ORDER = "out_of_order"


@dataclass
class FailureRule:
    """Rule for injecting failures."""
    
    failure_type: FailureType
    probability: float  # 0.0 to 1.0
    target_pattern: Optional[str] = None  # Regex pattern for message matching
    delay_range: tuple = (1.0, 5.0)  # Min/max delay for slow responses
    enabled: bool = True


class FailureInjector:
    """
    Injects controlled failures for testing reliable messaging.
    
    Provides various failure modes to test retry logic, error handling,
    and system resilience under adverse conditions.
    """
    
    def __init__(self):
        """Initialize failure injector."""
        self.failure_rules: Dict[str, FailureRule] = {}
        self.enabled = False
        
        # Failure statistics
        self.stats = {
            "failures_injected": 0,
            "timeouts_injected": 0,
            "corruptions_injected": 0,
            "duplicates_injected": 0,
            "delays_injected": 0,
        }
        
        # Message tracking for complex failures
        self.message_history: List[str] = []
        self.duplicate_candidates: List[Message] = []
        self.delayed_messages: List[tuple] = []  # (message, delay_until)
        
    def enable(self) -> None:
        """Enable failure injection."""
        self.enabled = True
        
    def disable(self) -> None:
        """Disable failure injection."""
        self.enabled = False
        
    def add_failure_rule(self, name: str, rule: FailureRule) -> None:
        """Add a failure injection rule."""
        self.failure_rules[name] = rule
        
    def remove_failure_rule(self, name: str) -> None:
        """Remove a failure injection rule."""
        self.failure_rules.pop(name, None)
        
    def clear_rules(self) -> None:
        """Clear all failure rules."""
        self.failure_rules.clear()
        
    async def should_inject_failure(self, message: Message) -> Optional[FailureType]:
        """
        Determine if failure should be injected for a message.
        
        Args:
            message: Message being processed.
            
        Returns:
            FailureType if failure should be injected, None otherwise.
        """
        if not self.enabled:
            return None
            
        for rule in self.failure_rules.values():
            if not rule.enabled:
                continue
                
            # Check if rule applies to this message
            if rule.target_pattern:
                import re
                # Search in message string representation and payload
                message_text = str(message) + " " + str(message.payload)
                if not re.search(rule.target_pattern, message_text):
                    continue
                    
            # Check probability
            if random.random() < rule.probability:
                self.stats["failures_injected"] += 1
                return rule.failure_type
                
        return None
        
    async def inject_failure(self, message: Message, failure_type: FailureType) -> bool:
        """
        Inject specified failure type.
        
        Args:
            message: Message to inject failure for.
            failure_type: Type of failure to inject.
            
        Returns:
            True if message should be dropped/failed, False if it should continue.
        """
        if failure_type == FailureType.NETWORK_TIMEOUT:
            return await self._inject_timeout(message)
            
        elif failure_type == FailureType.CONNECTION_LOST:
            return await self._inject_connection_lost(message)
            
        elif failure_type == FailureType.MESSAGE_CORRUPTION:
            return await self._inject_corruption(message)
            
        elif failure_type == FailureType.PARTIAL_FAILURE:
            return await self._inject_partial_failure(message)
            
        elif failure_type == FailureType.SLOW_RESPONSE:
            return await self._inject_slow_response(message)
            
        elif failure_type == FailureType.DUPLICATE_DELIVERY:
            return await self._inject_duplicate(message)
            
        elif failure_type == FailureType.OUT_OF_ORDER:
            return await self._inject_out_of_order(message)
            
        return False
        
    async def _inject_timeout(self, message: Message) -> bool:
        """Inject network timeout failure."""
        self.stats["timeouts_injected"] += 1
        # Simulate timeout by dropping message
        return True
        
    async def _inject_connection_lost(self, message: Message) -> bool:
        """Inject connection lost failure."""
        # Simulate connection loss by dropping message
        return True
        
    async def _inject_corruption(self, message: Message) -> bool:
        """Inject message corruption."""
        self.stats["corruptions_injected"] += 1
        
        # Corrupt message payload (this is a simulation)
        if hasattr(message.payload, 'update') and isinstance(message.payload, dict):
            message.payload['__corrupted__'] = True
            
        return False  # Continue processing corrupted message
        
    async def _inject_partial_failure(self, message: Message) -> bool:
        """Inject partial failure (some recipients fail)."""
        # For broadcast messages, simulate some recipients failing
        return random.random() < 0.5  # 50% chance of failure
        
    async def _inject_slow_response(self, message: Message) -> bool:
        """Inject slow response delay."""
        self.stats["delays_injected"] += 1
        
        # Add random delay
        delay = random.uniform(1.0, 5.0)
        await asyncio.sleep(delay)
        
        return False  # Continue after delay
        
    async def _inject_duplicate(self, message: Message) -> bool:
        """Inject duplicate message delivery."""
        self.stats["duplicates_injected"] += 1
        
        # Store message for later duplicate delivery
        self.duplicate_candidates.append(message)
        
        return False  # Continue with original
        
    async def _inject_out_of_order(self, message: Message) -> bool:
        """Inject out-of-order message delivery."""
        # Delay this message and deliver later
        delay_until = asyncio.get_event_loop().time() + random.uniform(0.5, 2.0)
        self.delayed_messages.append((message, delay_until))
        
        return True  # Drop for now, will be delivered later
        
    async def process_delayed_messages(self) -> List[Message]:
        """Process and return messages that should be delivered now."""
        current_time = asyncio.get_event_loop().time()
        ready_messages = []
        remaining_delayed = []
        
        for message, delay_until in self.delayed_messages:
            if current_time >= delay_until:
                ready_messages.append(message)
            else:
                remaining_delayed.append((message, delay_until))
                
        self.delayed_messages = remaining_delayed
        return ready_messages
        
    async def get_duplicate_messages(self) -> List[Message]:
        """Get messages that should be delivered as duplicates."""
        # Return and clear duplicate candidates
        duplicates = self.duplicate_candidates.copy()
        self.duplicate_candidates.clear()
        return duplicates
        
    def create_chaos_mode(self) -> None:
        """Create chaos mode with multiple failure types."""
        self.add_failure_rule("chaos_timeout", FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=0.1
        ))
        
        self.add_failure_rule("chaos_corruption", FailureRule(
            failure_type=FailureType.MESSAGE_CORRUPTION,
            probability=0.05
        ))
        
        self.add_failure_rule("chaos_slow", FailureRule(
            failure_type=FailureType.SLOW_RESPONSE,
            probability=0.15
        ))
        
        self.add_failure_rule("chaos_duplicate", FailureRule(
            failure_type=FailureType.DUPLICATE_DELIVERY,
            probability=0.08
        ))
        
    def create_network_partition_mode(self) -> None:
        """Create network partition simulation."""
        self.add_failure_rule("partition_timeout", FailureRule(
            failure_type=FailureType.NETWORK_TIMEOUT,
            probability=0.8  # High failure rate
        ))
        
        self.add_failure_rule("partition_connection", FailureRule(
            failure_type=FailureType.CONNECTION_LOST,
            probability=0.3
        ))
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get failure injection statistics."""
        return {
            **self.stats,
            "enabled": self.enabled,
            "active_rules": len([r for r in self.failure_rules.values() if r.enabled]),
            "delayed_messages": len(self.delayed_messages),
            "duplicate_candidates": len(self.duplicate_candidates),
        }
        
    def reset_statistics(self) -> None:
        """Reset failure injection statistics."""
        for key in self.stats:
            self.stats[key] = 0
            
    def __str__(self) -> str:
        """String representation of failure injector."""
        return (f"FailureInjector(enabled={self.enabled}, "
                f"rules={len(self.failure_rules)}, "
                f"failures={self.stats['failures_injected']})")
