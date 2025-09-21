"""
Tests for Phase 3 Feature Flags System
Tests centralized feature flag management and configuration.
"""

import pytest
import json
import os
import tempfile
from unittest.mock import patch, mock_open
import sys

# Import the feature flags module
sys.path.append('/home/ubuntu/github_repos/UtilityFog-Fractal-TreeOpen/UtilityFog_Agent_Package')
from agent.feature_flags import (
    FeatureFlags, FeatureFlagManager,
    get_feature_flags, initialize_feature_flags,
    is_telemetry_enabled, is_visualization_enabled, is_observability_enabled,
    get_telemetry_config, get_visualization_config, get_observability_config
)


class TestFeatureFlags:
    """Test FeatureFlags dataclass."""
    
    def test_default_values(self):
        """Test default feature flag values."""
        flags = FeatureFlags()
        
        # Core Phase 3 features should be enabled by default
        assert flags.enable_telemetry is True
        assert flags.enable_visualization is True
        assert flags.enable_observability is True
        
        # Check default configurations
        assert flags.telemetry_max_history == 1000
        assert flags.observability_log_level == "INFO"
        assert flags.viz_real_time_updates is True
        
        # Check run loop integration
        assert flags.run_loop_telemetry is True
        assert flags.run_loop_visualization is True
        assert flags.run_loop_observability is True
    
    def test_list_initialization(self):
        """Test that list fields are properly initialized."""
        flags = FeatureFlags()
        
        assert flags.viz_chart_types == ["line", "scatter", "bar", "heatmap"]
        assert flags.viz_export_formats == ["png", "html", "json"]
    
    def test_custom_values(self):
        """Test creating FeatureFlags with custom values."""
        flags = FeatureFlags(
            enable_telemetry=False,
            telemetry_max_history=500,
            observability_log_level="DEBUG",
            viz_chart_types=["line", "bar"]
        )
        
        assert flags.enable_telemetry is False
        assert flags.telemetry_max_history == 500
        assert flags.observability_log_level == "DEBUG"
        assert flags.viz_chart_types == ["line", "bar"]


class TestFeatureFlagManager:
    """Test FeatureFlagManager functionality."""
    
    def test_initialization_with_defaults(self):
        """Test manager initialization with default values."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            # Create empty config file
            json.dump({}, f)
            config_path = f.name
        
        try:
            manager = FeatureFlagManager(config_path)
            flags = manager.get_flags()
            
            # Should have default values
            assert flags.enable_telemetry is True
            assert flags.enable_observability is True
        finally:
            os.unlink(config_path)
    
    def test_load_from_file(self):
        """Test loading configuration from JSON file."""
        config_data = {
            "enable_telemetry": False,
            "telemetry_max_history": 2000,
            "observability_log_level": "DEBUG"
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name
        
        try:
            manager = FeatureFlagManager(config_path)
            flags = manager.get_flags()
            
            assert flags.enable_telemetry is False
            assert flags.telemetry_max_history == 2000
            assert flags.observability_log_level == "DEBUG"
            # Other values should remain default
            assert flags.enable_visualization is True
        finally:
            os.unlink(config_path)
    
    def test_load_from_environment(self):
        """Test loading configuration from environment variables."""
        env_vars = {
            'UFOG_ENABLE_TELEMETRY': 'false',
            'UFOG_TELEMETRY_MAX_HISTORY': '3000',
            'UFOG_OBSERVABILITY_LOG_LEVEL': 'WARNING',
            'UFOG_ENABLE_DEBUG_MODE': 'true'
        }
        
        with patch.dict(os.environ, env_vars):
            manager = FeatureFlagManager('/nonexistent/path')
            flags = manager.get_flags()
            
            assert flags.enable_telemetry is False
            assert flags.telemetry_max_history == 3000
            assert flags.observability_log_level == "WARNING"
            assert flags.enable_debug_mode is True
    
    def test_environment_overrides_file(self):
        """Test that environment variables override file configuration."""
        config_data = {
            "enable_telemetry": True,
            "telemetry_max_history": 1000
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name
        
        env_vars = {
            'UFOG_ENABLE_TELEMETRY': 'false',
            'UFOG_TELEMETRY_MAX_HISTORY': '5000'
        }
        
        try:
            with patch.dict(os.environ, env_vars):
                manager = FeatureFlagManager(config_path)
                flags = manager.get_flags()
                
                # Environment should override file
                assert flags.enable_telemetry is False
                assert flags.telemetry_max_history == 5000
        finally:
            os.unlink(config_path)
    
    def test_is_enabled(self):
        """Test is_enabled method."""
        manager = FeatureFlagManager('/nonexistent/path')
        
        assert manager.is_enabled('enable_telemetry') is True
        assert manager.is_enabled('enable_debug_mode') is False
        assert manager.is_enabled('nonexistent_flag') is False
    
    def test_get_config(self):
        """Test get_config method."""
        manager = FeatureFlagManager('/nonexistent/path')
        
        assert manager.get_config('telemetry_max_history') == 1000
        assert manager.get_config('observability_log_level') == "INFO"
        assert manager.get_config('nonexistent_config', 'default') == 'default'
    
    def test_update_flag(self):
        """Test update_flag method."""
        manager = FeatureFlagManager('/nonexistent/path')
        
        # Update existing flag
        manager.update_flag('enable_telemetry', False)
        assert manager.is_enabled('enable_telemetry') is False
        
        # Try to update non-existent flag
        with pytest.raises(ValueError, match="Unknown feature flag"):
            manager.update_flag('nonexistent_flag', True)
    
    def test_save_flags(self):
        """Test save_flags method."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_path = f.name
        
        try:
            manager = FeatureFlagManager('/nonexistent/path')
            manager.update_flag('enable_telemetry', False)
            manager.save_flags(config_path)
            
            # Load saved configuration
            with open(config_path, 'r') as f:
                saved_config = json.load(f)
            
            assert saved_config['enable_telemetry'] is False
            assert saved_config['enable_visualization'] is True
        finally:
            os.unlink(config_path)
    
    def test_reset_to_defaults(self):
        """Test reset_to_defaults method."""
        manager = FeatureFlagManager('/nonexistent/path')
        
        # Modify some flags
        manager.update_flag('enable_telemetry', False)
        manager.update_flag('telemetry_max_history', 5000)
        
        # Reset to defaults
        manager.reset_to_defaults()
        
        flags = manager.get_flags()
        assert flags.enable_telemetry is True
        assert flags.telemetry_max_history == 1000
    
    def test_get_phase3_status(self):
        """Test get_phase3_status method."""
        manager = FeatureFlagManager('/nonexistent/path')
        status = manager.get_phase3_status()
        
        expected_keys = ["telemetry", "visualization", "observability", "performance_monitoring"]
        assert all(key in status for key in expected_keys)
        assert all(isinstance(value, bool) for value in status.values())
    
    def test_get_run_loop_config(self):
        """Test get_run_loop_config method."""
        manager = FeatureFlagManager('/nonexistent/path')
        config = manager.get_run_loop_config()
        
        expected_keys = ["telemetry", "visualization", "observability"]
        assert all(key in config for key in expected_keys)
        assert all(isinstance(value, bool) for value in config.values())


class TestGlobalFunctions:
    """Test global convenience functions."""
    
    def test_global_manager_singleton(self):
        """Test that global manager is a singleton."""
        manager1 = get_feature_flags()
        manager2 = get_feature_flags()
        
        assert manager1 is manager2
    
    def test_initialize_feature_flags(self):
        """Test initialize_feature_flags function."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            config_data = {"enable_telemetry": False}
            json.dump(config_data, f)
            config_path = f.name
        
        try:
            manager = initialize_feature_flags(config_path)
            assert manager.is_enabled('enable_telemetry') is False
            
            # Global manager should be updated
            global_manager = get_feature_flags()
            assert global_manager is manager
        finally:
            os.unlink(config_path)
    
    def test_convenience_functions(self):
        """Test convenience functions for feature checks."""
        # Reset to defaults for predictable testing
        manager = get_feature_flags()
        manager.reset_to_defaults()
        
        assert is_telemetry_enabled() is True
        assert is_visualization_enabled() is True
        assert is_observability_enabled() is True
        
        # Test configuration getters
        telemetry_config = get_telemetry_config()
        assert telemetry_config['max_history'] == 1000
        assert telemetry_config['export_format'] == "json"
        
        viz_config = get_visualization_config()
        assert viz_config['real_time_updates'] is True
        assert "line" in viz_config['chart_types']
        
        obs_config = get_observability_config()
        assert obs_config['log_level'] == "INFO"
        assert obs_config['rate_limit'] == 10


class TestEnvironmentVariableParsing:
    """Test environment variable parsing logic."""
    
    def test_boolean_parsing(self):
        """Test boolean environment variable parsing."""
        test_cases = [
            ('true', True), ('1', True), ('yes', True), ('on', True),
            ('false', False), ('0', False), ('no', False), ('off', False),
            ('TRUE', True), ('FALSE', False)  # Case insensitive
        ]
        
        for env_value, expected in test_cases:
            env_vars = {'UFOG_ENABLE_TELEMETRY': env_value}
            
            with patch.dict(os.environ, env_vars):
                manager = FeatureFlagManager('/nonexistent/path')
                assert manager.is_enabled('enable_telemetry') == expected
    
    def test_integer_parsing(self):
        """Test integer environment variable parsing."""
        env_vars = {'UFOG_TELEMETRY_MAX_HISTORY': '2500'}
        
        with patch.dict(os.environ, env_vars):
            manager = FeatureFlagManager('/nonexistent/path')
            assert manager.get_config('telemetry_max_history') == 2500
    
    def test_string_parsing(self):
        """Test string environment variable parsing."""
        env_vars = {'UFOG_OBSERVABILITY_LOG_LEVEL': 'DEBUG'}
        
        with patch.dict(os.environ, env_vars):
            manager = FeatureFlagManager('/nonexistent/path')
            assert manager.get_config('observability_log_level') == 'DEBUG'


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    def test_invalid_json_file(self):
        """Test handling of invalid JSON configuration file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content")
            config_path = f.name
        
        try:
            # Should not raise exception, should fall back to defaults
            manager = FeatureFlagManager(config_path)
            flags = manager.get_flags()
            
            # Should have default values
            assert flags.enable_telemetry is True
        finally:
            os.unlink(config_path)
    
    def test_nonexistent_config_file(self):
        """Test handling of non-existent configuration file."""
        manager = FeatureFlagManager('/nonexistent/path/config.json')
        flags = manager.get_flags()
        
        # Should have default values
        assert flags.enable_telemetry is True
        assert flags.enable_visualization is True
    
    def test_directory_creation_for_save(self):
        """Test that save_flags creates directories if they don't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, 'subdir', 'config.json')
            
            manager = FeatureFlagManager('/nonexistent/path')
            manager.save_flags(config_path)
            
            # File should be created
            assert os.path.exists(config_path)
            
            # Content should be valid JSON
            with open(config_path, 'r') as f:
                config = json.load(f)
            assert 'enable_telemetry' in config


class TestIntegrationScenarios:
    """Test realistic integration scenarios."""
    
    def test_development_environment(self):
        """Test typical development environment configuration."""
        config_data = {
            "enable_debug_mode": True,
            "observability_log_level": "DEBUG",
            "enable_profiling": True,
            "telemetry_max_history": 100  # Smaller for dev
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            config_path = f.name
        
        try:
            manager = FeatureFlagManager(config_path)
            flags = manager.get_flags()
            
            assert flags.enable_debug_mode is True
            assert flags.observability_log_level == "DEBUG"
            assert flags.enable_profiling is True
            assert flags.telemetry_max_history == 100
            
            # Production features should still be enabled
            assert flags.enable_telemetry is True
            assert flags.enable_observability is True
        finally:
            os.unlink(config_path)
    
    def test_production_environment(self):
        """Test typical production environment configuration."""
        env_vars = {
            'UFOG_ENABLE_DEBUG_MODE': 'false',
            'UFOG_ENABLE_PROFILING': 'false',
            'UFOG_OBSERVABILITY_LOG_LEVEL': 'WARNING',
            'UFOG_TELEMETRY_MAX_HISTORY': '10000'
        }
        
        with patch.dict(os.environ, env_vars):
            manager = FeatureFlagManager('/nonexistent/path')
            flags = manager.get_flags()
            
            assert flags.enable_debug_mode is False
            assert flags.enable_profiling is False
            assert flags.observability_log_level == "WARNING"
            assert flags.telemetry_max_history == 10000
            
            # Core features should be enabled
            assert flags.enable_telemetry is True
            assert flags.enable_observability is True
    
    def test_feature_rollout_scenario(self):
        """Test gradual feature rollout scenario."""
        manager = FeatureFlagManager('/nonexistent/path')
        
        # Start with observability disabled
        manager.update_flag('enable_observability', False)
        manager.update_flag('run_loop_observability', False)
        
        status = manager.get_phase3_status()
        assert status['observability'] is False
        
        run_loop_config = manager.get_run_loop_config()
        assert run_loop_config['observability'] is False
        
        # Enable observability
        manager.update_flag('enable_observability', True)
        manager.update_flag('run_loop_observability', True)
        
        status = manager.get_phase3_status()
        assert status['observability'] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
