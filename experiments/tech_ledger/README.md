# Technology Ledger — Quarantined Validation Lab (`tech-ledger-v1`)

**This lab formalises record structure only.** Its single central rule:

> **Schema validity is not scientific validity, endorsement, implementation
> authority or evidence that a claim is true.**

## What this is — and is not

- This lab validates ledger **records and their evidential labels**. It does
  **not** validate scientific truth, score belief, or rank ideas.
- It does **not** supersede `docs/MEDUSA_THEORY_INTAKE_LEDGER.md`. The prose
  Theory Intake Ledger remains the authoritative intake instrument, and its
  existing graduation and promotion gate remains the only promotion path.
- Any update to that prose ledger remains a **separately authorised action**
  (its own gate; nothing in this lab touches it).
- **Inclusion is not endorsement.** **Validation is not factual
  verification.** **Classification is not implementation permission.**
- No entry may become a production truth constraint merely because it
  validates. Speculative and unsupported ideas remain labelled as such —
  that labelling is the point of the ledger, not a defect of it.
- The lab performs **no network access, no model invocation, no engine
  import, no telemetry import and no control path** of any kind. All
  outputs are deterministic and timestamp-free.

## Classification vocabulary (fixed)

Every entry has **exactly one** `primary_classification`; other applicable
labels are **qualifiers** (`classification_qualifiers`).

| Label | Meaning |
|---|---|
| **A** | demonstrated software or systems-engineering technology |
| **B** | established mathematical or scientific method |
| **C** | active research-stage technology |
| **D** | architecture analogy or inspiration only |
| **E** | speculative physical hypothesis requiring empirical validation |
| **F** | unsupported, misleading or technically mismatched claim |
| **G** | external factual claim requiring primary-source verification before repository inclusion |

## Record schema (`tech-ledger-v1`, closed)

Entries are exact JSON objects with exactly these fields (see `schema.py`
for the full typed rules): `schema`, `entry_id` (`TLV4-NNN`),
`neutral_name`, `primary_classification`, `classification_qualifiers`
(ordered, duplicate-free, never repeating the primary),
`classification_rationale`, `legitimate_uses`, `unsuitable_uses`,
`repository_placements` (from `executable-code` / `experiment` / `schema` /
`research-ledger` / `future-watch`), `implementation_disposition`
(`eligible` / `evidence-gated` / `deferred` / `prohibited`),
`minimal_evidence_before_implementation`, `implementation_seam` (non-empty
string or null), `provenance` (`source_kind`, `source_reference`,
`attributed_author`, `recorded_date` — a real `YYYY-MM-DD` date —
`verification_status`), `related_intake_ledger_entries`, `warnings`
(non-empty), `status` (`active` / `future-watch` / `v5-deferred` / `parked`).

Cross-field discipline (mechanically enforced): a primary **F** is always
`prohibited` with a null seam; `prohibited` and `deferred` dispositions
carry no seam; `eligible` and `evidence-gated` require one;
`v5-deferred` status requires a `deferred` disposition and a null seam; a
**G** classification never causes `verification_status` to be rewritten —
validation never mutates, infers or upgrades anything.

## Validator

```bash
python -m experiments.tech_ledger.validate experiments/tech_ledger/entries
```

Direct `.json` files only, deterministic filename order, duplicate-key-
rejecting parsing, symlink refusal, ceilings before parsing (256 entries,
128 KiB per entry, 4 MiB total). Exit map: **0** all valid · **2** JSON /
schema / cross-entry refusal · **4** path, symlink or inspection failure ·
**5** ceiling breach. One concise `error:` line per expected failure; no
writes; argparse usage errors keep argparse's own `SystemExit(2)`.

## Quarantine

The lab imports **only the Python standard library** — nothing from
`scripts/`, the engine, agents, CA, telemetry, Nextness or any other
production path — and no maintained production module imports the lab
(bidirectional, statically tested by
`tests/test_import_quarantine.py`). Entry JSON files are data only and can
never be imported as executable configuration. Lab tests live in
`experiments/tech_ledger/tests/` under their own path-scoped workflow and
are deliberately outside the main CI battery.

## Growth discipline

- This PR contains **five exemplar entries only**, proving the schema
  end-to-end.
- The complete thirty-entry seed pack is a **later, separately gated
  content PR** (prepared and audited outside the repository first).
- Subsequent PRs add **one coherent entry set per PR** — never a bulk
  mixed drop.

## Provenance note

Contributor attribution (including AURA or other collaborating-AI
attribution) appears only inside `provenance` data, where factually
applicable. The exemplar entries cite Kev's supplied V4 technology audit
handback as an **unverified, user-supplied audit source** — deliberately
not a primary source.
