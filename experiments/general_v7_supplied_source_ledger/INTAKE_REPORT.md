# Intake report --- `general-v7-supplied-source-ledger-v1`

**Boundary statement.** Every provisional source recorded here remains
`supplied-unretrieved`: nothing was fetched, opened, resolved or contacted.
Every claim and every relationship remains `unverified`. This document is
**not merge-authorized**, and a passing acceptance suite establishes
conformance to the contract's structure, never that any supplied statement
is true. Human audit is a separate and required step.

## What was admitted

| Collection | Records |
| --- | --- |
| `batches` | 63 |
| `sources` | 61 |
| `claims` | 89 |
| `relationships` | 0 |
| `unresolved` | 4 |
| `corrections` | 0 |
| `non_admitted` | 3 |

Every figure is computed from the collection it counts, and the ledger's
`counts` block is refused if it disagrees with those lengths.

## Evidence standing

**Packet-derived.** 63 supplied batches, reproduced from the packet
bytes: one record per member `BATCH_001.txt` through `BATCH_063.txt`, each
carrying that member's own SHA-256 alongside the archive digest, its
`origin_type` from the supplied `ORIGINS.tsv`, and its line-ending form. The
60/3 `origin_type` split and the 26 bibliography entries of batch 63 are
likewise packet-derived.

**Kev authorization.** The admission mapping is an authorization and is never
described as derived from packet structure: batches 1 through 61 introduce
provisional sources 1 through 61 in matching ordinal order; batch 62
introduces no source; batch 63 supplies bibliography metadata; batches 10, 22
and 62 carry non-admitted artifacts 1, 2 and 3; Kev supplied the packet and
AURA authored the summaries, and packet assembly does not change authorship.

**Opus inference.** Which bibliography entry belongs to which source is
neither packet structure nor a Kev authorization. See below.

**Admission standing.** Zero sources retrieved, zero verified; zero claims and
zero relationships verified; zero UAP V6 and zero Bridge Register records
admitted. These record what this process did and where this ledger's boundary
was drawn. No reading of the packet could establish them.

**How the pairing was determined, and its standing.** Batch 63 lists its 26
entries in a *thematic* order --- the batch says in its own first line that
the links were categorized --- so entry position does **not** encode a batch
number, and displayed order was not used. Each entry was paired to the batch
whose summary describes the same item. That pairing is **Opus inference from
supplied material**. It was not supplied by Kev, not supplied by AURA, and
not taken from any source.

It was derived three times independently --- once by the primary seat and
twice by read-only reviewers working without sight of each other's answers
--- and all three agreed on all 26 pairs. For 18 of the 26 there is a further
corroboration: batch 62 carries its own concept-to-title cross-reference that
names the same titles. Batch 62 is a **non-admitted artifact**; it is used
here as corroborating evidence only, and nothing from it enters the ledger.

Agreement is not proof. The pairing remains an inference and is recorded as
one, in a `seat-observation` claim per paired source that carries this
limitation in the record itself.

One `seat-observation` claim is recorded per paired source, 26 in all.
A claim references a batch rather than a source, so the link runs through the
introducing batch, which is one-to-one here. Each records that the pairing is
Opus inference, whether the batch-62 cross-reference corroborates it
(18 of 26 are covered), and that it establishes nothing
about the source itself.

## Locators

26 sources carry a supplied locator; 35 do not. The 35
without one carry `supplied_locator: null` and the absence reason
`no-locator-supplied`. They also carry `supplied_text: null`, meaning no
bibliography-entry text applies to them --- not that their batch supplied no
text. Batch prose is not admitted into the ledger for any source.

**Normalization and selection rules, disclosed.**

1. Every supplied surface form is preserved byte-exact in `supplied_text`,
   which holds the entry verbatim as supplied, markdown escaping and all.
   Nothing is collapsed and no supplied form is discarded.
2. `supplied_locator` holds the first **direct** locator surface form, byte-
   exact as supplied. Five entries wrap their locator in a search-engine
   URL; a search wrapper is a transport rewrite rather than the locator, so
   it is never selected. A choice is made among direct forms, and this is
   that disclosure.
3. Presentation-only markdown escaping is removed **only** in
   `normalized_locator` and `normalized_identifier`. The supplied fields keep
   it. In this packet every supplied form carries a trailing escape, so
   the supplied and normalized values differ in all 26 --- an observation
   about this packet, not a guarantee. They stay distinct fields even
   where they would coincide.
4. No locator was completed, inferred or invented. The endpoint string in
   batch 15 is service configuration, not a source locator, and is not
   admitted as one; batch 15 introduces a source with no locator at all.

## Identifiers

A source identifier is the ordinal of the batch that introduced it:
`G7S-SRC-0001` through `G7S-SRC-0061` correspond to `G7S-BAT-0001` through
`G7S-BAT-0061`. No locator value takes any part in forming one.

**The locator-bearing sources do occupy a contiguous identifier block**, from
`G7S-SRC-0036` to `G7S-SRC-0061`, and that is stated plainly rather than
glossed. It arises because the bibliography batch sits at the end of the packet
and supplies locators for the sources introduced by the last twenty-six
batches; the identifier still derives from the introducing batch ordinal and
from nothing else. CONTRACT.md section 4a states that such an incidental
contiguous block is legitimate and is not a defect, and explains why forbidding
the observable pattern would force renumbering to satisfy a shape. What is
checked is the derivation, not the shape.

The derivation is checked against the batch each source *declares* as its
introducer. Nothing committed witnesses that the declaration is truthful;
detecting a falsified declaration is a human-audit obligation.

## Duplicates

No duplicate supplied identifier and no duplicate supplied title was found, so
no `same-supplied-identifier` or `same-supplied-title-text` relationship exists
to record. Nothing was removed to tidy a count; there was nothing repeated to
remove. The 26 paired sources share one carrier batch, recorded on each
of them in `locator_carrier_batch_ref` rather than materialized as pairwise
relationship records that would add no information.

## Unresolved

Four issues are recorded. The declared `unresolved` shape carries an identifier
and a state and no text field, so the substance is recorded here:

- `G7S-UNR-0001` --- 35 of 61 sources have no supplied locator.
  Nothing in the packet supplies one for them and none was inferred.
- `G7S-UNR-0002` --- no source has been retrieved and none verified.
- `G7S-UNR-0003` --- where an entry supplied several surface forms, one was
  selected for `supplied_locator` by the disclosed rule. The selection is a
  choice and is recorded as one.
- `G7S-UNR-0004` --- 8 of the 26 pairings are not
  covered by the batch-62 cross-reference and rest on batch-summary matching
  alone. They are the pairings a human audit should examine first.

## Non-admitted material

Three artifacts are recorded by carrier batch, member digest, presence and
status only. Their content is not summarized, quoted or paraphrased anywhere:
the record shape has no field to paraphrase into. Batch 62 is one of them. Its
concept-to-title cross-reference was read as corroborating evidence for the
pairing, and nothing from it entered the ledger; being cited as evidence is not
admission.

## What this is not

A green acceptance suite establishes conformance to the frozen contract's
structure. It establishes nothing about whether any supplied statement is
accurate, and it is not source verification. In particular, **no control
witnesses that a locator is attached to the right source** --- the pairing is
an inference, and the suite would stay green if it were wrong.
