import os
import itertools
import datetime
import shutil
from utilityfog_frontend import main_simulation

# Configuration ranges
populations = [25, 50, 100]
mutation_rates = [0.1, 0.3, 0.5]
runs_per_config = 3  # repeat for statistical smoothing

# Directories for results and logs
results_dir = "data/results"
logs_dir = "data/logs"
os.makedirs(results_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)

def run_batch(population, mutation_rate, run_id):
    config = {
        "population_size": population,
        "mutation_rate": mutation_rate,
        "max_generations": 20,
        "run_id": run_id
    }

    print(f"🔁 Running simulation: Pop={population}, Mut={mutation_rate}, Run={run_id}")

    # Construct timestamped output subdirectory
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_folder = os.path.join(results_dir, f"pop{population}_mut{mutation_rate}_run{run_id}_{timestamp}")
    os.makedirs(output_folder, exist_ok=True)

    log_path = os.path.join(logs_dir, f"log_pop{population}_mut{mutation_rate}_run{run_id}.txt")
    with open(log_path, "w") as log_file:
        try:
            result = main_simulation.run_simulation(config=config)
            log_file.write(f"✔ SUCCESS\n{result}\n")
        except Exception as e:
            log_file.write(f"❌ ERROR: {e}\n")
            print(f"❌ Error during run: {e}")

if __name__ == "__main__":
    for (pop, mut) in itertools.product(populations, mutation_rates):
        for run_id in range(1, runs_per_config + 1):
            run_batch(pop, mut, run_id)
