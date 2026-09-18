---
name: "add-property-setter"
description: "Modify properties of existing fields on standard Frappe/ERPNext DocTypes programmatically using make_property_setter \u2014 covers field-level and DocType-level property changes, install/uninstall hooks, and modular file organization. Use this skill when changing a property of an existing field or DocType, such as a label, a default, read only or mandatory. Do NOT use it to add a new field."
---

# Add Property Setters to Existing DocTypes

Use this skill when your custom app needs to **modify properties** of existing fields on standard DocTypes — e.g., making a field read-only, hidden, adding filter options, changing default values, or reordering fields.

> **Property Setters vs Custom Fields:**
>
> - **Custom Fields** = adding **new** fields to a DocType
> - **Property Setters** = changing **existing** field properties (or DocType-level properties)

## Prerequisites

1. **App name** — which custom app owns these changes
2. **Target DocType(s)** — which DocType(s) to modify
3. **Changes to make** — which field/DocType properties to override

---

## Step 1: Create the Property Setter Definition File

Create one file per target DocType under `{app}/custom/property_setter/`:

```
{app_name}/{app_name}/custom/property_setter/
├── __init__.py             # Empty
├── attendance.py           # Property changes for Attendance
├── company.py              # Property changes for Company
└── sales_invoice.py        # Property changes for Sales Invoice
```

Each file returns a **list** of property setter dicts:

```python
# {app_name}/custom/property_setter/{doctype_snake}.py

def get_{doctype_snake}_properties():
	return [
		{
			"doctype": "Property Setter",
			"doc_type": "{DocType Name}",
			"doctype_or_field": "DocField",
			"field_name": "customer_name",
			"property": "read_only",
			"property_type": "Check",
			"value": "1",
		},
	]
```

### Property Setter Dict Fields

| Key                | Required              | Description                                                                                |
| ------------------ | --------------------- | ------------------------------------------------------------------------------------------ |
| `doctype`          | ✅                    | Always `"Property Setter"`                                                                 |
| `doc_type`         | ✅                    | Target DocType name (e.g., `"Sales Invoice"`)                                              |
| `doctype_or_field` | ✅                    | Target type (see table below)                                                              |
| `field_name`       | For DocField          | The fieldname to modify (omit for DocType-level changes)                                   |
| `row_name`         | For Link/Action/State | The `name` of the specific row in links/actions/states to modify                           |
| `property`         | ✅                    | The property to change (e.g., `"read_only"`, `"hidden"`, `"options"`, `"default"`)         |
| `property_type`    | ✅                    | Data type of the value: `"Check"`, `"Data"`, `"Select"`, `"Small Text"`, `"Text"`, `"Int"` |
| `value`            | ✅                    | The new value (always a string, even for booleans: `"1"` / `"0"`)                          |

### `doctype_or_field` Target Types

| Value              | Use Case                                                      |
| ------------------ | ------------------------------------------------------------- |
| `"DocField"`       | Change properties of a form field                             |
| `"DocType"`        | Change DocType-level properties (sort, naming, etc.)          |
| `"DocType Link"`   | Change properties of a linked document entry in DocType Links |
| `"DocType Action"` | Change properties of a DocType Action button                  |
| `"DocType State"`  | Change properties of a DocType State (workflow appearance)    |

### Common Field-Level Properties (`doctype_or_field = "DocField"`)

| `property`             | `property_type` | Example `value`                  | Effect                         |
| ---------------------- | --------------- | -------------------------------- | ------------------------------ |
| `read_only`            | `Check`         | `"1"`                            | Make field non-editable        |
| `hidden`               | `Check`         | `"1"`                            | Hide field from form           |
| `reqd`                 | `Check`         | `"1"`                            | Make field mandatory           |
| `in_list_view`         | `Check`         | `"1"`                            | Show in list view              |
| `in_standard_filter`   | `Check`         | `"1"`                            | Add to sidebar filters         |
| `allow_on_submit`      | `Data`          | `"1"`                            | Allow editing after submission |
| `default`              | `Data`          | `"Pending"`                      | Change default value           |
| `options`              | `Select`        | `"Option A\nOption B\nOption C"` | Change Select field options    |
| `label`                | `Data`          | `"New Label"`                    | Change field label             |
| `fetch_from`           | `Small Text`    | `"employee.company"`             | Set auto-fetch source          |
| `fetch_if_empty`       | `Check`         | `"1"`                            | Only fetch if empty            |
| `read_only_depends_on` | `Data`          | `"eval:doc.docstatus==1"`        | Conditional read-only          |
| `depends_on`           | `Data`          | `"eval:doc.status=='Active'"`    | Conditional visibility         |
| `mandatory_depends_on` | `Data`          | `"eval:doc.is_active==1"`        | Conditional mandatory          |
| `description`          | `Data`          | `"Help text here"`               | Change help text               |

### Common DocType-Level Properties (`doctype_or_field = "DocType"`)

| `property`      | `property_type` | Example `value`               | Effect                             |
| --------------- | --------------- | ----------------------------- | ---------------------------------- |
| `sort_field`    | `Data`          | `"modified"`                  | Change default sort column         |
| `sort_order`    | `Data`          | `"ASC"`                       | Change sort direction              |
| `field_order`   | `Data`          | `'["field1", "field2", ...]'` | Reorder fields (JSON array string) |
| `quick_entry`   | `Check`         | `"1"`                         | Enable/disable quick entry dialog  |
| `track_changes` | `Check`         | `"1"`                         | Enable/disable version tracking    |

> **Note for DocType-level changes:** Omit the `field_name` key entirely.

---

## Step 2: Create the Aggregator File

```python
# {app_name}/setup/property_setter.py
from {app_name}.custom.property_setter.attendance import get_attendance_properties
from {app_name}.custom.property_setter.company import get_company_properties
from {app_name}.custom.property_setter.sales_invoice import get_sales_invoice_properties


def get_field_properties():
	field_properties = get_attendance_properties()
	field_properties.extend(get_company_properties())
	field_properties.extend(get_sales_invoice_properties())
	return field_properties
```

> **Key difference from Custom Fields:** Property setters use a **list** (aggregated with `list.extend()`), not a dict (which uses `dict.update()`).

---

## Step 3: Add to Setup File

Add property setter logic to your existing `setup/setup.py` (alongside custom fields if applicable):

```python
# {app_name}/setup/setup.py
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import (
	make_property_setter,
	delete_property_setter,
)
from {app_name}.setup.custom_field import get_custom_fields
from {app_name}.setup.property_setter import get_field_properties


def after_install():
	create_custom_fields(get_custom_fields(), ignore_validate=True)
	add_property_setters(get_field_properties())
	frappe.db.commit()


def before_uninstall():
	delete_custom_fields(get_custom_fields())
	remove_property_setters(get_field_properties())
	frappe.db.commit()


def add_property_setters(property_setters):
	for prop in property_setters:
		make_property_setter(
			doctype=prop.get("doc_type"),
			fieldname=prop.get("field_name"),
			property=prop.get("property"),
			value=prop.get("value"),
			property_type=prop.get("property_type"),
			for_doctype=prop.get("doctype_or_field") == "DocType",
			validate_fields_for_doctype=False,
		)


def remove_property_setters(property_setters):
	for prop in property_setters:
		delete_property_setter(
			doc_type=prop.get("doc_type"),
			property=prop.get("property"),
			field_name=prop.get("field_name"),
		)
		frappe.clear_cache(doctype=prop.get("doc_type"))


def delete_custom_fields(custom_fields: dict):
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

Add to your app's `hooks.py` (if not already added for custom fields):

```python
after_install = "{app_name}.setup.setup.after_install"
before_uninstall = "{app_name}.setup.setup.before_uninstall"
```

---

## Step 5: Adding Property Setters After Initial Installation (via Patches)

```python
# {app_name}/patches/v15_0/update_field_properties.py
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	make_property_setter(
		doctype="Sales Invoice",
		fieldname="customer_name",
		property="read_only",
		value="1",
		property_type="Check",
		validate_fields_for_doctype=False,
	)
```

Register in `patches.txt`:

```
{app_name}.patches.v15_0.update_field_properties
```

> **Important:** Also add the property to the per-DocType definition file (`custom/property_setter/{doctype}.py`) and aggregator, so it's included in fresh installations.

---

## `make_property_setter` API Reference

```python
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

make_property_setter(
	doctype,                          # Target DocType name
	fieldname,                        # Field to modify (None for DocType-level)
	property,                         # Property name to change
	value,                            # New value (string)
	property_type,                    # Data type of value
	for_doctype=False,                # True for DocType-level properties
	validate_fields_for_doctype=True, # Set False in install/patches
	is_system_generated=True,         # Marks as system-managed
)
```

- `make_property_setter` **replaces** any existing Property Setter for the same doctype + field + property combination.
- Values are always strings. Use `"1"` / `"0"` for boolean Check properties.

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY for updating this skill.

- `apps/frappe/frappe/custom/doctype/property_setter/property_setter.py` — `make_property_setter()` and `delete_property_setter()` APIs
- `apps/one_fm/one_fm/setup/setup.py` — Install/uninstall hooks calling `add_property_setter` and `remove_property_setter`
- `apps/one_fm/one_fm/setup/property_setter.py` — Aggregator pattern (list-based with `list.extend()`)
- `apps/one_fm/one_fm/custom/property_setter/company.py` — Example: DocType-level and field-level properties
- `apps/one_fm/one_fm/custom/property_setter/attendance.py` — Example: multiple field properties including `options`, `read_only`, `fetch_from`