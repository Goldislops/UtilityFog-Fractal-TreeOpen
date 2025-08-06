from utilityfog_frontend.main_simulation import run_simulation

if __name__ == "__main__":
    test_configs = [
        {"param1": 1, "param2": "A"},
        {"param1": 2, "param2": "B"},
    ]
    for config in test_configs:
        result = run_simulation(config)
        print(result)
