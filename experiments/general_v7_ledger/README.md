# general_v7_ledger — synthetic implementation candidate

A complete, standard-library-only implementation candidate for the accepted
`general-v7-technology-ledger-v1` admission contract (`CONTRACT.md`), built
against the frozen 179-control acceptance surface in `tests/`.

**Everything in this candidate is synthetic.** The ledger, bibliography and
intake report were fabricated for engineering calibration; no real corpus
material was consulted, and no record here is evidence about any real
source, person, product or organization. Every locator uses the reserved
`example.invalid` name. This branch is a disposable engineering candidate
and is not merge-authorized.

## Surfaces

- `schema.py` — the frozen identity, vocabularies, bounds, closed shapes,
  the single refusal base `LedgerError`, the closed `REFUSAL_TOKENS`
  vocabulary, and the pure in-memory `validate_ledger(payload)`.
- `validate.py` — the file pipeline `validate_ledger_file(path)` (exactly
  one explicitly supplied path; staged refusal: path, byte ceiling, strict
  UTF-8 decode, JSON parse with duplicate-key refusal, then content), the
  stage classes `LedgerPathError` / `LedgerCeilingError` /
  `LedgerInputError`, and the frozen command line `main(argv)` — exit 0 on
  success, 1 on any refusal, 2 on a usage error. Success emits one line of
  canonical JSON through `sys.stdout.buffer`; a refusal emits exactly one
  token line on standard error and nothing on standard output. Every count
  in the output is computed from the validated collection, never asserted
  from a constant.
- `ledger.json` — the synthetic ledger document.
- `BIBLIOGRAPHY.md` — the structural bibliography: one heading per source
  identity, three labelled canonical-JSON locator fields per entry, both
  locator forms preserved exactly.
- `INTAKE_REPORT.md` — the synthetic intake summary.

## Architecture note

The shared implementation core lives in the package module `__init__.py`,
and `schema.py` / `validate.py` bind their public names from it via
`sys.modules`. This is forced by the acceptance surface itself: GV7-S-028
closes every production module over a standard-library import allowlist
with no sibling carve-out and refuses relative imports, the call-name
tripwire bans every dynamic-import mechanism, GV7-S-066 requires the
`validate` stage classes to subclass the one `schema.LedgerError`, and
GV7-S-026 runs `python -m experiments.general_v7_ledger.validate` in a
fresh process. The parent package is the only module the import system
guarantees to have executed before either surface in every required mode,
so it is the only lawful home for the shared objects.

## Running

From the repository root:

    python -m experiments.general_v7_ledger.validate \
        experiments/general_v7_ledger/ledger.json

    python -m pytest experiments/general_v7_ledger/tests -q

## Limitations

A green suite proves conformance to the frozen contract and nothing else.
No source was retrieved, no identity or claim was verified, and no
statement in the synthetic data is true of the world. A human audit remains
a separate and required acceptance step.
