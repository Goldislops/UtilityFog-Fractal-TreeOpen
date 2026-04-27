# BACKEND_PROVIDER_MATRIX.md — Provider-Neutral Backend Plan

> **Status**: design / roadmap update for Phase 18 PR 7+. Supersedes the earlier "build a bespoke `NemoCloudBackend`" framing.
> **Origin**: Jack (GPT-5.5) audit, 2026-04-27. The original PR 7 scope as written was "NemoCloudBackend"; Jack flagged that this risks vendor lock-in disguised as integration, since NVIDIA NIM is OpenAI-compatible at the wire and so is most of the local-model ecosystem.

## The Core Insight

**Most LLM providers worth caring about expose an OpenAI-compatible `/v1/chat/completions` API.** A single `OpenAICompatBackend` covers many of them — cloud services and local servers alike — with config-only differences.

Anthropic is the conspicuous exception: their content-block format and tool-use semantics are different enough that a separate `AnthropicBackend` is justified (and is already built — see `scripts/agent_backends/anthropic_backend.py`).

So the actual backend taxonomy is:

```
AgentBackend (ABC)
├── MockBackend                 — tests; scripted responses
├── AnthropicBackend            — Claude family; native Anthropic SDK
└── OpenAICompatBackend (next)  — everything else; one class, many configs
    ├─ config: NVIDIA NIM
    ├─ config: DeepSeek
    ├─ config: OpenAI itself
    ├─ config: Together / Fireworks / Anyscale
    ├─ config: vLLM (local)
    ├─ config: SGLang (local)
    ├─ config: Ollama (local)
    └─ config: llama.cpp server (local)
```

`NemoCloudBackend` is *not* a class. It's a config of `OpenAICompatBackend` pointed at NVIDIA NIM, with the chosen Nemotron model name.

## Provider Matrix

Tested and intended targets, with the config shape each one needs. All assume an `OpenAICompatBackend` that takes `base_url`, `model`, optional `api_key`, optional `extra_headers`.

| Provider | Base URL | Auth | Notes |
|----------|----------|------|-------|
| **OpenAI** | `https://api.openai.com/v1` | `api_key` (Bearer) | The reference implementation. |
| **Anthropic** | n/a | n/a | Use `AnthropicBackend`, not this seam. Different content-block format. |
| **NVIDIA NIM** | `https://integrate.api.nvidia.com/v1` | `api_key` | OpenAI-compatible. Multiple models including Nemotron family. |
| **DeepSeek** | `https://api.deepseek.com/v1` | `api_key` | OpenAI-compatible; significantly cheaper than peers. Tool use supported. |
| **Together AI** | `https://api.together.xyz/v1` | `api_key` | OpenAI-compatible cloud aggregator (Llama, Qwen, DeepSeek, etc.). |
| **Fireworks AI** | `https://api.fireworks.ai/inference/v1` | `api_key` | OpenAI-compatible cloud aggregator. |
| **vLLM (local)** | `http://localhost:8000/v1` | optional | Self-hosted; runs on the workstation when GPU isn't loaded. |
| **SGLang (local)** | `http://localhost:30000/v1` | optional | Self-hosted; tool-use-friendly serving framework. |
| **Ollama** | `http://localhost:11434/v1` | none | Self-hosted; OpenAI-compatible mode added in recent versions. |
| **llama.cpp server** | `http://localhost:8080/v1` | none | Self-hosted; lightweight CPU-fallback option. |

## What `OpenAICompatBackend` Actually Needs

Implementation should be small (~150 lines). Suggested shape mirroring `AnthropicBackend`'s:

```python
class OpenAICompatBackend(AgentBackend):
    name: ClassVar[str] = "openai-compat"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        client: Optional[Any] = None,  # injectable for tests
    ) -> None:
        ...
```

Wire-translation pattern is well-documented; OpenAI's tool-use messages/response shape is the reference. Differences vs `AnthropicBackend`:

- **Messages**: `{role, content}` strings or arrays of typed parts (text, tool_use, tool_result equivalents — though OpenAI uses `tool_calls` as a separate field on the assistant message rather than inline blocks).
- **Tools**: `[{"type": "function", "function": {name, description, parameters}}]`. Note `parameters` not `input_schema`.
- **Response**: `choices[0].message.content` for text, `choices[0].message.tool_calls` for calls. `finish_reason` analog of `stop_reason`.
- **Tool result reply**: `{"role": "tool", "tool_call_id": ..., "content": ...}` — distinct from Anthropic's user-message-with-tool-result-blocks pattern.

The translation layer hides all of this from the orchestrator; above the backend, a `ToolCall` is a `ToolCall`, same as it is for `AnthropicBackend`.

## Edge Cases / Provider Quirks

- **Tool-use availability**: not every model on every provider supports tool calls. Document required model capabilities per config rather than auto-detecting.
- **Auth schemes**: most are `Authorization: Bearer ...` but a few use custom headers. The `extra_headers` param covers these.
- **Streaming**: not in scope for PR 7. The orchestrator loop currently consumes one full response per turn; streaming can be a later PR if value is shown.
- **Extended thinking / reasoning models**: Anthropic's extended thinking and OpenAI's reasoning models have provider-specific output shapes. Initial backend ignores them; they're a follow-up if needed.
- **Local server warm-up**: vLLM / SGLang / Ollama may have slow first-request latency. The backend's job isn't to manage that; the orchestrator runner is.

## Local-First, Single-Node-First

Per Jack's recommendation and the project's budget posture:

1. **Don't build a swarm yet.** Logical agent roles (observer, proposer, critic, budget-guard, escalation summarizer) live INSIDE the existing single-process orchestrator loop first, executed serially through one backend.
2. **One local endpoint at a time.** When Medusa / BOINC / F@H aren't loaded, run a local model server (vLLM or Ollama is easiest) on the workstation. Don't try to host across multiple machines until parity is proven on one.
3. **Cluster-wide distribution is unblocked but not unlocked.** Phase 17b's `shard_protocol.py` + `shard_transport_zmq.py` already give us a transport-agnostic way to distribute work when needed. They're available; they're not yet warranted.

## Smaller Nemotron Variants — A Note

The original "NemoCloud" framing imagined hosting Nemotron-class models. The flagship Nemotron-3-Super-120B-A12B requires 8×H100-80GB and isn't a single-RTX-5090 play. *However*, the Nemotron family includes smaller variants (Nemotron-Mini-4B-Instruct, Nemotron-4-15B-Instruct, etc.) that are runnable on one consumer GPU when Medusa is paused. So the local-Nemotron path isn't architecturally blocked — it's just one config of `OpenAICompatBackend` pointed at a local vLLM/Ollama server hosting the appropriate-size variant.

## Roadmap Adjustment

Was:

> **PR 7 — `NemoCloudBackend`**. When NVIDIA Cloud is up.

Becomes:

> **PR 7 — `OpenAICompatBackend`** + provider configs. One backend class, multiple configurations. Tests use `MockBackend` (existing) plus a fake `httpx`/`requests` transport layer for the OpenAI-compatible request/response shape. Initial verified configs: OpenAI itself (smoke test), DeepSeek (cheap real-cloud target), local vLLM or Ollama (cost-zero local target). NVIDIA NIM and other clouds drop in as configs once API keys are in place.
>
> **PR 8 — Provider parity test**. Run the same orchestrator iteration through `AnthropicBackend` and `OpenAICompatBackend`-via-DeepSeek (or local), assert that valid proposals get accepted by the tuning API regardless of which brain produced them. This is the parity proof that closes the model-agnostic claim.

PR 7's complexity drops considerably. PR 8 becomes the actual model-agnosticism proof, not a hand-wave.

## What This Defers (Intentionally)

- Multi-process / cluster-wide agent distribution.
- Provider-specific advanced features (streaming, reasoning models, extended thinking).
- Specialized agent roles as separate processes (do them as logical roles inside one loop first).
- Running large frontier models locally.

These can each become their own PR when actually warranted by load or capability requirements. Until then, the boring single-process single-backend-class shape is enough.
