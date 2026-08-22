"""Tests for scripts/open_model/capabilities.py (OMI-V1).

Covers:
  - Every default is the fail-closed value, so a bare descriptor is
    ineligible rather than accidentally eligible.
  - Frozen dataclass rejects mutation (immutability fence).
  - Exact-type normalization: str subclasses, bools-as-ints, unknown
    vocabulary spellings, and hostile objects are all replaced by the
    conservative default without any supplied hook being invoked.
  - Sequence fields keep order, de-duplicate, filter against the closed
    runtime vocabulary, and cap their length.
  - provenance_url accepts only https and is never dereferenced.
  - observed_on accepts only a literal YYYY-MM-DD shape.
  - unresolved_fields reports in fixed declaration order.
  - preference_key orders light < medium < heavy < unknown.
"""

from __future__ import annotations

import dataclasses

import pytest

from scripts.open_model.capabilities import (
    RESOURCE_ORDER,
    ModelCapabilities,
)


class _Hostile:
    """Every hook raises, so an invoked hook fails the test loudly.

    ``raise`` statements, not ``assert``, so the traps survive ``python -O``.
    """

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

    def __getitem__(self, item):  # pragma: no cover
        raise RuntimeError("__getitem__ invoked")


class _StrSubclass(str):
    """A str subclass whose methods could be overridden; must be refused."""


# -- fail-closed defaults ----------------------------------------------------


def test_defaults_are_all_fail_closed():
    caps = ModelCapabilities(model_id="m")
    assert caps.locality == "unknown"
    assert caps.availability == "unknown"
    assert caps.resource_class == "unknown"
    assert caps.structured_output == "unknown"
    assert caps.tool_calling == "unknown"
    assert caps.max_context_tokens == 0
    assert caps.max_output_tokens == 0
    assert caps.quantisation == ""
    assert caps.runtimes == ()
    assert caps.licence_class == "unknown"
    assert caps.licence_name == ""
    assert caps.provenance_url == ""
    assert caps.observed_on == ""


def test_descriptor_is_frozen():
    caps = ModelCapabilities(model_id="m")
    with pytest.raises(dataclasses.FrozenInstanceError):
        caps.availability = "present"  # type: ignore[misc]


# -- exact-type normalization ------------------------------------------------


def test_str_subclass_model_id_is_refused():
    caps = ModelCapabilities(model_id=_StrSubclass("sneaky"))
    assert caps.model_id == ""
    assert type(caps.model_id) is str


def test_hostile_values_are_replaced_without_invoking_any_hook():
    caps = ModelCapabilities(
        model_id=_Hostile(),
        locality=_Hostile(),
        availability=_Hostile(),
        resource_class=_Hostile(),
        structured_output=_Hostile(),
        tool_calling=_Hostile(),
        max_context_tokens=_Hostile(),
        max_output_tokens=_Hostile(),
        quantisation=_Hostile(),
        runtimes=_Hostile(),
        licence_class=_Hostile(),
        licence_name=_Hostile(),
        licence_notes=_Hostile(),
        provenance_url=_Hostile(),
        observed_on=_Hostile(),
    )
    assert caps.model_id == ""
    assert caps.locality == "unknown"
    assert caps.availability == "unknown"
    assert caps.resource_class == "unknown"
    assert caps.structured_output == "unknown"
    assert caps.tool_calling == "unknown"
    assert caps.max_context_tokens == 0
    assert caps.max_output_tokens == 0
    assert caps.quantisation == ""
    assert caps.runtimes == ()
    assert caps.licence_class == "unknown"
    assert caps.licence_name == ""
    assert caps.licence_notes == ""
    assert caps.provenance_url == ""
    assert caps.observed_on == ""


def test_bool_is_not_accepted_as_a_token_count():
    # bool is an int subclass; True must not become a context length of 1.
    caps = ModelCapabilities(model_id="m", max_context_tokens=True)
    assert caps.max_context_tokens == 0


def test_negative_token_counts_become_zero():
    caps = ModelCapabilities(model_id="m", max_context_tokens=-4096)
    assert caps.max_context_tokens == 0


def test_unknown_vocabulary_spelling_falls_back_to_unknown():
    caps = ModelCapabilities(
        model_id="m",
        locality="on-prem",
        availability="maybe",
        structured_output="yes",
        tool_calling="probably",
        licence_class="mit-ish",
    )
    assert caps.locality == "unknown"
    assert caps.availability == "unknown"
    assert caps.structured_output == "unknown"
    assert caps.tool_calling == "unknown"
    assert caps.licence_class == "unknown"


def test_unknown_is_never_upgraded_to_supported():
    caps = ModelCapabilities(model_id="m", structured_output="unknown")
    assert caps.structured_output != "supported"


# -- sequence fields ---------------------------------------------------------


def test_runtimes_filter_against_vocabulary_and_keep_order():
    caps = ModelCapabilities(
        model_id="m",
        runtimes=("ollama", "not-a-runtime", "llama-cpp", "ollama", 7),
    )
    assert caps.runtimes == ("ollama", "llama-cpp")


def test_runtimes_accept_a_list_and_become_a_tuple():
    caps = ModelCapabilities(model_id="m", runtimes=["vllm", "sglang"])
    assert caps.runtimes == ("vllm", "sglang")
    assert type(caps.runtimes) is tuple


def test_an_over_long_sequence_input_is_refused_outright():
    # Bounding only the kept list would still walk every element.
    caps = ModelCapabilities(model_id="m", runtimes=["ollama"] * 100)
    assert caps.runtimes == ()


def test_quantisation_is_singular_and_must_be_a_safe_token():
    assert ModelCapabilities(model_id="m", quantisation="gguf-q4_k_m").quantisation == (
        "gguf-q4_k_m"
    )
    assert ModelCapabilities(model_id="m", quantisation=("gguf", "fp8")).quantisation == ""
    assert ModelCapabilities(model_id="m", quantisation="a b").quantisation == ""


# -- provenance and dates ----------------------------------------------------


@pytest.mark.parametrize(
    "supplied",
    [
        "http://example.invalid/card",
        "file:///etc/passwd",
        "data:text/plain,hello",
        "ollama serve",
        "https://",
        "",
    ],
)
def test_provenance_url_rejects_anything_but_a_real_https_url(supplied):
    caps = ModelCapabilities(model_id="m", provenance_url=supplied)
    assert caps.provenance_url == ""


def test_provenance_url_keeps_a_real_https_url():
    url = "https://huggingface.co/ibm-granite/granite-4.1-8b"
    caps = ModelCapabilities(model_id="m", provenance_url=url)
    assert caps.provenance_url == url


@pytest.mark.parametrize(
    "supplied",
    ["2026-8-22", "22-08-2026", "2026/08/22", "2026-08-22T00:00:00Z", "yesterday"],
)
def test_observed_on_rejects_anything_but_an_iso_day_shape(supplied):
    caps = ModelCapabilities(model_id="m", observed_on=supplied)
    assert caps.observed_on == ""


def test_observed_on_keeps_an_iso_day_shape():
    caps = ModelCapabilities(model_id="m", observed_on="2026-08-22")
    assert caps.observed_on == "2026-08-22"


# -- derived views -----------------------------------------------------------


def test_unresolved_fields_lists_every_unknown_in_declaration_order():
    caps = ModelCapabilities(model_id="")
    assert caps.unresolved_fields() == (
        "model_id",
        "variant_id",
        "repository_revision",
        "licence_source_url",
        "licence_revision",
        "locality",
        "availability",
        "resource_class",
        "structured_output",
        "tool_calling",
        "max_context_tokens",
        "runtimes",
        "licence_class",
    )


def test_unresolved_fields_is_empty_for_a_fully_specified_descriptor():
    caps = ModelCapabilities(
        model_id="m",
        variant_id="bf16",
        repository_revision="1111111111111111111111111111111111111111",
        licence_source_url="https://example.invalid/licence",
        licence_revision="2.0",
        locality="local",
        availability="present",
        resource_class="light",
        structured_output="supported",
        tool_calling="supported",
        max_context_tokens=8192,
        runtimes=("ollama",),
        licence_class="osi-open-source",
    )
    assert caps.unresolved_fields() == ()


def test_preference_key_orders_light_before_heavy_before_unknown():
    assert RESOURCE_ORDER["light"] < RESOURCE_ORDER["medium"]
    assert RESOURCE_ORDER["medium"] < RESOURCE_ORDER["heavy"]
    assert RESOURCE_ORDER["heavy"] < RESOURCE_ORDER["unknown"]

    light = ModelCapabilities(model_id="z", resource_class="light")
    heavy = ModelCapabilities(model_id="a", resource_class="heavy")
    unknown = ModelCapabilities(model_id="a", resource_class="nonsense")
    ordered = sorted([unknown, heavy, light], key=ModelCapabilities.preference_key)
    assert [c.resource_class for c in ordered] == ["light", "heavy", "unknown"]


def test_preference_key_breaks_ties_on_model_id():
    first = ModelCapabilities(model_id="aaa", resource_class="light")
    second = ModelCapabilities(model_id="bbb", resource_class="light")
    assert first.preference_key() < second.preference_key()
