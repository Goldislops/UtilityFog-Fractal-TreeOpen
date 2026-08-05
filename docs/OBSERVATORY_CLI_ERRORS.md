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

| | `human` (default) | `json` |
|---|---|---|
| Stream | stderr | stderr |
| Shape | `cosmic-observatory: error: <message>` | one JSON object |
| Lines | exactly one | exactly one |
| stdout | empty | empty |
| Exit status | unchanged | unchanged |

Human mode is byte-for-byte what it has always been. `--error-format human`
and omitting the option produce identical output.

## What is *not* affected

- **`--help` is never an error.** Help stays human-readable on **stdout** with
  exit status **0**, in both modes.
- **Successful output is unchanged.** `info --json` and `doctor --json` emit
  exactly the documents they always have, on stdout.
- **Unexpected defects still propagate.** A programming error keeps its
  traceback and is never dressed up as a user error. If the last line of
  stderr does not parse as an envelope, an internal error occurred — do not
  infer the envelope's presence from the exit status alone.

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
document is ASCII-escaped, and it is followed by one newline. Equivalent
inputs produce byte-identical output.

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
| `unknown-option` | An option is not recognised, or a value was given to a flag that takes none. |
| `missing-argument` | A required argument was omitted. |
| `invalid-argument-value` | An argument value failed validation (range, type, or choice). |
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
| `input-error` | Fallback for any other expected runtime failure. |

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

```bash
if ! out=$(python -m vis.observatory info "$SNAP" --json 2>err.json); then
  code=$(jq -r .code < err.json)
  case "$code" in
    snapshot-not-found)   echo "no such snapshot" ;;
    snapshot-unreadable)  echo "corrupt snapshot" ;;
    *)                    echo "failed: $(jq -r .message < err.json)" ;;
  esac
fi
```

### Python

```python
import json
import subprocess

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
    # The envelope is the LAST line of stderr: the warnings machinery and
    # matplotlib share this stream and are not under the CLI's control.
    line = [ln for ln in proc.stderr.splitlines() if ln.strip()][-1]
    error = json.loads(line)
    raise SystemExit(f"{error['code']}: {error['message']}")
```

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
