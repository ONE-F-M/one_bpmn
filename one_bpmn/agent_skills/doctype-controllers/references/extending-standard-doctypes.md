# Extending Standard DocTypes

Use this when modifying the behavior of standard Frappe/ERPNext DocTypes **from your custom app**. All changes go in `hooks.py`.

> **Never modify core Frappe/ERPNext files directly.** Always use hooks.

---

## B1. Decision Tree: Which Hook?

| Goal                                                 | Hook                           | When                                                    |
| ---------------------------------------------------- | ------------------------------ | ------------------------------------------------------- |
| Run code on document events (validate, submit, etc.) | `doc_events`                   | **Most common.** Additive — multiple apps can hook.     |
| Add methods/properties to controller (v16+)          | `extend_doctype_class`         | **Recommended.** Mixin-based, composable.               |
| Replace the entire controller class                  | `override_doctype_class`       | Override parent methods. **Only one app can override.** |
| Replace a whitelisted API endpoint                   | `override_whitelisted_methods` | Change result of `frappe.call` to a standard method     |
| Add buttons/fields/logic to form UI                  | `doctype_js`                   | Client-side form customization                          |
| Customize list view                                  | `doctype_list_js`              | List view rendering, indicators, buttons                |
| Customize tree view                                  | `doctype_tree_js`              | Tree view node rendering                                |
| Override form dashboard                              | `override_doctype_dashboards`  | Change linked document counts                           |
| Control visible records                              | `permission_query_conditions`  | SQL WHERE clause appended to list queries               |
| Control doc-level access                             | `has_permission`               | Python function returning True/False                    |
| Control portal access                                | `has_website_permission`       | Portal/website visitor access                           |
| Override link field search                           | `standard_queries`             | Customize dropdown/link results                         |
| Skip link validation on delete                       | `ignore_links_on_delete`       | Prevent "linked document" errors on delete              |
| Add custom timeline entries                          | `additional_timeline_content`  | Custom content in form timeline                         |

---

## B2. `doc_events` (Add Logic to Lifecycle Hooks)

Most common and safest. Your functions run **in addition to** the standard controller logic. Multiple apps can hook the same event.

> **Hook execution order:** See [writing-controllers.md](writing-controllers.md), Section A3 for the complete lifecycle hook order — your `doc_events` handlers run at the same point in the lifecycle as the controller method they hook into.

### hooks.py

```python
doc_events = {
	"Sales Order": {
		"validate": [
			"myapp.overrides.sales_order.validate_custom_rules",
			"myapp.overrides.sales_order.calculate_custom_fields",
		],
		"on_submit": "myapp.overrides.sales_order.on_submit_custom",
		"on_cancel": "myapp.overrides.sales_order.on_cancel_custom",
	},
	# Wildcard: runs for ALL doctypes
	"*": {
		"on_update": "myapp.overrides.global_hooks.log_all_changes",
	},
}
```

### Handler Signature

```python
# myapp/overrides/sales_order.py
import frappe
from frappe import _

def validate_custom_rules(doc, method):
	"""
	Args:
		doc: The document object (e.g., Sales Order instance)
		method: The event name string (e.g., "validate")
	"""
	if doc.custom_requires_approval and not doc.custom_approved_by:
		frappe.throw(_("Approval is required before saving"))
```

### When to Use

- ✅ Adding validation rules to standard DocTypes
- ✅ Creating linked documents on events
- ✅ Updating related records, sending notifications
- ❌ **Not** for replacing existing behavior

---

## B3. `extend_doctype_class` (v16+ Mixin — Recommended)

Adds methods and properties **without replacing** the controller. Multiple apps can extend.

### hooks.py

```python
extend_doctype_class = {
	"Sales Order": ["myapp.extensions.sales_order.SalesOrderMixin"],
}
```

### Mixin Class

```python
# myapp/extensions/sales_order.py
from frappe.model.document import Document

class SalesOrderMixin(Document):
	@property
	def full_customer_address(self):
		return f"{self.customer_address}, {self.territory}"

	def custom_validation(self):
		if self.custom_field and not self.custom_other_field:
			frappe.throw(_("Custom Other Field is required"))

	def validate(self):
		super().validate()
		self.custom_validation()
```

---

## B4. `override_doctype_class` (Replace Controller)

Replaces the entire controller class. **Only one app can override a DocType.**

### hooks.py

```python
override_doctype_class = {
	"Sales Order": "myapp.overrides.sales_order.CustomSalesOrder",
}
```

### Override Class

```python
# myapp/overrides/sales_order.py
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

class CustomSalesOrder(SalesOrder):
	def validate(self):
		super().validate()  # ALWAYS call parent first
		self.validate_custom_rules()

	def on_submit(self):
		super().on_submit()
		self.create_linked_records()

	# Override existing methods
	def set_missing_values(self, *args, **kwargs):
		super().set_missing_values(*args, **kwargs)
		if not self.custom_default_field:
			self.custom_default_field = "Default Value"
```

---

## B5. `override_whitelisted_methods` (Replace API)

```python
# hooks.py
override_whitelisted_methods = {
	"erpnext.selling.doctype.sales_order.sales_order.make_delivery_note":
		"myapp.overrides.sales_order.custom_make_delivery_note",
}

# myapp/overrides/sales_order.py
@frappe.whitelist()
def custom_make_delivery_note(source_name, target_doc=None):
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	delivery_note = make_delivery_note(source_name, target_doc)
	delivery_note.custom_field = "Custom Value"
	return delivery_note
```

---

## B6. `doctype_js` (Client-Side Extension)

Register in `hooks.py` — the JS files run **in addition to** the standard form script:

```python
# hooks.py
doctype_js = {
	"Sales Order": "public/js/doctype_js/sales_order.js",
}
doctype_list_js = {
	"Sales Order": "public/js/doctype_list_js/sales_order_list.js",
}
doctype_tree_js = {
	"Warehouse": "public/js/doctype_tree_js/warehouse_tree.js",
}
```

> **For writing the actual JS files** (form events, child table events, common API), see the `write-client-script` skill.

---

## B7. Permission Hooks

### Permission Query Conditions

```python
# hooks.py
permission_query_conditions = {
	"Sales Order": "myapp.permissions.sales_order_conditions",
}

# myapp/permissions.py
def sales_order_conditions(user):
	if "Sales Manager" in frappe.get_roles(user):
		return ""  # No restrictions
	return "(`tabSales Order`.owner = '{user}')".format(user=frappe.db.escape(user))
```

### Has Permission

```python
# hooks.py
has_permission = {
	"Sales Order": "myapp.permissions.has_sales_order_permission",
}

def has_sales_order_permission(doc, ptype, user):
	if ptype == "read" and doc.owner == user:
		return True
	return None  # Fall through to standard checks
```

### Has Website Permission

```python
# hooks.py
has_website_permission = {
	"Sales Order": "myapp.permissions.sales_order_website_permission",
}

def sales_order_website_permission(doc, ptype, user, verbose=False):
	if doc.contact_email == user:
		return True
	return False
```

---

## B8. Dashboard Override

```python
# hooks.py
override_doctype_dashboards = {
	"Project": "myapp.overrides.project_dashboard.get_data",
}

# myapp/overrides/project_dashboard.py
def get_data():
	return {
		"fieldname": "project",
		"non_standard_fieldnames": {
			"Custom DocType": "custom_project_field",
		},
		"transactions": [
			{"label": _("Custom"), "items": ["Custom DocType"]},
		],
	}
```

---

## B9. Other Hooks

### Standard Queries (override link search)

```python
# hooks.py
standard_queries = {
	"Employee": "myapp.overrides.queries.employee_query",
}

# myapp/overrides/queries.py
import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Locate

def employee_query(doctype, txt, searchfield, start, page_len, filters):
	Employee = DocType("Employee")
	query = (
		frappe.qb.from_(Employee)
		.select(Employee.name, Employee.employee_name, Employee.department)
		.where(Employee.status == "Active")
		.where(
			(Employee[searchfield].like(f"%{txt}%"))
			| (Employee.employee_name.like(f"%{txt}%"))
		)
		.orderby(Employee.employee_name)
		.limit(page_len)
		.offset(start)
	)
	return query.run()
```

### Ignore Links on Delete

```python
# hooks.py
ignore_links_on_delete = ["Communication", "ToDo", "Activity Log"]
```

### Additional Timeline Content

```python
# hooks.py
additional_timeline_content = {
	"*": ["myapp.timeline.all_timeline"],
	"Sales Order": ["myapp.timeline.so_timeline"],
}
```