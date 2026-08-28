"""Shared support for the ``general-v7-technology-ledger-v1`` acceptance suite.

Nothing here imports an implementation module at import time, so
``--collect-only`` succeeds against an empty laboratory.

**Absence is detected precisely.** Only the exact absence of an expected file
is reported as ``implementation-absent``. An import error raised *inside* a
present module, a permission failure, a wrong type, or a malformed ledger all
propagate unchanged: a broken implementation must never be able to disguise
itself as an unwritten one. Missing implementation is an ordinary assertion
failure — never skipped, never xfail.

Nothing in this module retrieves, opens, resolves, or contacts a locator, and
no locator string here refers to a real resource.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys

# --------------------------------------------------------------------------
# Paths, computed from this file alone. Nothing is searched or crawled.
# --------------------------------------------------------------------------

TESTS_DIR = pathlib.Path(__file__).resolve().parent
LAB_DIR = TESTS_DIR.parent
EXPERIMENTS_DIR = LAB_DIR.parent
REPO_ROOT = EXPERIMENTS_DIR.parent

CONTRACT_PATH = LAB_DIR / "CONTRACT.md"
SCHEMA_PATH = LAB_DIR / "schema.py"
VALIDATE_PATH = LAB_DIR / "validate.py"
LEDGER_PATH = LAB_DIR / "ledger.json"
BIBLIOGRAPHY_PATH = LAB_DIR / "BIBLIOGRAPHY.md"
INTAKE_REPORT_PATH = LAB_DIR / "INTAKE_REPORT.md"
README_PATH = LAB_DIR / "README.md"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------
# Precise absence detection.
# --------------------------------------------------------------------------

IMPLEMENTATION_ABSENT = "implementation-absent"

SCHEMA_MODULE = "experiments.general_v7_ledger.schema"
VALIDATE_MODULE = "experiments.general_v7_ledger.validate"


def absent(label: str) -> AssertionError:
    return AssertionError(
        f"{IMPLEMENTATION_ABSENT}: {label} is not present; implementation is "
        f"not yet authorized"
    )


def require_module(dotted_name: str, module_path: pathlib.Path):
    """Import an expected module.

    Only the exact non-existence of ``module_path`` is absence. Once the file
    exists, ``import_module`` runs unguarded: an ``ImportError`` raised inside
    it, a syntax error, or any other failure propagates and is reported as
    itself.
    """
    if not module_path.exists():
        raise absent(module_path.name)
    return importlib.import_module(dotted_name)


def require_schema():
    return require_module(SCHEMA_MODULE, SCHEMA_PATH)


def require_validate():
    return require_module(VALIDATE_MODULE, VALIDATE_PATH)


def require_file(path: pathlib.Path, label: str) -> str:
    """Return an expected file's text.

    Absence is absence. A permission failure or any other ``OSError``
    propagates unchanged.
    """
    if not path.exists():
        raise absent(label)
    return path.read_text(encoding="utf-8")


def load_json_file(path: pathlib.Path, label: str):
    """Parse an expected JSON file.

    Absence is absence. **A malformed document is not absence**: the parser's
    ``ValueError`` propagates, so a broken ledger can never be mistaken for an
    unwritten one.
    """
    if not path.exists():
        raise absent(label)
    return json.loads(path.read_text(encoding="utf-8"))


def require_ledger() -> dict:
    return load_json_file(LEDGER_PATH, "ledger.json")


# --------------------------------------------------------------------------
# Canonical form and digest. CONTRACT.md section 6i.
# --------------------------------------------------------------------------


def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_digest(obj) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


# --------------------------------------------------------------------------
# Deterministic reparse-point fixture, following the accepted neutral
# source-record approach. tmp_path only; never inside the repository.
# --------------------------------------------------------------------------


def make_reparse_directory(link: pathlib.Path, target: pathlib.Path) -> str:
    """Create a directory link-or-junction at ``link`` pointing at ``target``.

    Returns the mechanism used. Raises ``AssertionError`` if none is
    available: this control is never skipped, never marked xfail, and never
    passes conditionally. It changes no machine setting and needs no
    Developer Mode or administrator privilege — a Windows directory junction
    is creatable unprivileged, and it is the harder fixture besides, because
    ``os.path.islink`` and ``Path.is_symlink`` both report it as False.
    """
    try:
        os.symlink(target, link, target_is_directory=True)
        return "os.symlink"
    except (OSError, NotImplementedError, AttributeError):
        pass
    if sys.platform == "win32":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0 and link.exists():
            return "mklink-junction"
    raise AssertionError(
        "no deterministic reparse-point mechanism is available on this "
        "platform; the path-security control cannot be constructed and must "
        "not be skipped"
    )


def is_reparse_point(path: pathlib.Path) -> bool:
    """True for a symbolic link or a Windows reparse point."""
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


# --------------------------------------------------------------------------
# Recursive string-leaf walk, for payload screening that is not defeated by
# JSON escaping of a whole-document rendering.
# --------------------------------------------------------------------------


def string_leaves(obj, path=()):
    """Yield ``(path, value)`` for every string leaf, recursively."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key in sorted(obj):
            yield from string_leaves(obj[key], path + (key,))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from string_leaves(item, path + (index,))


# --------------------------------------------------------------------------
# Frozen identity and vocabularies, mirrored from CONTRACT.md.
# --------------------------------------------------------------------------

SCHEMA_ID = "source-record-v3"
LEDGER_ID = "general-v7-technology-ledger-v1"
CORPUS = "GENERAL V7 TECHNOLOGY CORPUS"
INTAKE_STATE = "intake-complete"

ID_PATTERN = r"\AGV7-(BAT|SRC|CLM|REL|UNR|ART|COR)-[0-9]{4}\Z"
ID_RE = re.compile(ID_PATTERN)
DIGEST_PATTERN = r"\A[0-9a-f]{64}\Z"
DIGEST_RE = re.compile(DIGEST_PATTERN)

ROOT_KEYS = frozenset(
    {
        "schema",
        "ledger_id",
        "corpus",
        "intake_state",
        "batches",
        "sources",
        "claims",
        "relationships",
        "unresolved",
        "artifacts",
        "corrections",
    }
)

COLLECTION_KEYS = (
    "batches",
    "sources",
    "claims",
    "relationships",
    "unresolved",
    "artifacts",
    "corrections",
)

ID_FIELD_BY_COLLECTION = {
    "batches": "batch_id",
    "sources": "source_id",
    "claims": "claim_id",
    "relationships": "relationship_id",
    "unresolved": "unresolved_id",
    "artifacts": "artifact_id",
    "corrections": "correction_id",
}

BATCH_KEYS = frozenset(
    {
        "batch_id",
        "batch_ordinal",
        "batch_kind",
        "introduces_sources",
        "introduces_artifacts",
        "updates_sources",
        "supplied_by_role",
        "supplied_by_label",
        "notes",
    }
)

SOURCE_KEYS = frozenset(
    {
        "source_id",
        "batch_ref",
        "supplied_title",
        "supplied_creator",
        "supplied_locator",
        "normalized_locator",
        "locator_absence",
        "supplied_date",
        "carrier_role",
        "carrier_label",
        "upstream_attribution",
        "metadata_provenance",
        "retrieval_state",
        "verification_state",
        "limitations",
        "safety_dispositions",
        "supersedes",
    }
)

CLAIM_KEYS = frozenset(
    {
        "claim_id",
        "source_ref",
        "batch_ref",
        "claim_text",
        "attribution_class",
        "evidence_basis",
        "limitations",
        "safety_dispositions",
        "verification_state",
        "supersedes",
    }
)

RELATIONSHIP_KEYS = frozenset(
    {
        "relationship_id",
        "left_ref",
        "right_ref",
        "relationship_type",
        "basis",
        "attribution_class",
        "verification_state",
        "limitations",
        "recorded_by_role",
        "recorded_by_label",
    }
)

UNRESOLVED_KEYS = frozenset(
    {
        "unresolved_id",
        "conflict_family",
        "statement",
        "positions",
        "refs",
        "resolution_state",
        "recorded_by_role",
        "recorded_by_label",
    }
)

ARTIFACT_KEYS = frozenset(
    {
        "artifact_id",
        "introducing_batch",
        "artifact_class",
        "identity_origin",
        "preservation_status",
        "rejection_basis",
        "executable_status",
        "safety_dispositions",
        "summary",
    }
)

CORRECTION_KEYS = frozenset(
    {
        "correction_id",
        "target_ref",
        "correction_kind",
        "statement",
        "recorded_by_role",
        "recorded_by_label",
    }
)

SUPERSEDES_KEYS = frozenset({"record_id", "content_digest"})

KEYS_BY_COLLECTION = {
    "batches": BATCH_KEYS,
    "sources": SOURCE_KEYS,
    "claims": CLAIM_KEYS,
    "relationships": RELATIONSHIP_KEYS,
    "unresolved": UNRESOLVED_KEYS,
    "artifacts": ARTIFACT_KEYS,
    "corrections": CORRECTION_KEYS,
}

BATCH_KINDS = ("source-bearing", "artifact-bearing", "bibliography-metadata")

ROLES = (
    "relay-agent",
    "operator",
    "auditor",
    "analysis-seat",
    "external-author",
    "unattributed",
)

#: Eleven classes. ``kev-observation`` and ``kev-authorization`` are distinct:
#: an attributed historical authorization is evidence that authorization
#: language was supplied, never current runtime authority.
ATTRIBUTION_CLASSES = (
    "direct-source",
    "source-derived-excerpt",
    "aura-summary",
    "aura-inference",
    "aura-capability-claim",
    "kev-observation",
    "kev-authorization",
    "jack-inference-or-audit",
    "eighty-four-inference",
    "implementation-proposal",
    "verified-implementation-evidence",
)

#: The retired compound token. It must never validate again.
RETIRED_ATTRIBUTION_CLASSES = ("kev-observation-or-authorization",)

#: A relationship records who noticed a relation. It can never be evidence.
RELATIONSHIP_ATTRIBUTION_CLASSES = tuple(
    value
    for value in ATTRIBUTION_CLASSES
    if value != "verified-implementation-evidence"
)

RETRIEVAL_STATES = ("not-attempted",)
SOURCE_VERIFICATION_STATES = ("supplied-unretrieved",)
CLAIM_VERIFICATION_STATES = ("unverified",)
RELATIONSHIP_VERIFICATION_STATES = ("unverified",)
UNRESOLVED_STATES = ("unresolved",)
PRESERVATION_STATES = ("preserved",)
EXECUTABLE_STATES = ("non-executable",)
IDENTITY_ORIGINS = ("supplied", "generated")

METADATA_PROVENANCE = (
    "supplied-by-carrier",
    "supplied-by-operator",
    "derived-from-supplied-text",
    "not-supplied",
)

LOCATOR_ABSENCE_REASONS = (
    "no-exact-locator-supplied",
    "locator-withheld-by-carrier",
    "locator-not-applicable",
)

RELATIONSHIP_TYPES = (
    "duplicate-of-supplied-material",
    "conflicts-with",
    "follow-up-to",
    "mirror-of-supplied-material",
    "same-supplied-topic",
    "derived-from-supplied-material",
)

RELATIONSHIP_BASES = (
    "recorded-by-inspection",
    "recorded-from-supplied-material",
    "recorded-as-proposed-elsewhere",
)

CORRECTION_KINDS = ("correction", "contest", "successor")

ARTIFACT_CLASSES = (
    "premature-synthesis",
    "premature-master-prompt",
    "premature-authorization",
)

ORDINARY_DISPOSITION = "ordinary"

SAFETY_DISPOSITIONS = (
    "ordinary",
    "quarantined-access-control-avoidance",
    "quarantined-covert-communication",
    "quarantined-credential-or-personal-data",
    "quarantined-unauthorized-external-interaction",
    "quarantined-self-replication-or-mutation",
    "quarantined-hidden-monitoring",
    "quarantined-unsigned-native-execution",
    "quarantined-destructive-storage-or-cooling",
)

CONFLICT_FAMILIES = (
    "ox-alpha-versus-qwen-core-identity",
    "local-only-versus-external-endpoints",
    "modular-hot-swap-versus-monolith",
    "zero-dependency-versus-third-party-dependencies",
    "transient-agents-versus-persistent-residency",
    "no-magic-numbers-versus-fixed-thresholds",
    "immutable-raw-provenance-versus-raw-deletion",
    "human-oversight-versus-autonomous-execution",
    "aura-capability-inconsistency",
    "missing-source-identity-or-bibliography-data",
    "unsupported-hardware-or-product-claim",
    "scientific-analogy-overreach",
    "quarantined-security-or-privacy-proposal",
)

LABEL_MAX = 128
TEXT_MAX = 8192
LIST_MAX = 64
MAX_LEDGER_BYTES = 4194304
NOT_SUPPLIED = "not-supplied"

# --------------------------------------------------------------------------
# Frozen inventory.
# --------------------------------------------------------------------------

EXPECTED_BATCHES = 63
EXPECTED_SOURCES = 61
EXPECTED_ARTIFACTS = 3
EXPECTED_SOURCES_WITH_LOCATOR = 26
EXPECTED_SOURCES_WITHOUT_LOCATOR = 35
EXPECTED_RETRIEVED = 0
EXPECTED_VERIFIED_SOURCES = 0
EXPECTED_VERIFIED_CLAIMS = 0
EXPECTED_BRIDGE_RECORDS = 0

#: Actual artifact provenance. The three artifacts arrived in three different
#: batches; only the third arrived in batch 62.
ARTIFACT_BATCHES = {
    "GV7-ART-0001": "GV7-BAT-0010",
    "GV7-ART-0002": "GV7-BAT-0022",
    "GV7-ART-0003": "GV7-BAT-0062",
}
ARTIFACT_IDS = tuple(sorted(ARTIFACT_BATCHES))
ARTIFACT_BEARING_BATCH = "GV7-BAT-0062"
BIBLIOGRAPHY_BATCH = "GV7-BAT-0063"

SOURCES_WITHOUT_LOCATOR = tuple(f"GV7-SRC-{n:04d}" for n in range(1, 36))
SOURCES_WITH_LOCATOR = tuple(f"GV7-SRC-{n:04d}" for n in range(36, 62))
ALL_SOURCE_IDS = SOURCES_WITHOUT_LOCATOR + SOURCES_WITH_LOCATOR

NETWORK_CAPABLE_MODULES = (
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "ftplib",
    "smtplib",
    "telnetlib",
    "asyncio",
    "subprocess",
    "importlib",
    "webbrowser",
    "xmlrpc",
)

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

MARKER_VALUE = "canary-value-1d7c4b93-do-not-echo"
MARKER_KEY = "canary-key-6a2f8e05-do-not-echo"
MARKERS = (MARKER_VALUE, MARKER_KEY)


def collection_of(ledger: dict, key: str) -> list:
    value = ledger.get(key)
    assert isinstance(value, list), f"{key}: expected a list"
    return value


def identifiers(records: list, field: str) -> list:
    return [record[field] for record in records]


def all_identifiers(ledger: dict) -> set:
    found = set()
    for collection, field in ID_FIELD_BY_COLLECTION.items():
        found |= set(identifiers(ledger.get(collection, []), field))
    return found
