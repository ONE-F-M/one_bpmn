# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Put the jobs that wake parked agent work on a queue of their own.

Frappe derives a scheduled job's queue from its frequency alone, so a Cron job always lands on
``default``. This overrides ``get_queue_name`` for our clock methods only, and claims the
``bpmn_clock`` queue only when the site declares it, so every other job and every undeclared site is unchanged.
"""

from __future__ import annotations

import frappe
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import ScheduledJobType

# The queue these jobs get, when the site provides a worker for it.
CLOCK_QUEUE = "bpmn_clock"

# The scheduled jobs that something is waiting on. Anything whose lateness is
# visible to a person as "why hasn't this happened yet" belongs here; routine
# housekeeping does not.
CLOCK_METHODS = frozenset({
	"processa.a2a.poller.poll_a2a_tasks",
	"processa.processa_engine.timers.process_timer_catch_events",
	"processa.processa_engine.timers.process_timer_start_events",
	"processa.processa_engine.timers.requeue_stranded_ai_steps",
})


class ProcessaScheduledJobType(ScheduledJobType):
	def get_queue_name(self) -> str:
		if self.method in CLOCK_METHODS and clock_queue_is_available():
			return CLOCK_QUEUE
		return super().get_queue_name()


def clock_queue_is_available() -> bool:
	"""Has the site declared the dedicated queue?

	Read from the same place Frappe reads its own queue list, so "declared" means
	exactly what it means to the worker: present in ``workers`` in
	common_site_config. A queue nothing consumes is a black hole, and enqueueing
	into one would turn a delay into a permanent stall.

	Deliberately silent on failure. This runs for every scheduled job on every
	scheduler tick, so logging here would turn one unreachable Redis into
	hundreds of identical error logs - and the answer it falls back to is the
	behaviour the site had anyway. If the reconciler is genuinely not running,
	``reconciler_health`` says so, once, where somebody is looking.
	"""
	try:
		from frappe.utils.background_jobs import get_queues_timeout

		return CLOCK_QUEUE in (get_queues_timeout() or {})
	except Exception:
		return False
