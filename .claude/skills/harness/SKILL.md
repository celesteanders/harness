---
name: harness
description: |
  Plan and execute feature requests, bug fixes, and improvements using the agent harness.
  Auto-detect when the user shares feedback, bug reports, or feature requests and enter
  triage mode automatically. Create per-ticket plans with acceptance criteria, then use
  the executor + evaluator pattern to implement and verify each task.
  TRIGGER when: user shares feedback, bug reports, feature requests, improvement ideas,
  or says /harness.
---

# Agent Harness

Turn feedback, bugs, and feature requests into verified implementations via structured planning and TDD.

```
Intake --> Triage --> Clarify --> Plan --> Execute --> Evaluate
```

## Workflow

### 1. Intake & Triage

Read all feedback items before acting. For each item:

1. Categorize: `bug` | `feature` | `improvement` | `chore`
2. Identify dependencies between items
3. Propose priority order: bugs first, then blocking items, then small wins, then large efforts
4. Present the triage as a numbered list with category, priority, and rationale

### 2. Clarify

Use the `AskUserQuestion` tool to interrogate the user with clarifying questions to turn vague feedback into testable requirements.

- Batch related questions (max 4 per call)
- Provide concrete options — don't make the user think from scratch
- Use previews for UI questions (ASCII mockups)
- One round is usually enough. Two max.
- Skip clarification when the requirement is already specific or the answer is obvious from the codebase

### 3. Plan

Create `.harness/plans/{slug}.json`. See [references/plan-format.md](references/plan-format.md) for the schema.

- Auto-generate slug from description: lowercase, hyphenated, max 40 chars
- Include `acceptance_criteria` on every task — the evaluator reads them
- Each task should be completable in one focused session
- Print a summary of all tasks with ACs for user review

### 4. Execute

For each pending task, follow the session protocol. See [references/session-protocol.md](references/session-protocol.md).

Summary:

1. Orient — read plan, progress notes, recent git history
2. Verify baseline — run the verification command before changing anything
3. Implement — backend: TDD (write failing tests first, then implement). Frontend: implement directly, unit tests only for complex logic.
4. Run verification to confirm implementation
5. **Evaluate** — spawn evaluator subagent (see S5). This is a hard gate.
6. Update state — mark task complete **only after evaluator returns PASS**, commit using `/commit`, append to progress.md

### 5. Evaluate (mandatory — subagent)

After implementing each task, you MUST spawn a subagent to evaluate the work before marking the task complete. Do NOT self-evaluate — the executor is biased toward passing its own work.

**How to spawn the evaluator:**

Use the Agent tool to launch a general-purpose subagent with this prompt template:

```
You are a skeptical code evaluator. Your job is to find problems, not praise.

Follow the evaluation steps in .claude/skills/harness/references/evaluator-guide.md exactly.

Evaluate task {task_id}: "{task_title}" from plan .harness/plans/{slug}.json

Do NOT fix anything. Only read code, run the verification command, and produce a VERDICT.
```

**Hard gate rules:**

- Do NOT mark a task complete until the evaluator subagent returns `OVERALL: PASS`
- If the evaluator returns `OVERALL: FAIL`, fix the issues it identified, then spawn a **new** evaluator subagent to re-evaluate
- Maximum 2 retry cycles (implement -> evaluate -> fix -> evaluate -> fix -> evaluate). If still failing after 2 retries, stop and ask the user
- The evaluator subagent must NOT have write access — it is read-only + Bash (for verification)

## Headless Runner

Automate the execute + evaluate loop for batch processing:

```bash
# Run next pending task from a specific plan
python3 .harness/runner.py --plan .harness/plans/{slug}.json

# Run all tasks in a plan
python3 .harness/runner.py --plan .harness/plans/{slug}.json --loop

# Run a specific task
python3 .harness/runner.py --plan .harness/plans/{slug}.json --task 2

# Dry run
python3 .harness/runner.py --plan .harness/plans/{slug}.json --dry-run
```

## File Locations

| File                         | Purpose                                    |
| ---------------------------- | ------------------------------------------ |
| `.harness/plans/{slug}.json` | Per-ticket plan with tasks and inline ACs  |
| `.harness/progress.md`       | Session notes across all work              |
| `.harness/runner.py`         | Headless executor + evaluator orchestrator |
| `.harness/evaluator.py`      | Skeptical evaluator agent                  |
| `.harness/eval_feedback/`    | Evaluator verdict JSONs                    |
