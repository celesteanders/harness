# Effective Harnesses for Long-Running Agents

*Published Nov 26, 2025*

A consolidated guide for building harnesses that enable autonomous agents to work across multiple sessions on complex, multi-step features. Based on Anthropic's [engineering blog post](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) and their [reference implementation](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding).

---

## 1. Core Architecture: The Two-Agent Pattern

Split the work into two distinct agent roles, each with its own prompt:

| Agent            | When                   | Purpose                                                                    |
| ---------------- | ---------------------- | -------------------------------------------------------------------------- |
| **Initializer**  | Session 1 only         | Setup environment, generate feature list, create scripts, init git         |
| **Coding Agent** | Session 2+ (recurring) | Pick up where last session left off, implement one feature, verify, commit |

The initializer runs once. Every subsequent session uses the coding agent prompt with a fresh context window, relying on persisted artifacts to re-establish context.

```
Session 1: Initializer → creates feature_list.json, init.sh, git repo
Session 2: Coding Agent → reads state, implements feature, commits
Session 3: Coding Agent → reads state, implements feature, commits
...
Session N: Coding Agent → all features passing, done
```

---

## 2. Persisted Artifacts (State That Survives Context Windows)

These files are the bridge between sessions. The agent reads them at the start of every session to understand what's done, what's broken, and what's next.

### 2.1 Feature List (`feature_list.json`)

The single source of truth. JSON format (not Markdown -- prevents model-induced corruption).

```json
[
  {
    "id": 1,
    "category": "Core Chat",
    "description": "Send a message and receive a streaming response",
    "verification_steps": [
      "Open the app",
      "Type a message in the input field",
      "Click send",
      "Verify response streams in real-time"
    ],
    "passes": false
  }
]
```

Rules enforced in prompts:

- **Never remove or edit test descriptions** -- only flip `"passes": false` to `true`
- **Never reorder, combine, or restructure** the list
- Initialize all features as `"passes": false`
- Aim for 200+ features for complex apps (reduce for faster demos)

### 2.2 Progress File (`claude-progress.txt`)

Free-form notes the agent writes at the end of each session:

- What was accomplished
- What bugs were found/fixed
- What to work on next
- Any architectural decisions made

### 2.3 Init Script (`init.sh`)

Automates environment setup so the agent doesn't waste context on installation:

```bash
#!/bin/bash
npm install
npm run dev &
sleep 3
echo "Server running at http://localhost:3000"
```

### 2.4 Git History

Descriptive commits act as a recovery mechanism:

- Agent reads the last 20 commits at session start
- Enables quick understanding of recent changes
- Allows reverting failed sessions

### 2.5 App Specification (`app_spec.txt`)

The original requirements document. Copied into the project directory so the agent can reference it.

---

## 3. Session Protocol

Every coding agent session follows this exact sequence:

```
1. pwd                          → verify working directory
2. Read claude-progress.txt     → understand what happened last
3. Read feature_list.json       → find incomplete features
4. git log --oneline -20        → understand recent changes
5. ./init.sh                    → start dev server
6. Run baseline verification    → catch regressions from previous session
7. Select highest-priority incomplete feature
8. Implement the feature
9. Verify through browser UI    → not just backend tests
10. Update feature_list.json    → flip passes to true
11. git commit                  → descriptive message
12. Update claude-progress.txt  → notes for next session
13. Verify clean state          → app still works, no console errors
```

The verification step (#6) before implementation is critical: **the previous session may have introduced bugs**.

---

## 4. Prompt Templates

### 4.1 Initializer Prompt

Purpose: Run once to set up the project scaffolding.

```markdown
You are an expert full-stack developer setting up a new project.

Read `app_spec.txt` in your working directory for the application specification.

Your tasks:

1. Create `feature_list.json` with minimum 200 features covering all spec
   requirements. Each feature must have: id, category, description,
   verification_steps (array), and passes (set to false).

2. Create `init.sh` that installs dependencies and starts the dev server.
   Make it executable with chmod +x.

3. Initialize a git repository with an initial commit containing all setup files.

4. Create the initial project structure based on the spec.

5. Create `claude-progress.txt` documenting what you set up.

CRITICAL RULES:

- Features in feature_list.json must NEVER be removed or edited after creation.
  They can only be marked as passes: true after verification.
- Use JSON format for the feature list, not Markdown.
- The feature list is the authoritative specification -- it should comprehensively
  cover every requirement in the app spec.
```

### 4.2 Coding Agent Prompt

Purpose: Run every session after initialization.

```markdown
You are an expert full-stack developer continuing work on an application.

## Orientation Phase

1. Run `pwd` to verify your working directory
2. Read `claude-progress.txt` for context from previous sessions
3. Read `feature_list.json` to see all features and their status
4. Run `git log --oneline -20` to see recent changes
5. Run `./init.sh` to start the development server

## Verification Phase

The previous session may have introduced bugs. Before implementing anything new,
verify that core functionality still works:

- Test through the browser UI (not just API calls)
- Take screenshots to verify visual state
- Check for console errors

## Implementation Phase

- Select ONE incomplete feature (passes: false) to implement
- Implement it fully with tests
- Verify through the browser UI with actual clicks and keyboard input
- Only mark passes: true AFTER successful verification

## Wrap-Up Phase

- Create a descriptive git commit
- Update claude-progress.txt with:
  - What you accomplished
  - Any bugs found/fixed
  - Recommendations for next session
- Verify the application is in a clean, working state

CRITICAL RULES:

- Work on ONE feature per session maximum
- NEVER remove, edit, combine, or reorder features in feature_list.json
- Only change the "passes" field from false to true
- Always test through browser UI, not just backend
- Leave the codebase in a clean, mergeable state
```

---

## 5. The Agentic Loop (Harness Code)

The outer loop manages sessions. Key implementation details:

```python
async def run_autonomous_agent(project_dir, model, max_iterations=None):
    project_dir.mkdir(parents=True, exist_ok=True)

    # Determine if first run
    is_first_run = not (project_dir / "feature_list.json").exists()

    if is_first_run:
        copy_spec_to_project(project_dir)

    iteration = 0
    while True:
        iteration += 1
        if max_iterations and iteration > max_iterations:
            break

        # Fresh client = fresh context window each session
        client = create_client(project_dir, model)

        # Choose prompt
        if is_first_run:
            prompt = load_prompt("initializer_prompt")
            is_first_run = False  # Only use initializer once
        else:
            prompt = load_prompt("coding_prompt")

        # Run session
        async with client:
            status, response = await run_agent_session(client, prompt, project_dir)

        # Auto-continue with small delay
        print_progress_summary(project_dir)
        await asyncio.sleep(3)
```

Key design decisions:

- **Fresh context window per session** -- create a new client each iteration
- **Auto-continue** -- 3-second delay between sessions, `Ctrl+C` to pause
- **Resume by re-running** -- same command picks up where it left off
- **Progress tracking** -- count passing/total tests after each session

---

## 6. Security (Defense in Depth)

Three layers prevent the agent from doing damage:

### Layer 1: OS-level Sandbox

```python
"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}
```

### Layer 2: Filesystem Restrictions

```python
"permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
        "Read(./**)", "Write(./**)", "Edit(./**)",
        "Glob(./**)", "Grep(./**)", "Bash(*)",
    ],
}
```

File operations restricted to the project directory via `cwd` setting.

### Layer 3: Bash Command Allowlist

```python
ALLOWED_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "grep",  # File inspection
    "cp", "mkdir", "chmod",                       # File operations
    "pwd",                                         # Directory
    "npm", "node",                                 # Node.js
    "git",                                         # Version control
    "ps", "lsof", "sleep", "pkill",               # Process management
}
```

Sensitive commands (`pkill`, `chmod`) get additional validation:

- `pkill` only allows killing dev processes (node, npm, vite)
- `chmod` only allows `+x` mode

The security hook parses commands with `shlex`, handles pipes/chaining, and blocks anything not in the allowlist.

---

## 7. Browser Verification with MCP

The agent uses Puppeteer MCP for end-to-end testing:

```python
mcp_servers={
    "puppeteer": {"command": "npx", "args": ["puppeteer-mcp-server"]}
}
```

Available tools:

- `puppeteer_navigate` -- go to URL
- `puppeteer_screenshot` -- capture visual state
- `puppeteer_click` -- click elements
- `puppeteer_fill` -- type into inputs
- `puppeteer_select` -- select dropdowns
- `puppeteer_hover` -- hover elements
- `puppeteer_evaluate` -- run JS in page

This is critical because agents will otherwise mark features complete without actually testing them through the UI.

**Known limitation:** Browser-native alert/confirm modals are invisible to Puppeteer, causing higher bug rates for features that use them.

---

## 8. Failure Modes and Mitigations

| Failure Mode                           | Cause                          | Mitigation                                                |
| -------------------------------------- | ------------------------------ | --------------------------------------------------------- |
| Declares victory prematurely           | No objective checklist         | Feature list with 200+ items, all starting as `false`     |
| Leaves undocumented bugs               | No baseline verification       | Mandatory verification phase before new work              |
| Marks features passing without testing | Skips browser verification     | Prompt explicitly requires UI testing with screenshots    |
| Wastes context on setup                | Re-installs deps every session | `init.sh` script handles setup in seconds                 |
| Corrupts feature list                  | Edits test descriptions        | Strict prompt rules: only modify `passes` field           |
| Loses track of progress                | Context window expires         | `claude-progress.txt` + git history + `feature_list.json` |
| Compounds bugs across sessions         | No regression checking         | Baseline verification at session start                    |
| Context exhaustion mid-feature         | Takes on too much              | One feature per session rule                              |

---

## 9. Project Structure Template

```
my-feature-harness/
├── autonomous_agent_demo.py      # Main entry point / agentic loop
├── agent.py                       # Session execution logic
├── client.py                      # Claude SDK client configuration
├── security.py                    # Bash command allowlist & validation
├── progress.py                    # Progress tracking utilities
├── prompts.py                     # Prompt loading
├── prompts/
│   ├── app_spec.txt              # Application/feature specification
│   ├── initializer_prompt.md     # First session prompt
│   └── coding_prompt.md          # Continuation session prompt
└── generations/
    └── my_project/                # Generated project (created at runtime)
        ├── feature_list.json      # Source of truth for progress
        ├── claude-progress.txt    # Session notes
        ├── init.sh                # Environment setup
        └── [application files]
```

---

## 10. Adapting This for Your Features

When building a harness for a specific feature (not a full app), adapt the pattern:

1. **Write `app_spec.txt`** -- Replace with your feature spec, API contract, or PRD
2. **Scope the feature list** -- Instead of 200 features, enumerate the specific acceptance criteria, edge cases, and integration points for your feature (20-50 items may suffice)
3. **Customize `init.sh`** -- Start your dev servers, seed test data, set up any prerequisites
4. **Tailor the prompts** -- Reference your codebase conventions, testing framework, and file structure
5. **Add domain-specific MCP tools** -- Puppeteer for frontend, database MCP for backend, API testing tools, etc.
6. **Adjust security allowlist** -- Add commands your stack needs (e.g., `go`, `python`, `docker`)
7. **Set max_turns appropriately** -- The reference uses 1000; adjust based on feature complexity

### Quick Adaptation Checklist

- [ ] Feature spec written and placed in `prompts/`
- [ ] Feature list JSON generated with all acceptance criteria as `"passes": false`
- [ ] `init.sh` starts all required services for your stack
- [ ] Initializer prompt customized for your project setup
- [ ] Coding prompt customized with your codebase conventions
- [ ] Security allowlist includes commands your stack needs
- [ ] MCP tools configured for your verification needs (browser, DB, API)
- [ ] Git repo initialized with clean first commit

---

## 11. Key Insights

1. **Context windows are the constraint; deliberate scaffolding is the solution.** Everything in this pattern exists to bridge the gap between sessions.

2. **JSON over Markdown for machine-readable state.** Models are less likely to corrupt structured JSON than freeform Markdown when making targeted edits.

3. **One feature per session.** This prevents context exhaustion and keeps each session focused and recoverable.

4. **Verify before building.** Always check that the previous session didn't break things before adding new work.

5. **The pattern mirrors human shift handoffs.** Clear documentation, actionable status updates, and verified baseline functionality before new work begins.

6. **Test as a user would.** Browser automation catches bugs that backend-only testing misses. Visual verification with screenshots is essential for UI work.
