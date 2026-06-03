# Issue #165 — Coverage-Broadening Triage Plan

**Status:** Triage / planning (docs-only). No code, CI, engine, or observer changes in this PR.
**Issue:** [#165 — CI blind spot: verify job skips the Python test suite](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/issues/165) (state: open, reopened)
**Predecessor:** #167 (`9e745d6`) added a `verify-python` CI job — the *first* pass. This document plans the *remaining* work: broadening that job safely.
**Approach:** Audit first, classify every broken collector, then propose the smallest safe path. Do **not** make bare `pytest` the gate.

---

## 1. Verified current state (audited, not assumed)

| Claim | Verdict | Evidence |
|---|---|---|
| `1d64d0d` (#171) is current `main` tip | ✅ Confirmed | `git log origin/main` |
| #167 added a Python CI job (`fixes #165`) | ✅ Confirmed (partial) | `9e745d6`, `.github/workflows/ci.yml` |
| The CI job runs the "maintained suite" / "275 passed" | ⚠️ **Narrower than stated** | The `verify-python` job runs **only 2 files**: `tests/test_nextness_observer.py` + `tests/test_nextness_calibration.py` |
| #165 is the last queued item | ✅ Confirmed open, `state_reason: reopened` | `issue_read #165` |

**Key correction:** the CI gate today is **2 of 27** test files in `tests/`. "Coverage-broadening" = safely bringing the *other 25 files* (and a decision on the root scripts) into the gate.

---

## 2. Audit methodology

Toolchain: fresh container, `pip install numpy pytest` (mirrors the #167 CI environment exactly — deliberately minimal).

```
python3 -m pytest tests/ --collect-only -q        # maintained suite
python3 -m pytest *_test.py test_phase3_integration.py --collect-only -q   # root scripts
```

Result: **`tests/` → 549 tests collected, 8 collection errors.** Root scripts → 4 hard import errors + 2 collectable-but-legacy.

---

## 3. Classification — the 8 `tests/` collection errors

| Test module | Error | Class | Recommended action |
|---|---|---|---|
| `test_observatory.py` | `No module named 'matplotlib'` | **Missing optional dep** | Add `matplotlib` to CI test deps, **or** guard with `pytest.importorskip("matplotlib")` |
| `test_visualization.py` | `No module named 'matplotlib'` | **Missing optional dep** | Same as above |
| `test_provider_parity.py` | `No module named 'flask'` | **Missing optional dep** | Add `flask`, **or** `importorskip` |
| `test_tuning_api.py` | `No module named 'flask'` | **Missing optional dep** | Add `flask`, **or** `importorskip` |
| `test_state_observation.py` | `No module named 'uft_ca'` | **Build artifact (Rust pyo3 ext)** | `uft_ca` is `crates/uft_ca` (cdylib). Requires a `maturin develop` build step, **or** `importorskip` until the Rust→Py build is wired into CI |
| `test_feature_flags.py` | `No module named 'agent.feature_flags'` | **Import-path / package shadowing** ⚠️ | Module **exists** at `UtilityFog_Agent_Package/agent/feature_flags.py`; a *second* `agent/` package at repo root shadows it. Needs a layout decision — see §5 |
| `test_observability.py` | `No module named 'agent.observability'` | **Import-path / package shadowing** ⚠️ | Same root cause as `test_feature_flags.py` |
| `test_cli_viz.py` | `cannot import name 'InteractiveRenderer'` | **Real (tiny) bug** | `InteractiveRenderer` is defined in `cli_viz/renderer.py:278` and used by `cli.py`, but **not re-exported** from `cli_viz/__init__.py`. One-line fix: add it to the `__init__` import + `__all__` |

### Corrections to the relayed brief (Jack/AURA archaeology)
- **`uft_ca` is NOT a Python collector.** It is a **Rust pyo3 crate** (`crates/uft_ca`, `crate-type = ["cdylib","rlib"]`). It cannot be "collected" by pytest; it must be *built*. The Python-visible failure is only the downstream `test_state_observation.py` import. *(AURA's "architecturally meaningful" instinct was right; the "pathing/deps" guess maps to "needs a Rust build step".)*
- **`cli_viz` is already partially covered** — `tests/test_cli_viz.py` exists. It is **not** legacy display debris; it's a real test blocked by one missing re-export. *(Revises AURA's "almost certainly legacy debris".)*
- **`agent.feature_flags` / `agent.observability` are NOT missing modules.** They exist under `UtilityFog_Agent_Package/`. The failure is a genuine **two-`agent`-package namespace collision** — meaningful, needs a decision, not a blind fix.

---

## 4. Classification — root-level scripts

Default pytest globs match both `test_*.py` and `*_test.py`, so a bare run from repo root would try to collect these.

| Script | Behaviour | Class | Recommended action |
|---|---|---|---|
| `backend_test.py` | imports `requests` + `websockets`, drives a **live server** | **Legacy/manual integration script** (not pytest) | Exclude from collection (see §6) |
| `final_test.py` | same (live websockets/requests) | **Legacy/manual integration** | Exclude |
| `proper_sim_test.py` | same | **Legacy/manual integration** | Exclude |
| `quick_sim_test.py` | same | **Legacy/manual integration** | Exclude |
| `demo_test.py` | imports `sys`/`os`; script-style | **Legacy scratchpad** (superseded by `tests/`) | Exclude / rename |
| `test_phase3_integration.py` | defines `def test_feature_flags()` etc. at root | **Ambiguous** — collectable, possibly superseded by `tests/` | Verify, then either move into `tests/` or exclude — **do not silently delete** |

None of these belong in the CI gate as-is. The safe move is to **scope collection to `tests/`**, not to delete history.

---

## 5. Open decisions requiring human / AURA / Jack sign-off

These are the two genuinely architectural calls — flagged, **not** acted on:

1. **The two-`agent`-package collision.** Repo root `agent/` (has `evolution_engine.py`, `foglet_agent.py`, …) vs. `UtilityFog_Agent_Package/agent/` (has `feature_flags.py`, `observability.py`). Some tests import `agent.X` expecting the *package* one. Options: (a) set `pythonpath`/rootdir to `UtilityFog_Agent_Package`, (b) consolidate the two `agent` packages, (c) make the tests import the fully-qualified path. **AURA: which `agent` is canonical?**
2. **`test_phase3_integration.py`** — is it a current integration test to keep (move into `tests/`) or a superseded Phase-3 scratchpad? **Needs a human/AURA call before move-or-exclude.**

---

## 6. Recommended bounded path (smallest safe steps, in tiers)

Each tier is independently shippable and reversible. **No tier makes bare `pytest` the gate.**

**Tier 0 — Hygiene (tiny, safe, optional config-only PR):**
- Add minimal pytest config scoping collection to the maintained suite and silencing noise:
  ```ini
  # pytest.ini (proposed)
  [pytest]
  testpaths = tests
  markers =
      asyncio: async tests (registers the currently-unknown mark warning)
  ```
  This alone stops the root scripts from ever being bulldozed, with zero source changes.

**Tier 1 — Dependency-gated tests (no source risk):**
- Add `matplotlib` + `flask` to the CI test-deps install, **or** wrap the 4 affected modules with `pytest.importorskip(...)`. Recommendation: `importorskip` (keeps CI lean, tests self-skip when a dep is absent). Brings `observatory`, `visualization`, `provider_parity`, `tuning_api` into the green count safely.

**Tier 2 — One real bug fix (surgical, ~1 line):**
- Re-export `InteractiveRenderer` from `cli_viz/__init__.py`. Unblocks `test_cli_viz.py`. *(Source change — keep in its own small PR, not bundled.)*

**Tier 3 — Decisions first, then implement:**
- Resolve the `agent` namespace collision (§5.1) → unblocks `test_feature_flags`, `test_observability`.
- Decide `test_phase3_integration.py` fate (§5.2).
- Wire `maturin develop` into CI (or `importorskip("uft_ca")`) → unblocks `test_state_observation`.

**Then** broaden the `verify-python` job from 2 files toward `tests/` as each tier lands — never widening past what is green.

---

## 7. Guardrails honored in this PR

- ✅ Docs-only. No engine touch, no observer semantics, no Lane A, no Swarm Hunter, no tuning API, no production sweeps.
- ✅ Bare `pytest` is **not** proposed as the gate.
- ✅ No unrelated cleanup bundled.
- ✅ No broken collector silently deleted — each has a classified, reversible action.

---

## 8. One-line summary for the bridge

> #165's CI job currently gates **2 of 27** `tests/` files. The other 25 fail to collect for **four distinct, well-understood reasons** (missing optional deps ×4, a Rust-build artifact ×1, an `agent` package collision ×2, one missing re-export ×1) plus **6 root legacy scripts** that should be scoped out, not deleted. Path forward is **4 small tiered PRs**, two of which need an architectural decision from AURA/Jack first.
