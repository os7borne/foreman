# Foreman contract test

The contract test verifies the durable-work handoff behavior independently of an agent conversation.

## Required behavior

1. Initialize a Foreman database.
2. Create a multi-step work item.
3. Complete some, but not all, steps.
4. Record a decision and meaningful event.
5. Attach a substantial output as an artifact reference.
6. Stop the original agent/session.
7. From a clean agent context, retrieve compact Foreman context.
8. Confirm the new agent can determine the objective, completed work, remaining work, decision, and artifact location without replaying the original conversation.
9. Complete the remaining work and verify the task reaches completion.

## Battle-test cases

Before calling the durable work layer production-ready, also test:

- retrying the same completion operation;
- completing a nonexistent step;
- invalid lifecycle transitions;
- agent crash immediately after a state-changing operation;
- concurrent writers;
- interruption during artifact creation;
- handoff between two different runtimes;
- blocked work becoming ready only after its blocker is resolved.
