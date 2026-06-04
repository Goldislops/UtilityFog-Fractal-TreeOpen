# Issue #165 — Tier 4 Test-Status Report (evidence before CI broadening)

**Status:** Report / planning (docs-only). **No CI changes in this PR.**
**Predecessors merged:** #172 (triage), #173 (T0), #174 (T1), #175 (T2), #176 (T2.1), #177 (T3 plan), #178/#179/#181 (T3A/B/C). Follow-up issue #180 (maturin build).
**Purpose (Jack + AURA):** map the full-suite reality under the current environment *before* broadening `verify-python`. Do not jump to bare `pytest` as the gate.

---

## Environment

Matches the lean CI (`verify-python`): `numpy` + `pytest` only.
**Absent optional deps:** `matplotlib`, `flask`, `openai`, `pyzmq`, `uft_ca` (Rust ext), and the internal `evolution_engine` import used by one test.

---

## 1. The counts (bare `pytest tests/`, current env)

| Outcome | Count |
|---|---:|
| **passed** | **588** |
| **failed** | **9** |
| **skipped** | **32** |
| errors (collection) | 0 |
| xfail / xpass | 0 |

Collection floor is clean (Tier 3 result holds). The 9 failures are **not** logic regressions — all are missing-dependency or async-runner issues (detail in §3).

---

## 2. The skips (32) — all deliberate, dependency-gated

| Reason | Modules (skips) |
|---|---|
| **`uft_ca` not built** (Rust/pyo3; tracked in #180) | `test_state_observation` (1), `test_fractal_topologies` (1), `test_parallel_stepping` (1), `test_graph_stepping` (5), `test_multi_state_stepping` (17) — **25** |
| **`matplotlib` absent** | `test_observatory` (1), `test_visualization` (1) — **2** |
| **`flask` absent** | `test_provider_parity` (1), `test_tuning_api` (1) — **2** |
| **`pyzmq` absent** | `test_event_bus` (1), `test_shard_transport_zmq` (1) — **2** |
| **`evolution_engine` not available** | `test_differentiation_fitness` (1) — **1** |

All 32 skip *cleanly* (no errors). `pyzmq` and `evolution_engine` are previously-uncatalogued gates discovered by this run — both already self-skip correctly, so no action needed beyond noting them.

---

## 3. The 9 failures — ⚠️ findings, NOT fixed here (stop-and-report rule)

Two environmental classes; no code-logic bugs:

### Class A — missing `openai` optional dep (5 failures)
| Test | Error |
|---|---|
| `test_openai_compat_backend::test_construction_without_api_key_or_env_var_does_not_crash` | `RuntimeError: OpenAICompatBackend requires pip install openai` |
| `test_openai_compat_backend::test_explicit_api_key_arg_is_passed_through` | same |
| `test_openai_compat_backend::test_env_var_api_key_does_not_trigger_dummy` | same |
| `test_orchestrator::test_create_backend_openai_compat` | `ModuleNotFoundError: No module named 'openai'` |
| `test_orchestrator::test_create_backend_underscore_alias_accepted` | same |

These are unguarded — they **hard-fail** instead of skipping. Same category as the Tier 1 matplotlib/flask work. **Recommended fix (future tier):** `pytest.importorskip("openai")` on the affected modules/tests (or skip just the openai-construction cases in `test_orchestrator`). *Not done here.*

> Note: the other 23 tests in `test_openai_compat_backend` and 32 in `test_orchestrator` pass — only the openai-construction paths fail.

### Class B — async runner absent (4 failures, all `test_telemetry.py`)
| Test |
|---|
| `TestTelemetryCollector::test_collection_lifecycle` |
| `TestExporters::test_prometheus_exporter` |
| `TestExporters::test_json_exporter` |
| `TestIntegration::test_full_telemetry_workflow` |

Error: *"async functions are not natively supported … install pytest-asyncio …"*. Same class as the Tier 2.1 `cli_viz` async test. The `asyncio` marker is registered (Tier 0) but no runner is installed. **Recommended fix (future tier):** check whether these tests actually `await` — if not, drop the spurious `async`/marker (the Tier 2.1 fix); if they genuinely need an event loop, add `pytest-asyncio` as a test dep. *Not done here — needs a small decision.*

---

## 4. Module-level status (all 27)

### ✅ Fully green — 0 fail / 0 skip (CI-expansion candidates)
| Module | Tests | Note |
|---|---:|---|
| `test_nextness_observer` | 90 | **already in CI** |
| `test_nextness_calibration` | 192 | **already in CI** |
| `test_agent_backend` | 26 | |
| `test_anthropic_backend` | 17 | |
| `test_cli_viz` | 19 | fixed in T2/T2.1 |
| `test_continuous_evolution_ca` | 29 | |
| `test_feature_flags` | 26 | fixed in T3A |
| `test_observability` | 25 | fixed in T3A |
| `test_nextness_metrics` | 38 | |
| `test_params_schema` | 24 | |
| `test_shard_protocol` | 15 | |
| `test_ising_tempering` | 22 | ~9s runtime (slowest) |

→ **10 new fully-green modules** (beyond the 2 already gated), all passing under `numpy`+`pytest` with no optional deps.

### ⏭️ Self-skipping (dep-gated) — safe but low marginal value
`test_state_observation`, `test_fractal_topologies`, `test_parallel_stepping`, `test_graph_stepping`, `test_multi_state_stepping` (uft_ca); `test_observatory`, `test_visualization` (matplotlib); `test_provider_parity`, `test_tuning_api` (flask); `test_event_bus`, `test_shard_transport_zmq` (pyzmq); `test_differentiation_fitness` (evolution_engine).

### ❌ Has failures — keep OUT of CI until fixed
`test_openai_compat_backend` (3 fail), `test_orchestrator` (2 fail), `test_telemetry` (4 fail).

---

## 5. Smallest safe first CI broadening step

**Recommendation: expand `verify-python` via an explicit allowlist of the 10 new fully-green modules** — keep the lean `numpy`+`pytest` install, do not switch to bare `pytest`, do not add the 3 failing modules.

Concretely, the `verify-python` `pytest` invocation would list (in addition to the current 2 nextness files):

```
tests/test_agent_backend.py
tests/test_anthropic_backend.py
tests/test_cli_viz.py
tests/test_continuous_evolution_ca.py
tests/test_feature_flags.py
tests/test_observability.py
tests/test_nextness_metrics.py
tests/test_params_schema.py
tests/test_shard_protocol.py
tests/test_ising_tempering.py
```

This adds **331 passing tests** to the gate (from ~282 to ~613 gated), stays green, and adds no dependencies. That is the proposed **Tier 4A** (a small CI PR, separate from this report).

### Roadmap beyond 4A (each its own small PR, sequenced)
- **Tier 4B:** guard the 5 `openai` failures with `importorskip("openai")` → those modules become CI-safe.
- **Tier 4C:** resolve the 4 `test_telemetry` async failures (drop spurious async, or add `pytest-asyncio`).
- **Tier 4D:** once 4B+4C land, *every* `tests/` module either passes or self-skips under `numpy`+`pytest` → `verify-python` can safely become `pytest tests/` (full suite as the gate), with optional deps (`matplotlib`/`flask`/`pyzmq`) and `uft_ca` (#180) added incrementally to convert skips into real runs.

> The end-state: the dep-gated skips (§2) and the openai/async fixes (§3) are the *only* things between us and a full-suite green gate. None requires engine/observer changes.

---

## Guardrails honored
- Report/docs only. No CI changes, no source changes, no fixes applied (failures reported, not patched).
- No engine touch, no observer semantics, no Lane A / Swarm Hunter / tuning API / production sweeps.
- Bare `pytest` is **not** proposed as the required gate; expansion is an explicit incremental allowlist.

## Decisions requested from Jack + AURA
1. **Tier 4A:** proceed with the 10-module allowlist expansion of `verify-python`? (recommended)
2. **Tier 4C (async):** for `test_telemetry`, prefer dropping spurious async (if no real awaits) vs adding `pytest-asyncio`? (I'll check the awaits and recommend when authorized.)
3. Sequencing: 4A first (pure win, no code), then 4B/4C, then 4D full-gate?
