"""Required-check workflow drift guard (Package AO).

Branch protection requires the status contexts ``agent-safety``,
``verify-python`` and ``frontend-quality``. Those context names are
produced by workflow JOBS in this repository, so workflow drift (a
renamed job, an added path filter, a job-level ``if:``, a trigger that
drops PR-update events) can silently make a required context stop
reporting and wedge every PR.

SCOPE / BOUNDARY (deliberate): a repository test can only guard the
GIT-CONTROLLED half of the contract -- the workflow files. It cannot
read or enforce the live branch-protection settings; the settings-side
evidence remains the recorded GET receipts (strict=true with exactly
the three contexts, 2026-07-12 consolidation).

Parsing note: CI's Python lane deliberately installs no YAML library,
and this guard must not introduce a dependency for one assertion file.
The ``_WorkflowDoc`` helper below is a BOUNDED STRUCTURAL reader for the
narrow, indentation-regular subset GitHub workflow files use (top-level
keys, the ``jobs:`` mapping, per-job keys, step ``uses:`` refs). It
builds a real (line, indent) tree -- not a formatting regex -- and is
BLOCK-SCALAR AWARE (Jack delta-audit): the literal content of ``|`` and
``>`` scalars (``run:`` scripts, ``path:`` lists) is excluded from every
structural scan, so shell text can never be mistaken for a job id, a
``uses:`` ref, a ``permissions`` grant or a ``pull_request_target``
trigger. Every rule reports file/job/rule in its failure message, and
the self-tests at the bottom fire each rule against inline VIOLATION
fixtures -- including multiline decoys -- without ever mutating the real
workflows.
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
# A PR-update trigger must fire on branch creation AND every subsequent
# push, or a required check goes stale on the newest commit. These are
# the default pull_request activity types; a `types:` filter that drops
# any of them can wedge merging.
CORE_PR_TYPES = frozenset({"opened", "synchronize", "reopened"})
# End-of-line block scalar indicator: `key: |`, `key: >`, with optional
# chomping (+/-) and explicit-indent digits, optional trailing comment.
_BLOCK_SCALAR_OPENER = re.compile(r":[ \t]*[|>][+-]?[0-9]*[ \t]*(#.*)?$")


class _WorkflowDoc:
    """Bounded, block-scalar-aware structural view of a workflow file."""

    def __init__(self, text: str, name: str) -> None:
        self.name = name
        self.lines = text.splitlines()
        # Line indices that are the LITERAL CONTENT of a block scalar and
        # must be excluded from every structural scan.
        self.content_lines = self._compute_block_scalar_lines()

    def _compute_block_scalar_lines(self) -> set[int]:
        content: set[int] = set()
        n = len(self.lines)
        i = 0
        while i < n:
            line = self.lines[i]
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and _BLOCK_SCALAR_OPENER.search(line):
                key_indent = len(line) - len(line.lstrip())
                j = i + 1
                while j < n:
                    cl = self.lines[j]
                    if not cl.strip():
                        content.add(j)
                        j += 1
                        continue
                    ci = len(cl) - len(cl.lstrip())
                    if ci <= key_indent:
                        break
                    # Literal content (indented past the block key) — never
                    # a nested opener: block scalar bodies are opaque text.
                    content.add(j)
                    j += 1
                i = j
                continue
            i += 1
        return content

    def _structural(self, i: int) -> bool:
        return i not in self.content_lines

    def _block(self, start: int) -> list[tuple[int, str]]:
        """Structural lines belonging to the block opened at ``start``."""
        base_indent = len(self.lines[start]) - len(self.lines[start].lstrip())
        out: list[tuple[int, str]] = []
        for i in range(start + 1, len(self.lines)):
            line = self.lines[i]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent and self._structural(i):
                break
            if self._structural(i):
                out.append((i, line))
        return out

    def top_level_key(self, key: str) -> int | None:
        for i, line in enumerate(self.lines):
            if not self._structural(i):
                continue
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
            # Direct children of `jobs:` only — exactly 2-space indent.
            # Deeper job-body keys and block-scalar content never match.
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$", line)
            if m:
                ids[m.group(1)] = i
        return ids

    def job_block(self, job_id: str) -> list[tuple[int, str]]:
        at = self.job_ids().get(job_id)
        assert at is not None, f"{self.name}: job '{job_id}' not found"
        return self._block(at)

    def job_has_key(self, job_id: str, key: str) -> bool:
        # Job-level key: exactly 4-space indent (step-level and deeper
        # keys, and block-scalar content, are excluded).
        return any(
            re.match(rf"^    {re.escape(key)}:", line) for _, line in self.job_block(job_id)
        )

    def on_block(self) -> list[tuple[int, str]]:
        at = self.top_level_key("on")
        assert at is not None, f"{self.name}: no top-level on: key"
        return self._block(at)

    def pull_request_block(self) -> list[tuple[int, str]] | None:
        """The `pull_request:` trigger's own sub-block, or None if absent.

        Matches `pull_request:` exactly — never `pull_request_target:`."""
        for i, line in self.on_block():
            if re.match(r"^  pull_request:\s*(#.*)?$", line):
                return self._block(i)
        return None

    def pull_request_types(self) -> set[str] | None:
        """The activity types on the pull_request trigger, or None if the
        trigger pins no `types:` (i.e. GitHub's defaults apply)."""
        pr = self.pull_request_block()
        if pr is None:
            return None
        for idx, (i, line) in enumerate(pr):
            m = re.match(r"^    types:\s*(.*?)\s*(#.*)?$", line)
            if not m:
                continue
            rest = m.group(1)
            flow = re.match(r"^\[(.*)\]$", rest)
            if flow:
                return {t.strip() for t in flow.group(1).split(",") if t.strip()}
            # Block-list form: subsequent `- item` lines, more indented.
            types: set[str] = set()
            for _, item in pr[idx + 1 :]:
                bm = re.match(r"^      -\s*(\S+)", item)
                if not bm:
                    break
                types.add(bm.group(1))
            return types
        return None

    def uses_refs(self) -> list[tuple[int, str]]:
        """Every structural `uses:` ref, quoted or unquoted; script text
        inside block scalars is skipped."""
        out: list[tuple[int, str]] = []
        for i, line in enumerate(self.lines):
            if not self._structural(i):
                continue
            m = re.match(r"""^\s*-?\s*uses:\s*['"]?([^'"#\s]+)['"]?""", line)
            if m:
                out.append((i, m.group(1)))
        return out

    def permissions_write_grants(self) -> list[tuple[int, str]]:
        """(line, text) of write scopes inside any structural permissions:
        block — block-scalar content (e.g. a `run:` script mentioning
        `contents: write`) is excluded."""
        grants: list[tuple[int, str]] = []
        for i, line in enumerate(self.lines):
            if not self._structural(i):
                continue
            if re.match(r"^\s*permissions:\s*(#.*)?$", line):
                for j, inner in self._block(i):
                    if re.search(r":\s*write(-all)?\s*(#.*)?$", inner.split("#")[0]):
                        grants.append((j, inner.strip()))
            elif re.match(r"^\s*permissions:\s*write-all\s*(#.*)?$", line):
                grants.append((i, line.strip()))
        return grants

    def structural_hits(self, needle: str) -> list[int]:
        """1-indexed structural line numbers containing ``needle`` (comment
        text stripped); block-scalar content is excluded."""
        return [
            i + 1
            for i, line in enumerate(self.lines)
            if self._structural(i) and needle in line.split("#")[0]
        ]


def _load(filename: str) -> _WorkflowDoc:
    path = WORKFLOWS / filename
    assert path.is_file(), f"{filename}: workflow file missing"
    return _WorkflowDoc(path.read_text(encoding="utf-8"), filename)


# Required PR workflows: (filename, required job ids). agent-safety pins
# the default PR activity types explicitly; ci.yml leaves them at default.
_REQUIRED_PR_WORKFLOWS = (
    ("ci.yml", REQUIRED_CI_JOBS),
    ("agent-safety.yml", (REQUIRED_SAFETY_JOB,)),
)


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


def _assert_unconditional_for_prs(filename: str, required_jobs: tuple[str, ...]) -> None:
    doc = _load(filename)
    pr = doc.pull_request_block()
    assert pr is not None, (
        f"{filename}/on: no pull_request trigger -- a required context that "
        f"never runs on PRs wedges merging"
    )
    # No path filters: an out-of-path PR would never produce the context.
    for i, line in pr:
        key = line.split("#")[0]
        assert not re.match(r"^    paths(-ignore)?:", key), (
            f"{filename}:{i + 1}: a paths/paths-ignore filter on the required "
            f"pull_request trigger ({line.strip()!r}) makes the context vanish "
            f"for out-of-path PRs"
        )
    # If types are pinned, they must still cover the core PR-update events.
    types = doc.pull_request_types()
    if types is not None:
        missing = CORE_PR_TYPES - types
        assert not missing, (
            f"{filename}/on/pull_request/types: drops {sorted(missing)} -- the "
            f"required context would not re-run on those PR events (keep at "
            f"least {sorted(CORE_PR_TYPES)})"
        )
    # No job-level `if:` that could suppress a required job.
    for job in required_jobs:
        assert not doc.job_has_key(job, "if"), (
            f"{filename}/jobs/{job}: a job-level if: condition can make this "
            f"required context disappear; keep it unconditional"
        )


def test_required_pr_workflows_are_unconditional() -> None:
    for filename, jobs in _REQUIRED_PR_WORKFLOWS:
        _assert_unconditional_for_prs(filename, jobs)


def test_required_workflows_keep_least_privilege_permissions() -> None:
    for filename, jobs in _REQUIRED_PR_WORKFLOWS:
        doc = _load(filename)
        top = doc.top_level_key("permissions")
        job_scoped = all(doc.job_has_key(job, "permissions") for job in jobs)
        assert top is not None or job_scoped, (
            f"{filename}: no explicit permissions at workflow level and not on "
            f"every required job -- required jobs must keep explicit "
            f"least-privilege permissions"
        )
        for line_no, grant in doc.permissions_write_grants():
            raise AssertionError(
                f"{filename}:{line_no + 1}: permissions grant a write scope "
                f"({grant!r}) -- required workflows are read-only"
            )


def test_no_pull_request_target_anywhere() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = _WorkflowDoc(path.read_text(encoding="utf-8"), path.name)
        hits = doc.structural_hits("pull_request_target")
        assert not hits, (
            f"{path.name}:{hits[0]}: pull_request_target grants secret access to "
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

# A required workflow that pins the DEFAULT PR types explicitly (mirrors
# the real agent-safety.yml) — this must be accepted, not rejected.
_FIXTURE_TYPES_OK = _FIXTURE_OK.replace(
    "  pull_request:\n",
    "  pull_request:\n    types: [opened, synchronize, reopened]\n",
)

# A run: block scalar that writes a nested workflow via heredoc, so its
# literal content contains lines that a NAIVE structural scan would
# mistake for real structure: a `uses:` ref, a `permissions:`/write
# grant, and a `pull_request_target:` trigger, each at the natural
# indentation (no echo-quoting to disarm them). Block-scalar awareness is
# what keeps them out of every structural scan.
_FIXTURE_MULTILINE_DECOY = _FIXTURE_OK.replace(
    "      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n",
    "      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n"
    "      - name: write a decoy workflow\n"
    "        run: |\n"
    "          cat > /tmp/decoy.yml <<'YAML'\n"
    "          permissions:\n"
    "            contents: write\n"
    "          jobs:\n"
    "            injected:\n"
    "              steps:\n"
    "                - uses: evil/action@v1\n"
    "          on:\n"
    "            pull_request_target:\n"
    "          YAML\n",
    1,
)


def test_selftest_parser_reads_the_ok_fixture() -> None:
    doc = _WorkflowDoc(_FIXTURE_OK, "fixture.yml")
    assert set(doc.job_ids()) == {"verify-python", "frontend-quality"}
    assert doc.top_level_key("permissions") is not None
    assert len(doc.uses_refs()) == 2


def test_selftest_missing_job_is_detected() -> None:
    doc = _WorkflowDoc(_FIXTURE_OK.replace("frontend-quality:", "frontend-renamed:"), "fixture.yml")
    assert "frontend-quality" not in doc.job_ids()


def test_selftest_default_types_are_accepted() -> None:
    doc = _WorkflowDoc(_FIXTURE_TYPES_OK, "fixture.yml")
    assert doc.pull_request_types() == set(CORE_PR_TYPES)
    missing = CORE_PR_TYPES - (doc.pull_request_types() or set())
    assert not missing  # a defaults-pinning types filter is safe


def test_selftest_types_dropping_a_core_event_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "  pull_request:\n", "  pull_request:\n    types: [opened, reopened]\n"
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    missing = CORE_PR_TYPES - (doc.pull_request_types() or set())
    assert missing == {"synchronize"}


def test_selftest_block_list_types_are_parsed() -> None:
    broken = _FIXTURE_OK.replace(
        "  pull_request:\n",
        "  pull_request:\n    types:\n      - opened\n      - reopened\n",
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    assert doc.pull_request_types() == {"opened", "reopened"}


def test_selftest_paths_filter_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "  pull_request:\n", "  pull_request:\n    paths: ['src/**']\n"
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    pr = doc.pull_request_block()
    assert pr is not None
    assert any(re.match(r"^    paths(-ignore)?:", line.split("#")[0]) for _, line in pr)


def test_selftest_paths_ignore_filter_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "  pull_request:\n", "  pull_request:\n    paths-ignore: ['docs/**']\n"
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    pr = doc.pull_request_block()
    assert pr is not None
    assert any(re.match(r"^    paths(-ignore)?:", line.split("#")[0]) for _, line in pr)


def test_selftest_job_level_if_is_detected() -> None:
    broken = _FIXTURE_OK.replace(
        "  frontend-quality:\n    runs-on: ubuntu-latest\n",
        "  frontend-quality:\n    if: github.repository == 'x/y'\n    runs-on: ubuntu-latest\n",
    )
    doc = _WorkflowDoc(broken, "fixture.yml")
    assert doc.job_has_key("frontend-quality", "if")


def test_selftest_agent_safety_paths_and_if_drift_is_detected() -> None:
    # An agent-safety-shaped required workflow that drifts on BOTH a paths
    # filter and a job-level if — the generalized rule must catch each.
    drifted = (
        "name: Agent Safety\n"
        "on:\n"
        "  pull_request:\n"
        "    types: [opened, synchronize, reopened]\n"
        "    paths: ['policy/**']\n"
        "permissions:\n"
        "  contents: read\n"
        "jobs:\n"
        "  agent-safety:\n"
        "    if: github.actor != 'dependabot[bot]'\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n"
    )
    doc = _WorkflowDoc(drifted, "agent-safety.yml")
    pr = doc.pull_request_block()
    assert pr is not None
    assert any(re.match(r"^    paths(-ignore)?:", line.split("#")[0]) for _, line in pr)
    assert doc.job_has_key("agent-safety", "if")


def test_selftest_quoted_uses_is_parsed_and_pin_checked() -> None:
    pinned = _FIXTURE_OK.replace(
        "      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n",
        '      - uses: "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"\n',
        1,
    )
    doc = _WorkflowDoc(pinned, "fixture.yml")
    refs = [ref for _, ref in doc.uses_refs()]
    # Quotes are stripped; the pin is recognised.
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in refs
    assert all(FULL_SHA.search(ref + " ") for ref in refs)

    unpinned = _FIXTURE_OK.replace(
        "      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0\n",
        "      - uses: 'actions/checkout@v4'\n",
        1,
    )
    doc2 = _WorkflowDoc(unpinned, "fixture.yml")
    assert [r for _, r in doc2.uses_refs() if not FULL_SHA.search(r + " ")] == [
        "actions/checkout@v4"
    ]


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


def test_selftest_write_permission_grant_is_detected() -> None:
    broken = _FIXTURE_OK.replace("  contents: read", "  contents: write")
    doc = _WorkflowDoc(broken, "fixture.yml")
    grants = doc.permissions_write_grants()
    assert [g for _, g in grants] == ["contents: write"]


def test_selftest_block_scalar_content_is_not_read_as_structure() -> None:
    doc = _WorkflowDoc(_FIXTURE_MULTILINE_DECOY, "fixture.yml")
    # The decoy job id inside the run: script is NOT a job.
    assert set(doc.job_ids()) == {"verify-python", "frontend-quality"}
    # The decoy `uses: evil/action@v1` inside the script is NOT a uses ref.
    assert all("evil" not in ref for _, ref in doc.uses_refs())
    # The decoy `contents: write` inside the script is NOT a permission grant.
    assert doc.permissions_write_grants() == []
    # The decoy pull_request_target mention inside the script is NOT a trigger.
    assert doc.structural_hits("pull_request_target") == []
