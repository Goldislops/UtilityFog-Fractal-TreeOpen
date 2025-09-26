
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
