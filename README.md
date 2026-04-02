# Agent Harness

A minimal harness for autonomous AI-driven software development with Claude Code. Implements the generator + evaluator pattern from [Anthropic](docs/research/260324_anthropic_harness_design.md), [OpenAI](docs/research/260211_openai_harness_engineering_codex.md), and [community](docs/research/250714_huntley_ralph_wiggum_technique.md) research.

## What it does

```
Feedback --> Triage --> Clarify --> Plan --> Execute (TDD) --> Evaluate --> Done
```

The harness decomposes work into structured plans, implements each task with test-driven development, then runs a skeptical evaluator agent that gates completion on acceptance criteria. Plans, progress, and evaluator verdicts are persisted as JSON so state survives context resets.

## Structure

```
.claude/skills/harness/    Claude Code skill (interactive workflow)
.harness/runner.py         Headless orchestrator (batch execution)
.harness/evaluator.py      Skeptical QA agent (separate session)
.harness/plans/            Per-ticket plans (JSON)
.harness/eval_feedback/    Evaluator verdicts (JSON)
.harness/progress.md       Session notes
docs/best-practices.md     Consolidated design principles
docs/research/             Source research papers
```

## Usage

### Interactive (skill)

Paste feedback or run `/harness` in Claude Code. The skill auto-detects bugs/features, clarifies requirements, creates a plan, implements with TDD, and evaluates.

### Headless (runner)

```bash
# Run next pending task
python3 .harness/runner.py --plan .harness/plans/{slug}.json

# Run all tasks
python3 .harness/runner.py --plan .harness/plans/{slug}.json --loop

# Run a specific task
python3 .harness/runner.py --plan .harness/plans/{slug}.json --task 2

# Skip evaluator (faster, less safe)
python3 .harness/runner.py --plan .harness/plans/{slug}.json --skip-eval
```

## Setup

Configure these in `runner.py` and `evaluator.py` for your project:

1. **`VERIFY_CMD`** -- your project's verification command (e.g., `["make", "check"]`)
2. **`CLAUDE_MD_PATH`** -- path to your project's `CLAUDE.md`
3. **Source directories** -- adjust search paths in evaluator prompts

## Key design decisions

- **Separate evaluator session** -- agents grade their own work too generously. A skeptical evaluator in a fresh context provides honest feedback.
- **JSON plans, not Markdown** -- structured state survives context resets and is machine-parseable.
- **Git as safety net** -- commit after every successful task. Recovery is always one `git reset` away.
- **Acceptance criteria as contract** -- every task has testable ACs that the evaluator checks mechanically.
- **Max 2 retry cycles** -- if a task fails evaluation twice, the runner exits rather than looping forever.

See [docs/best-practices.md](docs/best-practices.md) for the full set of consolidated principles.

## Research

| Document                                                                                             | Source           |
| ---------------------------------------------------------------------------------------------------- | ---------------- |
| [Harness Design (Mar 2026)](docs/research/260324_anthropic_harness_design.md)                        | Anthropic        |
| [Effective Harnesses (Nov 2025)](docs/research/251126_anthropic_effective_harnesses.md)              | Anthropic        |
| [Harness Engineering for Codex (Feb 2026)](docs/research/260211_openai_harness_engineering_codex.md) | OpenAI           |
| [The Ralph Wiggum Technique (Jul 2025)](docs/research/250714_huntley_ralph_wiggum_technique.md)      | Geoffrey Huntley |
