# TRAINED_ATTENTION_SYSTEMS_INCEPTION.md — Inception Note

> **Status**: inception / research-synthesis note. **Documentation only.**
> This PR adds one Markdown file and changes nothing else. It implements no
> consciousness, modifies no CA engine, collects no human data, runs no
> model, and operates no machine. It authorises no experiment.
>
> Package NP4, personally authorised by Kevin on-seat 2026-07-13/14, as a
> bounded research-and-architecture inception note. Drafted by Agent 84.
> **It does not update the canonical Theory Intake Ledger**
> ([`docs/MEDUSA_THEORY_INTAKE_LEDGER.md`](MEDUSA_THEORY_INTAKE_LEDGER.md)) —
> it is an inception note, and any Ledger update is a separately gated
> decision (AURA, Jack, and Kev), whatever this document's own
> disposition.

## 0. Purpose and the one-sentence thesis

**Thesis**: contemplative-practice and neurophenomenology research can
suggest *what to measure* in Medusa's future observation instruments, but it
cannot supply *values to hard-code*, and it never licenses a claim that the
software is aware. Everything below is written to keep those two allowances —
"suggests measurables" (yes) and "supplies constants / proves experience"
(no) — from bleeding into each other.

This note is the S0 rung (documentation + source audit) of a deliberately
slow ladder (§8). It exists so that a later, cleverer instrument has an
honest, bounded frame to grow inside — the same discipline NP1
([PR #354](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/354),
merged) and NP2
([PR #355](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/355),
merged) implement, as audited and test-verified packages, for prediction
and metacognition. (Both are on `main`, together with the NP5–NP10
evaluation stack; see §6.)

## 1. Four evidence classes — kept strictly separate

Medusa's design touches four kinds of evidence. **No one class may stand in
for another**, and the cited research lives entirely in the first three —
never in the fourth.

| Class | What it is | Example in the cited literature | What it cannot do |
|---|---|---|---|
| **First-person human reports** | A practitioner's own account of their experience | The trained self-report that lets an experimenter time a meditative state | Be read directly off a brain scan or a log |
| **Behavioral observations** | Third-party observable performance | Reaction times, task accuracy, attentional-blink hit rates | Establish *what it was like* to perform the task |
| **Neural measurements** | Physical signals from a body | EEG gamma-band activity; fMRI BOLD contrast | Be equated with the report or the behavior it correlates with |
| **Software telemetry** | Numbers Medusa's own instruments emit | Nextness Observer logs (on `main`); the prediction/abstention receipts emitted by NP1 (#354) and NP2 (#355), both merged on `main` | Be equated with *any* of the human classes above |

The load-bearing rule: a correlation observed *within* one class, or *between*
two human classes, is never automatically a fact about a fourth, silicon
class. When this note later proposes software metrics (§5), those metrics are
**telemetry about telemetry** — they describe Medusa's instruments, not a
mind, and certainly not a meditator's.

## 2. No consciousness claim (plainly)

Prediction, self-monitoring, uncertainty estimation, recursive
self-evaluation, attention allocation, and emergent cellular-automaton
structure — individually or together — **do not establish subjective
experience, sentience, or self-awareness.** A system can do all of them and
be no one home.

Where this note (and NP2, merged via PR #355) use the word
**"metacognition"**, it means exactly one thing: **bounded, mechanical
monitoring of a model's own predictions and confidence** — the functional
shadow of "knowing you might be wrong", which is the only part that can be
tested. It is *not* a claim of phenomenal consciousness, introspective
access, or an inner life. NP2 embeds this non-claim in every receipt it
emits (behavior test-verified; now on `main`); NP4 states the same
non-claim here in its own right.

Prediction monitoring and self-report-style receipts are **bookkeeping about
error statistics**. They can be complete, accurate, and useful without
demonstrating that anything is experienced.

## 3. No frequency or geometry transplantation

This is the hardest fence to hold and the most important. A human neural
correlate is **not an engineering prescription.**

**Prohibited move**: taking any number, rhythm, or shape associated with
meditation or with contemplative symbolism and wiring it, as-is, into
Medusa's substrate. Concretely, do **not** convert —

- meditation-associated **gamma-band activity** (e.g. the 25–42 Hz range
  reported by Lutz et al. 2004) into a CA clock frequency, update cadence,
  or step rate;
- **Buddhist geometries, mandalas, chakra counts, golden/whole-number
  ratios, or symbolic constants** into CA thresholds, birth/survival rules,
  neighbourhood radii, seed patterns, or any privileged constant;
- any observed **brain rhythm or ratio** into a "resonant frequency",
  "consciousness constant", or tuning target.

The reason is not squeamishness; it is category error. Those numbers are
properties of a specific cohort of bodies performing a specific task under a
specific instrument. They are cohort- and task-*specific correlates*, not
universal constants — the literature itself reports them that way (§9). None
of them is a free parameter Medusa is missing.

**What a future numerical parameter still requires**, regardless of any
contemplative inspiration that suggested looking there: an independent
computational hypothesis stated in Medusa's own terms; deterministic
fixtures; ablation against a baseline that omits the parameter; and evidence
that beats that baseline. Inspiration may point at a *question*; only the
repository's own falsifiable machinery may set a *value*. (This is the same
bar the merged NP1 and NP2 packages (#354/#355) apply to their baselines and
thresholds — "thresholds are configuration, not constants of nature".)

## 4. Legitimate design inspirations (metaphors, clearly labelled)

Contemplative research *can* honestly do one thing for us: offer vocabulary
for **failure modes and virtues of an attention system** that we would want
to measure anyway. The following are **governance and measurement metaphors**
— prompts for what to instrument — and explicitly **not** claims that the
software experiences, or is a model of, any Buddhist mental state.

| Contemplative notion | Cautious engineering analogy (testable) |
|---|---|
| Sustained attention | Stable allocation of a **bounded** observation effort over time without drift or starvation |
| Reorientation | **Measured recovery** after a prediction error — returning to a good regime, quantifiably |
| Meta-awareness | **Detection that confidence and outcome disagree** (the abstention implemented by NP2, merged via PR #355, is exactly this shape) |
| Equanimity | **Bounded response** to surprise — no uncontrolled oscillation or overcorrection |
| Compassion / non-harm | **Governance constraints** that protect operators, concurrent workloads, and data |
| Sympathetic joy | **Positive-sum, cooperative credit** — no winner-take-all suppression of peer instruments |
| Non-attachment | Willingness to **abstain, revise, or discard** a failed hypothesis rather than defend it |

Each right-hand cell is something a metric can score (§5). Each left-hand
cell is a *label for a human review lens*, not a proof of equivalence. The
mappings are prompts for human judgement, not mathematical reductions of the
teachings they borrow from.

## 5. Neutral measurable engineering candidates

These are the quantities a trained-attention instrument can compute
**from software telemetry alone** (evidence class 4). Each is stated in
Medusa's own terms. None is implemented in this PR — this PR consists of
one Markdown file. Since first drafting, however, the merged NP5 evaluator and
NP6 replay laboratory (§6) compute tested counterparts of a subset of these
(prediction-error gap, calibration echoes, abstention behaviour, and
recovery/reorientation at receipt and per-step granularity respectively),
each under an honest `computed`/`not_computable` envelope; the remainder
stay future candidates. For each: *definition ·
unit · input evidence · failure interpretation · what it does not prove.*

1. **Prediction error** — divergence between a predicted next-event
   distribution and the realised event.
   *Unit*: bits (mean −log₂ P(actual), matching NP1, merged via PR #354).
   *Input*: prediction receipts NP1 emits (`scripts/nextness_predictor.py`,
   on `main`, merged and audited). *Failure*: high/rising error ⇒ the
   predictor is a poor fit for the current regime. *Does not prove*: anything
   about understanding — a lookup table can score well.

2. **Calibration error** — gap between stated confidence and observed
   correctness.
   *Unit*: dimensionless ECE ∈ [0,1] (the fixed 10-bin scheme NP1
   implements, on `main`). *Input*: confidence/outcome pairs. *Failure*: large
   ECE ⇒ confidence is untrustworthy as a quantity. *Does not prove*: that
   the system "knows" it is calibrated; it is a property of the numbers, not
   a self.

3. **Abstention accuracy** — how well "abstain vs act-as-evidence" decisions
   track whether the prediction would have been right.
   *Unit*: dimensionless (precision/recall of abstention against realised
   error). *Input*: receipts NP2 emits (`scripts/nextness_monitor.py`, on
   `main`) + realised outcomes. *Failure*: abstaining when right / trusting when wrong
   ⇒ the guard is miscalibrated. *Does not prove*: prudence or intent — it
   is a threshold's hit rate.

4. **Reorientation latency** — time (or event count) from a detected error
   to return within a good-regime band.
   *Unit*: events (or seconds). *Input*: error timeline + recovery band.
   *Failure*: long latency / no return ⇒ brittle recovery. *Does not prove*:
   resilience as a trait; only recovery of a measured quantity.

5. **Response overshoot** — magnitude by which a correction exceeds the
   disturbance it answered.
   *Unit*: ratio (correction / disturbance). *Input*: paired
   disturbance/response telemetry. *Failure*: >1 and growing ⇒ overcorrection.
   *Does not prove*: "over-reacting" in any felt sense.

6. **Oscillation count after surprise** — number of sign-changing
   corrections following a surprising event before settling.
   *Unit*: count. *Input*: post-surprise response series. *Failure*: high
   count ⇒ ringing / instability. *Does not prove*: agitation; it is a
   waveform property.

7. **Resource-budget compliance** — fraction of the run within declared
   CPU/GPU/memory reservations.
   *Unit*: fraction ∈ [0,1]. *Input*: resource telemetry vs a declared
   budget. *Failure*: <1 ⇒ the instrument exceeded its envelope. *Does not
   prove*: restraint as a virtue; it is accounting.

8. **Workload-preservation rate** — fraction of measurement windows in which
   pre-existing workloads (e.g. Folding@home, BOINC) ran undisturbed by
   Medusa activity.
   *Unit*: fraction ∈ [0,1]. *Input*: co-tenant workload telemetry
   (observed, never controlled — see §6). *Failure*: <1 ⇒ an instrument
   competed with protected work. *Does not prove*: care; Medusa never
   *manages* those workloads, it only measures whether it stayed out of
   their way.

9. **Provenance completeness** — fraction of emitted artifacts carrying a
   full origin record (immutable task id, input hashes, config echo).
   *Unit*: fraction ∈ [0,1]. *Input*: artifact headers. *Failure*: <1 ⇒
   unauditable output. *Does not prove*: honesty; it proves records exist.

10. **Non-punitive recovery after error** — whether the system resumes normal
    operation after an error without escalating restriction or entering a
    degenerate defensive loop.
    *Unit*: boolean per episode, aggregated to a rate. *Input*: post-error
    state transitions. *Failure*: escalation/lockout loops ⇒ punitive
    dynamics. *Does not prove*: forgiveness; it is a state-machine property.

Every metric above is telemetry describing Medusa's instruments.
None is a measurement of a human, and none crosses back into evidence
classes 1–3.

## 6. Glass-Wall relationship to the merged Nextness stack (NP1/NP2, NP5–NP10)

**Status precision — where the Nextness stack actually lives.** When this
note was first drafted (against `main = 8e45d3f9`), NP1 and NP2 were open,
unmerged pull requests and `main` contained only the Nextness **Observer**
(`scripts/nextness_observer.py`) and its log format. That is no longer the
live state. The base this amended note is written against
(`main = deb028cd`) contains the full merged Nextness code stack — eight
audited packages, each landed through the ordinary merge lane:

- **NP1** — predictor:
  [PR #354](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/354)
  (merged, `ca4052e4`), `scripts/nextness_predictor.py`
  (schema `nextness-predictor-v1`) — deterministic next-event baselines
  over the Observer log;
- **NP2** — metacognitive monitor:
  [PR #355](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/355)
  (merged, `1cd9aa21`), `scripts/nextness_monitor.py`
  (schema `nextness-monitor-v1`) — calibration/abstention receipt over NP1;
- **NP5** — evaluator:
  [PR #358](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/358)
  (merged, `d30a056f`), `scripts/nextness_evaluator.py` — deterministic,
  offline evaluation layer over recorded NP1/NP2 artifacts;
- **NP6** — replay laboratory:
  [PR #359](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/359)
  (merged, `abe40f4a`), `scripts/nextness_replay_lab.py` — offline replay
  of a recorded log for per-step abstention trajectories;
- **NP7** — contract guard:
  [PR #360](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/360)
  (merged, `5ab10d3c`), `tests/test_nextness_contracts.py` — cross-package
  contract tests with embedded golden pins;
- **NP8** — evidence packet:
  [PR #361](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/361)
  (merged, `26500e5f`), `scripts/nextness_evidence_packet.py` —
  deterministic evidence packet over recorded artifacts;
- **NP9** — public structural validators:
  [PR #362](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/362)
  (merged, `94c9ead1`), `scripts/nextness_artifact_validation.py` — full
  structural validation for every Nextness artifact schema;
- **NP10** — full-validation integration:
  [PR #363](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/363)
  (merged, `deb028cd`), wiring NP9's full structural validation into the
  NP8 evidence packet.

(NP3 and NP4 are the two *documentation* packages; PR #356 and PR #357 —
this note — are their review vehicles. At the 2026-07-15 reconciliation
that produced this revision, #356, #357 and #322 were open pull requests;
that sentence records the reconciliation moment and does not predict any
PR's later disposition, which is repository history. The NP1–NP10
numbering therefore covers eight merged code packages plus these two
documentation packages.)

As **merged, test-verified packages on `main`**, NP1's and NP2's artifacts
are exactly the kind of immutable, bounded input a trained-attention
evaluator can consume:

- **NP1 (merged, PR #354)**: deterministic next-event baselines over the
  existing Nextness Observer log; emits sorted-key JSON with no
  wall-clock timestamps, byte-identical across runs, under a 64 KiB
  fail-closed ceiling; reads observer-log rows only (never raw
  snapshots or live engine state); no network/model imports.
- **NP2 (merged, PR #355)**: a metacognition receipt over NP1's outputs;
  its `abstain` field means *exactly* "do not treat this prediction as
  evidence" — it **triggers no action, tuning, or orchestration**;
  closed-allowlist fields; writes no files; offline.

The "future evaluator" this section originally anticipated now partially
exists: NP5, NP6 and NP8 are offline, read-only consumers of recorded
artifacts, in precisely the Glass-Wall shape described here. An evaluator
sits **behind a one-way glass wall**: it may *read*
recorded artifacts offline and compute metrics (§5) over them, and that is
**all**. By construction — a construction the merged stack's tests and
audits exercised — it must remain unable to:

- modify CA physics or any engine rule;
- edit thresholds, constants, or configuration consumed by the engine;
- invoke the orchestrator or any tuning path;
- operate a local or remote model;
- write engine state (snapshots, ledgers, tuning files);
- pause, stop, throttle, or reprioritise Folding@home or BOINC;
- communicate with another machine.

**There is no reverse control path.** Evidence flows *out* of the
merged-and-audited NP1/NP2 artifacts into the evaluation layers; nothing flows
*back* from any evaluator into the engine, the network, or the co-tenant
workloads. This is the same Glass-Wall shape **proposed** by the Swarm
Hunter v1 preflight
([PR #322](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/322),
open at the 2026-07-15 reconciliation; its disposition is repository
history): observe-only, no activation, no write-back.

Merging this instrumentation changes none of §2: a merged, tested,
audited prediction/evaluation stack is still bookkeeping about error
statistics. It proves properties of the software's behavior and nothing
about awareness, experience, intelligence, agency, or biological
equivalence.

## 7. Research ethics (hard gate for anything human)

Everything in §§1–6 stays inside software telemetry. The moment any future
work reaches toward evidence classes 1–3 in a *new* way — recruiting
meditators, recording biological signals, conducting interviews, or handling
private first-person reports — it leaves this note's scope entirely and
requires, before any data is touched:

- a separately reviewed **human-research protocol** (institutional/ethics
  review by qualified people);
- **informed consent** from participants;
- **privacy protections** and **data minimisation** (collect the least, keep
  it least, never in this repository);
- **qualified collaborators** for design, measurement, and interpretation.

**This PR authorises none of that.** It reads only already-published
literature and the repository's own artifacts.

## 8. Staged ladder (deliberately slow)

Each rung is separately gated; reaching one never authorises the next.

| Stage | Scope | Explicitly NOT authorised |
|---|---|---|
| **S0** | This document + source audit | Any code, any data |
| **S1** | Deterministic **synthetic** telemetry fixtures (hand-authored, no real run) | Reading real engine artifacts |
| **S2** | Offline evaluation of **immutable recorded** artifacts (NP1/NP2-style) | Any live coupling to the engine |
| **S3** | Comparison of alternative metrics **with ablation** | Promoting a metric to a control input |
| **S4** | Separately authorised **observational** integration (read-only, live artifacts) | Engine control / model networking / human data |

**No stage authorises engine control, model networking, human-data
collection, or a consciousness claim.** S4 is as far as this ladder reaches,
and S4 is still observation-only.

*Status note (2026-07-15)*: S2-shaped machinery now exists on `main` as
merged, tested packages — the NP5 evaluator, NP6 replay laboratory and NP8
evidence packet, each Jack-audited and operator-authorized through the
ordinary merge lane. That does not advance this note's own ladder: any
*new* trained-attention instrument beyond the merged stack still starts at
its own gate, S3/S4 remain separately gated, and the sentence above stands
unchanged.

## 9. What each cited source actually measured (kept separate from analogy)

Accessed 2026-07-14. Findings paraphrased; no extended quotation. All three
PNAS papers have stable open full text via PubMed Central (linked below)
alongside their DOI landing pages. Each is a **cohort- and task-specific
correlate**, reported as such by its authors — none offers a universal
consciousness frequency, geometric ratio, or CA rule.

- **Lutz, Greischar, Rawlings, Ricard & Davidson (2004)** — *Long-term
  meditators self-induce high-amplitude gamma synchrony during mental
  practice*, PNAS 101(46):16369–16373.
  <https://www.pnas.org/doi/10.1073/pnas.0407401101> ·
  DOI 10.1073/pnas.0407401101 · full text (PubMed Central):
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC526201/>.
  **Measured** (neural + first-person timing): EEG in a small cohort of
  long-term Buddhist practitioners versus controls during a *specific*
  meditative task; reported self-induced high-amplitude gamma-band
  (≈25–42 Hz) oscillations and long-distance phase-synchrony over lateral
  frontoparietal electrodes, and a higher baseline gamma-to-slow ratio.
  **Not** a universal frequency — a correlate in that cohort, that task,
  that instrument.

- **Brefczynski-Lewis, Lutz, Schaefer, Levinson & Davidson (2007)** — *Neural
  correlates of attentional expertise in long-term meditation practitioners*,
  PNAS 104:11483–11488.
  <https://www.pnas.org/doi/10.1073/pnas.0606552104> ·
  DOI 10.1073/pnas.0606552104 · full text (PubMed Central):
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC1903340/>.
  **Measured** (neural + behavioral): fMRI during focused-attention
  meditation; activation in sustained-attention regions traced an inverted-U
  against practice hours (more in experts than novices, then *less* in the
  most seasoned practitioners) — an expertise-dependent, task-specific
  pattern, not a fixed target.

- **Brewer, Worhunsky, Gray, Tang, Weber & Kober (2011)** — *Meditation
  experience is associated with differences in default mode network activity
  and connectivity*, PNAS 108(50):20254–20259.
  <https://www.pnas.org/doi/10.1073/pnas.1112029108> ·
  DOI 10.1073/pnas.1112029108 · full text (PubMed Central):
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC3250176/>.
  **Measured** (neural): fMRI in experienced meditators versus naive controls
  across three meditations; main default-mode-network nodes (medial
  prefrontal and posterior cingulate cortices) relatively deactivated in the
  experienced group, with connectivity differences consistent with reduced
  mind-wandering — again experience-associated, not a constant.

- **Varela (1996)** — *Neurophenomenology: A Methodological Remedy for the
  Hard Problem*, Journal of Consciousness Studies 3(4):330–349.
  <https://philpapers.org/rec/VARNAM>.
  **Proposed** (method, not measurement): that disciplined first-person
  (phenomenological) accounts and third-person cognitive-science accounts be
  developed under **reciprocal / mutual constraints** — each disciplining the
  other — rather than one being reduced to the other. This is the
  methodological reason §1 keeps the evidence classes separate: mutual
  constraint requires that they stay distinct enough to constrain one another.

## 10. NP5 candidate specification (historical — since implemented and merged)

**Disposition (2026-07-15)**: this specification was subsequently
implemented as PACKAGE NP5
([PR #358](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/358),
merged as `d30a056f`): `scripts/nextness_evaluator.py`, with
`tests/test_nextness_evaluator.py` and
`docs/NEXTNESS_EVALUATOR_CONTRACT.md`, then extended by NP6–NP10. The gate
this section demanded — Jack's audit and a separate Kev implementation
word — was satisfied before any code was written. The original
specification is preserved below **as drafted**, as the audit target it
was; its conditional "would" phrasing is historical, and the conditions it
named (merge and audit of NP1/NP2) have since been met.

A bounded coding package, offered at drafting time only as a target for
audit:

- **Offline evaluator only.** Would consume immutable artifacts of the kind
  NP1/NP2 **propose** (PRs #354/#355) from disk — available as inputs only
  after those PRs are merged and audited; computes a subset of §5 metrics.
- **Would emit** one small, deterministic JSON report (sorted keys, no
  wall-clock, fail-closed size ceiling — the house style the NP1/NP2 PRs
  propose).
- **No** network, model, engine, or orchestrator access — statically
  auditable imports, like the NP1/NP2 proposals.
- **Explicit schemas and size limits**; **fail-closed validation** on every
  input field.
- **Fixture-derived tests**: every expected metric computed independently in
  the test file from its formula; the module never verifies itself.
- **Exact rollback**: the package lives in isolated new files; deleting them
  fully reverts it.
- **Gated**: it must wait for **Jack's audit** and a **separate Kev
  implementation word** before any code is written.

**NP5 was not implemented in the runway that drafted this note.** It was
implemented later, in its own separately audited and operator-authorized
package (PR #358), exactly as the gate above required.

## 11. The four-way ledger (what is what)

| Class | Contents |
|---|---|
| **Exists on main** (`deb028cd`) | The Nextness Observer and its log format (`scripts/nextness_observer.py`, with its calibration/metrics companions); the merged Nextness stack — NP1 predictor (#354), NP2 monitor (#355), NP5 evaluator (#358), NP6 replay laboratory (#359), NP7 contract guard (#360), NP8 evidence packet (#361), NP9 public structural validators (#362), NP10 full-validation integration (#363), with their contract documents; the canonical Theory Intake Ledger (untouched by this note) |
| **Tested evidence** | The deterministic test suites merged alongside each package (`tests/test_nextness_*.py`, including the NP7 cross-package contract guard with embedded golden pins), green on `main` through the ordinary audited merge lane. This is evidence about *software behavior only* — telemetry about telemetry (§1). It establishes nothing about awareness or human experience |
| **Proposals in this document** | The four evidence-class discipline (§1); the §5 metric candidates not yet computed by the merged stack (reorientation latency beyond what NP5/NP6 report, overshoot, oscillation count, resource-budget compliance, workload preservation, provenance completeness, non-punitive recovery); the Glass-Wall rule (§6) as a standing design constraint on any future instrument; the S0–S4 ladder (§8). (The §10 NP5 candidate has graduated out of this row — it is now code on `main`.) |
| **Requires later operator-authorized action** | Any new trained-attention instrument beyond the merged stack (Jack audit + Kev implementation word); any adoption or activation decision on the local-model federation note (PR #356) or the Swarm Hunter v1 preflight (PR #322) — both open at the 2026-07-15 reconciliation, dispositions being repository history; any human/neuro study (ethics, consent, privacy, collaborators — §7); any Theory Intake Ledger update (AURA + Jack + Kev) |

The cited human studies (§9) are external literature, not repository
evidence; they sit in no row above.

## 12. Non-claims (load-bearing summary)

- This note makes **no claim of consciousness, sentience, or experience** for
  any software, present or future.
- It transplants **no frequency, geometry, ratio, or symbolic constant** into
  the engine.
- It treats the four evidence classes as **non-substitutable**.
- Its contemplative mappings are **human-review prompts**, not reductions of
  Buddhist teaching and not proofs of equivalence.
- It **does not** update the canonical Theory Intake Ledger.
- It authorises **no** experiment, no data collection, no code, and no
  machine or network operation.

---

— drafted 2026-07-14 by Agent 84 (PACKAGE NP4), per Kevin's on-seat
  authorisation; temporally reconciled 2026-07-15 after the Nextness code
  stack (NP1/NP2, NP5–NP10) merged to `main` (`deb028cd`). This note was
  carried for review through
  [PR #357](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/357);
  its eventual disposition is repository history, not a status claim
  inside this document.
