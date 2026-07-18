# LOCAL_MODEL_DEPLOYMENT_INCEPTION.md — Deployment Boundaries (Inception Note)

> **Status**: inception / design note. **Documentation only. No execution is
> authorised by this document.** This PR changes two Markdown files and
> nothing else — no model was run, no machine was configured, no service was
> touched, no network probe was made in producing it.
>
> Package NP3 ("Local Model Deployment Boundaries"), personally authorised by
> Kevin on 2026-07-13. Drafted by Agent 84. This note corrects and bounds the
> repository's future local-model plan; the companion amendment lands in
> [`LOCAL_OLLAMA_SMOKE_TEST.md`](../LOCAL_OLLAMA_SMOKE_TEST.md).

## Why this note exists

The 2026-05-01/05-05 smoke-test plan proved the transport plumbing works, but
it also left behind three things that must not silently become defaults:

1. a recommendation to bind Ollama to **every LAN interface**
   (`OLLAMA_HOST=0.0.0.0:11434`), made before the security implications were
   weighed as deployment policy rather than as a one-test convenience;
2. an implicit assumption that recorded LAN addresses stay current; and
3. no sequencing gate tying future live tests to the security work that has
   since been built.

This note supersedes those three points and records the boundaries any future
local-model work must respect.

## 1. What exists in the repo (implemented, merged)

| Surface | Where | What it is |
|---------|-------|------------|
| Agent backend abstraction | `scripts/agent_backends/base.py` | Frozen-dataclass content blocks, `ToolSpec`/`ToolCall`, `AgentResponse`, and the `AgentBackend` ABC — the seam every LLM backend implements. |
| Provider-neutral backend | `scripts/agent_backends/openai_compat_backend.py` | One class that speaks the OpenAI `/v1/chat/completions` shape; Ollama, vLLM, NIM, etc. are configurations, not new code. |
| Anthropic + mock backends | `scripts/agent_backends/` | The production backend and the scripted-test backend, shape-identical at the `AgentResponse` layer. |
| Shard protocol | `scripts/shard_protocol.py` | Transport-agnostic halo-exchange protocol (Phase 17b) with bitwise-reproducibility as a design invariant. |
| Shard transport | `scripts/shard_transport_zmq.py` | The one concrete cross-process transport (ZeroMQ PUSH/PULL); siblings (Ray/MPI/TCP) plug in without protocol change. |
| Provider taxonomy | `BACKEND_PROVIDER_MATRIX.md` | Canonical table of which provider is which backend configuration. |
| Smoke-test plan + log | [`LOCAL_OLLAMA_SMOKE_TEST.md`](../LOCAL_OLLAMA_SMOKE_TEST.md) | The 2026-05-01 plan and the 2026-05-05 execution log, now amended by this package. |

**Boundary: reuse, don't reinvent.** Any future local-model work uses the
`AgentBackend` seam for model I/O and the existing shard protocol for any
distribution need. **No second transport stack is to be invented.**

## 2. What has been tested (evidence on record)

- **2026-05-05, single backend call, PASSED** (execution log in
  [`LOCAL_OLLAMA_SMOKE_TEST.md`](../LOCAL_OLLAMA_SMOKE_TEST.md)):
  `OpenAICompatBackend` → real Ollama 0.23.0
  server → `granite4:3b` (IBM Granite 4, 3.4B, Q4_K_M) over the LAN, one
  read-only-shaped tool offered, well-formed tool call returned and parsed
  round-trip. 3.21 s cold latency, 300 tokens total.
- **Protocol parity** (PR #134): Anthropic-vs-OpenAI-compat parity proven
  against scripted mocks.
- **Not tested**: a full orchestrator iteration against a live tuning API;
  multi-iteration conversations; any multi-node inference topology; any model
  other than `granite4:3b`. Claims about those remain unmade.

## 3. Corrections to prior guidance (superseding)

### 3.1 Do not expose Ollama on every LAN interface

The old plan recommended `OLLAMA_HOST=0.0.0.0:11434` as a pre-install step,
and the 2026-05-05 execution configured it that way on Aurora. **That
recommendation is withdrawn as standing guidance.** Ollama's official FAQ
confirms the safe default: *"Ollama binds 127.0.0.1 port 11434 by default"*
([docs.ollama.com/faq](https://docs.ollama.com/faq), accessed 2026-07-13).
Loopback is the correct posture until a protected transport is designed and
operator-approved (§3.2).

Reverting Aurora's `0.0.0.0` binding (as recorded in the 2026-05-05
execution log; re-verify actual state at the time) to the loopback default
is a **later operator action** — this documentation PR changes no machine.

### 3.2 The local Ollama API requires no authentication

Ollama's official documentation states it directly: **"No authentication is
required when accessing Ollama's API locally via `http://localhost:11434`"**
([docs.ollama.com/api/authentication](https://docs.ollama.com/api/authentication),
accessed 2026-07-14). Authentication exists separately for ollama.com cloud
models, publishing, and private-model downloads (`ollama signin` /
`OLLAMA_API_KEY`) — so this is a bounded statement about the **local** API,
not a claim that Ollama has no authentication anywhere.

Two supports, kept at their correct weights:

- **Documentation**: the official statement above covers the local API.
- **Historical receipt**: the 2026-05-05 execution log — the backend's dummy
  `api_key` and a plain credential-less `curl` both succeeded against
  Ollama 0.23.0.

**Neither fact by itself proves that a broadly exposed LAN service is
safe.** What follows from them is only this: a process that can reach the
port can use the models, so reachability *is* the access control. The FAQ's
network-exposure guidance covers reverse proxies (Nginx) and tunnels (Ngrok,
Cloudflare Tunnel) — access control is left entirely to the deployment.

Therefore any **future** cross-machine use requires a separately reviewed,
operator-approved **protected transport design**, such as:

- a **narrowly scoped host firewall rule** (single source host, single port),
- an **authenticated reverse proxy** in front of the loopback-bound server, or
- an **operator-controlled tunnel** (e.g. SSH forwarding) opened per session.

Choosing among these is a design decision for a later package; none of them
is implemented, recommended-by-default, or configured here.

### 3.3 Recorded IP addresses are observations, not facts

`192.168.86.3` (Aurora) and `192.168.86.29` (Area 51) are DHCP-era
observations from 2026-05. **Do not assume a saved IP address remains
current.** Any future step that needs an address re-verifies it on the
machine itself, at that time, as an operator action.

## 4. Sequencing gates (ordered; each gate blocks everything after it)

1. **R/S/T lands and passes post-merge audit.** The quarantine stack —
   [#328](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/328)
   (R: reject autonomous `policy:auto` commits at the tuning-API write
   boundary),
   [#333](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/333)
   (S: observe-by-default orchestrator capability model), and
   [#334](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/334)
   (T: bounded loop, error semantics, receipts) — must merge and receive its
   post-merge audit **before any live local-model smoke test runs again**.
   The 2026-05-01 plan itself flagged the `policy:auto` auto-commit hazard
   and improvised around it; R/S/T closes it structurally, so no live test
   should predate that closure.
2. **First model role is observation-only.** The first live role may
   summarise bounded evidence handed to it. It **cannot propose runtime
   changes and cannot apply them** — stricter than the 2026-05-05 test, which
   offered a read-only tool but ran under a proposal-capable framing.
3. **One host, loopback, first.** Prove the full loop on a single machine
   against `127.0.0.1:11434` before any two-machine topology is considered.
   The 2026-05-05 LAN result predates gates 1–2 and does not satisfy this.
4. **Two machines only behind a protected transport** (§3.2), with explicit
   operator approval for that specific design.

## 5. Model candidates (no downloads here)

**Granite (`granite4:3b`) is the first future compatibility candidate** —
recorded as installed on Aurora (2026-05-05 execution log; re-verify before
any future use) and already proven at the tool-call level.
Other models (larger Granite variants, Qwen, Llama, etc.) remain **later
comparison candidates only**. This document does not recommend, perform, or
schedule any download.

Future **read-only inventory** of what is installed/loaded may use Ollama's
documented endpoints — `GET /api/tags` (list available models,
[docs.ollama.com/api/tags](https://docs.ollama.com/api/tags)) and
`GET /api/ps` (list models currently loaded into memory,
[docs.ollama.com/api/ps](https://docs.ollama.com/api/ps)) — but even that
read-only probe **requires its own execution authorization** when the time
comes. Nothing was probed for this PR.

## 6. Concurrent workloads are senior

Folding@home and BOINC **remain running**. The rules for any future
inference experiment:

- The experiment declares its CPU, GPU, and memory reservations up front.
- If the declared reservations are **not available, the experiment defers.**
  It does not negotiate for resources.
- **Medusa software must never pause, stop, throttle, or reprioritize
  Folding@home or BOINC automatically.** Any change to those workloads is a
  human operator's decision, made outside this system, every time.

(The old plan's "pause F@H during the test" checklist steps are superseded
accordingly — see the amendment in
[`LOCAL_OLLAMA_SMOKE_TEST.md`](../LOCAL_OLLAMA_SMOKE_TEST.md).)

## 7. Future worker roles (bounded; no controller)

If multi-worker topologies are ever designed, workers are limited to three
bounded roles:

| Role | May | May not |
|------|-----|---------|
| **Observer** | summarise bounded evidence it is handed | request more scope; propose or apply changes |
| **Predictor** | emit falsifiable predictions about declared observables | act on its own predictions |
| **Critic** | score/flag another worker's bounded output | modify that output; escalate beyond its receipt |

**There is no controller role.** No worker orchestrates other workers,
allocates resources, or holds write authority. Composition of worker outputs
is a human-reviewed step.

### Task envelope — design requirements only

Any future task handed to a worker must carry (design requirement, **no
implementation in this PR**):

- an **immutable task identifier**;
- **input hashes** for every piece of evidence supplied;
- a **bounded context** (explicit inputs; nothing ambient) and a **bounded
  result** (size- and schema-limited);
- a **deadline**, after which the task is void rather than retried
  indefinitely; and
- **provenance** — which principal authorised it, which worker ran it, when,
  against which input hashes.

## 8. The four-way ledger

| Class | Contents |
|-------|----------|
| **Exists in repo** | backend ABC + OpenAI-compat/Anthropic/mock backends; shard protocol + ZMQ transport; provider matrix; smoke-test plan/log (§1) |
| **Tested** | single backend↔Ollama tool-call round trip on real hardware (2026-05-05); mocked protocol parity (PR #134) (§2) |
| **Proposed** | sequencing gates (§4); observation-only first role; loopback-first proof; protected-transport options (§3.2); bounded worker roles + task envelope (§7); read-only inventory probe (§5) |
| **Later operator action** | reverting Aurora's `0.0.0.0` bind to loopback; re-verifying IPs; choosing + approving a protected transport; authorising the inventory probe; authorising any live test after R/S/T's post-merge audit |

## 9. Citations

- Ollama — Authentication: "No authentication is required when accessing
  Ollama's API locally via `http://localhost:11434`"; cloud models,
  publishing, and private-model downloads authenticate separately:
  <https://docs.ollama.com/api/authentication> (accessed 2026-07-14).
- Ollama — List models (`GET /api/tags`):
  <https://docs.ollama.com/api/tags> (accessed 2026-07-14).
- Ollama — List running models (`GET /api/ps`):
  <https://docs.ollama.com/api/ps> (accessed 2026-07-14).
- Ollama FAQ — "Ollama binds 127.0.0.1 port 11434 by default"; `OLLAMA_HOST`;
  proxy/tunnel exposure guidance:
  <https://docs.ollama.com/faq> (accessed 2026-07-13, re-confirmed
  2026-07-14).

---

— drafted 2026-07-13 by Agent 84 (PACKAGE NP3), per Kevin's on-seat
  authorisation; pending Jack's audit; unmerged until Kev's word
