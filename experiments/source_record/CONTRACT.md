# `source-record-v1` — frozen contract

**Status: contract and acceptance surface only. No implementation exists in this commit.**

This document is the single authority for the `source-record` laboratory. It
supersedes every earlier specification response once accepted. Where this file
and any prior text disagree, this file governs.

## 1. Purpose

`source-record-v1` is a **synthetic-only, read-only laboratory** for recording
**sources and attributed claims** across two mechanically separated corpus
registers and one bridge register. It records **who said what, on whose
authority, in which register**.

Four failures it is built to make *structurally impossible* rather than merely
discouraged:

1. **Conflating a delivery with a source.** `message` and `source` are distinct
   record types joined only through an explicit `assertion`. Each population is
   separately countable with its own denominator, and no field anywhere can hold
   their difference.
2. **Merging the two corpora.** Register is part of identity — encoded in the
   record id, in the `register` field, and in the containing directory. A
   cross-register reference is refused. A bridge is the only connection, and it
   neither composes nor traverses.
3. **Recording a conclusion as an observation.** Every relationship vocabulary
   is observational. No token means corroborates, supports, confirms, or
   duplicates.
4. **Promoting verification by inference.** In v1 `verification_state` is closed
   to the single token `unverified`, so promotion has no representation at all.

## 2. Epistemic limit

A record that is perfectly typed, correctly attributed, honestly marked
`unverified` and **entirely fabricated passes every rule in this contract.**
The schema constrains the *form* of an assertion and never the *truth* of its
content.

Six things remain human-gated and only human-gated:

- whether a record was filed in the right register;
- paraphrase-level content laundering, which is undetectable by construction;
- whether a relationship is warranted;
- whether a proposed vocabulary addition is evaluative;
- whether fixture content is semantically neutral;
- whether any output is being presented as more than it is.

**A green suite is not coverage of those six.**

## 3. Physical manifest

### 3a. Present in this commit

    experiments/source_record/CONTRACT.md
    experiments/source_record/tests/__init__.py
    experiments/source_record/tests/_support.py
    experiments/source_record/tests/test_schema.py
    experiments/source_record/tests/test_records.py
    experiments/source_record/tests/test_validate_cli.py
    experiments/source_record/tests/test_import_quarantine.py
    experiments/source_record/tests/test_controls_manifest.py

### 3b. Absent in this commit — future implementation, not yet authorized

    experiments/source_record/__init__.py
    experiments/source_record/schema.py
    experiments/source_record/validate.py
    experiments/source_record/.gitattributes
    experiments/source_record/README.md
    experiments/source_record/records/register-a/**
    experiments/source_record/records/register-b/**
    experiments/source_record/records/bridge/**
    .github/workflows/source-record.yml

The acceptance suite in 3a is expected to be **red** until 3b exists. That is
the evidence that the independent acceptance surface preceded implementation.

### 3c. Deferred — not part of this or the initial implementation acceptance

    tests/test_source_record_reverse_quarantine.py   (root reverse import guard)

A repository-wide import scanner would read files outside this laboratory's
authorized surface. The root reverse guard is therefore **deferred until an
explicitly bounded, non-excluded scan surface is defined**. It is:

- a deferred future control;
- **not** part of this phase or the initial implementation acceptance
  requirement;
- **never** to be claimed as present while absent;
- **not** to be substituted by a broad repository scan.

The laboratory-local forward quarantine control scans only
`experiments/source_record/**` and must never scan the repository generally.

**Nothing here claims a file is absent from the repository.** A sparse checkout
materializes only part of the tree, so on-disk absence inside this worktree
proves nothing about the repository. Deferral is asserted through the contract
and the manifest, never through a filesystem absence check.

### 3d. Frozen content of future files

These are contract, not suggestion. A control asserts each exactly and fails
with `implementation-absent` while the file does not exist.

**`experiments/source_record/.gitattributes`** — exactly:

    * text eol=lf

followed by a single line feed and nothing else.

**`experiments/source_record/README.md`** — must contain the section 2
epistemic limit verbatim, character for character, including the sentence that
a perfectly formed and entirely fabricated record passes every rule, the six
human-gated items, and the closing line that a green suite is not coverage of
them.

**`.github/workflows/source-record.yml`** — frozen by **exact bytes** against
the canonical string `WORKFLOW_CONTENT` in `tests/_support.py`, including its
final line feed (I88). It is triggered on `pull_request` and on `push` to the
default branch, both `paths`-filtered to `experiments/source_record/**` and to
the workflow file itself; `permissions:` grants `contents: read`; it runs the
two authorized pytest commands; and it references only checkout and Python
setup, both SHA-pinned. Its job name reads *informational, path-scoped* —
**not** non-required, because a workflow file cannot establish required-check
status, which is external repository configuration this phase does not touch.

## 4. Physical organization

    experiments/source_record/
      __init__.py            (future)
      schema.py              (future)
      validate.py            (future)
      records/               (future)
        register-a/          direct .json files only, non-recursive
        register-b/          direct .json files only, non-recursive
        bridge/              direct .json files only, non-recursive
      tests/                 (present)

The laboratory has **no write path**: no writer API, no tombstone, no
migration, no deletion.

### 4a. Records-root shape

The direct children of `records/` are **exactly** `register-a`, `register-b`
and `bridge`. Any other entry at that level is refused with
`records-root-unexpected-entry`. A missing one of the three is refused with
`records-root-missing-directory`. All three are mandatory; a directory
containing **zero records is permitted and is not a schema failure**.

### 4b. Record-directory shape

Inside each of the three directories, direct `.json` files are the only
permitted entries. A subdirectory or a non-JSON file is refused with
`record-directory-unexpected-entry`. **Nothing is silently ignored.** The
refusal never echoes the unexpected entry's name.

### 4c. Path security and the binding seam

**Reparse points.** The records root and each of the three data directories
must be a real directory. A symbolic link, a directory junction, or any other
reparse point is refused with `path-symlink-refused`. Checking
`Path.is_symlink()` alone is **not sufficient**: a Windows directory junction
is a reparse point that both `os.path.islink` and `Path.is_symlink` report as
False, and a validator inspecting only that predicate would accept it. The
implementation must consult the platform's reparse attribute where one exists.
The control builds its fixture with a symbolic link where privilege allows and
a directory junction otherwise, entirely under the test's temporary directory,
and it never skips.

**The binding seam.** I06 requires the directory binding to be held across
enumeration and capture, and to fail closed when no binding primitive is
available. A binding-primitive failure is a platform-capability event rather
than an input, so it is made testable through **one frozen private seam**:

    validate._acquire_directory_binding(path)

It is private by name, has no public configuration, no environment variable and
no verbose mode, and exists solely so a control can inject the fault. Its
contract: when it raises `OSError`, the validator refuses with
`path-binding-failed`, exit class 4. A control monkeypatches it and asserts
that exact token behaviourally.

**The binding must be *used*, not merely called.** Calling the seam and then
enumerating and reading through the original path again would satisfy a naive
control while leaving the time-of-check/time-of-use window wide open. The
smallest protocol that makes this decidable is therefore frozen. The object
returned by `_acquire_directory_binding` exposes exactly:

    binding.entries() -> tuple[str, ...]   # direct entry names, sorted
    binding.read(name) -> bytes            # the captured bytes of one entry
    binding.close() -> None                # deterministic lifecycle end
    binding.closed  -> bool                # observable lifecycle state

Binding rules, each behaviourally asserted:

1. **Enumeration comes from the binding.** The validator obtains directory
   entries only from `entries()`, never by re-listing the path.
2. **Captured bytes come from the binding.** Record bytes are obtained only
   from `read(name)`, never by re-opening the path.
3. **The binding stays live across both.** `closed` is False for every
   `entries()` and every `read()`.
4. **The lifecycle closes deterministically.** `close()` is called exactly once
   per binding, after the last `read()`, on the success path and on every
   refusal path alike.
5. **The bound view is authoritative.** Content reachable only through the
   original path — different bytes, or an entry the binding does not list —
   cannot replace or augment what the binding exposes.

The control substitutes a recording binding whose view **deliberately differs
from the on-disk content**, and asserts the outcome follows the bound view. An
implementation that re-read the path would produce a different refusal and fail.

The protocol is private in the same sense as the seam: no environment switch,
no verbose mode, no public configuration, and no escape hatch that would let an
implementation opt out of it.

## 5. Field inventory

### 5a. Common root keys, present on all six record types, in declared order

| Field | Type | Constraint |
|---|---|---|
| `schema` | exact `str` | exactly `source-record-v1` |
| `record_id` | exact `str` | section 6 grammar |
| `record_type` | exact `str` | `RECORD_TYPES` |
| `register` | exact `str` | `REGISTERS` |
| `origin` | exact `str` | `ORIGINS`, closed to `synthetic-fixture` |
| `recorded_date` | exact `str` | real ISO `YYYY-MM-DD`, ASCII digits only |
| `recorded_by_role` | exact `str` | `ROLES` |
| `recorded_by_label` | exact `str` | free text, 1..`LABEL_MAX` |
| `supersedes` | `null` or block | section 6 `supersedes` block |

`recorded_by_role` and `recorded_by_label` are the meta-provenance for **every**
record, including `link`, `bridge` and `contradiction`: this is who recorded or
proposed the relationship. There is no second proposer pair.

### 5b. Type-specific keys, appended in declared order

**`message`** — id form `SR-(A|B)-MSG-NNNN`

    carrier_role        ROLES
    carrier_label       free text, 1..LABEL_MAX
    received_date       real ISO YYYY-MM-DD, ASCII digits only
    sequence_ordinal    exact int in [ORDINAL_MIN, ORDINAL_MAX], or null

**`source`** — id form `SR-(A|B)-SRC-NNNN`

    neutral_label       free text, 1..TEXT_MAX
    locators            exact list of locator blocks, 0..LOCATORS_MAX, no duplicates
    issuer_claim        issuer_claim block

**`assertion`** — id form `SR-(A|B)-ASR-NNNN`

    message_ref             one MSG id, same register
    subject_ref             one SRC id, same register
    attribution_class       ATTRIBUTION_CLASSES
    asserted_by_role        ROLES
    attributed_author       free text 1..LABEL_MAX, or the token "unknown"
    claim_text              free text, 1..TEXT_MAX
    instrument_context      free text 1..TEXT_MAX, or "unknown", or null
    derived_from            list of ASR ids, same register, 1..DERIVED_FROM_MAX,
                            no duplicates, or null
    verification_state      VERIFICATION_STATES
    verification_evidence   always null

**`link`** — id form `SR-(A|B)-LNK-NNNN`

    left_ref            SRC id, same register
    right_ref           SRC id, same register
    link_type           LINK_TYPES
    basis               RELATIONSHIP_BASES
    verification_state  VERIFICATION_STATES

**`bridge`** — id form `SR-X-BRG-NNNN`

    side_a              SR-A-SRC-NNNN
    side_b              SR-B-SRC-NNNN
    bridge_type         BRIDGE_TYPES
    basis               RELATIONSHIP_BASES
    verification_state  VERIFICATION_STATES

The bridge key set contains **no** locator, claim text, attribution class,
attributed author, issuer claim, or verification evidence. Those fields do not
exist on it, so a bridge cannot assert; it can only relate. `basis` is a
**closed enum, not free text**, so the relationship layer carries no free-text
laundering channel beyond a bounded party label.

**`contradiction`** — id form `SR-(A|B)-CTR-NNNN`

    left_assertion_ref   ASR id, same register
    right_assertion_ref  ASR id, same register
    conflict_basis       CONFLICT_BASES
    resolution_state     RESOLUTION_STATES, closed to "unresolved"
    verification_state   VERIFICATION_STATES

A contradiction **records** a conflict and never resolves it. There is no
resolution path and no vocabulary for one.

## 6. Nested blocks and identity

**`locator`**, element of `source.locators`, closed key set:

    scheme      LOCATOR_SCHEMES
    value       exact str matching \Asynthetic-[a-z0-9-]{1,64}\Z
    resolution  LOCATOR_RESOLUTIONS, closed to "unattempted"

**`issuer_claim`**, on `source`, closed key set:

    claimed_issuer         free text 1..LABEL_MAX, or the token "unknown"
    verification_state     VERIFICATION_STATES
    verification_evidence  always null

**`supersedes`**, on every type, `null` or a closed key set:

    record_id       exact str; same register AND same record type as the
                    superseding record
    content_digest  exact str matching \A[0-9a-f]{64}\Z

`content_digest` is an exact builtin `str` whose **format** is separately
constrained. A value of the wrong length, wrong alphabet, wrong case, or
carrying surrounding whitespace is an exact string of the wrong shape, so it is
refused with **`digest-format-invalid`** — never with a type token and never
with a free-text length token. A non-`str` value is refused earlier, with
`type-not-exact`.

The lineage field is named **`supersedes`**. No field named `predecessor`
exists. Cycle detection operates on the **supersession graph**; an
increasing-ordinal shortcut is not a substitute and is not permitted.

**Record id grammar — the only accepted form:**

    \ASR-(A|B|X)-(MSG|SRC|ASR|LNK|BRG|CTR)-[0-9]{4}\Z

The `[0-9]` class is load-bearing, not stylistic: the Python `\d` class matches
Arabic-Indic and Devanagari digits and `int()` parses them.

`A` corresponds to `register-a`; `B` to `register-b`; `X` to `bridge`, which
also requires `record_type == "bridge"` and the `BRG` type segment. All of the
id segments, the fields, and the containing directory must agree.

Each record filename is exactly `<record_id>.json`.

## 7. Closed vocabularies

    SCHEMA_ID            = "source-record-v1"
    REGISTERS            = ("register-a", "register-b", "bridge")
    RECORD_TYPES         = ("message", "source", "assertion", "link",
                            "bridge", "contradiction")
    ORIGINS              = ("synthetic-fixture",)
    VERIFICATION_STATES  = ("unverified",)
    RESOLUTION_STATES    = ("unresolved",)
    LOCATOR_SCHEMES      = ("opaque-handle", "network-locator", "filename",
                            "document-number", "container-reference", "none")
    LOCATOR_RESOLUTIONS  = ("unattempted",)
    ATTRIBUTION_CLASSES  = ("receipt-fact", "attributed-assertion",
                            "recorded-observation", "derived-inference")
    ROLES                = ("relay-agent", "operator", "auditor",
                            "analysis-seat", "external-author", "unattributed")
    LINK_TYPES           = ("claimed-container-includes", "claimed-derivative-of",
                            "commentary-about", "apparent-textual-overlap",
                            "contested-correspondence")
    BRIDGE_TYPES         = ("shared-attributed-author", "shared-locator-value",
                            "apparent-textual-overlap", "contested-correspondence")
    RELATIONSHIP_BASES   = ("recorded-by-inspection",
                            "recorded-from-supplied-material",
                            "recorded-as-proposed-elsewhere")
    CONFLICT_BASES       = ("same-quantity-different-values",
                            "same-property-mutually-exclusive-values",
                            "presence-and-absence-of-the-same-property",
                            "incompatible-attributions")
    UNKNOWN_TOKEN        = "unknown"

    LABEL_MAX = 128 ; TEXT_MAX = 4096 ; LOCATORS_MAX = 16
    DERIVED_FROM_MAX = 16 ; ORDINAL_MIN = 1 ; ORDINAL_MAX = 9999
    MAX_RECORDS_PER_DIR = 256 ; MAX_RECORD_BYTES = 65536
    MAX_TOTAL_BYTES = 4194304

Absent by decision and never to be added: any token meaning duplicate,
corroborates, supports, confirms, same-subject, or any evaluative or
authenticity-implying relationship. `commentary-about` is **within-register
only** and does not appear in `BRIDGE_TYPES`.

## 8. Invariants

**Capture and structure**

- **I01** All three data directories are captured successfully before any
  set-level invariant is evaluated; partial capture fails closed.
- **I02** Each data directory is a real directory, not a symbolic link,
  junction, or reparse point.
- **I03** Enumeration is non-recursive; the records root and each data
  directory hold exactly the permitted entries, sections 4a and 4b.
- **I04** Enumeration is in deterministic sorted filename order.
- **I05** Ceilings are enforced over **captured bytes**, not stat sizes, before
  any parsing: per-directory record count, per-record bytes, running total.
- **I06** The directory binding is held across enumeration and capture; where no
  binding primitive exists, the validator fails closed rather than presenting an
  identity re-check as a binding.

**Identity**

- **I07** `schema` is exactly `SCHEMA_ID`, exact builtin `str`.
- **I08** `record_id` matches the section 6 grammar with ASCII digits only.
- **I09** The filename equals `<record_id>.json` exactly.
- **I10** The containing directory agrees with the id register segment.
- **I11** The `register` and `record_type` fields agree with the id register
  and type segments.
- **I12** Record-id uniqueness is a **derived structural guarantee, not an
  enforced refusal.** I09 makes a filename equal its record id, so ids are
  unique within a directory; I10 makes the directory agree with the id register
  segment, so ids in different directories differ in that segment. A duplicate
  full record id is therefore unreachable, and v1 declares **no refusal token**
  for it. A control asserts the derived guarantee; none asserts a refusal,
  because none can occur.

**Type discipline**

- **I13** The root is an exact builtin `dict`; every key is an exact builtin
  `str`.
- **I14** The root key set is exactly the declared set for the record type.
- **I15** Every nested block key set is likewise exact and closed.
- **I16** Exact builtin types throughout; subclasses are refused, and the
  refusal occurs **before any hook on the rejected object can run**.
- **I17** No float anywhere, including integral-valued floats and any JSON
  literal that parses to a non-finite value.
- **I18** Every integer field is an exact builtin `int`, never `bool`, within
  its declared bounded range.

**Register separation**

- **I19** `register` is part of identity and is therefore immutable; it is
  encoded redundantly in id, field and directory, and all three must agree.
- **I20** A non-bridge record may reference only records in its own corpus
  register.
- **I21** A bridge references exactly one `register-a` source and one
  `register-b` source.
- **I22** A bridge endpoint is never a bridge and never a non-`source` record.
- **I23** Bridge relationships do not compose and do not participate in
  traversal; no traversal API exists and no public callable accepts a depth or
  recursion parameter.
- **I24** No cross-register result set, deduplication, ordering, independence
  calculation, flattened export, or global corpus total exists.
- **I25** Identity resolution requires the declared register **plus** the
  complete record id; no public resolver accepts a stripped local ordinal.

**References and graph**

- **I26** Every reference resolves to an existing record within the captured set.
- **I27** Every reference points at a record of the declared type for that field.
- **I28** No record references itself.
- **I29** The within-register `link` graph is acyclic.
- **I30** At most one bridge exists per ordered `(side_a, side_b)` pair.
- **I31** No list field contains duplicate items.

**Attribution**

- **I32** `attribution_class` is closed and never inferred, defaulted, or
  promoted.
- **I33** `derived-inference` requires a non-empty `derived_from` whose members
  are **`assertion` records in the same register**; every other attribution
  class requires `derived_from` to be `null`.
- **I34** `recorded-observation` requires a non-null `instrument_context`, which
  may be the token `unknown`; every other class requires it to be `null`.
- **I35** `asserted_by_role == "unattributed"` if and only if
  `attributed_author == "unknown"`.
- **I36** An assertion joins exactly one message and exactly one source; the
  join is never widened, and no field can hold a count.

**Null and unknown**

- **I37** `null` means *inapplicable*; the exact string `unknown` means
  *applicable but unknown*. They are never interchangeable.
- **I38** Per field the schema declares which of the two is legal; the illegal
  one is refused in either direction.
- **I39** Neither is ever coerced to a value, a default, or a falsy substitute;
  a missing key is `missing-key`, never an implicit `null`.

**Synthetic only**

- **I40** `origin` is closed to `synthetic-fixture`.
- **I41** `verification_state` is closed to `unverified` everywhere it appears.
- **I42** `verification_evidence` is always `null`; it has no non-null
  representation.
- **I43** `locator.resolution` is closed to `unattempted`.
- **I44** Every `locator.value` matches the **anchored positive** pattern
  `\Asynthetic-[a-z0-9-]{1,64}\Z`. This is an allow-list, not a deny-list: a
  deny-list catches only what its author imagined.

**Free text**

- **I45** Every free-text field is bounded by its declared maximum and is
  non-empty where required.
- **I46** Free text is valid Unicode containing no null byte and no lone
  surrogate.
- **I47** No free-text field may contain a substring matching the record-id
  grammar; structured references use reference fields.
- **I48** Free text is inert data: never evaluated, formatted against,
  interpolated into code, or used as a path, key, or format string.

**Lineage**

- **I49** `supersedes` is `null` or a complete block naming an existing
  predecessor.
- **I50** The predecessor is in the same register and of the same record type.
- **I51** `content_digest` equals the SHA-256 of the predecessor **canonical
  form**, section 10, not its raw file bytes.
- **I52** A record never supersedes itself, and supersession chains are acyclic;
  acyclicity is decided on the supersession graph.
- **I53** A predecessor has **at most one** successor; a fork is refused.
- **I54** A superseded predecessor remains present and independently valid.

**Determinism**

- **I55** Canonical form is UTF-8, sorted keys, ASCII escaping, compact
  separators, no timestamps.
- **I56** Canonical output and digests are identical across key insertion order,
  filesystem enumeration order, separate processes, and differing hash seeds.
- **I57** Every field is read exactly once into a safe internal carrier; no
  check re-reads the input mapping after validating that field.
- **I58** The validator is pure and non-mutating: it never writes, infers,
  rewrites, defaults, or upgrades a field.
- **I59** Validation traverses the **schema declared field order**, never the
  input key order.

**Refusal and non-disclosure**

- **I60** Validation is deterministic **fail-fast** in the fixed order of
  section 9; defects are not collected or enumerated.
- **I61** A refusal carries exactly two things: a `token` from the section 8a
  closed vocabulary and a schema-declared `path`. **There is no rejected-value
  slot.**
- **I62** Path components are drawn only from the schema static path set and
  integer indices into declared lists; a path is never constructed from input
  text.
- **I63** An undeclared key is reported as the **nearest declared container
  path** plus the generic token `undeclared-key`. The key name, position, value,
  type name, and count are never reported. The same non-echo rule applies to
  `records-root-unexpected-entry` and `record-directory-unexpected-entry`.
- **I64** No refusal invokes `__repr__`, `__str__`, `__format__`, `__hash__`,
  `__eq__`, `__len__`, `__iter__` or `__index__` on a rejected object, and never
  reads the runtime type name of a rejected object: a hostile metaclass makes
  reading it execute code, and the name is attacker controlled.
- **I65** A foreign non-`str` mapping key is refused without being hashed,
  compared, or stringified.
- **I66** No refusal carries a number derived from input; length violations use
  a constant token revealing neither direction nor magnitude.
- **I67** Exception chaining discloses nothing: every refusal raised inside an
  `except` block uses `raise ... from None`, so `__cause__` is `None` and
  `__suppress_context__` is `True`.
- **I68** There is **no verbose refusal mode**; no flag, configuration, or
  environment variable alters refusal content.

**CLI and resources**

- **I69** Exit classes: `0` valid; `2` usage, parse, schema or record refusal;
  `4` path or binding refusal; `5` resource ceiling. Argparse usage errors keep
  the argparse `SystemExit(2)`.
- **I70** Unrelated programming errors are not caught and propagate loudly.
- **I71** Exactly one physical stderr line per expected failure; carriage
  return, line feed and terminal control characters are rendered as visible
  escapes and never reach a terminal raw.
- **I72** The validator writes nothing on any path: no file, directory, cache,
  or temporary artifact.
- **I73** No network call is made on any path.
- **I74** The success summary reports `register-a`, `register-b` and `bridge`
  blocks **separately**, and emits no combined total. **This guarantees only
  that the laboratory does not compute or emit the aggregate. It does not and
  cannot prevent an external consumer from adding the three numbers together.**

**Quarantine**

- **I75** Laboratory production modules import only the standard library and the
  laboratory own package.
- **I76** They never import `tech_ledger`, or any production, engine, agent,
  telemetry, or network module.
- **I77** No dynamic-import mechanism: no `importlib`, no `__import__`, no
  function-body import of a non-standard-library root, in production modules.
- **I78** Static scanning **parses** modules and never executes them; discovery
  finds modules that did not exist when the guard was written, and excludes
  `__pycache__`.
- **I79** The forward guard lives in the laboratory and scans only
  `experiments/source_record/**`. The root reverse guard is **deferred**,
  section 3c, and must never be claimed as present while absent.

**Neutrality and controls**

- **I80** Neutrality is enforced by **exact approved manifests** — the path
  manifest, module names, schema fields, closed vocabularies, fixture keys and
  fixture values — never by a blacklist of prohibited names. No proscribed-name
  list is created, stored, or read. Neutrality and textual-overlap detection are
  **review signals, not truth or acceptance controls**.
- **I81** Every scan asserts it examined a **non-zero expected surface**; a scan
  rooted at the wrong path is otherwise indistinguishable from a clean one.
- **I82** The control manifest is explicit and named. Adding or removing a
  control requires an intentional manifest edit. **A numeric test count is never
  the acceptance claim.**

**Amendments added after the audits.** These extend the set; existing
numbers are deliberately left unchanged so an auditor can diff the two commits
without renumbering noise.

- **I83** `content_digest` format violations — wrong length, alphabet, case, or
  surrounding whitespace on an exact `str` — are refused with
  `digest-format-invalid`, never with a type or free-text length token.
- **I84** The resource constants are exactly `MAX_RECORDS_PER_DIR = 256`,
  `MAX_RECORD_BYTES = 65536`, `MAX_TOTAL_BYTES = 4194304`. They are frozen
  values, not suggestions, and a control asserts each exactly.
- **I85** `derived_from`, when present, holds 1..`DERIVED_FROM_MAX` items; the
  upper boundary is accepted and one item beyond it is refused with
  `list-length-invalid`.
- **I86** `README.md` reproduces the section 2 epistemic limit **verbatim**,
  character for character. It is the one place a reader meets the limit before
  the code, so it may not be paraphrased.
- **I87** `.gitattributes` content is exactly `* text eol=lf` followed by a
  single line feed. Without it the laboratory's committed line endings depend
  on the checkout platform's line-ending configuration, and every
  canonical-form and digest guarantee becomes platform-conditional. The reason
  is platform-independent and does not rest on any particular checkout's
  current setting.
- **I88** `.github/workflows/source-record.yml` is frozen by **exact bytes**,
  not by fragment presence: fragment matching cannot enforce trigger scope,
  permissions, the commands actually run, or the absence of extra network
  steps, since every fragment could sit inside a comment while a far broader
  workflow still passed. A control asserts byte-for-byte equality against one
  canonical string, including its final line feed, and addresses that exact
  path — it never scans `.github` or any wider surface.
  **Disclosed future network surface.** Executing this workflow would fetch two
  SHA-pinned actions and, additionally, run `pip install` — so **a future
  execution contacts the configured Python package index** to obtain pytest.
  That is the whole of its network surface. pytest is pinned to the exact
  version under which the reported local suite ran, determined locally and
  read-only; nothing was installed, downloaded, browsed or fetched to determine
  it. **This phase freezes workflow text only**: it does not execute the
  workflow, does not prove what a runner would do, and does not establish
  repository-required status.
  **Epistemic limit on this invariant:** a workflow file, and a job name inside
  it, **cannot establish that a check is not required**. Required-check status
  is external repository configuration. This phase neither changes nor attests
  branch protection. The workflow is described as *informational and
  path-scoped*; it is **not** proven non-required, and no control claims it is.
- **I89** No laboratory production module contains a bare `assert` statement,
  which `python -O` strips, removing every runtime invariant it carried.
- **I90** No laboratory production module contains a bare `except:`, an
  `except Exception`, or an `except BaseException`, in any form. Narrow,
  explicitly named exception classes and tuples of them remain permitted. The
  earlier "broad catch without a re-raise" formulation was not mechanically
  decidable: any `raise` anywhere inside the handler satisfied it, including a
  conditional one on a branch that may never be taken, or an unrelated
  `raise ValueError(...)`. Prohibiting the broad forms outright is decidable
  from the syntax tree, and it is the rule.
- **I92** No laboratory production module calls a write-capable filesystem
  operation. Statically forbidden: `write_text`, `write_bytes`, `mkdir`,
  `makedirs`, `touch`, `unlink`, `rmdir`, `remove`, `rename`, `replace`,
  `symlink`, `link`, `chmod`, `truncate`, the `tempfile` creation helpers and
  the `shutil` copy, move and tree-removal helpers. `open` is permitted only in
  a read mode. This is a **bounded static control over the laboratory's own
  source**; it is paired with behavioural snapshots of the records tree and of
  the laboratory tree. **It does not claim protection over arbitrary external
  paths**, and no control asserts one.
- **I93** The directory binding of section 4c is **used, not merely acquired**.
  Enumeration comes from `entries()`, captured bytes from `read(name)`, `closed`
  is False throughout both, `close()` is called exactly once after the last
  read, and content reachable only through the original path cannot replace or
  augment the bound view. Controls substitute a recording binding whose view
  differs from the on-disk content and assert the outcome follows the binding.
- **I91** The Phase 2 ordering of section 9 is observable: supersession
  acyclicity is decided before digest matching, so `supersedes-cycle` is
  reachable. A control asserts each of the two tokens exactly, on fixtures that
  differ only in whether a cycle exists.

### 8a. Closed refusal-token vocabulary

Every token the validator can emit is a member; every member is reachable.

**Path and binding, exit 4:** `path-missing`, `path-not-directory`,
`path-symlink-refused`, `path-binding-failed`,
`records-root-missing-directory`, `records-root-unexpected-entry`,
`record-directory-unexpected-entry`

**Resource, exit 5:** `record-count-ceiling`, `record-bytes-ceiling`,
`total-bytes-ceiling`

**Parse, schema and record, exit 2:** `json-malformed`, `json-duplicate-key`,
`root-not-object`, `key-not-exact-str`, `undeclared-key`, `missing-key`,
`schema-id-invalid`, `record-id-malformed`, `record-id-filename-mismatch`,
`record-id-directory-mismatch`, `record-id-register-mismatch`,
`record-id-type-mismatch`, `type-not-exact`,
`float-refused`, `int-out-of-range`, `enum-value-invalid`, `digits-not-ascii`,
`date-invalid`, `string-empty`, `string-length-invalid`,
`string-not-valid-unicode`, `string-contains-record-id`, `list-length-invalid`,
`list-duplicate-item`, `locator-value-not-synthetic`, `null-not-permitted`,
`unknown-token-not-permitted`,
`attribution-author-mismatch`, `derived-from-required`, `derived-from-forbidden`,
`instrument-context-required`, `instrument-context-forbidden`,
`reference-not-found`, `reference-wrong-register`, `reference-wrong-type`,
`reference-self`, `reference-cycle`, `bridge-side-register-invalid`,
`bridge-endpoint-not-source`, `bridge-duplicate-pair`,
`digest-format-invalid`, `supersedes-target-missing`,
`supersedes-register-mismatch`,
`supersedes-type-mismatch`, `supersedes-digest-mismatch`,
`supersedes-fork-refused`, `supersedes-self`, `supersedes-cycle`,
`verification-state-invalid`, `verification-evidence-not-null`,
`resolution-state-invalid`

**Every retained token is bound to at least one control that constructs its
condition and asserts it exactly**, through the token-to-control manifest in
`tests/test_controls_manifest.py`. A token with no such control is removed from
this vocabulary rather than carried as an untested claim.

### 8b. Tokens removed from v1, with reasons

- **`record-id-duplicate`** — unreachable. See I12: uniqueness is derived from
  the filename and directory rules, so no duplicate full id can be constructed.
- **`attribution-class-mismatch`** — redundant. Every per-class rule already has
  its own exact token (`derived-from-required`, `derived-from-forbidden`,
  `instrument-context-required`, `instrument-context-forbidden`,
  `attribution-author-mismatch`), so no input reaches a residual class token.
- **`directory-set-incomplete`** — redundant with
  `records-root-missing-directory`, which names the same condition precisely.

**`path-symlink-refused` and `path-binding-failed` are retained.** An earlier
revision removed them for want of a deterministic control, which left the
contract unsatisfiable: I02 and I06 require the behaviour, and I61 requires
every refusal to carry a retained token, so no implementation could obey all
three. Both are reinstated with exact behavioural controls, described in
sections 4c and 9.

**One accepted, deliberate disclosure, named rather than hidden.** Fail-fast
with a schema-declared path means a refusal reveals *which declared field failed
first*. That is disclosure of **schema structure**, which is public and
documented, never of input content.

## 9. Static validation order

**Phase 0 — capture.** Verify the records-root shape, section 4a
(`path-missing`, `path-not-directory`, `path-symlink-refused`,
`records-root-missing-directory`, `records-root-unexpected-entry`). Then for
`register-a`, `register-b`, `bridge` in that fixed order: existence;
is-directory; **not a symbolic link, junction, or other reparse point**
(`path-symlink-refused`, section 4c); acquire the directory binding through
`_acquire_directory_binding`, whose `OSError` becomes `path-binding-failed`;
verify the directory shape of section 4b
(`record-directory-unexpected-entry`); enumerate direct `.json` files in sorted
order; per-directory count ceiling; per-record byte capture with per-record
ceiling; running total ceiling over captured bytes.

**All three directories must complete Phase 0 before any record is parsed.**
This is observable and is asserted: a set carrying a schema-invalid record in
`register-a` *and* a Phase 0 structural defect in `bridge` must refuse with the
**`bridge` Phase 0 token**, because no parsing may begin until capture of all
three has finished. A validator that parsed `register-a` on the way past would
emit the record token instead and fail that control.

**Phase 1 — per record**, directories in fixed order, filenames sorted. For each
record, in exactly this sequence: JSON parse with duplicate-key rejection; root
is an exact `dict`; every key is an exact `str`; `schema`; `record_id`; filename
match; directory match; `record_type`; `register`; root key-set closure for that
type; then the remaining common fields in declared order, `origin`,
`recorded_date`, `recorded_by_role`, `recorded_by_label`, `supersedes`; then the
type-specific fields in the declared order of section 5b. Each nested block is
validated at the point its field is reached, its key set closed before its fields
are read in declared order.

**Phase 2 — set level**, only once every record has passed Phase 1, in exactly
this order: reference existence; reference register; reference type; self
reference; `link` graph acyclicity per register; bridge pair uniqueness;
supersedes target existence, register and type; supersedes fork check;
**supersession graph acyclicity**; supersedes digest match.

**The last two steps are ordered deliberately, and the order is load-bearing.**
A digest covers a record canonical form, which includes that record own
`supersedes` block, so a supersession cycle can never be digest-consistent:
computing either digest would require the other. If digest matching ran first it
would always fire first on any cyclic fixture, and `supersedes-cycle` would be
unreachable — a declared token that no input could ever produce, and an
implementation with no cycle detector at all would pass. Acyclicity is therefore
decided **before** digests are compared. A control asserts exactly
`supersedes-cycle` on a cyclic fixture; a separate control asserts exactly
`supersedes-digest-mismatch` on an acyclic one.

Record-id uniqueness is deliberately **not** a Phase 2 step: it is derived
(I12), not enforced.

**Phase 3 — summary emission**, section 10.

## 10. Canonicalization, digest domain, and summary

**Canonical form of a record:**
`json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))`,
encoded UTF-8, with **no trailing newline**.

**Digest:** SHA-256 of those bytes, lowercase hex, 64 characters.

**Domain:** the digest covers a record **canonical form, not its raw file
bytes**. Consequence, deliberate: reformatting a predecessor whitespace or key
order does not break a lineage chain, while any single-character content change
does.

**Summary:** the same canonicalization plus exactly one trailing line feed:

    {"registers":{"bridge":{"record_count":N,"record_ids":[]},
                  "register-a":{"record_count":N,"record_ids":[]},
                  "register-b":{"record_count":N,"record_ids":[]}},
     "schema":"source-record-v1"}

No total key exists in the structure.

## 11. Implementation API pinned for the future implementation phase

`experiments/source_record/schema.py`

    SCHEMA_ID: str
    class SourceRecordError(ValueError)      # attributes: token: str, path: tuple
    REFUSAL_TOKENS: tuple[str, ...]
    REGISTERS, RECORD_TYPES, ORIGINS, VERIFICATION_STATES, RESOLUTION_STATES,
    LOCATOR_SCHEMES, LOCATOR_RESOLUTIONS, ATTRIBUTION_CLASSES, ROLES,
    LINK_TYPES, BRIDGE_TYPES, RELATIONSHIP_BASES, CONFLICT_BASES: tuple[str, ...]
    UNKNOWN_TOKEN: str
    RECORD_ID_PATTERN: re.Pattern[str]
    ROOT_KEYS: dict[str, frozenset[str]]
    LOCATOR_KEYS, ISSUER_CLAIM_KEYS, SUPERSEDES_KEYS: frozenset[str]
    LABEL_MAX, TEXT_MAX, LOCATORS_MAX, DERIVED_FROM_MAX,
    ORDINAL_MIN, ORDINAL_MAX: int
    def validate_record(obj: object) -> None
    def canonical_bytes(obj: object) -> bytes
    def digest(obj: object) -> str

`experiments/source_record/validate.py`

    REGISTER_DIRS: tuple[str, ...] = ("register-a", "register-b", "bridge")
    MAX_RECORDS_PER_DIR, MAX_RECORD_BYTES, MAX_TOTAL_BYTES: int
    class RecordsPathError(ValueError)        # exit 4
    class RecordsCeilingError(RuntimeError)   # exit 5
    class RecordsInputError(ValueError)       # exit 2
    def validate_records_root(root) -> dict
    def serialize_summary(summary: dict) -> str
    def main(argv: list[str] | None = None) -> int

    # Frozen private seam, section 4c. Private by name, no public
    # configuration, no environment variable, no verbose mode. It exists only
    # so a control can inject a binding fault deterministically. When it
    # raises OSError, the validator refuses with `path-binding-failed`.
    def _acquire_directory_binding(path) -> object

All three error classes carry `token` and `path`, as `SourceRecordError` does.

## 12. Acceptance criteria for the future implementation

A conforming implementation satisfies **every retained invariant, I01 through
I93** — the original set together with the amendments I83 through I93 — with a
failing-input control for each and every positive control passing — a validator that refuses
everything is broken, not correct. It is standard-library only; contains no bare
`assert`; contains **no bare `except:`, no `except Exception` and no
`except BaseException`** in any statically covered form (I90); holds the
laboratory-local forward quarantine; ships the byte-frozen **path-scoped,
informational** workflow of section 3d — *not* a non-required one, because
required-check status is external repository configuration that this phase
neither sets nor attests; and emits byte-identical output across key order,
filesystem order, processes and hash seeds. Its refusal carrier has no value
slot. Its controls match the manifest in `tests/test_controls_manifest.py`
exactly. Its own README reproduces section 2 verbatim. **Its prose claims match
what the tooling enforces, not what the author intended.**

### 12a. What the controls do not prove

Stated here so no reader has to infer it:

- The static scanners cover a **frozen, enumerated syntactic surface**, listed
  in section 12b. They do **not** prove the absence of every dynamically
  constructible Python form: a handler class assembled at runtime, an attribute
  resolved through `getattr`, or a write reached through an aliased module
  object can evade any purely static rule.
- The behavioural read-only controls snapshot the records tree and the
  laboratory tree, and **claim nothing about any other path**.
- Nothing here establishes repository configuration of any kind — branch
  protection, required checks, or workflow enablement.
- Byte-freezing the workflow text proves what the file must contain. It does
  **not** execute it, and it proves nothing about what a runner would do.

**A human source audit of the implementation remains a separate and required
acceptance step.** No control in this suite substitutes for it.

### 12b. The frozen static surface

**Broad-exception scanning (I90) mechanically covers**, in a laboratory
production module: a bare `except:`; `except Exception` and
`except BaseException`; the same two reached through an attribute, such as
`except builtins.Exception`; either appearing as a member of a tuple, such as
`except (ValueError, Exception)`; and either reached through a **simple
module-level or function-level alias**, such as

    E = Exception
    try:
        operation()
    except E:
        handle()

It does **not** cover a handler class produced by a call, a subscript, a
conditional expression, `getattr`, or any other runtime construction.

**Write-capability scanning (I92) mechanically covers**, in a laboratory
production module:

- *Unambiguous method names on any receiver* — `write_text`, `write_bytes`,
  `touch`, `mkdir`, `makedirs`, `rmdir`, `removedirs`, `unlink`, `rename`,
  `symlink_to`, `hardlink_to`, `rmtree`, `copytree`, `copyfile`, `mkstemp`,
  `mkdtemp`, `ftruncate`, `pwrite`, `writev`. These have no plausible
  non-filesystem meaning.
- *Module-qualified calls only* — `os.remove`, `os.rename`, `os.replace`,
  `os.write`, `os.truncate`, `os.chmod`, `os.chown`, `os.symlink`, `os.link`,
  `os.mkfifo`, `os.mknod`; `shutil.copy`, `shutil.copy2`, `shutil.move`,
  `shutil.make_archive`, `shutil.unpack_archive`; and every `tempfile` creation
  helper.
- *`open` and `Path.open`* — permitted only with no mode argument or a mode
  that is a literal read mode. Any other literal, or a non-literal mode
  expression, is prohibited.
- *`os.open`* — permitted **only** when its flags expression is composed
  exclusively of statically read-only flag names (`O_RDONLY`, `O_DIRECTORY`,
  `O_NOFOLLOW`, `O_CLOEXEC`, `O_BINARY`, `O_NOINHERIT`, `O_NONBLOCK`, `O_PATH`)
  combined with `|`. Any write, create, truncate, append or exclusive flag, and
  any non-static flags expression, is prohibited. This is what allows a
  legitimate read-only directory binding while still catching an obvious write.

It deliberately does **not** flag a bare `.replace(...)`, `.copy(...)` or
`.link(...)` on an unknown receiver: `str.replace` and `dict.copy` are ordinary
and harmless, and a receiver-blind rule would reject correct code while adding
no real assurance. `os.replace` is caught by the module-qualified rule. This
residual gap is exactly why the human source audit above is required.

No seat that authored a component independently accepts it.

## 13. Deferred from v1

Real source ingestion; verification promotion and any non-`unverified` state;
network resolution; cross-register `commentary-about`; deduplication;
independence scoring and connected-component counting; traversal and bridge
composition; flat import or export; tombstones and re-registration control;
concurrency; writer APIs; the human-facing register mapping, which is not
created now and lives outside the repository; automatic truth, authenticity or
neutrality judgment; and the root reverse import guard, section 3c.

The symbolic-link and binding-failure path controls are **no longer deferred**:
both tokens are retained and both are asserted behaviourally. See section 4c.

**Historical v1 records remain unchanged when any of these lands.**
