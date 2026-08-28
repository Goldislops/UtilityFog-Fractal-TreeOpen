# `general-v7-technology-ledger-v1` — frozen admission contract

**Status: contract and acceptance surface only. No implementation exists in this
commit.** No validator, schema module, ledger data, bibliography, intake report,
README, or workflow is authored here. The acceptance suite is expected to be
**red** wherever it depends on those files; that redness is the evidence the
independent acceptance surface preceded implementation.

## 1. Identity

    schema        source-record-v3
    ledger_id     general-v7-technology-ledger-v1
    corpus        GENERAL V7 TECHNOLOGY CORPUS
    intake_state  intake-complete

`source-record-v3` is the **schema** identity; `general-v7-technology-ledger-v1`
is the **ledger** identity. They are distinct fields and neither substitutes for
the other.

**The UAP V6 corpus is absent from this ledger.** No V6 source, claim, batch,
artifact, relationship, or verification state appears here in any form. Every
identifier lives in the corpus-specific `GV7-*` namespace. **Cross-corpus
bridges are deferred to a separate Bridge Register** and are not representable
in this schema: there is no bridge collection, no cross-corpus reference field,
and no path by which V7 material could inherit a V6 verification state.

## 2. Epistemic limit

This ledger records **what was supplied, by whom, with what limitations**. It
establishes nothing about the world.

- **Zero sources have been retrieved. Zero source identities are verified. Zero
  claims are verified.** No validator retrieves, opens, resolves, or contacts a
  locator, and none may be added.
- A syntactically valid URL is **not** evidence that a resource exists, that it
  is what the supplier said, or that its content matches the claim.
- **Past-tense AURA implementation language — "implemented", "deployed",
  "installed", "configured", "validated" — is not implementation evidence.** It
  is recorded as an attributed claim and nothing more.
- **Scientific, biological, cosmological and material analogies are design
  inspiration, never proof that a proposed software mechanism works.**
- Enthusiasm, repetition, a plausible analogy, or another agent's confidence
  never promotes a claim.
- **A green suite proves conformance to this contract. It proves nothing about
  the truth of any recorded claim**, and a human audit remains a separate and
  required acceptance step.

## 3. Physical manifest

### 3a. Present in this commit

    experiments/general_v7_ledger/CONTRACT.md
    experiments/general_v7_ledger/tests/__init__.py
    experiments/general_v7_ledger/tests/_support.py
    experiments/general_v7_ledger/tests/test_contract.py
    experiments/general_v7_ledger/tests/test_ledger_structure.py
    experiments/general_v7_ledger/tests/test_inventory.py
    experiments/general_v7_ledger/tests/test_provenance.py
    experiments/general_v7_ledger/tests/test_controls_manifest.py

### 3b. Absent — future implementation, not yet authorized

    experiments/general_v7_ledger/__init__.py
    experiments/general_v7_ledger/schema.py
    experiments/general_v7_ledger/validate.py
    experiments/general_v7_ledger/ledger.json
    experiments/general_v7_ledger/BIBLIOGRAPHY.md
    experiments/general_v7_ledger/INTAKE_REPORT.md
    experiments/general_v7_ledger/README.md

Tests **name** these files and assert their required properties. They never
create them. No workflow, configuration, dependency file, source datum, source
summary, or bridge record is authored in this phase.

## 4. Namespaces

All identifiers match:

    \AGV7-(BAT|SRC|CLM|REL|UNR|ART|COR)-[0-9]{4}\Z

`[0-9]` is load-bearing, not stylistic: Python's `\d` matches Arabic-Indic and
Devanagari digits and `int()` parses them.

| Segment | Collection | Meaning |
|---|---|---|
| `BAT` | `batches` | one intake batch |
| `SRC` | `sources` | one provisional external-source identity |
| `CLM` | `claims` | one attributed, limited claim |
| `REL` | `relationships` | one within-corpus relationship |
| `UNR` | `unresolved` | one recorded unresolved issue or conflict |
| `ART` | `artifacts` | one preserved, rejected synthesis artifact |
| `COR` | `corrections` | one additive correction record |

Identifiers are **globally unique across every collection**.

## 5. Frozen inventory

The future implementation must represent **exactly**:

| Quantity | Value |
|---|---|
| intake batches | **63** |
| provisional external-source identities | **61** |
| preserved synthesis artifacts | **3** |
| sources with a supplied URL/title/channel | **26** |
| sources without an exact supplied URL | **35** |
| retrieved sources | **0** |
| verified source identities | **0** |
| verified claims | **0** |
| admitted V6–V7 bridge records | **0** |

26 + 35 = 61, and the split is positional: **`GV7-SRC-0001` through
`GV7-SRC-0035` have no exact supplied URL; `GV7-SRC-0036` through
`GV7-SRC-0061` carry supplied URL/title/channel metadata.**

Required artifact identities, all three preserved and rejected:
`GV7-ART-0001`, `GV7-ART-0002`, `GV7-ART-0003`.

**Batch 62** (`GV7-BAT-0062`) is an **artifact-bearing batch that introduces no
new external-source identity**. **Batch 63** (`GV7-BAT-0063`) is a
**bibliography-metadata batch that updates existing source identities
`GV7-SRC-0036` through `GV7-SRC-0061` and creates no further source.**

**No frozen total is declared for claims, relationships, or unresolved issues.**
Inventing one would freeze a number nobody has counted. Instead:

- every external source carries **at least one** attributed, limited claim;
- **every count the validator emits equals the actual validated collection
  length** — counts are computed, never asserted from a constant;
- `relationships` and `unresolved` are **non-empty**, uniquely identified, and
  every reference resolves;
- the conflict families of section 10 are each covered by at least one
  unresolved record.

## 6. Record shapes

### 6a. Root

Closed key set, exactly:

    schema, ledger_id, corpus, intake_state,
    batches, sources, claims, relationships, unresolved, artifacts, corrections

Each collection is an exact builtin `list`. `corrections` may be empty; every
other collection is non-empty.

### 6b. `batch`

    batch_id            GV7-BAT-NNNN
    batch_ordinal       exact int, 1..63, equal to the id's numeric segment
    batch_kind          BATCH_KINDS
    introduces_sources  list of GV7-SRC ids (may be empty)
    introduces_artifacts list of GV7-ART ids (may be empty)
    updates_sources     list of GV7-SRC ids (may be empty)
    supplied_by_role    ROLES
    supplied_by_label   free text, 1..LABEL_MAX
    notes               free text, 1..TEXT_MAX

### 6c. `source`

    source_id           GV7-SRC-NNNN
    batch_ref           the introducing GV7-BAT id
    supplied_title      free text 1..TEXT_MAX, or the token "not-supplied"
    supplied_creator    free text 1..LABEL_MAX, or the token "not-supplied"
    supplied_locator    free text 1..TEXT_MAX, or null
    normalized_locator  free text 1..TEXT_MAX, or null
    locator_absence     LOCATOR_ABSENCE_REASONS, or null
    supplied_date       ISO YYYY-MM-DD, or the token "not-supplied"
    carrier_role        ROLES
    carrier_label       free text 1..LABEL_MAX
    upstream_attribution free text 1..TEXT_MAX, or the token "not-supplied"
    metadata_provenance METADATA_PROVENANCE
    retrieval_state     RETRIEVAL_STATES
    verification_state  SOURCE_VERIFICATION_STATES
    limitations         non-empty list of free text
    safety_disposition  SAFETY_DISPOSITIONS
    supersedes          null, or a supersedes block

**Locator rules.** `supplied_locator` and `normalized_locator` are both present
or both `null`; `locator_absence` is present exactly when they are `null`. A
present `normalized_locator` must be **HTTPS-only in shape**. The original
supplied form is always retained alongside the normalized one — normalization
never replaces what was supplied. **A syntactically valid URL is never treated
as evidence of anything**, and no field can express that it is.

**Verification.** `retrieval_state` is closed to `not-attempted` and
`verification_state` is closed to `supplied-unretrieved` — ladder level 1, which
**is** the unverified condition. There is deliberately **no separate boolean**:
a boolean could drift out of step with the ladder, and the ladder is the single
source of truth.

### 6d. `claim`

    claim_id            GV7-CLM-NNNN
    source_ref          exactly one GV7-SRC id
    batch_ref           exactly one GV7-BAT id
    claim_text          free text, 1..TEXT_MAX
    attribution_class   ATTRIBUTION_CLASSES
    evidence_basis      free text, 1..TEXT_MAX
    limitations         non-empty list of free text
    safety_disposition  SAFETY_DISPOSITIONS
    verification_state  CLAIM_VERIFICATION_STATES
    supersedes          null, or a supersedes block

### 6e. `relationship`

    relationship_id     GV7-REL-NNNN
    left_ref            GV7-SRC or GV7-CLM id
    right_ref           GV7-SRC or GV7-CLM id
    relationship_type   RELATIONSHIP_TYPES
    basis               RELATIONSHIP_BASES
    recorded_by_role    ROLES
    recorded_by_label   free text, 1..LABEL_MAX

Both endpoints resolve, are of the same kind, and are **distinct**: a
self-relationship is refused. Duplicate `(left_ref, right_ref, type)` triples
are refused. **Duplicate and conflicting material is cross-referenced, never
deleted.**

### 6f. `unresolved`

    unresolved_id       GV7-UNR-NNNN
    conflict_family     CONFLICT_FAMILIES
    statement           free text, 1..TEXT_MAX
    positions           list of 2..8 free-text position statements
    refs                non-empty list of GV7-SRC or GV7-CLM ids
    resolution_state    UNRESOLVED_STATES
    recorded_by_role    ROLES
    recorded_by_label   free text, 1..LABEL_MAX

`resolution_state` is closed to `unresolved`. **No field can record which
position is correct**, and no vocabulary token expresses adjudication.

### 6g. `artifact`

    artifact_id         GV7-ART-NNNN
    introducing_batch   GV7-BAT id
    artifact_class      ARTIFACT_CLASSES
    identity_origin     IDENTITY_ORIGINS
    preservation_status PRESERVATION_STATES
    rejection_basis     free text, 1..TEXT_MAX
    executable_status   EXECUTABLE_STATES
    safety_disposition  SAFETY_DISPOSITIONS
    summary             free text, 1..TEXT_MAX

`preservation_status` is closed to `preserved`; `executable_status` is closed to
`non-executable`. **An artifact is a preserved, rejected synthesis artifact —
never an executable prompt and never an authorization.**

### 6h. `correction`

    correction_id       GV7-COR-NNNN
    target_ref          any existing GV7 id
    correction_kind     CORRECTION_KINDS
    statement           free text, 1..TEXT_MAX
    recorded_by_role    ROLES
    recorded_by_label   free text, 1..LABEL_MAX

**Corrections are additive.** A correction never edits, deletes, or rewrites its
target; the target remains present and independently valid.

### 6i. `supersedes` block

    record_id           an existing id of the same collection
    content_digest      \A[0-9a-f]{64}\Z

A successor never removes its predecessor, and **verification state may not
improve across a supersession** — in v1 it cannot improve at all, because every
state vocabulary is closed to a single token.

## 7. Closed vocabularies

    SCHEMA_ID   = "source-record-v3"
    LEDGER_ID   = "general-v7-technology-ledger-v1"
    CORPUS      = "GENERAL V7 TECHNOLOGY CORPUS"
    INTAKE_STATE= "intake-complete"

    BATCH_KINDS = ("source-bearing", "artifact-bearing",
                   "bibliography-metadata")

    ROLES = ("relay-agent", "operator", "auditor", "analysis-seat",
             "external-author", "unattributed")

    ATTRIBUTION_CLASSES = (
        "direct-source", "source-derived-excerpt", "aura-summary",
        "aura-inference", "aura-capability-claim",
        "kev-observation-or-authorization", "jack-inference-or-audit",
        "eighty-four-inference", "implementation-proposal",
        "verified-implementation-evidence")

    RETRIEVAL_STATES            = ("not-attempted",)
    SOURCE_VERIFICATION_STATES  = ("supplied-unretrieved",)
    CLAIM_VERIFICATION_STATES   = ("unverified",)
    UNRESOLVED_STATES           = ("unresolved",)
    PRESERVATION_STATES         = ("preserved",)
    EXECUTABLE_STATES           = ("non-executable",)
    IDENTITY_ORIGINS            = ("supplied", "generated")

    METADATA_PROVENANCE = ("supplied-by-carrier", "supplied-by-operator",
                           "derived-from-supplied-text", "not-supplied")

    LOCATOR_ABSENCE_REASONS = ("no-exact-locator-supplied",
                               "locator-withheld-by-carrier",
                               "locator-not-applicable")

    RELATIONSHIP_TYPES = ("duplicate-of-supplied-material",
                          "conflicts-with", "follow-up-to", "mirror-of-supplied-material",
                          "same-supplied-topic", "derived-from-supplied-material")

    RELATIONSHIP_BASES = ("recorded-by-inspection",
                          "recorded-from-supplied-material",
                          "recorded-as-proposed-elsewhere")

    CORRECTION_KINDS = ("correction", "contest", "successor")

    ARTIFACT_CLASSES = ("premature-synthesis", "premature-master-prompt",
                        "premature-authorization")

    SAFETY_DISPOSITIONS = (
        "ordinary",
        "quarantined-access-control-avoidance",
        "quarantined-covert-communication",
        "quarantined-credential-or-personal-data",
        "quarantined-unauthorized-external-interaction",
        "quarantined-self-replication-or-mutation",
        "quarantined-hidden-monitoring",
        "quarantined-unsigned-native-execution",
        "quarantined-destructive-storage-or-cooling")

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
        "quarantined-security-or-privacy-proposal")

    LABEL_MAX = 128 ; TEXT_MAX = 8192 ; LIST_MAX = 64
    MAX_LEDGER_BYTES = 4194304        # fixed, documented byte ceiling
    NOT_SUPPLIED = "not-supplied"

**Absent by decision, and never to be added:** any token meaning corroborates,
confirms, proves, verified-by-agreement, or otherwise promoting a record by
assertion; any bridge or cross-corpus type; any adjudication token on an
unresolved record.

## 8. Quarantine

Material of the following kinds is recorded as an **attributed, categorical
summary with a quarantine disposition**, calmly and without operational detail:

avoidance of access controls, authentication, CAPTCHAs, WAFs or rate limits ·
covert DNS, ICMP, steganographic or hidden communication · credential
discovery, keylogging, hidden recording, synthetic identities, or personal-data
collection · probing or otherwise interacting with government or third-party
systems without authority · persistent hidden background monitoring ·
self-replication or uncontrolled mutation · unsigned dynamic native-code
execution · destructive storage settings or unapproved cooling control.

**The ledger may preserve an attributed summary of such a proposal. It must
never store a ready-to-run command, a credential, an exploit payload, a target
list, or any operational authorization.** Access controls and denials are stop
conditions, not obstacles. Recording a proposal is not endorsing it, and no
field can express endorsement.

## 9. Structural and validator contract

The future validator satisfies all of the following.

**Input and confinement.** It accepts a **file path only** — the committed
`ledger.json`. A directory, a missing path, a symbolic link or other reparse
point, or any path escaping the accepted root is refused. It never reads an
environment variable or the current working directory to locate input, and
Windows path behaviour is safe: no drive-relative, UNC-escaping, or
reserved-name traversal.

**Bytes and parsing.** The fixed ceiling `MAX_LEDGER_BYTES` is enforced over
**captured bytes before any parsing**. JSON parsing rejects duplicate object
keys. Every parse-step `ValueError`, including the integer-conversion
digit-limit failure that is **not** a `JSONDecodeError`, is refused as a
malformed-input token; no parser diagnostic, digit count, or literal is ever
disclosed.

**Types.** Exact builtin scalar and container types throughout. Subclasses are
refused before any hook on the rejected object can run. `bool` is refused
wherever `int` is required, and `int` wherever `bool` is required. No float
appears anywhere. Every integer carries an explicit bounded range.

**Shape.** Root and every nested block have exact, closed key sets. Every list
is duplicate-free and within `LIST_MAX`. Identifiers are globally unique. Every
reference resolves to an existing record of the declared kind. Self-relationships
are refused.

**Purity.** Validation is pure and non-mutating: it never writes, infers,
rewrites, defaults, or upgrades a field, and the validated payload and the
committed bytes are byte-identical before and after.

**Refusals.** A refusal carries exactly a closed token and a schema-declared
path — **no rejected-value slot**. Refusal tokens are **cause-agnostic and
non-disclosing**: they never echo input, never invoke `__repr__`/`__str__`/
`__hash__`/`__eq__` on a rejected object, never read a runtime type name, never
carry a number derived from input, and never chain an exception. There is no
verbose mode and no flag, configuration, or environment variable that alters
refusal content.

**Determinism.** Success emits **one line of canonical JSON** — sorted keys,
ASCII escaping, compact separators, no timestamps — followed by exactly one line
feed. Output is byte-identical across repeated runs, key insertion order,
separate processes, differing hash seeds, and **normal, `-O` and `-OO`**
execution. No bare `assert` appears in any production module, so `-O` strips
nothing load-bearing.

**Imports.** Neither `schema` nor `validate` imports a network-capable module:
no `socket`, `http`, `urllib`, `requests`, `ftplib`, `smtplib`, `asyncio`,
`ssl`, `subprocess`, or dynamic-import mechanism. **No validator retrieves,
opens, resolves, or contacts a locator**, and there is no code path that could.

**Emitted counts.** Every count in the output equals the actual validated
collection length. No count is read from a constant.

These controls **do not weaken** the accepted neutral `source_record`
conventions; where they overlap, they restate them.

## 10. Required unresolved coverage

At least one `unresolved` record exists for **each** of the thirteen
`CONFLICT_FAMILIES` of section 7. Each records the competing positions and
resolves none. **The acceptance controls assert coverage and neutrality only —
they never assert that either side of any conflict is true**, and the schema has
no field in which such an assertion could be stored.

## 11. Bibliography contract

The future `BIBLIOGRAPHY.md` must:

- contain **every one of the 61 source identities exactly once**;
- contain **every present locator exactly once**;
- **fabricate no locator** — a source without a supplied locator is rendered
  with its recorded absence reason and nothing else;
- add no source, and remove none.

## 12. Acceptance criteria for the future implementation

Every rule in sections 4 through 11, with a failing-input control for each and
every positive control passing — a validator that refuses everything is broken,
not correct. Standard library only. No bare `assert`. No network-capable
import. The refusal carrier has no value slot. Counts computed, never asserted.
Controls match the manifest in `tests/test_controls_manifest.py` exactly.

**What these controls do not prove:** they are static and behavioural checks
over this ledger's own surface. They do not verify a single source, do not
retrieve anything, do not establish that any recorded claim is true, and do not
establish repository configuration. **A human audit remains a separate and
required acceptance step.**

## 13. Deferred from v1

Source retrieval and every ladder state above `supplied-unretrieved`; claim
verification; the Bridge Register and every cross-corpus record; bibliography
and intake-report generation; any workflow; any dependency; any hardware,
model, or capability assertion. **Historical v1 records remain unchanged when
any of these lands** — every future change is an additive correction.
