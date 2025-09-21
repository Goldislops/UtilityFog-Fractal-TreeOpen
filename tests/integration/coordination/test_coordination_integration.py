
"""
Integration tests for coordination protocol.

Tests cover end-to-end coordination scenarios, state transitions,
backpressure handling, and recovery paths.
"""

import pytest
import asyncio
from unittest.mock import patch
from fractal_tree import TreeNode
from fractal_tree.coordination import (
    Coordinator, CoordinationState, SessionManager, BackpressureManager,
    BackpressureState, SessionEvent
)
from fractal_tree.message import Message, MessageType, MessagePriority


class FakeClock:
    """Fake clock for deterministic time-based testing."""
    
    def __init__(self, start_time: float = 0.0):
        self.current_time = start_time
    
    def time(self) -> float:
        return self.current_time
    
    def advance(self, seconds: float) -> None:
        self.current_time += seconds


@pytest.fixture
def fake_clock():
    """Provide a fake clock for testing."""
    return FakeClock()


@pytest.fixture
def mock_event_loop(fake_clock):
    """Mock event loop with fake clock."""
    with patch('asyncio.get_event_loop') as mock_loop:
        mock_loop.return_value.time.side_effect = fake_clock.time
        yield mock_loop


class TestCoordinationIntegration:
    """Test coordination protocol integration."""
    
    @pytest.mark.asyncio
    async def test_parent_child_coordination_flow(self, mock_event_loop, fake_clock):
        """Test complete parent-child coordination flow."""
        # Create tree structure
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        parent.add_child(child1)
        parent.add_child(child2)
        
        # Create coordinators
        parent_coordinator = Coordinator(parent, heartbeat_interval=10.0)
        child1_session_manager = SessionManager("child1")
        child2_session_manager = SessionManager("child2")
        
        # Start all components
        await parent_coordinator.start()
        await child1_session_manager.start()
        await child2_session_manager.start()
        
        try:
            # 1. Parent initiates coordination
            session_id = await parent_coordinator.initiate_coordination()
            assert parent_coordinator.current_state == CoordinationState.CONNECTING
            
            # 2. Children join session
            child1_session = await child1_session_manager.request_join("parent")
            child2_session = await child2_session_manager.request_join("parent")
            
            assert child1_session is not None
            assert child2_session is not None
            
            # 3. Simulate children becoming ready
            ready_msg1 = Message(
                message_type=MessageType.COMMAND,
                payload={"status": "ready"},
                sender_id="child1",
                metadata={
                    "coordination_type": "COORD_READY",
                    "session_id": session_id
                }
            )
            
            ready_msg2 = Message(
                message_type=MessageType.COMMAND,
                payload={"status": "ready"},
                sender_id="child2",
                metadata={
                    "coordination_type": "COORD_READY",
                    "session_id": session_id
                }
            )
            
            await parent_coordinator.handle_coordination_message(ready_msg1)
            await parent_coordinator.handle_coordination_message(ready_msg2)
            
            # Session should be synchronized
            session = parent_coordinator.sessions[session_id]
            assert session.state == CoordinationState.SYNCHRONIZED
            
            # 4. Execute coordination command
            result = await parent_coordinator.execute_command(
                session_id, "sync_data", {"data": "test_payload"}
            )
            assert result is True
            
            # 5. Handle heartbeats
            fake_clock.advance(15.0)
            
            await child1_session_manager.handle_heartbeat(child1_session, "parent")
            await child2_session_manager.handle_heartbeat(child2_session, "parent")
            
            heartbeat_msg = Message(
                message_type=MessageType.HEARTBEAT,
                payload={"timestamp": fake_clock.time()},
                sender_id="child1",
                metadata={
                    "coordination_type": "COORD_HEARTBEAT",
                    "session_id": session_id
                }
            )
            
            await parent_coordinator.handle_coordination_message(heartbeat_msg)
            
            # Check statistics
            parent_stats = parent_coordinator.get_statistics()
            assert parent_stats["active_sessions"] == 1
            assert parent_stats["commands_executed"] == 1
            assert parent_stats["heartbeats_received"] == 1
            
            child1_metrics = child1_session_manager.get_session_metrics(child1_session)
            assert child1_metrics["heartbeat_count"] == 1
            
        finally:
            # Cleanup
            await parent_coordinator.stop()
            await child1_session_manager.stop()
            await child2_session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_coordination_with_backpressure(self, mock_event_loop, fake_clock):
        """Test coordination with backpressure management."""
        # Create tree structure
        parent = TreeNode(node_id="parent")
        child = TreeNode(node_id="child")
        parent.add_child(child)
        
        # Create components
        coordinator = Coordinator(parent)
        session_manager = SessionManager("child")
        
        await coordinator.start()
        await session_manager.start()
        
        try:
            # Start coordination
            session_id = await coordinator.initiate_coordination()
            child_session = await session_manager.request_join("parent")
            
            # Get backpressure manager from session manager
            bp_manager = session_manager.backpressure_managers[child_session]
            
            # Register queue for monitoring
            test_queue = asyncio.Queue(maxsize=100)
            bp_manager.register_queue("test_queue", test_queue, 100)
            
            # Fill queue to trigger backpressure
            for _ in range(95):  # 95% utilization
                await test_queue.put("item")
            
            # Update metrics manually (normally done by monitor loop)
            bp_manager.queue_metrics["test_queue"].queue_size = 95
            bp_manager.queue_metrics["test_queue"].utilization = 0.95
            
            # Check backpressure state
            await bp_manager._check_backpressure()
            assert bp_manager.current_state == BackpressureState.PAUSED
            
            # Create and handle PAUSE message
            pause_msg = bp_manager.create_pause_message("child", "parent")
            await bp_manager.handle_backpressure_message(pause_msg)
            
            assert bp_manager.is_paused is True
            
            # Drain queue to relieve backpressure
            for _ in range(50):  # Drain to 45% utilization
                await test_queue.get()
            
            bp_manager.queue_metrics["test_queue"].queue_size = 45
            bp_manager.queue_metrics["test_queue"].utilization = 0.45
            
            await bp_manager._check_backpressure()
            assert bp_manager.current_state == BackpressureState.NORMAL
            
            # Create and handle RESUME message
            resume_msg = bp_manager.create_resume_message("child", "parent")
            await bp_manager.handle_backpressure_message(resume_msg)
            
            assert bp_manager.is_paused is False
            
        finally:
            await coordinator.stop()
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_coordination_failure_recovery(self, mock_event_loop, fake_clock):
        """Test coordination failure and recovery scenarios."""
        # Create tree structure
        parent = TreeNode(node_id="parent")
        child = TreeNode(node_id="child")
        parent.add_child(child)
        
        # Create components
        coordinator = Coordinator(parent)
        session_manager = SessionManager("child")
        
        # Track events
        events = []
        
        def track_events(event, session_id, data):
            events.append((event, session_id, data))
        
        session_manager.register_event_callback(SessionEvent.HEARTBEAT_TIMEOUT, track_events)
        session_manager.register_event_callback(SessionEvent.REJOIN_REQUEST, track_events)
        
        await coordinator.start()
        await session_manager.start()
        
        try:
            # 1. Start coordination
            coord_session_id = await coordinator.initiate_coordination()
            child_session_id = await session_manager.request_join("parent")
            
            # 2. Simulate error condition
            error_msg = Message(
                message_type=MessageType.ERROR,
                payload={"error": "Connection lost"},
                sender_id="child",
                metadata={
                    "coordination_type": "COORD_ERROR",
                    "session_id": coord_session_id
                }
            )
            
            await coordinator.handle_coordination_message(error_msg)
            
            # Session should be degraded
            session = coordinator.sessions[coord_session_id]
            assert session.state == CoordinationState.DEGRADED
            
            # 3. Simulate heartbeat timeout
            fake_clock.advance(100.0)  # Past heartbeat timeout
            await session_manager._check_heartbeat_timeouts()
            
            # Should have timeout event
            timeout_events = [e for e in events if e[0] == SessionEvent.HEARTBEAT_TIMEOUT]
            assert len(timeout_events) == 1
            
            # 4. Attempt rejoin
            rejoin_result = await session_manager.request_rejoin(child_session_id)
            assert rejoin_result is True
            
            # Should have rejoin event
            rejoin_events = [e for e in events if e[0] == SessionEvent.REJOIN_REQUEST]
            assert len(rejoin_events) == 1
            
            # 5. Simulate recovery
            ready_msg = Message(
                message_type=MessageType.COMMAND,
                payload={"status": "ready"},
                sender_id="child",
                metadata={
                    "coordination_type": "COORD_READY",
                    "session_id": coord_session_id
                }
            )
            
            await coordinator.handle_coordination_message(ready_msg)
            
            # Session should recover to synchronized
            assert session.state == CoordinationState.SYNCHRONIZED
            
        finally:
            await coordinator.stop()
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_multi_child_coordination_with_failures(self, mock_event_loop, fake_clock):
        """Test coordination with multiple children and partial failures."""
        # Create tree structure
        parent = TreeNode(node_id="parent")
        children = []
        session_managers = []
        
        for i in range(3):
            child = TreeNode(node_id=f"child{i}")
            parent.add_child(child)
            children.append(child)
            
            session_manager = SessionManager(f"child{i}")
            session_managers.append(session_manager)
        
        coordinator = Coordinator(parent)
        
        # Start all components
        await coordinator.start()
        for sm in session_managers:
            await sm.start()
        
        try:
            # 1. Start coordination
            session_id = await coordinator.initiate_coordination()
            
            # 2. All children join
            child_sessions = []
            for i, sm in enumerate(session_managers):
                child_session = await sm.request_join("parent")
                child_sessions.append(child_session)
            
            # 3. Two children become ready
            for i in range(2):
                ready_msg = Message(
                    message_type=MessageType.COMMAND,
                    payload={"status": "ready"},
                    sender_id=f"child{i}",
                    metadata={
                        "coordination_type": "COORD_READY",
                        "session_id": session_id
                    }
                )
                await coordinator.handle_coordination_message(ready_msg)
            
            # Session should be synchronized (simplified logic)
            session = coordinator.sessions[session_id]
            assert session.state == CoordinationState.SYNCHRONIZED
            
            # 4. One child reports error
            error_msg = Message(
                message_type=MessageType.ERROR,
                payload={"error": "Processing failed"},
                sender_id="child2",
                metadata={
                    "coordination_type": "COORD_ERROR",
                    "session_id": session_id
                }
            )
            
            await coordinator.handle_coordination_message(error_msg)
            
            # Session should be degraded
            assert session.state == CoordinationState.DEGRADED
            
            # 5. Failed child recovers
            recovery_msg = Message(
                message_type=MessageType.COMMAND,
                payload={"status": "ready"},
                sender_id="child2",
                metadata={
                    "coordination_type": "COORD_READY",
                    "session_id": session_id
                }
            )
            
            await coordinator.handle_coordination_message(recovery_msg)
            
            # Session should recover
            assert session.state == CoordinationState.SYNCHRONIZED
            
            # 6. Execute command with all children ready
            result = await coordinator.execute_command(
                session_id, "distributed_task", {"task_id": "task_123"}
            )
            assert result is True
            
        finally:
            await coordinator.stop()
            for sm in session_managers:
                await sm.stop()
    
    @pytest.mark.asyncio
    async def test_coordination_state_machine_transitions(self, mock_event_loop, fake_clock):
        """Test complete state machine transitions."""
        parent = TreeNode(node_id="parent")
        child = TreeNode(node_id="child")
        parent.add_child(child)
        
        coordinator = Coordinator(parent)
        session_manager = SessionManager("child")
        
        # Track state transitions
        state_transitions = []
        
        def track_state_transitions(old_state, new_state):
            state_transitions.append((old_state, new_state))
        
        coordinator.register_state_callback(CoordinationState.CONNECTING, track_state_transitions)
        coordinator.register_state_callback(CoordinationState.SYNCHRONIZED, track_state_transitions)
        coordinator.register_state_callback(CoordinationState.DEGRADED, track_state_transitions)
        coordinator.register_state_callback(CoordinationState.FAILED, track_state_transitions)
        
        await coordinator.start()
        await session_manager.start()
        
        try:
            # 1. DISCONNECTED → CONNECTING
            session_id = await coordinator.initiate_coordination()
            assert coordinator.current_state == CoordinationState.CONNECTING
            
            # 2. CONNECTING → SYNCHRONIZED
            ready_msg = Message(
                message_type=MessageType.COMMAND,
                payload={"status": "ready"},
                sender_id="child",
                metadata={
                    "coordination_type": "COORD_READY",
                    "session_id": session_id
                }
            )
            await coordinator.handle_coordination_message(ready_msg)
            
            session = coordinator.sessions[session_id]
            assert session.state == CoordinationState.SYNCHRONIZED
            
            # 3. SYNCHRONIZED → DEGRADED
            error_msg = Message(
                message_type=MessageType.ERROR,
                payload={"error": "Temporary failure"},
                sender_id="child",
                metadata={
                    "coordination_type": "COORD_ERROR",
                    "session_id": session_id
                }
            )
            await coordinator.handle_coordination_message(error_msg)
            assert session.state == CoordinationState.DEGRADED
            
            # 4. DEGRADED → SYNCHRONIZED (recovery)
            await coordinator.handle_coordination_message(ready_msg)
            assert session.state == CoordinationState.SYNCHRONIZED
            
            # Check state transitions were recorded
            assert len(state_transitions) >= 2
            assert (CoordinationState.DISCONNECTED, CoordinationState.CONNECTING) in state_transitions
            
        finally:
            await coordinator.stop()
            await session_manager.stop()


class TestCoordinationPerformance:
    """Test coordination protocol performance characteristics."""
    
    @pytest.mark.asyncio
    async def test_high_frequency_heartbeats(self, mock_event_loop, fake_clock):
        """Test handling high frequency heartbeats."""
        parent = TreeNode(node_id="parent")
        child = TreeNode(node_id="child")
        parent.add_child(child)
        
        coordinator = Coordinator(parent, heartbeat_interval=0.1)  # Very frequent
        session_manager = SessionManager("child")
        
        await coordinator.start()
        await session_manager.start()
        
        try:
            session_id = await coordinator.initiate_coordination()
            child_session = await session_manager.request_join("parent")
            
            # Send many heartbeats rapidly
            for i in range(100):
                fake_clock.advance(0.05)  # 50ms intervals
                
                heartbeat_msg = Message(
                    message_type=MessageType.HEARTBEAT,
                    payload={"timestamp": fake_clock.time()},
                    sender_id="child",
                    metadata={
                        "coordination_type": "COORD_HEARTBEAT",
                        "session_id": session_id
                    }
                )
                
                await coordinator.handle_coordination_message(heartbeat_msg)
                await session_manager.handle_heartbeat(child_session, "parent")
            
            # Check statistics
            assert coordinator.stats["heartbeats_received"] == 100
            
            child_metrics = session_manager.get_session_metrics(child_session)
            assert child_metrics["heartbeat_count"] == 100
            
        finally:
            await coordinator.stop()
            await session_manager.stop()
    
    @pytest.mark.asyncio
    async def test_many_concurrent_sessions(self, mock_event_loop, fake_clock):
        """Test handling many concurrent coordination sessions."""
        parent = TreeNode(node_id="parent")
        
        # Create many children
        num_children = 50
        children = []
        session_managers = []
        
        for i in range(num_children):
            child = TreeNode(node_id=f"child{i}")
            parent.add_child(child)
            children.append(child)
            
            session_manager = SessionManager(f"child{i}")
            session_managers.append(session_manager)
        
        coordinator = Coordinator(parent)
        
        await coordinator.start()
        for sm in session_managers:
            await sm.start()
        
        try:
            # Start coordination with all children
            session_id = await coordinator.initiate_coordination()
            
            # All children join
            child_sessions = []
            for sm in session_managers:
                child_session = await sm.request_join("parent")
                child_sessions.append(child_session)
            
            # All children become ready
            for i in range(num_children):
                ready_msg = Message(
                    message_type=MessageType.COMMAND,
                    payload={"status": "ready"},
                    sender_id=f"child{i}",
                    metadata={
                        "coordination_type": "COORD_READY",
                        "session_id": session_id
                    }
                )
                await coordinator.handle_coordination_message(ready_msg)
            
            # Check all sessions are active
            assert len(coordinator.sessions) == 1  # One coordination session
            assert len(session_managers[0].sessions) == 1  # Each child has one session
            
            # Execute command
            result = await coordinator.execute_command(
                session_id, "broadcast_task", {"data": "test"}
            )
            assert result is True
            
            # Send heartbeats from all children
            fake_clock.advance(1.0)
            for i, (sm, child_session) in enumerate(zip(session_managers, child_sessions)):
                await sm.handle_heartbeat(child_session, "parent")
                
                heartbeat_msg = Message(
                    message_type=MessageType.HEARTBEAT,
                    payload={"timestamp": fake_clock.time()},
                    sender_id=f"child{i}",
                    metadata={
                        "coordination_type": "COORD_HEARTBEAT",
                        "session_id": session_id
                    }
                )
                await coordinator.handle_coordination_message(heartbeat_msg)
            
            # Check statistics
            assert coordinator.stats["heartbeats_received"] == num_children
            
        finally:
            await coordinator.stop()
            for sm in session_managers:
                await sm.stop()
