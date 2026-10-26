"""Feedback records carry the exchange, an owner and the run's errors, and a fix can spread to its siblings."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.api import feedback
from one_bpmn.one_bpmn.patches.v1_0 import ai_feedback_requires_resolution_details as resolution_patch
from one_bpmn.security.script_validator import deep_inspect_script
from one_bpmn.tests.test_response_feedback import FeedbackFixture

OWNER = "wi_feedback_owner@example.com"
PROCESS_OWNER = "wi_process_owner@example.com"
TOOL_ERROR = '{"error": "Shape generate failed - TimeoutError: upstream"}'
RESOLUTION = "Raised the upstream timeout."


class OwnedFeedbackFixture(FeedbackFixture):
	def setUp(self):
		super().setUp()
		for email in (OWNER, PROCESS_OWNER):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": "Owner", "send_welcome_email": 0}
				).insert(ignore_permissions=True)

	def _agent(self, **fields):
		cfg = make_agent_configuration(**fields)
		self.addCleanup(
			lambda n=cfg.name: frappe.delete_doc("AI Agent Configuration", n, force=True, ignore_permissions=True)
		)
		return cfg.name

	def _failed_run(self, agent, result=TOOL_ERROR):
		run = self._run()
		frappe.db.set_value("AI Agent Run", run, "agent_configuration", agent)
		step = frappe.get_doc(
			{
				"doctype": "AI Agent Step",
				"run": run,
				"step_index": 1,
				"role": "tool",
				"tool_calls": [
					{"tool_name": "generate_process", "status": "Error", "tool_result": result},
					{"tool_name": "finalize", "status": "Success", "tool_result": '{"finalized": true}'},
				],
			}
		)
		step.flags.ignore_mandatory = True
		step.insert(ignore_permissions=True)
		return run

	def _rated_reply(self, run, text="Could you tell me more?"):
		reply = self._message("Bot", text, metadata={"agent_run": run})
		feedback.rate_response(reply.name, "Negative", comment="Ignored my request.")
		return frappe.get_doc("AI Response Feedback", {"message": reply.name})


class TestTheExchangeIsStored(OwnedFeedbackFixture):
	def test_a_reply_with_no_text_cannot_be_rated(self):
		empty = self._message("Bot", "")
		with self.assertRaises(frappe.ValidationError):
			feedback.rate_response(empty.name, "Positive")
		self.assertFalse(frappe.db.exists("AI Response Feedback", {"message": empty.name}))

	def test_a_reply_to_a_question_must_carry_the_question(self):
		answer = self._message("Bot", "Here is the diagram.")
		doc = frappe.get_doc(
			{
				"doctype": "AI Response Feedback",
				"message": answer.name,
				"conversation": self.conversation.name,
				"rated_by": "Administrator",
				"rating": "Positive",
				"output": answer.text,
				"user_message": "",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_rating_a_reply_stores_both_sides(self):
		answer = self._message("Bot", "Here is the diagram.")
		feedback.rate_response(answer.name, "Positive")
		row = frappe.db.get_value(
			"AI Response Feedback", {"message": answer.name}, ["user_message", "output"], as_dict=True
		)
		self.assertEqual(row.user_message, "Draw me a process.")
		self.assertEqual(row.output, "Here is the diagram.")

	def test_a_greeting_with_no_question_before_it_stays_rateable(self):
		feedback.rate_response(self.reply.name, "Positive")
		self.assertTrue(frappe.db.exists("AI Response Feedback", {"message": self.reply.name}))


class TestTheFeedbackOwner(OwnedFeedbackFixture):
	def test_new_feedback_goes_to_the_feedback_owner(self):
		agent = self._agent(feedback_owner=OWNER, process_owner=PROCESS_OWNER)
		doc = self._rated_reply(self._failed_run(agent))
		self.assertEqual(doc.process_owner, OWNER)

	def test_without_a_feedback_owner_it_falls_back_to_the_process_owner(self):
		agent = self._agent(process_owner=PROCESS_OWNER)
		doc = self._rated_reply(self._failed_run(agent))
		self.assertEqual(doc.process_owner, PROCESS_OWNER)


class TestTheRunErrorsAreCopied(OwnedFeedbackFixture):
	def test_failed_tool_calls_are_copied_with_their_tool_name(self):
		agent = self._agent(feedback_owner=OWNER)
		doc = self._rated_reply(self._failed_run(agent))
		self.assertEqual(doc.run_errors, f"generate_process: {TOOL_ERROR}")

	def test_a_run_with_no_failed_call_copies_nothing(self):
		agent = self._agent(feedback_owner=OWNER)
		run = self._run()
		frappe.db.set_value("AI Agent Run", run, "agent_configuration", agent)
		doc = self._rated_reply(run)
		self.assertFalse(doc.run_errors)


class TestAFixSpreadsToTheSameFailure(OwnedFeedbackFixture):
	def setUp(self):
		super().setUp()
		self.agent = self._agent(feedback_owner=OWNER)
		self.fixed = self._rated_reply(self._failed_run(self.agent), "First fallback.")
		self.sibling = self._rated_reply(self._failed_run(self.agent), "Second fallback.")
		self.other = self._rated_reply(self._failed_run(self.agent, '{"error": "not_permitted"}'), "Other.")
		feedback.set_feedback_status(self.fixed.name, "Fixed", RESOLUTION)

	def test_applying_gives_the_siblings_the_same_resolution_details(self):
		feedback.mark_same_error_fixed(self.fixed.name)
		self.assertEqual(
			frappe.db.get_value("AI Response Feedback", self.sibling.name, "resolution_details"), RESOLUTION
		)

	def test_only_new_records_with_the_same_errors_are_offered(self):
		offered = [row.name for row in feedback.get_same_error_feedback(self.fixed.name)]
		self.assertEqual(offered, [self.sibling.name])

	def test_a_record_outside_48_hours_is_not_offered(self):
		frappe.db.set_value(
			"AI Response Feedback", self.sibling.name, "rated_on", add_to_date(now_datetime(), hours=-49)
		)
		self.assertEqual(feedback.get_same_error_feedback(self.fixed.name), [])

	def test_applying_marks_the_siblings_fixed(self):
		out = feedback.mark_same_error_fixed(self.fixed.name)
		self.assertEqual(out["fixed"], [self.sibling.name])
		self.assertEqual(frappe.db.get_value("AI Response Feedback", self.sibling.name, "status"), "Fixed")
		self.assertEqual(frappe.db.get_value("AI Response Feedback", self.other.name, "status"), "New")

	def test_applying_from_a_record_that_is_not_fixed_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			feedback.mark_same_error_fixed(self.sibling.name)

	def test_a_user_without_access_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			feedback.get_same_error_feedback(self.fixed.name)


class TestFixedNeedsResolutionDetails(OwnedFeedbackFixture):
	def setUp(self):
		super().setUp()
		self.record = self._rated_reply(self._failed_run(self._agent(feedback_owner=OWNER)))

	def _status(self):
		return frappe.db.get_value("AI Response Feedback", self.record.name, "status")

	def test_saving_a_fixed_record_without_details_is_refused(self):
		for details in ("", "   "):
			self.record.status = "Fixed"
			self.record.resolution_details = details
			with self.assertRaises(frappe.ValidationError):
				self.record.save()

	def test_saving_a_fixed_record_with_details_works(self):
		self.record.status = "Fixed"
		self.record.resolution_details = RESOLUTION
		self.record.save()
		self.assertEqual(self._status(), "Fixed")

	def test_other_statuses_need_no_details(self):
		self.record.status = "Reviewed"
		self.record.save()
		self.assertEqual(self._status(), "Reviewed")

	def test_the_status_api_refuses_fixed_without_details(self):
		with self.assertRaises(frappe.ValidationError):
			feedback.set_feedback_status(self.record.name, "Fixed")
		self.assertEqual(self._status(), "New")

	def test_the_status_api_keeps_the_details_it_is_given(self):
		feedback.set_feedback_status(self.record.name, "Fixed", RESOLUTION)
		self.assertEqual(
			frappe.db.get_value("AI Response Feedback", self.record.name, "resolution_details"), RESOLUTION
		)

	def test_details_already_on_the_record_are_enough_for_the_status_api(self):
		frappe.db.set_value("AI Response Feedback", self.record.name, "resolution_details", RESOLUTION)
		feedback.set_feedback_status(self.record.name, "Fixed")
		self.assertEqual(self._status(), "Fixed")

	def test_the_rater_is_told_what_was_done_with_markup_escaped(self):
		sent = []
		with patch(
			"frappe.desk.doctype.notification_log.notification_log.enqueue_create_notification",
			side_effect=lambda users, doc: sent.append(doc),
		):
			feedback.set_feedback_status(self.record.name, "Fixed", "Raised the <b>timeout</b>.")
		self.assertEqual(len(sent), 1)
		self.assertIn("What was done: Raised the &lt;b&gt;timeout&lt;/b&gt;.", sent[0]["email_content"])


class TestResolutionDetailsPatch(OwnedFeedbackFixture):
	def setUp(self):
		super().setUp()
		self.record = self._rated_reply(self._failed_run(self._agent(feedback_owner=OWNER)))

	def _script(self):
		return frappe.db.get_value("Server Script", {"name": ["like", "AI Feedback%Mark Fixed"]}, "script")

	def _run_script(self):
		exec(self._script(), {"frappe": frappe, "doc": frappe.get_doc("AI Response Feedback", self.record.name)})

	def test_existing_fixed_records_get_a_note_and_others_are_left_alone(self):
		frappe.db.set_value("AI Response Feedback", self.record.name, "status", "Fixed")
		other = self._rated_reply(self._failed_run(self._agent(feedback_owner=OWNER)), "Another.")
		resolution_patch.backfill_fixed_records()
		self.assertEqual(
			frappe.db.get_value("AI Response Feedback", self.record.name, "resolution_details"),
			resolution_patch.BACKFILL,
		)
		self.assertFalse(frappe.db.get_value("AI Response Feedback", other.name, "resolution_details"))

	def test_a_backfill_does_not_overwrite_real_details(self):
		frappe.db.set_value(
			"AI Response Feedback", self.record.name, {"status": "Fixed", "resolution_details": RESOLUTION}
		)
		resolution_patch.backfill_fixed_records()
		self.assertEqual(
			frappe.db.get_value("AI Response Feedback", self.record.name, "resolution_details"), RESOLUTION
		)

	def test_mark_fixed_refuses_a_record_without_details(self):
		resolution_patch.require_resolution_in_mark_fixed()
		with self.assertRaises(frappe.ValidationError):
			self._run_script()
		self.assertEqual(frappe.db.get_value("AI Response Feedback", self.record.name, "status"), "New")

	def test_mark_fixed_marks_a_record_that_has_details(self):
		resolution_patch.require_resolution_in_mark_fixed()
		frappe.db.set_value("AI Response Feedback", self.record.name, "resolution_details", RESOLUTION)
		self._run_script()
		self.assertEqual(frappe.db.get_value("AI Response Feedback", self.record.name, "status"), "Fixed")

	def test_the_patched_script_passes_the_validator_the_engine_runs(self):
		resolution_patch.require_resolution_in_mark_fixed()
		self.assertEqual(deep_inspect_script(self._script()), [])

	def test_running_the_patch_again_changes_nothing(self):
		resolution_patch.execute()
		before = self._script()
		resolution_patch.execute()
		self.assertEqual(self._script(), before)
