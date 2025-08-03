import itertools
import json
import os
from utilityfog_frontend.main_simulation import run_simulation

param_grid = {
    "population": [25, 50, 100],
    "mutation_rate": [0.1, 0.3, 0.5]
}

all_configs = list(itertools.product(*param_grid.values()))
param_names = list(param_grid.keys())

os.makedirs("data/results", exist_ok=True)
os.makedirs("data/logs", exist_ok=True)

summary = []

for i, values in enumerate(all_configs):
    config = dict(zip(param_names, values))
    print(f"Running config {i+1}/{len(all_configs)}: {config}")
    result = run_simulation(config)

    result_file = f"data/results/result_{i+1}.json"
    with open(result_file, "w") as f:
        json.dump(result, f)

    log_file = f"data/logs/log_{i+1}.txt"
    with open(log_file, "w") as f:
        f.write(f"Config: {config}\nResult: {result}\n")

    summary.append(config)

with open("data/results/summary.md", "w") as f:
    for i, config in enumerate(summary):
        f.write(f"### Config {i+1}\n")
        f.write(json.dumps(config, indent=2))
        f.write("\n\n")
