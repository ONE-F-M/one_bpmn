# Test Patterns & Examples

## Test Fixture Patterns

### Pattern A: Inline Fixtures (Preferred for Custom Apps)

Create test data directly in `setUpClass` or helper methods:

```python
@classmethod
def setUpClass(cls):
    super().setUpClass()

    # Create with existence check to avoid duplicates across runs
    if not frappe.db.exists("Customer", "_Test Custom Customer"):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": "_Test Custom Customer",
            "customer_group": "All Customer Groups",
            "territory": "All Territories"
        }).insert(ignore_permissions=True)
```

### Pattern B: test_records.json (Standard Frappe Pattern)

Place a `test_records.json` file in the DocType directory. Frappe auto-loads these when running tests for that DocType:

```json
[
  {
    "doctype": "My Custom DocType",
    "field1": "_Test Value 1",
    "field2": 100,
    "items": [
      {
        "doctype": "My Custom DocType Item",
        "item_code": "_Test Item",
        "qty": 10,
        "rate": 50.0,
        "parentfield": "items"
      }
    ]
  }
]
```

### Pattern C: Helper Factory Functions (Recommended for Complex DocTypes)

Create reusable factory functions at module level:

```python
def make_my_doctype(**kwargs):
    """Factory function to create test documents with sensible defaults."""
    doc = frappe.get_doc({
        "doctype": "My Custom DocType",
        "title": kwargs.get("title", "_Test Title"),
        "status": kwargs.get("status", "Draft"),
        "customer": kwargs.get("customer", "_Test Customer"),
        "items": kwargs.get("items", [{
            "item_code": "_Test Item",
            "qty": kwargs.get("qty", 10),
            "rate": kwargs.get("rate", 100),
        }])
    })

    if not kwargs.get("do_not_save"):
        doc.insert(ignore_permissions=True)

        if not kwargs.get("do_not_submit") and doc.meta.is_submittable:
            doc.submit()

    return doc
```

Usage in tests:

```python
def test_basic_creation(self):
    doc = make_my_doctype(qty=5, rate=200)
    self.assertEqual(doc.items[0].amount, 1000)

def test_draft_state(self):
    doc = make_my_doctype(do_not_submit=True)
    self.assertEqual(doc.docstatus, 0)
```

---

## Common Test Patterns

### Testing Validation Logic

```python
def test_end_date_before_start_date(self):
    """Validation should prevent end_date < start_date."""
    doc = make_my_doctype(do_not_save=True)
    doc.start_date = "2025-06-15"
    doc.end_date = "2025-06-10"  # Before start

    with self.assertRaises(frappe.ValidationError):
        doc.insert()

def test_negative_value_rejected(self):
    doc = make_my_doctype(do_not_save=True)
    doc.amount = -100

    with self.assertRaises(frappe.ValidationError):
        doc.insert()
```

### Testing Submittable Documents

```python
def test_submission_workflow(self):
    doc = make_my_doctype(do_not_submit=True)
    self.assertEqual(doc.docstatus, 0)

    doc.submit()
    self.assertEqual(doc.docstatus, 1)

    doc.cancel()
    self.assertEqual(doc.docstatus, 2)

def test_cannot_modify_submitted(self):
    doc = make_my_doctype()  # auto-submitted
    self.assertEqual(doc.docstatus, 1)

    doc.some_field = "changed"
    with self.assertRaises(frappe.ValidationError):
        doc.save()
```

### Testing Permissions

```python
def test_role_based_access(self):
    doc = make_my_doctype()

    with self.set_user("test_restricted@example.com"):
        # Should NOT have write permission
        self.assertFalse(
            frappe.has_permission("My Custom DocType", "write", doc=doc)
        )

        # Should raise PermissionError on save
        doc.some_field = "hacked"
        with self.assertRaises(frappe.PermissionError):
            doc.save()

def test_whitelisted_method_permissions(self):
    """API method should check permissions."""
    from my_app.api.custom import restricted_method

    with self.set_user("test_restricted@example.com"):
        with self.assertRaises(frappe.PermissionError):
            restricted_method("some_arg")
```

### Testing Linked Documents

```python
def test_linked_document_creation(self):
    """Submitting parent should create child document."""
    parent = make_my_doctype(do_not_submit=True)
    parent.submit()

    # Verify linked document was created
    linked = frappe.get_all("Linked DocType",
        filters={"parent_ref": parent.name},
        fields=["name", "status"]
    )
    self.assertEqual(len(linked), 1)
    self.assertEqual(linked[0].status, "Active")

def test_cancel_reverses_linked(self):
    """Cancelling parent should cancel/cleanup linked documents."""
    parent = make_my_doctype()
    parent.cancel()

    linked = frappe.get_all("Linked DocType",
        filters={"parent_ref": parent.name},
        fields=["status"]
    )
    self.assertEqual(linked[0].status, "Cancelled")
```

### Testing Calculated Fields

```python
def test_totals_calculation(self):
    doc = make_my_doctype(do_not_save=True)
    doc.items = []
    doc.append("items", {"item_code": "_Test Item", "qty": 5, "rate": 200})
    doc.append("items", {"item_code": "_Test Item", "qty": 3, "rate": 150})
    doc.save()

    self.assertEqual(doc.items[0].amount, 1000)  # 5 * 200
    self.assertEqual(doc.items[1].amount, 450)    # 3 * 150
    self.assertEqual(doc.total, 1450)
```

### Testing with TestMixin (ERPNext Pattern)

For complex tests that need shared helper methods across test classes:

```python
# my_app/tests/my_mixin.py
class MyTestMixin:
    """Reusable test helpers for My App."""

    def create_test_customer(self, name="_Test My Customer"):
        if not frappe.db.exists("Customer", name):
            return frappe.get_doc({
                "doctype": "Customer",
                "customer_name": name,
                "customer_group": "All Customer Groups",
                "territory": "All Territories"
            }).insert(ignore_permissions=True)
        return frappe.get_doc("Customer", name)


# In test file:
from my_app.tests.my_mixin import MyTestMixin

class TestMyDocType(MyTestMixin, FrappeTestCase):
    def setUp(self):
        self.customer = self.create_test_customer()
```

---

## Complete Example: Custom DocType with Tests

### Controller

```python
# my_app/my_module/doctype/project_task/project_task.py
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

class ProjectTask(Document):
    def validate(self):
        self.validate_dates()
        self.calculate_progress()

    def validate_dates(self):
        if self.end_date and self.start_date:
            if getdate(self.end_date) < getdate(self.start_date):
                frappe.throw(_("End Date cannot be before Start Date"))

    def calculate_progress(self):
        if self.total_hours:
            self.progress = flt(self.completed_hours / self.total_hours * 100, 2)
        else:
            self.progress = 0

    def on_update(self):
        self.update_project_progress()

    def update_project_progress(self):
        if self.project:
            project = frappe.get_doc("Project", self.project)
            project.save()  # triggers project's recalculation
```

### Test File

```python
# my_app/my_module/doctype/project_task/test_project_task.py
import frappe
from frappe.tests.utils import FrappeTestCase, change_settings
from frappe.utils import add_days, today


def make_project_task(**kwargs):
    """Factory for test ProjectTask documents."""
    doc = frappe.get_doc({
        "doctype": "Project Task",
        "title": kwargs.get("title", "_Test Task"),
        "project": kwargs.get("project"),
        "start_date": kwargs.get("start_date", today()),
        "end_date": kwargs.get("end_date", add_days(today(), 7)),
        "total_hours": kwargs.get("total_hours", 40),
        "completed_hours": kwargs.get("completed_hours", 0),
    })

    if not kwargs.get("do_not_save"):
        doc.insert(ignore_permissions=True)

    return doc


class TestProjectTask(FrappeTestCase):
    def test_basic_creation(self):
        """Test that a task can be created with defaults."""
        doc = make_project_task()
        self.assertIsNotNone(doc.name)
        self.assertEqual(doc.title, "_Test Task")
        self.assertEqual(doc.progress, 0)

    def test_date_validation(self):
        """End date before start date should raise ValidationError."""
        doc = make_project_task(do_not_save=True)
        doc.start_date = "2025-06-15"
        doc.end_date = "2025-06-10"

        with self.assertRaises(frappe.ValidationError):
            doc.insert()

    def test_progress_calculation(self):
        """Progress should be calculated from hours."""
        doc = make_project_task(total_hours=40, completed_hours=10)
        self.assertEqual(doc.progress, 25.0)

        doc.completed_hours = 40
        doc.save()
        self.assertEqual(doc.progress, 100.0)

    def test_progress_with_zero_hours(self):
        """Progress should be 0 when total_hours is 0."""
        doc = make_project_task(total_hours=0, completed_hours=0)
        self.assertEqual(doc.progress, 0)

    def test_permissions(self):
        """Non-privileged user should not be able to delete."""
        doc = make_project_task()

        with self.set_user("test@example.com"):
            with self.assertRaises(frappe.PermissionError):
                frappe.delete_doc("Project Task", doc.name)
```