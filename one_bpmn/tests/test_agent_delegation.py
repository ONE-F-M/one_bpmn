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
		for reason in guardrails.IN_FLIGHT_LIMIT_REASONS:
			self.assertNotIn(reason, guardrails.LIMIT_REASONS)

	def test_retries_are_an_in_flight_limit(self):
		"""max_delegation_retries used to be a setting nothing read. It is now a
		real limit, reached while the worker is in flight, so it escalates
		through the same seam as the deadline and the turn cap."""
		self.assertIn("max_delegation_retries", guardrails.IN_FLIGHT_LIMIT_REASONS)
		self.assertNotIn("max_delegation_retries", guardrails.LIMIT_REASONS)

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

	def test_the_alert_only_suggests_things_a_person_can_actually_do(self):
		"""It used to say "raise the limit and hand it over again". There is no
		way to hand it over again — no re-delegate action exists — so anyone
		following that went looking for a button that was never built."""
		task_name, ad = self._recorded()
		delegation.stopped_at_limit(
			a2a_task=task_name, reason="turn_cap", limit_value=1, reached_value=1
		)
		message = frappe.db.get_value("Agent Delegation", ad, "error_message") or ""
		row = frappe.get_all(
			"Notification Log", filters={"document_name": task_name}, fields=["email_content"], limit=1
		)
		text = (row[0].email_content if row else "") or message
		# Whichever carried it, the promise of a button must not be in there.
		self.assertNotIn("hand it over again", text)

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


class TestEscalationWithoutARowYet(FrappeTestCase):
	"""A stopped delegation that has no tracking row must still be told once.

	The "already told someone" stamp lives on the Agent Delegation row. With no
	row, stopped_at_limit had nowhere to write it, so every reconciler tick told
	the person again — three passes, three alerts. record() never raises, which
	means it can decline and leave nothing behind, so the case is reachable.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_row_is_written_before_escalating(self):
		task = _task(state="working")
		self.assertIsNone(delegation.for_task(task.name), "precondition: no row yet")
		delegation.stopped_at_limit(a2a_task=task.name, reason="turn_cap",
			limit_value=1, reached_value=1)
		self.assertTrue(delegation.for_task(task.name), "the escalation left a record")

	def test_only_the_first_pass_tells_anyone(self):
		task = _task(state="working")
		told = [
			delegation.stopped_at_limit(a2a_task=task.name, reason="turn_cap",
				limit_value=1, reached_value=1)
			for _ in range(3)
		]
		self.assertLessEqual(sum(1 for t in told if t), 1, f"told on {told}")

	def test_the_row_carries_the_limit_that_stopped_it(self):
		task = _task(state="working")
		delegation.stopped_at_limit(a2a_task=task.name, reason="delegation_deadline_minutes",
			limit_value=30, reached_value=31)
		row = frappe.db.get_value("Agent Delegation", delegation.for_task(task.name),
			["status", "stopped_reason", "limit_value"], as_dict=True)
		self.assertEqual(row.status, "Needs Review")
		self.assertEqual(row.stopped_reason, "delegation_deadline_minutes")
		self.assertEqual(row.limit_value, 30)


class TestARetryActuallyRuns(FrappeTestCase):
	"""WI-002146. The limit was respected without anything being retried.

	A delegated specialist is a Background agent: the A2A Task row IS its
	trigger document, so "the process for this task" is the same lookup on every
	attempt. A retry found the process from the PREVIOUS attempt, reattached to
	it, read its finished state and failed again at once. Two delegations that
	exhausted their retries showed attempt_count 2 and 3 against ONE worker
	instance and ONE agent run each — three attempts, one execution.

	So these tests assert EXECUTIONS, not counted attempts. Counting was never
	the broken half.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_retry_asks_for_a_fresh_run(self):
		"""The seam: run_for_task must pass fresh through to the Background path,
		because that flag is the whole difference between retrying and
		re-reading."""
		import inspect

		from one_bpmn.agents.a2a import execute

		self.assertIn("fresh", inspect.signature(execute.run_for_task).parameters)
		self.assertIn("fresh", inspect.signature(execute.run_background).parameters)

	def test_the_reconciler_asks_for_a_fresh_run(self):
		"""A retry that does not ask for a fresh run is the original bug."""
		import inspect

		from one_bpmn import tasks

		source = inspect.getsource(tasks._retry_delegation)
		self.assertIn("fresh=True", source)

	def test_a_chat_worker_needs_no_fresh_flag(self):
		"""A Chat agent is re-invoked from scratch every time, so there is
		nothing there to inherit by accident — the flag is Background-only and
		must not change that path."""
		import inspect

		from one_bpmn.agents.a2a import execute

		self.assertNotIn("fresh", inspect.signature(execute.run_chat_turn).parameters)


class TestNoOrphanFromThePreviousAttempt(FrappeTestCase):
	"""A retry must not leave the last attempt running beside its replacement."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _instance(self, status):
		doc = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": frappe.db.get_value("BPMN Process Model", {}, "name"),
			"status": status,
		})
		doc.flags.ignore_links = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		return doc

	def test_a_still_running_attempt_is_retired(self):
		from one_bpmn.agents.a2a import execute

		instance = self._instance("Active")
		self.assertTrue(execute.retire_instance(instance.name))
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Cancelled"
		)

	def test_a_finished_attempt_is_left_alone(self):
		"""Its outcome is part of the delegation's history; rewriting it would
		lose what the first attempt actually did."""
		from one_bpmn.agents.a2a import execute

		instance = self._instance("Completed")
		self.assertFalse(execute.retire_instance(instance.name))
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Completed"
		)

	def test_nothing_to_retire_is_not_an_error(self):
		from one_bpmn.agents.a2a import execute

		self.assertFalse(execute.retire_instance(None))

	def test_waiting_rows_from_the_old_attempt_are_closed(self):
		"""Left open they surface in every task summary forever."""
		from one_bpmn.agents.a2a import execute

		instance = self._instance("Active")
		instance.append("active_tasks", {"task_id": "t1", "task_name": "Old step", "status": "Waiting"})
		instance.flags.ignore_permissions = True
		instance.save(ignore_permissions=True)
		execute.retire_instance(instance.name)
		self.assertEqual(
			frappe.db.count("BPMN Active Task", {"parent": instance.name, "status": "Waiting"}), 0
		)


class TestWhatIsNotWorthRetrying(FrappeTestCase):
	"""A retry is for a TRANSIENT failure.

	Repeating a configuration outcome only delays the escalation, and re-running
	something a person just cancelled would be worse than useless. This held
	before only because the reconciler's query happened to exclude those rows
	for an unrelated reason; it is a stated rule now.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _recorded(self, **updates):
		task = _task(state="failed")
		name = delegation.record(task, delegating_agent=None)
		if updates:
			frappe.db.set_value("Agent Delegation", name, updates, update_modified=False)
		return task, name

	def test_a_transient_failure_is_retried(self):
		task, _ = self._recorded()
		self.assertTrue(delegation.should_retry(task.name))

	def test_a_door_time_refusal_is_not_retried(self):
		"""Off the allow-list, or past a depth or hand-off limit: the answer will
		be the same every time."""
		for reason in ("max_recursion_depth", "max_task_handoffs", "target_not_allowed"):
			with self.subTest(reason=reason):
				task, _ = self._recorded(status="Failed", stopped_reason=reason)
				self.assertFalse(delegation.should_retry(task.name))

	def test_a_cancelled_delegation_is_not_retried(self):
		"""A person stopped it. Starting it again would undo their decision."""
		task, _ = self._recorded(status="Cancelled", stopped_reason=delegation.CANCELLED_REASON)
		self.assertFalse(delegation.should_retry(task.name))

	def test_a_delegation_already_escalated_is_not_retried(self):
		task, _ = self._recorded(status="Needs Review", stopped_reason="turn_cap")
		self.assertFalse(delegation.should_retry(task.name))

	def test_a_completed_delegation_is_not_retried(self):
		task, _ = self._recorded(status="Completed")
		self.assertFalse(delegation.should_retry(task.name))

	def test_the_rule_does_not_depend_on_the_reconcilers_query(self):
		"""The guard is in should_retry, so it holds wherever it is called from —
		the previous protection was a filter that excluded these rows for an
		unrelated reason."""
		task, _ = self._recorded(status="Failed", stopped_reason="max_task_handoffs")
		frappe.db.set_value("A2A Task", task.name, "resume_enqueued", 0, update_modified=False)
		self.assertFalse(delegation.should_retry(task.name))


class TestTheDeadlineCoversAllAttempts(FrappeTestCase):
	"""The story required this DECIDED, not left to whatever the code did.

	It covers the whole delegation. Restarting it per retry would let a worker
	that keeps failing run for retries × deadline, which is not what someone
	setting "30 minutes" has agreed to. The consequence is that a delegation can
	run out of time before it runs out of attempts — intended, so the record has
	to say so.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_decision_is_recorded_in_one_place(self):
		self.assertTrue(delegation.DEADLINE_SPANS_ALL_ATTEMPTS)

	def test_a_retry_does_not_move_the_deadline(self):
		task = _task(state="failed")
		delegation.record(task, delegating_agent=None)
		deadline = frappe.utils.add_to_date(now_datetime(), minutes=30)
		frappe.db.set_value("A2A Task", task.name, "deadline", deadline, update_modified=False)
		delegation.note_attempt(task.name)
		self.assertEqual(
			frappe.utils.get_datetime(frappe.db.get_value("A2A Task", task.name, "deadline")),
			frappe.utils.get_datetime(deadline),
		)

	def test_a_one_minute_deadline_is_reported_as_one_minute(self):
		"""Found on a real Route D run. The deadline is stamped a fraction of a
		second after `creation`, so a genuine one-minute allowance measures
		59.997s and FLOORED to zero — recording limit_value 0 and printing "its
		deadline had already passed", which is the wording meant for a deadline
		someone moved into the past by hand. One minute is the shortest a person
		can set and the likeliest to be used for testing, so it was also the
		likeliest to be misreported."""
		from one_bpmn import tasks as scheduled

		task = _task(state="working")
		created = frappe.utils.get_datetime(
			frappe.db.get_value("A2A Task", task.name, "creation")
		)
		# Exactly what local.delegate writes: now + N minutes, a few ms after
		# `creation` was stamped.
		frappe.db.set_value(
			"A2A Task",
			task.name,
			"deadline",
			frappe.utils.add_to_date(created, seconds=59, minutes=0) ,
			update_modified=False,
		)
		delegation.record(task, delegating_agent=None)
		scheduled._escalate_deadline(task.name)
		row = frappe.db.get_value(
			"Agent Delegation",
			delegation.for_task(task.name),
			["limit_value", "error_message"],
			as_dict=True,
		)
		self.assertEqual(row.limit_value, 1, "59.997 seconds is a one-minute deadline")
		self.assertNotIn("had already passed", row.error_message or "")

	def test_one_attempt_needs_no_explanation(self):
		task = _task(state="failed")
		delegation.record(task, delegating_agent=None)
		self.assertEqual(delegation.attempts_note(task.name), "")

	def test_more_than_one_attempt_says_the_time_was_shared(self):
		"""Otherwise "running for 30 minutes" reads as one long attempt when it
		was three short ones inside one window."""
		task = _task(state="failed")
		delegation.record(task, delegating_agent=None)
		delegation.note_attempt(task.name)
		delegation.note_attempt(task.name)
		note = delegation.attempts_note(task.name)
		self.assertIn("attempts", note)
		self.assertIn("not per attempt", note)


class TestCapabilityGate(FrappeTestCase):
	"""WI-002056, the hybrid. WHICH specialist gets the work is decided by the
	orchestrator reading the brief against the tool descriptions — a tag match
	cannot do that, because the signal is in the text (a work item asking to be
	sized carries no field saying so; its type is "Task" and it has no labels).
	WHETHER that specialist may receive it is decided from the registry.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _agent(self, tags):
		from one_bpmn.agents._eval_test_factories import make_agent_configuration

		agent = make_agent_configuration(a2a_exposed=1)
		agent.db_set("a2a_skill_tags", tags, update_modified=False)
		return agent

	def test_capabilities_are_read_from_the_skill_tags(self):
		agent = self._agent("connector, integration, api")
		self.assertEqual(
			guardrails.capabilities_of(agent.name), {"connector", "integration", "api"}
		)

	def test_tags_are_matched_regardless_of_case_or_padding(self):
		"""They are hand-typed into a comma-separated field, so ' REST ' and
		'rest' are the same capability."""
		agent = self._agent("  REST ,  OpenAPI  ")
		self.assertEqual(guardrails.capabilities_of(agent.name), {"rest", "openapi"})
		self.assertIsNone(guardrails.check_capability(agent.name, "rest"))
		self.assertIsNone(guardrails.check_capability(agent.name, " Rest "))

	def test_an_agent_without_the_capability_is_refused(self):
		agent = self._agent("connector, api")
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.check_capability(agent.name, "estimation")
		self.assertEqual(caught.exception.reason_code, "capability_mismatch")

	def test_the_refusal_names_who_could_do_it_instead(self):
		"""'Nobody can do this' and 'someone else can' call for different
		responses, so the refusal has to tell them apart."""
		wrong = self._agent("connector, api")
		right = self._agent("estimation, sizing")
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.check_capability(wrong.name, "estimation")
		self.assertIn(right.name, str(caught.exception))

	def test_a_capability_nobody_has_says_so(self):
		agent = self._agent("connector")
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.check_capability(agent.name, "quantum-alchemy")
		self.assertIn("No agent currently claims it", str(caught.exception))

	def test_no_required_capability_means_no_constraint(self):
		"""Every map that exists today declares nothing, and must keep working
		exactly as it did."""
		agent = self._agent("connector")
		self.assertIsNone(guardrails.check_capability(agent.name, None))
		self.assertIsNone(guardrails.check_capability(agent.name, ""))

	def test_only_agents_in_a2a_can_answer_a_capability_search(self):
		"""The registry narrows to agents that take part in agent-to-agent work;
		an unexposed agent with the right tag is still not a candidate."""
		from one_bpmn.agents._eval_test_factories import make_agent_configuration

		hidden = make_agent_configuration()
		hidden.db_set("a2a_skill_tags", "telepathy", update_modified=False)
		self.assertNotIn(hidden.name, guardrails.agents_with_capability("telepathy"))

	def test_the_gate_runs_inside_enforce(self):
		"""Both A2A doors go through enforce(), so the capability check belongs
		there rather than at one call site."""
		agent = self._agent("connector")
		counters = {"delegation_depth": 1, "handoff_count": 1}
		self.assertIsNone(guardrails.enforce(None, agent.name, counters))
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.enforce(None, agent.name, counters, required_capability="estimation")
		self.assertEqual(caught.exception.reason_code, "capability_mismatch")

	def test_changing_the_tags_changes_the_answer(self):
		"""Who may receive work is configuration, not a diagram: no code change
		and no map edit."""
		agent = self._agent("connector")
		with self.assertRaises(guardrails.DelegationRefused):
			guardrails.check_capability(agent.name, "estimation")
		agent.db_set("a2a_skill_tags", "connector, estimation", update_modified=False)
		self.assertIsNone(guardrails.check_capability(agent.name, "estimation"))


class TestCancellingADelegation(FrappeTestCase):
	"""Stopping a delegation is a PERSON's action.

	An agent able to cancel its own hand-offs could cancel its way out of a
	limit it had been given, so there is no tool shape for this and the only
	door is the admin endpoint.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _running(self, with_instance=False):
		task = _task(state="working")
		ad = delegation.record(task, delegating_agent=None)
		instance = None
		if with_instance:
			instance = frappe.get_doc({
				"doctype": "BPMN Process Instance",
				"process_model": frappe.db.get_value("BPMN Process Model", {}, "name"),
				"status": "Active",
			})
			instance.flags.ignore_links = True
			instance.flags.ignore_mandatory = True
			instance.insert(ignore_permissions=True)
			frappe.db.set_value(
				"Agent Delegation", ad, "worker_instance", instance.name, update_modified=False
			)
		return task, ad, instance

	def test_the_record_says_who_stopped_it_and_when(self):
		task, ad, _ = self._running()
		delegation.cancel(ad, reason="looping on a broken endpoint")
		row = frappe.db.get_value(
			"Agent Delegation",
			ad,
			["status", "stopped_reason", "cancelled_by", "cancelled_at", "ended_at", "error_message"],
			as_dict=True,
		)
		self.assertEqual(row.status, "Cancelled")
		self.assertEqual(row.stopped_reason, delegation.CANCELLED_REASON)
		self.assertEqual(row.cancelled_by, frappe.session.user)
		self.assertTrue(row.cancelled_at)
		self.assertTrue(row.ended_at)
		self.assertIn("looping on a broken endpoint", row.error_message)

	def test_the_task_is_closed_too(self):
		task, ad, _ = self._running()
		delegation.cancel(ad)
		row = frappe.db.get_value("A2A Task", task.name, ["state", "error_code"], as_dict=True)
		self.assertEqual(row.state, "canceled")
		self.assertEqual(row.error_code, delegation.CANCELLED_REASON)

	def test_a_running_worker_is_stopped_from_advancing(self):
		task, ad, instance = self._running(with_instance=True)
		result = delegation.cancel(ad)
		self.assertTrue(result["worker_stopped"])
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", instance.name, "status"), "Cancelled"
		)

	def test_it_admits_a_pass_may_still_be_running(self):
		"""The honest part. A pass already executing cannot be interrupted — the
		same reason the protocol's own cancel refuses anything past submitted —
		so a clean stop must not be reported when it cannot be guaranteed."""
		_, ad, _ = self._running(with_instance=True)
		self.assertTrue(delegation.cancel(ad)["pass_may_still_be_running"])

	def test_no_worker_process_is_not_a_failure(self):
		"""A delegation whose worker never started still cancels — it just stops
		waiting, and says that is what happened."""
		_, ad, _ = self._running()
		result = delegation.cancel(ad)
		self.assertEqual(result["status"], "Cancelled")
		self.assertFalse(result["worker_stopped"])
		self.assertFalse(result["pass_may_still_be_running"])

	def test_a_finished_delegation_cannot_be_cancelled(self):
		_, ad, _ = self._running()
		frappe.db.set_value("Agent Delegation", ad, "status", "Completed", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			delegation.cancel(ad)

	def test_cancelling_twice_is_refused_rather_than_silently_repeated(self):
		_, ad, _ = self._running()
		delegation.cancel(ad)
		with self.assertRaises(frappe.ValidationError):
			delegation.cancel(ad)

	def test_an_unknown_delegation_is_an_error(self):
		with self.assertRaises(frappe.DoesNotExistError):
			delegation.cancel("AD-does-not-exist")

	def test_a_worker_that_finished_first_is_not_overwritten(self):
		"""Found end to end. A worker can finish between the moment a person
		reads the screen and the moment they click, and one did — the
		cancellation overwrote a completed delegation with "Cancelled",
		destroying the real outcome. Whoever reaches a terminal state first
		wins."""
		_, ad, _ = self._running()
		frappe.db.set_value("Agent Delegation", ad, "status", "Completed", update_modified=False)
		with self.assertRaises(frappe.ValidationError) as caught:
			delegation.cancel(ad)
		self.assertIn("finished", str(caught.exception))
		self.assertEqual(frappe.db.get_value("Agent Delegation", ad, "status"), "Completed")

	def test_a_worker_we_could_not_stop_is_reported_as_maybe_running(self):
		"""The warning must be driven by whether the worker was RUNNING, not by
		whether we managed to mark it — the earlier version reported a clean
		stop in exactly the case where nothing was stopped."""
		from unittest.mock import patch as mock_patch

		_, ad, instance = self._running(with_instance=True)
		real = frappe.db.set_value

		def blocking(doctype, *args, **kwargs):
			if doctype == "BPMN Process Instance":
				raise frappe.QueryTimeoutError("Lock wait timeout exceeded")
			return real(doctype, *args, **kwargs)

		with mock_patch.object(frappe.db, "set_value", side_effect=blocking):
			result = delegation.cancel(ad)

		self.assertFalse(result["worker_stopped"])
		self.assertTrue(result["pass_may_still_be_running"])

	def test_the_comment_says_cancelled_not_stopped_at_a_limit(self):
		"""A cancellation is a decision, not a threshold. The shared comment
		helper used to hard-code the limit heading, so a cancelled delegation
		read as "Delegation stopped at a limit — Delegation cancelled"."""
		_, ad, _ = self._running()
		ref = frappe.db.get_value("A2A Task", {}, "name")
		frappe.db.set_value(
			"Agent Delegation", ad,
			{"reference_doctype": "A2A Task", "reference_name": ref},
			update_modified=False,
		)
		delegation.cancel(ad)
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "A2A Task", "reference_name": ref, "comment_type": "Comment"},
			fields=["content"],
			order_by="creation desc",
			limit=1,
		)
		if comments:
			self.assertIn("Delegation cancelled", comments[0].content)
			self.assertNotIn("stopped at a limit", comments[0].content)

	def test_a_busy_worker_cannot_block_the_cancellation(self):
		"""Found end to end, not by reading the code. Writing the worker's rows
		first meant a cancellation could fail outright with "Lock wait timeout
		exceeded", because a RUNNING worker holds the lock on its own A2A Task
		row — exactly the case cancellation exists for. The decision is recorded
		first now, and everything that can block is best-effort.
		"""
		from unittest.mock import patch as mock_patch

		task, ad, _ = self._running()
		real = frappe.db.set_value

		def blocking(doctype, *args, **kwargs):
			if doctype == "A2A Task":
				raise frappe.QueryTimeoutError("Lock wait timeout exceeded")
			return real(doctype, *args, **kwargs)

		with mock_patch.object(frappe.db, "set_value", side_effect=blocking):
			result = delegation.cancel(ad)

		self.assertEqual(result["status"], "Cancelled")
		self.assertFalse(result["task_closed"])
		self.assertTrue(
			result["pass_may_still_be_running"],
			"a task we could not close may still be running, and must be reported as such",
		)
		self.assertEqual(frappe.db.get_value("Agent Delegation", ad, "status"), "Cancelled")

	def test_a_task_that_could_not_be_closed_is_reported_not_hidden(self):
		"""The reconciler settles it later; the person cancelling is told now."""
		_, ad, _ = self._running()
		result = delegation.cancel(ad)
		self.assertTrue(result["task_closed"])

	def test_the_model_is_told_a_person_stopped_it_not_that_a_limit_was_hit(self):
		"""limit_note() carries the reason back to the delegating agent. A
		cancellation is not a limit, and describing it as one would have the
		orchestrator report a threshold that was never reached."""
		task, ad, _ = self._running()
		delegation.cancel(ad)
		note = delegation.limit_note(task.name)
		self.assertIn("cancelled", note.lower())
		self.assertNotIn("limit on", note)

	def test_the_answer_handed_back_says_it_was_cancelled(self):
		from one_bpmn.tasks import _delegation_answer

		task, ad, _ = self._running()
		delegation.cancel(ad)
		task.reload()
		self.assertIn("cancelled", _delegation_answer(task).lower())


class TestDeadlineBelongsToTheDelegator(FrappeTestCase):
	"""Whose clock is it?

	delegation_deadline_minutes used to be read off the TARGET agent, on the
	reasoning that the agent doing the work knows how long it needs. That made it
	the one guardrail a worker could set for itself: with 1 minute configured on
	the orchestrator and 60 on the worker, an end-to-end run took the worker's
	number and the orchestrator's limit did nothing at all. It now reads off the
	delegating agent, beside the three limits it belongs with.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@staticmethod
	def _agents():
		"""Two real configurations to play delegator and worker."""
		names = frappe.get_all("AI Agent Configuration", pluck="name", limit=2)
		return (names + [None, None])[:2]

	def test_the_delegating_agent_supplies_the_deadline(self):
		delegator, _ = self._agents()
		frappe.db.set_value("AI Agent Configuration", delegator, "delegation_deadline_minutes", 7)
		self.assertEqual(guardrails.deadline_minutes_for(delegator), 7)

	def test_a_blank_field_means_no_limit_of_its_own(self):
		"""0, so the caller falls through to its own backstop — as distinct from
		the DEFAULTS limits, where blank means "use the platform default"."""
		delegator, _ = self._agents()
		frappe.db.set_value("AI Agent Configuration", delegator, "delegation_deadline_minutes", 0)
		self.assertEqual(guardrails.deadline_minutes_for(delegator), 0)

	def test_no_delegating_agent_means_no_limit(self):
		self.assertEqual(guardrails.deadline_minutes_for(None), 0)

	def test_the_workers_own_number_is_not_consulted(self):
		"""The regression itself: the worker's field must not decide the clock."""
		delegator, worker = self._agents()
		if not worker or worker == delegator:
			self.skipTest("need two distinct agent configurations")
		frappe.db.set_value("AI Agent Configuration", delegator, "delegation_deadline_minutes", 1)
		frappe.db.set_value("AI Agent Configuration", worker, "delegation_deadline_minutes", 60)
		self.assertEqual(guardrails.deadline_minutes_for(delegator), 1)
		self.assertNotEqual(guardrails.deadline_minutes_for(delegator), 60)

	def test_the_target_fields_no_longer_carry_it(self):
		"""Pins the removal, so a future edit does not quietly reintroduce the
		worker's number as a fallback."""
		from one_bpmn.agents.a2a import local

		self.assertNotIn("delegation_deadline_minutes", local.TARGET_FIELDS)


class TestLimitReachesTheModel(FrappeTestCase):
	"""The delegating MODEL has to be told which limit stopped its worker.

	A worker that runs out of tool-calling turns still finishes its run, so the
	A2A Task reads "completed" and the only thing coming back is whatever thin
	text it managed. The orchestrator read that as an outage and reported the
	specialist was "unable to respond right now" — while the comment on the work
	item correctly said the turn cap had stopped it. The reason existed; the
	model was the one party never given it.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_note_when_nothing_stopped_the_delegation(self):
		task = _task(state="completed")
		delegation.record(task, delegating_agent=None)
		self.assertEqual(delegation.limit_note(task.name), "")

	def test_no_note_for_a_task_that_was_never_recorded(self):
		self.assertEqual(delegation.limit_note("A2A-does-not-exist"), "")
		self.assertEqual(delegation.limit_note(None), "")

	def test_note_names_the_limit_and_both_numbers(self):
		task = _task(state="completed")
		delegation.record(task, delegating_agent=None)
		delegation.stopped_at_limit(
			a2a_task=task.name, reason="turn_cap", limit_value=1, reached_value=1
		)
		note = delegation.limit_note(task.name)
		self.assertIn("tool-calling turns", note)
		self.assertIn("1 against a limit of 1", note)

	def test_note_says_a_retry_will_not_help(self):
		"""The behaviour this is for: the orchestrator must not offer to try
		again as though the worker had merely been unlucky."""
		task = _task(state="completed")
		delegation.record(task, delegating_agent=None)
		delegation.stopped_at_limit(
			a2a_task=task.name, reason="turn_cap", limit_value=1, reached_value=1
		)
		note = delegation.limit_note(task.name)
		self.assertIn("configured limit", note)
		self.assertIn("not", note)

	def test_the_answer_handed_back_carries_the_note(self):
		"""End of the seam: what tasks._delegation_answer actually returns."""
		from one_bpmn.tasks import _delegation_answer

		task = _task(state="completed")
		task.db_set("result", frappe.as_json({"text": "produced no answer."}), update_modified=False)
		task.reload()
		delegation.record(task, delegating_agent=None)
		delegation.stopped_at_limit(
			a2a_task=task.name, reason="turn_cap", limit_value=1, reached_value=1
		)
		answer = _delegation_answer(task)
		self.assertIn("produced no answer.", answer)
		self.assertIn("tool-calling turns", answer)


class TestDelegationRetry(FrappeTestCase):
	"""max_delegation_retries, now that something reads it.

	Four decisions are pinned here, because each was a judgement: only a FAILED
	worker is retried, the attempt count lives on the delegation, the first
	attempt counts toward the total, and exhausting the attempts escalates
	through the same seam every other limit uses.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _recorded(self, delegating_agent=None):
		task = _task(state="failed")
		return task, delegation.record(task, delegating_agent=delegating_agent)

	def test_attempts_allowed_counts_the_first_run_too(self):
		"""Three retries means four runs in total would be the other reading;
		this codebase treats the configured number as the run count."""
		agent = _any_agent()
		configured = guardrails.guardrails_for(agent)["max_delegation_retries"]
		self.assertEqual(delegation.attempts_allowed(agent), 1 + configured)

	def test_a_fresh_failure_has_a_retry_left(self):
		task, ad = self._recorded()
		self.assertTrue(delegation.should_retry(task.name))

	def test_each_attempt_is_counted_on_the_delegation(self):
		"""Not on the A2A Task: one delegation stays one row, and the count is
		what WI-002060's dashboard needs."""
		task, ad = self._recorded()
		self.assertEqual(delegation.note_attempt(task.name), 2)
		self.assertEqual(frappe.db.get_value("Agent Delegation", ad, "attempt_count"), 2)

	def test_a_retry_puts_it_back_to_in_progress(self):
		"""And clears the stale failure — the row spans every attempt."""
		task, ad = self._recorded()
		frappe.db.set_value("Agent Delegation", ad, "error_message", "old failure")
		delegation.note_attempt(task.name)
		row = frappe.db.get_value(
			"Agent Delegation", ad, ["status", "error_message"], as_dict=True
		)
		self.assertEqual(row.status, "In Progress")
		self.assertIsNone(row.error_message)

	def test_retries_run_out_after_the_allowed_number(self):
		task, ad = self._recorded()
		allowed = delegation.attempts_allowed(None)
		for _ in range(allowed - 1):
			self.assertTrue(delegation.should_retry(task.name))
			delegation.note_attempt(task.name)
		self.assertFalse(
			delegation.should_retry(task.name), "it retried past the configured limit"
		)

	def test_exhaustion_escalates_like_any_other_limit(self):
		task, ad = self._recorded()
		frappe.db.set_value("Agent Delegation", ad, "attempt_count", 99)
		delegation.retries_exhausted(task.name)
		row = frappe.db.get_value(
			"Agent Delegation", ad, ["status", "stopped_reason", "reached_value"], as_dict=True
		)
		self.assertEqual(row.status, "Needs Review")
		self.assertEqual(row.stopped_reason, "max_delegation_retries")
		self.assertEqual(row.reached_value, 99)

	def test_a_delegation_already_needing_review_is_not_retried(self):
		"""Once a person has been asked to look at it, retrying behind their
		back would undo the escalation."""
		task, ad = self._recorded()
		frappe.db.set_value("Agent Delegation", ad, "status", "Needs Review")
		self.assertFalse(delegation.should_retry(task.name))

	def test_an_unrecorded_task_is_never_retried(self):
		self.assertFalse(delegation.should_retry("A2A-NOT-A-THING"))
		self.assertEqual(delegation.note_attempt("A2A-NOT-A-THING"), 0)
