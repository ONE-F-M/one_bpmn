# View & Include Hooks

## doctype_js Hook

Inject client-side form logic into **standard DocTypes from other apps** without modifying their files:

```python
# hooks.py
doctype_js = {
	"Sales Order": "public/js/doctype_js/sales_order.js",
	"Employee": "public/js/doctype_js/employee.js",
}
```

```
{app_name}/{app_name}/public/js/doctype_js/
├── sales_order.js
└── employee.js
```

```javascript
// {app_name}/public/js/doctype_js/sales_order.js
frappe.ui.form.on("Sales Order", {
  refresh(frm) {
    // Add custom button to standard Sales Order form
    frm.add_custom_button(
      __("Generate Report"),
      function () {
        frappe.call({
          method: "myapp.api.reports.generate",
          args: { sales_order: frm.doc.name },
        });
      },
      __("Custom Actions"),
    );
  },

  customer(frm) {
    // React to customer change on standard form
    if (frm.doc.customer) {
      frappe.db.get_value(
        "Customer",
        frm.doc.customer,
        "custom_credit_limit",
        (r) => {
          frm.set_value("custom_credit_limit", r.custom_credit_limit);
        },
      );
    }
  },
});
```

> **Multiple apps can inject into the same DocType.** Scripts are additive, not replacements.

---

## doctype_list_js Hook

Customize list view behavior for standard DocTypes:

```python
# hooks.py
doctype_list_js = {
	"Sales Order": "public/js/list_js/sales_order_list.js",
}
```

```javascript
// {app_name}/public/js/list_js/sales_order_list.js
frappe.listview_settings["Sales Order"] = {
  // Add indicator colors
  get_indicator(doc) {
    if (doc.custom_priority === "Urgent") {
      return [__("Urgent"), "red", "custom_priority,=,Urgent"];
    }
  },

  // Custom button on list view
  onload(listview) {
    listview.page.add_action_item(__("Bulk Approve"), function () {
      const names = listview.get_checked_items().map((d) => d.name);
      frappe.call({
        method: "myapp.api.orders.bulk_approve",
        args: { names: names },
        callback: function () {
          listview.refresh();
        },
      });
    });
  },

  // Custom formatters
  formatters: {
    grand_total(value) {
      return `<b>${format_currency(value)}</b>`;
    },
  },

  // Hide name column
  hide_name_column: true,

  // Default filters
  filters: [["status", "=", "Draft"]],
};
```

---

## doctype_tree_js Hook

Customize tree view behavior for DocTypes that use `is_tree = 1`:

```python
# hooks.py
doctype_tree_js = {
	"Warehouse": "public/js/doctype_tree_js/warehouse_tree.js",
}
```

```javascript
// {app_name}/public/js/doctype_tree_js/warehouse_tree.js
frappe.treeview_settings["Warehouse"] = {
  // Add custom buttons to tree toolbar
  onload(treeview) {
    treeview.page.add_action_item(__("Sync Warehouses"), function () {
      frappe.call({
        method: "myapp.api.warehouse.sync_all",
      });
    });
  },

  // Custom filters for tree
  filters: [
    {
      fieldname: "company",
      fieldtype: "Link",
      options: "Company",
      label: __("Company"),
    },
  ],
};
```

---

## doctype_calendar_js Hook

Customize calendar view behavior for DocTypes:

```python
# hooks.py
doctype_calendar_js = {
	"Event": "public/js/calendar_js/event_calendar.js",
}
```

```javascript
// {app_name}/public/js/calendar_js/event_calendar.js
frappe.views.calendar["Event"] = {
  field_map: {
    start: "starts_on",
    end: "ends_on",
    id: "name",
    allDay: "all_day",
    title: "subject",
    color: "color",
  },

  get_events_method: "frappe.desk.calendar.get_events",

  get_css_class(event) {
    if (event.status === "Cancelled") {
      return "danger";
    }
  },
};
```

---

## page_js Hook

Inject JS into specific Frappe **Page** views (custom pages like setup-wizard, roster, etc.):

```python
# hooks.py
page_js = {
	"setup-wizard": "public/js/setup_wizard.js",
	"roster": [
		"public/js/roster_js/select2.min.js",
		"public/js/roster_js/jquery.dataTables.min.js",
	],
}
```

> The key is the **page name** (the slug used in the URL, e.g., `/app/roster`). The value can be a single path or a list of paths. Scripts load only when that specific page is accessed.

---

## Global Includes

Include JS/CSS on **all desk pages** (admin interface):

```python
# hooks.py
app_include_js = "/assets/myapp/js/myapp.js"
app_include_css = "/assets/myapp/css/myapp.css"

# Multiple files
app_include_js = [
	"/assets/myapp/js/utils.js",
	"/assets/myapp/js/overrides.js",
]
```

Files go in `{app_name}/{app_name}/public/js/` and `{app_name}/{app_name}/public/css/`.

> **Warning:** Files included via `app_include_js/css` load on **every page** and impact overall performance. Use sparingly — prefer `doctype_js` for form-specific scripts.

---

## Website Includes

Include JS/CSS on **public website pages** (non-desk):

```python
# hooks.py
web_include_js = "/assets/myapp/js/website.js"
web_include_css = "/assets/myapp/css/website.css"
```

---

## Email CSS

Include CSS in **outgoing emails** from Frappe:

```python
# hooks.py
email_css = ["email.bundle.css"]
```

> Files are resolved from your app's `public/css/` directory.