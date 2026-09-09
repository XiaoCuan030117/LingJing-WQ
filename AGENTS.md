# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains only `TASK.md`, the Chinese-language assignment specification. No source code, tests, assets, or dependency manifests exist yet. Read `TASK.md` before implementing features.

Stage one requires a minimal coding agent that reads and writes files and runs shell commands. CLI, TUI, and web interfaces are all acceptable. When scaffolding, keep agent orchestration, tool implementations, and interface code separate. Prefer `src/` for application code and `tests/` for automated tests unless the chosen framework uses another convention. Add an assets directory only if needed.

## Build, Test, and Development Commands

No build, development, or test commands are configured. After selecting a language and framework, document exact installation, local execution, build, and test commands in `README.md`. Keep those commands synchronized with the dependency manifest or task runner. Do not assume commands such as `npm test` work before configuring them.

## Coding Style & Naming Conventions

No language-specific style or formatter is established. Use the chosen language's standard formatter and linter, and commit their configuration. Use consistent indentation: two spaces for JavaScript/TypeScript and four for Python if selected. Give tool functions descriptive, action-oriented names, and follow language conventions for filenames and identifiers. Keep modules focused and isolate model-provider configuration from agent logic.

## Testing Guidelines

No testing framework or coverage threshold exists. Add tests for file reads and writes, shell execution, tool failures, and agent-loop termination. Use temporary directories for filesystem tests and mock model responses to avoid paid API calls. Follow the framework's test naming convention and document how to run the suite. Include a reproducible smoke test for a file-summary or script-generation task.

## Commit & Pull Request Guidelines

There is no commit history to establish a message convention. Use short, imperative subjects describing a focused change. As `TASK.md` requires, commit completed stage-one work before starting stage-two agent extensions. PR descriptions should explain scope, validation, and remaining limitations; include screenshots for UI changes and link relevant issues when available.

## Security & Configuration

Load API keys from environment variables. Ignore local secret files and provide placeholder configuration examples. Never commit credentials, model request logs containing secrets, or private workspace contents.
