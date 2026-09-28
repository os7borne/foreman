# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the major version is `0`, the public surface (CLI flags, `foreman_core`
function signatures, schema) is not yet stable — a minor bump may still
include breaking changes. Once the Phase 3 adapter work lands and the API
is considered stable, `1.0.0` will be cut and that will change.

The authoritative current version lives in `skills/foreman/SKILL.md`'s
frontmatter (`version:`); this file records what changed at each version.

## [Unreleased]

## [0.2.0] - 2026-09-28

### Added
- Lifecycle state machine (`ALLOWED_TRANSITIONS` / `validate_transition` in
  `foreman_core.py`) — invalid transitions such as `completed -> running`
  are now rejected.
- Idempotent `complete-step` — safe to retry, no duplicate events, never
  resurrects a terminal or blocked task's status.
- WAL mode, `busy_timeout`, and `BEGIN IMMEDIATE` transactions for
  concurrent writers.
- Automatic maintenance of `started_at` / `completed_at` /
  `current_step_id` / `blocked_reason`, no longer left to caller discipline.
- `pause` / `resume` / `cancel` operations; `resume` re-checks dependencies
  before allowing a transition back into `running`.
- The `dependencies` table is now live: `add-dependency` / `remove-dependency`
  auto-block and auto-unblock the dependent task, reject direct and
  transitive cycles (via BFS), and never treat a cancelled/failed
  dependency as satisfied.
- Duplicate/similar-task detection before `create`: `SKILL.md` now instructs
  the agent to `search` for related existing work before creating a new
  task, and to ask the user to resume/update/or treat it as separate rather
  than silently creating a duplicate.
- `description` column on tasks wired up end-to-end (`create_work` /
  CLI `--description`) — it existed in `schema.sql` but no code path ever
  set it.
- `search_work` now also matches `description` (not just `title`/
  `objective`) and returns `objective` / `blocked_reason` directly, so an
  agent can summarize a candidate task without a follow-up `context` call.

### Changed
- All logic extracted from the CLI into `skills/foreman/scripts/foreman_core.py`,
  an importable library of plain functions (`create_work`, `get_context`,
  `update_work`, `complete_step`, `add_dependency`, `pause_work`, etc.).
  `foreman.py` is now a thin argparse wrapper over it, so any future
  consumer (adapter, MCP server) can import `foreman_core` directly instead
  of shelling out.

### Testing
- 40 automated tests (stdlib `unittest`, no third-party deps) in
  `skills/foreman/tests/test_foreman.py`, all passing.

## [0.1.0] - 2026-09-06

### Added
- Initial prototype: task/step/decision/event/artifact schema and a basic
  CLI (`skills/foreman/scripts/foreman.py`).
- SQLite persistence, task lifecycle and status, ordered work steps,
  progress tracking, compact task context, decisions, events, artifact
  references, basic dependencies in the schema, task search and listing.
- Agent Skills-compatible `SKILL.md`, OpenClaw-compatible skill layout,
  Hermes-compatible installation model.

[Unreleased]: https://github.com/os7borne/foreman/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/os7borne/foreman/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/os7borne/foreman/releases/tag/v0.1.0
