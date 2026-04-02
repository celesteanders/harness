# Agent Harness

Orchestration layer for implementing features, fixes, and improvements using Claude Code sessions.

## How It Works

```
User feedback --> Triage --> Clarify --> Plan --> Execute (TDD) --> Evaluate --> Done
```

Use the `/harness` skill interactively, or the headless runner for batch processing.

## Files

| File                | Purpose                                                   |
| ------------------- | --------------------------------------------------------- |
| `plans/{slug}.json` | Per-ticket plans with tasks and inline acceptance criteria |
| `progress.md`       | Session notes appended after each work session            |
| `runner.py`         | Headless executor + evaluator orchestrator                |
| `evaluator.py`      | Skeptical evaluator agent                                 |
| `eval_feedback/`    | Evaluator verdict JSONs                                   |

## Interactive (Skill)

The `/harness` skill guides the full workflow interactively:

1. Auto-detects feedback/bugs and enters triage mode
2. Clarifies requirements via AskUserQuestion
3. Creates a plan at `.harness/plans/{slug}.json`
4. Implements each task with TDD
5. Evaluates against inline acceptance criteria via subagent

```bash
# Trigger explicitly
/harness

# Or just paste feedback — the skill auto-detects and enters triage mode
```

## Headless Runner

The runner automates execute + evaluate loops for batch processing.

```bash
# Run next pending task
python3 .harness/runner.py --plan .harness/plans/fix-csv-naming.json

# Run all tasks sequentially
python3 .harness/runner.py --plan .harness/plans/fix-csv-naming.json --loop

# Run a specific task
python3 .harness/runner.py --plan .harness/plans/fix-csv-naming.json --task 2

# Preview what would run
python3 .harness/runner.py --plan .harness/plans/fix-csv-naming.json --dry-run

# Skip evaluator (faster, less safe)
python3 .harness/runner.py --plan .harness/plans/fix-csv-naming.json --skip-eval
```

### Runner pipeline per task

```
1. Find next pending task (respects depends_on ordering)
2. Mark task "in_progress", save plan
3. Launch claude -p with task prompt (includes TDD instructions + ACs)
4. Run verification command (lint + typecheck + test)
5. Run evaluator (skeptical review against acceptance criteria)
6. Mark task "complete", save plan
```

If any step fails, the task resets to "pending" and the runner exits with code 1. Up to 2 retry cycles per step.

## Evaluator

The evaluator spawns a separate Claude session that reviews completed work skeptically.

### What it checks

1. **Verification** — project verification command passes
2. **Acceptance criteria** — read from inline `acceptance_criteria` in plan
3. **Test coverage** — tests exist, are meaningful, cover edge cases
4. **No placeholders** — no `TODO`, `FIXME`, `pass`, `NotImplementedError`
5. **TDD compliance** — test files committed before/alongside implementation

### Usage

```bash
# Evaluate a specific task
python3 .harness/evaluator.py --plan .harness/plans/fix-csv.json --task 1
python3 .harness/evaluator.py --plan .harness/plans/fix-csv.json --task 1 --fix --verbose
```

## Setup

Before using the harness, configure these placeholders in the runner and evaluator:

1. **`VERIFY_CMD`** in `runner.py` — your project's verification command (e.g., `["make", "check"]`, `["npm", "test"]`)
2. **`CLAUDE_MD_PATH`** in `runner.py` — path to your project's CLAUDE.md (defaults to `CLAUDE.md`)
3. **Source directories** in evaluator prompts — adjust search paths to match your project structure

## Plan Format

Per-ticket plans use this structure:

```json
{
  "slug": "fix-csv-naming",
  "title": "Fix CSV download naming convention",
  "type": "bug",
  "created": "2026-03-26",
  "status": "planned",
  "context": "Why this work is needed",
  "tasks": [
    {
      "id": "1",
      "title": "Update filename format",
      "status": "pending",
      "acceptance_criteria": ["Filename follows DDMMYY HH:MM {Name} format"],
      "files": ["src/components/TableViewer.tsx"],
      "depends_on": []
    }
  ]
}
```

Plans are kept in `.harness/plans/` forever as historical record.
