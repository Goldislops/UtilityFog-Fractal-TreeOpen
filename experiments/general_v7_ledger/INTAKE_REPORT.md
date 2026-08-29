# Intake report — synthetic implementation candidate

**This report describes a wholly synthetic ledger.** It was fabricated as an
engineering calibration exercise against the frozen
`general-v7-technology-ledger-v1` admission contract. No real source corpus,
attachment, video, transcript or external material was consulted, copied,
paraphrased or inferred from. Nothing below is evidence about any real
person, product, organization, research or event.

## Identity

    schema        source-record-v3
    ledger_id     general-v7-technology-ledger-v1
    corpus        GENERAL V7 TECHNOLOGY CORPUS
    intake_state  intake-complete

## What the synthetic ledger contains

The candidate exercises the exact frozen structure of the contract:

- **63 intake batches** (`GV7-BAT-0001` through `GV7-BAT-0063`). Batches
  10, 22 and 62 are artifact-bearing and introduce no source; batch 62
  introduces `GV7-ART-0003` only; batch 63 is a bibliography-metadata batch
  that updates `GV7-SRC-0036` through `GV7-SRC-0061`, creates no further
  source and introduces no artifact. The remaining 59 batches introduce the
  61 synthetic source identities, and introduction is reciprocal in both
  directions.
- **61 provisional external-source identities.** `GV7-SRC-0001` through
  `GV7-SRC-0035` carry no exact supplied locator and record an explicit
  absence reason; `GV7-SRC-0036` through `GV7-SRC-0061` carry supplied
  locator, title and channel metadata. Every locator uses the reserved
  `example.invalid` name. Supplied forms are preserved verbatim — including
  one deliberately whitespace-padded supplied locator, one parenthesised
  form, one bare-host form and one shared and one prefix-nested locator
  value — and only the `normalized_*` fields are canonical.
- **61 attributed, limited claims**, one per source, every one of them
  `unverified`. One claim records fabricated past-tense implementation
  language verbatim, one records fabricated historical authorization
  language (which grants nothing), and one records a fabricated quarantined
  proposal as a categorical summary with quarantine dispositions and no
  operational detail.
- **6 within-corpus relationships**, each `unverified`, with mandatory
  limitations; duplicate and conflicting synthetic material is
  cross-referenced, never deleted.
- **13 unresolved records**, exactly one per conflict family of the
  contract, each recording two competing synthetic positions and resolving
  none of them.
- **3 preserved, rejected synthesis artifacts** with the frozen provenance
  mapping: `GV7-ART-0001` from `GV7-BAT-0010`, `GV7-ART-0002` from
  `GV7-BAT-0022`, `GV7-ART-0003` from `GV7-BAT-0062`. All are
  `non-executable` and `preserved`.
- **0 corrections.** The additive history channel starts empty.

## Verification states

Zero sources retrieved. Zero source identities verified. Zero claims
verified. Every retrieval state is `not-attempted`, every source
verification state is `supplied-unretrieved`, every claim and relationship
is `unverified`, and no V6 material, bridge record or cross-corpus reference
exists or is representable.

## Epistemic limit

This ledger records what a fabricated carrier would have supplied, by whom,
with what limitations. It establishes nothing about the world. A green
acceptance suite proves conformance to the frozen contract; it proves
nothing about the truth of any recorded claim, and a human audit remains a
separate and required acceptance step.
