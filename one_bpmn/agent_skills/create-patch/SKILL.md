---
name: "create-patch"
description: "Create data migration patches in custom Frappe apps \u2014 patch file structure, execute() method, patches.txt registration, pre_model_sync vs post_model_sync, re-executing patches, and links to specialized patch patterns for custom fields, property setters, workflows, and assignment rules. Use this skill when a change needs a data migration, a patch file or a patches.txt entry. Do NOT use it for schema changes that bench migrate applies on its own."
---

# Create a Patch

Use this skill when you need to write a data migration patch for a custom Frappe app — i.e., a one-time script that runs during `bench migrate`.

> For schema changes (adding/removing DocType fields), use DocType JSON files instead — patches are for **data changes and configuration setup**.

---

## What Kind of Patch?

| Goal                                   | Pattern                                                                                |
| -------------------------------------- | -------------------------------------------------------------------------------------- |
| Add custom fields to standard DocTypes | → See `add-custom-fields` skill                                                        |
| Modify properties of existing fields   | → See `add-property-setter` skill                                                      |
| Create/update workflows                | → See `customize-doctype` skill (workflows reference) — uses `one_fm` utilities        |
| Create/update assignment rules         | → See `customize-doctype` skill (assignment rules reference) — uses `one_fm` utilities |
| General data migration / cleanup       | Continue below ↓                                                                       |

---

## Patch File Structure

```
{app_name}/{app_name}/patches/
├── v15_0/
│   ├── migrate_old_status_values.py
│   ├── add_custom_fields_for_employee.py
│   └── set_default_warehouse.py
└── v16_0/
    └── cleanup_orphaned_records.py
```

### Patch File Template

```python
# {app_name}/{app_name}/patches/v15_0/my_patch_name.py
import frappe


def execute():
    """One-line description of what this patch does."""

    # Your migration logic here
    frappe.db.set_value("Company", "My Company", "default_currency", "USD")
```

**Rules:**

- The file **must** have an `execute()` function — this is what `bench migrate` calls
- Add **all imports at the top** of the file (not inside `execute()`)
- Each patch runs **exactly once** per site (tracked in `tabPatch Log`)
- Patches run as **Administrator** — no permission checks needed
- Always use `frappe.db.commit()` if processing large batches

---

## Registering in patches.txt

Add the patch to `{app_name}/{app_name}/patches.txt`:

```txt
[pre_model_sync]
{app_name}.patches.v15_0.prepare_data_before_schema_change

[post_model_sync]
{app_name}.patches.v15_0.populate_new_field_values
{app_name}.patches.v15_0.cleanup_orphaned_records
```

### `pre_model_sync` vs `post_model_sync`

| Phase             | When It Runs                                  | Use When                                                                                                                                                      |
| ----------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pre_model_sync`  | **Before** DocType schema changes are applied | **Most patches go here.** Data migrations, cleanups, configuration setup, custom field/workflow creation — anything that doesn't depend on new schema columns |
| `post_model_sync` | **After** DocType schema changes are applied  | The patch needs to **read or write to new fields** that are being added in the same release                                                                   |

**Rule of thumb:** Default to `pre_model_sync`. Only use `post_model_sync` when your patch depends on schema changes (new fields, renamed fields) that haven't been applied yet.

```txt
# Example: Adding a new field and populating it
[pre_model_sync]
# General data cleanup — doesn't need new columns
myapp.patches.v15_0.cleanup_orphaned_records

[post_model_sync]
# Needs the new "fulfillment_status" column to exist first
myapp.patches.v15_0.populate_fulfillment_status
```

---

## Re-executing a Patch

Frappe tracks executed patches by their exact string in `tabPatch Log`. To re-run a patch, **add a date comment** at the end of the entry in `patches.txt`:

```txt
[pre_model_sync]
myapp.patches.v15_0.my_patch_name  # 24-02-2026
```

Since the string `myapp.patches.v15_0.my_patch_name  # 24-02-2026` doesn't match the original Patch Log entry, Frappe treats it as a new patch and executes it again on `bench migrate`.

**Best practice:** Use the current date as the comment (e.g., `# DD-MM-YYYY`) so you can track when re-execution was triggered.

> **Alternative:** You can also use `bench --site site1.local run-patch myapp.patches.v15_0.my_patch_name` to run a patch immediately regardless of Patch Log, but this is mainly for development/debugging.

---

## Common Patch Patterns

### Bulk Data Update

```python
import frappe
from frappe.utils import create_batch


def execute():
    """Update status for all old records."""
    records = frappe.get_all("My DocType",
        filters={"status": "Old Status"},
        pluck="name",
    )

    for batch in create_batch(records, 100):
        for name in batch:
            frappe.db.set_value("My DocType", name, "status", "New Status")
        frappe.db.commit()
```

### Conditional Execution (Idempotent)

```python
import frappe


def execute():
    """Add default value only if not already set."""
    if not frappe.db.get_single_value("My Settings", "default_warehouse"):
        frappe.db.set_single_value("My Settings", "default_warehouse", "Main - ABC")
```

### Create Configuration Documents

```python
import frappe


def execute():
    """Create a Workspace if it doesn't exist."""
    if not frappe.db.exists("Workspace", "My Workspace"):
        frappe.get_doc({
            "doctype": "Workspace",
            "name": "My Workspace",
            "label": "My Workspace",
            "module": "My Module",
        }).insert(ignore_permissions=True)
```

---

## Naming Convention

Patch filenames should be descriptive and follow snake_case:

```
# Good
add_custom_fields_for_purchase_order.py
migrate_serial_numbers_to_bundle.py
set_default_company_settings.py

# Bad
patch_001.py
fix.py
update_data.py
```

---

## Source References (for skill maintenance)

- Patch runner: `frappe/modules/patch_handler.py`
- Patch Log DocType: `frappe/core/doctype/patch_log/`
- `bench run-patch`: `frappe/commands/utils.py`