# OMI_V3_OBSERVATION_INCEPTION.md — the OMI-V3A observation envelope

> **Status**: implemented, inert, and hermetic. Corrected five times — after
> Jack's first HOLD round (§ 11), his second (§ 13), his third (§ 15), a fourth
> adversarial review (§ 17), and a fifth (§ 18) whose production correction is
> upstream in ``scripts/open_model/structured_exchange.py``. Each section lists
> every defect that round found and what each one cost. Modules
> [`scripts/open_model/observation.py`](../scripts/open_model/observation.py)
> and
> [`scripts/open_model/observation_receipt.py`](../scripts/open_model/observation_receipt.py).
>
> **What this is NOT.** Nothing here contacts an endpoint, resolves a name,
> opens a socket, downloads a model or a package, starts a runtime, registers a
> backend, or inspects a process, service, driver, port, credential, or any
> hardware or workload state. No model was run, loaded, listed, or measured in
> producing this document or the code it describes. `GET /api/tags`,
> `GET /api/ps`, `/v1/models`, and every health and inference endpoint remain
> uncontacted. Folding@home, BOINC, and Medusa operational state were not
> looked at, and this package has no means of looking at them.
>
> **What it is.** OMI-V3A turns the *design requirement* recorded in
> [`LOCAL_MODEL_DEPLOYMENT_INCEPTION.md`](LOCAL_MODEL_DEPLOYMENT_INCEPTION.md)
> § 7 — "Task envelope — design requirements only" — into an immutable carrier,
> a total planner, a single-invocation executor, and a payload-free receipt.
> The envelope is real; what it plans is still nothing, because the only thing
> that could reach a runtime is an exchange callable the caller injects, and no
> such callable exists in this repository outside a test double.
>
> **Same-author evidence.** This document and every control it cites were
> written by the agent that wrote the code under test. They demonstrate
> internal consistency, not independent acceptance.

## 1. Where this sits in the sequence

The inception note's § 4 gates are ordered, and each blocks everything after
it. OMI-V3A is deliberately positioned so that it clears none of them and
prejudges none of them:

| Gate | Status | What OMI-V3A does about it |
|------|--------|----------------------------|
| 1. R/S/T lands and passes post-merge audit | R [#328](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/328), S [#333](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/333), T [#334](https://github.com/Goldislops/UtilityFog-Fractal-TreeOpen/pull/334) are merged ancestors of the base commit | Verified as ancestors before this branch was cut. OMI-V3A does not claim the post-merge audit is complete, and runs no live test either way. |
| 2. First model role is observation-only | Encoded structurally | There is no tool capability, no proposal capability, no commit capability, no mutation action, no controller role, and no registration path anywhere in the package. |
| 3. One host, loopback, first | Encoded as a *declared* constraint | The envelope will not accept an endpoint that is not `http://<numeric-loopback>:<port>/v1`. It validates the declaration; it connects to nothing. |
| 4. Two machines behind a protected transport | Untouched | Out of scope, unaddressed, and unprejudged. |

The § 6 rule — *the experiment declares its CPU, GPU, and memory reservations
up front, and if they are not available it defers* — is encoded as a hard gate
in § 5 below. The § 7 role table's `Observer` row is the whole of what an
OMI-V3A envelope can ask for.

## 2. Reuse, and what would have been a second implementation

The standing boundary is *reuse, don't reinvent*. OMI-V3A adds no second
validator, no second dialect map, no second refusal vocabulary, and no second
network guard. Concretely:

| Concern | Whose code decides it |
|---------|----------------------|
| Is this dialect supported? | OMI-V2 `is_supported_dialect` |
| Is this schema acceptable, and what is its detached snapshot? | OMI-V2 `_validated_snapshot`, via `plan_structured_request` |
| What wire shape does this dialect need? | OMI-V2 `build_response_format` |
| Did the response parse as a usable JSON object? | OMI-V1 `validate_structured_output`, via OMI-V2 `request_structured_json` |
| What may a request refusal say? | OMI-V2 `REFUSAL_TOKENS` / `EXCHANGE_REFUSALS`, imported |
| Is a request refusal pre- or post-dialect? | OMI-V2 `is_pre_dialect_refusal`, imported |
| What may a response failure say? | OMI-V1/V2 `RESPONSE_FAILURES`, imported |
| Is this identifier safe to store? | OMI-V1 `is_safe_token` |
| Is the network blocked during a rehearsal? | OMI-V1 `hermetic_guard` |

`PlanRefusal` is **composed** from OMI-V2's `StructuredRefusal` exactly as
`ExchangeRefusal` is, so a dialect or schema token added to OMI-V2 arrives here
without an edit. Controls assert the two V3A vocabularies are disjoint from all
three OMI-V2 vocabularies, that no V3A token begins `dialect-` or `schema-`,
that the four dialect names appear nowhere in V3A source, and that the objects
V3A holds in its closure cells **are** OMI-V2's — `plan_structured_request`,
`StructuredOutputRequest`, `request_structured_json`, `is_supported_dialect`,
`is_pre_dialect_refusal`, `EXCHANGE_REFUSALS`, `RESPONSE_FAILURES`.

The two V3A modules also share every numeric bound rather than each holding a
copy: they live in `observation_receipt.py` and are imported by
`observation.py`, and a control asserts each is the *same object* in both. A
bound with two values is a bound with none.

One helper is imported rather than copied: `_restore_identity`, the eight-line
function that gives a factory-built class its module-level `__qualname__` back
so it can pickle. The import is intra-package and pinned by a control asserting
identity. One number *is* restated — `_MAX_SCHEMA_BYTES`, so the envelope can
bound a decode before handing the document to OMI-V2 — and a control asserts it
still equals `structured_request._SCHEMA_MAX_CHARS`.

`schema_conformance` remains closed to the single token `"unverified"`. Nothing
in OMI-V3A compares a response against the schema that was sent.

## 3. The envelope contract

`plan_observation` is keyword-only, **total over every input including a clock
that raises**, and never raises. It returns an `ObservationPlan` carrying
either an `ObservationEnvelope` or one closed token.

| Property | How it is enforced |
|----------|--------------------|
| **Immutable task identity** | `new_task_id()` generates a canonical UUIDv4 from a closed factory; `is_canonical_uuid4` accepts only the lowercase hyphenated 36-character form with version nibble `4` and variant in `{8,9,a,b}`. |
| **Input hashes** | Every `EvidenceItem` holds exact built-in `bytes` and computes its own SHA-256 in `__post_init__`. `digest` is not an init field, so a caller cannot supply one. `bytearray`, `memoryview` and `bytes` subclasses are refused. |
| **Bounded context** | Nothing ambient is read. Every evidence item is explicit, bounded per item and in total against both a module ceiling and the caller's declared bound, and must decode as strict UTF-8. |
| **Bounded result** | `max_result_bytes` bounds the canonical rendering of the accepted structured object; OMI-V2's `max_chars` bounds the payload string before it parses. |
| **Deadline** | Derived as `issued_ns + duration_ns` from an exact-`int` bounded duration and one reading of a caller-supplied monotonic clock, with both figures and the derived deadline inside the clock ceiling (§ 4a). |
| **Provenance** | An authorizing-principal token and a worker token, both `is_safe_token`. |
| **Declared loopback endpoint** | § 4. |
| **Resource reservation** | § 5. |

### Exact type is not unaltered

`object.__setattr__` will replace any field on a frozen dataclass, and the
digest computed at construction does not follow. A carrier cannot defend its
own past, so **every consumer re-derives**:

- **Before planning**, `plan_observation` revalidates each `EvidenceItem`'s
  identifier, byte payload, size and stored digest, and each
  `ResourceReservation`'s three figures and stored digest — recomputing both
  digests from the content actually present and requiring exact equality. All
  of it happens in the one controlled traversal that also builds the envelope's
  own tuple, so no caller container is read twice.
- **At construction**, `ObservationEnvelope.__post_init__` does the same, so a
  directly built envelope is held to the identical standard.
- **Before executing**, `execute_observation` re-derives the whole digest tree
  (§ 6).

This is the correction for Jack's first finding; § 11 records what it cost.

### One semantic authority, three consumers

There is now exactly **one** definition of an acceptable envelope —
`_envelope_semantics` — and the planner, the carrier and the executor all hold
it in a closure cell. That is structural rather than editorial, and it is the
answer to the same mistake found twice: Jack's first round caught the carrier
checking less than the planner about the dialect and the schema, and his second
caught it *still* checking less about strict UTF-8 evidence, which let invalid
bytes reach the adapter and raise `UnicodeDecodeError` out of a function
documented as total. Two gates that must agree cannot be two pieces of code.

A directly accepted envelope therefore cannot carry an unsupported, arbitrary,
subclassed or secret-shaped dialect; evidence that is not strict UTF-8; schema
bytes that are not the canonical ASCII rendering of a snapshot OMI-V2 accepts
*for that dialect*; a `schema_digest` that does not hash exactly those bytes; a
stale evidence or reservation digest; an over-limit field; or incoherent
required keys. Every rejection is `_EnvelopeRefused` — a `ValueError` carrying
the closed token — so no half-built envelope exists for a caller to hand to the
executor, and `plan_observation` stays total by translating the token back into
a plan refusal.

The schema check is not a second validator: the bytes are decoded, parsed, and
put back through OMI-V2's own `plan_structured_request`, and the snapshot it
returns is re-rendered canonically and compared byte-for-byte. A control
asserts, by object identity, that all three consumers hold the same functions.

### Validation *returns* the detached carriers — there is no window

`_envelope_semantics` does not validate and then hand back a verdict for
somebody else to act on. It returns `(refusal, snapshot)`, where the snapshot is
a three-part structure built **during the same pass**: a tuple of fresh
package-owned `EvidenceItem` carriers, a fresh `ResourceReservation`, and the
canonical digest document. Every value in it was placed there at the moment that
value was proved acceptable.

That ordering is Jack's third-round first finding. The previous revision
validated the caller's carriers, *returned*, and then walked them a second time
to copy them — and a third time to hash them. Each extra walk was an instant in
which something could change and be installed unchecked. The window was small
and it was real: `object.__setattr__` needs no cooperation from anyone, and
another thread needs no cooperation at all.

Now the constructor installs exactly what validation returned and hashes exactly
the document validation built.

> **This claim was false when round three made it, and § 17 records how.** It
> was true of the *constructor* and of the evidence and reservation; it was not
> true of the executor, which went on re-reading `issued_ns`, `deadline_ns`,
> `max_result_bytes` and every provenance field off the envelope — with two
> caller-supplied callables running in between. It is true now, of all three
> consumers, and a control reads it off the AST rather than off the prose.

A caller who keeps a reference to what they passed in holds an object the
envelope no longer contains. Controls assert this by *identity*, not equality —
equality would pass while the envelope still held the very object the caller
could reach.

**Exact integers only.** Every declared limit is checked with
`type(value) is int` **before** any comparison or representation, so `True`,
every `int` subclass, and every foreign object with `__index__`, `__lt__` or
`__gt__` is refused without its hooks running.

**No caller-owned mutable object survives into an accepted envelope.** Evidence
is a tuple of frozen items over immutable `bytes`; the schema is immutable
`bytes`; required keys are a tuple of `str`; the reservation is frozen. The
sequences a caller passes are read exactly once, into a container this package
owns, and their exact type is checked first.

## 4. The declared loopback endpoint — validated, not resolved

`validate_loopback_endpoint` accepts exactly
`http://<numeric-loopback>:<port>/v1`, where the host is a canonical dotted
quad in `127.0.0.0/8` or the bracketed literal `[::1]`, and the port is a
canonical decimal 1–65535.

Refused, each with its own token: any scheme but lowercase `http://`; user
information; a query or fragment; percent-encoding anywhere in the string; DNS
names including `localhost` and `*.localhost`; `0.0.0.0`; every non-loopback
address; ambiguous numeric spellings (`127.1`, `2130706433`, `0x7f000001`,
`0177.0.0.1`, `127.00.0.1`, `127.0.0.1.`); IPv6 spellings other than `[::1]`,
including the long form `[0:0:0:0:0:0:0:1]` and the mapped
`[::ffff:127.0.0.1]`; a missing port; a port with a leading zero, a sign, or
non-ASCII digits; and any path but exactly `/v1`.

Non-ASCII digits are worth naming. `int("١٢")` is `12`, and
`str.isdigit()` returns `True` for those characters, so a port written in
Arabic-Indic digits parses to an ordinary number. Every character is checked
against an explicit ASCII set before any conversion runs.

The parser is hand-written string slicing, not `urllib.parse`, for the reason
`registry._host_of` gives: this layer must keep importing nothing that can
perform I/O. A control asserts, from each module's own AST, that neither V3A
module imports `socket`, `urllib`, `http`, `ssl`, `subprocess`, `os`, `sys`,
`threading`, `ctypes`, `psutil`, or any SDK.

**Two loopback checks now exist, and that is deliberate.** OMI-V1's
`registry._is_loopback` classifies the host of an already-constructed backend
and accepts `localhost`; OMI-V3A asks a stricter question about declared text.
A control asserts the containment rather than duplicating either check.

> **This validates declared text and nothing more.** An opaque backend factory
> handed to `structured_exchange_adapter` could target another host entirely.
> Proving where a real adapter connects is live-adapter work under separate
> authority.

## 4a. The clock ceiling

Every clock reading OMI-V3A accepts, every deadline it derives, and every
elapsed duration it records must lie in `[0, MAX_CLOCK_NS]`, where
**`MAX_CLOCK_NS = 2**63 − 1 = 9 223 372 036 854 775 807`** nanoseconds — the
natural range of a 64-bit nanosecond clock, about 292 years. The value is
imported from `observation_receipt.py` and captured into a closure cell by
every check that uses it, so rebinding the name is inert.

The bound exists for a specific failure. An exact `int` has no width in Python,
so a clock returning `10**5000` produced a perfectly ordinary envelope and a
perfectly ordinary receipt — and then `json.dumps` raised
`ValueError: Exceeds the limit (4300 digits) for integer string conversion`
when the receipt was serialised. A magnitude that cannot be represented inside
the documented receipt bound is refused where it enters, not discovered where
it is written.

**A clock that raises is refused, not propagated.** `_read_clock` catches
`Exception` and returns the fixed word `raised`, which the planner spells
`clock-raised` and the executor spells the same. No exception text, class name,
argument or representation is read, stored or rendered. `BaseException` is not
caught, so `KeyboardInterrupt` and `SystemExit` still propagate.

> **One narrowing, stated rather than hidden.** A clock that somehow performed
> I/O and raised OMI-V1's `HermeticViolation` would be *refused* rather than
> failing the run loudly. A clock is not permitted to perform I/O, so that is a
> caller error rather than a breach of the boundary this package guards. The
> hermetic guarantee that matters lives on the **exchange** path, which is not
> caught anywhere. A single control pins both halves together.

## 5. Attested, not verified

`ResourceReservation` declares CPU cores, memory, and optionally GPU memory —
exact ints, bounded, positive, with `None` meaning *no GPU reservation is
declared* and zero refused so the two cannot be confused. It computes its own
digest, and every consumer re-derives that digest rather than trusting it.

`execute_observation` refuses unless an injected `ReservationDecision`
(a) is exactly that type, (b) still holds its accepted field types — checked
before `satisfied` is read in a boolean context, so a tampered value's
`__bool__` never runs — (c) carries the digest of *this* reservation **as
recomputed from its current fields**, and (d) reports `satisfied=True` as an
exact `bool`.

> **OMI-V3A inspects nothing.** It reads no CPU count, no memory figure, no GPU
> state, no process list, no service, and no concurrent workload. What it
> verifies is a **checker's or operator's attestation** — `"operator-asserted"`
> or `"checker-asserted"`. It is not evidence that the resources were
> available.
>
> A control asserts this directly by planning an observation whose reservation
> nothing on the machine could satisfy and watching it succeed. If that control
> ever starts failing, something in this package has begun measuring the host.

**Which party attested is carried into the receipt, not collapsed.**
`ObservationReceipt.reservation_attestation` holds the exact token when a
reservation was evaluated and `None` when it was not, and the two are enforced
to imply one another. Rendering `operator-asserted` and `checker-asserted`
identically would erase the only thing that says *whose* claim an operator is
being asked to rely on; a control asserts two otherwise-identical receipts
differ in their serialised bytes.

Folding@home and BOINC remain senior per the inception note § 6. OMI-V3A cannot
see them, cannot pause them, and cannot reprioritise them.

## 6. Execution: one invocation, one deadline, one receipt

The order is fixed:

1. the envelope's **exact type**, then **every field's exact runtime type**,
   then **every semantic constraint**, then its **re-derived digest tree**. All
   four produce a result with **no receipt**. The field check comes first so
   that no foreign `__iter__`, `__eq__`, `__ne__`, `__hash__` or `__len__` is
   ever reached. The semantics check comes *before* the digest, and is the
   correction for Jack's third second-round finding: **the digest is unkeyed**.
   It is a pure function of the envelope's own public fields, computed by a
   function this package exports, so anyone able to mutate a field can
   recompute and reinstall it. Digest equality establishes *self-consistency*,
   never *validity* — and the previous revision treated the two as the same
   thing, executing resealed envelopes that carried an unsupported dialect, a
   DNS endpoint, an over-limit reservation, or evidence that was no longer
   UTF-8;
2. `exchange` callability;
3. the first clock reading: callable, non-raising, exact `int`, in range, and
   not earlier than `issued_ns`;
4. the **deadline**. Already passed → `void`, the exchange never invoked, the
   reservation recorded `not-evaluated`. The deadline instant itself counts as
   exceeded;
5. the **reservation decision** (§ 5);
6. the **exchange, at most once**, through a latch;
7. the second clock reading, then the deadline again. A deadline crossed while
   the exchange ran voids the observation **even when the exchange succeeded**,
   and the value is discarded;
8. the exchange result: exactly an `ObservationExchange` — the V3A-owned
   carrier described in § 6a — and then **OMI-V2's entire state machine**, not
   merely field types and vocabulary membership. Success implies a value, a sent
   request, a named dialect and no failure token; failure implies no value and
   *exactly one* token; a request refusal implies nothing was sent while a
   response failure implies something was; the dialect phase follows OMI-V2's
   own `is_pre_dialect_refusal`; missing indices exist exactly when the failure
   is `missing-required-key`, and increase. An *exact but incoherent* carrier —
   every field legal, the combination impossible — previously reached receipt
   construction, where the receipt correctly refused it and raised `ValueError`
   out of a function documented as total;
9. the result size — **read as an integer off the carrier**, not measured
   here. See § 6a.

**The digest re-derivation covers content, not claims about content.** Every
stored digest is written beside one recomputed from the bytes themselves, and
every digest-bearing carrier beside its own fields, so an equal-length evidence
substitution, a `schema_bytes` swap and a reservation-field tamper are all
caught.

**The exchange is invoked at most once, and there is no retry loop.** The latch
enforces it: a second call raises. A control reads the executor's own source —
with docstrings and comments stripped by AST round-trip, so prose can neither
satisfy nor defeat it — and asserts exactly one call site, a latch guarding it,
and no loop of any kind.

> **What one invocation does not prove.** This is a fact about *this module's*
> call site, not a claim that an opaque SDK performs exactly one network
> attempt. Disabling and proving that is live-adapter work under separate
> authority.

**Totality, stated exactly.** `plan_observation` is total over every input.
`execute_observation` is total over every input **except an exception raised by
the injected `exchange`**, which propagates — because it matches OMI-V2, and
because OMI-V1's `HermeticViolation` must stay loud. That is the only
exception it lets past; a raising clock does not qualify (§ 4a). Removing the
executor's mapping walk (§ 6a) removed its last broad `except`, which is what
makes that statement unconditional rather than nearly true.

## 6a. Where the result is measured, and why not in the executor

Round two left one residual: when an exchange reported success, its `value` was
a `MappingProxyType`, and a proxy can wrap an *arbitrary foreign mapping*.
OMI-V2's own carrier records that there is no hook-free way to inspect what a
proxy wraps — so the executor, measuring the result, ran that mapping's
`keys`/`__getitem__`. It was bounded but not closed, and it was offered as a
trade against dropping the byte bound.

Jack rejected the trade, and he was right to: it was a false choice. The
measurement does not have to happen where the value is untrusted.

`structured_exchange_adapter` now measures it **immediately after OMI-V2
returns**, which is the one place in this package where a proxy's provenance is
knowable: it demonstrably wraps a `dict` OMI-V2 itself built from `json.loads`
under a hook that returns exact dicts. `_result_snapshot_bytes` copies that
once, walks it under bounds accepting only exact built-in JSON types, and
renders the canonical bytes. It returns `None` — never raises — for anything it
will not vouch for.

The adapter then hands back an `ObservationExchange`: OMI-V2's result paired
with those bytes. `result_bytes` is not an init field; it is `len(snapshot)`, so
a carrier cannot claim a size its own bytes do not have.

**The executor therefore never walks a mapping.** It compares an `int`. A caller
who substitutes a proxy over a hostile mapping after the carrier is built has
substituted something nothing will ever read — a control asserts the mapping's
hooks fire *zero* times on the accepted path, where round two could only assert
that nothing leaked. The byte bound is kept in full.

### What the measurement is, and is not, evidence of

`ObservationExchange` guarantees `result_bytes == len(result_snapshot)`, so a
carrier cannot claim a size its own bytes do not have. It does **not** guarantee
those bytes describe the exchange's value: an *injected* exchange builds its own
carrier and may pair a large value with a small snapshot.

That buys an attacker nothing — a caller who controls the exchange could simply
have returned a small value — but round three's wording implied a binding it
does not have. On the **canonical adapter path** the measurement is of the value
OMI-V2 produced, and a control asserts the recorded count equals the real
canonical rendering. For an injected exchange the count is that exchange's own
claim. Limitation 13.

`_result_snapshot_bytes` guards only its encoder, with named exceptions, so a
`HermeticViolation` raised by a mapping — or by anything else the exchange
touches — stays loud instead of becoming `result-not-serializable`.

## 7. The receipt

Four outcomes, kept apart because an operator who cannot tell a blown deadline
from a bad answer from a refused configuration cannot act on any of them:

| Outcome | Means |
|---------|-------|
| `observed` | the exchange ran inside the deadline and returned a usable JSON object within the declared byte bound |
| `unusable` | the exchange ran inside the deadline; OMI-V2's own token says whether the request was refused or the answer did not validate |
| `void` | the deadline was exceeded, before or during. OMI-V3A does not retry it |
| `refused` | OMI-V3A refused, for a token in `ExecutionRefusal` |

`DeadlineResult` carries a fourth token, `not-evaluated`, recording that **no
determination was completed** — so a receipt never reports `within-deadline` on
the strength of a check that did not happen.

The receipt carries a task id, an envelope digest, a schema digest, evidence
ids and digests, provenance tokens, a dialect, a reservation attestation, byte
counts, an elapsed duration, a deadline result, a reservation result, request
and response outcomes, an invocation count, missing-key **indices**, and the
schema-conformance status. It carries no evidence bytes, no prompt, no model
output, no schema content, no endpoint text, no header, no credential, no
exception text, no object representation, and no type name — structurally,
because there is no field one could occupy.

**Every bound it documents, it enforces.** `evidence_bytes`, `elapsed_ns`,
`result_bytes`, `context_ceiling_tokens`, `required_key_count`,
`exchange_invocations`, the evidence-item count and the missing-index count are
each checked against the same ceiling the envelope layer enforces. The previous
revision described them as bounded and checked only non-negativity.

Its coherence rules encode **the states the executor can genuinely emit**, not
merely field-by-field validity. A receipt will not construct if it claims an
attempted request with zero invocations; a satisfied reservation on a path that
never reached the decision; an elapsed duration without an invocation or
without a completed deadline verdict; an evidence-byte total below what its
item count implies; duplicate evidence ids; a missing-key index at or past
`required_key_count`; more missing indices than required keys; an unsatisfied
reservation recorded as anything but its own refusal; an evaluated reservation
without an attestation, or an unevaluated one with one; or — using OMI-V2's own
`is_pre_dialect_refusal` — a pre-dialect refusal that names a dialect or a
post-dialect refusal that does not.

`serialize_receipt` **writes the document its own validation produced**.
`_check_receipt` validates and builds the serialization document in one
traversal, placing each value in the document at the moment it is proved
acceptable; the serialiser renders that document and never reads the receipt
again.

Two rounds shaped this. Round two found that a receipt built honestly and then
given a secret-shaped `worker` wrote that secret into stored evidence, and added
re-validation. Round three found the re-validation was followed by a *second
read* of every field to build the document — so the fix had left a window of its
own. There is no second read now.

The checker is reached as a captured function object, not through the receipt or
even through the class's `__post_init__`: an instance attribute shadows a class
method, so a caller able to mutate a receipt could otherwise install one that
does nothing. Serialisation is deterministic and bounded: sorted keys, fixed
separators, ASCII output, refused for anything that is not exactly a receipt.
Because every field is bounded, **every accepted receipt serialises inside
`RECEIPT_MAX_BYTES`** — proved by a control that constructs the largest receipt
the carrier will accept, at every ceiling simultaneously, with the longest
identifiers OMI-V1's secret matcher will actually admit.

## 8. What was tested

Two suites, **1050 controls** (728 + 322), all passing under normal Python,
`-O`, and `-OO`.

- [`tests/test_omi_v3_observation_envelope.py`](../tests/test_omi_v3_observation_envelope.py)
  — identity, provenance, limits, duration, the clock ceiling, reservation
  carriers, the endpoint parser table, evidence, required keys, schema
  delegation, pre-plan carrier revalidation, direct-construction parity with the
  planner, carrier coherence, receipt bounds and coherence, serialisation at the
  ceiling, pickling, rebinding, and hidden-authority keyword injection.
- [`tests/test_omi_v3_observation_rehearsal.py`](../tests/test_omi_v3_observation_rehearsal.py)
  — the whole execution path inside `hermetic_guard` against in-process
  doubles: one successful observation, both deadline cases, raising and
  enormous clock readings at both reads, the reservation gate, decision-field
  tampering with hook tripwires, envelope-field and digest tampering, every
  invalid response OMI-V2 can report, attestation flow, invocation counting,
  and the no-retry structural control.

Both files carry a **non-vacuity control**: `-O` and `-OO` strip `assert`
statements, so each suite proves that a false assertion in it would still fail.
A further control asserts the production modules contain **no `assert`
statement at all**.

Hostile inputs are recorded rather than merely refused: the `str`, `int`,
`bytes`, mapping and sequence subclasses used here append to a tripwire list
when a hook runs, and the controls assert the list is **empty**. The same
technique covers tampered fields on the execution path — a digest with an
`__ne__`, an evidence container with an `__iter__`, a `satisfied` with a
`__bool__` — each asserted never to fire.

Rebinding is checked exhaustively rather than by nomination: every non-dunder
name in both modules is replaced in turn with an object that raises on call,
comparison, containment, indexing and iteration, and a fixed behavioural
signature must come back identical. The same is done for twenty-one shadowed
builtins, for the `scripts.open_model` package mirrors, and for the OMI-V2
names V3A imports.

## 9. Limitations, stated rather than discovered later

1. **Attested, not measured** — the reservation gate verifies a claim (§ 5).
2. **Declared, not resolved** — the endpoint gate validates text (§ 4).
3. **Usable, not conformant** — `schema_conformance` is `"unverified"`; a
   response with wrong types and extra keys still passes (§ 2).
4. **One call site, not one network attempt** — transport-internal retries are
   out of scope and unproven (§ 6).
5. **No tokenizer** — `context_ceiling_tokens` is carried and recorded. No
   token count is verified, and nothing here could verify one.
6. **The clock is the caller's** — OMI-V3A never reads a clock ambiently. It
   checks type, range, arithmetic and ordering against the readings it is
   handed; it does not establish that they came from `time.monotonic_ns`.
7. **A breaching clock is refused, not escalated** — the one narrowing in
   § 4a, pinned by a control in both directions.
8. **No uniqueness claim for a task id** — `new_task_id` guarantees canonical
   *form* and fixity for the life of an envelope. Not global non-reuse.
9. **Arbitrary code replacement remains out of scope**, exactly as it has been
   since OMI-V1's seventh round. Closure cells close *name rebinding*.
   Patching an attribute on a captured stdlib module, replacing a function
   object, or swapping `sys.modules` is a different threat.
10. **The hermetic guard is a guard, not a sandbox** — a double holding a
    reference captured before entry would not be stopped. It raises the cost of
    an accidental live call from zero to loud.
11. **`scripts/open_model/__init__.py`'s module docstring still enumerates only
    the OMI-V1 and OMI-V2 modules.** The authority for this work limited that
    file to exports. Recorded here rather than closed outside the fence.
12. **Nothing here attests transmission.** An injected exchange receives an
    envelope and may ignore it entirely. And on the canonical adapter path, the
    adapter hands *validated snapshot values* to a caller-supplied backend whose
    actual sending — and whose choice of endpoint — this package cannot observe.
    The receipt attests **what the executor validated**, never what any callable
    transmitted or contacted. § 18 records the double that demonstrated it.
13. **An injected exchange supplies its own measurement** — `result_bytes` is
    bound to the carrier's own snapshot bytes, not to the exchange's value.
    Truthful on the canonical adapter path; a self-report otherwise.
14. **Same-author evidence** — every control cited was written by the agent
    that wrote the code under test. Internal consistency, not independent
    acceptance. The fourth round (§ 17) was adversarial and fresh-seated, and
    it found real defects, but it was performed by the same agent lineage: it
    is stronger internal evidence, still not independent acceptance.

> Limitations 12 and 13 of the previous revision — the foreign-mapping residual
> and the trade it was said to imply against the result-byte bound — are
> **closed**, not carried forward. § 6a says how, and § 15 says why the trade
> was a false choice in the first place.

## 10. What OMI-V3A deliberately does not do

- **No live backend, no registration, no factory.** The registry still ships
  empty. `structured_exchange_adapter` binds whatever backend it is handed and
  is the boundary this package cannot see past.
- **No inventory probe.** `GET /api/tags` and `GET /api/ps` remain gated behind
  their own authorization per the inception note § 5.
- **No retry, no backoff, no queue.** A void observation is void.
- **No controller.** No worker orchestrates another, allocates a resource, or
  holds write authority.
- **No proposal or commit path.** The R/S/T quarantine boundaries in
  [`LEGACY_ORCHESTRATOR_QUARANTINE.md`](LEGACY_ORCHESTRATOR_QUARANTINE.md) are
  untouched; OMI-V3A neither imports the legacy orchestrator nor is importable
  by it.

## 11. Jack's first independent HOLD round (2026-08-24)

Twenty-four cases were demonstrated against head `e53b98f` and **all twenty-four
reproduced**. They fall into five findings, and the first three share one root
cause worth naming on its own: *an exact outer type was repeatedly mistaken for
an unaltered object.* `object.__setattr__` replaces any field on a frozen
dataclass, and three separate places trusted a carrier because
`type(x) is EvidenceItem` — or `ResourceReservation`, or `ReservationDecision` —
held.

**Finding 1 — carriers were adopted without revalidation.** An `EvidenceItem`
whose bytes were swapped for *different bytes of the same length* kept a stale
digest and was accepted as an envelope's initial state, so the receipt reported
the digest of bytes that were never sent. A `ResourceReservation` altered to
`cpu_cores=1 000 000 000` was accepted behind a digest describing two. An
evidence identifier replaced with a secret-shaped string was copied into the
envelope. **Corrected**: `plan_observation` revalidates every field and
recomputes both digests inside its one controlled traversal, with four new
refusal tokens (`evidence-id-not-safe-token`,
`evidence-content-not-exact-bytes`, `evidence-digest-not-recomputable`,
`reservation-field-not-exact-int`, `reservation-field-out-of-range`,
`reservation-digest-not-recomputable`).

**Finding 2 — direct construction did not keep its promise.** The class
docstring said direct construction "re-runs every check". It checked
`type(dialect) is str` and nothing more, so an envelope was constructible with
a secret-shaped dialect, with `schema_bytes` of `b"not json at all"`, and with
a `schema_digest` hashing nothing. **Corrected**: `__post_init__` now puts the
dialect to OMI-V2's `is_supported_dialect`, decodes and re-plans the schema
through OMI-V2 and requires the canonical re-rendering to match byte-for-byte,
requires `schema_digest` to hash exactly those bytes, and re-derives every
evidence and reservation digest. The claim is now true.

**Finding 3 — the clock could raise, and could be astronomically large.** Both
entry points documented totality; a clock raising `RuntimeError` escaped both.
A clock returning `10**5000` produced an ordinary envelope and a receipt that
`json.dumps` then refused to render. **Corrected**: `_read_clock` catches
`Exception` and returns a fixed token; `MAX_CLOCK_NS = 2**63 − 1` bounds every
reading, the derived deadline and the recorded elapsed duration. A detail worth
recording: pytest builds parameter ids with `str(value)`, so the control for
`10**5000` produced a *collection error* until given an explicit id — the
defect demonstrating itself inside the test harness.

**Finding 4 — execution-time revalidation ran supplied hooks.** Replacing
`envelope_digest` with an object carrying `__ne__` ran that hook during the
comparison; replacing `envelope.evidence` with an object carrying `__iter__`
ran that one during the digest walk; replacing `decision.satisfied` with an
object carrying `__bool__` ran that one *and let an unsatisfied gate reach the
exchange*; a tampered `attestation` was accepted and would have been recorded.
**Corrected**: `_envelope_shape_intact` and `_decision_fields_intact` prove
every field's exact runtime type by identity check before anything is iterated,
compared, hashed or truth-tested, with a new `envelope-field-not-exact-type`
refusal (receiptless, like the other two undescribable ones — there were
three at this checkpoint; a fourth joined in round three, see § 18) and a new
`reservation-decision-field-invalid`. The decision is bound to the reservation
digest **recomputed from current fields**, never the stored one.

**Finding 5 — the receipt did not enforce what it documented.** Counts were
checked for non-negativity only, so `elapsed_ns = 10**5000` constructed and
then could not serialise; evidence ids were not required distinct; a
missing-key index of 99 was accepted against a single required key; OMI-V2's
pre/post-dialect coherence was not applied; and the attestation was not carried
at all, collapsing `operator-asserted` and `checker-asserted` into an
indistinguishable satisfied claim. **Corrected**: every count is bounded
against the envelope layer's own ceiling, ids must be distinct, indices must
fall inside `required_key_count`, OMI-V2's `is_pre_dialect_refusal` is imported
and applied, and `reservation_attestation` is a carried field enforced to be
present exactly when a reservation was evaluated.

**What this round is evidence for.** Every one of the five is the same shape of
mistake the OMI-V2 rounds kept finding: *a claim in prose that the code did not
keep*. The lesson is not new and it is now recorded four times across this
package — a docstring is not a control, and an assertion covering a subset while
its wording covers the whole is worse than no assertion, because it reads as
coverage.

## 12. Repository-operations note: the `.git/HEAD` desync

During the first round, after a loop that checked out each commit in turn to
prove bisectability, `.git/HEAD` was found holding a raw SHA — detached at the
third commit — while its own reflog's most recent entry recorded the checkout
back to the branch. `.git/HEAD` and `.git/index` both carried mtimes from that
minute.

Nothing was lost: the index and the working tree both diffed empty against the
branch head, `git fsck` was clean, every local ref was intact, and the remote
ref and the PR head were already correct. It was repaired once with
`git switch`.

This is recorded as a fact about the seat rather than a theory about its cause.
The repository lives inside a OneDrive-synced directory, and this working
memory already carries a standing note that OneDrive's sync engine writes into
`.git`. The operative consequence is that git state on this seat can silently
rewind, so refs are re-verified after every GitHub write.

**Per Jack's instruction, no further metadata repair will be performed if this
recurs.** A recurrence is reported as a 🔴 stop with the exact Kev action
required, and nothing is touched.

## 13. Jack's second independent HOLD round (2026-08-24)

Twenty-one cases were demonstrated against head `310e28d` and **all twenty-one
reproduced**. Several escaped as raw `ValueError` or `UnicodeDecodeError` *out
of* `execute_observation`, which is the sharpest way of putting the round's
theme: the previous revision's totality claim was not true, and the reason it
was not true is that validation and *authority* had been confused.

**Finding 1 — direct construction skipped the strict-UTF-8 gate.** The planner
refused evidence that was not strict UTF-8; the carrier did not. An envelope
built directly with `b"\xff\xfe"` reached the adapter, whose `decode("utf-8")`
raised out of the executor. **Corrected** by making
`_envelope_semantics` the single definition of an acceptable envelope, held in
a closure cell by all three consumers. This is the second round in which the
two gates were found disagreeing; they are now one function, so there is
nothing left to disagree.

**Finding 2 — accepted envelopes retained the caller's carriers.**
`envelope.evidence[0] is caller_item` was true, as was
`envelope.reservation is caller_reservation`. Tampering was caught by the
digest, but the envelope was still holding objects a caller could reach.
**Corrected** by detaching during validation: the accepted primitive values are
copied into fresh package-owned carriers that recompute their own digests.

**Finding 3 — an unkeyed digest was treated as authority for validity.** This
is the round's most important finding. `_envelope_digest` is a pure function of
the envelope's public fields and this package exports it, so a caller who
mutates a field can reseal. Resealed envelopes carrying a secret-shaped
principal, an unsupported dialect, a DNS endpoint, an over-limit reservation,
an over-limit result bound and non-UTF-8 evidence were all **executed** — and
several then raised out of receipt construction, because the receipt correctly
refused what the executor had wrongly accepted. **Corrected** by revalidating
every semantic constraint before the digest, with the new receiptless refusal
`envelope-semantics-invalid`.

**Finding 4 — the returned exchange carrier was consumed unchecked.** Only its
outer type was verified before `ok` was read in a boolean context, `value` was
copied, and `dialect` was copied into a receipt. A tampered `ok` ran a
`__bool__` hook; a tampered `dialect` carried secret-shaped text to receipt
construction and raised. **Corrected** by `_exchange_fields_intact`, which
proves every field against OMI-V2's own imported vocabularies and predicate
before any of them is read, refusing with `exchange-result-field-invalid`.

**Finding 5 — a mutated receipt serialised.** A receipt given a secret-shaped
`worker` after construction wrote that secret into stored evidence; one given a
5000-digit `elapsed_ns` raised out of the serialiser. **Corrected** by
re-running the coherence check inside `serialize_receipt`, reached through the
class so an instance attribute cannot shadow it.

**Finding 6 — receipt coherence was incomplete.** A satisfied reservation with
zero invocations constructed, though the executor goes straight from the
satisfied gate to the latched invocation with no path between them that can
refuse. Refused and void receipts accepted a dialect, though both discard
whatever came back. **Corrected**: satisfied and attempted now imply one
another in both directions, and neither a refused nor a void receipt may name a
dialect.

**Finding 7 — an evidence-reporting error.** See § 14.

**What this round is evidence for.** Round one's lesson was *a docstring is not
a control*. Round two's is narrower and sharper: **a checksum is not an
authorisation.** An unkeyed digest answers "is this the same as it was?" and
nothing else, and every place the previous revision leaned on it to answer "is
this fit to act on?" was a place it could be walked straight through by anyone
willing to recompute it.

### The one residual, stated rather than closed

> **Superseded by round three (§ 6a), and kept as written rather than
> rewritten.** The paragraphs below described the residual accurately and
> framed closing it as a trade against the result-byte bound. That framing was
> wrong: the measurement simply did not have to happen where the value was
> untrusted. Moving it to the canonical adapter path closed the residual *and*
> kept the bound. The text stands as the record of a limitation stated more
> confidently than it had been examined.

When an exchange reports success its `value` must be exactly a
`MappingProxyType`, which closes every substitution of a different type. A
proxy can still wrap an arbitrary foreign mapping, and **OMI-V2's own carrier
records that there is no hook-free way to inspect what a proxy wraps** — so
measuring the result runs that mapping's `keys`/`__getitem__`.

Two things bound it. A foreign mapping that yields non-JSON, or that raises,
produces one fixed refusal and never an escaping exception. And a foreign
mapping that yields well-formed JSON is *indistinguishable from a legitimate
answer* — the exchange is injected, so a caller able to substitute a proxy could
equally have returned the same JSON openly. Nothing from the walk reaches the
receipt, which takes a byte count and nothing else.

Closing it entirely would mean dropping the result-byte bound, since the value
is the only place the size can be measured. That trade was not taken
unilaterally; it is recorded here as limitation 13 and offered as a decision.

## 14. Correction to this document's own evidence (finding 7)

The first-round handback and the previous PR body reported **"8/8 checks pass,
including `tripwire`"** for head `310e28d`. That was wrong. `310e28d` exposes
**seven** checks and `tripwire` is **absent**; the eight-check list including
`tripwire` belonged to the earlier head `e53b98f`, and was carried across
without being re-read.

The error is worth naming precisely because of what kind it is. Nothing about
the code was misstated — the checks that did run all passed. What was misstated
was *evidence about the current head*, reported from a stale observation of a
different one. That is the same failure this package spends its whole design
budget preventing in code: describing a thing by a record taken of some earlier
thing, without re-deriving it. The check inventory in a handback is re-read at
the head being described, and the count is taken from that reading.

No workflow file was inspected or modified in establishing this, and none is
authorised for modification. Why `tripwire` runs on one head and not another is
a property of the repository's workflow triggers and is not investigated here.

## 15. Jack's third independent HOLD round (2026-08-24)

Five gates, and one of them was a rejection rather than a defect: the residual
round two had *offered* as a trade was refused, correctly, because it was not a
trade at all.

**Gate 1 — the validation-to-detachment window.** Validation walked the
caller's carriers, returned, and then the constructor walked them again to
detach them and a third time to hash them. Anything that changed between those
walks was installed unchecked. **Corrected**: `_envelope_semantics` returns the
detached carriers and the digest document it built during the one pass, and
every consumer works from that snapshot. Nothing re-reads an envelope after
validation — a structural control asserts, from the AST with comments and
docstrings stripped, that no attribute of `self` is touched after the snapshot
comes back.

**Gate 2 — the receipt revalidation-to-rendering window.** The same shape one
layer over: `serialize_receipt` re-validated and then re-read every field to
build the document it wrote. **Corrected**: `_check_receipt` validates *and*
builds the document, and the serialiser renders that. A structural control
asserts nothing is read off the receipt afterwards.

**Gate 3 — the exchange state machine.** Field types and vocabulary membership
were checked; coherence was not. A carrier reporting success with no dialect, or
failure carrying both tokens or neither, or a response failure claiming no
request was sent, is not a thing OMI-V2 can produce — yet each was accepted, and
reached receipt construction, where the receipt refused it and raised
`ValueError` out of a function documented as total. **Corrected**:
`_exchange_state_ok` enforces the whole machine, reusing OMI-V2's vocabularies
and its `is_pre_dialect_refusal` so OMI-V2 remains the authority on every value.

> Why not re-run OMI-V2's own `__post_init__`? Because it *normalises* on the
> way through — it requires an exact `dict` value and installs a proxy — so it
> cannot be re-run against a carrier it has already normalised. Only the
> traversal is this module's; every value it consults is OMI-V2's.

**Gate 4 — the foreign-mapping residual, rejected.** Round two reported that
measuring a successful result ran an untrusted proxy's hooks, and framed
closing it as a trade against dropping the result-byte bound. That framing was
wrong, and Jack said so. The measurement never had to happen where the value was
untrusted. **Corrected**: it happens on the canonical adapter path, where the
proxy demonstrably wraps a dict OMI-V2 just built, and the executor consumes a
V3A-owned `ObservationExchange` carrying the measured bytes. See § 6a. The
executor no longer walks a mapping at all; the byte bound is kept in full; and a
control now asserts a substituted hostile mapping's hooks fire **zero** times,
where round two could only assert that nothing leaked.

**Gate 5 — hermeticity must stay loud.** Removing the executor's mapping walk
removed the broad `except Exception` that guarded it, which is what had made
`result-not-serializable` capable of swallowing a `HermeticViolation`.
`_result_snapshot_bytes` guards only its encoder, with named exceptions. A
control drives a mapping that reaches for a socket inside `hermetic_guard` and
asserts the violation propagates rather than becoming an ordinary receipt.

**What this round is evidence for.** Round one: *a docstring is not a control.*
Round two: *a checksum is not an authorisation.* Round three's is about the
shape of a fix rather than the shape of a claim — **closing a window by adding a
second check leaves the gap between the two checks.** Gates 1 and 2 were both
introduced *by round two's own corrections*: re-validating before use was right,
and re-reading afterwards put the window back a few instructions further along.
The only way to close that class of gap is for validation to *produce* the thing
that gets used, so there is no interval to exploit.

Gate 4 carries a second lesson, and it is the more uncomfortable one. A
limitation I had documented carefully, bounded honestly, and offered for review
was simply not a limitation — it was an artefact of having put the measurement
in the wrong place. Documenting a constraint well is not the same as
establishing that it exists.

## 16. Correction to the previous handback's `.gitignore` claim

The round-two handback described `.claude/settings.local.json` as *"ignored by
`.gitignore`"*. That was wrong about the source. `git check-ignore -v` reports
the match as:

```
C:\Users\kevin/.config/git/ignore:3:**/.claude/settings.local.json
```

— Kev's **user-global Git exclude file**, not this repository's `.gitignore`,
which does not mention the path at all. The operative facts were right (the file
is untracked, never appears in `git status`, and cannot be captured by a commit
of explicit paths) but the mechanism was misattributed, and a receipt that names
the wrong mechanism is a receipt somebody could act on wrongly — for instance by
looking for the rule in the repository and concluding it had been removed.

Recorded here for the same reason § 14 records the check-count error: the
failures worth writing down are the ones where the evidence was stated more
confidently than it had been checked.

## 17. Fourth adversarial review (2026-08-25)

A fresh Kev-seat review, attacking the claim surface rather than re-running the
controls. Five named attack points; **two produced demonstrated defects, one
produced a demonstrated overclaim, and two came back clean.**

### Clean

**Adapter-path provenance.** `_result_snapshot_bytes` copies a proxy exactly
once, on the canonical adapter path. The chain was traced end to end and probed
with tampering backends: `request_structured_json` builds the value from
`validate_structured_output`, which parses an exact `str` payload with
`json.loads` under a hook returning exact dicts, and `StructuredExchange`
re-wraps a fresh copy. No backend can place a foreign mapping there. Controls
now assert this positively instead of leaving it to argument.

**The exchange state machine.** A differential over the whole small state space
— 480 combinations — put each to OMI-V2 by construction and to
`_exchange_state_ok` by inspection. Zero disagreements in either direction. That
control replaced one that only asserted the checker *held* OMI-V2's vocabularies
in cells, which shows it consults the right values, not that it draws the same
boundary.

### Defect 1 — the executor re-read the envelope after validation

Round three's claim that nothing re-reads an envelope after validation was
false for the executor. It re-read `issued_ns`, `deadline_ns`,
`max_result_bytes`, `task_id`, `authorizing_principal`, `worker`,
`schema_digest`, `context_ceiling_tokens` and `required_keys`.

The window was not a thread race. **`execute_observation` calls two
caller-supplied callables** — the clock and the exchange — so the caller gets to
run arbitrary code *inside* the interval. Demonstrated:

- a hostile clock rewrote `max_result_bytes` from 8192 to 8, and the executor
  enforced the tampered bound;
- a hostile clock rewrote `deadline_ns`, changing the outcome to `void`;
- a hostile exchange rewrote `worker` to a secret-shaped token, and receipt
  construction raised **`ValueError` out of a function documented as total**;
- the same for `task_id`.

**Corrected**: every value consumed after validation is bound once, from the
document `_envelope_semantics` produced, and `_receipt` is assembled from that
document rather than from the envelope. An AST control asserts the executor
reads no attribute of the envelope after the digest bind.

### Defect 2 — the canonical adapter sent unvalidated values

The same shape, one layer along, and worse. The adapter read the envelope when
it was *invoked* — after the clock had run. Demonstrated:

- a clock that swapped the evidence tuple made the adapter transmit
  `OTHER EVIDENCE` while the receipt recorded the digest of `the evidence`.
  The digest chain no longer described what was sent, which is the one thing it
  exists to do;
- a clock that corrupted `schema_bytes` made the adapter raise a **decoder's
  exception, message and all**, out of package-owned code.

**Corrected in two steps.** The adapter now validates the envelope it is handed
and sends only values from that validation, refusing an invalid one with a fixed
non-disclosing message. And the executor hands the exchange a **package-owned
envelope rebuilt from the snapshot**, not the caller's object — so on the
the adapter cannot be desynchronised from what was validated, and a control
asserts the caller's envelope never appears in the executor's tail at all. What
that does **not** establish is transmission — see finding 2 in § 18.

> An *injected* exchange may still ignore the envelope and send whatever it
> likes. That is what injecting one means, and no receipt can claim otherwise.
> Limitation 12 states it.

### Defect 3 — a structural control that was not structural

Both AST controls split the source text and searched for `self.field` /
`receipt.`. A probe fed each a source that had moved the read behind a helper —
`_helper(self)`, `_reread(receipt)` — and both controls passed while the mutable
object was still handed on. They were not vacuous, but they proved something
about spelling rather than about structure.

**Corrected**: both now parse the function, take the statements after the
marker, and walk them for `Name` nodes. A non-vacuity control feeds the
predicates the same synthetic sources the probe used and requires them to
reject both.

### What this round is evidence for

Rounds one to three were about claims outrunning code, checksums mistaken for
authorisations, and fixes that left the gap between their own two checks. This
one adds: **an interval is only safe if you know whose code runs inside it.**
Every defect here came from treating "after validation" as an instant, when the
executor deliberately calls out to caller-supplied code twice in the middle of
it. Round three closed the windows it could see between its own statements and
did not ask what ran between them.

### Provenance of this round

Performed in a fresh Kev seat, adversarially, reproducing before fixing and
adding a regression for every demonstrated defect. It was **not** independent
acceptance: the same agent lineage wrote the code, the controls, and this
section. It is stronger internal evidence than a re-run of existing controls,
and it is still internal evidence.

## 18. Fifth round (2026-08-25)

Three findings, reproduced independently with in-process doubles before any
change: one code defect upstream in OMI-V2, one overclaim, and three narrower
claim/code contradictions.

### Finding 1 — OMI-V2 trusted a mutated exact completion

`request_structured_json` checked that the backend returned an exact
`StructuredCompletion` and then **read its fields without re-checking them**. A
backend is caller-supplied code, `StructuredCompletion` is frozen, and freezing
is not sealing. Reproduced through the canonical V3A adapter:

- `ok` replaced with an object whose `__bool__` raises → **the hook ran** inside
  `request_structured_json`, and `RuntimeError` escaped the adapter;
- `response` replaced with an object whose `.text` is a raising property → **the
  property ran**, and `RuntimeError` escaped;
- `dialect` replaced with a secret-shaped string → `StructuredExchange`
  construction raised `ValueError`, which escaped;
- `ok = 1` and `response_format_sent = False` on a success → **silently
  accepted**, producing an `observed` result from an incoherent completion.

**Corrected** in `scripts/open_model/structured_exchange.py`.
`_completion_state_ok` mirrors the carrier's own coherence rules — using the
carrier's own imported vocabulary and both of its predicates — and is applied
before any field is read. All four hook and escape cases, and every incoherent
state, now land on the existing closed token
`backend-not-structured-capable`. No new token was invented, and **no exception
is caught**: a raising backend still raises, and `HermeticViolation` still
propagates, both pinned by controls.

This is the fifth appearance of one pattern: *a frozen carrier's exact outer
type is not evidence that its fields remain as constructed.* It has now been
found in the envelope, the reservation decision, the receipt, the OMI-V2
exchange result, and the OMI-V2 completion.

### Finding 2 — canonical transmission faithfulness was overclaimed

Round four wrote that "on the canonical path what is transmitted is what was
recorded". That is not establishable. The adapter hands **validated snapshot
values** to a caller-supplied backend; what that backend transmits, and which
endpoint it contacts, is not observable from here. A double demonstrated it:
received `the evidence`, chose to send `OTHER EVIDENCE`, returned a valid
completion, and the receipt still recorded the original digest.

The earned claim, and the one now made everywhere: **the canonical adapter hands
the backend values derived from the validated snapshot; the receipt attests what
the executor validated, and cannot attest what any backend actually transmitted
or contacted.** Limitation 12 covers both the injected exchange and the injected
backend behind the canonical adapter. A control asserts the too-strong wording
is absent from the document, the module, and the suite.

### Finding 3 — three claims that outran the code

1. `plan_observation` said "never raises". `_read_clock` catches `Exception`
   deliberately and not `BaseException`, so a clock raising `KeyboardInterrupt`
   propagates. The claim is narrowed to ordinary exceptions and the boundary is
   stated. `BaseException` is **not** caught, and should not be.
2. `_envelope_semantics` said "total over any envelope" while
   `_envelope_semantics(None)` raises `AttributeError`. Its contract is now
   qualified — total over any *validated exact* `ObservationEnvelope` — and the
   control renamed to match. Deliberately **no** exact-type refusal was added:
   both public callers already gate on type, and a second gate here would be a
   second authority on what an envelope is.
3. `ObservationResult` said "the three" receiptless failures while
   `UNDESCRIBABLE_REFUSALS` holds four. Corrected, with a note saying when the
   fourth joined.

### On historical text

§ 13's "receiptless, like the other two undescribable ones" was **true when it
was written**, at a checkpoint where there were three. It is annotated in place
rather than rewritten. A correction log that edits its own past is not a
correction log.

### Provenance

Findings supplied by Jack as evidence and reproduced independently before any
change, in a fresh Kev seat, by the same agent lineage that wrote the code.
Not independent acceptance.
