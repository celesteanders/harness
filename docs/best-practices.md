# Best Practices for Building an Agent Harness

Consolidated from Anthropic, OpenAI, and community research on autonomous coding agent harnesses.

---

## 1. Architecture

### Use a multi-agent pattern with separated concerns

Split work across specialized agents rather than overloading a single agent. Common roles:

- **Planner** -- Expands a short prompt into a full product/feature spec. Focus on product context and high-level technical design, not granular implementation details. Over-specifying upfront causes cascading errors downstream.
- **Generator/Builder** -- Implements features one at a time against the spec. Works in focused increments.
- **Evaluator/QA** -- Tests the running application as a user would, grades output against criteria, and sends concrete feedback back to the generator for iteration.

The evaluator is critical because agents consistently rate their own work too generously. Separating generation from evaluation creates an honest feedback loop. Tuning a standalone evaluator to be skeptical is far more tractable than making a generator critical of its own work.

### Keep it monolithic until complexity demands otherwise

Start with a single-agent loop before reaching for multi-agent orchestration. Multi-agent systems introduce the same complexity as microservices, compounded by non-determinism. Only add agents when you hit a specific ceiling that a single agent cannot overcome.

### Fresh context windows per session (context resets)

Create a new client/context for each session rather than relying on compaction alone. Compaction preserves continuity but doesn't eliminate "context anxiety" (agents wrapping up prematurely as context fills). A full reset gives a clean slate, with structured handoff artifacts bridging the gap.

Note: More capable models (e.g., Opus 4.6) may handle long contexts well enough that compaction suffices and context resets become optional. Re-evaluate this as models improve.

---

## 2. State Management and Persistence

### Persist state in structured files, not in context

The agent's context window is ephemeral. Everything that must survive between sessions needs to be written to disk:

- **Task/feature list** (JSON, not Markdown) -- The single source of truth for what's done and what's remaining. JSON resists model-induced corruption better than freeform Markdown. Rules: never remove or reorder items, only flip status from incomplete to complete.
- **Progress notes** (free-form text) -- What was accomplished, bugs found/fixed, what to work on next, architectural decisions. Written at the end of each session.
- **Plan/spec file** -- The original requirements. Kept in the project directory so the agent can reference it.
- **Init/setup script** -- Automates environment setup so the agent doesn't waste context on installation.
- **Git history** -- Descriptive commits act as a recovery mechanism. The agent reads recent commits at session start to understand what changed.

### Use the repository as the system of record

Anything the agent can't access in-context effectively doesn't exist. Push all relevant knowledge into the repo: decisions from Slack threads, architectural patterns, product context. If it's not discoverable by the agent, it's illegible.

### AGENTS.md / CLAUDE.md should be a map, not an encyclopedia

Keep the top-level instruction file short (~100 lines). Use it as a table of contents pointing to deeper sources of truth in a structured `docs/` directory. A giant instruction file crowds out the task and rots quickly.

Structure knowledge for progressive disclosure: agents start with a small, stable entry point and are taught where to look, rather than being overwhelmed up front.

---

## 3. The Session Protocol

### Follow a consistent session lifecycle

Every session should follow a predictable sequence:

1. **Orient** -- Read progress notes, task list, recent git history
2. **Setup** -- Run init script to start dev servers / prerequisites
3. **Verify baseline** -- Test that existing functionality still works before touching anything new. The previous session may have introduced bugs.
4. **Select one task** -- Pick the highest-priority incomplete item
5. **Implement** -- Build the feature
6. **Test** -- Verify through the actual UI/API, not just unit tests
7. **Update state** -- Mark task complete, commit with descriptive message, write progress notes
8. **Clean exit** -- Confirm the application is in a working state

### One task per session

This prevents context exhaustion and keeps each session focused and recoverable. You may relax this as the project matures and the agent demonstrates reliability, but tighten it back if quality degrades.

### Verify before building

Always run baseline verification at the start of a session. Compounding bugs across sessions is one of the most common failure modes.

---

## 4. Feedback Loops and Backpressure

### Wire in automated verification as backpressure

Anything that can reject invalid output should be part of the loop: type checkers, linters, test suites, static analyzers, security scanners. The key constraint: the feedback wheel must turn fast. Slow verification (e.g., long compile times) reduces the number of iterations the agent can attempt.

After implementing functionality, immediately run tests for that specific unit of code.

### Use browser/UI automation for verification

Agents will mark features complete without actually testing them unless forced to interact with the running application. Use tools like Puppeteer or Playwright MCP to navigate, click, fill forms, and take screenshots. This catches bugs that backend-only testing misses.

### Build an evaluator with concrete grading criteria

Don't ask "is this good?" -- define specific, gradable criteria. For each criterion, provide:

- A clear definition of what good looks like
- Few-shot examples with score breakdowns for calibration
- Hard thresholds that trigger a failing grade

Weight criteria toward areas where the model is weakest (e.g., design originality, feature completeness) rather than areas it handles well by default (e.g., basic functionality, code correctness).

### Use sprint contracts for complex work

Before each implementation chunk, have the generator and evaluator negotiate what "done" looks like. The generator proposes what it will build and how success is verified; the evaluator reviews the proposal. This bridges the gap between high-level specs and testable implementation.

---

## 5. Context Window Management

### Treat context as a scarce resource

The more context you consume, the worse the outcomes. Strategies:

- **Offload expensive work to subagents** -- The primary context window should operate as a scheduler. Spawn subagents for file system searches, code analysis, test execution, and summarization.
- **Deterministically load the same core files each loop** -- Your plan and specifications should be loaded every iteration so the agent always has the same foundation.
- **Don't assume code doesn't exist** -- Code search (ripgrep) is non-deterministic. Instruct the agent to search before implementing to avoid duplicate implementations.

### Use subagents strategically

- Fan out subagents for read-only operations (search, analysis) with high parallelism
- Limit parallelism for write operations (build, test) to avoid backpressure issues
- Use subagents to summarize results rather than dumping raw output into the primary context

---

## 6. Prompt Engineering for Harnesses

### Prevent placeholder implementations

Agents are biased toward minimal/stub implementations because compiling code triggers their reward function. Explicitly instruct against placeholders and enforce full implementations. Use strong language if needed.

### Instruct agents to document their reasoning

When writing tests or making architectural decisions, have the agent capture the "why" in documentation or comments. Future iterations won't have the original reasoning in their context window, so these notes help the agent decide whether to keep, modify, or remove code.

### Allow the agent to self-improve its instructions

Permit the agent to update AGENTS.md / CLAUDE.md with learnings about how to build, test, and run the project. If the agent runs a command multiple times before finding the correct one, it should update the instructions so future loops don't repeat the mistake.

### Capture bugs immediately

When the agent discovers a bug (even unrelated to current work), it should document it in the plan/todo file immediately, then fix it or leave it for a future loop.

---

## 7. Security and Sandboxing

### Defense in depth with three layers

1. **OS-level sandbox** -- Isolate the agent's execution environment
2. **Filesystem restrictions** -- Limit file operations to the project directory
3. **Command allowlist** -- Only permit commands the agent needs. Parse commands with `shlex`, handle pipes/chaining, and block anything not explicitly allowed. Add validation for sensitive commands (e.g., `pkill` only for dev processes, `chmod` only for `+x`).

---

## 8. Code Quality and Architecture

### Enforce invariants mechanically, not through documentation alone

Use linters, structural tests, and CI checks to enforce architectural rules. Custom lint error messages should include remediation instructions so the agent can fix issues without human intervention.

Write lint rules as code so they apply everywhere at once. In an agent-generated codebase, encoded rules become multipliers.

### Treat technical debt like garbage collection

Run recurring cleanup agents that scan for deviations from "golden principles," update quality grades, and open targeted refactoring PRs. Pay down debt continuously in small increments rather than letting it compound.

### Optimize for agent legibility, not just human readability

Structure the codebase so agents can reason about the full business domain from the repository itself. Favor "boring" technologies (composable, stable APIs, well-represented in training data) over cutting-edge ones that are harder for agents to model.

### Make the application inspectable by agents

- Boot the app per git worktree so agents can run isolated instances
- Wire browser DevTools protocol into the agent runtime for DOM snapshots and screenshots
- Expose logs, metrics, and traces via queryable APIs (LogQL, PromQL) in ephemeral observability stacks

---

## 9. Recovery and Resilience

### Git is your safety net

- Commit after every successful task with descriptive messages
- Read recent git history at the start of each session
- Use git tags to mark known-good states
- When the agent produces a broken codebase, `git reset --hard` to the last good state and re-run

### Expect failures and plan for them

You will wake up to broken builds. The question is always: is it easier to reset and re-run, or to craft prompts to rescue the current state? Both are valid strategies.

### Regenerate the plan periodically

Todo lists and plans drift over time. Periodically delete and regenerate them by having the agent compare the current codebase against the specification. This prevents the agent from following stale or incorrect plans.

---

## 10. Evolving the Harness

### Re-evaluate harness complexity with each model upgrade

Every component in a harness encodes an assumption about what the model can't do on its own. These assumptions go stale as models improve. When a new model lands:

- Strip away scaffolding that's no longer load-bearing
- Add new components to achieve capabilities that weren't possible before
- Test by removing one component at a time and reviewing the impact

### The evaluator's value depends on task difficulty

The evaluator adds the most value when the task sits at or beyond the edge of what the generator can handle solo. For tasks well within the model's capability, it becomes unnecessary overhead. Calibrate accordingly.

### Start simple, add complexity only when needed

Find the simplest solution possible. Only increase complexity when you hit a specific, demonstrable ceiling. Three similar lines of code are better than a premature abstraction. A single-agent loop is better than a multi-agent system until the single agent provably fails.

---

## References

- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) -- Anthropic, Nov 2025
- [Ralph Wiggum as a "software engineer"](https://ghuntley.com/ralph/) -- Geoffrey Huntley, Jul 2025
- [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) -- Anthropic, Mar 2026
- [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/) -- OpenAI, Feb 2026

---

## Summary: The Core Principles

1. **Context windows are the constraint; structured artifacts are the solution.** Everything exists to bridge the gap between sessions.
2. **Separate generation from evaluation.** Agents can't objectively judge their own work.
3. **One task per session.** Focus prevents context exhaustion and keeps sessions recoverable.
4. **Verify before building.** Always check the previous session didn't break things.
5. **Wire in fast feedback loops.** Tests, linters, type checkers, and UI automation as backpressure.
6. **Repository is the single source of truth.** If it's not in the repo, it doesn't exist for the agent.
7. **Humans steer, agents execute.** Engineers design environments, specify intent, and build feedback loops. The agent writes the code.
8. **Expect eventual consistency.** Most issues can be resolved through more loops with better-tuned prompts.
9. **Simplify relentlessly.** Strip harness complexity that the model no longer needs. The interesting work moves, it doesn't shrink.
