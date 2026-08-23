# Copyright (c) 2026, one-fm and contributors
"""Asking the story owner instead of guessing (WI-002050).

The pause was already there — a User shape inside an agent's toolbox is a human
tool, and selecting it suspends the run until a person completes the task. What
is pinned here is everything a suspension alone does not give you: a record of
what was asked and answered, the right person being asked, a limit on how often,
and somebody chasing a question nobody answered.

The measured background matters for one of these. Interactive-agent research
finds models default to NOT asking until told to, and that told too forcefully
they ask unnecessary questions — so the cap exists to bound the noisy failure,
not the silent one.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents import clarification


def _work_item():
	"""A Work Item of this test's own, copied from whatever the site has.

	A real record because reference_name is a Dynamic Link — an invented name
	fails validation and the row would never be written. A FRESH one because the
	round count is per document: sharing an arbitrary existing item made these
	tests depend on how many questions had been asked about it by other tests,
	or by a real run. They passed alone and failed in a suite, which is the worst
	way for a test to be wrong.

	Removed by the rollback in tearDown like everything else.
	"""
	source = frappe.db.get_value("Work Item", {}, "name")
	doc = frappe.copy_doc(frappe.get_doc("Work Item", source))
	doc.title = f"_Test clarification {frappe.generate_hash(length=8)}"
	doc.orchestrator = 0
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _instance(context_docname=None):
	return frappe._dict(
		name=frappe.db.get_value("BPMN Process Instance", {}, "name"),
		context_doctype="Work Item",
		context_docname=context_docname or _work_item(),
	)


class TestWhoGetsAsked(FrappeTestCase):
	"""The question goes to whoever set the requirement."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_reporter_is_the_story_owner(self):
		"""Not the record's owner: on a duplicated or imported story the owner is
		a service account while the reporter is the person who wrote it."""
		item = _work_item()
		frappe.db.set_value("Work Item", item, "reporter_user", "Administrator", update_modified=False)
		self.assertEqual(clarification.story_owner("Work Item", item), "Administrator")

	def test_no_document_means_nobody_to_ask(self):
		self.assertIsNone(clarification.story_owner(None, None))
		self.assertIsNone(clarification.story_owner("Work Item", None))


class TestTheRecord(FrappeTestCase):
	"""A clarification that lives only in the run's transcript cannot be audited,
	and "why was it built this way" is asked weeks later."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_question_is_written_down_when_the_agent_pauses(self):
		name = clarification.record_question(
			instance=_instance(),
			human_task_id="AIH-0001",
			agent_configuration=None,
			agent_run=None,
			arguments={"question": "Which sprint should this land in?"},
		)
		self.assertTrue(name)
		row = frappe.db.get_value(
			"AI Clarification", name, ["status", "question", "round", "asked_at"], as_dict=True
		)
		self.assertEqual(row.status, "Awaiting Answer")
		self.assertEqual(row.question, "Which sprint should this land in?")
		self.assertEqual(row.round, 1)
		self.assertTrue(row.asked_at)

	def test_the_options_it_was_choosing_between_are_kept(self):
		"""A question with the readings attached is answerable in one line; one
		without them starts another round."""
		name = clarification.record_question(
			instance=_instance(),
			human_task_id="AIH-0002",
			agent_configuration=None,
			agent_run=None,
			arguments={
				"question": "Does 'archive' mean hide or delete?",
				"interpretations": "hide from the list, or remove the record",
			},
		)
		self.assertIn("remove the record", frappe.db.get_value("AI Clarification", name, "interpretations"))

	def test_the_answer_closes_the_record(self):
		item = _work_item()
		name = clarification.record_question(
			instance=_instance(item), human_task_id="AIH-0003",
			agent_configuration=None, agent_run=None,
			arguments={"question": "Which one?"},
		)
		clarification.record_answer(
			instance=_instance(item), human_task_id="AIH-0003", data={"answer": "the second"}
		)
		row = frappe.db.get_value(
			"AI Clarification", name, ["status", "answer", "answered_by", "answered_at"], as_dict=True
		)
		self.assertEqual(row.status, "Answered")
		self.assertEqual(row.answer, "the second")
		self.assertEqual(row.answered_by, frappe.session.user)
		self.assertTrue(row.answered_at)

	def test_an_answer_with_no_recognised_field_is_kept_verbatim(self):
		"""The form may collect fields nobody here knows the names of. Better to
		store them as they came than to record an empty answer."""
		item = _work_item()
		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-0004",
			agent_configuration=None, agent_run=None, arguments={"question": "?"},
		)
		clarification.record_answer(
			instance=_instance(item), human_task_id="AIH-0004", data={"whatever_field": "use metric"}
		)
		answer = frappe.db.get_value(
			"AI Clarification", {"human_task_id": "AIH-0004"}, "answer"
		)
		self.assertIn("use metric", answer)

	def test_the_pair_is_written_onto_the_document(self):
		"""An alert is gone once dismissed. The question and the answer belong
		where the next person to ask "why is it like this" is already looking."""
		item = _work_item()
		before = frappe.db.count(
			"Comment", {"reference_doctype": "Work Item", "reference_name": item, "comment_type": "Comment"}
		)
		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-0005",
			agent_configuration=None, agent_run=None, arguments={"question": "Which currency?"},
		)
		clarification.record_answer(
			instance=_instance(item), human_task_id="AIH-0005", data={"answer": "KWD"}
		)
		after = frappe.db.count(
			"Comment", {"reference_doctype": "Work Item", "reference_name": item, "comment_type": "Comment"}
		)
		self.assertEqual(after, before + 2, "the question and the answer are both on the record")

	def test_answering_something_that_was_never_asked_is_not_an_error(self):
		self.assertIsNone(
			clarification.record_answer(
				instance=_instance(), human_task_id="AIH-does-not-exist", data={"answer": "x"}
			)
		)

	def test_a_follow_up_chains_onto_the_question_before_it(self):
		"""The story requires a follow-up when an answer does not resolve the
		ambiguity, and a chain is what makes "we asked twice" visible."""
		item = _work_item()
		first = clarification.record_question(
			instance=_instance(item), human_task_id="AIH-0006",
			agent_configuration=None, agent_run=None, arguments={"question": "Which?"},
		)
		second = clarification.record_question(
			instance=_instance(item), human_task_id="AIH-0007",
			agent_configuration=None, agent_run=None, arguments={"question": "Still which?"},
		)
		row = frappe.db.get_value("AI Clarification", second, ["follow_up_of", "round"], as_dict=True)
		self.assertEqual(row.follow_up_of, first)
		self.assertEqual(row.round, 2)


class TestHowOftenItMayAsk(FrappeTestCase):
	"""Over-asking is the documented failure of an interactive agent — a question
	that adds friction without improving the outcome."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _agent(self, rounds):
		from one_bpmn.agents._eval_test_factories import make_agent_configuration

		agent = make_agent_configuration()
		agent.db_set("max_clarification_rounds", rounds, update_modified=False)
		return agent.name

	def test_no_cap_means_no_limit(self):
		agent = self._agent(0)
		item = _work_item()
		for i in range(4):
			clarification.record_question(
				instance=_instance(item), human_task_id=f"AIH-N{i}",
				agent_configuration=agent, agent_run=None, arguments={"question": "?"},
			)
		self.assertFalse(clarification.cap_reached(agent, "Work Item", item))

	def test_the_cap_is_reached_after_its_rounds(self):
		agent = self._agent(2)
		item = _work_item()
		self.assertFalse(clarification.cap_reached(agent, "Work Item", item))
		for i in range(2):
			clarification.record_question(
				instance=_instance(item), human_task_id=f"AIH-C{i}",
				agent_configuration=agent, agent_run=None, arguments={"question": "?"},
			)
		self.assertTrue(clarification.cap_reached(agent, "Work Item", item))

	def test_the_count_is_per_document_not_per_run(self):
		"""A story retried or handed back is the same story; a cap that reset
		would not be a cap."""
		agent = self._agent(1)
		item = _work_item()
		# A different run against the same document. `name` is left unset rather
		# than invented: it is a Link, and an instance that does not exist would
		# fail validation and the row would never be written.
		clarification.record_question(
			instance=frappe._dict(name=None, context_doctype="Work Item", context_docname=item),
			human_task_id="AIH-R1", agent_configuration=agent, agent_run=None,
			arguments={"question": "?"},
		)
		self.assertTrue(clarification.cap_reached(agent, "Work Item", item))

	def test_the_tool_is_withdrawn_once_the_cap_is_reached(self):
		"""Withdrawn rather than refused mid-call: a tool the model can see and
		cannot use invites it to keep trying."""
		from one_bpmn.agents.shape_tools import compile_shape_tools

		agent = self._agent(1)
		item = _work_item()
		instance = frappe._dict(
			name=None, context_doctype="Work Item", context_docname=item,
			_a2a_delegating_agent=agent,
		)
		shapes = [{"bpmn_id": "ask_owner", "human": True, "description": "Ask the owner"}]
		self.assertEqual(len(compile_shape_tools(shapes, instance)), 1)

		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-W1",
			agent_configuration=agent, agent_run=None, arguments={"question": "?"},
		)
		self.assertEqual(len(compile_shape_tools(shapes, instance)), 0)


class TestHowTheQuestionAppearsToAPerson(FrappeTestCase):
	"""Two things a person saw that they should not have.

	The task showed as "ask_story_owner" — the shape's id — in the Actions menu
	on their own work item. And that menu offered it as a workflow action, which
	completes the task with no answer in it, so the agent resumed having been
	told nothing and asked again.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_human_tool_task_shows_its_drawn_name(self):
		"""compile_process_model already records the shape's name as `label` on
		every human descriptor, so this only had to be looked up."""
		instance = frappe.get_doc("BPMN Process Instance", frappe.db.get_value("BPMN Process Instance", {}, "name"))
		instance._service_task_extensions = {
			"orchestrate": {
				"aiToolShapes": frappe.as_json(
					[{"bpmn_id": "ask_story_owner", "human": True, "label": "Ask the story owner"}]
				)
			}
		}
		task = frappe._dict(task_spec=frappe._dict(bpmn_id="orchestrate", name="orchestrate"))
		self.assertEqual(
			instance._human_tool_label(task, "ask_story_owner"), "Ask the story owner"
		)

	def test_an_unknown_shape_falls_back_rather_than_breaking(self):
		instance = frappe.get_doc("BPMN Process Instance", frappe.db.get_value("BPMN Process Instance", {}, "name"))
		instance._service_task_extensions = {"orchestrate": {"aiToolShapes": "[]"}}
		task = frappe._dict(task_spec=frappe._dict(bpmn_id="orchestrate", name="orchestrate"))
		self.assertEqual(instance._human_tool_label(task, "whatever"), "")

	def test_a_question_is_not_offered_as_a_workflow_action(self):
		"""Two doors to the same task, where one of them loses the answer, is
		worse than one."""
		from one_bpmn.api.instance_api import get_active_bpmn_tasks

		item = _work_item()
		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": frappe.db.get_value("BPMN Process Model", {}, "name"),
			"status": "Active",
			"context_doctype": "Work Item",
			"context_docname": item,
		})
		instance.append("active_tasks", {
			"task_id": "aihuman::test01", "task_name": "Ask the story owner",
			"task_type": "AI Human Task", "status": "Waiting",
		})
		instance.append("active_tasks", {
			"task_id": "real-user-task", "task_name": "Approve it",
			"task_type": "User Task", "status": "Waiting", "task_actions": "Approve",
		})
		instance.flags.ignore_links = True
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True)

		offered = [t["task_name"] for t in get_active_bpmn_tasks("Work Item", item)]
		self.assertIn("Approve it", offered, "a real user task still appears")
		self.assertNotIn("Ask the story owner", offered, "an agent's question does not")


class TestItWorksOnAnyDocument(FrappeTestCase):
	"""The record names a doctype and a document, so it was never
	Work-Item-specific. The form script is bound to every form for the same
	reason: the moment an agent is pointed at a Sales Order, a question about it
	has to appear on the Sales Order."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_question_can_be_about_something_other_than_a_work_item(self):
		task = frappe.db.get_value("A2A Task", {}, "name")
		if not task:
			self.skipTest("no A2A Task on this site to point at")
		name = clarification.record_question(
			instance=frappe._dict(
				name=None, context_doctype="A2A Task", context_docname=task
			),
			human_task_id="AIH-ANY1", agent_configuration=None, agent_run=None,
			arguments={"question": "Which one?"},
		)
		row = frappe.db.get_value(
			"AI Clarification", name, ["reference_doctype", "reference_name"], as_dict=True
		)
		self.assertEqual(row.reference_doctype, "A2A Task")
		self.assertEqual(row.reference_name, task)

	def test_the_document_endpoint_is_not_doctype_specific(self):
		from one_bpmn.api import clarification_api

		task = frappe.db.get_value("A2A Task", {}, "name")
		if not task:
			self.skipTest("no A2A Task on this site to point at")
		clarification.record_question(
			instance=frappe._dict(name=None, context_doctype="A2A Task", context_docname=task),
			human_task_id="AIH-ANY2", agent_configuration=None, agent_run=None,
			arguments={"question": "About a task, not a story"},
		)
		result = clarification_api.pending_for_document("A2A Task", task)
		self.assertTrue(result["pending"])
		self.assertEqual(result["pending"]["question"], "About a task, not a story")

	def test_the_form_script_is_told_which_doctypes_to_bother_with(self):
		"""It runs on every form, so it asks once which doctypes have ever had a
		question and does nothing on the rest — a form nobody has ever asked
		about costs no round trip."""
		from one_bpmn.api import clarification_api

		item = _work_item()
		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-ANY3",
			agent_configuration=None, agent_run=None, arguments={"question": "?"},
		)
		self.assertIn("Work Item", clarification_api.doctypes_with_questions()["doctypes"])

	def test_the_list_grows_by_itself_when_an_agent_asks_about_something_new(self):
		"""Built from the rows rather than a configured list, so there is nothing
		to remember to update."""
		from one_bpmn.api import clarification_api

		task = frappe.db.get_value("A2A Task", {}, "name")
		if not task:
			self.skipTest("no A2A Task on this site to point at")
		before = clarification_api.doctypes_with_questions()["doctypes"]
		clarification.record_question(
			instance=frappe._dict(name=None, context_doctype="A2A Task", context_docname=task),
			human_task_id="AIH-ANY4", agent_configuration=None, agent_run=None,
			arguments={"question": "?"},
		)
		after = clarification_api.doctypes_with_questions()["doctypes"]
		self.assertIn("A2A Task", after)
		self.assertTrue(set(before).issubset(set(after)))


class TestTheCapIsSetFromProcessa(FrappeTestCase):
	"""The limit has to be adjustable where the agent is configured.

	A cap that could only be changed in the Desk would be a control with its
	dial in another room — and this is the one setting a process owner is
	likeliest to want to turn while watching an agent behave.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@staticmethod
	def _control(agent):
		from one_bpmn.api import security_api

		for c in security_api.agent_screening(agent)["controls"]:
			if c["fieldname"] == "max_clarification_rounds":
				return c
		return None

	def test_it_is_offered_as_a_control(self):
		from one_bpmn.agents._eval_test_factories import make_agent_configuration

		control = self._control(make_agent_configuration().name)
		self.assertIsNotNone(control)
		self.assertEqual(control["fieldtype"], "Int")

	def test_it_has_its_own_group_rather_than_hiding_under_delegation(self):
		"""Asking a person a question is not delegating work to an agent, and
		filing it under Delegation would misdescribe it."""
		from one_bpmn.agents._eval_test_factories import make_agent_configuration

		self.assertEqual(self._control(make_agent_configuration().name)["group"], "Clarification")

	def test_saving_it_from_processa_changes_what_the_cap_reads(self):
		"""The point of editing it: the number the tool is withdrawn at moves."""
		from one_bpmn.agents._eval_test_factories import make_agent_configuration
		from one_bpmn.api import security_api

		agent = make_agent_configuration().name
		item = _work_item()
		security_api.save_agent_screening(agent, {"max_clarification_rounds": 1})
		self.assertEqual(clarification.rounds_allowed(agent), 1)
		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-PZ1",
			agent_configuration=agent, agent_run=None, arguments={"question": "?"},
		)
		self.assertTrue(clarification.cap_reached(agent, "Work Item", item))

		# Raised from Processa, the agent may ask again.
		security_api.save_agent_screening(agent, {"max_clarification_rounds": 4})
		self.assertFalse(clarification.cap_reached(agent, "Work Item", item))

	def test_it_can_be_turned_off_entirely(self):
		"""0 means no limit, and it has to be reachable — an agent whose stories
		are genuinely underspecified should not be silenced by a cap."""
		from one_bpmn.agents._eval_test_factories import make_agent_configuration
		from one_bpmn.api import security_api

		agent = make_agent_configuration().name
		security_api.save_agent_screening(agent, {"max_clarification_rounds": 0})
		self.assertEqual(clarification.rounds_allowed(agent), 0)
		self.assertFalse(clarification.cap_reached(agent, "Work Item", _work_item()))


class TestChasingAnUnansweredQuestion(FrappeTestCase):
	"""Do not block forever, and do not proceed on a timeout. This does the first
	half — somebody is told — and deliberately not the second."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _asked(self, minutes_ago):
		item = _work_item()
		name = clarification.record_question(
			instance=_instance(item), human_task_id=f"AIH-T{minutes_ago}",
			agent_configuration=None, agent_run=None, arguments={"question": "Which one?"},
		)
		frappe.db.set_value(
			"AI Clarification", name,
			{"asked_at": add_to_date(now_datetime(), minutes=-minutes_ago), "owner_asked": "Administrator"},
			update_modified=False,
		)
		return name

	def test_a_fresh_question_is_left_alone(self):
		name = self._asked(5)
		clarification.chase_unanswered(reminder_minutes=60, escalate_minutes=1440)
		self.assertIsNone(frappe.db.get_value("AI Clarification", name, "reminded_at"))

	def test_a_question_waiting_too_long_is_reminded(self):
		name = self._asked(90)
		result = clarification.chase_unanswered(reminder_minutes=60, escalate_minutes=1440)
		self.assertGreaterEqual(result["reminded"], 1)
		self.assertTrue(frappe.db.get_value("AI Clarification", name, "reminded_at"))

	def test_it_is_only_reminded_once(self):
		"""This runs on a schedule and would otherwise nag every hour."""
		name = self._asked(90)
		clarification.chase_unanswered(reminder_minutes=60, escalate_minutes=1440)
		second = clarification.chase_unanswered(reminder_minutes=60, escalate_minutes=1440)
		self.assertEqual(second["reminded"], 0)
		self.assertTrue(frappe.db.get_value("AI Clarification", name, "reminded_at"))

	def test_a_question_waiting_far_too_long_is_escalated(self):
		name = self._asked(2000)
		result = clarification.chase_unanswered(reminder_minutes=60, escalate_minutes=1440)
		self.assertGreaterEqual(result["escalated"], 1)
		self.assertTrue(frappe.db.get_value("AI Clarification", name, "escalated_at"))

	def test_chasing_never_answers_the_question_itself(self):
		"""The agent stays blocked. Auto-resolving after a wait would be guessing
		with extra steps, which is the thing this story exists to prevent."""
		name = self._asked(5000)
		clarification.chase_unanswered(reminder_minutes=60, escalate_minutes=1440)
		row = frappe.db.get_value("AI Clarification", name, ["status", "answer"], as_dict=True)
		self.assertEqual(row.status, "Awaiting Answer")
		self.assertFalse(row.answer)


class TestAnsweringFromTheStory(FrappeTestCase):
	"""The owner answers on the work item, not on a process instance they have no
	reason to open."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_pending_question_is_readable_from_the_document(self):
		from one_bpmn.api import clarification_api

		item = _work_item()
		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-P1",
			agent_configuration=None, agent_run=None, arguments={"question": "Which sprint?"},
		)
		result = clarification_api.pending_for_document("Work Item", item)
		self.assertTrue(result["pending"])
		self.assertEqual(result["pending"]["question"], "Which sprint?")

	def test_answered_questions_come_back_as_history(self):
		"""A follow-up reads as pedantic without the answer that failed to
		resolve the first question."""
		from one_bpmn.api import clarification_api

		item = _work_item()
		clarification.record_question(
			instance=_instance(item), human_task_id="AIH-P2",
			agent_configuration=None, agent_run=None, arguments={"question": "First?"},
		)
		clarification.record_answer(
			instance=_instance(item), human_task_id="AIH-P2", data={"answer": "yes"}
		)
		result = clarification_api.pending_for_document("Work Item", item)
		self.assertIsNone(result["pending"])
		self.assertTrue(any(h["question"] == "First?" for h in result["history"]))

	def test_an_empty_answer_is_refused(self):
		"""The agent is waiting on the actual decision."""
		from one_bpmn.api import clarification_api

		item = _work_item()
		name = clarification.record_question(
			instance=_instance(item), human_task_id="AIH-P3",
			agent_configuration=None, agent_run=None, arguments={"question": "?"},
		)
		with self.assertRaises(frappe.ValidationError):
			clarification_api.answer(name, "   ")

	def test_a_question_already_answered_cannot_be_answered_again(self):
		from one_bpmn.api import clarification_api

		item = _work_item()
		name = clarification.record_question(
			instance=_instance(item), human_task_id="AIH-P4",
			agent_configuration=None, agent_run=None, arguments={"question": "?"},
		)
		clarification.record_answer(
			instance=_instance(item), human_task_id="AIH-P4", data={"answer": "done"}
		)
		with self.assertRaises(frappe.ValidationError):
			clarification_api.answer(name, "again")

	def test_an_unknown_question_is_an_error(self):
		from one_bpmn.api import clarification_api

		with self.assertRaises(frappe.DoesNotExistError):
			clarification_api.answer("AC-does-not-exist", "hello")
