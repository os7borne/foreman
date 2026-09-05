# Host adapters

Foreman keeps its work model host-neutral. A host adapter explains how an agent runtime discovers the skill and executes the deterministic persistence helper.

## OpenClaw

Install the directory at `<workspace>/skills/foreman/` (or another OpenClaw skill root). OpenClaw discovers skills through the `SKILL.md` frontmatter and exposes the skill to the agent. The bundled helper is `scripts/foreman.py`.

The core Foreman model is independent of OpenClaw's task/session implementation. The host should treat Foreman as durable work state that can outlive a particular agent session.

## Hermes

Install the directory at `~/.hermes/skills/foreman/`. Hermes uses the same AgentSkills-style `SKILL.md` structure and can invoke installed skills from natural language or slash commands.

The Hermes adapter should not duplicate Hermes Kanban. Foreman is intended to be the portable work layer. A future Hermes adapter can map Foreman tasks to Hermes Kanban execution while retaining Foreman's durable, cross-agent representation.

## Shared-state handoff

For a genuine cross-agent test, both hosts must point to the same Foreman database. Create or update work in one host, stop that host, then resume from the second host by reading compact Foreman context. The second host should not need the original conversation transcript.

## Adapter boundary

Host-specific code may handle:

- skill discovery and invocation
- runtime-specific tool calls
- mapping host task IDs to Foreman IDs
- launching workers
- scheduling or notifications

Foreman should continue to own:

- durable objective and plan
- state and lifecycle
- compact context
- decisions
- important events
- artifact references
- handoff semantics
