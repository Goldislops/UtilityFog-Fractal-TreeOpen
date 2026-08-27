"""Laboratory-local forward import quarantine.

Scope is deliberately narrow: this control scans **only**
``experiments/source_record/**``. It never scans the repository generally, and
it never reads a file outside this laboratory.

The complementary *reverse* guard — proving no maintained production module
imports this laboratory — is **deferred**. It would require a repository-wide
scan surface that has not been defined. See CONTRACT.md section 3c. It is not
claimed here, and this file must never be widened to stand in for it.

Every scan is purely static: modules are parsed with ``ast`` and never
executed.

Control ids SR-Q-NNN are declared in ``test_controls_manifest.py``.
"""

from __future__ import annotations

import ast
import pathlib

from experiments.source_record.tests import _support as sup

#: Standard-library roots a laboratory production module may import, plus the
#: laboratory's own package. Nothing else.
PRODUCTION_ALLOWED = frozenset(
    {
        "__future__",
        "argparse",
        "datetime",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "stat",
        "sys",
        "typing",
        "unicodedata",
        "msvcrt",
        "_winapi",
    }
)

#: Additional roots the acceptance suite itself may import.
TESTS_EXTRA_ALLOWED = frozenset(
    {
        "ast",
        "copy",
        "importlib",
        "inspect",
        "pytest",
        "socket",
        "subprocess",
    }
)

LAB_PACKAGE_PREFIX = "experiments.source_record"

#: Import-name fragments a production module may never carry, whatever the
#: allow-list says. The allow-list is the control; this is a second fence.
PRODUCTION_FORBIDDEN_FRAGMENTS = (
    "tech_ledger",
    "swarm",
    "scripts.",
    "agent_backends",
    "telemetry",
    "nextness",
    "medusa",
    "orchestrat",
    "subprocess",
    "socket",
    "http",
    "urllib",
    "requests",
    "importlib",
    "numpy",
    "pytest",
)

DYNAMIC_IMPORT_NAMES = ("__import__", "import_module")


def import_roots(path: pathlib.Path) -> set[str]:
    """Static import roots of one module. Nothing is imported or executed."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module or "")
    return roots


def function_level_imports(path: pathlib.Path) -> list[str]:
    """Import statements that sit inside a function body."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Import):
                found.extend(alias.name for alias in inner.names)
            elif isinstance(inner, ast.ImportFrom):
                found.append(inner.module or "")
    return found


def dynamic_import_calls(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = None
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            name = target.attr
        if name in DYNAMIC_IMPORT_NAMES:
            found.append(name)
    return found


def violations(path: pathlib.Path, allowed: frozenset[str]) -> list[str]:
    found: list[str] = []
    for root in sorted(import_roots(path)):
        if root.startswith(LAB_PACKAGE_PREFIX):
            continue
        if root not in allowed:
            found.append(root)
    return found


# --------------------------------------------------------------------------
# Production modules
# --------------------------------------------------------------------------


def test_sr_q_001_every_laboratory_production_module_imports_stdlib_only():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        found = violations(path, PRODUCTION_ALLOWED)
        assert not found, f"{path.name}: {found}"


def test_sr_q_002_no_production_module_carries_a_forbidden_import_fragment():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        for root in sorted(import_roots(path)):
            for fragment in PRODUCTION_FORBIDDEN_FRAGMENTS:
                assert fragment not in root, (path.name, root, fragment)


def test_sr_q_003_no_production_module_uses_a_dynamic_import_mechanism():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        assert not dynamic_import_calls(path), path.name
        deferred = [
            name
            for name in function_level_imports(path)
            if not name.startswith(LAB_PACKAGE_PREFIX)
        ]
        assert not deferred, (path.name, deferred)


# --------------------------------------------------------------------------
# Tests tree
# --------------------------------------------------------------------------


def test_sr_q_004_every_suite_module_imports_only_its_declared_allowance():
    modules = sup.lab_test_modules()
    assert modules, "the tests-tree scan examined nothing"
    allowed = PRODUCTION_ALLOWED | TESTS_EXTRA_ALLOWED
    for path in modules:
        found = violations(path, allowed)
        assert not found, f"{path.name}: {found}"


def test_sr_q_005_the_scans_are_static_and_never_execute_a_module():
    """The scan helpers parse; they contain no exec, eval, or import call."""
    this_module = pathlib.Path(__file__).resolve()
    tree = ast.parse(this_module.read_text(encoding="utf-8"))
    banned = {"exec", "eval", "compile", "runpy"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned, node.func.id
    assert "importlib" not in import_roots(this_module)


# --------------------------------------------------------------------------
# Discovery controls
# --------------------------------------------------------------------------


def test_sr_q_006_discovery_examines_a_module_that_did_not_exist_before(tmp_path):
    """Synthetic control: a newly introduced module is scanned automatically."""
    fake_lab = tmp_path / "fake_lab"
    (fake_lab / "tests").mkdir(parents=True)
    (fake_lab / "helpers.py").write_text("import json\n", encoding="utf-8")
    (fake_lab / "leaky.py").write_text("import urllib.request\n", encoding="utf-8")
    (fake_lab / "tests" / "test_x.py").write_text(
        "import pytest\n", encoding="utf-8"
    )
    (fake_lab / "__pycache__").mkdir()
    (fake_lab / "__pycache__" / "junk.py").write_text(
        "import socket\n", encoding="utf-8"
    )

    discovered = sorted(
        path
        for path in fake_lab.rglob("*.py")
        if "__pycache__" not in path.parts
        and (fake_lab / "tests") not in path.parents
    )
    names = [path.name for path in discovered]
    assert names == ["helpers.py", "leaky.py"]
    assert violations(fake_lab / "helpers.py", PRODUCTION_ALLOWED) == []
    assert violations(fake_lab / "leaky.py", PRODUCTION_ALLOWED) == [
        "urllib.request"
    ]


def test_sr_q_007_discovery_is_deterministic_and_excludes_bytecode_caches():
    production = sup.lab_production_modules()
    tests = sup.lab_test_modules()
    assert production == sup.lab_production_modules()
    assert tests == sup.lab_test_modules()
    for path in production + tests:
        assert "__pycache__" not in path.parts


def test_sr_q_009_no_production_module_contains_a_bare_assert_statement():
    """``python -O`` strips ``assert``, taking every invariant it carried."""
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Assert)
        ]
        assert not offenders, (path.name, offenders)


BROAD_EXCEPTION_NAMES = ("Exception", "BaseException")


def _broad_aliases(tree: ast.AST) -> set[str]:
    """Simple names bound to a broad exception class, transitively.

    Covers ``E = Exception``, ``E = builtins.Exception`` and ``F = E``. It does
    not cover a class produced by a call, subscript, conditional, ``getattr`` or
    any other runtime construction — CONTRACT.md section 12b says so plainly.
    """
    aliases: set[str] = set()
    for _ in range(4):  # fixed point over simple chains; bounded, terminating
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id in aliases:
                continue
            value = node.value
            broad = (
                (isinstance(value, ast.Name)
                 and (value.id in BROAD_EXCEPTION_NAMES or value.id in aliases))
                or (isinstance(value, ast.Attribute)
                    and value.attr in BROAD_EXCEPTION_NAMES)
            )
            if broad:
                aliases.add(target.id)
                grew = True
        if not grew:
            break
    return aliases


def broad_exception_handlers(source: str) -> list[tuple[int, str]]:
    """Prohibited handlers: bare ``except:``, ``Exception``, ``BaseException``.

    Mechanically decidable from the syntax tree over the surface frozen in
    CONTRACT.md section 12b: the bare form, the two names directly, the same two
    through an attribute, either as a tuple member, and either through a simple
    alias. Narrow, explicitly named classes and tuples of them remain permitted.

    The earlier rule — a broad catch is fine provided some ``raise`` appears
    inside it — was not decidable: any ``raise`` anywhere satisfied it,
    including one under ``if False:``.
    """
    tree = ast.parse(source)
    aliases = _broad_aliases(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            found.append((node.lineno, "bare-except"))
            continue
        targets = (
            node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        )
        for target in targets:
            if isinstance(target, ast.Name):
                if target.id in BROAD_EXCEPTION_NAMES:
                    found.append((node.lineno, target.id))
                elif target.id in aliases:
                    found.append((node.lineno, f"alias:{target.id}"))
            elif (
                isinstance(target, ast.Attribute)
                and target.attr in BROAD_EXCEPTION_NAMES
            ):
                found.append((node.lineno, target.attr))
    return found


def _static_flag_names(expression) -> list[str] | None:
    """Flag names in a ``|``-composed static expression, or None if dynamic."""
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        left = _static_flag_names(expression.left)
        right = _static_flag_names(expression.right)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(expression, ast.Attribute):
        return [expression.attr]
    if isinstance(expression, ast.Name):
        return [expression.id]
    return None


def _os_open_is_read_only(node: ast.Call) -> bool:
    flags = node.args[1] if len(node.args) >= 2 else None
    for keyword in node.keywords:
        if keyword.arg == "flags":
            flags = keyword.value
    if flags is None:
        return False
    names = _static_flag_names(flags)
    if not names:
        return False
    return all(name in sup.READ_ONLY_OS_OPEN_FLAGS for name in names)


def _open_mode_is_read_only(node: ast.Call, mode_index: int) -> bool:
    """Mode check for ``open`` and for ``<receiver>.open``.

    The positional index differs: the builtin takes the path first, so its mode
    is argument 1, while a method call has no receiver argument, so its mode is
    argument 0. Reading the wrong slot silently treats ``Path(x).open('w')`` as
    having no mode at all.
    """
    mode = node.args[mode_index] if len(node.args) > mode_index else None
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return True
    return (
        isinstance(mode, ast.Constant)
        and isinstance(mode.value, str)
        and mode.value in sup.READ_ONLY_OPEN_MODES
    )


def write_capable_calls(source: str) -> list[tuple[int, str]]:
    """Write-capable filesystem calls, module- and receiver-aware.

    The covered surface is frozen in CONTRACT.md section 12b. It deliberately
    permits ``os.open(..., os.O_RDONLY | os.O_DIRECTORY)``, which is what a
    read-only directory binding needs, and it deliberately does not flag a bare
    ``.replace()`` or ``.copy()`` on an unknown receiver.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module, attribute = func.value.id, func.attr
            if module == "os" and attribute == "open":
                if not _os_open_is_read_only(node):
                    found.append((node.lineno, "os.open-not-read-only"))
                continue
            prohibited = sup.MODULE_QUALIFIED_WRITE_CALLS.get(module)
            if prohibited is not None and attribute in prohibited:
                found.append((node.lineno, f"{module}.{attribute}"))
                continue
        name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else getattr(func, "id", None)
        )
        if name in sup.UNAMBIGUOUS_WRITE_METHODS:
            found.append((node.lineno, name))
            continue
        if name == "open":
            mode_index = 1 if isinstance(func, ast.Name) else 0
            if not _open_mode_is_read_only(node, mode_index):
                found.append((node.lineno, "open-not-read-mode"))
    return found


def test_sr_q_010_no_production_module_catches_broadly_in_any_form():
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        offenders = broad_exception_handlers(path.read_text(encoding="utf-8"))
        assert not offenders, (path.name, offenders)


def test_sr_q_011_no_production_module_calls_a_write_capable_operation():
    """The static half of the read-only guarantee, bounded to this laboratory.

    It makes no claim about arbitrary external paths; SR-C-017 supplies the
    behavioural half over the records tree and the laboratory tree.
    """
    modules = sup.lab_production_modules()
    if not modules:
        raise AssertionError(
            f"{sup.IMPLEMENTATION_ABSENT}: no laboratory production module is "
            f"present; implementation is not yet authorized"
        )
    for path in modules:
        offenders = write_capable_calls(path.read_text(encoding="utf-8"))
        assert not offenders, (path.name, offenders)


def test_sr_q_012_the_broad_exception_guard_detects_every_prohibited_form():
    """Synthetic probes, in memory. Nothing is written and nothing is imported."""
    prohibited = (
        "try:\n    pass\nexcept:\n    pass\n",
        "try:\n    pass\nexcept Exception:\n    raise\n",
        "try:\n    pass\nexcept BaseException:\n    raise RuntimeError('x')\n",
        "try:\n    pass\nexcept (ValueError, Exception):\n    raise\n",
        "import builtins\ntry:\n    pass\nexcept builtins.Exception:\n    raise\n",
        "try:\n    pass\nexcept Exception:\n    if False:\n        raise\n",
        # Simple alias, the form named explicitly in CONTRACT.md section 12b.
        "E = Exception\ntry:\n    operation()\nexcept E:\n    handle()\n",
        "E = BaseException\ntry:\n    pass\nexcept E:\n    raise\n",
        "import builtins\nE = builtins.Exception\ntry:\n    pass\nexcept E:\n    raise\n",
        # Transitive alias chain.
        "E = Exception\nF = E\ntry:\n    pass\nexcept F:\n    raise\n",
        # Alias as a tuple member.
        "E = Exception\ntry:\n    pass\nexcept (OSError, E):\n    raise\n",
        # Alias declared inside a function body.
        "def f():\n    E = Exception\n    try:\n        pass\n    except E:\n        raise\n",
    )
    for source in prohibited:
        assert broad_exception_handlers(source), source
    permitted = (
        "try:\n    pass\nexcept OSError:\n    pass\n",
        "try:\n    pass\nexcept (OSError, ValueError):\n    raise\n",
        "try:\n    pass\nexcept KeyError:\n    raise RuntimeError('x') from None\n",
        # An alias to a NARROW class stays permitted.
        "E = OSError\ntry:\n    pass\nexcept E:\n    raise\n",
    )
    for source in permitted:
        assert not broad_exception_handlers(source), source


def test_sr_q_013_the_write_guard_detects_every_prohibited_operation():
    prohibited = (
        "import pathlib\npathlib.Path('x').write_text('y')\n",
        "import pathlib\npathlib.Path('x').write_bytes(b'y')\n",
        "import pathlib\npathlib.Path('x').mkdir()\n",
        "import pathlib\npathlib.Path('x').unlink()\n",
        "import pathlib\npathlib.Path('x').touch()\n",
        "import os\nos.remove('x')\n",
        "import os\nos.rename('x', 'y')\n",
        "import os\nos.replace('x', 'y')\n",
        "import os\nos.write(3, b'y')\n",
        "import os\nos.pwrite(3, b'y', 0)\n",
        "import os\nos.writev(3, [b'y'])\n",
        "import os\nos.ftruncate(3, 0)\n",
        "import os\nos.symlink('x', 'y')\n",
        "import shutil\nshutil.rmtree('x')\n",
        "import shutil\nshutil.copy('x', 'y')\n",
        "import tempfile\ntempfile.mkdtemp()\n",
        "open('x', 'w')\n",
        "open('x', mode='a')\n",
        "open('x', 'r+')\n",
        "import pathlib\npathlib.Path('x').open('w')\n",
        # os.open with any write, create, truncate or append flag.
        "import os\nos.open('x', os.O_WRONLY)\n",
        "import os\nos.open('x', os.O_RDONLY | os.O_CREAT)\n",
        "import os\nos.open('x', os.O_RDWR | os.O_TRUNC)\n",
        "import os\nos.open('x', os.O_RDONLY | os.O_APPEND)\n",
        # A non-static flags expression cannot be shown read-only.
        "import os\nos.open('x', flags)\n",
        "import os\nos.open('x')\n",
    )
    for source in prohibited:
        assert write_capable_calls(source), source
    permitted = (
        "open('x')\n",
        "open('x', 'rb')\n",
        "open('x', mode='r')\n",
        "import pathlib\npathlib.Path('x').read_text()\n",
        "import pathlib\npathlib.Path('x').open('rb')\n",
        "import json\njson.loads('{}')\n",
        # The read-only directory binding I06 requires must stay legal.
        "import os\nos.open('x', os.O_RDONLY | os.O_DIRECTORY)\n",
        "import os\nos.open('x', os.O_RDONLY)\n",
        "import os\nos.open('x', flags=os.O_RDONLY | os.O_NOFOLLOW)\n",
        # Harmless non-filesystem methods with generic names.
        "text = 'a'\ntext.replace('a', 'b')\n",
        "mapping = {}\nmapping.copy()\n",
        "data = b''\ndata.replace(b'a', b'b')\n",
        "import os\nos.fstat(3)\n",
        "import os\nos.close(3)\n",
        "import os\nos.read(3, 8)\n",
        "import os\nos.scandir('x')\n",
    )
    for source in permitted:
        assert not write_capable_calls(source), source


def test_sr_q_008_the_suite_scan_examined_a_non_zero_expected_surface():
    modules = sup.lab_test_modules()
    names = {path.name for path in modules}
    expected = {
        "__init__.py",
        "_support.py",
        "test_schema.py",
        "test_records.py",
        "test_validate_cli.py",
        "test_import_quarantine.py",
        "test_controls_manifest.py",
    }
    assert expected <= names, sorted(names)
    assert len(modules) >= len(expected)
    for path in modules:
        assert sup.LAB_DIR in path.parents, path
