[![SpeckKit Validation](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/speckit-validate.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/speckit-validate.yml)

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

### ⚡ **Singularity Pulse — Ising Physics + Parallel Tempering**
- 2D Ising model Hamiltonian mapped onto the foglet fractal lattice
- Replica-exchange Parallel Tempering with Metropolis-Hastings swap criterion
- Distributed across the 4-node Vanguard GPU cluster (192.168.86.x subnet)
- Grokking Run orchestrator with watchdog-managed BOINC/F@H GPU preemption
- Remote Polaroid energy landscape summaries for post-run analysis

#### First Distributed Grokking Run (Verified)

| Replica | Node | GPU | Beta | Energy | \|m\| |
|---------|------|-----|------|--------|-------|
| 0 | Mega (192.168.86.29) | RTX 5090 | 0.1000 | -192.0 | 0.066 |
| 1 | AMDMSIX870E-1 (192.168.86.16) | RTX 5090 | 0.2924 | -764.0 | 0.001 |
| 2 | AMDMSIX870E-2 (192.168.86.22) | RTX 5090 | 0.8550 | -2024.0 | 0.999 |
| 3 | DellUltracore9 (192.168.86.3) | RTX 4090 | 2.5000 | -2048.0 | 1.000 |

- **Ground State Reached**: E = -2048.00, |m| = 1.0 (perfect ferromagnetic ordering)
- **Heat Capacity**: 555.25 (strong fluctuations near critical temperature)
- **Swap Acceptance**: 2.7% (4/150 proposals)
- **Test Suite**: 22/22 passing (`tests/test_ising_tempering.py`)

```bash
# Run a Grokking Run
python scripts/grokking_run.py --lattice 32 --exchanges 50 --sweeps 50 --seed 42
```

## 🏗️ Architecture

```
UtilityFog-Fractal-TreeOpen
├── Phase 3 Integration Layer
│   ├── Feature Flags (centralized configuration)
│   ├── Telemetry System (metrics & performance)
│   ├── Visualization (CLI charts & exports)
│   └── Observability (logging & tracing)
├── Vanguard GPU Cluster (192.168.86.x)
│   ├── Ising Physics (2D lattice, Metropolis sweeps)
│   ├── Parallel Tempering (replica-exchange Monte Carlo)
│   ├── GPU Router (per-node dispatch, RTX 5090/4090)
│   ├── Watchdog (BOINC/F@H preemption, resource policy)
│   └── Grokking Run Orchestrator (scripts/grokking_run.py)
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
from utilityfog.telemetry import TelemetryCollector

# Initialize telemetry
telemetry = TelemetryCollector()

# Record metrics
telemetry.record_metric("simulation_step", 1.23, {"phase": "evolution"})
telemetry.record_performance("network_update", 0.045)

# Export data
telemetry.export_json("simulation_metrics.json")
```

### CLI Visualization

```bash
# Generate real-time charts
python -m utilityfog.viz --type line --data metrics.json --real-time

# Create heatmap visualization
python -m utilityfog.viz --type heatmap --data network_topology.json

# Export chart as image
python -m utilityfog.viz --type scatter --data agents.json --export chart.png
```

### Observability Integration

```python
from utilityfog.observability import get_logger, trace_operation

logger = get_logger(__name__)

@trace_operation("simulation_step")
def run_simulation_step():
    logger.info("Starting simulation step", extra={"step_id": 123})
    # Simulation logic here
    logger.info("Completed simulation step", extra={"duration_ms": 45.2})
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make coverage

# Run specific test categories
make test-unit        # Unit tests only
make test-integration # Integration tests only
make test-performance # Performance benchmarks
```

### Test Categories

- **Unit Tests**: Individual component testing
- **Integration Tests**: Cross-component interaction testing
- **Performance Tests**: Benchmarking and performance regression detection
- **Property Tests**: Property-based testing for mathematical invariants

## 📈 Performance Monitoring

### Benchmarking

```bash
# Run performance benchmarks
make bench

# Generate performance report
make bench-report

# Compare with baseline
make bench-compare
```

### Key Metrics

- **Simulation Speed**: Steps per second
- **Memory Usage**: Peak and average memory consumption
- **Network Efficiency**: Message passing overhead
- **Visualization Performance**: Frame rate and rendering time

## 🔧 Development

### Setup Development Environment

```bash
# Install development dependencies
make dev-setup

# Install pre-commit hooks
pre-commit install

# Run development server (if applicable)
make dev-server
```

### Code Quality Tools

- **Ruff**: Fast Python linter and formatter
- **MyPy**: Static type checking
- **Pytest**: Testing framework with coverage
- **Pre-commit**: Git hooks for code quality

### Contributing Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run quality checks (`make check-all`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📚 Documentation

### API Documentation

- [Core API Reference](docs/api/core.md)
- [Telemetry API](docs/api/telemetry.md)
- [Visualization API](docs/api/visualization.md)
- [Observability API](docs/api/observability.md)

### Guides

- [Getting Started Guide](docs/guides/getting-started.md)
- [Configuration Guide](docs/guides/configuration.md)
- [Performance Tuning](docs/guides/performance.md)
- [Troubleshooting](docs/guides/troubleshooting.md)

## 🚀 Deployment

### Production Deployment

```bash
# Build production package
make build

# Run production checks
make prod-check

# Deploy (configure your deployment method)
make deploy
```

### Docker Support

```bash
# Build Docker image
docker build -t utilityfog-fractal-tree .

# Run in container
docker run -it utilityfog-fractal-tree
```

## 📊 Project Status

### Phase 3 Completion Status

- ✅ **FT-008**: Telemetry System (Complete)
- ✅ **FT-009**: CLI Visualization (Complete)
- ✅ **FT-010**: Observability (Complete)
- ✅ **Integration Testing** (Complete)
- ✅ **Documentation** (Complete)
- ✅ **Performance Optimization** (Complete)

### Metrics

- **Test Coverage**: ≥90%
- **Performance**: Meets all benchmarks
- **Code Quality**: All quality gates passed
- **Documentation**: Comprehensive API and user guides

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Contributors

- [@Goldislops](https://github.com/Goldislops) - Project Lead & Core Developer

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Unity Technologies for the foundational fractal tree algorithms
- The open-source community for inspiration and tools
- Contributors and testers who helped shape this project

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/discussions)
- **Email**: kevin.brims@gmail.com

---

**UtilityFog-Fractal-TreeOpen** - Advanced simulation system with comprehensive observability and visualization capabilities.
