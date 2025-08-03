import os
import itertools
from utilityfog_frontend.main_simulation import run_simulation
from datetime import datetime

population_sizes = [25, 50, 100]
mutation_rates = [0.1, 0.3, 0.5]
repetitions = 3

results_dir = "data/results"
logs_dir = "data/logs"
os.makedirs(results_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)

summary_lines = []

for population, mutation_rate in itertools.product(population_sizes, mutation_rates):
    for i in range(repetitions):
        config_name = f"pop{population}_mut{mutation_rate}_run{i+1}"
        print(f"Running simulation: {config_name}")

        result_path = os.path.join(results_dir, f"{config_name}.json")
        log_path = os.path.join(logs_dir, f"{config_name}.log")

        metrics = run_simulation(
            population=population,
            mutation_rate=mutation_rate,
            save_path=result_path,
            log_path=log_path
        )

        summary = (
            f"Run: {config_name}\n"
            f"Population: {population}, Mutation Rate: {mutation_rate}\n"
            f"Fitness: {metrics.get('fitness')}, Duration: {metrics.get('duration')}\n"
        )
        summary_lines.append(summary)

# Save summary report
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
report_path = os.path.join(results_dir, f"summary_{timestamp}.md")
with open(report_path, "w") as f:
    f.write("# Simulation Summary\n\n")
    f.write("\n".join(summary_lines))

print(f"Summary report saved to: {report_path}")
