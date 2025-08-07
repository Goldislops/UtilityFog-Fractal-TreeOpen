"""
Simulation Result Validators for UtilityFog Testing

This module provides validation capabilities to ensure simulation results
are consistent, reasonable, and meet expected criteria.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ValidationRule:
    """Defines a validation rule for simulation results."""
    name: str
    description: str
    severity: str  # "ERROR", "WARNING", "INFO"
    check_function: callable


@dataclass
class ValidationResult:
    """Result of a validation check."""
    rule_name: str
    passed: bool
    severity: str
    message: str
    details: Optional[Dict[str, Any]] = None


class SimulationValidator:
    """Validator for simulation results and consistency checks."""
    
    def __init__(self):
        """Initialize the validator with default rules."""
        self.rules = self._create_default_rules()
    
    def validate_results(self, test_result) -> Dict[str, Any]:
        """
        Validate a test result against all rules.
        
        Args:
            test_result: TestResult object to validate
            
        Returns:
            Dictionary containing validation results
        """
        validation_results = []
        
        for rule in self.rules:
            try:
                result = rule.check_function(test_result)
                validation_results.append(result)
            except Exception as e:
                error_result = ValidationResult(
                    rule_name=rule.name,
                    passed=False,
                    severity="ERROR",
                    message=f"Validation rule failed to execute: {str(e)}"
                )
                validation_results.append(error_result)
        
        # Summarize results
        passed_count = sum(1 for r in validation_results if r.passed)
        failed_count = len(validation_results) - passed_count
        
        errors = [r for r in validation_results if r.severity == "ERROR" and not r.passed]
        warnings = [r for r in validation_results if r.severity == "WARNING" and not r.passed]
        
        return {
            "total_rules": len(validation_results),
            "passed_rules": passed_count,
            "failed_rules": failed_count,
            "errors": [{"rule": r.rule_name, "message": r.message} for r in errors],
            "warnings": [{"rule": r.rule_name, "message": r.message} for r in warnings],
            "all_results": [
                {
                    "rule": r.rule_name,
                    "passed": r.passed,
                    "severity": r.severity,
                    "message": r.message
                }
                for r in validation_results
            ],
            "validation_passed": len(errors) == 0
        }
    
    def _create_default_rules(self) -> List[ValidationRule]:
        """Create default validation rules."""
        return [
            ValidationRule(
                name="agent_count_positive",
                description="Agent count should be positive",
                severity="ERROR",
                check_function=self._check_agent_count_positive
            ),
            ValidationRule(
                name="energy_levels_valid",
                description="Agent energy levels should be between 0 and 1",
                severity="ERROR",
                check_function=self._check_energy_levels_valid
            ),
            ValidationRule(
                name="health_levels_valid",
                description="Agent health levels should be between 0 and 1",
                severity="ERROR", 
                check_function=self._check_health_levels_valid
            ),
            ValidationRule(
                name="meme_count_reasonable",
                description="Meme count should be reasonable relative to agent count",
                severity="WARNING",
                check_function=self._check_meme_count_reasonable
            ),
            ValidationRule(
                name="entanglement_events_present",
                description="Quantum myelin entanglement events should occur when enabled",
                severity="WARNING",
                check_function=self._check_entanglement_events_present
            ),
            ValidationRule(
                name="propagation_events_present",
                description="Meme propagation events should occur",
                severity="INFO",
                check_function=self._check_propagation_events_present
            ),
            ValidationRule(
                name="simulation_duration_reasonable",
                description="Simulation duration should be reasonable",
                severity="WARNING",
                check_function=self._check_simulation_duration_reasonable
            ),
            ValidationRule(
                name="fitness_scores_valid",
                description="Meme fitness scores should be between 0 and 1",
                severity="ERROR",
                check_function=self._check_fitness_scores_valid
            ),
            ValidationRule(
                name="network_connectivity",
                description="Network should have proper connectivity",
                severity="WARNING",
                check_function=self._check_network_connectivity
            ),
            ValidationRule(
                name="logs_present",
                description="Simulation should generate logs",
                severity="INFO",
                check_function=self._check_logs_present
            )
        ]
    
    def _check_agent_count_positive(self, test_result) -> ValidationResult:
        """Check that agent count is positive."""
        agent_metrics = test_result.agent_metrics or {}
        total_agents = agent_metrics.get('total_agents', 0)
        
        passed = total_agents > 0
        message = f"Total agents: {total_agents}" if passed else f"No agents found (total: {total_agents})"
        
        return ValidationResult(
            rule_name="agent_count_positive",
            passed=passed,
            severity="ERROR",
            message=message
        )
    
    def _check_energy_levels_valid(self, test_result) -> ValidationResult:
        """Check that agent energy levels are valid."""
        agent_metrics = test_result.agent_metrics or {}
        avg_energy = agent_metrics.get('average_energy', 0)
        
        # Check individual agent states if available
        agent_states = agent_metrics.get('agent_states', {})
        invalid_energies = []
        
        for agent_id, state in agent_states.items():
            energy = state.get('energy', 0)
            if energy < 0 or energy > 1:
                invalid_energies.append(f"{agent_id}: {energy}")
        
        # Also check average
        avg_valid = 0 <= avg_energy <= 1
        
        passed = len(invalid_energies) == 0 and avg_valid
        
        if passed:
            message = f"All energy levels valid (avg: {avg_energy:.3f})"
        else:
            issues = []
            if not avg_valid:
                issues.append(f"avg energy {avg_energy:.3f} out of range")
            if invalid_energies:
                issues.append(f"{len(invalid_energies)} agents with invalid energy")
            message = f"Energy validation failed: {', '.join(issues)}"
        
        return ValidationResult(
            rule_name="energy_levels_valid",
            passed=passed,
            severity="ERROR",
            message=message,
            details={"invalid_agents": invalid_energies} if invalid_energies else None
        )
    
    def _check_health_levels_valid(self, test_result) -> ValidationResult:
        """Check that agent health levels are valid."""
        agent_metrics = test_result.agent_metrics or {}
        avg_health = agent_metrics.get('average_health', 0)
        
        # Check individual agent states if available
        agent_states = agent_metrics.get('agent_states', {})
        invalid_healths = []
        
        for agent_id, state in agent_states.items():
            health = state.get('health', 0)
            if health < 0 or health > 1:
                invalid_healths.append(f"{agent_id}: {health}")
        
        # Also check average
        avg_valid = 0 <= avg_health <= 1
        
        passed = len(invalid_healths) == 0 and avg_valid
        
        if passed:
            message = f"All health levels valid (avg: {avg_health:.3f})"
        else:
            issues = []
            if not avg_valid:
                issues.append(f"avg health {avg_health:.3f} out of range")
            if invalid_healths:
                issues.append(f"{len(invalid_healths)} agents with invalid health")
            message = f"Health validation failed: {', '.join(issues)}"
        
        return ValidationResult(
            rule_name="health_levels_valid",
            passed=passed,
            severity="ERROR",
            message=message,
            details={"invalid_agents": invalid_healths} if invalid_healths else None
        )
    
    def _check_meme_count_reasonable(self, test_result) -> ValidationResult:
        """Check that meme count is reasonable relative to agent count."""
        agent_metrics = test_result.agent_metrics or {}
        meme_metrics = test_result.meme_metrics or {}
        
        total_agents = agent_metrics.get('total_agents', 0)
        total_memes = meme_metrics.get('total_memes', 0)
        
        if total_agents == 0:
            return ValidationResult(
                rule_name="meme_count_reasonable",
                passed=False,
                severity="WARNING",
                message="Cannot validate meme count: no agents found"
            )
        
        # Reasonable range: 0.5 to 10 memes per agent
        min_expected = total_agents * 0.5
        max_expected = total_agents * 10
        
        passed = min_expected <= total_memes <= max_expected
        
        if passed:
            message = f"Meme count reasonable: {total_memes} memes for {total_agents} agents"
        else:
            message = f"Meme count unusual: {total_memes} memes for {total_agents} agents (expected {min_expected:.0f}-{max_expected:.0f})"
        
        return ValidationResult(
            rule_name="meme_count_reasonable",
            passed=passed,
            severity="WARNING",
            message=message
        )
    
    def _check_entanglement_events_present(self, test_result) -> ValidationResult:
        """Check that entanglement events occurred when quantum myelin is enabled."""
        quantum_metrics = test_result.quantum_myelin_metrics or {}
        total_entanglements = quantum_metrics.get('total_entanglements', 0)
        
        # This check is only meaningful if we know quantum myelin was enabled
        # For now, we'll just check if entanglements occurred
        
        passed = total_entanglements > 0
        
        if passed:
            message = f"Entanglement events present: {total_entanglements} total"
        else:
            message = "No entanglement events recorded (may indicate quantum myelin disabled or insufficient conditions)"
        
        return ValidationResult(
            rule_name="entanglement_events_present",
            passed=passed,
            severity="WARNING",
            message=message
        )
    
    def _check_propagation_events_present(self, test_result) -> ValidationResult:
        """Check that meme propagation events occurred."""
        meme_metrics = test_result.meme_metrics or {}
        quantum_metrics = test_result.quantum_myelin_metrics or {}
        
        total_propagations_meme = meme_metrics.get('total_propagations', 0)
        total_propagations_quantum = quantum_metrics.get('total_propagations', 0)
        
        # Use the larger value
        total_propagations = max(total_propagations_meme, total_propagations_quantum)
        
        passed = total_propagations > 0
        
        if passed:
            message = f"Meme propagation events present: {total_propagations} total"
        else:
            message = "No meme propagation events recorded"
        
        return ValidationResult(
            rule_name="propagation_events_present",
            passed=passed,
            severity="INFO",
            message=message
        )
    
    def _check_simulation_duration_reasonable(self, test_result) -> ValidationResult:
        """Check that simulation duration is reasonable."""
        duration = test_result.duration
        
        # Reasonable range: 0.1 to 300 seconds for testing
        min_duration = 0.1
        max_duration = 300.0
        
        passed = min_duration <= duration <= max_duration
        
        if passed:
            message = f"Simulation duration reasonable: {duration:.2f}s"
        else:
            if duration < min_duration:
                message = f"Simulation duration too short: {duration:.2f}s (may indicate immediate failure)"
            else:
                message = f"Simulation duration too long: {duration:.2f}s (may indicate performance issues)"
        
        return ValidationResult(
            rule_name="simulation_duration_reasonable",
            passed=passed,
            severity="WARNING",
            message=message
        )
    
    def _check_fitness_scores_valid(self, test_result) -> ValidationResult:
        """Check that meme fitness scores are valid."""
        meme_metrics = test_result.meme_metrics or {}
        avg_fitness = meme_metrics.get('average_fitness', 0)
        
        passed = 0 <= avg_fitness <= 1
        
        if passed:
            message = f"Average fitness score valid: {avg_fitness:.3f}"
        else:
            message = f"Average fitness score out of range: {avg_fitness:.3f} (should be 0-1)"
        
        return ValidationResult(
            rule_name="fitness_scores_valid",
            passed=passed,
            severity="ERROR",
            message=message
        )
    
    def _check_network_connectivity(self, test_result) -> ValidationResult:
        """Check basic network connectivity metrics."""
        network_metrics = test_result.network_metrics or {}
        
        total_nodes = network_metrics.get('total_nodes', 0)
        total_connections = network_metrics.get('total_connections', 0)
        
        if total_nodes == 0:
            return ValidationResult(
                rule_name="network_connectivity",
                passed=False,
                severity="WARNING",
                message="No network nodes found"
            )
        
        # For a connected tree, we expect n-1 connections for n nodes (minimum)
        min_expected_connections = max(0, total_nodes - 1)
        
        passed = total_connections >= min_expected_connections
        
        if passed:
            message = f"Network connectivity adequate: {total_connections} connections for {total_nodes} nodes"
        else:
            message = f"Network may be disconnected: {total_connections} connections for {total_nodes} nodes (expected >= {min_expected_connections})"
        
        return ValidationResult(
            rule_name="network_connectivity",
            passed=passed,
            severity="WARNING",
            message=message
        )
    
    def _check_logs_present(self, test_result) -> ValidationResult:
        """Check that simulation generated logs."""
        log_count = len(test_result.logs)
        
        passed = log_count > 0
        
        if passed:
            message = f"Logs present: {log_count} log entries"
        else:
            message = "No logs generated (may indicate logging issues)"
        
        return ValidationResult(
            rule_name="logs_present",
            passed=passed,
            severity="INFO",
            message=message
        )