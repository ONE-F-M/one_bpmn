# AGENTS.md

This repository contains the `one_bpmn` custom Frappe app for BPMN process modelling and execution support.

## Stack
- Frappe v15
- Python 3.10+
- SpiffWorkflow
- Vue frontend under `spiff/`

## Repository layout
- `one_bpmn/api.py`: whitelisted backend API functions
- `one_bpmn/tasks.py`: scheduled task processing, including timer event handling
- `one_bpmn/one_bpmn/doctype/`: BPMN-related doctypes
- `one_bpmn/one_bpmn/workspace/processa/`: workspace definition
- `one_bpmn/public/`: built public assets
- `one_bpmn/www/spiff/`: route entrypoint for the BPMN UI
- `spiff/`: frontend source for the BPMN editor

## BPMN data model
Core doctypes include:
- `BPMN Process Model`
- `BPMN Process Instance`
- `BPMN Activity Log`
- `BPMN Shape Library`
- `BPMN Custom Shape`

## SpiffWorkflow integration
- BPMN XML is stored in process model documents.
- Runtime and scheduler interactions should remain compatible with current engine helpers.
- Be careful when changing XML parsing or timer event logic.

## API guidance
Primary API surface lives in `one_bpmn/api.py`.
Verify actual whitelisted functions before documenting or calling them. Do not invent endpoints.

## Process lifecycle
Typical states:
- Draft
- Active
- Completed
- Cancelled

## Task lifecycle
Typical states:
- Ready
- Claimed
- Completed
- Delegated

## Testing
- Existing doctype tests live under the respective doctype folders.
- Additional shared tests may live under `one_bpmn/tests/`.
- Run app tests with:
```bash
bench --site <site> run-tests --app one_bpmn --failfast
```

## Branch workflow
Use the standard flow:
- `staging`
- `test-production`
- `version-15`

## Security rule
Never modify the process execution engine behavior casually. Review any execution, scheduling, or permission-sensitive change carefully.
