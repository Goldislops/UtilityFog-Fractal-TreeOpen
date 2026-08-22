# OPEN_MODEL_INTEGRATION.md — OMI-V1

> **Status**: implemented foundation + dated source matrix. Package
> [`scripts/open_model/`](../scripts/open_model/).
>
> **What this is NOT.** No model has been downloaded, installed, served,
> benchmarked, or run in producing this document or the code it describes. No
> endpoint was contacted. No package was installed. Nothing here is a
> performance result or a recommendation to deploy a particular model. The
> matrix below is *metadata read off vendors' own pages on 2026-08-22*, and
> metadata is not approval.
>
> This package sits **above** the merged agent-backend seam in
> [`scripts/agent_backends/`](../scripts/agent_backends/) and does not modify
> it, per the standing boundary in
> [`LOCAL_MODEL_DEPLOYMENT_INCEPTION.md`](LOCAL_MODEL_DEPLOYMENT_INCEPTION.md):
> *reuse, don't reinvent; no second transport stack.*

## 1. Why this exists

The repository already had the transport half of provider neutrality:
`AgentBackend` as the seam, `OpenAICompatBackend` as the one class that
speaks to OpenAI, NVIDIA NIM, DeepSeek, vLLM, SGLang, Ollama and llama.cpp as
*configurations*, and `BACKEND_PROVIDER_MATRIX.md` as the taxonomy.

What it did not have was any way to answer the questions that come *before*
sending a request:

- Is this candidate actually available on this machine right now?
- Does it support what this task needs — structured output, tool calls,
  enough context — or are we about to find out the hard way?
- What licence governs it, and does that licence permit this use?
- If nothing qualifies, what happens? (Previously: nothing was defined, and
  the natural failure mode of a provider-neutral client is to quietly fall
  back to whatever cloud endpoint still has a key in the environment.)

OMI-V1 answers those four questions and nothing else.

## 2. What was added

| Module | Responsibility |
|---|---|
| [`capabilities.py`](../scripts/open_model/capabilities.py) | Immutable, fail-closed capability descriptors: locality, availability, structured output, tool calling, context limits, quantisation, licence classification, runtime compatibility. |
| [`registry.py`](../scripts/open_model/registry.py) | Explicit allowlist binding a name → descriptor → operator-written factory. No endpoint, command, or credential parameter exists anywhere in it. |
| [`routing.py`](../scripts/open_model/routing.py) | Deterministic eligibility, a single fixed no-eligible-backend outcome, explicit escalation reasons, and no silent fallback to a remote service. |
| [`structured.py`](../scripts/open_model/structured.py) | Total, non-disclosing validation of a model's structured output. |
| [`redaction.py`](../scripts/open_model/redaction.py) | Secret/path/email scrubbing for operator notes, plus the diagnostic record shape. |
| [`evaluation.py`](../scripts/open_model/evaluation.py) | Hermetic harness driven entirely by in-process doubles, with network entry points actively blocked. |
| [`catalogue.py`](../scripts/open_model/catalogue.py) | The matrix below, expressed as deliberately inert descriptors. |

### The four design commitments

**Fail-closed by default.** Every descriptor field defaults to its
conservative value, and support flags are tri-state — `supported`,
`unsupported`, `unknown` — where `unknown` blocks with its own escalation
reason. Nothing in the package ever upgrades an unknown into a yes. A
half-filled descriptor is ineligible, not accidentally eligible.

**No silent cloud fallback.** `TaskRequirements.require_local` defaults to
`True`. A remote candidate under a local-only task is refused with
`locality-not-local`, and the winner is re-evaluated after selection
specifically so a future edit to the selection logic cannot produce a remote
backend for a local-only task. When nothing qualifies the result is the fixed
`NO_ELIGIBLE_BACKEND` outcome carrying reasons — not an exception, not a
degraded pick, and not a quiet hop to whichever API key happens to be set.

**Disclosure resistance is structural, not filtered.** `TaskRequirements`
has no prompt, message, system, or free-text field at all; the routing layer
cannot leak prompt content because it never receives any. Evaluation records
carry codes, allowlist names, and sizes — never response text, timestamps,
paths, or environment values. The evaluation harness sends one fixed
synthetic probe rather than caller-supplied text, so no fixture in this repo
can come to contain a private prompt. `redact()` exists for the one
remaining free-text field (an operator note) and is honestly scoped: it
matches *shaped* secrets, and it is not claimed to sanitise arbitrary natural
language.

**Metadata is not approval.** Every catalogue entry declares
`availability="unknown"` and `locality="unknown"`, both blocking. No entry
carries a factory, and the registry needs one. A test asserts that no
catalogue entry can route under *any* requirement combination, including the
most permissive one expressible — so an entry cannot become live through an
editing slip.

## 3. How this matrix was produced

Three bounded, read-only research agents ran on 2026-08-22, each restricted
to primary sources: vendor model cards under the official org, vendor
documentation sites, vendor GitHub repositories, and licence texts. Blog
posts, video summaries, benchmark leaderboards and marketing copy were
treated as leads for finding an official page, never as sources of fact.
Agents were instructed to report `UNVERIFIED` rather than guess, and the
unresolved items they returned are reproduced in §6 rather than quietly
dropped.

Two honest caveats about that provenance. The URLs below are the ones the
research agents reported reading; they were not independently re-fetched
one-by-one when this document was assembled. And **no benchmark claim from
any source was used**: nothing below ranks, scores, or recommends a model on
quality, because this work has measured nothing.

## 4. Model candidate matrix (observed 2026-08-22)

Licence classes: **(a)** OSI open source · **(b)** open-weight but
licence-restricted · **(c)** source-available · **(d)** proprietary service.
Where OSI status could not be confirmed from the licence text itself, the
entry is classified into the *more* restrictive class.

| Model | Class | Licence | Weights | Vendor-claimed runtimes | First-party quantisation | Material restriction |
|---|---|---|---|---|---|---|
| [IBM Granite 4.1 (3B/8B/30B)](https://huggingface.co/ibm-granite/granite-4.1-8b) | **(a)** | Apache-2.0 | ungated | llama.cpp, Ollama, vLLM, SGLang, Transformers | **GGUF (first-party)**, FP8 | None attached to the weights. |
| [Google Gemma 4 (E2B…31B)](https://huggingface.co/google/gemma-4-12B-it) | **(a)** | Apache-2.0 | ungated (changed from prior Gemma generations) | llama.cpp, Ollama, vLLM, SGLang, LM Studio, MLX, NIM | **QAT q4_0 GGUF (first-party)**, w4a16 | Prohibited-Use Policy still referenced from the card; its status under Apache-2.0 is unresolved. |
| [Mistral Small 4 / Large 3 / Ministral 3](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603) | **(a)** | Apache-2.0 | ungated | vLLM (recommended), llama.cpp, SGLang, TensorRT-LLM | NVFP4 | None — but see the family split below. |
| [Mistral Devstral 2 · Medium 3.5](https://help.mistral.ai/en/articles/347393-under-which-license-are-mistral-s-open-models-available) | **(b)** | Modified MIT | ungated | vLLM, SGLang | FP8 | Companies above **$20M monthly revenue** need a commercial licence or must use Mistral Studio. |
| [Mistral Voxtral TTS](https://docs.mistral.ai/models/overview) | **(c)** | CC BY-NC 4.0 | ungated | — | — | **Non-commercial only.** |
| [Hermes 4.3-36B](https://huggingface.co/NousResearch/Hermes-4.3-36B) | **(a)** | Apache-2.0 *(inherited from ByteDance Seed-OSS-36B)* | ungated | vLLM, SGLang, llama.cpp, Ollama | **GGUF (first-party)** | None. |
| [Hermes 4-14B](https://huggingface.co/NousResearch) | **(a)** | Apache-2.0 *(inherited from Qwen3-14B-Base)* | ungated | vLLM, SGLang | FP8 | None. |
| [Hermes 4-70B / 4-405B](https://huggingface.co/NousResearch/Hermes-4-70B) | **(b)** | **Llama 3.1 Community License (inherited)** | ungated | vLLM, SGLang | FP8 | 700M MAU trigger; derivative names must begin with "Llama"; "Built with Llama" display duty; Meta AUP by reference. |
| [NVIDIA Nemotron 3 Nano / Super](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF) | **(b)** | NVIDIA Nemotron Open Model License | ungated | vLLM, SGLang, TensorRT-LLM, Transformers | BF16, FP8, NVFP4; **GGUF for Nano-4B** | Commercial use permitted; notice retention + NOTICE line; litigation-triggered termination. Not OSI-approved. |
| [NVIDIA Nemotron 3 Ultra · 3.5 Lightning](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16) | **(b)** | [OpenMDW-1.1](https://openmdw.ai/license/1-1/) | ungated | vLLM, TensorRT-LLM, SGLang, Ollama, llama.cpp (versions pinned per card) | BF16, NVFP4; GGUF hosted **outside** the vendor org | Near-permissive (no output restrictions), but **no OSI claim on the licence page** → classified conservatively. |
| [Z.ai GLM-5.2](https://huggingface.co/zai-org/GLM-5.2) | **(a)** | MIT (weights; code repo is Apache-2.0) | ungated | vLLM ≥0.23, SGLang ≥0.5.13, Transformers | FP8 | None contractual. Operational/jurisdictional caveat in §6. |
| [DeepSeek V4 Pro / Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731) | **(a)** | MIT | ungated | vLLM, SGLang, Transformers | FP8, FP4+FP8 mixed | None contractual. Operational/jurisdictional caveat in §6. |
| [Meta Llama 4 Scout / Maverick](https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct) | **(b)** | [Llama 4 Community License](https://developer.meta.com/ai/llama4/license/) | **GATED — requires legal name, DOB, organisation** | vLLM, SGLang, Transformers ≥4.51 | FP8 (Maverick), INT4 on-the-fly | 700M MAU trigger; "Llama" name-prefix + "Built with Llama" duties; AUP bars military, nuclear, espionage, ITAR-controlled and critical-infrastructure use. |

**Structured output is a runtime property, not a model property.** No vendor
in this table guarantees JSON-Schema-constrained decoding from the weights
themselves; constrained decoding comes from llama.cpp grammars, vLLM
structured outputs, or SGLang grammar backends. This is why
`ModelCapabilities.structured_output` describes the *composed* backend —
model as served by a bound runtime — and why every catalogue entry, which
binds no runtime, honestly reports `unknown`.

**Context figures.** `max_context_tokens` is populated in code only where an
exact token integer appeared on the vendor's own card (Granite 131072, GLM-5.2
1048576). Where a source stated a rounded "256K" / "1M" / "10M", the field is
left at `0` (unknown) rather than converted to a plausible power of two.
Routing compares integers, and a converted marketing figure would be a
fabricated fact wearing the costume of a measured one.

## 5. Runtime matrix (observed 2026-08-22)

| Runtime | Version seen | Licence | OpenAI-compatible path | Structured-output parameter | Tool calling | Model list | Health | Native Windows |
|---|---|---|---|---|---|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | v0.2.0 / build b10569 | MIT | `/v1/chat/completions`, `/v1/completions`, `/v1/responses`, and Anthropic-shaped `/v1/messages` | `grammar` (GBNF) or `json_schema` on `/completion`; `response_format:{type, **schema**}` — schema sits **directly under** `response_format` | yes, **requires `--jinja`** | `/v1/models` | `/health` | **yes** (MSVC, winget, prebuilt, WoA arm64) |
| [Ollama](https://github.com/ollama/ollama) | v0.32.15 | MIT | `/v1/chat/completions`, `/v1/models`, `/v1/responses` | native `format` on `/api/chat` (`"json"` or a schema); `response_format` on `/v1` | yes, no server flag — but **`tool_choice` is not supported on `/v1`** | `/api/tags`, `/v1/models` | `GET /` (source-verified only) | **yes** (native app, Win10 22H2+) |
| [vLLM](https://github.com/vllm-project/vllm) | v0.27.1 | Apache-2.0 | `/v1/chat/completions`, `/v1/responses`, `/v1/models` | `extra_body={"structured_outputs":{…}}` — **`guided_*` was removed in v0.12.0** — or `response_format.json_schema.schema` | yes, **requires `--enable-auto-tool-choice` + `--tool-call-parser`** | `/v1/models` | `/health` | **no** — WSL only |
| [SGLang](https://github.com/sgl-project/sglang) | v0.5.18 | Apache-2.0 | `/v1/chat/completions`, `/v1/models`, plus Ollama-shaped `/api/chat` | `response_format.json_schema.schema`, or `extra_body={"ebnf"` \| `"regex"}`; native puts them in `sampling_params` — **exactly one** constraint per request | yes, **requires `--tool-call-parser`**; `required`/named fully supported only on the xgrammar backend | `/v1/models` | `/health`, `/health_generate` | **unverified — assume unsupported** |
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) | 1.3.0 RC line | Apache-2.0 | via its own runtimes | — | — | — | — | Linux primary; Windows supported; NVIDIA GPUs only |
| [NVIDIA NIM](https://developer.nvidia.com/nim) | — | **proprietary** | OpenAI-compatible | — | — | — | — | self-hostable container |

Divergences an adapter has to absorb, and the reason a single `response_format`
passthrough is not sufficient:

- llama.cpp puts the schema at `response_format.schema`; vLLM and SGLang put
  it at `response_format.json_schema.schema`.
- vLLM renamed its guided-decoding parameters in a breaking way
  (`guided_json` → `structured_outputs.json`, removed in v0.12.0).
- Ollama is the only one needing no server-side tool parser flag — and also
  the only one without `tool_choice` on the OpenAI path.
- vLLM and SGLang need **launch-time flags** before tool calling works at
  all, and probing `/v1/models` will not tell you whether they were set.
- SGLang documents no per-request `seed`; determinism there is a launch-time
  `--enable-deterministic-inference` decision.

## 6. Unresolved licence, jurisdictional, and supply-chain risks

These are recorded because they are unresolved, not because they are settled.
Several are counsel questions, not engineering ones.

1. **Licence inheritance beats the fine-tuner's own label.** Hermes-4-70B and
   4-405B are Llama-3.1-encumbered regardless of what the fine-tuner's card
   says. Resolve licence **per repository**, never per family.
2. **NVIDIA splits licences inside one generation.** Nano and Super are under
   the Nemotron Open Model License; Ultra and 3.5 Lightning are under
   OpenMDW-1.1. "Nemotron is licensed X" is false as a family statement.
3. **OpenMDW-1.1 makes no OSI claim** on its licence page. Do not describe
   Nemotron Ultra or 3.5 Lightning as OSI open source in user-facing copy.
4. **Gemma's Prohibited Use Policy vs Apache-2.0.** The Gemma 4 card still
   references the PUP while the licence is Apache-2.0. Whether the PUP binds
   the weights is unresolved.
5. **Gemma 3 relicensing is unverified.** A Google releases page renders
   Gemma 3 as Apache-2.0, contradicting its original Gemma Terms of Use. Do
   not rely on that for Gemma 3 weights already in a supply chain.
6. **Llama 4 EU multimodal carve-out: conflicting reads.** Two reads of the
   licence text found no such clause; one fetch of the AUP page asserted one
   exists. Counsel review before any EU deployment of Llama 4 vision.
7. **Llama 4 gating requires PII** (legal name, DOB, organisation) to obtain
   weights — a privacy and automation problem for any CI path.
8. **China-headquartered vendors (Z.ai, DeepSeek): the licence is not the
   risk.** Both publish MIT weights with no field-of-use, residency, or
   export clause, so **self-hosted use is licence-clean**. The residual risk
   is operational: routing to their *hosted APIs* sends prompts to PRC
   infrastructure, and some procurement postures exclude PRC-origin models
   regardless of licence. No official vendor page addressing data residency
   or export control was located for either. Flag to counsel; do not
   represent as vendor-assured.
9. **First-party GGUF exists only for IBM Granite, Hermes 4.3, Gemma 4 QAT,
   and Nemotron Nano-4B.** Mistral, Z.ai and DeepSeek GGUFs are third-party —
   a provenance consideration for any llama.cpp or Ollama path. NVIDIA's own
   3.5 Lightning GGUF is hosted outside the vendor org.
10. **TensorRT-LLM bundles an LTX-2 component** carrying a $10M-revenue
    commercial threshold inside an otherwise Apache-2.0 repository. Audit
    which components are actually linked.
11. **NIM's free grant excludes multi-user servers.** RTX/GeForce NIMs may be
    used without a subscription only on an RTX workstation and **not** in a
    server serving multiple users; otherwise an AI Enterprise subscription is
    required.
12. **DeepSeek V4 ships no Jinja chat template** — it supplies encoding
    scripts instead. Any adapter assuming `apply_chat_template` will silently
    mis-format prompts.
13. **DeepSeek's `eagle3_gemma4_12b_ttt7` draft model** is Gemma-derived; its
    licence tag is unverified and is likely the Gemma Terms of Use, not MIT.
14. **GLM-5.3 (released 2026-08-18) weights are not publicly retrievable** —
    the HF repo returned HTTP 401. Treat as API-only until a public repo
    appears.
15. **Parameter and context figures disagree between sources** for Granite
    (131072 vs "up to 512K"), DeepSeek V4 (README vs repo metadata), and GLM
    (GitHub vs card). The lower/card figure is used, or the field is left
    unknown.
16. **Doc-host migrations** break cached links: `docs.sglang.ai` → 301 →
    `docs.sglang.io`, and `llama.com` → 301 → `developer.meta.com/ai/`.

## 7. Adding a real backend without granting it operational trust

Nothing in this package makes a backend reachable. That takes four deliberate
steps, and the sequence is intentionally not automatable from a data file.

**Step 1 — Observe it yourself.** Confirm the runtime is installed and
serving on the machine that will use it. This is an operator action with its
own authorization; note that
[`LOCAL_MODEL_DEPLOYMENT_INCEPTION.md`](LOCAL_MODEL_DEPLOYMENT_INCEPTION.md)
gates even a read-only `GET /api/tags` inventory probe behind its own
approval, and gates any live test behind the R/S/T post-merge audit,
observation-only first role, and loopback-first sequencing.

**Step 2 — Author a descriptor that asserts what you observed.** A catalogue
entry is not sufficient and cannot be promoted; write a new descriptor whose
`availability` and `locality` you are personally willing to stand behind,
and whose `structured_output` / `tool_calling` reflect the *composed* model
plus runtime, not the vendor's marketing.

```python
observed = ModelCapabilities(
    model_id="ibm-granite/granite-4.1-8b",
    locality="local",
    availability="present",        # only you can honestly assert this
    resource_class="light",
    structured_output="supported", # because the bound runtime provides it
    tool_calling="supported",
    max_context_tokens=131072,
    runtimes=("ollama",),
    licence_class="osi-open-source",
    licence_name="Apache-2.0",
    provenance_url="https://huggingface.co/ibm-granite/granite-4.1-8b",
    observed_on="2026-08-22",
)
```

**Step 3 — Write a factory, in reviewed code.** The factory takes no
arguments, so no endpoint or credential can be injected at routing time.
Configuration is closed over in code a reviewer reads. Reuse the existing
seam — do not write a new backend class:

```python
def make_local_granite() -> AgentBackend:
    return OpenAICompatBackend(
        base_url="http://127.0.0.1:11434/v1",   # loopback, per the inception note
        model="granite4:3b",
    )
```

**Step 4 — Register it against an explicit allowlist.**

```python
registry = BackendRegistry(allowed_names=("local-granite",))
registry.register("local-granite", observed, make_local_granite)

decision = route(registry, TaskRequirements(require_local=True))
if not decision.has_backend:
    escalate(decision.escalation)   # the only other branch there is
```

Note what is still true after all four steps: the router will still refuse
this backend the moment its descriptor stops asserting `present`, `create()`
will refuse it a second time independently, and a task requiring a capability
the descriptor does not claim will escalate rather than try its luck.

## 8. Deliberately not implemented

- **No live backend is registered anywhere in this repository.** The
  catalogue is inert and the registry ships empty.
- **No capability auto-detection.** Probing a live server to discover whether
  tool calling is enabled would require contacting it, which is outside this
  work's authority — and, per §5, `/v1/models` cannot answer the question
  anyway because tool support is a launch-flag property.
- **No changes to `OpenAICompatBackend`.** It still has no
  `response_format`, `json_schema`, or `seed` support. Adding a normalised
  structured-output parameter across the four runtime dialects in §5 is the
  obvious next package; it is not this one, and doing it here would have
  meant editing a merged, tested backend outside the stated scope.
- **No async, streaming, or batching.** Out of scope.
- **No cost, latency, or quality model.** `resource_class` is a *declared*
  band authored by a human, not a measurement. This package benchmarks
  nothing and must never be cited as if it had.
