# Notifications

## Overview

Notifications send email or system alerts when document events occur. They are configured as `Notification` DocType records.

## Notification Types

| Type                    | Description                               |
| ----------------------- | ----------------------------------------- |
| **Email**               | Sends email via configured SMTP           |
| **System Notification** | Shows bell icon notification in Frappe UI |
| **SMS**                 | Sends SMS via configured gateway          |

## Creating a Notification Programmatically

```python
import frappe

def create_notification():
	if frappe.db.exists("Notification", "Task Overdue Alert"):
		return

	frappe.get_doc({
		"doctype": "Notification",
		"name": "Task Overdue Alert",
		"subject": "Task {{ doc.subject }} is overdue",
		"document_type": "Task",
		"event": "Days After",
		"days_in_advance": -1,
		"date_changed": "exp_end_date",
		"channel": "Email",
		"recipients": [
			{
				"receiver_by_document_field": "_assign"
			}
		],
		"condition": "doc.status not in ('Completed', 'Cancelled')",
		"message": """
			<p>Hi,</p>
			<p>Task <b>{{ doc.subject }}</b> was due on {{ frappe.format_date(doc.exp_end_date) }}.</p>
			<p>Please complete it at the earliest.</p>
		""",
		"enabled": 1,
	}).insert(ignore_permissions=True)
```

## Event Types

| Event          | Trigger                                 |
| -------------- | --------------------------------------- |
| `New`          | When document is created                |
| `Save`         | On every save                           |
| `Submit`       | When document is submitted              |
| `Cancel`       | When document is cancelled              |
| `Days After`   | N days after a date field               |
| `Days Before`  | N days before a date field              |
| `Value Change` | When a specific field value changes     |
| `Method`       | Custom method call                      |
| `Custom`       | Triggered via `frappe.sendmail` in code |

## Recipient Options

| Recipient Type    | Field                        | Description                                                |
| ----------------- | ---------------------------- | ---------------------------------------------------------- |
| By document field | `receiver_by_document_field` | User/Email field on the DocType (e.g., `owner`, `_assign`) |
| By role           | `receiver_by_role`           | All users with this role                                   |
| CC                | `cc`                         | Carbon copy email addresses                                |
| Specific email    | `condition` on recipient row | Filter recipients by condition                             |

## Template Variables

Notification `subject` and `message` support Jinja2 with access to:

- `doc` — the document triggering the notification
- `frappe` — the frappe module (for utilities)
- Standard Jinja2 filters and functions