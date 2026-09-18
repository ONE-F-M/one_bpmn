# Controller Reference: ERPNext Hierarchy

> **AI INSTRUCTION:** Read this file only when the user is creating a DocType that inherits from an ERPNext controller and needs to understand what the base class provides.

## Inheritance Chain

```
Document (frappe.model.document)
 └── StatusUpdater (erpnext.controllers.status_updater)
      └── TransactionBase (erpnext.utilities.transaction_base)
           └── AccountsController (erpnext.controllers.accounts_controller)
                └── StockController (erpnext.controllers.stock_controller)
                     ├── SellingController (erpnext.controllers.selling_controller)
                     └── SubcontractingController (erpnext.controllers.subcontracting_controller)
                          └── BuyingController (erpnext.controllers.buying_controller)
```

---

## StatusUpdater

**Import:** `from erpnext.controllers.status_updater import StatusUpdater`

**Use for:** DocTypes that track fulfillment/completion status against linked documents.

**Key features:**

- `update_prevdoc_status()` — updates status of linked previous documents
- Over-allowance checks — validates qty/amount doesn't exceed linked doc limits
- `status_updater` list — define rules for automatic status transitions

---

## TransactionBase

**Import:** `from erpnext.utilities.transaction_base import TransactionBase`

**Use for:** Transaction DocTypes that need address and contact linking.

**Key features:**

- `validate_posting_time()` — validates transaction date/time
- Address and contact field setters
- `get_address_display()` — formats address for display

---

## AccountsController

**Import:** `from erpnext.controllers.accounts_controller import AccountsController`

**Use for:** DocTypes that create GL (General Ledger) entries — custom invoices, journal-like entries.

**Key features:**

- Tax calculation via `calculate_taxes_and_totals`
- GL entry creation via `make_gl_entries()`
- Payment schedule management
- Advance payment handling
- Budget validation
- Currency conversion
- Payment terms template processing
- Inter-company transaction support

**Example:**

```python
from erpnext.controllers.accounts_controller import AccountsController

class CustomInvoice(AccountsController):
	def validate(self):
		super().validate()  # Calculates taxes, totals
		self.validate_custom_rules()

	def on_submit(self):
		super().on_submit()
		self.make_gl_entries()

	def on_cancel(self):
		super().on_cancel()
		self.make_gl_entries(cancel=True)
```

---

## StockController

**Import:** `from erpnext.controllers.stock_controller import StockController`

**Use for:** DocTypes that create Stock Ledger Entries (inventory movements).

**Key features:**

- Stock ledger entry creation
- Batch and serial number handling (Serial and Batch Bundle)
- Quality inspection validation
- Warehouse validation
- Stock valuation

**Example:**

```python
from erpnext.controllers.stock_controller import StockController

class CustomStockMovement(StockController):
	def validate(self):
		super().validate()
		self.validate_warehouse()

	def on_submit(self):
		super().on_submit()
		self.update_stock_ledger()

	def on_cancel(self):
		super().on_cancel()
		self.update_stock_ledger()
```

---

## SellingController

**Import:** `from erpnext.controllers.selling_controller import SellingController`

**Use for:** Sales transactions (Sales Order, Sales Invoice, Delivery Note, Quotation).

**Key features (in addition to StockController):**

- Selling-specific pricing and discounts
- Sales team commission calculations
- Customer credit limit validation
- Blanket order handling
- Billing address management

**Example:**

```python
from erpnext.controllers.selling_controller import SellingController

class CustomQuotation(SellingController):
	def validate(self):
		super().validate()  # Pricing, taxes, sales team
		self.validate_custom_selling_rules()
```

---

## BuyingController

**Import:** `from erpnext.controllers.buying_controller import BuyingController`

**Use for:** Purchase transactions (Purchase Order, Purchase Invoice, Purchase Receipt).

**Key features (in addition to SubcontractingController → StockController):**

- Buying-specific pricing
- Supplier validation and quotation handling
- Purchase-specific tax handling
- Landed cost allocation

**Example:**

```python
from erpnext.controllers.buying_controller import BuyingController

class CustomPurchaseOrder(BuyingController):
	def validate(self):
		super().validate()  # Supplier validation, pricing
		self.validate_custom_buying_rules()
```

---

## SubcontractingController

**Import:** `from erpnext.controllers.subcontracting_controller import SubcontractingController`

**Use for:** Subcontracting transactions that involve sending raw materials to a supplier.

**Key features (in addition to StockController):**

- Raw material tracking and transfer
- BOM (Bill of Materials) validation
- Subcontracted item management

---

## HRMS: EmployeeBoardingController

**Import:** `from hrms.controllers.employee_boarding_controller import EmployeeBoardingController`

**Use for:** Employee onboarding/separation DocTypes.

**Key features:**

- Automatic project and task creation on submit
- Task assignment to users/roles based on activity template
- Holiday-aware task date scheduling
- Notification sending
- Automatic cleanup on cancel (deletes project + tasks)