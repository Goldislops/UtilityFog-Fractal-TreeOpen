# Test Configurations

This directory contains predefined test configurations for various simulation scenarios.

## Available Configurations

### Basic Tests
- **quick_test.json**: Fast test with minimal resources (5 agents, 2 generations)
- **standard_test.json**: Standard validation test (10 agents, 3 generations)
- **comprehensive_test.json**: Full feature test with more resources

### Specialized Tests
- **high_mutation_test.json**: Tests with high mutation rates
- **no_quantum_test.json**: Tests with quantum myelin disabled
- **network_stress_test.json**: Tests network topology under various conditions

### Research Configurations
- **meme_evolution_focus.json**: Focused on meme propagation and evolution
- **agent_interaction_focus.json**: Emphasized agent-to-agent interactions
- **quantum_entanglement_focus.json**: Maximized quantum myelin activity

## Usage

Test configurations can be loaded and used with the TestRunner:

```python
from testing_framework import TestRunner, TestConfiguration
import json

# Load a predefined configuration
with open('test_configs/standard_test.json', 'r') as f:
    config_data = json.load(f)

config = TestConfiguration(**config_data)
test_runner = TestRunner()
result = test_runner.run_single_test(config)
```

## Creating Custom Configurations

You can create new JSON configuration files following this structure:

```json
{
    "test_name": "my_custom_test",
    "num_agents": 10,
    "num_generations": 3,
    "simulation_steps": 50,
    "mutation_rate": 0.1,
    "crossover_rate": 0.8,
    "enable_quantum_myelin": true,
    "network_depth": 3,
    "branching_factor": 3,
    "initial_memes_per_agent": 2,
    "log_level": "INFO",
    "custom_parameters": {
        "special_setting": "custom_value"
    }
}
```