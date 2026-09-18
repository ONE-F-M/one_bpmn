---
name: "create-report"
description: "How to create custom reports in Frappe/ERPNext apps. Covers Script Reports (Python-powered with charts), Query Reports (SQL-based), Custom Reports (UI-created with code), report filters, column definitions, chart configuration, prepared reports, and permissions. Use this skill when building a Script Report, a Query Report or a report chart. Do NOT use it for a Processa dashboard or a Vue page."
---

# Creating Reports in Frappe/ERPNext

## Which Report Type?

```
What kind of report do you need?
│
├─ Simple SQL query, no custom logic?
│  └─ Query Report — SQL embedded in JSON, no Python file
│
├─ Complex logic, calculations, or joins?
│  └─ Script Report — Python `execute()` in module files
│
├─ Need charts, summaries, or custom formatting?
│  └─ Script Report — returns chart config + report_summary
│
├─ Power user creates report via UI (with Python/JS code)?
│  └─ Custom Report — code stored in DB, executed via safe_exec
│     └─ No files on disk. Requires "Script Manager" role.
│
├─ Very large dataset (>100k rows)?
│  └─ Script Report with `prepared_report: 1`
│     └─ Runs in background, caches result
│
└─ End-user creates via UI (no code)?
   └─ Report Builder — built-in, no skill needed
```

---

## Detailed References

| Reference                                                      | What's Inside                                                                                                                 |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| [Script Report](references/script-report.md)                   | JSON definition, `execute()` function, complete Python + JS example with charts, filters, and summary cards                   |
| [Query & Custom Report](references/query-and-custom-report.md) | Query Report (SQL-in-JSON), Custom Report (UI-created), comparison table                                                      |
| [Report UI Features](references/report-ui-features.md)         | Advanced filter patterns (dependent, on_change, multi-select), cell formatters, chart config, summary cards, prepared reports |

---

## File Structure

Reports live under `<module>/report/<report_name>/`:

```
my_app/
└── my_module/
    └── report/
        └── my_report/
            ├── __init__.py              # Required (empty)
            ├── my_report.json           # Report definition
            ├── my_report.py             # Python logic (Script Report only)
            └── my_report.js             # Client-side filters
```

**Naming rules:**

- Directory name: `snake_case` matching the report name
- All files use the same base name as the directory
- JSON `name` and `report_name`: Title Case with spaces (e.g., `"My Custom Report"`)

---

## Column Definitions

### Dict Format (Recommended)

```python
{
    "fieldname": "customer",          # Internal field name
    "label": _("Customer"),           # Display label (translatable)
    "fieldtype": "Link",              # Frappe fieldtype
    "options": "Customer",            # Link target or Select options
    "width": 180,                     # Column width in pixels
    "hidden": 0,                      # Hide column (still in data)
}
```

### Common Fieldtypes for Columns

| Fieldtype  | Description                 | Options                           |
| ---------- | --------------------------- | --------------------------------- |
| `Link`     | Clickable link to a doctype | DocType name (e.g., `"Customer"`) |
| `Data`     | Plain text                  | —                                 |
| `Int`      | Integer                     | —                                 |
| `Float`    | Decimal number              | —                                 |
| `Currency` | Currency with formatting    | Currency field name (optional)    |
| `Percent`  | Percentage with bar         | —                                 |
| `Date`     | Date                        | —                                 |
| `Datetime` | Date + time                 | —                                 |
| `Check`    | Checkbox (0/1)              | —                                 |
| `HTML`     | Raw HTML content            | —                                 |

### Shorthand String Format (Legacy)

```python
_("Customer") + ":Link/Customer:120"
# Format: "Label:Fieldtype/Options:Width"
```

---

## Report Permissions

Permissions are set in the JSON `roles` array:

```json
{
  "roles": [
    { "role": "Sales User" },
    { "role": "Accounts Manager" },
    { "role": "System Manager" }
  ]
}
```

You can also check permissions programmatically in `execute()`:

```python
def execute(filters=None):
    if not frappe.has_permission("Sales Order", "read"):
        frappe.throw(_("You need Sales Order read permission to view this report"))
    # ... rest of report logic
```

---

## Adding to Module

1. The report directory must be under `<app>/<module>/report/<report_name>/`
2. The JSON `module` field must match the module name exactly
3. Run `bench migrate` to register the report in the database

---

## Source References

| File / Path                                                        | What It Shows                                                                |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `erpnext/selling/report/sales_analytics/`                          | Script Report with charts, tree-type data, complex filters                   |
| `erpnext/selling/report/customer_credit_balance/`                  | Simple Script Report with basic filters and columns                          |
| `erpnext/selling/report/customers_without_any_sales_transactions/` | Query Report with SQL in JSON                                                |
| `frappe/core/doctype/report/report.py`                             | Report DocType controller — handles execution, permissions, prepared reports |