# Agent Skills

This directory contains skill modules that extend the agent's capabilities with domain-specific knowledge and tools.

## Available Skills

### vanguard-networking
Provides knowledge of the GPU cluster topology, networking configuration, and task submission patterns for the Vanguard SOC cluster (3x RTX 5090 + 2x RTX 4090).

**Key capabilities:**
- Cluster node IP/port mapping
- GPU affinity preferences
- Resource reservation policies
- gRPC API usage examples

### remote-ops
Enables remote status updates and command reception via mobile push notifications and webhooks.

**Key capabilities:**
- Pushover/Telegram/Discord integration
- Real-time alerts (task completion, thermal warnings)
- Remote command execution
- Dashboard updates

## Usage

Skills are loaded automatically by the agent framework. Each skill provides:

1. **Knowledge base** (`skill.md`): Markdown documentation with examples
2. **Tool definitions** (optional): MCP tool schemas
3. **Configuration** (optional): Environment variables, API keys

## Adding New Skills

1. Create a new directory: `agent/skills/my-skill/`
2. Add `skill.md` with documentation
3. (Optional) Add `tools.json` with MCP tool definitions
4. (Optional) Add `config.env.example` with required environment variables
5. Update this README
