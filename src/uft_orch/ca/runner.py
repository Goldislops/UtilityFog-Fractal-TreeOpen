"""CA experiment runner and orchestrator.

Loads rules, seeds, and experiment configs, then executes CA simulations
using the uft_ca Rust kernel.
"""

import json
import csv
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import tomli
import yaml
import numpy as np

try:
    import uft_ca
    HAS_UFT_CA = True
except ImportError:
    HAS_UFT_CA = False
    print("Warning: uft_ca module not available. Using stub implementation.")


@dataclass
class RuleSpec:
    """CA rule specification."""
    name: str
    states: List[str]
    neighborhood: str  # "moore-3d" or "graph"
    transition: str  # "outer-totalistic" or "table"
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_toml(cls, path: Path) -> "RuleSpec":
        """Load rule from TOML file."""
        with open(path, "rb") as f:
            data = tomli.load(f)
        return cls(
            name=data["rule"]["name"],
            states=data["rule"]["states"],
            neighborhood=data["rule"]["neighborhood"],
            transition=data["rule"]["transition"],
            params=data.get("params", {}),
        )


@dataclass
class ExperimentConfig:
    """Experiment configuration."""
    name: str
    rule_path: Path
    seed_path: Optional[Path]
    steps: int
    lattice_size: Optional[tuple] = None
    graph_nodes: Optional[int] = None
    metrics: List[str] = field(default_factory=list)
    output_dir: Path = Path("artifacts")

    @classmethod
    def from_yaml(cls, path: Path) -> "ExperimentConfig":
        """Load experiment config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        
        return cls(
            name=data["experiment"]["name"],
            rule_path=Path(data["experiment"]["rule"]),
            seed_path=Path(data["experiment"]["seed"]) if "seed" in data["experiment"] else None,
            steps=data["experiment"]["steps"],
            lattice_size=tuple(data["experiment"].get("lattice_size", [])) or None,
            graph_nodes=data["experiment"].get("graph_nodes"),
            metrics=data["experiment"].get("metrics", []),
            output_dir=Path(data["experiment"].get("output_dir", "artifacts")),
        )


class CARunner:
    """Orchestrates CA experiments."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.rule = RuleSpec.from_toml(config.rule_path)
        self.states: Optional[np.ndarray] = None
        self.metrics_history: List[Dict[str, float]] = []

    def load_seed(self) -> np.ndarray:
        """Load initial seed configuration."""
        if self.config.seed_path:
            with open(self.config.seed_path) as f:
                if self.config.seed_path.suffix == ".json":
                    data = json.load(f)
                else:
                    data = tomli.load(f)
                return np.array(data["states"], dtype=np.uint8)
        
        # Generate random seed
        if self.config.lattice_size:
            size = np.prod(self.config.lattice_size)
            return np.random.randint(0, len(self.rule.states), size=size, dtype=np.uint8)
        elif self.config.graph_nodes:
            return np.random.randint(0, len(self.rule.states), size=self.config.graph_nodes, dtype=np.uint8)
        else:
            raise ValueError("Must specify either lattice_size or graph_nodes")

    def step(self) -> np.ndarray:
        """Execute one CA step."""
        if not HAS_UFT_CA:
            # Stub implementation for testing
            return self.states
        
        if self.rule.neighborhood == "moore-3d" and self.config.lattice_size:
            w, h, d = self.config.lattice_size
            next_states = uft_ca.step_lattice_py(w, h, d, self.states.tolist())
            return np.array(next_states, dtype=np.uint8)
        else:
            # Graph stepping not yet implemented in Python bindings
            return self.states

    def compute_metrics(self) -> Dict[str, float]:
        """Compute requested metrics on current state."""
        metrics = {}
        
        if "density" in self.config.metrics:
            metrics["density"] = np.mean(self.states > 0)
        
        if "branching_factor" in self.config.metrics:
            # Simplified branching factor: ratio of active cells to previous step
            if len(self.metrics_history) > 0:
                prev_active = self.metrics_history[-1].get("active_cells", 1)
                current_active = np.sum(self.states > 0)
                metrics["branching_factor"] = current_active / max(prev_active, 1)
            else:
                metrics["branching_factor"] = 1.0
        
        if "connectivity" in self.config.metrics:
            # Simplified connectivity: fraction of non-void cells
            metrics["connectivity"] = np.mean(self.states > 0)
        
        if "survival" in self.config.metrics:
            # Survival: fraction of cells that remain active
            metrics["survival"] = np.mean(self.states > 0)
        
        metrics["active_cells"] = int(np.sum(self.states > 0))
        metrics["total_cells"] = int(len(self.states))
        
        return metrics

    def run(self) -> Dict[str, Any]:
        """Run the full experiment."""
        print(f"Running experiment: {self.config.name}")
        print(f"Rule: {self.rule.name}")
        print(f"Steps: {self.config.steps}")
        
        # Initialize
        self.states = self.load_seed()
        self.metrics_history = []
        
        # Run simulation
        for step in range(self.config.steps):
            metrics = self.compute_metrics()
            metrics["step"] = step
            self.metrics_history.append(metrics)
            
            if step % 100 == 0:
                print(f"Step {step}/{self.config.steps}: {metrics['active_cells']} active cells")
            
            self.states = self.step()
        
        # Final metrics
        final_metrics = self.compute_metrics()
        final_metrics["step"] = self.config.steps
        self.metrics_history.append(final_metrics)
        
        # Save results
        self.save_results()
        
        return {
            "experiment": self.config.name,
            "rule": self.rule.name,
            "steps": self.config.steps,
            "final_metrics": final_metrics,
        }

    def save_results(self):
        """Save metrics to CSV and final state to file."""
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save metrics CSV
        csv_path = self.config.output_dir / f"{self.config.name}_metrics.csv"
        with open(csv_path, "w", newline="") as f:
            if self.metrics_history:
                writer = csv.DictWriter(f, fieldnames=self.metrics_history[0].keys())
                writer.writeheader()
                writer.writerows(self.metrics_history)
        print(f"Saved metrics to {csv_path}")
        
        # Save final state
        state_path = self.config.output_dir / f"{self.config.name}_final_state.npy"
        np.save(state_path, self.states)
        print(f"Saved final state to {state_path}")


def main():
    """CLI entry point."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m uft_orch.ca.runner <experiment.yaml>")
        sys.exit(1)
    
    config_path = Path(sys.argv[1])
    config = ExperimentConfig.from_yaml(config_path)
    runner = CARunner(config)
    results = runner.run()
    
    print("\nExperiment complete!")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
