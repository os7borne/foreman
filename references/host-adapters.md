# Host adapters

Foreman is designed to sit above an agent runtime rather than replace its native execution system.

## Adapter responsibilities

A host adapter should translate between the runtime's native capabilities and Foreman's durable work model.

At minimum, an adapter should make it possible for an agent to:

1. discover existing Foreman work;
2. retrieve compact context for a work item;
3. create and update work;
4. record decisions, events, and artifacts;
5. complete steps without corrupting state;
6. resume work created by another agent or runtime.

The adapter should **not** copy an entire conversation into Foreman. Persist structured state and references to substantial artifacts instead.

## OpenClaw

OpenClaw skills use the AgentSkills-style `SKILL.md` format. Install Foreman in the workspace's `skills/foreman/` directory and expose the Foreman helper commands through the host's normal shell/tool execution mechanism.

The OpenClaw adapter should treat Foreman as the durable work layer while OpenClaw remains responsible for reasoning, tool use, and user communication.

## Hermes

Hermes supports AgentSkills-compatible skills under `~/.hermes/skills/`. The Hermes adapter should integrate with Foreman without attempting to duplicate Hermes Kanban's execution responsibilities.

Where Hermes Kanban already provides scheduling, dispatch, worker assignment, retries, or dependency handling, an adapter may map those capabilities into Foreman's durable work representation rather than recreating them.

## Cross-agent handoff

The critical adapter test is:

```text
Agent A / Runtime A
        │
        ├── create work
        ├── execute several steps
        ├── record decisions
        └── attach artifacts
                │
                ▼
            FOREMAN
                │
                ▼
Agent B / Runtime B
        │
        ├── get compact context
        ├── inspect relevant artifacts
        └── continue from the recorded next action
```

A successful handoff must not depend on replaying the original conversation.

## Adapter boundary

Keep the boundary narrow:

- **Foreman owns:** durable work state, work identity, lifecycle semantics, structured progress, decisions, events, dependencies, and artifact references.
- **Host owns:** model execution, tools, credentials, scheduling mechanisms, worker processes, UI, and user interaction.

If a capability can be implemented deterministically in the Foreman layer, prefer doing so there. If it depends on a runtime's execution environment, keep it in the adapter.
