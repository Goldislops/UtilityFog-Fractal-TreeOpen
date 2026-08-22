"""Regression tests for the OMI-V1 fourth independent-audit round.

Every control here reproduced against the code as it stood at `2a2db95`.

F1  artifact_path accepted URL schemes and silently collapsed traversal
F2  evidence URLs were bound by substring, not by structure
F3  a mutable tag name counted as an immutable runtime binding
F4  a missing bound runtime routed whenever the task did not narrow runtimes
F5  the in-process-stub exemption was a copyable field value
F6  surviving evidence prose overstated what was pinned

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.open_model.capabilities import (
    MODEL_EVIDENCE_HOST,
    RUNTIME_EVIDENCE_HOST,
    ModelCapabilities,
    is_canonical_relative_path,
    is_harness_double,
    is_official_evidence_url,
    parse_https_url,
    register_harness_double,
)
from scripts.open_model.catalogue import CATALOGUE, find
from scripts.open_model.evaluation import stub_capabilities
from scripts.open_model.routing import TaskRequirements, evaluate

_SECRET = "sk-ABCDEFGH12345678"
_BS = chr(92)
_SHA = "1504002f650e656a0a3789d99574df12e3e94ed0"
_VLLM = "6e448d0ea9bf3d88d898b65449ca6dc2aec170ac"
_REPO = "org/model"


def _real(model_id: str = _REPO, **overrides) -> ModelCapabilities:
    revision = overrides.get("repository_revision", _SHA)
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
    """Guard: without this, every negative below could pass for the wrong reason."""
    assert evaluate(_real(), TaskRequirements()) == ()


# == F1 - canonical repository-relative artifact identity ====================


@pytest.mark.parametrize(
    "supplied",
    [
        "https://evil.invalid/x.gguf",
        "http://evil.invalid/x.gguf",
        "file:///etc/passwd",
        "ftp://host/x.gguf",
        "../../etc/passwd",
        "sub/../../../etc/passwd",
        "./m.gguf",
        "../m.gguf",
        "sub/./m.gguf",
        "sub//m.gguf",
        "/absolute/m.gguf",
        "~/m.gguf",
        "C:/Users/kevin/m.gguf",
        "sub" + _BS + "m.gguf",
        _BS + _BS + "server" + _BS + "share",
        "user:pw@host/m.gguf",
        "m.gguf?token=" + _SECRET,
        "m.gguf#frag",
        "has space.gguf",
        "tab" + chr(9) + ".gguf",
        "null" + chr(0) + ".gguf",
        _SECRET,
        7,
        None,
        b"m.gguf",
        "x" * 400,
    ],
)
def test_f1_non_canonical_artifact_paths_are_rejected(supplied):
    assert is_canonical_relative_path(supplied) is False
    caps = _real(artifact_path=supplied)
    assert caps.artifact_path == ""
    assert caps.invalid_fields == ("artifact_path",)


@pytest.mark.parametrize(
    "supplied",
    [
        "m.gguf",
        "sub/dir/model-00001-of-00004.safetensors",
        "a.bin",
        "granite-4.1-8b-Q4_K_M.gguf",
        "NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf",
    ],
)
def test_f1_canonical_artifact_paths_survive(supplied):
    caps = _real(artifact_path=supplied, artifact_digest="sha256:" + "ab" * 32)
    assert caps.artifact_path == supplied
    assert caps.invalid_fields == ()


# == F2 - a rejected path must not collapse into the commit fallback =========


def test_f2_a_rejected_path_blocks_instead_of_collapsing():
    """The named control: reject, then route via the repository-commit pin."""
    caps = _real(
        artifact_path="../../etc/passwd", artifact_digest="sha256:" + "ab" * 32
    )
    assert caps.artifact_path == ""
    # The commit-id tree pin is still satisfied, which is exactly why the
    # collapse was dangerous: byte-pinning succeeds and hides the rejection.
    assert caps.is_byte_pinned() is True
    assert "descriptor-invalid" in evaluate(caps, TaskRequirements())


def test_f2_an_empty_path_is_not_an_invalid_path():
    # Claiming no file at all remains legitimate; only a supplied-and-unusable
    # path invalidates.
    caps = _real(artifact_path="")
    assert caps.invalid_fields == ()
    assert evaluate(caps, TaskRequirements()) == ()


# == F3 - structural evidence-URL parsing ====================================


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/?x=huggingface.co/" + _REPO + "/tree/" + _SHA,
        "https://evil.invalid/huggingface.co/" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co@evil.invalid/" + _REPO + "/tree/" + _SHA,
        "https://user:pw@huggingface.co/" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co.evil.invalid/" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co:8443/" + _REPO + "/tree/" + _SHA,
        "https://HuggingFace.co/" + _REPO + "/tree/" + _SHA,
        "http://huggingface.co/" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co/" + _REPO + "/tree/" + _SHA + "#frag",
        "https://huggingface.co/" + _REPO + "/tree/" + _SHA + "/extra",
        "https://huggingface.co/other/repo/tree/" + _SHA,
        "https://huggingface.co/" + _REPO + "/tree/main",
        "https://huggingface.co/" + _REPO,
        "https://huggingface.co//" + _REPO + "/tree/" + _SHA,
        "https://huggingface.co/" + _REPO + "/../evil/tree/" + _SHA,
        "",
        None,
        7,
    ],
)
def test_f3_spoofed_or_non_canonical_provenance_is_refused(url):
    assert "provenance-unpinned" in evaluate(
        _real(provenance_url=url), TaskRequirements()
    )


def test_f3_secret_bearing_query_is_refused():
    """A credential smuggled in a query string must not be stored or accepted."""
    url = "https://huggingface.co/" + _REPO + "/tree/" + _SHA + "?token=" + _SECRET
    caps = _real(provenance_url=url)
    assert "provenance-unpinned" in evaluate(caps, TaskRequirements())
    assert _SECRET not in repr(caps)


def test_f3_secret_bearing_licence_query_is_refused():
    url = (
        "https://huggingface.co/"
        + _REPO
        + "/blob/"
        + _SHA
        + "/README.md?key="
        + _SECRET
    )
    caps = _real(licence_source_url=url)
    assert "licence-source-unpinned" in evaluate(caps, TaskRequirements())
    assert _SECRET not in repr(caps)


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://huggingface.co/a/b", True),
        ("https://huggingface.co", True),
        ("https://user@huggingface.co/a", False),
        ("https://huggingface.co:443/a", False),
        ("https://huggingface.co/a?x=1", False),
        ("https://huggingface.co/a#f", False),
        ("https://huggingface.co/a/../b", False),
        ("https://huggingface.co/a//b", False),
        ("http://huggingface.co/a", False),
        ("https://HUGGINGFACE.co/a", False),
    ],
)
def test_f3_url_parser_behaviour(url, ok):
    assert parse_https_url(url)[0] is ok


def test_f3_official_evidence_url_is_exact_not_substring():
    good = "https://huggingface.co/" + _REPO + "/tree/" + _SHA
    assert is_official_evidence_url(
        good, host=MODEL_EVIDENCE_HOST, repository=_REPO, revision=_SHA, kind="tree"
    )
    assert not is_official_evidence_url(
        good + "/x",
        host=MODEL_EVIDENCE_HOST,
        repository=_REPO,
        revision=_SHA,
        kind="tree",
    )


# == F4 - immutable runtime evidence =========================================


@pytest.mark.parametrize(
    "overrides",
    [
        {"bound_runtime_version": "v0.27.1",
         "bound_runtime_source_url": "https://github.com/vllm-project/vllm/tree/v0.27.1"},
        {"bound_runtime_version": "main",
         "bound_runtime_source_url": "https://github.com/vllm-project/vllm/tree/main"},
        {"bound_runtime_version": "latest",
         "bound_runtime_source_url": "https://github.com/vllm-project/vllm/tree/latest"},
        {"bound_runtime_object_kind": ""},
        {"bound_runtime_object_kind": "branch"},
        {"bound_runtime_source_url": "https://evil.invalid/tree/" + _VLLM},
        {"bound_runtime_source_url": "https://github.com@evil.invalid/tree/" + _VLLM},
        {"bound_runtime_source_url": "https://github.com/vllm-project/vllm"},
        {"bound_runtime_source_url": "https://github.com/vllm-project/vllm/tree/" + _VLLM + "?k=" + _SECRET},
    ],
)
def test_f4_mutable_or_unofficial_runtime_evidence_is_refused(overrides):
    assert "bound-runtime-unpinned" in evaluate(
        _real(**overrides), TaskRequirements()
    )


def test_f4_a_labelled_tag_object_is_accepted():
    tag_object = "ff4c6e641d9f9bb174d34ff651c01c114aea8e40"
    caps = _real(
        runtimes=("sglang",),
        bound_runtime="sglang",
        bound_runtime_version=tag_object,
        bound_runtime_object_kind="tag-object",
        bound_runtime_source_url=(
            "https://github.com/sgl-project/sglang/tree/" + tag_object
        ),
    )
    assert caps.has_pinned_runtime_binding() is True
    assert evaluate(caps, TaskRequirements()) == ()


def test_f4_runtime_evidence_host_is_closed():
    assert RUNTIME_EVIDENCE_HOST == "github.com"
    assert MODEL_EVIDENCE_HOST == "huggingface.co"


# == F5 - bound runtime required under DEFAULT requirements ==================


def test_f5_missing_bound_runtime_blocks_even_with_no_runtime_constraint():
    """The named control: default requirements do not narrow runtimes."""
    requirements = TaskRequirements()
    assert requirements.allowed_runtimes == ()
    caps = _real(
        bound_runtime="",
        bound_runtime_version="",
        bound_runtime_object_kind="",
        bound_runtime_source_url="",
    )
    assert "bound-runtime-unspecified" in evaluate(caps, requirements)


def test_f5_no_catalogue_entry_routes_under_default_requirements():
    for entry in CATALOGUE:
        assert "bound-runtime-unspecified" in evaluate(entry, TaskRequirements())


# == F6 - the stub exemption is a construction path, not a field =============


def test_f6_an_external_descriptor_claiming_the_stub_runtime_gets_full_gates():
    """The named control: copying the stub fields must not buy an exemption."""
    external = ModelCapabilities(
        model_id="x/y",
        variant_id="in-process-double",
        repository_revision="repo-local-double",
        runtimes=("in-process-stub",),
        bound_runtime="in-process-stub",
        bound_runtime_version="repo-local-double",
        locality="local",
        availability="present",
        resource_class="light",
        structured_output="supported",
        tool_calling="supported",
        max_context_tokens=8192,
        licence_class="osi-open-source",
        licence_source_url="https://evil.invalid/licence",
        licence_revision="1.0",
    )
    assert is_harness_double(external) is False
    assert external.is_artifact_bearing() is True
    reasons = evaluate(external, TaskRequirements())
    assert "repository-revision-not-immutable" in reasons
    assert "provenance-unpinned" in reasons
    assert "licence-source-unpinned" in reasons
    assert "artifact-unpinned" in reasons


def test_f6_an_exact_value_copy_of_a_real_double_is_not_exempt():
    genuine = stub_capabilities("double")
    copy = ModelCapabilities(
        model_id=genuine.model_id,
        variant_id=genuine.variant_id,
        repository_revision=genuine.repository_revision,
        locality=genuine.locality,
        availability=genuine.availability,
        resource_class=genuine.resource_class,
        structured_output=genuine.structured_output,
        tool_calling=genuine.tool_calling,
        max_context_tokens=genuine.max_context_tokens,
        max_output_tokens=genuine.max_output_tokens,
        runtimes=genuine.runtimes,
        bound_runtime=genuine.bound_runtime,
        bound_runtime_version=genuine.bound_runtime_version,
        bound_runtime_source_url=genuine.bound_runtime_source_url,
        licence_class=genuine.licence_class,
        licence_name=genuine.licence_name,
        licence_source_url=genuine.licence_source_url,
        licence_revision=genuine.licence_revision,
    )
    # Value-equal, yet not exempt: membership is by identity.
    assert copy == genuine
    assert is_harness_double(genuine) is True
    assert is_harness_double(copy) is False
    assert evaluate(genuine, TaskRequirements()) == ()
    assert evaluate(copy, TaskRequirements()) != ()


def test_f6_the_exemption_survives_only_for_the_object_handed_out():
    caps = stub_capabilities("double")
    assert is_harness_double(caps) is True
    assert is_harness_double(ModelCapabilities(model_id="unrelated")) is False


def test_f6_register_harness_double_refuses_a_subclass():
    class Sneaky(ModelCapabilities):
        pass

    with pytest.raises(TypeError):
        register_harness_double(Sneaky(model_id="x/y"))


def test_f6_the_closed_construction_path_has_exactly_one_caller():
    """A second call site would widen the exemption; this keeps it greppable."""
    root = pathlib.Path(__file__).resolve().parents[1]
    callers = []
    for path in sorted((root / "scripts" / "open_model").glob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").split("\n"), 1
        ):
            if "register_harness_double(" in line and "def " not in line:
                callers.append((path.name, number))
    assert [name for name, _ in callers] == ["evaluation.py"], callers


# == F7 - evidence prose =====================================================

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "OPEN_MODEL_INTEGRATION.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_f7_no_surviving_all_runtimes_pinned_claim():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    assert "Every runtime claim above is pinned" not in flat
    assert "every runtime claim is now pinned to a version, an immutable commit" not in flat
    assert "UNRESOLVED" in flat


def test_f7_catalogue_gemma_note_retracts_the_policy_claim():
    entry = find("google/gemma-4-12B-it")
    assert entry is not None
    assert "retracted" in entry.licence_notes
    assert "references NO prohibited-use policy" in entry.licence_notes


def test_f7_catalogue_llama_note_records_the_literal_gated_value():
    entry = find("meta-llama/Llama-4-Scout-17B-16E-Instruct")
    assert entry is not None
    assert "manual" in entry.licence_notes
    assert "gated=true" not in entry.licence_notes


def test_f7_catalogue_evidence_urls_pass_the_structural_parser():
    for entry in CATALOGUE:
        assert entry.has_pinned_provenance(), entry.model_id
        assert entry.has_pinned_licence(), entry.model_id
