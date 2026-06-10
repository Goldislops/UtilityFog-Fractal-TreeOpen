# Theory Tripwire Action — Design (v0, no implementation)

> **Status**: design document only. **Nothing here is implemented.** No GitHub Action exists, no workflow files are added by this PR, no labels are created, no automation runs. Implementation (v1) happens only after Jack/AURA/Kev review this design.
>
> **Origin**: AURA's "memory needs teeth" delta (recorded in `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` → "AURA follow-up mechanisms"), sequenced by Jack as a design-first arc.

**Created**: 2026-06-10 (84/Fab5). **Guardrails**: docs only · no `.github/workflows` changes · no bot code · no engine/observer/Lane A/Swarm Hunter touch.

---

## 1. Purpose

Give the theory memory spine — `docs/MEDUSA_THEORY_INTAKE_LEDGER.md` and `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` — **teeth at future architectural decision points**:

- When a PR moves toward Lane A activation, Swarm Hunter work, observer-semantics changes, or a theory→architecture promotion, a small bot comment reminds the author (human or agent) that status-labelled caveats and a promotion gate exist, and links them.
- The failure mode it prevents: a future session (fresh container, no conversation memory) doing architecture work without ever opening the ledger — exactly the "wake up in the wrong timeline" class of error the bridge doc already fights, but at the *decision* moment rather than the *orientation* moment.
- It must be **low-noise by construction** (see §5) — a tripwire, not a klaxon.

## 2. Non-goals

- **Not a blocker** in v1 — comment-only, never a failing check.
- **Not a policy engine** — it links the gate; it does not evaluate compliance.
- **Not a reviewer replacement** — Jack/AURA/Kev review remains the actual gate.
- **Not an engine guard** — runtime safety stays in `params_schema.py` / tuning-API rails.
- **Not Lane A activation, not Swarm Hunter implementation** — it's a signpost about them, nothing more.

## 3. Triggers

### 3a. Primary: labels (deliberate, low-noise)
A PR triggers the tripwire when it carries any of:

| Label | Meaning |
|---|---|
| `lane-a-activation` | PR proposes acting on observer signals |
| `swarm-hunter` | PR touches Swarm Hunter design/implementation |
| `observer-semantics` | PR changes observer meaning (tokens, cascade, status model) |
| `theory-to-architecture` | PR promotes a ledger/preflight entry toward real design |
| `architecture-gate` | catch-all for gate-relevant work |

Labels are **opt-in and human/agent-applied**, which makes them the cleanest trigger: zero false positives by accident, and applying one is itself a moment of intent.

### 3b. Secondary: file paths (combination rule)
- Changes to **future Lane A / Swarm Hunter code paths** (once they exist — named at implementation time): trigger directly.
- Changes to the **theory docs themselves** (`docs/MEDUSA_THEORY_INTAKE_LEDGER.md`, `docs/MATURIN_ARC_THEORY_PREFLIGHT.md`): trigger **only in combination with** one of the §3a labels. Rationale: routine ledger maintenance (adding entry 11, fixing a typo) is docs gardening, not a gate moment — path-alone triggering would have fired on five recent maintenance PRs (#188, #189, #192, #194, and the entry-7 wording fix) for nothing.
- Core observer files (`scripts/nextness_observer.py`, `scripts/nextness_calibration.py`): **deferred decision** — see §8. They change for legitimate Lane-B hardening too.

### 3c. Explicitly rejected for v1: title/body phrase scanning
Proposed phrases ("Lane A", "Swarm Hunter", "promotion gate", "theory intake") fail on this repo's *actual history*: **every PR body we write contains "Lane A parked" as a guardrail attestation** — phrase-triggering on "Lane A" would have commented on essentially 100% of recent PRs (#172→#197). Negative-phrase parsing ("Lane A *parked*" vs "Lane A *activation*") is exactly the fragile NLP-by-regex this design avoids. If labels prove insufficient, revisit in v2 with word-boundary + negation rules — not before.

## 4. Comment payload

One short comment, posted once (see §5):

> ⚠️ **Theory-to-architecture boundary detected** (label: `<label>` / path: `<path>`).
> This PR appears to touch a gated scope. Before promotion, please confirm the five-step gate:
> **1.** source verification · **2.** explicit design doc · **3.** tests or falsification criteria · **4.** Jack/AURA/Kev review · **5.** no Lane A activation unless separately gated.
> Relevant caveats: [`MEDUSA_THEORY_INTAKE_LEDGER.md`](../blob/main/docs/MEDUSA_THEORY_INTAKE_LEDGER.md) · [`MATURIN_ARC_THEORY_PREFLIGHT.md`](../blob/main/docs/MATURIN_ARC_THEORY_PREFLIGHT.md) · [`AGENT_HANDOFF.md`](../blob/main/AGENT_HANDOFF.md)
> *(Comment-only; not a blocking check. Apply `tripwire-reviewed` to acknowledge.)*
> `<!-- theory-tripwire-marker -->`

The trailing HTML marker makes the comment machine-detectable for idempotency (§5).

## 5. Noise controls

1. **At most one comment per PR, ever** — before commenting, the Action searches existing comments for `theory-tripwire-marker`; if present, it exits silently (no edits, no re-posts on synchronize/label events).
2. **Labels over fuzzy scanning** (§3c).
3. **No comment on docs-only theory-doc maintenance** without a §3a label (§3b combination rule).
4. **Manual acknowledgment**: the `tripwire-reviewed` label suppresses any future triggering on that PR.
5. **Non-blocking in v1**: the workflow always exits 0; it can never redden the gate.
6. If it ever misfires repeatedly, the rollback is one-file: delete the workflow. No state, no migrations.

## 6. Safety rules

- **Comment-only**: no auto-merge, no auto-close, no auto-labeling, no branch pushes in v1.
- **Minimal permissions**: workflow-scoped `permissions: { contents: read, pull-requests: write }` and nothing else; default `GITHUB_TOKEN` only — no custom secrets.
- **No external network calls** — repo-local logic only.
- **Fork-safety note for implementation**: comment-writing on PRs interacts with GitHub's reduced-permission rules for fork PRs (`pull_request` vs `pull_request_target`). v1 must use the safe pattern (this is a solo repo today, but design for it anyway) — flagged as an implementation-PR review point.

## 7. Implementation plan (later PRs, each gated)

| Version | Content | Gate |
|---|---|---|
| **v0 (this doc)** | Design only | Jack/AURA/Kev review of this PR |
| **v1** | One small workflow file (separate from `ci.yml` — lightweight, independently removable), label creation, comment-once logic per §3–§6 | Separate PR; stop before merge; verify on a deliberately-labelled test PR |
| **v2 (only if needed)** | Optional required-check mode, phrase rules with negation, broader path coverage | Only after v1 proves quiet in practice |

## 8. Open questions (for review of this doc)

1. **Exact label set** — are the five §3a names right? Fewer? (`architecture-gate` may be redundant with `theory-to-architecture`.)
2. **Observer-path triggering** — should `scripts/nextness_*.py` changes trigger directly, or stay label-only? (They change for legitimate Lane-B work; my lean: label-only until Lane A files exist.)
3. **Mechanism choice** — GitHub Action (recommended: zero-friction, automatic) vs PR template checkbox (zero-code but relies on authors reading templates) vs issue template. My lean: Action for the tripwire + *also* adding the five-step gate to a PR template is cheap and complementary.
4. **Workflow placement** — separate `theory-tripwire.yml` (recommended: independently disableable) vs a job inside `ci.yml`.
5. **Label creation timing** — labels don't exist yet; create them in the v1 PR, or earlier by hand so humans can start using them as intent-markers before automation exists? (My lean: create at v1; they're meaningless until something listens.)

---

## Relationship to existing guardrails

This tripwire automates a *reminder of* — never a *replacement for* — the promotion gate in `docs/MATURIN_ARC_THEORY_PREFLIGHT.md` ("Integration with #180" section) and the graduation path in `docs/MEDUSA_THEORY_INTAKE_LEDGER.md`. Lane A remains parked regardless of any label, comment, or absence thereof. The mouthguard is designed; the teeth wait for the next gate.
