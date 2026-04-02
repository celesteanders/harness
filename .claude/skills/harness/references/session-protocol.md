# Session Protocol

Follow this lifecycle for each task in a plan.

## 1. Orient

1. Read the plan file (`.harness/plans/{slug}.json`) for the current task
2. Read `.harness/progress.md` for prior session notes
3. Run `git log --oneline -10` for recent changes
4. Identify the next pending task — respect `depends_on` ordering

## 2. Verify Baseline

<!-- PLACEHOLDER: Replace with your project's verification command -->
Run your verification command before changing anything. If it fails, fix regressions first. Do not start new work on a broken baseline.

## 3. Implement

### Backend (TDD required)

1. **Write failing tests first** based on the task's `acceptance_criteria`
2. **Implement** the minimum code to make tests pass
3. **Refactor** if needed while keeping tests green
4. Run verification to confirm

### Frontend (no TDD)

Implement directly. Unit tests are only needed for complex logic (e.g., state machines, data transformations). No component or integration tests required.

### Rules

- **No placeholders.** Every function must be fully implemented, not stubbed with `pass` or `TODO`.
- **No temp files.** Keep artifacts in memory or use proper storage.
- **Search before implementing.** Check if similar code already exists with Grep/Glob.
- **One task per session.** Stay focused. Note unrelated bugs in progress.md.
- **Document reasoning.** Add comments explaining _why_, not _what_.

<!-- PLACEHOLDER: Add any project-specific rules below -->
<!-- Examples:
- **Config from architecture.** Follow `architecture.md` for schemas and models.
- **API contracts.** Read SDK source instead of web docs.
- **Response format.** Follow the formatting pipeline in `architecture.md`.
-->

## 4. Evaluate (mandatory — do NOT skip)

After verification passes, spawn an **evaluator subagent** before marking the task complete. See SKILL.md S5 for the subagent template and hard gate rules.

**Do NOT self-evaluate.** The executor is biased toward passing its own work. The subagent evaluates in a fresh context with no sunk-cost pressure.

- If the evaluator returns PASS -> proceed to step 5
- If the evaluator returns FAIL -> fix the flagged issues, re-run verification, spawn a new evaluator subagent. Max 2 retry cycles.

## 5. Update State

1. Mark the task `"complete"` in the plan JSON file — **only after evaluator PASS**
2. If all tasks are complete, set the plan's top-level `status` to `"complete"`
3. **Commit** — invoke the `/commit` skill to stage and commit all changes from the completed task.
4. Append session notes to `.harness/progress.md`

### Session Notes Format

```markdown
## YYYY-MM-DD - {slug}: Task {id} - {title}

- What was implemented
- Key decisions and why
- Evaluator verdict (PASS on first try / PASS after N retries / issues found)
- Bugs found (if any)
- What to work on next
```
