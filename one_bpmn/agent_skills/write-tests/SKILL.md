---
name: "write-tests"
description: "How to write, run, and execute unit tests and integration tests for Frappe/ERPNext custom apps. Includes bench run-tests CLI commands, test runner options (--module, --case, --doctype, --failfast, --skip-test-records), FrappeTestCase, test fixtures, assertions, and permission testing. Use this skill when writing or running tests for a Frappe app. Do NOT use it for tests in the Processa Vue application or the mobile app."
---

# Writing Tests for Frappe/ERPNext Apps

## What Kind of Test?

```
What are you testing?
│
├─ DocType controller (validate, on_submit, on_cancel)?
│  └─ Integration test in doctype/test_<doctype>.py
│     └─ Inherit from FrappeTestCase
│
├─ Whitelisted API method?
│  └─ Integration test in test file near the API module
│     └─ Test permissions + business logic + error cases
│
├─ Pure utility function (no DB access)?
│  └─ Unit test — mock DB calls, test logic only
│     └─ Inherit from unittest.TestCase (or FrappeTestCase)
│
├─ External HTTP calls?
│  └─ Inherit from MockedRequestTestCase
│     └─ Uses `responses` library to mock HTTP
│
└─ Need to change system settings temporarily?
   └─ Use @change_settings decorator or context manager
```

---

## Detailed References

| Reference                                               | What's Inside                                                                                                                                                                                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [Test Utilities & API](references/test-utilities.md)    | FrappeTestCase base class, custom assertions (`assertDocumentEqual`, `assertQueryCount`, `assertRowsRead`), context managers (`set_user`, `freeze_time`, `change_settings`, `patch_hooks`, `timeout`), `MockedRequestTestCase` |
| [Test Patterns & Examples](references/test-patterns.md) | Fixture patterns (inline, test_records.json, factory functions), common test patterns (validation, submit/cancel, permissions, linked docs, calculations), TestMixin, complete example                                         |

---

## Test File Location & Naming

Tests live next to the code they test:

```
my_app/
└── my_module/
    └── doctype/
        └── my_doctype/
            ├── my_doctype.py           # Controller
            ├── my_doctype.json         # Definition
            ├── test_my_doctype.py      # ← Test file
            └── test_records.json       # ← Optional fixture data
```

**Naming rules:**

- Test file: `test_<doctype_snake_case>.py`
- Test class: `Test<DocTypePascalCase>(FrappeTestCase)`
- Test methods: `test_<what_is_being_tested>(self)`
- Prefix test data with `_Test` (e.g., `_Test Item`, `_Test Customer`)

---

## Running Tests

### Bench CLI Commands

```bash
# Run ALL tests for your app
bench --site mysite.localhost run-tests --app my_app

# Run tests for a specific DocType
bench --site mysite.localhost run-tests --doctype "My Custom DocType"

# Run tests for all DocTypes in a module
bench --site mysite.localhost run-tests --module-def "My Module"

# Run a specific test class
bench --site mysite.localhost run-tests --case "TestMyDocType"

# Run a specific test method
bench --site mysite.localhost run-tests --test test_validation_logic

# Run tests in a specific Python module
bench --site mysite.localhost run-tests --module my_app.my_module.doctype.my_doctype.test_my_doctype

# Run with coverage report
bench --site mysite.localhost run-tests --app my_app --coverage

# Stop on first failure (fast feedback)
bench --site mysite.localhost run-tests --app my_app --failfast

# Skip auto-loading test records (faster for unit tests)
bench --site mysite.localhost run-tests --app my_app --skip-test-records

# Generate JUnit XML report (for CI)
bench --site mysite.localhost run-tests --app my_app --junit-xml-output test-results.xml
```

### Direct pytest Execution (Alternative)

```bash
# If your app supports pytest
cd apps/my_app
python -m pytest my_app/my_module/doctype/my_doctype/test_my_doctype.py -v

# With coverage
python -m pytest --cov=my_app --cov-report=html
```

---

## Test Coverage Expectations

Every custom app should test:

| What                   | How                                                                   | Priority   |
| ---------------------- | --------------------------------------------------------------------- | ---------- |
| **DocType validation** | Test `validate()` with invalid data → `assertRaises(ValidationError)` | **High**   |
| **Calculated fields**  | Test `validate()` / `before_save()` calculations                      | **High**   |
| **Submit/Cancel**      | Test lifecycle for submittable docs                                   | **High**   |
| **Whitelisted APIs**   | Test return values, permission checks, error cases                    | **High**   |
| **Permissions**        | Test with different user roles via `set_user`                         | **Medium** |
| **Edge cases**         | None values, empty strings, large numbers, duplicates                 | **Medium** |
| **Linked documents**   | Test creation/cancellation of related docs                            | **Medium** |
| **Background jobs**    | Test the enqueued function directly (not `frappe.enqueue`)            | **Low**    |
| **Performance**        | Use `assertQueryCount` for critical paths                             | **Low**    |