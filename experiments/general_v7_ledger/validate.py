"""Command-line validation surface for ``general-v7-technology-ledger-v1``.

This module is the second frozen public surface. Like ``schema``, it binds
its exports from the already-imported package module via ``sys.modules``:
GV7-S-028's import allowlist admits no sibling import, and the parent
package is the one module the import system guarantees to have executed
first -- both under an ordinary dotted import and under
``python -m experiments.general_v7_ledger.validate``. Nothing here imports,
retrieves or executes anything.

The frozen interface is exactly one explicitly supplied file path. Exit
codes: 0 on success, 1 on any refusal, 2 on a usage error. Success writes
one line of canonical JSON and a single line feed through
``sys.stdout.buffer``; a refusal writes nothing to standard output and
exactly one token line to standard error.
"""

import sys

_core = sys.modules["experiments.general_v7_ledger"]

LedgerError = _core.LedgerError
LedgerPathError = _core.LedgerPathError
LedgerCeilingError = _core.LedgerCeilingError
LedgerInputError = _core.LedgerInputError

MAX_LEDGER_BYTES = _core.MAX_LEDGER_BYTES
REFUSAL_TOKENS = _core.REFUSAL_TOKENS

validate_ledger_file = _core.validate_ledger_file
main = _core.main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
