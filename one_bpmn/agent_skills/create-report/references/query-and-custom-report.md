# Query Report & Custom Report

## Query Report (SQL-Based)

Query Reports embed SQL directly in the JSON definition. No Python file needed — simpler but less flexible.

### JSON Definition

```json
{
  "add_total_row": 0,
  "doctype": "Report",
  "is_standard": "Yes",
  "module": "My Module",
  "name": "Inactive Customers",
  "owner": "Administrator",
  "query": "SELECT\n\t`tabCustomer`.name as \"Customer:Link/Customer:120\",\n\t`tabCustomer`.customer_name as \"Customer Name::200\",\n\t`tabCustomer`.territory as \"Territory:Link/Territory:120\"\nFROM\n\t`tabCustomer`\nWHERE\n\tnot exists(\n\t\tselect name from `tabSales Order`\n\t\twhere `tabCustomer`.name = `tabSales Order`.customer\n\t\tand `tabSales Order`.docstatus=1\n\t\tlimit 1\n\t)",
  "ref_doctype": "Customer",
  "report_name": "Inactive Customers",
  "report_type": "Query Report",
  "roles": [{ "role": "Sales User" }, { "role": "System Manager" }]
}
```

**Column format in SQL:** `"Label:Fieldtype/Options:Width"`

```sql
-- Examples:
-- Link column:     "Customer:Link/Customer:120"
-- Data column:     "Customer Name::200"       (fieldtype defaults to Data)
-- Currency column: "Amount:Currency:150"
-- Date column:     "Posting Date:Date:100"
-- Int column:      "Count:Int:80"
```

> **When to use:** Only for simple read-only queries with no calculated fields, no charts, and no custom formatting. Prefer Script Reports for anything more complex.

---

## Custom Report (UI-Created with Code)

Custom Reports are created entirely through the Frappe UI — no files on disk. The Python code is stored in the `report_script` field and executed via `safe_exec()`. The JavaScript (filters) is stored in the `javascript` field.

**Key differences from Script Report:**

|                   | Script Report                              | Custom Report                               |
| ----------------- | ------------------------------------------ | ------------------------------------------- |
| **Code location** | `.py` + `.js` files in app                 | `report_script` + `javascript` fields in DB |
| **is_standard**   | `"Yes"`                                    | `"No"`                                      |
| **Execution**     | `execute_module()` — imports Python module | `execute_script()` — runs via `safe_exec()` |
| **Required role** | Developer (file access)                    | Script Manager                              |
| **Deployment**    | Bundled with app, version-controlled       | Stored in DB, not in source control         |
| **Limitations**   | None                                       | `safe_exec` sandbox — restricted imports    |

### Creating via UI

1. Go to **Report List** → **+ Add Report**
2. Set **Report Type** = `"Script Report"` (Frappe sets it to Custom Report internally when `is_standard = "No"`)
3. Set **Ref DocType** to the primary DocType
4. Write Python in the **Script** field:

```python
# Available variables: filters, frappe, data, result
# Set result to a list of lists, OR set data to (columns, result)

columns = [
    {"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "width": 180},
    {"fieldname": "total", "label": "Total", "fieldtype": "Currency", "width": 150},
]

result = frappe.db.get_all("Sales Order",
    filters={"docstatus": 1, "customer": filters.get("customer")},
    fields=["customer", "sum(grand_total) as total"],
    group_by="customer",
    order_by="total desc"
)

data = columns, result
```

5. Write JavaScript in the **Javascript** field for filters:

```javascript
frappe.query_reports["My Custom Report"] = {
  filters: [
    {
      fieldname: "customer",
      label: __("Customer"),
      fieldtype: "Link",
      options: "Customer",
    },
  ],
};
```

6. Add allowed **Roles** and save

> **When to use:** Quick ad-hoc reports created by power users. For production reports that need version control and deployment, use Script Reports.