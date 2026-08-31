# `general-v7-supplied-source-ledger-v1`

A supplied-source admission ledger for the General V7 material packet.

**Boundary statement.** Every provisional source recorded here remains
`supplied-unretrieved`: nothing was fetched, opened, resolved or contacted.
Every claim and every relationship remains `unverified`. This document is
**not merge-authorized**, and a passing acceptance suite establishes
conformance to the contract's structure, never that any supplied statement is
true. Human audit is a separate and required step.

## What this laboratory is

Seven implementation files sit beside a frozen contract and a packet receipt:

| File | What it holds |
| --- | --- |
| `CONTRACT.md` | the frozen admission contract; the authority for everything else |
| `PACKET_RECEIPT.md` | archive-level provenance for the supplied packet |
| `__init__.py` | package identity |
| `schema.py` | closed shapes, closed vocabularies, canonical form, identifier derivation |
| `validate.py` | fail-closed parsing and refusal |
| `ledger.json` | the admitted records |
| `BIBLIOGRAPHY.md` | the 26 supplied bibliography entries |
| `INTAKE_REPORT.md` | what was admitted, and on whose authority |
| `tests/` | the acceptance surface |

Where this README and `CONTRACT.md` disagree, the contract is right and this
file is a defect.

## The human-audit boundary

Automated acceptance is **not** source verification, and three specific gaps
are stated rather than papered over.

1. **Nothing here verifies a source.** No locator was retrieved. A locator is
   recorded because it was supplied; that says nothing about whether it
   resolves, and nothing about whether the material behind it says what a
   summary says it says.
2. **The identifier derivation rests on a declared field.** A source
   identifier is derived from the batch the record *declares* introduced it.
   Nothing committed witnesses that the declaration is truthful, so an
   implementation that assigned identifiers some other way and then wrote the
   declaration to match would satisfy every automated control. Detecting that
   is a human-audit obligation.
3. **The import allowlist constrains static reach, not behaviour.** It walks
   import statements only. It does not establish that no code path could
   retrieve anything.

A green suite means the records conform to the contract's structure. It does
not mean the corpus is true, and no control in this laboratory may be
described as closing any of the three gaps above.

## Standing of the material

The packet was **supplied by Kev**; its batch material was **summarized by
AURA**. Those are different authorship standings and the ledger keeps them
apart: a claim attributed to AURA carries no byte evidence and must carry its
limitations.

The admission mapping — which batches introduce which sources, which batch
supplies the bibliography, and which batches carry non-admitted artifacts — is
recorded under **Kev's explicit authorization**. It is not a fact derived from
packet structure and is never described as one. `INTAKE_REPORT.md` sets out
the mapping and its standing in full.

## Corpus separation

No UAP V6 record and no Bridge Register record is admitted, and the schema
exposes no record type into which either could be placed. The exclusion
vocabulary necessarily appears in the contract and in the tests as guardrails,
because a boundary has to be stated to be enforced; those appearances are
guardrails, not admitted records.

## Non-admitted material

Packet material proposing future project work is recorded by batch identity,
member digest, presence and status only. The record shape carries no summary,
statement, quoted text or rejection basis, so such material cannot be
paraphrased into the ledger — there is no field to paraphrase into. Recording
that something was present is not endorsement of it.

## Running the acceptance surface

From the repository root:

    python -B -m pytest -p no:cacheprovider experiments/general_v7_supplied_source_ledger/tests

The suite is also run under `-O` and `-OO`, and must behave identically in all
three. Under the optimized modes pytest emits one configuration warning about
assertions outside test modules; that warning is a property of the mode, not
of this laboratory.
