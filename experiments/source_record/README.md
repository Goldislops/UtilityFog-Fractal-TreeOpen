# source-record-v1

A **synthetic-only, read-only laboratory** for recording sources and
attributed claims across two mechanically separated corpus registers and one
bridge register. It records who said what, on whose authority, in which
register — and nothing else.

The binding specification and acceptance surface is [CONTRACT.md](CONTRACT.md).
Where this file and the contract disagree, the contract governs.

## Epistemic limit

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

## Layout

    experiments/source_record/
      schema.py              closed record schema (one record in isolation)
      validate.py            directory validator CLI (capture, set rules, summary)
      records/
        register-a/          direct .json record files only
        register-b/          direct .json record files only
        bridge/              direct .json record files only
      tests/                 the frozen acceptance surface (not owned here)

The laboratory has no write path: no writer API, no tombstone, no migration,
no deletion. The validator writes nothing on any path and performs no network
access.

## Running

From the repository root:

    python -m pytest --collect-only -q experiments/source_record/tests
    python -m pytest -q -p no:cacheprovider experiments/source_record/tests
    python -m experiments.source_record.validate experiments/source_record/records

Exit classes: `0` valid; `2` usage, parse, schema or record refusal; `4` path
or binding refusal; `5` resource ceiling. A refusal prints exactly one stderr
line carrying a token from the closed refusal vocabulary and a schema-declared
path — never input content, never an input path, never a rejected value.

## Committed records

Every committed record is a synthetic exemplar: `origin` is
`synthetic-fixture`, every `verification_state` is `unverified`, every
`verification_evidence` is null, every locator `resolution` is `unattempted`,
and every locator value sits in the anchored `synthetic-` namespace. A green
validator run over these records is a check of the laboratory's mechanics.
It is not real-source validation, not operational validation, and not evidence
about anything outside this directory.

## Quarantine

Forward: the production modules import only the Python standard library and
this laboratory's own package, and the laboratory-local guard scans only
`experiments/source_record/**`. The root reverse import guard — proving that
no maintained production module imports this laboratory — is **deferred and
not present**; nothing here claims otherwise, and no broad repository scan
substitutes for it.

## Workflow

`.github/workflows/source-record.yml` is **informational and path-scoped**. A
workflow file cannot establish whether a check is required: required-check
status is external repository configuration, which this laboratory neither
sets nor attests.
