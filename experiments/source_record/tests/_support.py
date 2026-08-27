"""Shared support for the ``source-record-v1`` acceptance suite.

Nothing here imports an implementation module at import time. Every
implementation dependency is resolved *inside* a test through
``require_module`` and its wrappers, so ``--collect-only`` succeeds against an
empty laboratory and the full run fails for one clearly attributable reason.

Missing implementation is reported as an ordinary assertion failure. It is
never skipped and never marked xfail: an absent implementation is a red
acceptance surface, not an excused one.

Every fixture value in this module is synthetic. Locator values match the
anchored ``synthetic-`` pattern the contract requires.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import pathlib
import sys

import pytest

# --------------------------------------------------------------------------
# Paths. Computed from this file only; nothing is searched or crawled.
# --------------------------------------------------------------------------

TESTS_DIR = pathlib.Path(__file__).resolve().parent
LAB_DIR = TESTS_DIR.parent
EXPERIMENTS_DIR = LAB_DIR.parent
REPO_ROOT = EXPERIMENTS_DIR.parent

RECORDS_ROOT = LAB_DIR / "records"
REGISTER_DIR_NAMES = ("register-a", "register-b", "bridge")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------
# Implementation-absent reporting.
# --------------------------------------------------------------------------

IMPLEMENTATION_ABSENT = "implementation-absent"

SCHEMA_MODULE = "experiments.source_record.schema"
VALIDATE_MODULE = "experiments.source_record.validate"


def require_module(dotted_name: str):
    """Import an implementation module, or fail the calling test clearly.

    ``from None`` keeps the original ImportError out of the chained context:
    the acceptance surface reports its own reason and discloses nothing else.
    """
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


def require_records_root() -> pathlib.Path:
    """Return the records root, or fail the calling test clearly."""
    if not RECORDS_ROOT.is_dir():
        raise AssertionError(
            f"{IMPLEMENTATION_ABSENT}: records root is not present; "
            f"implementation is not yet authorized"
        )
    return RECORDS_ROOT


# --------------------------------------------------------------------------
# Contract mirrors. The test side keeps its own copy so a drift between the
# suite and the implementation is itself detectable.
# --------------------------------------------------------------------------

SCHEMA_ID = "source-record-v1"
REGISTERS = ("register-a", "register-b", "bridge")
RECORD_TYPES = (
    "message",
    "source",
    "assertion",
    "link",
    "bridge",
    "contradiction",
)
ORIGINS = ("synthetic-fixture",)
VERIFICATION_STATES = ("unverified",)
RESOLUTION_STATES = ("unresolved",)
LOCATOR_SCHEMES = (
    "opaque-handle",
    "network-locator",
    "filename",
    "document-number",
    "container-reference",
    "none",
)
LOCATOR_RESOLUTIONS = ("unattempted",)
ATTRIBUTION_CLASSES = (
    "receipt-fact",
    "attributed-assertion",
    "recorded-observation",
    "derived-inference",
)
ROLES = (
    "relay-agent",
    "operator",
    "auditor",
    "analysis-seat",
    "external-author",
    "unattributed",
)
LINK_TYPES = (
    "claimed-container-includes",
    "claimed-derivative-of",
    "commentary-about",
    "apparent-textual-overlap",
    "contested-correspondence",
)
BRIDGE_TYPES = (
    "shared-attributed-author",
    "shared-locator-value",
    "apparent-textual-overlap",
    "contested-correspondence",
)
RELATIONSHIP_BASES = (
    "recorded-by-inspection",
    "recorded-from-supplied-material",
    "recorded-as-proposed-elsewhere",
)
CONFLICT_BASES = (
    "same-quantity-different-values",
    "same-property-mutually-exclusive-values",
    "presence-and-absence-of-the-same-property",
    "incompatible-attributions",
)
UNKNOWN_TOKEN = "unknown"

LABEL_MAX = 128
TEXT_MAX = 4096
LOCATORS_MAX = 16
DERIVED_FROM_MAX = 16
ORDINAL_MIN = 1
ORDINAL_MAX = 9999

RECORD_ID_PATTERN = r"\ASR-(A|B|X)-(MSG|SRC|ASR|LNK|BRG|CTR)-[0-9]{4}\Z"
LOCATOR_VALUE_PATTERN = r"\Asynthetic-[a-z0-9-]{1,64}\Z"
DIGEST_PATTERN = r"\A[0-9a-f]{64}\Z"

REFUSAL_TOKENS = (
    # path and binding, exit 4
    "path-missing",
    "path-not-directory",
    "path-symlink-refused",
    "path-binding-failed",
    "records-root-missing-directory",
    "records-root-unexpected-entry",
    "record-directory-unexpected-entry",
    "directory-set-incomplete",
    # resource, exit 5
    "record-count-ceiling",
    "record-bytes-ceiling",
    "total-bytes-ceiling",
    # parse, schema and record, exit 2
    "json-malformed",
    "json-duplicate-key",
    "root-not-object",
    "key-not-exact-str",
    "undeclared-key",
    "missing-key",
    "schema-id-invalid",
    "record-id-malformed",
    "record-id-filename-mismatch",
    "record-id-directory-mismatch",
    "record-id-register-mismatch",
    "record-id-type-mismatch",
    "record-id-duplicate",
    "type-not-exact",
    "float-refused",
    "int-out-of-range",
    "enum-value-invalid",
    "digits-not-ascii",
    "date-invalid",
    "string-empty",
    "string-length-invalid",
    "string-not-valid-unicode",
    "string-contains-record-id",
    "list-length-invalid",
    "list-duplicate-item",
    "locator-value-not-synthetic",
    "null-not-permitted",
    "unknown-token-not-permitted",
    "attribution-class-mismatch",
    "attribution-author-mismatch",
    "derived-from-required",
    "derived-from-forbidden",
    "instrument-context-required",
    "instrument-context-forbidden",
    "reference-not-found",
    "reference-wrong-register",
    "reference-wrong-type",
    "reference-self",
    "reference-cycle",
    "bridge-side-register-invalid",
    "bridge-endpoint-not-source",
    "bridge-duplicate-pair",
    "supersedes-target-missing",
    "supersedes-register-mismatch",
    "supersedes-type-mismatch",
    "supersedes-digest-mismatch",
    "supersedes-fork-refused",
    "supersedes-self",
    "supersedes-cycle",
    "verification-state-invalid",
    "verification-evidence-not-null",
    "resolution-state-invalid",
)

COMMON_KEYS = (
    "schema",
    "record_id",
    "record_type",
    "register",
    "origin",
    "recorded_date",
    "recorded_by_role",
    "recorded_by_label",
    "supersedes",
)

TYPE_KEYS = {
    "message": (
        "carrier_role",
        "carrier_label",
        "received_date",
        "sequence_ordinal",
    ),
    "source": ("neutral_label", "locators", "issuer_claim"),
    "assertion": (
        "message_ref",
        "subject_ref",
        "attribution_class",
        "asserted_by_role",
        "attributed_author",
        "claim_text",
        "instrument_context",
        "derived_from",
        "verification_state",
        "verification_evidence",
    ),
    "link": (
        "left_ref",
        "right_ref",
        "link_type",
        "basis",
        "verification_state",
    ),
    "bridge": (
        "side_a",
        "side_b",
        "bridge_type",
        "basis",
        "verification_state",
    ),
    "contradiction": (
        "left_assertion_ref",
        "right_assertion_ref",
        "conflict_basis",
        "resolution_state",
        "verification_state",
    ),
}

ROOT_KEYS = {
    record_type: frozenset(COMMON_KEYS + extra)
    for record_type, extra in TYPE_KEYS.items()
}

LOCATOR_KEYS = frozenset({"scheme", "value", "resolution"})
ISSUER_CLAIM_KEYS = frozenset(
    {"claimed_issuer", "verification_state", "verification_evidence"}
)
SUPERSEDES_KEYS = frozenset({"record_id", "content_digest"})

# Fields on which a bridge must not be able to assert. The bridge key set is
# asserted disjoint from these.
ASSERTING_FIELDS = frozenset(
    {
        "locators",
        "issuer_claim",
        "claim_text",
        "attribution_class",
        "attributed_author",
        "instrument_context",
        "derived_from",
        "verification_evidence",
    }
)

# --------------------------------------------------------------------------
# Canary markers for the non-disclosure controls. Non-empty and unique.
# --------------------------------------------------------------------------

MARKER_VALUE = "canary-value-3f9a2c7e-do-not-echo"
MARKER_KEY = "canary-key-8b1d4a6f-do-not-echo"
MARKER_SECRET_SHAPED = "canary-secret-5c2e9d13-do-not-echo"
MARKERS = (MARKER_VALUE, MARKER_KEY, MARKER_SECRET_SHAPED)

# --------------------------------------------------------------------------
# Canonicalization mirror.
# --------------------------------------------------------------------------


def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")


def digest_of(obj) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


# --------------------------------------------------------------------------
# Hostile carriers. Each records whether a hook ran, so a control can assert a
# refusal happened BEFORE any hook on the rejected object could execute.
#
# ``reset_hooks`` exists because building a payload may itself invoke a hook
# (a mapping hashes its keys on insertion); the counters are zeroed after the
# payload is built and before the validator is called.
# --------------------------------------------------------------------------


class _HookRecorder:
    """Hook-counting mixin.

    It deliberately declares no ``__init__``: the immutable carriers below
    override ``__new__`` only, and a mixin ``__init__`` would be found first in
    the method resolution order and reject the constructor argument.
    """

    def _bump(self, name):
        self.hooks[name] = self.hooks.get(name, 0) + 1

    def reset_hooks(self):
        self.hooks.clear()

    def any_hook_ran(self) -> bool:
        return bool(self.hooks)


class HookedStr(str, _HookRecorder):
    def __new__(cls, value):
        obj = str.__new__(cls, value)
        obj.hooks = {}
        return obj

    def __eq__(self, other):
        self._bump("__eq__")
        return str.__eq__(self, other)

    def __ne__(self, other):
        self._bump("__ne__")
        return str.__ne__(self, other)

    def __hash__(self):
        self._bump("__hash__")
        return str.__hash__(self)

    def __repr__(self):
        self._bump("__repr__")
        return str.__repr__(self)

    def __str__(self):
        self._bump("__str__")
        return str.__str__(self)

    def __format__(self, spec):
        self._bump("__format__")
        return str.__format__(self, spec)

    def __len__(self):
        self._bump("__len__")
        return str.__len__(self)


class HookedInt(int, _HookRecorder):
    def __new__(cls, value):
        obj = int.__new__(cls, value)
        obj.hooks = {}
        return obj

    def __eq__(self, other):
        self._bump("__eq__")
        return int.__eq__(self, other)

    def __hash__(self):
        self._bump("__hash__")
        return int.__hash__(self)

    def __repr__(self):
        self._bump("__repr__")
        return int.__repr__(self)

    def __index__(self):
        self._bump("__index__")
        return int.__index__(self)

    def __format__(self, spec):
        self._bump("__format__")
        return int.__format__(self, spec)


class HookedBytes(bytes, _HookRecorder):
    def __new__(cls, value):
        obj = bytes.__new__(cls, value)
        obj.hooks = {}
        return obj

    def __eq__(self, other):
        self._bump("__eq__")
        return bytes.__eq__(self, other)

    def __hash__(self):
        self._bump("__hash__")
        return bytes.__hash__(self)

    def __repr__(self):
        self._bump("__repr__")
        return bytes.__repr__(self)

    def __len__(self):
        self._bump("__len__")
        return bytes.__len__(self)


class HookedDict(dict, _HookRecorder):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.hooks = {}

    def __iter__(self):
        self._bump("__iter__")
        return dict.__iter__(self)

    def __len__(self):
        self._bump("__len__")
        return dict.__len__(self)

    def __getitem__(self, key):
        self._bump("__getitem__")
        return dict.__getitem__(self, key)

    def __repr__(self):
        self._bump("__repr__")
        return dict.__repr__(self)


class HookedList(list, _HookRecorder):
    def __init__(self, *args):
        list.__init__(self, *args)
        self.hooks = {}

    def __iter__(self):
        self._bump("__iter__")
        return list.__iter__(self)

    def __len__(self):
        self._bump("__len__")
        return list.__len__(self)

    def __repr__(self):
        self._bump("__repr__")
        return list.__repr__(self)


class HookedTuple(tuple, _HookRecorder):
    def __new__(cls, value):
        obj = tuple.__new__(cls, value)
        obj.hooks = {}
        return obj

    def __iter__(self):
        self._bump("__iter__")
        return tuple.__iter__(self)

    def __len__(self):
        self._bump("__len__")
        return tuple.__len__(self)

    def __repr__(self):
        self._bump("__repr__")
        return tuple.__repr__(self)


class Betrayer(_HookRecorder):
    """A non-builtin object whose every observation is recorded.

    Its type name is deliberately misleading to a validator that reads
    ``type(x).__name__``: reading it is itself recorded.
    """

    def __init__(self, marker=MARKER_VALUE):
        self.hooks = {}
        self.marker = marker

    def __repr__(self):
        self._bump("__repr__")
        return self.marker

    def __str__(self):
        self._bump("__str__")
        return self.marker

    def __format__(self, spec):
        self._bump("__format__")
        return self.marker

    def __eq__(self, other):
        self._bump("__eq__")
        return NotImplemented

    def __hash__(self):
        self._bump("__hash__")
        return id(self)

    def __len__(self):
        self._bump("__len__")
        return 1

    def __iter__(self):
        self._bump("__iter__")
        return iter(())

    def __index__(self):
        self._bump("__index__")
        return 0


class MutatingDict(dict):
    """A mapping that would answer differently on a second read of one key.

    Exact-builtin-dict discipline means this is refused before it can betray.
    The control asserts ``reads == 0`` at refusal: the time-of-check /
    time-of-use window is closed by type discipline, not by re-reading care.
    """

    def __init__(self, base, key, second_value):
        dict.__init__(self, base)
        self._key = key
        self._second = second_value
        self.reads = 0

    def __getitem__(self, key):
        value = dict.__getitem__(self, key)
        if key == self._key:
            self.reads += 1
            if self.reads > 1:
                return self._second
        return value


def all_hooked_classes():
    return (
        HookedStr,
        HookedInt,
        HookedBytes,
        HookedDict,
        HookedList,
        HookedTuple,
        Betrayer,
    )


# --------------------------------------------------------------------------
# Synthetic fixture builders. Every value is synthetic; no locator, label or
# claim refers to anything outside this laboratory.
# --------------------------------------------------------------------------

FIXTURE_DATE = "2026-08-28"


def _common(record_id, record_type, register, **overrides):
    record = {
        "schema": SCHEMA_ID,
        "record_id": record_id,
        "record_type": record_type,
        "register": register,
        "origin": "synthetic-fixture",
        "recorded_date": FIXTURE_DATE,
        "recorded_by_role": "analysis-seat",
        "recorded_by_label": "synthetic recorder one",
        "supersedes": None,
    }
    record.update(overrides)
    return record


def message_record(record_id="SR-A-MSG-0001", register="register-a", **overrides):
    record = _common(record_id, "message", register)
    record.update(
        {
            "carrier_role": "relay-agent",
            "carrier_label": "synthetic carrier one",
            "received_date": FIXTURE_DATE,
            "sequence_ordinal": 1,
        }
    )
    record.update(overrides)
    return record


def locator_block(value="synthetic-handle-0001", **overrides):
    block = {
        "scheme": "opaque-handle",
        "value": value,
        "resolution": "unattempted",
    }
    block.update(overrides)
    return block


def issuer_claim_block(**overrides):
    block = {
        "claimed_issuer": UNKNOWN_TOKEN,
        "verification_state": "unverified",
        "verification_evidence": None,
    }
    block.update(overrides)
    return block


def source_record(record_id="SR-A-SRC-0001", register="register-a", **overrides):
    record = _common(record_id, "source", register)
    record.update(
        {
            "neutral_label": "synthetic source alpha",
            "locators": [locator_block()],
            "issuer_claim": issuer_claim_block(),
        }
    )
    record.update(overrides)
    return record


def assertion_record(
    record_id="SR-A-ASR-0001", register="register-a", **overrides
):
    prefix = record_id[:5]
    record = _common(record_id, "assertion", register)
    record.update(
        {
            "message_ref": prefix + "MSG-0001",
            "subject_ref": prefix + "SRC-0001",
            "attribution_class": "attributed-assertion",
            "asserted_by_role": "relay-agent",
            "attributed_author": "synthetic author one",
            "claim_text": "synthetic placeholder claim text for fixture use",
            "instrument_context": None,
            "derived_from": None,
            "verification_state": "unverified",
            "verification_evidence": None,
        }
    )
    record.update(overrides)
    return record


def link_record(record_id="SR-A-LNK-0001", register="register-a", **overrides):
    prefix = record_id[:5]
    record = _common(record_id, "link", register)
    record.update(
        {
            "left_ref": prefix + "SRC-0001",
            "right_ref": prefix + "SRC-0002",
            "link_type": "apparent-textual-overlap",
            "basis": "recorded-by-inspection",
            "verification_state": "unverified",
        }
    )
    record.update(overrides)
    return record


def bridge_record(record_id="SR-X-BRG-0001", **overrides):
    record = _common(record_id, "bridge", "bridge")
    record.update(
        {
            "side_a": "SR-A-SRC-0001",
            "side_b": "SR-B-SRC-0001",
            "bridge_type": "shared-attributed-author",
            "basis": "recorded-by-inspection",
            "verification_state": "unverified",
        }
    )
    record.update(overrides)
    return record


def contradiction_record(
    record_id="SR-A-CTR-0001", register="register-a", **overrides
):
    prefix = record_id[:5]
    record = _common(record_id, "contradiction", register)
    record.update(
        {
            "left_assertion_ref": prefix + "ASR-0001",
            "right_assertion_ref": prefix + "ASR-0002",
            "conflict_basis": "same-quantity-different-values",
            "resolution_state": "unresolved",
            "verification_state": "unverified",
        }
    )
    record.update(overrides)
    return record


BUILDERS = {
    "message": message_record,
    "source": source_record,
    "assertion": assertion_record,
    "link": link_record,
    "bridge": bridge_record,
    "contradiction": contradiction_record,
}


def valid_record(record_type):
    return BUILDERS[record_type]()


# --------------------------------------------------------------------------
# Refusal assertion helper.
# --------------------------------------------------------------------------


def assert_refused(schema, payload, token, path=None):
    """Assert ``validate_record`` refuses with an exact token.

    Also asserts the refusal carrier exposes exactly ``token`` and ``path`` and
    no rejected-value slot, and that the rendered message contains no marker.
    """
    with pytest.raises(schema.SourceRecordError) as excinfo:
        schema.validate_record(payload)
    error = excinfo.value
    assert error.token == token, (
        f"expected refusal token {token!r}, got {error.token!r}"
    )
    if path is not None:
        assert tuple(error.path) == tuple(path)
    assert error.token in REFUSAL_TOKENS
    rendered = str(error)
    for marker in MARKERS:
        assert marker not in rendered
    return error


def assert_accepted(schema, payload):
    """Assert a legal payload validates, and that validation did not mutate it."""
    before = canonical_bytes(payload)
    schema.validate_record(payload)
    assert canonical_bytes(payload) == before


# --------------------------------------------------------------------------
# Bounded module discovery for the laboratory-local forward quarantine.
# Scans only experiments/source_record/**. Never the repository generally.
# --------------------------------------------------------------------------


def lab_production_modules():
    """Every non-test Python module under the laboratory, sorted."""
    return sorted(
        path
        for path in LAB_DIR.rglob("*.py")
        if TESTS_DIR not in path.parents
        and path.parent != TESTS_DIR
        and "__pycache__" not in path.parts
    )


def lab_test_modules():
    """Every Python module under the laboratory tests tree, sorted."""
    return sorted(
        path
        for path in TESTS_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )
