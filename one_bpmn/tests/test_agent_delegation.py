# Copyright (c) 2026, one-fm and contributors
"""Agent Delegation: tracking a hand-over, and escalating one that stops.

WI-002053. Three things are pinned here.

**The record.** A delegation used to exist only as an A2A Task, which knows who
was asked and not what the work was about. The Agent Delegation row ties the
delegating instance, the task, the worker's instance and the referenced document
together, and its reference is generic on purpose: a Work Item on the Software
Development path, an A2A Task in the test harness.

**The escalation.** Depth and hand-off limits were already notified at the door
(WI-002008). A limit reached while the worker was RUNNING was silent — the
deadline set state="timed-out" and woke the caller, and a worker ending at its
turn cap returned partial text that looked like an answer. Both now land on
Needs Review and tell a person once.

**Identity.** None of the above means anything if the orchestrator is not
identified, and on the Call Activity path it was not: the delegating agent
resolved to None, so guardrails_for() returned DEFAULTS instead of the agent's
configured limits and may_delegate_to() skipped restrict_delegates entirely.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.a2a import delegation, guardrails


def _any_agent() -> str:
	"""A real AI Agent Configuration name — worker_agent is a Link field."""
	return frappe.db.get_value("AI Agent Configuration", {}, "name")


def _task(**kw):
	"""A real A2A Task row.

	Both worker_agent and a2a_task on Agent Delegation are Link fields, so a
	stub object with invented names fails validation and record() — correctly —
	declines to write anything. In production the task is inserted immediately
	before record() is called, so it always exists; the test has to do the same
	rather than pretend.
	"""
	doc = frappe.get_doc({
		"doctype": "A2A Task",
		"direction": "Internal",
		"state": kw.get("state", "submitted"),
		"agent_configuration": kw.get("agent_configuration") or _any_agent(),
		"caller_instance": kw.get("caller_instance"),
		"delegation_depth": kw.get("delegation_depth", 1),
		"handoff_count": kw.get("handoff_count", 1),
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc


class TestLimitReasonSets(FrappeTestCase):
	def test_door_and_in_flight_reasons_stay_separate(self):
		"""A limit reached in flight already HAS a task row, so putting it
		through record_limit_breach() would mint a duplicate."""
		self.assertEqual(
			guardrails.LIMIT_REASONS, ("max_recursion_depth", "max_task_handoffs")
		)
		self.assertEqual(
			guardrails.IN_FLIGHT_LIMIT_REASONS,
			("delegation_deadline_minutes", "turn_cap"),
		)
		for reason in guardrails.IN_FLIGHT_LIMIT_REASONS:
			self.assertNotIn(reason, guardrails.LIMIT_REASONS)

	def test_retries_are_not_a_limit_reason_anywhere(self):
		"""max_delegation_retries is a configured field that nothing reads —
		nothing retries a delegation. A branch for it would be unreachable code
		pretending to be a control."""
		everything = guardrails.LIMIT_REASONS + guardrails.IN_FLIGHT_LIMIT_REASONS
		self.assertNotIn("max_delegation_retries", everything)

	def test_every_reason_has_words_a_person_can_read(self):
		for reason in guardrails.LIMIT_REASONS + guardrails.IN_FLIGHT_LIMIT_REASONS:
			self.assertIn(reason, delegation.LIMIT_LABELS)


class TestDelegationRecord(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _instance(self, context_doctype=None, context_docname=None):
		doc = frappe.new_doc("BPMN Process Instance")
		doc.process_model = None
		doc.status = "Active"
		doc.context_doctype = context_doctype
		doc.context_docname = context_docname
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
		return doc.name

	def test_reference_is_taken_from_the_delegating_instance(self):
		"""The caller does not reliably know what the work is about, but its
		instance does. On the Software Development path the delegating instance
		is the CALLER's — a Call Activity has none of its own — and its context
		is the Work Item."""
		caller_task = _task()
		inst = self._instance("A2A Task", caller_task.name)
		doctype, name = delegation._reference_for(inst)
		self.assertEqual(doctype, "A2A Task")
		self.assertEqual(name, caller_task.name)

	def test_reference_is_empty_when_there_is_no_instance(self):
		self.assertEqual(delegation._reference_for(None), (None, None))

	def test_a_stale_reference_does_not_cost_us_the_record(self):
		"""reference_name is a Dynamic Link, so it is link-validated on insert.
		An instance whose context document has been deleted would otherwise take
		the whole tracking row down with it — losing the record of a delegation
		that really happened. Dropping the reference is the lesser failure."""
		inst = self._instance("A2A Task", "A2A-DELETED-LONG-AGO")
		self.assertEqual(delegation._reference_for(inst), (None, None))

		task = _task(caller_instance=inst)
		name = delegation.record(task, delegating_agent=None)
		self.assertIsNotNone(name, "the delegation record was lost with the reference")
		self.assertIsNone(frappe.db.get_value("Agent Delegation", name, "reference_name"))

	def test_record_ties_the_pieces_together(self):
		caller_task = _task()          # a real document for the context to point at
		inst = self._instance("A2A Task", caller_task.name)
		task = _task(caller_instance=inst, state="submitted")
		name = delegation.record(task, delegating_agent=None, instruction="do the thing")
		self.assertIsNotNone(name)

		row = frappe.db.get_value(
			"Agent Delegation",
			name,
			["status", "a2a_task", "reference_doctype", "reference_name", "instruction"],
			as_dict=True,
		)
		self.assertEqual(row.status, "Delegated")
		self.assertEqual(row.a2a_task, task.name)
		self.assertEqual(row.reference_doctype, "A2A Task")
		self.assertEqual(row.reference_name, caller_task.name)
		self.assertEqual(row.instruction, "do the thing")

	def test_record_is_idempotent_per_task(self):
		task = _task()
		first = delegation.record(task, delegating_agent=None)
		second = delegation.record(task, delegating_agent=None)
		self.assertEqual(first, second)

	def test_sync_follows_the_task_state(self):
		task = _task()
		name = delegation.record(task, delegating_agent=None)
		for state, expected in (
			("working", "In Progress"),
			("completed", "Completed"),
		):
			task.state = state
			delegation.sync_from_task(task)
			self.assertEqual(frappe.db.get_value("Agent Delegation", name, "status"), expected)

	def test_needs_review_is_sticky(self):
		"""A worker whose deadline expired can still drive its task to
		completed a moment later. Letting that overwrite Needs Review would
		erase the very thing a person was asked to look at."""
		task = _task()
		name = delegation.record(task, delegating_agent=None)
		frappe.db.set_value("Agent Delegation", name, "status", "Needs Review")

		task.state = "completed"
		delegation.sync_from_task(task)
		self.assertEqual(frappe.db.get_value("Agent Delegation", name, "status"), "Needs Review")

	def test_sync_on_an_unrecorded_task_is_a_no_op(self):
		delegation.sync_from_task(_task())  # unrecorded: must not raise


class TestStoppedAtLimit(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _recorded(self, delegating_agent=None):
		task = _task()
		return task.name, delegation.record(task, delegating_agent=delegating_agent)

	@staticmethod
	def _agent_with_an_owner() -> str | None:
		"""An agent whose configuration names a process owner, so
		refusal_recipient() has someone to land the alert on."""
		return frappe.db.get_value(
			"AI Agent Configuration", {"process_owner": ["is", "set"]}, "name"
		)

	def test_marks_needs_review_with_the_limit_and_the_number(self):
		"""'A limit was hit' is not actionable. Which limit, and what it
		reached, is."""
		task_name, ad = self._recorded()
		delegation.stopped_at_limit(
			a2a_task=task_name,
			reason="delegation_deadline_minutes",
			limit_value=30,
			reached_value=35,
			detail="ran long",
		)
		row = frappe.db.get_value(
			"Agent Delegation",
			ad,
			["status", "stopped_reason", "limit_value", "reached_value", "ended_at"],
			as_dict=True,
		)
		self.assertEqual(row.status, "Needs Review")
		self.assertEqual(row.stopped_reason, "delegation_deadline_minutes")
		self.assertEqual(row.limit_value, 30)
		self.assertEqual(row.reached_value, 35)
		self.assertIsNotNone(row.ended_at)

	def test_notifies_once_per_breach(self):
		"""The reconciler runs on a schedule and sees the same stopped
		delegation on every tick. A person needs telling once."""
		agent = self._agent_with_an_owner()
		if not agent:
			self.skipTest("no agent configuration names a process owner on this site")
		task_name, ad = self._recorded(delegating_agent=agent)
		before = frappe.db.count("Notification Log")
		delegation.stopped_at_limit(a2a_task=task_name, reason="turn_cap", limit_value=8)
		after_first = frappe.db.count("Notification Log")

		delegation.stopped_at_limit(a2a_task=task_name, reason="turn_cap", limit_value=8)
		after_second = frappe.db.count("Notification Log")

		self.assertGreater(after_first, before, "nobody was told the first time")
		self.assertEqual(after_second, after_first, "the same breach was reported twice")
		self.assertIsNotNone(frappe.db.get_value("Agent Delegation", ad, "notified_at"))

	def test_the_message_names_the_agent_and_the_limit(self):
		message = delegation._limit_message(
			worker="Connector Agent",
			reason="delegation_deadline_minutes",
			limit_value=30,
			reached_value=35,
			detail="",
			ref_doctype="Work Item",
			ref_name="WI-9",
		)
		self.assertIn("Connector Agent", message)
		self.assertIn("Work Item WI-9", message)
		self.assertIn("time allowed", message)   # plain words, not the field name
		self.assertIn("35", message)
		self.assertIn("30", message)
		self.assertIn("not", message)            # says the work is unfinished

	def test_it_never_raises_on_an_unknown_task(self):
		"""An escalation that fails must not also break the reconciler that
		noticed the breach."""
		self.assertFalse(delegation.stopped_at_limit(a2a_task="A2A-NOPE", reason="turn_cap"))
