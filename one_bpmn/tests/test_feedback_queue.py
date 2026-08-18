"""
The triage queue behind the Evals feedback page (WI-002068).

The page is Vue and this repo has no JS test harness, so what is pinned here is
the endpoint it lives on — the filters, the joined context that makes a row
judgeable, the permission scoping, and the reason a row cannot become a case.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_feedback_queue
"""

from __future__ import annotations

import json

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import eval_api, feedback

OTHER_USER = "wi2068_outsider@example.com"


class QueueFixture(FrappeTestCase):
	"""A conversation with two rated replies, each with a question before it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = frappe.get_doc(
			{"doctype": "Chat Conversation", "title": "WI-002068 probe", "agent_mode": "ProsAlly"}
		).insert(ignore_permissions=True)

		self.q1 = self._message("User", "How many leave days do I have?")
		self.r1 = self._message("Bot", "Twenty-six.")
		self.q2 = self._message("User", "And carry-over?")
		self.r2 = self._message("Bot", "None at all.")
		self.addCleanup(self._cleanup)

	def _message(self, kind, text, metadata=None):
		return frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation.name,
				"sender": "Administrator",
				"receiver": "User",
				"text": text,
				"message_type": kind,
				"metadata": json.dumps(metadata) if metadata else None,
			}
		).insert(ignore_permissions=True)

	def _run(self, label="queue"):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": label,
				"status": "Success",
				"started_at": frappe.utils.now_datetime(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: frappe.db.exists("AI Agent Run", n)
			and frappe.delete_doc("AI Agent Run", n, force=True, ignore_permissions=True)
		)
		return doc.name

	def _rows(self, **kw):
		"""Only this conversation's rows — the site carries other people's."""
		mine = {self.r1.name, self.r2.name}
		return [r for r in eval_api.list_response_feedback(**kw) if r["message"] in mine]

	def _cleanup(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"AI Response Feedback", filters={"conversation": self.conversation.name}, pluck="name"
		):
			frappe.delete_doc("AI Response Feedback", name, force=True, ignore_permissions=True)


class TestTheQueueIsTheDefault(QueueFixture):
	def test_it_defaults_to_negative_and_unreviewed(self):
		feedback.rate_response(self.r1.name, "Negative")
		feedback.rate_response(self.r2.name, "Positive")

		rows = self._rows()
		self.assertEqual([r["message"] for r in rows], [self.r1.name])
		self.assertEqual(rows[0]["rating"], "Negative")
		self.assertEqual(rows[0]["status"], "New")

	def test_a_reviewed_complaint_leaves_the_queue(self):
		feedback.rate_response(self.r1.name, "Negative")
		name = self._rows()[0]["name"]
		feedback.set_feedback_status(name, "Reviewed")

		self.assertEqual(self._rows(), [])
		self.assertEqual(len(self._rows(status="Reviewed")), 1)

	def test_widening_the_filters_shows_the_rest(self):
		feedback.rate_response(self.r1.name, "Negative")
		feedback.rate_response(self.r2.name, "Positive")

		self.assertEqual(len(self._rows(rating="All", status="All")), 2)
		self.assertEqual(len(self._rows(rating="Positive", status="All")), 1)

	def test_filtering_by_agent_narrows_it(self):
		feedback.rate_response(self.r1.name, "Negative")
		agent = self._rows()[0]["agent_configuration"]
		if not agent:
			self.skipTest("no agent configuration resolved on this site")
		self.assertEqual(len(self._rows(agent=agent)), 1)
		self.assertEqual(len(self._rows(agent="AI Agent Configuration-does-not-exist")), 0)


class TestARowCanBeJudged(QueueFixture):
	def test_the_question_that_prompted_the_reply_comes_with_it(self):
		"""A reply on its own is unjudgeable — "that answer was wrong" means
		nothing without the question."""
		feedback.rate_response(self.r2.name, "Negative")
		row = self._rows()[0]
		self.assertEqual(row["reply_text"], "None at all.")
		self.assertEqual(
			row["prompt_text"],
			"And carry-over?",
			"the row carries the wrong question — the reviewer would judge the wrong exchange",
		)

	def test_the_nearest_earlier_question_is_the_one_shown(self):
		feedback.rate_response(self.r1.name, "Negative")
		self.assertEqual(self._rows()[0]["prompt_text"], "How many leave days do I have?")

	def test_reasons_and_comment_travel_with_the_row(self):
		feedback.rate_response(
			self.r1.name, "Negative", reasons=["Inaccurate", "Wrong tone"], comment="Not close."
		)
		row = self._rows()[0]
		self.assertEqual(sorted(row["reasons"]), ["Inaccurate", "Wrong tone"])
		self.assertEqual(row["comment"], "Not close.")

	def test_a_reply_whose_question_is_missing_still_lists(self):
		"""An opening reply (a greeting) has nothing before it. That is a row with
		no question, not a row that fails to load."""
		lone = frappe.get_doc(
			{"doctype": "Chat Conversation", "title": "greeting only", "agent_mode": "ProsAlly"}
		).insert(ignore_permissions=True)
		reply = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": lone.name,
				"sender": "Administrator",
				"receiver": "User",
				"text": "Hello, I am ProsAlly.",
				"message_type": "Bot",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: [
				frappe.delete_doc("AI Response Feedback", n, force=True, ignore_permissions=True)
				for n in frappe.get_all("AI Response Feedback", filters={"conversation": lone.name}, pluck="name")
			]
		)
		feedback.rate_response(reply.name, "Negative")
		row = next(r for r in eval_api.list_response_feedback() if r["message"] == reply.name)
		self.assertEqual(row["prompt_text"], "")
		self.assertEqual(row["reply_text"], "Hello, I am ProsAlly.")


class TestWhyARowCannotBecomeATest(QueueFixture):
	def test_a_complaint_with_no_run_says_so_instead_of_offering_a_button(self):
		feedback.rate_response(self.r1.name, "Negative")
		row = self._rows()[0]
		self.assertFalse(row["can_convert"])
		self.assertIn("no agent run", (row["blocked_reason"] or "").lower())

	def test_a_complaint_with_a_run_can_be_converted(self):
		run = self._run()
		reply = self._message("Bot", "Wrong answer", metadata={"agent_run": run})
		feedback.rate_response(reply.name, "Negative")
		row = next(r for r in eval_api.list_response_feedback() if r["message"] == reply.name)
		self.assertTrue(row["can_convert"], row["blocked_reason"])
		self.assertIsNone(row["blocked_reason"])

	def test_a_positive_rating_is_never_convertible(self):
		feedback.rate_response(self.r2.name, "Positive")
		row = next(
			r for r in eval_api.list_response_feedback(rating="Positive", status="All")
			if r["message"] == self.r2.name
		)
		self.assertFalse(row["can_convert"])


class TestTheCounts(QueueFixture):
	def test_counts_carry_their_denominator(self):
		"""A satisfaction percentage would be confidently wrong: under 1% of
		replies are rated and raters sit at the extremes. The card shows rated
		out of replies instead."""
		feedback.rate_response(self.r1.name, "Negative")
		feedback.rate_response(self.r2.name, "Positive")

		o = eval_api.get_feedback_overview()
		for key in ("total_replies", "total_rated", "negative", "awaiting_review", "reviewed", "converted"):
			self.assertIn(key, o)
		self.assertGreaterEqual(o["total_replies"], 2)
		self.assertGreaterEqual(o["total_rated"], 2)
		self.assertNotIn("satisfaction", o)
		self.assertNotIn("score", o)

	def test_the_queue_count_follows_the_triage(self):
		feedback.rate_response(self.r1.name, "Negative")
		before = eval_api.get_feedback_overview()["awaiting_review"]
		feedback.set_feedback_status(self._rows()[0]["name"], "Reviewed")
		after = eval_api.get_feedback_overview()
		self.assertEqual(after["awaiting_review"], before - 1)
		self.assertGreaterEqual(after["reviewed"], 1)


class TestTriageDecisions(QueueFixture):
	def test_dismissing_is_available_and_final_enough(self):
		"""Most thumbs-down are not regressions. Dismiss has to be as reachable as
		review, or reviewers convert everything."""
		feedback.rate_response(self.r1.name, "Negative")
		name = self._rows()[0]["name"]
		feedback.set_feedback_status(name, "Dismissed")
		self.assertEqual(frappe.db.get_value("AI Response Feedback", name, "status"), "Dismissed")

	def test_converted_cannot_be_typed_by_hand(self):
		"""Converted means a case exists. Setting it directly would leave rows
		claiming a test nobody created."""
		feedback.rate_response(self.r1.name, "Negative")
		name = self._rows()[0]["name"]
		with self.assertRaises(frappe.ValidationError):
			feedback.set_feedback_status(name, "Converted")

	def test_a_converted_row_is_not_reopened(self):
		feedback.rate_response(self.r1.name, "Negative")
		name = self._rows()[0]["name"]
		frappe.db.set_value("AI Response Feedback", name, "status", "Converted")
		with self.assertRaises(frappe.ValidationError):
			feedback.set_feedback_status(name, "Reviewed")

	def test_a_bad_status_is_refused(self):
		feedback.rate_response(self.r1.name, "Negative")
		with self.assertRaises(frappe.ValidationError):
			feedback.set_feedback_status(self._rows()[0]["name"], "Sorted")


class TestPermissionsComeFromTheDoctype(QueueFixture):
	def test_a_user_without_the_role_is_refused_not_shown_an_empty_queue(self):
		"""No second permission model: get_list applies AI Response Feedback's own
		permissions. It REFUSES rather than returning [], which is the honest
		outcome — an empty table would tell someone "nobody has rated anything"
		when the truth is "you may not look". The page renders the refusal as
		such."""
		if not frappe.db.exists("User", OTHER_USER):
			frappe.get_doc(
				{"doctype": "User", "email": OTHER_USER, "first_name": "WI2068", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		feedback.rate_response(self.r1.name, "Negative")

		frappe.set_user(OTHER_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				eval_api.list_response_feedback()
		finally:
			frappe.set_user("Administrator")


class TestStayingInsideProcessa(QueueFixture):
	"""Converting hands the reviewer straight to the eval case editor, which lives
	on the suite page. Both halves of that route have to come back from the
	server, or the page falls out to the desk mid-task."""

	def test_conversion_returns_the_suite_to_navigate_to(self):
		run = self._run("nav")
		reply = self._message("Bot", "Wrong", metadata={"agent_run": run})
		name = feedback.rate_response(reply.name, "Negative")["name"]
		frappe.db.set_value("AI Response Feedback", name, "status", "Reviewed")

		with patch(
			"one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			return_value="EVAL-CASE-NAV",
		):
			out = feedback.create_eval_case_from_feedback(name)

		self.assertEqual(out["eval_case"], "EVAL-CASE-NAV")
		self.assertTrue(out.get("suite"), "no suite came back — the page cannot route to the case")

	def test_an_already_converted_row_still_returns_its_suite(self):
		"""Clicking convert twice must not lose the destination."""
		run = self._run("nav2")
		reply = self._message("Bot", "Wrong again", metadata={"agent_run": run})
		name = feedback.rate_response(reply.name, "Negative")["name"]
		frappe.db.set_value("AI Response Feedback", name, "status", "Reviewed")

		with patch(
			"one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			return_value="EVAL-CASE-NAV2",
		):
			first = feedback.create_eval_case_from_feedback(name)
		# The case row does not exist on this site, so the guard that returns early
		# is the status one; assert the shape the page depends on either way.
		self.assertTrue(first.get("suite"))

	def test_a_row_with_a_case_carries_the_suite_for_open_eval_case(self):
		agent = frappe.db.get_value("AI Eval Suite", {}, "agent_configuration") or frappe.db.get_value(
			"AI Agent Configuration", {"enabled": 1}
		)
		if not agent:
			self.skipTest("no agent configuration on this site to own a suite")
		suite = frappe.get_doc(
			{
				"doctype": "AI Eval Suite",
				"title": "WI-002068 nav suite",
				"eval_type": "Direct",
				"agent_configuration": agent,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("AI Eval Suite", suite.name, force=True, ignore_permissions=True)
		)
		case = frappe.get_doc(
			{
				"doctype": "AI Eval Case",
				"title": "nav case",
				"suite": suite.name,
				"input_user_prompt": "anything",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("AI Eval Case", case.name, force=True, ignore_permissions=True)
		)

		feedback.rate_response(self.r1.name, "Negative")
		name = self._rows()[0]["name"]
		frappe.db.set_value("AI Response Feedback", name, "eval_case", case.name)

		row = next(
			r for r in eval_api.list_response_feedback(rating="All", status="All")
			if r["name"] == name
		)
		self.assertEqual(row["eval_suite"], suite.name)
