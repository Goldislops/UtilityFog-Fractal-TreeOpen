"""OMI-V1 - dated, inert candidate descriptors. **Nothing here is approved.**

Read this paragraph before using anything in this module. Every entry below
is *metadata a human read off a vendor's own page on 2026-08-22*. Presence in
this catalogue does **not** mean a model has been downloaded, installed,
benchmarked, evaluated, licensed for any particular use, trusted, or
approved. No entry has been run. This repository has executed none of them.

That is enforced, not merely asserted, in four independent ways:

  1. Every entry declares ``availability="unknown"`` and ``locality="unknown"``.
     Both are blocking conditions in ``scripts.open_model.routing``.
  2. Every entry leaves ``repository_revision`` empty, which is blocking on
     its own - see "What is deliberately unpinned" below.
  3. No entry carries a factory. ``scripts.open_model.registry`` requires an
     operator-written factory callable to make anything constructible, and a
     descriptor alone provides none. A ``local`` claim additionally requires
     an explicit operator attestation at the registration site.
  4. No entry carries an endpoint, command, credential, or download location.

``tests/test_open_model_routing.py`` asserts unroutability over the whole
catalogue under every requirement combination, so an entry cannot become
routable through an editing slip.

**One descriptor, one artifact (corrected after audit).** Entries name an
exact variant, never a family. ``google/gemma-4-12B-it`` (BF16 safetensors)
and ``google/gemma-4-12B-it-qat-q4_0-gguf`` (a quantised GGUF build) are
different files, with different digests, different runtime support, and
different failure modes; collapsing them under one "Gemma 4 12B" row makes
any claim about either unfalsifiable. ``quantisation`` is therefore singular,
and a descriptor that makes an artifact-format claim must also carry an
``artifact_digest`` or it is refused.

**What is deliberately unpinned, and why that is the honest state.**
``repository_revision`` and ``artifact_digest`` are empty on every entry
below. The 2026-08-22 survey read model cards and licence texts; it did
**not** retrieve commit revisions or file digests, and inventing
plausible-looking hex would be far worse than leaving them blank - it would
manufacture exactly the false confidence this field exists to prevent.
Populating them is an operator step, performed against the actual artifact
being adopted, at the time of adoption. Until then these entries are blocked
on ``repository-revision-unpinned``, which is correct.

**Licence classification is conservative.** Where a licence's OSI status
could not be confirmed from the licence text itself, the entry is classified
into the *more* restrictive class. NVIDIA's OpenMDW-1.1 is the clearest case:
its terms are close to permissive, but the licence page makes no OSI claim,
so it is recorded as ``open-weight-restricted`` with the nuance in the note.

**Fine-tunes inherit.** Where a model is a fine-tune, the class recorded is
the one that governs a downstream user - the *base* licence - not whatever
the fine-tuner wrote on their own card. ``Hermes-4-70B`` below is the worked
example.

**``licence_revision`` convention**: the licence's own version or effective
identifier where it has one (``"2.0"`` for Apache-2.0, ``"1.1"`` for
OpenMDW, ``"2025-12-15"`` for a dated effective edition); otherwise the ISO
date the text was retrieved, for licences that carry no version of their own
(MIT).

Sources for every field are in ``docs/OPEN_MODEL_INTEGRATION.md``, which
carries the full dated matrix including the unresolved risks that did not fit
in a descriptor.
"""

from __future__ import annotations

from typing import Final, Optional

from scripts.open_model.capabilities import ModelCapabilities


_OBSERVED: Final[str] = "2026-08-22"

_APACHE_URL: Final[str] = "https://www.apache.org/licenses/LICENSE-2.0"
_APACHE_REV: Final[str] = "2.0"


CATALOGUE: Final[tuple[ModelCapabilities, ...]] = (
    ModelCapabilities(
        model_id="ibm-granite/granite-4.1-8b",
        variant_id="bf16-safetensors",
        resource_class="light",
        tool_calling="supported",
        max_context_tokens=131072,
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=_APACHE_URL,
        licence_revision=_APACHE_REV,
        licence_notes=(
            "Apache-2.0 end to end: no revenue threshold, no acceptable-use "
            "policy attached to the weights, not gated. Card states a 131072 "
            "sequence length while IBM's blog claims up to 512K; the card "
            "figure is used."
        ),
        provenance_url="https://huggingface.co/ibm-granite/granite-4.1-8b",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="ibm-granite/granite-4.1-8b-GGUF",
        variant_id="gguf-q4-k-m",
        quantisation="gguf-q4_k_m",
        resource_class="light",
        tool_calling="supported",
        max_context_tokens=131072,
        runtimes=("llama-cpp", "ollama"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=_APACHE_URL,
        licence_revision=_APACHE_REV,
        licence_notes=(
            "First-party GGUF published by IBM itself, which is unusual - "
            "most vendors leave GGUF to third parties. Separate repository "
            "from the BF16 weights, hence a separate descriptor."
        ),
        provenance_url="https://huggingface.co/ibm-granite/granite-4.1-8b-GGUF",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="google/gemma-4-12B-it",
        variant_id="bf16-safetensors",
        resource_class="medium",
        tool_calling="supported",
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=_APACHE_URL,
        licence_revision=_APACHE_REV,
        licence_notes=(
            "Gemma 4 moved to Apache-2.0 and is no longer click-through "
            "gated, unlike earlier Gemma generations. The Gemma Prohibited "
            "Use Policy is still referenced from the model card; whether it "
            "binds Apache-2.0 weights is unresolved - a counsel question, "
            "not a routing input. Context documented as 256K, not as an "
            "exact token count, so it is left unknown."
        ),
        provenance_url="https://huggingface.co/google/gemma-4-12B-it",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="google/gemma-4-12B-it-qat-q4_0-gguf",
        variant_id="qat-q4-0-gguf",
        quantisation="gguf-q4_0",
        resource_class="light",
        tool_calling="supported",
        runtimes=("llama-cpp", "ollama"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=_APACHE_URL,
        licence_revision=_APACHE_REV,
        licence_notes=(
            "Quantisation-aware-trained q4_0 GGUF published by Google "
            "itself. A distinct artifact from the BF16 repository: different "
            "file, different runtimes, different numerics."
        ),
        provenance_url="https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16",
        variant_id="bf16",
        resource_class="medium",
        tool_calling="supported",
        runtimes=("vllm", "sglang", "tensorrt-llm"),
        licence_class="open-weight-restricted",
        licence_name="OpenMDW-1.1",
        licence_source_url="https://openmdw.ai/license/1-1/",
        licence_revision="1.1",
        licence_notes=(
            "OpenMDW-1.1 is close to permissive - use without restriction, "
            "no output restrictions, notice retention plus a patent-"
            "litigation termination clause - but the licence page makes no "
            "OSI claim, so it is classified conservatively. Tool calls use "
            "Qwen3-Coder-style syntax via the runtime parser, not OpenAI-"
            "native. NVIDIA points at a GGUF build hosted outside its own "
            "org: a separate artifact with a different trust boundary, so "
            "it is not folded into this entry."
        ),
        provenance_url=(
            "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF",
        variant_id="gguf",
        quantisation="gguf",
        resource_class="light",
        licence_class="open-weight-restricted",
        licence_name="NVIDIA Nemotron Open Model License",
        licence_source_url=(
            "https://www.nvidia.com/en-us/agreements/enterprise-software/"
            "nvidia-nemotron-open-model-license/"
        ),
        licence_revision="2025-12-15",
        licence_notes=(
            "Commercial use permitted, redistribution and derivatives "
            "allowed, requires notice retention and a NOTICE line; "
            "litigation-triggered termination; no acceptable-use clause "
            "found in the licence text. Not OSI-approved. Deliberately left "
            "underspecified: no runtime, context, or tool-calling claim was "
            "verified for this specific repository, so none is recorded."
        ),
        provenance_url="https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="mistralai/Mistral-Small-4-119B-2603",
        variant_id="bf16-safetensors",
        resource_class="heavy",
        tool_calling="supported",
        runtimes=("vllm", "sglang", "llama-cpp"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=_APACHE_URL,
        licence_revision=_APACHE_REV,
        licence_notes=(
            "Apache-2.0, not gated. Note the family is split: Devstral 2 and "
            "Mistral Medium 3.5 are Modified MIT with a $20M/month revenue "
            "trigger, and Voxtral TTS is CC BY-NC. 'Mistral means Apache' is "
            "false at the family level. GGUF builds are community, not "
            "first-party. Context documented as 256K, not an exact count."
        ),
        provenance_url="https://huggingface.co/mistralai/Mistral-Small-4-119B-2603",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="NousResearch/Hermes-4.3-36B",
        variant_id="bf16-safetensors",
        resource_class="medium",
        tool_calling="supported",
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0 (inherited from ByteDance Seed-OSS-36B base)",
        licence_source_url=_APACHE_URL,
        licence_revision=_APACHE_REV,
        licence_notes=(
            "Fine-tune of an Apache-2.0 base, so the inherited class is "
            "clean. Trained to emit valid JSON for a given schema and to "
            "repair malformed objects, but that is a training claim, not a "
            "decoding guarantee - constrained decoding still comes from the "
            "runtime."
        ),
        provenance_url="https://huggingface.co/NousResearch/Hermes-4.3-36B",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="NousResearch/Hermes-4-70B",
        variant_id="bf16-safetensors",
        resource_class="heavy",
        tool_calling="supported",
        runtimes=("vllm", "sglang"),
        licence_class="open-weight-restricted",
        licence_name="Llama 3.1 Community License (inherited from base)",
        licence_source_url=(
            "https://huggingface.co/meta-llama/Llama-3.1-405B/blob/main/LICENSE"
        ),
        licence_revision="3.1",
        licence_notes=(
            "The worked inheritance example. Sibling Hermes models are "
            "Apache-2.0, but this one is fine-tuned from Llama 3.1 70B and "
            "the base terms govern a downstream user: 700M monthly-active-"
            "user trigger requiring Meta's discretionary permission, a duty "
            "to prefix derivative model names with 'Llama', a 'Built with "
            "Llama' display duty, and Meta's AUP incorporated by reference."
        ),
        provenance_url="https://huggingface.co/NousResearch/Hermes-4-70B",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="zai-org/GLM-5.2-FP8",
        variant_id="fp8",
        quantisation="fp8",
        resource_class="heavy",
        max_context_tokens=1048576,
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="MIT (weights)",
        licence_source_url="https://huggingface.co/zai-org/GLM-5.2/blob/main/LICENSE",
        licence_revision=_OBSERVED,
        licence_notes=(
            "Weights are MIT with no added restriction; the code repo is "
            "Apache-2.0, so cite the weights licence for the weights. "
            "Licence-clean when self-hosted. The residual risk is "
            "operational, not contractual: routing to the vendor's hosted "
            "API sends prompts to PRC infrastructure, and procurement "
            "postures may exclude PRC-origin models. No vendor data-"
            "residency statement was found. Tool-calling support for the "
            "open weights is undocumented."
        ),
        provenance_url="https://huggingface.co/zai-org/GLM-5.2",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="deepseek-ai/DeepSeek-V4-Flash-0731",
        variant_id="dated-checkpoint-0731",
        resource_class="heavy",
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="MIT",
        licence_source_url=(
            "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/raw/main/README.md"
        ),
        licence_revision=_OBSERVED,
        licence_notes=(
            "MIT weights, licence-clean when self-hosted; the same hosted-"
            "API and procurement caveats as GLM apply and are operational, "
            "not contractual. Adapter hazard: V4 ships no Jinja chat "
            "template and instead supplies encoding scripts, so anything "
            "assuming apply_chat_template will silently mis-format. JSON "
            "mode and tool calls are documented at the hosted-API layer "
            "only, not for the open weights. Dated checkpoint, deliberately "
            "not collapsed into a generic 'DeepSeek-V4-Flash' row."
        ),
        provenance_url="https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
        variant_id="bf16-safetensors",
        resource_class="heavy",
        runtimes=("vllm", "sglang"),
        licence_class="open-weight-restricted",
        licence_name="Llama 4 Community License",
        licence_source_url="https://developer.meta.com/ai/llama4/license/",
        licence_revision="2025-04-05",
        licence_notes=(
            "Comparison candidate only. Weights are GATED: access requires "
            "accepting the licence and submitting full legal name, date of "
            "birth and organisation, which is a privacy and automation "
            "problem for any CI path. 700M MAU trigger; 'Llama' name-prefix "
            "and 'Built with Llama' duties; AUP incorporated by reference "
            "barring military, nuclear, espionage, ITAR-controlled and "
            "critical-infrastructure use."
        ),
        provenance_url=(
            "https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct"
        ),
        observed_on=_OBSERVED,
    ),
)
"""Dated candidate metadata. Inert: no entry can route and none can construct."""


def find(model_id: str, variant_id: str = "") -> Optional[ModelCapabilities]:
    """Look up one catalogue entry by exact model id, optionally by variant.

    When ``variant_id`` is omitted and several variants of a model id exist,
    this returns ``None`` rather than guessing which artifact was meant -
    picking one arbitrarily is precisely the collapsing this module exists to
    prevent.

    Returning a descriptor grants nothing: it is still unavailable, still
    unlocated, still unpinned, still factory-less, and still unroutable.
    """
    if type(model_id) is not str or type(variant_id) is not str:
        return None
    matches = [entry for entry in CATALOGUE if entry.model_id == model_id]
    if variant_id:
        matches = [entry for entry in matches if entry.variant_id == variant_id]
    if len(matches) == 1:
        return matches[0]
    return None


__all__ = ["CATALOGUE", "find"]
