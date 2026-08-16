"""
What the chat panel needs in order to show a rating control (WI-001822).

The control itself is a Vue component and this repo has no JS test harness, so
what is pinned here is everything the panel depends on and could silently lose:

  * a resumed conversation's replies arrive WITH their row id, or the control has
    nothing to attach an answer to and quietly disappears on reload
  * the panel can read back this user's ratings in one call, so a rating left
    before a reload is still showing afterwards
  * an agent can be configured not to collect feedback at all
  * one user's rating is never shown to another — the control shows what you
    said, not a tally

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_feedback_surface
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import feedback
from one_bpmn.utils.chat_persistence import load_history

AGENT = "prosally_agent"
OTHER_USER = "wi1822_outsider@example.com"


def _ensure_user(email: str):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "WI1822", "send_welcome_email": 0}
		).insert(ignore_permissions=True)


class PanelFixture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.conversation = frappe.get_doc(
			{"doctype": "Chat Conversation", "title": "WI-001822 probe", "agent_mode": "ProsAlly"}
		).insert(ignore_permissions=True)
		self.question = self._message("User", "What is the leave policy?")
		self.reply = self._message("Bot", "Twenty-six days.")
		self.reply2 = self._message("Bot", "Plus public holidays.")
		self.addCleanup(self._cleanup)

	def _message(self, kind: str, text: str):
		return frappe.get_doc(
			{
				"doctype": "Chat Message",
				"conversation": self.conversation.name,
				"sender": "Administrator",
				"receiver": "User",
				"text": text,
				"message_type": kind,
			}
		).insert(ignore_permissions=True)

	def _cleanup(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"AI Response Feedback", filters={"conversation": self.conversation.name}, pluck="name"
		):
			frappe.delete_doc("AI Response Feedback", name, force=True, ignore_permissions=True)


class TestAResumedConversationCanStillBeRated(PanelFixture):
	def test_history_carries_the_row_id_of_every_message(self):
		history = load_history(self.conversation.name)
		self.assertEqual(len(history), 3)
		for row in history:
			self.assertTrue(
				row.get("message"),
				"a redrawn reply with no id cannot be rated — the control would vanish on reload",
			)
		self.assertEqual(
			[r["message"] for r in history],
			[self.question.name, self.reply.name, self.reply2.name],
			"history ids are not the rows they describe, in order",
		)

	def test_history_still_carries_role_and_content(self):
		"""The id is additive: nothing that already read this may break."""
		history = load_history(self.conversation.name)
		self.assertEqual([r["role"] for r in history], ["user", "assistant", "assistant"])
		self.assertEqual(history[0]["content"], "What is the leave policy?")


class TestReadingBackYourOwnRatings(PanelFixture):
	def test_one_call_returns_every_rating_in_the_conversation(self):
		feedback.rate_response(self.reply.name, "Positive")
		feedback.rate_response(self.reply2.name, "Negative", reasons=["Incomplete"])

		got = feedback.get_conversation_ratings(self.conversation.name)
		self.assertEqual(got, {self.reply.name: "Positive", self.reply2.name: "Negative"})

	def test_an_unrated_conversation_reads_as_empty_not_as_an_error(self):
		self.assertEqual(feedback.get_conversation_ratings(self.conversation.name), {})

	def test_clearing_a_rating_removes_it_from_the_read_back(self):
		feedback.rate_response(self.reply.name, "Positive")
		feedback.clear_response_rating(self.reply.name)
		self.assertEqual(feedback.get_conversation_ratings(self.conversation.name), {})

	def test_re_rating_shows_the_latest_answer(self):
		feedback.rate_response(self.reply.name, "Positive")
		feedback.rate_response(self.reply.name, "Negative")
		self.assertEqual(
			feedback.get_conversation_ratings(self.conversation.name),
			{self.reply.name: "Negative"},
		)

	def test_you_never_see_somebody_elses_rating(self):
		"""The control shows what YOU said. Showing another participant's answer
		would turn a private signal into a public score."""
		_ensure_user(OTHER_USER)
		conv = frappe.get_doc("Chat Conversation", self.conversation.name)
		conv.append("participants", {"user": OTHER_USER})
		conv.save(ignore_permissions=True)

		frappe.set_user(OTHER_USER)
		try:
			feedback.rate_response(self.reply.name, "Negative")
			self.assertEqual(
				feedback.get_conversation_ratings(self.conversation.name),
				{self.reply.name: "Negative"},
			)
		finally:
			frappe.set_user("Administrator")

		# The owner rated nothing, so the owner sees nothing.
		self.assertEqual(feedback.get_conversation_ratings(self.conversation.name), {})

	def test_an_outsider_cannot_read_the_ratings_of_a_conversation(self):
		_ensure_user(OTHER_USER)
		frappe.set_user(OTHER_USER)
		try:
			with self.assertRaises(frappe.PermissionError):
				feedback.get_conversation_ratings(self.conversation.name)
		finally:
			frappe.set_user("Administrator")


class TestPerAgentSwitch(FrappeTestCase):
	"""The disabled-agent case. Configuration, not code — the panel asks the
	surface, exactly as it does for the greeting and the icon."""

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("AI Agent Configuration", {"agent_id": AGENT, "enabled": 1}):
			self.skipTest(f"{AGENT} is not configured on this site")
		self.config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT, "enabled": 1})
		self.original = frappe.db.get_value("AI Agent Configuration", self.config, "collect_feedback")
		self.addCleanup(
			lambda: frappe.db.set_value(
				"AI Agent Configuration", self.config, "collect_feedback", self.original
			)
		)

	def _surface(self):
		from one_bpmn.api.agent_invocation import get_agent_surface

		frappe.clear_cache(doctype="AI Agent Configuration")
		return get_agent_surface(AGENT)

	def test_feedback_is_collected_by_default(self):
		frappe.db.set_value("AI Agent Configuration", self.config, "collect_feedback", 1)
		self.assertIs(self._surface()["collect_feedback"], True)

	def test_an_agent_can_be_told_not_to_collect_feedback(self):
		frappe.db.set_value("AI Agent Configuration", self.config, "collect_feedback", 0)
		self.assertIs(self._surface()["collect_feedback"], False)

	def test_the_surface_still_carries_everything_the_panel_already_used(self):
		"""collect_feedback is additive; the panel reads this dict for six other
		things and none of them may go missing."""
		surface = self._surface()
		for key in ("agent_id", "label", "greeting", "composer_placeholder", "surface_type", "artifact_type"):
			self.assertIn(key, surface)
