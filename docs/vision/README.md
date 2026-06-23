# `docs/vision/` — Pre-Pivot Vision Archive (salvaged, inspiration only)

> **What this is**: a small **archive** of pre-pivot (September 2025) conceptual/theory documents, **salvaged** from stale open PR **#17** (`docs/research-and-design @ 33449a7`) so their ideas are not lost when that PR is eventually closed.
>
> **What this is NOT**: current architecture, an engine spec, validated theory, or marching orders. These predate the **February-2026 pivot to the Medusa CA engine** and describe an **abandoned `fractal_tree` vision**. Treat everything here as **historical inspiration only** — exactly like (and weaker than) the entries in [`docs/MEDUSA_THEORY_INTAKE_LEDGER.md`](../MEDUSA_THEORY_INTAKE_LEDGER.md). Inclusion here is **not** endorsement, validation, or implementation authority.

## Provenance
- **Source PR**: #17 — *"docs: add research index, design philosophy, and algorithms seeds"* — branch `docs/research-and-design`, head `33449a7`, opened 2025-09-20 by Goldislops.
- **Status of PR #17**: still **OPEN and untouched** by this salvage. This PR does **not** close, comment on, label, or merge #17 (or any stale PR). Closure of #17/#25/#52–#58 is a separate, separately-authorized action (see the stale-PR triage in [`REPOSITORY_HEALTH_AUDIT_2026-06.md`](../REPOSITORY_HEALTH_AUDIT_2026-06.md)).
- **Faithfulness**: each file below is the **verbatim** PR-#17 content with **only** a provenance banner prepended (no edits to the original text).

## Salvaged files (the 4 unique concept specs)
| File | Original path in PR #17 | What it is (pre-pivot) |
|---|---|---|
| [`DESIGN_PHILOSOPHY.md`](DESIGN_PHILOSOPHY.md) | `docs/DESIGN_PHILOSOPHY.md` | "Design Philosophy — BEAM + Mindful Replication": the early guiding-philosophy framing. |
| [`algorithms/mindfulness_protocol.md`](algorithms/mindfulness_protocol.md) | `algorithms/mindfulness_protocol.md` | "Mindfulness Protocol Algorithm": a 5-phase conceptual protocol spec. |
| [`algorithms/replication_rules.md`](algorithms/replication_rules.md) | `algorithms/replication_rules.md` | "Replication Rules Engine": pre-pivot replication-rule concepts. |
| [`algorithms/meme_propagation.md`](algorithms/meme_propagation.md) | `algorithms/meme_propagation.md` | "Meme Propagation Algorithm": flood / selective / epidemic propagation concepts (Blackmore-style memetics). |

## What was deliberately NOT salvaged (and why)
Per the AURA-ratified Option A scope, the following PR-#17 files were **dropped**:
- **6 binary PDFs** (`*.pdf` twins of the docs) — ~440 KB of merge bloat; the `.md` sources are authoritative.
- **`docs/PROJECT_LOG.md`** — dead-era project log; no forward value.
- **`docs/RESEARCH_INDEX.md`** — a pre-pivot index of content that no longer exists on `main`.
- **Anything tied to the abandoned `src/fractal_tree/` implementation** (the FT-001…007 stack in PRs #52–#58) — that framework never landed on `main` and is out of scope here.

## How to read this material
These are **muses, not mandates.** If any concept here is ever to influence Medusa, it must go through the normal route: a Theory-Intake-Ledger entry → design doc → the README §4 six-step promotion gate → explicit AURA/Jack/Kev review. Sitting in this archive grants it none of that.
