# Foreman v0.1 smoke test

The smoke test verifies the core durable-work contract without relying on an agent conversation.

## 1. Initialize

```bash
python3 scripts/foreman.py init
```

Expected: the local Foreman database is created at `~/.foreman/foreman.db`.

## 2. Create work

```bash
python3 scripts/foreman.py create \
  --title "Research fintech targets" \
  --objective "Identify qualified Series A fintech investment targets"
```

Save the returned task ID as `TASK_ID`.

## 3. Add ordered steps

```bash
python3 scripts/foreman.py add-step "$TASK_ID" --title "Define screening criteria"
python3 scripts/foreman.py add-step "$TASK_ID" --title "Identify candidate companies"
python3 scripts/foreman.py add-step "$TASK_ID" --title "Research qualifying companies"
```

## 4. Complete partial work

Complete the first two steps and verify that progress advances without marking the task complete.

```bash
python3 scripts/foreman.py complete-step "$TASK_ID" <STEP_ID_1> --result "Criteria defined"
python3 scripts/foreman.py complete-step "$TASK_ID" <STEP_ID_2> --result "Initial candidates identified"
python3 scripts/foreman.py context "$TASK_ID"
```

Expected compact context should show the original objective, the task still in progress, the remaining research step, meaningful progress, and a useful current/next step.

## 5. Record durable reasoning

```bash
python3 scripts/foreman.py decision "$TASK_ID" \
  --text "Exclude public companies and require ARR above $10M."

python3 scripts/foreman.py event "$TASK_ID" \
  --type SIGNIFICANT_FINDING \
  --severity meaningful \
  --summary "Initial candidate set contains several likely matches."
```

## 6. Attach an artifact

```bash
python3 scripts/foreman.py artifact "$TASK_ID" \
  --path /tmp/fintech-research.md \
  --description "Detailed candidate research"
```

The task should retain the reference without storing the entire artifact in task state.

## 7. Cross-agent handoff simulation

Stop the original agent/session. From a clean agent context, retrieve only the task context:

```bash
python3 scripts/foreman.py context "$TASK_ID"
```

The new agent should be able to identify what the project is trying to accomplish, what has already been completed, what remains, the important recorded decision, the meaningful recent event, and where the detailed artifact lives.

The new agent should **not** require the original conversation to determine the next action.

## 8. Completion

Complete the final step and retrieve context again.

Expected:

- progress reaches `1.0`;
- the task transitions to completed;
- completion is represented in durable state/event history.

## Battle-test cases

The following cases are required before treating the work layer as production-ready:

- retry the same completion operation;
- attempt to complete a nonexistent step;
- attempt invalid lifecycle transitions;
- kill an agent after a state-changing operation and resume;
- run two writers concurrently;
- interrupt work while an artifact is being produced;
- resume from another runtime using only Foreman state;
- verify blocked work cannot be reported as ready without the blocker being resolved.
