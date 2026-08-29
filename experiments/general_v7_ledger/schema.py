"""Public schema surface for ``general-v7-technology-ledger-v1``.

This module is one of the two frozen public surfaces the acceptance suite
names. The shared implementation core lives in the package module
``experiments/general_v7_ledger/__init__.py``: GV7-S-028 closes every
production module over a standard-library import allowlist with no sibling
carve-out and refuses relative imports, and the call-name tripwire bans every
dynamic-import mechanism -- so the one location guaranteed by the import
system itself to have executed before this module, in every required
execution mode, is the parent package. The bindings below therefore read the
already-imported package object from ``sys.modules``; nothing here imports,
retrieves or executes anything.
"""

import sys

_core = sys.modules["experiments.general_v7_ledger"]

SCHEMA_ID = _core.SCHEMA_ID
LEDGER_ID = _core.LEDGER_ID
CORPUS = _core.CORPUS
INTAKE_STATE = _core.INTAKE_STATE
NOT_SUPPLIED = _core.NOT_SUPPLIED
ID_PATTERN = _core.ID_PATTERN

ROOT_KEYS = _core.ROOT_KEYS
COLLECTION_KEYS = _core.COLLECTION_KEYS
KEYS_BY_COLLECTION = _core.KEYS_BY_COLLECTION
ID_FIELD_BY_COLLECTION = _core.ID_FIELD_BY_COLLECTION
ROOT_COLLECTION_BOUNDS = _core.ROOT_COLLECTION_BOUNDS

BATCH_KINDS = _core.BATCH_KINDS
ROLES = _core.ROLES
ATTRIBUTION_CLASSES = _core.ATTRIBUTION_CLASSES
RETIRED_ATTRIBUTION_CLASSES = _core.RETIRED_ATTRIBUTION_CLASSES
CLAIM_ATTRIBUTION_CLASSES = _core.CLAIM_ATTRIBUTION_CLASSES
RELATIONSHIP_ATTRIBUTION_CLASSES = _core.RELATIONSHIP_ATTRIBUTION_CLASSES
RESERVED_UNUSED_ATTRIBUTION_CLASSES = _core.RESERVED_UNUSED_ATTRIBUTION_CLASSES
RETRIEVAL_STATES = _core.RETRIEVAL_STATES
SOURCE_VERIFICATION_STATES = _core.SOURCE_VERIFICATION_STATES
CLAIM_VERIFICATION_STATES = _core.CLAIM_VERIFICATION_STATES
RELATIONSHIP_VERIFICATION_STATES = _core.RELATIONSHIP_VERIFICATION_STATES
UNRESOLVED_STATES = _core.UNRESOLVED_STATES
PRESERVATION_STATES = _core.PRESERVATION_STATES
EXECUTABLE_STATES = _core.EXECUTABLE_STATES
IDENTITY_ORIGINS = _core.IDENTITY_ORIGINS
METADATA_PROVENANCE = _core.METADATA_PROVENANCE
LOCATOR_ABSENCE_REASONS = _core.LOCATOR_ABSENCE_REASONS
RELATIONSHIP_TYPES = _core.RELATIONSHIP_TYPES
RELATIONSHIP_BASES = _core.RELATIONSHIP_BASES
CORRECTION_KINDS = _core.CORRECTION_KINDS
ARTIFACT_CLASSES = _core.ARTIFACT_CLASSES
ORDINARY_DISPOSITION = _core.ORDINARY_DISPOSITION
SAFETY_DISPOSITIONS = _core.SAFETY_DISPOSITIONS
CONFLICT_FAMILIES = _core.CONFLICT_FAMILIES

LABEL_MAX = _core.LABEL_MAX
TEXT_MAX = _core.TEXT_MAX
LIST_MAX = _core.LIST_MAX
ROOT_COLLECTION_MAX = _core.ROOT_COLLECTION_MAX

REFUSAL_TOKENS = _core.REFUSAL_TOKENS
LedgerError = _core.LedgerError

validate_ledger = _core.validate_ledger
