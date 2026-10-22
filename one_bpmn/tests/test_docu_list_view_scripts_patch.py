# Copyright (c) 2026, one-fm and contributors
"""Docu drafts a list script, asks for a yes, and applies it only after the person confirms.

The stage runs the patch's script body, so these tests need no Docu map on the site; only the model reply is faked.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import docu_writes_list_view_scripts as fix
from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

CONVERSATION = "_test_docu_list_view_script"
SCRIPT = 'frappe.listview_settings["Note"] = { add_fields: ["public"], hide_name_column: true };'
REQUEST = "hide the ID column in the Note list"
PENDING = {"doctype": "Note", "script": SCRIPT, "request": REQUEST}
NO_ROLE_USER = "docu-list-stage-probe@example.com"

# The shape of the live Classify Intent script around the three anchors.
CLASSIFY = (
	'_small_talk = True\n'
	'turn = {"session_state": STATE}\n'
	'intent = "SMALL_TALK" if _small_talk else ""\n'
	'if intent not in ("CREATE", "MODIFY", "EDIT_FIELD_PROPERTY", "DISAMBIGUATE") and intent not in _cheap_intents:\n'
	"    pass\n"
	'nxt = {"DISAMBIGUATE": "clarify", "EDIT_FIELD_PROPERTY": "edit_field_property"}.get(intent, "write_schema")\n'
)


class _Adapter:
	def __init__(self, reply):
		self.reply = reply

	async def complete(self, **kwargs):
		return SimpleNamespace(text=json.dumps(self.reply))


def _run_stage(message, reply=None, pending=None, doctype="Note"):
	state = {"pending_list_script": pending} if pending else {}
	set_turn(CONVERSATION, {"user_text": message, "doctype": doctype, "session_state": state})
	recorded = []
	with (
		patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=_Adapter(reply or {})),
		patch("one_bpmn.agents.memory.session_state.record", side_effect=lambda _c, values: recorded.append(values)),
	):
		exec(fix.WRITE_SCRIPT_BODY, {"frappe": frappe, "context_docname": CONVERSATION, "result": {}})
	return get_turn(CONVERSATION)["output"], recorded


def _list_script():
	return frappe.db.get_value("Client Script", {"dt": "Note", "view": "List"}, "script")


class TestWriteListScriptStage(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("write_list_script")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="write_list_script")
		clear_turn(CONVERSATION)

	def test_a_request_is_drafted_and_held_until_confirmed(self):
		output, recorded = _run_stage(REQUEST, {"doctype": "Note", "script": SCRIPT, "summary": "The ID column is hidden."})
		self.assertEqual(recorded[0]["pending_list_script"]["script"], SCRIPT)
		self.assertIn("Shall I apply it to the Note list?", output["response"])
		self.assertEqual(output["options"], ["Yes, apply it", "No, cancel"])
		self.assertIsNone(_list_script())

	def test_a_yes_applies_the_pending_script(self):
		output, recorded = _run_stage("yes, go ahead", pending=PENDING)
		self.assertEqual(_list_script(), SCRIPT)
		self.assertIn("I created the list script on Note", output["response"])
		self.assertEqual(recorded, [{"pending_list_script": None}])

	def test_a_no_drops_the_pending_script(self):
		output, recorded = _run_stage("no, cancel", pending=PENDING)
		self.assertIsNone(_list_script())
		self.assertIn("I have not changed the list on Note", output["response"])
		self.assertEqual(recorded, [{"pending_list_script": None}])

	def test_a_change_request_redrafts_from_the_pending_request(self):
		changed = SCRIPT.replace("hide_name_column: true", "hide_name_column: false")
		output, recorded = _run_stage("keep the ID column", {"doctype": "Note", "script": changed}, pending=PENDING)
		self.assertEqual(recorded[0]["pending_list_script"]["script"], changed)
		self.assertIn(changed, output["response"])
		self.assertIsNone(_list_script())

	def test_an_unsafe_draft_is_refused_and_not_held(self):
		unsafe = SCRIPT + '\nfetch("/api/method/x")'
		output, recorded = _run_stage(REQUEST, {"doctype": "Note", "script": unsafe})
		self.assertIn("I could not use that script", output["response"])
		self.assertEqual(recorded, [])

	def test_a_question_from_the_writer_is_passed_on(self):
		output, recorded = _run_stage(
			"make it nicer", {"doctype": "Note", "script": "", "question": "Which column should change?"}
		)
		self.assertEqual(output["response"], "Which column should change?")
		self.assertEqual(recorded, [])

	def test_an_existing_script_is_said_to_be_replaced(self):
		frappe.get_doc(
			{"doctype": "Client Script", "__newname": "Note-List", "dt": "Note", "view": "List", "script": SCRIPT, "enabled": 1}
		).insert(ignore_permissions=True)
		output, _recorded = _run_stage(REQUEST, {"doctype": "Note", "script": SCRIPT})
		self.assertIn("This replaces the list script on Note.", output["response"])

	def test_a_user_without_the_role_changes_nothing(self):
		if not frappe.db.exists("User", NO_ROLE_USER):
			frappe.get_doc({"doctype": "User", "email": NO_ROLE_USER, "first_name": "Probe", "send_welcome_email": 0}).insert(
				ignore_permissions=True
			)
		frappe.set_user(NO_ROLE_USER)
		output, _recorded = _run_stage("yes", pending=PENDING)
		self.assertIn("not allowed", output["response"])
		frappe.set_user("Administrator")
		self.assertIsNone(_list_script())


class TestClassifierEdits(FrappeTestCase):
	def _edited(self):
		script = CLASSIFY
		for anchor, replacement in (
			(fix.ACCEPT_OLD, fix.ACCEPT_NEW),
			(fix.ROUTE_OLD, fix.ROUTE_NEW),
			(fix.PENDING_OLD, fix.PENDING_NEW),
		):
			script = apply_edit(script, anchor, replacement)
		return script

	def _run(self, state):
		scope = {"STATE": state, "_cheap_intents": ("SMALL_TALK", "OFF_TOPIC")}
		exec(self._edited(), scope)
		return scope["intent"], scope["nxt"]

	def test_a_reply_with_a_pending_draft_goes_to_the_list_script_stage(self):
		self.assertEqual(self._run({"pending_list_script": PENDING}), ("LIST_VIEW_SCRIPT", "write_list_script"))

	def test_a_greeting_with_no_pending_draft_stays_small_talk(self):
		self.assertEqual(self._run({})[0], "SMALL_TALK")

	def test_the_edits_apply_once(self):
		once = self._edited()
		self.assertEqual(once.count("write_list_script"), 1)
		for anchor, replacement in ((fix.ROUTE_OLD, fix.ROUTE_NEW), (fix.PENDING_OLD, fix.PENDING_NEW)):
			self.assertEqual(apply_edit(once, anchor, replacement), once)
