import os
import time
import yaml
from datetime import datetime
from simulation.main_simulation import SimulationRunner

# Define test parameters
POPULATIONS = [25, 50, 100]
MUTATION_RATES = [0.1, 0.3, 0.5]
REPETITIONS = 3
MAX_STEPS = 500

RESULTS_DIR = "data/results"
LOGS_DIR = "data/logs"
REPORT_PATH = os.path.join(RESULTS_DIR, "summary_report.md")

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def run_single_simulation(pop, mut_rate, run_id):
    config = {
        "population_size": pop,
        "mutation_rate": mut_rate,
        "max_steps": MAX_STEPS
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = f"pop{pop}_mut{int(mut_rate * 100)}_run{run_id}_{timestamp}"
    result_path = os.path.join(RESULTS_DIR, f"{label}.yaml")
    log_path = os.path.join(LOGS_DIR, f"{label}.log")

    print(f"▶️ Running: {label}")

    runner = SimulationRunner(config=config)
    with open(log_path, 'w') as log_file:
        runner.run_simulation(log_output=log_file)

    with open(result_path, 'w') as f:
        yaml.dump(runner.metrics, f)

    return label, result_path

def summarize_results(results):
    lines = ["# Simulation Summary Report\n"]

    for label, path in results:
        with open(path, 'r') as f:
            metrics = yaml.safe_load(f)

        lines.append(f"## {label}")
        lines.append(f"- Final Step: {metrics.get('step', 'N/A')}")
        lines.append(f"- Avg Fitness: {metrics.get('avg_fitness', 'N/A')}")
        lines.append(f"- Diversity: {metrics.get('diversity', 'N/A')}")
        lines.append(f"- Energy: {metrics.get('energy', 'N/A')}\n")

    with open(REPORT_PATH, 'w') as f:
        f.write("\n".join(lines))
    print(f"📄 Summary written to: {REPORT_PATH}")

def main():
    results = []
    for pop in POPULATIONS:
        for mut in MUTATION_RATES:
            for rep in range(1, REPETITIONS + 1):
                label, path = run_single_simulation(pop, mut, rep)
                results.append((label, path))
                time.sleep(2)
    summarize_results(results)

if __name__ == "__main__":
    main()
