# Policy Check CLI

A command-line interface for checking policies against JSON data using Open Policy Agent (OPA).

## Overview

The Policy Check CLI tool allows you to evaluate JSON data against policies with support for various input methods, output formats, and detailed explanations. It's designed to integrate seamlessly with CI/CD pipelines and development workflows.

## Installation

### Prerequisites

- Python 3.8 or higher
- OPA (Open Policy Agent) binary in PATH

### Install OPA

```bash
# Linux/macOS
curl -L -o opa https://openpolicyagent.org/downloads/v0.57.0/opa_linux_amd64_static
chmod 755 ./opa
sudo mv opa /usr/local/bin

# Verify installation
opa version
```

### Install the CLI

```bash
# From the repository root
pip install -e .

# Or install development dependencies
pip install -r requirements-dev.txt
```

## Usage

### Basic Usage

```bash
# Check inline JSON data
policy-check --data '{"user": "alice", "action": "read"}' --policy access_control

# Check data from file
policy-check --file data.json --policy access_control

# Check data from stdin
echo '{"user": "bob", "action": "write"}' | policy-check --policy access_control
```

### Command Line Options

| Option | Short | Description | Required |
|--------|-------|-------------|----------|
| `--data` | `-d` | Inline JSON data to check | No* |
| `--file` | `-f` | JSON file to check | No* |
| `--policy` | `-p` | Policy file or policy name | Yes |
| `--feature-flags` | | Feature flags as JSON string | No |
| `--explain` | | Provide detailed explanation | No |
| `--format` | | Output format (json, text, yaml) | No |
| `--verbose` | `-v` | Verbose output | No |

*One of `--data`, `--file`, or stdin input is required.

### Input Methods

#### 1. Inline JSON Data

```bash
policy-check --data '{"user": "alice", "resource": "/api/users"}' --policy api_access
```

#### 2. File Input

```bash
# Create a JSON file
echo '{"user": "bob", "action": "delete", "resource": "document"}' > request.json

# Check the file
policy-check --file request.json --policy document_policy
```

#### 3. Stdin Input

```bash
# Pipe JSON data
echo '{"service": "auth", "endpoint": "/login"}' | policy-check --policy service_policy

# From curl response
curl -s https://api.example.com/request | policy-check --policy api_validation
```

### Output Formats

#### Text Format (Default)

```bash
policy-check --data '{"user": "alice"}' --policy test_policy
```

Output:
```
Policy Decision: ALLOW
Policy: test_policy
```

#### JSON Format

```bash
policy-check --data '{"user": "alice"}' --policy test_policy --format json
```

Output:
```json
{
  "allow": true,
  "policy": "test_policy",
  "input": {"user": "alice"},
  "flags": {}
}
```

#### YAML Format

```bash
policy-check --data '{"user": "alice"}' --policy test_policy --format yaml
```

Output:
```yaml
---
allow: true
policy: test_policy
input: {"user": "alice"}
flags: {}
```

### Feature Flags

Pass feature flags to influence policy evaluation:

```bash
policy-check \
  --data '{"user": "alice", "action": "admin"}' \
  --policy admin_policy \
  --feature-flags '{"beta_features": true, "strict_mode": false}'
```

### Detailed Explanations

Get detailed explanations of policy decisions:

```bash
policy-check \
  --data '{"user": "alice", "action": "read"}' \
  --policy access_control \
  --explain
```

Output:
```
Policy Decision: ALLOW
Policy: access_control

Explanation: Policy 'access_control' evaluated successfully. User 'alice' has read permissions.
Details: {
  "evaluated_rules": ["user_permissions", "resource_access"],
  "decision_path": "allow -> user.permissions.read == true"
}
```

### Verbose Mode

Enable verbose output for debugging:

```bash
policy-check \
  --data '{"user": "alice"}' \
  --policy test_policy \
  --verbose
```

## Exit Codes

The CLI uses standard exit codes to indicate the result:

| Exit Code | Meaning | Description |
|-----------|---------|-------------|
| `0` | **ALLOW** | Policy allows the action |
| `1` | **ERROR** | Error occurred during evaluation |
| `2` | **DENY** | Policy denies the action |

### Using Exit Codes in Scripts

```bash
#!/bin/bash

# Check policy and handle result
if policy-check --data "$REQUEST_DATA" --policy security_policy; then
    echo "Request approved"
    # Continue with approved action
else
    exit_code=$?
    if [ $exit_code -eq 2 ]; then
        echo "Request denied by policy"
    else
        echo "Error evaluating policy"
    fi
    exit $exit_code
fi
```

## Integration Examples

### CI/CD Pipeline

```yaml
# .github/workflows/policy-check.yml
- name: Validate deployment request
  run: |
    echo '${{ toJson(github.event) }}' | \
    policy-check --policy deployment_policy --format json
```

### Docker Integration

```dockerfile
FROM python:3.11-slim

# Install OPA
RUN curl -L -o /usr/local/bin/opa \
    https://openpolicyagent.org/downloads/v0.57.0/opa_linux_amd64_static && \
    chmod +x /usr/local/bin/opa

# Install policy-check
COPY . /app
WORKDIR /app
RUN pip install -e .

ENTRYPOINT ["policy-check"]
```

### Kubernetes Admission Controller

```bash
# Validate Kubernetes resources
kubectl get pod my-pod -o json | \
policy-check --policy k8s_security --explain
```

## Development

### Running Tests

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/test_policy_check_cli.py -v

# Run with coverage
pytest tests/test_policy_check_cli.py --cov=tools.policy-check --cov-report=html
```

### Project Structure

```
tools/policy-check/
├── check_policy.py      # Main CLI implementation
└── README.md           # This documentation

tests/
└── test_policy_check_cli.py  # Test suite

.github/workflows/
└── policy-check.yml    # CI workflow

requirements-dev.txt    # Development dependencies
pyproject.toml         # Package configuration
```

## Troubleshooting

### Common Issues

1. **OPA not found in PATH**
   ```
   Error: OPA (Open Policy Agent) binary not found in PATH
   ```
   Solution: Install OPA binary and ensure it's in your PATH.

2. **Invalid JSON input**
   ```
   Error: Invalid JSON in --data: Expecting ',' delimiter
   ```
   Solution: Validate your JSON input using a JSON validator.

3. **Policy file not found**
   ```
   Error: Policy file 'my_policy' not found
   ```
   Solution: Ensure the policy file exists and is accessible.

### Debug Mode

Use verbose mode to troubleshoot issues:

```bash
policy-check --data '{"test": "data"}' --policy my_policy --verbose
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `pytest tests/test_policy_check_cli.py`
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
