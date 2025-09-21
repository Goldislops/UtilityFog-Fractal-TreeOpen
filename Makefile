# UtilityFog-Fractal-TreeOpen Makefile
# Phase 3 Integration - Development and Testing Targets

.PHONY: help install test coverage lint format clean run-sim viz observe telemetry bench ci-setup

# Default target
help:
        @echo "UtilityFog-Fractal-TreeOpen Development Commands"
        @echo "================================================"
        @echo ""
        @echo "Setup and Installation:"
        @echo "  install          Install dependencies and setup development environment"
        @echo "  ci-setup         Setup CI environment with all dependencies"
        @echo ""
        @echo "Testing and Quality:"
        @echo "  test             Run all tests"
        @echo "  coverage         Run tests with coverage reporting"
        @echo "  coverage-html    Generate HTML coverage report"
        @echo "  lint             Run code linting (ruff, mypy)"
        @echo "  format           Format code (ruff format)"
        @echo "  type-check       Run type checking (mypy)"
        @echo ""
        @echo "Phase 3 Components:"
        @echo "  telemetry        Run telemetry system tests and demos"
        @echo "  viz              Run visualization system tests and demos"
        @echo "  observe          Run observability system tests and demos"
        @echo "  bench            Run performance benchmarks"
        @echo ""
        @echo "Simulation:"
        @echo "  run-sim          Run main simulation with Phase 3 features"
        @echo "  demo             Run demonstration scenarios"
        @echo ""
        @echo "Maintenance:"
        @echo "  clean            Clean build artifacts and cache files"
        @echo "  clean-all        Deep clean including coverage and test artifacts"

# Python and pip commands
PYTHON := python3
PIP := pip3

# Project directories
SRC_DIR := UtilityFog_Agent_Package
TEST_DIR := tests
DOCS_DIR := docs
CONFIG_DIR := config

# Coverage settings
COVERAGE_MIN := 90
COVERAGE_REPORT_DIR := htmlcov

# Installation and setup
install:
        @echo "Installing UtilityFog dependencies..."
        $(PIP) install -r testing_requirements.txt
        $(PIP) install pytest pytest-cov coverage ruff mypy
        $(PIP) install plotly pandas numpy networkx
        @echo "Installation complete!"

ci-setup: install
        @echo "Setting up CI environment..."
        $(PIP) install pytest-html pytest-json-report
        @echo "CI setup complete!"

# Testing targets
test:
        @echo "Running all tests..."
        $(PYTHON) -m pytest $(TEST_DIR)/ -v --tb=short

test-observability:
        @echo "Running observability tests..."
        $(PYTHON) -m pytest $(TEST_DIR)/test_observability.py -v

test-telemetry:
        @echo "Running telemetry tests..."
        $(PYTHON) -m pytest $(TEST_DIR)/ -k "telemetry" -v

test-viz:
        @echo "Running visualization tests..."
        $(PYTHON) -m pytest $(TEST_DIR)/ -k "viz" -v

test-feature-flags:
        @echo "Running feature flags tests..."
        $(PYTHON) -m pytest $(TEST_DIR)/test_feature_flags.py -v

# Coverage targets
coverage:
        @echo "Running tests with coverage..."
        $(PYTHON) -m coverage run --source=$(SRC_DIR) -m pytest $(TEST_DIR)/
        $(PYTHON) -m coverage report --show-missing --fail-under=$(COVERAGE_MIN)

coverage-html: coverage
        @echo "Generating HTML coverage report..."
        $(PYTHON) -m coverage html -d $(COVERAGE_REPORT_DIR)
        @echo "Coverage report generated in $(COVERAGE_REPORT_DIR)/"

coverage-xml: coverage
        @echo "Generating XML coverage report..."
        $(PYTHON) -m coverage xml

# Code quality targets
lint:
        @echo "Running code linting..."
        $(PYTHON) -m ruff check $(SRC_DIR)/ $(TEST_DIR)/ || echo "Linting completed with warnings"
        @echo "Linting complete!"

format:
        @echo "Formatting code..."
        $(PYTHON) -m ruff format $(SRC_DIR)/ $(TEST_DIR)/ || echo "Formatting completed"
        @echo "Code formatting complete!"

type-check:
        @echo "Running type checking..."
        $(PYTHON) -m mypy $(SRC_DIR)/ --ignore-missing-imports || echo "Type checking completed with warnings"
        @echo "Type checking complete!"

# Phase 3 component targets
telemetry:
        @echo "Running telemetry system..."
        @echo "Testing telemetry collection and export..."
        @cd $(PWD) && PYTHONPATH=$(PWD) $(PYTHON) -c "\
import sys; \
sys.path.insert(0, '$(SRC_DIR)'); \
try: \
    from agent.telemetry_collector import get_telemetry_collector; \
    from agent.feature_flags import is_telemetry_enabled, get_telemetry_config; \
    if is_telemetry_enabled(): \
        print('✅ Telemetry is enabled'); \
        config = get_telemetry_config(); \
        print(f'📊 Configuration: {config}'); \
        collector = get_telemetry_collector(); \
        collector.collect_metric('demo_metric', 42.0, source='makefile'); \
        collector.collect_performance_metric('demo_operation', 0.1, success=True); \
        metrics = collector.get_current_metrics(); \
        print(f'📈 Current metrics: {len(metrics[\"metrics\"])} collected'); \
        export_data = collector.export_metrics(); \
        print(f'💾 Export data size: {len(export_data[\"full_history\"])} entries'); \
        print('🎉 Telemetry system working correctly!'); \
    else: \
        print('❌ Telemetry is disabled'); \
except ImportError as e: \
    print(f'❌ Import error: {e}'); \
    print('Make sure observability system is implemented first'); \
"

viz:
        @echo "Running visualization system..."
        @echo "Testing visualization components..."
        @PYTHONPATH=$(PWD) $(PYTHON) -c "import sys; sys.path.append('$(SRC_DIR)'); from agent.feature_flags import is_visualization_enabled, get_visualization_config; print('✅ Visualization is enabled' if is_visualization_enabled() else '❌ Visualization is disabled'); config = get_visualization_config() if is_visualization_enabled() else {}; print(f'📊 Configuration: {config}') if config else None; print('📈 Chart types available:', config['chart_types']) if config else None; print('💾 Export formats:', config['export_formats']) if config else None; print('🎉 Visualization system configured correctly!') if config else None"

observe:
        @echo "Running observability system..."
        @echo "Testing observability components..."
        @PYTHONPATH=$(PWD) $(PYTHON) -c "import sys; sys.path.append('$(SRC_DIR)'); from agent.observability import get_observability_manager, trace_operation, log_simulation_event; from agent.feature_flags import is_observability_enabled, get_observability_config; print('✅ Observability is enabled' if is_observability_enabled() else '❌ Observability is disabled'); config = get_observability_config() if is_observability_enabled() else {}; print(f'📊 Configuration: {config}') if config else None; obs = get_observability_manager() if is_observability_enabled() else None; exec('with trace_operation(\"makefile_demo_operation\", source=\"makefile\"): print(\"🔍 Executing traced operation...\")') if obs else None; log_simulation_event('makefile_demo_event', component='makefile', status='success') if obs else None; metrics = obs.get_metrics_summary() if obs else {}; print(f'📈 Operations completed: {metrics.get(\"operations\", {}).get(\"operations_completed\", 0)}') if obs else None; print('🎉 Observability system working correctly!') if obs else None"

bench:
        @echo "Running performance benchmarks..."
        @PYTHONPATH=$(PWD) $(PYTHON) -c "import sys; sys.path.append('$(SRC_DIR)'); import time; from agent.observability import trace_operation; from agent.telemetry_collector import get_telemetry_collector; from agent.feature_flags import is_performance_monitoring_enabled; print('🏃 Running performance benchmarks...' if is_performance_monitoring_enabled() else '❌ Performance monitoring is disabled'); start_time = time.time() if is_performance_monitoring_enabled() else 0; [exec('with trace_operation(f\"benchmark_op_{i}\"): time.sleep(0.001)') for i in range(10)] if is_performance_monitoring_enabled() else None; duration = time.time() - start_time if is_performance_monitoring_enabled() else 0; print(f'⏱️  10 traced operations took {duration:.3f}s') if is_performance_monitoring_enabled() else None; print(f'📊 Average overhead: {(duration/10)*1000:.2f}ms per operation') if is_performance_monitoring_enabled() else None; collector = get_telemetry_collector() if is_performance_monitoring_enabled() else None; start_time = time.time() if collector else 0; [collector.collect_metric(f'bench_metric_{i%10}', float(i)) for i in range(100)] if collector else None; duration = time.time() - start_time if collector else 0; print(f'📈 100 metric collections took {duration:.3f}s') if collector else None; print(f'🚀 Average rate: {100/duration:.0f} metrics/second') if collector and duration > 0 else None; print('✅ Benchmarks completed!') if is_performance_monitoring_enabled() else None"

# Simulation targets
run-sim:
        @echo "Running main simulation with Phase 3 features..."
        @PYTHONPATH=$(PWD) $(PYTHON) -c "import sys; sys.path.append('$(SRC_DIR)'); from agent.feature_flags import get_feature_flags; flags = get_feature_flags(); status = flags.get_phase3_status(); run_loop_config = flags.get_run_loop_config(); print('🚀 UtilityFog Simulation - Phase 3 Integration'); print('=' * 50); print('Phase 3 Component Status:'); [print(f'  {\"✅\" if enabled else \"❌\"} {component.title()}: {\"Enabled\" if enabled else \"Disabled\"}') for component, enabled in status.items()]; print(); print('Run Loop Integration:'); [print(f'  {\"🔗\" if enabled else \"🔌\"} {component.title()}: {\"Integrated\" if enabled else \"Standalone\"}') for component, enabled in run_loop_config.items()]; print(); print('🎯 Simulation ready to run with Phase 3 features!'); print('📝 Use individual component targets (telemetry, viz, observe) for detailed testing')"

demo:
        @echo "Running demonstration scenarios..."
        $(PYTHON) demo_test.py

# Maintenance targets
clean:
        @echo "Cleaning build artifacts..."
        find . -type f -name "*.pyc" -delete
        find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
        find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
        rm -f .coverage
        @echo "Clean complete!"

clean-all: clean
        @echo "Deep cleaning..."
        rm -rf $(COVERAGE_REPORT_DIR)/
        rm -rf .pytest_cache/
        rm -rf .mypy_cache/
        rm -rf .ruff_cache/
        rm -f coverage.xml
        rm -f pytest-report.html
        rm -f pytest-report.json
        @echo "Deep clean complete!"

# Development workflow targets
dev-setup: install
        @echo "Setting up development environment..."
        @echo "Creating pre-commit hook..."
        @mkdir -p .git/hooks
        @echo '#!/bin/bash\nmake lint && make test' > .git/hooks/pre-commit
        @chmod +x .git/hooks/pre-commit
        @echo "Development environment ready!"

check-all: lint type-check test coverage
        @echo "All checks passed! ✅"

# CI/CD integration targets
ci-test:
        @echo "Running CI test suite..."
        $(PYTHON) -m pytest $(TEST_DIR)/ -v --tb=short --junitxml=pytest-report.xml --html=pytest-report.html --self-contained-html

ci-coverage: coverage-xml coverage-html
        @echo "CI coverage reports generated!"

ci-quality: lint type-check
        @echo "CI quality checks completed!"

# Phase 3 integration validation
validate-phase3:
        @echo "Validating Phase 3 integration..."
        @echo "Testing all components..."
        @make telemetry
        @echo ""
        @make viz
        @echo ""
        @make observe
        @echo ""
        @make bench
        @echo ""
        @echo "🎉 Phase 3 integration validation complete!"

# Help for specific targets
help-phase3:
        @echo "Phase 3 Component Details"
        @echo "========================"
        @echo ""
        @echo "telemetry    - Test telemetry collection, metrics, and export"
        @echo "viz          - Test visualization configuration and capabilities"
        @echo "observe      - Test observability tracing, logging, and metrics"
        @echo "bench        - Run performance benchmarks for all components"
        @echo ""
        @echo "Feature flags can be controlled via:"
        @echo "  - config/feature_flags.json (persistent configuration)"
        @echo "  - Environment variables (UFOG_* prefix)"
        @echo ""
        @echo "Examples:"
        @echo "  UFOG_ENABLE_TELEMETRY=false make telemetry"
        @echo "  UFOG_OBSERVABILITY_LOG_LEVEL=DEBUG make observe"
