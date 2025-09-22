# Observability System (FT-010)

Comprehensive observability with structured logging, distributed tracing, and event tracking.

## Quick Start

```python
from agent.observability import trace_operation, log_simulation_event

# Trace operations
with trace_operation("agent_movement", agent_id=123) as trace_id:
    calculate_movement()

# Log events
log_simulation_event("agent_created", agent_id=456, position=[0, 0, 0])
```

## Features

- **Structured JSON Logs**: Consistent schema with trace propagation
- **Distributed Tracing**: Thread-local context management
- **Rate-Limited Errors**: Intelligent spam prevention
- **Event System**: Structured event tracking
- **94% Test Coverage**: Exceeds quality requirements

All logs use structured JSON format with trace IDs for correlation.
