
"""
Message routing implementation for the Fractal Tree MVP.

This module provides message routing capabilities for communication
between nodes in the fractal tree structure.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Set, Any
from collections import defaultdict, deque
from .message import Message, MessageType, MessagePriority
from .tree_node import TreeNode
from .exceptions import NodeNotFoundError, InvalidNodeError


class MessageRouter:
    """
    Handles message routing and delivery in the fractal tree.
    
    The MessageRouter manages message queues, routing tables, and delivery
    mechanisms for efficient communication between tree nodes.
    """
    
    def __init__(self, node: TreeNode, max_queue_size: int = 1000):
        """
        Initialize the message router for a tree node.
        
        Args:
            node: The tree node this router belongs to.
            max_queue_size: Maximum size of message queues.
        """
        self.node = node
        self.max_queue_size = max_queue_size
        
        # Message queues by priority
        self.message_queues: Dict[MessagePriority, asyncio.Queue] = {
            priority: asyncio.Queue(maxsize=max_queue_size)
            for priority in MessagePriority
        }
        
        # Message handlers by type
        self.message_handlers: Dict[MessageType, List[Callable]] = defaultdict(list)
        
        # Pending acknowledgments
        self.pending_acks: Dict[str, Message] = {}
        
        # Message history for duplicate detection
        self.message_history: Set[str] = set()
        self.max_history_size = 10000
        
        # Routing statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_routed": 0,
            "messages_dropped": 0,
            "acks_sent": 0,
            "acks_received": 0
        }
        
        # Router state
        self.running = False
        self.router_task: Optional[asyncio.Task] = None
        
        # Logger
        self.logger = logging.getLogger(f"MessageRouter.{node.id}")
        
    async def start(self) -> None:
        """Start the message router."""
        if self.running:
            return
            
        self.running = True
        self.router_task = asyncio.create_task(self._router_loop())
        self.logger.info(f"Message router started for node {self.node.id}")
        
    async def stop(self) -> None:
        """Stop the message router."""
        if not self.running:
            return
            
        self.running = False
        if self.router_task:
            self.router_task.cancel()
            try:
                await self.router_task
            except asyncio.CancelledError:
                pass
                
        self.logger.info(f"Message router stopped for node {self.node.id}")
        
    def register_handler(self, message_type: MessageType, handler: Callable) -> None:
        """
        Register a message handler for a specific message type.
        
        Args:
            message_type: Type of message to handle.
            handler: Async function to handle the message.
        """
        self.message_handlers[message_type].append(handler)
        self.logger.debug(f"Registered handler for {message_type.value}")
        
    def unregister_handler(self, message_type: MessageType, handler: Callable) -> None:
        """
        Unregister a message handler.
        
        Args:
            message_type: Type of message.
            handler: Handler function to remove.
        """
        if handler in self.message_handlers[message_type]:
            self.message_handlers[message_type].remove(handler)
            self.logger.debug(f"Unregistered handler for {message_type.value}")
            
    async def send_message(self, message: Message) -> bool:
        """
        Send a message through the router.
        
        Args:
            message: Message to send.
            
        Returns:
            True if message was queued successfully, False otherwise.
        """
        try:
            # Add to appropriate priority queue
            queue = self.message_queues[message.priority]
            await queue.put(message)
            self.stats["messages_sent"] += 1
            
            self.logger.debug(f"Queued message {message.message_id[:8]} for sending")
            return True
            
        except asyncio.QueueFull:
            self.logger.warning(f"Message queue full, dropping message {message.message_id[:8]}")
            self.stats["messages_dropped"] += 1
            return False
            
    async def send_to_parent(self, message: Message) -> bool:
        """Send message to parent node."""
        if self.node.parent is None:
            self.logger.warning("Cannot send to parent: node has no parent")
            return False
            
        message.recipient_id = self.node.parent.id
        return await self.send_message(message)
        
    async def send_to_children(self, message: Message) -> int:
        """
        Send message to all child nodes.
        
        Returns:
            Number of children the message was sent to.
        """
        sent_count = 0
        for child in self.node.children:
            child_message = Message(
                message_type=message.message_type,
                payload=message.payload,
                sender_id=message.sender_id,
                recipient_id=child.id,
                priority=message.priority,
                ttl=message.ttl,
                requires_ack=message.requires_ack,
                correlation_id=message.correlation_id,
                metadata=message.metadata.copy()
            )
            if await self.send_message(child_message):
                sent_count += 1
                
        return sent_count
        
    async def broadcast_message(self, message: Message) -> int:
        """
        Broadcast message to entire subtree.
        
        Returns:
            Number of nodes the message was sent to.
        """
        sent_count = 0
        
        # Send to all descendants
        for descendant in self.node.get_descendants():
            broadcast_message = Message(
                message_type=message.message_type,
                payload=message.payload,
                sender_id=message.sender_id,
                recipient_id=descendant.id,
                priority=message.priority,
                ttl=message.ttl,
                requires_ack=message.requires_ack,
                correlation_id=message.correlation_id,
                metadata=message.metadata.copy()
            )
            if await self.send_message(broadcast_message):
                sent_count += 1
                
        return sent_count
        
    async def receive_message(self, message: Message) -> None:
        """
        Receive and process an incoming message.
        
        Args:
            message: Incoming message to process.
        """
        self.stats["messages_received"] += 1
        
        # Check for duplicate messages
        if message.message_id in self.message_history:
            self.logger.debug(f"Dropping duplicate message {message.message_id[:8]}")
            return
            
        # Add to history
        self._add_to_history(message.message_id)
        
        # Check if message is for this node
        if message.recipient_id == self.node.id or message.recipient_id is None:
            await self._handle_message(message)
        else:
            # Route message to destination
            await self._route_message(message)
            
    async def _handle_message(self, message: Message) -> None:
        """Handle a message destined for this node."""
        self.logger.debug(f"Handling message {message.message_id[:8]} of type {message.message_type.value}")
        
        # Send acknowledgment if required
        if message.requires_ack:
            ack_message = message.create_ack(self.node.id)
            await self.send_message(ack_message)
            self.stats["acks_sent"] += 1
            
        # Process acknowledgments
        if message.message_type == MessageType.RESPONSE and message.correlation_id:
            if message.correlation_id in self.pending_acks:
                del self.pending_acks[message.correlation_id]
                self.stats["acks_received"] += 1
                self.logger.debug(f"Received ack for message {message.correlation_id[:8]}")
                
        # Call registered handlers
        handlers = self.message_handlers.get(message.message_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                self.logger.error(f"Error in message handler: {e}")
                
                # Send error response if message requires ack
                if message.requires_ack:
                    error_message = message.create_error_response(self.node.id, str(e))
                    await self.send_message(error_message)
                    
    async def _route_message(self, message: Message) -> None:
        """Route a message to its destination."""
        if not message.decrement_ttl():
            self.logger.warning(f"Message {message.message_id[:8]} expired (TTL=0)")
            self.stats["messages_dropped"] += 1
            return
            
        self.stats["messages_routed"] += 1
        
        # Simple routing: try to find the target node in the tree
        target_node = self.node.find_node(message.recipient_id)
        
        if target_node:
            # Found target in subtree, route down
            await self._route_down(message, target_node)
        else:
            # Not in subtree, route up to parent
            await self._route_up(message)
            
    async def _route_down(self, message: Message, target_node: TreeNode) -> None:
        """Route message down the tree to target node."""
        # Find path to target
        path = []
        current = target_node
        while current != self.node and current is not None:
            path.append(current)
            current = current.parent
            
        if not path:
            # Target is this node (shouldn't happen)
            await self._handle_message(message)
            return
            
        # Send to next hop (last item in reversed path)
        next_hop = path[-1]
        
        # Find which child leads to the target
        for child in self.node.children:
            if child == next_hop or child.find_node(next_hop.id):
                # Route through this child
                routed_message = Message(
                    message_type=message.message_type,
                    payload=message.payload,
                    sender_id=message.sender_id,
                    recipient_id=message.recipient_id,
                    message_id=message.message_id,
                    timestamp=message.timestamp,
                    priority=message.priority,
                    ttl=message.ttl,
                    requires_ack=message.requires_ack,
                    correlation_id=message.correlation_id,
                    metadata=message.metadata
                )
                await self.send_message(routed_message)
                break
                
    async def _route_up(self, message: Message) -> None:
        """Route message up to parent node."""
        if self.node.parent is None:
            self.logger.warning(f"Cannot route message {message.message_id[:8]}: no parent and target not found")
            self.stats["messages_dropped"] += 1
            return
            
        # Send to parent
        routed_message = Message(
            message_type=message.message_type,
            payload=message.payload,
            sender_id=message.sender_id,
            recipient_id=message.recipient_id,
            message_id=message.message_id,
            timestamp=message.timestamp,
            priority=message.priority,
            ttl=message.ttl,
            requires_ack=message.requires_ack,
            correlation_id=message.correlation_id,
            metadata=message.metadata
        )
        await self.send_message(routed_message)
        
    async def _router_loop(self) -> None:
        """Main router loop that processes messages from queues."""
        while self.running:
            try:
                # Process messages by priority (highest first)
                message_processed = False
                
                for priority in sorted(MessagePriority, key=lambda p: p.value, reverse=True):
                    queue = self.message_queues[priority]
                    
                    try:
                        # Try to get message with short timeout
                        message = await asyncio.wait_for(queue.get(), timeout=0.1)
                        await self._process_outgoing_message(message)
                        message_processed = True
                        break
                    except asyncio.TimeoutError:
                        continue
                        
                # If no messages processed, sleep briefly
                if not message_processed:
                    await asyncio.sleep(0.01)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in router loop: {e}")
                await asyncio.sleep(0.1)
                
    async def _process_outgoing_message(self, message: Message) -> None:
        """Process an outgoing message from the queue."""
        # Track pending acknowledgments
        if message.requires_ack:
            self.pending_acks[message.message_id] = message
            
        # For now, just log the message (actual delivery would depend on transport layer)
        self.logger.debug(f"Processing outgoing message {message.message_id[:8]} to {message.recipient_id}")
        
        # In a real implementation, this would send the message over network/IPC
        # For testing, we'll just mark it as processed
        
    def _add_to_history(self, message_id: str) -> None:
        """Add message ID to history for duplicate detection."""
        self.message_history.add(message_id)
        
        # Limit history size
        if len(self.message_history) > self.max_history_size:
            # Remove oldest entries (simplified - in practice would use LRU)
            excess = len(self.message_history) - self.max_history_size + 100
            for _ in range(excess):
                self.message_history.pop()
                
    def get_statistics(self) -> Dict[str, Any]:
        """Get router statistics."""
        return {
            **self.stats,
            "queue_sizes": {
                priority.name: queue.qsize()
                for priority, queue in self.message_queues.items()
            },
            "pending_acks": len(self.pending_acks),
            "history_size": len(self.message_history),
            "handlers_registered": sum(len(handlers) for handlers in self.message_handlers.values())
        }
        
    def clear_statistics(self) -> None:
        """Clear router statistics."""
        for key in self.stats:
            self.stats[key] = 0
            
    def __str__(self) -> str:
        """String representation of the router."""
        return f"MessageRouter(node={self.node.id}, running={self.running})"
        
    def __repr__(self) -> str:
        """Detailed string representation of the router."""
        return (f"MessageRouter(node={self.node.id}, running={self.running}, "
                f"queues={sum(q.qsize() for q in self.message_queues.values())}, "
                f"handlers={len(self.message_handlers)})")
