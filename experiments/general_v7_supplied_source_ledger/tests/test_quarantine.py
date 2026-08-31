"""Family Q --- non-admission and non-executability.

Every control begins with a gate call and fails, at the contract-only head,
with the single reason ``implementation-absent``.

These controls constrain what the future implementation can STATICALLY REACH
and what shape a non-admitted record may take. The import scan walks ``import``
and ``from ... import`` statements only: it is one layer of a layered
assurance, it does not establish behavioural impossibility, and human audit
remains required. CONTRACT.md section 6 says so, and this module does not
claim more than the scan proves.
"""

from __future__ import annotations

import ast

from experiments.general_v7_supplied_source_ledger.tests import _support as sup

NETWORK_CAPABLE = (
    "socket",
    "ssl",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "asyncio",
    "requests",
    "subprocess",
    "webbrowser",
)


def import_roots(source: str):
    tree = ast.parse(source, optimize=0)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module or ""


def test_g7s_q_001_the_implementation_imports_only_the_stdlib_allowance():
    sup.require_production_source("__init__.py")
    for name in sup.PRODUCTION_MODULES:
        source = sup.require_production_source(name)
        for dotted in import_roots(source):
            assert dotted.split(".")[0] in sup.PRODUCTION_ALLOWED_IMPORTS, (
                name,
                dotted,
            )


def test_g7s_q_002_no_implementation_module_imports_another_ledger_package():
    sup.require_production_source("__init__.py")
    for name in sup.PRODUCTION_MODULES:
        source = sup.require_production_source(name)
        for dotted in import_roots(source):
            assert dotted not in sup.FORBIDDEN_LEDGER_PACKAGES, (name, dotted)


def test_g7s_q_003_no_implementation_module_reaches_a_network_capable_root():
    sup.require_production_source("__init__.py")
    for name in sup.PRODUCTION_MODULES:
        source = sup.require_production_source(name)
        for dotted in import_roots(source):
            assert dotted.split(".")[0] not in NETWORK_CAPABLE, (name, dotted)
    for forbidden in NETWORK_CAPABLE:
        assert forbidden not in sup.PRODUCTION_ALLOWED_IMPORTS, forbidden


def test_g7s_q_004_no_implementation_module_evaluates_anything():
    sup.require_init()
    for name in sup.PRODUCTION_MODULES:
        source = sup.require_production_source(name)
        tree = ast.parse(source, optimize=0)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            label = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            assert label not in (
                "eval",
                "exec",
                "compile",
                "__import__",
                "import_module",
            ), (name, label)


def test_g7s_q_005_no_public_callable_accepts_a_collapse_parameter():
    sup.require_production_source("__init__.py")
    for name in sup.PRODUCTION_MODULES:
        source = sup.require_production_source(name)
        tree = ast.parse(source, optimize=0)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arguments = list(node.args.args) + list(node.args.kwonlyargs)
            for argument in arguments:
                assert argument.arg not in sup.FORBIDDEN_COLLAPSE_PARAMETERS, (
                    name,
                    node.name,
                    argument.arg,
                )


def test_g7s_q_006_the_non_admitted_shape_carries_no_content_channel():
    schema = sup.require_schema()
    keys = schema.KEYS_BY_COLLECTION["non_admitted"]
    for forbidden in (
        "summary",
        "statement",
        "quoted_text",
        "rejection_basis",
        "locator",
        "supplied_locator",
        "text",
        "body",
        "description",
    ):
        assert forbidden not in keys, forbidden


def test_g7s_q_007_a_non_admitted_record_carries_no_origin_type():
    schema = sup.require_schema()
    keys = schema.KEYS_BY_COLLECTION["non_admitted"]
    assert "origin_type" not in keys
    assert "origin_id" not in keys


def test_g7s_q_008_every_non_admitted_status_is_fixed():
    ledger = sup.require_ledger()
    for record in ledger.get("non_admitted", []):
        assert record["presence"] == "present-in-packet"
        assert record["admission_status"] == "not-admitted"
        assert record["executable_status"] == "non-executable"
        assert record["normative_status"] == "non-normative"


def test_g7s_q_009_every_non_admitted_record_carries_only_provenance():
    ledger = sup.require_ledger()
    for record in ledger.get("non_admitted", []):
        carrier = record["carrier_batch_ref"]
        assert sup.ID_RE.match(carrier), carrier
        assert carrier.split("-")[1] == "BAT", carrier
        assert sup.DIGEST_RE.match(record["carrier_member_sha256"])
        assert set(record) == {
            "record_id",
            "carrier_batch_ref",
            "carrier_member_sha256",
            "presence",
            "admission_status",
            "executable_status",
            "normative_status",
        }, sorted(record)


def test_g7s_q_010_the_ledger_carries_no_executable_leaf():
    ledger = sup.require_ledger()
    stack = [ledger]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str):
            lowered = value.lower()
            for fragment in ("__import__", "eval(", "exec(", "subprocess", "os.system"):
                assert fragment not in lowered, value[:60]


def test_g7s_q_011_each_liftable_document_carries_its_own_boundary_statement():
    readme = sup.require_readme()
    bibliography = sup.require_bibliography()
    intake = sup.require_intake_report()
    texts = {
        "README.md": readme,
        "BIBLIOGRAPHY.md": bibliography,
        "INTAKE_REPORT.md": intake,
    }
    assert set(texts) == set(sup.LIFTABLE_DOCUMENTS), sorted(texts)
    for name, text in sorted(texts.items()):
        flattened = sup.flat(text)
        assert "supplied-unretrieved" in flattened, name
        assert "unverified" in flattened, name
        assert "not merge-authorized" in flattened, name


def test_g7s_q_012_no_liftable_document_reproduces_packet_prose():
    bibliography = sup.require_bibliography()
    intake = sup.require_intake_report()
    for text in (bibliography, intake):
        assert "```" not in text, "a liftable document carries a fenced block"
        for line in text.split("\n"):
            assert len(line) <= 500, "an over-long line suggests pasted packet prose"


def test_g7s_q_013_no_record_type_can_hold_a_sealed_corpus_record():
    """The witness for the two corpus standings, where the contract puts it.

    CONTRACT.md section 5b says these two zeros are not counts: the schema
    exposes no record type into which a UAP V6 or Bridge Register record could
    be placed, so there is nothing to enumerate and the zero records a
    structural impossibility. The honest witness is therefore the declared key
    sets --- an allowlist, per section 12 --- and not a search of the data.
    """
    schema = sup.require_schema()
    for collection, keys in sorted(schema.KEYS_BY_COLLECTION.items()):
        for key in sorted(keys):
            lowered = key.lower()
            assert "uap" not in lowered, (collection, key)
            assert "bridge" not in lowered, (collection, key)
    assert set(schema.KEYS_BY_COLLECTION) == set(sup.COLLECTIONS)
    standing = sup.FROZEN_ADMISSION_STANDING
    assert standing["admitted_uap_v6_records"] == 0
    assert standing["admitted_bridge_records"] == 0
