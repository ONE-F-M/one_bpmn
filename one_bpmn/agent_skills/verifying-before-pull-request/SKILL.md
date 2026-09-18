---
name: "verifying-before-pull-request"
description: "Checks to run and report before opening a pull request in this bench: tests, a read of your own diff against the house rules, and what to say when a check could not run. Use this skill when you are about to call open_pull_request, when run_tests fails, or when you have tried the same fix more than twice. Do NOT use it for deciding what to build."
---

# Verify before you open a pull request

A reviewer sees the pull request, not your run. Anything you checked that you do
not write down is lost, and anything you skipped and do not mention reads as
passing.

## Order

1. Stop changing files.
2. `run_tests` once. Read the failures. A failure inside the test setup is not
   your change failing: say which it was.
3. Read your own diff. Check it against the list below.
4. `open_pull_request` with the report.

## Read your diff for these

- Raw SQL with string formatting. Use `frappe.qb` or the ORM.
- `ignore_permissions=True` with no role or permission check above it.
- `frappe.get_all` inside a whitelisted method. Use `frappe.get_list` there.
- A whitelisted method with no type annotations.
- User facing text not wrapped in `_()` in Python or `__()` in JavaScript.
- Inline `style="..."` in client script HTML.
- Comments that narrate the change, restate the next line, or carry a work item id.
- Secrets, tokens, API keys or local paths.
- Files you touched that the work order did not ask for.

## The report

Write it in the pull request body, in this shape:

```
Tests: passed | failed | could not run (reason)
Changed: <file> - <why>
Not verified: <what a reviewer still has to check>
```

Say "could not run" and the exact error when the suite dies before your tests.
Never say the tests passed unless the tool result said so.

## Stop rule

Three attempts at the same failure and you stop. Report what failed, what you
tried, and what you think it needs. A fourth attempt at the same error spends
turns you need for the pull request itself.
