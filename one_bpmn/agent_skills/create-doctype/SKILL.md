---
name: "create-doctype"
description: "Scaffold a new Frappe DocType with all boilerplate files \u2014 supports standard, child table, virtual, single, submittable, and tree variants with naming rules, controller base class selection, and permissions. Use this skill when a new DocType is needed, including a child table, virtual, single, submittable or tree variant. Do NOT use it to change a DocType that already exists."
---

# Create a DocType

## Prerequisites

Before creating a DocType, gather the following from the user:

1. **App name** — which custom app to create the DocType in (e.g., `my_app`)
2. **Module name** — the module within the app (e.g., `My Module`)
3. **DocType name** — Title Case, singular form (e.g., `Project Milestone`)
4. **DocType variant** — standard | child table | virtual | single
5. **Naming strategy** — how documents should be named (see Step 3)
6. **Is submittable?** — does the document have a submit/cancel workflow?
7. **Fields** — at minimum the core fields needed

---

## Detailed References

| Reference                                  | What's Inside                                                                                                                    |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| [Field Types](references/field-types.md)   | All fieldtypes (text, number, date, link, selection, media, layout), field properties (`reqd`, `depends_on`, `fetch_from`, etc.) |
| [Boilerplates](references/boilerplates.md) | Controller templates for all variants (standard, tree, virtual, child table, ERPNext), client script and test file templates     |
| [Controllers](references/controllers.md)   | Controller reference patterns                                                                                                    |

---

## Step 1: Create the Directory Structure

Every DocType needs a folder with these files:

```
apps/{app_name}/{app_name}/{module_snake}/doctype/{doctype_snake}/
├── {doctype_snake}.json        # Schema definition
├── {doctype_snake}.py          # Server controller
├── {doctype_snake}.js          # Client script
├── __init__.py                 # Empty file (required by Frappe)
└── test_{doctype_snake}.py     # Tests
```

Where:

- `{module_snake}` = module name in snake_case (e.g., `my_module`)
- `{doctype_snake}` = doctype name in snake_case (e.g., `project_milestone`)

**Also ensure:**

- The module is listed in `{app_name}/modules.txt` — one module name per line, Title Case:
  ```
  My Module
  Another Module
  ```
- The module directory `{app_name}/{module_snake}/` has an empty `__init__.py`
- The `{app_name}/{module_snake}/doctype/` directory has an empty `__init__.py`

> **Note:** All `__init__.py` files in Frappe apps are empty. Do not add any content to them.

---

## Step 2: Create the DocType JSON Schema

The JSON file defines the full DocType structure. Use this as the canonical template and adjust for your variant:

```json
{
  "actions": [],
  "allow_copy": 1,
  "allow_import": 1,
  "allow_rename": 0,
  "autoname": "naming_series:",
  "creation": "2025-01-01 00:00:00.000000",
  "doctype": "DocType",
  "editable_grid": 1,
  "engine": "InnoDB",
  "field_order": [],
  "fields": [
    {
      "fieldname": "naming_series",
      "fieldtype": "Select",
      "label": "Naming Series",
      "options": "PM-.YYYY.-.#####",
      "reqd": 1,
      "set_only_once": 1,
      "no_copy": 1
    },
    {
      "fieldname": "title",
      "fieldtype": "Data",
      "label": "Title",
      "reqd": 1,
      "in_list_view": 1
    },
    {
      "fieldname": "column_break_1",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "status",
      "fieldtype": "Select",
      "label": "Status",
      "options": "\nDraft\nIn Progress\nCompleted\nCancelled",
      "default": "Draft",
      "in_list_view": 1,
      "in_standard_filter": 1
    },
    {
      "fieldname": "section_break_1",
      "fieldtype": "Section Break",
      "label": "Details"
    },
    {
      "fieldname": "description",
      "fieldtype": "Text Editor",
      "label": "Description"
    },
    {
      "fieldname": "amended_from",
      "fieldtype": "Link",
      "label": "Amended From",
      "no_copy": 1,
      "options": "Project Milestone",
      "print_hide": 1,
      "read_only": 1
    }
  ],
  "index_web_pages_for_search": 0,
  "image_field": "",
  "is_submittable": 0,
  "is_tree": 0,
  "is_virtual": 0,
  "issingle": 0,
  "istable": 0,
  "links": [],
  "modified": "2025-01-01 00:00:00.000000",
  "modified_by": "Administrator",
  "module": "My Module",
  "name": "Project Milestone",
  "naming_rule": "By \"Naming Series\" field",
  "owner": "Administrator",
  "permissions": [
    {
      "create": 1,
      "delete": 1,
      "email": 1,
      "export": 1,
      "print": 1,
      "read": 1,
      "report": 1,
      "role": "System Manager",
      "share": 1,
      "write": 1
    }
  ],
  "show_title_field_in_link": 0,
  "sort_field": "creation",
  "sort_order": "DESC",
  "states": [],
  "title_field": "",
  "track_changes": 1
}
```

### DocType Variants — Adjust These Properties

| Variant         | Key JSON Overrides                                                                                  |
| --------------- | --------------------------------------------------------------------------------------------------- |
| **Standard**    | `istable=0`, `issingle=0`, `is_virtual=0` (default)                                                 |
| **Child Table** | `istable=1`, `editable_grid=1`, remove `permissions` array, remove `autoname`/`naming_rule`         |
| **Single**      | `issingle=1` — only one record exists (like Settings)                                               |
| **Virtual**     | `is_virtual=1` — no database table, controller handles storage                                      |
| **Submittable** | `is_submittable=1` — include the `amended_from` field, add `submit`/`cancel`/`amend` to permissions |
| **Tree**        | `is_tree=1` — hierarchical structure (like Chart of Accounts), add `nsm_parent_field`               |

> **Notes:**
>
> - Include `amended_from` field **only** for submittable DocTypes (`is_submittable=1`).
> - Set `title_field` to a fieldname (e.g., `"title"`) to display a human-readable name instead of the document ID.
> - Set `show_title_field_in_link` to `1` to show the title in Link fields instead of the name.
> - Set `image_field` to an Attach Image fieldname to show thumbnails in list views.
> - For all available field types and properties, see [Field Types reference](references/field-types.md).

### Permissions

```json
{
  "permissions": [
    {
      "role": "System Manager",
      "read": 1,
      "write": 1,
      "create": 1,
      "delete": 1,
      "submit": 0,
      "cancel": 0,
      "amend": 0,
      "report": 1,
      "export": 1,
      "import": 1,
      "print": 1,
      "email": 1,
      "share": 1
    }
  ]
}
```

> **Note:** Child tables (`istable=1`) do NOT have their own permissions — they inherit from the parent.

---

## Step 3: Configure Naming

The `autoname` and `naming_rule` properties in the JSON control how document names are generated. Choose one:

| Option                   | `naming_rule`              | `autoname`                           | Notes                                                                            |
| ------------------------ | -------------------------- | ------------------------------------ | -------------------------------------------------------------------------------- |
| **Naming Series**        | `By "Naming Series" field` | `naming_series:`                     | Add a `naming_series` Select field with options like `PM-.YYYY.-.#####`          |
| **Field-based**          | `By fieldname`             | `field:{fieldname}`                  | Name = value of a field (e.g., `field:project_name`)                             |
| **Format string**        | `Expression`               | `format:PM-{project}-{YYYY}-{#####}` | Placeholders: `{fieldname}`, `{YYYY}`, `{YY}`, `{MM}`, `{DD}`, `{WW}`, `{#####}` |
| **Hash**                 | `Random`                   | `hash`                               | Random unique 10-char string                                                     |
| **Prompt**               | `Set by user`              | `prompt`                             | User enters name manually                                                        |
| **Autoincrement**        | `Autoincrement`            | `autoincrement`                      | Integer sequence (1, 2, 3...)                                                    |
| **Custom method**        | _(any)_                    | _(ignored)_                          | Define `autoname(self)` in the controller to set `self.name`                     |
| **Document Naming Rule** | _(any)_                    | _(ignored)_                          | Create a `Document Naming Rule` record via UI — takes priority over `autoname`   |

> **For autoname implementation patterns** (controller `autoname()` method, `before_naming`, format placeholders, Document Naming Rule), see `doctype-controllers` skill, Section A2.

---

## Step 4: Create Controller & Boilerplate Files

Select the correct base class based on your DocType variant:

| DocType Setting            | Base Class                         | Import                                                                                 |
| -------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------- |
| **Standard** (default)     | `Document`                         | `from frappe.model.document import Document`                                           |
| **`is_tree=1`**            | `NestedSet`                        | `from frappe.utils.nestedset import NestedSet`                                         |
| **`is_virtual=1`**         | `Document` (with protocol methods) | `from frappe.model.document import Document`                                           |
| **Website page generator** | `WebsiteGenerator`                 | `from frappe.website.website_generator import WebsiteGenerator`                        |
| **Accounting transaction** | `AccountsController`               | `from erpnext.controllers.accounts_controller import AccountsController`               |
| **Inventory movement**     | `StockController`                  | `from erpnext.controllers.stock_controller import StockController`                     |
| **Sales transaction**      | `SellingController`                | `from erpnext.controllers.selling_controller import SellingController`                 |
| **Purchase transaction**   | `BuyingController`                 | `from erpnext.controllers.buying_controller import BuyingController`                   |
| **Subcontracting**         | `SubcontractingController`         | `from erpnext.controllers.subcontracting_controller import SubcontractingController`   |
| **Onboarding/separation**  | `EmployeeBoardingController`       | `from hrms.controllers.employee_boarding_controller import EmployeeBoardingController` |

> **For controller pattern details** (lifecycle hooks, validation, ERPNext controller inheritance chain), see the `doctype-controllers` skill, Section A1.
>
> **For complete boilerplate templates** (controller, client script, test file for all variants), see [Boilerplates reference](references/boilerplates.md).

---

## Step 5: Register and Migrate

After creating all files:

```bash
# Register the new DocType in the database
bench --site {site_name} migrate

# Clear cache
bench --site {site_name} clear-cache
```

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY so that if this skill needs to be updated or corrected, you can directly reference the source files without re-searching the codebase.

### Frappe Framework

- `apps/frappe/frappe/model/document.py` — `Document` base class
- `apps/frappe/frappe/model/naming.py` — All naming/autoname logic (`set_new_name`, `NamingSeries`, `make_autoname`, `parse_naming_series`)
- `apps/frappe/frappe/model/virtual_doctype.py` — `VirtualDoctype` protocol
- `apps/frappe/frappe/utils/nestedset.py` — `NestedSet` base class for tree DocTypes
- `apps/frappe/frappe/website/website_generator.py` — `WebsiteGenerator` base class
- `apps/frappe/frappe/core/doctype/doctype/doctype.py` — DocType meta validation
- `apps/frappe/frappe/custom/doctype/custom_field/custom_field.py` — `create_custom_fields()` API

### ERPNext Controllers

- `apps/erpnext/erpnext/controllers/status_updater.py` — `StatusUpdater(Document)`
- `apps/erpnext/erpnext/utilities/transaction_base.py` — `TransactionBase(StatusUpdater)`
- `apps/erpnext/erpnext/controllers/accounts_controller.py` — `AccountsController(TransactionBase)`
- `apps/erpnext/erpnext/controllers/stock_controller.py` — `StockController(AccountsController)`
- `apps/erpnext/erpnext/controllers/selling_controller.py` — `SellingController(StockController)`
- `apps/erpnext/erpnext/controllers/buying_controller.py` — `BuyingController(SubcontractingController)`
- `apps/erpnext/erpnext/controllers/subcontracting_controller.py` — `SubcontractingController(StockController)`

### HRMS

- `apps/hrms/hrms/controllers/employee_boarding_controller.py` — `EmployeeBoardingController(Document)`
- `apps/hrms/hrms/setup.py` — Custom fields pattern (`create_custom_fields` in `after_install`)