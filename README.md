
# UtilityFog-Fractal-TreeOpen

<!-- Status Badges -->
[![Tests](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/ci.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/codeql.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/codeql.yml)
[![Release Smoke](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/release-smoke.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/release-smoke.yml)
[![Nightly Benchmarks](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/nightly-bench.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/nightly-bench.yml)
[![OSSF Scorecard](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/scorecard.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/scorecard.yml)
[![Documentation](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/docs-deploy.yml/badge.svg)](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/docs-deploy.yml)

<!-- Project Badges -->
[![Python 3.9+](https://upload.wikimedia.org/wikipedia/commons/thumb/1/1b/Blue_Python_3.9_Shield_Badge.svg/1280px-Blue_Python_3.9_Shield_Badge.svg.png)
[![License](https://i.ytimg.com/vi/4cgpu9L2AE8/maxresdefault.jpg)
[![Latest Release](https://i.ytimg.com/vi/acIwQO1eOtw/sddefault.jpg)
[![SBOM](https://scribesecurity.com/wp-content/uploads/2022/01/sbom-components-scribe-security-1024x602.webp)

<!-- Security & Quality Badges -->
[![OpenSSF Scorecard](https://lh7-us.googleusercontent.com/cXEJ6b5vKmme8Paj7UuLaLucbskRDKDXOhkY7PwCjTDqD1rQK-is0FSs1AlWPGKKYfqC6IET-GLr_IeU7poBDs_lQi7pMahp-BJ_bHZCb5j-AOBXENFOJdLkse9AIAEP1NwyEzC8qGx_Ez77qUOKL-A)
[![Supply Chain Security](https://upload.wikimedia.org/wikipedia/commons/thumb/6/67/SD_Cards.svg/794px-SD_Cards.svg.png)

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

## 🛡️ Security & Supply Chain

This project implements comprehensive security measures:

- **CodeQL Security Analysis**: Automated vulnerability scanning
- **OSSF Scorecard**: Supply chain security assessment
- **SBOM Generation**: Software Bill of Materials with attestations
- **Dependency Updates**: Automated via Dependabot
- **Branch Protection**: Enforced code review and status checks

## 📚 Documentation

- **[Quick Start Guide](docs/quickstart.md)** - Get up and running quickly
- **[Telemetry Documentation](docs/TELEMETRY.md)** - Metrics and monitoring
- **[Visualization Guide](docs/VISUALIZATION.md)** - CLI visualization tools
- **[Observability](docs/OBSERVABILITY.md)** - Logging and tracing
- **[API Documentation](https://goldislops.github.io/UtilityFog-Fractal-TreeOpen/)** - Full API reference

## 🚀 Quick Start

```bash
# Install from PyPI (when available)
pip install utilityfog-fractal-tree

# Or install from source
git clone https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen.git
cd UtilityFog-Fractal-TreeOpen
pip install -e .

# Run diagnostics
ufog-diagnose --json --fail-on-warn
```

## 🧪 Development

```bash
# Install development dependencies
pip install -r testing_requirements.txt

# Run tests
python -m pytest

# Run benchmarks
python -m pytest test_benchmarks.py --benchmark-only

# Generate documentation
make docs
```

## 📊 Performance

Nightly benchmarks track performance across key operations:
- Tree node creation and manipulation
- Message processing throughput
- Visualization data preparation
- Memory usage patterns

View latest benchmark results in [GitHub Actions](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/actions/workflows/nightly-bench.yml).

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

All contributions are subject to:
- Code review requirements
- Automated testing and quality checks
- Security scanning and compliance
- Documentation updates

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- **Documentation**: https://goldislops.github.io/UtilityFog-Fractal-TreeOpen/
- **Issues**: https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues
- **Discussions**: https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/discussions
- **Security**: [SECURITY.md](SECURITY.md)

---

**Built with ❤️ for the UtilityFog community**
