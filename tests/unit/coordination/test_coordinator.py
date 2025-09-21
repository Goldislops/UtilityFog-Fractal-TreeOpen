
"""
Unit tests for Coordinator class.

Tests cover coordinator lifecycle, session management, and
coordination protocol handling.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fractal_tree import TreeNode
from fractal_tree.coordination import Coordinator, CoordinationState


class TestCoordinatorCreation:
    """Test Coordinator creation and initialization."""
    
    def test_create_coordinator(self):
        """Test creating a coordinator."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        assert coordinator.node == node
        assert coordinator.heartbeat_interval == 30.0
        assert coordinator.current_state == CoordinationState.DISCONNECTED
        assert len(coordinator.sessions) == 0
        assert not coordinator.running
        
    def test_create_coordinator_with_custom_heartbeat(self):
        """Test creating coordinator with custom heartbeat interval."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node, heartbeat_interval=60.0)
        
        assert coordinator.heartbeat_interval == 60.0


class TestCoordinatorLifecycle:
    """Test coordinator lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_coordinator(self):
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
        
    @pytest.mark.asyncio
    async def test_start_already_running_coordinator(self):
        """Test starting an already running coordinator."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        await coordinator.start()
        first_task = coordinator.heartbeat_task
        
        # Start again - should not create new task
        await coordinator.start()
        assert coordinator.heartbeat_task == first_task
        
        await coordinator.stop()


class TestCoordinationSessions:
    """Test coordination session management."""
    
    @pytest.mark.asyncio
    async def test_initiate_coordination(self):
        """Test initiating coordination with children."""
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        
        parent.add_child(child1)
        parent.add_child(child2)
        
        coordinator = Coordinator(parent)
        
        session_id = await coordinator.initiate_coordination()
        
        assert session_id in coordinator.sessions
        session = coordinator.sessions[session_id]
        assert session.parent_id == "parent"
        assert session.child_ids == {"child1", "child2"}
        assert session.state == CoordinationState.CONNECTING
        assert coordinator.current_state == CoordinationState.CONNECTING
        
    @pytest.mark.asyncio
    async def test_initiate_coordination_with_specific_children(self):
        """Test initiating coordination with specific children."""
        parent = TreeNode(node_id="parent")
        child1 = TreeNode(node_id="child1")
        child2 = TreeNode(node_id="child2")
        child3 = TreeNode(node_id="child3")
        
        parent.add_child(child1)
        parent.add_child(child2)
        parent.add_child(child3)
        
        coordinator = Coordinator(parent)
        
        session_id = await coordinator.initiate_coordination(["child1", "child3"])
        
        session = coordinator.sessions[session_id]
        assert session.child_ids == {"child1", "child3"}
        
    @pytest.mark.asyncio
    async def test_execute_command_valid_session(self):
        """Test executing command in valid session."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        # Create a mock session in synchronized state
        session_id = await coordinator.initiate_coordination([])
        session = coordinator.sessions[session_id]
        session.state = CoordinationState.SYNCHRONIZED
        
        result = await coordinator.execute_command(session_id, "test_command", {"param": "value"})
        
        assert result is True
        assert coordinator.stats["commands_executed"] == 1
        
    @pytest.mark.asyncio
    async def test_execute_command_invalid_session(self):
        """Test executing command with invalid session."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        result = await coordinator.execute_command("invalid-session", "test_command", {})
        
        assert result is False
        assert coordinator.stats["commands_executed"] == 0


class TestCoordinatorStatistics:
    """Test coordinator statistics and monitoring."""
    
    def test_get_statistics(self):
        """Test getting coordinator statistics."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        stats = coordinator.get_statistics()
        
        required_keys = [
            "sessions_created", "sessions_completed", "sessions_failed",
            "commands_executed", "heartbeats_sent", "heartbeats_received",
            "active_sessions", "current_state", "heartbeat_interval"
        ]
        
        for key in required_keys:
            assert key in stats
            
    @pytest.mark.asyncio
    async def test_statistics_tracking(self):
        """Test that statistics are properly tracked."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        # Create session
        session_id = await coordinator.initiate_coordination([])
        
        stats = coordinator.get_statistics()
        assert stats["sessions_created"] == 1
        assert stats["active_sessions"] == 1


class TestCoordinatorStringRepresentation:
    """Test string representation methods."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        node = TreeNode(node_id="test-node")
        coordinator = Coordinator(node)
        
        str_repr = str(coordinator)
        assert "Coordinator" in str_repr
        assert "test-node" in str_repr
        assert "disconnected" in str_repr
        assert "sessions=0" in str_repr
