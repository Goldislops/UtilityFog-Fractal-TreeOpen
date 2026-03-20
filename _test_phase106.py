import sys
sys.path.insert(0, "src")
from uft_orch.ca.phase106 import (Phase106Params, EquanimityParams, IceBatteryParams,
    TrashBatteryParams, FogSim, CellMeta, e_reclaim, e_deliver, p_base, p_ice_boost, p_resist)
import numpy as np

tb = TrashBatteryParams()
val = e_reclaim(4, tb)
expected = 0.15 * 4 * 0.05
assert abs(val - min(expected, 0.05)) < 1e-9, f"e_reclaim failed: {val}"
print("PASS: e_reclaim")

eq = EquanimityParams()
val = p_base(2.0, 1.0, eq)
assert val == 0.0, f"p_base age<min should be 0: {val}"
val = p_base(5.0, 1.0, eq)
assert val > 0.0, f"p_base age>min should be >0: {val}"
print("PASS: p_base")

ice = IceBatteryParams()
val = p_ice_boost(4.0, 0.3, ice)
assert val == 0.0, "p_ice_boost below threshold should be 0"
val = p_ice_boost(4.0, 1.0, ice)
assert val > 0.0, f"p_ice_boost above threshold should be >0: {val}"
print("PASS: p_ice_boost")

params = Phase106Params()
val = p_resist(10.0, 3.0, 5.0, params)
assert val <= 0.95, f"p_resist should be capped at 0.95: {val}"
print("PASS: p_resist capped")

states = np.array([1, 1, 2, 0, 3, 1, 2, 0], dtype=np.uint8)
adj = []
w, h, d = 2, 2, 2
for idx in range(8):
    x, y, z = idx % w, (idx // w) % h, idx // (w * h)
    neighbors = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                nx, ny, nz = x + dx, y + dy, z + dz
                if 0 <= nx < w and 0 <= ny < h and 0 <= nz < d:
                    neighbors.append(nx + ny * w + nz * w * h)
    adj.append(neighbors)

sim = FogSim(states=states, adjacency=adj, params=params)
sim.step()
census = sim.census()
print(f"PASS: FogSim step completed, census={census}")

sim.step_n(5)
print(f"PASS: FogSim 5 more steps, gen={sim.generation}")

age = sim.max_compute_age()
energy = sim.avg_compute_energy()
print(f"PASS: max_compute_age={age:.2f}, avg_compute_energy={energy:.4f}")

print("ALL PHASE 10.6 VALIDATION TESTS PASSED")
