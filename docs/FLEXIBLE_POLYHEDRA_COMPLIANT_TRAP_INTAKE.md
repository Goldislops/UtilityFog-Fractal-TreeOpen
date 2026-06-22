# Flexible Polyhedra / Compliant Trap Intake

> **Status**: source-hygiene intake and speculative design analogy. This note records a
> geometry metaphor for future theory work. It is **not** an engine spec, not a
> toy inception, and not implementation authority.

## Why This Exists

Toy #5 established a sharp boundary for passive trap mechanics:

- v0 latch: a localized rule-mask can arrest a canonical Conway glider, but only
  by transforming it into a small contained period-1/2 Life object.
- v1 strict-passive freeze: an always-on local freeze behaves like an inert wall;
  it shears the glider on entry, with 0/384 release-success.

That result naturally raises a different question: can a trap **yield** under
entry, preserve identity, and then lock without becoming a timed shutter? A
Steve Mould video on Jessen's icosahedron / flexible polyhedra supplied a useful
analogy, but the geometry terms are easy to conflate. This note preserves the
corrected science before the metaphor gets reused.

## Corrected Geometry

### Jessen's Orthogonal Icosahedron

Jessen's orthogonal icosahedron, also called Jessen's icosahedron, is a
"shaky" polyhedron: rigid, but not infinitesimally rigid. It has a first-order
motion, but it is not a genuinely flexible polyhedron.

Use it as inspiration for **near-mechanism / first-order yielding**, not as an
example of true continuous flex.

### Connelly Sphere / Connelly's Flexible Polyhedron

Robert Connelly's 1977 example is the first non-self-intersecting embedded
flexible polyhedron in three-dimensional Euclidean space. It is commonly
referred to as the Connelly sphere or Connelly's flexible polyhedron, and the
example discussed in the intake has **18 triangular faces**.

This is the true flexible-polyhedron object in the story, distinct from the
Jessen "shaky" object.

### Steffen's Polyhedron

Steffen's polyhedron is a later and simpler embedded flexible polyhedron, with
14 triangular faces. It is useful background, but it is not the 18-face Connelly
example.

## Bellows Boundary

The Bellows conjecture, proved by Sabitov and later Connelly-Sabitov-Walz in
generality, states that a flexible polyhedron preserves its enclosed volume
while flexing. Informally: it can change shape while all face shapes / edge
lengths stay fixed, but it cannot pump like a bellows because its volume does
not change.

Guardrail: do **not** casually apply the Bellows theorem to Jessen's
icosahedron. Jessen's object is rigid-but-shaky, not a true flexible polyhedron.

## Safe Medusa Translation

This is inspiration for a future **Discrete Compliant Trap** or
**Quasi-Mechanism Trap** primitive.

Candidate future question:

> Can a localized discrete rule yield under entry, preserve a structure's
> identity signature, and then lock without requiring an explicit temporal
> shutter?

This is **not** Toy #5 v0, not Toy #5 v1 strict-passive, and not Janus+MOF
coupling. It would be a separately named primitive if the team ever chooses to
promote it.

Possible discrete invariants, to be chosen only in a future design lock:

- live-cell count;
- bounding box;
- canonical phase and orientation;
- period signature;
- re-emergence after release;
- local identity signature.

## What This Does Not Authorize

- No code.
- No engine, observer, GPU, R3, Vanguard, Lane A, or Swarm Hunter work.
- No Toy #6.
- No Janus+MOF coupling.
- No shutter/gating experiment.
- No continuous Hooke's law, tensile strain, material elasticity, floating-point
  mechanics, or real material model.

Any future use must pass the normal theory-promotion path: source verification,
explicit design doc, falsifiable criteria, Jack/AURA/Kev review, separate PR,
and no Lane A activation unless separately gated.

## References / Source Hygiene

- Borge Jessen's orthogonal icosahedron / Jessen's icosahedron: rigid but not
  infinitesimally rigid ("shaky"), not truly flexible.
- Robert Connelly, "A counterexample to the rigidity conjecture for polyhedra,"
  *Publications Mathematiques de l'IHES*, 1977.
- Robert Connelly, "A flexible sphere," *The Mathematical Intelligencer*, 1978.
- Robert Connelly, I. Sabitov, and Anke Walz, "The Bellows Conjecture,"
  *Beitrage zur Algebra und Geometrie*, 1997.
- Steffen's polyhedron: later embedded flexible polyhedron with 14 triangular
  faces.

Secondary web references used for intake hygiene:

- <https://en.wikipedia.org/wiki/Jessen%27s_icosahedron>
- <https://en.wikipedia.org/wiki/Flexible_polyhedron>
- <https://en.wikipedia.org/wiki/Steffen%27s_polyhedron>
- <https://de.wikipedia.org/wiki/Robert_Connelly>
