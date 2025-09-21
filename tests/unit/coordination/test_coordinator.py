
"""
Unit tests for Coordinator class.

Tests cover coordination session management, state transitions,
and message handling functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fractal_tree import TreeNode
from fractal_tree.coordination import Coordinator, CoordinationState, CoordinationSession
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


class TestCoordinatorCreation:
    """Test Coordinator creation and initialization."""
    
    def test_create_coordinator(self):
        """Test creating a coordinator."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        assert coordinator.node == node
        assert coordinator.heartbeat_interval == 30.0
        assert coordinator.current_state == CoordinationState.DISCONNECTED
        assert not coordinator.running
        assert len(coordinator.sessions) == 0


class TestCoordinatorLifecycle:
    """Test coordinator lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_coordinator(self, mock_event_loop):
        """Test starting and stopping the coordinator."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        # Start coordinator
        await coordinator.start()
        assert coordinator.running
        assert coordinator.heartbeat_task is not None
        
        # Stop coordinator
        await coordinator.stop()
        assert not coordinator.running


class TestCoordinationSessions:
    """Test coordination session management."""
    
    @pytest.mark.asyncio
    async def test_initiate_coordination(self, mock_event_loop):
        """Test initiating coordination with children."""
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        parent.add_child(child1)
        parent.add_child(child2)
        
        coordinator = Coordinator(parent)
        await coordinator.start()
        
        # Initiate coordination
        session_id = await coordinator.initiate_coordination()
        
        assert session_id is not None
        assert session_id in coordinator.sessions
        
        session = coordinator.sessions[session_id]
        assert session.parent_id == "parent"
        assert session.child_ids == {"child1", "child2"}
        assert session.state == CoordinationState.CONNECTING
        assert coordinator.current_state == CoordinationState.CONNECTING
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_initiate_coordination_specific_children(self, mock_event_loop):
        """Test initiating coordination with specific children."""
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        child3 = TreeNode(node_id="child3")
        
        parent.add_child(child1)
        parent.add_child(child2)
        parent.add_child(child3)
        
        coordinator = Coordinator(parent)
        await coordinator.start()
        
        # Initiate coordination with specific children
        session_id = await coordinator.initiate_coordination(["child1", "child3"])
        
        session = coordinator.sessions[session_id]
        assert session.child_ids == {"child1", "child3"}
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_execute_command(self, mock_event_loop):
        """Test executing coordination commands."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create a session in synchronized state
        session_id = "test-session"
        session = CoordinationSession(
            session_id=session_id,
            parent_id="test-node",
            state=CoordinationState.SYNCHRONIZED
        )
        coordinator.sessions[session_id] = session
        
        # Execute command
        result = await coordinator.execute_command(
            session_id, "test_command", {"param1": "value1"}
        )
        
        assert result is True
        assert coordinator.stats["commands_executed"] == 1
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_execute_command_invalid_session(self, mock_event_loop):
        """Test executing command with invalid session."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Try to execute command on non-existent session
        result = await coordinator.execute_command(
            "invalid-session", "test_command", {}
        )
        
        assert result is False
        assert coordinator.stats["commands_executed"] == 0
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_execute_command_wrong_state(self, mock_event_loop):
        """Test executing command in wrong state."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create session in connecting state
        session_id = "test-session"
        session = CoordinationSession(
            session_id=session_id,
            parent_id="test-node",
            state=CoordinationState.CONNECTING
        )
        coordinator.sessions[session_id] = session
        
        # Try to execute command
        result = await coordinator.execute_command(
            session_id, "test_command", {}
        )
        
        assert result is False
        assert coordinator.stats["commands_executed"] == 0
        
        await coordinator.stop()


class TestMessageHandling:
    """Test coordination message handling."""
    
    @pytest.mark.asyncio
    async def test_handle_ready_message(self, mock_event_loop):
        """Test handling COORD_READY message."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create session in connecting state
        session_id = "test-session"
        session = CoordinationSession(
            session_id=session_id,
            parent_id="test-node",
            state=CoordinationState.CONNECTING
        )
        coordinator.sessions[session_id] = session
        
        # Create ready message
        message = Message(
            message_type=MessageType.COMMAND,
            payload={"status": "ready"},
            sender_id="child1",
            recipient_id="test-node",
            metadata={
                "coordination_type": "COORD_READY",
                "session_id": session_id
            }
        )
        
        # Handle message
        await coordinator.handle_coordination_message(message)
        
        # Session should transition to synchronized
        assert session.state == CoordinationState.SYNCHRONIZED
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_handle_error_message(self, mock_event_loop):
        """Test handling COORD_ERROR message."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create session in synchronized state
        session_id = "test-session"
        session = CoordinationSession(
            session_id=session_id,
            parent_id="test-node",
            state=CoordinationState.SYNCHRONIZED
        )
        coordinator.sessions[session_id] = session
        
        # Create error message
        message = Message(
            message_type=MessageType.ERROR,
            payload={"error": "Test error"},
            sender_id="child1",
            recipient_id="test-node",
            metadata={
                "coordination_type": "COORD_ERROR",
                "session_id": session_id
            }
        )
        
        # Handle message
        await coordinator.handle_coordination_message(message)
        
        # Session should transition to degraded
        assert session.state == CoordinationState.DEGRADED
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_handle_heartbeat_message(self, mock_event_loop, fake_clock):
        """Test handling COORD_HEARTBEAT message."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create session
        session_id = "test-session"
        session = CoordinationSession(
            session_id=session_id,
            parent_id="test-node"
        )
        coordinator.sessions[session_id] = session
        
        initial_time = fake_clock.time()
        fake_clock.advance(10.0)
        
        # Create heartbeat message
        message = Message(
            message_type=MessageType.HEARTBEAT,
            payload={"timestamp": fake_clock.time()},
            sender_id="child1",
            recipient_id="test-node",
            metadata={
                "coordination_type": "COORD_HEARTBEAT",
                "session_id": session_id
            }
        )
        
        # Handle message
        await coordinator.handle_coordination_message(message)
        
        # Check heartbeat was recorded
        assert session.last_heartbeat == fake_clock.time()
        assert coordinator.stats["heartbeats_received"] == 1
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_handle_invalid_message(self, mock_event_loop):
        """Test handling invalid coordination message."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create message without coordination metadata
        message = Message(
            message_type=MessageType.COMMAND,
            payload={"test": "data"},
            sender_id="child1",
            recipient_id="test-node"
        )
        
        # Handle message (should not crash)
        await coordinator.handle_coordination_message(message)
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_handle_unknown_session_message(self, mock_event_loop):
        """Test handling message for unknown session."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create message for unknown session
        message = Message(
            message_type=MessageType.COMMAND,
            payload={"status": "ready"},
            sender_id="child1",
            recipient_id="test-node",
            metadata={
                "coordination_type": "COORD_READY",
                "session_id": "unknown-session"
            }
        )
        
        # Handle message (should not crash)
        await coordinator.handle_coordination_message(message)
        
        await coordinator.stop()


class TestStateTransitions:
    """Test coordinator state transitions."""
    
    @pytest.mark.asyncio
    async def test_state_transition_callbacks(self, mock_event_loop):
        """Test state transition callbacks."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        # Register callback
        callback_called = False
        old_state = None
        new_state = None
        
        def state_callback(old, new):
            nonlocal callback_called, old_state, new_state
            callback_called = True
            old_state = old
            new_state = new
        
        coordinator.register_state_callback(CoordinationState.CONNECTING, state_callback)
        
        await coordinator.start()
        
        # Trigger state transition
        await coordinator._transition_state(CoordinationState.CONNECTING)
        
        assert callback_called
        assert old_state == CoordinationState.DISCONNECTED
        assert new_state == CoordinationState.CONNECTING
        
        await coordinator.stop()
    
    @pytest.mark.asyncio
    async def test_async_state_callback(self, mock_event_loop):
        """Test async state transition callback."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        # Register async callback
        callback_called = False
        
        async def async_callback(old, new):
            nonlocal callback_called
            callback_called = True
        
        coordinator.register_state_callback(CoordinationState.CONNECTING, async_callback)
        
        await coordinator.start()
        
        # Trigger state transition
        await coordinator._transition_state(CoordinationState.CONNECTING)
        
        assert callback_called
        
        await coordinator.stop()


class TestHeartbeatLoop:
    """Test heartbeat loop functionality."""
    
    @pytest.mark.asyncio
    async def test_heartbeat_loop_sends_heartbeats(self, mock_event_loop, fake_clock):
        """Test that heartbeat loop sends heartbeats."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node, heartbeat_interval=1.0)
        
        # Create session in synchronized state
        session_id = "test-session"
        session = CoordinationSession(
            session_id=session_id,
            parent_id="test-node",
            state=CoordinationState.SYNCHRONIZED
        )
        coordinator.sessions[session_id] = session
        
        await coordinator.start()
        
        initial_heartbeats = coordinator.stats["heartbeats_sent"]
        
        # Let some time pass
        fake_clock.advance(2.0)
        await asyncio.sleep(0.1)  # Allow heartbeat loop to run
        
        # Should have sent heartbeats
        assert coordinator.stats["heartbeats_sent"] > initial_heartbeats
        
        await coordinator.stop()


class TestStatistics:
    """Test coordinator statistics."""
    
    @pytest.mark.asyncio
    async def test_get_statistics(self, mock_event_loop):
        """Test getting coordinator statistics."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        await coordinator.start()
        
        # Create some sessions
        session1 = CoordinationSession("session1", "test-node")
        session2 = CoordinationSession("session2", "test-node")
        coordinator.sessions["session1"] = session1
        coordinator.sessions["session2"] = session2
        
        stats = coordinator.get_statistics()
        
        assert stats["active_sessions"] == 2
        assert stats["current_state"] == CoordinationState.DISCONNECTED.value
        assert stats["heartbeat_interval"] == 30.0
        assert "sessions_created" in stats
        assert "commands_executed" in stats
        
        await coordinator.stop()


class TestCoordinatorIntegration:
    """Integration tests for coordinator functionality."""
    
    @pytest.mark.asyncio
    async def test_full_coordination_flow(self, mock_event_loop, fake_clock):
        """Test complete coordination flow."""
        # Create parent-child structure
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        parent.add_child(child1)
        parent.add_child(child2)
        
        coordinator = Coordinator(parent)
        await coordinator.start()
        
        # 1. Initiate coordination
        session_id = await coordinator.initiate_coordination()
        assert coordinator.current_state == CoordinationState.CONNECTING
        
        # 2. Simulate children becoming ready
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
        
        await coordinator.handle_coordination_message(ready_msg1)
        await coordinator.handle_coordination_message(ready_msg2)
        
        # Session should be synchronized
        session = coordinator.sessions[session_id]
        assert session.state == CoordinationState.SYNCHRONIZED
        
        # 3. Execute command
        result = await coordinator.execute_command(
            session_id, "test_command", {"param": "value"}
        )
        assert result is True
        
        # 4. Simulate heartbeats
        fake_clock.advance(35.0)  # Advance past heartbeat interval
        
        heartbeat_msg = Message(
            message_type=MessageType.HEARTBEAT,
            payload={"timestamp": fake_clock.time()},
            sender_id="child1",
            metadata={
                "coordination_type": "COORD_HEARTBEAT",
                "session_id": session_id
            }
        )
        
        await coordinator.handle_coordination_message(heartbeat_msg)
        assert coordinator.stats["heartbeats_received"] == 1
        
        await coordinator.stop()
