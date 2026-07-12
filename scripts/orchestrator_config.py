"""Phase 18 PR 6 + 7a — Legacy tuning orchestrator configuration.

Centralises the knobs an operator will realistically want to change between
environments (local dev vs. live Medusa) without having to edit the
orchestrator's loop logic itself.

Reads the following env vars, all optional:

  Core:
    MEDUSA_API_BASE_URL        Medusa REST endpoint (default: http://127.0.0.1:8080)
    MEDUSA_AGENT_BACKEND       "mock" | "anthropic" | "openai-compat"  (default: "mock")
    MEDUSA_ORCHESTRATOR_MODE   "observe" | "propose"  (default: "observe"; any
                               absent/malformed/unknown value fails closed to
                               "observe" — see scripts/orchestrator.resolve_mode)
    MEDUSA_MAX_TOOL_DEPTH      int (default: 8)
    MEDUSA_MAX_TOKENS          int (default: 2048)

  Anthropic backend (when MEDUSA_AGENT_BACKEND=anthropic):
    ANTHROPIC_API_KEY          read by AnthropicBackend / SDK directly
    MEDUSA_ANTHROPIC_MODEL     read by AnthropicBackend directly

  OpenAI-compatible backend (when MEDUSA_AGENT_BACKEND=openai-compat):
    MEDUSA_OPENAI_BASE_URL       provider endpoint (e.g. https://api.deepseek.com/v1)
    MEDUSA_OPENAI_MODEL          model identifier (e.g. deepseek-chat)
    MEDUSA_OPENAI_API_KEY        provider API key
    MEDUSA_OPENAI_EXTRA_HEADERS  JSON dict for non-Bearer auth schemes

The swap that AURA and Jack keep calling out is real, and lives in one env var:

    export MEDUSA_AGENT_BACKEND=anthropic                            # Claude (cloud)

    export MEDUSA_AGENT_BACKEND=openai-compat \\
           MEDUSA_OPENAI_BASE_URL=https://api.deepseek.com/v1 \\
           MEDUSA_OPENAI_MODEL=deepseek-chat                          # DeepSeek (cheap)

    export MEDUSA_AGENT_BACKEND=openai-compat \\
           MEDUSA_OPENAI_BASE_URL=http://localhost:11434/v1 \\
           MEDUSA_OPENAI_MODEL=llama3.1:8b                            # Ollama (local, free)

    export MEDUSA_AGENT_BACKEND=openai-compat \\
           MEDUSA_OPENAI_BASE_URL=https://integrate.api.nvidia.com/v1 \\
           MEDUSA_OPENAI_MODEL=nvidia/nemotron-mini-4b-instruct       # NVIDIA NIM (Nemo)

NemoCloud is NOT a separate backend any more; it's an `openai-compat` config
pointed at NVIDIA NIM. See `BACKEND_PROVIDER_MATRIX.md` for the canonical
provider table.

`create_orchestrator()` wires everything together and returns a ready-to-run
instance. `create_backend()` is exposed separately so tests and ad-hoc
scripts can mix-and-match.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from scripts.agent_backends import (
    AgentBackend,
    AnthropicBackend,
    MockBackend,
    OpenAICompatBackend,
)
from scripts.orchestrator import (
    DEFAULT_MAX_TOTAL_TOOL_CALLS,
    MODE_OBSERVE,
    Orchestrator,
    OrchestratorClient,
    OrchestratorMode,
    ToolRouter,
    resolve_mode,
    tools_for_mode,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8080"

# Crafted to work with Phase 18's tool surface. Not model-specific.
# Describes the quarantined surface accurately: observation is always
# available; in `propose` mode a dry-run-only proposal tool is added; there is
# no LLM-facing commit tool. Tool errors are surfaced two ways depending on
# transport: native backends expose an `is_error` result flag; the
# OpenAI-compatible backend marks the same condition with a leading "[ERROR]"
# in the tool-result text (it has no native error flag). The prompt names both
# so the model recognises an error regardless of backend.
DEFAULT_SYSTEM_PROMPT = """\
You are the Medusa legacy tuning orchestrator. Your job is to observe the
Medusa cellular-automata engine and report what you see. In `propose` mode you
may additionally validate a small parameter tuning as a DRY RUN for a human to
review later.

Rules:
  1. ALWAYS inspect the current state first. Use get_params,
     get_params_schema, get_medusa_census, get_medusa_equanimity, and
     get_acoustic_map to gather context.
  2. If a `propose_tuning` tool is available, every call MUST include a
     `justification` string explaining what concerning signal you saw and why
     this change would help. Proposals are validated as dry-run only — this
     orchestrator cannot commit any change.
  3. Prefer SMALL adjustments. Change at most 1–2 params per proposal.
  4. LOCKED params are off-limits entirely. Don't propose changes to them.
     HUMAN_APPROVAL params may be proposed as dry-run for a human to review.
  5. If the matrix looks healthy, say so and stop. No tuning is correct.
  6. A tool result may be reported as an error. Native backends flag it with
     `is_error`; the OpenAI-compatible backend marks the same condition with a
     leading `[ERROR]` in the result text. Either form means the call failed —
     read it, then decide whether to retry, choose a different tool, or stop
     and report.

Be concise. Observation first, then at most one dry-run proposal per iteration."""


@dataclass
class OrchestratorConfig:
    base_url: str = DEFAULT_BASE_URL
    backend_name: str = "mock"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    mode: OrchestratorMode = MODE_OBSERVE
    max_tool_depth: int = 8
    max_total_tool_calls: int = DEFAULT_MAX_TOTAL_TOOL_CALLS
    max_tokens: int = 2048
    temperature: float = 0.0
    orchestrator_source: str = "agent:orchestrator"
    # Used only when backend_name == "openai-compat":
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_extra_headers: Optional[dict] = None

    @classmethod
    def from_env(cls) -> "OrchestratorConfig":
        # Parse extra_headers as JSON if present; tolerate malformed input.
        extra_headers: Optional[dict] = None
        raw_headers = os.environ.get("MEDUSA_OPENAI_EXTRA_HEADERS")
        if raw_headers:
            try:
                parsed = json.loads(raw_headers)
                if isinstance(parsed, dict):
                    extra_headers = parsed
            except (ValueError, TypeError):
                extra_headers = None
        return cls(
            base_url=os.environ.get("MEDUSA_API_BASE_URL", DEFAULT_BASE_URL),
            backend_name=os.environ.get("MEDUSA_AGENT_BACKEND", "mock").lower(),
            # Fail-closed: absent/malformed/unknown → observe (resolve_mode).
            mode=resolve_mode(os.environ.get("MEDUSA_ORCHESTRATOR_MODE")),
            max_tool_depth=int(os.environ.get("MEDUSA_MAX_TOOL_DEPTH", "8")),
            max_total_tool_calls=int(os.environ.get(
                "MEDUSA_MAX_TOTAL_TOOL_CALLS", str(DEFAULT_MAX_TOTAL_TOOL_CALLS))),
            max_tokens=int(os.environ.get("MEDUSA_MAX_TOKENS", "2048")),
            openai_base_url=os.environ.get("MEDUSA_OPENAI_BASE_URL") or None,
            openai_model=os.environ.get("MEDUSA_OPENAI_MODEL") or None,
            openai_api_key=os.environ.get("MEDUSA_OPENAI_API_KEY") or None,
            openai_extra_headers=extra_headers,
        )


def create_backend(config: OrchestratorConfig) -> AgentBackend:
    """Factory. This is the one-line swap AURA keeps calling out.

    Three backends today:
      - "mock"          → tests / smoke
      - "anthropic"     → Claude family (separate Anthropic SDK)
      - "openai-compat" → everything else (OpenAI, NIM, DeepSeek, Together,
                          Fireworks, vLLM, SGLang, Ollama, llama.cpp server, …)

    NemoCloud is NOT a separate name; configure "openai-compat" with NIM's
    base_url and a Nemotron model name.
    """
    # PR 7b: accept openai_compat (underscore) as an alias for openai-compat.
    # Humans will inevitably type the underscore — both because most env vars
    # use underscores and because the hyphen is awkward on the shell side.
    name = config.backend_name
    if name == "openai_compat":
        name = "openai-compat"

    if name == "anthropic":
        if AnthropicBackend is None:
            raise RuntimeError(
                "MEDUSA_AGENT_BACKEND=anthropic requires `pip install anthropic`"
            )
        return AnthropicBackend()

    if name == "openai-compat":
        if OpenAICompatBackend is None:
            raise RuntimeError(
                "MEDUSA_AGENT_BACKEND=openai-compat requires `pip install openai`"
            )
        kwargs: dict = {}
        if config.openai_base_url:
            kwargs["base_url"] = config.openai_base_url
        if config.openai_model:
            kwargs["model"] = config.openai_model
        if config.openai_api_key:
            kwargs["api_key"] = config.openai_api_key
        if config.openai_extra_headers:
            kwargs["extra_headers"] = config.openai_extra_headers
        return OpenAICompatBackend(**kwargs)

    if name == "mock":
        return MockBackend(responses=[])

    if name in ("nemo_cloud", "nemocloud", "nemo-cloud", "nemo"):
        # Friendly redirect: this used to be a planned bespoke backend but
        # got reframed as an openai-compat config in Phase 18.5 (PR #128).
        raise ValueError(
            f"MEDUSA_AGENT_BACKEND={name!r} is no longer a separate backend. "
            "Use MEDUSA_AGENT_BACKEND=openai-compat with MEDUSA_OPENAI_BASE_URL "
            "pointed at NVIDIA NIM (https://integrate.api.nvidia.com/v1) and "
            "MEDUSA_OPENAI_MODEL set to a Nemotron model name. "
            "See BACKEND_PROVIDER_MATRIX.md."
        )

    raise ValueError(f"unknown backend: {name!r}")


def create_orchestrator(
    config: Optional[OrchestratorConfig] = None,
    *,
    backend: Optional[AgentBackend] = None,
    client: Optional[OrchestratorClient] = None,
) -> Orchestrator:
    """Wire a live orchestrator from config (reading env by default)."""
    if config is None:
        config = OrchestratorConfig.from_env()
    backend = backend or create_backend(config)
    client = client or OrchestratorClient(config.base_url)
    router = ToolRouter(
        client,
        mode=config.mode,
        orchestrator_source=config.orchestrator_source,
    )
    return Orchestrator(
        backend=backend,
        client=client,
        system_prompt=config.system_prompt,
        mode=config.mode,
        tools=tools_for_mode(config.mode),
        router=router,
        max_tool_depth=config.max_tool_depth,
        max_total_tool_calls=config.max_total_tool_calls,
        max_tokens_per_call=config.max_tokens,
        temperature=config.temperature,
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_SYSTEM_PROMPT",
    "OrchestratorConfig",
    "create_backend",
    "create_orchestrator",
]
