# Code Review Instructions for one_bpmn

This is a Frappe v15 app integrating Spiffworkflow BPMN engine with a Vue 3 frontend.
A significant portion of the code is AI-generated. Focus heavily on eliminating bloat.

## Philosophy: The Best Code Is the Code Not Written

- Flag dead code, unused imports, unused variables, and unreachable branches.
- Flag over-engineering: unnecessary abstractions, wrapper functions that just delegate, config objects that could be inline.
- Flag verbose patterns: prefer ternaries for simple assignments, destructuring over repetitive property access, early returns over nested blocks.
- Flag duplicated logic that should be extracted OR duplicated abstractions that should be inlined.
- If a function can be replaced by a built-in or library call, flag it.
- Remove comments that restate the code (e.g., `// set the value` above `setValue()`).

## Python (Frappe Backend)

- Formatting: tabs for indentation, double quotes, 110 char line length (ruff enforced).
- All API endpoints MUST use `@frappe.whitelist()`, typed parameters, and docstrings.
- Always call `doc.check_permission()` before mutations.
- Use `frappe.throw(_(...))` for user-facing errors, never bare `raise`.
- Never use raw SQL — use `frappe.db.get_value`, `frappe.get_list`, `frappe.get_all`.
- Prefer `frappe.db.exists()` over try/except for existence checks.
- DocTypes in this app: BPMN Process Model, BPMN Shape Library, BPMN Custom Shape.

## Spiffworkflow Integration

- BPMN XML must be validated before storage.
- Workflow execution must be idempotent — re-running a step must not cause side effects.
- Always handle SpiffWorkflow exceptions explicitly, never silently catch.
