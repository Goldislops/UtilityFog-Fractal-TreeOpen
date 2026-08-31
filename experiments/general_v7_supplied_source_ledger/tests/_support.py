"""Shared support for the ``general-v7-supplied-source-ledger-v1`` suite.

Nothing here imports an implementation module at import time, so
``--collect-only`` succeeds against an empty laboratory.

**This module contains no bare ``assert``, and that is load-bearing.** Pytest's
assertion rewriting replaces assert nodes only in the modules it collects as
tests. This module is not rewritten, so under ``python -O`` every bare assert
in it would be deleted at compile time and every helper built on one would
silently guarantee nothing while the control counting on it still reported a
pass. Every failure here is therefore raised explicitly. ``G7S-M-014``
enforces the rule statically.

**Absence is detected precisely.** Only the exact absence of an expected entry
is reported as ``implementation-absent``. An import error raised inside a
present module, a permission failure, a path-too-long error, a wrong type or a
malformed document all propagate unchanged: a broken implementation must never
be able to disguise itself as an unwritten one.

Nothing in this module retrieves, opens, resolves or contacts a locator, and
no locator string here refers to a real resource.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import pathlib
import re
import subprocess
import sys

# --------------------------------------------------------------------------
# Paths, computed from this file alone. Nothing is searched or crawled.
# --------------------------------------------------------------------------

TESTS_DIR = pathlib.Path(__file__).resolve().parent
LAB_DIR = TESTS_DIR.parent
EXPERIMENTS_DIR = LAB_DIR.parent
REPO_ROOT = EXPERIMENTS_DIR.parent

#: The laboratory's path relative to the repository root, in POSIX form. Git
#: object reads are addressed with this, never with a platform path.
LAB_POSIX = "experiments/general_v7_supplied_source_ledger"

CONTRACT_PATH = LAB_DIR / "CONTRACT.md"
RECEIPT_PATH = LAB_DIR / "PACKET_RECEIPT.md"

INIT_PATH = LAB_DIR / "__init__.py"
SCHEMA_PATH = LAB_DIR / "schema.py"
VALIDATE_PATH = LAB_DIR / "validate.py"
LEDGER_PATH = LAB_DIR / "ledger.json"
BIBLIOGRAPHY_PATH = LAB_DIR / "BIBLIOGRAPHY.md"
INTAKE_REPORT_PATH = LAB_DIR / "INTAKE_REPORT.md"
README_PATH = LAB_DIR / "README.md"

#: Authored in this phase. Present in both admissible states.
PHASE_A_PATHS = (
    "CONTRACT.md",
    "PACKET_RECEIPT.md",
    "tests/__init__.py",
    "tests/_support.py",
    "tests/test_contract.py",
    "tests/test_controls_manifest.py",
    "tests/test_packet_manifest.py",
    "tests/test_inventory.py",
    "tests/test_schema.py",
    "tests/test_provenance.py",
    "tests/test_quarantine.py",
)

#: The future implementation surface. All seven, or none.
IMPLEMENTATION_PATHS = (
    "__init__.py",
    "schema.py",
    "validate.py",
    "ledger.json",
    "BIBLIOGRAPHY.md",
    "INTAKE_REPORT.md",
    "README.md",
)

#: Paths that belong to no admissible state, in either phase.
NEVER_AUTHORIZED_PATHS = (".gitattributes", "records")

PRE_IMPLEMENTATION_STATE = "pre-implementation"
IMPLEMENTED_STATE = "implemented"
ADMISSIBLE_STATES = (PRE_IMPLEMENTATION_STATE, IMPLEMENTED_STATE)

#: The names a contract-only control may not mention. The classifier keys on
#: the path CONSTANT rather than on the helper name, because ``require_file``
#: is also used for CONTRACT.md and PACKET_RECEIPT.md, which are present in
#: both states; "calls a gate helper" alone is not a sound discriminator.
IMPLEMENTATION_PATH_CONSTANTS = frozenset(
    {
        "INIT_PATH",
        "SCHEMA_PATH",
        "VALIDATE_PATH",
        "LEDGER_PATH",
        "BIBLIOGRAPHY_PATH",
        "INTAKE_REPORT_PATH",
        "README_PATH",
    }
)

GATE_HELPERS = frozenset(
    {
        "require_init",
        "require_schema",
        "require_validate",
        "require_ledger",
        "require_bibliography",
        "require_intake_report",
        "require_readme",
        "require_production_source",
    }
)

CONTRACT_ONLY_MODULES = (
    "test_contract.py",
    "test_controls_manifest.py",
    "test_packet_manifest.py",
)

IMPLEMENTATION_DEPENDENT_MODULES = (
    "test_inventory.py",
    "test_schema.py",
    "test_provenance.py",
    "test_quarantine.py",
)

#: Roots the acceptance suite itself may import. This is the SUITE's
#: allowance; the production allowance below is separate and narrower.
SUITE_ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "ast",
        "hashlib",
        "importlib",
        "json",
        "os",
        "pathlib",
        "re",
        "subprocess",
        "sys",
        "experiments",
        "pytest",
    }
)

#: An ALLOWLIST over import roots for the future implementation. A blocklist
#: would admit every network-capable package published tomorrow. Stated
#: honestly: this walks ``import`` and ``from ... import`` statements only. It
#: constrains what a production module can STATICALLY REACH. It is one layer
#: of a layered assurance and is **not** a proof of behavioural impossibility.
#: Human audit remains required.
PRODUCTION_ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "ntpath",
        "os",
        "pathlib",
        "re",
        "stat",
        "sys",
        "typing",
        "unicodedata",
    }
)

#: Refused by EXACT name. A prefix rule would also refuse an unrelated future
#: module whose dotted name merely begins with one of these.
FORBIDDEN_LEDGER_PACKAGES = frozenset(
    {
        "experiments.general_v7_ledger",
        "experiments.source_record",
        "experiments.tech_ledger",
        "experiments.uap_v6_ledger",
    }
)

# --------------------------------------------------------------------------
# Identity.
# --------------------------------------------------------------------------

LEDGER_ID = "general-v7-supplied-source-ledger-v1"
SCHEMA_ID = "supplied-source-v1"
CORPUS = "GENERAL V7 SUPPLIED SOURCE CORPUS"
NAMESPACE = "G7S-"

#: ``[0-9]`` rather than a digit shorthand: the shorthand matches Arabic-Indic
#: and Devanagari digits and ``int()`` parses them.
ID_PATTERN = r"\AG7S-(BAT|SRC|CLM|REL|UNR|COR|NAD)-[0-9]{4}\Z"
ID_RE = re.compile(ID_PATTERN)

DIGEST_PATTERN = r"\A[0-9a-f]{64}\Z"
DIGEST_RE = re.compile(DIGEST_PATTERN)

CONTROL_ID_PATTERN = re.compile(r"\Atest_g7s_([a-z])_([0-9]{3})_")

COLLECTIONS = (
    "batches",
    "sources",
    "claims",
    "relationships",
    "unresolved",
    "corrections",
    "non_admitted",
)

ID_SEGMENT_BY_COLLECTION = {
    "batches": "BAT",
    "sources": "SRC",
    "claims": "CLM",
    "relationships": "REL",
    "unresolved": "UNR",
    "corrections": "COR",
    "non_admitted": "NAD",
}

# --------------------------------------------------------------------------
# Closed vocabularies.
# --------------------------------------------------------------------------

ATTRIBUTION_CLASSES = (
    "supplied-by-kev-verbatim",
    "supplied-by-kev-inline",
    "packet-structural-fact",
    "aura-summary",
    "aura-inference",
    "seat-observation",
)

RELATIONSHIP_TYPES = (
    "same-supplied-identifier",
    "same-supplied-title-text",
    "shares-carrier-batch",
    "conflicts-with-supplied-material",
)

ORIGIN_TYPES = ("attachment", "inline_user_message")

RETRIEVAL_STATES = ("not-attempted",)
SOURCE_VERIFICATION_STATES = ("supplied-unretrieved",)
CLAIM_VERIFICATION_STATES = ("unverified",)
RELATIONSHIP_VERIFICATION_STATES = ("unverified",)
UNRESOLVED_STATES = ("unresolved",)

CORRECTION_KINDS = ("correction", "contest", "withdrawal", "supersession")

NON_ADMITTED_STATUSES = (
    "present-in-packet",
    "not-admitted",
    "non-executable",
    "non-normative",
)

#: The closed refusal vocabulary. A refusal carries exactly one of these and
#: never echoes the value it rejected. ``G7S-D-046`` pins this list against
#: CONTRACT.md section 11a; ``G7S-S-031`` pins it against the implementation.
REFUSAL_TOKENS = (
    "absence-representation-not-permitted",
    "attribution-class-not-permitted",
    "bool-not-integer",
    "correction-target-not-permitted",
    "duplicate-key",
    "duplicate-relationship",
    "encoding-not-permitted",
    "float-not-permitted",
    "integer-out-of-bounds",
    "malformed-document",
    "missing-key",
    "non-ascii-digit",
    "non-finite-not-permitted",
    "path-identity-changed",
    "path-not-relative",
    "path-reserved-component",
    "path-separator-not-permitted",
    "path-traversal",
    "reference-cycle",
    "reference-not-found",
    "relationship-endpoints-identical",
    "reparse-point-refused",
    "self-reference",
    "supersession-not-reciprocal",
    "unknown-key",
    "verification-state-not-permitted",
    "vocabulary-token-not-permitted",
    "wrong-type",
)

#: The minimal validator surface the future implementation must expose.
#: Declared here and in CONTRACT.md section 11a so the implementer has a fixed
#: target rather than a guess.
REQUIRED_VALIDATE_ATTRIBUTES = (
    "RefusalError",
    "validate_document",
    "validate_ledger_file",
)
REQUIRED_SCHEMA_ATTRIBUTES = (
    "REFUSAL_TOKENS",
    "KEYS_BY_COLLECTION",
    "canonical_bytes",
)

#: The declared field names per record kind, mirroring CONTRACT.md section 4b.
#: The acceptance surface uses exactly these and no others, and ``G7S-D-047``
#: proves the contract declares every one of them. Without this, the record
#: shape would be discoverable only by reading test source, and the contract's
#: promise of "a fixed target rather than a guess" would hold for the module
#: surface while quietly failing for the records themselves.
RECORD_FIELDS = {
    "root": (
        "schema_id",
        "ledger_id",
        "corpus",
        "counts",
    ),
    "batches": (
        "record_id",
        "batch_ordinal",
        "member_filename",
        "member_sha256",
        "packet_sha256",
        "origin_type",
        "origin_id",
        "line_ending_form",
    ),
    "sources": (
        "record_id",
        "supplied_locator",
        "normalized_locator",
        "normalized_identifier",
        "locator_absence_reason",
        "bibliography_entry",
        "supplied_text",
        "retrieval_state",
        "verification_state",
        "verification_evidence",
    ),
    "claims": (
        "record_id",
        "batch_ref",
        "attribution_class",
        "verification_state",
        "byte_evidence",
        "limitations",
    ),
    "relationships": (
        "record_id",
        "left_ref",
        "right_ref",
        "relationship_type",
        "verification_state",
    ),
    "unresolved": ("record_id", "state"),
    "corrections": (
        "record_id",
        "target_ref",
        "correction_kind",
        "reciprocal_ref",
    ),
    "non_admitted": (
        "record_id",
        "carrier_batch_ref",
        "carrier_member_sha256",
        "presence",
        "admission_status",
        "executable_status",
        "normative_status",
    ),
}

#: The only fields in which a locator may appear. Two supplied, two
#: normalized; CONTRACT.md section 4b closes the set.
LOCATOR_FIELDS = frozenset(
    {
        "supplied_locator",
        "supplied_text",
        "normalized_locator",
        "normalized_identifier",
    }
)

#: Fields the promotion-vocabulary prohibition binds. It reaches controlled
#: vocabularies and statuses ONLY: a supplied title containing "confirmed" is
#: preserved byte-for-byte under CONTRACT.md section 6.2, and a scan over
#: supplied text would make preservation and vocabulary unsatisfiable at once.
CONTROLLED_VOCABULARY_FIELDS = frozenset(
    {
        "attribution_class",
        "relationship_type",
        "retrieval_state",
        "verification_state",
        "state",
        "correction_kind",
        "presence",
        "admission_status",
        "executable_status",
        "normative_status",
        "locator_absence_reason",
    }
)

#: Documented so v1 inherits a specification rather than inventing one. Only
#: the first level is admissible in v1.
FUTURE_VERIFICATION_LADDER = (
    "supplied-unretrieved",
    "retrieval-attempted",
    "retrieved-unverified",
    "identity-verified",
    "content-verified",
)

#: Tokens the vocabularies must never acquire. Recording that material was
#: received is not endorsement of it.
FORBIDDEN_PROMOTION_FRAGMENTS = (
    "corrobor",
    "confirm",
    "proven",
    "proof",
    "authentic",
    "genuine",
    "credib",
    "endorse",
    "verified-by-agreement",
    "bridge",
)

#: Parameter names no public callable may accept. Duplicates are
#: cross-referenced, never removed.
FORBIDDEN_COLLAPSE_PARAMETERS = ("dedupe", "unique", "distinct", "merge", "collapse")

# --------------------------------------------------------------------------
# Archive-level packet constants. Reproduced by the authoring seat from the
# packet bytes and witnessed by PACKET_RECEIPT.md.
#
# The packet is NOT committed to this repository. No control reads it at run
# time. The receipt is the committed witness for these, and they are
# reconciled against that document rather than against the archive.
# --------------------------------------------------------------------------

PACKET_ARCHIVE_NAME = "general-v7-material-packet-2026-08-29.zip"
PACKET_ARCHIVE_BYTES = 191457
PACKET_ARCHIVE_SHA256 = (
    "fd468794e8b228ab2e2cffe3cde42915a6d0d18430a91c745dabeaa83df2fe89"
)
PACKET_NESTED_ROOT = "general-v7-material-packet-2026-08-29/"
PACKET_ENTRY_COUNT = 65
PACKET_DIRECTORY_ENTRY_COUNT = 0
PACKET_FILE_ENTRY_COUNT = 65
PACKET_MEMBER_CHECKSUMS = 64
PACKET_CHECKSUMS_PASSED = 64
PACKET_CHECKSUMS_FAILED = 0
PACKET_MEMBER_BYTES = 384106
PACKET_SUMS_SHA256 = (
    "1ad2b0bc842fcf79e7d16d310bc7f324007dafb856d18144bba7988b59f17686"
)
PACKET_ORIGINS_SHA256 = (
    "c16f5815a9abf5a56ee3e7225c35c9e432ce09fcbeb00d996a735cf79789005d"
)

# --------------------------------------------------------------------------
# Content-derived packet facts. Reproduced from packet CONTENT and witnessed
# by CONTRACT.md section 5a, **not** by the receipt: none of 60, 26 or the
# ORIGINS.tsv row count appears in PACKET_RECEIPT.md at all. The two
# exceptions are the supplied-batch count and the inline-row count, which both
# documents record and for which the receipt is authoritative.
# --------------------------------------------------------------------------

EXPECTED_BATCHES = 63
EXPECTED_ORIGIN_ROWS = 63
EXPECTED_ATTACHMENT_ROWS = 60
EXPECTED_INLINE_ROWS = 3
EXPECTED_BIBLIOGRAPHY_ENTRIES = 26
EXPECTED_VIDEO_IDENTIFIERS = 26

# --------------------------------------------------------------------------
# ADMISSION AND PROCESS STANDING. **Not packet-derived.**
#
# These record what THIS admission process did and where THIS ledger's
# boundary was drawn. No reading of the packet could establish any of them,
# and no control may describe them as reproduced from packet bytes.
#
# The four retrieval and verification values are counted: a population exists
# and the count over it is zero. The two corpus values are different in kind
# --- the schema exposes no record type into which a UAP V6 or Bridge Register
# record could be placed, so there is nothing to enumerate and the zero
# records a structural impossibility rather than an empty search. CONTRACT.md
# section 5b keeps the two kinds of zero apart.
# --------------------------------------------------------------------------

EXPECTED_RETRIEVED = 0
EXPECTED_VERIFIED_SOURCES = 0
EXPECTED_VERIFIED_CLAIMS = 0
EXPECTED_VERIFIED_RELATIONSHIPS = 0
EXPECTED_ADMITTED_UAP_V6_RECORDS = 0
EXPECTED_ADMITTED_BRIDGE_RECORDS = 0

LINE_ENDING_CENSUS = {
    "crlf-only": 62,
    "lf-only": 1,
    "mixed": 2,
    "none": 0,
}

#: PRIOR INTERPRETIVE EXPECTATIONS. These were NOT reproduced from packet
#: structure by this phase; they are inherited from the adjacent
#: ``general-v7-technology-ledger-v1`` laboratory. They are recorded so an
#: auditor can see what was expected, and they are **never** asserted as
#: structural facts. ``G7S-D-012`` and ``G7S-M-036`` keep them out of both
#: frozen classes.
#:
#: ``identities_with_exact_locator`` is inherited too, and is listed here so
#: the reconciliation 26 + 35 = 61 closes **within this dict**. An earlier
#: form spent ``EXPECTED_VIDEO_IDENTIFIERS`` --- a frozen packet fact --- as
#: the 26, which made an inherited, unreproduced relation load-bearing on a
#: reproduced constant: correcting the packet figure would have failed an
#: interpretive reconciliation, and the failure would have read as a
#: structural defect. The two 26s coincide; they are not the same quantity.
PRIOR_INTERPRETIVE_EXPECTATIONS = {
    "provisional_source_identities": 61,
    "identities_without_exact_locator": 35,
    "identities_with_exact_locator": 26,
    "non_admitted_artifacts": 3,
}

#: The two evidence classes a frozen figure may carry. A figure's class is a
#: STORED fact, not an implication of which literal it was typed into.
PACKET_DERIVED = "packet-derived"
ADMISSION_STANDING = "admission-standing"
EVIDENCE_CLASSES = (PACKET_DERIVED, ADMISSION_STANDING)

#: The single classified source of truth for every frozen figure.
#:
#: One dict, one class token per key. This shape is deliberate. Two sibling
#: dicts would store the classification *nowhere* --- it would be implied by
#: which literal a row was typed into, so swapping one packet fact for one
#: admission value between them would keep both sets disjoint, keep the union
#: at twelve names, and silently redraw the class boundary with nothing able
#: to see it. Here a key has exactly one class and a re-merge is not
#: expressible; ``G7S-M-037`` pins the key-to-class map literally, so a class
#: swap is a one-token diff caught by one equality.
#:
#: Every value binds by REFERENCE to its constant above. Authoring these as
#: bare integer literals would make the table an independent copy that could
#: drift from the constant it claims to mirror.
FROZEN_INVENTORY = {
    "batches": (EXPECTED_BATCHES, PACKET_DERIVED),
    "origin_rows": (EXPECTED_ORIGIN_ROWS, PACKET_DERIVED),
    "attachment_rows": (EXPECTED_ATTACHMENT_ROWS, PACKET_DERIVED),
    "inline_rows": (EXPECTED_INLINE_ROWS, PACKET_DERIVED),
    "bibliography_entries": (EXPECTED_BIBLIOGRAPHY_ENTRIES, PACKET_DERIVED),
    "video_identifiers": (EXPECTED_VIDEO_IDENTIFIERS, PACKET_DERIVED),
    "retrieved": (EXPECTED_RETRIEVED, ADMISSION_STANDING),
    "verified_sources": (EXPECTED_VERIFIED_SOURCES, ADMISSION_STANDING),
    "verified_claims": (EXPECTED_VERIFIED_CLAIMS, ADMISSION_STANDING),
    "verified_relationships": (EXPECTED_VERIFIED_RELATIONSHIPS, ADMISSION_STANDING),
    "admitted_uap_v6_records": (
        EXPECTED_ADMITTED_UAP_V6_RECORDS,
        ADMISSION_STANDING,
    ),
    "admitted_bridge_records": (
        EXPECTED_ADMITTED_BRIDGE_RECORDS,
        ADMISSION_STANDING,
    ),
}


def _view(evidence_class: str) -> dict:
    return {
        key: value
        for key, (value, carried) in FROZEN_INVENTORY.items()
        if carried == evidence_class
    }


#: Figures reproduced from packet structure or packet content.
FROZEN_PACKET_FACTS = _view(PACKET_DERIVED)

#: Facts about this admission process and this ledger's boundary. Derived, so
#: the two views can never disagree with the classification above.
FROZEN_ADMISSION_STANDING = _view(ADMISSION_STANDING)

#: Controls whose bodies legitimately contain absolute-, UNC- and
#: device-shaped path STRINGS, because their whole purpose is to hand such a
#: path to the validator and require a refusal. ``G7S-R-020`` exempts these
#: bodies and only these; everywhere else an absolute path constant is a
#: defect, because it is how a suite starts reaching outside its laboratory.
SYNTHETIC_PATH_FIXTURE_CONTROLS = ("G7S-S-027",)

#: Canary values. A refusal must never echo the value it rejected, so a
#: rejected payload carries one of these and the rendered message must not.
MARKER_VALUE = "canary-value-4f9a2c17-do-not-echo"
MARKER_KEY = "canary-key-8b3e6d05-do-not-echo"
MARKERS = (MARKER_VALUE, MARKER_KEY)

#: The three documents that may each be lifted out of the laboratory alone.
#: Each must carry its own boundary statement rather than relying on a sibling
#: to disclaim on its behalf.
LIFTABLE_DOCUMENTS = ("BIBLIOGRAPHY.md", "INTAKE_REPORT.md", "README.md")

# --------------------------------------------------------------------------
# Retired controls. Nothing is silently deleted: a retired id is never reused
# and never renumbered, so an auditor reading an earlier handback can look one
# up and find that it was withdrawn rather than find a different control
# wearing its name. ``G7S-M-006`` enforces both halves.
# --------------------------------------------------------------------------

RETIRED_CONTROLS: dict = {}

# --------------------------------------------------------------------------
# Precise absence detection.
# --------------------------------------------------------------------------

IMPLEMENTATION_ABSENT = "implementation-absent"

#: ``ERROR_FILENAME_EXCED_RANGE``. Windows maps it onto ``FileNotFoundError``
#: alongside genuine absence, and "too long" is not "absent".
PATH_TOO_LONG_WINERROR = 206

INIT_MODULE = "experiments.general_v7_supplied_source_ledger"
SCHEMA_MODULE = "experiments.general_v7_supplied_source_ledger.schema"
VALIDATE_MODULE = "experiments.general_v7_supplied_source_ledger.validate"

PRODUCTION_MODULES = ("__init__.py", "schema.py", "validate.py")


def absent(label: str) -> AssertionError:
    """The single factory for the absence token. Always raised, never returned.

    ``G7S-M-028`` proves every call site raises the result, and
    ``G7S-M-029`` proves the token is produced nowhere else.
    """
    return AssertionError(
        f"{IMPLEMENTATION_ABSENT}: {label} is not present; implementation is "
        f"not yet authorized"
    )


def harness_fault(detail: str) -> AssertionError:
    """A fault in the test harness, deliberately not carrying the absence token."""
    return AssertionError(f"harness-fault: {detail}")


def entry_is_absent(path: pathlib.Path) -> bool:
    """True only when the named entry is *genuinely* missing.

    ``Path.exists()`` is unusable here: it swallows ``PermissionError`` and
    every other ``OSError`` into a bare ``False``, so an unreadable directory
    would read as an unwritten implementation. ``lstat`` is used instead and
    **only ``FileNotFoundError`` counts as absence**; every other ``OSError``
    propagates. ``lstat`` does not follow links, so a dangling symlink or
    junction is present-but-invalid, never absent.
    """
    try:
        os.lstat(path)
    except FileNotFoundError as error:
        if getattr(error, "winerror", None) == PATH_TOO_LONG_WINERROR:
            raise
        return True
    return False


def laboratory_state(names) -> str:
    """Classify the laboratory into exactly one of two admissible states.

    Nothing here asserts the implementation surface is absent. A control that
    can only be made green by deleting a file is an obstacle, not evidence.
    """
    present = [name for name in IMPLEMENTATION_PATHS if name in names]
    if not present:
        return PRE_IMPLEMENTATION_STATE
    if len(present) == len(IMPLEMENTATION_PATHS):
        return IMPLEMENTED_STATE
    raise AssertionError(
        f"partial implementation surface is not an admissible state: "
        f"present={sorted(present)}"
    )


def laboratory_file_names() -> frozenset:
    """Top-level entry names in the laboratory, excluding caches."""
    return frozenset(
        entry.name
        for entry in LAB_DIR.iterdir()
        if entry.name not in ("__pycache__", ".pytest_cache")
    )


# --------------------------------------------------------------------------
# Gate helpers. Each of these touches an IMPLEMENTATION path, so any control
# calling one is implementation-dependent by construction.
# --------------------------------------------------------------------------


def _require_implementation_file(path: pathlib.Path, label: str) -> str:
    if entry_is_absent(path):
        raise absent(label)
    return path.read_text(encoding="utf-8")


def _require_module(dotted_name: str, module_path: pathlib.Path):
    """Import an expected module.

    Only a genuinely missing entry is absence. Once the entry exists,
    ``import_module`` runs unguarded: an ``ImportError`` raised inside it, a
    syntax error or a decoding failure all propagate as themselves and are
    never recategorized.

    The entry is checked by *path* but imported by *dotted name*, and those two
    can diverge. The module that comes back is therefore required to be the
    entry that was inspected; a divergence is a harness fault that does not
    carry the absence token, because a stale ``sys.modules`` entry or a
    shadowing ``sys.path`` root is not an unwritten implementation.
    """
    if entry_is_absent(module_path):
        raise absent(module_path.name)
    module = importlib.import_module(dotted_name)
    bound = getattr(module, "__file__", None)
    if bound is None or pathlib.Path(bound).resolve() != module_path.resolve():
        raise harness_fault(
            f"module identity divergence: {dotted_name!r} bound to {bound!r}, "
            f"which is not the entry that was inspected, {str(module_path)!r}"
        )
    return module


def require_init():
    return _require_module(INIT_MODULE, INIT_PATH)


def require_schema():
    return _require_module(SCHEMA_MODULE, SCHEMA_PATH)


def require_validate():
    return _require_module(VALIDATE_MODULE, VALIDATE_PATH)


def require_production_source(name: str) -> str:
    """The source text of one production module, for static scanning."""
    if name not in PRODUCTION_MODULES:
        raise harness_fault(f"{name!r} is not a production module")
    return _require_implementation_file(LAB_DIR / name, name)


def require_bibliography() -> str:
    return _require_implementation_file(BIBLIOGRAPHY_PATH, "BIBLIOGRAPHY.md")


def require_intake_report() -> str:
    return _require_implementation_file(INTAKE_REPORT_PATH, "INTAKE_REPORT.md")


def require_readme() -> str:
    return _require_implementation_file(README_PATH, "README.md")


def require_ledger() -> dict:
    """Load ``ledger.json``.

    Absence is absence. A malformed document raises its own parse error and is
    never recategorized: a broken ledger must not read as an unwritten one.
    """
    if entry_is_absent(LEDGER_PATH):
        raise absent("ledger.json")
    text = LEDGER_PATH.read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise AssertionError(f"ledger.json root is {type(value).__name__}, not a dict")
    return value


# --------------------------------------------------------------------------
# Files present in BOTH states. These are not gate helpers.
# --------------------------------------------------------------------------


def require_file(path: pathlib.Path, label: str) -> str:
    """Return an expected file's text.

    Absence is absence. A permission failure, a directory where a file was
    expected and a decoding failure all propagate unchanged.
    """
    if entry_is_absent(path):
        raise harness_fault(f"{label} is missing from the phase-A surface")
    return path.read_text(encoding="utf-8")


def contract_text() -> str:
    return require_file(CONTRACT_PATH, "CONTRACT.md")


def receipt_text() -> str:
    return require_file(RECEIPT_PATH, "PACKET_RECEIPT.md")


# --------------------------------------------------------------------------
# Provenance reads. The committed blob, never the checkout.
# --------------------------------------------------------------------------


def committed_blob(relative_posix_path: str) -> bytes:
    """The bytes Git has stored for a tracked path, index first then HEAD.

    Not the working tree. This repository enables ``core.autocrlf``, which
    rewrites LF to CRLF on checkout, so a working-tree byte check would report
    a line-ending defect that does not exist in the repository and would fail
    on a fresh clone. The blob is the only durable provenance and is what every
    consumer of this repository actually receives.

    The index is consulted first so the property is checkable once the files
    are staged, before the commit exists. A read failure is a harness fault
    with its own reason and never reports as an absent implementation.
    """
    for spec in (f":{relative_posix_path}", f"HEAD:{relative_posix_path}"):
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "-p", spec],
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            return completed.stdout
    raise harness_fault(
        f"cannot read the committed blob for {relative_posix_path} from the "
        f"index or from HEAD; line-ending provenance is established from Git, "
        f"never from the checkout"
    )


def blob_defects(raw: bytes) -> list:
    """Every whitespace and encoding defect in one committed blob."""
    defects = []
    if not raw:
        defects.append("empty blob")
        return defects
    if b"\r" in raw:
        defects.append("carriage return present; committed blobs are LF-only")
    if b"\t" in raw:
        defects.append("tab present")
    if raw.startswith(b"\xef\xbb\xbf"):
        defects.append("byte-order mark present")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        defects.append("not valid UTF-8")
        return defects
    if not raw.endswith(b"\n"):
        defects.append("no final newline")
    if raw.endswith(b"\n\n"):
        defects.append("more than one final newline")
    for number, line in enumerate(text.split("\n"), 1):
        if line != line.rstrip():
            defects.append(f"trailing whitespace on line {number}")
            break
    return defects


def tracked_lab_paths() -> list:
    """Paths Git tracks under the laboratory, as POSIX strings."""
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "--", LAB_POSIX],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise harness_fault("git ls-files failed for the laboratory path")
    return [line for line in completed.stdout.splitlines() if line]


# --------------------------------------------------------------------------
# Canonical form.
# --------------------------------------------------------------------------


def canonical_bytes(value) -> bytes:
    """Sorted keys, ASCII escaping, compact separators, no trailing newline."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


# --------------------------------------------------------------------------
# Text helpers.
# --------------------------------------------------------------------------


def flat(text: str) -> str:
    """Collapse every whitespace run to a single space.

    Phrase controls must be independent of where a paragraph happens to wrap,
    or reflowing a document silently retires a control.
    """
    return " ".join(text.split())


def control_id_of(function_name: str):
    match = CONTROL_ID_PATTERN.match(function_name)
    if match is None:
        return None
    return f"G7S-{match.group(1).upper()}-{match.group(2)}"


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
