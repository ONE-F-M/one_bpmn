# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Put the jobs that wake parked agent work on a queue of their own (WI-002055).

Frappe decides a scheduled job's queue from its FREQUENCY alone: "long" for a
Long or Maintenance frequency, "default" for everything else. A Cron job is
therefore always on ``default`` — which on this site is shared with 172 other
enabled jobs, plus every enqueue the rest of the application makes.

That is fine for work nobody is waiting on. It is not fine for these three,
because they are what NOTICES things:

- ``poll_a2a_tasks`` — a delegated worker finished, a deadline passed, a retry
  is due
- ``process_timer_catch_events`` — a waiting instance's timer elapsed
- ``process_timer_start_events`` — a timed process should start now

When they sit behind a long job, a delegation that finished five minutes ago is
still shown as running, and a deadline that passed is not noticed until whatever
is ahead of them completes. Measured on this bench: a median gap of 76 seconds
against a 60-second schedule, but a worst gap of 4,058 — a delegation could go
sixty-eight minutes without anyone noticing it had finished.

The precedent is already here. Agent TURNS were given their own worker
(``bpmn_ai_agent``) for exactly this reason: a long LLM call must not queue behind
somebody's bulk import. This does the same for the jobs that wake those turns up
— the parts of the system with a clock attached.

WHY OVERRIDE THE DOCTYPE RATHER THAN CHANGE THE SCHEDULE
--------------------------------------------------------
The queue is not configurable per job: ``get_queue_name`` derives it from the
frequency and nothing else. Declaring the jobs as "Hourly Long" to reach the
``long`` queue would move them onto a queue meant for slow work AND change how
often they run, which is the opposite of what is wanted.

So the method is overridden, for our methods only. Every other scheduled job on
the site — Frappe's, ERPNext's, one_fm's — falls through to the original
behaviour untouched.

DEGRADES TO TODAY'S BEHAVIOUR
-----------------------------
If no worker is listening on the dedicated queue, the jobs would enqueue and wait
forever, which is worse than being slow. So the queue is only claimed when the
site actually declares it; otherwise these jobs stay on ``default`` exactly as
they are now. That makes deploying the code safe on its own, in any order with
the worker configuration.
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
	"one_bpmn.tasks.poll_a2a_tasks",
	"one_bpmn.tasks.process_timer_catch_events",
	"one_bpmn.tasks.process_timer_start_events",
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
	hundreds of identical error logs — and the answer it falls back to is the
	behaviour the site had anyway. If the reconciler is genuinely not running,
	``reconciler_health`` says so, once, where somebody is looking.
	"""
	try:
		from frappe.utils.background_jobs import get_queues_timeout

		return CLOCK_QUEUE in (get_queues_timeout() or {})
	except Exception:
		return False
