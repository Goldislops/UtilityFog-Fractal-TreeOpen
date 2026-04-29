"""Phase 18 PR 6 + 7a — Orchestrator configuration.

Centralises the knobs an operator will realistically want to change between
environments (local dev vs. live Medusa) without having to edit the
orchestrator's loop logic itself.

Reads the following env vars, all optional:

  Core:
    MEDUSA_API_BASE_URL        Medusa REST endpoint (default: http://127.0.0.1:8080)
    MEDUSA_AGENT_BACKEND       "mock" | "anthropic" | "openai-compat"  (default: "mock")
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
    Orchestrator,
    OrchestratorClient,
    ToolRouter,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8080"

# Crafted to work with Phase 18's tool surface. Not model-specific.
DEFAULT_SYSTEM_PROMPT = """\
You are the Medusa Swarm Hunter orchestrator. Your job is to observe the
Medusa cellular-automata engine and, when warranted, propose small
parameter tunings to keep the matrix healthy.

Rules:
  1. ALWAYS inspect the current state before proposing. Use get_params,
     get_params_schema, get_medusa_census, get_medusa_equanimity, and
     get_acoustic_map to gather context.
  2. Every propose_tuning call MUST include a `justification` string
     explaining what concerning signal you saw and why this change helps.
  3. Prefer SMALL adjustments. Change at most 1–2 params per proposal.
  4. Only commit AUTO-category parameters. HUMAN_APPROVAL params can be
     proposed as dry-run for human review, but don't attempt to commit
     them — the API will return 403 and you should stop and explain
     what a human should check.
  5. LOCKED params are off-limits entirely. Don't propose changes to them.
  6. If the matrix looks healthy, say so and stop. No tuning is correct.
  7. Tool results that begin with "[ERROR]" indicate the tool execution
     failed. Read the rest of the message, decide whether to retry, choose
     a different tool, or stop and report.

Be concise. Observation first, then at most one proposal per iteration."""


@dataclass
class OrchestratorConfig:
    base_url: str = DEFAULT_BASE_URL
    backend_name: str = "mock"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_tool_depth: int = 8
    max_tokens: int = 2048
    temperature: float = 0.0
    orchestrator_source: str = "agent:orchestrator"
    commit_approver: str = "policy:auto"
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
            max_tool_depth=int(os.environ.get("MEDUSA_MAX_TOOL_DEPTH", "8")),
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
    name = config.backend_name

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
        orchestrator_source=config.orchestrator_source,
        commit_approver=config.commit_approver,
    )
    return Orchestrator(
        backend=backend,
        client=client,
        system_prompt=config.system_prompt,
        router=router,
        max_tool_depth=config.max_tool_depth,
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
