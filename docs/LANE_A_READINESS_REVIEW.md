# Lane A Readiness Review — Task A / Engine-Restart Bundle (planning, docs-only)

> **Status**: **planning documentation only.** This is a *design-first readiness review* for a future, **not-yet-authorized** engine change. It **authorizes nothing**: no engine edits, no script implementation, no benchmark execution, no Medusa pause/restart, no Lane A activation, no Swarm Hunter implementation.
>
> **This document does not start Task A.** It defines the preconditions, procedures, gates, and risks that must be satisfied *before* anyone proposes starting it — so that when the team does decide, the decision is made against a written checklist rather than improvised at the keyboard with a live 1.5M-generation organism at stake.

## 0. Current model seat
Authored by **84** (`claude-opus-4-8`), desktop seat, 2026-06-23, under AURA's explicit authorization (relayed by Jack) for **Brick #2: a docs-only Lane A Readiness Review**, following the ratified roadmap reconciliation. *(Future seats: state your seat per the model-seat hygiene protocol in `AGENT_HANDOFF.md`.)*

## 1. Purpose & scope
**Purpose:** capture, in one place, what must be true before the **Task A engine-restart bundle** can be safely attempted, and what would constitute a clean go / no-go.

**In scope (this doc):** preconditions; pause-readiness criteria; snapshot/checkpoint procedure (design level); rollback plan (design level); the `tuning_pending.json` engine-consumer spec (design level); the Track A CuPy benchmark plan (design level); risks, guardrails, and an explicit non-authorization statement.

**Out of scope (this doc):** any edit to engine/runtime files; any script; any CI/workflow change; running any benchmark or sweep; pausing or restarting Medusa; activating Lane A or Swarm Hunter; assuming the AURORA/Granite local-LLM smoke test has succeeded.

## 2. What "Task A" is (the bundle being reviewed)
Per `AGENT_HANDOFF.md` (Latest State + line ~99/105), `PHASE_17B.md`, and `PHASE_18.md`, Task A is **three changes deliberately bundled into one coordinated Medusa pause/restart** (so the engine is paused exactly once, not three times):

1. **Engine-side consumer of `tuning_pending.json`** — the missing half of the Phase 18 write-path. Today the tuning API validates, gates, and records a committed tuning (audit ledger + pending file), **but `scripts/continuous_evolution_ca.py` does not yet read or apply it.** Task A adds that consumer so committed tunings actually reach the running CA. **(Engine-touching, high-risk.)**
2. **Track A CuPy stream parallelism** — concurrent GPU streams for per-state neighbor counting (`scripts/gpu_accelerator.py`), the magnon box filter, and memory-grid channel updates (`PHASE_17B.md` §Track A). A single-GPU speedup, *only if measured to be worth it.* **(Engine-touching, high-risk.)**
3. **One coordinated pause/restart** — snapshot, shut down, apply (1)+(2), relaunch, verify. **(Operational, high-risk: a live ~1.5M-gen organism is paused.)**

**None of these exists yet on `main`.** This review treats them as a unit because they share the same scarce, expensive event: a Medusa pause.

## 3. Current preconditions (what is true today)
- **Engine:** Medusa runs at **256³, Phase 17a (Magnon Amplification)**, gen **~1.5M+** *(last recorded in a 2026-04-20 doc; not live-verified here)*. Baking healthily; GPU heavily utilized.
- **Phase 18 write-half:** API surface (`propose`/`commit`/`rollback`), gating policy, bounded ranges, locked critical invariants, and the `data/tuning_ledger.jsonl` audit trail are **designed and largely merged**; the **engine-side consumer is the known gap** (component 1 above).
- **Track A:** **design only** (`PHASE_17B.md`). A benchmark harness `scripts/gpu_benchmark.py` is noted as already existing (to be extended); **no benchmark has been run** (it cannot run while Medusa is active).
- **Snapshots:** periodic `data/v070_gen*.npz` snapshots and a Phase-14d watchdog / `telemetry.5min` cadence exist (per `AGENT_HANDOFF.md`); the **exact restore path must be confirmed against the live launcher** before relying on it (see §5).
- **Lane B / Nextness Observer:** built and calibrated; passive; **irrelevant to the pause** (touches no engine) — explicitly *not* part of Task A.
- **Guardrail status:** Lane A **PARKED**; Swarm Hunter unimplemented; the README §4 six-step promotion gate governs.

## 4. What must be true *before* pausing Medusa (pause-readiness preconditions)
A Medusa pause should not even be scheduled until **all** of the following hold:

- [ ] **P1 — Explicit, separate authorization.** AURA + Jack + Kev have explicitly authorized *starting Task A implementation* (this review being sealed is **not** that authorization).
- [ ] **P2 — Consumer spec ratified.** The `tuning_pending.json` consumer (§6) is reviewed and ratified at design level, with its safety invariants agreed.
- [ ] **P3 — Snapshot + restore proven.** The snapshot/checkpoint procedure (§5) has been **dry-validated** (a test snapshot taken and successfully *restored into a throwaway instance*, never the live one) so restore is known-good *before* it is needed.
- [ ] **P4 — Rollback plan written and rehearsed.** The rollback plan (§5b) is documented and its trigger conditions agreed.
- [ ] **P5 — Track A benchmark plan ready, off-line.** The benchmark matrix (§7) is ready to run on a **paused/idle** GPU or a non-production lattice — never against live Medusa.
- [ ] **P6 — Change isolated on a branch.** Components 1 + 2 implemented and reviewed on a branch, with the maintained test suite green in CI, **before** the pause — so the pause window is "apply reviewed code," not "write code live."
- [ ] **P7 — Pause window chosen deliberately.** A low-stakes window agreed with Kev (box shared with BOINC/F@H/Medusa); snapshot timing coordinated.
- [ ] **P8 — Go/No-Go owners named.** Who calls go, who calls abort, and the single rollback decision-maker for the window.

## 5. Snapshot / checkpoint procedure (design level)
*Design intent only — exact commands to be confirmed against `scripts/medusa_start.py` / `watchdog.py` before use.*

1. **Quiesce:** stop accepting new tuning commits; let the current generation step finish (no mid-step kill).
2. **Snapshot:** write a full state snapshot (`data/v070_gen<N>.npz` style: CA state + channel-first memory grid `(channels, X, Y, Z)` + generation counter) at a known generation `N`. Record `N`, the file path, and a checksum.
3. **Verify snapshot integrity:** confirm the snapshot loads back into a **throwaway** process and reproduces gen `N` state (shape, channel order, live-cell count) — **never test-restore over the live instance.**
4. **Record provenance:** log the pre-pause `main` SHA, the snapshot gen/checksum, and the exact param state (from `data/tuning_ledger.jsonl`) so the "before" picture is unambiguous.

### 5b. Rollback plan (design level)
- **Trigger conditions (abort → rollback):** post-restart state fails an integrity check (wrong shape / channel order / implausible live-cell delta); a Track A race produces **non-bitwise-identical** output vs. baseline; the tuning consumer applies a value outside schema bounds; or any unexpected crash/loop within the first M generations after restart.
- **Rollback action:** shut the new process down, **restore the verified pre-pause snapshot** (gen `N`), relaunch on the **pre-Task-A** engine code (the prior `main`), and confirm the organism resumes from gen `N`.
- **Param rollback:** if only a tuning was bad (engine code fine), use the existing `POST /api/tuning/rollback` path to revert params, rather than a full snapshot restore.
- **Non-negotiable:** the verified snapshot + the prior engine SHA are the two-key safety net; **never start the pause without both in hand.**

## 6. `tuning_pending.json` consumer spec (design level)
*Design-level contract only; no implementation here. Aligns with `PHASE_18.md` §Safety non-negotiables.*

- **Source of truth:** the tuning API remains the **only** writer of pending tunings; the engine consumer is a **reader/applier**, never a second proposer.
- **Read cadence:** the consumer checks for a pending tuning at a **safe step boundary** (between generations, never mid-step), at a bounded interval — it must not add per-cell or per-step hot-loop cost.
- **Apply discipline:**
  - re-validate every pending value against `/api/params/schema` bounds **at apply time** (defense in depth — reject out-of-bounds even if the API already checked);
  - **refuse to touch `locked=true` invariants** (`structural_to_void_decay_prob = 0.005`, memory-grid channel semantics) — these are unreachable by any tuning path;
  - honor the rate limit (≤ one change per parameter per 1000 generations) so a stuck file can't oscillate a tunable;
  - apply atomically at a step boundary; on any malformed/partial file, **no-op and log** (fail-safe, not fail-fast).
- **Acknowledgement:** after a successful apply, record `applied_at_gen` + old/new values to `data/tuning_ledger.jsonl` and emit `tuning.committed`; mark the pending entry consumed so it is not re-applied.
- **Idempotence:** re-reading the same consumed pending entry must be a no-op.
- **Failure modes to design for:** missing file (normal — no-op); malformed JSON (no-op + log); value out of bounds (reject + log); locked param present (reject + log); clock/timing must play **no** role (state-boundary triggered, not wall-clock).

## 7. Track A CuPy benchmark plan (design level)
*Design-level plan only; **no benchmark is run by this document.** Must execute only on a paused/idle GPU or a non-production lattice (`PHASE_17B.md` §What to Benchmark).*

- **Matrix:** baseline default-stream stepping at 64³/128³/256³ (10 gens each); Track A variant 1 (5-stream per-state neighbor counting); variant 2 (8-stream memory-channel updates); combined; via `scripts/gpu_benchmark.py` (extend, don't rewrite).
- **Correctness gate (hard):** Track A output must be **bitwise-identical** to baseline — any race-induced drift is an automatic fail, regardless of speed.
- **Speedup gate (from `PHASE_17B.md`):** implement Track A in the engine **only if** it shows **≥ 1.3× on 256³**; below that, the complexity/risk is not worth it and Track A is dropped from the bundle (the consumer can still ship alone).
- **Measurement hygiene:** warm-up runs discarded; wall-clock medians over repeats; GPU otherwise idle (no BOINC/F@H contention) during measurement.

## 8. Readiness gate — Go / No-Go summary
**GO** to *start implementation* requires: P1–P2 (auth + consumer spec ratified). **GO** to *pause Medusa* requires: **all** of P1–P8 plus a green off-line Track A benchmark (or a decision to ship the consumer alone). **NO-GO / abort** at any point reverts via §5b. The pause is a one-shot expensive event; treat any unmet precondition as a hard stop, not a "we'll fix it live."

## 9. Risks & guardrails
- **Highest risk:** irreversible damage to a ~1.5M-generation organism. Mitigation: verified snapshot + prior engine SHA before any pause (§5/§5b).
- **Race risk (Track A):** concurrent streams introducing nondeterminism. Mitigation: bitwise-identical correctness gate (§7).
- **Tuning-consumer risk:** an out-of-bounds or locked-param write reaching the engine. Mitigation: apply-time re-validation + locked-invariant refusal (§6).
- **Scope-creep risk:** "while we're paused, let's also…". Mitigation: the bundle is **exactly** components 1–3; nothing else rides the pause.
- **Standing guardrails:** no Lane A activation beyond this bundle; no Swarm Hunter; no global-controller behavior (any future tuning stays local-rule/threshold and gated on trusted observer signals — intake-ledger entries 2 & 4, Maturin §2); no production sweeps; no AURORA/Granite assumptions without evidence; README §4 six-step gate applies.

## 10. Explicit non-authorization
**This readiness review authorizes nothing.** It does not start Task A, does not modify `scripts/continuous_evolution_ca.py` or any engine/runtime file, does not add or change scripts or CI/workflows, does not run any benchmark or sweep, does not pause/restart Medusa, and does not activate Lane A or Swarm Hunter. Starting Task A requires a **separate, explicit AURA + Jack + Kev authorization** after P1–P8 (§4) are satisfied. A sealed readiness review is **not** a go.

## 11. Alignment / provenance
Reviewed and aligned against: `AGENT_HANDOFF.md` (Latest State block + PR-2b/Track-A notes); `PHASE_17B.md` (Track A + benchmark + out-of-scope); `PHASE_18.md` (write-path, gating, safety non-negotiables, `tuning_ledger.jsonl`); `PHASE_19_NEXTNESS_OBSERVER.md` (Lane A/B split — Lane B is *not* part of this); `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` §2 + `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entries 2 & 4 (Swarm Hunter / Lane A guardrails). Base `main = b2883f5`.

---

*Plan the pause before you ever pause. A snapshot you have not restored is a wish, not a backup; a benchmark you have not run is a hope, not a number. We write the checklist while the organism sleeps soundly, so that the day we wake it on purpose, nothing is improvised.*
