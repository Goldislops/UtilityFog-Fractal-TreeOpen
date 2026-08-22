"""Regression tests for the OMI-V1 independent-audit findings.

One section per finding, each asserting the corrected behaviour and - where
the finding was about an over-claim rather than a bug - asserting the shape
of the bound that replaced it.

Finding 1  locality guarantee was over-claimed
Finding 2  diagnostic and evaluation records retained arbitrary text
Finding 3  malformed min_context_tokens failed open
Finding 4  model provenance was absent and variants were collapsed
Finding 5  Ollama tool_choice claim challenged; re-verified and pinned
Finding 6  every finding above carries a regression test (this file)
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.agent_backends.base import AgentBackend, AgentResponse, TextBlock
from scripts.open_model.capabilities import ModelCapabilities
from scripts.open_model.catalogue import CATALOGUE, find
from scripts.open_model.evaluation import (
    EvaluationCase,
    scripted_stub,
    stub_capabilities,
)
from scripts.open_model.redaction import (
    INVALID_IDENTIFIER,
    REDACTED_SECRET,
    DiagnosticRecord,
    is_safe_token,
)
from scripts.open_model.registry import (
    BackendRegistry,
    BackendUnavailable,
    RegistrationRefused,
    detect_endpoint_host,
)
from scripts.open_model.registry import _host_of, _is_loopback
from scripts.open_model.routing import (
    ESCALATION_REASONS,
    NO_ELIGIBLE_BACKEND,
    EscalationReason,
    TaskRequirements,
    evaluate,
    route,
)
from scripts.open_model.structured import validate_structured_output


def _pinned(model_id: str = "org/model", **overrides) -> ModelCapabilities:
    """A fully-pinned, fully-satisfying descriptor."""
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


class _EndpointBackend(AgentBackend):
    """A double that advertises an endpoint, the way a real client does."""

    name = "endpoint-double"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def complete(self, messages, tools, *, system=None, max_tokens=2048, temperature=0.0):
        return AgentResponse.from_content([TextBlock(text="{}")])


class _OpaqueBackend(AgentBackend):
    """A double that exposes no endpoint at all - the undetectable case."""

    name = "opaque-double"

    def complete(self, messages, tools, *, system=None, max_tokens=2048, temperature=0.0):
        return AgentResponse.from_content([TextBlock(text="{}")])


# == Finding 1 - the locality guarantee ======================================


def test_finding1_a_local_descriptor_bound_to_a_remote_factory_is_refused():
    """The adversarial mismatch the audit described, now caught."""
    registry = BackendRegistry(allowed_names=("sneaky",))
    registry.register(
        "sneaky",
        _pinned("m", locality="local"),
        lambda: _EndpointBackend("https://api.paid-vendor.invalid/v1"),
        locality_attestation="operator-asserted",
    )
    # Routing still selects it - routing reads the descriptor, and the
    # descriptor says local. Construction is where the lie is caught.
    decision = route(registry, TaskRequirements(require_local=True))
    assert decision.selected == "sneaky"
    with pytest.raises(BackendUnavailable) as excinfo:
        registry.create("sneaky")
    assert excinfo.value.reason == "locality-mismatch-detected"


def test_finding1_a_loopback_endpoint_under_a_local_claim_is_accepted():
    registry = BackendRegistry(allowed_names=("local-server",))
    registry.register(
        "local-server",
        _pinned("m", locality="local"),
        lambda: _EndpointBackend("http://127.0.0.1:11434/v1"),
        locality_attestation="operator-asserted",
    )
    assert isinstance(registry.create("local-server"), AgentBackend)


def test_finding1_a_local_claim_requires_an_explicit_operator_attestation():
    registry = BackendRegistry(allowed_names=("unattested",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register("unattested", _pinned("m", locality="local"), _OpaqueBackend)
    assert excinfo.value.reason == "locality-attestation-required"


def test_finding1_an_attestation_cannot_be_attached_to_a_non_local_claim():
    registry = BackendRegistry(allowed_names=("remote",))
    with pytest.raises(RegistrationRefused) as excinfo:
        registry.register(
            "remote",
            _pinned("m", locality="remote"),
            _OpaqueBackend,
            locality_attestation="operator-asserted",
        )
    assert excinfo.value.reason == "locality-attestation-not-applicable"


def test_finding1_the_residual_boundary_is_real_and_named_not_hidden():
    """The bounded case, asserted rather than glossed.

    A backend that exposes no endpoint cannot be checked. It is admitted on
    the operator's attestation alone. This test exists so that the limit is
    visible in the suite rather than only in a docstring.
    """
    registry = BackendRegistry(allowed_names=("opaque",))
    registry.register(
        "opaque",
        _pinned("m", locality="local"),
        _OpaqueBackend,
        locality_attestation="operator-asserted",
    )
    assert detect_endpoint_host(_OpaqueBackend()) == ""
    assert isinstance(registry.create("opaque"), AgentBackend)
    assert registry.attestation_for("opaque") == "operator-asserted"


@pytest.mark.parametrize(
    "url,host",
    [
        ("https://api.openai.com/v1", "api.openai.com"),
        ("http://127.0.0.1:11434/v1", "127.0.0.1"),
        ("http://user:pw@evil.invalid:8080/v1", "evil.invalid"),
        ("http://[::1]:8080/v1", "[::1]"),
        ("localhost:11434", "localhost"),
    ],
)
def test_finding1_host_extraction(url, host):
    assert _host_of(url) == host


@pytest.mark.parametrize(
    "host,loopback",
    [
        ("127.0.0.1", True),
        ("127.13.9.2", True),
        ("localhost", True),
        ("app.localhost", True),
        ("[::1]", True),
        ("0.0.0.0", False),
        ("api.openai.com", False),
        ("10.0.0.5", False),
    ],
)
def test_finding1_loopback_classification(host, loopback):
    # 0.0.0.0 means every interface, which is the opposite of loopback.
    assert _is_loopback(host) is loopback


def test_finding1_detects_the_endpoint_of_the_repositorys_real_backend():
    """The concrete case this detector exists for."""
    pytest.importorskip("openai")
    from scripts.agent_backends.openai_compat_backend import OpenAICompatBackend

    remote = OpenAICompatBackend(
        base_url="https://api.paid-vendor.invalid/v1", model="x", api_key="k"
    )
    assert detect_endpoint_host(remote) == "api.paid-vendor.invalid"
    local = OpenAICompatBackend(
        base_url="http://127.0.0.1:11434/v1", model="x", api_key="k"
    )
    assert _is_loopback(detect_endpoint_host(local))


# == Finding 2 - records must not retain arbitrary text ======================

_SECRET = "sk-ABCDEFGH12345678"
_PATH = "C:" + chr(92) + "Users" + chr(92) + "kevin" + chr(92) + "secrets.txt"


def test_finding2_event_is_a_closed_vocabulary():
    assert DiagnosticRecord(event="route-selected").event == "route-selected"
    leaked = DiagnosticRecord(event=f"failed with {_SECRET}")
    assert leaked.event == "invalid-event"
    assert _SECRET not in repr(leaked)


def test_finding2_backend_must_be_a_safe_identifier():
    assert DiagnosticRecord(event="route-refused", backend="light").backend == "light"
    for hostile in (_SECRET, _PATH, "a@b.com", "has space", "x" * 500, 7, None):
        record = DiagnosticRecord(event="route-refused", backend=hostile)
        assert record.backend == INVALID_IDENTIFIER
        assert _SECRET not in repr(record)


def test_finding2_reasons_are_dropped_unless_in_the_closed_vocabulary():
    record = DiagnosticRecord(
        event="route-refused",
        reasons=("licence-unknown", f"note {_SECRET}", "made-up-reason", 7),
    )
    assert record.reasons == ("licence-unknown",)
    assert _SECRET not in repr(record)


def test_finding2_escalation_literal_and_runtime_vocabulary_agree():
    from typing import get_args

    assert set(get_args(EscalationReason)) == ESCALATION_REASONS


def test_finding2_case_id_must_be_a_safe_token():
    assert EvaluationCase(case_id="ok-1", requirements=TaskRequirements()).case_id
    for hostile in (_SECRET, _PATH, "a@b.com", "has space", "", 7, None):
        with pytest.raises(ValueError):
            EvaluationCase(case_id=hostile, requirements=TaskRequirements())


def test_finding2_unsafe_required_keys_fail_closed_instead_of_being_dropped():
    """The dangerous half of this finding: a dropped key is a false pass."""
    outcome = validate_structured_output(
        '{"summary": "ok"}', required_keys=("summary", _SECRET)
    )
    assert outcome.ok is False
    assert outcome.failure == "required-key-not-safe"
    assert _SECRET not in repr(outcome)


@pytest.mark.parametrize(
    "keys", [("has space",), ("a@b.com",), ("x" * 200,), (7,), "notatuple", (None,)]
)
def test_finding2_malformed_required_keys_are_refused(keys):
    outcome = validate_structured_output('{"a": 1}', required_keys=keys)
    assert outcome.ok is False
    assert outcome.failure == "required-key-not-safe"


def test_finding2_missing_keys_are_indices_never_text():
    outcome = validate_structured_output(
        '{"a": 1}', required_keys=("a", "b", "c")
    )
    assert outcome.missing_key_indices == (1, 2)
    rendered = repr(outcome)
    assert "'b'" not in rendered and '"b"' not in rendered


def test_finding2_indices_map_onto_the_callers_tuple_without_dedup_shift():
    keys = ("a", "a", "z")
    outcome = validate_structured_output('{"a": 1}', required_keys=keys)
    assert outcome.missing_key_indices == (2,)
    assert keys[2] == "z"


def test_finding2_safe_token_rejects_secret_shapes_despite_a_legal_charset():
    # sk-... is letters, digits and hyphens: legal by charset, refused by the
    # redaction cross-check. That cross-check is the point of the gate.
    assert is_safe_token("granite-4.1-8b") is True
    assert is_safe_token("tool_calls") is True
    assert is_safe_token(_SECRET) is False


# == Finding 3 - malformed min_context_tokens must fail closed ===============


@pytest.mark.parametrize(
    "supplied", [-1, -32768, 1.5, "8192", True, None, object()]
)
def test_finding3_malformed_min_context_is_recorded_as_malformed(supplied):
    requirements = TaskRequirements(min_context_tokens=supplied)
    assert "min_context_tokens" in requirements.malformed_fields


def test_finding3_a_malformed_minimum_cannot_select_a_one_token_backend():
    """The exact failure the audit described."""
    registry = BackendRegistry(allowed_names=("tiny",))
    registry.register(
        "tiny",
        _pinned("tiny", max_context_tokens=1),
        scripted_stub(['{"a": 1}']),
        locality_attestation="operator-asserted",
    )
    # A caller who meant "at least 32768" but wrote it wrongly.
    decision = route(registry, TaskRequirements(min_context_tokens=-32768))
    assert decision.outcome == NO_ELIGIBLE_BACKEND
    assert decision.selected is None
    assert decision.escalation == ("requirements-invalid",)


def test_finding3_a_wellformed_minimum_still_works():
    registry = BackendRegistry(allowed_names=("tiny",))
    registry.register(
        "tiny",
        _pinned("tiny", max_context_tokens=1),
        scripted_stub(['{"a": 1}']),
        locality_attestation="operator-asserted",
    )
    assert route(registry, TaskRequirements(min_context_tokens=32768)).outcome == (
        NO_ELIGIBLE_BACKEND
    )
    assert route(registry, TaskRequirements(min_context_tokens=1)).selected == "tiny"


def test_finding3_malformed_requirements_block_every_candidate():
    requirements = TaskRequirements(min_context_tokens=-1)
    assert "requirements-invalid" in evaluate(_pinned("m"), requirements)


def test_finding3_malformed_requirements_are_reported_even_with_no_registry():
    decision = route(
        BackendRegistry(allowed_names=()), TaskRequirements(min_context_tokens=-5)
    )
    assert decision.escalation == ("requirements-invalid",)


# == Finding 4 - immutable model provenance ==================================


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"variant_id": ""}, "variant-unspecified"),
        ({"repository_revision": ""}, "repository-revision-unpinned"),
        (
            {"repository_revision": "main", "runtimes": ("vllm",)},
            "artifact-unpinned",
        ),
        ({"licence_source_url": ""}, "licence-source-unpinned"),
        ({"licence_revision": ""}, "licence-source-unpinned"),
        ({"artifact_path": "model.gguf"}, "artifact-digest-missing"),
    ],
)
def test_finding4_unpinned_provenance_blocks_routing(overrides, reason):
    assert reason in evaluate(_pinned(**overrides), TaskRequirements())


def test_finding4_an_artifact_claim_with_a_digest_is_accepted():
    digest = "sha256:" + "ab" * 32
    caps = _pinned(
        quantisation="gguf-q4_k_m", artifact_path="m.gguf", artifact_digest=digest
    )
    assert caps.artifact_digest == digest
    assert evaluate(caps, TaskRequirements()) == ()


@pytest.mark.parametrize(
    "supplied",
    [
        "abc123",
        "sha256:short",
        "sha256:" + "AB" * 32,
        "sha512:" + "ab" * 32,
        "sha256:" + "zz" * 32,
        7,
        None,
    ],
)
def test_finding4_a_malformed_digest_is_refused_not_stored(supplied):
    caps = _pinned(artifact_path="m.gguf", artifact_digest=supplied)
    assert caps.artifact_digest == ""
    assert "artifact-digest-missing" in evaluate(caps, TaskRequirements())


def test_finding4_identity_fields_reject_paths_and_secrets():
    caps = ModelCapabilities(
        model_id=_PATH, variant_id=_SECRET, repository_revision="/home/kevin/x"
    )
    assert caps.model_id == ""
    assert caps.variant_id == ""
    assert caps.repository_revision == ""


def test_finding4_every_catalogue_entry_names_an_exact_variant():
    for entry in CATALOGUE:
        assert entry.variant_id, f"{entry.model_id} has no variant_id"
        assert entry.licence_source_url.startswith("https://")
        assert entry.licence_revision


def test_finding4_catalogue_variants_are_not_collapsed():
    # Two Granite artifacts and two Gemma artifacts are separate entries, not
    # one row each with a bag of quantisations.
    identities = [(e.model_id, e.variant_id) for e in CATALOGUE]
    assert len(identities) == len(set(identities))
    granite = [e for e in CATALOGUE if e.model_id.startswith("ibm-granite/")]
    assert len(granite) >= 2
    assert {e.quantisation for e in granite} == {"", "gguf-q4_k_m"}
    # The two Granite rows are different repositories, not one row with a bag
    # of quantisations.
    assert len({e.model_id for e in granite}) == 2


def test_finding4_catalogue_is_byte_pinned_but_still_inert():
    # Round two: revisions and digests were retrieved from official metadata.
    # A pin says WHICH BYTES, never THAT YOU MAY RUN THEM - the entries stay
    # unroutable on availability and locality.
    for entry in CATALOGUE:
        assert entry.is_byte_pinned(), entry.model_id
        assert entry.availability == "unknown"
        assert entry.locality == "unknown"
        assert evaluate(entry, TaskRequirements())


def test_finding4_find_refuses_to_guess_between_variants():
    assert find("ibm-granite/granite-4.1-8b").variant_id == (
        "bf16-safetensors-sharded"
    )
    assert find("ibm-granite/granite-4.1-8b", "bf16-safetensors-sharded") is not None
    assert find("nonexistent/model") is None


# == Finding 5 - the Ollama claim, re-verified and pinned ====================

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "OPEN_MODEL_INTEGRATION.md"


def test_finding5_every_runtime_row_pins_a_version():
    text = _DOC.read_text(encoding="utf-8")
    for pinned in ("v0.32.15", "v0.27.1", "v0.5.18", "b10569"):
        assert pinned in text, f"runtime claim not pinned to {pinned}"


def test_finding5_the_challenged_claim_is_recorded_with_its_sources():
    text = _DOC.read_text(encoding="utf-8")
    assert "tool_choice" in text
    # The re-verification must name that it was re-checked, not merely assert.
    assert "re-verified" in text.lower()
    assert "docs.ollama.com/api/openai-compatibility" in text
