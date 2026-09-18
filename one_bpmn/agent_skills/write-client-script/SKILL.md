---
name: "write-client-script"
description: "Write file-based client-side JavaScript for Frappe forms, lists, pages, and trees \u2014 doctype_js, doctype_list_js, doctype_tree_js, doctype_calendar_js, page_js, app_include_js/css, web_include_js/css, email_css, form event handlers, child table events, and common form API. Use this skill when writing desk JavaScript for a form, list, tree or page, or when registering one in hooks.py. Do NOT use it for the Processa Vue application under spiff."
---

# Write Client-Side Scripts

Use this skill when you need to add client-side behavior to Frappe forms, list views, pages, or include global JS/CSS.

> For building a standalone Vue.js SPA frontend, see the `build-vue-frontend` skill.

> **File-based vs Client Script DocType:** This skill covers **file-based scripts** (`.js` files bundled with your app, registered via `hooks.py`). Frappe also has a **Client Script** DocType for UI-created scripts stored in the database — those are for power users making quick customizations without app deployments and are not covered here.

---

## What Are You Building?

| Goal                                                       | Reference                                                                          |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Add form logic to a custom DocType you own                 | → [Form Scripts](references/form-scripts.md) (own DocType `.js` file)              |
| Handle child table row events                              | → [Child Table Events](references/form-scripts.md#child-table-events)              |
| Use common form API (set_value, toggle, buttons)           | → [Common Form API](references/form-scripts.md#common-form-api)                    |
| Inject form logic into a standard DocType from another app | → [doctype_js hook](references/hooks-and-includes.md#doctype_js-hook)              |
| Customize list view behavior                               | → [doctype_list_js](references/hooks-and-includes.md#doctype_list_js-hook)         |
| Customize tree view behavior                               | → [doctype_tree_js](references/hooks-and-includes.md#doctype_tree_js-hook)         |
| Customize calendar view behavior                           | → [doctype_calendar_js](references/hooks-and-includes.md#doctype_calendar_js-hook) |
| Inject JS into a specific Frappe page                      | → [page_js](references/hooks-and-includes.md#page_js-hook)                         |
| Include global JS/CSS on all desk pages                    | → [Global Includes](references/hooks-and-includes.md#global-includes)              |
| Include JS/CSS on public website pages                     | → [Website Includes](references/hooks-and-includes.md#website-includes)            |
| Include CSS in outgoing emails                             | → [Email CSS](references/hooks-and-includes.md#email-css)                          |
| Build a standalone Vue.js SPA                              | → Use `build-vue-frontend` skill                                                   |

---

## Detailed References

| Reference                                            | What's Inside                                                                                                                                                                                                                                                               |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Form Scripts](references/form-scripts.md)           | Form lifecycle events (`setup`, `refresh`, `validate`, `before_save`, etc.), field change handlers, child table events (`qty`, `items_remove`, `items_add`), common form API (`set_value`, `set_query`, `toggle_display`, custom buttons, dashboard indicators)             |
| [Hooks & Includes](references/hooks-and-includes.md) | `doctype_js` for injecting into standard DocTypes, `doctype_list_js` for list views, `doctype_tree_js` for tree views, `doctype_calendar_js` for calendars, `page_js` for specific pages, `app_include_js/css` for desk-wide, `web_include_js/css` for website, `email_css` |

---

## File Organization

**Own DocType scripts** live next to the DocType definition:

```
{app_name}/{module_snake}/doctype/{doctype_snake}/
└── {doctype_snake}.js    # Client controller
```

**Hook-based scripts** (injecting into other apps' DocTypes) live in `public/js/`:

```
{app_name}/{app_name}/public/js/
├── doctype_js/             # doctype_js scripts
│   ├── sales_order.js
│   └── employee.js
├── list_js/                # doctype_list_js scripts
│   └── sales_order_list.js
├── doctype_tree_js/        # doctype_tree_js scripts
│   └── warehouse_tree.js
├── calendar_js/            # doctype_calendar_js scripts
│   └── event_calendar.js
├── myapp.js                # app_include_js (global)
└── website.js              # web_include_js
```

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY for updating this skill.

- `apps/frappe/frappe/hooks.py` — `page_js`, `doctype_js`, `app_include_js/css`, `web_include_js/css`, `email_css`
- `apps/one_fm/one_fm/hooks.py` lines 51–66 — `page_js` example (roster, checkpoint-scan)
- `apps/one_fm/one_fm/hooks.py` lines 70–148 — `doctype_js` (60+ entries), `doctype_list_js`
- `apps/one_fm/one_fm/hooks.py` lines 148–150 — `doctype_tree_js` example (Warehouse)
- `apps/one_fm/one_fm/public/js/doctype_js/` — Example client scripts per DocType