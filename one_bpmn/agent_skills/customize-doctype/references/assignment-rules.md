# Assignment Rules

## Overview

Assignment Rules automatically assign documents to users based on conditions. They support Round Robin, Load Balancing, and Field-Based assignment strategies.

## File Structure (one_fm Pattern)

```
{app_name}/{app_name}/
├── setup/
│   └── assignment_rule.py           # Orchestrator
└── custom/
    └── assignment_rule/
        ├── assignment_rule.py       # Helpers: create/delete
        └── task_assignment.json     # Rule JSON definition
```

## Assignment Rule JSON Structure

```json
{
  "doctype": "Assignment Rule",
  "name": "Task Auto Assignment",
  "document_type": "Task",
  "description": "Auto-assign tasks to team members",
  "priority": 0,
  "disabled": 0,
  "assign_condition": "status == 'Open'",
  "unassign_condition": "status in ('Completed', 'Cancelled')",
  "close_condition": "status == 'Completed'",
  "rule": "Round Robin",
  "users": [{ "user": "user1@example.com" }, { "user": "user2@example.com" }],
  "assignment_days": [
    { "day": "Monday" },
    { "day": "Tuesday" },
    { "day": "Wednesday" },
    { "day": "Thursday" },
    { "day": "Friday" }
  ]
}
```

### Key Properties

| Property             | Description                                                            |
| -------------------- | ---------------------------------------------------------------------- |
| `document_type`      | DocType to apply this rule to                                          |
| `assign_condition`   | Python expression — when true, assigns the document                    |
| `unassign_condition` | Python expression — when true, removes the assignment                  |
| `close_condition`    | Python expression — when true, closes the ToDo                         |
| `rule`               | Assignment strategy: `Round Robin`, `Load Balancing`, `Based on Field` |
| `field`              | (Only for `Based on Field`) — Link/User field on the DocType           |
| `users`              | List of users for Round Robin / Load Balancing                         |
| `due_date_based_on`  | Date field on DocType to set as ToDo due date                          |
| `priority`           | Higher priority rules are evaluated first                              |
| `assignment_days`    | Days of the week when this rule is active                              |

### Assignment Strategies

| Strategy           | Behavior                                     |
| ------------------ | -------------------------------------------- |
| **Round Robin**    | Cycles through users list in order           |
| **Load Balancing** | Assigns to user with fewest open assignments |
| **Based on Field** | Assigns to user specified in a DocType field |

## Helper Utilities

All assignment rule helper functions are provided by `one_fm`. Import them directly:

```python
from one_fm.custom.assignment_rule.assignment_rule import (
	get_assignment_rule_json_file,  # Load JSON from custom/assignment_rule/
	create_assignment_rule,          # Create or update assignment rule
	delete_assignment_rule,          # Delete assignment rule by name
)
```

### Key Functions

| Function                                                      | Description                                                                                                      |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `get_assignment_rule_json_file(file_name, app_name="one_fm")` | Loads JSON from `{app_name}/custom/assignment_rule/{file_name}`. Pass your app name to load from a different app |
| `create_assignment_rule(rule_dict, process_task_name=None)`   | Creates/updates Assignment Rule. Optionally links a Process Task via `custom_routine_task`                       |
| `delete_assignment_rule(rule_dict)`                           | Deletes an Assignment Rule by `name`                                                                             |

> **Source:** `one_fm/custom/assignment_rule/assignment_rule.py`

### Per-App JSON Loader

For other apps, pass the `app_name` parameter:

```python
# Loading from your own app's custom/assignment_rule/ directory
from one_fm.custom.assignment_rule.assignment_rule import get_assignment_rule_json_file

data = get_assignment_rule_json_file("my_rule.json", app_name="{app_name}")
```

## Orchestrator

```python
# {app_name}/setup/assignment_rule.py
from one_fm.custom.assignment_rule.assignment_rule import (
	get_assignment_rule_json_file, create_assignment_rule, delete_assignment_rule
)


def create_assignment_rules():
	create_assignment_rule(get_assignment_rule_json_file("task_assignment.json", app_name="{app_name}"))


def delete_assignment_rules():
	delete_assignment_rule(get_assignment_rule_json_file("task_assignment.json", app_name="{app_name}"))
```

---

## Assignment Rules Based on Process Task

For assignment rules that use the `"Based on Process Task"` strategy, use the `create_process_task` utility from `one_fm.utils`.

### Process Task Utility

```python
from one_fm.utils import create_process_task

# Create a Process Task (auto-creates Process and Method if they don't exist)
process_task = create_process_task(
    process_name="HD Ticket Resolution",      # Process name (created if not exists)
    erp_document="HD Ticket",                  # Target DocType
    task_description="Resolve HD Ticket",      # Task description
    employee="HR-EMP-00001",                   # Optional: assigned employee
    process_owner=None,                        # Optional: process owner user
    business_analyst=None,                     # Optional: BA user
    task_type="Repetitive",                    # "Repetitive" or custom
    is_routine_task=0,                         # 1 if routine
    frequency="",                              # Cron frequency (optional)
    cron_format="",                            # Required if frequency="Cron"
    is_automated=0,                            # 1 if automated
    method="",                                 # Method name (optional)
)
```

### Assignment Rule JSON for Process Task

```json
{
  "name": "HD Ticket - Development Process Owner",
  "document_type": "HD Ticket",
  "assign_condition": "status == 'Open'",
  "unassign_condition": "status in ('Resolved', 'Closed')",
  "close_condition": "status == 'Closed'",
  "rule": "Based on Process Task",
  "doctype": "Assignment Rule",
  "assignment_days": [
    { "day": "Monday" },
    { "day": "Tuesday" },
    { "day": "Wednesday" },
    { "day": "Thursday" },
    { "day": "Friday" },
    { "day": "Saturday" },
    { "day": "Sunday" }
  ],
  "users": []
}
```

### Patch Pattern for Process-Task-Based Assignment Rules

```python
# {app_name}/{app_name}/patches/v15_0/add_assignment_rule_for_hd_ticket_process_task.py
import frappe
from one_fm.utils import create_process_task
from {app_name}.custom.assignment_rule.assignment_rule import (
    create_assignment_rule, get_assignment_rule_json_file
)


def execute():
    process_task = create_process_task(
        process_name="HD Ticket Resolution",
        erp_document="HD Ticket",
        task_description="Resolve HD Ticket",
        employee="HR-EMP-00001",
    )

    assignment_rule_data = get_assignment_rule_json_file(
        "hd_ticket_development_process_owner.json"
    )

    if process_task and process_task.employee:
        employee_data = frappe.db.get_value(
            "Employee", process_task.employee,
            ["employee_name", "user_id", "department"],
            as_dict=True,
        )
        if employee_data:
            assignment_rule_data["employee_name"] = employee_data.employee_name
            assignment_rule_data["employee_user"] = employee_data.user_id
            assignment_rule_data["department"] = employee_data.department

    create_assignment_rule(assignment_rule_data, process_task.name if process_task else None)
```