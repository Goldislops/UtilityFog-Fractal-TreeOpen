import csv
import numpy as np


STATE_NAMES = ["void", "structural", "compute", "energy", "sensor"]


def to_numpy(history):
    if not history:
        return np.empty((0, 5), dtype=np.uint64)
    if isinstance(history[0], dict):
        rows = []
        for entry in history:
            rows.append([entry.get(i, 0) for i in range(5)])
        return np.array(rows, dtype=np.uint64)
    return np.array(history, dtype=np.uint64)


def to_csv(history, path, header=True):
    arr = to_numpy(history)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(["step"] + STATE_NAMES)
        for step_idx, row in enumerate(arr):
            writer.writerow([step_idx] + list(row))
    return path


def history_to_dict_list(history):
    arr = to_numpy(history)
    result = []
    for step_idx, row in enumerate(arr):
        d = {"step": step_idx}
        for i, name in enumerate(STATE_NAMES):
            d[name] = int(row[i])
        result.append(d)
    return result
