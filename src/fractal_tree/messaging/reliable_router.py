
"""
Reliable message router with retry policies and delivery guarantees.

This module extends the basic MessageRouter with reliability features
including retry logic, exponential backoff, and delivery tracking.
"""

import asyncio
import logging
import random
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from ..message import Message, MessageType, MessagePriority
from ..message_router import MessageRouter
from ..tree_node import TreeNode
from .retry_policy import RetryPolicy, BackoffStrategy
from .delivery_tracker import DeliveryTracker, DeliveryStatus


class ReliabilityLevel(Enum):
    """Message reliability levels."""
    
    BEST_EFFORT = "best_effort"      # No retries, fire and forget
    AT_LEAST_ONCE = "at_least_once"  # Retry until delivered
    EXACTLY_ONCE = "exactly_once"    # Deduplicated delivery


@dataclass
class ReliableMessage:
    """Message wrapper with reliability metadata."""
    
    message: Message
    reliability_level: ReliabilityLevel = ReliabilityLevel.AT_LEAST_ONCE
    retry_policy: Optional[RetryPolicy] = None
    max_inflight: int = 10
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    attempt_count: int = 0
    last_attempt: float = 0.0
    next_retry: float = 0.0
    delivery_deadline: Optional[float] = None


class ReliableMessageRouter(MessageRouter):
    """
    Message router with reliability guarantees.
    
    Extends MessageRouter with retry policies, exponential backoff,
    delivery tracking, and failure handling.
    """
    
    def __init__(self, node: TreeNode, max_queue_size: int = 1000, 
                 default_retry_policy: Optional[RetryPolicy] = None):
        """
        Initialize reliable message router.
        
        Args:
            node: The tree node this router belongs to.
            max_queue_size: Maximum size of message queues.
            default_retry_policy: Default retry policy for messages.
        """
        super().__init__(node)
        self.max_queue_size = max_queue_size
        
        # Reliability configuration
        self.default_retry_policy = default_retry_policy or RetryPolicy()
        self.max_inflight_messages = 100
        
        # Delivery tracking
        self.delivery_tracker = DeliveryTracker()
        self.pending_messages: Dict[str, ReliableMessage] = {}
        self.inflight_messages: Set[str] = set()
        
        # Retry management
        self.retry_queue: asyncio.Queue = asyncio.Queue()
        self.retry_task: Optional[asyncio.Task] = None
        
        # Reliability statistics
        self.reliability_stats = {
            "messages_delivered": 0,
            "messages_failed": 0,
            "retries_attempted": 0,
            "duplicates_detected": 0,
            "inflight_limit_hits": 0,
        }
        
        # Logger
        self.logger = logging.getLogger(f"ReliableMessageRouter.{node.id}")
        
    async def start(self) -> None:
        """Start the reliable message router."""
        await super().start()
        
        # Start retry processing
        self.retry_task = asyncio.create_task(self._retry_loop())
        self.logger.info("Reliable message router started")
        
    async def stop(self) -> None:
        """Stop the reliable message router."""
        # Stop retry processing
        if self.retry_task:
            self.retry_task.cancel()
            try:
                await self.retry_task
            except asyncio.CancelledError:
                pass
                
        await super().stop()
        self.logger.info("Reliable message router stopped")
        
    async def send_reliable_message(self, message: Message, 
                                  reliability_level: ReliabilityLevel = ReliabilityLevel.AT_LEAST_ONCE,
                                  retry_policy: Optional[RetryPolicy] = None,
                                  delivery_deadline: Optional[float] = None) -> str:
        """
        Send a message with reliability guarantees.
        
        Args:
            message: Message to send.
            reliability_level: Desired reliability level.
            retry_policy: Custom retry policy (uses default if None).
            delivery_deadline: Absolute deadline for delivery.
            
        Returns:
            Delivery tracking ID.
        """
        # Create reliable message wrapper
        reliable_msg = ReliableMessage(
            message=message,
            reliability_level=reliability_level,
            retry_policy=retry_policy or self.default_retry_policy,
            delivery_deadline=delivery_deadline
        )
        
        # Generate tracking ID
        tracking_id = f"reliable-{message.message_id}"
        
        # Check inflight limit
        if len(self.inflight_messages) >= self.max_inflight_messages:
            self.reliability_stats["inflight_limit_hits"] += 1
            self.logger.warning(f"Inflight message limit reached, queuing message {tracking_id}")
            # Queue for later processing
            await self.retry_queue.put(reliable_msg)
            return tracking_id
            
        # Start delivery attempt
        await self._attempt_delivery(reliable_msg, tracking_id)
        return tracking_id
        
    async def _attempt_delivery(self, reliable_msg: ReliableMessage, tracking_id: str) -> None:
        """Attempt to deliver a reliable message."""
        reliable_msg.attempt_count += 1
        reliable_msg.last_attempt = asyncio.get_event_loop().time()
        
        # Add to inflight tracking
        self.inflight_messages.add(tracking_id)
        self.pending_messages[tracking_id] = reliable_msg
        
        # Update delivery tracker
        self.delivery_tracker.start_delivery(tracking_id, reliable_msg.message)
        
        try:
            # Attempt delivery through base router
            success = await super().send_message(reliable_msg.message)
            
            if success:
                self.logger.debug(f"Message {tracking_id} sent successfully (attempt {reliable_msg.attempt_count})")
                
                # For BEST_EFFORT, consider it delivered immediately
                if reliable_msg.reliability_level == ReliabilityLevel.BEST_EFFORT:
                    await self._handle_delivery_success(tracking_id)
                # For others, wait for acknowledgment
                
            else:
                # Delivery failed, schedule retry
                await self._handle_delivery_failure(tracking_id, "Send failed")
                
        except Exception as e:
            await self._handle_delivery_failure(tracking_id, str(e))
            
    async def _handle_delivery_success(self, tracking_id: str) -> None:
        """Handle successful message delivery."""
        reliable_msg = self.pending_messages.pop(tracking_id, None)
        if reliable_msg:
            self.inflight_messages.discard(tracking_id)
            self.delivery_tracker.mark_delivered(tracking_id)
            self.reliability_stats["messages_delivered"] += 1
            
            self.logger.info(f"Message {tracking_id} delivered successfully after {reliable_msg.attempt_count} attempts")
            
    async def _handle_delivery_failure(self, tracking_id: str, error: str) -> None:
        """Handle failed message delivery."""
        reliable_msg = self.pending_messages.get(tracking_id)
        if not reliable_msg:
            return
            
        self.logger.warning(f"Message {tracking_id} delivery failed (attempt {reliable_msg.attempt_count}): {error}")
        
        # Check if we should retry
        if self._should_retry(reliable_msg):
            # Calculate next retry time with backoff
            backoff_delay = reliable_msg.retry_policy.calculate_backoff(reliable_msg.attempt_count)
            reliable_msg.next_retry = asyncio.get_event_loop().time() + backoff_delay
            
            # Schedule retry
            await self._schedule_retry(reliable_msg, tracking_id)
            self.reliability_stats["retries_attempted"] += 1
            
        else:
            # Give up on delivery
            self.inflight_messages.discard(tracking_id)
            self.pending_messages.pop(tracking_id, None)
            self.delivery_tracker.mark_failed(tracking_id, error)
            self.reliability_stats["messages_failed"] += 1
            
            self.logger.error(f"Message {tracking_id} delivery failed permanently after {reliable_msg.attempt_count} attempts")
            
    def _should_retry(self, reliable_msg: ReliableMessage) -> bool:
        """Determine if message should be retried."""
        # Check attempt limit
        if reliable_msg.attempt_count >= reliable_msg.retry_policy.max_attempts:
            return False
            
        # Check delivery deadline
        if reliable_msg.delivery_deadline:
            current_time = asyncio.get_event_loop().time()
            if current_time >= reliable_msg.delivery_deadline:
                return False
                
        # Check reliability level
        if reliable_msg.reliability_level == ReliabilityLevel.BEST_EFFORT:
            return False
            
        return True
        
    async def _schedule_retry(self, reliable_msg: ReliableMessage, tracking_id: str) -> None:
        """Schedule message for retry."""
        # Remove from inflight for now
        self.inflight_messages.discard(tracking_id)
        
        # Add to retry queue
        await self.retry_queue.put((reliable_msg, tracking_id))
        
    async def _retry_loop(self) -> None:
        """Background loop for processing retries."""
        while self.running:
            try:
                # Get next retry item
                try:
                    item = await asyncio.wait_for(self.retry_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                    
                if isinstance(item, ReliableMessage):
                    # New message to process
                    tracking_id = f"reliable-{item.message.message_id}"
                    await self._attempt_delivery(item, tracking_id)
                elif isinstance(item, tuple):
                    # Retry item
                    reliable_msg, tracking_id = item
                    current_time = asyncio.get_event_loop().time()
                    
                    # Check if it's time to retry
                    if current_time >= reliable_msg.next_retry:
                        await self._attempt_delivery(reliable_msg, tracking_id)
                    else:
                        # Not time yet, put back in queue
                        await self.retry_queue.put(item)
                        await asyncio.sleep(0.1)  # Brief pause to avoid busy loop
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in retry loop: {e}")
                await asyncio.sleep(1.0)
                
    async def handle_acknowledgment(self, ack_message: Message) -> None:
        """Handle acknowledgment message."""
        # Extract original message ID from acknowledgment
        original_msg_id = ack_message.correlation_id
        if not original_msg_id:
            return
            
        tracking_id = f"reliable-{original_msg_id}"
        
        if tracking_id in self.pending_messages:
            await self._handle_delivery_success(tracking_id)
        else:
            self.logger.debug(f"Received ack for unknown message {tracking_id}")
            
    async def receive_message(self, message: Message) -> None:
        """Receive and process incoming message with deduplication."""
        # Check for duplicate delivery (EXACTLY_ONCE)
        if self._is_duplicate_message(message):
            self.reliability_stats["duplicates_detected"] += 1
            self.logger.debug(f"Duplicate message detected: {message.message_id}")
            
            # Send acknowledgment but don't process
            if message.requires_ack:
                ack = message.create_ack(self.node.id)
                await super().send_message(ack)
            return
            
        # Process message normally
        await super().receive_message(message)
        
    def _is_duplicate_message(self, message: Message) -> bool:
        """Check if message is a duplicate."""
        # This is a skeleton implementation
        # Full implementation would maintain a deduplication cache
        return False
        
    def get_delivery_status(self, tracking_id: str) -> Optional[DeliveryStatus]:
        """Get delivery status for a message."""
        return self.delivery_tracker.get_status(tracking_id)
        
    def get_reliability_statistics(self) -> Dict[str, Any]:
        """Get reliability statistics."""
        return {
            **self.reliability_stats,
            "pending_messages": len(self.pending_messages),
            "inflight_messages": len(self.inflight_messages),
            "retry_queue_size": self.retry_queue.qsize(),
            "delivery_tracker_stats": self.delivery_tracker.get_statistics(),
        }
        
    def __str__(self) -> str:
        """String representation of reliable router."""
        return (f"ReliableMessageRouter(node={self.node.id}, "
                f"pending={len(self.pending_messages)}, "
                f"inflight={len(self.inflight_messages)})")
