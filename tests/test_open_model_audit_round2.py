"""Regression tests for the OMI-V1 second independent-audit round.

One section per finding. Every negative control here reproduced against the
code as it stood before the correction.

R1  invalid allowed_runtimes normalized to the empty "no constraint" state
R2  registry names and persisted refusal reasons could carry arbitrary text
R3  a real 40-character repository SHA was rejected as secret-shaped
R4  the digest requirement keyed off quantisation, exempting BF16/safetensors
R5  claims were bound to mutable branch URLs, and GLM FP8 to the wrong repo
R6  three renderings of one vendor document were called independent evidence
R7  routing.py still carried an absolute locality claim
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.agent_backends.base import AgentBackend, AgentResponse, TextBlock
from scripts.open_model.capabilities import ModelCapabilities
from scripts.open_model.catalogue import CATALOGUE, find
from scripts.open_model.evaluation import EvaluationCase, run_case
from scripts.open_model.redaction import (
    CONSTRUCTION_REFUSAL_REASONS,
    REGISTRATION_REFUSAL_REASONS,
    is_commit_revision,
    is_safe_revision,
)
from scripts.open_model.registry import (
    BackendRegistry,
    BackendUnavailable,
    RegistrationRefused,
)
from scripts.open_model.routing import (
    NO_ELIGIBLE_BACKEND,
    TaskRequirements,
    evaluate,
    route,
)

_SECRET = "sk-ABCDEFGH12345678"
_PATH = "C:" + chr(92) + "Users" + chr(92) + "kevin" + chr(92) + "creds.txt"
_REAL_SHA = "1504002f650e656a0a3789d99574df12e3e94ed0"


def _pinned(model_id: str = "m", **overrides) -> ModelCapabilities:
    base = dict(
        model_id=model_id,
        variant_id="bf16",
        repository_revision=_REAL_SHA,
        licence_source_url="https://example.invalid/licence",
        licence_revision="1.0",
        locality="local",
        availability="present",
        resource_class="light",
        structured_output="supported",
        tool_calling="supported",
        max_context_tokens=8192,
        runtimes=("in-process-stub",),
        licence_class="osi-open-source",
    )
    base.update(overrides)
    return ModelCapabilities(**base)  # type: ignore[arg-type]


_REAL_REPO = "org/model"


def _real(**overrides) -> ModelCapabilities:
    """An artifact-bearing descriptor with complete immutable provenance."""
    base = dict(
        model_id=_REAL_REPO,
        variant_id="bf16",
        repository_revision=_REAL_SHA,
        provenance_url="https://huggingface.co/%s/tree/%s" % (_REAL_REPO, _REAL_SHA),
        licence_source_url=(
            "https://huggingface.co/%s/blob/%s/README.md" % (_REAL_REPO, _REAL_SHA)
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
        bound_runtime_source_url="https://github.com/vllm-project/vllm/tree/6e448d0ea9bf3d88d898b65449ca6dc2aec170ac",
        licence_class="osi-open-source",
    )
    base.update(overrides)
    return ModelCapabilities(**base)  # type: ignore[arg-type]


# == R1 - an invalid runtime constraint must never widen the constraint ======


@pytest.mark.parametrize(
    "supplied",
    [
        ("ollama-v2",),          # typo / stale name
        ("unknown",),            # explicitly non-allow-listable
        ("ollama", 7),           # wrong element type
        ("ollama", None),
        "ollama",                # not a sequence at all
        ("ollama",) * 20,        # over the item limit
        ("OLLAMA",),             # wrong case is not the same token
    ],
)
def test_r1_invalid_allowed_runtimes_is_requirements_invalid(supplied):
    requirements = TaskRequirements(allowed_runtimes=supplied)  # type: ignore[arg-type]
    assert "allowed_runtimes" in requirements.malformed_fields
    assert "requirements-invalid" in evaluate(_pinned(), requirements)


def test_r1_an_invalid_constraint_never_becomes_no_constraint():
    """The exact failure: a narrowing instruction becoming a widening one."""
    registry = BackendRegistry(allowed_names=("stub",))
    registry.register(
        "stub",
        _pinned("stub"),
        lambda: _Double(),
        locality_attestation="operator-asserted",
    )
    # The caller meant to restrict to ollama and mistyped it. Before the
    # correction this filtered to (), which means "no runtime constraint",
    # and the in-process-stub backend was selected.
    decision = route(registry, TaskRequirements(allowed_runtimes=("ollama-v2",)))
    assert decision.outcome == NO_ELIGIBLE_BACKEND
    assert decision.selected is None
    assert decision.escalation == ("requirements-invalid",)


def test_r1_a_valid_runtime_constraint_still_works():
    requirements = TaskRequirements(allowed_runtimes=("ollama", "vllm"))
    assert requirements.malformed_fields == ()
    assert requirements.allowed_runtimes == ("ollama", "vllm")


def test_r1_an_explicitly_empty_constraint_is_still_honoured_as_no_constraint():
    requirements = TaskRequirements(allowed_runtimes=())
    assert requirements.malformed_fields == ()
    assert evaluate(_pinned(), requirements) == ()


def test_r1_duplicates_are_not_malformed():
    requirements = TaskRequirements(allowed_runtimes=("ollama", "ollama"))
    assert requirements.malformed_fields == ()
    assert requirements.allowed_runtimes == ("ollama",)


@pytest.mark.parametrize(
    "supplied", [("nonsense",), ("unknown",), ("osi-open-source", 7), "osi-open-source"]
)
def test_r1_invalid_allowed_licence_classes_is_also_requirements_invalid(supplied):
    requirements = TaskRequirements(allowed_licence_classes=supplied)  # type: ignore[arg-type]
    assert "allowed_licence_classes" in requirements.malformed_fields
    assert "requirements-invalid" in evaluate(_pinned(), requirements)


# == R2 - names and persisted refusal reasons =================================


class _Double(AgentBackend):
    name = "double"

    def complete(self, messages, tools, *, system=None, max_tokens=2048, temperature=0.0):
        return AgentResponse.from_content([TextBlock(text='{"a": 1}')])


@pytest.mark.parametrize(
    "name", [_SECRET, _PATH, "a@b.com", "has space", "x" * 200, "", 7, None, "-leading"]
)
def test_r2_unsafe_registry_names_are_refused(name):
    registry = BackendRegistry(allowed_names=("ok",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register(
            name, _pinned(), _Double, locality_attestation="operator-asserted"
        )
    assert excinfo.value.reason == "name-not-safe-token"
    assert _SECRET not in str(excinfo.value)


@pytest.mark.parametrize("name", [_SECRET, _PATH, "a@b.com", "has space", 7, None])
def test_r2_unsafe_names_never_enter_the_allowlist(name):
    registry = BackendRegistry(allowed_names=("ok", name))
    assert registry.allowed_names == ("ok",)


def test_r2_an_operator_factory_cannot_write_free_text_into_a_record():
    """A factory raising BackendUnavailable with arbitrary text."""

    def hostile_factory():
        raise BackendUnavailable(f"failed talking to {_PATH} using {_SECRET}")

    registry = BackendRegistry(allowed_names=("hostile",))
    registry.register(
        "hostile", _pinned(), hostile_factory, locality_attestation="operator-asserted"
    )
    record = run_case(
        registry,
        EvaluationCase(
            case_id="hostile-refusal",
            requirements=TaskRequirements(),
            expected_construction_refused="invalid-reason",
        ),
    )
    assert record.construction_refused == "invalid-reason"
    rendered = repr(record)
    assert _SECRET not in rendered
    assert "Users" not in rendered
    assert record.passed is True


def test_r2_refusal_reasons_are_closed_at_the_exception_constructor():
    # Not merely at this module's call sites: an operator raises these too.
    hostile = BackendUnavailable(_SECRET)
    assert hostile.reason == "invalid-reason"
    assert str(hostile) == "invalid-reason"
    assert _SECRET not in repr(hostile.args)

    registration = RegistrationRefused(_PATH)
    assert registration.reason == "invalid-reason"
    assert str(registration) == "invalid-reason"


@pytest.mark.parametrize("reason", sorted(CONSTRUCTION_REFUSAL_REASONS))
def test_r2_genuine_construction_reasons_survive(reason):
    assert BackendUnavailable(reason).reason == reason


@pytest.mark.parametrize("reason", sorted(REGISTRATION_REFUSAL_REASONS))
def test_r2_genuine_registration_reasons_survive(reason):
    assert RegistrationRefused(reason).reason == reason


def test_r2_every_reason_this_module_raises_is_in_its_vocabulary():
    # A code added at a call site but not to the vocabulary would silently
    # degrade to invalid-reason; this keeps the two in step.
    registry = BackendRegistry(allowed_names=("gone",))
    registry.register(
        "gone",
        _pinned(availability="absent"),
        _Double,
        locality_attestation="operator-asserted",
    )
    with pytest.raises(BackendUnavailable) as excinfo:
        registry.create("gone")
    assert excinfo.value.reason == "availability-not-present"


# == R3 - real repository SHAs must be accepted ==============================


@pytest.mark.parametrize(
    "revision",
    [
        _REAL_SHA,
        "0" * 40,
        "f" * 40,
        "a" * 64,          # SHA-256 object format
        "865b82c2e7970d82e3731278c88c57ae7138359c",
    ],
)
def test_r3_full_commit_ids_are_accepted(revision):
    """The regression: the long-opaque-run secret rule ate real git SHAs."""
    assert is_commit_revision(revision) is True
    assert is_safe_revision(revision) is True
    assert ModelCapabilities(
        model_id="a/b", repository_revision=revision
    ).repository_revision == revision


@pytest.mark.parametrize(
    "revision",
    [
        "A" * 40,          # uppercase hex is not the canonical form
        "z" * 40,          # not hex
        "1" * 39,          # wrong length
        "1" * 41,
        "1" * 63,
        _PATH,
        7,
        None,
    ],
)
def test_r3_non_commit_shapes_are_not_treated_as_commit_ids(revision):
    assert is_commit_revision(revision) is False


def test_r3_tag_shaped_revisions_are_still_accepted():
    for tag in ("v1.2.1", "main", "refs/tags/v0.5.18", "repo-local-double"):
        assert is_safe_revision(tag) is True


def test_r3_a_symbolic_revision_is_not_a_byte_pin():
    # Accepted as an identifier, but a branch can move after review.
    caps = _pinned(repository_revision="main", runtimes=("vllm",))
    assert caps.repository_revision == "main"
    assert caps.is_byte_pinned() is False
    assert "artifact-unpinned" in evaluate(caps, TaskRequirements())


def test_r3_a_path_still_cannot_ride_in_as_a_revision():
    assert ModelCapabilities(
        model_id="a/b", repository_revision=_PATH
    ).repository_revision == ""


# == R4 - digests are required for artifact-bearing variants =================


def test_r4_a_non_quantised_named_file_still_needs_a_digest():
    """The finding: the requirement used to key off quantisation."""
    caps = _pinned(
        runtimes=("vllm",),
        repository_revision="main",
        artifact_path="model-00001-of-00004.safetensors",
        quantisation="",
    )
    assert "artifact-digest-missing" in evaluate(caps, TaskRequirements())


def test_r4_an_artifact_bearing_variant_must_be_byte_pinned_somehow():
    caps = _pinned(runtimes=("vllm",), repository_revision="v1.0")
    assert caps.is_artifact_bearing() is True
    assert caps.is_byte_pinned() is False
    assert "artifact-unpinned" in evaluate(caps, TaskRequirements())


def test_r4_a_full_commit_id_pins_a_sharded_variant():
    caps = _real()
    assert caps.is_byte_pinned() is True
    assert evaluate(caps, TaskRequirements()) == ()


def test_r4_a_named_file_plus_digest_pins_a_single_file_variant():
    caps = _real(artifact_path="m.gguf", artifact_digest="sha256:" + "ab" * 32)
    assert caps.is_byte_pinned() is True
    assert evaluate(caps, TaskRequirements()) == ()


def test_r4_the_in_process_double_bears_no_artifact():
    caps = _pinned(runtimes=("in-process-stub",), repository_revision="repo-local")
    assert caps.is_artifact_bearing() is False
    assert "artifact-unpinned" not in evaluate(caps, TaskRequirements())


def test_r4_every_catalogue_entry_is_byte_pinned():
    for entry in CATALOGUE:
        assert entry.is_byte_pinned(), entry.model_id


def test_r4_single_file_catalogue_entries_carry_a_real_digest():
    with_paths = [e for e in CATALOGUE if e.artifact_path]
    assert len(with_paths) >= 3
    for entry in with_paths:
        assert entry.artifact_digest.startswith("sha256:")
        assert len(entry.artifact_digest) == len("sha256:") + 64


# == R5 - immutable binding to the exact repository ==========================


def test_r5_every_catalogue_url_is_pinned_to_its_own_revision():
    for entry in CATALOGUE:
        assert entry.repository_revision in entry.provenance_url, entry.model_id
        assert entry.repository_revision in entry.licence_source_url, entry.model_id
        # A branch URL would silently change under a reviewer.
        assert "/main/" not in entry.licence_source_url
        assert "/tree/main" not in entry.provenance_url


def test_r5_every_catalogue_url_points_at_its_own_repository():
    for entry in CATALOGUE:
        assert entry.model_id in entry.provenance_url, entry.model_id
        assert entry.model_id in entry.licence_source_url, entry.model_id


def test_r5_the_glm_row_binds_to_the_fp8_repository():
    """The specific mis-binding the audit caught."""
    entry = find("zai-org/GLM-5.2-FP8")
    assert entry is not None
    assert entry.variant_id == "fp8"
    assert "GLM-5.2-FP8/tree/" in entry.provenance_url
    assert "GLM-5.2-FP8/blob/" in entry.licence_source_url
    # and no row silently stands in for it under the non-FP8 id
    assert find("zai-org/GLM-5.2") is None


def test_r5_revisions_are_full_commit_ids_not_tags():
    for entry in CATALOGUE:
        assert is_commit_revision(entry.repository_revision), entry.model_id


# == R6 and R7 - documented claims ===========================================

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "OPEN_MODEL_INTEGRATION.md"
_ROUTING = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "open_model"
    / "routing.py"
)


def test_r6_three_renderings_are_not_called_independent_evidence():
    lowered = _flat(_DOC.read_text(encoding="utf-8")).lower()
    assert "three independent official sources" not in lowered
    assert "mechanically corroborating" in lowered
    assert "single primary source" in lowered


def _flat(text: str) -> str:
    """Collapse whitespace so a wrapped docstring still matches a phrase."""
    return " ".join(text.split())


def test_r7_routing_carries_no_absolute_locality_claim():
    source = _flat(_ROUTING.read_text(encoding="utf-8"))
    banned = "no path by which a task requiring local execution can be served"
    assert banned not in source
    assert "cannot establish where a backend will actually execute" in source
    assert "remains undetectable" in source
