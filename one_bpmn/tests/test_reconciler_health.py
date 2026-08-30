# Copyright (c) 2026, one-fm and contributors
# WI-002055: the jobs that wake parked agent work must run on time, and when they
# do not, that must be visible as its own fact.
#
# The point of these tests is the DISTINCTION. A starved reconciler, a stopped
# job, a disabled scheduler and a hung agent all present the same way — things
# sitting in Working — and each needs a different fix. A health check that only
# said "late" would be no better than the guessing it replaces, so what is pinned
# here is that each cause reports itself, and in the right order of precedence.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.a2a import reconciler_health as H
from one_bpmn.overrides.scheduled_job_type import (
	CLOCK_METHODS,
	CLOCK_QUEUE,
	ProcessaScheduledJobType,
)

METHOD = H.RECONCILER_METHOD


def _job():
	return frappe.db.get_value("Scheduled Job Type", {"method": METHOD}, "name")


class TestTheReconcilerReportsItsOwnState(FrappeTestCase):
	"""Each cause names itself rather than being inferred from stuck delegations."""

	def setUp(self):
		super().setUp()
		self.job = _job()
		if not self.job:
			self.skipTest("the reconciler is not scheduled on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _healthy_now(self):
		"""Make the job look freshly run, so a test can isolate one cause."""
		frappe.db.set_value(
			"Scheduled Job Type", self.job, "last_execution", now_datetime(),
			update_modified=False,
		)

	def test_a_job_that_just_ran_is_reported_as_running(self):
		self._healthy_now()
		with patch.object(H, "_scheduler_is_off", return_value=False):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "running")
		self.assertTrue(out["ok"])

	def test_a_disabled_scheduler_says_so_and_says_it_is_site_wide(self):
		"""The most misleading failure: nothing scheduled runs at all, and every
		other explanation is a distraction. bench migrate turns the scheduler off
		at the start and on at the end, so an interrupted migrate leaves it off —
		which is the state this bench was found in."""
		with patch.object(H, "_scheduler_is_off", return_value=True):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "scheduler_disabled")
		self.assertFalse(out["ok"])
		self.assertIn("not just this one", out["summary"])

	def test_the_site_switch_outranks_everything_else(self):
		"""Even a stopped job and an empty queue must not be reported while the
		scheduler is off — they are true, and they are not the reason."""
		frappe.db.set_value("Scheduled Job Type", self.job, "stopped", 1, update_modified=False)
		with patch.object(H, "_scheduler_is_off", return_value=True):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "scheduler_disabled")

	def test_a_stopped_job_is_distinguished_from_a_stopped_site(self):
		frappe.db.set_value("Scheduled Job Type", self.job, "stopped", 1, update_modified=False)
		with patch.object(H, "_scheduler_is_off", return_value=False):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "job_stopped")
		self.assertIn("rest of the site", out["summary"])

	def test_being_enqueued_outranks_an_empty_queue_reading(self):
		"""Direct evidence beats circumstantial. While a queue change is rolling
		out, the scheduler still enqueues to the old queue until it restarts, so
		the job waits in a backed-up queue while its CONFIGURED queue reads empty.
		Observed live: this reported 'unexplained' while the job was demonstrably
		queued behind 37 others."""
		frappe.db.set_value(
			"Scheduled Job Type", self.job, "last_execution",
			add_to_date(now_datetime(), hours=-3), update_modified=False,
		)
		with patch.object(H, "_scheduler_is_off", return_value=False), \
			patch.object(H, "_is_waiting_in_a_queue", return_value=True), \
			patch.object(H, "_queue_state", return_value=(0, 1)):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "queue_backlog")

	def test_a_queue_nobody_consumes_is_named_as_such(self):
		"""Worse than slow: the job enqueues and waits forever. Declaring a queue
		without starting its worker does this, which is why the routing only
		claims the queue once the site declares it."""
		frappe.db.set_value(
			"Scheduled Job Type", self.job, "last_execution",
			add_to_date(now_datetime(), hours=-3), update_modified=False,
		)
		with patch.object(H, "_scheduler_is_off", return_value=False), \
			patch.object(H, "_is_waiting_in_a_queue", return_value=False), \
			patch.object(H, "_queue_state", return_value=(0, 0)):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "no_worker")

	def test_late_for_no_visible_reason_points_at_the_job_itself(self):
		frappe.db.set_value(
			"Scheduled Job Type", self.job, "last_execution",
			add_to_date(now_datetime(), hours=-3), update_modified=False,
		)
		with patch.object(H, "_scheduler_is_off", return_value=False), \
			patch.object(H, "_is_waiting_in_a_queue", return_value=False), \
			patch.object(H, "_queue_state", return_value=(0, 1)):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "late_unexplained")
		self.assertIn("Scheduled Job Log", out["fix"])

	def test_it_never_raises(self):
		"""It is read by a screen somebody opens BECAUSE something looks wrong.
		Throwing there replaces one confusing answer with another."""
		with patch.object(H, "_health", side_effect=RuntimeError("redis is gone")):
			out = H.reconciler_health()
		self.assertEqual(out["state"], "unknown")
		self.assertIsNone(out["ok"])


class TestLatenessIsJudgedAgainstTheJobsOwnSchedule(FrappeTestCase):
	def test_a_minute_job_is_not_late_after_seventy_seconds(self):
		"""Jitter is not an incident. A threshold set at the interval would cry
		wolf on every busy minute and stop being worth reading."""
		job = frappe._dict(frequency="Cron", cron_format="* * * * *")
		self.assertEqual(H._interval_seconds(job), 60)
		self.assertGreaterEqual(H.MINIMUM_LATE_SECONDS, 70)

	def test_an_hourly_job_is_allowed_hours(self):
		job = frappe._dict(frequency="Hourly", cron_format=None)
		interval = H._interval_seconds(job)
		self.assertEqual(interval, 3600)
		self.assertEqual(
			max(interval * H.LATE_AFTER_INTERVALS, H.MINIMUM_LATE_SECONDS), 10800
		)

	def test_an_unparseable_cron_does_not_explode(self):
		job = frappe._dict(frequency="Cron", cron_format="not a cron")
		self.assertGreater(H._interval_seconds(job), 0)


class TestTheClockJobsGetTheirOwnQueue(FrappeTestCase):
	"""Frappe derives a queue from FREQUENCY alone, so a Cron job is always on
	'default' — here shared with 172 other enabled jobs. Agent turns already have
	their own worker for this reason; these are the jobs that wake them."""

	def _doc(self, method):
		name = frappe.db.get_value("Scheduled Job Type", {"method": method}, "name")
		if not name:
			self.skipTest(f"{method} is not scheduled on this site")
		return frappe.get_doc("Scheduled Job Type", name)

	def test_the_clock_jobs_route_to_the_dedicated_queue(self):
		with patch(
			"one_bpmn.overrides.scheduled_job_type.clock_queue_is_available",
			return_value=True,
		):
			for method in CLOCK_METHODS:
				with self.subTest(method=method):
					doc = self._doc(method)
					self.assertEqual(ProcessaScheduledJobType.get_queue_name(doc), CLOCK_QUEUE)

	def test_every_other_job_is_left_exactly_as_frappe_had_it(self):
		"""The override is for our three methods. Frappe's, ERPNext's and
		one_fm's scheduled jobs must be untouched."""
		others = frappe.get_all(
			"Scheduled Job Type",
			filters={"method": ["not in", list(CLOCK_METHODS)]},
			fields=["name", "method", "frequency"],
			limit=25,
		)
		with patch(
			"one_bpmn.overrides.scheduled_job_type.clock_queue_is_available",
			return_value=True,
		):
			for row in others:
				doc = frappe.get_doc("Scheduled Job Type", row.name)
				expected = "long" if ("Long" in (doc.frequency or "") or "Maintenance" in (doc.frequency or "")) else "default"
				self.assertEqual(ProcessaScheduledJobType.get_queue_name(doc), expected, row.method)

	def test_without_the_queue_declared_nothing_changes(self):
		"""A queue nothing consumes is a black hole, and enqueueing into one turns
		a delay into a permanent stall. So the code is safe to deploy on its own,
		before or without the worker configuration."""
		with patch(
			"one_bpmn.overrides.scheduled_job_type.clock_queue_is_available",
			return_value=False,
		):
			doc = self._doc(H.RECONCILER_METHOD)
			self.assertEqual(ProcessaScheduledJobType.get_queue_name(doc), "default")

	def test_an_unreadable_queue_list_falls_back_rather_than_stalling(self):
		from one_bpmn.overrides import scheduled_job_type as S

		with patch(
			"frappe.utils.background_jobs.get_queues_timeout",
			side_effect=RuntimeError("redis is gone"),
		):
			self.assertFalse(S.clock_queue_is_available())
