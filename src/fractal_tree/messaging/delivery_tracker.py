
"""
Delivery tracking for reliable messaging.

This module provides delivery status tracking and monitoring
for reliable message delivery.
"""

import asyncio
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, field
from ..message import Message


class DeliveryStatus(Enum):
    """Message delivery status."""
    
    PENDING = "pending"        # Delivery in progress
    DELIVERED = "delivered"    # Successfully delivered
    FAILED = "failed"         # Delivery failed permanently
    EXPIRED = "expired"       # Delivery deadline expired


@dataclass
class DeliveryRecord:
    """Record of message delivery attempt."""
    
    tracking_id: str
    message_id: str
    recipient_id: Optional[str]
    status: DeliveryStatus = DeliveryStatus.PENDING
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    delivered_at: Optional[float] = None
    failed_at: Optional[float] = None
    failure_reason: Optional[str] = None
    attempt_count: int = 0
    last_attempt: Optional[float] = None


class DeliveryTracker:
    """
    Tracks delivery status of reliable messages.
    
    Maintains records of message delivery attempts, success/failure status,
    and provides monitoring and statistics.
    """
    
    def __init__(self, max_records: int = 10000):
        """
        Initialize delivery tracker.
        
        Args:
            max_records: Maximum number of delivery records to keep.
        """
        self.max_records = max_records
        self.records: Dict[str, DeliveryRecord] = {}
        
        # Statistics
        self.stats = {
            "total_deliveries": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "expired_deliveries": 0,
            "average_delivery_time": 0.0,
        }
        
    def start_delivery(self, tracking_id: str, message: Message) -> None:
        """Start tracking a message delivery."""
        record = DeliveryRecord(
            tracking_id=tracking_id,
            message_id=message.message_id,
            recipient_id=message.recipient_id,
            status=DeliveryStatus.PENDING
        )
        
        self.records[tracking_id] = record
        self.stats["total_deliveries"] += 1
        
        # Limit record count
        self._cleanup_old_records()
        
    def mark_delivered(self, tracking_id: str) -> None:
        """Mark message as successfully delivered."""
        record = self.records.get(tracking_id)
        if not record:
            return
            
        current_time = asyncio.get_event_loop().time()
        record.status = DeliveryStatus.DELIVERED
        record.delivered_at = current_time
        
        # Update statistics
        self.stats["successful_deliveries"] += 1
        delivery_time = current_time - record.created_at
        self._update_average_delivery_time(delivery_time)
        
    def mark_failed(self, tracking_id: str, reason: str) -> None:
        """Mark message delivery as failed."""
        record = self.records.get(tracking_id)
        if not record:
            return
            
        record.status = DeliveryStatus.FAILED
        record.failed_at = asyncio.get_event_loop().time()
        record.failure_reason = reason
        
        self.stats["failed_deliveries"] += 1
        
    def mark_expired(self, tracking_id: str) -> None:
        """Mark message delivery as expired."""
        record = self.records.get(tracking_id)
        if not record:
            return
            
        record.status = DeliveryStatus.EXPIRED
        record.failed_at = asyncio.get_event_loop().time()
        record.failure_reason = "Delivery deadline expired"
        
        self.stats["expired_deliveries"] += 1
        
    def update_attempt(self, tracking_id: str) -> None:
        """Update attempt count for a delivery."""
        record = self.records.get(tracking_id)
        if not record:
            return
            
        record.attempt_count += 1
        record.last_attempt = asyncio.get_event_loop().time()
        
    def get_status(self, tracking_id: str) -> Optional[DeliveryStatus]:
        """Get delivery status for a tracking ID."""
        record = self.records.get(tracking_id)
        return record.status if record else None
        
    def get_record(self, tracking_id: str) -> Optional[DeliveryRecord]:
        """Get full delivery record for a tracking ID."""
        return self.records.get(tracking_id)
        
    def get_pending_deliveries(self) -> List[DeliveryRecord]:
        """Get all pending delivery records."""
        return [
            record for record in self.records.values()
            if record.status == DeliveryStatus.PENDING
        ]
        
    def get_failed_deliveries(self) -> List[DeliveryRecord]:
        """Get all failed delivery records."""
        return [
            record for record in self.records.values()
            if record.status == DeliveryStatus.FAILED
        ]
        
    def cleanup_expired_deliveries(self, max_age: float = 3600.0) -> int:
        """
        Clean up expired delivery records.
        
        Args:
            max_age: Maximum age in seconds for delivery records.
            
        Returns:
            Number of records cleaned up.
        """
        current_time = asyncio.get_event_loop().time()
        expired_ids = []
        
        for tracking_id, record in self.records.items():
            age = current_time - record.created_at
            if age > max_age and record.status in [DeliveryStatus.DELIVERED, DeliveryStatus.FAILED, DeliveryStatus.EXPIRED]:
                expired_ids.append(tracking_id)
                
        for tracking_id in expired_ids:
            del self.records[tracking_id]
            
        return len(expired_ids)
        
    def _cleanup_old_records(self) -> None:
        """Clean up old records to maintain size limit."""
        if len(self.records) <= self.max_records:
            return
            
        # Sort by creation time and remove oldest
        sorted_records = sorted(
            self.records.items(),
            key=lambda x: x[1].created_at
        )
        
        excess_count = len(self.records) - self.max_records + 100  # Remove extra for buffer
        excess_count = min(excess_count, len(sorted_records))  # Don't exceed available records
        for i in range(excess_count):
            tracking_id, _ = sorted_records[i]
            del self.records[tracking_id]
            
    def _update_average_delivery_time(self, delivery_time: float) -> None:
        """Update average delivery time statistic."""
        current_avg = self.stats["average_delivery_time"]
        successful_count = self.stats["successful_deliveries"]
        
        # Calculate running average
        if successful_count == 1:
            self.stats["average_delivery_time"] = delivery_time
        else:
            self.stats["average_delivery_time"] = (
                (current_avg * (successful_count - 1) + delivery_time) / successful_count
            )
            
    def get_statistics(self) -> Dict[str, Any]:
        """Get delivery tracking statistics."""
        pending_count = len([r for r in self.records.values() if r.status == DeliveryStatus.PENDING])
        
        return {
            **self.stats,
            "active_records": len(self.records),
            "pending_deliveries": pending_count,
            "success_rate": (
                self.stats["successful_deliveries"] / max(1, self.stats["total_deliveries"])
            ) * 100,
        }
        
    def __str__(self) -> str:
        """String representation of delivery tracker."""
        return (f"DeliveryTracker(records={len(self.records)}, "
                f"success_rate={self.get_statistics()['success_rate']:.1f}%)")
