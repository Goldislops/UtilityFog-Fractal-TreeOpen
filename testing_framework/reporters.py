"""
Test Result Reporters for UtilityFog Simulation Testing

This module provides comprehensive reporting capabilities for test results,
including formatted output, statistical analysis, and data export.
"""

import os
import json
import time
from typing import Dict, List, Any, Optional
from datetime import datetime
import statistics


class TestReporter:
    """Comprehensive test result reporter and analyzer."""
    
    def __init__(self, output_dir: str = "test_results"):
        """Initialize the test reporter."""
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def save_test_result(self, test_result, test_output_dir: str):
        """Save a single test result to files."""
        # Create result dictionary
        result_dict = {
            "test_name": test_result.test_name,
            "timestamp": test_result.timestamp,
            "duration": test_result.duration,
            "success": test_result.success,
            "final_generation": test_result.final_generation,
            "metrics": {
                "agent_metrics": test_result.agent_metrics,
                "meme_metrics": test_result.meme_metrics,
                "network_metrics": test_result.network_metrics,
                "quantum_myelin_metrics": test_result.quantum_myelin_metrics,
                "evolution_metrics": test_result.evolution_metrics
            },
            "error_message": test_result.error_message,
            "total_logs": len(test_result.logs)
        }
        
        # Save main result file
        result_file = os.path.join(test_output_dir, "test_result.json")
        with open(result_file, 'w') as f:
            json.dump(result_dict, f, indent=2)
        
        # Save detailed logs
        logs_file = os.path.join(test_output_dir, "detailed_logs.json")
        with open(logs_file, 'w') as f:
            json.dump(test_result.logs, f, indent=2)
        
        # Generate human-readable summary
        self._generate_human_readable_summary(test_result, test_output_dir)
        
        print(f"💾 Test result saved to: {test_output_dir}")
    
    def _generate_human_readable_summary(self, test_result, test_output_dir: str):
        """Generate a human-readable summary of the test result."""
        summary_file = os.path.join(test_output_dir, "summary.md")
        
        with open(summary_file, 'w') as f:
            f.write(f"# Test Result Summary: {test_result.test_name}\n\n")
            f.write(f"**Timestamp:** {test_result.timestamp}\n")
            f.write(f"**Duration:** {test_result.duration:.2f} seconds\n")
            f.write(f"**Success:** {'✅ Yes' if test_result.success else '❌ No'}\n")
            
            if test_result.error_message:
                f.write(f"**Error:** {test_result.error_message}\n")
            
            f.write(f"\n## Simulation Results\n\n")
            f.write(f"**Final Generation:** {test_result.final_generation}\n")
            
            # Agent Metrics
            if test_result.agent_metrics:
                agent_metrics = test_result.agent_metrics
                f.write(f"\n### Agent Metrics\n")
                f.write(f"- **Total Agents:** {agent_metrics.get('total_agents', 'N/A')}\n")
                f.write(f"- **Average Energy:** {agent_metrics.get('average_energy', 0):.3f}\n")
                f.write(f"- **Average Health:** {agent_metrics.get('average_health', 0):.3f}\n")
                f.write(f"- **Total Active Memes:** {agent_metrics.get('total_active_memes', 0)}\n")
            
            # Meme Metrics
            if test_result.meme_metrics:
                meme_metrics = test_result.meme_metrics
                f.write(f"\n### Meme Metrics\n")
                f.write(f"- **Total Memes:** {meme_metrics.get('total_memes', 0)}\n")
                f.write(f"- **Average Fitness:** {meme_metrics.get('average_fitness', 0):.3f}\n")
                f.write(f"- **Total Propagations:** {meme_metrics.get('total_propagations', 0)}\n")
                
                if 'meme_types_distribution' in meme_metrics:
                    f.write(f"\n**Meme Type Distribution:**\n")
                    for meme_type, count in meme_metrics['meme_types_distribution'].items():
                        f.write(f"- {meme_type}: {count}\n")
            
            # Quantum Myelin Metrics
            if test_result.quantum_myelin_metrics:
                quantum_metrics = test_result.quantum_myelin_metrics
                f.write(f"\n### Quantum Myelin Metrics\n")
                f.write(f"- **Total Entanglements:** {quantum_metrics.get('total_entanglements', 0)}\n")
                f.write(f"- **Total Infections:** {quantum_metrics.get('total_infections', 0)}\n")
                f.write(f"- **Total Propagations:** {quantum_metrics.get('total_propagations', 0)}\n")
                f.write(f"- **Average Entanglement Strength:** {quantum_metrics.get('average_entanglement_strength', 0):.3f}\n")
                
                if 'most_entangled_agents' in quantum_metrics and quantum_metrics['most_entangled_agents']:
                    f.write(f"\n**Most Entangled Agents:**\n")
                    for agent_id, count in list(quantum_metrics['most_entangled_agents'].items())[:3]:
                        f.write(f"- {agent_id}: {count} entanglements\n")
            
            # Network Metrics
            if test_result.network_metrics:
                network_metrics = test_result.network_metrics
                f.write(f"\n### Network Metrics\n")
                f.write(f"- **Total Nodes:** {network_metrics.get('total_nodes', 0)}\n")
                f.write(f"- **Total Connections:** {network_metrics.get('total_connections', 0)}\n")
                f.write(f"- **Max Depth:** {network_metrics.get('max_depth', 0)}\n")
                f.write(f"- **Branching Factor:** {network_metrics.get('branching_factor', 0)}\n")
            
            f.write(f"\n## Logs Summary\n")
            f.write(f"**Total Log Entries:** {len(test_result.logs)}\n")
            
            # Count logs by level
            log_levels = {}
            for log in test_result.logs:
                level = log.get('level', 'UNKNOWN')
                log_levels[level] = log_levels.get(level, 0) + 1
            
            for level, count in log_levels.items():
                f.write(f"- **{level}:** {count}\n")
    
    def generate_batch_report(self, test_results: List, batch_duration: float):
        """Generate a comprehensive batch report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_report_dir = os.path.join(self.output_dir, f"batch_report_{timestamp}")
        os.makedirs(batch_report_dir, exist_ok=True)
        
        # Generate statistical analysis
        self._generate_batch_statistics(test_results, batch_report_dir, batch_duration)
        
        # Generate comparison matrix
        self._generate_comparison_matrix(test_results, batch_report_dir)
        
        # Generate performance trends
        self._generate_performance_trends(test_results, batch_report_dir)
        
        print(f"📊 Batch report generated: {batch_report_dir}")
    
    def _generate_batch_statistics(self, test_results: List, output_dir: str, batch_duration: float):
        """Generate statistical analysis of the test batch."""
        stats_file = os.path.join(output_dir, "batch_statistics.md")
        
        successful_tests = [r for r in test_results if r.success]
        failed_tests = [r for r in test_results if not r.success]
        
        with open(stats_file, 'w') as f:
            f.write(f"# Batch Test Statistics\n\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n")
            f.write(f"**Total Tests:** {len(test_results)}\n")
            f.write(f"**Successful:** {len(successful_tests)}\n")
            f.write(f"**Failed:** {len(failed_tests)}\n")
            f.write(f"**Success Rate:** {len(successful_tests) / len(test_results) * 100:.1f}%\n")
            f.write(f"**Total Batch Duration:** {batch_duration:.2f} seconds\n")
            
            if successful_tests:
                # Duration statistics
                durations = [r.duration for r in successful_tests]
                f.write(f"\n## Duration Statistics (Successful Tests)\n")
                f.write(f"- **Average Duration:** {statistics.mean(durations):.2f}s\n")
                f.write(f"- **Median Duration:** {statistics.median(durations):.2f}s\n")
                f.write(f"- **Min Duration:** {min(durations):.2f}s\n")
                f.write(f"- **Max Duration:** {max(durations):.2f}s\n")
                
                # Agent metrics statistics
                total_agents = [r.agent_metrics.get('total_agents', 0) for r in successful_tests if r.agent_metrics]
                if total_agents:
                    f.write(f"\n## Agent Statistics\n")
                    f.write(f"- **Average Agents per Test:** {statistics.mean(total_agents):.1f}\n")
                
                avg_energies = [r.agent_metrics.get('average_energy', 0) for r in successful_tests if r.agent_metrics]
                if avg_energies:
                    f.write(f"- **Average Energy Across Tests:** {statistics.mean(avg_energies):.3f}\n")
                    f.write(f"- **Energy Standard Deviation:** {statistics.stdev(avg_energies) if len(avg_energies) > 1 else 0:.3f}\n")
                
                # Quantum myelin statistics
                total_entanglements = [
                    r.quantum_myelin_metrics.get('total_entanglements', 0) 
                    for r in successful_tests if r.quantum_myelin_metrics
                ]
                if total_entanglements:
                    f.write(f"\n## Quantum Myelin Statistics\n")
                    f.write(f"- **Total Entanglements Across Tests:** {sum(total_entanglements)}\n")
                    f.write(f"- **Average Entanglements per Test:** {statistics.mean(total_entanglements):.1f}\n")
                    f.write(f"- **Max Entanglements in Single Test:** {max(total_entanglements)}\n")
                
                # Meme statistics
                meme_counts = [r.meme_metrics.get('total_memes', 0) for r in successful_tests if r.meme_metrics]
                if meme_counts:
                    f.write(f"\n## Meme Statistics\n")
                    f.write(f"- **Average Memes per Test:** {statistics.mean(meme_counts):.1f}\n")
                    
                propagation_counts = [r.meme_metrics.get('total_propagations', 0) for r in successful_tests if r.meme_metrics]
                if propagation_counts:
                    f.write(f"- **Average Propagations per Test:** {statistics.mean(propagation_counts):.1f}\n")
            
            if failed_tests:
                f.write(f"\n## Failed Tests\n")
                for test in failed_tests:
                    f.write(f"- **{test.test_name}:** {test.error_message}\n")
    
    def _generate_comparison_matrix(self, test_results: List, output_dir: str):
        """Generate a comparison matrix of test results."""
        comparison_file = os.path.join(output_dir, "test_comparison.md")
        
        successful_tests = [r for r in test_results if r.success]
        
        if not successful_tests:
            return
        
        with open(comparison_file, 'w') as f:
            f.write("# Test Comparison Matrix\n\n")
            
            # Create comparison table
            f.write("| Test Name | Duration | Agents | Entanglements | Memes | Propagations | Avg Energy |\n")
            f.write("|-----------|----------|--------|---------------|-------|-------------|------------|\n")
            
            for test in successful_tests:
                agent_metrics = test.agent_metrics or {}
                meme_metrics = test.meme_metrics or {}
                quantum_metrics = test.quantum_myelin_metrics or {}
                
                f.write(f"| {test.test_name} | ")
                f.write(f"{test.duration:.1f}s | ")
                f.write(f"{agent_metrics.get('total_agents', 'N/A')} | ")
                f.write(f"{quantum_metrics.get('total_entanglements', 0)} | ")
                f.write(f"{meme_metrics.get('total_memes', 0)} | ")
                f.write(f"{meme_metrics.get('total_propagations', 0)} | ")
                f.write(f"{agent_metrics.get('average_energy', 0):.3f} |\n")
    
    def _generate_performance_trends(self, test_results: List, output_dir: str):
        """Generate performance trends analysis."""
        trends_file = os.path.join(output_dir, "performance_trends.md")
        
        successful_tests = [r for r in test_results if r.success]
        
        if len(successful_tests) < 2:
            return
        
        with open(trends_file, 'w') as f:
            f.write("# Performance Trends Analysis\n\n")
            
            # Sort tests by timestamp
            sorted_tests = sorted(successful_tests, key=lambda x: x.timestamp)
            
            f.write("## Test Execution Timeline\n\n")
            for i, test in enumerate(sorted_tests):
                f.write(f"{i+1}. **{test.test_name}** ({test.timestamp[:19]})\n")
                f.write(f"   - Duration: {test.duration:.2f}s\n")
                f.write(f"   - Entanglements: {test.quantum_myelin_metrics.get('total_entanglements', 0)}\n")
                f.write(f"   - Avg Energy: {test.agent_metrics.get('average_energy', 0):.3f}\n")
            
            # Performance correlation analysis
            f.write("\n## Performance Correlations\n\n")
            
            entanglements = [t.quantum_myelin_metrics.get('total_entanglements', 0) for t in sorted_tests]
            durations = [t.duration for t in sorted_tests]
            
            if len(set(entanglements)) > 1 and len(set(durations)) > 1:
                # Simple correlation coefficient calculation
                mean_ent = statistics.mean(entanglements)
                mean_dur = statistics.mean(durations)
                
                numerator = sum((e - mean_ent) * (d - mean_dur) for e, d in zip(entanglements, durations))
                den_ent = sum((e - mean_ent) ** 2 for e in entanglements)
                den_dur = sum((d - mean_dur) ** 2 for d in durations)
                
                if den_ent > 0 and den_dur > 0:
                    correlation = numerator / (den_ent * den_dur) ** 0.5
                    f.write(f"**Entanglements vs Duration Correlation:** {correlation:.3f}\n")
                    
                    if correlation > 0.5:
                        f.write("- Strong positive correlation: More entanglements tend to increase duration\n")
                    elif correlation < -0.5:
                        f.write("- Strong negative correlation: More entanglements tend to decrease duration\n")
                    else:
                        f.write("- Weak correlation between entanglements and duration\n")
    
    def export_results_to_csv(self, test_results: List, filename: str):
        """Export test results to CSV format for external analysis."""
        import csv
        
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w', newline='') as csvfile:
            fieldnames = [
                'test_name', 'timestamp', 'duration', 'success',
                'total_agents', 'average_energy', 'average_health',
                'total_entanglements', 'total_propagations', 'total_memes'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for test in test_results:
                agent_metrics = test.agent_metrics or {}
                meme_metrics = test.meme_metrics or {}
                quantum_metrics = test.quantum_myelin_metrics or {}
                
                writer.writerow({
                    'test_name': test.test_name,
                    'timestamp': test.timestamp,
                    'duration': test.duration,
                    'success': test.success,
                    'total_agents': agent_metrics.get('total_agents', ''),
                    'average_energy': agent_metrics.get('average_energy', ''),
                    'average_health': agent_metrics.get('average_health', ''),
                    'total_entanglements': quantum_metrics.get('total_entanglements', ''),
                    'total_propagations': meme_metrics.get('total_propagations', ''),
                    'total_memes': meme_metrics.get('total_memes', '')
                })
        
        print(f"📄 Results exported to CSV: {filepath}")