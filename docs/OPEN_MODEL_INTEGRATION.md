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

**No silent cloud fallback — and an honestly bounded locality claim.**
`TaskRequirements.require_local` defaults to `True`. A remote *descriptor*
under a local-only task is refused with `locality-not-local`, and the winner
is re-evaluated after selection specifically so a future edit to the
selection logic cannot produce a remote descriptor for a local-only task.
When nothing qualifies the result is the fixed `NO_ELIGIBLE_BACKEND` outcome
carrying reasons — not an exception, not a degraded pick, and not a quiet hop
to whichever API key happens to be set.

What that does **not** mean, and what an earlier draft of this document
wrongly implied: routing reads a *descriptor*, and a descriptor is an
assertion. A factory is arbitrary operator code and can construct a backend
pointed at a paid remote endpoint while its descriptor claims `local`. No
amount of care in this package makes that impossible. Two things bound it:

- **A gate.** Registering a `local` descriptor requires an explicit
  `locality_attestation="operator-asserted"` argument at the registration
  site, so the trust is named in code a reviewer reads rather than implied by
  a field.
- **A best-effort detector.** `create()` inspects the constructed backend for
  a `base_url`-shaped attribute and refuses with `locality-mismatch-detected`
  when a `local` descriptor produced a non-loopback endpoint. This catches
  the concrete case in this repository — `OpenAICompatBackend` holds an SDK
  client with a `base_url` — and anything following the same convention. It
  is not universal: a backend that hides its endpoint is not detected, and
  *not detected* is recorded as unknown, never as local.

The residual guarantee is an operator assertion, cross-checked where the
shape permits. It is not a structural proof and is no longer described as one.

**Provenance is part of identity.** A descriptor names one artifact and says
where it came from: `model_id` + `variant_id` + `repository_revision`
identify it, `artifact_digest` pins the bytes whenever an artifact-format
claim is made, and `licence_source_url` + `licence_revision` pin the terms
that were actually read. All are blocking. `quantisation` is singular for the
same reason — see "Variant identity" in §4.

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

Corrected after audit: "carry codes and names" was the intent, but several
fields only *sliced* their input, leaving room for 64–128 characters of
arbitrary caller text. Identifier fields are now closed rather than trimmed —
`DiagnosticRecord.event` must be a member of `DIAGNOSTIC_EVENTS`, its
`reasons` members of `ESCALATION_REASONS` (non-members are dropped whole, not
truncated), and `backend`, `EvaluationCase.case_id` and every entry of
`required_keys` must be *safe tokens*: bounded, drawn from a closed character
class, **and unchanged by the secret matcher** — that last condition is what
refuses `sk-ABCDEFGH12345678`, which the character class alone would admit.
Unsafe `required_keys` now fail the whole validation rather than being
dropped, because dropping one silently reported success for a payload that
had never been checked against it. And missing keys are reported as
**indices** into the caller's own tuple, never as key text.

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
| [Google Gemma 4 (E2B…31B)](https://huggingface.co/google/gemma-4-12B-it) | **(a)** | Apache-2.0 | ungated (changed from prior Gemma generations) | llama.cpp, Ollama, vLLM, SGLang, LM Studio, MLX, NIM | **QAT q4_0 GGUF (first-party)**, w4a16 | Card at `707f0a3b` declares `license: apache-2.0` and references **no** prohibited-use policy; a separate general Gemma policy exists in Google docs and its status is unresolved. See §6. |
| [Mistral Small 4 / Large 3 / Ministral 3](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603) | **(a)** | Apache-2.0 | ungated | vLLM (recommended), llama.cpp, SGLang, TensorRT-LLM | NVFP4 | None — but see the family split below. |
| [Mistral Devstral 2 · Medium 3.5](https://help.mistral.ai/en/articles/347393-under-which-license-are-mistral-s-open-models-available) | **(b)** | Modified MIT | ungated | vLLM, SGLang | FP8 | Companies above **$20M monthly revenue** need a commercial licence or must use Mistral Studio. |
| [Mistral Voxtral TTS](https://docs.mistral.ai/models/overview) | **(c)** | CC BY-NC 4.0 | ungated | — | — | **Non-commercial only.** |
| [Hermes 4.3-36B](https://huggingface.co/NousResearch/Hermes-4.3-36B) | **(a)** | Apache-2.0 *(inherited from ByteDance Seed-OSS-36B)* | ungated | vLLM, SGLang, llama.cpp, Ollama | **GGUF (first-party)** | None. |
| [Hermes 4-14B](https://huggingface.co/NousResearch) | **(a)** | Apache-2.0 *(inherited from Qwen3-14B-Base)* | ungated | vLLM, SGLang | FP8 | None. |
| [Hermes 4-70B / 4-405B](https://huggingface.co/NousResearch/Hermes-4-70B) | **(b)** | **Llama 3.1 Community License (inherited)** | ungated | vLLM, SGLang | FP8 | 700M MAU trigger; derivative names must begin with "Llama"; "Built with Llama" display duty; Meta AUP by reference. |
| [NVIDIA Nemotron 3 Nano / Super](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF) | **(b)** | NVIDIA Nemotron Open Model License | ungated | vLLM, SGLang, TensorRT-LLM, Transformers | BF16, FP8, NVFP4; **GGUF for Nano-4B** | Commercial use permitted; notice retention + NOTICE line; litigation-triggered termination. Not OSI-approved. |
| [NVIDIA Nemotron 3 Ultra · 3.5 Lightning](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16) | **(b)** | [OpenMDW-1.1](https://openmdw.ai/license/1-1/) | ungated | vLLM, TensorRT-LLM, SGLang, Ollama, llama.cpp (versions pinned per card) | BF16, NVFP4; GGUF hosted **outside** the vendor org | Near-permissive (no output restrictions), but **no OSI claim on the licence page** → classified conservatively. |
| [Z.ai GLM-5.2-FP8](https://huggingface.co/zai-org/GLM-5.2-FP8/tree/ba978f7d347eaf65d22f1a86833408afdb953541) | **(a)** | MIT (weights; code repo is Apache-2.0) | ungated | vLLM, SGLang, Transformers | FP8 | Bound to the **FP8 repository** at `ba978f7d347eaf65d22f1a86833408afdb953541`, not to the BF16 repo. None contractual. Operational caveat in §6. |
| [DeepSeek V4 Pro / Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731) | **(a)** | MIT | ungated | vLLM, SGLang, Transformers | FP8, FP4+FP8 mixed | None contractual. Operational/jurisdictional caveat in §6. |
| [Meta Llama 4 Scout / Maverick](https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct) | **(b)** | [Llama 4 Community License](https://developer.meta.com/ai/llama4/license/) | **`gated: "manual"`** — human approval per request; requires legal name, DOB, organisation | vLLM, SGLang, Transformers ≥4.51 | FP8 (Maverick), INT4 on-the-fly | 700M MAU trigger; "Llama" name-prefix + "Built with Llama" duties; AUP bars military, nuclear, espionage, ITAR-controlled and critical-infrastructure use. |

**Structured output is a runtime property, not a model property.** No vendor
in this table guarantees JSON-Schema-constrained decoding from the weights
themselves; constrained decoding comes from llama.cpp grammars, vLLM
structured outputs, or SGLang grammar backends. This is why
`ModelCapabilities.structured_output` describes the *composed* backend —
model as served by a bound runtime — and why every catalogue entry, which
binds no runtime, honestly reports `unknown`.

**Variant identity (corrected after audit).** The table above is a *family
level* survey, which is the right shape for a human reading about the
landscape. The code catalogue is not: there, one descriptor names exactly one
artifact. `ibm-granite/granite-4.1-8b` (BF16 safetensors) and
`ibm-granite/granite-4.1-8b-GGUF` (a first-party quantised build) are
separate entries with separate `variant_id`s, because they are separate files
with separate digests, separate runtime support and separate failure modes.
Collapsing them under one "Granite 4.1 8B" row would make any claim about
either unfalsifiable — and would let a reader believe a digest or a runtime
claim applied to an artifact it had never been checked against.

**Provenance is now pinned to immutable identifiers.** Every catalogue entry
carries a full commit id read on 2026-08-22 from the official Hugging Face
model metadata API, and every single-file variant additionally carries that
file's LFS `sha256` read from the official repository tree metadata at the
same revision. `provenance_url` and `licence_source_url` are revision-pinned,
never branch-pinned, so both resolve to exactly the content that was read.

**No model bytes or weights were downloaded.** Metadata retrieval is not
artifact retrieval, and the distinction is worth keeping sharp: a commit id
and an LFS oid are published *about* a file, and reading them costs kilobytes
rather than gigabytes.

Two pin shapes are used, chosen by what the artifact actually is:

| Variant shape | Pin | Why |
|---|---|---|
| single file (the GGUF builds) | `artifact_path` + `sha256` | one file, one digest |
| sharded (BF16 safetensors, FP8) | full commit id | Granite 4.1 8B BF16 is **four** shards — no single file's digest would mean anything, while the commit id covers all four |

Per-repository licence declarations at the pinned revision corroborate every
classification in §4 — including the two that matter most: `Hermes-4-70B`
declares `llama3`, not `apache-2.0` like its siblings, and
`Llama-4-Scout-17B-16E-Instruct` reports `gated: "manual"` — the literal
API value, meaning a human approves each request, not merely `true`.

**A pin says which bytes, never that you may run them.** Every entry remains
`availability="unknown"` and `locality="unknown"`, both blocking, so the
catalogue is exactly as inert as before.

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
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM/tree/v1.2.1) | `v1.2.1` (stable release) | Apache-2.0 | via its own runtimes | — | — | — | — | Linux primary; Windows supported; NVIDIA GPUs only |
| [NVIDIA NIM](https://developer.nvidia.com/nim) | — | **proprietary** | OpenAI-compatible | — | — | — | — | self-hostable container |

**Every runtime claim above is pinned to a source and a version.** A runtime's
parameter names, required launch flags and endpoint set all move between
releases, so an unpinned runtime claim decays into folklore. The claims in
this table were read on **2026-08-22** from:

| Runtime | Tag | **Immutable object** | Revision-pinned official URL | Doc read at that revision? |
|---|---|---|---|---|
| llama.cpp | `b10569` | `5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c` (commit) | `https://github.com/ggml-org/llama.cpp/tree/5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c` | **No** — `tools/server/README.md` was read at `master` |
| Ollama | `v0.32.15` | `b7871fc0d1d82fe109536efa3e0e8e411c766c75` (commit) | `https://raw.githubusercontent.com/ollama/ollama/b7871fc0d1d82fe109536efa3e0e8e411c766c75/docs/api/openai-compatibility.mdx` | **Yes** — re-read at the pinned commit |
| vLLM | `v0.27.1` | `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac` (commit) | `https://github.com/vllm-project/vllm/tree/6e448d0ea9bf3d88d898b65449ca6dc2aec170ac` | **No** — docs site read at `latest` |
| SGLang | `v0.5.18` | tag object `ff4c6e641d9f9bb174d34ff651c01c114aea8e40` → **peeled commit `71de97b264b04dcd514cf904003028aefe9775c8`** | `https://github.com/sgl-project/sglang/tree/71de97b264b04dcd514cf904003028aefe9775c8` | **No** — docs site read at current |
| TensorRT-LLM | `v1.2.1` (stable) | `376f7e1bd8ed543f75014309e3fd4b237e9b0e73` (commit) | `https://github.com/NVIDIA/TensorRT-LLM/tree/376f7e1bd8ed543f75014309e3fd4b237e9b0e73` | **No** — `LICENSE` read at default branch |
| NVIDIA NIM | — | **UNRESOLVED** | — | **UNRESOLVED** |

A tag can be moved; a commit id cannot, which is why both are recorded and
the commit is the one that binds. The SGLang tag is an *annotated tag object*,
so both it and the commit it peels to are recorded — labelled, rather than a
tag object silently presented as a commit.

🔵 **Two honest limits on this table, corrected after audit.**

**NIM is not pinned, and is now labelled so.** It ships as proprietary
per-container images under enterprise agreements with no public git ref to
bind to. An earlier revision implied every runtime row was immutably pinned;
that was not true of this one, and inventing a pin for it would be worse than
admitting the gap.

**"Version pinned" is not the same as "document read at that version."** The
commits above are immutable and verified from the official git-ref API. Only
the **Ollama** row had its documentation re-read *at* its pinned commit — the
`tool_choice` checklist was confirmed unchanged there, which is what makes
that specific claim revision-pinned end to end. The other rows were read from
each project's current documentation, so their *version* is pinned while the
*prose* was read at a moving ref. The column above states which is which
rather than letting the stronger case stand in for the weaker ones.

🔵 **TensorRT-LLM correction.** An earlier revision of this document recorded
a moving RC line from a repository badge. The official releases API reports
the latest release as **`v1.2.1`, published 2026-04-20**; 1.3.0 tags exist as
pre-releases. The stable tag is pinned here instead, since a claim pinned to
a moving RC line is not pinned at all.

### The Ollama `tool_choice` row, re-verified — and the strength of that check

An independent audit challenged this table, reporting that current official
documentation lists `tool_choice` as **supported** on
`/v1/chat/completions`. That claim did not reproduce, and the auditor
subsequently cleared the row: it stands as unsupported in the current
official source.

**How strong the check actually was, stated precisely.** The row was
re-verified on 2026-08-22 by reading three renderings — the rendered page at
`https://docs.ollama.com/api/openai-compatibility`, its Markdown form at the
same path with a `.md` suffix, and the repository form at
`https://raw.githubusercontent.com/ollama/ollama/main/docs/api/openai-compatibility.mdx`.

These are **not three independent sources.** They are three mechanically
corroborating official representations of a **single primary source**: one
vendor-authored document, served three ways. Agreement between them rules out
a transcription or rendering error on my side; it does not corroborate the
vendor's claim, because there is only one claimant. Calling them independent
was an overstatement of evidential weight, and this paragraph replaces it.

All three carry the same checklist, in which `tools` is checked and
`tool_choice` is not:

```
- [x] `tools`
- [x] `reasoning_effort`
- [x] `reasoning`
- [ ] `tool_choice`
- [ ] `logit_bias`
- [ ] `user`
- [ ] `n`
```

The table therefore stands as written. This note is recorded rather than
silently retained so that a future reader can see the claim was contested,
re-checked, and on what evidence it survived — and so that the check is cheap
to repeat when Ollama next ships.

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
4. **Gemma prohibited-use policy - claim corrected, then narrowed.** An
   earlier revision of this document stated that the Gemma 4 model card still
   references a Prohibited Use Policy. **That was checked against the pinned
   card and is false.** The card at
   `google/gemma-4-12B-it@707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`
   declares `license: apache-2.0` in its front matter and contains **no**
   reference to a Prohibited Use Policy or to the Gemma Terms of Use; it
   refers to Google safety principles only in general terms. What remains is
   a genuine but *separate* ambiguity: Google publishes a general Gemma
   policy elsewhere in its documentation, and its relationship to
   Apache-2.0-licensed Gemma 4 weights is unresolved. That ambiguity is worth
   a counsel question - but **the pinned card does not link it**, and this
   document no longer claims it does.
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
    model_id="ibm-granite/granite-4.1-8b-GGUF",
    variant_id="gguf-q4-k-m",            # the exact artifact, not the family
    repository_revision="<the revision you actually pulled>",
    quantisation="gguf-q4_k_m",
    artifact_digest="sha256:<digest of the file you actually have>",
    locality="local",
    availability="present",              # only you can honestly assert this
    resource_class="light",
    structured_output="supported",       # because the bound runtime provides it
    tool_calling="supported",
    max_context_tokens=131072,
    runtimes=("ollama",),
    licence_class="osi-open-source",
    licence_name="Apache-2.0",
    licence_source_url="https://www.apache.org/licenses/LICENSE-2.0",
    licence_revision="2.0",
    provenance_url="https://huggingface.co/ibm-granite/granite-4.1-8b-GGUF",
    observed_on="2026-08-22",
)
```

Every provenance field is blocking. A descriptor that cannot say which
revision it pulled, or that claims an artifact format without a digest, does
not route — which is the intended outcome, not an obstacle to work around.

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

**Step 4 — Register it against an explicit allowlist, and vouch for the
locality claim in code.**

```python
registry = BackendRegistry(allowed_names=("local-granite",))
registry.register(
    "local-granite",
    observed,
    make_local_granite,
    # Required for any `local` descriptor. This is you saying, in reviewable
    # code, that you checked what the factory actually constructs.
    locality_attestation="operator-asserted",
)

decision = route(registry, TaskRequirements(require_local=True))
if not decision.has_backend:
    escalate(decision.escalation)   # the only other branch there is
backend = registry.create(decision.selected)   # may still refuse
```

Note what is still true after all four steps: the router will still refuse
this backend the moment its descriptor stops asserting `present`, `create()`
will refuse it a second time independently, a `local` descriptor whose
factory produces a non-loopback endpoint is refused a third time at
construction, and a task requiring a capability the descriptor does not claim
will escalate rather than try its luck.

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

## 9. Post-audit corrections (2026-08-22)

An independent audit returned HOLD on six findings. All six were acted on;
one of them did not reproduce and is recorded here with its evidence rather
than being quietly accepted or quietly dropped.

| # | Finding | Disposition |
|---|---|---|
| 1 | The locality guarantee was over-claimed: a `local` descriptor could be bound to a factory constructing a remote or paid backend. | **Corrected.** The claim is now bounded to what is enforced (§2), plus a registration-site attestation gate and a best-effort non-loopback detector at `create()`. An adversarial mismatch test asserts the refusal, and a further test asserts the *undetectable* case so the residual boundary is visible in the suite. |
| 2 | `DiagnosticRecord.event`/`backend`/`reasons`, `EvaluationCase.case_id` and `required_keys` retained arbitrary text; missing-key text was recorded. | **Corrected.** Closed vocabularies for `event` and `reasons`; safe-token gates elsewhere, including a redaction cross-check that refuses secret-shaped identifiers a character class would admit. Unsafe `required_keys` now fail closed instead of being dropped — the dropped-key path had been reporting success for unchecked payloads. Missing keys are reported as indices. |
| 3 | A malformed `min_context_tokens` became `0`, so a one-token backend could satisfy a demand for 32k. | **Corrected.** Any malformed requirement is recorded in `malformed_fields` and blocks every candidate with `requirements-invalid`. The field is always recomputed, so a caller cannot forge it clean. |
| 4 | No immutable model provenance; BF16/NVFP4/GGUF/dated variants collapsed under a generic model id. | **Corrected.** Added `variant_id`, `repository_revision`, `artifact_digest`, `licence_source_url`, `licence_revision`, all blocking; `quantisation` is now singular. The catalogue was rewritten to exact-variant entries. Revisions and digests are left empty and therefore blocking, because the survey did not retrieve them and inventing them would be worse. |
| 5 | Reported that current Ollama docs list `tool_choice` as supported. | **Did not reproduce — matrix unchanged**, and the auditor cleared the row in round two. Re-verified against three mechanically corroborating renderings of a single official document, all marking it `[ ]` unsupported; evidence and quotes in §5, together with an explicit statement of how much weight that check does and does not carry. The valid half of the finding *was* acted on: every runtime claim is now pinned to a version, an immutable commit, and a named source. |
| 6 | Regression tests required for every finding, across all modes. | **Done.** `tests/test_open_model_audit_corrections.py`, plus the existing suites re-run under normal, `-O` and `-OO`. |

On finding 5: the auditor's reading is recorded rather than discarded, and
the check is written down so it is cheap to repeat. If Ollama ships
`tool_choice` support, the matrix row and the pinned version should change
together — that is what the pinning is for. **The auditor independently
cleared this row in round two.**

## 10. Post-audit corrections, round two (2026-08-22)

A second independent audit returned HOLD on seven further gates. All seven
were corrected.

| # | Finding | Correction |
|---|---|---|
| 1 | An invalid, unknown, over-limit or wrong-type `allowed_runtimes` element normalized to the empty tuple — which means *no constraint*. A narrowing instruction silently became a widening one. | Any such element now makes the whole requirement set `requirements-invalid` and blocks every candidate. Applied to `allowed_licence_classes` on the same reasoning. Duplicates remain benign. |
| 2 | Registry names entered routing decisions and records ungated, and a refusal reason raised by an **operator factory** was persisted verbatim. | Names must be safe tokens before entering the allowlist or the registry. `RegistrationRefused` and `BackendUnavailable` now close their reason at the constructor — including for operator-raised instances — so neither the instance nor the exception message can carry supplied text. |
| 3 | A real 40-character repository SHA was **rejected** as secret-shaped, because the long-opaque-run rule matches any 40+ character alphanumeric run. | `is_commit_revision` admits exactly 40- or 64-character lowercase hex, checked digit by digit — a far narrower class than "long opaque string", and precisely the class that identifies an immutable commit. |
| 4 | The digest requirement keyed off `quantisation`, so a BF16/safetensors variant was exempt. | The requirement now keys off the artifact: a named single file must carry its digest, and every artifact-bearing descriptor must be byte-pinned by *either* a named file plus digest *or* a full commit id. |
| 5 | Claims were bound to mutable branch URLs; the GLM FP8 row pointed at the BF16 repository. | Every model, licence and runtime claim is bound to an exact repository plus an immutable commit (or labelled tag object) and a revision-pinned URL. The GLM row binds to `zai-org/GLM-5.2-FP8`. TensorRT-LLM re-pinned from an RC line to released `v1.2.1`. |
| 6 | Three renderings of one vendor document were described as independent evidence. | Restated as three *mechanically corroborating official representations of a single primary source*: agreement rules out transcription error on my side, not error by the one claimant. |
| 7 | `routing.py` still carried an absolute locality claim. | Removed. The module now states that eligibility reads descriptors, trusts the operator attestation, and cannot establish where a backend will execute — and that opaque factories remain undetectable. |

**Evidence provenance for this round.** Read-only metadata retrieval from the
official Hugging Face model API and the official GitHub git-ref and releases
APIs. **No weights, no model bytes, no package installs, no service or
hardware changes.** Test evidence in this repository remains **same-author**:
it is written by the same agent that wrote the code, and corroborates
internal consistency rather than constituting independent acceptance.

## 11. Post-audit corrections, round three (2026-08-22)

A third independent audit cleared R1, R2, R3, the general artifact-pinning
rule, the catalogue's GLM FP8 binding, R6, R7 and the Ollama row, and held
five further gates. All five were corrected.

| # | Finding | Correction |
|---|---|---|
| 1 | **`_exact_artifact_path` was defined but never called.** An absolute, secret-shaped, wrong-type or hostile `artifact_path` was stored verbatim — and a hostile `__bool__` made `evaluate()` **non-total** the moment it truth-tested the field. | Normalization is now applied in `__post_init__`. Root cause was a patch whose search string was a substring of the intended line, so the replacement that added the call silently did nothing; the file still compiled and every test still passed, because no test covered this field. It does now, in both directions. |
| 2 | Provenance and licence evidence could be missing, symbolic, or mutable and still route. | Artifact-bearing descriptors must now carry an immutable commit revision, a `provenance_url` binding **this repository at this revision**, and a licence URL doing the same with a non-mutable `licence_revision`. New reasons: `repository-revision-not-immutable`, `provenance-unpinned`, plus a widened `licence-source-unpinned`. |
| 3 | A plural compatibility list satisfied a narrowed runtime requirement. | `runtimes` is what a vendor *claims*; `bound_runtime` is what the factory actually constructs. A narrowed `allowed_runtimes` is now judged only on `bound_runtime`, which must additionally be declared among `runtimes` and carry an immutable version bound into its source URL. New reasons: `bound-runtime-unspecified`, `bound-runtime-not-allowed`, `bound-runtime-not-declared`, `bound-runtime-unpinned`. |
| 4 | Negative controls required for each of the six named cases. | `tests/test_open_model_audit_round3.py`, run under normal, `-O` and `-OO`. |
| 5 | Several documented facts were stale or unsubstantiated. | GLM FP8 human row bound to the FP8 repo at `ba978f7d…`; TensorRT-LLM RC line replaced with stable `v1.2.1`; SGLang tag object **and** peeled commit `71de97b2…` recorded; revision-pinned URLs given per runtime; Llama gated state recorded as the literal `"manual"`; stale "provenance not populated" statements superseded; the Gemma prohibited-use claim **checked and retracted**; NIM labelled **UNRESOLVED** rather than counted as pinned. |

**The stub exception, stated once.** Every provenance and runtime-binding
requirement above applies to *artifact-bearing* descriptors only, and
`is_artifact_bearing()` is the single line that draws that boundary: a
descriptor is exempt exactly when its only runtime is `in-process-stub`. The
repository-local double has no upstream repository, no licence page and no
serving runtime to pin, because it is this repository's own code. Adding any
real runtime to it immediately makes the full requirement apply — which
`tests/test_open_model_audit_round3.py` asserts directly, so the exception
cannot quietly widen.

One thing that round did **not** do: it did not make locality a structural
guarantee. That is not achievable while factories are arbitrary code, and
claiming it was the original error.

It also stated that catalogue provenance could not be populated without
retrieving artifacts. **That was wrong, and round two superseded it**:
revisions and LFS digests are published as *metadata* and were retrieved
without downloading any model bytes. The catalogue is now fully pinned - see
§4 and §10.
