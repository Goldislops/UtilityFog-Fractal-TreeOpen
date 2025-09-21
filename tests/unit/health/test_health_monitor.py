
"""
Unit tests for HealthMonitor class.

Tests cover health monitoring, heartbeat tracking,
and status management functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fractal_tree import TreeNode
from fractal_tree.health import HealthMonitor, HealthStatus


class TestHealthMonitorCreation:
    """Test HealthMonitor creation and initialization."""
    
    def test_create_health_monitor(self):
        """Test creating a health monitor."""
        node = TreeNode(node_id="test-node")
        monitor = HealthMonitor(node)
        
        assert monitor.node == node
        assert monitor.heartbeat_interval == 30.0
        assert monitor.timeout_threshold == 90.0
        assert monitor.current_status == HealthStatus.UNKNOWN
        assert not monitor.running


class TestHealthMonitorLifecycle:
    """Test health monitor lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_monitor(self):
        """Test starting and stopping the health monitor."""
        node = TreeNode(node_id="test-node")
        monitor = HealthMonitor(node)
        
        # Start monitor
        await monitor.start()
        assert monitor.running
        assert monitor.current_status == HealthStatus.HEALTHY
        
        # Stop monitor
        await monitor.stop()
        assert not monitor.running


class TestHeartbeatTracking:
    """Test heartbeat tracking functionality."""
    
    @pytest.mark.asyncio
    async def test_record_heartbeat(self):
        """Test recording heartbeat from another node."""
        node = TreeNode(node_id="test-node")
        monitor = HealthMonitor(node)
        
        await monitor.record_heartbeat("other-node")
        
        assert monitor.last_heartbeat > 0
        assert monitor.stats["heartbeats_received"] == 1
        assert monitor.error_count == 0


class TestHealthSnapshots:
    """Test health snapshot functionality."""
    
    def test_get_health_snapshot(self):
        """Test getting current health snapshot."""
        node = TreeNode(node_id="test-node")
        monitor = HealthMonitor(node)
        
        snapshot = monitor.get_health_snapshot()
        
        assert snapshot.node_id == "test-node"
        assert snapshot.status == HealthStatus.UNKNOWN
        assert snapshot.timestamp > 0
        assert snapshot.error_count == 0
