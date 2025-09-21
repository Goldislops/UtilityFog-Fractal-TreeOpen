
"""
Phase 3 Feature Flags Registry
Centralized feature flag management for telemetry, visualization, and observability.
"""

import os
import json
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class FeatureFlags:
    """Feature flags configuration for Phase 3 components."""
    
    # Core Phase 3 features
    enable_telemetry: bool = True
    enable_visualization: bool = True
    enable_observability: bool = True
    
    # Telemetry configuration
    telemetry_max_history: int = 1000
    telemetry_export_format: str = "json"
    telemetry_auto_export: bool = False
    
    # Visualization configuration
    viz_real_time_updates: bool = True
    viz_max_data_points: int = 500
    viz_chart_types: list = None
    viz_export_formats: list = None
    
    # Observability configuration
    observability_log_level: str = "INFO"
    observability_rate_limit: int = 10
    observability_trace_all: bool = False
    observability_export_metrics: bool = True
    
    # Performance and debugging
    enable_performance_monitoring: bool = True
    enable_debug_mode: bool = False
    enable_profiling: bool = False
    
    # Integration settings
    run_loop_telemetry: bool = True
    run_loop_visualization: bool = True
    run_loop_observability: bool = True
    
    def __post_init__(self):
        """Initialize default values for list fields."""
        if self.viz_chart_types is None:
            self.viz_chart_types = ["line", "scatter", "bar", "heatmap"]
        if self.viz_export_formats is None:
            self.viz_export_formats = ["png", "html", "json"]


class FeatureFlagManager:
    """Centralized feature flag management system."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._get_default_config_path()
        self._flags = self._load_flags()
    
    def _get_default_config_path(self) -> str:
        """Get default configuration file path."""
        return os.path.join(
            os.path.dirname(__file__), 
            "..", "..", "config", "feature_flags.json"
        )
    
    def _load_flags(self) -> FeatureFlags:
        """Load feature flags from configuration file or environment."""
        # Start with defaults
        flags = FeatureFlags()
        
        # Try to load from file first
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config_data = json.load(f)
                # Apply file configuration
                for key, value in config_data.items():
                    if hasattr(flags, key):
                        setattr(flags, key, value)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Failed to load feature flags from {self.config_path}: {e}")
        
        # Load from environment variables (overrides file)
        env_overrides = self._load_from_environment()
        
        # Apply environment overrides
        for key, value in env_overrides.items():
            if hasattr(flags, key):
                setattr(flags, key, value)
        
        return flags
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load feature flag overrides from environment variables."""
        env_overrides = {}
        prefix = "UFOG_"
        
        for key, value in os.environ.items():
            if key.startswith(prefix):
                flag_name = key[len(prefix):].lower()
                
                # Convert string values to appropriate types
                if value.lower() in ('true', '1', 'yes', 'on'):
                    env_overrides[flag_name] = True
                elif value.lower() in ('false', '0', 'no', 'off'):
                    env_overrides[flag_name] = False
                elif value.isdigit():
                    env_overrides[flag_name] = int(value)
                else:
                    env_overrides[flag_name] = value
        
        return env_overrides
    
    def get_flags(self) -> FeatureFlags:
        """Get current feature flags."""
        return self._flags
    
    def is_enabled(self, feature_name: str) -> bool:
        """Check if a specific feature is enabled."""
        return getattr(self._flags, feature_name, False)
    
    def get_config(self, config_name: str, default: Any = None) -> Any:
        """Get a specific configuration value."""
        return getattr(self._flags, config_name, default)
    
    def update_flag(self, flag_name: str, value: Any) -> None:
        """Update a specific feature flag."""
        if hasattr(self._flags, flag_name):
            setattr(self._flags, flag_name, value)
        else:
            raise ValueError(f"Unknown feature flag: {flag_name}")
    
    def save_flags(self, path: Optional[str] = None) -> None:
        """Save current feature flags to configuration file."""
        save_path = path or self.config_path
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, 'w') as f:
            json.dump(asdict(self._flags), f, indent=2)
    
    def reset_to_defaults(self) -> None:
        """Reset all flags to default values."""
        self._flags = FeatureFlags()
    
    def get_phase3_status(self) -> Dict[str, bool]:
        """Get status of all Phase 3 components."""
        return {
            "telemetry": self._flags.enable_telemetry,
            "visualization": self._flags.enable_visualization,
            "observability": self._flags.enable_observability,
            "performance_monitoring": self._flags.enable_performance_monitoring
        }
    
    def get_run_loop_config(self) -> Dict[str, bool]:
        """Get run loop integration configuration."""
        return {
            "telemetry": self._flags.run_loop_telemetry,
            "visualization": self._flags.run_loop_visualization,
            "observability": self._flags.run_loop_observability
        }


# Global feature flag manager instance
_feature_flag_manager = None


def get_feature_flags() -> FeatureFlagManager:
    """Get the global feature flag manager instance."""
    global _feature_flag_manager
    if _feature_flag_manager is None:
        _feature_flag_manager = FeatureFlagManager()
    return _feature_flag_manager


def initialize_feature_flags(config_path: Optional[str] = None) -> FeatureFlagManager:
    """Initialize the global feature flag system."""
    global _feature_flag_manager
    _feature_flag_manager = FeatureFlagManager(config_path)
    return _feature_flag_manager


# Convenience functions for common feature checks
def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled."""
    return get_feature_flags().is_enabled("enable_telemetry")


def is_visualization_enabled() -> bool:
    """Check if visualization is enabled."""
    return get_feature_flags().is_enabled("enable_visualization")


def is_observability_enabled() -> bool:
    """Check if observability is enabled."""
    return get_feature_flags().is_enabled("enable_observability")


def is_performance_monitoring_enabled() -> bool:
    """Check if performance monitoring is enabled."""
    return get_feature_flags().is_enabled("enable_performance_monitoring")


def get_telemetry_config() -> Dict[str, Any]:
    """Get telemetry configuration."""
    flags = get_feature_flags().get_flags()
    return {
        "max_history": flags.telemetry_max_history,
        "export_format": flags.telemetry_export_format,
        "auto_export": flags.telemetry_auto_export
    }


def get_visualization_config() -> Dict[str, Any]:
    """Get visualization configuration."""
    flags = get_feature_flags().get_flags()
    return {
        "real_time_updates": flags.viz_real_time_updates,
        "max_data_points": flags.viz_max_data_points,
        "chart_types": flags.viz_chart_types,
        "export_formats": flags.viz_export_formats
    }


def get_observability_config() -> Dict[str, Any]:
    """Get observability configuration."""
    flags = get_feature_flags().get_flags()
    return {
        "log_level": flags.observability_log_level,
        "rate_limit": flags.observability_rate_limit,
        "trace_all": flags.observability_trace_all,
        "export_metrics": flags.observability_export_metrics
    }
