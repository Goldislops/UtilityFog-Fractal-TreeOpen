"""
Unit tests for DeliveryTracker class.

Tests cover delivery tracking, status management,
and statistics collection.
"""

import pytest
import asyncio
from unittest.mock import patch
from fractal_tree import Message, MessageType
from fractal_tree.messaging import DeliveryTracker, DeliveryStatus


class TestDeliveryTrackerCreation:
    """Test DeliveryTracker creation and initialization."""
    
    def test_create_delivery_tracker(self):
        """Test creating a delivery tracker."""
        tracker = DeliveryTracker()
        
        assert tracker.max_records == 10000
        assert len(tracker.records) == 0
        assert tracker.stats["total_deliveries"] == 0
        assert tracker.stats["successful_deliveries"] == 0
        assert tracker.stats["failed_deliveries"] == 0
        
    def test_create_delivery_tracker_with_limit(self):
        """Test creating tracker with custom record limit."""
        tracker = DeliveryTracker(max_records=5000)
        
        assert tracker.max_records == 5000


class TestDeliveryTracking:
    """Test delivery tracking functionality."""
    
    @pytest.fixture
    def tracker(self):
        """Create a delivery tracker for testing."""
        return DeliveryTracker()
        
    @pytest.fixture
    def test_message(self):
        """Create a test message."""
        return Message(
            message_type=MessageType.COMMAND,
            payload="test",
            sender_id="sender1",
            recipient_id="recipient1"
        )
        
    def test_start_delivery(self, tracker, test_message):
        """Test starting delivery tracking."""
        tracking_id = "test-tracking-123"
        
        tracker.start_delivery(tracking_id, test_message)
        
        assert tracking_id in tracker.records
        record = tracker.records[tracking_id]
        assert record.tracking_id == tracking_id
        assert record.message_id == test_message.message_id
        assert record.recipient_id == test_message.recipient_id
        assert record.status == DeliveryStatus.PENDING
        assert record.attempt_count == 0
        assert tracker.stats["total_deliveries"] == 1
        
    def test_mark_delivered(self, tracker, test_message):
        """Test marking delivery as successful."""
        tracking_id = "test-tracking-123"
        
        tracker.start_delivery(tracking_id, test_message)
        tracker.mark_delivered(tracking_id)
        
        record = tracker.records[tracking_id]
        assert record.status == DeliveryStatus.DELIVERED
        assert record.delivered_at is not None
        assert tracker.stats["successful_deliveries"] == 1
        
    def test_mark_failed(self, tracker, test_message):
        """Test marking delivery as failed."""
        tracking_id = "test-tracking-123"
        error_reason = "Network timeout"
        
        tracker.start_delivery(tracking_id, test_message)
        tracker.mark_failed(tracking_id, error_reason)
        
        record = tracker.records[tracking_id]
        assert record.status == DeliveryStatus.FAILED
        assert record.failed_at is not None
        assert record.failure_reason == error_reason
        assert tracker.stats["failed_deliveries"] == 1
        
    def test_mark_expired(self, tracker, test_message):
        """Test marking delivery as expired."""
        tracking_id = "test-tracking-123"
        
        tracker.start_delivery(tracking_id, test_message)
        tracker.mark_expired(tracking_id)
        
        record = tracker.records[tracking_id]
        assert record.status == DeliveryStatus.EXPIRED
        assert record.failed_at is not None
        assert record.failure_reason == "Delivery deadline expired"
        assert tracker.stats["expired_deliveries"] == 1
        
    def test_update_attempt(self, tracker, test_message):
        """Test updating attempt count."""
        tracking_id = "test-tracking-123"
        
        tracker.start_delivery(tracking_id, test_message)
        tracker.update_attempt(tracking_id)
        
        record = tracker.records[tracking_id]
        assert record.attempt_count == 1
        assert record.last_attempt is not None
        
        tracker.update_attempt(tracking_id)
        assert record.attempt_count == 2


class TestDeliveryQueries:
    """Test delivery query functionality."""
    
    @pytest.fixture
    def tracker_with_data(self):
        """Create tracker with test data."""
        tracker = DeliveryTracker()
        
        # Add some test records
        message1 = Message(MessageType.COMMAND, "test1", "sender1", "recipient1")
        message2 = Message(MessageType.QUERY, "test2", "sender2", "recipient2")
        message3 = Message(MessageType.EVENT, "test3", "sender3", "recipient3")
        
        tracker.start_delivery("pending-1", message1)
        tracker.start_delivery("delivered-1", message2)
        tracker.start_delivery("failed-1", message3)
        
        tracker.mark_delivered("delivered-1")
        tracker.mark_failed("failed-1", "Test failure")
        
        return tracker
        
    def test_get_status(self, tracker_with_data):
        """Test getting delivery status."""
        assert tracker_with_data.get_status("pending-1") == DeliveryStatus.PENDING
        assert tracker_with_data.get_status("delivered-1") == DeliveryStatus.DELIVERED
        assert tracker_with_data.get_status("failed-1") == DeliveryStatus.FAILED
        assert tracker_with_data.get_status("nonexistent") is None
        
    def test_get_record(self, tracker_with_data):
        """Test getting delivery record."""
        record = tracker_with_data.get_record("pending-1")
        assert record is not None
        assert record.tracking_id == "pending-1"
        assert record.status == DeliveryStatus.PENDING
        
        assert tracker_with_data.get_record("nonexistent") is None
        
    def test_get_pending_deliveries(self, tracker_with_data):
        """Test getting pending deliveries."""
        pending = tracker_with_data.get_pending_deliveries()
        
        assert len(pending) == 1
        assert pending[0].tracking_id == "pending-1"
        assert pending[0].status == DeliveryStatus.PENDING
        
    def test_get_failed_deliveries(self, tracker_with_data):
        """Test getting failed deliveries."""
        failed = tracker_with_data.get_failed_deliveries()
        
        assert len(failed) == 1
        assert failed[0].tracking_id == "failed-1"
        assert failed[0].status == DeliveryStatus.FAILED


class TestDeliveryCleanup:
    """Test delivery record cleanup functionality."""
    
    @pytest.fixture
    def tracker(self):
        """Create a delivery tracker for testing."""
        return DeliveryTracker(max_records=5)
        
    def test_cleanup_expired_deliveries(self, tracker):
        """Test cleaning up expired delivery records."""
        # Create some old records with mocked time
        with patch('asyncio.get_event_loop') as mock_loop:
            # Set initial time for record creation
            mock_loop.return_value.time.return_value = 1000.0
            
            messages = []
            for i in range(3):
                message = Message(MessageType.COMMAND, f"test{i}", f"sender{i}")
                messages.append(message)
                tracker.start_delivery(f"old-{i}", message)
                
            # Mark them as delivered/failed
            tracker.mark_delivered("old-0")
            tracker.mark_failed("old-1", "test error")
            # Leave old-2 as pending
            
            # Move time forward to make records old
            mock_loop.return_value.time.return_value = 5000.0  # 4000 seconds later
            
            # Clean up records older than 1 hour (3600 seconds)
            cleaned = tracker.cleanup_expired_deliveries(max_age=3600.0)
            
        # Should clean up delivered and failed, but not pending
        assert cleaned == 2
        assert len(tracker.records) == 1
        assert "old-2" in tracker.records
        
    def test_record_limit_enforcement(self, tracker):
        """Test automatic cleanup when record limit is exceeded."""
        # Add more records than the limit
        for i in range(10):
            message = Message(MessageType.COMMAND, f"test{i}", f"sender{i}")
            tracker.start_delivery(f"record-{i}", message)
            
        # Should automatically clean up old records
        assert len(tracker.records) <= tracker.max_records


class TestDeliveryStatistics:
    """Test delivery statistics functionality."""
    
    def test_get_statistics(self):
        """Test getting delivery statistics."""
        tracker = DeliveryTracker()
        
        # Add some test data
        messages = []
        for i in range(5):
            message = Message(MessageType.COMMAND, f"test{i}", f"sender{i}")
            messages.append(message)
            tracker.start_delivery(f"msg-{i}", message)
            
        # Mark some as delivered/failed
        tracker.mark_delivered("msg-0")
        tracker.mark_delivered("msg-1")
        tracker.mark_failed("msg-2", "error")
        # Leave msg-3 and msg-4 as pending
        
        stats = tracker.get_statistics()
        
        assert stats["total_deliveries"] == 5
        assert stats["successful_deliveries"] == 2
        assert stats["failed_deliveries"] == 1
        assert stats["active_records"] == 5
        assert stats["pending_deliveries"] == 2
        assert stats["success_rate"] == 40.0  # 2/5 * 100
        
    def test_average_delivery_time_calculation(self):
        """Test average delivery time calculation."""
        tracker = DeliveryTracker()
        
        message = Message(MessageType.COMMAND, "test", "sender")
        
        # Mock time progression
        with patch('asyncio.get_event_loop') as mock_loop:
            # Start delivery at time 0
            mock_loop.return_value.time.return_value = 0.0
            tracker.start_delivery("test-1", message)
            
            # Mark delivered at time 5
            mock_loop.return_value.time.return_value = 5.0
            tracker.mark_delivered("test-1")
            
            # Start another delivery at time 10
            mock_loop.return_value.time.return_value = 10.0
            tracker.start_delivery("test-2", message)
            
            # Mark delivered at time 13
            mock_loop.return_value.time.return_value = 13.0
            tracker.mark_delivered("test-2")
            
        stats = tracker.get_statistics()
        # Average should be (5 + 3) / 2 = 4.0
        assert stats["average_delivery_time"] == 4.0


class TestDeliveryTrackerStringRepresentation:
    """Test string representation of delivery tracker."""
    
    def test_str_representation(self):
        """Test __str__ method."""
        tracker = DeliveryTracker()
        
        # Add some test data
        message = Message(MessageType.COMMAND, "test", "sender")
        tracker.start_delivery("test-1", message)
        tracker.mark_delivered("test-1")
        
        str_repr = str(tracker)
        
        assert "DeliveryTracker" in str_repr
        assert "records=1" in str_repr
        assert "success_rate=" in str_repr
