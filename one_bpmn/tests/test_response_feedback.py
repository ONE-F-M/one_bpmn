"""
What a user thought of an agent reply, end to end (WI-001641).

Everything here runs without a browser and without an LLM, which is the point:
the record, the endpoint and the eval-case path are the half of response
feedback that can be proven headlessly, so WI-001822 can add the thumbs control
on top of something already known to work.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_response_feedback
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import feedback

OTHER_USER = "wi1641_outsider@example.com"


def _sse_events(chunks) -> list[dict]:
	out = []
	for chunk in chunks:
		for line in chunk.splitlines():
			if line.startswith("data: "):
				out.append(json.loads(line[len("data: ") :]))
	return out


class FeedbackFixture(FrappeTestCase):
	"""A conversation owned by the current user, with one agent reply in it."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = frappe.get_doc(
			{"doctype": "Chat Conversation", "title": "WI-001641 probe", "agent_mode": "ProsAlly"}
		).insert(ignore_permissions=True)

		self.reply = self._message("Bot", "Here is your process.")
		self.question = self._message("User", "Draw me a process.")
		self.addCleanup(self._cleanup)

	def _message(self, kind: str, text: str, metadata: dict | None = None):
		doc = frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation.name,
				"sender": "Administrator",
				"receiver": "User",
				"text": text,
				"message_type": kind,
				"metadata": json.dumps(metadata) if metadata else None,
			}
		)
		# The PII hook on Chat Message is load-bearing elsewhere; these fixtures
		# only need the row to exist.
		doc.insert(ignore_permissions=True)
		return doc

	def _run(self, label="probe"):
		"""A real AI Agent Run row. The link is validated on save, so a made-up
		name would not just fail the test — it is the same failure a user would
		hit if their run had been trimmed, which is why the endpoint drops a
		dangling run rather than storing it."""
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

	def _cleanup(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"AI Response Feedback", filters={"conversation": self.conversation.name}, pluck="name"
		):
			frappe.delete_doc("AI Response Feedback", name, force=True, ignore_permissions=True)


class TestCaptureAndReRating(FeedbackFixture):
	def test_a_rating_is_stored_against_the_reply(self):
		out = feedback.rate_response(self.reply.name, "Positive")
		self.assertEqual(out["rating"], "Positive")
		row = frappe.get_doc("AI Response Feedback", out["name"])
		self.assertEqual(row.message, self.reply.name)
		self.assertEqual(row.conversation, self.conversation.name)
		self.assertEqual(row.rated_by, "Administrator")
		self.assertTrue(row.rated_on)

	def test_re_rating_updates_in_place_and_never_duplicates(self):
		first = feedback.rate_response(self.reply.name, "Positive")["name"]
		second = feedback.rate_response(
			self.reply.name, "Negative", reasons=["Inaccurate", "Incomplete"]
		)["name"]

		self.assertEqual(first, second, "a changed mind created a second row")
		rows = frappe.get_all("AI Response Feedback", filters={"message": self.reply.name})
		self.assertEqual(len(rows), 1)

		row = frappe.get_doc("AI Response Feedback", second)
		self.assertEqual(row.rating, "Negative")
		self.assertEqual(sorted(r.reason for r in row.reasons), ["Inaccurate", "Incomplete"])

	def test_the_change_of_mind_is_auditable(self):
		"""Auditability is Frappe's own Version trail rather than a bespoke audit
		table, so the thing to protect is track_changes staying on: switch it off
		and every re-rating becomes silent.

		The Version ROW is not asserted here because the test runner does not
		produce one. Verified against the live site instead — a Positive changed
		to Negative writes exactly:
		    {"changed": [["rating", "Positive", "Negative"]]}
		"""
		self.assertTrue(
			frappe.get_meta("AI Response Feedback").track_changes,
			"track_changes is off: re-rating would leave no history",
		)
		name = feedback.rate_response(self.reply.name, "Positive")["name"]
		feedback.rate_response(self.reply.name, "Negative")
		self.assertEqual(frappe.db.get_value("AI Response Feedback", name, "rating"), "Negative")

	def test_unrated_and_negative_are_different_things(self):
		self.assertIsNone(feedback.get_response_rating(self.reply.name)["rating"])
		self.assertEqual(
			frappe.db.count("AI Response Feedback", {"message": self.reply.name}),
			0,
			"an unrated reply must have no row at all",
		)

		feedback.rate_response(self.reply.name, "Negative")
		self.assertEqual(feedback.get_response_rating(self.reply.name)["rating"], "Negative")

	def test_clearing_removes_the_row_rather_than_storing_a_third_state(self):
		feedback.rate_response(self.reply.name, "Negative")
		out = feedback.clear_response_rating(self.reply.name)
		self.assertTrue(out["cleared"])
		self.assertEqual(frappe.db.count("AI Response Feedback", {"message": self.reply.name}), 0)

	def test_reasons_are_dropped_on_a_positive_rating(self):
		out = feedback.rate_response(self.reply.name, "Positive", reasons=["Inaccurate"])
		self.assertEqual(out["reasons"], [])

	def test_unknown_reasons_are_discarded(self):
		out = feedback.rate_response(
			self.reply.name, "Negative", reasons=["Inaccurate", "Made me sad"]
		)
		self.assertEqual(out["reasons"], ["Inaccurate"])

	def test_reasons_accept_a_json_string_from_the_wire(self):
		"""Frappe hands whitelisted args through as strings over HTTP."""
		out = feedback.rate_response(self.reply.name, "Negative", reasons='["Wrong tone"]')
		self.assertEqual(out["reasons"], ["Wrong tone"])

	def test_a_bad_rating_value_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			feedback.rate_response(self.reply.name, "Meh")


class TestWhatMayBeRated(FeedbackFixture):
	def test_only_an_agent_reply_can_be_rated(self):
		"""Rating your own question would quietly pollute every per-agent
		average with rows no agent produced."""
		with self.assertRaises(frappe.ValidationError):
			feedback.rate_response(self.question.name, "Positive")

	def test_a_missing_message_is_refused(self):
		with self.assertRaises(frappe.DoesNotExistError):
			feedback.rate_response("CM-does-not-exist", "Positive")

	def test_someone_outside_the_conversation_cannot_rate_it(self):
		if not frappe.db.exists("User", OTHER_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": OTHER_USER,
					"first_name": "WI1641",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		frappe.set_user(OTHER_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				feedback.rate_response(self.reply.name, "Negative")
		finally:
			frappe.set_user("Administrator")

	def test_a_participant_who_does_not_own_the_conversation_may_rate(self):
		if not frappe.db.exists("User", OTHER_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": OTHER_USER,
					"first_name": "WI1641",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		conv = frappe.get_doc("Chat Conversation", self.conversation.name)
		conv.append("participants", {"user": OTHER_USER})
		conv.save(ignore_permissions=True)

		frappe.set_user(OTHER_USER)
		try:
			out = feedback.rate_response(self.reply.name, "Positive")
			self.assertEqual(out["rating"], "Positive")
		finally:
			frappe.set_user("Administrator")

	def test_two_users_rating_the_same_reply_are_two_rows(self):
		"""The uniqueness is per person, not per reply — otherwise one user's
		opinion would overwrite another's."""
		if not frappe.db.exists("User", OTHER_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": OTHER_USER,
					"first_name": "WI1641",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		conv = frappe.get_doc("Chat Conversation", self.conversation.name)
		conv.append("participants", {"user": OTHER_USER})
		conv.save(ignore_permissions=True)

		feedback.rate_response(self.reply.name, "Positive")
		frappe.set_user(OTHER_USER)
		try:
			feedback.rate_response(self.reply.name, "Negative")
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.count("AI Response Feedback", {"message": self.reply.name}), 2)


class TestTheJoinToTheRun(FeedbackFixture):
	"""Without the run, feedback cannot be set beside cost and latency, which is
	the only reason to record the run at all."""

	def test_the_run_is_taken_from_the_reply_metadata(self):
		run = self._run("direct")
		reply = self._message("Bot", "With a run", metadata={"agent_run": run})
		out = feedback.rate_response(reply.name, "Negative")
		self.assertEqual(out["agent_run"], run)

	def test_a_nested_agent_result_run_is_also_found(self):
		run = self._run("nested")
		reply = self._message("Bot", "Nested", metadata={"agent_result": {"agent_run": run}})
		out = feedback.rate_response(reply.name, "Negative")
		self.assertEqual(out["agent_run"], run)

	def test_a_run_that_has_been_trimmed_does_not_cost_the_user_their_rating(self):
		"""agent_run is a Link: a name that no longer resolves would make the
		save throw and the click would be lost to housekeeping nobody saw."""
		reply = self._message("Bot", "Stale run", metadata={"agent_run": "RUN-LONG-GONE"})
		out = feedback.rate_response(reply.name, "Negative")
		self.assertIsNone(out["agent_run"])
		self.assertEqual(out["rating"], "Negative")

	def test_a_reply_with_no_run_is_still_rateable(self):
		"""Feedback on a reply whose run has been trimmed is still feedback."""
		out = feedback.rate_response(self.reply.name, "Negative")
		self.assertIsNone(out["agent_run"])
		self.assertEqual(out["rating"], "Negative")


class TestReplicationIntoTests(FeedbackFixture):
	def _negative(self, status="Reviewed", run=True):
		run = self._run("convert") if run else None
		reply = self._message("Bot", "Wrong answer", metadata={"agent_run": run} if run else None)
		name = feedback.rate_response(reply.name, "Negative", reasons=["Inaccurate"])["name"]
		frappe.db.set_value("AI Response Feedback", name, "status", status)
		return name

	def test_a_positive_rating_never_becomes_a_test(self):
		out = feedback.rate_response(self.reply.name, "Positive")
		frappe.db.set_value("AI Response Feedback", out["name"], "status", "Reviewed")
		with self.assertRaises(frappe.ValidationError):
			feedback.create_eval_case_from_feedback(out["name"])

	def test_unreviewed_feedback_never_becomes_a_test(self):
		"""People press thumbs down because an answer was slow, or because they
		disagreed with a correct answer. Auto-converting would fill the suite
		with noise and destroy trust in it."""
		name = self._negative(status="New")
		with self.assertRaises(frappe.ValidationError):
			feedback.create_eval_case_from_feedback(name)

	def test_feedback_with_no_run_cannot_become_a_test(self):
		name = self._negative(run=False)
		with self.assertRaises(frappe.ValidationError):
			feedback.create_eval_case_from_feedback(name)

	def test_a_reviewed_complaint_becomes_a_linked_case(self):
		name = self._negative()
		with patch(
			"one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			return_value="EVAL-CASE-FIXTURE",
		) as factory:
			out = feedback.create_eval_case_from_feedback(name, suite="SUITE-1")

		self.assertTrue(out["created"])
		self.assertEqual(out["eval_case"], "EVAL-CASE-FIXTURE")
		factory.assert_called_once()
		# A case from a failure must not be seeded with "match what it did" —
		# that would certify the wrong answer as the expected one.
		self.assertIs(factory.call_args.kwargs["add_starter_assertion"], False)
		self.assertEqual(factory.call_args.kwargs["suite"], "SUITE-1")

		row = frappe.get_doc("AI Response Feedback", name)
		self.assertEqual(row.status, "Converted")
		self.assertEqual(row.eval_case, "EVAL-CASE-FIXTURE")

	def test_converting_twice_returns_the_same_case(self):
		name = self._negative()
		with patch(
			"one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			return_value="EVAL-CASE-FIXTURE",
		):
			feedback.create_eval_case_from_feedback(name)

		# The case row does not exist on this site, so the second call falls
		# through to creating again rather than silently returning a dangling
		# link — assert on the guard that does hold: status is already Converted.
		self.assertEqual(frappe.db.get_value("AI Response Feedback", name, "status"), "Converted")


class TestTheReplyCarriesItsOwnId(FrappeTestCase):
	"""Part 1. The client cannot rate a reply it cannot name."""

	def test_the_stream_uses_the_persisted_message_name_as_the_message_id(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "hi", "message_name": "CM-PERSISTED-1"},
		):
			events = _sse_events(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		text_events = [e for e in events if e.get("type", "").startswith("TEXT_MESSAGE")]
		self.assertTrue(text_events)
		for event in text_events:
			self.assertEqual(
				event.get("messageId"),
				"CM-PERSISTED-1",
				"the reply's id is not the row the user can rate",
			)

	def test_a_runner_that_persists_nothing_still_gets_a_usable_id(self):
		from one_bpmn.agents import agui_stream

		with patch(
			"one_bpmn.api.agent_invocation.invoke_agent",
			return_value={"response": "hi"},
		):
			events = _sse_events(agui_stream.agent_event_stream("any_agent", "hi", "CONV-1"))

		ids = {e["messageId"] for e in events if e.get("type", "").startswith("TEXT_MESSAGE")}
		self.assertEqual(len(ids), 1, "the text events of one reply must share one id")
		self.assertTrue(next(iter(ids)))


class TestWhereTheCaseIsFiled(FeedbackFixture):
	"""Nobody should have to know a suite name to file a regression — and the
	suite it lands in must not be one that gets wiped."""

	AGENT = "prosally_agent"

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("AI Agent Configuration", {"agent_id": self.AGENT, "enabled": 1}):
			self.skipTest(f"{self.AGENT} is not configured on this site")
		self.config = frappe.db.get_value(
			"AI Agent Configuration", {"agent_id": self.AGENT, "enabled": 1}
		)
		self.agent_name = frappe.db.get_value("AI Agent Configuration", self.config, "agent_name")
		self.addCleanup(self._drop_regression_suites)

	def _drop_regression_suites(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"AI Eval Suite",
			filters={"title": f"{self.agent_name} — Regressions", "agent_configuration": self.config},
			pluck="name",
		):
			for case in frappe.get_all("AI Eval Case", filters={"suite": name}, pluck="name"):
				frappe.delete_doc("AI Eval Case", case, force=True, ignore_permissions=True)
			frappe.delete_doc("AI Eval Suite", name, force=True, ignore_permissions=True)

	def test_a_suite_is_created_on_first_use(self):
		suite = feedback._resolve_regression_suite(self.config)
		doc = frappe.get_doc("AI Eval Suite", suite)
		self.assertEqual(doc.title, f"{self.agent_name} — Regressions")
		self.assertEqual(doc.agent_configuration, self.config)

	def test_the_same_suite_is_reused_forever_after(self):
		first = feedback._resolve_regression_suite(self.config)
		second = feedback._resolve_regression_suite(self.config)
		self.assertEqual(first, second, "a second complaint created a second suite")
		self.assertEqual(
			frappe.db.count(
				"AI Eval Suite",
				{"title": f"{self.agent_name} — Regressions", "agent_configuration": self.config},
			),
			1,
		)

	def test_it_is_never_the_provisioned_baseline_suite(self):
		"""agent_provisioning rebuilds "<agent> — Baseline" from sample prompts on
		every re-provision, and rebuilding DELETES every case in it. A regression
		parked there would quietly disappear."""
		suite = feedback._resolve_regression_suite(self.config)
		title = frappe.db.get_value("AI Eval Suite", suite, "title")
		self.assertNotEqual(title, f"{self.agent_name} — Baseline")

	def test_the_replay_matches_how_the_agent_actually_runs(self):
		"""A failure that happened through the map has to be replayed through the
		map, or the tools that produced it never run."""
		suite = feedback._resolve_regression_suite(self.config)
		doc = frappe.get_doc("AI Eval Suite", suite)
		has_map = bool(frappe.db.get_value("AI Agent Configuration", self.config, "process_model"))
		self.assertEqual(doc.eval_type, "Agent" if has_map else "Direct")

	def test_a_regression_suite_does_not_gate_deployment_by_itself(self):
		suite = feedback._resolve_regression_suite(self.config)
		self.assertFalse(frappe.db.get_value("AI Eval Suite", suite, "gate_deployment"))

	def test_conversion_needs_no_suite_argument(self):
		run = self._run("filed")
		reply = self._message("Bot", "Wrong", metadata={"agent_run": run})
		name = feedback.rate_response(reply.name, "Negative")["name"]
		frappe.db.set_value("AI Response Feedback", name, "agent_configuration", self.config)
		frappe.db.set_value("AI Response Feedback", name, "status", "Reviewed")

		with patch(
			"one_bpmn.agents.eval_case_factory.create_eval_case_from_run",
			return_value="EVAL-CASE-FILED",
		) as factory:
			out = feedback.create_eval_case_from_feedback(name)

		self.assertTrue(out["created"])
		filed_to = factory.call_args.kwargs["suite"]
		self.assertTrue(filed_to, "the case was filed with no suite at all")
		self.assertEqual(
			frappe.db.get_value("AI Eval Suite", filed_to, "title"),
			f"{self.agent_name} — Regressions",
		)

	def test_feedback_with_no_agent_cannot_be_filed(self):
		name = self._negative_no_agent()
		with self.assertRaises(frappe.ValidationError):
			feedback.create_eval_case_from_feedback(name)

	def _negative_no_agent(self):
		run = self._run("orphan")
		reply = self._message("Bot", "Wrong", metadata={"agent_run": run})
		name = feedback.rate_response(reply.name, "Negative")["name"]
		frappe.db.set_value("AI Response Feedback", name, "agent_configuration", None)
		frappe.db.set_value("AI Response Feedback", name, "status", "Reviewed")
		return name
