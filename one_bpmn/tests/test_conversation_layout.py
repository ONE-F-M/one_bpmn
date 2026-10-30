# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Conversation layout: the HD Ticket thread, saved replies, Reply, Add Note and task actions in the email."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.api.todo_actions import thread_items
from one_bpmn.email_builder import composer
from one_bpmn.email_builder.renderer import render_layout_amp, render_layout_html
from one_bpmn.tests.test_amp_validation import _validate_amp4email
from one_bpmn.tests.test_conversation_endpoints import _mock_secret, make_hd_ticket

AGENT = "agent@test.com"
CONV = {
	"actions": [{"key": "reply", "label": "Reply"}, {"key": "note", "label": "Add Note"}],
	"internalNotes": True,
	"canned": ["Card printed"],
}
RESOLVE = {
	"key": "resolve",
	"label": {"en": "Resolve", "ar": "حل"},
	"primary": True,
	"confirm": False,
	"sign": False,
	"reason": False,
	"state": "",
	"style": "",
	"url": "",
	"token": "tok-resolve",
}


class TestConversationLayout(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("DocType", "HD Ticket"):
			self.skipTest("Helpdesk (HD Ticket) is not installed on this site")
		self.ticket = make_hd_ticket(self)

	def _comm(self, content, owner):
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"reference_doctype": "HD Ticket",
				"reference_name": self.ticket.name,
				"sender": "customer@example.com",
				"content": content,
				"owner": owner,
			}
		).insert(ignore_permissions=True)

	def _ctx(self, task_cfg):
		clear_cache()
		instance = frappe._dict(
			name="INST-CONV-L",
			doctype="BPMN Process Instance",
			context_doctype="HD Ticket",
			context_docname=self.ticket.name,
		)
		real_get_all = frappe.get_all

		def get_all(doctype, *args, **kwargs):
			if doctype == "HD Saved Reply":
				return [
					frappe._dict(
						name="Card printed",
						title="Card printed",
						message="<p>The new card is printed.</p><p>It reaches the site by 9.</p>",
					)
				]
			return real_get_all(doctype, *args, **kwargs)

		with (
			_mock_secret(),
			patch.object(composer, "_build_layout_actions", return_value=[dict(RESOLVE)]),
			patch.object(composer.frappe, "get_all", side_effect=get_all),
			patch("one_bpmn.utils.translation.translate_cached", side_effect=lambda text: text),
		):
			return composer._build_layout_context(
				instance, AGENT, "Review the Ticket", "task-1", "review", task_cfg
			)

	def test_chat_on_a_ticket_builds_the_conversation(self):
		self._comm("My printer is on fire.", "Administrator")
		ctx = self._ctx({"notifyLayout": "chat", "notifyConversation": json.dumps(CONV)})

		self.assertEqual(ctx["layout"], "conversation")
		self.assertEqual(ctx["kick"]["en"], f"Helpdesk · Ticket {self.ticket.name}")
		self.assertEqual(ctx["question"]["en"], self.ticket.subject)
		self.assertIn("get_amp_thread?token=", ctx["thread_url"])
		self.assertEqual([c["key"] for c in ctx["conv_actions"]], ["reply", "note"])
		self.assertTrue(ctx["conv_actions"][0]["endpoint"].endswith("post_amp_reply"))
		self.assertEqual(
			ctx["saved_replies"],
			[{"title": "Card printed", "message": "The new card is printed.\nIt reaches the site by 9."}],
		)
		self.assertEqual(ctx["thread"][-1]["message"], "My printer is on fire.")

	def test_chat_on_a_doctype_without_a_thread_sends_the_card(self):
		instance = frappe._dict(
			name="INST-T", doctype="BPMN Process Instance", context_doctype="ToDo", context_docname=""
		)
		with (
			patch.object(composer, "_build_layout_actions", return_value=[]),
			patch("one_bpmn.email_builder.fields.build_kick", return_value={"en": "k", "ar": "k"}),
			patch.object(composer.frappe, "log_error") as log_error,
		):
			ctx = composer._build_layout_context(
				instance, AGENT, "Review", "t", "review", {"notifyLayout": "chat"}
			)

		self.assertEqual(ctx["layout"], "decision_card")
		self.assertIn("Decision card", log_error.call_args.kwargs["message"])

	def test_thread_items_mark_the_users_own_messages(self):
		self._comm("Customer message", "Administrator")
		self._comm("Agent answer", AGENT)
		frappe.db.set_value("Communication", {"content": "Agent answer"}, "owner", AGENT)
		items = thread_items("HD Ticket", self.ticket.name, {}, AGENT)
		mine = {item["message"]: item["is_mine"] for item in items}
		self.assertEqual(mine, {"Customer message": False, "Agent answer": True})

	def test_amp_renders_the_thread_saved_replies_and_forms_and_validates(self):
		self._comm("My printer is on fire.", "Administrator")
		ctx = self._ctx({"notifyLayout": "chat", "notifyConversation": json.dumps(CONV)})
		with_status = render_layout_amp(ctx)
		_validate_amp4email(with_status, "conversation_status")
		_validate_amp4email(render_layout_amp({**ctx, "status_url": ""}), "conversation_plain")

		# The thread list sits before the status list, never inside it
		self.assertLess(
			with_status.index('<amp-list class="thread-list"'), with_status.index("<amp-list src=")
		)
		self.assertEqual(with_status.count('<amp-list class="thread-list"'), 2)
		self.assertIn("ردود جاهزة", with_status)
		self.assertIn("Card printed</button>", with_status)
		self.assertIn("The new card is printed.\\nIt reaches the site by 9.", with_status)
		self.assertIn("post_amp_reply", with_status)
		self.assertIn("post_amp_note", with_status)
		self.assertIn('value="tok-resolve"', with_status)
		self.assertIn("Replies from this email have expired.", with_status)
		self.assertIn("Open ticket in Helpdesk", with_status)

	def test_html_part_is_a_transcript_with_a_helpdesk_link(self):
		self._comm("My printer is on fire.", "Administrator")
		ctx = self._ctx({"notifyLayout": "chat", "notifyConversation": json.dumps(CONV)})
		html = render_layout_html(ctx)

		self.assertNotIn("<form", html)
		self.assertIn('<span class="mtext">My printer is on fire.</span>', html)
		self.assertIn(f'href="{ctx["open_link"]}" target="_blank">Open ticket in Helpdesk</a>', html)
