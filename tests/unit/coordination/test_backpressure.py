
"""
Unit tests for BackpressureManager class.

Tests cover queue watermark monitoring, PAUSE/RESUME signals,
and flow control functionality.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fractal_tree.coordination import BackpressureManager, BackpressureState, BackpressureConfig
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


class TestBackpressureManagerCreation:
    """Test BackpressureManager creation and initialization."""
    
    def test_create_backpressure_manager(self):
        """Test creating a backpressure manager."""
        manager = BackpressureManager("test-session")
        
        assert manager.session_id == "test-session"
        assert manager.current_state == BackpressureState.NORMAL
        assert not manager.is_paused
        assert not manager.running
    
    def test_create_with_custom_config(self):
        """Test creating manager with custom configuration."""
        config = BackpressureConfig(
            warning_threshold=0.8,
            pause_threshold=0.95,
            max_enqueue_rate=500.0
        )
        
        manager = BackpressureManager("test-session", config)
        
        assert manager.config.warning_threshold == 0.8
        assert manager.config.pause_threshold == 0.95
        assert manager.config.max_enqueue_rate == 500.0


class TestBackpressureLifecycle:
    """Test backpressure manager lifecycle."""
    
    @pytest.mark.asyncio
    async def test_start_and_stop_manager(self, mock_event_loop):
        """Test starting and stopping the backpressure manager."""
        manager = BackpressureManager("test-session")
        
        # Start manager
        await manager.start()
        assert manager.running
        assert manager.monitor_task is not None
        
        # Stop manager
        await manager.stop()
        assert not manager.running


class TestQueueMonitoring:
    """Test queue monitoring functionality."""
    
    @pytest.mark.asyncio
    async def test_register_queue(self, mock_event_loop):
        """Test registering a queue for monitoring."""
        manager = BackpressureManager("test-session")
        queue = asyncio.Queue(maxsize=100)
        
        manager.register_queue("test-queue", queue, 100)
        
        assert "test-queue" in manager.monitored_queues
        assert "test-queue" in manager.queue_metrics
        
        metrics = manager.queue_metrics["test-queue"]
        assert metrics.max_size == 100
        assert metrics.utilization == 0.0
    
    @pytest.mark.asyncio
    async def test_unregister_queue(self, mock_event_loop):
        """Test unregistering a queue."""
        manager = BackpressureManager("test-session")
        queue = asyncio.Queue(maxsize=100)
        
        manager.register_queue("test-queue", queue, 100)
        manager.unregister_queue("test-queue")
        
        assert "test-queue" not in manager.monitored_queues
        assert "test-queue" not in manager.queue_metrics
    
    @pytest.mark.asyncio
    async def test_check_enqueue_allowed_normal(self, mock_event_loop):
        """Test enqueue allowed in normal state."""
        manager = BackpressureManager("test-session")
        queue = asyncio.Queue(maxsize=100)
        
        manager.register_queue("test-queue", queue, 100)
        
        allowed = await manager.check_enqueue_allowed("test-queue")
        assert allowed is True
    
    @pytest.mark.asyncio
    async def test_check_enqueue_blocked_when_paused(self, mock_event_loop):
        """Test enqueue blocked when paused."""
        manager = BackpressureManager("test-session")
        manager.is_paused = True
        
        allowed = await manager.check_enqueue_allowed("test-queue")
        assert allowed is False
    
    @pytest.mark.asyncio
    async def test_check_enqueue_blocked_at_critical_threshold(self, mock_event_loop):
        """Test enqueue blocked at critical threshold."""
        config = BackpressureConfig(critical_threshold=0.9)
        manager = BackpressureManager("test-session", config)
        
        queue = asyncio.Queue(maxsize=100)
        manager.register_queue("test-queue", queue, 100)
        
        # Simulate high utilization
        metrics = manager.queue_metrics["test-queue"]
        metrics.utilization = 0.95  # Above critical threshold
        
        allowed = await manager.check_enqueue_allowed("test-queue")
        assert allowed is False


class TestRateLimiting:
    """Test rate limiting functionality."""
    
    @pytest.mark.asyncio
    async def test_record_enqueue_dequeue(self, mock_event_loop, fake_clock):
        """Test recording enqueue and dequeue operations."""
        manager = BackpressureManager("test-session")
        
        # Record some operations
        await manager.record_enqueue("test-queue")
        fake_clock.advance(0.5)
        await manager.record_dequeue("test-queue")
        
        assert len(manager.enqueue_times) == 1
        assert len(manager.dequeue_times) == 1
    
    @pytest.mark.asyncio
    async def test_rate_limit_enforcement(self, mock_event_loop, fake_clock):
        """Test rate limit enforcement."""
        config = BackpressureConfig(max_enqueue_rate=2.0, rate_window=1.0)
        manager = BackpressureManager("test-session", config)
        
        # Record operations at high rate
        for _ in range(5):
            await manager.record_enqueue("test-queue")
            fake_clock.advance(0.1)
        
        # Should hit rate limit
        allowed = await manager.check_enqueue_allowed("test-queue")
        assert allowed is False
        assert manager.stats["rate_limit_hits"] == 1


class TestBackpressureStates:
    """Test backpressure state transitions."""
    
    @pytest.mark.asyncio
    async def test_state_transition_warning(self, mock_event_loop):
        """Test transition to warning state."""
        config = BackpressureConfig(warning_threshold=0.7)
        manager = BackpressureManager("test-session", config)
        
        # Register state callback
        callback_called = False
        old_state = None
        new_state = None
        
        def state_callback(old, new):
            nonlocal callback_called, old_state, new_state
            callback_called = True
            old_state = old
            new_state = new
        
        manager.register_state_callback(BackpressureState.WARNING, state_callback)
        
        await manager.start()
        
        # Simulate high utilization
        queue = asyncio.Queue(maxsize=100)
        manager.register_queue("test-queue", queue, 100)
        manager.queue_metrics["test-queue"].utilization = 0.8
        
        # Trigger state check
        await manager._check_backpressure()
        
        assert manager.current_state == BackpressureState.WARNING
        assert callback_called
        assert old_state == BackpressureState.NORMAL
        assert new_state == BackpressureState.WARNING
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_state_transition_paused(self, mock_event_loop):
        """Test transition to paused state."""
        config = BackpressureConfig(pause_threshold=0.9)
        manager = BackpressureManager("test-session", config)
        
        await manager.start()
        
        # Simulate very high utilization
        queue = asyncio.Queue(maxsize=100)
        manager.register_queue("test-queue", queue, 100)
        manager.queue_metrics["test-queue"].utilization = 0.95
        
        # Trigger state check
        await manager._check_backpressure()
        
        assert manager.current_state == BackpressureState.PAUSED
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_state_transition_critical(self, mock_event_loop):
        """Test transition to critical state."""
        config = BackpressureConfig(critical_threshold=0.95)
        manager = BackpressureManager("test-session", config)
        
        await manager.start()
        
        # Simulate critical utilization
        queue = asyncio.Queue(maxsize=100)
        manager.register_queue("test-queue", queue, 100)
        manager.queue_metrics["test-queue"].utilization = 0.98
        
        # Trigger state check
        await manager._check_backpressure()
        
        assert manager.current_state == BackpressureState.CRITICAL
        
        await manager.stop()


class TestBackpressureMessages:
    """Test backpressure message handling."""
    
    def test_create_pause_message(self):
        """Test creating PAUSE signal message."""
        manager = BackpressureManager("test-session")
        
        message = manager.create_pause_message("sender", "recipient")
        
        assert message.message_type == MessageType.COMMAND
        assert message.payload["action"] == "PAUSE"
        assert message.payload["reason"] == "backpressure"
        assert message.priority == MessagePriority.HIGH
        assert message.metadata["backpressure_signal"] is True
        assert message.metadata["session_id"] == "test-session"
    
    def test_create_resume_message(self):
        """Test creating RESUME signal message."""
        manager = BackpressureManager("test-session")
        
        message = manager.create_resume_message("sender", "recipient")
        
        assert message.message_type == MessageType.COMMAND
        assert message.payload["action"] == "RESUME"
        assert message.payload["reason"] == "backpressure_relieved"
        assert message.priority == MessagePriority.HIGH
        assert message.metadata["backpressure_signal"] is True
    
    @pytest.mark.asyncio
    async def test_handle_pause_signal(self, mock_event_loop):
        """Test handling PAUSE signal."""
        manager = BackpressureManager("test-session")
        
        # Register pause callback
        callback_called = False
        
        def pause_callback(message):
            nonlocal callback_called
            callback_called = True
        
        manager.register_pause_callback(pause_callback)
        
        # Create pause message
        message = Message(
            message_type=MessageType.COMMAND,
            payload={"action": "PAUSE", "reason": "backpressure"},
            sender_id="sender",
            metadata={"backpressure_signal": True}
        )
        
        # Handle message
        await manager.handle_backpressure_message(message)
        
        assert manager.is_paused is True
        assert manager.stats["pause_events"] == 1
        assert callback_called
    
    @pytest.mark.asyncio
    async def test_handle_resume_signal(self, mock_event_loop):
        """Test handling RESUME signal."""
        manager = BackpressureManager("test-session")
        manager.is_paused = True  # Start paused
        
        # Register resume callback
        callback_called = False
        
        def resume_callback(message):
            nonlocal callback_called
            callback_called = True
        
        manager.register_resume_callback(resume_callback)
        
        # Create resume message
        message = Message(
            message_type=MessageType.COMMAND,
            payload={"action": "RESUME", "reason": "backpressure_relieved"},
            sender_id="sender",
            metadata={"backpressure_signal": True}
        )
        
        # Handle message
        await manager.handle_backpressure_message(message)
        
        assert manager.is_paused is False
        assert manager.stats["resume_events"] == 1
        assert callback_called
    
    @pytest.mark.asyncio
    async def test_handle_non_backpressure_message(self, mock_event_loop):
        """Test handling non-backpressure message."""
        manager = BackpressureManager("test-session")
        
        # Create regular message
        message = Message(
            message_type=MessageType.COMMAND,
            payload={"action": "PAUSE"},
            sender_id="sender"
        )
        
        # Handle message (should be ignored)
        await manager.handle_backpressure_message(message)
        
        assert manager.is_paused is False
        assert manager.stats["pause_events"] == 0


class TestBackpressureMetrics:
    """Test backpressure metrics and monitoring."""
    
    @pytest.mark.asyncio
    async def test_get_metrics(self, mock_event_loop):
        """Test getting backpressure metrics."""
        manager = BackpressureManager("test-session")
        
        # Register a queue
        queue = asyncio.Queue(maxsize=100)
        manager.register_queue("test-queue", queue, 100)
        
        metrics = manager.get_metrics()
        
        assert metrics["state"] == BackpressureState.NORMAL.value
        assert metrics["is_paused"] is False
        assert "test-queue" in metrics["queue_metrics"]
        assert "statistics" in metrics
        
        queue_metrics = metrics["queue_metrics"]["test-queue"]
        assert queue_metrics["max_size"] == 100
        assert queue_metrics["utilization"] == 0.0
    
    @pytest.mark.asyncio
    async def test_monitor_loop_updates_metrics(self, mock_event_loop, fake_clock):
        """Test that monitor loop updates metrics."""
        config = BackpressureConfig(check_interval=0.1)
        manager = BackpressureManager("test-session", config)
        
        # Register queue and add some items
        queue = asyncio.Queue(maxsize=100)
        for _ in range(50):  # Fill queue to 50%
            await queue.put("item")
        
        manager.register_queue("test-queue", queue, 100)
        
        await manager.start()
        
        # Let monitor loop run
        fake_clock.advance(0.2)
        await asyncio.sleep(0.1)
        
        # Check metrics were updated
        metrics = manager.queue_metrics["test-queue"]
        assert metrics.queue_size == 50
        assert metrics.utilization == 0.5
        
        await manager.stop()


class TestBackpressureScenarios:
    """Test complex backpressure scenarios."""
    
    @pytest.mark.asyncio
    async def test_backpressure_recovery_scenario(self, mock_event_loop, fake_clock):
        """Test backpressure recovery scenario."""
        config = BackpressureConfig(
            warning_threshold=0.7,
            pause_threshold=0.9,
            resume_threshold=0.5,
            check_interval=0.1
        )
        manager = BackpressureManager("test-session", config)
        
        # Track state changes
        state_changes = []
        
        def track_state_change(old, new):
            state_changes.append((old, new))
        
        manager.register_state_callback(BackpressureState.WARNING, track_state_change)
        manager.register_state_callback(BackpressureState.PAUSED, track_state_change)
        manager.register_state_callback(BackpressureState.NORMAL, track_state_change)
        
        await manager.start()
        
        # Register queue
        queue = asyncio.Queue(maxsize=100)
        manager.register_queue("test-queue", queue, 100)
        
        # 1. Fill queue to warning level
        manager.queue_metrics["test-queue"].utilization = 0.8
        await manager._check_backpressure()
        assert manager.current_state == BackpressureState.WARNING
        
        # 2. Fill queue to pause level
        manager.queue_metrics["test-queue"].utilization = 0.95
        await manager._check_backpressure()
        assert manager.current_state == BackpressureState.PAUSED
        
        # 3. Drain queue to resume level
        manager.queue_metrics["test-queue"].utilization = 0.4
        await manager._check_backpressure()
        assert manager.current_state == BackpressureState.NORMAL
        
        # Check state transitions
        assert len(state_changes) == 3
        assert state_changes[0] == (BackpressureState.NORMAL, BackpressureState.WARNING)
        assert state_changes[1] == (BackpressureState.WARNING, BackpressureState.PAUSED)
        assert state_changes[2] == (BackpressureState.PAUSED, BackpressureState.NORMAL)
        
        await manager.stop()
    
    @pytest.mark.asyncio
    async def test_multiple_queue_monitoring(self, mock_event_loop):
        """Test monitoring multiple queues."""
        manager = BackpressureManager("test-session")
        
        await manager.start()
        
        # Register multiple queues
        queue1 = asyncio.Queue(maxsize=100)
        queue2 = asyncio.Queue(maxsize=200)
        queue3 = asyncio.Queue(maxsize=50)
        
        manager.register_queue("queue1", queue1, 100)
        manager.register_queue("queue2", queue2, 200)
        manager.register_queue("queue3", queue3, 50)
        
        # Set different utilization levels
        manager.queue_metrics["queue1"].utilization = 0.5  # Normal
        manager.queue_metrics["queue2"].utilization = 0.8  # Warning
        manager.queue_metrics["queue3"].utilization = 0.95  # Critical
        
        # Check backpressure (should use highest utilization)
        await manager._check_backpressure()
        
        assert manager.current_state == BackpressureState.CRITICAL
        
        await manager.stop()
