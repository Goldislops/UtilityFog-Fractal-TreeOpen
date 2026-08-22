"""Regression tests for the OMI-V1 fifth independent-audit round.

Every control here reproduced against the code as it stood at `4a0653a`.

J1  bound_runtime was bound only to github.com plus a trailing object id, so
    a real vLLM commit could vouch for an unrelated repository
J2  the long-opaque secret rule was skipped for the WHOLE URL, excusing a
    credential in the owner, repository or file-name position
J3  a secret-bearing licence path was stored even though routing refused it
J4  percent-encoded components were neither decoded nor refused, so
    %2e%2e traversal was stored AND eligible
J5  the round-two prose still claimed every runtime claim was pinned

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.open_model.capabilities import (
    RUNTIME_REPOSITORIES,
    ModelCapabilities,
    is_canonical_relative_path,
    parse_https_url,
)
from scripts.open_model.catalogue import CATALOGUE
from scripts.open_model.routing import TaskRequirements, evaluate

_SHA = "1504002f650e656a0a3789d99574df12e3e94ed0"
_VLLM = "6e448d0ea9bf3d88d898b65449ca6dc2aec170ac"
_SGLANG_TAG = "ff4c6e641d9f9bb174d34ff651c01c114aea8e40"
_FOREIGN_SHA = "0123456789abcdef0123456789abcdef01234567"
_REPO = "org/model"
_SECRET48 = "A" * 48
_SECRET_B64 = "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHZlcnkgbG9uZyBzZWNyZXQx"


def _real(**overrides) -> ModelCapabilities:
    base = dict(
        model_id=_REPO,
        variant_id="bf16",
        repository_revision=_SHA,
        provenance_url="https://huggingface.co/" + _REPO + "/tree/" + _SHA,
        licence_source_url=(
            "https://huggingface.co/" + _REPO + "/blob/" + _SHA + "/README.md"
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
        bound_runtime_version=_VLLM,
        bound_runtime_object_kind="commit",
        bound_runtime_source_url=(
            "https://github.com/vllm-project/vllm/tree/" + _VLLM
        ),
        licence_class="osi-open-source",
    )
    base.update(overrides)
    return ModelCapabilities(**base)  # type: ignore[arg-type]


def test_baseline_is_eligible():
    """Guard: without this every negative below could pass for a wrong reason."""
    assert evaluate(_real(), TaskRequirements()) == ()


# == J1 - a runtime token binds to its exact official repository =============


def test_j1_a_real_commit_cannot_vouch_for_an_unrelated_repository():
    """The named control: a genuine vLLM commit under someone else's repo."""
    caps = _real(
        bound_runtime_source_url=(
            "https://github.com/evil-org/fake-runtime/tree/" + _VLLM
        )
    )
    assert caps.has_pinned_runtime_binding() is False
    assert "bound-runtime-unpinned" in evaluate(caps, TaskRequirements())


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/evil-org/vllm/tree/" + _VLLM,          # wrong owner
        "https://github.com/vllm-project/not-vllm/tree/" + _VLLM,  # wrong repo
        "https://github.com/vllm-project/vllm/blob/" + _VLLM,      # wrong kind
        "https://github.com/vllm-project/vllm/tree/" + _VLLM + "/x",  # suffix
        "https://github.com/x/vllm-project/vllm/tree/" + _VLLM,    # prefixed
        "https://gitlab.com/vllm-project/vllm/tree/" + _VLLM,      # wrong host
    ],
)
def test_j1_only_the_complete_canonical_path_is_accepted(url):
    assert "bound-runtime-unpinned" in evaluate(
        _real(bound_runtime_source_url=url), TaskRequirements()
    )


@pytest.mark.parametrize(
    "token,repository",
    [
        ("llama-cpp", "ggml-org/llama.cpp"),
        ("ollama", "ollama/ollama"),
        ("vllm", "vllm-project/vllm"),
        ("sglang", "sgl-project/sglang"),
        ("tensorrt-llm", "NVIDIA/TensorRT-LLM"),
    ],
)
def test_j1_the_close_map_is_exactly_as_specified(token, repository):
    assert RUNTIME_REPOSITORIES[token] == repository
    caps = _real(
        runtimes=(token,),
        bound_runtime=token,
        bound_runtime_source_url=(
            "https://github.com/" + repository + "/tree/" + _VLLM
        ),
    )
    assert caps.has_pinned_runtime_binding() is True
    assert evaluate(caps, TaskRequirements()) == ()


def test_j1_the_in_process_stub_token_has_no_official_repository():
    # It is not a public runtime, so an artifact-bearing descriptor claiming
    # it has nothing legitimate to point at.
    assert "in-process-stub" not in RUNTIME_REPOSITORIES
    caps = _real(
        runtimes=("in-process-stub",),
        bound_runtime="in-process-stub",
        bound_runtime_source_url=(
            "https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/tree/" + _VLLM
        ),
    )
    assert caps.has_pinned_runtime_binding() is False


def test_j1_a_labelled_sglang_tag_object_still_works():
    caps = _real(
        runtimes=("sglang",),
        bound_runtime="sglang",
        bound_runtime_version=_SGLANG_TAG,
        bound_runtime_object_kind="tag-object",
        bound_runtime_source_url=(
            "https://github.com/sgl-project/sglang/tree/" + _SGLANG_TAG
        ),
    )
    assert evaluate(caps, TaskRequirements()) == ()


# == J2 - full secret detection on every non-exempt component ================


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/" + _SECRET48 + "/vllm/tree/" + _VLLM,
        "https://github.com/vllm-project/" + _SECRET48 + "/tree/" + _VLLM,
        "https://github.com/" + _SECRET_B64 + "/vllm/tree/" + _VLLM,
    ],
)
def test_j2_a_long_opaque_secret_in_the_runtime_path_is_not_stored(url):
    """The named control: neither stored nor eligible."""
    caps = _real(bound_runtime_source_url=url)
    assert caps.bound_runtime_source_url == ""
    assert _SECRET48 not in repr(caps)
    assert _SECRET_B64 not in repr(caps)
    assert "bound-runtime-unpinned" in evaluate(caps, TaskRequirements())


@pytest.mark.parametrize(
    "url",
    [
        "https://huggingface.co/" + _SECRET48 + "/model/tree/" + _SHA,
        "https://huggingface.co/org/" + _SECRET48 + "/tree/" + _SHA,
    ],
)
def test_j2_a_long_opaque_secret_in_the_model_path_is_not_stored(url):
    caps = _real(provenance_url=url)
    assert caps.provenance_url == ""
    assert _SECRET48 not in repr(caps)
    assert "provenance-unpinned" in evaluate(caps, TaskRequirements())


def test_j2_the_exemption_covers_only_this_descriptors_own_object_ids():
    """A foreign 40-hex run is refused; only the descriptor's own is waived."""
    foreign = (
        "https://huggingface.co/" + _REPO + "/blob/" + _SHA + "/" + _FOREIGN_SHA
    )
    caps = _real(licence_source_url=foreign)
    assert caps.licence_source_url == ""
    own = "https://huggingface.co/" + _REPO + "/tree/" + _SHA
    assert _real(provenance_url=own).provenance_url == own


def test_j2_other_secret_rules_still_apply_to_an_exempt_component():
    # The waiver is for the long-run rule only. A component that equals the
    # revision cannot also be secret-shaped by some other rule, but the code
    # path that would allow it is asserted closed here.
    from scripts.open_model.redaction import has_credential_shape

    assert has_credential_shape(_SHA) is False
    assert has_credential_shape("sk-ABCDEFGH12345678") is True


# == J3 - a secret-bearing licence path is not stored ========================


def test_j3_a_secret_in_a_licence_file_path_is_not_stored():
    """The named control: not stored, even though routing would refuse it."""
    url = (
        "https://huggingface.co/"
        + _REPO
        + "/blob/"
        + _SHA
        + "/"
        + _SECRET48
        + ".md"
    )
    caps = _real(licence_source_url=url)
    assert caps.licence_source_url == ""
    assert _SECRET48 not in repr(caps)
    assert "licence-source-unpinned" in evaluate(caps, TaskRequirements())


def test_j3_a_secret_in_a_nested_licence_directory_is_not_stored():
    url = (
        "https://huggingface.co/"
        + _REPO
        + "/blob/"
        + _SHA
        + "/"
        + _SECRET48
        + "/LICENSE"
    )
    caps = _real(licence_source_url=url)
    assert caps.licence_source_url == ""
    assert _SECRET48 not in repr(caps)


# == J4 - percent-encoded components are refused =============================


@pytest.mark.parametrize(
    "suffix",
    [
        "/%2e%2e/%2e%2e/README.md",
        "/%2E%2E/README.md",
        "/%2e/README.md",
        "/sub%2fREADME.md",
        "/READ%00ME.md",
        "/READ%09ME.md",
        "/%252e%252e/README.md",
    ],
)
def test_j4_encoded_licence_paths_are_refused(suffix):
    url = "https://huggingface.co/" + _REPO + "/blob/" + _SHA + suffix
    caps = _real(licence_source_url=url)
    assert caps.licence_source_url == ""
    assert "licence-source-unpinned" in evaluate(caps, TaskRequirements())


@pytest.mark.parametrize(
    "url",
    [
        "https://huggingface.co/" + _REPO + "%2f..%2f/tree/" + _SHA,
        "https://huggingface.co%40evil.invalid/" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co/%2e%2e/" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co/org%2fmodel/tree/" + _SHA,
    ],
)
def test_j4_encoded_model_evidence_urls_are_refused(url):
    caps = _real(provenance_url=url)
    assert caps.provenance_url == ""
    assert "provenance-unpinned" in evaluate(caps, TaskRequirements())


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/vllm-project/vllm/tree/%2e%2e/" + _VLLM,
        "https://github.com%40evil.invalid/vllm-project/vllm/tree/" + _VLLM,
        "https://github.com/vllm-project%2fvllm/tree/" + _VLLM,
    ],
)
def test_j4_encoded_runtime_evidence_urls_are_refused(url):
    caps = _real(bound_runtime_source_url=url)
    assert caps.bound_runtime_source_url == ""
    assert "bound-runtime-unpinned" in evaluate(caps, TaskRequirements())


def test_j4_percent_is_refused_by_the_parser_and_by_paths():
    assert parse_https_url("https://huggingface.co/a/%2e%2e/b")[0] is False
    assert is_canonical_relative_path("%2e%2e/README.md") is False
    assert is_canonical_relative_path("a%2fb.gguf") is False


def test_j4_an_artifact_path_cannot_carry_encoded_traversal():
    caps = _real(artifact_path="%2e%2e/%2e%2e/etc/passwd")
    assert caps.artifact_path == ""
    assert caps.invalid_fields == ("artifact_path",)
    assert "descriptor-invalid" in evaluate(caps, TaskRequirements())


# == J5 - the round-two prose is qualified ===================================

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "OPEN_MODEL_INTEGRATION.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_j5_the_round_two_row_names_nim_as_unresolved_inline():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    stale = (
        "Every model, licence and runtime claim is bound to an exact "
        "repository plus an immutable commit"
    )
    assert stale not in flat
    assert "every runtime claim except NVIDIA NIM" in flat
    assert "NIM has no public git ref and remains UNRESOLVED" in flat


# == the catalogue still satisfies every tightened rule ======================


def test_catalogue_urls_survive_the_tightened_parser():
    for entry in CATALOGUE:
        assert entry.provenance_url, entry.model_id
        assert entry.licence_source_url, entry.model_id
        assert entry.has_pinned_provenance(), entry.model_id
        assert entry.has_pinned_licence(), entry.model_id


def test_catalogue_remains_inert():
    permissive = TaskRequirements(
        require_local=False,
        allowed_licence_classes=(
            "osi-open-source",
            "open-weight-restricted",
            "source-available",
            "proprietary-service",
        ),
    )
    assert sum(1 for e in CATALOGUE if not evaluate(e, permissive)) == 0
