"""Phase 18 PR 4 — MockBackend for tests and orchestrator development.

Scripted `AgentBackend` that returns pre-canned responses without any
network calls. Used as the test double in the orchestrator's own tests
(PR 6) and as the reference implementation that `AnthropicBackend`
and `NemoCloudBackend` are tested against.

Two modes:
  - **List mode**: pass a list of `AgentResponse`s; each `complete()`
    call pops the next one. Raises `StopIteration` (wrapped as
    `RuntimeError`) when exhausted — test writers get a loud failure
    rather than silent wrong-answer.
  - **Callable mode**: pass a callable `(messages, tools, **kwargs)
    -> AgentResponse`. The callable is invoked on every `complete()`
    call; useful for stateful scenarios (e.g. "respond based on the
    last tool result").

Every call is recorded in `.calls` for assertion in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Optional, Union

from scripts.agent_backends.base import (
    AgentBackend,
    AgentResponse,
    Message,
    ToolSpec,
)


ResponseSource = Union[
    list[AgentResponse],
    Callable[..., AgentResponse],
]


@dataclass
class RecordedCall:
    """One recorded invocation of `MockBackend.complete()`."""

    messages: list[Message]
    tools: list[ToolSpec]
    system: Optional[str]
    max_tokens: int
    temperature: float


class MockBackend(AgentBackend):
    """Scripted backend. No network, no LLM."""

    name: ClassVar[str] = "mock"

    def __init__(self, responses: ResponseSource) -> None:
        if isinstance(responses, list):
            # Defensive copy so the caller can't mutate the queue after init.
            self._queue: Optional[list[AgentResponse]] = list(responses)
            self._fn: Optional[Callable[..., AgentResponse]] = None
        elif callable(responses):
            self._queue = None
            self._fn = responses
        else:
            raise TypeError(
                "MockBackend responses must be a list[AgentResponse] or a callable"
            )
        self._calls: list[RecordedCall] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        *,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> AgentResponse:
        # Record BEFORE resolving the response so even an exhausted queue
        # captures the attempted call (useful for debugging test fixtures).
        self._calls.append(
            RecordedCall(
                messages=list(messages),
                tools=list(tools),
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        )
        if self._fn is not None:
            return self._fn(
                messages,
                tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        assert self._queue is not None  # for type-checker; set in __init__
        if not self._queue:
            raise RuntimeError(
                f"MockBackend exhausted: complete() called {len(self._calls)} times "
                f"but only {len(self._calls) - 1} responses were scripted."
            )
        return self._queue.pop(0)

    @property
    def calls(self) -> list[RecordedCall]:
        """Snapshot of every complete() call made, in order."""
        return list(self._calls)

    @property
    def remaining(self) -> int:
        """Number of scripted responses left (list mode only). None in callable mode."""
        return -1 if self._queue is None else len(self._queue)

    def reset_calls(self) -> None:
        """Clear the recorded calls (but not the queued responses)."""
        self._calls.clear()


__all__ = ["MockBackend", "RecordedCall"]
