"""OMI-V1 - dated, inert candidate descriptors. **Nothing here is approved.**

Read this paragraph before using anything in this module. Every entry below
is *metadata a human read off a vendor's own page on 2026-08-22*. Presence in
this catalogue does **not** mean a model has been downloaded, installed,
benchmarked, evaluated, licensed for any particular use, trusted, or
approved. No entry has been run. This repository has executed none of them.

That is enforced, not merely asserted, in three independent ways:

  1. Every entry declares ``availability="unknown"`` and ``locality="unknown"``.
     Both are blocking conditions in ``scripts.open_model.routing``, so no
     catalogue entry can be selected by any set of requirements whatsoever.
     ``tests/test_open_model_routing.py`` asserts this over the whole
     catalogue, so an entry cannot become routable through an editing slip.
  2. No entry carries a factory. ``scripts.open_model.registry`` requires an
     operator-written factory callable to make anything constructible, and a
     descriptor alone provides none.
  3. No entry carries an endpoint, command, credential, or download location.

To actually use a model, an operator writes a factory, observes the backend
working, authors a *new* descriptor asserting ``availability="present"`` and a
real ``locality``, and registers it against an explicit allowlist. That
sequence is deliberately not automatable from this file.

**How the numbers were chosen.** ``max_context_tokens`` is populated only
where an exact token integer was read from the vendor's own model card. Where
a source stated a rounded figure - "256K", "1M", "10M" - the field is left at
``0`` (unknown) rather than converted to a plausible power of two. Routing
compares integers, and a converted marketing figure would be a fabricated
fact wearing the costume of a measured one. Several entries below are
therefore blocked on ``context-unknown``, which is the correct state.

**Licence classification is conservative.** Where a licence's OSI status
could not be confirmed from the licence text itself, the entry is classified
into the *more* restrictive class. NVIDIA's OpenMDW-1.1 is the clearest case:
its terms are close to permissive, but the licence page makes no OSI claim,
so it is recorded as ``open-weight-restricted`` with the nuance in the note.

**Fine-tunes inherit.** Where a model is a fine-tune, the class recorded is
the one that governs a downstream user - the *base* licence - not whatever
the fine-tuner wrote on their own card. ``Hermes-4-70B`` below is the worked
example.

Sources for every field are in ``docs/OPEN_MODEL_INTEGRATION.md``, which
carries the full dated matrix including the unresolved risks that did not fit
in a descriptor.
"""

from __future__ import annotations

from typing import Final, Optional

from scripts.open_model.capabilities import ModelCapabilities


_OBSERVED: Final[str] = "2026-08-22"


CATALOGUE: Final[tuple[ModelCapabilities, ...]] = (
    ModelCapabilities(
        model_id="ibm-granite/granite-4.1-8b",
        resource_class="light",
        tool_calling="supported",
        max_context_tokens=131072,
        quantisations=("bf16", "gguf-q4_k_m", "gguf-q8_0"),
        runtimes=("llama-cpp", "ollama", "vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_notes=(
            "Apache-2.0 end to end: no revenue threshold, no acceptable-use "
            "policy attached to the weights, not gated. First-party GGUF is "
            "published by IBM itself. Card states a 131072 sequence length "
            "while IBM's blog claims up to 512K; the card figure is used."
        ),
        provenance_url="https://huggingface.co/ibm-granite/granite-4.1-8b",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="google/gemma-4-12B-it",
        resource_class="medium",
        tool_calling="supported",
        quantisations=("bf16", "qat-q4_0-gguf", "w4a16"),
        runtimes=("llama-cpp", "ollama", "vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_notes=(
            "Gemma 4 moved to Apache-2.0 and is no longer click-through "
            "gated, unlike earlier Gemma generations. The Gemma Prohibited "
            "Use Policy is still referenced from the model card; whether it "
            "binds Apache-2.0 weights is unresolved - counsel question, not "
            "a routing input. Context documented as 256K, not as an exact "
            "token count."
        ),
        provenance_url="https://huggingface.co/google/gemma-4-12B-it",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B",
        resource_class="medium",
        tool_calling="supported",
        quantisations=("bf16", "nvfp4"),
        runtimes=("llama-cpp", "ollama", "vllm", "sglang", "tensorrt-llm"),
        licence_class="open-weight-restricted",
        licence_name="OpenMDW-1.1",
        licence_notes=(
            "OpenMDW-1.1 is close to permissive - use without restriction, "
            "no output restrictions, notice retention plus a patent-"
            "litigation termination clause - but the licence page makes no "
            "OSI claim, so it is classified conservatively. Tool calls use "
            "Qwen3-Coder-style syntax via the runtime parser, not OpenAI-"
            "native. The GGUF build lives outside the vendor org."
        ),
        provenance_url=(
            "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="nvidia/NVIDIA-Nemotron-3-Nano-4B",
        resource_class="light",
        quantisations=("bf16", "fp8", "gguf"),
        licence_class="open-weight-restricted",
        licence_name="NVIDIA Nemotron Open Model License",
        licence_notes=(
            "Commercial use permitted, redistribution and derivatives "
            "allowed, requires notice retention and a NOTICE line; "
            "litigation-triggered termination; no acceptable-use clause "
            "found in the licence text. Not OSI-approved. Deliberately left "
            "underspecified here: no runtime, context, or tool-calling claim "
            "was verified for this specific 4B repo, so none is recorded."
        ),
        provenance_url="https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="mistralai/Mistral-Small-4-119B-2603",
        resource_class="heavy",
        tool_calling="supported",
        quantisations=("bf16", "nvfp4"),
        runtimes=("vllm", "sglang", "llama-cpp"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
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
        resource_class="medium",
        tool_calling="supported",
        quantisations=("bf16", "gguf"),
        runtimes=("vllm", "sglang", "llama-cpp", "ollama"),
        licence_class="osi-open-source",
        licence_name="Apache-2.0 (inherited from ByteDance Seed-OSS-36B base)",
        licence_notes=(
            "Fine-tune of an Apache-2.0 base, so the inherited class is "
            "clean. Trained to emit valid JSON for a given schema and to "
            "repair malformed objects, but that is a training claim, not a "
            "decoding guarantee - constrained decoding still comes from the "
            "runtime. First-party GGUF published."
        ),
        provenance_url="https://huggingface.co/NousResearch/Hermes-4.3-36B",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="NousResearch/Hermes-4-70B",
        resource_class="heavy",
        tool_calling="supported",
        quantisations=("bf16", "fp8"),
        runtimes=("vllm", "sglang"),
        licence_class="open-weight-restricted",
        licence_name="Llama 3.1 Community License (inherited from base)",
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
        model_id="zai-org/GLM-5.2",
        resource_class="heavy",
        max_context_tokens=1048576,
        quantisations=("bf16", "fp8"),
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="MIT (weights)",
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
        model_id="deepseek-ai/DeepSeek-V4-Flash",
        resource_class="heavy",
        quantisations=("bf16", "fp8", "fp4-fp8-mixed"),
        runtimes=("vllm", "sglang"),
        licence_class="osi-open-source",
        licence_name="MIT",
        licence_notes=(
            "MIT weights, licence-clean when self-hosted; the same hosted-"
            "API and procurement caveats as GLM apply and are operational, "
            "not contractual. Adapter hazard: V4 ships no Jinja chat "
            "template and instead supplies encoding scripts, so anything "
            "assuming apply_chat_template will silently mis-format. JSON "
            "mode and tool calls are documented at the hosted-API layer "
            "only, not for the open weights."
        ),
        provenance_url="https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731",
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
        resource_class="heavy",
        quantisations=("bf16", "int4-on-the-fly"),
        runtimes=("vllm", "sglang"),
        licence_class="open-weight-restricted",
        licence_name="Llama 4 Community License",
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


def find(model_id: str) -> Optional[ModelCapabilities]:
    """Look up one catalogue entry by exact model id, or ``None``.

    Returning a descriptor grants nothing: it is still unavailable, still
    unlocated, still factory-less, and still unroutable.
    """
    if type(model_id) is not str:
        return None
    for entry in CATALOGUE:
        if entry.model_id == model_id:
            return entry
    return None


__all__ = ["CATALOGUE", "find"]
