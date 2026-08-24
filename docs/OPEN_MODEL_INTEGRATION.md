# OPEN_MODEL_INTEGRATION.md — OMI-V1 and OMI-V2

> **Status**: implemented foundation + dated source matrix (OMI-V1, §§1–15),
> plus a closed structured-output request contract (OMI-V2, §16), plus an
> inert observation envelope built on top of it (OMI-V3A, §17 — full contract
> in [`OMI_V3_OBSERVATION_INCEPTION.md`](OMI_V3_OBSERVATION_INCEPTION.md)).
> Packages
> [`scripts/open_model/`](../scripts/open_model/) and, for OMI-V2 only,
> [`scripts/agent_backends/structured_request.py`](../scripts/agent_backends/structured_request.py).
>
> **What this is NOT.** No model has been downloaded, installed, served,
> benchmarked, or run in producing this document or the code it describes. No
> endpoint was contacted. No package was installed. Nothing here is a
> performance result or a recommendation to deploy a particular model. The
> matrix below is *metadata read off vendors' own pages on 2026-08-22*, and
> metadata is not approval. The OMI-V2 wire shapes in §16 are read from each
> runtime's own repository at a pinned revision — also metadata, also not a
> claim that any of it was executed.
>
> **On modifying the backend seam.** OMI-V1 sat entirely **above** the merged
> agent-backend seam in [`scripts/agent_backends/`](../scripts/agent_backends/)
> and modified nothing in it. That is no longer true of the repository as a
> whole: **OMI-V2 deliberately modified `OpenAICompatBackend`** — see §16 for
> what changed and why, and §8 for the superseded statement it replaces. The
> standing boundary in
> [`LOCAL_MODEL_DEPLOYMENT_INCEPTION.md`](LOCAL_MODEL_DEPLOYMENT_INCEPTION.md)
> — *reuse, don't reinvent; no second transport stack* — is unaffected and
> still holds: OMI-V2 adds one request field to the existing seam and invents
> no transport, no client, and no parallel backend.

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

> 🔴 **This table is a DATED FAMILY SURVEY. It is NOT pinned evidence.**
> Its links are ordinary vendor pages — repository landing pages without a
> revision, help-centre articles, licence portals — and **those pages move**.
> A claim in this table was true of what a human read on 2026-08-22 and is
> not independently verifiable from the link alone afterwards.
>
> **The pinned evidence in this work is the 12 descriptors in
> [`scripts/open_model/catalogue.py`](../scripts/open_model/catalogue.py)**,
> and only those. Each carries an exact repository, a full immutable commit
> id, revision-pinned `provenance_url` and `licence_source_url`, and — for
> single-file variants — an LFS `sha256`. Those are enforced: a descriptor
> that loses any of them stops routing.
>
> Read this section for orientation across the landscape. Read the catalogue
> when you need a claim that can be checked.

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
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | v0.2.0 / build b10569 | MIT | `/v1/chat/completions`, `/v1/completions`, `/v1/responses`, and Anthropic-shaped `/v1/messages` | `grammar` (GBNF) or `json_schema` on `/completion`; `response_format.json_schema.schema` for `type=json_schema` — the flat `response_format.schema` is read **only** for `type=json_object`, and the server README contradicts the server source on this (§16.3) | yes, **requires `--jinja`** | `/v1/models` | `/health` | **yes** (MSVC, winget, prebuilt, WoA arm64) |
| [Ollama](https://github.com/ollama/ollama) | v0.32.15 | MIT | `/v1/chat/completions`, `/v1/models`, `/v1/responses` | native `format` on `/api/chat` (`"json"` or a schema); `response_format` on `/v1` | yes, no server flag — but **`tool_choice` is not supported on `/v1`** | `/api/tags`, `/v1/models` | `GET /` (source-verified only) | **yes** (native app, Win10 22H2+) |
| [vLLM](https://github.com/vllm-project/vllm) | v0.27.1 | Apache-2.0 | `/v1/chat/completions`, `/v1/responses`, `/v1/models` | `extra_body={"structured_outputs":{…}}` — **`guided_*` was removed in v0.12.0** — or `response_format.json_schema.schema` | yes, **requires `--enable-auto-tool-choice` + `--tool-call-parser`** | `/v1/models` | `/health` | **no** — WSL only |
| [SGLang](https://github.com/sgl-project/sglang) | v0.5.18 | Apache-2.0 | `/v1/chat/completions`, `/v1/models`, plus Ollama-shaped `/api/chat` | `response_format.json_schema.schema`, or `extra_body={"ebnf"` \| `"regex"}`; native puts them in `sampling_params` — **exactly one** constraint per request | yes, **requires `--tool-call-parser`**; `required`/named fully supported only on the xgrammar backend | `/v1/models` | `/health`, `/health_generate` | **unverified — assume unsupported** |
| [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM/tree/v1.2.1) | `v1.2.1` (stable release) | Apache-2.0 | via its own runtimes | — | — | — | — | Linux primary; Windows supported; NVIDIA GPUs only |
| [NVIDIA NIM](https://developer.nvidia.com/nim) | — | **proprietary** | OpenAI-compatible | — | — | — | — | self-hostable container |

**Runtime claims are pinned to a version, with one exception and one
caveat, both stated in the table below.** The exception is **NVIDIA NIM**,
which has no public git ref and is recorded as **UNRESOLVED**. The caveat
is that a pinned *version* is not the same as a document *read at* that
version - only the Ollama row is pinned end to end. A runtime's
parameter names, required launch flags and endpoint set all move between
releases, so an unpinned runtime claim decays into folklore. The claims in
this table were read on **2026-08-22** from:

| Runtime | Tag | **Immutable object** | Revision-pinned official URL | Doc read at that revision? |
|---|---|---|---|---|
| llama.cpp | `b10569` | `5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c` (commit) | `https://github.com/ggml-org/llama.cpp/tree/5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c` | **Yes** — `tools/server/README.md` and `tools/server/server-common.cpp` both re-read at the pinned commit; **they disagree**, and the executable source is followed (§16.3) |
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

- All four runtimes read the schema at `response_format.json_schema.schema`
  for `type=json_schema`. llama.cpp additionally reads a flat
  `response_format.schema`, but **only** for `type=json_object` — its README
  says otherwise and its source is what runs (§16.3). vLLM and SGLang also
  carry a `json_schema.name`; llama.cpp and Ollama have no such field.
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
- **No changes to `OpenAICompatBackend`.** ~~It still has no
  `response_format`, `json_schema`, or `seed` support.~~ Adding a normalised
  structured-output parameter across the four runtime dialects in §5 is the
  obvious next package; it is not this one, and doing it here would have
  meant editing a merged, tested backend outside the stated scope.

  > **Superseded by OMI-V2 (§16), 2026-08-23.** This bullet describes OMI-V1
  > accurately and is kept as written rather than rewritten. It is no longer
  > true of the repository: `OpenAICompatBackend` now has a closed
  > `response_format` path across exactly the four dialects named above,
  > added as its own authorised package. `seed` remains unsupported and
  > explicitly out of scope.
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
| 5 | Reported that current Ollama docs list `tool_choice` as supported. | **Did not reproduce — matrix unchanged**, and the auditor cleared the row in round two. Re-verified against three mechanically corroborating renderings of a single official document, all marking it `[ ]` unsupported; evidence and quotes in §5, together with an explicit statement of how much weight that check does and does not carry. The valid half of the finding *was* acted on: runtime claims are now pinned to a version, an immutable commit and a named source — **except NIM, which has no public ref and is recorded UNRESOLVED**, and noting that four of five rows had their prose read at a moving ref rather than at the pinned commit. |
| 6 | Regression tests required for every finding, across all modes. | **Done.** `tests/test_open_model_audit_corrections.py`, plus the existing suites re-run under normal, `-O` and `-OO`. |

On finding 5: the auditor's reading is recorded rather than discarded, and
the check is written down so it is cheap to repeat. If Ollama ships
`tool_choice` support, the matrix row and the pinned version should change
together — that is what the pinning is for. **The auditor independently
cleared this row in round two.**

One thing that round did **not** do: it did not make locality a structural
guarantee. That is not achievable while factories are arbitrary code, and
claiming it was the original error.

It also stated that catalogue provenance could not be populated without
retrieving artifacts. **That was wrong, and round two superseded it**:
revisions and LFS digests are published as *metadata* and were retrieved
without downloading any model bytes. The catalogue is now fully pinned - see
§4 and §10.

## 10. Post-audit corrections, round two (2026-08-22)

A second independent audit returned HOLD on seven further gates. All seven
were corrected.

| # | Finding | Correction |
|---|---|---|
| 1 | An invalid, unknown, over-limit or wrong-type `allowed_runtimes` element normalized to the empty tuple — which means *no constraint*. A narrowing instruction silently became a widening one. | Any such element now makes the whole requirement set `requirements-invalid` and blocks every candidate. Applied to `allowed_licence_classes` on the same reasoning. Duplicates remain benign. |
| 2 | Registry names entered routing decisions and records ungated, and a refusal reason raised by an **operator factory** was persisted verbatim. | Names must be safe tokens before entering the allowlist or the registry. `RegistrationRefused` and `BackendUnavailable` now close their reason at the constructor — including for operator-raised instances — so neither the instance nor the exception message can carry supplied text. |
| 3 | A real 40-character repository SHA was **rejected** as secret-shaped, because the long-opaque-run rule matches any 40+ character alphanumeric run. | `is_commit_revision` admits exactly 40- or 64-character lowercase hex, checked digit by digit — a far narrower class than "long opaque string", and precisely the class that identifies an immutable commit. |
| 4 | The digest requirement keyed off `quantisation`, so a BF16/safetensors variant was exempt. | The requirement now keys off the artifact: a named single file must carry its digest, and every artifact-bearing descriptor must be byte-pinned by *either* a named file plus digest *or* a full commit id. |
| 5 | Claims were bound to mutable branch URLs; the GLM FP8 row pointed at the BF16 repository. | **Scoped to the 12 code-catalogue descriptors**: each is bound to an exact repository plus a full immutable commit and revision-pinned URLs. **The §4 family survey is NOT covered** — it is a dated survey over moving vendor pages and is labelled as such. Of the runtime claims, **every one except NVIDIA NIM** is bound to an immutable commit or labelled tag object; **NIM has no public git ref and remains UNRESOLVED**, not counted as pinned. The GLM row binds to `zai-org/GLM-5.2-FP8`. TensorRT-LLM re-pinned from an RC line to released `v1.2.1`. And a pinned *version* is not a document *read at* that version; only the Ollama row is pinned end to end (§5). |
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
`is_artifact_bearing()` is the single line that draws that boundary. Round
four changed *how* that line is drawn — see §12.

## 12. Post-audit corrections, round four (2026-08-22)

A fourth independent audit cleared the round-three controls, the twelve model
revision pins, the three GGUF digests, the five runtime commit targets, the
Ollama row, GLM FP8 identity, and the head/base/path inventory. Six gates
remained.

| # | Finding | Correction |
|---|---|---|
| 1 | `artifact_path` accepted URL schemes and absolute paths verbatim, and a traversal path **collapsed to `""` and then routed** through the repository-commit fallback as though no artifact had been claimed. | `is_canonical_relative_path` rejects schemes, absolute paths, drive letters, backslashes, userinfo, queries, fragments, whitespace, control characters, and any empty/`.`/`..` component. A supplied-but-unusable value now sets `invalid_fields` and blocks with `descriptor-invalid` — it is never silently blanked. |
| 2 | Evidence URLs were bound by **substring**, so `https://evil.invalid/?x=huggingface.co/org/model/tree/<sha>` satisfied them. | `parse_https_url` parses structurally and rejects userinfo, ports, queries, fragments, control characters, non-canonical hosts and `..`. `is_official_evidence_url` then requires the path to *equal* `/{repo}/{kind}/{revision}`. Model evidence must come from `huggingface.co`, runtime evidence from `github.com`. |
| 3 | A mutable tag name such as `v0.27.1` inside any URL counted as an immutable runtime binding. | Runtime evidence must resolve to a **full commit id** or a full **tag-object id explicitly labelled** via `bound_runtime_object_kind`, with the source URL on the official host and ending in that object id. |
| 4 | A missing `bound_runtime` routed whenever the task did not narrow runtimes. | Every artifact-bearing descriptor must declare a bound runtime, **whatever the task asked for**. "The task did not ask" is not a reason to stop requiring it. |
| 5 | The `in-process-stub` exemption was a **copyable field value** — any external author could type that string and bypass every gate at once. | Exemption is now a property of *how the descriptor was constructed*, not what it says: only an object handed out through `register_harness_double` is exempt, checked **by identity**, so an equal-but-separately-constructed copy is not. A test asserts that closed path has exactly one caller. |
| 6 | Surviving prose overstated what was pinned. | The catalogue's Gemma note now records the retraction; Llama's note records the literal `gated: "manual"`; the "every runtime claim is pinned" heading is narrowed; the round-two all-pinned statement is qualified. NIM stays **UNRESOLVED**, and pinned commits stay distinguished from documents read at moving references. |

🔵 **Two defects the round-four controls found, recorded rather than
quietly fixed.** A secret-bearing URL query was *refused for routing* but
still **stored** on the descriptor and visible in its `repr` — URL fields are
now structurally normalized at construction, so a credential never lands in
the object at all. And the credential check initially rejected every
legitimate pinned URL, because a 40-character hex commit id matches the
long-opaque-run secret rule — the same false positive `is_commit_revision`
exists to avoid. `has_credential_shape` now skips exactly that one rule, by
identity, while every other secret rule still applies; queries, fragments and
userinfo are already refused structurally, so a credential has no
conventional place left to hide.

## 13. Post-audit corrections, round five (2026-08-22)

A fifth independent audit cleared all six round-four gates under normal,
`-O` and `-OO`, and held four findings.

| # | Finding | Correction |
|---|---|---|
| 1 | `bound_runtime` was bound only to `github.com` plus a trailing object id, so a **genuine vLLM commit could vouch for an unrelated repository** — `https://github.com/evil-org/fake-runtime/tree/<real vLLM commit>` satisfied it. | `RUNTIME_REPOSITORIES` close-maps each token to its exact official repository (`llama-cpp`→`ggml-org/llama.cpp`, `ollama`→`ollama/ollama`, `vllm`→`vllm-project/vllm`, `sglang`→`sgl-project/sglang`, `tensorrt-llm`→`NVIDIA/TensorRT-LLM`), and the **complete** canonical `/{owner}/{repository}/tree/{object}` path must match. `in-process-stub` deliberately has no entry. |
| 2 | The long-opaque-run rule was skipped for the **whole URL**, which excused a 48-character credential sitting in the owner, repository or file-name position. | Secret detection is now **per path component**. The long-run rule is waived only for a component that *exactly equals* this descriptor's own repository revision or runtime object id; every other component — owner, repository, file name — gets the full matcher, and so does the host. A foreign 40-hex run is refused. |
| 3 | A secret-bearing licence path was **stored** on the descriptor even though routing refused it, so it sat in the `repr` and in any log built from one. | A refused URL is never stored. Asserted directly against both the model and licence evidence fields. |
| 4 | `%2e%2e/%2e%2e/README.md` was neither decoded nor refused — it was stored **and the descriptor stayed eligible**, a working traversal-equivalent bypass. | Percent-encoding is **forbidden outright** in evidence URLs and artifact paths. Decoding would mean re-deriving canonicality afterwards, and `%2e%2e`, `%2f`, `%40` and `%00` reintroduce exactly the traversal, separator, userinfo and control cases the parser already refuses. |
| 5 | The round-two table still stated that every model, licence and runtime claim was immutably pinned. | That row now says inline that **NIM has no public git ref and remains UNRESOLVED**, and repeats that a pinned version is not a document read at that version. |

🔵 **On finding 4 specifically**: the reproduction was worse than reported.
`%2e%2e` was not merely stored — the descriptor remained *eligible*, because
the canonical-path check saw three ordinary-looking components and none of
them was literally `..`. That is the whole argument for refusing percent
encoding rather than decoding it.

## 14. Post-audit corrections, round six (2026-08-22)

A sixth independent audit cleared all four round-five findings and held two
gates.

| # | Finding | Correction |
|---|---|---|
| 1 | `RUNTIME_REPOSITORIES` was a `Final[dict]`. **`Final` is a type-checker annotation with no runtime effect**, so `RUNTIME_REPOSITORIES["vllm"] = "evil-org/fake-runtime"` silently restored eligibility for an attacker-selected repository — and `update`, `del`, `pop` and `clear` worked just as well. | The authoritative data is now a **tuple of pairs captured in a closure**, reachable by no ordinary expression, and consulted through a private lookup function. `RUNTIME_REPOSITORIES` remains exported as a **`MappingProxyType`** read-only view over a private copy: `__setitem__`, `__delitem__`, `update`, `pop`, `popitem`, `clear` and `setdefault` all refuse. Routing reads the closure, **not** the exported name, so even re-binding the module attribute changes nothing about what is trusted. |
| 2 | The documentation claimed every model and licence claim was immutably pinned, while the **§4 family survey** still linked moving vendor pages — repository landing pages without a revision, help-centre articles, licence portals. | §4 now opens with an explicit label: it is a **dated family survey, not pinned evidence**, and those pages move. The pinning claim is **scoped to the 12 code-catalogue descriptors**, and the round-two row says so inline. A test asserts the scoped claim is actually *true* of all twelve, so the narrowing cannot become a way to say less and check less. |

**On gate 1, stated plainly.** Python has no true privacy. `__closure__`
cell surgery, or replacing this module in `sys.modules`, could still defeat
the closure. Those are not ordinary mutation paths; the claim here is bounded
to the ordinary ones — assignment, deletion, `update`, `pop`, `clear`,
`setdefault`, and re-binding the exported name — all of which are now closed
and asserted closed under normal, `-O` and `-OO`.

> ⚠️ **Superseded by round seven (§15).** The account above is preserved as
> the historical record of what round six did, but its central design — a
> **private closure lookup that routing consults** — is no longer how this
> works. Round six closed the trust *data* name and left the *lookup* name
> resolvable at call time, so rebinding `_runtime_repository_for` still
> redirected routing. Round seven **inlined the five repositories and the
> evidence host into `has_pinned_runtime_binding` as code constants**, and
> routing now consults neither `RUNTIME_REPOSITORIES` nor
> `_runtime_repository_for`. Both remain exported, as **inspection and
> testing mirrors only**. Read §15 for the design that is actually in force.

## 15. Post-audit corrections, round seven (2026-08-22)

A seventh independent audit cleared the public-mapping immutability and the
documentation scoping, and held one material gate.

| # | Finding | Correction |
|---|---|---|
| 1 | Round six moved the trust **data** into a closure but `has_pinned_runtime_binding` still resolved the **lookup** through a module-level name. `capabilities._runtime_repository_for = lambda t: "evil-org/fake-runtime"` made the attacker repository eligible **and the official vLLM repository ineligible**, under normal, `-O` and `-OO`. | The five-repository relationship is now **inlined in the method as code constants**, together with the evidence host. The method reads no rebindable trust name at all — asserted structurally against its `co_names`. `RUNTIME_REPOSITORIES` and `_runtime_repository_for` remain exported for readers and tests and are no longer consulted by routing; a drift guard asserts the inline constants and the exported view still agree in both directions. |

### The supported boundary, stated exactly

**In scope, and closed.** Ordinary reassignment of the repository trust data
or of its lookup: `RUNTIME_REPOSITORIES`, `_runtime_repository_for`, and the
evidence-host constant — individually or all at once. Also every ordinary
mutation of the public mapping: `__setitem__`, `__delitem__`, `update`,
`pop`, `popitem`, `clear`, `setdefault`. After any of these, the official
repository stays **eligible** and the attacker repository stays **blocked**.

**Out of scope, and not claimed.** Replacing the class method itself,
replacing the router, patching the generic validators (`parse_https_url`,
`is_commit_revision`), `__closure__` cell surgery, or swapping the module in
`sys.modules`. Those are arbitrary code replacement rather than reassignment
of trust data, and no amount of care inside this module prevents them.

The distinction is the whole point: a reader should be able to tell which
attacks this design stops and which it merely does not pretend to.

## 16. OMI-V2 — the structured-output request contract (2026-08-23)

OMI-V1 stopped at §8's third bullet: `OpenAICompatBackend` could not ask a
runtime for schema-constrained decoding. OMI-V2 adds exactly that, for
exactly four runtimes, through exactly one request field.

### 16.1 Why an adapter is needed at all

The four self-hosted runtimes in §5 all speak the OpenAI
`/v1/chat/completions` shape and all four accept a `response_format`. They do
not agree on where the schema goes. That disagreement is the whole reason
this is a package rather than a one-line change.

| Dialect | Schema path | `name` sent | Evidence strength |
|---|---|---|---|
| `llama-cpp` | `response_format.json_schema.schema` | no — no such key exists | **Source** — README conflicts, see §16.3 |
| `ollama` | `response_format.json_schema.schema` | no — no such field exists | **Source only** |
| `vllm` | `response_format.json_schema.{name,schema}` | yes — a fixed constant, never caller data | **Source** |
| `sglang` | `response_format.json_schema.{name,schema}` | yes — a fixed constant, never caller data | **Source** |

Corrected 2026-08-23. The `llama-cpp` row previously read
`response_format.schema` (**flat**) with evidence strength **Documented**.
That was wrong in a way that produced silently unconstrained output; §16.3
records how.

Every wire-shape claim above is bound to one exact file at one exact
commit, identified by its git blob id. A tree URL is not enough: it pins the
revision but not which file was read, and a claim that cannot be re-fetched
byte for byte is not evidence. Re-verify any row with
`git hash-object <file>` after fetching the raw URL.

| Dialect | Repository | Commit | File | Blob (SHA-1) | Bytes |
|---|---|---|---|---|---|
| `llama-cpp` | `ggml-org/llama.cpp` | `5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c` | `tools/server/server-common.cpp` | `585f65e83c655d3b8b7e398e8bf76552dc846f36` | 65,033 |
| `llama-cpp` (conflicting doc) | `ggml-org/llama.cpp` | `5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c` | `tools/server/README.md` | `93736c3edfa9bd094bf79f7d2de4659fbf8e74c9` | 105,082 |
| `ollama` | `ollama/ollama` | `b7871fc0d1d82fe109536efa3e0e8e411c766c75` | `openai/openai.go` | `2d38607dbd5d04e35935023ed19962c33685cee7` | 26,679 |
| `vllm` (nesting required) | `vllm-project/vllm` | `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac` | `vllm/entrypoints/openai/chat_completion/protocol.py` | `1cdfd2f698f90a2d76f58c81243b6cdf73e8c6ba` | 47,397 |
| `vllm` (`name` required) | `vllm-project/vllm` | `6e448d0ea9bf3d88d898b65449ca6dc2aec170ac` | `vllm/entrypoints/openai/engine/protocol.py` | `805c639d7d16a52f495d8942880682732280da0f` | 13,428 |
| `sglang` | `sgl-project/sglang` | `71de97b264b04dcd514cf904003028aefe9775c8` | `python/sglang/srt/entrypoints/openai/protocol.py` | `da62e3b0fbd632702a56de76050d2ea37c6e0690` | 70,651 |

Immutable raw URLs, one per row in order:

- `https://raw.githubusercontent.com/ggml-org/llama.cpp/5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c/tools/server/server-common.cpp`
- `https://raw.githubusercontent.com/ggml-org/llama.cpp/5a32f7b66ef6cfb3e60deea26e3454cc6ad3438c/tools/server/README.md`
- `https://raw.githubusercontent.com/ollama/ollama/b7871fc0d1d82fe109536efa3e0e8e411c766c75/openai/openai.go`
- `https://raw.githubusercontent.com/vllm-project/vllm/6e448d0ea9bf3d88d898b65449ca6dc2aec170ac/vllm/entrypoints/openai/chat_completion/protocol.py`
- `https://raw.githubusercontent.com/vllm-project/vllm/6e448d0ea9bf3d88d898b65449ca6dc2aec170ac/vllm/entrypoints/openai/engine/protocol.py`
- `https://raw.githubusercontent.com/sgl-project/sglang/71de97b264b04dcd514cf904003028aefe9775c8/python/sglang/srt/entrypoints/openai/protocol.py`

**Why vLLM needs two rows.** The `name` column of the first table asserts
that `json_schema.name` is required, and the `chat_completion/protocol.py`
blob does not contain that fact: it types the field as the imported
`AnyResponseFormat` and only validates that the `json_schema` nesting is
present at all. The model itself lives in `engine/protocol.py`, where
`JsonSchemaResponseFormat.name: str` carries no default and is therefore
mandatory. A round of this audit correctly found the claim bound to a blob
that did not carry it; rather than soften the claim, the file that does carry
it is now cited. SGLang needs no second row — its
`JsonSchemaResponseFormat.name: str` is in the blob already listed, at line
219.

Two things the file-level read established that a tree-level read had not:

- **vLLM's protocol module has moved.** At this commit it is at
  `vllm/entrypoints/openai/chat_completion/protocol.py`; the path this
  document implied, `vllm/entrypoints/openai/protocol.py`, returns 404 at
  this revision. Its validator raises when `type=json_schema` arrives without
  a `json_schema` field, so the nesting is required, not merely accepted.
- **SGLang is lenient where the others are not.** Its `set_json_schema`
  model-validator pops a flat `schema` and rewrites it into
  `json_schema.{name,schema}`, deriving the name from the schema's `title`.
  This package still sends the nested form: relying on a rewrite that only
  one of four runtimes performs would make the shape correct by accident.

SGLang additionally documents that only one constraint parameter
(`json_schema`, `regex`, or `ebnf`) may be sent per request. This package
sends only `json_schema`.

### 16.2 The Ollama shape is source-derived, and that is a real difference

At the pinned revision Ollama's documentation mentions `response_format`
exactly twice, and **neither mention specifies a shape**:

- `docs/api/openai-compatibility.mdx` (blob
  `4b34fa0960040bbfb407dc3c564dda6adad72a7a`, 22,463 bytes) line 201 — a bare
  supported-parameter checklist entry, ``- [x] `response_format` ``.
- `docs/capabilities/structured-outputs.mdx` (blob
  `c570a12f9dac6693e9f3e1b8d9242604cc034b5a`, 5,024 bytes) line 197 — a tip
  bullet, "Structured outputs work through the OpenAI-compatible API via
  `response_format`". Everything else in that file documents Ollama's
  *native* `format` parameter on `/api/chat`, which is a different API.

An earlier revision of this section said the documentation contained **only**
the checklist line. That was wrong in its exclusivity — there are two
mentions, in two files — and it is corrected here. The load-bearing half is
unchanged and was independently re-checked: neither mention gives a wire
shape, so the mapping used here comes from the source, not from
documentation:

```go
type ResponseFormat struct {
    Type       string      `json:"type"`
    JsonSchema *JsonSchema `json:"json_schema,omitempty"`
}
type JsonSchema struct {
    Schema json.RawMessage `json:"schema"`
}
```

A flat `schema` is silently ignored; there is no `name` field to populate.
This is weaker evidence than the other three rows and is labelled as such
everywhere it is relied upon. It is not a claim about any other revision.

### 16.3 Two divergences, and how each was decided

**llama.cpp: the README and the source conflict, and the source wins.** At
`5a32f7b6` the README shows the schema flat under `response_format` for the
`json_schema` type. The parser that runs does not read it there:

```cpp
if (response_type == "json_object") {
    if (response_format.contains("schema") || json_schema.empty()) {
        json_schema = json_value(response_format, "schema", json::object());
    }
} else if (response_type == "json_schema") {
    auto schema_wrapper = json_value(response_format, "json_schema", json::object());
    json_schema = json_value(schema_wrapper, "schema", json::object());
}
```

The flat key is read **only** for `type=json_object`. Sent with
`type=json_schema` it is ignored, `schema_wrapper` defaults to `{}`, the
constraint becomes an empty schema, and decoding proceeds unconstrained —
with no error, and nothing for a caller to notice. An earlier revision of
this package emitted the flat form on the README's authority and carried
exactly that defect.

Both paths are still not shotgunned. One shape is emitted, and it is now the
one the executable source reads. A test transcribes the branch above and
asserts the superseded shape decodes to `{}` while the emitted shape decodes
to the real schema, so the reason for the change survives the code that was
wrong. A test still asserts no dialect emits a schema at both paths.

**The transmitted `name` is a constant, not caller data.** `json_schema.name`
is sent to vLLM and SGLang, so whatever it holds leaves the process. It was
caller-supplied, guarded by a local check — exact `str`, 1..64 characters,
`[A-Za-z0-9_-]`. That alphabet admits `sk-OMIV2SECRET123456789`, so a caller
who named a schema after a credential had it put on the wire by the function
meant to prevent that.

Reusing the hardened primitive in `scripts/open_model/redaction.py` — which
does reject that string, because it cross-checks candidates against the
secret matcher — is unreachable from the backend package: `scripts.open_model`
imports it, so importing back is a genuine import cycle. Copying its rules
would be a second secret detector free to drift from the first.

So the field stopped being caller data. `STRUCTURED_WIRE_NAME` is a fixed
constant, `StructuredOutputRequest` has no `name`, and `name-not-safe` has
left the refusal vocabulary. llama.cpp and Ollama have no such key and are
still sent none.

### 16.4 What sending a request does not establish

Emitting `response_format` asks for constrained decoding. It does not prove
constrained decoding happened, and nothing in this package reports that it
did. Ollama makes the gap concrete:

```go
switch strings.ToLower(strings.TrimSpace(r.ResponseFormat.Type)) {
case "json_object": ...
case "json_schema":
    if r.ResponseFormat.JsonSchema != nil { format = ...Schema }
}
```

An unrecognised `type`, or a `json_schema` type with the nesting absent,
leaves the decoding format unset and yields unconstrained output **with no
error**. A caller treating a successful round trip as proof of conformance
would be wrong exactly there and would have no way to notice.

So the backend result field is named `response_format_sent`, which is what
it records. The response is then checked by
`scripts/open_model/structured_exchange.py` against the **existing**
`scripts/open_model/structured.py`. No second validator was written.

**That check does not establish schema conformance, and this package never
says it does.** It establishes that the payload parsed as a JSON object and
carried every required key — usability. Nothing here compares a response
against the schema that was sent, because the package carries no JSON Schema
implementation and will not hand-roll one. The gap is concrete: against a
schema demanding a boolean `ok` and forbidding extra properties, the payload
`{"ok": "wrong type", "extra": 123}` passes — wrong type, extra key, still
`ok=True`.

Earlier revisions of this document and of three docstrings described that
check as establishing or deciding conformance. That was false and is
corrected here. `StructuredExchange` now carries `schema_conformance`, closed
at runtime to the single token `"unverified"`, so the limit travels in the
result a caller reads rather than only in prose a caller might not. A real
conformance check would have to widen that vocabulary deliberately and
visibly.

### 16.5 The two validators run in opposite directions

`structured.py` parses an untrusted **response payload string** a model
emitted. The request-side checks in `structured_request.py` walk a
caller-supplied **JSON Schema document** about to be serialised outbound.
Different artifact, opposite direction, no shared decision — which is why one
is not a reimplementation of the other. The reuse is proved two ways in
`tests/test_omi_v2_exchange.py`: structurally, by reading the import; and
behaviourally, by monkeypatching the validator and observing the exchange's
verdict change, which a private copy could not do.

### 16.6 Closures, and what they cost

- **The dialect is explicit.** It is a constructor parameter and is never
  inferred from `base_url`, installed software, environment variables, or a
  probe. None of those identify a runtime: a URL is caller-chosen text, a
  local port says nothing about what is listening on it, and probing would
  mean contacting an endpoint in order to decide how to talk to it. A
  present-but-unrecognised dialect raises at **construction**, before any SDK
  client is built.
- **There is no escape hatch.** No `extra_body`, no `**kwargs` passthrough,
  no provider-specific field. This has a real cost worth naming: vLLM's
  `structured_outputs` route (which replaced the removed `guided_json` in
  v0.12.0) is reachable *only* through `extra_body` and is therefore not
  reachable from here at all. `response_format` is supported by all four
  runtimes and is the only path built.
- **Tools and structured output are refused together.** That combination was
  not verified at any of the four pinned revisions, and tool-choice work is
  out of scope. Refusing states the limit of the evidence; sending both and
  describing the result as supported would not. This is a claim about what
  was checked, not about what the runtimes can do.
- **Diagnostics carry nothing.** Every refusal is one token from a closed
  vocabulary. No schema fragment, key name, prompt, response, offset, length,
  type name, or exception text reaches a result.
- **No decision path resolves an undocumented global — proved at the
  bytecode.** Every function that takes a trust decision is built by a
  module-level factory that binds what it needs into **closure cells**: the
  four predicates, the wire-shape check, the snapshot validator, the
  response-format builder, the planner, the whole `OpenAICompatBackend` class
  (constructor, `complete_structured`, `_response_from_wire` and the wire
  translators), `_attr_or_key`, `_block_to_summary_dict`,
  `request_structured_json`, and all three result carriers. That includes the
  builtins the exact-type checks use, the stdlib module objects, and the
  exception classes.

  **Cells, not defaulted parameters.** An earlier revision bound these as
  defaulted `_name=` parameters. That closed name rebinding and opened
  something strictly worse, because a defaulted parameter is *directly
  addressable*: no rebinding was needed at all. `OpenAICompatBackend(...,
  dialect="sk-…", _dialect_ok=lambda v: True)` admitted a secret-shaped
  dialect; `complete_structured(..., _plan=…)` put an arbitrary object on the
  wire as the `response_format`; `request_structured_json(..., _validate=…)`
  reported success for invalid JSON. Cells cannot be addressed, the public
  signatures read exactly as documented, and passing any former capture
  keyword now raises `TypeError` — asserted for each one by name.

  **The proof is not a list.** `tests/test_omi_v2_jack_round4.py` discovers
  every authored callable in the three modules and reads the actual
  `LOAD_GLOBAL` instructions out of its bytecode. A hand-written
  forbidden-name set had previously stood in for this, and it found only what
  its author had thought of: it listed no stdlib module alias, so rebinding
  `structured_request.json` bypassed the UTF-8 refusal outright; it omitted
  `getattr`, `callable` and `_FINISH_REASON_MAP`; and it never examined
  `_response_from_wire` at all.

  **The finish reason is inlined, not looked up.** `_FINISH_REASON_MAP` was a
  plain module dict — rebindable *and* mutable in place — so
  `_FINISH_REASON_MAP["stop"] = <anything>` put arbitrary text into
  `AgentResponse.stop_reason`. Every branch now yields a literal from the
  closed `StopReason` vocabulary. The mapping remains an inspection mirror
  with a drift guard.

  `SUPPORTED_DIALECTS`, `DIALECT_WIRE_SHAPES`, `STRUCTURED_WIRE_NAME` and
  `_FINISH_REASON_MAP` are **inspection mirrors only**, each with a drift
  guard.

  **The complete allowlist is three constants**, and they are the only
  globals any authored decision path still resolves: `_SCHEMA_MAX_CHARS`,
  `_SCHEMA_MAX_DEPTH` and `_SCHEMA_MAX_NODES`. They bound *how much* is
  accepted and never *what type*, so rebinding one cannot admit a foreign
  type, a `str` subclass, or a secret — only widen or narrow a size limit,
  which a deployment may legitimately want to do. That openness is itself
  exercised by a control.

  **Out of scope, and not claimed**: closure-cell surgery, replacing a
  function or class object, patching an attribute *on* a captured stdlib
  module, and swapping a module in `sys.modules`. Those are arbitrary code
  replacement rather than name rebinding, as they have been since the OMI-V1
  seventh round. Dataclass-generated methods (`__eq__`, `__setattr__`, …) are
  compiled by `dataclasses` against the defining module's globals and are not
  authored here; the one that matters — the frozen-instance guard — is
  separately asserted to hold while `type` is rebound.

### 16.7 Interface decisions, recorded rather than taken silently

Five decisions were unavoidable. Each is the narrowest option that still
delivered the package; all five are also recorded in the module docstring of
`scripts/agent_backends/openai_compat_backend.py`.

| # | Decision | Why not the alternative |
|---|---|---|
| 1 | Structured output is a new method, `complete_structured()`. | Adding a `structured=` keyword to `AgentBackend.complete()` would change the ABC every backend implements, including two out of scope. The ABC is untouched. |
| 2 | It returns a new `StructuredCompletion`, not an `AgentResponse`. | A refusal must be distinguishable from model output, and `AgentResponse` has nowhere to put a refusal code that a caller could not mistake for content. |
| 3 | Response validation lives in `scripts/open_model/`, not in the backend. | The validator to be reused lives above the backend package, which imports downward only. Importing it from the backend would invert the layering the package docstring states. |
| 4 | `dialect` is a constructor parameter, and an invalid value raises. | It is configuration, not a per-call argument, and an explicitly wrong value is a configuration error worth failing at the point of configuration. |
| 5 | Tools plus structured output is refused. | See §16.6. |

Out of scope and untouched: tool-choice semantics, seed normalisation,
capability auto-detection, streaming, async, batching, TensorRT-LLM, and NIM.
No live backend is registered; the catalogue and registry remain inert. No
prompt, response, schema, or secret enters any persisted evaluation or
routing record — OMI-V2 persists nothing at all.

### 16.8 What was tested

724 hermetic tests across nine files, injected clients only — no network, no
key, no endpoint, no download.

| File | Tests | Covers |
|---|---|---|
| `tests/test_omi_v2_structured_request.py` | 94 | Exact wire shape per dialect; the closed dialect gate; schema, depth, size, and type negatives; refusal-vocabulary containment; non-disclosure; rebinding controls; layering. |
| `tests/test_omi_v2_backend.py` | 47 | Ordering — every refusal completes against a client that raises on *any* attribute access; legacy request equality with and without a dialect configured; exactly one added key; no `extra_body` or passthrough; no key in request or result. |
| `tests/test_omi_v2_exchange.py` | 54 | Validator reuse, structurally and behaviourally; the full response-failure boundary; request refusals kept distinct from response failures; no file written. |
| `tests/test_omi_v2_result_closure.py` | 111 | Structural closure of all three result carriers: exact booleans, closed vocabularies, coherent missing indices, and every incoherent state refused at construction. |
| `tests/test_omi_v2_jack_round1.py` | 48 | Jack's first independent HOLD round — one control per confirmed defect; see §16.9. |
| `tests/test_omi_v2_jack_round2.py` | 66 | Jack's second independent HOLD round — the closed mutation window, rebinding closure across every mirror in every consuming module, and full cross-field carrier coherence; see §16.10. |
| `tests/test_omi_v2_jack_round3.py` | 51 | Jack's third independent HOLD round — transitive closure of every decision path including builtins, the backend dialect authority, and the narrowed exchange value; see §16.11. |
| `tests/test_omi_v2_jack_round4.py` | 87 | Jack's fourth independent HOLD round — removal of caller-addressable authorities, stdlib-alias and capability closure, the finish-reason vocabulary, and a bytecode-level completeness proof; see §16.12. |
| `tests/test_omi_v2_jack_round5.py` | 166 | Jack's fifth independent HOLD round — restored module-level public identity, pickle round-trips, and re-assertion that the closure cells are unweakened; see §16.13. |

These counts are checked by the suite itself. `test_omi_v2_jack_round1.py`
asserts that every `tests/test_omi_v2_*.py` file on disk is named in this
table, that the stated total equals the sum of the rows, and that the table
names no file that does not exist. The table above went stale once — it
claimed 186 tests across three files while a fourth file of 111 tests existed
and none of the three figures was right — and prose alone did not catch it.

The ordering control is the load-bearing one. `ExplodingClient` raises on
every attribute access, so a refusal returned while the backend holds one
proves the refusal completed before the SDK was reached — a refused request
never becomes a billed, logged, or rate-limited call. A guard test asserts
`ExplodingClient` actually fires, so that proof cannot go vacuous.

All five files pass identically under normal, `-O` and `-OO`. No library
`assert` is relied upon (`-O` strips those) and no test reads `__doc__`
(`-OO` strips that); documentation checks read the source file instead.

**Same-author evidence.** Every test here was written by the same agent that
wrote the code under test. It demonstrates internal consistency, not
independent acceptance.

### 16.9 Jack's first independent HOLD round (2026-08-23)

An independent audit reproduced six gates against §16 as it stood at
`a6577f47`. All six are corrected. A verification sweep run afterwards
surfaced further defects; those that survived adversarial re-verification are
corrected here too, and are marked *sweep* below.

| # | Defect | Correction |
|---|---|---|
| 1 | **The llama.cpp mapping was wrong and silently unconstrained.** `server-common.cpp` reads the flat `schema` key **only** for `type=json_object`; for `type=json_schema` it reads `response_format.json_schema.schema`. The flat form this package emitted therefore produced an empty schema — no constraint, no error. | The `llama-cpp` dialect now emits the nested form, following the executable source rather than the README. Neither path is shotgunned. The README/source conflict is recorded in §16.3, and a control replays the pinned parser against both the superseded and the corrected shape. |
| 2 | **Response validation was described as establishing schema conformance.** It establishes JSON-object syntax plus required-key presence; `{"ok":"wrong type","extra":123}` passes against a schema demanding a boolean `ok` and no additional properties. | `StructuredExchange.schema_conformance` is a field closed to the single token `"unverified"`, so the limit is carried in the result rather than only in prose, and a future conformance check has to widen the vocabulary in the open. No JSON Schema validator was hand-rolled and no dependency was added. |
| 3 | **A secret-shaped schema name could reach the wire.** The caller supplied `json_schema.name`, guarded only by a local `[A-Za-z0-9_-]{1,64}` check — which admits `sk-OMIV2SECRET123456789`. | The field stopped being caller data: `StructuredOutputRequest` has no `name`, and the transmitted value is a fixed literal. Neither of the two rejected repairs was taken — the hardened primitive in `redaction.py` is unreachable without an import cycle, and copying its rules would have created a second drifting detector. |
| 4 | **The three result carriers accepted incoherent states.** | All three now enforce exact booleans, closed refusal/failure/dialect vocabularies, success requiring both the correct payload and the sent state, response failure requiring a sent request, and coherent missing indices. 111 controls in `test_omi_v2_result_closure.py`. |
| 5 | **The validated schema was not snapshotted.** A caller could mutate the document after validation and before transmission, so every guarantee described a document that was no longer the one being sent. | The planner re-parses the encoding the walk already produced, which is both a genuine deep snapshot and provably *the validated document* rather than a re-traversal. Mutation regressions cover top-level, nested, and list-element mutation. |
| 6 | **Wire-shape claims were not bound to immutable evidence.** | Every claim is bound to an exact repository, commit, file path, git blob id, and byte count, with the raw URL given so any row can be re-fetched and re-hashed. See the table in §16.1. |
| 7 | *sweep* — **A lone UTF-16 surrogate in a schema was accepted.** It is an exact `str` and passes every element check; `json.dumps` emits it verbatim and UTF-8 cannot encode it, so `complete_structured` raised an uncaught `UnicodeEncodeError` from inside the SDK — an exception escaping a method that promises a refusal. | The document is UTF-8 encoded during validation, while a refusal is still possible, and refused as `schema-not-utf8-encodable`. |
| 8 | *sweep* — **The tools gate was time-of-check/time-of-use bypassable.** `tools` was truth-tested once for the gate and again inside `_build_request`, so an object whose `__bool__` answered `False` then `True` passed the gate as tool-free and still had its tools attached beside the `response_format`. | `tools` is truth-tested exactly once and the result is reused, so the gate and the request cannot disagree. `complete()` is unaffected: it passes no `include_tools` and truth-tests exactly as before. |
| 9 | *sweep* — **The transmitted wire name resolved a rebindable module global.** `build_response_format` read `STRUCTURED_WIRE_NAME` from module scope, so rebinding one attribute put arbitrary text into `json_schema.name` — reopening by the back door the leak that gate 3 closed. | The literal is inlined at both call sites. `STRUCTURED_WIRE_NAME` remains exported as an inspection mirror with a drift guard, and a structural control asserts the builder's `co_names` contains no rebindable trust name at all — the property the previous round's section header claimed without asserting. |
| 10 | *sweep* — **`StructuredCompletion.response` and `StructuredExchange.value` were checked only for `None`.** A successful completion could carry any object, which made `request_structured_json` — documented as total — raise `AttributeError`; and `value` was the last field through which an arbitrary caller string could ride into a result. | Both are exact-type checked: an `AgentResponse` and an exact mapping respectively. |
| 11 | *sweep* — **Concurrent mutation escaped as `RuntimeError`.** A schema mutated by another thread during the walk raised `dictionary changed size during iteration` out of a function that promises a refusal for every input. | Caught and reported as `schema-changed-during-validation`. A control asserts no exception escapes across 3,000 validations against a live mutator. |
| 12 | *sweep* — **Several controls were vacuous.** The depth-boundary test nested 8 levels against a limit of 32; the ordering test could not distinguish the two orderings it existed to separate, because `ValueError` arrives either way once `openai` is importable; the no-file-write guard covered only `builtins.open`; the drift guard could not detect a corrupted mirror string for `vllm` or `sglang`. | Each is replaced by a control that fails without its feature: both sides of the real depth edge plus a control proving the edge moves with the constant; SDK construction made to raise a *distinct* exception so seeing `ValueError` proves the gate ran first; filesystem guards over `pathlib` and `os` as well, each with its own would-actually-fire guard; and a drift guard that checks every dialect's mirror individually. |
| 13 | *sweep* — **The `STRUCTURED_WIRE_NAME` docstring claimed both runtimes document an alphabet and length for the field.** Neither pinned source constrains it; both declare a bare `str`. | Claim withdrawn and replaced with the pinned evidence that the field is *required* — which is the fact that actually justifies sending a constant. |
| 14 | *sweep* — **The documented test inventory was stale in every cell** and omitted an entire test file. | §16.8 corrected, and the suite now asserts its own inventory against the files on disk. |

One residual is stated rather than closed, because it cannot be closed
without defeating the parameter's purpose: **the schema document itself is
caller data and is transmitted verbatim**, with no secret check. A caller who
writes a credential into a schema key or description puts it on the wire.
What is closed is narrower and exact — no field whose value *this package
chooses* can carry caller text off the machine.

### 16.10 Jack's second independent HOLD round (2026-08-23)

A second independent audit cleared the original six gates and the eight-blob
evidence matrix, and reproduced three remaining gates. All three are closed.

| # | Defect | Correction |
|---|---|---|
| 1 | **A mutation window sat between validation and snapshot.** Validation walked the caller's containers; the snapshot was then produced by handing the **caller's own object** to `json.dumps` and re-parsing the text. That is a second read of caller-owned data, so anything changed in between was serialised having never been checked — an over-depth structure, an over-node structure, or a refused type could all be substituted into an already-visited slot and accepted. | Validation and copying are now **one traversal**. Each value is checked and written into the detached structure the moment it is first seen, so the accepted snapshot contains exactly and only what was inspected. Everything afterwards — including the encoding — reads the snapshot; the caller's object is never touched again. Scalars are shared rather than copied because `str`, `int`, `float`, `bool` and `None` are immutable. |
| 2 | **Refusal, failure and dialect decisions ran through rebindable names.** `REFUSAL_TOKENS`, `EXCHANGE_REFUSALS`, `RESPONSE_FAILURES` and the imported `is_supported_dialect` aliases were read from module scope inside every carrier's `__post_init__`, so rebinding one attribute admitted arbitrary — including secret-shaped — refusal, failure or dialect text into a result. | Every decision now runs against an **object captured when the class was defined**, bound as a defaulted parameter of `__post_init__`. A dataclass calls it with no arguments, so nothing is ever looked up again. All three carriers now resolve **no trust name at all** — asserted structurally against `co_names`, including the builtins used in the exact-type checks. |
| 3 | **Cross-field coherence was incomplete.** A carrier could report success without naming a dialect, name a dialect on a refusal taken before the dialect gate, omit one on a refusal taken after it, or carry an arbitrary dictionary on a successful plan. The exchange also *described* its value as read-only while accepting a plain `dict`. | Full coherence is enforced: success requires a verified dialect; pre-dialect refusals (the three dialect refusals plus `backend-not-structured-capable`) carry none; post-dialect refusals and every response failure require one; and a successful plan must carry one of the **two exact dialect wire shapes**, not merely a dictionary. The value claim is made true rather than softened — whatever is supplied is re-wrapped over a fresh top-level copy, so a caller holding the original cannot change what the result reports. |


> **Superseded by §16.12 on the mechanism, 2026-08-23.** Row 2 above records
> what this round actually did, and is kept as written. It is no longer how
> the code works: binding an authority as a **defaulted parameter of**
> `__post_init__` closed name rebinding but left that authority *directly
> addressable by any caller willing to pass the keyword*, which was a wider
> hole than the one it closed. Every authority now lives in a **closure
> cell** and the carriers take `__post_init__(self)` and nothing else.

**How gate 1 is proved deterministically.** The window is reproduced with no
threads and no timing: `json.dumps` itself performs the mutation, which is
exactly the instant the old design re-read caller data. If the serialiser
still received the caller's object, the injected payload would land in the
snapshot — or, for a refused type, would fail the plan. Three controls inject
an over-depth structure, an over-node structure and a wrong type, and each
asserts three things: that the injection really happened, that the serialiser
was **not** handed the caller's document, and that the snapshot still contains
only what was validated. A companion control walks both graphs and asserts
they share no container object, with a guard proving the share-detector
itself fires.

**How gate 2 is proved.** A fixture rebinds **every** exported or global
mirror in **every** consuming module — sixteen in total, across
`structured_request`, `openai_compat_backend` and `structured_exchange`,
including the wire name, the dialect tuple, the shape mirror, `AgentResponse`
and `MappingProxyType` — to secret-shaped values, and then asserts that no
secret-shaped refusal, failure, dialect, wire shape or response can be
constructed, that a built request still carries the correct wire name, and
that no fifth dialect opens. A guard asserts the valid cases remain valid, so
a check that rejected everything could not pass by accident.

**Scope note.** The captures close rebinding of a *name*. They do not claim to
survive arbitrary code replacement — overwriting `__defaults__`, replacing the
method object, or swapping the module in `sys.modules` remain out of scope, as
they have been since the OMI-V1 seventh round. That distinction is the whole
point of stating it: a reader should be able to tell which attacks this design
stops and which it does not pretend to.

**The read-only boundary, stated exactly.** `StructuredExchange.value` is a
genuinely read-only view over a fresh **top-level** copy. The proxy is
shallow, exactly as `StructuredOutcome.value` is: nested containers reached
through it remain ordinary mutable objects, and a control asserts that
directly rather than leaving it implied. It prevents top-level mutation of a
shared result; it does not claim deep immutability.

> **Amended by §16.11.** This round accepted *either* an exact `dict` or an
> exact `MappingProxyType` on the public carrier path. That was wrong: a
> proxy is an exact type that can wrap an **arbitrary foreign mapping**, and
> copying one runs that mapping's hooks. The public path now accepts an exact
> `dict` only.

### 16.11 Jack's third independent HOLD round (2026-08-23)

A third independent audit cleared the mutation-window correction, the direct
named-mirror carrier controls, cross-field coherence, wire-shape enforcement,
top-level read-only behaviour, the PR-body receipt, ancestry, paths,
exact-head CI, and the eight-blob matrix. It reproduced three remaining gates.

| # | Defect | Correction |
|---|---|---|
| 1 | **The backend's dialect authority was rebindable.** `OpenAICompatBackend.__init__` resolved the imported `is_supported_dialect` alias, and so did the refusal path in `complete_structured`. Rebinding that one attribute admitted an **exact secret-shaped string as backend dialect configuration**. | Both now take the decision against a captured object. The constructor additionally captures `dict`; `complete_structured` captures the planner, the completion carrier and `bool`. |
| 2 | **The closure was not transitive.** Round 2 asserted that the three `__post_init__` bodies resolved no trust name. True, and insufficient: the helpers they *captured* — `is_supported_dialect`, `is_supported_wire_shape`, `is_pre_dialect_refusal` — still looked up `type`, `str`, `dict` and `len` as module globals. `structured_request.type = <replacement>` changed their decisions without replacing the function, its defaults, its code, or `sys.modules`, and a **deceptive `str` subclass** carrying hidden attributes and lying in `__repr__` was admitted into `StructuredCompletion.dialect`, `StructuredExchange.dialect`, and a plan's transmitted `json_schema.name`. | Every trust-path function is now produced by a factory that binds its builtins and dependencies in **closure cells**: the four predicates, the snapshot validator, the builder, the planner, and — via captured defaults — the backend constructor, `complete_structured`, `_response_from_wire`, `request_structured_json` and all three carriers. A parametrised control asserts the closure at **every** layer. |
| 3 | **A proxy could smuggle foreign mapping hooks onto the public carrier path.** `StructuredExchange` accepted an exact `MappingProxyType`, then called `dict()` on it. A proxy is an exact type that can wrap an **arbitrary foreign mapping**, so that copy executed the wrapped mapping's `keys`/`__getitem__`/`__iter__` — and a hostile mapping raised caller-supplied secret-shaped `RuntimeError` text out of a public constructor, under normal, `-O` and `-OO`. | The public path accepts an **exact `dict` only**, whose copy cannot call out. There is no hook-free way to inspect what a proxy wraps, so the type is narrowed rather than inspected. The canonical internal path in `request_structured_json` adapts the validator's proxy before it reaches the carrier; that conversion is safe *because* `structured.py` guarantees its `value` is always a proxy over the exact `dict` `json.loads` produced, and the validator is now a captured default so that guarantee cannot be swapped out by rebinding a name. |


> **Superseded by §16.12 on the mechanism, 2026-08-23.** Rows 2 and 3 above
> describe authorities bound "via captured defaults". Kept as the record of
> this round; no longer current. Defaulted parameters were themselves the
> next defect — see §16.12 — and every authority is now bound in a closure
> cell, with no defaulted authority parameter anywhere.

**Why the round-2 `co_names` assertion was not proof.** It examined one
frame. A decision is only as closed as the whole call graph beneath it, and
the helpers were where the lookups lived. The lesson is recorded here rather
than quietly fixed: *immediate-layer cleanliness is not transitive closure*,
and a control that checks one layer should say so.

**How the gates are proved.** A single fixture installs the hostile
environment — twenty-six rebindings across all three modules, including
`type`, `str`, `dict` and `len` **added** to namespaces where they do not
normally exist, every data and predicate mirror, the builder, the snapshot
validator, the planner, the validator, and both carrier types. A guard test
asserts the fixture is actually installed, so nothing below can pass by
accident. Under it: exact secret strings and deceptive subclasses are refused
as backend dialect, plan wire name, completion dialect and exchange dialect;
the four real dialects still construct; a real request still succeeds and
still carries the correct wire name; and the planner still builds the real
shape. Separately, every decision path is asserted to resolve no forbidden
name, with a companion asserting each one actually captured something (so a
function that did nothing could not pass) and a third proving the assertion
fires on a deliberately leaky function.

For gate 3, a `HostileMapping` records whether any hook ran: the control
asserts the proxy is refused **and** that `touched` is still False, with a
guard proving the same mapping does raise when copied normally.

**Same-author evidence.** Everything above was written by the agent that
wrote the code under test. It demonstrates internal consistency, not
independent acceptance.

### 16.12 Jack's fourth independent HOLD round (2026-08-23)

A fourth independent audit cleared the backend-alias, captured-helper,
hostile-proxy, mutation-window, carrier-coherence, wire-shape, evidence,
ancestry, path, PR-body and exact-head CI gates, and reproduced five more.

| # | Defect | Correction |
|---|---|---|
| 1 | **The captures were caller-addressable.** Bound as defaulted `_name=` parameters on `OpenAICompatBackend.__init__`, `complete_structured` and `request_structured_json`, they required no rebinding to defeat — a keyword argument sufficed. Jack used them to admit an exact secret string as backend dialect, send an arbitrary `response_format` shape, and report success for invalid JSON. | Every authority moved into **closure cells** built by module-level factories. The documented public signatures are unchanged and passing any former capture keyword raises `TypeError`, asserted for each of the twelve by name. |
| 2 | **Stdlib module aliases were open.** `_validated_snapshot` resolved `json`, `math` and its exception classes globally, so `structured_request.json = <replacement>` bypassed the UTF-8 refusal and admitted an unpaired surrogate. | The stdlib **module objects** and every exception class are bound in cells. Capturing the module rather than `json.dumps` is deliberate: rebinding the module-level *name* is closed, while patching an attribute *on* the captured module stays the documented arbitrary-code-replacement boundary — the same boundary the gate-1 mutation-window controls rely on. |
| 3 | **The capability decision was open.** `request_structured_json` resolved `getattr` and `callable` globally, so rebinding `structured_exchange.getattr` made a plain `object()` present a callable `complete_structured`. | Both are captured. A backend with no real method stays `backend-not-structured-capable` under the hostile fixture, for five different non-backends. |
| 4 | **Response translation was never audited.** `_response_from_wire` was outside the asserted inventory entirely and resolved `_FINISH_REASON_MAP`, `_attr_or_key`, the block classes, the parsing authorities and the exact-type builtins. `_FINISH_REASON_MAP` is a plain dict, so it was rebindable **and mutable in place**, and either put a secret-shaped string into `AgentResponse.stop_reason`. | The finish-reason decision is **inlined**: every branch yields a literal from the closed `StopReason` vocabulary. The whole translation path — including `_attr_or_key` and `_block_to_summary_dict` — is closed and is now in the asserted inventory. Controls cover ten wire values against both rebinding and in-place mutation. |
| 5 | **The proof was a hand-written list.** A curated forbidden-name set is only ever as complete as its author's imagination, and this one had missed every defect above. | The proof now **discovers** every authored callable in the three modules and reads the real `LOAD_GLOBAL` instructions from its bytecode. The allowlist is three documented constants. Public signatures are separately asserted to expose no underscore-prefixed parameter and no callable, type or vocabulary default. |

**The lesson, stated plainly.** Round three closed name rebinding by moving
authorities into defaulted parameters, and the assertion that "proved" it
could not see the wider hole it had just opened, because the assertion was a
list written by the same author who chose the mechanism. A capture a caller
can pass is not a capture. A proof that enumerates what to look for finds only
what was already suspected. Both are now structural: cells cannot be
addressed, and the closure check reads bytecode rather than names.

**One defect this file's own controls found.** The first draft classified a
binding factory by name prefix alone, which silently exempted
`OpenAICompatBackend._build_request` — a method, not a factory — from the
closure assertion. A prefix is not a category; factories are now identified as
module-level builders and additionally asserted to be unexported.

**Same-author evidence.** Everything above was written by the agent that wrote
the code under test. It demonstrates internal consistency, not independent
acceptance.

### 16.13 Jack's fifth independent HOLD round (2026-08-23)

A fifth independent audit cleared the four closure corrections under normal,
`-O` and `-OO`, and reproduced one compatibility regression that those
corrections had introduced.

| # | Defect | Correction |
|---|---|---|
| 1 | **Factory-built objects lost their module-level identity.** Moving every authority into closure cells meant creating the exported classes and functions *inside* factories, and an object created inside a function takes its `__qualname__` from that function: `_build_backend_class.<locals>.OpenAICompatBackend`. `pickle` resolves an object by `__module__` plus `__qualname__`, so all ten exported classes and functions raised `PicklingError`, and the frozen dataclasses leaked the factory name into every `repr`. | A single `_restore_identity` helper sets `__module__`, `__name__` and `__qualname__` on each factory-built object and on its own methods, immediately at the point of binding. Nothing else is touched. |

**This was a genuine regression, not a theoretical one.** `OpenAICompatBackend`
pickles at the base commit `3241c40b` and at the previous head `88e8cb5a`, and
stopped pickling at `c42c8806`. That is the definition of a compatibility
break, and it was introduced by the round-four commit that wrapped the class.

**What the fix does not do.** It sets three identity attributes. It does not
read, replace, expose or widen any captured authority; it reintroduces no
defaulted parameter; and the object bound at module level is the same object
the factory returned. Rather than assert that by inspection alone, this round
re-runs the protections directly: the closure completeness check, the
signature-purity check, a cell-contents check that every captured authority in
`request_structured_json` is still the object it was, the former-capture
keywords still raising `TypeError`, a secret-shaped dialect still refused, and
a mirror rebinding still changing nothing.

**The controls are discovered, not listed.** Every class and function bound at
module level in the three modules is enumerated and asserted to have exact
`__module__` / `__name__` / module-level `__qualname__`, to resolve back to
itself by name, to expose no `<locals>` on any of its own methods, and to
pickle to the *identical* object. A guard builds a deliberately factory-local
function and asserts it both carries `<locals>` and raises `PicklingError`, so
the assertions cannot pass against a broken check. The **specifically
supported instance states named by the tests** round-trip through pickle and
compare equal, and no carrier `repr` contains `<locals>`. That is narrower
than it first read: a *successful* exchange cannot be pickled at all — see
§16.14.

**A note on the historical sections.** §16.10 and §16.11 record authorities
bound as *defaulted parameters of* `__post_init__`. Those statements are
accurate records of what those rounds did and are kept as written, each now
carrying an explicit superseded notice: defaulted parameters were themselves
the next defect (§16.12), and every authority now lives in a closure cell with
`__post_init__(self)` taking nothing else. The three carrier docstrings that
still described the defaulted-parameter mechanism in the present tense have
been corrected to describe the cells.

**Same-author evidence.** Everything above was written by the agent that wrote
the code under test. It demonstrates internal consistency, not independent
acceptance.

### 16.14 Jack's sixth independent HOLD round (2026-08-23)

A sixth independent audit cleared the identity restoration, public-object
pickle identity, clean representations and the previous closure protections
under normal, `-O` and `-OO`. It reproduced two evidence defects — both in the
controls rather than in the package, and both of the same kind: a claim
broader than what was actually tested.

| # | Defect | Correction |
|---|---|---|
| 1 | **The carrier-instance pickle claim was overbroad.** §16.13 and the round-five controls said "carrier instances round-trip", having tested only *refused* states. A canonical **successful** `request_structured_json` result carries its value as a `MappingProxyType` and raises `TypeError: cannot pickle 'mappingproxy' object`. The claim was true of what was tested and false of what it said. | The claim is narrowed to *the specifically supported instance states named by the tests*, which now include a successful plan and both completion dialect states. A negative control builds a canonical success **through the real path** and pins the `TypeError`, and the limitation is stated in the `StructuredExchange` docstring, here, and in the pull-request body. |
| 2 | **The round-five closure discovery repeated the round-four classification defect.** It exempted binding factories by name prefix alone, which again silently excluded `OpenAICompatBackend._build_request` — a method, not a factory — from the audited surface. Round four had already fixed exactly this. | Round five now requires a candidate to be **module-level** before the prefix exempts it, matching round four. A non-vacuity guard asserts `_build_request` is present in the discovered surface and that the surface holds at least 22 paths, so a third occurrence cannot ship quietly. Round four's controls are untouched. |

**On the pickle limitation, and why it was not engineered away.** The two
available fixes were to weaken the read-only proxy or to add custom
`__reduce__` behaviour. Both were declined in this bounded correction. The
proxy is a live protection — it is what stops a caller mutating a shared
result through the reference they passed in — and trading it for a
serialisation convenience nobody has asked for would be a poor exchange made
quietly. A caller who needs to serialise a successful result can copy the
value out: `dict(result.value)` is an ordinary picklable dict.

**What remains true, stated exactly.** The exported classes and functions all
pickle to their *identical* module attributes; that is the compatibility
regression §16.13 fixed and it is unaffected. The refused and
response-failure carrier states pickle and compare equal. The successful
exchange state does not pickle, by design, and is asserted not to.

**The lesson, again.** Both defects are the same failure: an assertion that
covered a subset while its wording covered the whole. A control is only
evidence for the cases it actually runs, and a name is not a category — the
second of those has now been recorded three times, which is why it is pinned
by a guard rather than by care.

**Same-author evidence.** Everything above was written by the agent that wrote
the code under test. It demonstrates internal consistency, not independent
acceptance.

## 17. OMI-V3A — the observation envelope (2026-08-24)

**Status: implemented, inert, hermetic.** The full contract, every limitation,
and the complete control inventory live in
[`OMI_V3_OBSERVATION_INCEPTION.md`](OMI_V3_OBSERVATION_INCEPTION.md). This
section exists so a reader of §§1–16 knows the layer is there and knows where
its boundary is drawn; it deliberately does not restate the contract.

**What was added.** Two modules —
[`scripts/open_model/observation.py`](../scripts/open_model/observation.py) and
[`scripts/open_model/observation_receipt.py`](../scripts/open_model/observation_receipt.py)
— carrying the task envelope that
[`LOCAL_MODEL_DEPLOYMENT_INCEPTION.md`](LOCAL_MODEL_DEPLOYMENT_INCEPTION.md)
§ 7 specified as a design requirement: immutable task identity, input hashes,
bounded context and result, a monotonic deadline, provenance, plus a declared
loopback endpoint and an explicit resource reservation. Nothing in §§1–16
changed.

**What it reuses rather than reinventing.** OMI-V3A adds **no** second schema
validator, dialect map, refusal vocabulary, or network guard. The dialect and
the schema are decided end to end by §16's `plan_structured_request`, whose
refusal token travels through unchanged; the response is validated by §16's
`request_structured_json`; the two refusal vocabularies and the response-failure
vocabulary are imported; `hermetic_guard` is OMI-V1's. `schema_conformance`
stays closed to `"unverified"` — §16.4 is unaffected, and OMI-V3A adds nothing
that could establish conformance.

**The boundary, stated exactly.** OMI-V3A contacts no endpoint, resolves no
name, opens no socket, downloads nothing, starts no runtime, registers no
backend, and inspects no process, service, port, credential, or hardware or
workload state. §8's "no live backend is registered anywhere in this
repository" remains true. §7's four deliberate steps for adding a real backend
are unchanged and uncleared. The read-only inventory probe of
`LOCAL_MODEL_DEPLOYMENT_INCEPTION.md` § 5 remains gated behind its own
authorization and was not run.

Two things OMI-V3A validates are **declarations**, not facts about the world,
and the receipt records them as such: the loopback endpoint is validated as
text with no name resolved and no socket opened, and the resource reservation
is gated on an injected checker or operator **attestation** rather than on any
measurement. Both limits, and eight more, are enumerated in § 9 of the
inception document.

**Corrected five times (2026-08-24 / 25).**
Twenty-four demonstrated cases all reproduced, in five findings — three of them
one root cause: an exact outer type mistaken for an unaltered object, since
`object.__setattr__` replaces any field on a frozen dataclass and the digest
computed at construction does not follow. Carriers are now revalidated and
their digests recomputed before planning, at construction, and again before
execution; direct envelope construction is held to the planner's exact
standard through OMI-V2's own dialect and schema authorities; a clock that
raises is refused with a fixed token and every clock figure is bounded;
execution-time revalidation proves field types before anything is iterated,
compared or truth-tested; and the receipt enforces every bound it documents.
The second round went further: it found the two gates *still* disagreeing about
strict UTF-8 evidence, found accepted envelopes retaining the caller's own
carriers, and - most importantly - found an **unkeyed digest being treated as
authority for validity**, so that an envelope resealed after a tamper executed
normally. Every semantic constraint is now revalidated before execution, the
returned OMI-V2 carrier is revalidated field by field before any of it is read,
and the receipt re-checks itself at serialisation. Sections 11 and 13 of the
inception document list each finding and its correction. The third round closed
two windows that round two's own corrections had introduced - validation
followed by a second read of the thing just validated, in the envelope and in
the receipt - required OMI-V2's full exchange state machine to be enforced
before a result is consumed, and rejected as a false choice the residual round
two had offered as a trade: the result is now measured on the canonical adapter
path, where a mapping proxy's provenance is knowable, so the executor never
walks a mapping and the byte bound is kept. Sections 15, 14 and 16 record the
findings and two reporting errors in this work's own earlier evidence. A
fourth adversarial review then found that the executor and the canonical
adapter both went on reading the envelope *after* validation - with
caller-supplied callables running in between, which is how a hostile clock
could shrink a bound mid-flight and a hostile exchange could make receipt
construction raise. Section 17 records it. A fifth round then found the same
pattern one layer upstream - `request_structured_json` read the fields of a
returned `StructuredCompletion` without re-checking them, so a backend that
mutated one could run its own hooks inside OMI-V2 - and corrected it there;
section 18 records that, together with a transmission claim that was withdrawn
because no receipt can attest what a caller-supplied backend actually sends.

**Same-author evidence.** As with §16, everything above was written by the
agent that wrote the code under test. It demonstrates internal consistency,
not independent acceptance.
