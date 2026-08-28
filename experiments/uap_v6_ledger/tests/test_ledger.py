"""Acceptance controls for the attributed UAP V6 intake ledger."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import unittest

from experiments.uap_v6_ledger import schema, validate


PACKAGE = pathlib.Path(__file__).resolve().parents[1]
REPOSITORY = PACKAGE.parents[1]
LEDGER = PACKAGE / "ledger.json"
BIBLIOGRAPHY = PACKAGE / "BIBLIOGRAPHY.md"


def load_payload() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


class LedgerAcceptanceTests(unittest.TestCase):
    def test_committed_ledger_validates(self) -> None:
        payload = load_payload()
        before = copy.deepcopy(payload)
        schema.validate_ledger(payload)
        self.assertEqual(payload, before)

    def test_inventory_counts_are_explicit_and_stable(self) -> None:
        summary = validate.validate_file(LEDGER)
        self.assertEqual(summary["batches"], 36)
        self.assertEqual(summary["sources"], 23)
        self.assertEqual(summary["claims"], 40)
        self.assertEqual(summary["relationships"], 10)
        self.assertEqual(summary["unresolved"], 10)
        self.assertEqual(summary["corpus"], "UAP V6 CORPUS")
        self.assertEqual(summary["intake_state"], "intake-open")

    def test_every_claim_is_attributed_unverified_and_limited(self) -> None:
        payload = load_payload()
        for claim in payload["claims"]:
            self.assertIn(claim["attribution_class"], schema.ATTRIBUTION_CLASSES)
            self.assertEqual(claim["verification_state"], "unverified")
            self.assertIn(claim["evidence_basis"], schema.EVIDENCE_BASES)
            self.assertGreater(len(claim["limitations"]), 0)

    def test_every_source_is_unverified_and_unretrieved(self) -> None:
        payload = load_payload()
        for source in payload["sources"]:
            self.assertEqual(source["identity_state"], "unverified")
            self.assertEqual(source["retrieval_state"], "not-attempted")

    def test_bibliography_preserves_every_source_id_and_locator(self) -> None:
        payload = load_payload()
        bibliography = BIBLIOGRAPHY.read_text(encoding="utf-8")
        for source in payload["sources"]:
            self.assertEqual(bibliography.count(source["source_id"]), 1)
            self.assertEqual(bibliography.count(source["locator"]), 1)

    def test_general_v7_corpus_is_absent_from_data(self) -> None:
        encoded = LEDGER.read_text(encoding="utf-8")
        self.assertNotIn("GENERAL V7 TECHNOLOGY CORPUS", encoded)
        payload = json.loads(encoded)
        self.assertEqual(payload["corpus"], "UAP V6 CORPUS")
        identifiers = []
        for key, field in (
            ("batches", "batch_id"),
            ("sources", "source_id"),
            ("claims", "claim_id"),
            ("relationships", "relationship_id"),
            ("unresolved", "issue_id"),
        ):
            identifiers.extend(item[field] for item in payload[key])
        self.assertTrue(all(identifier.startswith("UV6-") for identifier in identifiers))

    def test_duplicate_json_key_is_refused(self) -> None:
        with self.assertRaises(validate.LedgerInputError) as caught:
            validate._parse(b'{"schema":"source-record-v2","schema":"other"}')
        self.assertEqual(caught.exception.token, "json-duplicate-key")
        self.assertEqual(caught.exception.path, ())

    def test_verification_promotion_is_unrepresentable(self) -> None:
        payload = load_payload()
        payload["claims"][0]["verification_state"] = "verified"
        with self.assertRaises(schema.LedgerError) as caught:
            schema.validate_ledger(payload)
        self.assertEqual(caught.exception.token, "enum-invalid")

    def test_retrieval_promotion_is_unrepresentable(self) -> None:
        payload = load_payload()
        payload["sources"][0]["retrieval_state"] = "retrieved"
        with self.assertRaises(schema.LedgerError) as caught:
            schema.validate_ledger(payload)
        self.assertEqual(caught.exception.token, "enum-invalid")

    def test_wrong_corpus_is_refused(self) -> None:
        payload = load_payload()
        payload["corpus"] = "GENERAL V7 TECHNOLOGY CORPUS"
        with self.assertRaises(schema.LedgerError) as caught:
            schema.validate_ledger(payload)
        self.assertEqual(caught.exception.token, "corpus-invalid")

    def test_dangling_reference_is_refused(self) -> None:
        payload = load_payload()
        payload["claims"][0]["subject_refs"] = ["UV6-SRC-9999"]
        with self.assertRaises(schema.LedgerError) as caught:
            schema.validate_ledger(payload)
        self.assertEqual(caught.exception.token, "reference-not-found")

    def test_cli_is_identical_in_normal_optimized_and_docstring_free_modes(self) -> None:
        outputs = []
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for mode in ((), ("-O",), ("-OO",)):
            completed = subprocess.run(
                (
                    sys.executable,
                    *mode,
                    "-B",
                    "-m",
                    "experiments.uap_v6_ledger.validate",
                    str(LEDGER),
                ),
                cwd=REPOSITORY,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(completed.stderr, b"")
            self.assertTrue(completed.stdout.endswith(b"\n"))
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        self.assertEqual(len(hashlib.sha256(outputs[0]).hexdigest()), 64)

    def test_validator_imports_have_no_network_surface(self) -> None:
        forbidden = {"httpx", "requests", "socket", "urllib"}
        for path in (PACKAGE / "schema.py", PACKAGE / "validate.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertTrue(forbidden.isdisjoint(imported))

    def test_validation_does_not_change_committed_bytes(self) -> None:
        before = hashlib.sha256(LEDGER.read_bytes()).digest()
        validate.validate_file(LEDGER)
        after = hashlib.sha256(LEDGER.read_bytes()).digest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
