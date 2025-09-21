
"""
Unit tests for SessionManager class.

Tests cover session lifecycle, rejoin with backoff, heartbeat
monitoring, and per-session metrics tracking.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fractal_tree.coordination import SessionManager, SessionEvent, SessionConfig, SessionMetrics
from fractal_tree.coordination import CoordinationState, CoordinationSession
from fractal_tree.message import Message, MessageType


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


class TestSessionManagerCreation:
    """Test SessionManager creation and initialization."""
    
    def test_create_session_manager(self):
        """Test creating a session manager."""
        manager = SessionManager("test-node")
        
        assert manager.node_id == "test-node"
        assert len(manager.sessions) == 0
        assert not manager.running
    
    def test_create_with_custom_config(self):
        """Test creating manager with custom configuration."""
        config = SessionConfig(
            join_timeout=60.0,
            heartbeat_interval=15.0,
            max_concurrent_sessions=50
        )
        
        manager = SessionManager("test-node", config)
        
        assert manager.config.join_timeout == 60.0
        assert manager.config.heartbeat_interval == 15.0
        assert manager.config.max_concurrent_sessions == 50


class TestSessionManagerLifecycle:
    """Test session manager lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_manager(self, mock_event_loop):
        """Test starting and stopping the session manager."""
        manager = SessionManager("test-node")
        
        # Start manager
        await manager.start()
        assert manager.running
        assert manager.heartbeat_task is not None
        assert manager.cleanup_task is not None
        
        # Stop manager
        await manager.stop()
        assert not manager.running


class TestSessionJoinLeave:
    """Test session join and leave functionality."""
    
    @pytest.mark.asyncio
    async def test_request_join(self, mock_event_loop, fake_clock):
        """Test requesting to join a session."""
        manager = SessionManager("test-node")
        await manager.start()
        
        # Request join
        session_id = await manager.request_join("parent-node")
        
        assert session_id is not None
        assert session_id in manager.sessions
        assert session_id in manager.session_metrics
        assert session_id in manager.backpressure_managers
        
        session = manager.sessions[session_id]
        assert session.parent_id == "parent-node"
        assert session.state == CoordinationState.CONNECTING
        
        metrics = manager.session_metrics[session_id]
        assert metrics.session_id == session_id
        assert metrics.join_time == fake_clock.time()
        
        assert manager.stats["sessions_created"] == 1
        assert manager.stats["sessions_joined"] == 1
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_request_join_with_config(self, mock_event_loop):
        """Test requesting to join with session config."""
        manager = SessionManager("test-node")
        await manager.start()
        
        session_config = {"priority": "high", "timeout": 60}
        session_id = await manager.request_join("parent-node", session_config)
        
        session = manager.sessions[session_id]
        assert session.metadata == session_config
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_request_join_session_limit(self, mock_event_loop):
        """Test join request with session limit reached."""
        config = SessionConfig(max_concurrent_sessions=2)
        manager = SessionManager("test-node", config)
        await manager.start()
        
        # Create maximum sessions
        session1 = await manager.request_join("parent1")
        session2 = await manager.request_join("parent2")
        
        assert session1 is not None
        assert session2 is not None
        
        # Try to create one more (should fail)
        session3 = await manager.request_join("parent3")
        assert session3 is None
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_leave_session(self, mock_event_loop):
        """Test leaving a session."""
        manager = SessionManager("test-node")
        await manager.start()
        
        # Join session
        session_id = await manager.request_join("parent-node")
        
        # Leave session
        result = await manager.leave_session(session_id, "test_reason")
        
        assert result is True
        assert session_id not in manager.sessions
        assert session_id not in manager.session_metrics
        assert session_id not in manager.backpressure_managers
        assert manager.stats["sessions_left"] == 1
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_leave_nonexistent_session(self, mock_event_loop):
        """Test leaving a non-existent session."""
        manager = SessionManager("test-node")
        await manager.start()
        
        result = await manager.leave_session("nonexistent", "test_reason")
        assert result is False
        
        await manager.stop()


class TestSessionRejoin:
    """Test session rejoin functionality."""
    
    @pytest.mark.asyncio
    async def test_request_rejoin(self, mock_event_loop, fake_clock):
        """Test requesting to rejoin a session."""
        config = SessionConfig(initial_backoff=1.0, backoff_multiplier=2.0)
        manager = SessionManager("test-node", config)
        await manager.start()
        
        session_id = "test-session"
        
        # First rejoin attempt
        result = await manager.request_rejoin(session_id)
        
        assert result is True
        assert manager.rejoin_attempts[session_id] == 1
        assert manager.stats["rejoin_attempts"] == 1
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_rejoin_with_backoff(self, mock_event_loop, fake_clock):
        """Test rejoin with exponential backoff."""
        config = SessionConfig(
            initial_backoff=1.0,
            backoff_multiplier=2.0,
            backoff_jitter=0.0  # No jitter for predictable testing
        )
        manager = SessionManager("test-node", config)
        await manager.start()
        
        session_id = "test-session"
        
        # First attempt (no backoff)
        start_time = fake_clock.time()
        await manager.request_rejoin(session_id)
        assert fake_clock.time() == start_time  # No delay
        
        # Second attempt (1s backoff)
        start_time = fake_clock.time()
        with patch('asyncio.sleep') as mock_sleep:
            await manager.request_rejoin(session_id)
            mock_sleep.assert_called_once()
            # Check backoff delay was calculated
            assert manager.backoff_delays[session_id] > 0
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_rejoin_max_attempts(self, mock_event_loop):
        """Test rejoin maximum attempts limit."""
        config = SessionConfig(max_rejoin_attempts=3)
        manager = SessionManager("test-node", config)
        await manager.start()
        
        session_id = "test-session"
        
        # Make maximum attempts
        for i in range(3):
            result = await manager.request_rejoin(session_id)
            assert result is True
        
        # One more attempt should fail
        result = await manager.request_rejoin(session_id)
        assert result is False
        
        await manager.stop()


class TestHeartbeatHandling:
    """Test heartbeat handling functionality."""
    
    @pytest.mark.asyncio
    async def test_handle_heartbeat(self, mock_event_loop, fake_clock):
        """Test handling heartbeat messages."""
        manager = SessionManager("test-node")
        await manager.start()
        
        # Create session
        session_id = await manager.request_join("parent-node")
        
        initial_time = fake_clock.time()
        fake_clock.advance(10.0)
        
        # Handle heartbeat
        await manager.handle_heartbeat(session_id, "parent-node")
        
        session = manager.sessions[session_id]
        metrics = manager.session_metrics[session_id]
        
        assert session.last_heartbeat == fake_clock.time()
        assert metrics.last_heartbeat == fake_clock.time()
        assert metrics.heartbeat_count == 1
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_handle_heartbeat_with_lag_calculation(self, mock_event_loop, fake_clock):
        """Test heartbeat handling with lag calculation."""
        manager = SessionManager("test-node")
        await manager.start()
        
        session_id = await manager.request_join("parent-node")
        session = manager.sessions[session_id]
        
        # Set last sent heartbeat time
        sent_time = fake_clock.time()
        session.metadata["last_sent_heartbeat"] = sent_time
        
        # Advance time and handle heartbeat
        fake_clock.advance(5.0)
        await manager.handle_heartbeat(session_id, "parent-node")
        
        metrics = manager.session_metrics[session_id]
        assert metrics.lag_ms == 5000.0  # 5 seconds in milliseconds
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_heartbeat_timeout_detection(self, mock_event_loop, fake_clock):
        """Test heartbeat timeout detection."""
        config = SessionConfig(heartbeat_timeout=30.0, heartbeat_interval=1.0)
        manager = SessionManager("test-node", config)
        
        # Track timeout events
        timeout_events = []
        
        def track_timeout(event, session_id, data):
            if event == SessionEvent.HEARTBEAT_TIMEOUT:
                timeout_events.append(session_id)
        
        manager.register_event_callback(SessionEvent.HEARTBEAT_TIMEOUT, track_timeout)
        
        await manager.start()
        
        # Create session
        session_id = await manager.request_join("parent-node")
        
        # Advance time past timeout threshold
        fake_clock.advance(35.0)
        
        # Trigger timeout check
        await manager._check_heartbeat_timeouts()
        
        assert len(timeout_events) == 1
        assert timeout_events[0] == session_id
        assert manager.stats["heartbeat_timeouts"] == 1
        
        # Session should be marked as failed
        session = manager.sessions[session_id]
        assert session.state == CoordinationState.FAILED
        
        await manager.stop()


class TestSessionMetrics:
    """Test session metrics tracking."""
    
    @pytest.mark.asyncio
    async def test_record_message(self, mock_event_loop):
        """Test recording messages for metrics."""
        manager = SessionManager("test-node")
        await manager.start()
        
        session_id = await manager.request_join("parent-node")
        
        # Record some messages
        message = Message(MessageType.COMMAND, {"test": "data"}, "sender")
        await manager.record_message(session_id, message)
        await manager.record_message(session_id, message)
        
        metrics = manager.session_metrics[session_id]
        assert metrics.message_count == 2
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_record_error(self, mock_event_loop):
        """Test recording errors for metrics."""
        manager = SessionManager("test-node")
        await manager.start()
        
        session_id = await manager.request_join("parent-node")
        
        # Record some errors
        await manager.record_error(session_id, "Test error 1")
        await manager.record_error(session_id, "Test error 2")
        
        metrics = manager.session_metrics[session_id]
        assert metrics.error_count == 2
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_record_drops_and_requeues(self, mock_event_loop):
        """Test recording drops and requeues."""
        manager = SessionManager("test-node")
        await manager.start()
        
        session_id = await manager.request_join("parent-node")
        
        # Record drops and requeues
        await manager.record_drop(session_id)
        await manager.record_drop(session_id)
        await manager.record_requeue(session_id)
        
        metrics = manager.session_metrics[session_id]
        assert metrics.drops == 2
        assert metrics.requeues == 1
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_get_session_metrics(self, mock_event_loop, fake_clock):
        """Test getting session metrics."""
        manager = SessionManager("test-node")
        await manager.start()
        
        session_id = await manager.request_join("parent-node")
        
        # Add some activity
        message = Message(MessageType.COMMAND, {"test": "data"}, "sender")
        await manager.record_message(session_id, message)
        await manager.record_error(session_id, "Test error")
        await manager.record_drop(session_id)
        
        fake_clock.advance(60.0)  # 1 minute uptime
        
        metrics_dict = manager.get_session_metrics(session_id)
        
        assert metrics_dict is not None
        assert metrics_dict["session_id"] == session_id
        assert metrics_dict["state"] == CoordinationState.CONNECTING.value
        assert metrics_dict["message_count"] == 1
        assert metrics_dict["error_count"] == 1
        assert metrics_dict["drops"] == 1
        assert metrics_dict["uptime"] == 60.0
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_get_all_session_metrics(self, mock_event_loop):
        """Test getting all session metrics."""
        manager = SessionManager("test-node")
        await manager.start()
        
        # Create multiple sessions
        session1 = await manager.request_join("parent1")
        session2 = await manager.request_join("parent2")
        
        all_metrics = manager.get_all_session_metrics()
        
        assert len(all_metrics) == 2
        assert session1 in all_metrics
        assert session2 in all_metrics
        
        await manager.stop()


class TestEventCallbacks:
    """Test session event callbacks."""
    
    @pytest.mark.asyncio
    async def test_join_event_callback(self, mock_event_loop):
        """Test join event callback."""
        manager = SessionManager("test-node")
        
        # Register callback
        events = []
        
        def track_event(event, session_id, data):
            events.append((event, session_id, data))
        
        manager.register_event_callback(SessionEvent.JOIN_REQUEST, track_event)
        
        await manager.start()
        
        # Request join
        session_id = await manager.request_join("parent-node")
        
        assert len(events) == 1
        assert events[0][0] == SessionEvent.JOIN_REQUEST
        assert events[0][1] == session_id
        assert events[0][2]["parent_id"] == "parent-node"
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_leave_event_callback(self, mock_event_loop):
        """Test leave event callback."""
        manager = SessionManager("test-node")
        
        # Register callback
        events = []
        
        def track_event(event, session_id, data):
            events.append((event, session_id, data))
        
        manager.register_event_callback(SessionEvent.LEAVE_REQUEST, track_event)
        
        await manager.start()
        
        # Join and leave session
        session_id = await manager.request_join("parent-node")
        await manager.leave_session(session_id, "test_reason")
        
        assert len(events) == 1
        assert events[0][0] == SessionEvent.LEAVE_REQUEST
        assert events[0][1] == session_id
        assert events[0][2]["reason"] == "test_reason"
        
        await manager.stop()


class TestSessionCleanup:
    """Test session cleanup functionality."""
    
    @pytest.mark.asyncio
    async def test_session_expiration(self, mock_event_loop, fake_clock):
        """Test session expiration cleanup."""
        config = SessionConfig(session_ttl=3600.0)  # 1 hour TTL
        manager = SessionManager("test-node", config)
        
        # Track expiration events
        expired_sessions = []
        
        def track_expiration(event, session_id, data):
            if event == SessionEvent.SESSION_EXPIRED:
                expired_sessions.append(session_id)
        
        manager.register_event_callback(SessionEvent.SESSION_EXPIRED, track_expiration)
        
        await manager.start()
        
        # Create session
        session_id = await manager.request_join("parent-node")
        
        # Advance time past TTL
        fake_clock.advance(3700.0)  # 1 hour + 100 seconds
        
        # Trigger cleanup
        await manager._cleanup_expired_sessions()
        
        assert len(expired_sessions) == 1
        assert expired_sessions[0] == session_id
        assert session_id not in manager.sessions
        assert manager.stats["sessions_expired"] == 1
        
        await manager.stop()


class TestSessionManagerStatistics:
    """Test session manager statistics."""
    
    @pytest.mark.asyncio
    async def test_get_statistics(self, mock_event_loop, fake_clock):
        """Test getting session manager statistics."""
        manager = SessionManager("test-node")
        await manager.start()
        
        # Create some sessions with different states
        session1 = await manager.request_join("parent1")
        session2 = await manager.request_join("parent2")
        
        # Make some rejoin attempts
        await manager.request_rejoin("old-session")
        await manager.request_rejoin("old-session")
        
        fake_clock.advance(30.0)  # Age sessions
        
        stats = manager.get_statistics()
        
        assert stats["active_sessions"] == 2
        assert stats["sessions_created"] == 2
        assert stats["sessions_joined"] == 2
        assert stats["rejoin_attempts"] == 2
        assert stats["total_rejoin_attempts"] == 2
        assert stats["average_session_age"] == 30.0
        
        # Check session state counts
        state_counts = stats["session_states"]
        assert state_counts[CoordinationState.CONNECTING.value] == 2
        
        await manager.stop()


class TestSessionManagerIntegration:
    """Integration tests for session manager."""
    
    @pytest.mark.asyncio
    async def test_full_session_lifecycle(self, mock_event_loop, fake_clock):
        """Test complete session lifecycle."""
        config = SessionConfig(
            heartbeat_interval=10.0,
            heartbeat_timeout=30.0,
            initial_backoff=1.0
        )
        manager = SessionManager("test-node", config)
        
        # Track all events
        events = []
        
        def track_all_events(event, session_id, data):
            events.append((event, session_id, data))
        
        for event_type in SessionEvent:
            manager.register_event_callback(event_type, track_all_events)
        
        await manager.start()
        
        # 1. Join session
        session_id = await manager.request_join("parent-node", {"priority": "high"})
        assert session_id is not None
        
        # 2. Handle heartbeats
        fake_clock.advance(5.0)
        await manager.handle_heartbeat(session_id, "parent-node")
        
        # 3. Record some activity
        message = Message(MessageType.COMMAND, {"cmd": "test"}, "parent-node")
        await manager.record_message(session_id, message)
        await manager.record_error(session_id, "Minor error")
        
        # 4. Check metrics
        metrics = manager.get_session_metrics(session_id)
        assert metrics["message_count"] == 1
        assert metrics["error_count"] == 1
        assert metrics["heartbeat_count"] == 1
        
        # 5. Leave session
        await manager.leave_session(session_id, "completed")
        
        # Check events were fired
        join_events = [e for e in events if e[0] == SessionEvent.JOIN_REQUEST]
        leave_events = [e for e in events if e[0] == SessionEvent.LEAVE_REQUEST]
        
        assert len(join_events) == 1
        assert len(leave_events) == 1
        assert join_events[0][1] == session_id
        assert leave_events[0][1] == session_id
        
        await manager.stop()
