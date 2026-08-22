"""Regression tests for the OMI-V1 seventh independent-audit round.

The control reproduced against the code as it stood at `8f81078`.

L1  Round six moved the trust DATA into a closure, but
    ``has_pinned_runtime_binding`` still resolved the LOOKUP through a
    module-level name. An ordinary assignment,
    ``capabilities._runtime_repository_for = lambda t: "evil-org/fake-runtime"``,
    made the attacker repository eligible and the official vLLM repository
    ineligible.

Supported boundary, stated exactly (see also the module comment in
``capabilities.has_pinned_runtime_binding``):

  IN SCOPE, and closed here - ordinary reassignment of the repository trust
  data or of its lookup name: ``RUNTIME_REPOSITORIES`` and
  ``_runtime_repository_for``, plus the evidence-host constant. The method
  reads none of them; the relationship is inlined as code constants.

  OUT OF SCOPE, and not claimed - replacing the class method itself,
  replacing the router, patching the generic validators
  (``parse_https_url``, ``is_commit_revision``), ``__closure__`` cell
  surgery, or swapping the module in ``sys.modules``. Those are arbitrary
  code replacement, not reassignment of trust data.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

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
_OFFICIAL = "https://github.com/vllm-project/vllm/tree/" + _VLLM
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
        bound_runtime_source_url=_OFFICIAL,
        licence_class="osi-open-source",
    )
    base.update(overrides)
    return ModelCapabilities(**base)  # type: ignore[arg-type]


@pytest.fixture
def restore_module_names():
    """Restore every rebindable trust name, whatever the test does to them."""
    saved = {
        name: getattr(capabilities_module, name)
        for name in (
            "RUNTIME_REPOSITORIES",
            "_runtime_repository_for",
            "RUNTIME_EVIDENCE_HOST",
            "MODEL_EVIDENCE_HOST",
        )
    }
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(capabilities_module, name, value)


def test_baseline_official_eligible_and_evil_blocked():
    """Guard: without both halves every rebinding test proves nothing."""
    assert evaluate(_real(), TaskRequirements()) == ()
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


# == L1 - rebinding the lookup cannot redirect routing =======================


def test_l1_rebinding_the_lookup_cannot_alter_the_trusted_repository(
    restore_module_names,
):
    """The named control, exactly as reported."""
    capabilities_module._runtime_repository_for = (
        lambda token: "evil-org/fake-runtime"
    )
    # The attacker repository stays blocked...
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()
    # ...and the official repository stays eligible.
    assert evaluate(_real(), TaskRequirements()) == ()
    assert _real().has_pinned_runtime_binding() is True
    assert _real(bound_runtime_source_url=_EVIL).has_pinned_runtime_binding() is False


@pytest.mark.parametrize(
    "replacement",
    [
        pytest.param(lambda token: "evil-org/fake-runtime", id="always-evil"),
        pytest.param(lambda token: None, id="always-none"),
        pytest.param(lambda token: "vllm-project/vllm", id="always-vllm"),
        pytest.param(None, id="not-callable"),
        pytest.param("not-a-function", id="a-string"),
    ],
)
def test_l1_no_replacement_of_the_lookup_changes_routing(
    restore_module_names, replacement
):
    capabilities_module._runtime_repository_for = replacement
    assert evaluate(_real(), TaskRequirements()) == ()
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


def test_l1_rebinding_the_view_and_the_host_together_changes_nothing(
    restore_module_names,
):
    capabilities_module.RUNTIME_REPOSITORIES = {"vllm": "evil-org/fake-runtime"}
    capabilities_module._runtime_repository_for = lambda token: "evil-org/fake-runtime"
    capabilities_module.RUNTIME_EVIDENCE_HOST = "evil.invalid"
    assert evaluate(_real(), TaskRequirements()) == ()
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


def test_l1_the_method_reads_no_rebindable_trust_name():
    """Structural: the trust names are absent from the method's globals."""
    referenced = set(ModelCapabilities.has_pinned_runtime_binding.__code__.co_names)
    for forbidden in (
        "_runtime_repository_for",
        "RUNTIME_REPOSITORIES",
        "RUNTIME_EVIDENCE_HOST",
    ):
        assert forbidden not in referenced, forbidden


def test_l1_the_inlined_relationship_matches_the_exported_view():
    """Drift guard: the inline constants and the exported view must agree."""
    for token, repository in RUNTIME_REPOSITORIES.items():
        good = _real(
            runtimes=(token,),
            bound_runtime=token,
            bound_runtime_source_url=(
                "https://github.com/" + repository + "/tree/" + _VLLM
            ),
        )
        assert good.has_pinned_runtime_binding() is True, token
        wrong = _real(
            runtimes=(token,),
            bound_runtime=token,
            bound_runtime_source_url=(
                "https://github.com/evil-org/fake-runtime/tree/" + _VLLM
            ),
        )
        assert wrong.has_pinned_runtime_binding() is False, token
    # And the convenience lookup, though unused by routing, still agrees.
    for token, repository in RUNTIME_REPOSITORIES.items():
        assert _runtime_repository_for(token) == repository


def test_l1_an_unmapped_token_is_still_refused():
    for token in ("in-process-stub", "unknown", "nonsense"):
        caps = _real(
            runtimes=(token,),
            bound_runtime=token,
            bound_runtime_source_url=(
                "https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/tree/"
                + _VLLM
            ),
        )
        assert caps.has_pinned_runtime_binding() is False, token


def test_l1_the_evidence_host_is_enforced_inline():
    caps = _real(
        bound_runtime_source_url=(
            "https://gitlab.com/vllm-project/vllm/tree/" + _VLLM
        )
    )
    assert caps.has_pinned_runtime_binding() is False


# == public mapping controls remain closed ===================================


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.__setitem__("vllm", "evil-org/fake-runtime"),
        lambda m: m.__delitem__("vllm"),
        lambda m: m.update({"vllm": "evil-org/fake-runtime"}),
        lambda m: m.pop("vllm"),
        lambda m: m.popitem(),
        lambda m: m.clear(),
        lambda m: m.setdefault("vllm", "evil-org/fake-runtime"),
    ],
)
def test_public_mapping_mutation_remains_closed(mutate):
    with pytest.raises((TypeError, AttributeError)):
        mutate(RUNTIME_REPOSITORIES)
    assert evaluate(_real(), TaskRequirements()) == ()
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


def test_public_mapping_rebinding_remains_closed(restore_module_names):
    capabilities_module.RUNTIME_REPOSITORIES = {"vllm": "evil-org/fake-runtime"}
    assert evaluate(_real(), TaskRequirements()) == ()
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()


def test_the_mapping_view_exposes_no_mutating_member():
    for mutator in (
        "__setitem__",
        "__delitem__",
        "update",
        "clear",
        "pop",
        "popitem",
        "setdefault",
    ):
        assert not hasattr(RUNTIME_REPOSITORIES, mutator), mutator


# == prior rounds remain closed ==============================================


def test_round_five_and_six_controls_remain_closed():
    """Re-asserted so this file stands alone as a regression gate."""
    # J1 - a real commit cannot vouch for an unrelated repository
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()
    # J2 - long-opaque secret in the owner position is not stored
    owner = _real(
        bound_runtime_source_url=(
            "https://github.com/" + _SECRET48 + "/vllm/tree/" + _VLLM
        )
    )
    assert owner.bound_runtime_source_url == ""
    assert _SECRET48 not in repr(owner)
    # J3 - secret in a licence file path is not stored
    licence = _real(
        licence_source_url=(
            "https://huggingface.co/" + _REPO + "/blob/" + _SHA + "/"
            + _SECRET48 + ".md"
        )
    )
    assert licence.licence_source_url == ""
    # J4 - percent-encoded traversal refused
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
    # K1 - the mapping view is still intact
    assert len(RUNTIME_REPOSITORIES) == 5
    assert RUNTIME_REPOSITORIES["vllm"] == "vllm-project/vllm"


def test_round_five_controls_remain_closed_after_lookup_rebinding(
    restore_module_names,
):
    """The rounds interact: a redirected lookup must not reopen J1."""
    capabilities_module._runtime_repository_for = (
        lambda token: "evil-org/fake-runtime"
    )
    assert evaluate(_real(bound_runtime_source_url=_EVIL), TaskRequirements()) != ()
    owner = _real(
        bound_runtime_source_url=(
            "https://github.com/" + _SECRET48 + "/vllm/tree/" + _VLLM
        )
    )
    assert owner.bound_runtime_source_url == ""


def test_the_catalogue_is_unaffected_and_still_inert(restore_module_names):
    capabilities_module._runtime_repository_for = lambda token: "evil-org/x"
    permissive = TaskRequirements(
        require_local=False,
        allowed_licence_classes=(
            "osi-open-source",
            "open-weight-restricted",
            "source-available",
            "proprietary-service",
        ),
    )
    assert len(CATALOGUE) == 12
    assert sum(1 for e in CATALOGUE if not evaluate(e, permissive)) == 0
