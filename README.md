# Foreman

**The skill that makes sure your agents don't drop the ball.**

> **Your agent may change. Your work shouldn't.**

Foreman is a portable, agent-agnostic work-management skill for AI agents. It gives agents a durable place to keep the **work itself** — objectives, plans, decisions, state, progress, blockers, and artifact references — independently of the agent runtime doing the work.

The idea is simple:

```text
                 ┌─────────────────────┐
                 │       FOREMAN       │
                 │                     │
                 │   Durable Work      │
                 │   goals             │
                 │   plans             │
                 │   decisions         │
                 │   state             │
                 │   artifacts         │
                 │   history           │
                 └──────────┬──────────┘
                            │
                 ┌──────────┴──────────┐
                 │                     │
           ┌─────▼─────┐         ┌─────▼─────┐
           │   Agent A  │         │   Agent B  │
           │   worker   │         │   worker   │
           └────────────┘         └────────────┘
```

An agent is the **worker**. Foreman is the **manager and memory of the work**.

## Why Foreman exists

Agent runtimes change quickly. A project might start in Hermes today, continue in OpenClaw tomorrow, and eventually be picked up by another agent entirely.

Without a durable work layer, the useful state of the project is trapped inside the conversation or inside one runtime.

Foreman separates those concerns:

- **Agent runtime** — executes the work, uses tools, reasons, and communicates with the user.
- **Foreman** — owns durable representation of the work and makes it resumable.
- **Artifacts** — hold substantial research, documents, code, and other outputs; Foreman stores references to them rather than stuffing their contents into every context window.

The goal is not to replace an agent's native task system. A runtime such as Hermes can remain the execution backend. Foreman provides a portable work representation that can survive a runtime change.

## The killer test

Foreman should make this possible:

> Start a substantial project in one agent. Stop it halfway through. Open a different agent. Ask it to continue. It should understand what remains without replaying the old conversation.

That cross-agent handoff is the core design test for Foreman.

## Core loop

Foreman follows a simple lifecycle:

**Understand → Plan → Confirm when necessary → Execute → Record → Report → Resume**

For simple work, an agent should not create unnecessary project-management overhead. Foreman becomes valuable when work has multiple meaningful steps, dependencies, a deadline, multiple tools or agents, substantial effort, or a realistic need to pause and resume.

For complex or consequential work, the agent should produce a compact plan and obtain approval before execution when appropriate. Consequential actions may require a separate action-level confirmation.

## What Foreman persists

Foreman deliberately separates **state**, **context**, **history**, and **artifacts**.

### State

Small information that should be cheap to retrieve:

- objective
- status
- progress
- current step
- next action
- blockers
- due date
- key constraints

### Context

Information retrieved when it is relevant:

- decisions
- findings
- constraints
- notes
- recent meaningful events

### History

An append-only event trail of what happened. History should normally remain outside the model context unless the agent needs to investigate what happened.

### Artifacts

Large outputs belong in files, not in the task record. Foreman stores references to those files so another agent can retrieve them when needed.

This separation is important for **token efficiency**: agents should spend context on judgment and execution, not repeatedly reconstructing state or reading their entire history.

## Architecture

Foreman is intentionally a **skill/protocol layer**, not a required hosted application or web UI.

The first implementation uses a deterministic SQLite store and a small Python CLI. An agent skill instructs the host agent how and when to use that store.

The intended architecture is:

```text
┌─────────────────────────────────────────────┐
│                  FOREMAN                    │
│                                             │
│  Durable work representation + conventions  │
│                                             │
│  tasks · steps · decisions · events         │
│  dependencies · artifacts · lifecycle       │
└──────────────────────┬──────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
     Hermes adapter            OpenClaw adapter
          │                         │
      Hermes agent              OpenClaw agent
```

A runtime-specific adapter can translate the host's native task/agent APIs into Foreman's durable representation. The Foreman model remains the portable contract.

## v0.1

The current implementation provides a deliberately small foundation:

- durable SQLite persistence
- task lifecycle and status
- ordered work steps
- progress tracking
- compact task context
- decisions
- events
- artifact references
- basic dependencies in the schema
- task search and listing
- deterministic Python CLI
- AgentSkills-compatible `SKILL.md`
- OpenClaw-compatible skill layout
- Hermes-compatible installation model

The implementation intentionally does **not** attempt to provide a full hosted task-management product.

### Current limitations

v0.1 is a foundation, not the finished protocol. Areas still being hardened include:

- stronger lifecycle/state-transition validation
- retry and crash-recovery semantics
- concurrent SQLite access
- schema versioning and migrations
- richer dependency operations
- native scheduling and recurring execution
- host-specific adapters
- real cross-agent integration tests
- notification delivery
- remote/shared storage
- web UI

These are deliberate follow-on areas rather than reasons to make the core work model larger prematurely.

## Installation

### OpenClaw

Install the skill under the workspace skill directory:

```text
<workspace>/skills/foreman/
```

The directory should contain `SKILL.md` and the supporting Foreman files.

### Hermes

Install the skill under:

```text
~/.hermes/skills/foreman/
```

Foreman follows the AgentSkills-style `SKILL.md` convention so the core instructions can remain portable across compatible hosts.

## Storage

The default local database is:

```text
~/.foreman/foreman.db
```

The database is an implementation detail of the current local adapter. The long-term goal is for the **Foreman work model** to remain portable even when its persistence backend changes.

## Design principles

### 1. Work outlives the worker

The project should not disappear because an agent crashes, a session ends, or the user changes runtimes.

### 2. State is cheap; history is not context

Always retrieve a compact representation of the current state. Retrieve historical detail only when it is useful.

### 3. Deterministic operations should stay deterministic

Progress calculation, lifecycle transitions, dependencies, persistence, and other bookkeeping should not depend on an LLM making a judgment it does not need to make.

### 4. Agents own judgment

Agents should handle decomposition, interpretation, research, decisions, tool use, and communication. Foreman should make the resulting work state durable.

### 5. High-level operations beat raw database access

Agents should interact with work through semantic operations rather than constructing arbitrary SQL or manually maintaining database invariants.

### 6. Idempotency matters

Agents crash. Tools retry. Messages get duplicated. Work operations should be designed so a retry does not silently corrupt the project state.

### 7. Artifacts are first-class

Research and generated outputs should live where they naturally belong. The work record should point to them rather than becoming a giant transcript.

## Intended operation surface

The initial protocol is intentionally small. The core operations are conceptually:

```text
create_work()
get_context()
update_work()
complete_step()
record_decision()
record_event()
attach_artifact()
search_work()
```

Additional operations such as dependencies, scheduling, recurring work, and host-specific dispatch can build on this foundation without changing the core model.

## Example

A project might look like this from Foreman's perspective:

```json
{
  "objective": "Identify 20 qualified Series A fintech investment targets.",
  "status": "running",
  "progress": 0.4,
  "current_step": "Filter candidates against investment criteria",
  "next_action": "Review the remaining candidate set",
  "constraints": [
    "ARR > $10M",
    "Exclude public companies"
  ],
  "completed": [
    "Define screening criteria",
    "Identify initial candidate set"
  ],
  "remaining": [
    "Filter candidates",
    "Research qualifying companies",
    "Produce investment rationale"
  ]
}
```

An agent does not need the entire original conversation to continue. It needs the compact state, relevant decisions/findings, and the referenced artifacts.

## Development roadmap

The next milestone is **v0.1.1: battle-test the durable work layer**.

Priority tests:

1. crash halfway through a project and resume
2. hand work from one agent to another
3. verify compact context stays useful without replaying history
4. test retry/idempotency behavior
5. test concurrent access and failure recovery
6. verify blocked/unblocked work behaves correctly
7. verify artifacts survive agent changes
8. prevent accidental or invalid completion
9. exercise the skill in both OpenClaw and Hermes

The most important demonstration is a real **OpenClaw ↔ Hermes handoff** where one agent starts substantial work, stops, and another agent continues from Foreman's durable state.

## Repository layout

```text
skills/foreman/
├── SKILL.md
├── README.md
├── schema.sql
├── scripts/
│   └── foreman.py
└── tests/
    └── smoke-test.md
```

## Status

**Early v0.1 / active development.**

The core thesis is intentionally being tested before adding a large feature surface: **can serious agent work survive the death or replacement of the agent that started it?**

If the answer is yes, Foreman has a reason to exist.
