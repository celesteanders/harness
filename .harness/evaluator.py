#!/usr/bin/env python3
"""
Evaluator agent for the harness.

Spawns a *separate* Claude Code session that reviews the implementation of a
completed task against acceptance criteria. Designed to be skeptical — the
evaluator's job is to find problems, not to praise.

Usage:
    python .harness/evaluator.py --plan .harness/plans/fix-csv.json --task 1
    python .harness/evaluator.py --plan .harness/plans/fix-csv.json --task 1 --fix
    python .harness/evaluator.py --plan .harness/plans/fix-csv.json --task 1 --verbose
"""

import argparse
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_DIR = ROOT / ".harness" / "eval_feedback"

# ---------------------------------------------------------------------------
# PLACEHOLDER: Configure these for your project
# ---------------------------------------------------------------------------

# Command to verify the project (must match runner.py's VERIFY_CMD).
VERIFY_CMD: list[str] = ["make", "check"]

# Source directories to search when evaluating (adjust to your project).
# Examples: ["src/", "lib/"], ["app/", "packages/"]
SOURCE_DIRS: list[str] = ["src/"]


def load_plan(plan_path: Path) -> dict:
    return json.loads(plan_path.read_text())


def find_task(plan: dict, task_id: str):
    """Find a task by ID. Returns (plan, task) or (None, None)."""
    for task in plan["tasks"]:
        if task["id"] == task_id:
            return plan, task
    return None, None


def build_ac_section(task: dict) -> str:
    """Build AC section from inline acceptance_criteria."""
    acs = task.get("acceptance_criteria", [])
    if not acs:
        return textwrap.dedent(
            """\
            ## Acceptance Criteria

            This task has no explicit acceptance criteria.
            Evaluate based on the task title, implementation quality, and test coverage.
        """
        )

    ac_list = "\n".join(f"- {ac}" for ac in acs)
    return textwrap.dedent(
        f"""\
        ## Acceptance Criteria to Verify

        This task must satisfy the following criteria:
        {ac_list}

        For EACH criterion listed above:
        1. Find the code that implements it (use Grep to search for relevant functions)
        2. Find the test(s) that verify it
        3. Determine PASS or FAIL based on whether the implementation fully satisfies the AC
    """
    )


def build_eval_prompt(plan: dict, task: dict, auto_fix: bool) -> str:
    """Build the evaluator prompt with skepticism calibration."""
    ac_section = build_ac_section(task)
    context_line = f"This is part of: {plan['title']} ({plan['slug']})"
    source_dirs_str = ", ".join(f"`{d}`" for d in SOURCE_DIRS)
    verify_cmd_str = " ".join(VERIFY_CMD)

    fix_section = ""
    if auto_fix:
        fix_section = textwrap.dedent(
            """
            ## Auto-Fix Mode

            If you find issues, fix them directly:
            1. Edit the code to resolve the issue
            2. Update or add tests as needed
            3. Run the verification command to verify your fix
            4. Commit the fix with a descriptive message

            After fixing, re-evaluate and produce the final verdict.
        """
        )

    return textwrap.dedent(
        f"""\
        You are a skeptical code evaluator. Your job is to find problems in the
        implementation of task {task["id"]}: {task["title"]}

        {context_line}

        ## Your Mindset

        You are NOT the implementer. You are the reviewer. Your default assumption
        is that things are probably wrong or incomplete until you verify otherwise.
        The implementer is biased toward marking things complete — your job is to
        catch what they missed.

        Common problems to watch for:
        - Tests that pass but don't actually verify the acceptance criteria
        - Tests that mock so aggressively they don't test real behavior
        - Functions that exist but aren't wired into the actual request flow
        - Stub implementations hidden behind interfaces that look complete
        - Missing error handling paths that the AC specifies

        ## Evaluation Steps

        Do these IN ORDER. Do not skip steps.

        ### Step 1: Run `{verify_cmd_str}`
        Run `{verify_cmd_str}` and record whether it passes.

        ### Step 2: Read the implementation
        Find and read the source files for this task. Use Grep to search in {source_dirs_str}.

        ### Step 3: Check for placeholders
        Grep for `TODO`, `FIXME`, `pass`, `...` (Ellipsis), `NotImplementedError`
        in the implementation files. Any of these is an automatic FAIL.

        ### Step 4: Verify acceptance criteria
        {ac_section}
        ### Step 5: Assess test quality
        Read the test files. For each test, ask:
        - Does this test actually verify the behavior, or just that code runs without error?
        - Are assertions specific (checking exact values) or vague (just `assert result`)?
        - Are edge cases covered (empty input, error conditions, boundary values)?

        ### Step 6: Check TDD compliance
        Run: `git log --oneline --name-only -5`
        Check whether test files were modified in commits BEFORE or ALONGSIDE
        implementation files. If implementation was committed without corresponding
        tests, note this as a TDD violation (warning, not automatic FAIL).

        ## Output Format

        You MUST end your response with EXACTLY this format (the verdict block).
        Everything above it can be free-form analysis.

        ```
        VERDICT
        task: {task["id"]}
        title: {task["title"]}

        make_check: PASS|FAIL
        acceptance_criteria: PASS|FAIL|N/A
        test_coverage: PASS|FAIL
        no_placeholders: PASS|FAIL
        tdd_compliance: PASS|WARN|FAIL

        ac_checklist:
        - [x] AC text: brief reason (PASS)
        - [ ] AC text: what's missing (FAIL)

        issues:
        - issue 1 description
        - issue 2 description

        OVERALL: PASS|FAIL
        ```

        ## Scoring Rules

        - OVERALL is FAIL if ANY of: make_check, acceptance_criteria, test_coverage,
          or no_placeholders is FAIL.
        - tdd_compliance WARN does not cause overall FAIL but should be noted.
        - If acceptance_criteria is N/A (infrastructure task), it doesn't affect overall.
        - When in doubt, FAIL. It is better to flag a false positive than to miss a real issue.

        ## Few-shot Examples of FAIL Verdicts

        Example 1 — Test exists but doesn't verify the AC:
        ```
        - [ ] AC: "On error, return 400 status" (FAIL — test mocks the error handler
              and checks it was called, but doesn't verify the status code)
        ```

        Example 2 — Function exists but isn't wired in:
        ```
        - [ ] AC: "Paginate results for lists over 100" (FAIL — paginate() exists
              and is tested in isolation, but the route handler never calls it.
              The function is dead code.)
        ```

        Example 3 — Placeholder hiding behind interface:
        ```
        no_placeholders: FAIL
        issues:
        - src/services/manager.py:broadcast() contains `pass` — event broadcasting
          is not implemented, just stubbed.
        ```
        {fix_section}
    """
    )


def parse_verdict(output: str) -> dict:
    """Parse the VERDICT block from evaluator output."""
    verdict_match = re.search(
        r"VERDICT\s*\n(.+?)$",
        output,
        re.DOTALL,
    )
    if not verdict_match:
        return {
            "overall": "FAIL",
            "parse_error": "Could not find VERDICT block in evaluator output",
        }

    verdict_text = verdict_match.group(1)

    overall_match = re.search(r"OVERALL:\s*(PASS|FAIL)", verdict_text)
    overall = overall_match.group(1) if overall_match else "FAIL"

    result: dict = {"overall": overall}
    for field in [
        "make_check",
        "acceptance_criteria",
        "test_coverage",
        "no_placeholders",
        "tdd_compliance",
    ]:
        match = re.search(rf"{field}:\s*(PASS|FAIL|WARN|N/A)", verdict_text)
        result[field] = match.group(1) if match else "UNKNOWN"

    issues: list[str] = []
    issues_match = re.search(r"issues:\s*\n((?:- .+\n?)+)", verdict_text)
    if issues_match:
        issues = [
            line.strip("- ").strip()
            for line in issues_match.group(1).strip().split("\n")
            if line.strip().startswith("-")
        ]
    result["issues"] = issues

    return result


def print_verdict(verdict: dict, task_id: str, verbose: bool, raw_output: str) -> None:
    """Print a formatted verdict summary."""
    if verbose:
        print(raw_output)
        print()

    overall = verdict["overall"]
    icon = "PASS" if overall == "PASS" else "FAIL"
    print(f"\n{'='*50}")
    print(f"  Evaluator Verdict: {icon}  (task {task_id})")
    print(f"{'='*50}")

    for field in [
        "make_check",
        "acceptance_criteria",
        "test_coverage",
        "no_placeholders",
        "tdd_compliance",
    ]:
        val = verdict.get(field, "UNKNOWN")
        mark = (
            "[ok]"
            if val in ("PASS", "N/A")
            else "[!!]" if val == "FAIL" else "[??]" if val == "UNKNOWN" else "[~~]"
        )
        print(f"  {mark} {field}: {val}")

    issues = verdict.get("issues", [])
    if issues:
        print(f"\n  Issues ({len(issues)}):")
        for issue in issues:
            print(f"    - {issue}")

    if "parse_error" in verdict:
        print(f"\n  Parse error: {verdict['parse_error']}")

    print()


def main():
    parser = argparse.ArgumentParser(description="Agent harness evaluator")
    parser.add_argument(
        "--task", required=True, help="Task ID to evaluate (e.g., 1)"
    )
    parser.add_argument("--plan", required=True, help="Path to plan file")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues found")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full evaluator output",
    )
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path

    if not plan_path.exists():
        print(f"Plan file not found: {plan_path}")
        sys.exit(1)

    plan = load_plan(plan_path)
    _, task = find_task(plan, args.task)

    if not task:
        print(f"Task {args.task} not found in plan.")
        sys.exit(1)

    print(f"\n── Evaluating task {task['id']}: {task['title']} ──")

    prompt = build_eval_prompt(plan, task, auto_fix=args.fix)

    allowed_tools = "Bash,Read,Glob,Grep"
    if args.fix:
        allowed_tools += ",Edit,Write"

    result = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--allowedTools",
            allowed_tools,
            "--output-format",
            "text",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    raw_output = result.stdout or ""
    if result.returncode != 0:
        print(f"Claude session failed (exit code {result.returncode})")
        if result.stderr:
            print(result.stderr)
        sys.exit(1)

    verdict = parse_verdict(raw_output)
    print_verdict(verdict, args.task, verbose=args.verbose, raw_output=raw_output)

    # Persist feedback
    FEEDBACK_DIR.mkdir(exist_ok=True)
    feedback_path = FEEDBACK_DIR / f"{plan['slug']}_{args.task}.json"
    feedback_path.write_text(json.dumps(verdict, indent=2) + "\n")

    if verdict["overall"] == "PASS":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
