
# UtilityFog-Fractal-TreeOpen

[![Tests](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/phase3-ci.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/phase3-ci.yml)
[![Coverage](https://files.readme.io/8192810-codecov_uploader.png)
[![Python 3.9+](https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/Blue_Python_3.9_Shield_Badge.svg/1280px-Blue_Python_3.9_Shield_Badge.svg.png)
[![License](https://i.ytimg.com/vi/4cgpu9L2AE8/maxresdefault.jpg)
[![Phase 3](https://upload.wikimedia.org/wikipedia/en/thumb/0/03/Flag_of_Italy.svg/330px-Flag_of_Italy.svg.png)

> **`UtilityFog-Fractal-TreeOpen` is both a simulation platform and a governed, model-agnostic agent orchestration / tuning framework around the Medusa engine.**
>
> The repository hosts two coupled surfaces:
>
> 1. **Cellular-automata simulation engine** (Medusa) — a 256³ voxel CA evolving on the Vanguard GPU cluster, currently running Phase 17a (Magnon Amplification). Substrate-independent design with Portable Genome Format, STL/QR/WASM export, and a transport-agnostic shard protocol for eventual 512³ multi-node distribution.
> 2. **Governed agent orchestration framework** built on top of the engine in Phase 18 — REST API for live observation + a write-side tuning bus with safety rails (propose / commit / rollback, schema-bound parameter categories, per-param rate limits), a ZMQ PUB event stream, a model-agnostic `AgentBackend` abstraction with concrete Anthropic / Mock backends, and an orchestrator loop that drives an LLM through observe → decide → act cycles.
>
> Treat them as one project with two surfaces, not two projects in a trenchcoat. Phase 18 was added because the simulation got mature enough to need autonomous tuning. The orchestration is in service of the matrix; the matrix is the substrate the orchestration governs.

## 📍 Where to Start

| If you are... | Read |
|---------------|------|
| ...a new contributor (human) | This README, then `AGENT_HANDOFF.md` |
| ...a new contributor (AI / agent) | `AGENT_HANDOFF.md` first — operational orientation |
| ...looking for the latest architectural decisions | `git log --oneline -20`, then `PHASE_17B.md` and `PHASE_18.md` |
| ...looking to drive the engine via REST | `scripts/medusa_api.py` (port 8080) and `scripts/nemoclaw_tools.json` |
| ...looking to subscribe to events | `scripts/event_bus.py` (ZMQ PUB on port 8081) |
| ...running the orchestrator | `scripts/orchestrator_config.py` + `MEDUSA_AGENT_BACKEND` env var |

## 🤖 Agent Orchestration Framework (Phase 18)

The orchestration framework was designed to be **model-agnostic**: the LLM brain on the other end is a one-line config swap, not a rewrite. Today's AnthropicBackend (Claude) is one concrete backend among several planned (Mock for tests; Nemotron via NVIDIA Cloud as a future drop-in once that account is provisioned).

```bash
# Read-only observation (always available once medusa_api.py is running):
curl http://localhost:8080/api/params/schema | jq .
curl http://localhost:8080/api/equanimity   | jq .

# Subscribe to push-worthy events:
python -c "
import zmq; ctx = zmq.Context(); s = ctx.socket(zmq.SUB)
s.connect('tcp://127.0.0.1:8081'); s.setsockopt_string(zmq.SUBSCRIBE, '')
while True: print(s.recv_multipart())
"

# Drive the agent loop one iteration (set ANTHROPIC_API_KEY first):
export MEDUSA_AGENT_BACKEND=anthropic
python -c "
from scripts.orchestrator_config import create_orchestrator
print(create_orchestrator().run_one_iteration('Observe Medusa; suggest one tuning if needed.'))
"
```

Safety contract (enforced at three layers — schema, router, API):

- **LOCKED** parameters (e.g. `structural_to_void_decay_prob`) cannot be changed via any commit path.
- **HUMAN_APPROVAL** parameters require an `approver` string starting with `human:` — the orchestrator never supplies one; it commits as `policy:auto`, which only succeeds for AUTO-category proposals.
- Per-parameter rate limit (1000 generations between successive commits to the same param).
- Every proposal requires a non-empty justification string.
- Append-only JSONL audit trail at `data/tuning_ledger.jsonl`.

See `PHASE_18.md` for the full design and the seven-PR roadmap that built it.

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
