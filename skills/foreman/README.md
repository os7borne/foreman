# Foreman

**The skill that makes sure your agents don't drop the ball.**

Foreman is a portable, agent-agnostic work-management skill. v0.1 is deliberately small: a standard `SKILL.md` plus a deterministic SQLite persistence layer.

## Compatibility

- **OpenClaw:** native `SKILL.md` format and workspace skill layout.
- **Hermes Agent:** compatible `SKILL.md` format, including Hermes metadata.
- **Other AgentSkills-compatible hosts:** the core skill instructions are host-neutral. Hosts that cannot execute the bundled Python helper can substitute equivalent persistence tools.

OpenClaw skills use YAML frontmatter and a `SKILL.md`; skills may include supporting `references/`, `scripts/`, `assets/`, and other files. Hermes likewise supports `SKILL.md` plus supporting files.

## Install

### OpenClaw

Copy this directory into `<workspace>/skills/foreman/` and start a new session or refresh skills as appropriate.

### Hermes

Copy this directory into `~/.hermes/skills/foreman/` and start a new Hermes session.

## Persistence

By default the helper stores its SQLite database at `~/.foreman/foreman.db`. Override with `--db /path/to/foreman.db`.

## v0.1 scope

Included:

- durable tasks
- compact task context
- ordered steps
- deterministic progress calculation
- decisions
- events with severity
- artifact references
- status lifecycle
- search
- SQLite persistence
- plan/approval semantics in the skill

Intentionally deferred:

- remote sync
- multi-user concurrency
- native scheduler daemon
- agent-specific adapters
- web UI
- full dependency graph tooling
- recurring task execution engine
- automatic notification delivery

The next milestone is an adapter layer that lets Hermes and OpenClaw share the same Foreman work database and prove cross-agent handoff.
