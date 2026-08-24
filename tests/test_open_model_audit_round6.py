"""Regression tests for the OMI-V1 sixth independent-audit round.

Both controls reproduced against the code as it stood at `8eac3c0`.

K1  RUNTIME_REPOSITORIES was a ``Final[dict]``. ``Final`` is a type-checker
    annotation with no runtime effect, so
    ``RUNTIME_REPOSITORIES["vllm"] = "evil-org/fake-runtime"`` silently
    restored eligibility for an attacker-selected repository, and ``update``
    and ``del`` worked just as well.
K2  the documentation claimed every model and licence claim was immutably
    pinned, while the family-level survey still linked moving vendor pages.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pathlib

import pytest

from scripts.open_model import capabilities as capabilities_module
from scripts.open_model.capabilities import (
    RUNTIME_REPOSITORIES,
    ModelCapabilities,
    _runtime_repository_for,
)
from scripts.open_model.catalogue import CATALOGUE
from scripts.open_model.routing import TaskRequirements, evaluate

_SHA = "1504002f650e656a0a3789d99574df12e3e94ed0"
_VLLM = "6e448d0ea9bf3d88d898b65449ca6dc2aec170ac"
_REPO = "org/model"
_EVIL = "https://github.com/evil-org/fake-runtime/tree/" + _VLLM
_SECRET48 = "A" * 48


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


def test_baseline_is_eligible_and_the_evil_repository_is_not():
    """Guard: without this pair every mutation test below proves nothing."""
    assert evaluate(_real(), TaskRequirements()) == ()
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


# == K1 - the trust mapping is immutable at runtime ==========================


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda m: m.__setitem__("vllm", "evil-org/fake-runtime"), id="setitem"
        ),
        pytest.param(lambda m: m.__delitem__("vllm"), id="delitem"),
        pytest.param(
            lambda m: m.update({"vllm": "evil-org/fake-runtime"}), id="update"
        ),
        pytest.param(lambda m: m.pop("vllm"), id="pop"),
        pytest.param(lambda m: m.popitem(), id="popitem"),
        pytest.param(lambda m: m.clear(), id="clear"),
        pytest.param(
            lambda m: m.setdefault("vllm", "evil-org/fake-runtime"), id="setdefault"
        ),
    ],
)
def test_k1_every_ordinary_mutation_path_refuses(mutate):
    """The named control: assignment, deletion, update and friends."""
    with pytest.raises((TypeError, AttributeError)):
        mutate(RUNTIME_REPOSITORIES)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.__setitem__("vllm", "evil-org/fake-runtime"),
        lambda m: m.__delitem__("vllm"),
        lambda m: m.update({"vllm": "evil-org/fake-runtime"}),
        lambda m: m.pop("vllm"),
        lambda m: m.clear(),
    ],
)
def test_k1_a_wrong_repository_stays_blocked_after_every_attempt(mutate):
    """The named control: routing is unchanged by an attempted mutation."""
    try:
        mutate(RUNTIME_REPOSITORIES)
    except (TypeError, AttributeError):
        pass
    assert _runtime_repository_for("vllm") == "vllm-project/vllm"
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()
    assert evaluate(_real(), TaskRequirements()) == ()


def test_k1_the_mapping_contents_survive_every_attempt():
    before = dict(RUNTIME_REPOSITORIES)
    for mutate in (
        lambda m: m.__setitem__("vllm", "evil"),
        lambda m: m.__delitem__("ollama"),
        lambda m: m.update({"sglang": "evil"}),
        lambda m: m.clear(),
    ):
        try:
            mutate(RUNTIME_REPOSITORIES)
        except (TypeError, AttributeError):
            pass
    assert dict(RUNTIME_REPOSITORIES) == before
    assert len(RUNTIME_REPOSITORIES) == 5


def test_k1_rebinding_the_module_attribute_does_not_change_routing():
    """Routing consults the closed lookup, never the exported view."""
    original = capabilities_module.RUNTIME_REPOSITORIES
    try:
        capabilities_module.RUNTIME_REPOSITORIES = {
            "vllm": "evil-org/fake-runtime"
        }
        assert _runtime_repository_for("vllm") == "vllm-project/vllm"
        assert (
            evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()
        )
        assert evaluate(_real(), TaskRequirements()) == ()
    finally:
        capabilities_module.RUNTIME_REPOSITORIES = original
    assert capabilities_module.RUNTIME_REPOSITORIES is RUNTIME_REPOSITORIES


def test_k1_the_exported_view_is_a_read_only_mapping():
    from types import MappingProxyType

    assert isinstance(RUNTIME_REPOSITORIES, MappingProxyType)
    # Replaces a tautology (`... or True`, which asserted nothing) with the
    # check it was meant to be: a mappingproxy exposes NONE of the mutating
    # members, so an explicit call raises AttributeError rather than being
    # merely refused at runtime.
    for mutator in ("__setitem__", "__delitem__", "update", "clear", "pop",
                    "popitem", "setdefault"):
        assert not hasattr(RUNTIME_REPOSITORIES, mutator), mutator
    # Read access is unaffected.
    for reader in ("get", "items", "keys", "values", "__getitem__"):
        assert hasattr(RUNTIME_REPOSITORIES, reader), reader
    with pytest.raises((TypeError, AttributeError)):
        RUNTIME_REPOSITORIES["new-runtime"] = "evil/evil"


def test_k1_the_closed_lookup_is_total_and_type_safe():
    assert _runtime_repository_for("vllm") == "vllm-project/vllm"
    assert _runtime_repository_for("in-process-stub") is None
    assert _runtime_repository_for("nonsense") is None
    for hostile in (None, 7, object(), b"vllm", ["vllm"]):
        assert _runtime_repository_for(hostile) is None


def test_k1_the_lookup_and_the_view_agree():
    for token, repository in RUNTIME_REPOSITORIES.items():
        assert _runtime_repository_for(token) == repository


# == round-five controls remain closed =======================================


def test_round_five_controls_remain_closed():
    """Re-asserted here so this suite stands alone as a regression gate."""
    # J1 - a real commit cannot vouch for an unrelated repository
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()
    # J2 - a long-opaque secret in the owner position is not stored
    secret_owner = _real(
        bound_runtime_source_url=(
            "https://github.com/" + _SECRET48 + "/vllm/tree/" + _VLLM
        )
    )
    assert secret_owner.bound_runtime_source_url == ""
    assert _SECRET48 not in repr(secret_owner)
    # J3 - a secret in a licence file path is not stored
    secret_licence = _real(
        licence_source_url=(
            "https://huggingface.co/" + _REPO + "/blob/" + _SHA + "/" + _SECRET48
            + ".md"
        )
    )
    assert secret_licence.licence_source_url == ""
    # J4 - percent-encoded traversal is refused
    encoded = _real(
        licence_source_url=(
            "https://huggingface.co/" + _REPO + "/blob/" + _SHA
            + "/%2e%2e/%2e%2e/README.md"
        )
    )
    assert encoded.licence_source_url == ""
    assert _real(artifact_path="%2e%2e/etc/passwd").invalid_fields == (
        "artifact_path",
    )


def test_round_five_controls_remain_closed_after_mutation_attempts():
    """The two rounds interact: mutation must not reopen J1."""
    for mutate in (
        lambda m: m.__setitem__("vllm", "evil-org/fake-runtime"),
        lambda m: m.update({"vllm": "evil-org/fake-runtime"}),
    ):
        try:
            mutate(RUNTIME_REPOSITORIES)
        except (TypeError, AttributeError):
            pass
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


# == K2 - the documentation scopes its pinning claim =========================

_DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "OPEN_MODEL_INTEGRATION.md"


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_k2_the_family_survey_is_labelled_dated_and_not_pinned():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    assert "This table is a DATED FAMILY SURVEY. It is NOT pinned evidence." in flat
    assert "those pages move" in flat


def test_k2_the_pinned_claim_is_scoped_to_the_code_catalogue():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    assert "The pinned evidence in this work is the 12 descriptors in" in flat
    assert "Scoped to the 12 code-catalogue descriptors" in flat
    # Matched without the section glyph so console encodings cannot skew it.
    assert "family survey is NOT covered" in flat


def test_k2_no_unscoped_all_pinned_claim_survives():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    for stale in (
        "Every model and licence claim, and **every runtime claim except NVIDIA NIM**,"
        " is bound to an exact repository",
        "Every model, licence and runtime claim is bound to an exact repository",
        "Every runtime claim above is pinned",
    ):
        assert stale not in flat


def test_k2_the_catalogue_really_does_carry_what_the_doc_claims():
    """The scoped claim must be true of the 12, not merely narrower."""
    assert len(CATALOGUE) == 12
    for entry in CATALOGUE:
        assert entry.has_immutable_revision(), entry.model_id
        assert entry.has_pinned_provenance(), entry.model_id
        assert entry.has_pinned_licence(), entry.model_id
        assert entry.is_byte_pinned(), entry.model_id
