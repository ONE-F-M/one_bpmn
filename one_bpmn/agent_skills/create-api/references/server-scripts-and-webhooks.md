# Server Scripts, Webhooks & Lifecycle Hooks

## Server Scripts

No-code/low-code alternative to whitelisted methods and doc events. Created via Frappe UI (Setup > Server Script). Require `Script Manager` role.

### Script Types

| Type                 | Use Case                                      |
| -------------------- | --------------------------------------------- |
| **API**              | Create REST endpoint without Python files     |
| **DocType Event**    | Hook into document lifecycle without hooks.py |
| **Scheduler Event**  | Run periodic tasks without hooks.py           |
| **Permission Query** | Dynamic permission conditions                 |

### API Server Script Example

- **Script Type:** API
- **API Method:** `get_open_tasks`
- **Allow Guest:** No

```python
# Script content (in Frappe UI)
tasks = frappe.get_list("Task",
	filters={"status": "Open"},
	fields=["name", "subject", "priority"],
	limit=20,
)
frappe.response["message"] = tasks
```

Callable at: `POST /api/method/get_open_tasks`

### Rate Limiting (API type only)

Server Scripts support built-in rate limiting:

- **Request Limit:** Number of requests allowed (e.g., 5)
- **Time Window:** Period in seconds (e.g., 86400 = 1 day)

---

## Webhooks

Outgoing HTTP requests triggered on document events. Configured via Frappe UI (Setup > Webhook).

### Webhook Properties

| Property            | Description                                                                                                     |
| ------------------- | --------------------------------------------------------------------------------------------------------------- |
| `webhook_doctype`   | DocType that triggers the webhook                                                                               |
| `webhook_docevent`  | Event: `after_insert`, `on_update`, `on_submit`, `on_cancel`, `on_trash`, `on_update_after_submit`, `on_change` |
| `request_url`       | Target URL to POST to                                                                                           |
| `request_method`    | `POST`, `PUT`, `DELETE`                                                                                         |
| `request_structure` | `Form URL-Encoded` or `JSON`                                                                                    |
| `webhook_headers`   | Custom HTTP headers (e.g., Authorization)                                                                       |
| `webhook_data`      | Field-to-key mapping for payload                                                                                |
| `condition`         | Python expression — webhook fires only when true                                                                |
| `is_dynamic_url`    | Use Jinja in the URL (e.g., `https://api.example.com/{{ doc.name }}`)                                           |

### Creating a Webhook Programmatically

```python
frappe.get_doc({
	"doctype": "Webhook",
	"name": "Notify External on Sales Order Submit",
	"webhook_doctype": "Sales Order",
	"webhook_docevent": "on_submit",
	"request_url": "https://api.example.com/orders",
	"request_method": "POST",
	"request_structure": "JSON",
	"condition": "doc.grand_total > 10000",
	"webhook_headers": [
		{"key": "Authorization", "value": "Bearer {{ frappe.get_single('API Settings').api_key }}"},
		{"key": "Content-Type", "value": "application/json"},
	],
	"webhook_data": [
		{"fieldname": "name", "key": "order_id"},
		{"fieldname": "customer", "key": "customer_name"},
		{"fieldname": "grand_total", "key": "total_amount"},
	],
	"enabled": 1,
}).insert(ignore_permissions=True)
```

---

## Lifecycle Hooks

Hooks into request processing, background job execution, and user session events via `hooks.py`.

### Session Hooks

```python
# hooks.py
on_login = "myapp.auth.on_user_login"
on_logout = "myapp.auth.on_user_logout"
on_session_creation = "myapp.auth.on_session_created"
```

```python
# myapp/auth.py

def on_user_login(login_manager):
	"""Called after successful login"""
	frappe.log_error(title="Login", message=f"User {frappe.session.user} logged in")

def on_user_logout():
	"""Called on logout"""
	pass

def on_session_created():
	"""Called when a new session is created"""
	pass
```

### Request Hooks

```python
# hooks.py
before_request = ["myapp.middleware.before_request"]
after_request = ["myapp.middleware.after_request"]
```

```python
# myapp/middleware.py

def before_request():
	"""Called before every HTTP request is processed"""
	# Rate limiting, logging, etc.
	pass

def after_request():
	"""Called after every HTTP request is processed"""
	# Cleanup, metrics, etc.
	pass
```

### Background Job Hooks

```python
# hooks.py
before_job = ["myapp.middleware.before_job"]
after_job = ["myapp.middleware.after_job"]
```

```python
# myapp/middleware.py

def before_job():
	"""Called before a background job starts"""
	pass

def after_job():
	"""Called after a background job completes"""
	pass
```