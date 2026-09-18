# Form Scripts & Child Table Events

## Form Event Handlers

For DocTypes your app owns, form logic lives alongside the DocType definition:

```
{app_name}/{module_snake}/doctype/{doctype_snake}/
└── {doctype_snake}.js    # Client controller for this DocType
```

```javascript
// {app_name}/{module_snake}/doctype/{doctype_snake}/{doctype_snake}.js

frappe.ui.form.on("{DocType Name}", {
  // --- Form lifecycle ---
  setup(frm) {
    // Runs once when form is first loaded (before data is available)
    // Use for setting up queries, filters, formatters
    frm.set_query("customer", function () {
      return {
        filters: { disabled: 0 },
      };
    });
  },

  onload(frm) {
    // Runs each time form is loaded (data is available)
  },

  refresh(frm) {
    // Runs on every form refresh (load, save, route change)
    // Use for custom buttons, conditional UI
    if (frm.doc.docstatus === 0) {
      frm.add_custom_button(__("Create Task"), function () {
        frappe.call({
          method: "myapp.api.tasks.create_from_doc",
          args: { source_name: frm.doc.name },
          callback: function (r) {
            frappe.show_alert(__("Task created"));
            frm.reload_doc();
          },
        });
      });
    }
  },

  // --- Field events ---
  customer(frm) {
    // Triggered when 'customer' field value changes
    if (frm.doc.customer) {
      frappe.db.get_value("Customer", frm.doc.customer, "territory", (r) => {
        frm.set_value("territory", r.territory);
      });
    }
  },

  // --- Form actions ---
  validate(frm) {
    // Runs before save — throw to prevent save
    if (frm.doc.grand_total < 0) {
      frappe.throw(__("Grand Total cannot be negative"));
    }
  },

  before_save(frm) {
    // Runs right before save
  },

  after_save(frm) {
    // Runs after successful save
  },

  before_submit(frm) {
    // Runs before submission
  },

  after_submit(frm) {
    // Runs after successful submission — renamed from on_submit
  },

  before_cancel(frm) {
    // Runs before cancellation
  },

  after_cancel(frm) {
    // Runs after successful cancellation
  },
});
```

---

## Child Table Events

```javascript
frappe.ui.form.on("{Child DocType Name}", {
  // Triggers when child row field changes
  qty(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, "amount", row.qty * row.rate);
    calculate_totals(frm);
  },

  rate(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    frappe.model.set_value(cdt, cdn, "amount", row.qty * row.rate);
    calculate_totals(frm);
  },

  // When a row is removed
  items_remove(frm) {
    calculate_totals(frm);
  },

  // When a row is added
  items_add(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    row.qty = 1;
  },
});

function calculate_totals(frm) {
  let total = 0;
  frm.doc.items.forEach((row) => {
    total += row.amount || 0;
  });
  frm.set_value("grand_total", total);
}
```

---

## Common Form API

```javascript
// Set field value
frm.set_value("fieldname", value);

// Set field property
frm.set_df_property("fieldname", "read_only", 1);
frm.set_df_property("fieldname", "hidden", 1);
frm.set_df_property("fieldname", "reqd", 1);

// Toggle visibility
frm.toggle_display("fieldname", condition);
frm.toggle_reqd("fieldname", condition);
frm.toggle_enable("fieldname", condition);

// Set filter on Link field
frm.set_query("fieldname", function () {
  return {
    filters: { status: "Active" },
  };
});

// Filter within child table
frm.set_query("item_code", "items", function (doc, cdt, cdn) {
  return {
    filters: { item_group: doc.item_group },
  };
});

// Add/remove custom buttons
frm.add_custom_button(__("Label"), callback, __("Group"));
frm.remove_custom_button(__("Label"), __("Group"));

// Page actions
frm.page.set_primary_action(__("Submit"), callback);
frm.page.set_secondary_action(__("Cancel"), callback);

// Dashboard indicators
frm.dashboard.add_indicator(__("Status: Active"), "green");

// Highlight a field
frm.set_intro(__("Important note displayed at the top"), "blue");

// Add HTML to form
frm.fields_dict.html_field.$wrapper.html("<div>Custom HTML</div>");

// Reload form data from server
frm.reload_doc();

// Server call
frm.call("server_method_name", { arg1: "value" }).then((r) => {
  // r.message contains return value
});
```