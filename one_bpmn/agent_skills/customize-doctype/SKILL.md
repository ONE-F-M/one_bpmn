---
name: "customize-doctype"
description: "Add app-bundled customizations to Frappe/ERPNext DocTypes via setup hooks \u2014 workflows, assignment rules, notifications, workspaces with dashboard charts and number cards, print formats, and web forms. Routes to the right pattern based on what you need. Use this skill when adding a workflow, an assignment rule, a notification, a workspace, a print format or a web form from an app. Do NOT use it to change how a single field behaves."
---

# Customize Existing DocTypes

Use this skill when you need to add configuration-level customizations to DocTypes. This covers automation, UI, and document lifecycle features that don't require modifying controller code.

> **For code-level changes** (custom fields, property setters, controller logic, overrides), see the `add-custom-fields`, `add-property-setter`, and `doctype-controllers` skills.

---

## Decision Tree: What Are You Trying to Do?

| Goal                                   | Reference File                                          |
| -------------------------------------- | ------------------------------------------------------- |
| Add approval flow / status transitions | → [workflows.md](references/workflows.md)               |
| Auto-assign documents to users         | → [assignment-rules.md](references/assignment-rules.md) |
| Send email/system alerts on events     | → [notifications.md](references/notifications.md)       |
| Create a module landing page           | → [workspaces.md](references/workspaces.md)             |
| Create a PDF/HTML document layout      | → [print-formats.md](references/print-formats.md)       |
| Create a public-facing form            | → [web-forms.md](references/web-forms.md)               |

---

## Setup Pattern (Install / Uninstall)

All customizations follow the same `setup.py` pattern established in the `add-custom-fields` and `add-property-setter` skills. The complete `setup.py` integrating all customization types:

```python
# {app_name}/setup/setup.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from {app_name}.setup.custom_field import get_custom_fields
from {app_name}.setup.property_setter import get_field_properties
from {app_name}.setup.workflow import create_workflows, delete_workflows
from {app_name}.setup.assignment_rule import create_assignment_rules, delete_assignment_rules


def after_install():
	create_custom_fields(get_custom_fields(), ignore_validate=True)
	add_property_setters(get_field_properties())
	create_workflows()
	create_assignment_rules()
	frappe.db.commit()


def before_uninstall():
	delete_custom_fields(get_custom_fields())
	remove_property_setters(get_field_properties())
	delete_workflows()
	delete_assignment_rules()
	frappe.db.commit()


# Helper functions for property setters and custom fields cleanup
# (see add-custom-fields and add-property-setter skills for full implementation)
```

Register in `hooks.py`:

```python
after_install = "{app_name}.setup.setup.after_install"
before_uninstall = "{app_name}.setup.setup.before_uninstall"
```

---

## Directory Structure

```
{app_name}/{app_name}/
├── setup/
│   ├── setup.py               # Install/uninstall hooks
│   ├── custom_field.py         # Custom field aggregator
│   ├── property_setter.py      # Property setter aggregator
│   ├── workflow.py             # Workflow create/delete orchestrator
│   └── assignment_rule.py      # Assignment rule create/delete orchestrator
├── custom/
│   ├── custom_field/           # One file per DocType (see add-custom-fields skill)
│   ├── property_setter/        # One file per DocType (see add-property-setter skill)
│   ├── workflow/               # Workflow JSON files + helper utility
│   │   ├── workflow.py         # create_workflow(), delete_workflow() helpers
│   │   ├── task.json           # Example workflow definition
│   │   └── leave_application.json
│   └── assignment_rule/        # Assignment rule JSON files + helper utility
│       ├── assignment_rule.py  # create_assignment_rule(), delete_assignment_rule() helpers
│       └── task_assignment.json
└── print_format/               # Jinja print format templates (optional)
```

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY for updating this skill.

- `apps/one_fm/one_fm/setup/setup.py` — Complete install/uninstall hook with all customization types
- `apps/one_fm/one_fm/setup/workflow.py` — Workflow orchestrator (create/delete)
- `apps/one_fm/one_fm/setup/assignment_rule.py` — Assignment rule orchestrator
- `apps/one_fm/one_fm/custom/workflow/workflow.py` — Helper: `create_workflow()`, `create_workflow_state()`, `create_workflow_action_master()`, `delete_workflow()`
- `apps/one_fm/one_fm/custom/workflow/task.json` — Example workflow JSON with states and transitions
- `apps/frappe/frappe/automation/doctype/assignment_rule/assignment_rule.json` — Assignment Rule DocType schema
- `apps/frappe/frappe/desk/doctype/workspace/workspace.json` — Workspace DocType schema (6 child types)
- `apps/frappe/frappe/email/doctype/notification/notification.json` — Notification DocType schema