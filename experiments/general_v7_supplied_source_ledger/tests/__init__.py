"""Acceptance suite for ``general-v7-supplied-source-ledger-v1``.

Contract, packet receipt and acceptance surface only. No implementation module
is imported at import time, so collection succeeds against an empty
laboratory.

This package deliberately contains no ``assert``. Pytest rewrites assertions
only in the modules it collects as tests; this module is not one of them, so a
bare assert here would be deleted outright under ``python -O`` and would
silently guarantee nothing.
"""
