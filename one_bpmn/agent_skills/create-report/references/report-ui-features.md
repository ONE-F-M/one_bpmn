# Script Report (Python-Powered)

Script Reports are the most common type. They use a Python `execute()` function to fetch and process data.

## Report Definition (JSON)

```json
{
  "add_total_row": 1,
  "creation": "2025-01-01 00:00:00.000000",
  "disable_prepared_report": 0,
  "disabled": 0,
  "docstatus": 0,
  "doctype": "Report",
  "idx": 0,
  "is_standard": "Yes",
  "modified": "2025-01-01 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "My Module",
  "name": "My Custom Report",
  "owner": "Administrator",
  "prepared_report": 0,
  "ref_doctype": "Sales Order",
  "report_name": "My Custom Report",
  "report_type": "Script Report",
  "roles": [
    { "role": "Sales User" },
    { "role": "Sales Manager" },
    { "role": "System Manager" }
  ]
}
```

**Key JSON fields:**

| Field             | Description                                                |
| ----------------- | ---------------------------------------------------------- |
| `report_type`     | `"Script Report"`, `"Query Report"`, or `"Custom Report"`  |
| `ref_doctype`     | Primary DocType this report queries                        |
| `module`          | Module this report belongs to                              |
| `is_standard`     | `"Yes"` for app-bundled reports, `"No"` for Custom Reports |
| `add_total_row`   | `1` to auto-add a totals row                               |
| `prepared_report` | `1` to enable background execution for large datasets      |
| `roles`           | Array of roles allowed to view this report                 |

## Python File — The `execute()` Function

The `execute()` function is the core. It returns up to 6 values:

```python
def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    message = None        # Optional: HTML message above report
    chart = get_chart(data)  # Optional: chart config
    report_summary = get_summary(data)  # Optional: summary cards
    skip_total_row = False  # Optional: override add_total_row

    return columns, data, message, chart, report_summary, skip_total_row
```

> You can return just `columns, data` for simple reports. The remaining 4 values are optional.

### Complete Example

```python
# my_app/my_module/report/sales_summary/sales_summary.py
import frappe
from frappe import _
from frappe.query_builder import DocType, functions as fn


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    report_summary = get_report_summary(data)

    return columns, data, None, chart, report_summary


def get_columns():
    return [
        {
            "fieldname": "customer",
            "label": _("Customer"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 180
        },
        {
            "fieldname": "customer_name",
            "label": _("Customer Name"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "territory",
            "label": _("Territory"),
            "fieldtype": "Link",
            "options": "Territory",
            "width": 130
        },
        {
            "fieldname": "total_orders",
            "label": _("Total Orders"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "total_qty",
            "label": _("Total Qty"),
            "fieldtype": "Float",
            "width": 100
        },
        {
            "fieldname": "total_amount",
            "label": _("Total Amount"),
            "fieldtype": "Currency",
            "width": 150
        }
    ]


def get_data(filters):
    SO = DocType("Sales Order")
    Customer = DocType("Customer")
    SOI = DocType("Sales Order Item")

    query = (
        frappe.qb.from_(SO)
        .join(Customer).on(SO.customer == Customer.name)
        .join(SOI).on(SOI.parent == SO.name)
        .select(
            SO.customer,
            Customer.customer_name,
            Customer.territory,
            fn.Count(SO.name).distinct().as_("total_orders"),
            fn.Sum(SOI.qty).as_("total_qty"),
            fn.Sum(SOI.amount).as_("total_amount"),
        )
        .where(SO.docstatus == 1)
        .groupby(SO.customer, Customer.customer_name, Customer.territory)
        .orderby(fn.Sum(SOI.amount), order=frappe.qb.desc)
    )

    query = apply_filters(query, filters, SO, Customer)
    return query.run(as_dict=True)


def apply_filters(query, filters, SO, Customer):
    if filters.get("from_date"):
        query = query.where(SO.transaction_date >= filters["from_date"])

    if filters.get("to_date"):
        query = query.where(SO.transaction_date <= filters["to_date"])

    if filters.get("territory"):
        query = query.where(Customer.territory == filters["territory"])

    if filters.get("customer_group"):
        query = query.where(Customer.customer_group == filters["customer_group"])

    if filters.get("company"):
        query = query.where(SO.company == filters["company"])

    return query


def get_chart(data):
    if not data:
        return None

    # Show top 10 customers by amount
    top_10 = data[:10]

    return {
        "data": {
            "labels": [d.customer_name for d in top_10],
            "datasets": [{
                "name": _("Total Amount"),
                "values": [d.total_amount for d in top_10]
            }]
        },
        "type": "bar",  # Options: bar, line, pie, donut, percentage, heatmap
        "colors": ["#5e64ff"],
        "barOptions": {
            "stacked": False
        }
    }


def get_report_summary(data):
    if not data:
        return []

    total_customers = len(data)
    total_amount = sum(d.total_amount or 0 for d in data)
    total_orders = sum(d.total_orders or 0 for d in data)

    return [
        {
            "value": total_customers,
            "label": _("Total Customers"),
            "datatype": "Int",
            "indicator": "blue"
        },
        {
            "value": total_orders,
            "label": _("Total Orders"),
            "datatype": "Int",
            "indicator": "blue"
        },
        {
            "value": total_amount,
            "label": _("Total Revenue"),
            "datatype": "Currency",
            "indicator": "green"
        }
    ]
```

## JavaScript File — Report Filters

```javascript
// my_app/my_module/report/sales_summary/sales_summary.js
frappe.query_reports["Sales Summary"] = {
  filters: [
    {
      fieldname: "from_date",
      label: __("From Date"),
      fieldtype: "Date",
      default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
      reqd: 1,
    },
    {
      fieldname: "to_date",
      label: __("To Date"),
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
      reqd: 1,
    },
    {
      fieldname: "company",
      label: __("Company"),
      fieldtype: "Link",
      options: "Company",
      default: frappe.defaults.get_user_default("Company"),
      reqd: 1,
    },
    {
      fieldname: "territory",
      label: __("Territory"),
      fieldtype: "Link",
      options: "Territory",
    },
    {
      fieldname: "customer_group",
      label: __("Customer Group"),
      fieldtype: "Link",
      options: "Customer Group",
    },
  ],
};
```