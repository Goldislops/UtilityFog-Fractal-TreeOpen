"""Shared support for the ``general-v7-technology-ledger-v1`` acceptance suite.

Nothing here imports an implementation module at import time. Every
implementation dependency is resolved *inside* a test through
``require_module`` and its wrappers, so ``--collect-only`` succeeds against an
empty laboratory and the full run fails for one clearly attributable reason.

Missing implementation is reported as an ordinary assertion failure. It is
never skipped and never marked xfail: an absent implementation is a red
acceptance surface, not an excused one.

Nothing in this module retrieves, opens, resolves, or contacts a locator, and
no locator string here refers to a real resource.
"""

from __future__ import annotations

import importlib
import pathlib
import re
import sys

# --------------------------------------------------------------------------
# Paths, computed from this file alone. Nothing is searched or crawled.
# --------------------------------------------------------------------------

TESTS_DIR = pathlib.Path(__file__).resolve().parent
LAB_DIR = TESTS_DIR.parent
EXPERIMENTS_DIR = LAB_DIR.parent
REPO_ROOT = EXPERIMENTS_DIR.parent

CONTRACT_PATH = LAB_DIR / "CONTRACT.md"
LEDGER_PATH = LAB_DIR / "ledger.json"
BIBLIOGRAPHY_PATH = LAB_DIR / "BIBLIOGRAPHY.md"
INTAKE_REPORT_PATH = LAB_DIR / "INTAKE_REPORT.md"
README_PATH = LAB_DIR / "README.md"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------
# Implementation-absent reporting.
# --------------------------------------------------------------------------

IMPLEMENTATION_ABSENT = "implementation-absent"

SCHEMA_MODULE = "experiments.general_v7_ledger.schema"
VALIDATE_MODULE = "experiments.general_v7_ledger.validate"


def require_module(dotted_name: str):
    try:
        return importlib.import_module(dotted_name)
    except ImportError:
        raise AssertionError(
            f"{IMPLEMENTATION_ABSENT}: {dotted_name} is not present; "
            f"implementation is not yet authorized"
        ) from None


def require_schema():
    return require_module(SCHEMA_MODULE)


def require_validate():
    return require_module(VALIDATE_MODULE)


def require_file(path: pathlib.Path, label: str) -> str:
    """Return a required future file's text, or fail the calling test clearly.

    This asserts a file is *required*. It never asserts a file is absent: this
    is a sparse worktree, so on-disk absence proves nothing about the
    repository.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        raise AssertionError(
            f"{IMPLEMENTATION_ABSENT}: {label} is not present; "
            f"implementation is not yet authorized"
        ) from None


def require_ledger() -> dict:
    """Return the parsed committed ledger, or fail the calling test clearly."""
    import json

    text = require_file(LEDGER_PATH, "ledger.json")
    try:
        return json.loads(text)
    except ValueError:
        raise AssertionError(
            f"{IMPLEMENTATION_ABSENT}: ledger.json is not parseable JSON"
        ) from None


# --------------------------------------------------------------------------
# Frozen identity and vocabularies, mirrored from CONTRACT.md so a drift
# between the suite and the implementation is itself detectable.
# --------------------------------------------------------------------------

SCHEMA_ID = "source-record-v3"
LEDGER_ID = "general-v7-technology-ledger-v1"
CORPUS = "GENERAL V7 TECHNOLOGY CORPUS"
INTAKE_STATE = "intake-complete"

ID_PATTERN = r"\AGV7-(BAT|SRC|CLM|REL|UNR|ART|COR)-[0-9]{4}\Z"
ID_RE = re.compile(ID_PATTERN)
DIGEST_PATTERN = r"\A[0-9a-f]{64}\Z"

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
        "safety_disposition",
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
        "safety_disposition",
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
        "safety_disposition",
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

BATCH_KINDS = ("source-bearing", "artifact-bearing", "bibliography-metadata")

ROLES = (
    "relay-agent",
    "operator",
    "auditor",
    "analysis-seat",
    "external-author",
    "unattributed",
)

ATTRIBUTION_CLASSES = (
    "direct-source",
    "source-derived-excerpt",
    "aura-summary",
    "aura-inference",
    "aura-capability-claim",
    "kev-observation-or-authorization",
    "jack-inference-or-audit",
    "eighty-four-inference",
    "implementation-proposal",
    "verified-implementation-evidence",
)

RETRIEVAL_STATES = ("not-attempted",)
SOURCE_VERIFICATION_STATES = ("supplied-unretrieved",)
CLAIM_VERIFICATION_STATES = ("unverified",)
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

ARTIFACT_IDS = ("GV7-ART-0001", "GV7-ART-0002", "GV7-ART-0003")
ARTIFACT_BEARING_BATCH = "GV7-BAT-0062"
BIBLIOGRAPHY_BATCH = "GV7-BAT-0063"

#: GV7-SRC-0001 .. GV7-SRC-0035 carry no exact supplied locator.
SOURCES_WITHOUT_LOCATOR = tuple(f"GV7-SRC-{n:04d}" for n in range(1, 36))
#: GV7-SRC-0036 .. GV7-SRC-0061 carry supplied URL/title/channel metadata.
SOURCES_WITH_LOCATOR = tuple(f"GV7-SRC-{n:04d}" for n in range(36, 62))
ALL_SOURCE_IDS = SOURCES_WITHOUT_LOCATOR + SOURCES_WITH_LOCATOR

#: Modules a read-only, never-retrieving validator may never import.
NETWORK_CAPABLE_MODULES = (
    "socket",
    "ssl",
    "http",
    "http.client",
    "urllib",
    "urllib.request",
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

#: Tokens that would promote a record by assertion. None may exist.
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
    assert isinstance(value, list), f"{key}: expected a list, got {type(value)!r}"
    return value


def identifiers(records: list, field: str) -> list:
    return [record[field] for record in records]
