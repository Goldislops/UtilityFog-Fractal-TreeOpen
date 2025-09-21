"""
Unit tests for RetryPolicy class.

Tests cover retry policy configuration, backoff calculations,
and retry decision logic.
"""

import pytest
import time
from fractal_tree.messaging import RetryPolicy, BackoffStrategy


class TestRetryPolicyCreation:
    """Test RetryPolicy creation and configuration."""
    
    def test_create_default_retry_policy(self):
        """Test creating a default retry policy."""
        policy = RetryPolicy()
        
        assert policy.max_attempts == 3
        assert policy.base_delay == 1.0
        assert policy.max_delay == 60.0
        assert policy.backoff_strategy == BackoffStrategy.EXPONENTIAL_JITTER
        assert policy.jitter_factor == 0.1
        assert policy.backoff_multiplier == 2.0
        
    def test_create_custom_retry_policy(self):
        """Test creating a custom retry policy."""
        policy = RetryPolicy(
            max_attempts=5,
            base_delay=2.0,
            max_delay=120.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            jitter_factor=0.2,
            backoff_multiplier=3.0
        )
        
        assert policy.max_attempts == 5
        assert policy.base_delay == 2.0
        assert policy.max_delay == 120.0
        assert policy.backoff_strategy == BackoffStrategy.EXPONENTIAL
        assert policy.jitter_factor == 0.2
        assert policy.backoff_multiplier == 3.0


class TestBackoffCalculation:
    """Test backoff delay calculations."""
    
    def test_fixed_backoff(self):
        """Test fixed backoff strategy."""
        policy = RetryPolicy(
            base_delay=5.0,
            backoff_strategy=BackoffStrategy.FIXED
        )
        
        assert policy.calculate_backoff(1) == 5.0
        assert policy.calculate_backoff(2) == 5.0
        assert policy.calculate_backoff(3) == 5.0
        
    def test_linear_backoff(self):
        """Test linear backoff strategy."""
        policy = RetryPolicy(
            base_delay=2.0,
            backoff_strategy=BackoffStrategy.LINEAR
        )
        
        assert policy.calculate_backoff(1) == 2.0
        assert policy.calculate_backoff(2) == 4.0
        assert policy.calculate_backoff(3) == 6.0
        
    def test_exponential_backoff(self):
        """Test exponential backoff strategy."""
        policy = RetryPolicy(
            base_delay=1.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            backoff_multiplier=2.0
        )
        
        assert policy.calculate_backoff(1) == 1.0
        assert policy.calculate_backoff(2) == 2.0
        assert policy.calculate_backoff(3) == 4.0
        assert policy.calculate_backoff(4) == 8.0
        
    def test_exponential_jitter_backoff(self):
        """Test exponential backoff with jitter."""
        policy = RetryPolicy(
            base_delay=1.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL_JITTER,
            backoff_multiplier=2.0,
            jitter_factor=0.1
        )
        
        # Test multiple times to account for randomness
        delays = [policy.calculate_backoff(2) for _ in range(10)]
        
        # All delays should be around 2.0 with jitter
        for delay in delays:
            assert 1.8 <= delay <= 2.2  # 2.0 +/- 10% jitter
            
    def test_max_delay_limit(self):
        """Test maximum delay limit enforcement."""
        policy = RetryPolicy(
            base_delay=10.0,
            max_delay=15.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            backoff_multiplier=2.0
        )
        
        assert policy.calculate_backoff(1) == 10.0
        assert policy.calculate_backoff(2) == 15.0  # Capped at max_delay
        assert policy.calculate_backoff(3) == 15.0  # Still capped
        
    def test_zero_attempt_backoff(self):
        """Test backoff calculation for zero attempts."""
        policy = RetryPolicy()
        assert policy.calculate_backoff(0) == 0.0
        
    def test_negative_attempt_backoff(self):
        """Test backoff calculation for negative attempts."""
        policy = RetryPolicy()
        assert policy.calculate_backoff(-1) == 0.0


class TestRetryDecision:
    """Test retry decision logic."""
    
    def test_should_retry_within_limit(self):
        """Test retry decision within attempt limit."""
        policy = RetryPolicy(max_attempts=3)
        
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True
        assert policy.should_retry(3) is False  # At limit
        assert policy.should_retry(4) is False  # Over limit
        
    def test_should_retry_no_attempts(self):
        """Test retry decision with no retry policy."""
        policy = RetryPolicy(max_attempts=1)
        
        assert policy.should_retry(1) is False  # No retries allowed


class TestRetryPolicyFactories:
    """Test retry policy factory methods."""
    
    def test_create_aggressive_policy(self):
        """Test creating aggressive retry policy."""
        policy = RetryPolicy.create_aggressive()
        
        assert policy.max_attempts == 5
        assert policy.base_delay == 0.1
        assert policy.max_delay == 5.0
        assert policy.backoff_strategy == BackoffStrategy.EXPONENTIAL_JITTER
        assert policy.backoff_multiplier == 1.5
        
    def test_create_conservative_policy(self):
        """Test creating conservative retry policy."""
        policy = RetryPolicy.create_conservative()
        
        assert policy.max_attempts == 3
        assert policy.base_delay == 2.0
        assert policy.max_delay == 120.0
        assert policy.backoff_strategy == BackoffStrategy.EXPONENTIAL_JITTER
        assert policy.backoff_multiplier == 3.0
        
    def test_create_fixed_delay_policy(self):
        """Test creating fixed delay retry policy."""
        policy = RetryPolicy.create_fixed_delay(5.0, 4)
        
        assert policy.max_attempts == 4
        assert policy.base_delay == 5.0
        assert policy.max_delay == 5.0
        assert policy.backoff_strategy == BackoffStrategy.FIXED
        
    def test_create_no_retry_policy(self):
        """Test creating no-retry policy."""
        policy = RetryPolicy.create_no_retry()
        
        assert policy.max_attempts == 1


class TestRetryPolicyUtilities:
    """Test retry policy utility methods."""
    
    def test_get_total_timeout(self):
        """Test total timeout calculation."""
        policy = RetryPolicy(
            max_attempts=3,
            base_delay=1.0,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            backoff_multiplier=2.0
        )
        
        # Should be 1.0 + 2.0 + 4.0 = 7.0
        total_timeout = policy.get_total_timeout()
        assert total_timeout == 7.0
        
    def test_str_representation(self):
        """Test string representation."""
        policy = RetryPolicy(max_attempts=5, base_delay=2.0)
        str_repr = str(policy)
        
        assert "RetryPolicy" in str_repr
        assert "attempts=5" in str_repr
        assert "base_delay=2.0s" in str_repr
