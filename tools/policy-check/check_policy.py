#!/usr/bin/env python3
"""
Policy Check CLI Tool

A command-line interface for checking policies against JSON data.
Supports inline JSON, file input, and stdin input with various output formats.
"""

import sys
import json
import click
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List


@click.command()
@click.option('--data', '-d', help='Inline JSON data to check')
@click.option('--file', '-f', 'data_file', type=click.Path(exists=True), help='JSON file to check')
@click.option('--policy', '-p', required=True, help='Policy file or policy name to check against')
@click.option('--feature-flags', help='Feature flags as JSON string')
@click.option('--explain', is_flag=True, help='Provide detailed explanation of policy decision')
@click.option('--format', 'output_format', type=click.Choice(['json', 'text', 'yaml']), default='text', help='Output format')
@click.option('--verbose', '-v', is_flag=True, help='Verbose output')
def main(data: Optional[str], data_file: Optional[str], policy: str, feature_flags: Optional[str], 
         explain: bool, output_format: str, verbose: bool):
    """
    Policy Check CLI - Evaluate JSON data against policies.
    
    Exit codes:
    0 - Policy allows the action
    1 - Error occurred during evaluation
    2 - Policy denies the action
    """
    try:
        # Get input data
        input_data = get_input_data(data, data_file)
        
        # Parse feature flags if provided
        flags = {}
        if feature_flags:
            try:
                flags = json.loads(feature_flags)
            except json.JSONDecodeError as e:
                click.echo(f"Error parsing feature flags: {e}", err=True)
                sys.exit(1)
        
        # Check if OPA is available
        if not check_opa_available():
            click.echo("Error: OPA (Open Policy Agent) binary not found in PATH", err=True)
            click.echo("Please install OPA: https://www.openpolicyagent.org/docs/latest/#running-opa", err=True)
            sys.exit(1)
        
        # Evaluate policy
        result = evaluate_policy(input_data, policy, flags, explain, verbose)
        
        # Format and output result
        output_result(result, output_format, explain)
        
        # Exit with appropriate code
        if result.get('allow', False):
            sys.exit(0)  # Allow
        else:
            sys.exit(2)  # Deny
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def get_input_data(data: Optional[str], data_file: Optional[str]) -> Dict[str, Any]:
    """Get input data from various sources."""
    if data:
        try:
            return json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in --data: {e}")
    
    elif data_file:
        try:
            with open(data_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in file {data_file}: {e}")
        except IOError as e:
            raise ValueError(f"Cannot read file {data_file}: {e}")
    
    else:
        # Read from stdin
        try:
            stdin_data = sys.stdin.read().strip()
            if not stdin_data:
                raise ValueError("No input data provided (stdin is empty)")
            return json.loads(stdin_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from stdin: {e}")


def check_opa_available() -> bool:
    """Check if OPA binary is available in PATH."""
    try:
        subprocess.run(['opa', 'version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def evaluate_policy(data: Dict[str, Any], policy: str, flags: Dict[str, Any], 
                   explain: bool, verbose: bool) -> Dict[str, Any]:
    """Evaluate data against policy using OPA."""
    # This is a mock implementation for demonstration
    # In a real implementation, this would use OPA to evaluate the policy
    
    if verbose:
        click.echo(f"Evaluating policy: {policy}", err=True)
        click.echo(f"Input data keys: {list(data.keys())}", err=True)
        click.echo(f"Feature flags: {flags}", err=True)
    
    # Mock policy evaluation logic
    # This would be replaced with actual OPA integration
    result = {
        'allow': True,  # Mock result
        'policy': policy,
        'input': data,
        'flags': flags
    }
    
    if explain:
        result['explanation'] = f"Policy '{policy}' evaluated successfully. Mock implementation allows all requests."
        result['details'] = {
            'evaluated_rules': ['mock_rule_1', 'mock_rule_2'],
            'decision_path': 'allow -> true'
        }
    
    return result


def output_result(result: Dict[str, Any], format_type: str, explain: bool):
    """Output the result in the specified format."""
    if format_type == 'json':
        click.echo(json.dumps(result, indent=2))
    elif format_type == 'yaml':
        # Simple YAML-like output without requiring PyYAML
        click.echo("---")
        for key, value in result.items():
            if isinstance(value, (dict, list)):
                click.echo(f"{key}: {json.dumps(value)}")
            else:
                click.echo(f"{key}: {value}")
    else:  # text format
        status = "ALLOW" if result.get('allow') else "DENY"
        click.echo(f"Policy Decision: {status}")
        click.echo(f"Policy: {result.get('policy', 'unknown')}")
        
        if explain and 'explanation' in result:
            click.echo(f"\nExplanation: {result['explanation']}")
            if 'details' in result:
                click.echo(f"Details: {json.dumps(result['details'], indent=2)}")


if __name__ == '__main__':
    main()
