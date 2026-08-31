# `general-v7-supplied-source-ledger-v1` --- supplied-source admission contract

This document is the frozen admission contract for a future, separately
versioned General V7 supplied-source ledger. It is authored **before** the
implementation, and it is authored so that the implementation can satisfy it
without any control here being deleted.

**This phase authorizes no implementation and no ledger records.** Nothing in
this laboratory retrieves a source. All provisional sources remain
`supplied-unretrieved`. All claims and relationships remain `unverified`. A
passing test does not establish source verification or independent acceptance.

## 1. Identity

| Property | Value |
| --- | --- |
| Ledger id | `general-v7-supplied-source-ledger-v1` |
| Schema id | `supplied-source-v1` |
| Corpus | `GENERAL V7 SUPPLIED SOURCE CORPUS` |
| Record id namespace | `G7S-` |
| Laboratory | `experiments/general_v7_supplied_source_ledger` |

The namespace prefix is `G7S-` and is deliberately **not** `GV7-`. The adjacent
laboratory `experiments/general_v7_ledger` holds
`general-v7-technology-ledger-v1` and owns the `GV7-` namespace. Reusing that
prefix would make a cross-ledger reference syntactically valid and therefore
reachable by a typo. A distinct prefix makes it a grammar violation.

## 2. Epistemic limit

1. Zero sources have been retrieved. Zero sources are verified. Zero claims
   are verified. Zero relationships are verified.
2. Cryptographic provenance establishes which bytes were received. It
   establishes nothing about where the material originated, whether any
   statement in it is accurate, or whether any locator resolves.
3. A green acceptance suite establishes conformance to the structure this
   contract describes and nothing semantic. **Human audit is a separate and
   required acceptance step, distinct from the automated tests.**
4. No text field in this ledger is executable authority.

## 3. Physical manifest

### 3a. Phase-A surface --- present in both admissible states

These eleven paths are authored in this phase and are present in both
admissible states:

- `CONTRACT.md`
- `PACKET_RECEIPT.md`
- `tests/__init__.py`
- `tests/_support.py`
- `tests/test_contract.py`
- `tests/test_controls_manifest.py`
- `tests/test_packet_manifest.py`
- `tests/test_inventory.py`
- `tests/test_schema.py`
- `tests/test_provenance.py`
- `tests/test_quarantine.py`

### 3b. Implementation surface --- all seven, or none

The future implementation surface is exactly these seven paths:

- `__init__.py`
- `schema.py`
- `validate.py`
- `ledger.json`
- `BIBLIOGRAPHY.md`
- `INTAKE_REPORT.md`
- `README.md`

The laboratory is in one of exactly two admissible states: `pre-implementation`
(none of the seven present) or `implemented` (all seven present). A partial
surface is not an admissible state. **No control asserts that the
implementation surface is absent**, because a control that can only be made
green by deleting it is an obstacle rather than evidence; the evidence that
the tests preceded the implementation lives in Git history.

`.gitattributes` is a never-authorized path in this laboratory, and so is any
`records` directory. Line-ending provenance is established from the Git blob,
not from a checkout filter.

### 3c. Dependency boundary

The future implementation must use **only the Python standard library**. It
must not import another ledger package: `experiments.general_v7_ledger`,
`experiments.source_record`, `experiments.tech_ledger` and
`experiments.uap_v6_ledger` are each refused by exact name. Prefix matching is
not used, because a prefix rule would also refuse an unrelated future module
whose name merely begins with an allowed one.

## 4. Record concepts

Seven distinct record concepts, each with its own id segment. Ids are globally
unique across every collection.

| Segment | Collection | Concept |
| --- | --- | --- |
| `BAT` | `batches` | supplied batch |
| `SRC` | `sources` | provisional source |
| `CLM` | `claims` | attributed claim |
| `REL` | `relationships` | attributed relationship |
| `UNR` | `unresolved` | unresolved issue |
| `COR` | `corrections` | additive correction |
| `NAD` | `non_admitted` | non-admitted artifact |

The frozen id grammar is:

`\AG7S-(BAT|SRC|CLM|REL|UNR|COR|NAD)-[0-9]{4}\Z`

`[0-9]` is load-bearing and is used in place of a digit shorthand, because the
shorthand matches Arabic-Indic and Devanagari digits and `int()` parses them.

### 4a. Identity stability

An identity is stable only if nothing that may later be corrected takes part
in forming it. Permitted id inputs are: the batch ordinal taken from the
member filename, and monotone allocation order within a collection. **Forbidden
id inputs** are: `origin_type`, the presence or absence of a locator,
admission status, any count, and any interpretive classification.

Consequently, **the ledger must not partition an id range by an interpretive
property.** Numbering sources so that one contiguous id block means "has a
locator" and another means "has none" welds an interpretation into identity,
and correcting that interpretation would then require renumbering --- which
this contract's additive-only rule forbids. Locator presence is a field, never
an id range.

Allocation is monotone. A retired id is never reused and never renumbered.
Gaps are legal and are not a defect.

### 4b. Declared record shapes

The implementer gets a fixed target rather than a guess. These are the field
names each record kind carries; the acceptance surface uses exactly these and
no others.

| Kind | Fields |
| --- | --- |
| root | `schema_id`, `ledger_id`, `corpus`, `counts`, and the seven collections |
| `batch` | `record_id`, `batch_ordinal`, `member_filename`, `member_sha256`, `packet_sha256`, `origin_type`, `origin_id`, `line_ending_form` |
| `source` | `record_id`, `supplied_locator`, `normalized_locator`, `normalized_identifier`, `locator_absence_reason`, `bibliography_entry`, `supplied_text`, `retrieval_state`, `verification_state`, `verification_evidence` |
| `claim` | `record_id`, `batch_ref`, `attribution_class`, `verification_state`, `byte_evidence`, `limitations` |
| `relationship` | `record_id`, `left_ref`, `right_ref`, `relationship_type`, `verification_state` |
| `unresolved` | `record_id`, `state` |
| `correction` | `record_id`, `target_ref`, `correction_kind`, `reciprocal_ref` |
| `non_admitted` | `record_id`, `carrier_batch_ref`, `carrier_member_sha256`, `presence`, `admission_status`, `executable_status`, `normative_status` |

A field name ending `_ref` holds exactly one record id and is resolved by the
reference-integrity rule. `counts` is a mapping from collection name to that
collection's length; every entry in it is computed, and a `counts` block that
disagrees with any collection length is refused.

`supplied_text` and `supplied_locator` are supplied fields and are preserved
byte-for-byte. `normalized_locator` and `normalized_identifier` are the only
normalized fields, and a locator may appear in no field other than these four.

## 5. Frozen inventory, by evidence standing

Figures are recorded with the standing of the evidence behind them. The two
classes are never mixed, and an interpretive figure is never asserted as a
structural fact.

### 5a. Structural --- independently reproduced from the packet

These were reproduced by the authoring seat directly from the packet bytes and
are frozen:

| Quantity | Value |
| --- | --- |
| Supplied batches | `63` |
| `ORIGINS.tsv` data rows | `63` |
| `origin_type` attachment rows | `60` |
| `origin_type` inline_user_message rows | `3` |
| Bibliography title entries | `26` |
| Distinct supplied video identifiers | `26` |
| Sources retrieved | `0` |
| Sources verified | `0` |
| Claims verified | `0` |
| Relationships verified | `0` |
| UAP V6 records | `0` |
| Bridge Register records | `0` |

The bibliography relation is one-to-one: each of the 26 bibliography entries
yields exactly one distinct supplied video identifier, and the 26 entries
yield 26 distinct identifiers.

### 5b. Prior interpretive expectations --- recorded, not frozen

These figures were **not** reproduced from packet structure by this phase.
They are inherited from the adjacent `general-v7-technology-ledger-v1`
laboratory, where they are frozen constants over the same supplied corpus:

| Quantity | Prior expectation |
| --- | --- |
| Provisional source identities | `61` |
| Identities without an exact locator | `35` |
| Non-admitted artifacts | `3` |

The relation `26 + 35 = 61` is an internal arithmetic reconciliation of these
three figures and is recorded as such.

**No control asserts 61, 35 or 3 as a structural fact**, and the schema does
not freeze a count for `sources` or for `non_admitted`. Freezing them would
launder an unreproduced interpretation into structure. The `non_admitted`
collection may legitimately be empty.

### 5c. Counts that are deliberately not frozen

The number of supplied **locator surface forms** is not frozen at any value.
The count is an artifact of how a tokenizer cuts the supplied text: the same
bibliography yields 104 raw URL tokens, 100 identifier occurrences, 66
per-line-distinct token strings, or 33 corpus-distinct token strings,
depending entirely on the extraction rule and on whether trailing punctuation
and backslash escapes are stripped. A figure that changes with the tokenizer
is not a structural fact about the packet, and this contract refuses to freeze
one. Surface forms are enumerated by the implementation from the supplied
bytes; their number is computed, never asserted from a constant.

No claim count is invented, and the packet itself is not committed to this
repository.

Two committed witnesses carry packet facts, and they carry different kinds:

- `PACKET_RECEIPT.md` is the sole committed witness for **archive-level**
  facts --- the archive digest and byte size, the entry census, the member
  manifest and its checksum result, the line-ending and encoding censuses.
  Every control that checks one of those checks it against the receipt.
- **This contract** carries the **content-derived** structural figures in
  section 5a --- the `ORIGINS.tsv` row census, the `origin_type` split, and
  the bibliography and identifier counts. They are recorded here under the
  authoring seat's own standing, because deriving them required reading batch
  content, and section 8.5 of the receipt deliberately keeps content-derived
  counts out of the receipt.

Neither document witnesses the other's figures, and neither claims to. A
figure's standing is whichever of the two records it, and section 5b figures
are recorded by neither: they are inherited and unreproduced.

## 6. Provenance requirements

1. **Exact packet and member-hash provenance.** Every batch record carries the
   packet archive digest and the batch member digest, both matching the frozen
   digest grammar. The member manifest does not cover itself; that asymmetry
   is recorded in the receipt and is not smoothed over.
2. **Supplied locators are preserved exactly.** A supplied value is stored
   byte-for-byte as supplied. It is never trimmed, stripped, case-folded,
   Unicode-normalized, unescaped or re-rendered. Every whitespace-canonicality
   rule in this contract applies to a normalized field only.
3. **Normalized locators are stored separately.** `supplied_locator` and
   `normalized_locator` are distinct fields and remain distinct **even when
   their values are identical**.
4. **No inferred locator completion.** Normalization never supplies a
   character that was not supplied. No scheme insertion, no host completion,
   no identifier reconstruction from a partial. Where normalization would have
   to guess, `normalized_locator` is `null`.
5. **Every locator has a carrier.** A locator record carries the batch that
   carried it. There is no field in which a locator without a carrier could be
   stored, so an uncarried locator is unrepresentable rather than merely
   disallowed.
6. **No source or locator retrieval is authorized.** No validator retrieves,
   opens, resolves, dereferences or contacts a locator. The static import
   allowlist is one layer of a layered assurance; it walks import statements
   only and does not establish behavioural impossibility, and human audit
   remains required.

## 7. Missing information

Three absence representations are distinct and are never interchangeable:

- `null` --- the field is inapplicable to this record.
- `not-supplied` --- the field applies and nothing was supplied.
- the empty string --- the field applies, something was supplied, and it was
  empty.

**Null is retained for missing metadata.** A missing value is never replaced
by an empty string, never replaced by a placeholder, and never dropped. "No
locator supplied" and "locator supplied but empty" are different values of the
same field, and no code path may coerce between them. Each field declares
which subset it admits, and an inadmissible representation is refused in
either direction.

Zero is a recorded value, not an absent one. Every emitted count equals the
length of the collection it counts; counts are computed, never asserted from a
constant.

## 8. Duplicates and cross-references

1. **No duplicate deletion.** The ledger has no deletion path, no tombstone
   and no deduplication interface. No public callable accepts a `dedupe`,
   `unique`, `distinct`, `merge` or `collapse` parameter.
2. **Duplicates are cross-referenced.** Material that repeats is recorded
   twice and joined by a relationship. Nothing is removed to make a count
   tidy.
3. The redundant surface forms in the supplied bibliography --- the same
   identifier supplied several times in several spellings on one line --- are
   modelled as several supplied surface forms normalizing to one identifier.
   They are never collapsed to a single stored locator, and a source record
   has no single supplied-locator slot in which "the" supplied form could be
   chosen without disclosing that a choice was made.
4. The schema must not assume a one-to-one relation between bibliography
   entries and identifiers. In this packet the relation happens to be
   one-to-one, but assuming it makes the first genuine collision an
   unrepresentable state.

### 8a. Closed attribution vocabulary

The attribution vocabulary is closed to exactly:

- `supplied-by-kev-verbatim`
- `supplied-by-kev-inline`
- `packet-structural-fact`
- `aura-summary`
- `aura-inference`
- `seat-observation`

"Supplied by Kev" and "summarized by AURA" are different authorship standings
and are separately countable. A claim carries exactly one attribution class.

**Absent by decision, and never to be added:** any token meaning corroborates,
confirms, proves, authenticates, endorses, is-credible, or verified-by-
agreement. Recording that material was received is not endorsement of it.

This prohibition binds **controlled-vocabulary and status fields only** ---
attribution classes, relationship types, verification and retrieval states,
and the non-admission statuses. It does **not** reach supplied text. A supplied
title that happens to contain the word "confirmed" is preserved byte-for-byte
under section 6.2, and a scan that refused it would make the preservation rule
and the vocabulary rule unsatisfiable at the same time.

### 8b. Closed relationship vocabulary

The relationship vocabulary is closed to exactly:

- `same-supplied-identifier`
- `same-supplied-title-text`
- `shares-carrier-batch`
- `conflicts-with-supplied-material`

A relationship is observational. It never promotes, verifies, rehomes or
transfers confidence between its endpoints. The type `same-supplied-identifier`
records that two records carry the same supplied identifier; it does not claim
they are the same thing in the world. Endpoints must be distinct and the
triple of left endpoint, right endpoint and type is unique.

## 9. Fixed v1 verification states

Each vocabulary is closed to a single token in v1:

| Vocabulary | v1 value |
| --- | --- |
| Retrieval state | `not-attempted` |
| Source verification state | `supplied-unretrieved` |
| Claim verification state | `unverified` |
| Relationship verification state | `unverified` |
| Unresolved state | `unresolved` |

Promotion has no representation: there is no second token to promote to, and
no separate boolean exists that could drift out of step with the ladder. A
value outside its vocabulary is refused.

A future ladder is documented so that v1 inherits a specification rather than
inventing one: `supplied-unretrieved`, `retrieval-attempted`,
`retrieved-unverified`, `identity-verified`, `content-verified`. **In v1 only
the first level is admissible.** The forward set is documentation and nothing
in v1 may rely on it.

## 10. Additive corrections

The `correction_kind` vocabulary is closed to exactly `correction`,
`contest`, `withdrawal` and `supersession`.

1. A correction is **additive**. It never edits, deletes or rewrites its
   target, and the target remains present and independently valid. Historical
   rewriting is prohibited.
2. A correction may not target another correction. That refusal is distinct
   from an unresolved-reference refusal: the target exists and is refused for
   being the wrong kind.
3. Corrections never reduce a frozen structural count.
4. A withdrawn record is retired, never deleted and never renumbered, and its
   id is reserved with a reason so that an auditor reading an earlier handback
   can find what it was.

### 10a. Reciprocal supersession

Supersession is expressed as an ordered **pair** of correction records, not as
a field on the superseded record. A field on the predecessor would require
editing the predecessor in order to record that it had been superseded, which
is exactly the historical rewrite this contract forbids.

Both directions must exist: a supersession correction targeting the
predecessor names the correction targeting the successor, and the correction
targeting the successor names the first. Each names the other, neither names
itself, and a third correction naming either is refused. **Supersession is
reciprocal in both directions**, and a one-sided supersession is refused.

A supersession may not promote a verification state.

## 11. Serialization and fail-closed parsing

1. **Deterministic canonical output.** Canonical bytes are produced with
   sorted keys, ASCII escaping, and the compact separators comma and colon
   with no spaces, encoded UTF-8 with no trailing newline. Canonical form is
   independent of input key order, and it carries no timestamp, no path and no
   environment value. The **committed** `ledger.json` is exactly those
   canonical bytes followed by a single newline, because every committed blob
   in this laboratory ends with exactly one newline. The newline is a property
   of the file, never of the canonical form, and the two are never conflated.
2. **Schema closure.** Every record type declares its complete key set. An
   undeclared key is refused, at the root and in every nested block. A key
   differing only in case is refused, never folded.
3. **Duplicate JSON keys are refused** with their own reason, never resolved
   last-wins. That refusal is distinct from a malformed-document refusal.
4. **Floats are refused everywhere**, including integral floats such as one
   point zero. The literals `NaN`, `Infinity` and `-Infinity` are refused at
   parse time and never coerced. An overflow literal such as `1e400` is
   refused and is never read as infinity.
5. **A bool is not an int.** True and False are refused wherever an integer is
   required.
6. **Integer bounds are closed intervals** and are stated numerically. Both
   edges are accepted and both edges plus one are refused.
7. **Encoding correctness.** Every file is UTF-8. Every open in text mode
   passes an explicit encoding argument. A binary-mode open passes an explicit
   binary mode and no encoding, which is how a member digest is computed over
   bytes; a text-mode open with no encoding is refused. A byte-order mark is
   refused. Committed blobs are LF-only.
8. **Path identity.** A stored path is relative and POSIX-separated. Absolute
   paths, drive-relative paths, UNC paths, device-namespace paths, backslash
   separators, parent and current directory components, Windows reserved
   component names, and components with a trailing dot or trailing space are
   each refused. A trailing dot or space is a distinct defect from a reserved
   name, and both are refused under the reserved-component rule. A parent
   component is refused after normalization, not before.
9. **Symlinks, junctions and reparse points are refused** at a target path,
   with their own reason. A dangling reparse point is present-but-invalid,
   never absent.
10. **Replacement between validation stages is detected.** The artifact that
    was inspected must be the artifact that is read. A path checked and then
    substituted before the open, or between two opens, is refused.
11. **Reference integrity.** Every cross-reference resolves to a present
    record. There is no self-reference and no reference cycle.
12. **Refusal is fail-closed.** A refusal never mutates, infers, repairs or
    upgrades its input, and never echoes the rejected value.

### 11a. The minimal validator surface

The future implementation exposes exactly this surface, so the acceptance
surface has a fixed target rather than a guess:

- `validate.RefusalError` --- the single refusal exception, carrying a
  `token` attribute drawn from the closed vocabulary below.
- `validate.validate_document(text)` --- parse and validate one JSON document
  supplied as text, returning the validated value or raising `RefusalError`.
- `validate.validate_ledger_file(path)` --- validate `ledger.json` at a path.
- `schema.REFUSAL_TOKENS` --- the closed refusal vocabulary.
- `schema.KEYS_BY_COLLECTION` --- the complete declared key set per record
  type.
- `schema.canonical_bytes(value)` --- the canonical serialization of section
  11.

The refusal vocabulary is closed to exactly:

- `absence-representation-not-permitted`
- `attribution-class-not-permitted`
- `bool-not-integer`
- `correction-target-not-permitted`
- `duplicate-key`
- `duplicate-relationship`
- `encoding-not-permitted`
- `float-not-permitted`
- `integer-out-of-bounds`
- `malformed-document`
- `missing-key`
- `non-ascii-digit`
- `non-finite-not-permitted`
- `path-identity-changed`
- `path-not-relative`
- `path-reserved-component`
- `path-separator-not-permitted`
- `path-traversal`
- `reference-cycle`
- `reference-not-found`
- `relationship-endpoints-identical`
- `reparse-point-refused`
- `self-reference`
- `supersession-not-reciprocal`
- `unknown-key`
- `verification-state-not-permitted`
- `vocabulary-token-not-permitted`
- `wrong-type`

A refusal carries **exactly one** token. It never echoes the rejected value
and the exception carries no rejected-value slot, because a refusal that
renders what it refused is a channel for the refused material.

**The validator must also accept.** A validator that refused every document
with a per-case-correct token would satisfy every refusal control and be
useless, so the acceptance surface additionally requires that a well-formed
minimal document of each record kind is **accepted** and returned unchanged.
Refusal controls and the acceptance control are both mandatory; neither
substitutes for the other.

## 12. Corpus separation

**The UAP V6 corpus is absent from this ledger.** **The Bridge Register is
absent from this ledger.** Neither contributes a record, a field, a vocabulary
token or an identifier namespace, and the schema exposes no record type into
which either could be placed. Separation is enforced by a key **allowlist**,
not by a name blocklist, because a blocklist admits every name coined
tomorrow.

There is **no transfer of truth from synthetic calibration data.** Any
synthetic record committed for calibration is evidence about validator
behaviour only. It is never evidence about a source, a claim or a
relationship, and no count derived from synthetic material may be reported as
a corpus figure.

## 13. Non-admitted proposal material

Packet material proposing future project work is **non-admitted**. It is
recorded by batch identity, presence and cryptographic provenance only.

A non-admitted record carries a carrier batch reference, that batch member
digest, and closed status fields fixed to `present-in-packet`, `not-admitted`,
`non-executable` and `non-normative`.

**The record shape contains no content channel.** There is no summary field,
no statement field, no quoted-text field, no rejection-basis field and no
locator field. A non-admitted artifact therefore cannot be paraphrased into
the ledger, because the schema has no field to paraphrase into. Removing the
channel is preferred to policing it: a prose summary is precisely how
non-admitted content re-enters as narrative.

**Packet proposal material is structurally non-executable and non-normative.**
No packet text is executed, imported, evaluated, compiled or followed as an
instruction, and no packet proposal is a requirement in this laboratory.

The field `origin_type` carries no admission, authorship or trust meaning; it
is a delivery channel. **The three inline_user_message rows are not
established to be the three non-admitted artifacts**, and no field, vocabulary
token, ordering or derived count may equate them. The counter-example is
already in hand: the bibliography batch is itself an inline_user_message. A
non-admitted record therefore carries no `origin_type` field at all.

### 13a. Liftable documents

`BIBLIOGRAPHY.md`, `INTAKE_REPORT.md` and `README.md` are **liftable**: each
may be pasted into a ticket, an appendix or a slide and read without the other
two. So each must carry its own boundary statement, before its substantive
content, rather than relying on a sibling document to disclaim on its behalf.

Each of the three states, in its own text, that provisional sources remain
`supplied-unretrieved`, that claims and relationships remain `unverified`, and
that the document is **not merge-authorized**. A 26-entry bibliography of
live-looking locators is the most liftable artifact this laboratory will ever
produce and the least self-describing unless it says so itself.

No liftable document reproduces packet prose, and none carries a fenced block.

## 14. Acceptance surface

### 14a. Control families

| Family | Module | Scope |
| --- | --- | --- |
| `D` | `tests/test_contract.py` | contract |
| `M` | `tests/test_controls_manifest.py` | manifest |
| `R` | `tests/test_packet_manifest.py` | packet receipt |
| `I` | `tests/test_inventory.py` | inventory |
| `S` | `tests/test_schema.py` | schema and serialization |
| `P` | `tests/test_provenance.py` | provenance and verification |
| `Q` | `tests/test_quarantine.py` | non-admission and non-executability |

A control id is written `G7S-` followed by the family letter and a three-digit
number, and it is carried by the test function name.

### 14b. Exact control census

The census proves, on every run, that: every declared control exists exactly
once in its declared module; no undeclared control exists; the module set is
closed in both directions; family totals reconcile against a census derived
from the source rather than from the declaration; optimized modes collect an
identical control set; and **no control is silently retired.** A retired id is
recorded with a reason, is never reused and never renumbered. **The manifest
is never padded to reproduce an earlier total.**

### 14c. The two groups

The acceptance surface is partitioned by module, and the partition is exact:

- **Contract-only group** --- `test_contract.py`, `test_controls_manifest.py`
  and `test_packet_manifest.py`. Every control in these three modules passes
  with no implementation present. No control in this group references an
  implementation path or calls a gate helper, and that independence is checked
  statically rather than assumed.
- **Implementation-dependent group** --- `test_inventory.py`,
  `test_schema.py`, `test_provenance.py` and `test_quarantine.py`. Every
  control in these four modules begins with a gate call and therefore fails,
  at the contract-only head, with the single reason `implementation-absent`.

**At the contract-only head, no other complete-suite failure reason is
acceptable.**

### 14d. How absence is reported

Missing implementation is an ordinary assertion failure. It is **never
skipped, never xfail**, and no marker or outcome-manipulating call appears
anywhere in the suite. The token `implementation-absent` is produced by a
single factory and is always raised, never returned.

Absence is detected precisely. Only the exact absence of an expected entry is
reported as absence; the suite uses a link-preserving stat rather than an
existence test, because an existence test swallows a permission failure into a
bare false. A broken import, a malformed document, a permission failure, a
path-too-long error and a race-time disappearance each propagate as
themselves. A broken implementation must never be able to disguise itself as
an unwritten one.

### 14e. Optimization-mode identity

The suite behaves identically under ordinary Python, `-O` and `-OO`.

This is not automatic, and the mechanism is stated because it is easy to lose:
`-O` deletes assert statements at compile time. Pytest assertion rewriting
replaces every assert node in a collected test module before compilation, so
assertions in a test module survive. Modules that pytest does not rewrite ---
`_support.py` and `tests/__init__.py` --- are not protected, so **no bare
assert may appear outside a test module**; helper failures are raised
explicitly. For the same reason the debug builtin appears nowhere, and no
assert appears at module level.

The `-OO` mode additionally strips docstrings, and since Python 3.13 the AST
parser inherits the interpreter optimization level. **Every AST parse in the
suite pins the optimization level to zero**, so a static scan reads the same
tree in all three modes.

Under `-O` and `-OO` pytest emits one configuration warning reporting that
assertions outside test modules are ignored. That warning is expected and is a
property of the mode rather than of this suite.

The claim that it is the **only** warning is environment-conditional and is
stated as such: the repository's root `pytest.ini` sets an asyncio mode, and a
run without `pytest-asyncio` installed adds an unknown-config-option warning in
every mode. The measured figure of one warning under `-O` and `-OO`, and none
in ordinary mode, holds for an environment with that plugin present. It is not
intrinsic to this laboratory and no control asserts a warning count.

### 14f. Provenance reads

Line-ending and whitespace provenance is read from the Git blob, never from
the checkout, because this repository enables automatic CRLF conversion and
rewrites LF to CRLF in the working tree. The blob is resolved from the index
first and from the committed head as a fallback, so the property is checkable
once the files are staged. A failure to read a blob is a harness fault with
its own distinct reason and never reports as an absent implementation.

### 14g. Audit controls and refusal controls

An **audit** control reads committed data and asserts a property of what is
recorded; it establishes nothing about what a validator would refuse. A
**refusal** control feeds a malformed payload to the implementation and
requires an exact reason. No rule whose only control is an audit may be
described as validator-enforced.

### 14h. No workflow

No repository workflow is added while the complete suite is deliberately
failing-first.

## 15. Acceptance criteria for the future implementation

The implementation is acceptable when all seven implementation paths exist,
the complete suite passes in all three optimization modes with no control
deleted or retired to achieve it, every count it emits is computed from the
collection it counts, and a human audit --- separate from these tests --- has
been recorded. Until then the complete suite fails, by design, with the single
reason `implementation-absent`.
