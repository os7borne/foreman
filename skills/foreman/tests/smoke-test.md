# Foreman v0.1 smoke test

1. Initialize the database.
2. Create a task.
3. Add three steps.
4. Complete two steps.
5. Record a decision.
6. Record a meaningful event.
7. Attach a research artifact.
8. Read `context`.
9. Confirm the context contains objective, progress, remaining step, decision, event, and artifact without requiring the original conversation.

## Cross-agent test

1. Start the task in Hermes.
2. Stop Hermes.
3. Open OpenClaw.
4. Ask OpenClaw to resume the task.
5. It should call Foreman context, understand the next action, and continue without replaying the prior chat.
