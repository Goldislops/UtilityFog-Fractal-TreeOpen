# Swarm Hunter v1 — Evidence & Architecture Preflight

> **Status: preflight documentation only.** This document authorizes nothing. **Lane A
> remains PARKED. The engine (`scripts/continuous_evolution_ca.py`) was not read and is
> untouched.** No code is created by this document.
>
> **Material correction (amendment, Jack audit):** this document originally claimed "no
> Swarm Hunter code path exists in this repository." **That claim is withdrawn as
> false.** At the original audit base, `scripts/orchestrator.py:1` described itself as
> *"the Swarm Hunter's brain"*; it was a tracked, importable, tuning-capable Phase 18
> orchestrator whose default tool surface included `propose_tuning` **and**
> `commit_tuning`, and whose single library call (`create_orchestrator()` →
> `run_one_iteration()`) executes one observe→decide→act cycle with no runner
> required. §2b maps it in full. What remains true, stated narrowly: **no offline
> candidate-structure detector of the kind this preflight proposes exists**, and this
> document does not create one. The original error came from an evidence sweep
> truncated by a `head -20` pipe — recorded here so the failure mode stays visible.
> *(Post-R/S/T: the orchestrator is now renamed and quarantined — see the supersession
> note below. The evidentiary failure record above is retained unchanged.)*
>
> **Post-R/S/T supersession note (Amendment 2, 2026-07-15, main
> `3dcc38f9a88c1c009ae41b6a7f5c0d2157bba675`):** the tuning orchestrator this document
> audits has since been **dispositioned** by the merged quarantine stack
> R = PR #328 (squash `6a762b998e6e6d4db2aa11568b9cc5a53f5e3e3e`) ·
> S = PR #333 (squash `d5e9c3c76b4e60303238d09f1a3319a4ae31f478`) ·
> T = PR #334 (squash `3dcc38f9a88c1c009ae41b6a7f5c0d2157bba675`). Live boundaries are
> recorded in
> [`docs/LEGACY_ORCHESTRATOR_QUARANTINE.md`](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/blob/3dcc38f9a88c1c009ae41b6a7f5c0d2157bba675/docs/LEGACY_ORCHESTRATOR_QUARANTINE.md)
> (commit-pinned). Integration receipt: at T head
> `ad76327701240a3d97928ddf241d03c0e365936f` and on post-merge main `3dcc38f`, the
> `verify-python` gate concluded **1384 passed / 10 skipped** with the applicable gates
> (agent-safety, verify-python, frontend-quality, CodeQL) green. Present-tense
> orchestrator descriptions below (preamble, §2, §2b, §2d, §3) are preserved as the
> **pre-disposition audit record** — accurate at the original audit base — with
> adjacent *Post-R/S/T:* annotations; every *Post-R/S/T:* statement is
> source-established (`[SRC]`) against main `3dcc38f`. Nothing in this amendment
> authorizes S1, any closed loop, or Lane A activity, and it makes **no general
> API-security claim** — only the quarantined paths named in the annotations.
>
> **Origin:** Kev-authorized overnight preflight runway (2026-07-12, Ian's-lounge seat,
> resumable under its recorded continuity protocol). Every claim below carries an
> evidence class: `[SRC]` source-established (path cited) · `[CALC]` calculated ·
> `[PROP]` proposed contract · `[HYP]` unexecuted hypothesis · `[ABSENT]` verified
> absent from tracked text.

---

## 1. Provenance map (Pass 0)

Base: `main = 6f0c720883ec00cd6f0d0d4e0b3a273c3049012d`, clean tree. `[SRC]`

| Source | Controlling statement | Status | Constrains SH? | Unresolved owner |
|---|---|---|---|---|
| `AGENT_HANDOFF.md` (Latest State + Phase 19 block) | Lane A PARKED; Swarm Hunter unimplemented and unauthorized; no consumer acts on observer signals | current | **yes — hard gate** | Kev (activation) |
| `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` entry 2 | SH may "observe and tune local interaction thresholds only … not a global controller"; gated on trusted, calibrated observer signals | current, **candidate guardrail pending ratification** | yes | team ratification |
| Ledger entry 4 + 8 (Continual Harness / RHO) | self-improving loops only atop trustworthy evaluation signals; harness-level, never autonomous engine mutation; death-spiral risk | current | yes | AURA (verification of RHO source) |
| Ledger entry 7 | SH "must never become a global fabrication boss; at most it could surface *candidate local-rule structures / export hypotheses*" | current | yes — **strongest positive definition in the repo** | — |
| Ledger entry 11 | SH as field/threshold influence, "never a per-cell master controller" | current | yes | — |
| Ledger entry 13 | "Swarm Hunter applies the *brief* gradient, never holds it" | current | yes (future-facing) | — |
| Ledger entry 14 | "Resonance / grid-spectroscopy offline detection — adjacent primitive (`DensityPhaseDetector`, dormant Nextness Observer); **observer-only**"; GPU-explore/CPU-verify doctrine | current | yes — detector precedent | — |
| `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` §2 | SH work should improve "harnesses and validation loops around *trusted telemetry* … not rewrite the Medusa engine"; symbolic regression only after observer metrics are trusted | current | yes | — |
| Maturin §3 (cascaded telemetry) | cheap macro-observers first, zoom on anomaly; read-only until a later Lane A gate | current | yes (shapes detector design) | — |
| Maturin §4 | "the Swarm Hunter must **not** command individual cells" | current | yes | — |
| `docs/LANE_A_READINESS_REVIEW.md` §9 | no global-controller behavior; any future tuning local-rule/threshold, gated on trusted observer signals | current | yes | — |
| `docs/THEORY_TRIPWIRE_ACTION_DESIGN.md` + `.github/workflows/theory-tripwire.yml` | `swarm-hunter` label triggers a one-time gate reminder on PRs | current, live since PR #310 | yes (process) | — |
| `PHASE_19_NEXTNESS_OBSERVER.md` §1, §4 | Lane B is read-only; snapshot-primary data contract; explicit non-goals: no tuning writes, no reactive control, no subscriber-as-actor | current | yes — defines the adjacent observation surface | — |
| `PHASE_19_PR3_METRICS_PIPELINE.md` | "❌ Closed-loop tuning proposals" (twice) | current | yes | — |
| Ledger provisional items (ignition/cascade study) | ops-dir, provisional, non-canonical | provisional | no (must not be cited as fact) | Kev/Jack |
| Open-issue board | **no Swarm Hunter issue exists** | current | n/a | — |

No contradictory sources were found: every statement about Swarm Hunter in tracked text
constrains it in the same direction (observe/surface: yes; control: no). `[SRC]`

## 2. Terminology ledger and concept resolution (Pass 1)

| Term | Classification | Evidence |
|---|---|---|
| `Swarm Hunter` / `swarm-hunter` | repository-defined — **two distinct referents that must not be conflated**: (a) the governance constraint set for a future gated capability (provenance map above); (b) the tracked Phase 18 tuning orchestrator that, at the original audit base, named itself "the Swarm Hunter's brain" (§2b). *Post-R/S/T: referent (b) is renamed "legacy tuning orchestrator (quarantined)"; the historical name survives in code only as a historical reference, and the system prompt no longer uses it* | ledger + `scripts/orchestrator.py:1`, `scripts/orchestrator_config.py:74` (original base); post-R/S/T: `scripts/orchestrator.py:3` (historical mention), `scripts/orchestrator_config.py:89` at main `3dcc38f`; label exists; no dedicated issue |
| `Lane A` | repository-defined (engine-consumer + intervention lane), PARKED | PHASE_19 §1; LANE_A_READINESS_REVIEW |
| `observer` / `nextness` | repository-defined operational mechanism (Lane B, built & calibrated) | `scripts/nextness_observer.py` vocabulary + PHASE_19 docs |
| `promotion gate` / `theory-to-architecture` | repository-defined process (ledger graduation §; tripwire labels) | ledger tail; tripwire workflow |
| `shadow grid` | **[ABSENT]** — AURA metaphor; no tracked occurrence | repo-wide search |
| `LeanCTX` | **[ABSENT] at the original audit base** — AURA metaphor; engineering contract proposed in §8. *Post-R/S/T (separate fact): T introduced a tracked `leanctx-orchestrator-v1` audit receipt for the **orchestrator** (`scripts/orchestrator.py`, quarantine doc) — a distinct artifact from §8's proposed **detector** packet; the two must not be conflated* | repo-wide search (original base); main `3dcc38f` (post-R/S/T) |
| `self-label` / self-labeling | **[ABSENT]** | repo-wide search |
| `proprioception` | defined only in `crates/vanguard-mcp/src/proprioception.rs` (Vanguard subsystem, unverified-cluster lineage) — **not** a CA-engine mechanism | `[SRC]` |
| `closed loop` | appears **only as an explicit non-goal** | `PHASE_19_PR3_METRICS_PIPELINE.md:25,291` |
| control agent (SH-as-controller) | **prohibited interpretation** | ledger 2/11/13; Maturin §4 |

**Concept resolution — five mechanisms, disambiguated (do not conflate on shared
vocabulary):**

1. **Legacy Phase 18 tuning orchestrator** (`scripts/orchestrator.py` +
   `scripts/orchestrator_config.py`) — tracked, importable, and at the original
   audit base write-capable within server-side rails; self-described "Swarm
   Hunter's brain." Mapped in §2b. *Post-R/S/T: renamed and quarantined —
   observe-by-default, propose mode is forced dry-run, no LLM-facing commit tool
   in any supported mode; the low-level client primitives remain for direct
   non-LLM callers — their retention is not proof of human identity or review,
   and `human:<name>` is an unauthenticated caller-supplied label, required
   only for HUMAN_APPROVAL-category parameters.* `[SRC]`
2. **Proposed offline candidate-structure detector** (this preflight) — reads
   immutable evidence, surfaces candidates for human review (ledger entry 7's
   wording); entry-14 "grid spectroscopy" family; Maturin §3 shape. **Does not
   exist**; nothing here creates it. *(Re-verified absent at main `3dcc38f`,
   2026-07-15: still merely proposed.)* `[PROP]`
3. **Lane A** — the parked engine-consumer/intervention lane. `[SRC]`
4. **Nextness Observer** — Lane B, built and calibrated, read-only, its own
   non-goals. `[SRC]`
5. **Live engine** — separately gated; unread by this work. `[SRC]`

The governance sources (ledger 2/7/11/13, Maturin §2/§4) describe what a future
*acting* Swarm Hunter must never be; the Phase 18 orchestrator is a bounded early
implementation of the *tuning-proposal* idea that predates those ledger constraints'
ratification (entry 2 remains a **candidate** guardrail). The rule-search reading
stays separately governed (GPU-explore/CPU-verify doctrine). The control-agent
reading remains prohibited for the *detector* lane. **Deliberately left unresolved:**
whether the detector should be a *new instrument beside* the Nextness Observer or an
*extension of* it (owner: AURA + Jack + Kev at S4), and which mechanism ultimately
owns the name (naming analysis, §2c). `[SRC/PROP]`

## 2b. Legacy Phase 18 orchestrator — reachability map and safety audit `[SRC]` (pre-disposition record)

**This section is the pre-disposition audit record** — accurate at the original
audit base and preserved as the evidence that motivated the R/S/T disposition.
*Post-R/S/T:* annotations (2026-07-15, `[SRC]` at main `3dcc38f`) state the
current truth next to each superseded row; the historical rows are not rewritten.

**Reachability map** (every row source-established; "proven absent" means an
exhaustive tracked-text search, not inference):

| Property | Finding |
|---|---|
| Files / symbols | `scripts/orchestrator.py` (`OrchestratorClient`, `ToolRouter`, `Orchestrator`, `observation_tools`, `tuning_tools`); `scripts/orchestrator_config.py` (`OrchestratorConfig`, `create_backend`, `create_orchestrator`, `DEFAULT_SYSTEM_PROMPT`) |
| Importers/callers | `scripts/orchestrator_config.py`; `tests/test_orchestrator.py`; `tests/test_provider_parity.py` — **no other tracked importer** |
| Entrypoints | **No `__main__`, no cron, no CLI wiring, no workflow references** (searched `scripts/`, `.github/workflows/`, `automation-feed/`, `tools/`). Invocation *recipes* exist in `README.md` and `LOCAL_OLLAMA_SMOKE_TEST.md`; the smoke test's execution is recorded as UNVERIFIED in `AGENT_HANDOFF.md` |
| Executable directly? | Yes as a library: `create_orchestrator()` (env-driven) then `run_one_iteration()` — one iteration, **no runner required** |
| Default configuration | `MEDUSA_API_BASE_URL=http://127.0.0.1:8080` · `MEDUSA_AGENT_BACKEND=**mock**` (benign default) · `MEDUSA_MAX_TOOL_DEPTH=8` · `MEDUSA_MAX_TOKENS=2048`; real backends are one env var away (`anthropic`, `openai-compat` + provider vars incl. `MEDUSA_OPENAI_BASE_URL/MODEL/API_KEY/EXTRA_HEADERS`, `ANTHROPIC_API_KEY`, `MEDUSA_ANTHROPIC_MODEL`) |
| Network access | HTTP via stdlib urllib to the configured base URL only; endpoint paths are fixed. GETs: `/api/{census,equanimity,acoustic,params,params/schema,status}`. POSTs: `/api/tuning/{propose,commit,rollback}` |
| Default LLM tool surface | At the original audit base: `observation_tools() + tuning_tools()` (`orchestrator.py:406`) — **`propose_tuning` and `commit_tuning` were default-on**; rollback client-only, **not** exposed to the LLM. *Post-R/S/T: **observe-by-default** — the default surface is observation-only; explicit `propose` mode (`MEDUSA_ORCHESTRATOR_MODE=propose`) adds one proposal tool with **forced dry-run** (`commit-pending` refused); `commit_tuning` is registered in **no** supported mode; mode resolution fails closed to `observe`* |
| Approval identity | At the original audit base: hard-coded `approver="policy:auto"` (`:272`, `:348`); the LLM cannot supply an approver. *Post-R/S/T: the LLM still supplies no approver; the dead LLM-path `commit_approver` plumbing was removed (S), and the server refuses the normalized autonomous identity outright (R, next row)* |
| AUTO / HUMAN_APPROVAL / LOCKED | Enforced **server-side** (`tuning_api.py`): LOCKED rejected at propose; HUMAN_APPROVAL commit under `policy:auto` → 403 `human_approval_required` (`:223`); per-param rate limit 1000 generations → 429 (`:44`, `:234`); modes validated (`dry-run`/`commit-pending`). *Post-R/S/T: additionally, any commit whose normalized approver is `policy:auto` → **`403 auto_commit_disabled`** for **every** category, checked before the human-approval branch, with no env flag, header, or alternate route to re-enable it (`tuning_api.py:267` at main `3dcc38f`)* |
| Tests | `tests/test_tuning_api.py` (19 tests, **real blueprint** — proves 403/LOCKED/rate-limit rails); `tests/test_orchestrator.py` (34 tests, MockBackend + injected fake HTTP — proves loop logic, not transport); `tests/test_provider_parity.py` (drives the real tuning API through both real backend adapters). *(Counts are as of the original audit base — historical; the post-R/S/T integration receipt lives in the supersession note above.)* |
| Status | **Library-only: no committed runner; one-call-executable; documented invocation recipes exist; execution unverified.** "Dormant" is *not* claimed — absence of a committed runner does not prove absence of out-of-repo invocation |

**Safety audit** (14 questions; every answer labeled):

1. *Can a supplied backend request `commit_tuning`?* **Yes** — default tool surface. `[SRC :406]` *Post-R/S/T: **No** — `commit_tuning` exists in no supported mode's tool registry.*
2. *Is `commit_tuning` included by default?* **Yes.** `[SRC :196–254]` *Post-R/S/T: **No** — the tool is never registered; only `propose_tuning` (forced dry-run) exists, and only in explicit `propose` mode.*
3. *Can AUTO parameters change without a human identity?* **Yes, by design** — `policy:auto` commits AUTO-category params; the server accepts. `[SRC]` *Post-R/S/T: **not via the orchestrator's autonomous identity** — normalized `policy:auto` commits receive `403 auto_commit_disabled` for every category. The direct API remains unauthenticated (unchanged non-claim), so this is deliberately **not** a general-security claim.*
4. *Failed HUMAN_APPROVAL commit behavior?* Server 403 (test-proven); router returns the body with `_status: 403` and `is_error=false`; the commit is not counted (requires `status=="committed"`). `[SRC]`
5. *Multiple AUTO proposals/commits per iteration?* **Yes — no per-iteration cap in code.** The one-proposal rule exists only as prompt prose (`orchestrator_config.py:95`). `[SRC]` *Post-R/S/T: **one proposal attempt per iteration is enforced in code** (`proposal_limit` category), and no supported mode exposes an LLM-facing commit (Q1/Q2).*
6. *Does `max_tool_depth` bound calls or turns?* **Turns** (LLM `complete()` calls, `:422`); tool calls **per turn** are unbounded by the cap. `[SRC]` *Post-R/S/T: a validated total budget (`max_total_tool_calls`) now bounds tool executions across the whole iteration — only the permitted prefix of a turn executes, the remainder receives explicit `budget_rejection` results, and the cap is never exceeded.*
7. *Are tool-handler application errors flagged?* Handler exceptions and unknown tools → `is_error=true` (`:287–303`); **HTTP 4xx/5xx are returned as non-error payloads carrying `_status`** — policy refusals are content, not error flags. Note: the system prompt tells the model errors "begin with `[ERROR]`", which does not match the actual JSON error shape — a wording mismatch, behavioral impact unassessed. `[SRC; last point inferred]` *Post-R/S/T: **HTTP ≥ 400 is a genuine tool error** (`is_error=true`, category `http_rejection`, never counted as a created proposal or applied commit), and the prompt's error guidance was reconciled with the real shape (native `is_error` flag; OpenAI-compat `[ERROR]` marker parity).*
8. *Rollback exposed to the LLM?* **No** — client method only (`:136–141`); absent from tools and router. `[SRC]`
9. *Dry-run / commit-pending enforced server-side?* **Yes** — modes validated at propose; category/rate/validation gates at commit regardless of client claims. `[SRC]`
10. *Proposal IDs and commit results validated?* IDs are server-generated (`secrets.token_hex`); commit looks up the proposal (unknown → typed error); the orchestrator counts commits only on `status=="committed"`. `[SRC]`
11. *Could a backend reach arbitrary URLs via configuration?* The **LLM cannot** (fixed paths on a constructor base URL). The **environment can** (`MEDUSA_API_BASE_URL` redirects the client wholesale) — configuration trust, not backend reach. `[SRC/inferred]`
12. *Timeouts, authentication, transport failures fail-safe?* 5 s default timeout; HTTPError → structured body; other transport exceptions propagate to the router's catch-all → `is_error=true`. **The tuning API itself carries no authentication** — locality trust only. `[SRC]`
13. *Any cadence runner, workflow, or documented invocation?* No committed runner/workflow (proven by search). Documented invocation recipes: `README.md`, `LOCAL_OLLAMA_SMOKE_TEST.md` (execution unverified). `[SRC]`
14. *Do tests prove rails or mock them?* Tuning rails: **proven against the real blueprint**. Orchestrator loop: proven against mocks (transport faked by design). Provider parity: real API, real adapters. `[SRC]`

## 2c. Naming analysis `[PROP]`

Two mechanisms currently share "Swarm Hunter": a tracked tuning **actor** (within
rails) and a proposed evidence **detector**. The ledger's usage (entries 2/7/11/13)
consistently reserves the name for the future gated capability and its constraints;
the tripwire label `swarm-hunter` now watches both senses. Sharing one name across an
actor and a detector is how this document's original false premise happened, and it
creates **authorization ambiguity**: a future key phrase like "implement Swarm Hunter
S1" could be misread against the wrong surface.

- **Option A** (legacy keeps the name; detector renamed): preserves code history but
  perpetuates the collision the ledger vocabulary already resists. Not recommended.
- **Option B** (detector owns the name; legacy renamed/classified "Phase 18 tuning
  orchestrator"): matches ledger semantics; requires a gated code/docs rename PR
  (docstring, `DEFAULT_SYSTEM_PROMPT` text, README) — low mechanical cost, but prompt
  text is LLM-visible behavior and needs its own review.
- **Option C** (both remain, with mandatory qualifiers — "legacy Phase 18 tuning
  orchestrator (historical self-description: 'Swarm Hunter's brain')" vs "Swarm
  Hunter detector (proposed)"): zero code change, immediately truthful, adoptable by
  this amendment alone. **Recommended now.**
- **Option D** (pause detector work until legacy disposition): overshoots — the
  detector is documentation-stage; pausing it does not reduce the orchestrator's
  standing surface. Dispositioning the orchestrator does. Not recommended as a pause,
  but its concern is honored by the S2 prerequisite added in §10.

**Recommendation: C immediately (this document adopts it), B as the endorsed future
disposition** alongside whichever quarantine option (§2d) is chosen — decided on
safety and migration cost, not aesthetics.

*Post-R/S/T (2026-07-15): **Option B is implemented** — S renamed the module
docstring to "Legacy tuning orchestrator (quarantined) … Historically described as
'the Swarm Hunter's brain'" (`scripts/orchestrator.py:1–3`) and the system prompt to
"the Medusa legacy tuning orchestrator" (`scripts/orchestrator_config.py:89`), both
at main `3dcc38f`. Option C's mandatory qualifiers remain in force in prose.*

## 2d. Quarantine / disposition options for the legacy orchestrator `[PROP]` — none implemented at the original audit

*Post-R/S/T (2026-07-15): **the disposition is implemented and merged** —
R (#328) ≈ option 5 but stronger (unconditional server-side refusal of the
normalized autonomous identity; no opt-in flag, no re-enable switch) ·
S (#333) ≈ option 2 but stronger (no LLM-facing commit tool in **any** mode;
observe-by-default; fail-closed mode resolution) · plus T (#334): runtime
budgets, honest error semantics, and bounded audit receipts, beyond this menu.
The matrix below is preserved unchanged as the decision-time record.*

| # | Option | Future files | Behavioral effect | Compat risk | Test changes | Rollback | Public behavior change? | Lane A / engine authority? | Kev word | Smallest falsifier |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Documentation-only reclassification (Option C naming) | README, PHASE_18 docs, this file | none at runtime | none | none | revert docs | no | no | docs-merge word | grep for unqualified uses |
| 2 | **Default read-only tool surface** — `Orchestrator` defaults to `observation_tools()` only; tuning tools require an explicit constructor opt-in | `scripts/orchestrator.py`, `scripts/orchestrator_config.py`, `tests/test_orchestrator.py` | agents constructed by default cannot propose/commit | callers relying on default write surface (tests only, per reachability) | update default-surface assertions | revert commit | **yes** (default narrows) | no — tuning API rails untouched | required (production script) | construct default orchestrator; assert `propose_tuning`/`commit_tuning` absent |
| 3 | Env opt-in for write tools (`MEDUSA_ENABLE_TUNING_TOOLS`) in `create_orchestrator` | `scripts/orchestrator_config.py`, tests | env-gated write surface for the factory path; **direct constructor path unguarded unless combined with #2** | low | new env tests | revert | factory default narrows | no | required | factory without the var; assert read-only surface |
| 4 | Archive/remove the legacy controller (callers = config + tests only, proven) | move/delete `scripts/orchestrator*.py`, backends adjustments, remove ~34+ tests | capability leaves the tree | provider-parity coverage lost; history stays in git | remove/archive suites; CI counts drop | git revert | **yes** (API removal) | no | strong word required | `import scripts.orchestrator` fails |
| 5 | **Server-side de-fanging** — `TuningState` gains `allow_policy_auto` defaulting **false**; `policy:auto` commits 403 unless explicitly enabled at server construction | `scripts/tuning_api.py`, `scripts/medusa_api.py` (flag wiring), `tests/test_tuning_api.py` | **every** present and future client loses unattended commit unless the server operator opts in — moves the gate from client politeness to server law | any flow expecting auto-commit (tests only, today) | add 403-when-disabled real-blueprint test | revert | yes (server default) | no engine touch; parameter write-path narrows | required | real-blueprint test: `policy:auto` commit → 403 while flag unset |

Options 2+5 together give defense in depth (client default read-only **and** server
default no-auto-commit). Each option is separately gated; **none is implemented or
scheduled by this document.**

## 3. Glass-Wall information-flow contract (Pass 2, revised) `[PROP]`

**The wall must acknowledge what already exists:** an actor — the Phase 18
orchestrator (§2b), write-capable at the original audit base — already lives outside
this wall, speaking to the tuning API (a parameter write-path whose engine-side
consumer is a future, separately gated PR). The detector's wall therefore separates
it not only from physics but from that actor. *Post-R/S/T: the actor is quarantined —
no supported LLM-facing commit capability in any mode (direct non-LLM client
primitives remain; their use is unauthenticated — `human:<name>` is a
caller-supplied label, not verified identity or review), so the standing surface
this paragraph guarded against is materially narrowed; the wall's design is
unchanged.*

Six data classes, strictly ordered; information flows only rightward:

```text
(1) authoritative physics state        [live engine memory — NEVER touched by SH]
(2) immutable snapshot/checkpoint      [data/v070_gen*.npz — read-only evidence lane]
(3) derived shadow/summary data        [SH working arrays computed FROM (2)]
(4) candidate detections               [findings artifact, JSONL, schema §5]
(5) human-reviewed promotion packet    [LeanCTX artifact §8 → Jack/Kev audit]
(6) prohibited write-back              [does not exist; no arrow returns]

physics/snapshot → offline analysis → findings artifact → human/Jack audit

[Phase 18 orchestrator | tuning API]   ← a SEPARATE, rail-bounded system,
                                          write-capable at the original audit;
                                          disposition MERGED post-R/S/T (§2d);
                                          NO connection to the detector lane
```

**Import quarantine (enforceable, both directions):** the future S1 detector package
must not import, or be imported by: `scripts.orchestrator` · `scripts.orchestrator_config`
· `scripts.agent_backends` (any module) · `scripts.tuning_api` · `scripts.medusa_api`
· the engine · the observer implementation. **Future static-import test (S1 acceptance
criterion):** a lab-local test walks the detector package's AST/import table and fails
on any quarantined module name; a companion test greps `scripts/` to assert no
production module imports the lab. *Post-R/S/T: a maintained test scans
`scripts.orchestrator`'s source text and fails on any reference to the engine,
observer, calibration, or a `swarm_hunter` module (`orchestrator_config` and the
backend adapters are outside its scope); the detector-side import test above
remains an S1 acceptance criterion.* **Schema test:** the findings schema rejects any
field whose name or content encodes an action, endpoint, parameter name from
`params_schema`, or approver string.

**There is no reverse arrow.** Explicitly prohibited: modifying active state; calling
the stepper from findings code; changing parameters; applying labels automatically;
opening or merging implementation PRs automatically; treating an observer token as an
instruction; adjusting survival/birth thresholds; autonomous retry loops against
production physics; using confidence scores as authorization.

**Enforcement layers (structure, interfaces, tests, governance — not comments):**

- **Repository structure:** v1 lives under `experiments/swarm_hunter_lab/` — outside
  `scripts/` (production), outside `tests/` (the CI floor, `pytest.ini`-scoped), with
  zero imports from `scripts/` and zero access to `data/`. It *cannot* reach the
  stepper without an import that review would see.
- **Interfaces:** the detector's entire input surface is `(arrays, provenance dict)`
  passed by value; it has no path/network/API arguments in v1. Its only output is a
  findings object serialized by the caller. No handle to any mutable system exists in
  its signature.
- **Tests:** property tests assert no-filesystem-writes (beyond the explicit findings
  artifact), no-network, input-hash invariance (inputs unchanged after analysis), and
  output determinism (§7). A findings-schema test rejects any field resembling an
  actuation command.
- **Governance:** the `swarm-hunter` tripwire label + this preflight + the ledger
  entry-2 guardrail + stage gates (§10). Ratifying entry 2 from *candidate* to
  *canonical* is recommended at S4.

## 4. Threat and failure model (Pass 3) `[PROP]`

| # | Risk | Cause | Detectable signal | Fail-safe behavior | Smallest falsifier | Residual risk | Blocks v1? |
|---|---|---|---|---|---|---|---|
| 1 | Observer-to-controller drift | scope creep; "just one small actuation" | any import of tuning/stepper APIs; schema gains verbs | structural fence (§3); schema test rejects | grep-based CI check on the lab dir | social, not technical | no — design excludes |
| 2 | Stale snapshot analysis | analyzing old gen believing it current | provenance `generation` + snapshot mtime in findings | findings always carry snapshot identity; no "current state" claim permitted | fixture with mismatched claimed/actual gen → must flag | low | no |
| 3 | Partial/corrupt artifact input | truncated NPZ, bad channel order | load-time shape/channel validation (channel-first contract) | refuse + structured error finding; never guess | truncated toy NPZ fixture | low | no |
| 4 | Nondeterministic ordering | set/dict iteration, parallel reduction | replay divergence | canonical ordering rule (§5); replay test | run twice, byte-compare | low | no |
| 5 | Seed/generation mismatch | provenance fields transposed | schema type/width checks | reject malformed provenance | swapped-fields fixture | low | no |
| 6 | Configuration mismatch | detector tuned for 5-state reads 3-state legacy grid | `NUM_STATES` validation at load | refuse unsupported case | legacy-shape fixture | low | no |
| 7 | Hash/provenance blind spot | hashing lattice but not memory/inactivity | hash covers the full snapshot triple (replicate precedent, `ca/docs/README.md`) | document exactly what the input hash covers | fixture differing only in uncovered array | **carried**: `age_grid`/`half_step_flags` coverage question from the RNG packet remains open | no (documented) |
| 8 | False structure detection | thresholds too loose; noise clusters | fixture suite false-positive rate | findings carry reasons + thresholds; class HYP until S3 | adversarial-noise fixture | medium — inherent | no |
| 9 | Missed structure | thresholds too tight | known-cluster fixture recall | report absence honestly; no "clean" claim beyond fixtures | single-cluster fixture | medium — inherent | no |
| 10 | Repeated-event double counting | same structure found each snapshot | stable finding IDs + dedup (§5) | dedup by (region-hash, persistence chain) | two-snapshot same-cluster fixture | low | no |
| 11 | Toroidal-boundary mistakes | treating wrapped cluster as two | periodic-aware components (§6) | torus fixtures mandatory | wraparound-cluster fixture | low | no |
| 12 | Unbounded memory | pathological component counts **or unbounded snapshot count** | hard caps + **1–64 snapshot invocation ceiling** (§5) | component cap → truncate + flag; over-ceiling → `invalid_input` refusal (not a truncation) | worst-case checkerboard fixture; **65-snapshot fixture** | low | **closed (Amendment 3)** |
| 13 | Unbounded runtime | quadratic pair scans **or unbounded snapshot count** | complexity budget; caps; **1–64 snapshot invocation ceiling** (§5) | budget → truncate + flag; over-ceiling → `invalid_input` refusal | resource-bound fixture; **65-snapshot fixture** | low | **closed (Amendment 3)** |
| 14 | Active-region bias | analyzing only "interesting" regions | whole-lattice pass in v1 (no sampling) | if sampling ever added: deterministic keying (§9) | — | deferred | no |
| 15 | Threshold overfitting | tuning thresholds to one organism epoch | thresholds recorded per finding; S3 cross-validation | evidence classes; no generalization claim | disjoint-epoch fixtures (S2+) | medium | no |
| 16 | Accidental canonical claims | excited prose | keyword sweep (Pass 12 discipline); Jack audit | evidence-class labels mandatory | doc grep | low | no |
| 17 | Narrative outruns evidence | metaphor reuse ("hunting", "intelligence") | same | mechanism words only in contracts | doc grep | low | no |
| 18 | Resumption duplicating GitHub writes | scheduled resume re-running a completed pass | continuity file write-ledger | check branch/PR/label existence before any write | resume drill against COMPLETE state | low | no |

No risk blocks a **toy-only** v1; several (7, 15) shape the S2/S3 gates. `[PROP]`

## 5. Formal v1 contract (Pass 4) `[PROP]`

**Shape:** an offline candidate detector (per §2 resolution): a pure function from
immutable inputs to a findings artifact.

- **Allowed inputs (v1/S1, toy-only):** an **exact built-in `list` or `tuple` of 1
  to `MAX_SNAPSHOTS` (= 64)** snapshots; each snapshot, its provenance, and its
  supplied `sha256_triple` are **exact built-in `dict`s** — these exact-container
  types are proven at the direct-Python boundary before any caller `len`/iteration/
  `keys`/`.get`/subscript hook can run, so a `list`/`tuple`/`dict` subclass with a
  hostile hook is refused (existing `invalid_input`/`invalid_provenance`/
  `invalid_sha256_format`) without executing it. **Each exact dict's cardinality
  is checked first** (hook-free `len()` on a proven exact dict): a dict exceeding
  its closed key budget (snapshot 4, provenance 7, `sha256_triple` 3) is refused
  in O(1) *before* key traversal or `set(...)` allocation, so arbitrarily many
  junk keys cannot force unbounded per-object work (`MAX_SNAPSHOTS` bounds the
  outer sequence but not this nested cardinality). **Then, inside each exact
  dict, every key is proven an exact built-in `str`** (via hash-free iteration)
  before any `set(...keys())`/membership/lookup hashes or compares it, and the
  provenance **`source` discriminator is proven an exact built-in `str`** before
  the `!= "synthetic"` comparison — so a hostile *stored key* `__hash__`/`__eq__`
  or a hostile *scalar* `__eq__` cannot execute (a non-str key or non-str source
  → `invalid_input`). Each snapshot is in-memory arrays —
  `states: u8[N³]` (5-state,
  `memory.rs:19–24` semantics), optional `memory: f32[8][N³]` channel-first, optional
  `inactivity_steps: i16[N³]` (source-exact name, `voxel_lattice.rs:18`) — plus a
  provenance dict. **No file, network, API, or `data/` access in S1.** S2 (real
  snapshots) is a separately keyed stage (§10): `data/` is evidence-lane material
  under Kev's hard gate.
- **Required provenance fields:** `{snapshot_id, sha256_triple, generation: u64-safe
  int, lattice_size, num_states, channel_layout_version, source: synthetic|snapshot}` —
  findings without full provenance are invalid by schema.
- **Deterministic ordering:** cells row-major (`z·N²+y·N+x`, matching
  `voxel_lattice.rs:56–62`); components labeled by minimum member index; findings
  sorted by (label, first-seen generation); no hash-map iteration order may leak.
- **Bounded resources:** a **fixed 1–64 snapshot invocation ceiling**
  (`MAX_SNAPSHOTS = 64`) bounds validation, discovery, `run.snapshot_ids`,
  `run.generations`, persistence observation lists and serialization — exceeding
  it is unsupported input yielding the existing `invalid_input` structured refusal
  (decided before item inspection; **not** a truncation and **not** partial
  processing); ≤ 64³ lattices in S1; component count cap (default 4,096) and
  runtime budget with **explicit truncation flags** when hit — cap/budget
  truncation is a reported result, not an error. **Honesty note (unchanged):** the
  deterministic per-invocation operation counter is an input-size proxy for the
  cap/budget mechanism, **not** a wall-clock or adversarial-runtime security bound;
  because it scales with snapshot count it cannot bound count on its own, which is
  precisely why the explicit `MAX_SNAPSHOTS` ceiling exists (Amendment 3).
- **Output schema (JSONL, one finding per line):** `{finding_id, detector: {name,
  version}, snapshot: provenance, label: <deterministic component label — the
  minimum row-major member cell index, the same key used for ordering>, region:
  {bbox_min[3], bbox_max[3], wraps: [bool;3]}, periodic_interpretation: "torus",
  cell_count, state_counts: {per state}, density, persistence: {seen_in_snapshots,
  chain_id} (when multiple snapshots supplied), reasons: [{predicate, threshold,
  measured}], evidence_class: SRC|CALC|HYP, truncated: bool}`.
- **Excluded from findings, by schema:** commands or parameter suggestions of any kind;
  birth/survival recommendations; actions; uncalibrated confidence scores; claims of
  consciousness, intent, or agency.
- **Stable IDs + dedup:** `finding_id = sha256(detector_version ‖ snapshot_id ‖
  canonical-region-encoding)[:16]`; persistence chains link findings across snapshots
  instead of re-emitting duplicates.
- **No-write guarantees:** inputs are never mutated (hash-before == hash-after test);
  the only artifact is the findings object returned to the caller.
- **Error behavior:** malformed input → structured refusal finding (`evidence_class:
  SRC`, reason `invalid_input`), never a partial silent result. **Empty result** is a
  first-class artifact: a run that finds nothing emits a header record saying so.
- **Replay contract:** identical inputs ⇒ byte-identical findings artifact.
- **Versioning:** `DETECTOR_VERSION` participates in `finding_id`; any algorithm change
  bumps it (golden fixtures make drift visible — the PR #315 pattern).
- **Rollback:** delete the lab directory; no state, no migrations.
- **Unsupported cases (explicit):** non-cubic lattices; `num_states ≠ 5`; non-periodic
  boundaries; live-process attachment; GPU arrays.

## 6. Detector options matrix (Pass 5)

| Family | Data needed | Determinism | Memory | Runtime | Torus handling | False-positive surface | Glass-Wall fit | Testability | Smallest falsifier | v1 suitability |
|---|---|---|---|---|---|---|---|---|---|---|
| **Connected-component persistence** (non-VOID components tracked across snapshots) | states (+ optional memory summaries) | full (union-find, canonical labels) | O(N³) ints | O(N³ α) | wrap-aware union-find | moderate (noise blobs → size/persistence thresholds) | pure read | excellent (small fixtures) | two-cluster + wraparound fixtures | **PRIMARY** |
| **Stable/periodic local-hash detection** (per-block content hash; stability/periodicity across snapshots) | states (+ blocks) | full | O(blocks) | O(N³) | periodic block tiling | low for stability; period claims need ≥ p+1 snapshots | pure read | excellent | stable + transient fixtures | **SECONDARY (optional)** |
| Density-spike detection | states + baseline statistics | full | O(N³) | O(N³) | box filters exist as precedent (`filters.rs:79`) | high until baselines exist (needs epoch statistics) | pure read | good | noise fixture | v2 — needs S2 baselines |
| Moving-front / cluster-cohesion tracking | dense temporal sampling | full | O(N³·T) | high | hard | high at ~10-min snapshot cadence (`PHASE_19 §4`) — motion aliases badly | pure read | moderate | oscillator fixture | rejected for v1 (cadence mismatch) `[CALC]` |
| Observer-token correlation | observer JSONL + snapshots | full | O(patches) | low | inherited | n/a (annotation, not detection) | pure read | good | token-fixture join | **S3 comparison layer, not a v1 detector** |
| Rule-search scoring | engine/replicate runs | n/a here | — | — | — | — | touches parked instrument + GPU doctrine (ledger 14) | — | — | out of scope — separately governed |

**Selection (a proposal, not canon):** primary = **connected-component persistence**;
optional secondary = **stable local-hash periodicity** (shares the block/tiling
machinery). Both run on immutable arrays alone, need no RNG, no baselines, no engine
contact, and have small mathematical fixtures. `[PROP]`

## 7. Deterministic toy harness design (Pass 6) `[PROP]` — designed, not implemented

Fixtures (all synthetic arrays, ≤ 32³ unless stated; expectations labeled
**M** mathematical / **S** source-derived / **H** hypothetical):

| Fixture | Content | Expected findings | Expectation class |
|---|---|---|---|
| empty | all VOID | none — empty-result header only | M |
| single cluster | one 3³ STRUCTURAL block | exactly 1 finding, correct bbox/counts | M |
| two separated clusters | two blocks, gap > 1 | exactly 2, stable distinct IDs | M |
| wraparound cluster | block spanning the +x/−x seam | exactly **1** finding, `wraps=[true,false,false]` | M (torus definition) |
| transient cluster | present snapshot 1, absent 2 | persistence chain length 1; no double count | M |
| stable cluster | identical across 3 snapshots | one chain, `seen_in_snapshots=3` | M |
| oscillator (period 2) | alternating pair of shapes | secondary detector reports period 2 with ≥ 3 snapshots; primary reports persistence | M |
| adversarial noise | deterministic pseudo-random single cells | findings only below thresholds → none above min-size | H (threshold-dependent — the point of the fixture) |
| malformed provenance | missing sha256 field | structured refusal, no analysis | M (schema) |
| resource bound | checkerboard (maximal components) | truncation flag set at cap, deterministic prefix | M |

Property tests: input-order independence (fixture dict order shuffled); replay identity
(byte-equal artifacts); **translation invariance on the torus** (same cluster shifted ⇒
same counts/shape, different absolute bbox, `wraps` consistent); stable IDs across
runs; dedup across snapshot chains; bounded output size (the `MAX_SNAPSHOTS` = 64
invocation ceiling bounds header `snapshot_ids`/`generations` and observation lists,
alongside the component cap; over-ceiling input is an `invalid_input` refusal — see §5);
input hashes unchanged; no
network (no socket imports); no filesystem writes outside the explicit artifact.

## 8. LeanCTX artifact contract (Pass 7) `[PROP]` — metaphor → engineering

A **bounded audit handoff** (the only thing a reviewer must read), containing exactly:
run identity (detector name/version, timestamp, continuity-runway id) · input hashes
(per snapshot triple) · bounded summary (≤ 50 findings-table rows: id, region, counts,
persistence, evidence class) · **changed findings since prior run** (new / vanished /
persisted, by chain id) · **one minimal anomaly excerpt** (the single highest-signal
finding, full record) · **falsifiers or failed invariants** (any property-test failure
or truncation, always included — a summary that omits failed cases is invalid) ·
omitted-payload declaration (what was truncated and why).

Limits: ≤ 64 KiB or ≤ 200 records per artifact, whichever first; deterministic
truncation (sorted order, cut tail, `truncated: true` + counts of omitted records).
Prohibited: tensor dumps; snapshot copies; unbounded logs; silent truncation;
summaries that hide failures.

## 9. Relationship to observer and RNG work (Pass 8)

- **Can v1 operate entirely on immutable snapshots?** Yes — S1 doesn't even need
  snapshots (synthetic arrays); S2 is snapshot-only by contract. `[PROP]`
- **Does it require RNG?** **No.** Both selected detectors are deterministic. `[CALC]`
- **If sampling is ever added:** keyed deterministically by a counter tuple in the
  LAB-CRNG-v1 style (`docs/COUNTER_INDEXED_RNG_FEASIBILITY.md` Appendix) — never by a
  stateful stream. `[PROP]`
- **Does PR #315 unblock anything directly?** No hard dependency — it improves future
  replay/scheduling options. No dependency is created merely because the arcs are
  adjacent. `[SRC]`
- **What evidence would a changed RNG stream invalidate?** Trajectory-derived
  expectations only. Snapshot-anchored findings cite the snapshot hash + generation
  and remain valid for that snapshot regardless of stream. `[CALC]`
- **Observer tokens as annotations?** Yes at S3 — joined to findings as *descriptive
  context* (entry-14 precedent), with schema-level exclusion from `reasons` so a token
  can never become a control input or detection trigger. `[PROP]`

## 10. Promotion ladder (Pass 9) `[PROP]`

| Stage | Content | Prerequisites | Evidence required | Tests | Rollback | Gates |
|---|---|---|---|---|---|---|
| **S0** | this preflight document | — | provenance map | n/a | close PR | Jack audit; Kev merge word; `swarm-hunter` label |
| **S1** | toy offline detector in `experiments/swarm_hunter_lab/` (synthetic arrays only) | S0 sealed; Kev implementation word | §7 fixtures green; properties green; **static-import quarantine tests (§3) green in both directions** | full §7 suite + quarantine tests | delete lab dir | Jack audit; Kev word; label |
| **S2** | immutable-snapshot analyser (reads real `data/` NPZ) | S1 sealed; **explicit Kev evidence-lane key (`data/` is a hard gate)**; hash-coverage question resolved; **a legacy-orchestrator disposition option (§2d) chosen by Kev/Jack** — a snapshot-reading detector must not coexist with an undispositioned write-capable namesake. *Post-R/S/T: the disposition prerequisite is **SATISFIED** (2026-07-15) — R #328 `6a762b9` · S #333 `d5e9c3c` · T #334 `3dcc38f` merged; namesake renamed and quarantined. The other S2 prerequisites remain open* | S1 evidence + real-snapshot dry runs with receipts | §7 + provenance/refusal tests on real headers | disable path; artifacts deleted | Jack audit; **Kev evidence-lane word**; label |
| **S3** | comparison against observer outputs | S2 sealed; observer artifacts available | correlation report, evidence-classed | join determinism tests | drop join layer | Jack audit; Kev word; label |
| **S4** | human-reviewed candidate architecture (instrument-vs-extension decision; entry-2 ratification proposal) | S3 sealed | LeanCTX packets from S1–S3 | n/a | archive | **AURA + Jack + Kev** |
| Lane A / engine integration | **not part of this ladder's authorization** | separate future decision | — | — | — | separate keys entirely |

**Passing S1–S3 does not authorize a closed loop.** Hard-stop conditions at every
stage: any write path toward physics; any actuation field in a finding; any `data/`
access before the S2 key; any claim drift flagged by audit.

## 11. Readiness ruling (Pass 10 — re-evaluated after the §2b discovery)

The prior ruling was issued under a false premise ("no Swarm Hunter code path
exists"). Re-evaluated against the corrected evidence, the outcome considered each
allowed verdict: **HOLD** was rejected because the S1 detector shares zero code with
the orchestrator, its surface is synthetic arrays only, and pausing documentation-
stage work does not reduce the orchestrator's standing surface — dispositioning it
does (§2d). **NO-GO** was rejected because every new risk identified (authorization
ambiguity, import adjacency, coexistence at snapshot stage) has a named, enforceable
mitigation. The evidence supports:

**CONDITIONAL GO** for a toy-only offline v1 (S1) — **tightened**, with named
prerequisites:

1. Jack's audit of this preflight (S0) and Kev's merge word for it.
2. A separate, explicit Kev implementation word for S1 (this document is not it).
3. The S1 fence exactly as specified: new directory `experiments/swarm_hunter_lab/`
   (detector module + fixtures + lab-local tests), **no imports from `scripts/`, no
   `data/` access, not collected by the CI floor** (`pytest.ini` scopes collection to
   `tests/`); dependency policy: numpy only (already the project floor); no new
   dependencies.
4. Test fence: the §7 fixture and property suite lives inside the lab; the maintained
   `tests/` suite is untouched.
5. Estimated bounded runtime: full §7 suite < 10 s CPU on toy sizes `[CALC — to be
   measured, not promised]`.
6. Labels: `swarm-hunter` on every ladder PR (tripwire fires by design; acknowledged
   by humans, never by the seat).
7. Rollback: delete the lab directory.
8. **(New)** The S1 PR ships the §3 static-import quarantine tests as acceptance
   criteria, and adopts the §2c Option-C naming qualifiers in all of its prose.
9. **(New)** Before S2 — not S1 — a §2d disposition option for the legacy
   orchestrator must be chosen and keyed by Kev/Jack (also encoded as an S2
   prerequisite in §10). *Post-R/S/T: **SATISFIED** (2026-07-15) — the disposition
   merged as R #328 (`6a762b9`) · S #333 (`d5e9c3c`) · T #334 (`3dcc38f`); receipts
   in the supersession note. All other prerequisites, including the separate Kev
   implementation word for S1 (prerequisite 2), remain open.*

**Rejected alternatives:** SH-as-controller (prohibited by ledger 2/11/13, Maturin
§4); rule-search-first (separately governed; parked instrument); moving-front tracking
at current snapshot cadence (aliasing, §6); density-spike v1 (needs S2 baselines);
starting inside `scripts/` or `tests/` (fence violations); sampling with stateful RNG
(replay hazard); any S2 start before the evidence-lane key (hard gate).

**Open questions (owners):** instrument-vs-extension identity (AURA+Jack+Kev, S4);
entry-2 ratification to canonical (team, S4); snapshot hash coverage of
`age_grid`/`half_step_flags` (engine-gated check, before S2); observer-artifact
availability contract for S3 (Jack); whether S1 belongs in the theory-sandbox policy
family or as its own lab README (Jack, at S1 PR).

---

*Preflight ends. Nothing above is activated by being written down; the ladder's keys
stay in Kev's hands, the audits in Jack's, and Lane A stays parked exactly where the
handoff says it is.*
