#!/usr/bin/env python3
"""
Headless agent runner for the harness.

Orchestrates Claude Code sessions to implement tasks from per-ticket plans,
then runs verification and evaluation to ensure quality.

Usage:
    python .harness/runner.py --plan .harness/plans/fix-csv-naming.json
    python .harness/runner.py --plan .harness/plans/fix-csv-naming.json --loop
    python .harness/runner.py --plan .harness/plans/fix-csv-naming.json --task 2
    python .harness/runner.py --plan .harness/plans/fix-csv-naming.json --dry-run
    python .harness/runner.py --plan .harness/plans/fix-csv-naming.json --skip-eval
    python .harness/runner.py --plan .harness/plans/fix-csv-naming.json --eval-only 1
"""

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS_PATH = ROOT / ".harness" / "progress.md"
FEEDBACK_DIR = ROOT / ".harness" / "eval_feedback"

MAX_RETRIES = 2  # Max evaluator->generator retry cycles per task

# ---------------------------------------------------------------------------
# PLACEHOLDER: Configure these for your project
# ---------------------------------------------------------------------------

# Command to verify the project (lint + typecheck + test).
# Examples: ["make", "check"], ["npm", "test"], ["./scripts/verify.sh"]
VERIFY_CMD: list[str] = ["make", "check"]

# Path to your project's CLAUDE.md (relative to ROOT). Set to None if not used.
CLAUDE_MD_PATH: str | None = "CLAUDE.md"

# Source directories to reference in prompts (for developer orientation).
# Examples: ["src/", "lib/"], ["app/", "tests/"]
SOURCE_DIRS: list[str] = ["src/"]


# ---------------------------------------------------------------------------
# Plan I/O
# ---------------------------------------------------------------------------


def load_plan(plan_path: Path) -> dict:
    return json.loads(plan_path.read_text())


def save_plan(plan: dict, plan_path: Path) -> None:
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Task finding
# ---------------------------------------------------------------------------


def find_next_task(plan: dict, task_id: str | None = None):
    """Find next pending task. Returns (plan, task) or (None, None)."""
    for task in plan["tasks"]:
        if task_id and task["id"] != task_id:
            continue
        if task["status"] == "pending":
            # Check depends_on — all dependencies must be complete
            deps = task.get("depends_on", [])
            if deps:
                all_done = all(
                    any(
                        t["id"] == dep and t["status"] == "complete"
                        for t in plan["tasks"]
                    )
                    for dep in deps
                )
                if not all_done:
                    continue
            return plan, task
    return None, None


def find_task(plan: dict, task_id: str):
    """Find any task by ID."""
    for task in plan["tasks"]:
        if task["id"] == task_id:
            return plan, task
    return None, None


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_prompt(plan: dict, task: dict, plan_path: Path) -> str:
    """Build the prompt for a task."""
    ac_text = "\n".join(f"- {ac}" for ac in task.get("acceptance_criteria", []))
    files_text = "\n".join(f"- {f}" for f in task.get("files", []))

    claude_md_line = ""
    if CLAUDE_MD_PATH:
        claude_md_line = f"1. Read the {CLAUDE_MD_PATH} for project context and rules."

    verify_cmd_str = " ".join(VERIFY_CMD)

    return textwrap.dedent(
        f"""\
        You are implementing task {task["id"]}: {task["title"]}

        This is part of: {plan["title"]} ({plan["slug"]})
        Type: {plan["type"]}
        Context: {plan.get("context", "")}

        ## Acceptance Criteria

        {ac_text}

        ## Files likely affected

        {files_text}

        ## Instructions

        {claude_md_line}
        2. Read the plan at {plan_path.relative_to(ROOT)} to understand the full scope.
        3. Check git log --oneline -10 for recent changes.
        4. Run `{verify_cmd_str}` to verify the baseline is clean before starting.
        5. For backend changes: follow TDD — write failing tests first, then implement.
           For frontend changes: implement directly, unit tests only for complex logic.
        6. Run `{verify_cmd_str}` after implementation to verify everything passes.
        7. Mark task {task["id"]} as "complete" in {plan_path.relative_to(ROOT)}.
        8. Commit your changes with a descriptive message.
        9. Append session notes to .harness/progress.md.

        ## Task Focus

        Implement ONLY task {task["id"]}: {task["title"]}
        Do NOT work on other tasks. If you find bugs, note them in progress.md.
    """
    )


def build_fix_prompt(plan: dict, task: dict, feedback: dict, plan_path: Path) -> str:
    """Build fix prompt for evaluator feedback."""
    issues_text = "\n".join(f"- {issue}" for issue in feedback.get("issues", []))
    ac_text = "\n".join(f"- {ac}" for ac in task.get("acceptance_criteria", []))

    claude_md_line = ""
    if CLAUDE_MD_PATH:
        claude_md_line = f"1. Read {CLAUDE_MD_PATH} for project context."

    verify_cmd_str = " ".join(VERIFY_CMD)

    return textwrap.dedent(
        f"""\
        You are fixing issues flagged by the evaluator for task {task["id"]}: {task["title"]}

        This is part of: {plan["title"]} ({plan["slug"]})

        ## Evaluator Feedback

        The evaluator found the following issues:

        {issues_text}

        Verdict summary:
        - make_check: {feedback.get("make_check", "UNKNOWN")}
        - acceptance_criteria: {feedback.get("acceptance_criteria", "UNKNOWN")}
        - test_coverage: {feedback.get("test_coverage", "UNKNOWN")}
        - no_placeholders: {feedback.get("no_placeholders", "UNKNOWN")}

        ## Acceptance Criteria

        {ac_text}

        ## Instructions

        {claude_md_line}
        2. Read the plan at {plan_path.relative_to(ROOT)}.
        3. Fix EACH issue listed above. Do not skip any.
        4. Run `{verify_cmd_str}` to verify everything passes.
        5. Commit your fixes with a descriptive message.
        6. Append notes about what you fixed to .harness/progress.md.

        ## Task Focus

        Fix ONLY the issues listed above for task {task["id"]}: {task["title"]}
        Do NOT work on other tasks or refactor unrelated code.
    """
    )


def build_verify_fix_prompt(task: dict, check_output: str, context_name: str) -> str:
    """Build a prompt to fix verification failures."""
    # Truncate output to avoid blowing context — keep the tail where errors are
    max_chars = 4000
    if len(check_output) > max_chars:
        check_output = "...(truncated)...\n" + check_output[-max_chars:]

    claude_md_line = ""
    if CLAUDE_MD_PATH:
        claude_md_line = f"1. Read {CLAUDE_MD_PATH} for project context."

    verify_cmd_str = " ".join(VERIFY_CMD)

    return textwrap.dedent(
        f"""\
        You are fixing verification failures (`{verify_cmd_str}`) for task {task["id"]}: {task["title"]}

        This is part of {context_name}.

        ## Verification Output

        `{verify_cmd_str}` failed with the following output:

        ```
        {check_output}
        ```

        ## Instructions

        {claude_md_line}
        2. Analyze the errors above — identify which are lint, type, or test failures.
        3. Fix EACH failure. Common fixes:
           - Test failures: fix the implementation bug (not the test) unless the test is wrong.
           - Type errors: add or correct type annotations.
           - Lint errors: apply the formatting/style fix.
        4. Run `{verify_cmd_str}` to verify everything passes.
        5. Commit your fixes with a descriptive message.

        ## Task Focus

        Fix ONLY the `{verify_cmd_str}` failures for task {task["id"]}: {task["title"]}
        Do NOT work on other tasks or refactor unrelated code.
    """
    )


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def load_eval_feedback(task_id: str, slug: str | None = None) -> dict | None:
    """Load evaluator feedback for a task, if it exists."""
    if slug:
        feedback_path = FEEDBACK_DIR / f"{slug}_{task_id}.json"
        if feedback_path.exists():
            return json.loads(feedback_path.read_text())
    feedback_path = FEEDBACK_DIR / f"{task_id}.json"
    if feedback_path.exists():
        return json.loads(feedback_path.read_text())
    return None


def run_verification() -> tuple[bool, str]:
    """Run the verification command and return (passed, output)."""
    cmd_str = " ".join(VERIFY_CMD)
    print(f"\n── Verification: {cmd_str} ──")
    result = subprocess.run(
        VERIFY_CMD,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        print(output)
    return result.returncode == 0, output


def run_evaluator(
    task_id: str, plan_path: Path, auto_fix: bool = False, verbose: bool = False
) -> bool:
    """Run the evaluator agent against the completed task."""
    print(f"\n── Evaluator: task {task_id} ──")
    cmd = [sys.executable, str(ROOT / ".harness" / "evaluator.py"), "--task", task_id]
    cmd.extend(["--plan", str(plan_path)])
    if auto_fix:
        cmd.append("--fix")
    if verbose:
        cmd.append("--verbose")
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=False,
    )
    return result.returncode == 0


def run_claude_session(prompt: str) -> int:
    """Launch a headless Claude Code session with the given prompt."""
    print("\n── Launching Claude Code session ──")
    result = subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Bash,Read,Edit,Write,Glob,Grep"],
        cwd=ROOT,
        capture_output=False,
    )
    return result.returncode


def update_plan_status(plan: dict) -> None:
    """Update top-level status based on task completion."""
    tasks = plan.get("tasks", [])
    if all(t["status"] == "complete" for t in tasks):
        plan["status"] = "complete"
    elif any(t["status"] in ("in_progress", "complete") for t in tasks):
        plan["status"] = "in_progress"


def print_status(plan: dict) -> None:
    """Print current task status."""
    done = sum(1 for t in plan["tasks"] if t["status"] == "complete")
    total = len(plan["tasks"])
    status = "DONE" if done == total else f"{done}/{total}"
    print(f"  {plan['slug']}: {plan['title']} [{status}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Agent harness runner")
    parser.add_argument("--plan", required=True, help="Path to plan file")
    parser.add_argument("--task", help="Run a specific task by ID (e.g., 2)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run")
    parser.add_argument(
        "--skip-eval", action="store_true", help="Skip evaluator after task"
    )
    parser.add_argument(
        "--loop", action="store_true", help="Keep running tasks until done"
    )
    parser.add_argument(
        "--eval-only", metavar="TASK_ID", help="Run evaluator on a task (no build)"
    )
    parser.add_argument(
        "--fix", action="store_true", help="Allow evaluator to auto-fix issues"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Show full evaluator output"
    )
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path

    if not plan_path.exists():
        print(f"Plan file not found: {plan_path}")
        sys.exit(1)

    plan = load_plan(plan_path)

    # --eval-only: just run the evaluator on an existing task
    if args.eval_only:
        _, task = find_task(plan, args.eval_only)
        if not task:
            print(f"Task {args.eval_only} not found in plan.")
            sys.exit(1)
        passed = run_evaluator(
            args.eval_only, plan_path, auto_fix=args.fix, verbose=args.verbose
        )
        sys.exit(0 if passed else 1)

    while True:
        _, task = find_next_task(plan, task_id=args.task)
        context_name = f"{plan['title']} ({plan['slug']})"

        if not task:
            print("No pending tasks found.")
            break

        task_label = f"Task {task['id']}: {task['title']}"
        print(f"\n{'='*60}")
        print(task_label)
        print(f"Context: {context_name}")
        print(f"{'='*60}")

        if args.dry_run:
            print("\n[dry-run] Would execute this task. Prompt:")
            print(build_prompt(plan, task, plan_path))
            if not args.loop:
                break
            task["status"] = "complete"
            continue

        # Mark task as in progress
        task["status"] = "in_progress"
        save_plan(plan, plan_path)

        # Run the Claude session
        prompt = build_prompt(plan, task, plan_path)
        exit_code = run_claude_session(prompt)

        if exit_code != 0:
            print(f"\nClaude session exited with code {exit_code}")
            task["status"] = "pending"
            save_plan(plan, plan_path)
            sys.exit(1)

        # Run verification with retry loop
        verify_passed, check_output = run_verification()
        verify_retries = 0

        while not verify_passed and verify_retries < MAX_RETRIES:
            verify_retries += 1
            print(
                f"\n── Verify retry {verify_retries}/{MAX_RETRIES}: feeding output back to generator ──"
            )

            fix_prompt = build_verify_fix_prompt(task, check_output, context_name)
            fix_exit = run_claude_session(fix_prompt)
            if fix_exit != 0:
                print(f"\nFix session exited with code {fix_exit}")
                break

            verify_passed, check_output = run_verification()

        if not verify_passed:
            print(
                f"\nVerification still failing after {verify_retries} retries. Task NOT marked complete."
            )
            task["status"] = "pending"
            save_plan(plan, plan_path)
            sys.exit(1)

        # Run evaluator with retry loop
        if not args.skip_eval:
            eval_passed = run_evaluator(
                task["id"], plan_path, auto_fix=False, verbose=args.verbose
            )
            retries = 0
            slug = plan.get("slug")

            while not eval_passed and retries < MAX_RETRIES:
                retries += 1
                print(
                    f"\n── Retry {retries}/{MAX_RETRIES}: feeding evaluator issues back to generator ──"
                )

                feedback = load_eval_feedback(task["id"], slug=slug)
                if not feedback or not feedback.get("issues"):
                    print("No actionable feedback found. Cannot retry.")
                    break

                fix_prompt = build_fix_prompt(plan, task, feedback, plan_path)
                fix_exit = run_claude_session(fix_prompt)
                if fix_exit != 0:
                    print(f"\nFix session exited with code {fix_exit}")
                    break

                verify_ok, _ = run_verification()
                if not verify_ok:
                    print("\nVerification failed after fix attempt.")
                    break

                eval_passed = run_evaluator(
                    task["id"], plan_path, auto_fix=False, verbose=args.verbose
                )

            if not eval_passed:
                print(
                    f"\nEvaluator still failing after {retries} retries. Task NOT marked complete."
                )
                task["status"] = "pending"
                save_plan(plan, plan_path)
                sys.exit(1)

        # Mark complete
        task["status"] = "complete"
        update_plan_status(plan)
        save_plan(plan, plan_path)
        print(f"\nTask {task['id']} completed successfully.")

        # Reload plan in case the agent modified it
        plan = load_plan(plan_path)

        if not args.loop:
            break
        if args.task:
            break

    # Final status
    plan = load_plan(plan_path)
    print_status(plan)


if __name__ == "__main__":
    main()
