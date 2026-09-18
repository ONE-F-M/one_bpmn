---
name: "doctype-controllers"
description: "Complete guide to DocType controller development \u2014 writing new controllers, lifecycle hooks (doc events), extending/overriding standard DocTypes, autoname patterns, validation, calculations, permissions, and all hooks.py integration points. Use this skill when writing or changing a controller, a lifecycle hook or a hooks.py doc_events entry, or when extending a DocType another app owns. Do NOT use it for client side form JavaScript."
---

# DocType Controllers

## What Are You Trying to Do?

| Goal                                                    | Reference                                                                  |
| ------------------------------------------------------- | -------------------------------------------------------------------------- |
| Write server-side logic for a **new** DocType you own   | → [Writing Controllers](references/writing-controllers.md)                 |
| Extend or override a **standard** DocType from your app | → [Extending Standard DocTypes](references/extending-standard-doctypes.md) |

---

## Quick Reference: Writing Controllers

For new DocType controllers, see [writing-controllers.md](references/writing-controllers.md) for:

| Section | Topic                             |
| ------- | --------------------------------- |
| A1      | Base controller class selection   |
| A2      | Autoname / naming patterns        |
| A3      | Document lifecycle hooks (all 20) |
| A4      | Validation patterns               |
| A5      | Calculation patterns              |
| A6      | Linked document operations        |
| A7      | Database update patterns          |
| A8      | Background processing             |
| A9      | ERPNext-specific (GL, stock)      |
| A10     | Common imports                    |

---

## Quick Reference: Extending Standard DocTypes

For extending standard DocTypes via `hooks.py`, see [extending-standard-doctypes.md](references/extending-standard-doctypes.md) for:

| Section | Hook                           | When to Use                                                      |
| ------- | ------------------------------ | ---------------------------------------------------------------- |
| B1      | Decision tree                  | Which hook to choose                                             |
| B2      | `doc_events`                   | **Most common.** Additive — multiple apps can hook               |
| B3      | `extend_doctype_class`         | **v16+ recommended.** Mixin-based, composable                    |
| B4      | `override_doctype_class`       | Replace controller. **Only one app can override**                |
| B5      | `override_whitelisted_methods` | Replace `frappe.call` API endpoint                               |
| B6      | `doctype_js`                   | Client-side form customization (see `write-client-script` skill) |
| B7      | Permission hooks               | `permission_query_conditions`, `has_permission`                  |
| B8      | `override_doctype_dashboards`  | Change linked document counts                                    |
| B9      | Other hooks                    | `standard_queries`, `ignore_links_on_delete`, timeline           |

---

## Choosing Between Methods

| Scenario                                       | Best Method                    |
| ---------------------------------------------- | ------------------------------ |
| Add validation without changing existing logic | `doc_events`                   |
| Add methods/properties to a controller (v16+)  | `extend_doctype_class`         |
| Need to override an existing controller method | `override_doctype_class`       |
| Replace a `frappe.call` API endpoint           | `override_whitelisted_methods` |
| Add buttons/UI to a form                       | `doctype_js`                   |
| Filter user's visible records                  | `permission_query_conditions`  |
| Control doc-level access                       | `has_permission`               |
| Control portal access                          | `has_website_permission`       |

> **Rule of thumb:** Prefer `doc_events` for event-driven logic. For v16+, prefer `extend_doctype_class` over `override_doctype_class` — it's composable and doesn't conflict with other apps.

---

## Directory Structure

```
{app_name}/{app_name}/
├── hooks.py                          # All hook registrations
├── overrides/                        # doc_events + override_doctype_class
│   ├── sales_order.py
│   ├── purchase_order.py
│   ├── project_dashboard.py          # override_doctype_dashboards
│   └── queries.py                    # standard_queries
├── extensions/                       # extend_doctype_class mixins (v16+)
│   └── sales_order.py
├── permissions.py                    # permission hooks
├── timeline.py                       # additional_timeline_content
├── {module}/
│   └── doctype/
│       └── {doctype_name}/
│           ├── {doctype_name}.py     # New controller
│           └── {doctype_name}.json   # DocType definition
└── public/
    └── js/
        ├── doctype_js/               # Form scripts
        ├── doctype_list_js/          # List view scripts
        └── doctype_tree_js/          # Tree view scripts
```

---

## Source References

> **AI INSTRUCTION:** Do NOT read these during normal skill execution. Listed for updating only.

- `apps/frappe/frappe/model/document.py` — `Document` base class with all lifecycle hooks
- `apps/frappe/frappe/model/naming.py` — Autoname/naming logic (`set_new_name`, `make_autoname`, `NamingSeries`)
- `apps/frappe/frappe/model/base_document.py` — `BaseDocument` with `db_set`, `get_doc_before_save`
- `apps/frappe/frappe/hooks.py` — Definitive list of all available hooks
- `apps/frappe/frappe/model/document.py` — Where `run_method` dispatches doc events
- `apps/frappe/frappe/permissions.py` — Permission hook dispatch
- `apps/erpnext/erpnext/controllers/accounts_controller.py` — GL entry patterns
- `apps/erpnext/erpnext/controllers/stock_controller.py` — Stock ledger patterns