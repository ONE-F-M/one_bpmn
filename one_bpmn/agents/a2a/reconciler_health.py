# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Is the thing that wakes parked agent work actually running? (WI-002055)

``poll_a2a_tasks`` is what notices that a delegated worker has finished, that a
deadline has passed, that a retry is due. When it stops running, none of that is
noticed — and what a person SEES is delegations sitting in Working and deadlines
sailing past. Which is also exactly what a hung agent looks like, and exactly what
a crashed worker looks like.

Three different faults, one symptom, three different fixes. Today you tell them
apart by guessing. This module makes the reconciler's own state a fact you can
read, and names the cause rather than the symptom:

- **the scheduler is switched off for the site** — nothing scheduled runs at all,
  not just this. ``bench migrate`` turns it off at the start and back on at the
  end, so an interrupted or failing migrate leaves the whole site's background
  work stopped. Observed on this bench: every cron job's last execution stamped
  the same second, hours earlier.
- **this job is stopped** — someone ticked it off, and the rest of the site is
  fine.
- **its queue is backed up** — the job is enqueued and waiting behind other work.
  This is the starvation case: on a shared queue, one long job delays every agent
  wake-up behind it.
- **nothing is consuming its queue** — a worker is missing, so the job enqueues
  and waits forever.
- **it is late for none of those reasons** — the job itself is slow or erroring;
  look at its log.

WHY "LATE" IS NOT SIMPLY "last_execution IS OLD"
------------------------------------------------
A minute-by-minute job that last ran 70 seconds ago is not late; one that last ran
70 seconds ago on an hourly schedule is early. The threshold is derived from the
job's own schedule, and set at several times the interval rather than at it —
otherwise every ordinary scheduling jitter reads as an incident and the signal
stops being worth looking at.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

RECONCILER_METHOD = "one_bpmn.tasks.poll_a2a_tasks"

# How many scheduled intervals may pass before lateness is worth reporting.
# Three, because the scheduler enqueues on a tick and a busy queue routinely
# costs a tick or two; a job that has missed three in a row is not jitter.
LATE_AFTER_INTERVALS = 3

# The floor for that threshold. A minute-by-minute job would otherwise be
# "overdue" three minutes after a restart, which is noise.
MINIMUM_LATE_SECONDS = 300


def reconciler_health(method: str = RECONCILER_METHOD) -> dict:
	"""What state the reconciler is in, and — when it is not running — why.

	Never raises. This is read by a screen somebody opens *because* something
	looks wrong; an exception here would replace one confusing answer with
	another.
	"""
	try:
		return _health(method)
	except Exception:
		frappe.log_error(
			title="A2A reconciler health check failed", message=frappe.get_traceback()
		)
		return {
			"ok": None,
			"state": "unknown",
			"summary": _("Could not determine whether the reconciler is running."),
			"method": method,
		}


def _health(method: str) -> dict:
	job = frappe.db.get_value(
		"Scheduled Job Type",
		{"method": method},
		["name", "stopped", "last_execution", "frequency", "cron_format"],
		as_dict=True,
	)
	if not job:
		return _verdict(
			"not_scheduled",
			ok=False,
			summary=_("The reconciler is not scheduled on this site at all."),
			fix=_("Run bench migrate so the scheduled job is created."),
			method=method,
		)

	interval = _interval_seconds(job)
	late_after = max(interval * LATE_AFTER_INTERVALS, MINIMUM_LATE_SECONDS)
	since = (
		(now_datetime() - job.last_execution).total_seconds() if job.last_execution else None
	)
	common = {
		"method": method,
		"job": job.name,
		"queue": _queue_for(job.name),
		"interval_seconds": interval,
		"late_after_seconds": late_after,
		"last_execution": job.last_execution,
		"seconds_since_last_run": int(since) if since is not None else None,
	}

	# The site-wide switch first: when this is off NOTHING scheduled runs, and
	# every other explanation is a distraction.
	if _scheduler_is_off():
		return _verdict(
			"scheduler_disabled",
			ok=False,
			summary=_("The scheduler is switched off for this site, so no scheduled job is running — not just this one."),
			fix=_("Re-enable it (System Settings → Enable Scheduler, or bench --site … enable-scheduler). A migrate that was interrupted or that failed part-way leaves it off."),
			**common,
		)

	if job.stopped:
		return _verdict(
			"job_stopped",
			ok=False,
			summary=_("The reconciler job is stopped. The rest of the site's scheduled work is unaffected."),
			fix=_("Untick Stopped on the Scheduled Job Type record."),
			**common,
		)

	if since is not None and since <= late_after:
		return _verdict(
			"running",
			ok=True,
			summary=_("The reconciler is running on schedule."),
			fix="",
			**common,
		)

	# It is late. Say what is holding it up rather than that it is late.
	backlog, consumers = _queue_state(common["queue"])
	common["queue_depth"] = backlog
	common["queue_consumers"] = consumers

	# Ask the job itself first. Whether it is CURRENTLY waiting in a queue is
	# direct evidence, where queue depth is circumstantial — and the two can
	# disagree: while a queue change is being rolled out, the scheduler process
	# still enqueues to the old queue until it reloads, so the job sits in a
	# backed-up queue while its configured one reads empty. Checked live: this
	# reported "unexplained" while the job was demonstrably queued behind 37
	# others.
	if _is_waiting_in_a_queue(job.name):
		return _verdict(
			"queue_backlog",
			ok=False,
			summary=_("The reconciler is enqueued and has not been picked up — it is waiting behind other work."),
			fix=_("A long job on a shared queue delays every agent wake-up behind it. Give the reconciler a queue of its own, or add workers. If the queue was changed recently, the scheduler keeps using the old one until it is restarted."),
			**common,
		)

	if consumers == 0:
		return _verdict(
			"no_worker",
			ok=False,
			summary=_("Nothing is consuming the '{0}' queue, so the reconciler is enqueued and waiting forever.").format(common["queue"]),
			fix=_("Start a worker for that queue."),
			**common,
		)
	if backlog and backlog > 0:
		return _verdict(
			"queue_backlog",
			ok=False,
			summary=_("The reconciler is waiting behind {0} other job(s) on the '{1}' queue.").format(backlog, common["queue"]),
			fix=_("A long job on a shared queue delays every agent wake-up behind it. Give the reconciler a queue of its own, or add workers."),
			**common,
		)
	return _verdict(
		"late_unexplained",
		ok=False,
		summary=_("The reconciler has not run for {0} minutes, and its queue is neither blocked nor unattended.").format(int((since or 0) / 60)),
		fix=_("Look at the job's Scheduled Job Log — it is most likely erroring or timing out."),
		**common,
	)


def _verdict(state: str, *, ok: bool, summary: str, fix: str, **rest) -> dict:
	return {"state": state, "ok": ok, "summary": summary, "fix": fix, **rest}


def _scheduler_is_off() -> bool:
	"""Both switches, because either one stops everything.

	``disable_scheduler`` in site config is the deployment-level one; the System
	Settings checkbox is what migrate toggles.
	"""
	try:
		from frappe.utils.scheduler import is_scheduler_disabled

		return bool(is_scheduler_disabled())
	except Exception:
		return not bool(frappe.db.get_single_value("System Settings", "enable_scheduler"))


def _is_waiting_in_a_queue(job_name: str) -> bool:
	"""Is this job sitting in SOME queue right now, unpicked-up?

	Frappe keys a scheduled job's RQ id off the job type, so this answers
	"enqueued but not yet run" without needing to know which queue it landed on.
	False on any failure — claiming a job is stuck because Redis hiccuped would
	send somebody to fix the wrong thing.
	"""
	try:
		from frappe.utils.background_jobs import is_job_enqueued

		return bool(is_job_enqueued(frappe.get_doc("Scheduled Job Type", job_name).rq_job_id))
	except Exception:
		return False


def _queue_for(job_name: str) -> str:
	try:
		return frappe.get_doc("Scheduled Job Type", job_name).get_queue_name()
	except Exception:
		return "default"


def _queue_state(queue: str) -> tuple[int | None, int | None]:
	"""(jobs waiting, workers listening) for *queue*, or (None, None) if unknown.

	Unknown rather than zero on failure: reporting "no worker" because Redis was
	briefly unreachable would send somebody to fix the wrong thing.
	"""
	try:
		from rq import Worker

		from frappe.utils.background_jobs import get_queue, get_redis_conn

		q = get_queue(queue)
		conn = get_redis_conn()
		listening = sum(1 for w in Worker.all(connection=conn) if q.name in [x.name for x in w.queues])
		return q.count, listening
	except Exception:
		return None, None


def _interval_seconds(job) -> int:
	"""How often the job is meant to run, from its own schedule."""
	if (job.frequency or "") == "Cron" and job.cron_format:
		try:
			from croniter import croniter

			base = now_datetime()
			it = croniter(job.cron_format, base)
			first = it.get_next(type(base))
			second = it.get_next(type(base))
			return max(int((second - first).total_seconds()), 1)
		except Exception:
			pass
	return {
		"All": 240,
		"Hourly": 3600, "Hourly Long": 3600, "Hourly Maintenance": 3600,
		"Daily": 86400, "Daily Long": 86400, "Daily Maintenance": 86400,
		"Weekly": 604800, "Weekly Long": 604800,
		"Monthly": 2592000, "Monthly Long": 2592000,
		"Yearly": 31536000, "Annual": 31536000,
	}.get(job.frequency or "", 3600)


def _(text: str) -> str:
	"""frappe._ without importing it at module scope, so this module stays
	importable from a plain script."""
	try:
		return frappe._(text)
	except Exception:
		return text
