
"""
Retry policy implementation with exponential backoff and jitter.

This module provides configurable retry policies for reliable message delivery.
"""

import random
import math
from typing import Optional
from enum import Enum
from dataclasses import dataclass


class BackoffStrategy(Enum):
    """Backoff strategies for retry policies."""
    
    FIXED = "fixed"                    # Fixed delay between retries
    LINEAR = "linear"                  # Linear increase in delay
    EXPONENTIAL = "exponential"        # Exponential backoff
    EXPONENTIAL_JITTER = "exponential_jitter"  # Exponential with jitter


@dataclass
class RetryPolicy:
    """
    Retry policy configuration for reliable message delivery.
    
    Defines how messages should be retried on failure, including
    backoff strategies, jitter, and attempt limits.
    """
    
    max_attempts: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL_JITTER
    jitter_factor: float = 0.1  # 10% jitter
    backoff_multiplier: float = 2.0
    
    def calculate_backoff(self, attempt: int) -> float:
        """
        Calculate backoff delay for given attempt number.
        
        Args:
            attempt: Attempt number (1-based).
            
        Returns:
            Delay in seconds before next retry.
        """
        if attempt <= 0:
            return 0.0
            
        if self.backoff_strategy == BackoffStrategy.FIXED:
            delay = self.base_delay
            
        elif self.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.base_delay * attempt
            
        elif self.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.base_delay * (self.backoff_multiplier ** (attempt - 1))
            
        elif self.backoff_strategy == BackoffStrategy.EXPONENTIAL_JITTER:
            # Exponential backoff with jitter
            exponential_delay = self.base_delay * (self.backoff_multiplier ** (attempt - 1))
            jitter = exponential_delay * self.jitter_factor * (2 * random.random() - 1)
            delay = exponential_delay + jitter
            
        else:
            delay = self.base_delay
            
        # Apply maximum delay limit
        delay = min(delay, self.max_delay)
        
        # Ensure non-negative delay
        return max(0.0, delay)
        
    def should_retry(self, attempt: int, elapsed_time: float = 0.0) -> bool:
        """
        Determine if retry should be attempted.
        
        Args:
            attempt: Current attempt number.
            elapsed_time: Total elapsed time since first attempt.
            
        Returns:
            True if retry should be attempted, False otherwise.
        """
        return attempt < self.max_attempts
        
    def get_total_timeout(self) -> float:
        """
        Calculate total timeout for all retry attempts.
        
        Returns:
            Total timeout in seconds.
        """
        total_delay = 0.0
        
        for attempt in range(1, self.max_attempts + 1):
            total_delay += self.calculate_backoff(attempt)
            
        return total_delay
        
    @classmethod
    def create_aggressive(cls) -> 'RetryPolicy':
        """Create aggressive retry policy with fast retries."""
        return cls(
            max_attempts=5,
            base_delay=0.1,
            max_delay=5.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL_JITTER,
            backoff_multiplier=1.5
        )
        
    @classmethod
    def create_conservative(cls) -> 'RetryPolicy':
        """Create conservative retry policy with slower retries."""
        return cls(
            max_attempts=3,
            base_delay=2.0,
            max_delay=120.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL_JITTER,
            backoff_multiplier=3.0
        )
        
    @classmethod
    def create_fixed_delay(cls, delay: float, max_attempts: int = 3) -> 'RetryPolicy':
        """Create retry policy with fixed delay."""
        return cls(
            max_attempts=max_attempts,
            base_delay=delay,
            max_delay=delay,
            backoff_strategy=BackoffStrategy.FIXED
        )
        
    @classmethod
    def create_no_retry(cls) -> 'RetryPolicy':
        """Create policy with no retries."""
        return cls(max_attempts=1)
        
    def __str__(self) -> str:
        """String representation of retry policy."""
        return (f"RetryPolicy(attempts={self.max_attempts}, "
                f"strategy={self.backoff_strategy.value}, "
                f"base_delay={self.base_delay}s)")
