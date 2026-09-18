# Test Utilities & API Reference

## FrappeTestCase — The Base Class

**ALWAYS inherit from `FrappeTestCase`, not `unittest.TestCase`.**

`FrappeTestCase` provides:

- **Automatic rollback** after each test class (no leftover test data)
- **Commit on `setUpClass`** to flush pending changes
- **Thread-local restoration** (flags, error_log, message_log)
- **Custom assertions** for documents, queries, and performance
- **Context managers** for user switching, time freezing, DB connections

```python
import frappe
from frappe.tests.utils import FrappeTestCase

class TestMyDocType(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()  # MUST call super
        # One-time setup: create shared test fixtures
        cls.create_test_data()

    def setUp(self):
        # Runs before EACH test method
        frappe.set_user("Administrator")

    def tearDown(self):
        # Runs after EACH test method
        frappe.set_user("Administrator")

    def test_something(self):
        # Your test logic here
        pass

    @classmethod
    def create_test_data(cls):
        """Create fixtures needed by all tests in this class."""
        if not frappe.db.exists("Item", "_Test Skill Item"):
            frappe.get_doc({
                "doctype": "Item",
                "item_code": "_Test Skill Item",
                "item_name": "_Test Skill Item",
                "item_group": "Products",
                "stock_uom": "Nos"
            }).insert(ignore_permissions=True)
```

> **CRITICAL:** Always call `super().setUpClass()` — it sets up rollback.
> Do NOT call `frappe.db.commit()` in tests unless absolutely necessary.
> All changes auto-rollback after the test class completes.

---

## Custom Assertions

### assertDocumentEqual — Compare Documents

Compares expected fields against an actual document, with smart handling of floats (uses field precision), booleans, and child tables:

```python
def test_document_values(self):
    doc = make_my_doctype(qty=10, rate=100)
    doc.reload()

    self.assertDocumentEqual(
        {
            "customer": "_Test Customer",
            "grand_total": 1000.0,
            "items": [
                {"item_code": "_Test Item", "qty": 10, "rate": 100.0}
            ]
        },
        doc
    )
```

### assertQueryCount — Performance Guard

Ensures a code block doesn't exceed a query count:

```python
def test_no_n_plus_one(self):
    make_my_doctype()
    make_my_doctype()
    make_my_doctype()

    with self.assertQueryCount(5):
        # This should fetch all 3 docs in ≤5 queries
        frappe.get_list("My Custom DocType", fields=["name", "customer"])
```

### assertRowsRead — DB Row Access Guard

```python
def test_efficient_query(self):
    with self.assertRowsRead(100):
        # Should not scan more than 100 rows
        frappe.get_list("My Custom DocType",
            filters={"status": "Active"},
            fields=["name"]
        )
```

### assertRedisCallCounts — Cache Efficiency Guard

```python
def test_caching_works(self):
    with self.assertRedisCallCounts(2):
        # Should hit Redis at most twice
        frappe.get_cached_doc("System Settings")
        frappe.get_cached_doc("System Settings")  # Cached → no extra call
```

### Standard unittest Assertions

These are the most commonly used assertions from `unittest.TestCase` in Frappe tests:

```python
# Value equality
self.assertEqual(doc.status, "Draft")
self.assertNotEqual(doc.name, "")

# Boolean checks
self.assertTrue(frappe.db.exists("Customer", "_Test Customer"))
self.assertFalse(doc.is_cancelled)
self.assertIsNotNone(doc.name)
self.assertIsNone(doc.optional_field)

# Numeric
self.assertAlmostEqual(doc.total, 999.99, places=2)
self.assertGreater(doc.qty, 0)
self.assertLessEqual(doc.discount, 20)

# Collections
self.assertIn("item_code", result)
self.assertNotIn("secret_field", public_data)

# Types
self.assertIsInstance(result, dict)

# Exceptions (CRITICAL for validation testing)
self.assertRaises(frappe.ValidationError, doc.insert)
self.assertRaises(frappe.PermissionError, frappe.delete_doc, "Customer", "_Test Customer")

# Context manager form (preferred — allows checking message)
with self.assertRaises(frappe.ValidationError) as cm:
    doc.insert()
self.assertIn("cannot be negative", str(cm.exception))
```

---

## Context Managers & Decorators

### set_user — Test as Different User

```python
def test_non_admin_access(self):
    doc = make_my_doctype()

    with self.set_user("test@example.com"):
        # Code runs as test@example.com
        self.assertTrue(
            frappe.has_permission("My Custom DocType", "read", doc=doc)
        )
        self.assertFalse(
            frappe.has_permission("My Custom DocType", "delete", doc=doc)
        )

    # Automatically restored to previous user
```

### freeze_time — Control Time in Tests

```python
def test_date_based_logic(self):
    with self.freeze_time("2025-01-15 10:30:00"):
        doc = make_my_doctype()
        self.assertEqual(doc.posting_date, "2025-01-15")
```

### change_settings — Temporarily Modify Settings

As a **decorator**:

```python
from frappe.tests.utils import change_settings

@change_settings("Selling Settings", {"allow_zero_qty_in_sales_order": 1})
def test_zero_qty_allowed(self):
    doc = make_my_doctype(qty=0)
    doc.save()  # Should not raise
    self.assertEqual(doc.items[0].qty, 0)
```

As a **context manager**:

```python
def test_setting_changes(self):
    with change_settings("Stock Settings", {"default_warehouse": "_Test Warehouse - _TC"}):
        # Setting is changed
        self.assertEqual(
            frappe.db.get_single_value("Stock Settings", "default_warehouse"),
            "_Test Warehouse - _TC"
        )
    # Setting automatically restored
```

### patch_hooks — Override Hooks in Tests

```python
from frappe.tests.utils import patch_hooks

def test_custom_hook_behavior(self):
    with patch_hooks({"on_session_creation": ["my_app.auth.custom_session_handler"]}):
        # Test with overridden hook
        pass
```

### timeout — Prevent Infinite Loops

```python
from frappe.tests.utils import timeout

@timeout(seconds=10)
def test_potentially_slow_operation(self):
    # Raises exception if takes > 10 seconds
    result = process_large_dataset()
    self.assertIsNotNone(result)
```

---

## MockedRequestTestCase — Testing External HTTP Calls

For testing code that makes external HTTP requests:

```python
from frappe.tests.utils import MockedRequestTestCase

class TestExternalAPI(MockedRequestTestCase):
    def test_api_call(self):
        # Mock external endpoint
        self.responses.add(
            self.responses.GET,
            "https://api.example.com/data",
            json={"status": "ok", "result": 42},
            status=200
        )

        # Your code that calls the external API
        from my_app.integrations.example import fetch_data
        result = fetch_data()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(self.responses.calls), 1)

    def test_api_failure(self):
        self.responses.add(
            self.responses.GET,
            "https://api.example.com/data",
            json={"error": "not found"},
            status=404
        )

        from my_app.integrations.example import fetch_data
        with self.assertRaises(frappe.ValidationError):
            fetch_data()
```

---

## Source References

| File                                                      | What It Provides                                                                                                                    |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `frappe/tests/utils.py`                                   | `FrappeTestCase`, `MockedRequestTestCase`, `change_settings`, `timeout`, `patch_hooks`                                              |
| `erpnext/selling/doctype/sales_order/test_sales_order.py` | Real-world test patterns: factory functions, `setUpClass`/`tearDownClass`, `change_settings` decorator, permission tests, TestMixin |
| `erpnext/tests/test_accounts_mixin.py`                    | TestMixin pattern — reusable helper methods across test classes                                                                     |
| `frappe/tests/test_*.py` (76+ files)                      | Framework-level test examples for DB, API, hooks, caching, etc.                                                                     |