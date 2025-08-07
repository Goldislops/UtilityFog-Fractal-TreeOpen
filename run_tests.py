#!/usr/bin/env python3
"""
Main Test Script for UtilityFog-Fractal-TreeOpen Simulation

This script provides easy access to run the testing framework with various
configurations for validating the agent-based simulation system.
"""

import os
import sys
import argparse
from typing import List

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from testing_framework import TestRunner, TestConfiguration


def main():
    """Main entry point for running tests."""
    parser = argparse.ArgumentParser(
        description="Run UtilityFog-Fractal-TreeOpen simulation tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py --quick                    # Run a single quick test
  python run_tests.py --standard                 # Run the standard test suite
  python run_tests.py --custom --agents 15       # Run custom test with 15 agents
  python run_tests.py --batch                    # Run full test batch
  python run_tests.py --no-quantum               # Run without quantum myelin
        """
    )
    
    # Test type options
    test_group = parser.add_mutually_exclusive_group()
    test_group.add_argument('--quick', action='store_true',
                           help='Run a single quick test (5 agents, 2 generations)')
    test_group.add_argument('--standard', action='store_true',
                           help='Run the standard test (10 agents, 3 generations)')
    test_group.add_argument('--batch', action='store_true',
                           help='Run the full test suite with multiple configurations')
    test_group.add_argument('--custom', action='store_true',
                           help='Run a custom test with specified parameters')
    
    # Custom test parameters
    parser.add_argument('--agents', type=int, default=10,
                       help='Number of agents for custom test (default: 10)')
    parser.add_argument('--generations', type=int, default=3,
                       help='Number of generations for custom test (default: 3)')
    parser.add_argument('--steps', type=int, default=50,
                       help='Number of simulation steps (default: 50)')
    parser.add_argument('--mutation-rate', type=float, default=0.1,
                       help='Mutation rate (default: 0.1)')
    parser.add_argument('--no-quantum', action='store_true',
                       help='Disable quantum myelin interactions')
    parser.add_argument('--name', type=str, default='custom_test',
                       help='Test name for custom test (default: custom_test)')
    
    # Output options
    parser.add_argument('--output-dir', type=str, default='test_results',
                       help='Output directory for results (default: test_results)')
    parser.add_argument('--export-csv', action='store_true',
                       help='Export results to CSV format')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    
    args = parser.parse_args()
    
    # Print banner
    print("🔬 UtilityFog-Fractal-TreeOpen Testing Framework")
    print("=" * 50)
    
    # Initialize test runner
    test_runner = TestRunner(base_output_dir=args.output_dir)
    
    try:
        if args.quick:
            # Quick test
            config = TestConfiguration(
                test_name="quick_test",
                num_agents=5,
                num_generations=2,
                simulation_steps=25,
                enable_quantum_myelin=not args.no_quantum
            )
            print("\n🚀 Running quick test...")
            result = test_runner.run_single_test(config)
            results = [result]
            
        elif args.standard:
            # Standard test
            config = test_runner.create_default_test_config("standard_test")
            config.enable_quantum_myelin = not args.no_quantum
            print("\n🚀 Running standard test...")
            result = test_runner.run_single_test(config)
            results = [result]
            
        elif args.custom:
            # Custom test
            config = TestConfiguration(
                test_name=args.name,
                num_agents=args.agents,
                num_generations=args.generations,
                simulation_steps=args.steps,
                mutation_rate=args.mutation_rate,
                enable_quantum_myelin=not args.no_quantum
            )
            print(f"\n🚀 Running custom test: {args.name}")
            print(f"   Parameters: {args.agents} agents, {args.generations} generations, {args.steps} steps")
            result = test_runner.run_single_test(config)
            results = [result]
            
        elif args.batch:
            # Full test suite
            configs = test_runner.create_test_suite()
            if args.no_quantum:
                for config in configs:
                    config.enable_quantum_myelin = False
            print(f"\n🚀 Running test batch with {len(configs)} configurations...")
            results = test_runner.run_test_batch(configs)
            
        else:
            # Default: run standard test
            print("\n🚀 Running default standard test (use --help for more options)...")
            config = test_runner.create_default_test_config("default_test")
            config.enable_quantum_myelin = not args.no_quantum
            result = test_runner.run_single_test(config)
            results = [result]
        
        # Print summary
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50)
        
        stats = test_runner.get_summary_statistics()
        print(f"Total tests run: {stats['total_tests']}")
        print(f"Successful: {stats['successful_tests']}")
        print(f"Failed: {stats['failed_tests']}")
        print(f"Success rate: {stats['success_rate']:.1f}%")
        print(f"Average duration: {stats['average_duration']:.2f}s")
        print(f"Total quantum myelin events: {stats['total_quantum_myelin_events']}")
        
        # Show individual test results
        for result in results:
            if result.success:
                print(f"\n✅ {result.test_name}")
                print(f"   Duration: {result.duration:.2f}s")
                print(f"   Agents: {result.agent_metrics.get('total_agents', 'N/A')}")
                print(f"   Entanglements: {result.quantum_myelin_metrics.get('total_entanglements', 0)}")
                print(f"   Avg Energy: {result.agent_metrics.get('average_energy', 0):.3f}")
            else:
                print(f"\n❌ {result.test_name}")
                print(f"   Error: {result.error_message}")
        
        # Export to CSV if requested
        if args.export_csv:
            csv_filename = f"test_results_{len(results)}_tests.csv"
            test_runner.reporter.export_results_to_csv(results, csv_filename)
        
        print(f"\n📁 Detailed results saved in: {args.output_dir}")
        print("🎯 Testing completed successfully!")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Testing interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n❌ Testing failed with error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())