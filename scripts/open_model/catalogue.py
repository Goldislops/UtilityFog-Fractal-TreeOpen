"""OMI-V1 - dated, inert candidate descriptors. **Nothing here is approved.**

Read this paragraph before using anything in this module. Every entry below
is *metadata a human read off a vendor's own page on 2026-08-22*. Presence in
this catalogue does **not** mean a model has been downloaded, installed,
benchmarked, evaluated, licensed for any particular use, trusted, or
approved. No entry has been run. This repository has executed none of them.

That is enforced, not merely asserted, in four independent ways:

  1. Every entry declares ``availability="unknown"`` and ``locality="unknown"``.
     Both are blocking conditions in ``scripts.open_model.routing``.
  2. Every entry is byte-pinned but still unavailable and unlocated: a pin
     says *which bytes*, never *that you may run them*.
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

**Provenance is now pinned to immutable identifiers (audit round two).**
Every entry carries a full commit id read on 2026-08-22 from the official
Hugging Face model metadata API, and every single-file variant additionally
carries that file's LFS ``sha256`` digest read from the official repository
tree metadata at that same revision. **No model bytes or weights were
downloaded**; metadata retrieval is not artifact retrieval, and the two are
worth keeping distinct.

``provenance_url`` and ``licence_source_url`` are revision-pinned URLs, not
branch URLs, so both resolve to the exact content that was read. A branch URL
would silently change under a reviewer.

Two pin shapes are used, and which one applies is a property of the artifact
rather than a matter of taste:

  - **single-file variants** (the GGUF builds) carry ``artifact_path`` plus
    the ``sha256`` of that file;
  - **sharded variants** (BF16 safetensors, FP8) carry the full commit id,
    which pins every shard at once. Granite 4.1 8B BF16 is four shards -
    there is no single file whose digest would mean anything.

Digests were read for the named single files only; shard-level digests exist
in the same metadata and were not transcribed, because the commit id already
covers them and copying sixty hashes by hand invites transcription error.

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

CATALOGUE: Final[tuple[ModelCapabilities, ...]] = (
    ModelCapabilities(
        model_id="ibm-granite/granite-4.1-8b",
        variant_id="bf16-safetensors-sharded",
        repository_revision="1504002f650e656a0a3789d99574df12e3e94ed0",
        resource_class="light",
        tool_calling="supported",
        max_context_tokens=131072,
        runtimes=('vllm', 'sglang'),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=(
            "https://huggingface.co/ibm-granite/granite-4.1-8b/blob/1504002f650e656a0a3789d99574df12e3e94ed0/README.md"
        ),
        licence_revision="2.0",
        licence_notes=(
            "Repo metadata at this revision declares license apache-2.0. "
            "Weights are four safetensors shards, so no single-file digest "
            "would be meaningful; the commit id pins all four exactly. Card "
            "states 131072 while the vendor blog claims up to 512K, so the card "
            "figure is used."
        ),
        provenance_url=(
            "https://huggingface.co/ibm-granite/granite-4.1-8b/tree/1504002f650e656a0a3789d99574df12e3e94ed0"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="ibm-granite/granite-4.1-8b-GGUF",
        variant_id="gguf-q4-k-m",
        repository_revision="865b82c2e7970d82e3731278c88c57ae7138359c",
        artifact_path="granite-4.1-8b-Q4_K_M.gguf",
        artifact_digest=(
            "sha256:ed902ac9eb6adce5a90c6a08c8ea201b50e23fdc5976d1cd0362006afac5309e"
        ),
        quantisation="gguf-q4_k_m",
        resource_class="light",
        tool_calling="supported",
        max_context_tokens=131072,
        runtimes=('llama-cpp', 'ollama'),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=(
            "https://huggingface.co/ibm-granite/granite-4.1-8b-GGUF/blob/865b82c2e7970d82e3731278c88c57ae7138359c/README.md"
        ),
        licence_revision="2.0",
        licence_notes=(
            "First-party GGUF published by IBM itself. The digest is the LFS "
            "oid of the single named file at this revision, read from official "
            "repository metadata; no weights were downloaded. The same "
            "repository publishes a bf16 GGUF and eleven other quantisations, "
            "each a distinct artifact with its own digest."
        ),
        provenance_url=(
            "https://huggingface.co/ibm-granite/granite-4.1-8b-GGUF/tree/865b82c2e7970d82e3731278c88c57ae7138359c"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="google/gemma-4-12B-it",
        variant_id="bf16-safetensors",
        repository_revision="707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7",
        resource_class="medium",
        tool_calling="supported",
        runtimes=('vllm', 'sglang'),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=(
            "https://huggingface.co/google/gemma-4-12B-it/blob/707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7/README.md"
        ),
        licence_revision="2.0",
        licence_notes=(
            "Repo metadata at this revision declares license apache-2.0, "
            "corroborating the Gemma 4 move away from the Gemma Terms of Use, "
            "and the repository is not gated. The card at this revision was "
            "checked and references NO prohibited-use policy and no Gemma "
            "Terms of Use; an earlier claim that it did was false and is "
            "retracted. A separate general Gemma policy exists elsewhere in "
            "Google docs and its relation to Apache-2.0 weights is "
            "unresolved, but this card does not link it."
        ),
        provenance_url=(
            "https://huggingface.co/google/gemma-4-12B-it/tree/707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="google/gemma-4-12B-it-qat-q4_0-gguf",
        variant_id="qat-q4-0-gguf",
        repository_revision="29d097773436b69ff9feafd636ab4cf873786537",
        artifact_path="gemma-4-12b-it-qat-q4_0.gguf",
        artifact_digest=(
            "sha256:93567e57a8fe10b23569b9d9ec38cd005deedf71e29477c421a4b83f418a538b"
        ),
        quantisation="gguf-q4_0",
        resource_class="light",
        tool_calling="supported",
        runtimes=('llama-cpp', 'ollama'),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=(
            "https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf/blob/29d097773436b69ff9feafd636ab4cf873786537/README.md"
        ),
        licence_revision="2.0",
        licence_notes=(
            "Quantisation-aware-trained q4_0 GGUF published by Google. A "
            "distinct artifact from the BF16 repository: different file, "
            "different runtimes, different numerics. The repository also "
            "carries a separate mmproj file, which is a further distinct "
            "artifact and is not this descriptor."
        ),
        provenance_url=(
            "https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf/tree/29d097773436b69ff9feafd636ab4cf873786537"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16",
        variant_id="bf16",
        repository_revision="d468880b6ad3c6e0d21377ce7242adaea4cc884d",
        resource_class="medium",
        tool_calling="supported",
        runtimes=('vllm', 'sglang', 'tensorrt-llm'),
        licence_class="open-weight-restricted",
        licence_name="OpenMDW-1.1",
        licence_source_url=(
            "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/blob/d468880b6ad3c6e0d21377ce7242adaea4cc884d/README.md"
        ),
        licence_revision="1.1",
        licence_notes=(
            "Repo metadata at this revision declares license_name openmdw-1.1. "
            "OpenMDW is close to permissive, but its licence page makes no OSI "
            "claim, so it is classified conservatively. Tool calls use "
            "Qwen3-Coder-style syntax via the runtime parser, not "
            "OpenAI-native."
        ),
        provenance_url=(
            "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/tree/d468880b6ad3c6e0d21377ce7242adaea4cc884d"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF",
        variant_id="gguf-q4-k-m",
        repository_revision="ba223d14e45525f7fae81db77ea8cabeb2fc6c25",
        artifact_path="NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf",
        artifact_digest=(
            "sha256:be5d9a656a51922f24f1f09a759cebb694e1f5d9728bf0ef9f8c972c5a0b5ef2"
        ),
        quantisation="gguf-q4_k_m",
        resource_class="light",
        runtimes=('llama-cpp', 'ollama'),
        licence_class="open-weight-restricted",
        licence_name="NVIDIA Nemotron Open Model License",
        licence_source_url=(
            "https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF/blob/ba223d14e45525f7fae81db77ea8cabeb2fc6c25/LICENSE"
        ),
        licence_revision="2025-12-15",
        licence_notes=(
            "Repo metadata declares license_name "
            "nvidia-nemotron-open-model-license, and the repository carries its "
            "own LICENSE file, pinned here at this revision. Commercial use "
            "permitted; notice retention plus a NOTICE line; "
            "litigation-triggered termination; not OSI-approved. Note the "
            "artifact file name omits a hyphen the repository id carries, "
            "recorded verbatim rather than tidied."
        ),
        provenance_url=(
            "https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF/tree/ba223d14e45525f7fae81db77ea8cabeb2fc6c25"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="mistralai/Mistral-Small-4-119B-2603",
        variant_id="bf16-safetensors",
        repository_revision="a11f36bebf709121056b1dbcc943d1c6afbe494d",
        resource_class="heavy",
        tool_calling="supported",
        runtimes=('vllm', 'sglang', 'llama-cpp'),
        licence_class="osi-open-source",
        licence_name="Apache-2.0",
        licence_source_url=(
            "https://huggingface.co/mistralai/Mistral-Small-4-119B-2603/blob/a11f36bebf709121056b1dbcc943d1c6afbe494d/README.md"
        ),
        licence_revision="2.0",
        licence_notes=(
            "Repo metadata declares apache-2.0. The family is split: Devstral 2 "
            "and Mistral Medium 3.5 are Modified MIT with a 20M USD monthly "
            "revenue trigger, and Voxtral TTS is CC BY-NC. A blanket "
            "family-level claim would be false. GGUF builds are community, not "
            "first-party."
        ),
        provenance_url=(
            "https://huggingface.co/mistralai/Mistral-Small-4-119B-2603/tree/a11f36bebf709121056b1dbcc943d1c6afbe494d"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="NousResearch/Hermes-4.3-36B",
        variant_id="bf16-safetensors",
        repository_revision="3899db2b6c4b35f16bde3b570bb7dd2775d56161",
        resource_class="medium",
        tool_calling="supported",
        runtimes=('vllm', 'sglang'),
        licence_class="osi-open-source",
        licence_name="Apache-2.0 (inherited from ByteDance Seed-OSS-36B)",
        licence_source_url=(
            "https://huggingface.co/NousResearch/Hermes-4.3-36B/blob/3899db2b6c4b35f16bde3b570bb7dd2775d56161/README.md"
        ),
        licence_revision="2.0",
        licence_notes=(
            "Repo metadata declares apache-2.0, consistent with its Apache-2.0 "
            "base. Trained to emit valid JSON for a given schema and to repair "
            "malformed objects, but that is a training claim, not a decoding "
            "guarantee; constrained decoding still comes from the runtime."
        ),
        provenance_url=(
            "https://huggingface.co/NousResearch/Hermes-4.3-36B/tree/3899db2b6c4b35f16bde3b570bb7dd2775d56161"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="NousResearch/Hermes-4-70B",
        variant_id="bf16-safetensors",
        repository_revision="d5dec2bd6b3930a09ddefd0b7fc6523fe0720d09",
        resource_class="heavy",
        tool_calling="supported",
        runtimes=('vllm', 'sglang'),
        licence_class="open-weight-restricted",
        licence_name="Llama 3.1 Community License (inherited)",
        licence_source_url=(
            "https://huggingface.co/NousResearch/Hermes-4-70B/blob/d5dec2bd6b3930a09ddefd0b7fc6523fe0720d09/README.md"
        ),
        licence_revision="3.1",
        licence_notes=(
            "The worked inheritance example, and repository metadata "
            "corroborates it directly: the declared license tag at this "
            "revision is llama3, not apache-2.0, unlike its Hermes siblings. "
            "Base terms govern a downstream user: 700M monthly-active-user "
            "trigger, a duty to prefix derivative model names with Llama, a "
            "Built with Llama display duty, and the Meta acceptable-use policy "
            "incorporated by reference."
        ),
        provenance_url=(
            "https://huggingface.co/NousResearch/Hermes-4-70B/tree/d5dec2bd6b3930a09ddefd0b7fc6523fe0720d09"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="zai-org/GLM-5.2-FP8",
        variant_id="fp8",
        repository_revision="ba978f7d347eaf65d22f1a86833408afdb953541",
        quantisation="fp8",
        resource_class="heavy",
        max_context_tokens=1048576,
        runtimes=('vllm', 'sglang'),
        licence_class="osi-open-source",
        licence_name="MIT (weights)",
        licence_source_url=(
            "https://huggingface.co/zai-org/GLM-5.2-FP8/blob/ba978f7d347eaf65d22f1a86833408afdb953541/README.md"
        ),
        licence_revision="2026-08-22",
        licence_notes=(
            "Corrected after audit: this row now binds to the FP8 repository "
            "itself rather than to the BF16 repository. Repo metadata at this "
            "revision declares license mit. Licence-clean when self-hosted; the "
            "residual risk is operational rather than contractual, being "
            "hosted-API prompt egress to PRC infrastructure and procurement "
            "posture. Weights are sharded, so the commit id is the byte pin."
        ),
        provenance_url=(
            "https://huggingface.co/zai-org/GLM-5.2-FP8/tree/ba978f7d347eaf65d22f1a86833408afdb953541"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="deepseek-ai/DeepSeek-V4-Flash-0731",
        variant_id="dated-checkpoint-0731",
        repository_revision="7872f01b1d1fe23eabc4c98b48bffcef5a386062",
        resource_class="heavy",
        runtimes=('vllm', 'sglang'),
        licence_class="osi-open-source",
        licence_name="MIT",
        licence_source_url=(
            "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/blob/7872f01b1d1fe23eabc4c98b48bffcef5a386062/README.md"
        ),
        licence_revision="2026-08-22",
        licence_notes=(
            "Repo metadata declares license mit. The same hosted-API and "
            "procurement caveats as GLM apply and are operational rather than "
            "contractual. Adapter hazard: V4 ships no Jinja chat template and "
            "supplies encoding scripts instead, so anything assuming "
            "apply_chat_template will silently mis-format."
        ),
        provenance_url=(
            "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-0731/tree/7872f01b1d1fe23eabc4c98b48bffcef5a386062"
        ),
        observed_on=_OBSERVED,
    ),
    ModelCapabilities(
        model_id="meta-llama/Llama-4-Scout-17B-16E-Instruct",
        variant_id="bf16-safetensors",
        repository_revision="92f3b1597a195b523d8d9e5700e57e4fbb8f20d3",
        resource_class="heavy",
        runtimes=('vllm', 'sglang'),
        licence_class="open-weight-restricted",
        licence_name="Llama 4 Community License",
        licence_source_url=(
            "https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct/blob/92f3b1597a195b523d8d9e5700e57e4fbb8f20d3/README.md"
        ),
        licence_revision="2025-04-05",
        licence_notes=(
            "Comparison candidate only. Repo metadata at this revision reports "
            "the literal gated value \"manual\" - human approval per "
            "request, not merely true - and license=other, corroborating "
            "the gating claim: "
            "access requires accepting the licence and submitting legal name, "
            "date of birth and organisation, which is a privacy and automation "
            "problem for any CI path. 700M monthly-active-user trigger; naming "
            "and display duties; the acceptable-use policy bars military, "
            "nuclear, espionage, ITAR-controlled and critical-infrastructure "
            "use."
        ),
        provenance_url=(
            "https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct/tree/92f3b1597a195b523d8d9e5700e57e4fbb8f20d3"
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
    unlocated, still factory-less, and still unroutable. It is byte-pinned,
    which tells you which bytes it names - not that you may run them.
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
