# Copyright (c) 2026, one-fm and contributors
"""Docu saves a Form View client script only after the safety gate passes, for people the Docu Agent admits."""

import json
from types import SimpleNamespace
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agui_contract.translators import _script_diff
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.api.docu_api import apply_client_script, preview_client_script
from one_bpmn.one_bpmn.patches.v1_0 import docu_edits_field_properties as previous
from one_bpmn.one_bpmn.patches.v1_0 import docu_writes_form_client_scripts as patch
from one_bpmn.security.client_script_validator import validate_form_script

DT = "Note"
SCRIPT = 'frappe.ui.form.on("Note", {\n\tpublic(frm) {\n\t\tfrm.toggle_reqd("content", frm.doc.public);\n\t},\n});\n'


def _script_names():
	return frappe.get_all("Client Script", filters={"dt": DT, "view": "Form"}, pluck="name")


class TestFormScriptValidator(FrappeTestCase):
	def test_a_script_for_the_form_passes(self):
		self.assertEqual(validate_form_script(DT, SCRIPT), [])

	def test_each_forbidden_construct_is_refused(self):
		for body in ("eval(frm.doc.title)", "fetch('/x')", "cur_frm.reload_doc()", "console.log(frm.doc)"):
			script = f'frappe.ui.form.on("Note", {{ refresh(frm) {{ {body}; }} }});'
			with self.subTest(body=body):
				self.assertEqual(len(validate_form_script(DT, script)), 1)

	def test_a_script_for_another_form_is_refused(self):
		script = SCRIPT.replace('"Note"', '"ToDo"')
		self.assertIn("frappe.ui.form.on", validate_form_script(DT, script)[0])

	def test_a_field_the_form_does_not_have_is_refused(self):
		script = SCRIPT.replace('"content"', '"no_such_field"')
		self.assertIn("no_such_field", validate_form_script(DT, script)[0])

	def test_an_empty_script_is_refused(self):
		self.assertEqual(len(validate_form_script(DT, "  ")), 1)


class TestApplyClientScript(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("docu_form_script")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="docu_form_script")
		frappe.clear_cache(doctype=DT)

	def test_a_new_script_is_created_as_an_enabled_form_script(self):
		message = apply_client_script(DT, SCRIPT)

		row = frappe.db.get_value("Client Script", f"{DT}-Form", ["dt", "view", "enabled", "script"], as_dict=True)
		self.assertEqual((row.dt, row.view, row.enabled), (DT, "Form", 1))
		self.assertEqual(row.script, SCRIPT)
		self.assertIn("created", message)

	def test_a_second_apply_updates_the_same_row(self):
		apply_client_script(DT, SCRIPT)
		changed = SCRIPT.replace("frm.doc.public", "!frm.doc.public")

		message = apply_client_script(DT, changed)

		self.assertEqual(_script_names(), [f"{DT}-Form"])
		self.assertEqual(frappe.db.get_value("Client Script", f"{DT}-Form", "script"), changed)
		self.assertIn("updated", message)

	def test_a_script_that_fails_the_gate_saves_nothing(self):
		with self.assertRaises(frappe.ValidationError):
			apply_client_script(DT, SCRIPT.replace("frm.toggle_reqd", "eval"))

		self.assertEqual(_script_names(), [])

	def test_a_person_the_agent_does_not_admit_is_refused(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			apply_client_script(DT, SCRIPT)

		frappe.set_user("Administrator")
		self.assertEqual(_script_names(), [])

	def test_preview_diffs_against_the_saved_script_and_writes_nothing(self):
		self.assertFalse(preview_client_script(DT, SCRIPT)["exists"])
		apply_client_script(DT, SCRIPT)

		preview = preview_client_script(DT, SCRIPT.replace("frm.doc.public", "!frm.doc.public"))

		self.assertTrue(preview["exists"])
		self.assertIn('+\t\tfrm.toggle_reqd("content", !frm.doc.public);', preview["diff"])


class TestRoutingPatchChain(FrappeTestCase):
	def test_each_replacement_anchor_is_in_what_the_previous_patch_left(self):
		self.assertIn(patch.ACCEPT_OLD, previous.ACCEPT_NEW)
		self.assertIn(patch.ROUTE_OLD, previous.ROUTE_NEW)
		self.assertIn(patch.SYSTEM_OLD, previous.SYSTEM_NEW)
		self.assertIn(patch.ENUM_OLD, previous.ENUM_NEW)

	def test_the_patch_is_a_no_op_on_a_site_without_docu(self):
		if frappe.db.exists("AI Agent Configuration", {"agent_id": patch.AGENT_ID}):
			self.skipTest("this site has Docu")
		patch.execute()


CONVERSATION = "_test_docu_edit_client_script"
REQUEST = "When a note is made public, make its content mandatory"


class _Adapter:
	def __init__(self, *replies):
		self.replies = list(replies)
		self.calls = 0

	async def complete(self, **kwargs):
		self.calls += 1
		return SimpleNamespace(text=json.dumps(self.replies.pop(0)))


def _run_stage(replies, doctype=DT):
	set_turn(CONVERSATION, {"user_text": REQUEST, "doctype": doctype})
	adapter = _Adapter(*replies)
	with mock_patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter):
		exec(patch.STAGE_SCRIPT_BODY, {"frappe": frappe, "context_docname": CONVERSATION, "result": {}})
	return get_turn(CONVERSATION)["output"], adapter


class TestEditClientScriptStage(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("docu_form_script_stage")

	def tearDown(self):
		frappe.db.rollback(save_point="docu_form_script_stage")
		clear_turn(CONVERSATION)

	def test_a_clear_request_proposes_the_script_and_saves_nothing(self):
		output, _ = _run_stage([{"script": SCRIPT.strip(), "summary": "Content becomes mandatory."}])

		self.assertEqual((output["intent"], output["mode"]), ("EDIT_CLIENT_SCRIPT", "CREATE"))
		self.assertEqual(output["modified_script"], SCRIPT)
		self.assertEqual(output["apply_target"], DT)
		self.assertIn("press Apply", output["response"])
		self.assertEqual(_script_names(), [])

	def test_an_existing_script_is_proposed_as_a_modify_with_a_diff(self):
		apply_client_script(DT, SCRIPT)
		changed = SCRIPT.replace("frm.doc.public", "!frm.doc.public")

		output, _ = _run_stage([{"script": changed.strip(), "summary": "Reversed."}])

		self.assertEqual(output["mode"], "MODIFY")
		self.assertEqual(output["diff"][0]["type"], "changed")

	def test_an_unclear_request_asks_one_question_with_options(self):
		output, _ = _run_stage([{"question": "Which field?", "options": ["Content", "Title"]}])

		self.assertEqual(output["intent"], "DISAMBIGUATE")
		self.assertEqual(output["options"], ["Content", "Title"])
		self.assertIsNone(output["modified_script"])

	def test_an_unsafe_script_is_retried_once_then_refused(self):
		unsafe = {"script": SCRIPT.replace("frm.toggle_reqd", "eval")}

		output, adapter = _run_stage([unsafe, unsafe])

		self.assertEqual(adapter.calls, 2)
		self.assertIsNone(output["modified_script"])
		self.assertIn("could not write a safe script", output["response"])

	def test_no_selected_form_asks_which_form(self):
		output, adapter = _run_stage([], doctype="")

		self.assertEqual(adapter.calls, 0)
		self.assertIn("Which form", output["response"])


class TestScriptDiffEvent(FrappeTestCase):
	def test_the_stage_output_becomes_an_apply_target_script_card(self):
		(event,) = list(
			_script_diff(
				{"intent": "EDIT_CLIENT_SCRIPT", "mode": "MODIFY", "modified_script": SCRIPT, "apply_target": DT}
			)
		)

		self.assertEqual(event.value["mode"], "MODIFY")
		self.assertEqual(event.value["apply_target"], DT)

	def test_a_question_reply_makes_no_card(self):
		self.assertEqual(list(_script_diff({"intent": "DISAMBIGUATE", "mode": "CREATE"})), [])


class TestPatchAddsTheStage(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Process Model", patch.MAP) or not frappe.db.exists("Server Script", patch.CLASSIFY):
			self.skipTest("this site has no Docu map")
		try:
			frappe.get_doc("AI Agent Configuration", {"agent_id": patch.AGENT_ID}).validate()
		except frappe.ValidationError:
			self.skipTest("the Docu configuration on this site does not validate")
		frappe.db.savepoint("docu_form_script_patch")

	def tearDown(self):
		frappe.db.rollback(save_point="docu_form_script_patch")

	def test_the_stage_is_on_the_map_before_the_classifier_routes_to_it(self):
		patch.execute()
		patch.execute()

		xml = frappe.db.get_value("BPMN Process Model", patch.MAP, "bpmn_xml")
		self.assertEqual(xml.count(f'id="{patch.STAGE}"'), 1)
		self.assertTrue(frappe.db.exists("Server Script", patch.STAGE_SCRIPT))
		self.assertIn(patch.ROUTE_NEW, frappe.db.get_value("Server Script", patch.CLASSIFY, "script"))
