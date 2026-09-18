# Writing Controllers

Use this when implementing server-side logic in a DocType controller `.py` file.

> **Prerequisite:** The DocType and boilerplate files should already exist (see `create-doctype` skill).

---

## A1. Base Controller Classes

Choose the right base class:

| Base Class                 | When to Use                     | Import                                                                               |
| -------------------------- | ------------------------------- | ------------------------------------------------------------------------------------ |
| `Document`                 | Most custom DocTypes            | `from frappe.model.document import Document`                                         |
| `AccountsController`       | DocTypes that create GL entries | `from erpnext.controllers.accounts_controller import AccountsController`             |
| `StockController`          | DocTypes that affect stock      | `from erpnext.controllers.stock_controller import StockController`                   |
| `SellingController`        | Selling transactions            | `from erpnext.controllers.selling_controller import SellingController`               |
| `BuyingController`         | Buying transactions             | `from erpnext.controllers.buying_controller import BuyingController`                 |
| `SubcontractingController` | Subcontracting transactions     | `from erpnext.controllers.subcontracting_controller import SubcontractingController` |

**Inheritance chain:**

```
Document
└── TransactionBase
    └── AccountsController
        ├── SellingController
        │   └── (Sales Order, Sales Invoice, Quotation...)
        ├── BuyingController
        │   ├── SubcontractingController
        │   └── (Purchase Order, Purchase Invoice...)
        └── StockController
            └── (Stock Entry, Delivery Note...)
```

> **Rule:** Always call `super()` when inheriting from ERPNext controllers.

---

## A2. Autoname / Naming Patterns

Set in DocType JSON `autoname` field or via the `autoname` hook in the controller.

### Autoname Options (set in DocType JSON)

| Pattern        | Example `autoname` Value    | Generated Name                              |
| -------------- | --------------------------- | ------------------------------------------- |
| Naming Series  | `naming_series:`            | Uses the `naming_series` field on the form  |
| Field-based    | `field:employee_name`       | Uses the value of the `employee_name` field |
| Format string  | `format:PRJ-{YYYY}-{####}`  | `PRJ-2025-0001`                             |
| Hash (default) | `hash`                      | Random 10-char hash                         |
| Autoincrement  | `autoincrement`             | 1, 2, 3... (DB autoincrement)               |
| Prompt         | `prompt`                    | User enters the name manually               |
| Expression     | `naming_series:EMP-.YYYY.-` | `EMP-2025-00001`                            |

### Format String Placeholders

| Placeholder   | Resolves To                        |
| ------------- | ---------------------------------- |
| `{YYYY}`      | 4-digit year                       |
| `{YY}`        | 2-digit year                       |
| `{MM}`        | 2-digit month                      |
| `{DD}`        | 2-digit day                        |
| `{####}`      | Counter (number of `#` = digits)   |
| `{fieldname}` | Value of the field on the document |
| `{WW}`        | 2-digit week number                |

### Custom Autoname in Controller

```python
class MyDocType(Document):
    def autoname(self):
        # Option 1: Manual name
        self.name = f"{self.department}-{self.employee_id}"

    def before_naming(self):
        # Option 2: Modify naming_series before autoname runs
        if self.is_amendment:
            self.naming_series = "AMD-.####"
```

### Document Naming Rule (UI-Based)

Frappe v15+ provides a **Document Naming Rule** DocType for condition-based naming without code:

1. Go to **Document Naming Rule** list → **+ Add**
2. Set **Document Type** (e.g., `Sales Order`)
3. Set **Priority** (higher = checked first)
4. Add **Conditions** (e.g., `company == "ABC Corp"`)
5. Set the **Prefix** and **Suffix** pattern

Multiple rules can exist per DocType — the first matching condition wins. Rules take precedence over JSON `autoname` when conditions match.

---

## A3. Document Lifecycle Hooks

Hooks execute in this order. Implement only the hooks you need:

### Creation Flow

| Hook            | When                        | Common Use                                  |
| --------------- | --------------------------- | ------------------------------------------- |
| `before_insert` | Before INSERT query         | Set initial values, generate linked records |
| `before_naming` | Before name is set          | Modify naming inputs before `autoname` runs |
| `autoname`      | During INSERT, before save  | Custom naming logic (`self.name = ...`)     |
| `after_insert`  | After INSERT, before commit | Send notifications, create related docs     |

### Save Flow (every save, including insert)

| Hook              | When                                      | Common Use                                       |
| ----------------- | ----------------------------------------- | ------------------------------------------------ |
| `before_validate` | Before validation                         | Normalize data, set computed defaults            |
| `validate`        | **Main validation — most important hook** | Business rules, calculations, cross-field checks |
| `before_save`     | After validation, before UPDATE           | Set derived values, last-minute changes          |
| `on_update`       | After successful save to DB               | Update related records, clear caches             |
| `before_change`   | After `on_update`, before `on_change`     | Pre-process before final change hook             |
| `on_change`       | Final hook in the save lifecycle          | Trigger side effects that depend on saved state  |

### Submit/Cancel Flow (submittable DocTypes only)

| Hook                         | When                                 | Common Use                                     |
| ---------------------------- | ------------------------------------ | ---------------------------------------------- |
| `before_submit`              | Before docstatus changes to 1        | Final validation before locking                |
| `on_submit`                  | After submission                     | Create GL entries, stock entries, linked docs  |
| `before_cancel`              | Before docstatus changes to 2        | Validate cancel is allowed                     |
| `on_cancel`                  | After cancellation                   | **Reverse all side effects from on_submit**    |
| `before_update_after_submit` | Before amending submitted doc fields | Validate which changes are allowed post-submit |
| `on_update_after_submit`     | After amending submitted doc fields  | Process allowed-on-submit field changes        |

### Delete Flow

| Hook           | When            | Common Use                                           |
| -------------- | --------------- | ---------------------------------------------------- |
| `on_trash`     | Before deletion | Check for linked docs, prevent if dependencies exist |
| `after_delete` | After deletion  | Cleanup related records                              |

### Rename Flow

| Hook            | When                       | Common Use                                         |
| --------------- | -------------------------- | -------------------------------------------------- |
| `before_rename` | Before document is renamed | Validate rename is allowed, custom rename logic    |
| `after_rename`  | After document is renamed  | Update references in other documents, clear caches |

---

## A4. Validation Patterns

### Basic Field Validation

```python
def validate(self):
	self.validate_dates()
	self.validate_amounts()
	self.validate_status_transition()

def validate_dates(self):
	if self.end_date and self.start_date:
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(
				msg=_("End Date cannot be before Start Date"),
				title=_("Invalid Dates"),
			)

def validate_amounts(self):
	if flt(self.grand_total) < 0:
		frappe.throw(_("Grand Total cannot be negative"))

	for item in self.items:
		if flt(item.qty) <= 0:
			frappe.throw(
				_("Row {0}: Quantity must be greater than zero").format(item.idx)
			)
```

### Mandatory Conditional Validation

```python
def validate(self):
	if self.is_billable and not self.billing_rate:
		frappe.throw(
			msg=_("Billing Rate is required when Is Billable is checked"),
			title=_("Missing Required Field"),
		)
```

### Duplicate Prevention

```python
def validate_duplicate(self):
	if frappe.db.exists(self.doctype, {
		"employee": self.employee,
		"attendance_date": self.attendance_date,
		"name": ("!=", self.name),
		"docstatus": ("!=", 2),
	}):
		frappe.throw(
			_("Attendance already exists for {0} on {1}").format(
				self.employee, self.attendance_date
			)
		)
```

### Status Transition Validation

```python
VALID_TRANSITIONS = {
	"Draft": ["Pending", "Cancelled"],
	"Pending": ["Approved", "Rejected"],
	"Approved": ["Completed"],
}

def validate_status_change(self):
	if self.has_value_changed("status"):
		old_status = self.get_doc_before_save().status if self.get_doc_before_save() else "Draft"
		allowed = VALID_TRANSITIONS.get(old_status, [])
		if self.status not in allowed:
			frappe.throw(
				_("Cannot change status from {0} to {1}").format(old_status, self.status)
			)
```

---

## A5. Calculation Patterns

### Totals from Child Table

```python
def calculate_totals(self):
	self.total_qty = 0
	self.grand_total = 0

	for item in self.items:
		item.amount = flt(item.qty) * flt(item.rate)
		self.total_qty += flt(item.qty)
		self.grand_total += flt(item.amount)

	self.grand_total = flt(self.grand_total, self.precision("grand_total"))
```

### Setting Values from Linked Documents

```python
def set_missing_values(self):
	if self.customer and not self.customer_name:
		self.customer_name = frappe.db.get_value("Customer", self.customer, "customer_name")

	if self.project:
		project = frappe.db.get_value(
			"Project", self.project, ["company", "cost_center"], as_dict=True
		)
		if project:
			self.company = project.company
			self.cost_center = project.cost_center
```

---

## A6. Linked Document Operations

### Creating Related Documents on Submit

```python
def on_submit(self):
	self.create_task()

def create_task(self):
	task = frappe.get_doc({
		"doctype": "Task",
		"subject": _("Follow up: {0}").format(self.name),
		"project": self.project,
		"expected_start_date": self.start_date,
	})
	task.insert(ignore_permissions=True)
	self.db_set("task", task.name)
```

### Reversing Side Effects on Cancel

```python
def on_cancel(self):
	if self.task:
		task = frappe.get_doc("Task", self.task)
		if task.docstatus == 1:
			task.cancel()
		elif task.docstatus == 0:
			task.delete()
		self.db_set("task", "")
```

### Preventing Deletion When Linked

```python
def on_trash(self):
	if frappe.db.exists("Task", {"reference_name": self.name}):
		frappe.throw(_("Cannot delete {0}: linked Tasks exist").format(self.name))
```

---

## A7. Database Update Patterns

| Method                     | Triggers Hooks                     | Use When                                    |
| -------------------------- | ---------------------------------- | ------------------------------------------- |
| `doc.save()`               | ✅ Yes (validate, on_update, etc.) | You need validation and side effects        |
| `doc.db_set(field, value)` | ❌ No                              | Simple status updates, counters, timestamps |
| `frappe.db.set_value()`    | ❌ No                              | Updating another document's field quickly   |

```python
# Single field — fast, no hooks triggered
self.db_set("status", "Completed")

# Multiple fields — single query
self.db_set({
	"status": "Completed",
	"completion_date": today(),
	"completed_by": frappe.session.user,
})
```

---

## A8. Background Processing

```python
def on_submit(self):
	if len(self.items) > 100:
		frappe.enqueue(
			method="myapp.module.doctype.my_doc.my_doc.process_items_background",
			queue="long",
			timeout=1500,
			doc_name=self.name,
		)
		frappe.msgprint(_("Processing started in background."))
	else:
		self.process_items()

# Module-level function for enqueue
def process_items_background(doc_name):
	doc = frappe.get_doc("My DocType", doc_name)
	doc.process_items()
	doc.db_set("processing_status", "Completed")

	frappe.publish_realtime(
		event="processing_complete",
		message={"doc_name": doc_name},
		user=doc.owner,
	)
```

---

## A9. ERPNext-Specific Patterns

### GL Entry Creation (AccountsController)

```python
from erpnext.controllers.accounts_controller import AccountsController

class CustomInvoice(AccountsController):
	def on_submit(self):
		super().on_submit()
		self.make_gl_entries()

	def on_cancel(self):
		super().on_cancel()
		self.make_gl_entries(cancel=True)

	def make_gl_entries(self, cancel=False):
		from erpnext.accounts.general_ledger import make_gl_entries
		gl_entries = self.get_gl_entries()
		if gl_entries:
			make_gl_entries(gl_entries, cancel=cancel)
```

### Stock Ledger Updates (StockController)

```python
from erpnext.controllers.stock_controller import StockController

class CustomStockMovement(StockController):
	def on_submit(self):
		super().on_submit()
		self.update_stock_ledger()

	def on_cancel(self):
		super().on_cancel()
		self.update_stock_ledger()
```

---

## A10. Common Imports

```python
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	flt,       # Safe float conversion with precision
	cint,      # Safe integer conversion
	cstr,      # Safe string conversion
	today,     # Current date as string
	nowdate,   # Same as today()
	now,       # Current datetime as string
	getdate,   # Parse date string to date object
	add_days,  # Date arithmetic
	add_months,
	date_diff, # Days between two dates
	get_link_to_form,  # HTML link to a document
)
```