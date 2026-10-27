"""Tests for the AMP conversation endpoints in :mod:`one_bpmn.api.todo_actions`.

Covers ``get_amp_thread``, ``post_amp_reply`` and ``post_amp_note`` with an
HD Ticket as the context document (the only configuration tested), and the
guard that keeps a conversation token out of ``handle_amp_action``.

The task configuration is a fixture: ``notifyConversation`` is placed in the
instance's serialized spec, as the endpoints read it. The BPMN instance row,
the Helpdesk agent check and the secret are patched; the HD Ticket,
Communication and HD Ticket Comment are real, so the HD Ticket tests skip on a
site without Helpdesk installed.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_conversation_endpoints
"""

from __future__ import annotations

import inspect
import json
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

_TEST_SECRET = "test-secret-key-for-unit-tests"
_TASK_ID = "task-uuid"
_BPMN_ID = "Task_1"
_INSTANCE = "INST-CONV-001"
_USER = "agent@test.com"


_BOTH_COMPLETE = {"actions": [{"key": "reply", "completesWith": "Resolve"}, {"key": "note", "completesWith": "Resolve"}]}


def _mock_secret():
	return patch("one_bpmn.utils.token._get_secret", return_value=_TEST_SECRET)


def _setup_request(method="POST"):
	frappe.local.request = MagicMock()
	frappe.local.request.method = method
	frappe.local.request.headers = {"Origin": "https://mail.google.com"}
	frappe.local.request.args = {}
	frappe.local.response.headers = {}
	frappe.local.response.http_status_code = None


def _token(kind: str = "reply", expiry_hours: int = 72) -> str:
	with _mock_secret():
		from one_bpmn.utils.token import generate_conversation_token

		return generate_conversation_token(_INSTANCE, _TASK_ID, _USER, kind, expiry_hours)


def _expired_token(kind: str = "reply") -> str:
	import base64

	with _mock_secret():
		from one_bpmn.utils.token import _sign

		payload = {
			"expires": int(time.time()) - 3600,
			"instance_name": _INSTANCE,
			"task_id": _TASK_ID,
			"type": kind,
			"user": _USER,
		}
		payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
		encoded = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
		return f"{encoded}.{_sign(payload_json)}"


def _raw(fn):
	"""The endpoint without its rate limiter, so tests do not touch the cache."""
	return inspect.unwrap(fn)


class TestConversationToken(FrappeTestCase):
	def test_payload_carries_type_and_no_action(self):
		from one_bpmn.utils.token import verify_action_token

		for kind in ("thread", "reply", "note"):
			with _mock_secret():
				payload = verify_action_token(_token(kind))
			self.assertEqual(payload["type"], kind)
			self.assertEqual(payload["instance_name"], _INSTANCE)
			self.assertEqual(payload["task_id"], _TASK_ID)
			self.assertEqual(payload["user"], _USER)
			self.assertNotIn("action", payload)

	def test_unknown_kind_refused(self):
		from one_bpmn.utils.token import generate_conversation_token

		with _mock_secret():
			with self.assertRaises(ValueError):
				generate_conversation_token(_INSTANCE, _TASK_ID, _USER, "approve")


class TestConversationTokenRefusedByActionEndpoint(FrappeTestCase):
	def test_conversation_token_refused_by_handle_amp_action(self):
		"""AC9: a reply token can never complete the task with an action."""
		from one_bpmn.api.todo_actions import handle_amp_action

		for kind in ("thread", "reply", "note"):
			_setup_request()
			with _mock_secret(), patch("one_bpmn.api.instance_api.complete_task") as mock_ct:
				result = handle_amp_action(token=_token(kind))
			self.assertEqual(frappe.local.response.http_status_code, 403)
			self.assertIn("error", result)
			mock_ct.assert_not_called()

	def test_post_endpoints_are_rate_limited(self):
		from one_bpmn.api.todo_actions import post_amp_note, post_amp_reply

		for fn in (post_amp_reply, post_amp_note):
			self.assertTrue(hasattr(fn, "__wrapped__"), f"{fn.__name__} has no rate limiter")


class TestConversationEndpoints(FrappeTestCase):
	"""HD Ticket as the context document."""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("DocType", "HD Ticket"):
			self.skipTest("Helpdesk (HD Ticket) is not installed on this site")
		values = {
			"doctype": "HD Ticket",
			"subject": "Conversation endpoint test",
			"raised_by": "customer@example.com",
			"description": "My printer is on fire.",
		}
		# Sites add mandatory custom fields to HD Ticket (e.g. a category):
		# fill whatever is required with an existing value.
		for df in frappe.get_meta("HD Ticket").fields:
			if df.fieldname == "status":
				continue  # HD Ticket sets its own status
			if not df.reqd or values.get(df.fieldname) or df.default or df.hidden or df.read_only:
				continue
			choices = [o for o in (df.options or "").split("\n") if o.strip()]
			if df.fieldtype in ("Link", "Select") and len(choices) > 1:
				values[df.fieldname] = "Open" if "Open" in choices else choices[0]
			elif df.fieldtype == "Link":
				values[df.fieldname] = frappe.db.get_value(df.options, {}, "name")
				if not values[df.fieldname]:
					self.skipTest(f"No {df.options} record to fill mandatory {df.fieldname}")
			elif df.fieldtype == "Select":
				values[df.fieldname] = choices[0] if choices else None
			elif df.fieldtype in ("Int", "Float", "Currency", "Check"):
				values[df.fieldname] = 1
			elif df.fieldtype in ("Data", "Small Text", "Text", "Long Text", "Text Editor"):
				values[df.fieldname] = "Test"
		try:
			# after_insert runs the site's ticket automation (assignment, SLA,
			# notifications), which is not what these tests exercise.
			ticket = frappe.get_doc(values)
			with patch.object(type(ticket), "after_insert", create=True):
				self.ticket = ticket.insert(ignore_permissions=True)
		except Exception as e:
			import traceback

			frames = [f"{f.filename.split('apps/')[-1]}:{f.lineno}:{f.name}" for f in traceback.extract_tb(e.__traceback__)]
			self.fail(f"HD Ticket fixture failed with {values}: " + " | ".join(frames[:8]))
		self.addCleanup(self._remove_ticket)

	def _remove_ticket(self):
		frappe.db.rollback()

	# -- fixtures ---------------------------------------------------------

	def _instance(self, conv: dict | None):
		spec = {"user_task_extensions": {_BPMN_ID: {"notifyConversation": conv or {}}}}
		state = {"tasks": {_TASK_ID: {"task_spec": _BPMN_ID}}}
		return frappe._dict(
			context_doctype="HD Ticket",
			context_docname=self.ticket.name,
			serialized_spec=json.dumps(spec),
			workflow_state=json.dumps(state),
		)

	def _call(self, fn, token, text=None, conv=None, agent=True, handled=None):
		"""Call an endpoint. Returns ``(result, complete_task mock)``."""
		_setup_request("GET" if fn.__name__ == "get_amp_thread" else "POST")
		kwargs = {"token": token}
		if text is not None:
			kwargs["text"] = text
		with ExitStack() as stack:
			stack.enter_context(_mock_secret())
			stack.enter_context(patch.object(frappe, "set_user"))
			stack.enter_context(
				patch("one_bpmn.api.todo_actions._get_instance_context", return_value=self._instance(conv))
			)
			stack.enter_context(patch("one_bpmn.api.todo_actions._is_helpdesk_agent", return_value=agent))
			stack.enter_context(
				patch("one_bpmn.api.todo_actions._handled_by_message", return_value=handled)
			)
			# The sandbox has no outgoing email account; the Communication is still
			# created, only the actual send is stubbed.
			stack.enter_context(patch.object(frappe, "sendmail"))
			mock_ct = stack.enter_context(patch("one_bpmn.api.instance_api.complete_task"))
			result = _raw(fn)(**kwargs)
		return result, mock_ct

	def _status(self):
		return frappe.local.response.http_status_code

	def _communications(self):
		return frappe.db.count(
			"Communication", {"reference_doctype": "HD Ticket", "reference_name": self.ticket.name}
		)

	def _comments(self):
		return frappe.db.count("HD Ticket Comment", {"reference_ticket": self.ticket.name})

	def _add_communication(self, content="<p>Hello <b>there</b></p>"):
		frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"sender": "customer@example.com",
				"subject": "Hi",
				"content": content,
				"reference_doctype": "HD Ticket",
				"reference_name": self.ticket.name,
			}
		).insert(ignore_permissions=True)

	def _add_comment(self, content="Internal only"):
		frappe.get_doc(
			{"doctype": "HD Ticket Comment", "reference_ticket": self.ticket.name, "content": content}
		).insert(ignore_permissions=True)

	# -- thread (AC1) -----------------------------------------------------

	def test_thread_without_notes(self):
		from one_bpmn.api.todo_actions import get_amp_thread

		self._add_communication()
		self._add_comment()

		result, _ = self._call(get_amp_thread, _token("thread"), conv={"internalNotes": False})

		items = result["items"]
		self.assertTrue(items)
		self.assertTrue(all(i["is_note"] is False for i in items))
		self.assertIn("Hello there", [i["message"] for i in items])
		self.assertEqual(set(items[0]), {"who", "message", "time", "is_note"})
		# AMP CORS headers were set.
		self.assertIn("Access-Control-Expose-Headers", frappe.flags._amp_extra_headers)

	def test_thread_with_notes_oldest_first(self):
		from one_bpmn.api.todo_actions import get_amp_thread

		self._add_communication()
		self._add_comment("Internal only")

		result, _ = self._call(get_amp_thread, _token("thread"), conv={"internalNotes": True})

		items = result["items"]
		notes = [i for i in items if i["is_note"]]
		self.assertEqual([n["message"] for n in notes], ["Internal only"])
		self.assertFalse(items[0]["is_note"])
		self.assertTrue(items[-1]["is_note"])

	def test_thread_limited_to_latest_ten(self):
		from one_bpmn.api.todo_actions import get_amp_thread

		for i in range(12):
			self._add_communication(f"<p>Message {i}</p>")

		result, _ = self._call(get_amp_thread, _token("thread"), conv={})

		messages = [i["message"] for i in result["items"]]
		self.assertEqual(len(messages), 10)
		self.assertEqual(messages[-1], "Message 11")
		self.assertNotIn("Message 0", messages)

	# -- reply (AC2, AC4) -------------------------------------------------

	def test_reply_creates_communication(self):
		from one_bpmn.api.todo_actions import post_amp_reply

		self._add_communication()
		before = self._communications()
		result, mock_ct = self._call(post_amp_reply, _token("reply"), "We are on it.", conv={})
		self.assertNotIn("error", result, str(result)[:600])

		self.assertEqual(self._communications(), before + 1)
		self.assertIn("We are on it.", result["message"])
		self.assertEqual(frappe.db.get_value("HD Ticket", self.ticket.name, "status"), "Replied")
		# Completes task is off: the task stays open.
		mock_ct.assert_not_called()
		self.assertFalse(result["completed"])

	def test_reply_is_addressed_to_the_customer(self):
		from one_bpmn.api.todo_actions import post_amp_reply

		self._add_communication()
		result, _ = self._call(post_amp_reply, _token("reply"), "We are on it.", conv={})
		self.assertNotIn("error", result, str(result)[:600])

		recipients = frappe.db.get_value(
			"Communication",
			{"reference_doctype": "HD Ticket", "reference_name": self.ticket.name, "sent_or_received": "Sent"},
			"recipients",
		)
		self.assertEqual(recipients, "customer@example.com")

	def test_reply_completes_task_when_configured(self):
		from one_bpmn.api.todo_actions import post_amp_reply

		self._add_communication()
		conv = {"actions": [{"key": "reply", "completesWith": "Resolve"}, {"key": "note", "completesWith": ""}]}
		result, mock_ct = self._call(post_amp_reply, _token("reply"), "Fixed it.", conv=conv)
		self.assertNotIn("error", result, str(result)[:600])

		mock_ct.assert_called_once()
		kwargs = mock_ct.call_args.kwargs
		self.assertEqual(kwargs["instance_name"], _INSTANCE)
		self.assertEqual(kwargs["task_id"], _TASK_ID)
		self.assertEqual(json.loads(kwargs["data"]), {"action": "Resolve", "comment": "Fixed it."})
		self.assertTrue(result["completed"])

	def test_reply_does_not_complete_when_only_note_finishes(self):
		from one_bpmn.api.todo_actions import post_amp_reply

		self._add_communication()
		conv = {"actions": [{"key": "reply", "completesWith": ""}, {"key": "note", "completesWith": "Resolve"}]}
		result, mock_ct = self._call(post_amp_reply, _token("reply"), "Still looking.", conv=conv)
		self.assertNotIn("error", result, str(result)[:600])

		mock_ct.assert_not_called()
		self.assertFalse(result["completed"])

	def test_old_completes_tick_does_not_complete(self):
		from one_bpmn.api.todo_actions import post_amp_reply

		self._add_communication()
		conv = {"actions": [{"key": "reply", "completes": True}]}
		result, mock_ct = self._call(post_amp_reply, _token("reply"), "Old setting.", conv=conv)
		self.assertNotIn("error", result, str(result)[:600])

		mock_ct.assert_not_called()
		self.assertFalse(result["completed"])

	# -- note (AC3, AC4) --------------------------------------------------

	def test_note_creates_ticket_comment(self):
		from one_bpmn.api.todo_actions import post_amp_note

		before = self._comments()
		result, mock_ct = self._call(post_amp_note, _token("note"), "Called the customer.", conv={})

		self.assertEqual(self._comments(), before + 1)
		self.assertIn("Called the customer.", result["message"])
		mock_ct.assert_not_called()

	def test_note_completes_task_when_configured(self):
		from one_bpmn.api.todo_actions import post_amp_note

		conv = json.dumps({"actions": [{"key": "note", "completesWith": "Reviewed"}]})  # JSON string form
		result, mock_ct = self._call(post_amp_note, _token("note"), "Done.", conv=conv)

		mock_ct.assert_called_once()
		self.assertEqual(json.loads(mock_ct.call_args.kwargs["data"]), {"action": "Reviewed", "comment": "Done."})

	# -- refusals (AC5-AC8) -----------------------------------------------

	def test_empty_text_is_400_and_creates_nothing(self):
		from one_bpmn.api.todo_actions import post_amp_note, post_amp_reply

		comms, comments = self._communications(), self._comments()
		for fn, kind in ((post_amp_reply, "reply"), (post_amp_note, "note")):
			result, mock_ct = self._call(fn, _token(kind), "   ", conv=_BOTH_COMPLETE)
			self.assertEqual(self._status(), 400)
			self.assertEqual(result["error"], "Write a message first.")
			mock_ct.assert_not_called()
		self.assertEqual(self._communications(), comms)
		self.assertEqual(self._comments(), comments)

	def test_expired_token_is_403_and_creates_nothing(self):
		from one_bpmn.api.todo_actions import post_amp_reply

		comms = self._communications()
		result, mock_ct = self._call(post_amp_reply, _expired_token("reply"), "Hello")

		self.assertEqual(self._status(), 403)
		self.assertIn("error", result)
		self.assertEqual(self._communications(), comms)
		mock_ct.assert_not_called()

	def test_tampered_token_is_403(self):
		from one_bpmn.api.todo_actions import post_amp_note

		comments = self._comments()
		result, _ = self._call(post_amp_note, "tampered.XXXX", "Hello")

		self.assertEqual(self._status(), 403)
		self.assertEqual(self._comments(), comments)

	def test_token_of_wrong_kind_is_403(self):
		from one_bpmn.api.todo_actions import get_amp_thread, post_amp_note

		comments = self._comments()
		result, _ = self._call(post_amp_note, _token("reply"), "Hello")
		self.assertEqual(self._status(), 403)
		self.assertEqual(self._comments(), comments)

		result, _ = self._call(get_amp_thread, _token("note"))
		self.assertEqual(self._status(), 403)

	def test_non_agent_is_403_and_creates_nothing(self):
		from one_bpmn.api.todo_actions import post_amp_note, post_amp_reply

		comms, comments = self._communications(), self._comments()
		for fn, kind in ((post_amp_reply, "reply"), (post_amp_note, "note")):
			result, mock_ct = self._call(fn, _token(kind), "Hello", agent=False, conv=_BOTH_COMPLETE)
			self.assertEqual(self._status(), 403)
			self.assertIn("Permission denied", result["error"])
			mock_ct.assert_not_called()
		self.assertEqual(self._communications(), comms)
		self.assertEqual(self._comments(), comments)

	def test_task_not_waiting_says_who_handled_it(self):
		from one_bpmn.api.todo_actions import post_amp_note, post_amp_reply

		comms, comments = self._communications(), self._comments()
		for fn, kind in ((post_amp_reply, "reply"), (post_amp_note, "note")):
			result, mock_ct = self._call(
				fn, _token(kind), "Hello", handled="This task was already handled by Jane Doe."
			)
			self.assertIn("Jane Doe", result["message"])
			mock_ct.assert_not_called()
		self.assertEqual(self._communications(), comms)
		self.assertEqual(self._comments(), comments)

	def test_handled_by_message_reads_the_active_task_row(self):
		from one_bpmn.api.todo_actions import _handled_by_message

		with patch.object(frappe.db, "get_value") as gv:
			gv.return_value = frappe._dict(status="Waiting", assigned_user="Administrator")
			self.assertIsNone(_handled_by_message(_INSTANCE, _TASK_ID))

			gv.return_value = frappe._dict(status="Completed", assigned_user="Administrator")
			self.assertIn("already handled by", _handled_by_message(_INSTANCE, _TASK_ID))

			gv.return_value = None
			self.assertIn("already handled", _handled_by_message(_INSTANCE, _TASK_ID))
