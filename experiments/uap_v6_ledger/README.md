# UAP V6 attributed source ledger

This directory is the first real-source admission layer built after the
synthetic `source-record-v1` laboratory. It uses schema
`source-record-v2` and ledger identity `uap-v6-ledger-v1`.

The ledger does **not** establish that a supplied source is authentic, that a
video contains the described event, that an institutional statement is
accurate, or that any physics interpretation is correct. It records what Kev
supplied, what AURA was reported to have said, and which questions remain open.

## Current state

- Corpus: `UAP V6 CORPUS`
- Intake state: `intake-open`
- General V7 records: absent by design
- Source retrieval: not attempted
- Verification promotion: unavailable in this schema version
- Final V6 master prompt: not drafted

The admitted populations remain separately countable:

1. intake batches;
2. supplied source identities and locators;
3. attributed claims;
4. Jack-recorded duplicate, conflict, mirror, and follow-up relationships;
5. unresolved questions and required future actions.

No count is evidence of source independence or claim truth.

## Provenance rules

- Every batch is carried by Kev and names AURA as the upstream role.
- Every claim has an explicit attribution class.
- All source identities and claims are frozen at `unverified`.
- All locators remain `not-attempted`; the validator performs no network work.
- Duplicate or conflict records cross-reference predecessors instead of
  deleting or rewriting them.
- Physics mappings are stored only as `aura-inference`.
- AURA capability claims are retained alongside their contradiction.
- Normalized locators preserve a note that the visible direct URL was extracted
  from malformed supplied Markdown.

## Validation

From the repository root:

```text
python -m experiments.uap_v6_ledger.validate experiments/uap_v6_ledger/ledger.json
python -m unittest -v experiments.uap_v6_ledger.tests.test_ledger
```

Successful validation emits one deterministic JSON line containing separate
counts. Exit code 2 means JSON or ledger refusal, 4 means path refusal, and 5
means the fixed one-megabyte byte ceiling was exceeded.

## Admission boundary

This version accepts only the material already supplied in the conversation.
Adding retrieval results, primary-document bytes, verified identities,
non-`unverified` states, General V7 records, bridge records between V6 and V7,
or a final master prompt requires a later, separately reviewed change.
