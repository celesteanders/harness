# Evaluator Guide

The evaluator reviews completed work with a skeptical mindset. Its job is to find problems, not praise.

## Evaluation Steps

Do these in order. Do not skip steps.

### Step 1: Run verification

<!-- PLACEHOLDER: Replace with your project's verification command (e.g., make check, npm test, ./scripts/verify.sh) -->
Run your project's verification command and record whether it passes. This is a hard gate.

### Step 2: Read the implementation

Find and read the source files for the task:

<!-- PLACEHOLDER: Adjust search paths to match your project structure (e.g., src/, lib/, app/) -->
- Use Grep to search for relevant functions in the source directories
- Cross-reference with the task's `files` hints in the plan

### Step 3: Check for placeholders

Grep for `TODO`, `FIXME`, `pass`, `...` (Ellipsis), `NotImplementedError` in implementation files. Any of these is an automatic FAIL.

### Step 4: Verify acceptance criteria

For EACH criterion in the task's `acceptance_criteria`:

1. Find the code that implements it
2. Find the test(s) that verify it
3. Determine PASS or FAIL based on whether the implementation fully satisfies the AC

### Step 5: Assess test quality

For each test, ask:

- Does it actually verify the behavior, or just that code runs without error?
- Are assertions specific (checking exact values) or vague (`assert result`)?
- Are edge cases covered (empty input, error conditions, boundary values)?

### Step 6: Check TDD compliance

Run `git log --oneline --name-only -5`. Check whether test files were modified before or alongside implementation. TDD violation is a warning, not automatic FAIL.

## Verdict Format

```
VERDICT
task: {id}
title: {title}

make_check: PASS|FAIL
acceptance_criteria: PASS|FAIL|N/A
test_coverage: PASS|FAIL
no_placeholders: PASS|FAIL
tdd_compliance: PASS|WARN|FAIL

ac_checklist:
- [x] AC text here (PASS)
- [ ] AC text here (FAIL - what's missing)

issues:
- issue 1 description
- issue 2 description

OVERALL: PASS|FAIL
```

## Scoring Rules

- OVERALL is FAIL if ANY of: make_check, acceptance_criteria, test_coverage, or no_placeholders is FAIL
- tdd_compliance WARN does not cause overall FAIL
- When in doubt, FAIL — better to flag a false positive than miss a real issue

## Common FAIL Patterns

**Test exists but doesn't verify the AC:**

```
- [ ] AC: "On error, return 400 status" (FAIL - test mocks the error handler
      and checks it was called, but doesn't verify the status code)
```

**Function exists but isn't wired in:**

```
- [ ] AC: "Split long responses into pages" (FAIL - paginate() exists and is
      tested, but the route handler never calls it. Dead code.)
```

**Placeholder hiding behind interface:**

```
no_placeholders: FAIL
issues:
- src/services/manager.py:broadcast() contains `pass` - not implemented
```
