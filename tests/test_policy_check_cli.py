"""
Tests for the policy-check CLI tool.
"""

import json
import pytest
import subprocess
import sys
from pathlib import Path
from click.testing import CliRunner

# Add the tools directory to the path so we can import the CLI
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "policy-check"))

from check_policy import main, get_input_data, evaluate_policy


class TestPolicyCheckCLI:
    """Test suite for policy-check CLI."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()
        self.sample_data = {"user": "test", "action": "read", "resource": "document"}
        self.sample_policy = "test_policy"
    
    def test_inline_json_data(self):
        """Test CLI with inline JSON data."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy
        ])
        assert result.exit_code in [0, 2]  # Allow or deny
        assert "Policy Decision:" in result.output
    
    def test_file_input(self, tmp_path):
        """Test CLI with file input."""
        # Create temporary JSON file
        json_file = tmp_path / "test_data.json"
        json_file.write_text(json.dumps(self.sample_data))
        
        result = self.runner.invoke(main, [
            '--file', str(json_file),
            '--policy', self.sample_policy
        ])
        assert result.exit_code in [0, 2]
        assert "Policy Decision:" in result.output
    
    def test_feature_flags(self):
        """Test CLI with feature flags."""
        flags = {"debug": True, "experimental": False}
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy,
            '--feature-flags', json.dumps(flags)
        ])
        assert result.exit_code in [0, 2]
    
    def test_explain_flag(self):
        """Test CLI with explain flag."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy,
            '--explain'
        ])
        assert result.exit_code in [0, 2]
        assert "Policy Decision:" in result.output
    
    def test_json_output_format(self):
        """Test CLI with JSON output format."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy,
            '--format', 'json'
        ])
        assert result.exit_code in [0, 2]
        # Should be valid JSON
        try:
            json.loads(result.output)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")
    
    def test_yaml_output_format(self):
        """Test CLI with YAML output format."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy,
            '--format', 'yaml'
        ])
        assert result.exit_code in [0, 2]
        assert "---" in result.output  # YAML document separator
    
    def test_verbose_flag(self):
        """Test CLI with verbose flag."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy,
            '--verbose'
        ])
        assert result.exit_code in [0, 2]
    
    def test_invalid_json_data(self):
        """Test CLI with invalid JSON data."""
        result = self.runner.invoke(main, [
            '--data', '{"invalid": json}',
            '--policy', self.sample_policy
        ])
        assert result.exit_code == 1  # Error
        assert "Error:" in result.output
    
    def test_invalid_feature_flags(self):
        """Test CLI with invalid feature flags JSON."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data),
            '--policy', self.sample_policy,
            '--feature-flags', '{"invalid": json}'
        ])
        assert result.exit_code == 1
        assert "Error parsing feature flags" in result.output
    
    def test_missing_policy(self):
        """Test CLI without required policy parameter."""
        result = self.runner.invoke(main, [
            '--data', json.dumps(self.sample_data)
        ])
        assert result.exit_code == 2  # Click error for missing required option
    
    def test_nonexistent_file(self):
        """Test CLI with nonexistent file."""
        result = self.runner.invoke(main, [
            '--file', '/nonexistent/file.json',
            '--policy', self.sample_policy
        ])
        assert result.exit_code == 2  # Click error for nonexistent file


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_get_input_data_from_string(self):
        """Test getting input data from JSON string."""
        data = '{"test": "value"}'
        result = get_input_data(data, None)
        assert result == {"test": "value"}
    
    def test_get_input_data_from_file(self, tmp_path):
        """Test getting input data from file."""
        json_file = tmp_path / "test.json"
        test_data = {"file": "data"}
        json_file.write_text(json.dumps(test_data))
        
        result = get_input_data(None, str(json_file))
        assert result == test_data
    
    def test_get_input_data_invalid_json_string(self):
        """Test error handling for invalid JSON string."""
        with pytest.raises(ValueError, match="Invalid JSON in --data"):
            get_input_data('{"invalid": json}', None)
    
    def test_evaluate_policy_basic(self):
        """Test basic policy evaluation."""
        data = {"test": "data"}
        result = evaluate_policy(data, "test_policy", {}, False, False)
        
        assert isinstance(result, dict)
        assert "allow" in result
        assert "policy" in result
        assert result["policy"] == "test_policy"
    
    def test_evaluate_policy_with_explanation(self):
        """Test policy evaluation with explanation."""
        data = {"test": "data"}
        result = evaluate_policy(data, "test_policy", {}, True, False)
        
        assert "explanation" in result
        assert "details" in result


if __name__ == "__main__":
    pytest.main([__file__])
