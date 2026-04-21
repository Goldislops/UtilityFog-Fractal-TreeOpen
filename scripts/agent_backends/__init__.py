"""Model-agnostic agent backend abstraction (Phase 18 PR 4+).

Subpackage for LLM-backed agent backends that all speak the same
`AgentBackend` ABC. The orchestrator layer (later PR) imports only
this package — swapping Anthropic Opus ↔ Nemotron ↔ anything else
is a one-line config change in `scripts/orchestrator_config.py`.

Exports:
  - ToolSpec, ToolCall                  — tool-use call sites
  - TextBlock, ToolUseBlock, ToolResultBlock, ContentBlock  — message content
  - Message                             — one turn in a conversation
  - AgentResponse                       — what a backend returns
  - AgentBackend                        — the ABC every backend implements
  - MockBackend                         — scripted responses for tests
"""

from scripts.agent_backends.base import (
    AgentBackend,
    AgentResponse,
    ContentBlock,
    Message,
    TextBlock,
    ToolCall,
    ToolResultBlock,
    ToolSpec,
    ToolUseBlock,
)
from scripts.agent_backends.mock import MockBackend

# AnthropicBackend requires `pip install anthropic`; import lazily so the
# package is usable (MockBackend still works) when anthropic isn't installed.
try:
    from scripts.agent_backends.anthropic_backend import (  # noqa: F401
        AnthropicBackend,
        DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL,
    )
except ImportError:
    AnthropicBackend = None  # type: ignore[assignment]
    ANTHROPIC_DEFAULT_MODEL = None  # type: ignore[assignment]

__all__ = [
    "AgentBackend",
    "AgentResponse",
    "AnthropicBackend",
    "ANTHROPIC_DEFAULT_MODEL",
    "ContentBlock",
    "Message",
    "MockBackend",
    "TextBlock",
    "ToolCall",
    "ToolResultBlock",
    "ToolSpec",
    "ToolUseBlock",
]
