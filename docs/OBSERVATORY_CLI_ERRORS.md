# Observatory CLI — machine-readable error contract

The Cosmic Observatory CLI (`python -m vis.observatory`) can report an
**expected** failure either as human prose or as a single JSON object. This
document specifies the JSON form, version 1.

It describes only what is implemented today. Nothing here is a forward promise.

## Two error modes

```
python -m vis.observatory [--error-format {human,json}] <command> ...
```

`--error-format` is a **global** option and must appear **before** the
subcommand. Placing it after the subcommand is itself a usage error, because
the subcommand consumes everything that follows it.

Only occurrences **before the subcommand** count — everything from the command
name onward belongs to that subcommand. A misplaced `--error-format` after the
subcommand is a usage error, and it neither overrides nor supplies a global
selection. So this still emits a JSON envelope, because JSON *was* validly
selected before the subcommand:

```
--error-format json info snap.npz --error-format human   # JSON envelope, status 2
```

Within that prefix, if the option is repeated the last occurrence wins —
argparse's ordinary behaviour. But if **any** prefix occurrence carries an
unrecognised value or is missing its value, the invocation cannot be parsed at
all, and the refusal is reported in **human** form: a format that was never
validly selected is not trusted to carry the refusal.

| | `human` (default) | `json` |
|---|---|---|
| Stream | stderr | stderr |
| Shape | `cosmic-observatory: error: <message>` | one JSON object |
| Lines the CLI writes | exactly one | exactly one |
| stdout | empty | empty |
| Exit status | unchanged | unchanged |

`--error-format human` and omitting the option produce identical output, and
human runtime-error prose, successful output and the exit statuses are all
unchanged from before this option existed.

The one thing that necessarily did change is the **help and usage displays**:
they now list `--error-format {human,json}`, as any new option would.

### The stderr contract, precisely

The CLI guarantees what it writes. It does **not** own the stream.

**Guaranteed:**

- the expected-error path writes **exactly one** JSON envelope line, and
  nothing else — no usage preamble, no traceback, no additional prose;
- stdout is empty;
- output is deterministic for identical inputs.

**Not guaranteed:** that the envelope is the only thing on stderr, or that it
is the final line. Python's `warnings` machinery, matplotlib, and the
interpreter's own shutdown notices can write to stderr before or after the
CLI does, and none of them are under its control.

**So a consumer must locate the envelope rather than parse the whole stream:**
scan stderr for a line that parses as a JSON object whose `schema` is
`utilityfog.observatory.error/1`. If more than one is present — which can only
happen when the stream carries output from something besides a single CLI
invocation — use the **last** match.

## What is *not* affected

- **`--help` is never an error.** Help stays human-readable on **stdout** with
  exit status **0**, in both modes.
- **Successful output is unchanged.** `info --json` and `doctor --json` emit
  exactly the documents they always have, on stdout.
- **Unexpected defects still propagate.** A programming error keeps its
  traceback and is never dressed up as a user error. If stderr carries no line
  matching the error schema, an internal error occurred — do not infer the
  envelope's presence from the exit status alone.

## Version-1 schema

```json
{"argument":null,"category":"usage","code":"unknown-command","command":null,"exit_status":2,"message":"unknown command 'bod'. Did you mean 'body'?","ok":false,"schema":"utilityfog.observatory.error/1","suggestion":"Did you mean 'body'?"}
```

Formatted for reading:

```json
{
  "schema": "utilityfog.observatory.error/1",
  "ok": false,
  "category": "usage",
  "code": "unknown-command",
  "message": "unknown command 'bod'. Did you mean 'body'?",
  "suggestion": "Did you mean 'body'?",
  "command": null,
  "argument": null,
  "exit_status": 2
}
```

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Always `utilityfog.observatory.error/1` in this version. |
| `ok` | boolean | Always `false`. Present so the envelope is self-describing. |
| `category` | string | `usage` or `input`. Fixes the exit status. |
| `code` | string | Stable identifier from the vocabulary below. |
| `message` | string | Human text. **Unstable — never parse it.** |
| `suggestion` | string \| null | A suggested correction, when one exists. |
| `command` | string \| null | The subcommand, when one was determined. |
| `argument` | string \| null | The option or argument at fault, when known. |
| `exit_status` | integer | `2` or `1`. Restates the process status. |

**Serialization.** Keys are sorted, separators are compact (`,` and `:`), the
document is ASCII-escaped, and it occupies one physical line followed by one
newline. Equivalent inputs produce byte-identical output.

ASCII escaping is a correctness requirement, not a style choice. `U+2028`,
`U+2029` and `U+0085` are legal unescaped in JSON strings but are line
boundaries to Python's `str.splitlines()` and to many log processors. Escaping
them keeps the one-line guarantee true for a hostile filename.

**Nullable fields are always present.** A field that vanishes when
inapplicable forces consumers to branch on key existence; `null` means "not
applicable", never "unknown".

## Category and code vocabulary

`category` fixes the exit status: `usage` → **2**, `input` → **1**.

### `usage` — the command line could not be accepted (exit 2)

| `code` | Raised when |
|---|---|
| `missing-command` | No subcommand was given. |
| `unknown-command` | The subcommand is not recognised. |
| `unknown-option` | An option is not recognised, or a value was given to a flag that takes none (`--json=x`). |
| `missing-argument` | A required argument was omitted, or an option was present without its value (`--save` with nothing after it). |
| `invalid-argument-value` | A value *was* supplied and failed validation (range, type, or choice). |
| `usage-error` | Fallback for any other usage failure. |

### `input` — the command line parsed but named something unusable (exit 1)

| `code` | Raised when |
|---|---|
| `snapshot-not-found` | The snapshot path does not exist. |
| `snapshot-wrong-path-kind` | A directory was given where a file is required. |
| `snapshot-unsupported-suffix` | The suffix is not `.npz` or `.json`. |
| `snapshot-unreadable` | The file exists but could not be decoded. |
| `animation-directory-invalid` | The animation directory is missing, is not a directory, or holds no usable frames. |
| `level-out-of-range` | A `--level` lies outside the selected axis. |
| `input-error` | Fallback for any other expected runtime failure — including a path the OS refused to examine at all. |

The three specific `snapshot-*` path codes are reported only for a path
**positively established** to be a directory, to be missing, or to have an
unsupported suffix. When the operating system refuses to examine the path —
a name past `NAME_MAX`, or one the filesystem rejects — nothing has been
established about what kind of thing it is, so the honest `input-error`
fallback is used rather than a code that would assert more than is known.

`usage-error` and `input-error` are honest fallbacks. argparse's own messages
are English prose that varies by Python version and may be localised, so
classification is deliberately conservative: an unrecognised shape is reported
as a fallback rather than guessed into a specific code a consumer might trust.

## `info --json` and `doctor --json`

These commands already speak JSON on success, so they speak it on failure too
— **even when `--error-format` was omitted**:

```bash
python -m vis.observatory info missing.npz --json     # envelope on stderr, status 1
```

The upgrade is scoped to those two commands. Every other subcommand stays
human unless `--error-format json` is given explicitly, and an explicit
`--error-format human` overrides the upgrade.

The upgrade covers **runtime** failures (status 1). A *usage* error on those
commands is reported in human form unless the global option was given, because
at that point argparse has not confirmed `--json` was even valid in context.

## A failed doctor check is not a CLI error

This is the distinction most likely to trip a consumer, because both exit `1`.

| | Failed `doctor` **check** | CLI **error** |
|---|---|---|
| Meaning | The snapshot loaded; the report says it violates the contract. | The command could not be carried out. |
| Stream | **stdout** | **stderr** |
| Shape | `utilityfog.observatory.report/1` | `utilityfog.observatory.error/1` |
| stderr | empty | the envelope |
| Exit status | 1 | 1 |

A completed diagnostic run containing failures is a **result**, not an error.
`ok: false` alone does not distinguish them — a failing doctor report also
carries it. Use the **stream** or the **`schema`** value.

Consequently the envelope is keyed on the error *type*, never on "the status
was 1".

## Forward compatibility

1. `schema` is `utilityfog.observatory.error/1`. The trailing `/N` bumps only
   for an incompatible structural change.
2. New keys may be added at any time. **Ignore keys you do not recognise.**
3. Existing keys are never removed, renamed or retyped within a version.
4. Tolerate an unknown `code` by falling back to `category`; tolerate an
   unknown `category` by falling back to the process exit status.
5. `message` and `suggestion` are human text — unstable, possibly localised,
   never to be parsed.
6. Nullable fields are always present.
7. The **process exit status is authoritative**; `exit_status` restates it for
   readers who see the document detached from the process, such as a log line.

## Consumer examples

### Shell

Select the envelope line; do not parse the whole file.

```bash
SCHEMA=utilityfog.observatory.error/1

if ! out=$(python -m vis.observatory info "$SNAP" --json 2>err.txt); then
  # Keep only lines that are JSON objects carrying the error schema, and
  # take the last. `-c` keeps each match on one line; `//empty` drops
  # anything that is not an object.
  envelope=$(jq -Rc --arg s "$SCHEMA" \
    'fromjson? // empty | select(type == "object" and .schema == $s)' \
    err.txt | tail -n 1)

  if [ -z "$envelope" ]; then
    echo "no error envelope found — internal error" >&2
    exit 1
  fi

  case "$(printf '%s' "$envelope" | jq -r .code)" in
    snapshot-not-found)   echo "no such snapshot" ;;
    snapshot-unreadable)  echo "corrupt snapshot" ;;
    *) printf '%s' "$envelope" | jq -r '"failed: " + .message' ;;
  esac
fi
```

### Python

```python
import json
import subprocess

ERROR_SCHEMA = "utilityfog.observatory.error/1"


def find_envelope(stderr):
    """Return the CLI's error envelope, or None if it did not emit one.

    stderr is shared with the warnings machinery, matplotlib and the
    interpreter's own shutdown notices, so the stream as a whole is not a
    JSON document and its last line is not necessarily the envelope. Scan
    for a JSON object carrying the error schema; take the last if several.
    """
    found = None
    for line in stderr.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            document = json.loads(line)
        except ValueError:
            continue
        if isinstance(document, dict) and document.get("schema") == ERROR_SCHEMA:
            found = document
    return found


proc = subprocess.run(
    ["python", "-m", "vis.observatory", "--error-format", "json",
     "doctor", snapshot],
    capture_output=True, text=True,
)

if proc.returncode == 0:
    report = json.loads(proc.stdout)          # all checks passed
elif proc.returncode == 1 and proc.stdout:
    report = json.loads(proc.stdout)          # ran; some checks failed
else:
    error = find_envelope(proc.stderr)
    if error is None:
        # No envelope means an internal error, not an expected failure.
        raise SystemExit(f"observatory failed unexpectedly:\n{proc.stderr}")
    raise SystemExit(f"{error['code']}: {error['message']}")
```

Note the last branch: **do not infer the envelope's presence from the exit
status alone.** An unexpected defect also exits non-zero, with a traceback and
no envelope. Absence of a matching line is how you tell them apart.

## Bounds and safety

- Every string field is collapsed to one line, forced to ASCII, and truncated
  at 256 characters with a visible `...` marker. Truncation applies to field
  **values**, never to the serialised document.
- Lone surrogates — from a POSIX `surrogateescape` filename or an unpaired
  UTF-16 unit on Windows — are rendered as literal text, so the document never
  contains an unpaired escape that strict parsers reject.
- No traceback, and no unrestricted exception representation, is emitted.

### Known limitation

`message` for `snapshot-unreadable` embeds the underlying decoder's text,
which can include absolute paths and OS-localised strings. It is bounded and
sanitised, but it is *not* a curated string. Treat `message` as untrusted
human text — which rule 5 above already requires — and key automation off
`code`.
