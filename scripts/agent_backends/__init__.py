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

__all__ = [
    "AgentBackend",
    "AgentResponse",
    "ContentBlock",
    "Message",
    "MockBackend",
    "TextBlock",
    "ToolCall",
    "ToolResultBlock",
    "ToolSpec",
    "ToolUseBlock",
]
