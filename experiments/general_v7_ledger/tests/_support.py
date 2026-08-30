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

import builtins
import hashlib
import importlib
import io
import json
import ntpath
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

# --------------------------------------------------------------------------
# The two frozen path sets. CONTRACT.md section 3.
#
# The suite must stay satisfiable BY an implementation: a control that can only
# be made green by deleting it is not evidence, it is an obstacle. So nothing
# here asserts that the implementation surface is absent. It asserts that the
# laboratory is in one of exactly two admissible states, and that the evidence
# the tests preceded the implementation lives in Git history -- an immutable
# record -- rather than in a test that must be retired to let the work land.
# --------------------------------------------------------------------------

#: Authored in Phase A. Present in both admissible states.
PHASE_A_PATHS = (
    "CONTRACT.md",
    "tests/__init__.py",
    "tests/_support.py",
    "tests/test_contract.py",
    "tests/test_controls_manifest.py",
    "tests/test_inventory.py",
    "tests/test_ledger_structure.py",
    "tests/test_provenance.py",
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

PRE_IMPLEMENTATION_STATE = "pre-implementation"
IMPLEMENTED_STATE = "implemented"
ADMISSIBLE_STATES = (PRE_IMPLEMENTATION_STATE, IMPLEMENTED_STATE)


def laboratory_state(names) -> str:
    """Classify laboratory-relative POSIX file names into a frozen state.

    Returns ``PRE_IMPLEMENTATION_STATE``, ``IMPLEMENTED_STATE``, or a string
    beginning ``invalid:`` naming the exact defect. A partial implementation
    surface and an unrelated extra path are both invalid; neither is a state
    the ledger may ever be in.
    """
    present = frozenset(names)
    phase_a = frozenset(PHASE_A_PATHS)
    implementation = frozenset(IMPLEMENTATION_PATHS)

    missing_phase_a = sorted(phase_a - present)
    if missing_phase_a:
        return f"invalid: phase-A file absent: {missing_phase_a}"

    unrelated = sorted(present - phase_a - implementation)
    if unrelated:
        return f"invalid: unrelated path present: {unrelated}"

    found = present & implementation
    if not found:
        return PRE_IMPLEMENTATION_STATE
    if found == implementation:
        return IMPLEMENTED_STATE
    return (
        "invalid: partial implementation surface, absent: "
        f"{sorted(implementation - found)}"
    )


def laboratory_file_names() -> frozenset:
    """Every laboratory file, relative and POSIX, excluding bytecode caches."""
    return frozenset(
        path.relative_to(LAB_DIR).as_posix()
        for path in LAB_DIR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )


def committed_blob(relative_posix_path: str) -> bytes:
    """The bytes Git has stored for a tracked path at ``HEAD``.

    Not the working tree. On this platform ``core.autocrlf`` rewrites LF to
    CRLF on checkout, so a working-tree byte check would report a line-ending
    defect that does not exist in the repository and would fail on a fresh
    clone. The committed blob is the only durable provenance, and it is what
    every consumer of this repository actually receives.
    """
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{relative_posix_path}"],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"cannot read the committed blob for {relative_posix_path}: "
        f"git exited {completed.returncode}. Line-ending provenance is "
        f"established from Git, not from the checkout."
    )
    return completed.stdout

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------
# Precise absence detection.
# --------------------------------------------------------------------------

IMPLEMENTATION_ABSENT = "implementation-absent"

#: ``ERROR_FILENAME_EXCED_RANGE``. Windows maps it to ``FileNotFoundError``
#: alongside genuine absence, and the two must not be confused.
PATH_TOO_LONG_WINERROR = 206

SCHEMA_MODULE = "experiments.general_v7_ledger.schema"
VALIDATE_MODULE = "experiments.general_v7_ledger.validate"

#: Every module that ships. ``__init__.py`` runs on every import of ``schema``
#: and was previously unscanned by the import, assert and call-name controls.
PRODUCTION_MODULES = ("__init__.py", "schema.py", "validate.py")

#: The ONE key a production module may bind from ``sys.modules``: the package's
#: own core. A surface may re-export what the package already imported; it may
#: not reach anything else this way.
SYS_MODULES_SELF_BINDING_KEY = "experiments.general_v7_ledger"

#: Exactly how many conforming self-bindings each production module may carry,
#: where "conforming" means one MODULE-SCOPE ``_core = sys.modules[...]``
#: assignment whose ``sys`` is not rebound by any of the ENUMERATED binding
#: forms. "Enumerated", not "provably": an earlier version of that list omitted
#: ``match`` capture patterns and a decoy rebind went undetected. ``__init__.py`` is the core itself and needs none. This pins the
#: direct static shape only; it proves no runtime property, and the separate
#: human audit remains required.
SYS_MODULES_ALLOWED_USES = {
    "__init__.py": 0,
    "schema.py": 1,
    "validate.py": 1,
}

#: An ALLOWLIST over `import` roots. A blocklist admits every network-capable
#: package published tomorrow, so the allowlist is the better shape -- but it is
#: **one layer of a static assurance, not the authoritative rule**, and the
#: claim that it "establishes that no code path could retrieve anything" is
#: **withdrawn**. It walks `import` and `from ... import` statements only; both
#: public surfaces obtain the shared core through a `sys.modules` subscript,
#: which no import walker sees. That route is constrained separately, by
#: ``SYS_MODULES_ALLOWED_USES`` below, and what the layers together establish is
#: what a production module can STATICALLY REACH -- never an absolute
#: behavioural impossibility. A human audit remains required.
PRODUCTION_ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "argparse",
        "hashlib",
        "json",
        "ntpath",
        "os",
        "os.path",
        "pathlib",
        "re",
        "stat",
        "sys",
        "typing",
        "unicodedata",
    }
)


def absent(label: str) -> AssertionError:
    return AssertionError(
        f"{IMPLEMENTATION_ABSENT}: {label} is not present; implementation is "
        f"not yet authorized"
    )


def entry_is_absent(path: pathlib.Path) -> bool:
    """True only when the path entry is *genuinely* missing.

    ``Path.exists()`` is unusable here: it swallows ``PermissionError`` and
    every other ``OSError`` into a bare ``False``, so an unreadable directory
    would be reported as an unwritten implementation. ``lstat`` is used instead
    and **only ``FileNotFoundError`` counts as absence** — every other
    ``OSError``, ``PermissionError`` first among them, propagates.

    ``lstat`` does not follow links, so a dangling symlink or junction is
    *present but invalid*, never absent. The subsequent import or read then
    fails on its own terms.

    The rule is about **the named entry**, not about paths beneath it. A path
    the operating system cannot resolve at all -- one whose ancestor directory
    is missing, or whose ancestor is a dangling reparse point -- is reported as
    ``ENOENT`` and therefore reads as absence. That is a decided semantics, not
    an accident: it is pinned by ``GV7-M-020``, and the laboratory root the
    suite actually asks about is itself asserted present there, so a
    misconfigured root cannot masquerade as an unwritten implementation.
    """
    try:
        os.lstat(path)
    except FileNotFoundError as error:
        # ``ERROR_FILENAME_EXCED_RANGE`` (206) also maps to ``FileNotFoundError``
        # on Windows, so a path that merely overflows ``MAX_PATH`` would read as
        # an unwritten implementation -- exactly the inversion this helper
        # exists to prevent. Too long is not absent; it propagates.
        if getattr(error, "winerror", None) == PATH_TOO_LONG_WINERROR:
            raise
        return True
    return False


def require_module(dotted_name: str, module_path: pathlib.Path):
    """Import an expected module.

    Only a genuinely missing entry is absence. Once the entry exists,
    ``import_module`` runs unguarded: an ``ImportError`` raised inside it, a
    syntax error, a decoding failure, or a race-time ``FileNotFoundError`` all
    propagate as themselves and are never recategorized as absence.

    The entry is checked by *path* but imported by *dotted name*, and those two
    can diverge. The module that comes back is therefore required to be the
    entry that was inspected; a divergence raises a plain ``AssertionError``
    that does not carry the absence token.
    """
    if entry_is_absent(module_path):
        raise absent(module_path.name)
    module = importlib.import_module(dotted_name)
    bound = getattr(module, "__file__", None)
    if bound is None or pathlib.Path(bound).resolve() != module_path.resolve():
        raise AssertionError(
            f"module identity divergence: {dotted_name!r} bound to {bound!r}, "
            f"which is not the entry that was inspected, "
            f"{str(module_path)!r}; a stale sys.modules entry, a shadowing "
            f"sys.path root, a namespace portion or a compiled artifact can "
            f"cause this. It is a harness fault and never an unwritten "
            f"implementation."
        )
    return module


def require_schema():
    return require_module(SCHEMA_MODULE, SCHEMA_PATH)


def require_validate():
    return require_module(VALIDATE_MODULE, VALIDATE_PATH)


def require_file(path: pathlib.Path, label: str) -> str:
    """Return an expected file's text.

    Absence is absence. A permission failure, a directory where a file was
    expected, a decoding failure, and a race-time ``FileNotFoundError`` all
    propagate unchanged.
    """
    if entry_is_absent(path):
        raise absent(label)
    return path.read_text(encoding="utf-8")


def load_json_file(path: pathlib.Path, label: str):
    """Parse an expected JSON file.

    Absence is absence. **A malformed document is not absence**: the parser's
    ``ValueError`` propagates, so a broken ledger can never be mistaken for an
    unwritten one.
    """
    if entry_is_absent(path):
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
    """True for a symbolic link or ANY Windows reparse point.

    Deliberately broad, and deliberately **not** the refusal predicate. A
    OneDrive cloud placeholder carries ``FILE_ATTRIBUTE_REPARSE_POINT`` too,
    and this repository lives inside a OneDrive folder: refusing on the bare
    attribute would refuse an ordinary, unhydrated ledger file. Use
    ``is_refused_reparse_point`` for the rule; this stays as the descriptive
    predicate the fixture asserts against.
    """
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


#: Windows reparse tags that REDIRECT a path. ``stat`` exposes the first two by
#: name; the name-surrogate bit is not exposed and is frozen here.
REPARSE_TAG_SYMLINK = 0xA000000C
REPARSE_TAG_MOUNT_POINT = 0xA0000003
REPARSE_NAME_SURROGATE_BIT = 0x20000000
REDIRECTING_REPARSE_TAGS = (REPARSE_TAG_SYMLINK, REPARSE_TAG_MOUNT_POINT)


def reparse_tag_of(path: pathlib.Path):
    """The reparse tag for an entry, or ``None`` when it is not a reparse point."""
    try:
        status = os.lstat(path)
    except OSError:
        return None
    attributes = getattr(status, "st_file_attributes", 0)
    if not attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return None
    return getattr(status, "st_reparse_tag", 0) or None


def is_refused_reparse_point(path: pathlib.Path) -> bool:
    """True only for a reparse point that REDIRECTS the path elsewhere.

    Symbolic links and mount points/junctions redirect; so does any tag with
    the name-surrogate bit set. A cloud placeholder, an AppExecLink and every
    other non-surrogate tag do not, and must not be refused: they name the
    same file, they merely describe how its contents are stored.
    """
    if path.is_symlink():
        return True
    tag = reparse_tag_of(path)
    if tag is None:
        return False
    return tag in REDIRECTING_REPARSE_TAGS or bool(
        tag & REPARSE_NAME_SURROGATE_BIT
    )


# --------------------------------------------------------------------------
# Frozen Windows path hazards. Platform-independent by construction: nothing
# here consults the running interpreter. ``pathlib.PurePath.is_reserved()`` is
# deprecated and scheduled for removal in Python 3.15, and its behaviour has
# varied across versions, so the rule is frozen rather than delegated.
# --------------------------------------------------------------------------

WINDOWS_RESERVED_NAMES = frozenset(
    ("CON", "PRN", "AUX", "NUL")
    + tuple(f"COM{n}" for n in range(1, 10))
    + tuple(f"LPT{n}" for n in range(1, 10))
)


def component_is_reserved(component: str) -> bool:
    """Case-insensitive, extension-bearing, trailing dot/space tolerant.

    ``CON``, ``con``, ``CON.txt``, ``CON.``, ``CON `` and ``NUL...`` are all
    reserved. ``COM0``, ``LPT0``, ``LPT10``, ``CONSOLE`` and ``COMPANY`` are
    not: Windows reserves ``COM1``-``COM9`` and ``LPT1``-``LPT9`` only.
    """
    trimmed = component.rstrip(" .")
    stem = trimmed.split(".", 1)[0].rstrip(" .")
    return stem.upper() in WINDOWS_RESERVED_NAMES


def path_has_reserved_component(value: str) -> bool:
    return any(
        component_is_reserved(part)
        for part in re.split(r"[\\/]", value)
        if part
    )


def is_drive_relative(value: str) -> bool:
    """``C:ledger.json`` names a per-drive current directory, not a location."""
    drive, rest = ntpath.splitdrive(value)
    return bool(drive) and not rest.startswith(("\\", "/"))


def is_device_namespace(value: str) -> bool:
    """``\\\\?\\`` and ``\\\\.\\`` bypass the OS's own name checks.

    ``\\\\?\\`` disables reserved-name, trailing-dot and normalisation
    handling, so it is the bypass for every other rule here. The device form is
    consumed into the *drive* by ``splitroot``, so a component scan cannot see
    it -- the anchor is where it must be caught.
    """
    normalized = value.replace("/", "\\")
    return normalized.startswith("\\\\?\\") or normalized.startswith("\\\\.\\")


#: Windows also reserves these, and this list deliberately does NOT.
#: ``ntpath`` on Python 3.14 carries thirty reserved names: the twenty-two
#: frozen above plus ``CONIN$``, ``CONOUT$`` and the superscript ``COM``/``LPT``
#: variants, which the DOS device parser folds to the ASCII digit. They are
#: recorded here as a **disclosed gap**, not as a rule: the frozen list is the
#: one this contract was instructed to freeze, and a wider list would be a
#: number nobody counted. A future correction may promote them.
WINDOWS_RESERVED_NAMES_KNOWN_UNCOVERED = (
    "CONIN$",
    "CONOUT$",
    "COM\u00b9",
    "COM\u00b2",
    "COM\u00b3",
    "LPT\u00b9",
    "LPT\u00b2",
    "LPT\u00b3",
)


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


def string_nodes(obj, path=()):
    """Every string leaf **and every mapping key**.

    ``string_leaves`` walks values only, so a payload hidden in a key is
    invisible to it. Screening must see keys too: a mapping key is
    attacker-supplied text exactly as a value is.
    """
    yield from string_leaves(obj, path)
    if isinstance(obj, dict):
        for key in sorted(obj):
            if isinstance(key, str):
                yield path + ("<key>", key), key
            yield from string_nodes(obj[key], path + (key,))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            if isinstance(item, (dict, list)):
                yield from string_nodes(item, path + (index,))


def has_lone_surrogate(value: str) -> bool:
    """A code point in D800..DFFF that no UTF-8 encoder can represent.

    ``json.loads`` admits one silently from a ``\\uD800`` escape, and from raw
    WTF-8 bytes when handed ``bytes`` rather than ``str`` -- ``json.loads``
    decodes bytes with ``errors="surrogatepass"``. Surrogate *pairs* are
    recombined correctly and are not affected.
    """
    if value.isascii():
        return False
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


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
        "normalized_date",
        "supplied_channel",
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

#: Reserved future design, per CONTRACT.md 6i. ``supersedes`` is closed to
#: ``null`` in v1, so no control consults this; it is kept so the future
#: schema inherits a specification rather than inventing one.
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

#: Neither can a v1 claim. Every claim in this ledger is closed to
#: ``unverified``, so a claim asserting itself to be verified implementation
#: evidence would contradict its own verification state. The token stays
#: reserved in the broader vocabulary for a future verified-evidence schema;
#: no v1 claim and no v1 relationship may carry it.
CLAIM_ATTRIBUTION_CLASSES = tuple(
    value
    for value in ATTRIBUTION_CLASSES
    if value != "verified-implementation-evidence"
)

#: Reserved but unusable in v1.
RESERVED_UNUSED_ATTRIBUTION_CLASSES = ("verified-implementation-evidence",)

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

#: A bound on NESTED lists only -- a limitations list, a positions list, an
#: introduces_sources list. It is not a bound on a root collection: the frozen
#: inventory alone requires 63 batches and 61 sources, so applying 64 at the
#: root would make the contract unsatisfiable by arithmetic.
LIST_MAX = 64

#: The root resource ceiling. This is a denial-of-service bound, not a frozen
#: factual total: no count is asserted from it and no collection is expected
#: to approach it.
ROOT_COLLECTION_MAX = 4096

MAX_LEDGER_BYTES = 4194304
NOT_SUPPLIED = "not-supplied"

#: ISO calendar-date shape for ``normalized_date``. The supplied form is never
#: required to match it; that is the whole point of keeping both.
ISO_DATE_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")

#: Exact labelled fields a bibliography entry carries, parsed as canonical
#: JSON scalars and compared to the ledger field by equality -- never by
#: substring containment, which cannot tell a locator from its own prefix.
BIBLIOGRAPHY_FIELD_LABELS = (
    "supplied_locator",
    "normalized_locator",
    "locator_absence",
)

#: A correction may target any record except another correction. Permitting
#: ``GV7-COR-*`` would admit self-targets and correction cycles, and v1 has no
#: field in which a resolution order could be recorded.
CORRECTION_TARGET_COLLECTIONS = tuple(
    key for key in COLLECTION_KEYS if key != "corrections"
)

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

#: Inclusive (minimum, maximum) length for every root collection. The three
#: frozen inventories are exact; the rest are bounded, never asserted.
ROOT_COLLECTION_BOUNDS = {
    "batches": (EXPECTED_BATCHES, EXPECTED_BATCHES),
    "sources": (EXPECTED_SOURCES, EXPECTED_SOURCES),
    "artifacts": (EXPECTED_ARTIFACTS, EXPECTED_ARTIFACTS),
    "claims": (EXPECTED_SOURCES, ROOT_COLLECTION_MAX),
    "relationships": (1, ROOT_COLLECTION_MAX),
    "unresolved": (1, ROOT_COLLECTION_MAX),
    "corrections": (0, ROOT_COLLECTION_MAX),
}

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

#: A HEURISTIC TRIPWIRE, never a proof. A call-name scan cannot establish that
#: a module does not perform networking: an alias, an attribute lookup, or one
#: level of indirection defeats it. It is ONE LAYER of a static assurance --
#: alongside the import allowlist, the ban on dynamic import, the constrained
#: `sys.modules` self-binding and a required human audit -- and no layer of
#: that assurance is authoritative alone. Generic names that also match harmless standard-library calls --
#: ``get`` on a dict, ``run`` on an unrelated object, ``post``, ``request`` --
#: are deliberately excluded: a screen that fires on ``dict.get`` teaches
#: readers to ignore it.
RETRIEVAL_CALL_TRIPWIRE_NAMES = (
    "urlopen",
    "urlretrieve",
    "create_connection",
    "getaddrinfo",
    "Popen",
    "system",
    "__import__",
    "import_module",
    "eval",
    "exec",
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


# --------------------------------------------------------------------------
# The documentation acceptance boundary. CONTRACT.md section 12.
#
# Each of these three documents may be lifted out of the laboratory on its own
# -- pasted into a ticket, an appendix, a slide -- and read without the other
# two. So each must carry BOTH statements itself, before its substantive
# content, rather than relying on a sibling document to disclaim on its behalf.
# --------------------------------------------------------------------------

ACCEPTANCE_BOUNDARY_DOCUMENTS = (
    "BIBLIOGRAPHY.md",
    "INTAKE_REPORT.md",
    "README.md",
)

#: SUPERSEDED by ``SYNTHETIC_MATERIAL_RE`` in Correction 7, and kept only so an
#: auditor reading an earlier handback can find what it was. It is no longer
#: consulted by ``acceptance_boundary_violations``: its fixed-width lookbehinds
#: guard only the immediately adjacent word, so "not, in any sense, synthetic"
#: satisfied it.
#:
#: The PHRASE the contract names, not a bare token. A bare ``synthetic`` is
#: satisfied by a locator such as ``https://example.invalid/synthetic/item-0001``
#: or by an identifier, with no prose disclaimer anywhere -- so the token form
#: is **withdrawn**. The lookbehinds refuse a negated declaration: ``non-`` and
#: ``not `` are both four characters, so both are fixed-width and legal here.
SYNTHETIC_DECLARATION_RE = re.compile(
    r"(?i)(?<!non-)(?<!not )\b(synthetic|fabricated)\b"
)

#: URL-like spans are stripped BEFORE the declaration is looked for. Without
#: this a locator such as ``https://example.invalid/synthetic/item-0001``
#: satisfies the declaration with no prose anywhere, and a check that a URL
#: can satisfy is not a check.
URL_SPAN_RE = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|\bwww\.)\S*")

#: "not merge-authorized" -- the acceptance boundary, in any ordinary spelling,
#: including the British ``-ised``/``-isation`` forms this repository also uses.
NOT_MERGE_AUTHORIZED_RE = re.compile(
    r"(?i)\bnot\s+merge[- ]authoris?(ed|ation|zed|zation)\b"
)

#: A line that begins substantive content: a sub-heading at ANY index, a
#: labelled data line, or anything URL-like. The preamble ends at the first of
#: these, so a document whose very first line is a record heading has an EMPTY
#: preamble and cannot satisfy the rule from inside its own records.
SUBSTANTIVE_LINE_RE = re.compile(
    r"\A(?:#{2,}\s|-\s*[A-Za-z_][A-Za-z0-9_]*\s*:|>?\s*(?:[a-z][a-z0-9+.-]*://|www\.))"
)
URL_ANYWHERE_RE = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|\bwww\.)")


#: The four production refusal helpers, each pinned by exact signature and
#: exact single executable statement.
#:
#: Correction 6 pinned ``_refuse`` alone. The three siblings carry ten of the
#: thirty-nine tokens between them -- every stage-1 path refusal, the stage-2
#: ceiling and all three stage-3 parse refusals -- and appeared nowhere in the
#: acceptance surface, so a sibling that returned instead of raising passed the
#: whole suite and then accepted a ledger read through a redirecting junction.
#: That is the Correction 6 defeat one helper over, and this closes it.
FROZEN_REFUSAL_HELPERS = (
    (
        "_refuse",
        "def _refuse(token, path=()):\n    pass\n",
        "raise LedgerError(token, path) from None\n",
    ),
    (
        "_refuse_path",
        "def _refuse_path(token):\n    pass\n",
        "raise LedgerPathError(token) from None\n",
    ),
    (
        "_refuse_ceiling",
        "def _refuse_ceiling(token):\n    pass\n",
        "raise LedgerCeilingError(token) from None\n",
    ),
    (
        "_refuse_input",
        "def _refuse_input(token):\n    pass\n",
        "raise LedgerInputError(token) from None\n",
    ),
)

#: The one host every locator in the COMMITTED synthetic calibration data uses.
#: This is an evidence rule about this fabricated candidate, **not** a rule the
#: validator enforces and not a restriction on a future legitimate real-source
#: ledger. RFC 6761 reserves ``.invalid``, so nothing here can resolve.
CALIBRATION_LOCATOR_HOST = "example.invalid"

#: The exact boundary sentence each liftable document must carry, and the
#: heading it must sit after. Position is checked separately, by the preamble
#: rule below: a sentence that appears only after the records is not a boundary.
CALIBRATION_BOUNDARY_SENTENCES = {
    "BIBLIOGRAPHY.md": (
        "**Synthetic calibration material. "
        "This bibliography is not merge-authorized.**"
    ),
    "INTAKE_REPORT.md": (
        "**This synthetic calibration material is not merge-authorized.**"
    ),
}

#: Spans that carry no meaning to a reader of the rendered document. A
#: declaration only a source-reader can see is not a disclosure, so these are
#: removed before the declaration is looked for.
HTML_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
FENCED_BLOCK_RE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$")
#: A tag and everything inside its angle brackets. An attribute value renders
#: as nothing at all: `<img alt="Synthetic calibration material...">` satisfied
#: the declaration while showing a reader an image and no sentence.
HTML_TAG_RE = re.compile(r"(?s)<[^<>]*>")

#: The declaration must be an ASSERTION ABOUT THE MATERIAL, in one of two
#: ordinary shapes: "<synthetic> <material-noun>", or "is/are <synthetic>".
#: A bare token is not enough -- "synthetic-rubber gasket" satisfied the earlier
#: form -- and neither is a word inside a locator, which is why URL spans are
#: stripped first.
SYNTHETIC_MATERIAL_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:synthetic|fabricated)\b[\s,]+"
    r"(?:wholly\s+|entirely\s+|purely\s+|calibration\s+|engineering\s+|test\s+)*"
    r"(?:material|data|ledger|bibliograph\w*|report|records?|candidate|corpus"
    r"|documents?|fixtures?|entries|entry)"
    r"|\b(?:is|are|was|were)\s+"
    r"(?:wholly\s+|entirely\s+|purely\s+|deliberately\s+)*"
    r"(?:synthetic|fabricated)\b"
    r")"
)

#: Words that reverse the sentence around them. Checked over the WORDS BEFORE a
#: match, never inside it, so "is not merge-authorized" is not read as negating
#: its own declaration while "It is false that this ... is not merge-authorized"
#: is.
NEGATION_CUE_RE = re.compile(
    r"(?i)(?:\bnon-|\b(?:not|no|never|false|falsely|neither|nor|hardly|untrue"
    r"|contrary|opposite)\b)"
)

#: How many words before a declaration are read for a negation cue.
NEGATION_LOOKBACK_WORDS = 8

#: An affirmative claim of merge authority, and an affirmative claim that real
#: sources were obtained or checked. Both are screened only AFTER their negated
#: forms are removed, because "not merge-authorized" contains "merge-authorized"
#: and "no source was retrieved" contains "was retrieved".
MERGE_AUTHORITY_RE = re.compile(
    r"(?i)\b(?:merge[- ]authoris?(?:ed|ation|zed|zation)"
    r"|approved\s+for\s+merge|cleared\s+(?:to|for)\s+merge|ready\s+to\s+merge)\b"
)
REAL_SOURCE_VERIFICATION_RE = re.compile(
    r"(?i)\b(?:peer[- ]reviewed|independently\s+verified|corroborated"
    r"|authenticated|retrieved\s+and\s+verified|verified\s+sources?"
    r"|(?:sources?|claims?|identit(?:y|ies))\s+(?:were|was|are|is)\s+"
    r"(?:retrieved|verified)"
    r"|(?:was|were|is|are)\s+(?:retrieved|verified))\b"
)


def _visible_prose(text: str) -> str:
    """``text`` with the spans a reader of the rendered document never sees."""
    without_comments = HTML_COMMENT_RE.sub(" ", text)
    without_fences = FENCED_BLOCK_RE.sub(" ", without_comments)
    return HTML_TAG_RE.sub(" ", without_fences)


def _unnegated(pattern, text: str) -> bool:
    """True when ``pattern`` matches with no negation cue in the words before it.

    This is a BOUNDED STRUCTURAL CHECK over a small committed corpus of three
    documents, not a semantic detector. It cannot decide the meaning of
    arbitrary prose and does not claim to; see CONTRACT.md section 8a.
    """
    for match in pattern.finditer(text):
        before = text[: match.start()].split()[-NEGATION_LOOKBACK_WORDS:]
        if not NEGATION_CUE_RE.search(" ".join(before)):
            return True
    return False


def merge_authority_claims(text: str):
    """Affirmative merge-authority claims, with the negated form removed."""
    stripped = NOT_MERGE_AUTHORIZED_RE.sub(" ", _visible_prose(text))
    return sorted({match.group(0).lower() for match in MERGE_AUTHORITY_RE.finditer(stripped)})


def real_source_verification_claims(text: str):
    """Affirmative real-source claims, by the same look-back as everything else.

    An earlier form searched the WHOLE sentence for a negation cue, including
    the text after the match, so "Every source was retrieved and verified, and
    no entry was omitted" was silenced by the unrelated "no". The cue is read
    only over the words BEFORE the match, which is the discipline
    ``NEGATION_CUE_RE`` documents and ``_unnegated`` already follows.
    """
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+", _visible_prose(text)):
        for match in REAL_SOURCE_VERIFICATION_RE.finditer(sentence):
            before = sentence[: match.start()].split()[-NEGATION_LOOKBACK_WORDS:]
            if not NEGATION_CUE_RE.search(" ".join(before)):
                found.append(match.group(0).lower())
    return sorted(set(found))


def acceptance_boundary_preamble(text: str) -> str:
    """Everything before the document's first substantive line.

    A statement that appears only after the records is not a boundary: a reader
    who stops at the first entry never reaches it. The preamble therefore ends
    at the first line that begins substantive content -- a ``##``-or-deeper
    sub-heading, a ``- label:`` data line, or any URL-like line -- **at any
    index, including the very first**. A ``# Title`` line is not substantive and
    does not end it.

    If a document contains no substantive line at all, the whole text is
    returned, and ``acceptance_boundary_violations`` reports that separately
    rather than letting the placement rule pass vacuously.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if SUBSTANTIVE_LINE_RE.match(line) or URL_ANYWHERE_RE.search(line):
            return "\n".join(lines[:index])
    return text


def acceptance_boundary_violations(name: str, text: str):
    """``(name, defect)`` for each missing statement. Empty means compliant.

    Correction 7. The earlier predicate was satisfied by an HTML comment, by
    text inside a fenced block, by "synthetic-rubber gasket", by a sentence
    NEGATING the declaration at any distance, and by a double negation -- five
    shapes a reader would never accept as a disclosure. The declaration must
    now be visible in the rendered document, be an assertion about the material,
    carry no negation cue in the words before it, and stand beside no
    refutation of itself.

    This remains a BOUNDED STRUCTURAL CHECK over three committed documents. It
    is defence in depth, not a semantic detector, and it establishes nothing
    about arbitrary prose; CONTRACT.md section 8a states that limit and this
    docstring does not exceed it.
    """
    preamble = acceptance_boundary_preamble(text)
    found = []
    if preamble == text:
        # No substantive line was found, so "before the content" has nothing to
        # be before. Reported rather than passed: a silent pass here would make
        # the placement rule vacuous for exactly the shape it cannot police.
        found.append(
            (name, "no substantive content boundary: the placement rule cannot bind")
        )
    visible = _visible_prose(preamble)
    prose = URL_SPAN_RE.sub(" ", visible)
    if not _unnegated(SYNTHETIC_MATERIAL_RE, prose):
        found.append((name, "no synthetic-calibration statement before the content"))
    if not _unnegated(NOT_MERGE_AUTHORIZED_RE, visible):
        found.append((name, "no not-merge-authorized statement before the content"))
    for claim in merge_authority_claims(preamble):
        found.append((name, f"the preamble claims merge authority: {claim}"))
    for claim in real_source_verification_claims(preamble):
        found.append(
            (name, f"the preamble claims real-source verification: {claim}")
        )
    return found


#: Tokens the acceptance surface names by exact string. The production
#: vocabulary must be a superset: a token the controls demand but the
#: implementation never defines is a contract the implementation did not meet.
REQUIRED_REFUSAL_TOKENS = (
    "collection-length-invalid",
    "correction-target-not-permitted",
    "date-pairing-invalid",
    "disposition-ordinary-not-exclusive",
    "enum-value-invalid",
    "float-refused",
    "identifier-duplicate",
    "identifier-malformed",
    "identifier-wrong-collection",
    "int-out-of-range",
    "introduction-not-reciprocal",
    "json-duplicate-key",
    "json-malformed",
    "key-not-exact-str",
    "ledger-bytes-ceiling",
    "ledger-encoding-invalid",
    "list-duplicate-item",
    "list-length-invalid",
    "locator-not-https",
    "locator-pairing-invalid",
    "missing-key",
    "ordinal-id-mismatch",
    "path-device-namespace",
    "path-drive-relative",
    "path-missing",
    "path-not-file",
    "path-reserved-name",
    "path-symlink-refused",
    "reference-not-found",
    "reference-wrong-kind",
    "relationship-duplicate",
    "relationship-endpoint-kind-mismatch",
    "relationship-self",
    "root-not-object",
    "string-not-encodable",
    "supersedes-not-permitted",
    "text-length-invalid",
    "type-not-exact",
    "undeclared-key",
)

#: The stage-1-adjacent token for a file whose identity is not the identity
#: that was inspected. Named here so a control can demand it of the production
#: vocabulary before any implementation exists.
#:
#: It is deliberately NOT folded into ``REQUIRED_REFUSAL_TOKENS`` while no
#: implementation declares it: that list is what the pre-Correction-8 surface
#: demanded, and adding to it would turn GV7-S-068 red for the same defect
#: GV7-S-075 already reports. ``GV7-S-075`` demands the token of the production
#: vocabulary directly, and does so whether or not the list has been updated.
PATH_IDENTITY_TOKEN = "path-identity-changed"


def _open_via_builtins(path):
    return builtins.open(path, "rb")


def _open_via_io(path):
    return io.open(path, "rb")


def _open_via_pathlib(path):
    return pathlib.Path(path).open("rb")


def _open_via_os(path):
    return os.fdopen(os.open(path, os.O_RDONLY), "rb")


#: Every standard-library route to a read handle a production module may use.
#: ``io.open`` IS ``builtins.open`` -- the same function object -- but they are
#: two module ATTRIBUTES, so patching one leaves the other bound to the
#: original. ``pathlib.Path.open`` calls ``io.open``, which is how a compliant
#: implementation slipped past a probe that hooked only ``builtins``.
#: GV7-S-078 proves every route here actually reaches the fixture.
OPENER_ROUTES = (
    ("builtins.open", _open_via_builtins),
    ("io.open", _open_via_io),
    ("pathlib.Path.open", _open_via_pathlib),
    ("os.open + os.fdopen", _open_via_os),
)


class ReplaceBeforeOpen:
    """Replace a named file in the instant before it is opened.

    Deterministic, not a race: the replacement happens inside the opener call,
    so every name resolution performed BEFORE the open saw the original object
    and every byte read comes from the replacement.

    That is what makes it discriminating. A validator that "binds" by looking
    the NAME up again -- before the open or after it -- compares two
    resolutions that do not include the opened object, and reads the swapped
    file anyway. Only an identity taken from the open descriptor sees the
    difference; ``IdentityQueryLog`` is what proves that is where it came from.

    Every route in ``OPENER_ROUTES`` is hooked. If none is reached for the
    target, ``replaced`` stays ``False`` and the control using this must fail
    rather than pass: the window it exists to test was never entered.
    """

    def __init__(self, target, replacement, swap_on=1):
        self.target = pathlib.Path(target)
        self.replacement = pathlib.Path(replacement)
        #: Which open of the target the swap lands before. The default lands
        #: before the first, which is the ordinary check-then-open window. A
        #: validator that opens a PROBE descriptor, inspects it, closes it and
        #: opens again to read has a second window, between its two opens, and
        #: passes every control when the swap can only land before the first.
        self.swap_on = swap_on
        self.inspected = None
        self.replaced = False
        #: How many times the TARGET was opened. The contract says the file is
        #: opened once and the bytes are read from that handle; an
        #: implementation that opens a probe descriptor, stats it, closes it and
        #: then opens again to read was measured green on every other control.
        self.open_count = 0
        self._builtins_open = builtins.open
        self._io_open = io.open
        self._os_open = os.open
        self._lstat = os.lstat

    def _same(self, path):
        try:
            return os.path.normcase(os.fspath(path)) == os.path.normcase(
                str(self.target)
            )
        except TypeError:
            return False

    def _swap(self, path):
        if not self._same(path):
            return
        self.open_count += 1
        if self.replaced or self.open_count < self.swap_on:
            return
        current = self._lstat(self.target)
        self.inspected = (current.st_dev, current.st_ino)
        os.replace(self.replacement, self.target)
        self.replaced = True

    def _patches(self):
        def builtins_open(file, *args, **kwargs):
            self._swap(file)
            return self._builtins_open(file, *args, **kwargs)

        def io_open(file, *args, **kwargs):
            self._swap(file)
            return self._io_open(file, *args, **kwargs)

        def os_open(path, *args, **kwargs):
            self._swap(path)
            return self._os_open(path, *args, **kwargs)

        return (
            (builtins, "open", builtins_open),
            (io, "open", io_open),
            (os, "open", os_open),
        )

    def install(self, monkeypatch):
        for module, name, replacement in self._patches():
            monkeypatch.setattr(module, name, replacement)
        return self

    def install_raw(self):
        """Install without pytest, and return a callable that undoes it.

        GV7-S-077 runs in a subprocess and must use these exact semantics, not
        a narrower hand-written copy that could drift from them.
        """
        originals = [(module, name, getattr(module, name))
                     for module, name, _ in self._patches()]
        for module, name, replacement in self._patches():
            setattr(module, name, replacement)

        def restore():
            for module, name, original in originals:
                setattr(module, name, original)

        return restore

    def opened_identity(self):
        """The identity now behind that name -- what an open will reach."""
        current = self._lstat(self.target)
        return (current.st_dev, current.st_ino)


class IdentityQueryLog:
    """Record whether an identity was asked of a DESCRIPTOR or of a name.

    The contract requires the compared identity to come from the opened handle
    and never from a second lookup of the name. Both a pre-open and a post-open
    re-inspection of the pathname produce the right token against a swapped
    file while proving nothing about the object actually read -- a post-open
    re-check with a full zero guard was measured passing every outcome control.

    So the evidence is dynamic: ``os.stat``/``os.fstat`` called with an ``int``
    is a query against an open descriptor; called with anything else it is one
    more name resolution. A control can then require that the implementation
    asked a descriptor at all.
    """

    def __init__(self):
        self.descriptor_queries = 0
        self.path_queries = 0
        #: Which objects were asked. Counting queries alone is satisfied by
        #: `os.fstat(0)`; naming the identity that came back is not.
        self.descriptor_identities = set()
        self._stat = os.stat
        self._fstat = os.fstat

    def _record(self, first, result):
        if isinstance(first, int) and not isinstance(first, bool):
            self.descriptor_queries += 1
            dev = getattr(result, "st_dev", None)
            ino = getattr(result, "st_ino", None)
            self.descriptor_identities.add((dev, ino))
        else:
            self.path_queries += 1

    @staticmethod
    def _subject(args, kwargs, keys):
        """The thing being asked about, however the caller spelled the call."""
        if args:
            return args[0]
        for key in keys:
            if key in kwargs:
                return kwargs[key]
        return None

    def _patches(self):
        def stat_(*args, **kwargs):
            result = self._stat(*args, **kwargs)
            self._record(self._subject(args, kwargs, ("path",)), result)
            return result

        def fstat_(*args, **kwargs):
            result = self._fstat(*args, **kwargs)
            self._record(self._subject(args, kwargs, ("fd",)), result)
            return result

        return ((os, "stat", stat_), (os, "fstat", fstat_))

    def install(self, monkeypatch):
        for module, name, replacement in self._patches():
            monkeypatch.setattr(module, name, replacement)
        return self

    def install_raw(self):
        """Install without pytest, and return a callable that undoes it."""
        originals = [(module, name, getattr(module, name))
                     for module, name, _ in self._patches()]
        for module, name, replacement in self._patches():
            setattr(module, name, replacement)

        def restore():
            for module, name, original in originals:
                setattr(module, name, original)

        return restore


#: The ways an identity can fail to prove anything. Each is pinned separately:
#: a guard that fires only when BOTH components are zero was measured passing
#: every control while accepting a swap on a volume that zeroes just one.
UNPROVABLE_IDENTITY_CASES = ("dev-zero", "ino-zero", "both-zero",
                             "dev-absent", "ino-absent")


class UnprovableIdentity:
    """Report a platform whose file identity does not identify anything."""

    def __init__(self, case):
        assert case in UNPROVABLE_IDENTITY_CASES, case
        self.case = case
        self._stat = os.stat
        self._lstat = os.lstat
        #: `os.fstat` is masked too. Masking only the name routes left the
        #: descriptor side UNMASKED, so the two identities always differed,
        #: every implementation appeared to refuse, and one with no zero guard
        #: at all was green on the whole suite.
        self._fstat = os.fstat

    class _Masked:
        """The platform's own result, with the fields under test suppressed.

        Rebuilding an ``os.stat_result`` from its ten base fields would drop
        the Windows extended attributes the reparse screen reads, so this
        forwards instead of fabricating.
        """

        def __init__(self, wrapped, case):
            self._wrapped = wrapped
            self._case = case

        def __getattr__(self, name):
            case = object.__getattribute__(self, "_case")
            if name == "st_dev":
                if case in ("dev-zero", "both-zero"):
                    return 0
                if case == "dev-absent":
                    raise AttributeError(name)
            if name == "st_ino":
                if case in ("ino-zero", "both-zero"):
                    return 0
                if case == "ino-absent":
                    raise AttributeError(name)
            return getattr(object.__getattribute__(self, "_wrapped"), name)

        #: `os.stat_result` supports the tuple protocol, and the stdlib ships
        #: `stat.ST_DEV` / `stat.ST_INO` for exactly that access style. Masking
        #: only attribute reads let an implementation index past the mask.
        _INDEX_OF = {"st_ino": 1, "st_dev": 2}

        def __getitem__(self, index):
            wrapped = object.__getattribute__(self, "_wrapped")
            for field, position in UnprovableIdentity._Masked._INDEX_OF.items():
                if index == position:
                    return getattr(self, field)
            return wrapped[index]

    def install(self, monkeypatch):
        def mask(result):
            return UnprovableIdentity._Masked(result, self.case)

        monkeypatch.setattr(os, "stat", lambda *a, **k: mask(self._stat(*a, **k)))
        monkeypatch.setattr(os, "lstat", lambda *a, **k: mask(self._lstat(*a, **k)))
        monkeypatch.setattr(os, "fstat", lambda *a, **k: mask(self._fstat(*a, **k)))
        return self


def padded_refusable(length):
    """A JSON document that refuses at the content stage, of an exact length.

    Equal-length fixtures matter: a validator that compares the number of bytes
    read with the recorded size is not comparing identity at all, and a
    different-length replacement lets that proxy look correct.
    """
    body = b"{}"
    assert length >= len(body), length
    return body + b" " * (length - len(body))


#: Controls withdrawn by Correction 3, with the reason. Nothing is silently
#: deleted: a retired id must never be reused, and must never reappear in a
#: module. ``GV7-M-025`` enforces both.
RETIRED_CONTROLS = {
    "GV7-S-038": (
        "positive supersession chain -- withdrawn: non-null supersession is "
        "deferred to a future schema version, so there is no valid v1 chain "
        "to accept"
    ),
    "GV7-S-039": (
        "supersedes block shape -- withdrawn: v1 admits no block to shape"
    ),
    "GV7-S-040": (
        "supersedes digest mismatch -- withdrawn with the block itself"
    ),
    "GV7-S-041": (
        "missing or cross-collection predecessor -- withdrawn with the block"
    ),
    "GV7-S-042": (
        "supersession cannot promote verification state -- withdrawn: no v1 "
        "supersession exists to promote across, and GV7-P-010 already refuses "
        "every promoted state directly"
    ),
    "GV7-S-045": (
        "the valid supersession fixture breaks no other rule -- withdrawn "
        "with the fixture"
    ),
}


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
