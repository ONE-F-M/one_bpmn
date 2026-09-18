# Scheduler Events & Background Jobs

## Scheduler Events

Run background tasks on a schedule via `hooks.py`. Use for periodic data processing, cleanup, notifications, and integrations.

### hooks.py

```python
scheduler_events = {
	# Runs every minute
	"all": [
		"myapp.tasks.process_queue",
	],

	# Standard intervals
	"hourly": [
		"myapp.tasks.sync_external_data",
	],
	"daily": [
		"myapp.tasks.send_daily_digest",
	],
	"weekly": [
		"myapp.tasks.generate_weekly_report",
	],
	"monthly": [
		"myapp.tasks.archive_old_records",
	],

	# Maintenance queues (don't align with wall-clock time)
	# Use when you don't care about exact timing
	"hourly_maintenance": [
		"myapp.tasks.cleanup_temp_files",
	],
	"daily_maintenance": [
		"myapp.tasks.run_data_integrity_checks",
	],

	# Long-running variants (run in long queue, 30min timeout)
	"daily_long": [
		"myapp.tasks.heavy_data_migration",
	],
	"weekly_long": [
		"myapp.tasks.take_backup",
	],
	"monthly_long": [
		"myapp.tasks.full_reindex",
	],

	# Cron expressions (most flexible)
	"cron": {
		"0/15 * * * *": [  # Every 15 minutes
			"myapp.tasks.check_external_status",
		],
		"30 6 * * *": [  # Daily at 6:30 AM
			"myapp.tasks.morning_sync",
		],
		"0 0 1 * *": [  # First of every month at midnight
			"myapp.tasks.monthly_rollover",
		],
	},
}
```

### Scheduler Event Types

| Type                 | Frequency              | Queue | Timeout |
| -------------------- | ---------------------- | ----- | ------- |
| `all`                | Every minute           | short | 2 min   |
| `hourly`             | Every hour at :00      | short | 2 min   |
| `hourly_maintenance` | ~hourly, no fixed time | short | 2 min   |
| `daily`              | Daily at midnight      | short | 2 min   |
| `daily_long`         | Daily                  | long  | 30 min  |
| `daily_maintenance`  | ~daily, no fixed time  | short | 2 min   |
| `weekly`             | Weekly                 | short | 2 min   |
| `weekly_long`        | Weekly                 | long  | 30 min  |
| `monthly`            | Monthly                | short | 2 min   |
| `monthly_long`       | Monthly                | long  | 30 min  |
| `cron`               | Custom cron expression | short | 2 min   |

### Cron Expression Format

```
*  *  *  *  *
┬  ┬  ┬  ┬  ┬
│  │  │  │  └─ day of week (0-6, 0=Sunday)
│  │  │  └──── month (1-12)
│  │  └─────── day of month (1-31)
│  └────────── hour (0-23)
└───────────── minute (0-59)
```

### Task Function Pattern

```python
# {app_name}/{app_name}/tasks.py
import frappe
from frappe import _


def send_daily_digest():
	"""Scheduled task: Send daily digest emails.

	No arguments. Must handle its own setup/teardown.
	Runs as Administrator by default.
	"""
	users = frappe.get_all("User",
		filters={"enabled": 1, "user_type": "System User"},
		pluck="name",
	)

	for user in users:
		try:
			send_digest_for_user(user)
		except Exception:
			frappe.log_error(
				title=_("Daily Digest Error for {0}").format(user),
			)


def heavy_data_migration():
	"""Long-running task — use daily_long queue.

	For large operations, commit periodically to avoid
	long-running transactions.
	"""
	records = frappe.get_all("Old Record", filters={"migrated": 0}, limit=1000)

	for i, record in enumerate(records):
		migrate_record(record.name)

		# Commit every 100 records to avoid long transactions
		if i % 100 == 0:
			frappe.db.commit()
```

---

## Enqueuing Background Jobs (Ad-hoc)

For one-off long-running operations from controller code or API handlers, use `frappe.enqueue`:

```python
# Enqueue a background job
frappe.enqueue(
	method="myapp.tasks.process_large_file",
	queue="long",          # short (2m), default (5m), long (30m)
	timeout=1500,
	file_path=file_path,
	user=frappe.session.user,
	now=False,             # True = run synchronously in same request
)

# Prevent duplicate jobs
from frappe.utils.background_jobs import is_job_enqueued

job_id = f"import::{record_name}"
if not is_job_enqueued(job_id):
	frappe.enqueue(
		method="myapp.tasks.import_data",
		job_id=job_id,
		queue="long",
		timeout=3000,
		record_name=record_name,
	)

# Notify user when done (via Realtime)
def process_in_background(doc_name):
	try:
		# ... processing ...
		frappe.publish_realtime(
			event="task_complete",
			message={"doc_name": doc_name, "status": "success"},
			user=frappe.session.user,
		)
	except Exception:
		frappe.log_error(title=f"Background task failed: {doc_name}")
		frappe.publish_realtime(
			event="task_complete",
			message={"doc_name": doc_name, "status": "failed"},
			user=frappe.session.user,
		)
```

### Queue Types

| Queue     | Default Timeout | Use Case                                           |
| --------- | --------------- | -------------------------------------------------- |
| `short`   | 2 minutes       | Quick operations, notifications                    |
| `default` | 5 minutes       | Standard processing                                |
| `long`    | 30 minutes      | Data imports, report generation, heavy computation |