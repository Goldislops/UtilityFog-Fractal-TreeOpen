"""
Main Test Runner for UtilityFog-Fractal-TreeOpen Simulation Testing

This module coordinates test execution, data collection, and reporting
for the agent-based simulation system.
"""

import time
import json
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from .simulation_runner import SimulationRunner
from .loggers import QuantumMyelinLogger, SimulationLogger
from .reporters import TestReporter
from .validators import SimulationValidator


@dataclass
class TestConfiguration:
    """Configuration for a single test run."""
    test_name: str
    num_agents: int = 10
    num_generations: int = 3
    simulation_steps: int = 100
    mutation_rate: float = 0.1
    crossover_rate: float = 0.8
    enable_quantum_myelin: bool = True
    network_depth: int = 3
    branching_factor: int = 3
    initial_memes_per_agent: int = 2
    log_level: str = "INFO"
    output_dir: str = "test_results"
    custom_parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Results from a single test run."""
    test_name: str
    timestamp: str
    duration: float
    success: bool
    final_generation: int
    agent_metrics: Dict[str, Any]
    meme_metrics: Dict[str, Any]
    network_metrics: Dict[str, Any]
    quantum_myelin_metrics: Dict[str, Any]
    evolution_metrics: Dict[str, Any]
    error_message: Optional[str] = None
    logs: List[Dict[str, Any]] = field(default_factory=list)


class TestRunner:
    """Main test orchestrator for the UtilityFog simulation system."""
    
    def __init__(self, base_output_dir: str = "test_results"):
        """
        Initialize the test runner.
        
        Args:
            base_output_dir: Base directory for test outputs
        """
        self.base_output_dir = base_output_dir
        self.test_results: List[TestResult] = []
        
        # Ensure output directory exists
        os.makedirs(base_output_dir, exist_ok=True)
        
        # Initialize components
        self.quantum_logger = QuantumMyelinLogger()
        self.simulation_logger = SimulationLogger()
        self.reporter = TestReporter(base_output_dir)
        self.validator = SimulationValidator()
        
        print(f"🧪 TestRunner initialized with output directory: {base_output_dir}")
    
    def run_single_test(self, config: TestConfiguration) -> TestResult:
        """
        Run a single test with the given configuration.
        
        Args:
            config: Test configuration
            
        Returns:
            Test result with metrics and logs
        """
        print(f"\n🚀 Starting test: {config.test_name}")
        print(f"   Agents: {config.num_agents}, Generations: {config.num_generations}")
        
        start_time = time.time()
        timestamp = datetime.now().isoformat()
        
        # Create test-specific output directory
        test_output_dir = os.path.join(self.base_output_dir, config.test_name, timestamp.replace(":", "-"))
        os.makedirs(test_output_dir, exist_ok=True)
        
        try:
            # Initialize simulation runner
            simulation_runner = SimulationRunner(
                config=config,
                quantum_logger=self.quantum_logger,
                simulation_logger=self.simulation_logger,
                output_dir=test_output_dir
            )
            
            # Run the simulation
            simulation_results = simulation_runner.run_simulation()
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Create test result
            result = TestResult(
                test_name=config.test_name,
                timestamp=timestamp,
                duration=duration,
                success=True,
                final_generation=simulation_results.get("final_generation", 0),
                agent_metrics=simulation_results.get("agent_metrics", {}),
                meme_metrics=simulation_results.get("meme_metrics", {}),
                network_metrics=simulation_results.get("network_metrics", {}),
                quantum_myelin_metrics=simulation_results.get("quantum_myelin_metrics", {}),
                evolution_metrics=simulation_results.get("evolution_metrics", {}),
                logs=simulation_runner.get_all_logs()
            )
            
            # Validate results
            validation_results = self.validator.validate_results(result)
            result.agent_metrics["validation"] = validation_results
            
            print(f"✅ Test completed successfully in {duration:.2f}s")
            print(f"   Final generation: {result.final_generation}")
            print(f"   Quantum myelin events: {result.quantum_myelin_metrics.get('total_entanglements', 0)}")
            
        except Exception as e:
            duration = time.time() - start_time
            result = TestResult(
                test_name=config.test_name,
                timestamp=timestamp,
                duration=duration,
                success=False,
                final_generation=0,
                agent_metrics={},
                meme_metrics={},
                network_metrics={},
                quantum_myelin_metrics={},
                evolution_metrics={},
                error_message=str(e)
            )
            print(f"❌ Test failed after {duration:.2f}s: {e}")
        
        # Save individual test result
        self.reporter.save_test_result(result, test_output_dir)
        self.test_results.append(result)
        
        return result
    
    def run_test_batch(self, configs: List[TestConfiguration]) -> List[TestResult]:
        """
        Run a batch of tests with different configurations.
        
        Args:
            configs: List of test configurations
            
        Returns:
            List of test results
        """
        print(f"\n📊 Starting test batch with {len(configs)} configurations")
        
        batch_start_time = time.time()
        batch_results = []
        
        for i, config in enumerate(configs, 1):
            print(f"\n--- Test {i}/{len(configs)} ---")
            result = self.run_single_test(config)
            batch_results.append(result)
            
            # Brief pause between tests
            time.sleep(1)
        
        batch_duration = time.time() - batch_start_time
        
        # Generate batch report
        self.reporter.generate_batch_report(batch_results, batch_duration)
        
        print(f"\n🎯 Batch completed in {batch_duration:.2f}s")
        print(f"   Successful tests: {sum(1 for r in batch_results if r.success)}/{len(batch_results)}")
        
        return batch_results
    
    def create_default_test_config(self, test_name: str = "default_test") -> TestConfiguration:
        """Create a default test configuration for quick testing."""
        return TestConfiguration(
            test_name=test_name,
            num_agents=10,
            num_generations=3,
            simulation_steps=50,
            mutation_rate=0.1,
            crossover_rate=0.8,
            enable_quantum_myelin=True,
            network_depth=2,
            branching_factor=3,
            initial_memes_per_agent=2
        )
    
    def create_test_suite(self) -> List[TestConfiguration]:
        """Create a comprehensive test suite with various configurations."""
        return [
            # Basic functionality test
            TestConfiguration(
                test_name="basic_functionality",
                num_agents=5,
                num_generations=2,
                simulation_steps=25
            ),
            
            # Standard test as specified by user
            TestConfiguration(
                test_name="standard_test",
                num_agents=10,
                num_generations=3,
                simulation_steps=50
            ),
            
            # High mutation rate test
            TestConfiguration(
                test_name="high_mutation",
                num_agents=10,
                num_generations=3,
                simulation_steps=50,
                mutation_rate=0.3
            ),
            
            # Quantum myelin disabled test
            TestConfiguration(
                test_name="no_quantum_myelin",
                num_agents=10,
                num_generations=3,
                simulation_steps=50,
                enable_quantum_myelin=False
            ),
            
            # Larger network test
            TestConfiguration(
                test_name="large_network",
                num_agents=15,
                num_generations=4,
                simulation_steps=75,
                network_depth=4,
                branching_factor=3
            )
        ]
    
    def get_summary_statistics(self) -> Dict[str, Any]:
        """Get summary statistics from all test results."""
        if not self.test_results:
            return {"message": "No test results available"}
        
        successful_tests = [r for r in self.test_results if r.success]
        failed_tests = [r for r in self.test_results if not r.success]
        
        total_quantum_events = sum(
            r.quantum_myelin_metrics.get("total_entanglements", 0) 
            for r in successful_tests
        )
        
        avg_duration = sum(r.duration for r in self.test_results) / len(self.test_results)
        
        return {
            "total_tests": len(self.test_results),
            "successful_tests": len(successful_tests),
            "failed_tests": len(failed_tests),
            "success_rate": len(successful_tests) / len(self.test_results) * 100,
            "average_duration": avg_duration,
            "total_quantum_myelin_events": total_quantum_events,
            "test_names": [r.test_name for r in self.test_results],
            "latest_test": self.test_results[-1].test_name if self.test_results else None
        }