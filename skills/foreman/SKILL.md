---
name: foreman
description: Manage durable work so agents do not drop the ball.
version: 0.1.0
---

# Foreman

**Your agent may change. Your work shouldn't.**

Foreman is a portable work-management skill for AI agents. It keeps durable work state separate from the agent runtime so substantial work can be paused, resumed, handed off, and recovered across agents.

## Core loop

Understand → Plan → Confirm when necessary → Execute → Record → Report → Resume.

## Use Foreman when

Use it for work with multiple meaningful steps, dependencies, deadlines, recurring execution, multiple tools or agents, substantial research or creation, or likely pause/resume. Do not create durable work for trivial one-step questions unless the user explicitly asks.

## State discipline

Keep durable state compact: objective, status, progress, current step, next action, blockers, constraints, and key decisions. Keep substantial generated material in artifacts and store references to those artifacts. Do not inject full event history into context.

## Planning

Execute low-risk obvious work directly. For complex, consequential, expensive, ambiguous, recurring, or externally impactful work, present a compact plan and obtain plan approval unless the user has already authorized execution. Treat consequential external actions as requiring their own approval when appropriate.

## Recording

After meaningful work, update durable state and record important decisions, blockers, milestones, failures, and artifact references. Prefer deterministic state transitions and idempotent operations over free-form bookkeeping.

## Host neutrality

This skill is designed to run under AgentSkills-compatible hosts including OpenClaw and Hermes. Host-specific behavior belongs in adapter documentation, not in the core work model.
