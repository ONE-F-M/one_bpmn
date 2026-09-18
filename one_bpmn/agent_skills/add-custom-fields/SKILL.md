---
name: "add-custom-fields"
description: "Add custom fields to existing standard Frappe/ERPNext DocTypes programmatically using create_custom_fields \u2014 covers field definitions, install/uninstall hooks, modular file organization, and incremental additions via patches. Use this skill when adding a field to a DocType another app owns, such as an ERPNext or HRMS DocType. Do NOT use it for a field on a DocType this app owns, which belongs in that DocType's own JSON."
---

# Add Custom Fields to Existing DocTypes

Use this skill when your custom app needs to add fields to standard Frappe/ERPNext DocTypes (e.g., adding fields to `Company`, `Employee`, `Sales Invoice`).

> **Do NOT** use the Frappe UI to add custom fields for app-distributed customizations. Always use the programmatic `create_custom_fields` API so fields are version-controlled and portable.

## Prerequisites

1. **App name** — which custom app owns these fields
2. **Target DocType(s)** — which existing DocType(s) to add fields to
3. **Fields to add** — fieldname, fieldtype, label, insert_after, and any other properties

---

## Step 1: Create the Custom Field Definition File

Create one file per target DocType under `{app}/custom/custom_field/`:

```
{app_name}/{app_name}/custom/custom_field/
├── __init__.py             # Empty
├── company.py              # Fields for Company DocType
├── employee.py             # Fields for Employee DocType
└── sales_invoice.py        # Fields for Sales Invoice DocType
```

Each file exports a function returning a dict in the `create_custom_fields` format:

```python
# {app_name}/custom/custom_field/{doctype_snake}.py

def get_{doctype_snake}_custom_fields():
	return {
		"{DocType Name}": [
			{
				"fieldname": "custom_field_1",
				"fieldtype": "Data",
				"label": "My Custom Field",
				"insert_after": "existing_field_name",
			},
			{
				"fieldname": "custom_section",
				"fieldtype": "Section Break",
				"label": "Custom Section",
				"insert_after": "custom_field_1",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_link_field",
				"fieldtype": "Link",
				"label": "Related Record",
				"options": "Other DocType",
				"insert_after": "custom_section",
				"reqd": 1,
			},
		]
	}
```

### Field Dict Properties

Each field dict supports all standard DocType field properties (see `create-doctype` skill), plus:

| Property              | Required | Purpose                                                             |
| --------------------- | -------- | ------------------------------------------------------------------- |
| `fieldname`           | ✅       | Unique identifier for the field                                     |
| `fieldtype`           | ✅       | Field type (Data, Link, Select, etc.)                               |
| `label`               | ✅       | Display label                                                       |
| `insert_after`        | ✅       | Fieldname of the existing field to insert after — controls position |
| `module`              | —        | Module to associate the custom field with                           |
| `is_system_generated` | —        | Set to `1` to mark as system-managed                                |

> **Finding `insert_after` values:** Open the target DocType in the browser, inspect the field order, and choose the fieldname you want your field to appear after. You can also check the DocType JSON at `apps/{app}/{app}/{module}/doctype/{doctype_snake}/{doctype_snake}.json`.
>
> **Tip:** Use `"insert_after": "append"` to add the field at the end of the form without knowing the last fieldname.

---

## Step 2: Create the Aggregator File

Create a central file that collects all custom field definitions:

```python
# {app_name}/setup/custom_field.py
from {app_name}.custom.custom_field.company import get_company_custom_fields
from {app_name}.custom.custom_field.employee import get_employee_custom_fields
from {app_name}.custom.custom_field.sales_invoice import get_sales_invoice_custom_fields


def get_custom_fields():
	custom_fields = {}
	custom_fields.update(get_company_custom_fields())
	custom_fields.update(get_employee_custom_fields())
	custom_fields.update(get_sales_invoice_custom_fields())
	return custom_fields
```

> **Note:** Each `get_*_custom_fields()` function returns a dict keyed by DocType name. Using `dict.update()` merges them. Since each targets a different DocType, there are no key collisions.

---

## Step 3: Create the Setup File with Install/Uninstall Hooks

```python
# {app_name}/setup/setup.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from {app_name}.setup.custom_field import get_custom_fields


def after_install():
	create_custom_fields(get_custom_fields(), ignore_validate=True)
	frappe.db.commit()


def before_uninstall():
	delete_custom_fields(get_custom_fields())
	frappe.db.commit()


def delete_custom_fields(custom_fields: dict):
	"""Remove custom fields added by this app"""
	for doctype, fields in custom_fields.items():
		frappe.db.delete(
			"Custom Field",
			{
				"fieldname": ("in", [f["fieldname"] for f in fields]),
				"dt": doctype,
			},
		)
		frappe.clear_cache(doctype=doctype)
```

---

## Step 4: Register the Hooks

Add to your app's `hooks.py`:

```python
after_install = "{app_name}.setup.setup.after_install"
before_uninstall = "{app_name}.setup.setup.before_uninstall"
```

---

## Step 5: Adding Fields After Initial Installation (via Patches)

When adding new custom fields to an app that is already installed, use a **patch** to apply them:

```python
# {app_name}/patches/v15_0/add_new_custom_fields.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Sales Order": [
			{
				"fieldname": "custom_new_field",
				"fieldtype": "Data",
				"label": "New Field",
				"insert_after": "customer_name",
			},
		]
	})
```

Register the patch in `patches.txt`:

```
{app_name}.patches.v15_0.add_new_custom_fields
```

> **Important:** Also add the field to the per-DocType definition file (`custom/custom_field/{doctype}.py`) and the aggregator, so it's included in fresh installations via `after_install`.

---

## `create_custom_fields` API Reference

```python
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

create_custom_fields(
	custom_fields,          # dict: {"DocType Name": [list of field dicts]}
	ignore_validate=False,  # skip field validation (use True in after_install)
	update=True,            # update existing fields if they already exist
)
```

**Multi-DocType shorthand:** Use a tuple of DocType names as key to apply the same fields to multiple DocTypes:

```python
create_custom_fields({
	("Sales Order", "Purchase Order"): [
		{
			"fieldname": "custom_approval_status",
			"fieldtype": "Select",
			"label": "Approval Status",
			"options": "Pending\nApproved\nRejected",
			"insert_after": "status",
		},
	]
})
```

- Fields are identified by `fieldname` — if a field with the same `fieldname` already exists on the DocType, it will be **updated** (when `update=True`).
- The `insert_after` property determines field positioning. If the referenced field doesn't exist, the field is appended at the end.

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY for updating this skill.

- `apps/frappe/frappe/custom/doctype/custom_field/custom_field.py` — `create_custom_fields()` API implementation
- `apps/hrms/hrms/setup.py` — HRMS pattern (single-dict in `get_custom_fields()`)
- `apps/one_fm/one_fm/setup/setup.py` — one_fm install/uninstall hooks
- `apps/one_fm/one_fm/setup/custom_field.py` — one_fm aggregator pattern (one file per DocType)
- `apps/one_fm/one_fm/custom/custom_field/company.py` — Example per-DocType field definition
- `apps/one_fm/one_fm/patches/v15_0/` — Examples of adding custom fields via patches