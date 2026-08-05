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
| **G** | externally checkable factual assertion carried in a record's prose — see "The G rule" below for the trigger classes (a)-(g), the exclusions and their precedence, the dossier obligation (applying equally to PRs that include and PRs that correct such assertions), the condition-bound prospective mode, and the every-G-accountable deadline |

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

## The G rule

> **G marks an externally checkable factual assertion carried in a record's prose.**
>
> An assertion is *externally checkable* when its truth-maker lies outside this repository and a primary source could confirm or refute it. G is triggered by any of:
> **(a)** a named publication, venue, or publication/peer-review status;
> **(b)** a research-status claim bounded to dates, venues, **or activity** (an emphatic existence assertion about a field's research — "real active research in their own field", "Real research literature" — satisfies the activity limb and exceeds any label's semantics; a non-emphatic activity restatement that stays within a label's defined semantics — "Active [field] research" on a C-record — does not satisfy this limb and is judged under exclusion 1);
> **(c)** a measured figure imported from an external source;
> **(d)** a named external empirical result — a specific experiment, demonstration, measurement, or standard;
> **(e)** a capability claim about an external technology or physical effect — affirmative or negative — that the record's reasoning relies on as a checkable fact;
> **(f)** the licence, availability, release, or maintenance status of a named external artifact;
> **(g)** the **specific substantive content of an external theorem, analytic solution, or mathematical result** — stating what the mathematics says ("the pseudotensor is coordinate-dependent, so only integrated or asymptotic quantities are meaningful") is externally checkable and is **never exempt merely because its truth-maker is proof**. A generic statement that an approximation method has a bounded validity regime states the character of approximation methods as a class and is method identity, not (g)-content.
>
> **G is never triggered by:**
> 1. the classification labels themselves, or prose restating a label's defined semantics with **no added empirical assertion** — including a negative restatement (an unbounded "no settled technique" on a C-record restates research-stage meaning) and its affirmative mirror (a bare "Active [field] research" on a C-record restates C's own active-research-stage semantics); an emphatic existence claim — one insisting on reality in words the label does not supply ("real", "Real") — exceeds the label and is judged under trigger (b);
> 2. schema fields, enums and record-state metadata;
> 3. repository-internal facts, whose truth-maker is this repository's own tree (by recorded convention this includes statements *about the record's own source document*, e.g. "the user-supplied audit supplies no…", whose truth-maker is the recorded intake, not the world);
> 4. pure hypotheticals and conditionals;
> 5. genuinely synthetic, repository-local procedures and test fixtures;
> 6. a **bare method name or operator choice** ("WKB approximation", "standard mathematical analysis tooling"), a **categorical existence-reference** to a method's standard results, and **descriptions of a field's own standard methodological practice** — where *naming* means specific identification by author, venue, year, title, or figure, and a categorical reference asserts only that a method's standard mathematics exists.
>
> **Requirements are not a shelter, with stated precedence:** a normative requirement or prohibition is exempt only when it neither asserts nor presupposes an external fact **beyond exclusion 6's method identity**. Precedence rule: a categorical existence-reference remains exempt wherever it appears, including inside a requirement ("Match to a textbook asymptotic result" presupposes only that the method's standard mathematics exists); a requirement that **names** a specific publication, result, or capability, or states (g)-content, is never sheltered (a gate naming "Moreva et al., PRA 89, 052122 (2014)" carries G for exactly that reason).
>
> **Obligation:** a record carrying G for its own assertions must have those assertions routed through a bounded primary-source evidence dossier — with recorded access levels and a pinned receipt — before the content PR that **includes or corrects** them merges. A record already merged whose prose is found to trigger G is corrected under this same obligation; history is never grounds for exemption.
> **Prospective G:** valid only on a record with a `deferred` disposition (null seam) and a `v5-deferred`, `future-watch` or `parked` status; it binds each future ingested claim, not the record's own prose, and requires no dossier until such a claim lands.
> **Every G must be one or the other, on a deadline:** a G that corresponds neither to a current trigger with dossier treatment nor to valid prospective mode is a defect and must be regularized **at the record's next content PR — for an unmerged record, the PR that includes it**. Regularization means binding the G to a real trigger with dossier treatment, converting the record to valid prospective mode, or revising the G *together with any prose clause that references it* with a recorded reason — a bare qualifier deletion that strands referencing prose is not a valid regularization.
> **G never changes `verification_status`** — verification is a separate recorded act, and inclusion is not endorsement.

## Validator

```bash
python -m experiments.tech_ledger.validate experiments/tech_ledger/entries
```

Direct `.json` files only, deterministic filename order, duplicate-key-
rejecting parsing. The **entries directory itself is verified and bound**:
a symbolic-link, junction or equivalent reparse-path directory is refused;
where directory-relative descriptors are supported, candidates are
enumerated and opened relative to the verified directory descriptor, and
elsewhere a directory handle that denies delete/rename sharing is **held
for the whole interval** from before enumeration until after the last
capture — so the inspected directory cannot be renamed or replaced
meanwhile, including during a transient swap-and-restore that no
before/after identity check could observe. Where neither binding
primitive exists the validator **fails closed before enumeration** rather
than presenting identity rechecks as a binding. Every candidate is then captured through
a **verified descriptor boundary** (symlinks refused before and during
capture; `O_NOFOLLOW` where the platform supplies it; `st_dev`/`st_ino`
identity agreement across pre-open, opened-descriptor and post-open
inspections — any mismatch, replacement or incomplete identity inspection
fails closed on exit 4; no protection is claimed against an unobservable
filesystem or kernel violation). Ceilings (256 entries, 128 KiB per entry, 4 MiB total)
are enforced over the **exact captured bytes** — cheap stat checks run
first, but the authoritative aggregate is the captured total, reading
stops as soon as that total necessarily breaches, and nothing is parsed
until every candidate is captured and every actual-byte ceiling has
passed; the summary's `total_entry_bytes` is the captured sum, never a
stale stat size. Exit map: **0** all valid · **2** JSON / schema /
cross-entry refusal · **4** path, symlink, replacement or inspection
failure · **5** ceiling breach. Exactly **one physical `error:` stderr
line** per expected failure (CR/LF in messages rendered as visible
escapes); no writes; argparse usage errors keep argparse's own
`SystemExit(2)`.

## Quarantine

Enforcement is two-part, matching how each direction can actually drift:

- **Forward quarantine** (the lab imports only the Python standard
  library — nothing from `scripts/`, the engine, agents, CA, telemetry,
  Nextness or any other production path): lab-local static test
  (`tests/test_import_quarantine.py` here) under the path-scoped
  tech-ledger workflow, which triggers whenever the lab changes. The scan
  **discovers every non-test lab module automatically** (a future
  `helpers.py` is examined the moment it exists — proven by synthetic
  controls); the tests tree is scanned through its own separate allowlist.
- **Reverse quarantine** (no maintained production module imports the
  lab): the **maintained main-suite guard**
  `tests/test_tech_ledger_reverse_quarantine.py`, which runs on ordinary
  repository CI and statically scans every maintained Python location —
  so a production-only change can never bypass it merely because the lab
  workflow did not trigger. The guard resolves **both absolute and
  relative imports** against each file's repository package context
  (namespace-package aware), so `from .. import tech_ledger` inside the
  `experiments` tree is caught exactly like
  `import experiments.tech_ledger`. (A fast lab-local snapshot of the
  same direction also runs here.)

Entry JSON files are data only and can never be imported as executable
configuration. Lab tests live in `experiments/tech_ledger/tests/` under
their own path-scoped workflow and are deliberately outside the main CI
battery; the reverse guard is the one deliberate exception, living in the
main battery by design.

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
