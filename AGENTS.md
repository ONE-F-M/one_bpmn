# AGENTS.md

This repository contains the `one_bpmn` Frappe app. It provides BPMN process modelling and execution support for Frappe v15, with backend APIs in Python and a Vue/bpmn-js frontend under `spiff/`.

Use this file as the first source of context before changing the app.

## Stack

- Frappe v15 / ERPNext-compatible custom app
- Python 3.10+
- SpiffWorkflow for BPMN execution concepts and serialization
- Vue frontend source in `spiff/`
- Public app module in `one_bpmn/`
- Standard branch flow: PRs target `staging`, then `test-production`, then `version-15`

## Repository Layout

- `one_bpmn/api.py`: whitelisted backend API surface for process diagrams, process lists, shape libraries, uploads, and diagram ordering.
- `one_bpmn/hooks.py`: Frappe app hooks, scheduler hooks, fixtures, app metadata, and asset registration.
- `one_bpmn/tasks.py`: scheduled/background task helpers, especially timer-related BPMN handling.
- `one_bpmn/one_bpmn/doctype/`: DocType controllers, JSON definitions, and tests for BPMN entities.
- `one_bpmn/www/spiff/`: Frappe web route used to serve the BPMN UI.
- `one_bpmn/public/`: built assets copied into the Frappe public path.
- `spiff/`: Vue, bpmn-js, Vite, Tailwind, and editor source files.
- `.github/workflows/`: CI, deployment, linting, test, and type-check workflows.

## BPMN Data Model

The app centres on these business objects:

- `BPMN Process Model`: Stores BPMN XML, process metadata, serialized SpiffWorkflow specs, subprocess specs, version, active status, and links to a parent Process where applicable.
- `BPMN Process Instance`: Represents a running or completed execution of a process model. Treat instance state as business-critical.
- `BPMN Activity Log`: Records process execution activity and task transitions.
- `BPMN Shape Library`: Groups reusable custom BPMN/editor shapes.
- `BPMN Custom Shape`: Stores uploaded custom SVG shapes linked to a shape library.

Expected process lifecycle:

- `Draft`: Process definition is being prepared or edited.
- `Active`: Process definition is ready for use or an instance is currently running.
- `Completed`: Execution finished successfully.
- `Cancelled`: Execution was intentionally stopped.

Expected task lifecycle:

- `Ready`: Task is available for action.
- `Claimed`: A user or process actor has taken ownership.
- `Completed`: Task finished and process should advance.
- `Delegated`: Ownership moved to another user or actor.

Do not invent new lifecycle states without checking the DocType schema and downstream consumers.

## SpiffWorkflow Integration

SpiffWorkflow concepts appear in model serialization, subprocess handling, timers, events, and runtime execution helpers. When working in this area:

- Preserve BPMN XML validity. Invalid XML can break both the frontend modeller and backend execution.
- Keep serialized process specs compatible with existing records.
- Treat subprocess, timer, and signal behaviour as execution-engine logic, not simple UI data.
- Avoid changing scheduler/timer semantics unless the task explicitly requires it.
- Verify any change against both process definition data and process instance behaviour.

Security rule: never modify the process execution engine, scheduler, timer handling, signal handling, or permission checks casually. These changes require focused review because they can affect live process state.

## API Patterns

The primary API surface lives in `one_bpmn/api.py`. Before adding or changing an endpoint:

- Search for existing `@frappe.whitelist()` functions.
- Confirm the exact frontend caller in `spiff/src/`.
- Check permission handling before returning or mutating documents.
- Prefer Frappe ORM methods over raw SQL.
- Use `frappe.throw` for user-facing validation failures.
- Return stable dict/list shapes because the Vue app consumes these responses directly.
- Do not expose raw tracebacks, private document fields, or unrestricted file paths.

Common API groups:

- Process model CRUD: save, fetch, list, import, delete, and version-related operations.
- Process/diagram navigation: list processes, get diagrams by process, and update diagram order.
- Shape library management: create/delete libraries and upload/delete custom shapes.
- Runtime-related operations: task, signal, timer, or instance functions if present in the current branch.

Always verify the current code before naming an endpoint. Documentation and tests must match actual whitelisted functions, not assumed Frappe conventions.

## Frontend Notes

The frontend is a Vue-based BPMN editor. Key areas:

- `spiff/src/views/Home.vue`: process list and navigation into the editor.
- `spiff/src/views/Editor.vue`: editor page for process diagrams.
- `spiff/src/components/BpmnEditor.vue`: bpmn-js integration point.
- `spiff/src/components/ShapeLibraryPanel.vue`: custom shape drag-and-drop.
- `spiff/src/components/FormattingToolbar.vue`: visual formatting controls.
- `spiff/src/router/`: route definitions for `/spiff` and process/diagram routes.

When changing frontend API calls, update backend response shapes or callers together. Do not silently change payload names used by existing views/components.

## Testing Conventions

Use Frappe test commands when validating app behaviour:

```bash
bench --site <site> run-tests --app one_bpmn --failfast
```

Shared tests can live under `one_bpmn/tests/`. DocType-specific tests should remain near the relevant DocType controller unless a task asks for shared integration coverage.

For BPMN execution tests:

- Keep fixture BPMN XML small and readable.
- Cover sequential flow, gateway paths, subprocess behaviour, timer events, signal events, cancellation, and restart behaviour when those features are touched.
- Mock external or scheduler behaviour where full Frappe execution would make tests slow or brittle.
- Prefer tests that assert process state transitions over tests that only assert files exist.

For API tests:

- Group by process CRUD, instance management, task operations, signal handling, timer management, and authorization.
- Patch `frappe` carefully; assert permission checks on write/delete paths.
- Test both happy paths and validation failures.

## Code Quality

- Follow the repo's `.editorconfig`, Ruff, pre-commit, commitlint, and type-check configuration.
- Keep Python compatible with 3.10+.
- Use concise type hints where they improve API/test clarity.
- Keep commits scoped to the task branch. Do not mix unrelated workflow, deployment, or formatting changes into a branch.
- If a branch is only for documentation, avoid touching CI or runtime files.

## Branch And PR Workflow

Each sprint task branch should match the work item ID, for example `WI-000768`.

Standard flow:

1. Checkout the task branch.
2. Fetch/pull latest upstream for that exact branch.
3. Compare implementation against the sprint description and acceptance criteria.
4. If it already matches, do not change it.
5. If it does not match, fix only the mismatch.
6. Commit with the work item ID in the subject.
7. Push back to `upstream`.

Use conventional commits:

```text
docs(WI-000768): expand agent guidance
fix(WI-000771): read typed files from mypy config
ci(WI-000762): align Frappe linter workflow
```

## Review Checklist

Before pushing:

- The changed files match the task scope.
- No secrets, tokens, or local paths are added.
- Workflows target `staging`, `test-production`, and `version-15` when the task says protected branches.
- BPMN execution changes preserve existing lifecycle and permission behaviour.
- Documentation names only current files/endpoints/features.
- Tests or direct file/config checks were run where practical.
