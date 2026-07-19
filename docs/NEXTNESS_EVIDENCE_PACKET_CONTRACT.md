# Nextness Evidence Packet Contract (NP8)

**Module**: `scripts/nextness_evidence_packet.py` · **Tests**: `tests/test_nextness_evidence_packet.py`
**Schema**: `nextness-evidence-packet-v1` · **Status**: packaging and provenance verification only — no new metric

## What this is

A compact, offline **audit manifest** over up to eight recorded
Nextness artifacts (one per role: `report`, `receipts`, `evaluation`,
`lab`, `protocol`, `log`). For each artifact it records the schema
identifier, byte length and SHA-256; and it **verifies the provenance
links the v1 schemas themselves record**:

| Link | Recorded by | Verified against |
|---|---|---|
| `evaluation_report_sha256` | NP5 evaluation (`artifacts.report.sha256`) | the report file's bytes |
| `evaluation_receipts_sha256` | NP5 evaluation (`artifacts.receipts.sha256`) | the receipts file's bytes |
| `lab_protocol_sha256` | NP6 lab report (`input.protocol_sha256`) | the protocol file's bytes |
| `lab_sequence_sha256` | NP6 lab report (`input.sequence_sha256`) | the log's accepted dominant-token sequence, recomputed through NP1's own bounded reader **with the lab's recorded `max_rows`/`max_line_bytes`** |

A checkable link is `verified` or `broken` (byte-level hash
comparison, both hashes reported). A link whose counterpart was not
provided is typed `not_computable` / `counterpart_absent`; a link the
recording artifact did not embed (e.g. an evaluation produced without
receipts) is `not_computable` / `link_not_recorded` — **absence is
never failure and never invention**.

**Recorded reader bounds.** A lab produced under non-default
`--max-rows`/`--max-line-bytes` accepted a *different* sequence than
the defaults would, so the sequence link recomputes with the lab's own
recorded `config.max_rows`/`config.max_line_bytes` — exact-type
validated against the same acceptance ranges NP1/NP6 enforce (bool,
float, string, negative, zero and out-of-range values are malformed
input, fail closed; `max_line_bytes` is additionally capped
DEFENSIVELY at extraction to [1, 16 777 216] — the shared
`MAX_LINE_BYTES_CEILING` — even if upstream validation changes later,
so the reader replay can never receive an index-overflowing bound)
and echoed in the link as `reader_bounds`. The log
manifest entry's own `sequence_sha256` uses NP1 defaults, with the
bounds echoed as `sequence_bounds`. No lab ⇒ no bounds are invented.

**`provided` flags are exact builtin bools.** In
`evaluation.artifacts.<role>.provided`: `true` requires and verifies
the recorded sha256; `false` is typed `link_not_recorded`; **every
other value** (1, 0, "true", "false", null, [], {}) is malformed input
and raises — a truthy non-bool can never silently suppress
verification.

## Honest validation depth (recorded per artifact)

- `report`, `receipts`, `protocol` — validated through the **existing**
  validators (`nextness_evaluator.validate_report` /
  `validate_receipt_series`, `nextness_replay_lab.load_protocol`);
  manifest records `validation: "full"`. Nothing is duplicated.
- `evaluation`, `lab` — validated through NP9's **public structural
  validators** (`nextness_artifact_validation`); the manifest now
  records `validation: "full"` because the complete public structural
  schema is actually covered. Each JSON artifact is still parsed
  exactly once (the validators take the already-parsed object).
  Malformed consumed fields therefore fail closed at validation and
  can never suppress link verification.
- `log` — not JSON; it enters the stack only through
  `read_dominant_sequence`; the manifest records both the raw-byte hash
  and the accepted-sequence hash (`validation: "sequence_reader"`).

**Self-check**: the emitted packet is validated against NP9's
`validate_evidence_packet` before serialization. A failure there is an
**internal programming/contract failure, not user input**: it is
re-raised as a plain `RuntimeError` — retained as a **stable
internal-failure classification independent of exception ancestry**.
Both a raw `ArtifactValidationError` and the converted `RuntimeError`
lie outside `main()`'s typed `PacketInputError` catch, so the internal
failure propagates loudly either way. Malformed **external** artifacts
are wrapped as `PacketInputError` at validation and keep the concise
exit-2 contract.
Provenance links remain independently recomputed by this module;
structural validation never converts a broken link into success.

Unknown schema variants, malformed link fields, duplicate JSON keys and
artifacts failing their validators are all rejected **fail-closed**.

## Non-claims (load-bearing, embedded in every packet)

No scoring, ranking, recommendation, tuning, action, model invocation
or service contact (no such structure exists in the output — key-walk
tested). A `not_computable` link says which artifacts were provided,
not anything about integrity. No awareness, consciousness,
phenomenology or biological-equivalence claim.

## Bounds and determinism

≤ `MAX_PACKET_ARTIFACTS` (8) artifacts (the one-per-role rule caps
practice at six); every JSON input read through a hard pre-parse bound
(`MAX_INPUT_BYTES`, 1 MiB), **parsed exactly once** (spy-tested);
output checked against a **64 KiB fail-closed ceiling**.

**Log size contract** (`MAX_LOG_BYTES`, 16 MiB): the raw log gets its
own role-specific ceiling — size-checked via `stat` **before any
read**, re-enforced during reading, and hashed in fixed-size 64 KiB
chunks (the log is never materialized whole). **16 MiB is NP8's own
explicit packaging/work ceiling** — it keeps the hash and the bounded
sequence read cheap and testable. It is **not derived as coverage of
NP1's defaults**: observer rows carry more than a generation and token
counts (timestamps, filenames, lattice shape, sampling information,
metrics, diagnostics, a nested budget block), so **no claim is made
about what fraction of real or default-configuration logs fit** until
that is measured. NP8 intentionally accepts raw logs no larger than
16 MiB; otherwise-valid larger logs are refused fail-closed — a
documented subset of what NP1/NP6 can ingest. Tested at the exact
limit, limit+1, and with a valid >1 MiB log whose sequence link
verifies.
Deterministic sorted-key serialization, fixed vocabularies, no
timestamps, no random identifiers, no absolute paths; byte-identical
across repeated runs; manifest order is the fixed role order regardless
of invocation order.

**Hook-free refusal diagnostics (DIRECT Python API included).** A refusal
never reads an attribute of the rejected value or of its class — in
particular never `type(value).__name__`, since `__name__` is an
overridable **metaclass** property whose getter would run
caller-controlled code from inside error formatting and escape the typed
`PacketInputError`. Builtin type names come from a literal identity
table; anything else is described as `non-builtin value`. Public
CLI/artifact messages, exception types and range messages are
unaffected: `json.loads` yields only builtins, so every reachable-lane
diagnostic is byte-identical to before.

**Exact-string field lookup.** A required field is fetched from a
proven-exact builtin `dict` by **item iteration only**: an unproven key
is never hashed, compared, stringified or represented, only exact
builtin `str` keys are compared against the field name, and the matched
value is taken **straight from the iteration** — never from a second
subscript, which would re-enter the hash table and could meet a
colliding hostile key. This is a **soundness** boundary, not only a hook
boundary: the previous `field not in container` / `container[field]`
pair hashed the field name and compared it against whatever shared its
bucket, so a non-string key whose `__hash__` collided with a required
name had its `__eq__` invoked — and an `__eq__` returning `True` let
that hostile key **satisfy the required field and supply its own value
as the field's content**. A foreign key can now never satisfy a
required string field, and a container holding both a foreign key and
the genuine string field returns the genuine value.

**Exact role-map boundary (top level).** The same class of defect existed
one level up, in the **outer role map** passed to `build_packet()` and
`validate_output_path()`. Both consumed the caller's mapping directly —
`set(paths)`, `role in paths`, `paths[role]`, `inputs[role]` and, in the
unknown-roles message, list rendering that `repr`'d every key.

**Reachability**: the **PUBLIC CLI is unaffected** — it constructs this
map itself with exact builtin `str` roles, so none of the hazards below
are reachable from the command line. They are **DIRECT-Python-API only**.

Failing-first evidence (Jack's outer-role-map audit), all reproduced
against the pre-repair tree:

| probe | pre-repair |
|---|---|
| foreign role key whose `__repr__` raises | escaped `build_packet()` as a raw `RuntimeError` |
| key colliding with `"report"`, `__eq__` → `True` | **satisfied the role and supplied its own value** — reached `_validate_role` and parsed the file |
| colliding key whose `__eq__` raises | escaped `validate_output_path()` |
| soft-colliding key in `validate_output_path()` | **accepted**, supplying the primary input that anchors the whole write boundary |
| `dict` **subclass** with armed iteration hooks | `__iter__` executed in `build_packet()`; accepted outright by `validate_output_path()` |

Both entry points now normalize through **one shared private boundary**
before any membership test, lookup or key rendering. It accepts only an
exact builtin `dict` (refusing anything else generically, naming no
supplied type), inspects a rejected mapping or key no further than exact
type identity, traverses by item iteration only, admits a key solely on
exact builtin `str` identity — never hashing, comparing, stringifying or
representing a foreign key — and returns a **fresh exact dict** that is
the only thing later membership, lookup, `.get()` and primary-role
selection ever see. A foreign key is **rejected even when a genuine role
is also present**, never silently dropped. Messages for no artifacts, the
artifact ceiling and unknown exact-string roles are unchanged, as is
behavior for valid CLI inputs and valid exact-dict direct inputs.

**Correction of record.** An earlier note accompanying the field-lookup
repair stated that it removed *"the only mechanism by which a hostile key
could raise anything here."* That claim was **too strong**: it accounted
for the per-container field lookup but not for this outer role map, which
remained a live DIRECT-API hole. The claim is withdrawn and superseded by
this section.

## Write boundary

Default output is **stdout**. `--output` must resolve inside the
primary input's directory (first provided role in the fixed order),
never inside the repository `data/` tree, and never on a path aliasing
**any** input — by resolved path and by file identity
(`os.path.samefile`; existing hard links included), with the same
validation-time semantics and documented residual race as the NP6 lab.
Files are written as raw UTF-8 bytes (LF-only).

**Destination boundary on operational write failure** (audited 2026-07-17;
stage-pinned in the focused tests): a failure **at or before the binary
open** — an unwritable or read-only destination, an absent or invalid
parent — preserves any existing destination byte-identically and creates
no output. **After a successful direct non-atomic open**, a later failure
may truncate the destination or leave partial output (the whole-buffer
write truncates on open, so a failed write leaves an empty file). A
**close-time failure** may leave the complete canonical packet bytes
in place even though the run reports the operational-failure exit —
a present file does not imply a successful run. Supplied-input
preservation on these lanes is bounded by the existing validation-to-write
(TOCTOU) non-claim. No atomic-write behavior is provided or implied.

## CLI exit codes

`0` success · `2` validation failure (missing/oversized/malformed/
unknown-variant artifact, or none provided) · `4` output-path failure ·
`5` packet over the ceiling. One concise `error:` line per expected
failure, never a traceback.

**Typed input boundary (evidence-packet pilot)**: the exit-2 catch is
exactly the typed `PacketInputError` — **not arbitrary `ValueError`**.
Every established input failure already arrives as `PacketInputError`
through the existing wrapping boundaries (bounded JSON loading; the
`EvaluatorInputError`/`LabInputError` conversion; the NP9
`ArtifactValidationError` conversion), so **established input failures
retain byte-identical messages and exit 2**. A plain `ValueError` — like
any exception outside the documented catch classes — now **propagates**
through public `main()` (test-pinned beside the standing
sentinel-`RuntimeError` pin), consistent with the self-check's existing
`RuntimeError` re-raise. No raise was retyped, no new exception class
was introduced, no validator behavior changed; `build_packet`'s
direct-Python behavior and its existing typed failures are unchanged.
This is a packet-only decision; no family-wide convention is implied.

## Safety

Offline; no network; imports only the four Nextness instrument modules
and stdlib (statically auditable). Reads only the files named on the
command line; never modifies an input (the whole-chain tests assert
byte-identity after every refusal path).
