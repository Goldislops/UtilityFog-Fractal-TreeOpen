"""Regression tests for the OMI-V1 third independent-audit round.

Each section reproduces a negative control that **did** occur against the
code as it stood at `8d2e592`, then asserts the corrected behaviour.

T1  `_exact_artifact_path` was defined but never called
T2  provenance and licence evidence could be missing, symbolic, or mutable
T3  a plural compatibility list satisfied a narrowed runtime requirement
T4  the six named negative controls, each asserted directly

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.open_model.capabilities import ModelCapabilities
from scripts.open_model.catalogue import CATALOGUE
from scripts.open_model.evaluation import stub_capabilities
from scripts.open_model.routing import TaskRequirements, evaluate

_SECRET = "sk-ABCDEFGH12345678"
_ABS_SECRET_PATH = (
    "C:" + chr(92) + "Users" + chr(92) + "kevin" + chr(92) + _SECRET + ".gguf"
)
_SHA = "1504002f650e656a0a3789d99574df12e3e94ed0"
_VLLM = "6e448d0ea9bf3d88d898b65449ca6dc2aec170ac"
_REPO = "org/model"


class _HostileBool:
    """Truth-testing this raises. Storing it made ``evaluate()`` non-total."""

    def __bool__(self):  # pragma: no cover - invocation is the failure
        raise RuntimeError("__bool__ invoked")

    def __len__(self):  # pragma: no cover
        raise RuntimeError("__len__ invoked")

    def __str__(self):  # pragma: no cover
        raise RuntimeError("__str__ invoked")

    def __repr__(self):  # pragma: no cover
        raise RuntimeError("__repr__ invoked")

    def __eq__(self, other):  # pragma: no cover
        raise RuntimeError("__eq__ invoked")

    def __hash__(self):  # pragma: no cover
        raise RuntimeError("__hash__ invoked")

    def __iter__(self):  # pragma: no cover
        raise RuntimeError("__iter__ invoked")


def _real(model_id: str = "org/model", **overrides) -> ModelCapabilities:
    """Artifact-bearing descriptor with complete immutable provenance."""
    revision = overrides.get("repository_revision", "1504002f650e656a0a3789d99574df12e3e94ed0")
    base = dict(
        model_id=model_id,
        variant_id="bf16",
        repository_revision=revision,
        provenance_url="https://huggingface.co/" + model_id + "/tree/" + revision,
        licence_source_url=(
            "https://huggingface.co/" + model_id + "/blob/" + revision + "/README.md"
        ),
        licence_revision="2.0",
        locality="local",
        availability="present",
        resource_class="light",
        structured_output="supported",
        tool_calling="supported",
        max_context_tokens=8192,
        runtimes=("vllm",),
        bound_runtime="vllm",
        bound_runtime_version="6e448d0ea9bf3d88d898b65449ca6dc2aec170ac",
        bound_runtime_object_kind="commit",
        bound_runtime_source_url=(
            "https://github.com/vllm-project/vllm/tree/6e448d0ea9bf3d88d898b65449ca6dc2aec170ac"
        ),
        licence_class="osi-open-source",
    )
    base.update(overrides)
    return ModelCapabilities(**base)  # type: ignore[arg-type]


def test_the_baseline_descriptor_is_actually_eligible():
    """Guards the suite: if this failed, every negative below proves nothing."""
    assert evaluate(_real(), TaskRequirements()) == ()


# == Control 1 - absolute secret-shaped artifact_path surviving and routing ==


def test_control1_absolute_secret_shaped_artifact_path_is_normalized_away():
    caps = _real(artifact_path=_ABS_SECRET_PATH)
    assert caps.artifact_path == ""
    assert _SECRET not in repr(caps)
    assert "Users" not in repr(caps)


def test_control1_a_rejected_path_invalidates_rather_than_collapsing():
    """Inverted in round four, because the old behaviour was the defect.

    This previously asserted that a rejected path collapsed to "" and the
    descriptor then routed through the repository-commit fallback - which is
    exactly the silent downgrade the fourth audit named. A supplied path that
    cannot be made canonical now invalidates the descriptor instead.
    """
    caps = _real(
        artifact_path=_ABS_SECRET_PATH, artifact_digest="sha256:" + "ab" * 32
    )
    assert caps.artifact_path == ""
    assert caps.invalid_fields == ("artifact_path",)
    assert "descriptor-invalid" in evaluate(caps, TaskRequirements())


@pytest.mark.parametrize(
    "supplied",
    [
        _ABS_SECRET_PATH,
        "/home/kevin/model.gguf",
        "/Users/kevin/model.gguf",
        chr(92) + chr(92) + "server" + chr(92) + "share" + chr(92) + "m.gguf",
        "C:/Users/kevin/m.gguf",
        _SECRET,
        "has space.gguf",
        7,
        None,
        b"m.gguf",
    ],
)
def test_control1_unsafe_artifact_paths_all_normalize_to_empty(supplied):
    assert ModelCapabilities(model_id="a/b", artifact_path=supplied).artifact_path == ""


def test_control1_a_legitimate_repository_relative_path_survives():
    for good in ("m.gguf", "sub/dir/model-00001-of-00004.safetensors", "a.bin"):
        assert ModelCapabilities(model_id="a/b", artifact_path=good).artifact_path == good


# == Control 2 - hostile artifact_path __bool__ raising ======================


def test_control2_a_hostile_artifact_path_invokes_no_hook_and_is_dropped():
    caps = ModelCapabilities(model_id="a/b", artifact_path=_HostileBool())
    assert caps.artifact_path == ""
    assert type(caps.artifact_path) is str


def test_control2_evaluate_stays_total_against_a_hostile_artifact_path():
    caps = _real(artifact_path=_HostileBool())
    reasons = evaluate(caps, TaskRequirements())
    assert isinstance(reasons, tuple)


def test_control2_unresolved_fields_stays_total_against_a_hostile_path():
    caps = _real(artifact_path=_HostileBool())
    assert isinstance(caps.unresolved_fields(), tuple)


def test_control2_every_derived_predicate_stays_total():
    caps = _real(artifact_path=_HostileBool())
    assert caps.is_artifact_bearing() is True
    assert caps.is_byte_pinned() is True
    assert caps.has_pinned_provenance() is True
    assert caps.has_pinned_licence() is True
    assert caps.has_pinned_runtime_binding() is True


# == Control 3 - missing provenance_url routing ==============================


def test_control3_a_missing_provenance_url_blocks():
    assert "provenance-unpinned" in evaluate(
        _real(provenance_url=""), TaskRequirements()
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://huggingface.co/org/model",                       # no revision
        "https://huggingface.co/org/model/tree/main",             # symbolic
        "https://huggingface.co/other/repo/tree/" + _SHA,         # wrong repo
        "http://huggingface.co/org/model/tree/" + _SHA,           # not https
    ],
)
def test_control3_provenance_must_bind_this_repo_at_this_revision(url):
    assert "provenance-unpinned" in evaluate(
        _real(provenance_url=url), TaskRequirements()
    )


# == Control 4 - repository_revision="main" plus a file digest ===============


def test_control4_a_symbolic_revision_with_a_digest_no_longer_routes():
    """Byte-pinned by the file, but the repository claim is still mutable."""
    caps = _real(
        repository_revision="main",
        artifact_path="m.gguf",
        artifact_digest="sha256:" + "ab" * 32,
    )
    assert caps.is_byte_pinned() is True          # the file is pinned
    reasons = evaluate(caps, TaskRequirements())
    assert "repository-revision-not-immutable" in reasons
    assert "provenance-unpinned" in reasons


@pytest.mark.parametrize(
    "revision", ["main", "master", "HEAD", "latest", "dev", "stable", "v1.2.3"]
)
def test_control4_symbolic_revisions_are_refused_for_artifact_bearing(revision):
    assert "repository-revision-not-immutable" in evaluate(
        _real(repository_revision=revision), TaskRequirements()
    )


# == Control 5 - mutable licence URL and revision =============================


def test_control5_a_blob_main_licence_url_no_longer_routes():
    assert "licence-source-unpinned" in evaluate(
        _real(
            licence_source_url=(
                "https://huggingface.co/" + _REPO + "/blob/main/README.md"
            )
        ),
        TaskRequirements(),
    )


def test_control5_a_mutable_licence_revision_no_longer_routes():
    assert "licence-source-unpinned" in evaluate(
        _real(licence_revision="main"), TaskRequirements()
    )


@pytest.mark.parametrize(
    "revision", ["main", "master", "HEAD", "latest", "stable", "nightly", ""]
)
def test_control5_mutable_licence_revisions_are_all_refused(revision):
    assert "licence-source-unpinned" in evaluate(
        _real(licence_revision=revision), TaskRequirements()
    )


def test_control5_a_licence_url_for_another_repository_is_refused():
    assert "licence-source-unpinned" in evaluate(
        _real(
            licence_source_url=(
                "https://huggingface.co/other/repo/blob/" + _SHA + "/README.md"
            )
        ),
        TaskRequirements(),
    )


# == Control 6 - an unbound runtime satisfying allowed_runtimes ==============


def test_control6_a_compatibility_list_alone_cannot_satisfy_a_narrowed_task():
    """The exact failure: `runtimes` is what a vendor claims, not what runs."""
    caps = _real(
        runtimes=("vllm", "sglang"),
        bound_runtime="",
        bound_runtime_version="",
        bound_runtime_source_url="",
    )
    reasons = evaluate(caps, TaskRequirements(allowed_runtimes=("vllm",)))
    assert "bound-runtime-unspecified" in reasons


def test_control6_the_bound_runtime_is_what_a_narrowed_task_is_judged_on():
    # Compatible with sglang on paper, but the factory binds vllm.
    caps = _real(runtimes=("vllm", "sglang"), bound_runtime="vllm")
    assert "bound-runtime-not-allowed" in evaluate(
        caps, TaskRequirements(allowed_runtimes=("sglang",))
    )
    assert evaluate(caps, TaskRequirements(allowed_runtimes=("vllm",))) == ()


def test_control6_a_bound_runtime_must_be_among_the_declared_runtimes():
    caps = _real(runtimes=("vllm",), bound_runtime="ollama")
    assert "bound-runtime-not-declared" in evaluate(caps, TaskRequirements())


@pytest.mark.parametrize(
    "overrides",
    [
        {"bound_runtime_version": ""},
        {"bound_runtime_source_url": ""},
        {"bound_runtime_version": "main"},
        {"bound_runtime_source_url": "https://github.com/vllm-project/vllm"},
        {"bound_runtime_source_url": "http://github.com/vllm-project/vllm/tree/" + _VLLM},
    ],
)
def test_control6_an_unpinned_runtime_binding_is_refused(overrides):
    assert "bound-runtime-unpinned" in evaluate(
        _real(**overrides), TaskRequirements()
    )


def test_control6_no_catalogue_entry_can_satisfy_a_narrowed_runtime_task():
    # Catalogue entries carry compatibility lists and no factory, so none of
    # them declares a bound runtime.
    for entry in CATALOGUE:
        assert entry.bound_runtime == ""
        reasons = evaluate(entry, TaskRequirements(allowed_runtimes=("vllm",)))
        assert "bound-runtime-unspecified" in reasons


# == The stub exception stays explicit and narrow ============================


def test_the_stub_exception_is_narrow_and_named():
    stub = stub_capabilities("double")
    assert stub.is_artifact_bearing() is False
    assert stub.bound_runtime == "in-process-stub"
    assert evaluate(stub, TaskRequirements()) == ()
    assert evaluate(stub, TaskRequirements(allowed_runtimes=("in-process-stub",))) == ()


def test_the_stub_exception_does_not_extend_to_a_real_runtime():
    # Adding any real runtime makes it artifact-bearing, and the full
    # provenance requirement immediately applies.
    pretender = stub_capabilities("pretender")
    widened = ModelCapabilities(
        model_id=pretender.model_id,
        variant_id=pretender.variant_id,
        repository_revision=pretender.repository_revision,
        locality="local",
        availability="present",
        resource_class="light",
        structured_output="supported",
        tool_calling="supported",
        max_context_tokens=8192,
        runtimes=("in-process-stub", "vllm"),
        licence_class="osi-open-source",
        licence_source_url=pretender.licence_source_url,
        licence_revision=pretender.licence_revision,
    )
    assert widened.is_artifact_bearing() is True
    reasons = evaluate(widened, TaskRequirements())
    assert "repository-revision-not-immutable" in reasons
    assert "provenance-unpinned" in reasons


# == Documented facts corrected this round ===================================

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "OPEN_MODEL_INTEGRATION.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_doc_records_the_corrected_facts():
    text = _flat(_DOC.read_text(encoding="utf-8"))
    # GLM FP8 human row bound to the FP8 repo at its exact revision
    assert "zai-org/GLM-5.2-FP8" in text
    assert "ba978f7d347eaf65d22f1a86833408afdb953541" in text
    # TensorRT-LLM RC line replaced by the stable release
    assert "1.3.0 RC line" not in text
    assert "v1.2.1" in text
    # SGLang tag object AND its peeled commit
    assert "ff4c6e641d9f9bb174d34ff651c01c114aea8e40" in text
    assert "71de97b264b04dcd514cf904003028aefe9775c8" in text
    # Llama gated state recorded exactly
    assert "manual" in text
    # NIM is not claimed to be pinned
    assert "unresolved" in text.lower()


def test_doc_no_longer_claims_catalogue_provenance_is_unpopulated():
    text = _flat(_DOC.read_text(encoding="utf-8")).lower()
    for stale in (
        "provenance is unpinned, deliberately",
        "did not retrieve commit revisions or file digests",
        "are empty on every entry",
    ):
        assert stale not in text


def test_doc_does_not_claim_the_pinned_gemma_card_links_a_use_policy():
    text = _flat(_DOC.read_text(encoding="utf-8"))
    assert "Prohibited Use Policy is still referenced from the card" not in text
    assert "Prohibited Use Policy is still referenced from the model card" not in text
