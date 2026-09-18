# Workflows

## Overview

Workflows add approval flows and status transitions to DocTypes. A workflow controls which roles can transition a document between states (e.g., Draft → Pending Approval → Approved).

## File Structure (one_fm Pattern)

```
{app_name}/{app_name}/
├── setup/
│   └── workflow.py                  # Orchestrator: create_workflows() / delete_workflows()
└── custom/
    └── workflow/
        ├── workflow.py              # Helpers: create_workflow(), delete_workflow()
        ├── task.json                # Workflow definition for Task DocType
        └── leave_application.json   # Workflow definition for Leave Application
```

### Filename Convention

When saving workflow JSON files, generate the filename from the `workflow_name`:

1. Replace all spaces and non-alphanumeric characters (except underscores) with a single underscore
2. If multiple such characters appear consecutively, collapse to a single underscore
3. Remove any leading or trailing underscores
4. Convert to lowercase
5. Add `.json` extension

| `workflow_name`               | Filename                         |
| ----------------------------- | -------------------------------- |
| `Task`                        | `task.json`                      |
| `Purchase Order`              | `purchase_order.json`            |
| `Leave Application - Manager` | `leave_application_manager.json` |

> This convention applies to **all** JSON-based customization files across all custom apps (workflows, assignment rules, etc.).

---

## Workflow JSON Structure

Each workflow is stored as a JSON file:

```json
{
  "workflow_name": "Task",
  "document_type": "Task",
  "is_active": 1,
  "override_status": 0,
  "send_email_alert": 0,
  "workflow_state_field": "workflow_state",
  "doctype": "Workflow",
  "states": [
    {
      "state": "Open",
      "doc_status": "0",
      "update_field": "status",
      "update_value": "Open",
      "is_optional_state": 0,
      "avoid_status_override": 0,
      "allow_edit": "Employee",
      "style": "Primary",
      "doctype": "Workflow Document State"
    },
    {
      "state": "Pending Approval",
      "doc_status": "0",
      "update_field": "status",
      "update_value": "Pending Approval",
      "is_optional_state": 0,
      "avoid_status_override": 0,
      "allow_edit": "HR Manager",
      "style": "Warning",
      "doctype": "Workflow Document State"
    },
    {
      "state": "Approved",
      "doc_status": "1",
      "update_field": "status",
      "update_value": "Approved",
      "is_optional_state": 0,
      "avoid_status_override": 0,
      "allow_edit": "HR Manager",
      "style": "Success",
      "doctype": "Workflow Document State"
    }
  ],
  "transitions": [
    {
      "state": "Open",
      "action": "Submit for Approval",
      "next_state": "Pending Approval",
      "allowed": "Employee",
      "allow_self_approval": 1,
      "condition": "",
      "doctype": "Workflow Transition"
    },
    {
      "state": "Pending Approval",
      "action": "Approve",
      "next_state": "Approved",
      "allowed": "HR Manager",
      "allow_self_approval": 0,
      "doctype": "Workflow Transition"
    },
    {
      "state": "Pending Approval",
      "action": "Reject",
      "next_state": "Open",
      "allowed": "HR Manager",
      "allow_self_approval": 0,
      "doctype": "Workflow Transition"
    }
  ]
}
```

### State Properties

| Property            | Description                                                               |
| ------------------- | ------------------------------------------------------------------------- |
| `state`             | Workflow State name (auto-created if doesn't exist)                       |
| `doc_status`        | `"0"` = Draft, `"1"` = Submitted, `"2"` = Cancelled                       |
| `update_field`      | Field on the DocType to update when entering this state                   |
| `update_value`      | Value to set on `update_field`                                            |
| `allow_edit`        | Role allowed to edit the document in this state                           |
| `style`             | Badge color: `Primary`, `Info`, `Success`, `Warning`, `Danger`, `Inverse` |
| `is_optional_state` | `1` if state can be skipped                                               |

### Transition Properties

| Property              | Description                                                            |
| --------------------- | ---------------------------------------------------------------------- |
| `state`               | Starting state                                                         |
| `action`              | Button label (auto-created as Workflow Action Master if doesn't exist) |
| `next_state`          | Target state                                                           |
| `allowed`             | Role allowed to perform this action                                    |
| `allow_self_approval` | `1` to allow the document owner to perform this action                 |
| `allowed_user_field`  | Field on DocType containing the user allowed to act                    |
| `condition`           | Python expression that must be true for the action to appear           |

## Helper Utilities

All workflow helper functions are provided by `one_fm`. Import them directly:

```python
from one_fm.custom.workflow.workflow import (
	get_workflow_json_file,  # Load workflow JSON from one_fm/custom/workflow/
	create_workflow,         # Create or update workflow (auto-creates states + actions)
	delete_workflow,         # Delete a workflow by name
)
from one_fm.utils import get_json_file  # Generic JSON file loader
```

### Key Functions

| Function                            | Description                                                               |
| ----------------------------------- | ------------------------------------------------------------------------- |
| `get_workflow_json_file(file_name)` | Loads JSON from `one_fm/custom/workflow/{file_name}`                      |
| `create_workflow(workflow_dict)`    | Creates/updates Workflow, auto-creates Workflow States and Action Masters |
| `delete_workflow(workflow_dict)`    | Deletes a Workflow by `workflow_name`                                     |

> **Source:** `one_fm/custom/workflow/workflow.py`

### Per-App JSON Loader

Each app that has its own workflow JSON files should define its own `get_workflow_json_file`:

```python
# {app_name}/custom/workflow/workflow.py
import frappe
from one_fm.utils import get_json_file


def get_workflow_json_file(file_name):
	"""Load workflow JSON from this app's workflow folder"""
	folder = frappe.get_app_path("{app_name}", "custom", "workflow")
	return get_json_file(file_name, folder)
```

## Orchestrator

```python
# {app_name}/setup/workflow.py
from {app_name}.custom.workflow.workflow import get_workflow_json_file
from one_fm.custom.workflow.workflow import create_workflow, delete_workflow


def create_workflows():
	create_workflow(get_workflow_json_file("task.json"))
	create_workflow(get_workflow_json_file("leave_application.json"))


def delete_workflows():
	delete_workflow(get_workflow_json_file("task.json"))
	delete_workflow(get_workflow_json_file("leave_application.json"))
```

> **Note:** Each app defines its own `get_workflow_json_file` pointing to its own `custom/workflow/` directory, but reuses `create_workflow` / `delete_workflow` from `one_fm`.

---

## ⚠️ Common Mistake: Updating Workflow State

**Never** use `frappe.db.set_value` or `doc.db_set` to change `workflow_state`. This silently updates the field without triggering workflow logic — assignment rules, email alerts, and state validations will **not** execute.

```python
# ❌ WRONG — silently updates, skips assignment rules and workflow logic
frappe.db.set_value("Leave Application", name, "workflow_state", "Approved")

# ❌ ALSO WRONG
doc.db_set("workflow_state", "Approved")
```

**Always** use `apply_workflow` to transition documents between workflow states:

```python
# ✅ CORRECT — triggers assignment rules, email alerts, and all workflow logic
from frappe.workflow.doctype.workflow.workflow import apply_workflow

doc = frappe.get_doc("Leave Application", name)
apply_workflow(doc, "Approve")  # Pass the ACTION name, not the state name
```

> **Note:** The second argument to `apply_workflow` is the **action name** (e.g., `"Approve"`, `"Reject"`, `"Submit for Approval"`) — NOT the target state name.