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
input, fail closed) and echoed in the link as `reader_bounds`. The log
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
- `evaluation`, `lab` — no public validator exists; only the schema
  identifier and the exact link fields consumed are checked, and the
  manifest says so: `validation: "schema_identifier_only"`.
- `log` — not JSON; it enters the stack only through
  `read_dominant_sequence`; the manifest records both the raw-byte hash
  and the accepted-sequence hash (`validation: "sequence_reader"`).

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
chunks (the log is never materialized whole). Justification: NP1
ingests at most `MAX_ROWS_DEFAULT` = 100,000 physical records per run
and observer-emitted rows (single-line JSON, one generation plus at
most 16 token-count keys) are well under 170 bytes, so 16 MiB covers
every default-bounds observer-emitted log. **This is deliberately not
a universal-compatibility claim**: a log recorded under raised
`--max-rows`/`--max-line-bytes` settings may exceed the ceiling and is
refused fail-closed — NP8 packages a documented subset of what NP1/NP6
can, in the extreme, ingest. Tested at the exact limit, limit+1, and
with a valid >1 MiB log whose sequence link verifies.
Deterministic sorted-key serialization, fixed vocabularies, no
timestamps, no random identifiers, no absolute paths; byte-identical
across repeated runs; manifest order is the fixed role order regardless
of invocation order.

## Write boundary

Default output is **stdout**. `--output` must resolve inside the
primary input's directory (first provided role in the fixed order),
never inside the repository `data/` tree, and never on a path aliasing
**any** input — by resolved path and by file identity
(`os.path.samefile`; existing hard links included), with the same
validation-time semantics and documented residual race as the NP6 lab.
Files are written as raw UTF-8 bytes (LF-only).

## CLI exit codes

`0` success · `2` validation failure (missing/oversized/malformed/
unknown-variant artifact, or none provided) · `4` output-path failure ·
`5` packet over the ceiling. One concise `error:` line per expected
failure, never a traceback.

## Safety

Offline; no network; imports only the four Nextness instrument modules
and stdlib (statically auditable). Reads only the files named on the
command line; never modifies an input (the whole-chain tests assert
byte-identity after every refusal path).
