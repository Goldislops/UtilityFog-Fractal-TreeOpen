# `general-v7-technology-ledger-v1` — frozen admission contract

**Status: contract and acceptance surface. The implementation is authored
separately, and this suite admits both the pre-implementation and the
implemented state.** The acceptance suite is expected to be **red** wherever it
depends on an implementation file that does not yet exist; that redness is a
truthful report of absence, never a claim that the implementation must remain
absent.

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

The laboratory has **exactly two admissible states**, and the acceptance suite
admits both.

### 3a. Phase-A surface — present in both states

    experiments/general_v7_ledger/CONTRACT.md
    experiments/general_v7_ledger/tests/__init__.py
    experiments/general_v7_ledger/tests/_support.py
    experiments/general_v7_ledger/tests/test_contract.py
    experiments/general_v7_ledger/tests/test_ledger_structure.py
    experiments/general_v7_ledger/tests/test_inventory.py
    experiments/general_v7_ledger/tests/test_provenance.py
    experiments/general_v7_ledger/tests/test_controls_manifest.py

### 3b. Implementation surface — all seven, or none

    experiments/general_v7_ledger/__init__.py
    experiments/general_v7_ledger/schema.py
    experiments/general_v7_ledger/validate.py
    experiments/general_v7_ledger/ledger.json
    experiments/general_v7_ledger/BIBLIOGRAPHY.md
    experiments/general_v7_ledger/INTAKE_REPORT.md
    experiments/general_v7_ledger/README.md

The two admissible states are **`pre-implementation`** — the eight Phase-A
files and none of the seven — and **`implemented`** — the eight and all seven.
**A partial implementation surface is refused**, because a half-written
validator alongside a written ledger is the state in which a broken
implementation most easily passes for a working one. **An unrelated extra path
is refused** too.

**Git history, not a permanently red future test, is the evidence that the
acceptance surface preceded the implementation.** The commits that authored
this contract and these controls carry no implementation file, and those
commits are immutable. **No control asserts that the implementation is
absent.** Such a control could only ever be made green by editing or retiring
it, and an assertion that must be destroyed to permit the work it guards
proves nothing about the work and destroys its own record in the process.

Tests **name** the implementation files and assert their required properties.
They never create them. No workflow, configuration, dependency file, source
datum, source summary, or bridge record is authored in this phase.

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

**Artifact provenance is frozen record by record.** The three artifacts
arrived in three *different* batches, and only the third arrived in batch 62:

| Artifact | Introducing batch |
|---|---|
| `GV7-ART-0001` | `GV7-BAT-0010` |
| `GV7-ART-0002` | `GV7-BAT-0022` |
| `GV7-ART-0003` | `GV7-BAT-0062` |

The mapping is **reciprocal**: each artifact's `introducing_batch` names a
batch whose `introduces_artifacts` list contains that artifact, and no other
batch claims it. Any statement that all three artifacts originated in batch 62
is withdrawn — it would have destroyed the provenance of two of them.

**Batch 62** (`GV7-BAT-0062`) is an **artifact-bearing batch that introduces no
new external-source identity**; it introduces `GV7-ART-0003` only. **Batch 63**
(`GV7-BAT-0063`) is a **bibliography-metadata batch that updates existing source
identities `GV7-SRC-0036` through `GV7-SRC-0061`, creates no further source, and
introduces no artifact.**

**No frozen total is declared for claims, relationships, or unresolved issues.**
Inventing one would freeze a number nobody has counted. Instead:

- every external source carries **at least one** attributed, limited claim;
- **every count the validator emits equals the actual validated collection
  length** — counts are computed, never asserted from a constant;
- `relationships` and `unresolved` are **non-empty**, uniquely identified, and
  every reference resolves;
- **introduction is reciprocal in both directions**, for sources and for
  artifacts alike: a record naming an introducing batch that omits it is
  refused; a batch listing a record whose own introducing field points elsewhere
  is refused; and a record listed by two batches is refused. Checking only that
  a reference resolves is not reciprocity, and the refusal token is
  `introduction-not-reciprocal`;
- the conflict families of section 10 are each covered by at least one
  unresolved record.

**Bounds are not totals.** A bound refuses an absurd document; it never asserts
how many records exist. `batches`, `sources` and `artifacts` are frozen exactly
at 63, 61 and 3. `claims` is **at least 61** — one per source — and at most
`ROOT_COLLECTION_MAX`. `relationships` and `unresolved` are **non-empty** and at
most `ROOT_COLLECTION_MAX`. `corrections` runs from **zero** to
`ROOT_COLLECTION_MAX`. No count is ever read from these figures.

## 6. Record shapes

### 6a. Root

Closed key set, exactly:

    schema, ledger_id, corpus, intake_state,
    batches, sources, claims, relationships, unresolved, artifacts, corrections

Each collection is an exact builtin `list`. `corrections` may be empty; every
other collection is non-empty.

**`LIST_MAX` bounds nested lists, never a root collection.** It applies to a
`limitations` list, a `positions` list, an `introduces_sources` list — the lists
*inside* a record.

The scope matters because section 9 previously said "every list is
duplicate-free and within `LIST_MAX`", and a root collection is a list. Applying
64 there is not impossible by arithmetic — 63 batches and 61 sources both fit —
and that is precisely what makes it dangerous. It leaves **one** record of
headroom on `batches` and three on `sources`, and it silently caps
`claims`, `relationships`, `unresolved` and `corrections` at 64 apiece, which
section 5 explicitly declines to freeze. A bound one record away from a frozen
total is not a resource ceiling; it is an accidental total that nobody counted.
It would also cap the number of corrections this ledger could ever record, and
`corrections` is its entire additive history channel.

Root collections are therefore bounded by `ROOT_COLLECTION_MAX`, a resource
ceiling and not a frozen factual total, with the per-collection minima and
maxima of section 5.

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
    supplied_channel    free text 1..LABEL_MAX, or the token "not-supplied"
    supplied_locator    free text 1..TEXT_MAX, or null
    normalized_locator  free text 1..TEXT_MAX, or null
    locator_absence     LOCATOR_ABSENCE_REASONS, or null
    supplied_date       free text 1..LABEL_MAX, or the token "not-supplied"
    normalized_date     ISO YYYY-MM-DD, or null
    carrier_role        ROLES
    carrier_label       free text 1..LABEL_MAX
    upstream_attribution free text 1..TEXT_MAX, or the token "not-supplied"
    metadata_provenance METADATA_PROVENANCE
    retrieval_state     RETRIEVAL_STATES
    verification_state  SOURCE_VERIFICATION_STATES
    limitations         non-empty list of free text
    safety_dispositions non-empty, duplicate-free list from SAFETY_DISPOSITIONS
    supersedes          null

**A supplied field is verbatim and is never trimmed or rewritten.** Every
`supplied_*` field records what the carrier actually supplied, character for
character. Requiring a supplied value to equal its own whitespace-stripped form
would quietly destroy the provenance this ledger exists to keep, so **every
whitespace-canonicality requirement applies to a `normalized_*` field only.**

**Dates keep both forms.** `supplied_date` is the verbatim supplied text, or the
token `not-supplied` when no date was supplied at all. `normalized_date` is an
ISO `YYYY-MM-DD` calendar date, or `null`. A supplied date that is real but is
not a calendar date — `Spring 2024`, `c. 2019`, `undated` — is **retained
verbatim with `normalized_date` `null`**; it is never discarded and never
guessed into a day. `supplied_date` equal to `not-supplied` **requires**
`normalized_date` to be `null`. The converse does not hold, because a supplied
but unnormalizable date is precisely the case worth recording.

**Creator and channel are separate provenance.** The 26 sources carrying
bibliography metadata require a supplied title and a supplied channel.
`supplied_creator` **may honestly remain `not-supplied`**: many supplied items
name a publisher or a platform without naming an author, and inventing one
would be fabrication.

**Locator rules.** `supplied_locator` and `normalized_locator` are both present
or both `null`; `locator_absence` is present exactly when they are `null`, and
is `null` exactly when they are present. A present `normalized_locator` must be
**HTTPS-only in shape** and whitespace-canonical; `supplied_locator` is subject
to neither, being verbatim. The original supplied form is always retained
alongside the normalized one — normalization never replaces what was supplied.
**A syntactically valid URL is never treated as evidence of anything**, and no
field can express that it is.

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
    attribution_class   CLAIM_ATTRIBUTION_CLASSES
    evidence_basis      free text, 1..TEXT_MAX
    limitations         non-empty list of free text
    safety_dispositions non-empty, duplicate-free list from SAFETY_DISPOSITIONS
    verification_state  CLAIM_VERIFICATION_STATES
    supersedes          null

**A v1 claim can never be verified implementation evidence.** Every claim in
this ledger is closed to `unverified`, so a claim carrying
`verified-implementation-evidence` would contradict its own verification state
in the same record. `CLAIM_ATTRIBUTION_CLASSES` therefore excludes that token
exactly as `RELATIONSHIP_ATTRIBUTION_CLASSES` does. The token **remains
reserved** in the broader `ATTRIBUTION_CLASSES` vocabulary for a future
verified-evidence schema; **no v1 claim and no v1 relationship may use it**, and
the validator refuses it in both positions.

### 6e. `relationship`

    relationship_id     GV7-REL-NNNN
    left_ref            GV7-SRC or GV7-CLM id
    right_ref           GV7-SRC or GV7-CLM id
    relationship_type   RELATIONSHIP_TYPES
    basis               RELATIONSHIP_BASES
    attribution_class   RELATIONSHIP_ATTRIBUTION_CLASSES
    verification_state  RELATIONSHIP_VERIFICATION_STATES
    limitations         non-empty, duplicate-free list of bounded free text
    recorded_by_role    ROLES
    recorded_by_label   free text, 1..LABEL_MAX

Both endpoints resolve, are of the same kind, and are **distinct**: a
self-relationship is refused. Duplicate `(left_ref, right_ref, type)` triples
are refused. **Duplicate and conflicting material is cross-referenced, never
deleted.**

**A relationship is itself unverified, and says so.** Its `verification_state`
is closed to `unverified`, its `limitations` are mandatory, and its
`attribution_class` records the carrier/recorder distinction — who noticed the
relation and on what footing. `verified-implementation-evidence` is **not
permitted** as a relationship attribution: a relationship is an observation
about two records, never evidence about the world. **A relationship never
promotes, verifies, rehomes, or transfers confidence between its endpoints**,
and no field can express that it does.

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
    safety_dispositions non-empty, duplicate-free list from SAFETY_DISPOSITIONS
    summary             free text, 1..TEXT_MAX

`preservation_status` is closed to `preserved`; `executable_status` is closed to
`non-executable`. **An artifact is a preserved, rejected synthesis artifact —
never an executable prompt and never an authorization.**

### 6h. `correction`

    correction_id       GV7-COR-NNNN
    target_ref          an existing batch, source, claim, relationship,
                        unresolved or artifact id — never a GV7-COR id
    correction_kind     CORRECTION_KINDS
    statement           free text, 1..TEXT_MAX
    recorded_by_role    ROLES
    recorded_by_label   free text, 1..LABEL_MAX

**Corrections are additive.** A correction never edits, deletes, or rewrites its
target; the target remains present and independently valid. **`corrections` is
the additive history channel of v1**: every later change to a historical record
is expressed as a correction, and the historical record itself never changes.

**A correction may not target a correction.** Permitting a `GV7-COR-*`
`target_ref` would admit a self-targeting correction, a two-record cycle, and
arbitrarily long cycles, and v1 has no field in which a resolution order could
be recorded — so a cycle would be unreadable rather than merely odd. The
refusal token is `correction-target-not-permitted`, and it is distinct from
`reference-not-found`: the target exists, and is refused for being the wrong
kind of record to correct.

### 6i. `supersedes` — reserved design, closed to `null` in v1

**In v1, `source.supersedes` and `claim.supersedes` are present and closed to
`null`. A non-null supersession is refused**, with the token
`supersedes-not-permitted`, and non-null supersession is **deferred to a future
schema version**.

The channel is closed because in v1 it is dead, not merely unused. The frozen
inventory fixes `sources` at exactly 61 with a positional locator split, so a
successor source would have to be a 62nd record — refused by the inventory — or
consume one of the 61 identities, which is not succession but replacement. And
every verification vocabulary is closed to a single token, so nothing about a
successor could differ in the one dimension a supersession exists to carry.
Any statement that source successors are operational in v1 is **withdrawn**.

The design below is **retained as reserved documentation for that future
version**, so the eventual implementation inherits a specification rather than
inventing one. Nothing in v1 may rely on it.

    record_id           an existing id of the same collection
    content_digest      \A[0-9a-f]{64}\Z

`content_digest` is the **SHA-256, lowercase hex, of the predecessor record's
canonical form**: `json.dumps(record, sort_keys=True, ensure_ascii=True,
separators=(",", ":"))` encoded UTF-8, with no trailing newline. Because the
domain is the canonical form and not the raw file bytes, reformatting the
document cannot break a chain while any content change does.

The predecessor must exist and belong to the **same collection**: a
cross-collection supersession is refused, as is a missing predecessor and a
digest that does not match. A successor never removes its predecessor, which
remains present and independently valid, and **verification state may not
improve across a supersession**.

All of that is reserved future design. **In v1 the only admissible value of
`supersedes` is `null`**, and additive history is recorded through
`corrections` instead.

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
        "kev-observation", "kev-authorization", "jack-inference-or-audit",
        "eighty-four-inference", "implementation-proposal",
        "verified-implementation-evidence")          # eleven values

    RETIRED_ATTRIBUTION_CLASSES = ("kev-observation-or-authorization",)

    RELATIONSHIP_ATTRIBUTION_CLASSES = ATTRIBUTION_CLASSES minus
                                       "verified-implementation-evidence"
    CLAIM_ATTRIBUTION_CLASSES        = ATTRIBUTION_CLASSES minus
                                       "verified-implementation-evidence"
    RESERVED_UNUSED_ATTRIBUTION_CLASSES = (
        "verified-implementation-evidence",)   # reserved, unusable in v1

    RELATIONSHIP_VERIFICATION_STATES = ("unverified",)
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

    LABEL_MAX = 128 ; TEXT_MAX = 8192
    LIST_MAX = 64                     # NESTED lists only, never a root
    ROOT_COLLECTION_MAX = 4096        # resource ceiling, not a factual total
    MAX_LEDGER_BYTES = 4194304        # fixed, documented byte ceiling
    NOT_SUPPLIED = "not-supplied"

    WINDOWS_RESERVED_NAMES = ("CON", "PRN", "AUX", "NUL",
                              "COM1".."COM9", "LPT1".."LPT9")

**`safety_dispositions` is a list, and provenance survives.** It is an exact
builtin list, non-empty, duplicate-free, and drawn only from the closed
vocabulary above. **`ordinary` is exclusive**: if present it must be the only
element. Otherwise one or more quarantine categories may coexist, because a
single proposal can be quarantined on several independent grounds at once and
collapsing them to one would lose provenance.

**`kev-authorization` is evidence of language, never runtime authority.** An
attributed historical `kev-authorization` record is evidence that authorization
language was supplied at some past moment, recorded like any other attributed
claim. **It is not current runtime authority.** It cannot authorize a tool, an
agent, network access, repository mutation, external interaction, a push, a
pull request, or a merge. **Only Kev's fresh task-level instruction can grant
such authority.** `kev-observation` is the separate class for an observation
that grants nothing; the retired compound token
`kev-observation-or-authorization` conflated the two and is refused.

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

**Input.** The interface is frozen as **exactly one explicitly supplied file
path**, and nothing else:

- the caller supplies one path argument; the validator reads **only** that file;
- **the path may lie outside the repository**, so an isolated temporary-file
  control can exercise the parser without writing anywhere in the tree. An
  earlier "must remain beneath an accepted repository root" requirement is
  **withdrawn**: it was unsatisfiable alongside temporary-file testing, and
  confinement is not what actually protects this validator — reading exactly
  one named file is;
- the path must resolve to an **existing regular file**; a directory, a missing
  path, or a non-regular file is refused;
- **no component of the supplied path may be a symbolic link, junction, or
  other redirecting reparse point**, so a swapped directory on the way to the
  file cannot redirect the read;
- it performs **no directory discovery, no adjacent-file discovery, no
  environment lookup, no current-directory lookup, and no locator retrieval**;
- drive-relative, malformed, and reserved-name paths remain refused, and
  Windows path behaviour is safe.

**Reparse points: redirection, not storage.** A path component is refused when
it is a symbolic link, a mount point or junction, or carries any reparse tag
with the **name-surrogate bit** (`0x20000000`) set — the tags that make a path
name something other than where it appears to be. It is **not** refused merely
for carrying `FILE_ATTRIBUTE_REPARSE_POINT`. A OneDrive cloud placeholder
carries that attribute too, and this repository lives inside a OneDrive folder,
so a blanket refusal would reject an ordinary unhydrated ledger file and make
the rule unimplementable on the machine it must run on.
`IO_REPARSE_TAG_SYMLINK` is `0xA000000C` and `IO_REPARSE_TAG_MOUNT_POINT` is
`0xA0000003`; both carry the name-surrogate bit, and an AppExecLink and a cloud
placeholder do not.

**The validator performs no retrieval, so its input must already be locally
hydrated.** Nothing faults a placeholder in, and nothing may be added that
would: hydration is the caller's business, and a read that would have to reach
the network is a read this validator does not perform.

**A final-component file symbolic link cannot be constructed here without
privilege**, so the deterministic fixture is a directory junction — creatable
unprivileged, and the harder case besides, because `os.path.islink` and
`Path.is_symlink` both report it as `False`. **That residual gap is disclosed
rather than skipped:** the file-symlink case is covered by the same tag rule and
by no fixture on this machine.

**Drive-relative and reserved-name refusal is frozen, not delegated.**
`C:ledger.json` names a per-drive current directory rather than a location, and
is refused. `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9` and `LPT1`–`LPT9` are
refused case-insensitively in **any** path component, including with an
extension (`CON.txt`) and with trailing dots or spaces (`CON.`, `NUL...`).
`COM0`, `LPT0`, `LPT10`, `CONSOLE` and `COMPANY` are **not** reserved and must
not be refused. The list is frozen here rather than delegated to
`pathlib.PurePath.is_reserved()`, which is deprecated, is scheduled for removal
in Python 3.15, and has varied across versions.

**The device namespace is refused on the anchor.** `\\?\` disables the
operating system's own reserved-name, trailing-dot and normalisation handling,
so it is the bypass for every other rule here; `\\.\` names a device
directly. Both are consumed into the *drive* rather than into a path component,
so a component scan cannot see them, and the refusal is
`path-device-namespace`.

**A disclosed gap, recorded rather than quietly closed.** Windows also reserves
`CONIN$`, `CONOUT$` and the superscript `COM¹`–`COM³` and `LPT¹`–`LPT³` forms,
which its device parser folds to the ASCII digit. **This contract deliberately
freezes the twenty-two names listed above and no more**, because that is the
list it was instructed to freeze and a wider one would be a number nobody
counted. The eight further names are recorded in the acceptance surface as a
known, uncovered gap. A future correction may promote them; until it does, they
are not refused and this contract does not pretend otherwise.

**Bytes and parsing.** The fixed ceiling `MAX_LEDGER_BYTES` is enforced over
**captured bytes before any parsing**.

**The captured bytes are decoded as strict UTF-8, and never handed to the
parser as bytes.** `json.loads` on `bytes` decodes with
`errors="surrogatepass"`, so raw WTF-8 — an unpaired surrogate encoded as
`ED A0 80` — is admitted silently, while `bytes.decode("utf-8")` refuses it.
Handing the parser bytes would therefore make the validator and this acceptance
suite disagree about the same file. The decode is strict and its failure is
refused as `ledger-encoding-invalid`.

**A duplicate object key carries its own exact token and is not a parse
`ValueError`.** Duplicate-key rejection is the validator's own refusal, raised
from an object-pairs hook while the parse is still running, and it is reported
as `json-duplicate-key`. Every **other** parse-step `ValueError` — an ordinary
syntax fault, and the integer-conversion digit-limit failure that is **not** a
`JSONDecodeError` — is refused as the single cause-agnostic token
`json-malformed`. **The general parse-`ValueError` rule therefore excludes the
duplicate-key refusal**, which would otherwise be collapsed into it and lose the
one parse diagnosis worth naming. **Neither path echoes input and neither chains
the original exception**: no parser diagnostic, digit count, position, or
literal is disclosed, `__cause__` is `None`, and `__suppress_context__` is set
on both.

**Types.** Exact builtin scalar and container types throughout. Subclasses are
refused before any hook on the rejected object can run. `bool` is refused
wherever `int` is required, and `int` wherever `bool` is required. No float
appears anywhere. Every integer carries an explicit bounded range.

**Shape.** Root and every nested block have exact, closed key sets. Every
**nested** list is duplicate-free and within `LIST_MAX`; every **root**
collection is bounded by section 5 and `ROOT_COLLECTION_MAX`. Identifiers are globally unique. Every
reference resolves to an existing record of the declared kind. Self-relationships
are refused.

**Purity.** Validation is pure and non-mutating: it never writes, infers,
rewrites, defaults, or upgrades a field, and the validated payload and the
committed bytes are byte-identical before and after.

**Refusal order.** Refusal is staged, and **the earliest applicable stage
wins**. An input violating two rules is refused by the earlier one, always, so
a refusal token identifies the stage that stopped the document and never a
race between checks:

1. lexical and path-entry checks — the shape of the supplied path,
   drive-relative and reserved-name refusal, existence, regular-file, and
   redirecting reparse points;
2. the byte ceiling, over captured bytes;
3. JSON parsing, including the duplicate-key refusal;
4. exact builtin types;
5. closed key sets and closed shapes;
6. identifiers, closed enum vocabularies, scalar bounds, and string
   encodability;
7. references, reciprocity, and domain rules;
8. canonical inventory rules.

**Encodability is a stage-6 rule, and `ensure_ascii=True` is load-bearing.** A
JSON `\uD800` escape decodes to a lone surrogate, which `str.encode("utf-8")`
cannot represent. The frozen canonical form sets `ensure_ascii=True`, which
re-escapes the surrogate back to ASCII — so canonical encoding **does not** in
fact crash on this input today, and any claim that it does is withdrawn.
Relaxing that flag to `ensure_ascii=False` **would** raise `UnicodeEncodeError`
on the same value. The validator therefore refuses any string carrying a
surrogate code point at stage 6, as `string-not-encodable`, **before** a digest
or a canonical rendering is computed: defence in depth for a flag that must
never be relaxed, not a repair for a crash the frozen form already avoids.

**Refusal classes and exit codes.** `schema.LedgerError` is the single refusal
base. `validate.LedgerPathError`, `validate.LedgerCeilingError` and
`validate.LedgerInputError` are its subclasses, covering stages 1, 2 and 3.
**None of the three is a subclass of another**, so a content refusal can never
be satisfied by a path refusal merely because the two share a superclass; a
refusal from stage 4 or later is a `schema.LedgerError` that is none of them.

Command-line exit codes are frozen: **`0` on success, `1` on any refusal, `2` on
a usage error.** `main` **returns** `0` and `1`; a usage error **raises**
`SystemExit(2)`, because an unusable invocation never reached the document. **A
refusal writes nothing to standard output** and writes **exactly one line** to
standard error: the closed token and a line feed, nothing else. Refusal content
is byte-identical whatever the environment: no flag, configuration, or
environment variable alters it.

**Refusals.** A refusal carries exactly a closed token and a schema-declared
path — **no rejected-value slot**. Refusal tokens are **cause-agnostic and
non-disclosing**: they never echo input, never invoke `__repr__`/`__str__`/
`__hash__`/`__eq__` on a rejected object, never read a runtime type name, never
carry a number derived from input, and never chain an exception. There is no
verbose mode and no flag, configuration, or environment variable that alters
refusal content.

**Determinism.** Success emits **one line of canonical JSON** — sorted keys,
ASCII escaping, compact separators, no timestamps — followed by exactly one line
feed. **The line feed is a single `0x0A` byte, so the output is written through
`sys.stdout.buffer`, never through `print`.** Windows text mode translates `\n`
to `\r\n`, so a `print`-based implementation emits `0x0D 0x0A` and the "exactly
one line feed" guarantee is false at byte level while every capture-based
control still passes. Output is byte-identical across repeated runs, key insertion order,
separate processes, differing hash seeds, and **normal, `-O` and `-OO`**
execution. No bare `assert` appears in any production module, so `-O` strips
nothing load-bearing.

**Imports.** Neither `schema` nor `validate` imports a network-capable module:
no `socket`, `http`, `urllib`, `requests`, `ftplib`, `smtplib`, `asyncio`,
`ssl`, `subprocess`, or dynamic-import mechanism. **No validator retrieves,
opens, resolves, or contacts a locator**, and there is no code path that could.

**The import allowlist is the authoritative rule.** A scan for call *names* is
at most a **heuristic tripwire** and establishes nothing: an alias, an attribute
lookup, or one level of indirection defeats it. Generic names such as `get`,
`run`, `post` and `request` also match `dict.get` and unrelated methods, and a
screen that fires on `dict.get` teaches its readers to ignore it, so they are
excluded. **No control claims that a call-name scan proves the absence of
networking.**

**Emitted counts.** Every count in the output equals the actual validated
collection length. No count is read from a constant, and the acceptance surface
**proves** it rather than restating it: one additional well-formed record is
added to a valid ledger, the real command-line interface is run over both, and
**exactly one count must change, by exactly one**. A hardcoded count table
fails that control.

These controls **do not weaken** the accepted neutral `source_record`
conventions; where they overlap, they restate them.

## 10. Required unresolved coverage

At least one `unresolved` record exists for **each** of the thirteen
`CONFLICT_FAMILIES` of section 7. Each records the competing positions and
resolves none. **The acceptance controls assert coverage and neutrality only —
they never assert that either side of any conflict is true**, and the schema has
no field in which such an assertion could be stored.

## 11. Bibliography contract

The static `BIBLIOGRAPHY.md` **is required in the future implementation**. A
separate automated bibliography-*generation* feature is **deferred** — the file
is a required artifact; a generator for it is not part of v1. The two are
distinct, and the deferral of the generator never excuses the absence of the
file.

**Both locator forms are preserved.** Normalisation never replaces what was
supplied, and the bibliography is where that promise is most easily broken.

**Accounting is structural, and never by substring.** Substring counting cannot
tell a locator from its own prefix; it cannot tell two sources that legitimately
share one locator from a duplicated rendering; and it silently mis-reads a
locator followed by punctuation or wrapped in parentheses. Containment tests of
the form *value in form or form in value* are **withdrawn** for the same reason.
The entry format is therefore frozen, and every value is compared **by equality
after parsing**:

    ### GV7-SRC-NNNN
    - supplied_locator: <canonical JSON scalar>
    - normalized_locator: <canonical JSON scalar>
    - locator_absence: <canonical JSON scalar>

Each labelled value is exactly one JSON scalar — a JSON string, or `null` —
parsed with `json.loads` and compared for **exact equality** against that
source's corresponding ledger field. The rules are then exact:

- **every one of the 61 source identities appears exactly once**, as exactly one
  `### GV7-SRC-NNNN` heading;
- **each of the three labelled fields appears exactly once inside its entry**;
- `supplied_locator` equals the recorded `supplied_locator` **exactly** — the
  preserved verbatim form, never a stripped or re-rendered one;
- `normalized_locator` equals the recorded `normalized_locator` exactly, and
  stays a **distinct labelled field** even when its value is identical to the
  supplied form, and even when one value is a prefix of the other;
- **two different sources may share a locator value**, and each entry preserves
  it independently: sharing is never conflated with duplication;
- for **every source without a locator**, both locator values are `null` and
  `locator_absence` is that source's **exact recorded** absence token;
- **no URL-like material may appear anywhere in an entry outside the labelled
  locator values** — nothing is fabricated, and nothing leaks in through prose;
- no source is added, and none removed.

Testing only `normalized_locator` would let the original supplied string be
silently dropped or rewritten, which is exactly the provenance this ledger
exists to keep. **A negative control alters the parsed field itself** — the
value the rule actually compares — rather than demonstrating that a
helper-built string changed, which would test the helper and not the rule. The
negative fixtures include a shared locator, a prefix-nested locator, a
punctuation-adjacent locator and a parenthesised locator.

## 12. Acceptance criteria for the future implementation

Every rule in sections 4 through 11 **that governs input** carries a
failing-input control reaching the production `schema` or `validate` module, and
every positive control passes — a validator that refuses everything is broken,
not correct. Standard library only. No bare `assert`. No network-capable
import. The refusal carrier has no value slot. Counts computed, never asserted.
Controls match the manifest in `tests/test_controls_manifest.py` exactly.

**Two kinds of control, and they are not interchangeable.** A
**canonical-ledger audit control** reads the committed `ledger.json` and asserts
a property of the data actually recorded; it establishes nothing whatever about
what the validator would refuse. A **hostile-input validator control** feeds a
deliberately malformed payload to the production module and requires an exact
refusal token. The frozen inventory of section 5, the artifact provenance
mapping, the bibliography renderings and the conflict coverage of section 10 are
**audited**. The shape, type, identifier, vocabulary, scalar-bound, reference,
reciprocity, locator, date and path rules are **refused**. **An audit control is
never described as a rejection control**, and no rule whose only control is an
audit is claimed to be enforced by the validator.

**Line-ending provenance is read from Git, not from the checkout.** This
repository is developed on a platform where `core.autocrlf` rewrites LF to CRLF
in the working tree, so a byte check over the checked-out file would report a
defect that does not exist in the repository and would fail on a fresh clone.
The controls inspect the **committed blob**, which is what every consumer of
this repository actually receives, and require it to be LF-only, tab-free, free
of trailing whitespace, and terminated by exactly one newline. **No
`.gitattributes` file is added by this contract.**

**Absence is detected precisely, by `lstat` and not by `exists()`.**
`Path.exists()` swallows `PermissionError` and every other `OSError` into a bare
`False`, so an unreadable entry would be reported as an unwritten
implementation. The acceptance suite inspects the expected path entry with
`lstat` and converts **only `FileNotFoundError`** into `implementation-absent`.
`PermissionError` and every other `OSError` propagate. Because `lstat` does not
follow links, a dangling symlink or junction is **present but invalid, never
absent**. That rule is about the named entry, and it is not about paths beneath
it: a path the operating system cannot resolve at all -- one whose ancestor
directory is missing, or whose ancestor is a dangling reparse point -- is
reported as `ENOENT` and therefore reads as absence. That is a decided
semantics, not an accident, and the laboratory root every check is taken
relative to is itself asserted present, so a misconfigured root fails loudly
instead of reporting a broken harness as an unwritten implementation.

The subsequent import or read runs unguarded, so an `ImportError`
raised inside a module that does exist, a syntax or decoding failure, a
malformed ledger, and a race-time `FileNotFoundError` all propagate as
themselves. An expected module is inspected by *path* but imported by *dotted
name*, and a stale `sys.modules` entry, a shadowing `sys.path` root, a
namespace portion or a compiled artifact can bind a module other than the one
inspected; the imported module is therefore required to be the entry that was
inspected, and **a divergence is a harness fault, never absence**.
**A broken implementation can never disguise itself as an unwritten
one**, and controls prove that missing, permission-denied, import-broken,
malformed and present-but-invalid all remain distinguishable.

**A path that merely overflows `MAX_PATH` is not absent.** Windows maps
`ERROR_FILENAME_EXCED_RANGE` (206) to `FileNotFoundError`, alongside genuine
absence, so an entry that exists at a path too long for the API would otherwise
be reported as an unwritten implementation — the exact inversion this section
exists to prevent. That one `winerror` propagates instead of converting.

The static scan over the absence helper is a **tripwire, not a detector**: a
name-based check cannot exclude every swallowing predicate, and what
establishes the rule is the behavioural set of controls, not the scan.

**Retired controls are recorded, never deleted.** A control withdrawn by a
correction keeps its identifier reserved with the reason it was withdrawn; the
identifier is never reused and never renumbered, so the manifest carries
deliberate gaps and an auditor reading an earlier handback can look up what a
withdrawn control used to assert. Reusing a retired identifier for a different
control is itself refused.

**What these controls do not prove:** they are static and behavioural checks
over this ledger's own surface. They do not verify a single source, do not
retrieve anything, do not establish that any recorded claim is true, and do not
establish repository configuration. **A human audit remains a separate and
required acceptance step.**

## 13. Deferred from v1

Source retrieval and every ladder state above `supplied-unretrieved`; claim
verification; **non-null supersession and every `supersedes` block above
`null`**; any use of the reserved `verified-implementation-evidence`
attribution; the Bridge Register and every cross-corpus record; bibliography
and intake-report generation; any workflow; any dependency; any hardware,
model, or capability assertion. **Historical v1 records remain unchanged when
any of these lands** — every future change is an additive correction.
