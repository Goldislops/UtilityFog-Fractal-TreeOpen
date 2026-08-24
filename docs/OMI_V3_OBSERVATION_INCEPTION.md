# OMI_V3_OBSERVATION_INCEPTION.md — the OMI-V3A observation envelope

> **Status**: implemented, inert, and hermetic. Modules
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
| Is this dialect supported? | OMI-V2 `is_supported_dialect`, via `plan_structured_request` |
| Is this schema acceptable, and what is its detached snapshot? | OMI-V2 `_validated_snapshot`, via `plan_structured_request` |
| What wire shape does this dialect need? | OMI-V2 `build_response_format` |
| Did the response parse as a usable JSON object? | OMI-V1 `validate_structured_output`, via OMI-V2 `request_structured_json` |
| What may a request refusal say? | OMI-V2 `REFUSAL_TOKENS` / `EXCHANGE_REFUSALS`, imported |
| What may a response failure say? | OMI-V1/V2 `RESPONSE_FAILURES`, imported |
| Is this identifier safe to store? | OMI-V1 `is_safe_token` |
| Is the network blocked during a rehearsal? | OMI-V1 `hermetic_guard` |

`PlanRefusal` is **composed** from OMI-V2's `StructuredRefusal` exactly as
`ExchangeRefusal` is, so a dialect or schema token added to OMI-V2 arrives here
without an edit. `tests/test_omi_v3_observation_envelope.py` asserts the two
V3A vocabularies are disjoint from all three OMI-V2 vocabularies, that no V3A
token begins `dialect-` or `schema-`, that the four dialect names appear
nowhere in V3A source, and that the planner's captured `plan_structured_request`
and the adapter's captured `request_structured_json` **are** OMI-V2's objects
rather than lookalikes.

One helper is imported rather than copied: `_restore_identity`, the eight-line
function that gives a factory-built class its module-level `__qualname__` back
so it can pickle. A third verbatim copy was the alternative. The import is
intra-package and pinned by a control asserting identity.

`schema_conformance` remains closed to the single token `"unverified"`. Nothing
in OMI-V3A compares a response against the schema that was sent, because
nothing below it does and this layer adds nothing that could.

## 3. The envelope contract

`plan_observation` is keyword-only, total over every input, and never raises.
It returns an `ObservationPlan` carrying either an `ObservationEnvelope` or one
closed token. The order is fixed and the first refusal wins.

| Property | How it is enforced |
|----------|--------------------|
| **Immutable task identity** | `new_task_id()` generates a canonical UUIDv4 from a closed factory; `is_canonical_uuid4` accepts only the lowercase hyphenated 36-character form with version nibble `4` and variant in `{8,9,a,b}`. Braced, URN, uppercase and unhyphenated spellings are refused rather than normalised. |
| **Input hashes** | Every `EvidenceItem` holds exact built-in `bytes` and computes its own SHA-256 in `__post_init__`. `digest` is not an init field, so a caller cannot supply one, and there is no window between the check and the hash. `bytearray`, `memoryview` and `bytes` subclasses are all refused. |
| **Bounded context** | Nothing ambient is read. Every evidence item is explicit, bounded per item and in total, against both a module ceiling and the caller's own declared bound, and must decode as strict UTF-8. |
| **Bounded result** | `max_result_bytes` bounds the canonical rendering of the accepted structured object; OMI-V2's `max_chars` bounds the payload string before it parses. |
| **Deadline** | Derived as `issued_ns + duration_ns` from an exact-`int` bounded duration and one reading of a caller-supplied monotonic clock. |
| **Provenance** | An authorizing-principal token and a worker token, both `is_safe_token`, both copied into the receipt. |
| **Declared loopback endpoint** | § 4. |
| **Resource reservation** | § 5. |

**Exact integers only.** Every declared limit is checked with
`type(value) is int` **before** any comparison or representation, so `True`,
every `int` subclass, and every foreign object with `__index__`, `__lt__` or
`__gt__` is refused without its hooks running. Zero, negatives and over-ceiling
values are refused separately, with their own token.

**No caller-owned mutable object survives into an accepted envelope.** Evidence
is a tuple of frozen items over immutable `bytes`; the schema is immutable
`bytes`; required keys are a tuple of `str`; the reservation is frozen. A
caller who keeps a reference to the list, tuple or dict they passed in cannot
reach through it afterwards. The sequences they pass are read exactly once,
into a container this package owns, and their exact type is checked first so a
subclass whose `__iter__` returns different elements on a second pass never
gets a second pass.

**The snapshot is built during the controlled traversal.** The schema the
envelope carries is the canonical rendering of the detached snapshot OMI-V2's
`_validated_snapshot` produced — a structure containing exactly the values it
inspected, because validation and copying are one traversal there. Key order is
canonicalised so the digest is comparable; JSON object member order is not
semantically significant.

**Refusal reasons carry no caller text.** Every token is an inlined literal
from a closed set. A secret-shaped principal is refused as
`principal-not-safe-token`, and the secret appears nowhere.

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
Arabic-Indic digits parses to an ordinary number. Every character is therefore
checked against an explicit ASCII set before any conversion runs.

The parser is hand-written string slicing, not `urllib.parse`, for the reason
`registry._host_of` gives: this layer must keep importing nothing that can
perform I/O. A control asserts, from each module's own AST, that neither V3A
module imports `socket`, `urllib`, `http`, `ssl`, `subprocess`, `os`, `sys`,
`threading`, `ctypes`, `psutil`, or any SDK.

**Two loopback checks now exist, and that is deliberate.** OMI-V1's
`registry._is_loopback` classifies the host of an already-constructed backend
and accepts `localhost` and lenient dotted quads, which is the right answer to
the question it asks. OMI-V3A asks a stricter question about declared text. A
control asserts the containment rather than duplicating either check: every
endpoint V3A accepts has a host OMI-V1 also calls loopback, and the containment
is strict.

> **This validates declared text and nothing more.** It is not a claim about
> where a request goes. An opaque backend factory handed to
> `structured_exchange_adapter` could target another host entirely. Proving
> where a real adapter connects is live-adapter work under separate authority.

## 5. Attested, not verified

`ResourceReservation` declares CPU cores, memory, and optionally GPU memory —
exact ints, bounded, positive, with `None` meaning *no GPU reservation is
declared* and zero refused so the two cannot be confused. It computes its own
digest.

`execute_observation` refuses unless an injected `ReservationDecision`
(a) is exactly that type, (b) carries the digest of *this* reservation, and
(c) reports `satisfied=True` as an exact `bool`. A decision about some other
reservation is not a decision about this one, however satisfied it says it is.

> **OMI-V3A inspects nothing.** It reads no CPU count, no memory figure, no GPU
> state, no process list, no service, and no concurrent workload. What it
> verifies is a **checker's or operator's attestation** — `"operator-asserted"`
> or `"checker-asserted"` — and what the receipt records is that a named party
> made a claim. It is not evidence that the resources were available.
>
> A control asserts this directly by planning an observation whose reservation
> nothing on the machine could satisfy and watching it succeed. If that control
> ever starts failing, something in this package has begun measuring the host,
> which is outside its authority.

Folding@home and BOINC remain senior per the inception note § 6. OMI-V3A cannot
see them, cannot pause them, and cannot reprioritise them.

## 6. Execution: one invocation, one deadline, one receipt

The order is fixed:

1. the envelope's **exact type**, then its **re-derived digest**. Both produce a
   result with **no receipt** — nothing else may describe an envelope it could
   not first trust;
2. `exchange` and `clock` callability;
3. the first clock reading: exact `int`, not earlier than `issued_ns`;
4. the **deadline**. Already passed → the observation is `void`, the exchange is
   never invoked, and the reservation is recorded `not-evaluated` because it
   never was. The deadline instant itself counts as exceeded;
5. the **reservation decision** (§ 5);
6. the **exchange, at most once**, through a latch;
7. the second clock reading, then the deadline again. A deadline crossed while
   the exchange ran voids the observation **even when the exchange succeeded**,
   and the value is discarded — a late answer is not an answer;
8. the exchange result's exact type, then OMI-V2's own three-state outcome;
9. the result size, measured on the canonical rendering of what OMI-V2 accepted.

**The digest re-derivation covers content, not claims about content.** An
earlier revision of `_envelope_digest` read each item's *stored* digest and
`len(content)`, so replacing an item's bytes with different bytes of the same
length changed nothing it looked at — and the re-derivation that exists to
catch tampering would have agreed nothing had happened. The same held for
`schema_bytes` against a stored `schema_digest`, and for a reservation's fields
against its stored digest. Every stored digest is now written beside one
recomputed from the bytes themselves, and every digest-bearing carrier beside
its own fields. `tests/test_omi_v3_observation_rehearsal.py` carries the
equal-length substitution control that would have caught the original defect.

**The exchange is invoked at most once, and there is no retry loop.** The
latch enforces it rather than documenting it: a second call raises. A control
reads the executor's own source — with docstrings and comments stripped by AST
round-trip, so prose cannot satisfy or defeat it — and asserts exactly one call
site, a latch guarding it, and no loop of any kind in the function.

> **What one invocation does not prove.** This is a fact about *this module's*
> call site. It is not a claim that an opaque SDK or HTTP client performs
> exactly one network attempt; transports retry internally. Disabling and then
> proving that is live-adapter work under separate authority.

**An exception from the injected exchange propagates.** It is not caught into a
receipt, for two reasons. It matches OMI-V2, where `request_structured_json`
documents that transport errors propagate. And OMI-V1's `HermeticViolation`
must stay loud: folding an exchange exception into a tidy receipt would turn a
hermetic breach — a double that reached the network — into a record of a failed
observation, which is exactly the failure mode the guard exists to prevent. A
control asserts the propagation for both a socket attempt and a `urlopen`
attempt.

**Result sizing is honest about what it measured.** The byte bound is applied by
OMI-V3A to the canonical rendering of the object OMI-V2 accepted; the char
bound is applied by OMI-V2's validator to the payload string. Neither bounds
how many bytes a transport read before either of them saw anything, and
OMI-V3A has no transport to ask.

## 7. The receipt

Four outcomes, kept apart because an operator who cannot tell a blown deadline
from a bad answer from a refused configuration cannot act on any of them:

| Outcome | Means |
|---------|-------|
| `observed` | the exchange ran inside the deadline and returned a usable JSON object within the declared byte bound |
| `unusable` | the exchange ran inside the deadline; OMI-V2's own token says whether the request was refused or the answer did not validate |
| `void` | the deadline was exceeded, before or during. OMI-V3A does not retry it |
| `refused` | OMI-V3A refused, for a token in `ExecutionRefusal` |

`DeadlineResult` carries a fourth token, `not-evaluated`. It is not a fourth
place the deadline could fall — it records that **no determination was
completed**, because the execution refused before a usable clock reading
existed, or the reading after the exchange was unusable. It exists so a receipt
never reports `within-deadline` on the strength of a check that did not happen.

The receipt carries a task id, an envelope digest, a schema digest, evidence
ids and digests, provenance tokens, a dialect, byte counts, an elapsed
duration, a deadline result, a reservation result, request and response
outcomes, an invocation count, missing-key **indices**, and the schema-
conformance status. It carries no evidence bytes, no prompt, no model output,
no schema content, no endpoint text, no header, no credential, no exception
text, no object representation, and no type name — structurally, because there
is no field one could occupy.

Its coherence rules are enforced, not documented: a receipt claiming a request
was attempted while reporting zero invocations, or an observation that
succeeded while carrying a refusal, will not construct. Evidence that can lie
about itself is worse than no evidence.

`serialize_receipt` is deterministic and bounded: sorted keys, fixed
separators, ASCII output, refused for anything that is not exactly a receipt.
Determinism is a property of the function — `elapsed_ns` legitimately differs
between runs.

## 8. What was tested

Two suites, 633 controls, all passing under normal Python, `-O`, and `-OO`.

- [`tests/test_omi_v3_observation_envelope.py`](../tests/test_omi_v3_observation_envelope.py)
  — identity, provenance, limits, duration, reservation carriers, the endpoint
  parser table, evidence, required keys, schema delegation, carrier coherence,
  receipt shape and serialisation, pickling, rebinding, and hidden-authority
  keyword injection.
- [`tests/test_omi_v3_observation_rehearsal.py`](../tests/test_omi_v3_observation_rehearsal.py)
  — the whole execution path inside `hermetic_guard` against in-process
  doubles: one successful observation, both deadline cases, the reservation
  gate, envelope tampering, every invalid response OMI-V2 can report,
  invocation counting, and the no-retry structural control.

Both files carry a **non-vacuity control**: `-O` and `-OO` strip `assert`
statements, so each suite proves that a false assertion in it would still fail,
rather than trusting pytest's rewriting to have happened. A further control
asserts the production modules contain **no `assert` statement at all**, so
nothing they do changes under either flag.

Hostile inputs are recorded rather than merely refused: the `str`, `int`,
`bytes`, mapping and sequence subclasses used here append to a tripwire list
when a hook runs, and the controls assert the list is **empty** — refusal by
exact-type check, before any supplied `__len__`, `__eq__`, `__hash__`,
`__iter__`, `__index__`, `keys`, `items`, `encode` or `decode` could execute.

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
   checks arithmetic, type and ordering against the readings it is handed; it
   does not establish that they came from `time.monotonic_ns`.
7. **No uniqueness claim for a task id** — `new_task_id` guarantees canonical
   *form* and fixity for the life of an envelope. Not global non-reuse, and
   not that any external system agrees the identifier names this task.
8. **Arbitrary code replacement remains out of scope**, exactly as it has been
   since OMI-V1's seventh round. Closure cells close *name rebinding*.
   Patching an attribute on a captured stdlib module, replacing a function
   object, or swapping `sys.modules` is a different threat and is not defended
   against here.
9. **The hermetic guard is a guard, not a sandbox** — OMI-V1 says so, and it is
   still true: a double holding a reference captured before entry, or reaching
   for the OS another way, would not be stopped. It raises the cost of an
   accidental live call from zero to loud.
10. **`scripts/open_model/__init__.py`'s module docstring still enumerates only
    the OMI-V1 and OMI-V2 modules.** The authority for this work limited that
    file to exports, so the two V3A modules are exported but not listed in the
    prose inventory there. It is a documentation gap, recorded here rather than
    closed outside the fence.
11. **Same-author evidence** — every control cited was written by the agent
    that wrote the code under test. Internal consistency, not independent
    acceptance.

## 10. What OMI-V3A deliberately does not do

- **No live backend, no registration, no factory.** The registry still ships
  empty. `structured_exchange_adapter` binds whatever backend it is handed and
  is the boundary this package cannot see past.
- **No inventory probe.** `GET /api/tags` and `GET /api/ps` remain gated behind
  their own authorization per the inception note § 5, and nothing here touches
  them.
- **No retry, no backoff, no queue.** A void observation is void.
- **No controller.** No worker orchestrates another, allocates a resource, or
  holds write authority. Composition of worker outputs remains a human-reviewed
  step.
- **No proposal or commit path.** The R/S/T quarantine boundaries in
  [`LEGACY_ORCHESTRATOR_QUARANTINE.md`](LEGACY_ORCHESTRATOR_QUARANTINE.md) are
  untouched; OMI-V3A neither imports the legacy orchestrator nor is importable
  by it, and adds no second route to the tuning API.
