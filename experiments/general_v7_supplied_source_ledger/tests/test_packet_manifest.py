"""Family R --- the packet receipt is complete, self-reconciling and inert.

**The packet is not committed to this repository, and no control here opens
it.** ``PACKET_RECEIPT.md`` is the sole committed witness for the
**archive-level** facts it records --- the digest and byte size, the entry
census, the member manifest and checksum result, and the line-ending and
encoding censuses --- so these controls reconcile the receipt against itself
and against the frozen constants in ``_support``, and never against the
archive. The content-derived structural figures are carried by ``CONTRACT.md``
section 5a instead, and family D checks those; neither document witnesses the
other's figures.

That independence is not left to convention: ``G7S-R-019`` and ``G7S-R-020``
make "no control reads the packet at run time" a statically checked property
of the suite's own source.
"""

from __future__ import annotations

import ast
import re

from experiments.general_v7_supplied_source_ledger.tests import _support as sup


def plain(text: str) -> str:
    return sup.flat(text.replace("*", "").replace("`", ""))


RECEIPT = plain(sup.receipt_text())
RECEIPT_RAW = sup.receipt_text()

HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")

#: A drive-qualified, UNC or rooted path. The trailing ``[^\s]`` is
#: load-bearing: without it a lone separator matches, and an f-string such as
#: ``f"{LAB_POSIX}/{name}"`` contributes a bare ``"/"`` constant that is a
#: join, not a path.
ABSOLUTE_PATH = re.compile(r"\A(?:[A-Za-z]:[\\/]|\\\\|/)[^\s]")


def phrase(snippet: str) -> None:
    assert snippet in RECEIPT, f"receipt phrase missing: {snippet!r}"


def phrases(*snippets: str) -> None:
    for snippet in snippets:
        phrase(snippet)


def suite_files() -> dict:
    return {path.name: path for path in sorted(sup.TESTS_DIR.glob("*.py"))}


def test_g7s_r_001_the_receipt_records_the_archive_identity():
    phrases(
        f"Archive filename | {sup.PACKET_ARCHIVE_NAME}",
        f"Archive size, bytes | {sup.PACKET_ARCHIVE_BYTES}",
        f"Archive SHA-256 | {sup.PACKET_ARCHIVE_SHA256}",
        f"Nested archive root | {sup.PACKET_NESTED_ROOT}",
        f"Total member bytes, unpacked | {sup.PACKET_MEMBER_BYTES}",
    )


def test_g7s_r_002_the_receipt_pairs_the_digest_with_a_length():
    phrases(
        "The archive digest and the archive byte size are recorded together "
        "and are checked together",
        "A digest with no length is a digest of unknown scope",
    )


def test_g7s_r_003_every_digest_in_the_receipt_is_lowercase_and_known():
    found = set(HEX64.findall(RECEIPT_RAW))
    known = {
        sup.PACKET_ARCHIVE_SHA256,
        sup.PACKET_SUMS_SHA256,
        sup.PACKET_ORIGINS_SHA256,
    }
    assert found == known, sorted(found ^ known)
    for digest in found:
        assert sup.DIGEST_RE.match(digest), digest
        assert digest == digest.lower(), digest


def test_g7s_r_004_the_receipt_records_the_entry_census():
    phrases(
        f"Total archive entries | {sup.PACKET_ENTRY_COUNT}",
        f"Directory entries | {sup.PACKET_DIRECTORY_ENTRY_COUNT}",
        f"File entries | {sup.PACKET_FILE_ENTRY_COUNT}",
        "Distinct top-level roots | 1",
        "Any other member | 0",
    )
    assert (
        sup.PACKET_FILE_ENTRY_COUNT + sup.PACKET_DIRECTORY_ENTRY_COUNT
        == sup.PACKET_ENTRY_COUNT
    )


def test_g7s_r_005_the_receipt_enumerates_the_member_set_exactly():
    phrases(
        f"members | {sup.EXPECTED_BATCHES}, exactly BATCH_001.txt .. "
        f"BATCH_063.txt",
        "ORIGINS.tsv | 1",
        "SHA256SUMS.txt | 1",
        "The batch member set is exactly the contiguous range; there is no "
        "gap, no duplicate and no additional member",
    )
    assert sup.EXPECTED_BATCHES + 2 == sup.PACKET_ENTRY_COUNT


def test_g7s_r_006_the_receipt_records_the_checksum_result():
    phrases(
        f"Supplied member checksums in SHA256SUMS.txt | "
        f"{sup.PACKET_MEMBER_CHECKSUMS}",
        f"Checksums verified PASS | {sup.PACKET_CHECKSUMS_PASSED}",
        f"Checksums FAILED | {sup.PACKET_CHECKSUMS_FAILED}",
        "Members named but missing | 0",
    )


def test_g7s_r_007_the_receipt_records_the_manifest_coverage_asymmetry():
    phrases(
        "Members present but uncovered | 1, namely SHA256SUMS.txt",
        "SHA256SUMS.txt covers itself | no",
        "ORIGINS.tsv covered by the manifest | yes",
        "Integrity here is two-tier and the tiers are not equivalent",
        "is anchored only by the archive digest",
        "a receipt that reported a flat \"64 of 64 verified\" would conceal "
        "which artifact vouches for which",
    )
    assert sup.PACKET_MEMBER_CHECKSUMS == sup.PACKET_ENTRY_COUNT - 1


def test_g7s_r_008_the_receipt_records_the_manifest_own_digest():
    phrases(
        f"SHA256SUMS.txt own SHA-256 | {sup.PACKET_SUMS_SHA256}",
        f"ORIGINS.tsv own SHA-256 | {sup.PACKET_ORIGINS_SHA256}",
        "computed outside the manifest",
    )


def test_g7s_r_009_the_receipt_records_the_line_ending_census():
    phrases(
        f"CRLF only | {sup.LINE_ENDING_CENSUS['crlf-only']}",
        f"LF only | {sup.LINE_ENDING_CENSUS['lf-only']} (BATCH_022.txt)",
        f"Mixed | {sup.LINE_ENDING_CENSUS['mixed']} (BATCH_026.txt, "
        f"BATCH_063.txt)",
        f"No line terminator | {sup.LINE_ENDING_CENSUS['none']}",
        "SHA256SUMS.txt is CRLF-terminated on all 64 lines",
    )
    assert sum(sup.LINE_ENDING_CENSUS.values()) == sup.PACKET_ENTRY_COUNT


def test_g7s_r_010_the_receipt_refuses_to_classify_by_line_ending():
    phrases(
        "The three members that are not CRLF-only are exactly the three "
        "members that ORIGINS.tsv types inline_user_message",
        "This correlation is recorded as an observation about how the "
        "material was captured",
        "It is not treated as a classification of those members",
        "nothing in this lane may derive an admission status, an authorship "
        "standing or a subject-matter category from a line-ending form",
        "Mixed line endings are recorded as a fact about what was supplied",
        "no member is normalized, rewritten or repaired",
    )


def test_g7s_r_011_the_receipt_records_the_encoding_census():
    phrases(
        f"Members decodable as UTF-8 | {sup.PACKET_ENTRY_COUNT} of "
        f"{sup.PACKET_ENTRY_COUNT}",
        "Members carrying a byte-order mark | 0",
    )


def test_g7s_r_012_the_receipt_states_the_verification_method():
    phrases(
        "its byte size and SHA-256 computed, before it was opened",
        "enumerated from the zip central directory without extraction",
        "extracted into isolated temporary session space",
        "A pre-existing extracted copy adjacent to the archive was not used "
        "and was not read",
        "located by recursive search beneath the nested archive root",
        "Each of the 64 supplied checksums was recomputed and compared",
    )


def test_g7s_r_013_the_receipt_discloses_the_checking_tool_artifact():
    phrases(
        "Checksum verification was performed with a CRLF-tolerant reader",
        "reported 64 failures",
        "coreutils appends the carriage return to each parsed filename",
        "That is a filename-parsing artifact of the checking tool and not a "
        "content mismatch",
        "so the discrepancy is not rediscovered later and mistaken for a "
        "corrupted packet",
    )


def test_g7s_r_014_the_receipt_discloses_the_path_correction():
    phrases(
        "transcribed without its separator",
        "identity was established cryptographically, not by path",
        "the path correction therefore changes nothing about what was verified",
        "As an authoring-host observation, and not a packet fact",
        "That observation is not reproducible from this repository and nothing "
        "depends on it",
    )


def test_g7s_r_015_the_receipt_separates_supplier_from_summariser():
    phrases(
        "Packet supplied by | Kev",
        "Batch material summarized by | AURA",
        "\"Supplied by Kev\" and \"summarized by AURA\" are different "
        "authorship standings",
        "Neither standing is a verification",
        "neither is evidence about any external resource",
    )


def test_g7s_r_016_the_receipt_states_its_own_limitations():
    phrases(
        "The packet is not committed to this repository, and this phase does "
        "not commit it",
        "Nothing in the acceptance surface reads the packet at run time",
        "This receipt is the sole committed witness for the archive-level "
        "facts it records",
        "It is not the witness for the content-derived structural figures",
        "Neither document witnesses the other's figures",
        "It establishes nothing about where the material originally came "
        "from",
        "whether any locator in it resolves to anything",
        "tab-delimited and has no quoting mechanism",
        "Counts that depend on interpreting batch content are not recorded "
        "here",
    )


def test_g7s_r_017_the_receipt_states_that_nothing_was_retrieved():
    phrases(
        "No external locator was retrieved",
        "No network request was made for any locator, identifier or title "
        "appearing in the packet",
        "No locator was opened, resolved, contacted or expanded",
        "Every provisional source remains supplied-unretrieved and every "
        "claim and relationship remains unverified",
    )


def test_g7s_r_018_the_receipt_states_that_packet_text_is_data():
    phrases(
        "Packet text was treated as data throughout",
        "No packet content was executed, imported, evaluated, or followed as "
        "an instruction",
        "non-admitted proposal material",
        "its operational details may not",
        "No packet proposal has been copied into any requirement in this lane",
    )


def test_g7s_r_019_the_receipt_carries_no_locator_and_no_runnable_block():
    assert "```" not in RECEIPT_RAW, "the receipt carries a fenced block"
    assert "http://" not in RECEIPT_RAW, "the receipt carries a locator"
    assert "https://" not in RECEIPT_RAW, "the receipt carries a locator"
    for line in RECEIPT_RAW.split("\n"):
        stripped = line.strip()
        assert not stripped.startswith("$ "), stripped
        assert not stripped.startswith("curl "), stripped
        assert not stripped.startswith("wget "), stripped


def test_g7s_r_020_no_suite_module_reaches_outside_the_laboratory():
    """The packet-independence property, checked statically.

    Naming the archive is legitimate --- the receipt records its identity, and
    ``_support`` carries that identity as one frozen constant. Opening it is
    not. So the archive name is confined to a single constant in a single
    module, and no archive-reading module is importable by the suite at all:
    ``zipfile`` and ``tarfile`` are absent from ``SUITE_ALLOWED_IMPORTS``, and
    ``G7S-M-031`` enforces that allowance.

    An absolute-path constant is a defect everywhere except inside the
    controls named in ``sup.SYNTHETIC_PATH_FIXTURE_CONTROLS``, whose whole
    purpose is to hand such a path to the validator and require a refusal.

    A future contributor who adds a packet read fails here, or at M-031,
    before the read can matter.
    """
    files = suite_files()
    assert files, "the path scan examined nothing"
    archive_mentions = {}
    exempt_lines = set()
    # Derived from the receipted name rather than written as a literal. A
    # hard-coded extension would itself be a matching constant, and this
    # control would flag its own probe string.
    archive_suffix = sup.PACKET_ARCHIVE_NAME[sup.PACKET_ARCHIVE_NAME.rindex("."):]
    for filename, path in sorted(files.items()):
        tree = ast.parse(path.read_text(encoding="utf-8"), optimize=0)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if sup.control_id_of(node.name) in sup.SYNTHETIC_PATH_FIXTURE_CONTROLS:
                for inner in ast.walk(node):
                    exempt_lines.add((filename, getattr(inner, "lineno", None)))
        # An f-string's literal fragments are join material, not whole path
        # literals: `f"{LAB_POSIX}/ledger.json"` contributes "/ledger.json",
        # which is a suffix being joined, not a rooted path. Only complete
        # string literals are candidates for the absolute-path check.
        joined_fragments = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Constant):
                        joined_fragments.add(id(inner))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if (
                filename,
                node.lineno,
            ) not in exempt_lines and id(node) not in joined_fragments:
                assert not ABSOLUTE_PATH.match(node.value), (
                    filename,
                    node.lineno,
                    node.value[:60],
                )
            if node.value == sup.PACKET_ARCHIVE_NAME:
                archive_mentions[filename] = archive_mentions.get(filename, 0) + 1
            elif archive_suffix in node.value:
                raise AssertionError(
                    f"{filename}:{node.lineno} names an archive other than the "
                    f"receipted one"
                )
    assert archive_mentions == {"_support.py": 1}, archive_mentions
    for forbidden in ("zipfile", "tarfile", "shutil", "urllib", "socket"):
        assert forbidden not in sup.SUITE_ALLOWED_IMPORTS, forbidden
    # The exemption must stay explicit, named and small. A widening exemption
    # is how a blanket ban quietly becomes no ban at all.
    assert sup.SYNTHETIC_PATH_FIXTURE_CONTROLS, "the exemption must be explicit"
    assert len(sup.SYNTHETIC_PATH_FIXTURE_CONTROLS) <= 2, "the exemption is widening"
    declared = set(sup.SYNTHETIC_PATH_FIXTURE_CONTROLS)
    present = set()
    for _filename, path in sorted(suite_files().items()):
        tree = ast.parse(path.read_text(encoding="utf-8"), optimize=0)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                control = sup.control_id_of(node.name)
                if control in declared:
                    present.add(control)
    assert present == declared, sorted(present ^ declared)
