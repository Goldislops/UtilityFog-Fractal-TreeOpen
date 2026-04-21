"""Phase 18 PR 6 — Orchestrator configuration.

Centralises the knobs an operator will realistically want to change between
environments (local dev vs. live Medusa) without having to edit the
orchestrator's loop logic itself.

Reads the following env vars, all optional:
  - MEDUSA_API_BASE_URL        (default: http://127.0.0.1:8080)
  - MEDUSA_AGENT_BACKEND       (default: "mock"; one of: "mock", "anthropic")
  - MEDUSA_ANTHROPIC_MODEL     (read by AnthropicBackend directly)
  - MEDUSA_MAX_TOOL_DEPTH      (default: 8)
  - MEDUSA_MAX_TOKENS          (default: 2048)
  - ANTHROPIC_API_KEY          (read by AnthropicBackend directly)

The swap-out AURA keeps asking about is literally one env var here:
  export MEDUSA_AGENT_BACKEND=anthropic  # today
  # export MEDUSA_AGENT_BACKEND=nemo_cloud  # tomorrow, once PR 7 lands

`create_orchestrator()` wires everything together and returns a ready-to-run
instance. `create_backend()` is exposed separately so tests and ad-hoc
scripts can mix-and-match.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from scripts.agent_backends import (
    AgentBackend,
    AnthropicBackend,
    MockBackend,
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

    @classmethod
    def from_env(cls) -> "OrchestratorConfig":
        return cls(
            base_url=os.environ.get("MEDUSA_API_BASE_URL", DEFAULT_BASE_URL),
            backend_name=os.environ.get("MEDUSA_AGENT_BACKEND", "mock").lower(),
            max_tool_depth=int(os.environ.get("MEDUSA_MAX_TOOL_DEPTH", "8")),
            max_tokens=int(os.environ.get("MEDUSA_MAX_TOKENS", "2048")),
        )


def create_backend(config: OrchestratorConfig) -> AgentBackend:
    """Factory. This is the one-line swap AURA keeps calling out."""
    name = config.backend_name
    if name == "anthropic":
        if AnthropicBackend is None:
            raise RuntimeError(
                "MEDUSA_AGENT_BACKEND=anthropic requires `pip install anthropic`"
            )
        return AnthropicBackend()
    if name == "mock":
        # A mock with no scripted responses is useful for import-smoke tests
        # only. Real mock usage passes responses via the constructor.
        return MockBackend(responses=[])
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
