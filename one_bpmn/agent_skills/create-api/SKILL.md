---
name: "create-api"
description: "Create API endpoints in Frappe \u2014 whitelisted methods, REST API patterns, scheduled jobs, server scripts, webhooks, and request/session lifecycle hooks. Use this skill when adding a whitelisted method, a REST endpoint, a scheduled job, a background job or a webhook. Do NOT use it for a Server Script that runs inside a BPMN process map."
---

# Create API Endpoints

Use this skill when you need to expose server-side functionality via HTTP endpoints, run scheduled background tasks, or hook into request/session lifecycle events.

---

## What Are You Building?

| Goal                                       | Reference                                                                                         |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Expose a Python function as an API         | → [Whitelisted Methods](references/whitelisted-methods.md)                                        |
| Schedule recurring background tasks        | → [Scheduler Events](references/scheduler-and-background-jobs.md#scheduler-events)                |
| Run a one-off long operation in background | → [Background Jobs](references/scheduler-and-background-jobs.md#enqueuing-background-jobs-ad-hoc) |
| Create a no-code API or event handler      | → [Server Scripts](references/server-scripts-and-webhooks.md#server-scripts)                      |
| Call external services on document events  | → [Webhooks](references/server-scripts-and-webhooks.md#webhooks)                                  |
| Run code on login/logout/request lifecycle | → [Lifecycle Hooks](references/server-scripts-and-webhooks.md#lifecycle-hooks)                    |

---

## Detailed References

| Reference                                                                               | What's Inside                                                                                                                                                       |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Whitelisted Methods](references/whitelisted-methods.md)                                | `@frappe.whitelist()` decorator, HTTP method restrictions, `@rate_limit()`, complete example with security layers, calling patterns                                 |
| [Scheduler & Background Jobs](references/scheduler-and-background-jobs.md)              | `scheduler_events` in hooks.py, all event types (all/hourly/daily/weekly/monthly/cron), long queues, task function patterns, `frappe.enqueue`, duplicate prevention |
| [Server Scripts, Webhooks & Lifecycle Hooks](references/server-scripts-and-webhooks.md) | Server Scripts (API, DocType Event, Scheduler Event, Permission Query), Webhooks (programmatic creation, conditions), session/request/job hooks                     |

---

## Security Checklist

1. **Always add type annotations** to whitelisted method parameters — Frappe auto-validates types at runtime
2. **Always check permissions** — `frappe.only_for()` for role checks, `doc.check_permission()` for doc-level
3. **Never use `ignore_permissions=True`** without explicit role checks first
4. **Use `frappe.get_list()`** instead of `frappe.get_all()` — `get_list` applies user permissions automatically
5. **Validate all inputs** — check existence, type, and business rules
6. **Restrict HTTP methods** — use `methods=["GET"]` for reads, `methods=["POST"]` for writes
7. **Add rate limiting** to public (`allow_guest=True`) endpoints

---

## File Organization

```
{app_name}/{app_name}/
├── api/
│   ├── __init__.py
│   ├── customers.py          # Customer-related endpoints
│   ├── reports.py            # Report-related endpoints
│   └── utils.py              # Shared API utilities
├── api/v1/                   # Versioned API (optional)
│   ├── __init__.py
│   └── customers.py
├── api/v2/
│   ├── __init__.py
│   └── customers.py
├── tasks.py                  # Scheduled task implementations
├── auth.py                   # Session hooks
└── middleware.py              # Request/job hooks
```

---

## Source References

> **AI INSTRUCTION:** Do NOT read these files during normal skill execution. They are listed here ONLY for updating this skill.

- `apps/frappe/frappe/hooks.py` — Scheduler events, session/request/job hooks, `override_whitelisted_methods`
- `apps/one_fm/one_fm/hooks.py` — Real-world scheduler_events with 30+ cron patterns
- `apps/one_fm/one_fm/api/` — API directory with versioned endpoints (v1, v2, v3)
- `apps/frappe/frappe/core/doctype/server_script/server_script.json` — Server Script DocType schema
- `apps/frappe/frappe/integrations/doctype/webhook/webhook.json` — Webhook DocType schema