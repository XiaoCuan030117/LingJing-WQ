# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a greenfield project to implement a minimal coding agent with file read/write and shell execution capabilities. The agent must complete basic tasks like summarizing files and generating scripts based on requirements.

**Language**: Implementation language not yet chosen. Review PLAN.md section "核心结构与契约" before selecting Python or another language.

**Development context**: This is a timed technical assessment with screen recording required. The assignment specification is in Chinese (`TASK.md`), and the detailed implementation plan is in `PLAN.md`.

## Implementation Phases

The project follows a staged approach defined in TASK.md and PLAN.md:

1. **Stage One (60 min)**: Minimal agent with CLI, three basic tools (read_file, write_file, run_shell), serial execution loop, and model integration. **Must commit stage one before starting stage two.**

2. **Stage Two (45-75 min)**: Extensions selected from:
   - Streamlit WebUI with chat interface
   - Tool permission controls (dangerous operations require user approval)
   - `ask_user` tool for agent-initiated questions
   - Parallel tool execution
   
   Focus on completion quality over feature count.

## Architecture Constraints

From PLAN.md "核心结构与契约":

- **No frameworks**: Use plain Python functions for the agent loop, not LangChain/AutoGPT/etc.
- **No infrastructure**: No separate backend services, databases, message queues, or account systems
- **Single-user local demo**: Not designed for multi-user or production deployment
- **Serial execution**: Tools run one at a time unless parallel execution is explicitly implemented in stage two
- **Fixed working directory**: Configured at startup, documented in README. File tools must reject path traversal (`..`) and absolute paths outside the working directory.
- **Shell interpreter**: On Windows, default to PowerShell. Document the choice in README.

## Tool Implementation Contract

All tools must return structured results with:
- Success flag
- Result data or error type + description
- Original tool call ID for correlation

### Tool Definitions

| Tool | Input | Output | Authorization |
|------|-------|--------|--------------|
| `read_file` | Path within working directory | UTF-8 text or structured error | Auto-approved |
| `write_file` | Path, full content | Success or structured error; must show if overwriting | Requires approval per call |
| `run_shell` | Command string | stdout, stderr, exit code, or timeout info | Requires approval per call |
| `ask_user` | Single clear question | User-submitted text answer; loop pauses until submission | No approval needed |

**Security requirements**:
- Validate tool parameters before execution
- Reject unknown tools without execution
- Path traversal prevention is mandatory, enforced by code not just prompts
- All shell commands require per-call approval (no "allow forever" option)
- File size limits: 100KB read, 100KB write
- Shell timeout: 30 seconds with process termination attempt
- Shell output: keep first 20KB, mark truncation

## Agent Loop State Machine

From PLAN.md "核心状态与状态迁移":

```
idle → running → (waiting_approval | waiting_user | completed | failed)
                  ↓                    ↓
                  running ←────────────┘
```

| State | Meaning |
|-------|---------|
| `idle` | Ready for new task |
| `running` | Processing model request and tools serially |
| `waiting_approval` | Paused on dangerous operation; needs allow/deny |
| `waiting_user` | Paused on `ask_user`; needs non-empty answer |
| `completed` | Task finished, ready for next conversation |
| `failed` | Terminated with error; allow reset or new task |

**Loop limits** (from PLAN.md):
- Max 12 model requests per turn
- Max 20 tool calls per turn
- 60s model request timeout
- 30s shell execution timeout

## Session State for Streamlit

Use `st.session_state` to persist:
- Message history
- Current run ID
- Current state enum
- Pending tool call queue
- Current waiting item (approval or question)
- Tool results
- Step counters

**Critical**: Button/form submissions must consume waiting items exactly once. Completed calls must not re-execute on Streamlit rerun.

## File Organization Suggestions

From PLAN.md "核心结构与契约":

```
src/
  agent.py       # Loop, state machine
  tools.py       # Tool implementations
  model.py       # Model client isolation
  cli.py         # Stage one CLI entry
app.py           # Streamlit interface
tests/           # Automated tests
requirements.txt
.env.example
README.md
```

## Testing Requirements

From PLAN.md "测试范围与完成定义":

- **Tool unit tests**: Temp directory read/write, overwrite, missing files, path traversal, encoding, size limits; shell success/failure/timeout/truncation
- **Core unit tests**: Mock model responses; cover normal completion, unknown tools, invalid params, multi-call queuing, call ID mapping, API errors, loop limits
- **Interaction state tests**: Approval executes once, denial has zero side effects, waiting doesn't advance, answer resumes, rerun doesn't replay
- **Smoke test**: File summary, script generation + execution, question + approval flow with real model (minimal API usage)

Do not call paid APIs in daily test runs. Use mocks except for smoke tests.

## Configuration & Secrets

- API keys via environment variables only
- Shell interpreter and working directory configured at startup, documented in README
- Provide `.env.example` with placeholder values
- Never commit keys, request logs with secrets, or workspace contents

## Completion Criteria

From PLAN.md:

1. All four stage deliverables verified
2. Three selected stage-two extensions run end-to-end
3. Failures show actionable feedback
4. README includes reproducible install/config/run/test steps
5. Stage one committed before stage two work
6. Screen recording accessible
7. GitHub repo URL provided

Avoid spending time on: UI polish, multi-user support, persistence, deployment infrastructure, parallel execution (unless explicitly chosen as a stage-two extension).
