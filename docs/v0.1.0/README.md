
# UtilityFog-Fractal-TreeOpen

[![Tests](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/phase3-ci.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/phase3-ci.yml)
[![Coverage](https://files.readme.io/8192810-codecov_uploader.png)
[![Python 3.9+](https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/Blue_Python_3.9_Shield_Badge.svg/1280px-Blue_Python_3.9_Shield_Badge.svg.png)
[![License](https://i.ytimg.com/vi/4cgpu9L2AE8/maxresdefault.jpg)
[![Phase 3](https://upload.wikimedia.org/wikipedia/en/thumb/0/03/Flag_of_Italy.svg/330px-Flag_of_Italy.svg.png)

Advanced UtilityFog simulation system with comprehensive telemetry, visualization, and observability capabilities.

## 🚀 Phase 3 Features

### 📊 **Telemetry System (FT-008)**
- Real-time metrics collection and aggregation
- Performance monitoring with historical data
- Configurable export formats (JSON, CSV, XML)
- Thread-safe operations for concurrent simulations

### 📈 **CLI Visualization (FT-009)**
- Interactive command-line visualization tools
- Multiple chart types (line, scatter, bar, heatmap)
- Real-time data updates and export capabilities
- Integration with telemetry system

### 🔍 **Observability (FT-010)**
- Structured JSON logging with trace ID propagation
- Distributed tracing across operations
- Rate-limited error logging to prevent spam
- Event logging system for simulation events
- Comprehensive metrics and monitoring

## 🏗️ Architecture

```
UtilityFog-Fractal-TreeOpen
├── Phase 3 Integration Layer
│   ├── Feature Flags (centralized configuration)
│   ├── Telemetry System (metrics & performance)
│   ├── Visualization (CLI charts & exports)
│   └── Observability (logging & tracing)
├── Core Simulation Engine
│   ├── Agent System (foglet agents)
│   ├── Network Topology (distributed mesh)
│   ├── Evolution Engine (adaptive behaviors)
│   └── Meme Structure (information propagation)
└── Testing & CI/CD
    ├── Comprehensive Test Suite (≥90% coverage)
    ├── Automated Quality Checks
    └── Multi-Python Version Support
```

## 🛠️ Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen.git
cd UtilityFog-Fractal-TreeOpen

# Install dependencies
make install

# Run tests to verify installation
make test
```

### Basic Usage

```bash
# Run simulation with all Phase 3 features
make run-sim

# Test individual components
make telemetry    # Test telemetry system
make viz          # Test visualization
make observe      # Test observability
make bench        # Run performance benchmarks
```

### Development Workflow

```bash
# Setup development environment
make dev-setup

# Run all quality checks
make check-all

# Generate coverage report
make coverage-html
```

## 📋 Available Commands

### Core Operations
- `make install` - Install dependencies and setup environment
- `make test` - Run all tests
- `make coverage` - Run tests with coverage reporting
- `make run-sim` - Run main simulation with Phase 3 features

### Phase 3 Components
- `make telemetry` - Test and demonstrate telemetry system
- `make viz` - Test and demonstrate visualization capabilities
- `make observe` - Test and demonstrate observability features
- `make bench` - Run performance benchmarks

### Code Quality
- `make lint` - Run code linting (ruff)
- `make format` - Format code automatically
- `make type-check` - Run type checking (mypy)

### Maintenance
- `make clean` - Clean build artifacts
- `make help` - Show all available commands

## ⚙️ Configuration

### Feature Flags

Control Phase 3 components via `config/feature_flags.json`:

```json
{
  "enable_telemetry": true,
  "enable_visualization": true,
  "enable_observability": true,
  "telemetry_max_history": 1000,
  "observability_log_level": "INFO",
  "viz_real_time_updates": true
}
```

### Environment Variables

Override settings with environment variables:

```bash
# Disable telemetry
UFOG_ENABLE_TELEMETRY=false make run-sim

# Set debug logging
UFOG_OBSERVABILITY_LOG_LEVEL=DEBUG make observe

# Configure telemetry history
UFOG_TELEMETRY_MAX_HISTORY=5000 make telemetry
```

## 📊 Usage Examples

### Telemetry Collection

```python
from agent.telemetry_collector import get_telemetry_collector

collector = get_telemetry_collector()

# Collect metrics
collector.collect_metric("agent_count", 150)
collector.collect_performance_metric("simulation_step", 0.05, success=True)

# Get current metrics
metrics = collector.get_current_metrics()
print(f"Collected {len(metrics['metrics'])} metrics")
```

### Observability Tracing

```python
from agent.observability import trace_operation, log_simulation_event

# Trace operations
with trace_operation("agent_movement", agent_id=123):
    # Your simulation code here
    calculate_agent_movement()

# Log events
log_simulation_event("collision_detected", 
                     agents=[123, 456], 
                     severity="high")
```

### Feature Flag Usage

```python
from agent.feature_flags import is_telemetry_enabled, get_telemetry_config

if is_telemetry_enabled():
    config = get_telemetry_config()
    print(f"Telemetry configured with {config['max_history']} max history")
```

## 🧪 Testing

### Test Coverage

- **Overall Coverage**: ≥90% across all Phase 3 components
- **Observability**: 94% coverage (180 statements, 10 missed)
- **Telemetry**: 98% coverage (98 statements, 2 missed)
- **Feature Flags**: 100% coverage

### Running Tests

```bash
# All tests
make test

# Specific component tests
make test-observability
make test-telemetry

# Coverage with HTML report
make coverage-html
```

### Continuous Integration

The project uses GitHub Actions for:
- Multi-Python version testing (3.9, 3.10, 3.11)
- Code quality checks (linting, type checking)
- Security scanning
- Coverage reporting
- Integration testing of all Phase 3 components

## 📚 Documentation

### Component Documentation
- **[Observability System](docs/OBSERVABILITY.md)** - Comprehensive guide to structured logging and tracing
- **[Feature Flags](config/feature_flags.json)** - Configuration options and defaults
- **[Makefile](Makefile)** - All available development commands

### API Reference
- **Observability**: `UtilityFog_Agent_Package/agent/observability.py`
- **Telemetry**: `UtilityFog_Agent_Package/agent/telemetry_collector.py`
- **Feature Flags**: `UtilityFog_Agent_Package/agent/feature_flags.py`

## 🔧 Development

### Project Structure

```
UtilityFog-Fractal-TreeOpen/
├── UtilityFog_Agent_Package/
│   └── agent/
│       ├── observability.py          # FT-010: Observability system
│       ├── telemetry_collector.py    # FT-008: Enhanced telemetry
│       ├── feature_flags.py          # Phase 3: Feature management
│       ├── main_simulation.py        # Core simulation
│       ├── foglet_agent.py          # Agent system
│       └── ...
├── tests/
│   ├── test_observability.py        # Observability tests (25 tests)
│   └── ...
├── docs/
│   ├── OBSERVABILITY.md             # Observability documentation
│   └── ...
├── config/
│   ├── feature_flags.json           # Feature flag configuration
│   └── agent_limits.yaml           # Agent configuration
├── .github/workflows/
│   └── phase3-ci.yml               # CI/CD pipeline
├── Makefile                        # Development commands
└── README.md                       # This file
```

### Contributing

1. **Setup Development Environment**
   ```bash
   make dev-setup
   ```

2. **Make Changes**
   - Follow existing code patterns
   - Add tests for new functionality
   - Update documentation as needed

3. **Quality Checks**
   ```bash
   make check-all  # Runs lint, type-check, test, coverage
   ```

4. **Submit Pull Request**
   - Ensure all CI checks pass
   - Include comprehensive description
   - Reference related issues

### Code Quality Standards

- **Test Coverage**: ≥90% for all new code
- **Type Hints**: Required for all public APIs
- **Documentation**: Comprehensive docstrings and README updates
- **Linting**: Code must pass ruff linting
- **Formatting**: Use ruff format for consistent style

## 🚀 Deployment

### Production Readiness

The system is designed for production deployment with:
- **Configurable feature flags** for gradual rollout
- **Comprehensive monitoring** and observability
- **Performance benchmarks** and optimization
- **Multi-environment support** (dev, staging, prod)

### Deployment Commands

```bash
# Validate deployment readiness
make validate-phase3

# Run full test suite
make ci-test

# Generate deployment artifacts
make clean-all && make coverage-html
```

## 📈 Performance

### Benchmarks

- **Observability Overhead**: ~1-2% in typical scenarios
- **Telemetry Collection**: >1000 metrics/second
- **Trace Propagation**: Minimal overhead using thread-local storage
- **Memory Usage**: Configurable history limits prevent memory leaks

### Optimization Features

- **Rate-limited logging** prevents log spam
- **Efficient JSON serialization** for structured logs
- **Thread-safe operations** for concurrent simulations
- **Configurable buffer sizes** for telemetry collection

## 🤝 Support

### Getting Help

- **Issues**: [GitHub Issues](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues)
- **Documentation**: See `docs/` directory
- **Examples**: Run `make help` for command examples

### Troubleshooting

```bash
# Check system status
make validate-phase3

# Debug with verbose logging
UFOG_OBSERVABILITY_LOG_LEVEL=DEBUG make observe

# Reset to clean state
make clean-all && make install
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Phase 3 Integration**: Complete implementation of telemetry, visualization, and observability
- **Comprehensive Testing**: ≥90% coverage across all components
- **Production Ready**: Feature flags, CI/CD, and deployment automation
- **Developer Experience**: Rich Makefile, documentation, and tooling

---

**Ready for production deployment with comprehensive Phase 3 capabilities!** 🚀

For detailed component documentation, see the `docs/` directory. For development commands, run `make help`.
