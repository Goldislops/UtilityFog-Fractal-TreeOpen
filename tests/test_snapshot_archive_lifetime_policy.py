"""One regression: a closure proof may not be written with a permissive default.

This file used to also carry an experimental repository-wide static gate that
tried to decide whether every NumPy load in `scripts/` and `vis/` released its
archive. That gate was removed before review. Repeated adversarial audit kept
finding shapes it certified while the archive leaked, and narrowing it to a
small set of recognised forms did not fix the underlying problem: whether
arbitrary code releases a resource on every path is not a question a syntactic
matcher can answer, and a gate that records its own known false certifications
is not an enforceable policy. The authoritative evidence that the corrected
loader releases its archive is behavioural, in
`tests/test_workstream_b_profile_predicates.py` and
`tests/test_dandelion_snapshot_loading.py`, which open a real archive and
assert on a real handle.

WHAT REMAINS, and exactly what it claims. `NpzFile` releases its handle by
setting `fid` to `None`, and `fid` is a CLASS attribute that is only assigned
on the instance when `np.load` owned the file. So

    getattr(handle, "closed", True)

returns its default when the attribute is absent: it reports success for an
archive that was never closed, and for one that was never even opened. That
exact spelling is what defect 2 of this PR corrected, and this file exists to
stop it coming back.

The claim is deliberately that narrow. This forbids ONE spelling. It does not
prove that closure assertions are non-vacuous in general -- a bare
`assert handle.fid is None` used as the sole witness is equally permissive, and
`h.__dict__.get("closed", True)`, a `getattr` whose attribute name is computed,
and `unittest`'s `assertIsNone` are all invisible here. Nothing in this file
should be read as evidence about any of those.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: Scanned DIRECTLY and in full: every `test_*.py` beneath it. There is no
#: discovery filter. An earlier revision only scanned files it first judged to
#: "look like" closure proofs, which meant a proof written in an unrecognised
#: style was never checked at all -- the failure mode a filter always has.
TEST_DIR = "tests"


def _permissive_closure_defaults(tree) -> list:
    """Line numbers of ``getattr(x, "closed", <default>)`` calls in ``tree``.

    Any default is flagged, not just a literal ``True``: a non-literal default
    cannot be read statically and is no safer.
    """
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) == 3
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "closed"
    ]


def _offenders(root=None):
    """``(offenders, scanned)`` for every ``test_*.py`` under ``TEST_DIR``."""
    root = _REPO_ROOT if root is None else root
    directory = root / TEST_DIR
    assert directory.is_dir(), f"{TEST_DIR}/ is missing -- the scan covers nothing"

    offenders, scanned = {}, 0
    for path in sorted(directory.rglob("test_*.py")):
        scanned += 1
        hits = _permissive_closure_defaults(
            ast.parse(path.read_text(encoding="utf-8"))
        )
        if hits:
            offenders[path.relative_to(root).as_posix()] = hits
    return offenders, scanned


_PLANTED_OFFENDER = (
    'def test_archive_is_released(archives):\n'
    '    assert getattr(archives[0].fid, "closed", True)\n'
)

_PLANTED_STRICT = (
    'def test_archive_is_released(archives, original_fid):\n'
    '    assert archives[0].zip is None\n'
    '    assert original_fid.closed\n'
)


def test_no_snapshot_closure_proof_uses_a_permissive_default():
    """The regression itself, over the whole declared scope.

    The scanned count is asserted because an empty offenders mapping is also
    what a wrong glob or a renamed directory returns.
    """
    offenders, scanned = _offenders()
    assert scanned, f"no test_*.py found under {TEST_DIR}/ -- wrong scope"
    assert offenders == {}, (
        "closure proof written with a permissive getattr default "
        f"(path -> line numbers): {offenders}"
    )


def test_the_matcher_flags_a_planted_offender():
    """Non-vacuity: "no findings" and "the matcher is broken" look identical."""
    assert _permissive_closure_defaults(ast.parse(_PLANTED_OFFENDER)) == [2]


def test_the_matcher_accepts_a_strict_control():
    """A proof that reads the handle state directly must not be flagged."""
    assert _permissive_closure_defaults(ast.parse(_PLANTED_STRICT)) == []
