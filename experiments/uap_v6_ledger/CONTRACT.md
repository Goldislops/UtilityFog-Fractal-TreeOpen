# `source-record-v2` / `uap-v6-ledger-v1` contract

## Purpose

The ledger preserves a source-intake history without converting attributed
material into established fact. It is a read-only data and validation surface;
it is not a retrieval system, a truth engine, a telemetry analyser, or a Medusa
control path.

## Fixed identities

- `schema`: `source-record-v2`
- `ledger_id`: `uap-v6-ledger-v1`
- `corpus`: `UAP V6 CORPUS`
- `intake_state`: `intake-open`

The General V7 corpus is not represented in this ledger. Cross-corpus bridge
work is deferred.

## Epistemic invariants

1. Every supplied source identity remains `unverified`.
2. Every locator remains `not-attempted`.
3. Every claim remains `unverified` and carries an attribution class, evidence
   basis, tags, and at least one limitation.
4. AURA summaries, AURA inferences, AURA capability claims, Kev observations,
   Jack inferences, supplied direct-source excerpts, and other material are
   distinct classes.
5. Relationships are Jack inferences recorded as `unverified`; they preserve
   both endpoints.
6. Duplicate batches are cross-referenced rather than deleted.
7. The ledger contains an unresolved-work register and cannot represent a
   closed issue in this version.
8. No validation path retrieves a locator or mutates the ledger.

## Structural invariants

- Root and nested keys are closed.
- Built-in container and scalar types are required exactly.
- IDs use corpus-specific `UV6-*` namespaces and are globally unique.
- Every batch, source, claim, relationship, and issue reference resolves.
- A relationship cannot target itself.
- Source locators must be supplied HTTPS strings; this is shape validation, not
  identity verification.
- Lists that function as sets reject duplicates.
- The committed ledger must remain below 1,048,576 bytes.

## Non-claims

Schema validity does not establish authenticity, source independence,
classification accuracy, calibrated kinematics, causal mechanism, or physical
feasibility. A deterministic summary is an inventory result only.

## Growth rule

Future material is admitted additively. Corrections use new records and
relationships; historical supplied labels, claims, and provenance notes are not
silently rewritten. Verification promotion, source retrieval, General V7, and
V6-to-V7 bridges require a new authorized version or extension with tests.
