"""Required-check workflow drift guard (Package AO).

Branch protection requires the status contexts ``agent-safety``,
``verify-python`` and ``frontend-quality``. Those context names are
produced by workflow JOBS in this repository, so workflow drift (a
renamed job, an added path filter, a job-level ``if:``) can silently
make a required context stop reporting and wedge every PR.

SCOPE / BOUNDARY (deliberate): a repository test can only guard the
GIT-CONTROLLED half of the contract -- the workflow files. It cannot
read or enforce the live branch-protection settings; the settings-side
evidence remains the recorded GET receipts (strict=true with exactly
the three contexts, 2026-07-12 consolidation).

Parsing note: CI's Python lane deliberately installs no YAML library,
and this guard must not introduce a dependency for one assertion file.
The ``_WorkflowDoc`` helper below is a BOUNDED STRUCTURAL reader for
the narrow, indentation-regular subset GitHub workflow files use (top-
level keys, the ``jobs:`` mapping, per-job keys, step ``uses:`` refs).
It builds a real (line, indent) tree -- it is not a formatting regex --
and every rule reports file/job/rule in its failure message. The
self-tests at the bottom run each rule against inline VIOLATION
fixtures, so the guard itself is failure-tested without ever mutating
the real workflows.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

REQUIRED_CI_JOBS = ("verify-python", "frontend-quality")
REQUIRED_SAFETY_JOB = "agent-safety"
REMOVED_INERT_JOB = "verify"
FULL_SHA = re.compile(r"@[0-9a-f]{40}(\s|#|$)")


class _WorkflowDoc:
    """Bounded structural view of a GitHub workflow file."""

    def __init__(self, text: str, name: str) -> None:
        self.name = name
        self.lines = text.splitlines()

    def _block(self, start: int) -> list[tuple[int, str]]:
        """Lines belonging to the block opened at ``start`` (exclusive)."""
        base_indent = len(self.lines[start]) - len(self.lines[start].lstrip())
        out: list[tuple[int, str]] = []
        for i in range(start + 1, len(self.lines)):
            line = self.lines[i]
            if not line.strip() or line.lstrip().startswith("#"):
                out.append((i, line))
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent:
                break
            out.append((i, line))
        return out

    def top_level_key(self, key: str) -> int | None:
        for i, line in enumerate(self.lines):
            if re.match(rf"^{re.escape(key)}:\s*(#.*)?$", line) or re.match(
                rf"^{re.escape(key)}:\s+\S", line
            ):
                return i
        return None

    def job_ids(self) -> dict[str, int]:
        jobs_at = self.top_level_key("jobs")
        assert jobs_at is not None, f"{self.name}: no top-level jobs: key"
        ids: dict[str, int] = {}
        for i, line in self._block(jobs_at):
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)
            if m:
                ids[m.group(1)] = i
        return ids

    def job_block(self, job_id: str) -> list[tuple[int, str]]:
        at = self.job_ids().get(job_id)
        assert at is not None, f"{self.name}: job '{job_id}' not found"
        return self._block(at)

    def job_has_key(self, job_id: str, key: str) -> bool:
        return any(
            re.match(rf"^    {re.escape(key)}:", line) for _, line in self.job_block(job_id)
        )

    def on_block(self) -> list[tuple[int, str]]:
        at = self.top_level_key("on")
        assert at is not None, f"{self.name}: no top-level on: key"
        return self._block(at)

    def uses_refs(self) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        for i, line in enumerate(self.lines):
            m = re.match(r"^\s*-?\s*uses:\s*(\S+)", line)
            if m:
                out.append((i, m.group(1)))
        return out

    def text(self) -> str:
        return "\n".join(self.lines)


def _load(filename: str) -> _WorkflowDoc:
    path = WORKFLOWS / filename
    assert path.is_file(), f"{filename}: workflow file missing"
    return _WorkflowDoc(path.read_text(encoding="utf-8"), filename)


# ---------------------------------------------------------------------------
# Contract over the real workflow files
# ---------------------------------------------------------------------------


def test_ci_yml_defines_both_required_job_ids() -> None:
    doc = _load("ci.yml")
    ids = doc.job_ids()
    for job in REQUIRED_CI_JOBS:
        assert job in ids, (
            f"ci.yml: required job id '{job}' is missing -- the branch-protection "
            f"context of the same name would stop reporting and wedge every PR"
        )


def test_agent_safety_yml_defines_the_agent_safety_job() -> None:
    doc = _load("agent-safety.yml")
    assert REQUIRED_SAFETY_JOB in doc.job_ids(), (
        "agent-safety.yml: required job id 'agent-safety' is missing -- the "
        "required context would stop reporting"
    )


def test_frontend_quality_is_unconditional_for_prs() -> None:
    doc = _load("ci.yml")
    # Workflow-level: pull_request trigger present and carrying NO paths
    # filter (a filtered required check disappears on out-of-path PRs and
    # wedges them under branch protection).
    on_lines = [line for _, line in doc.on_block()]
    assert any(re.match(r"^  pull_request:\s*(#.*)?$", l) for l in on_lines), (
        "ci.yml/on: pull_request trigger must be present and bare -- a paths/"
        "types filter here can make required contexts vanish for some PRs"
    )
    for _, line in doc.on_block():
        assert "paths" not in line.split("#")[0], (
            f"ci.yml/on: a paths filter appeared ({line.strip()!r}) -- required "
            f"contexts must be always-present for PRs"
        )
    # Job-level: no `if:` that could suppress the required jobs.
    for job in REQUIRED_CI_JOBS:
        assert not doc.job_has_key(job, "if"), (
            f"ci.yml/jobs/{job}: a job-level if: condition can make this "
            f"required context disappear; keep it unconditional"
        )


def _permissions_write_grants(doc: _WorkflowDoc) -> list[tuple[int, str]]:
    """(line, text) of write scopes inside any permissions: block."""
    grants: list[tuple[int, str]] = []
    for i, line in enumerate(doc.lines):
        if re.match(r"^\s*permissions:\s*(#.*)?$", line):
            for j, inner in doc._block(i):
                if re.search(r":\s*write(-all)?\s*(#.*)?$", inner.split("#")[0] or inner):
                    grants.append((j, inner.strip()))
        elif re.match(r"^\s*permissions:\s*write-all\s*(#.*)?$", line.split("#")[0] + " "):
            grants.append((i, line.strip()))
    return grants


def test_required_workflows_keep_least_privilege_permissions() -> None:
    for filename, jobs in (("ci.yml", REQUIRED_CI_JOBS), ("agent-safety.yml", (REQUIRED_SAFETY_JOB,))):
        doc = _load(filename)
        top = doc.top_level_key("permissions")
        job_scoped = all(doc.job_has_key(job, "permissions") for job in jobs)
        assert top is not None or job_scoped, (
            f"{filename}: no explicit permissions at workflow level and not on "
            f"every required job -- required jobs must keep explicit "
            f"least-privilege permissions"
        )
        for line_no, grant in _permissions_write_grants(doc):
            raise AssertionError(
                f"{filename}:{line_no + 1}: permissions grant a write scope "
                f"({grant!r}) -- required workflows are read-only"
            )


def test_no_pull_request_target_anywhere() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            assert "pull_request_target" not in line.split("#")[0], (
                f"{path.name}:{n}: pull_request_target grants secret access to "
                f"fork code paths and is banned in this repository"
            )


def test_every_uses_reference_is_full_sha_pinned() -> None:
    for filename in ("ci.yml", "agent-safety.yml"):
        doc = _load(filename)
        for i, ref in doc.uses_refs():
            assert FULL_SHA.search(ref + " "), (
                f"{filename}:{i + 1}: uses reference {ref!r} is not pinned to a "
                f"full 40-hex commit SHA (repository pinning policy)"
            )


def test_the_removed_inert_root_verify_job_does_not_return() -> None:
    doc = _load("ci.yml")
    assert REMOVED_INERT_JOB not in doc.job_ids(), (
        "ci.yml: the inert root 'verify' job (removed 2026-07-12 after "
        "branch-protection Phase 2) has reappeared -- it auto-passed without "
        "verifying anything and its context is no longer required"
    )


# ---------------------------------------------------------------------------
# Failing-fixture self-tests: each rule must actually fire on a violation.
# Inline fixtures only -- the real workflows are never mutated.
# ---------------------------------------------------------------------------

_FIXTURE_OK = """\
name: F
on:
  pull_request:
  push:
permissions:
  contents: read
jobs:
  verify-python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
  frontend-quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
"""


def test_selftest_parser_reads_the_ok_fixture() -> None:
    doc = _WorkflowDoc(_FIXTURE_OK, "fixture.yml")
    assert set(doc.job_ids()) == {"verify-python", "frontend-quality"}
    assert doc.top_level_key("permissions") is not None
    assert len(doc.uses_refs()) == 2


def test_selftest_missing_job_is_detected() -> None:
    doc = _WorkflowDoc(_FIXTURE_OK.replace("frontend-quality:", "frontend-renamed:"), "fixture.yml")
    assert "frontend-quality" not in doc.job_ids()


def test_selftest_paths_filter_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "  pull_request:\n", "  pull_request:\n    paths: ['src/**']\n"
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    assert any("paths" in line for _, line in doc.on_block())


def test_selftest_job_level_if_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "  frontend-quality:\n    runs-on: ubuntu-latest\n",
        "  frontend-quality:\n    if: github.repository == 'x/y'\n    runs-on: ubuntu-latest\n",
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    assert doc.job_has_key("frontend-quality", "if")


def test_selftest_unpinned_uses_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0",
        "actions/checkout@v4",
        1,
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    unpinned = [ref for _, ref in doc.uses_refs() if not FULL_SHA.search(ref + " ")]
    assert unpinned == ["actions/checkout@v4"]


def test_selftest_returned_verify_job_is_detected() -> None:
    broken = _FIXTURE_OK + "  verify:\n    runs-on: ubuntu-latest\n"
    doc = _WorkflowDoc(broken, "fixture.yml")
    assert "verify" in doc.job_ids()


def test_selftest_pull_request_target_is_detected() -> None:
    broken = _FIXTURE_OK.replace("  pull_request:", "  pull_request_target:")
    hits = [l for l in broken.splitlines() if "pull_request_target" in l.split("#")[0]]
    assert hits


def test_selftest_write_permission_grant_is_detected() -> None:
    broken = _FIXTURE_OK.replace("  contents: read", "  contents: write")
    doc = _WorkflowDoc(broken, "fixture.yml")
    grants = _permissions_write_grants(doc)
    assert [g for _, g in grants] == ["contents: write"]
