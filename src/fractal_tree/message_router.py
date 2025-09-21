
"""
Message routing system for fractal tree communication.

This module provides message routing, fan-out, broadcast, and
delivery management for the fractal tree network.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Callable, Any
from enum import Enum
from dataclasses import dataclass, field
from .message import Message, MessageType, MessagePriority
from .tree_node import TreeNode


class RouteType(Enum):
    """Types of message routes."""
    
    DIRECT = "direct"           # Point-to-point
    FANOUT = "fanout"          # One-to-many (parent to children)
    BROADCAST = "broadcast"     # One-to-all (entire subtree)
    UPSTREAM = "upstream"       # Child to parent chain
    DOWNSTREAM = "downstream"   # Parent to descendant chain


@dataclass
class Route:
    """Represents a message route."""
    
    route_type: RouteType
    source_id: str
    target_ids: Set[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class MessageRouter:
    """
    Routes messages within the fractal tree network.
    
    Provides intelligent routing, fan-out, broadcast capabilities,
    and delivery tracking for tree-structured communication.
    """
    
    def __init__(self, node: TreeNode):
        """
        Initialize message router.
        
        Args:
            node: The tree node this router serves.
        """
        self.node = node
        
        # Message handlers
        self.message_handlers: Dict[MessageType, List[Callable]] = {}
        self.route_handlers: Dict[RouteType, Callable] = {}
        
        # Message queues
        self.outbound_queue: asyncio.Queue = asyncio.Queue()
        self.inbound_queue: asyncio.Queue = asyncio.Queue()
        
        # Routing tables
        self.routing_table: Dict[str, str] = {}  # node_id -> next_hop
        self.neighbor_nodes: Dict[str, TreeNode] = {}
        
        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_routed": 0,
            "fanout_messages": 0,
            "broadcast_messages": 0,
            "routing_errors": 0
        }
        
        # Background tasks
        self.running = False
        self.router_task: Optional[asyncio.Task] = None
        
        # Logger
        self.logger = logging.getLogger(f"MessageRouter.{node.id}")
        
        # Initialize default route handlers
        self._setup_default_handlers()
    
    def _setup_default_handlers(self) -> None:
        """Setup default route handlers."""
        self.route_handlers = {
            RouteType.DIRECT: self._handle_direct_route,
            RouteType.FANOUT: self._handle_fanout_route,
            RouteType.BROADCAST: self._handle_broadcast_route,
            RouteType.UPSTREAM: self._handle_upstream_route,
            RouteType.DOWNSTREAM: self._handle_downstream_route
        }
    
    async def start(self) -> None:
        """Start the message router."""
        if self.running:
            return
            
        self.running = True
        self.router_task = asyncio.create_task(self._router_loop())
        
        # Build initial routing table
        await self._rebuild_routing_table()
        
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
    
    async def send_message(self, message: Message, route_type: RouteType = RouteType.DIRECT) -> bool:
        """
        Send a message using specified routing.
        
        Args:
            message: Message to send.
            route_type: Type of routing to use.
            
        Returns:
            True if message was queued successfully.
        """
        try:
            # Create route based on message and route type
            route = await self._create_route(message, route_type)
            
            # Queue message for processing
            await self.outbound_queue.put((message, route))
            
            self.stats["messages_sent"] += 1
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending message: {e}")
            self.stats["routing_errors"] += 1
            return False
    
    async def receive_message(self, message: Message) -> None:
        """
        Receive an incoming message.
        
        Args:
            message: Incoming message to process.
        """
        await self.inbound_queue.put(message)
        self.stats["messages_received"] += 1
    
    async def fanout_to_children(self, message: Message) -> int:
        """
        Fan out message to all child nodes.
        
        Args:
            message: Message to fan out.
            
        Returns:
            Number of children the message was sent to.
        """
        children = self.node.children
        if not children:
            return 0
            
        # Create fanout copies
        sent_count = 0
        for child in children:
            child_message = Message(
                message_type=message.message_type,
                payload=message.payload,
                sender_id=message.sender_id,
                recipient_id=child.id,
                priority=message.priority,
                requires_ack=message.requires_ack,
                metadata=message.metadata.copy()
            )
            
            if await self.send_message(child_message, RouteType.DIRECT):
                sent_count += 1
                
        self.stats["fanout_messages"] += 1
        self.logger.debug(f"Fanned out message to {sent_count} children")
        return sent_count
    
    async def broadcast_to_subtree(self, message: Message) -> int:
        """
        Broadcast message to entire subtree.
        
        Args:
            message: Message to broadcast.
            
        Returns:
            Number of nodes the message was sent to.
        """
        descendants = self.node.get_descendants()
        if not descendants:
            return 0
            
        sent_count = 0
        for descendant in descendants:
            broadcast_message = Message(
                message_type=message.message_type,
                payload=message.payload,
                sender_id=message.sender_id,
                recipient_id=descendant.id,
                priority=message.priority,
                requires_ack=message.requires_ack,
                metadata=message.metadata.copy()
            )
            
            if await self.send_message(broadcast_message, RouteType.DIRECT):
                sent_count += 1
                
        self.stats["broadcast_messages"] += 1
        self.logger.debug(f"Broadcast message to {sent_count} descendants")
        return sent_count
    
    def register_message_handler(self, message_type: MessageType, handler: Callable) -> None:
        """Register a handler for specific message type."""
        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []
        self.message_handlers[message_type].append(handler)
    
    def register_route_handler(self, route_type: RouteType, handler: Callable) -> None:
        """Register a custom route handler."""
        self.route_handlers[route_type] = handler
    
    async def _router_loop(self) -> None:
        """Main router processing loop."""
        while self.running:
            try:
                # Process outbound messages
                outbound_task = asyncio.create_task(self._process_outbound())
                
                # Process inbound messages
                inbound_task = asyncio.create_task(self._process_inbound())
                
                # Wait for either task to complete
                done, pending = await asyncio.wait(
                    [outbound_task, inbound_task],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=1.0
                )
                
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in router loop: {e}")
                await asyncio.sleep(0.1)
    
    async def _process_outbound(self) -> None:
        """Process outbound message queue."""
        try:
            message, route = await asyncio.wait_for(self.outbound_queue.get(), timeout=1.0)
            await self._route_message(message, route)
            self.stats["messages_routed"] += 1
        except asyncio.TimeoutError:
            pass
    
    async def _process_inbound(self) -> None:
        """Process inbound message queue."""
        try:
            message = await asyncio.wait_for(self.inbound_queue.get(), timeout=1.0)
            await self._handle_inbound_message(message)
        except asyncio.TimeoutError:
            pass
    
    async def _route_message(self, message: Message, route: Route) -> None:
        """Route a message using the specified route."""
        handler = self.route_handlers.get(route.route_type)
        if handler:
            await handler(message, route)
        else:
            self.logger.warning(f"No handler for route type: {route.route_type}")
    
    async def _handle_inbound_message(self, message: Message) -> None:
        """Handle an inbound message."""
        handlers = self.message_handlers.get(message.message_type, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
            except Exception as e:
                self.logger.error(f"Error in message handler: {e}")
    
    async def _create_route(self, message: Message, route_type: RouteType) -> Route:
        """Create a route for the message."""
        if route_type == RouteType.DIRECT:
            target_ids = {message.recipient_id} if message.recipient_id else set()
        elif route_type == RouteType.FANOUT:
            target_ids = {child.id for child in self.node.children}
        elif route_type == RouteType.BROADCAST:
            target_ids = {desc.id for desc in self.node.get_descendants()}
        elif route_type == RouteType.UPSTREAM:
            target_ids = {anc.id for anc in self.node.get_ancestors()}
        else:
            target_ids = set()
            
        return Route(
            route_type=route_type,
            source_id=self.node.id,
            target_ids=target_ids
        )
    
    async def _handle_direct_route(self, message: Message, route: Route) -> None:
        """Handle direct routing."""
        # This is a stub - in a real implementation, this would
        # send the message to the target node
        self.logger.debug(f"Direct route: {message} to {route.target_ids}")
    
    async def _handle_fanout_route(self, message: Message, route: Route) -> None:
        """Handle fanout routing."""
        await self.fanout_to_children(message)
    
    async def _handle_broadcast_route(self, message: Message, route: Route) -> None:
        """Handle broadcast routing."""
        await self.broadcast_to_subtree(message)
    
    async def _handle_upstream_route(self, message: Message, route: Route) -> None:
        """Handle upstream routing."""
        # Send to parent
        parent = self.node.parent
        if parent:
            upstream_message = Message(
                message_type=message.message_type,
                payload=message.payload,
                sender_id=message.sender_id,
                recipient_id=parent.id,
                priority=message.priority,
                requires_ack=message.requires_ack,
                metadata=message.metadata.copy()
            )
            await self.send_message(upstream_message, RouteType.DIRECT)
    
    async def _handle_downstream_route(self, message: Message, route: Route) -> None:
        """Handle downstream routing."""
        # Send to all descendants
        await self.broadcast_to_subtree(message)
    
    async def _rebuild_routing_table(self) -> None:
        """Rebuild the routing table based on current tree structure."""
        self.routing_table.clear()
        
        # Add direct children
        for child in self.node.children:
            self.routing_table[child.id] = child.id
            
        # Add parent
        parent = self.node.parent
        if parent:
            self.routing_table[parent.id] = parent.id
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            **self.stats,
            "routing_table_size": len(self.routing_table),
            "registered_handlers": {
                msg_type.value: len(handlers) 
                for msg_type, handlers in self.message_handlers.items()
            },
            "queue_sizes": {
                "outbound": self.outbound_queue.qsize(),
                "inbound": self.inbound_queue.qsize()
            }
        }
    
    def __str__(self) -> str:
        """String representation of the router."""
        return f"MessageRouter(node={self.node.id}, routes={len(self.routing_table)})"
