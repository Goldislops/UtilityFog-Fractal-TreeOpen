"""``general-v7-supplied-source-ledger-v1`` --- supplied-source admission ledger.

Contract: ``CONTRACT.md``. Packet provenance: ``PACKET_RECEIPT.md``.

Standard library only. This package imports no other ledger package, retrieves
nothing, and resolves no locator. Every provisional source it records remains
`supplied-unretrieved` and every claim and relationship remains `unverified`;
a green acceptance suite establishes conformance to the contract's structure
and nothing about whether any supplied statement is true.
"""

from __future__ import annotations

SCHEMA_ID = "supplied-source-v1"
LEDGER_ID = "general-v7-supplied-source-ledger-v1"
CORPUS = "GENERAL V7 SUPPLIED SOURCE CORPUS"

__all__ = ["SCHEMA_ID", "LEDGER_ID", "CORPUS"]
