# Issue #165 — Tier 3 Plan (structural blueprint, no implementation)

**Status:** Planning / decision doc (docs-only). **No structural code changes in this PR.**
**Predecessors merged:** triage map #172, Tier 0 #173, Tier 1 #174, Tier 2 #175, Tier 2.1 #176.
**Mandate (Jack + AURA):** Tier 3 touches package layout and build steps, so plan first, implement in sub-tiers.

---

## 0. Where #165 stands now

The maintained `tests/` suite collects **568 tests with exactly 3 remaining collection errors** — all Tier 3:

| # | Module | Cause (verified) |
|---|---|---|
| 1 | `tests/test_feature_flags.py` | stale hardcoded `sys.path` → `agent.feature_flags` not found |
| 2 | `tests/test_observability.py` | same stale hardcoded `sys.path` |
| 3 | `tests/test_state_observation.py` | `from uft_ca import ...` — Rust pyo3 ext not built |

Everything else (Tiers 0–2.1) is green. After Tier 3, `tests/` collects cleanly.

---

## Tier 3A — `agent` namespace resolution

### Root cause (empirically verified, not assumed)
Both `test_feature_flags.py` and `test_observability.py` contain a **hardcoded absolute path from a different machine**:

```python
sys.path.append('/home/ubuntu/github_repos/UtilityFog-Fractal-TreeOpen/UtilityFog_Agent_Package')
```

That `/home/ubuntu/...` directory does not exist in this checkout (`/home/user/...`), so `UtilityFog_Agent_Package` never lands on `sys.path` and `from agent.feature_flags import ...` fails.

### The "collision" is actually a mergeable namespace
Neither `agent/` directory has an `__init__.py` — both are **PEP 420 namespace packages**. Verified locally: with **both** repo-root and `UtilityFog_Agent_Package` on `sys.path`, `agent` merges across both directory portions and all of these import together:

```
agent.__path__ = ['<root>/agent', '<root>/UtilityFog_Agent_Package/agent']
import agent.ising_tempering   # OK  (root portion)
import agent.feature_flags     # OK  (canonical portion)
import agent.observability     # OK  (canonical portion)
```

So `UtilityFog_Agent_Package/agent/` being "canonical" and root `agent/` being the "legacy shadow" (per AURA) is correct — **but they coexist as namespace portions; we do not have to delete or move either to fix the tests.**

### Layout reality (overlap to be aware of)
| Module | root `agent/` | `UtilityFog_Agent_Package/agent/` |
|---|:---:|:---:|
| evolution_engine, foglet_agent, meme_structure, network_topology, simulation_metrics | ✅ | ✅ (overlap) |
| ising_tempering | ✅ | — |
| feature_flags, observability, main_simulation, telemetry_collector | — | ✅ |

The 5 overlapping modules are a *latent* risk only if a single test needs a specific version of an overlapping name (namespace order would decide the winner). The two failing tests import **only canonical-unique** modules (`feature_flags`, `observability`, `telemetry_collector`), so no shadowing affects them.

### Recommended fix (smallest, contained) — **3A primary**
Replace the stale hardcoded path in the 2 tests with a `__file__`-relative path to the canonical package, matching the idiom already used by `test_ising_tempering.py` / `test_visualization.py`:

```python
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "UtilityFog_Agent_Package"))
```

- Scope: 2 test files, ~2 lines changed each. No source/layout changes.
- Risk: minimal — verified the imports resolve with this path present.

### Alternative (cleaner, broader) — note for decision
Add `pythonpath = . UtilityFog_Agent_Package` to `pytest.ini` (pytest's built-in `pythonpath` ini option) and **delete** the per-test `sys.path` hacks across the suite. Elegant and centralizes path setup, **but** it places both `agent` portions on the path for *every* test, which could change resolution order for the 5 overlapping modules in other tests. Given the "no breakage" mandate, recommend the per-test fix first; consider this consolidation as a separate, well-tested follow-up.

**Decision needed from Jack/AURA:** 3A-primary (per-test path fix) vs 3A-alt (central `pythonpath` + remove hacks). Recommendation: **3A-primary now**, 3A-alt later.

---

## Tier 3B — `uft_ca` Rust/pyo3 handling

### State (verified)
- `tests/test_state_observation.py` → `from uft_ca import MultiStateGraphLattice`.
- `crates/uft_ca/` is a pyo3 crate (`crate-type = ["cdylib","rlib"]`) with `Cargo.toml` + `src/`, but **no `pyproject.toml`** and **no built `.so`** in the tree. The extension is simply not built/installed for Python.

### Options
- **3B-safe (recommended first):** add `pytest.importorskip("uft_ca")` at the top of `test_state_observation.py`. Self-skips when the ext is unbuilt — zero risk, mirrors the Tier 1 pattern, removes the collection error immediately.
- **3B-full (tracked follow-up):** add a maturin `pyproject.toml` to `crates/uft_ca` and a `maturin develop` build step in CI (requires a Rust toolchain on the runner). This actually *runs* the test rather than skipping it.

**Decision needed:** importorskip now vs commit to a maturin CI build. Recommendation: **3B-safe now**, open a separate tracked issue for the maturin build so coverage isn't silently lost.

---

## Tier 3C — retire `test_phase3_integration.py`

### State (verified)
Already **inert**: Tier 0's `testpaths = tests` means bare `pytest` collects 0 from it. It remains git-tracked at repo root. AURA's call: Phase-3 debris (we are in Phase 19), retire/exclude explicitly.

### Recommended action
`git rm test_phase3_integration.py` (a deliberate, reviewable deletion) — it is superseded by the structured `tests/` suite and is not collected. If any assertion in it is still considered valuable, salvage that into a `tests/` module first; a quick scan suggests it duplicates feature-flag/integration coverage already present.

**Decision needed:** delete outright vs salvage-then-delete. Recommendation: **delete** (it's superseded and inert); flag if a salvage pass is wanted.

> Note: the other 5 root-level legacy scripts (`backend_test.py`, `final_test.py`, `proper_sim_test.py`, `quick_sim_test.py`, `demo_test.py`) are live-server manual integration scripts — a **separate** question from `test_phase3_integration.py` and explicitly **out of Tier 3C scope**.

---

## Proposed sub-tier sequencing

Each is an independent, small, reversible PR — and **none** makes bare `pytest` the CI gate:

1. **Tier 3A** — fix the 2 stale `sys.path` paths → `test_feature_flags` + `test_observability` collect. *(2 test files.)*
2. **Tier 3B** — `importorskip("uft_ca")` → `test_state_observation` self-skips. *(1 test file.)* + open maturin-build follow-up issue.
3. **Tier 3C** — retire `test_phase3_integration.py`. *(1 deletion.)*

After 3A + 3B, **`tests/` collects with 0 errors** (568 collected; `uft_ca` test skipped pending build).

### Optional Tier 4 (separate, later)
Once `tests/` collects cleanly, broaden the `verify-python` CI job from the current 2 nextness files toward the full suite — incrementally, never past green.

---

## Guardrails (all sub-tiers)
- Plan-only in this PR — no structural code yet.
- No engine touch, no observer semantics, no Lane A / Swarm Hunter / tuning API / production sweeps.
- Bare `pytest` is **not** proposed as the CI gate.
- Each sub-tier stays small, contained, and reversible; nothing bundled.

## Decisions requested from Jack + AURA
1. **3A:** per-test path fix (recommended) vs central `pytest.ini pythonpath`.
2. **3B:** `importorskip` now (recommended) vs commit to a maturin CI build now.
3. **3C:** delete `test_phase3_integration.py` outright (recommended) vs salvage-then-delete.
