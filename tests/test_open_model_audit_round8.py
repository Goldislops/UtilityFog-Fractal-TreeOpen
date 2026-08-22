"""Regression checks for the OMI-V1 eighth independent-audit round.

Documentation truth only - the seventh-round functional gate was cleared and
no routing repair was requested.

M1  ``_build_runtime_repository_lookup`` still claimed, in the present tense,
    that routing consults the returned private lookup. Routing had already
    stopped doing so in round seven: the five repositories and the evidence
    host are inlined in ``has_pinned_runtime_binding``.
M2  the correction sections had drifted into reverse-chronological order -
    12, then 15, 14, 13 - because each round was inserted above the last.

These are narrow checks on prose that makes a security claim. A docstring
that describes a trust path the code no longer takes is not a cosmetic
problem: it is the thing a reviewer reads instead of the code.

Same-author evidence: written by the agent that wrote the code under test.
It demonstrates internal consistency, not independent acceptance.
"""

from __future__ import annotations

import pathlib
import re

from scripts.open_model.capabilities import ModelCapabilities

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DOC = _ROOT / "docs" / "OPEN_MODEL_INTEGRATION.md"
_CAPABILITIES = _ROOT / "scripts" / "open_model" / "capabilities.py"


def _flat(text: str) -> str:
    """Collapse whitespace, dropping Markdown blockquote markers.

    Without stripping the leading ``>`` the marker lands mid-phrase when a
    blockquote wraps, and a substring check fails on prose that is actually
    correct.
    """
    cleaned = []
    for line in text.split(chr(10)):
        stripped = line.lstrip()
        while stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        cleaned.append(stripped)
    return " ".join(" ".join(cleaned).split())


# == M1 - the docstring must not describe a trust path routing does not take =


def _source_between(start: str, end: str) -> str:
    """Flattened source slice.

    Read from the FILE, never from ``__doc__``. Under ``-OO`` docstrings are
    stripped, so a runtime ``__doc__`` assertion either fails spuriously or -
    worse - passes vacuously when it is checking for the ABSENCE of a stale
    phrase. A documentation-truth check must inspect the text a reviewer
    reads, which is the source.
    """
    source = _CAPABILITIES.read_text(encoding="utf-8")
    begin = source.index(start)
    finish = source.index(end, begin)
    return _flat(source[begin:finish])


_FACTORY_DOC = ("def _build_runtime_repository_lookup():", "    entries = (")
_LOOKUP_DOC = ("    def lookup(token: Any)", "        if type(token) is not str:")


def test_m1_the_factory_docstring_makes_no_current_tense_routing_claim():
    """The exact stale phrase, and its close variants, must be gone."""
    docstring = _source_between(*_FACTORY_DOC)
    for stale in (
        "Routing consults the returned *function*",
        "Routing consults the returned function",
        "routing consults the returned",
    ):
        assert stale.lower() not in docstring.lower(), stale


def test_m1_no_current_tense_trust_path_claim_survives_in_the_module():
    """Scan the whole module, not just the one docstring."""
    source = _flat(_CAPABILITIES.read_text(encoding="utf-8")).lower()
    for stale in (
        "routing consults the returned",
        "routing consults the closure",
        "routing reads their closure",
        "routing consults it",
    ):
        assert stale not in source, stale


def test_m1_the_factory_docstring_names_them_as_mirrors():
    docstring = _source_between(*_FACTORY_DOC)
    assert "mirrors, not the trust path" in docstring.lower()
    assert "it does not call the ``lookup`` returned" in docstring
    assert "does not read ``RUNTIME_REPOSITORIES``" in docstring


def test_m1_the_exported_names_are_documented_as_off_the_trust_path():
    source = _CAPABILITIES.read_text(encoding="utf-8")
    flat = _flat(source)
    assert "Exported inspection mirrors of the runtime trust mapping." in flat
    assert "Neither is on the trust path." in flat


def test_m1_the_lookup_docstring_says_routing_does_not_call_it():
    docstring = _source_between(*_LOOKUP_DOC)
    assert "inspection mirror" in docstring.lower()
    assert "routing does not call this" in docstring.lower()


def test_m1_the_documented_claim_matches_the_code():
    """Prose and behaviour must agree: the method reads neither name."""
    referenced = set(ModelCapabilities.has_pinned_runtime_binding.__code__.co_names)
    assert "_runtime_repository_for" not in referenced
    assert "RUNTIME_REPOSITORIES" not in referenced


# == M2 - correction sections in chronological order =========================

_HEADING = re.compile(r"^## (\d+)\. ")


def _numbered_headings() -> list[tuple[int, str]]:
    found = []
    for line in _DOC.read_text(encoding="utf-8").split("\n"):
        match = _HEADING.match(line)
        if match:
            found.append((int(match.group(1)), line.strip()))
    return found


def test_m2_numbered_sections_are_in_ascending_order():
    numbers = [number for number, _ in _numbered_headings()]
    assert numbers == sorted(numbers), numbers


def test_m2_no_section_number_is_duplicated():
    numbers = [number for number, _ in _numbered_headings()]
    assert len(numbers) == len(set(numbers)), numbers


def test_m2_the_correction_rounds_run_twelve_through_fifteen_in_order():
    headings = dict(_numbered_headings())
    assert "round four" in headings[12]
    assert "round five" in headings[13]
    assert "round six" in headings[14]
    assert "round seven" in headings[15]


def test_m2_the_round_six_account_is_preserved():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    # The historical record must survive the reordering, not be deleted.
    assert "Post-audit corrections, round six" in flat
    assert "`Final` is a type-checker annotation with no runtime effect" in flat


def test_m2_the_round_six_account_is_marked_superseded():
    flat = _flat(_DOC.read_text(encoding="utf-8"))
    assert "Superseded by round seven" in flat
    assert "private closure lookup that routing consults" in flat
    assert "inspection and testing mirrors only" in flat


def test_m2_the_supersession_note_sits_inside_the_round_six_section():
    text = _DOC.read_text(encoding="utf-8")
    start = text.index("## 14. Post-audit corrections, round six")
    end = text.index("## 15. Post-audit corrections, round seven")
    assert "Superseded by round seven" in text[start:end]
