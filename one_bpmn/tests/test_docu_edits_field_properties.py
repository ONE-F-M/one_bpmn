# Copyright (c) 2026, one-fm and contributors
"""Docu changes a field property when asked, instead of asking what form to design.

The stage runs the patch's script body, so these tests need no Docu map on the site; only the model reply is faked.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.api.docu import apply_field_properties
from one_bpmn.one_bpmn.patches.v1_0 import docu_edits_field_properties as fix
from one_bpmn.tests.site_scripts import as_deployed

CONVERSATION = "_test_docu_edit_field_property"
PRODUCTION_MESSAGE = 'I want the Replacement coverage section to hidden unless "replacement_requires_coverage" is checked as true'
SECTION_DEPENDS_ON = [{"fieldname": "seen_by_section", "property": "depends_on", "value": "eval:doc.public"}]
CUSTOM_DT = "Docu Field Property Probe"


class _Adapter:
	def __init__(self, reply):
		self.reply = reply

	async def complete(self, **kwargs):
		return SimpleNamespace(text=json.dumps(self.reply))


def _run_stage(message, changes, doctype=""):
	set_turn(CONVERSATION, {"user_text": message, "doctype": doctype})
	with patch(
		"one_bpmn.processa_engine.agent_runtime.llm_factory.get_llm_adapter_from_settings",
		return_value=_Adapter({"changes": changes}),
	):
		exec(as_deployed(fix.EDIT_SCRIPT_BODY), {"frappe": frappe, "context_docname": CONVERSATION, "result": {}})
	return get_turn(CONVERSATION)["output"]


class TestEditFieldPropertyStage(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("edit_field_property")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="edit_field_property")
		clear_turn(CONVERSATION)
		frappe.clear_cache(doctype="Note")

	def test_the_production_message_hides_the_section_through_a_property_setter(self):
		output = _run_stage(PRODUCTION_MESSAGE, SECTION_DEPENDS_ON, doctype="Note")
		self.assertEqual(
			frappe.db.get_value("Property Setter", "Note-seen_by_section-depends_on", "value"),
			"eval:doc.public",
		)
		self.assertEqual(output["intent"], "EDIT_FIELD_PROPERTY")
		self.assertIn("shows only when Public is ticked", output["response"])

	def test_a_stored_fieldname_finds_the_form_when_none_is_selected(self):
		output = _run_stage(
			"make notify_on_every_login mandatory",
			[{"fieldname": "notify_on_every_login", "property": "reqd", "value": 1}],
		)
		self.assertEqual(
			frappe.db.get_value("Property Setter", "Note-notify_on_every_login-reqd", "value"), "1"
		)
		self.assertIn("On Note", output["response"])

	def test_an_unknown_field_changes_nothing_and_says_so(self):
		output = _run_stage(
			PRODUCTION_MESSAGE,
			[{"fieldname": "no_such_field", "property": "hidden", "value": 1}],
			doctype="Note",
		)
		self.assertIn("no field named no_such_field", output["response"])
		self.assertFalse(frappe.db.exists("Property Setter", "Note-no_such_field-hidden"))

	def test_a_user_without_system_manager_changes_nothing(self):
		frappe.set_user("Guest")
		output = _run_stage(PRODUCTION_MESSAGE, SECTION_DEPENDS_ON, doctype="Note")
		self.assertIn("not allowed to change forms", output["response"])
		self.assertFalse(frappe.db.exists("Property Setter", "Note-seen_by_section-depends_on"))


class TestCustomDocTypeIsEditedInPlace(FrappeTestCase):
	def setUp(self):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": CUSTOM_DT,
				"module": "ONE BPMN",
				"custom": 1,
				"fields": [
					{"fieldname": "needs_cover", "fieldtype": "Check", "label": "Needs Cover"},
					{"fieldname": "cover_section", "fieldtype": "Section Break", "label": "Cover"},
					{"fieldname": "cover_by", "fieldtype": "Data", "label": "Cover By"},
				],
				"permissions": [{"role": "System Manager", "read": 1, "write": 1}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		# Creating the DocType's table committed it, so the class rollback cannot remove it.
		frappe.delete_doc("DocType", CUSTOM_DT, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_the_docfield_changes_and_no_property_setter_is_written(self):
		lines = apply_field_properties(
			CUSTOM_DT,
			[{"fieldname": "cover_section", "property": "depends_on", "value": "eval:doc.needs_cover"}],
		)
		self.assertEqual(
			frappe.get_meta(CUSTOM_DT).get_field("cover_section").depends_on, "eval:doc.needs_cover"
		)
		self.assertFalse(frappe.db.exists("Property Setter", {"doc_type": CUSTOM_DT}))
		self.assertEqual(lines, ["Cover shows only when Needs Cover is ticked."])


class TestWritePermissionOnTheTarget(FrappeTestCase):
	"""The requester needs write on the DocType, and a refusal leaves it untouched."""

	WRITER = "docu-writer-probe@example.com"
	READER = "docu-reader-probe@example.com"
	CHANGE = [{"fieldname": "cover_section", "property": "depends_on", "value": "eval:doc.needs_cover"}]

	def setUp(self):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": CUSTOM_DT,
				"module": "ONE BPMN",
				"custom": 1,
				"fields": [
					{"fieldname": "needs_cover", "fieldtype": "Check", "label": "Needs Cover"},
					{"fieldname": "cover_section", "fieldtype": "Section Break", "label": "Cover"},
				],
				"permissions": [
					{"role": "System Manager", "read": 1, "write": 1},
				],
			}
		).insert(ignore_permissions=True)  # perms: test fixture
		for email, roles in ((self.WRITER, ["System Manager"]), (self.READER, [])):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": "Probe",
						"send_welcome_email": 0,
						"roles": [{"role": role} for role in roles],
					}
				).insert(ignore_permissions=True)  # perms: test fixture

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.flags.requesting_user = None
		frappe.delete_doc("DocType", CUSTOM_DT, force=True, ignore_permissions=True)  # perms: test fixture
		for email in (self.WRITER, self.READER):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)  # perms: test fixture
		frappe.db.commit()

	@staticmethod
	def _snapshot():
		fields = frappe.get_all("DocField", filters={"parent": CUSTOM_DT}, fields=["*"], order_by="idx")
		setters = frappe.get_all("Property Setter", filters={"doc_type": CUSTOM_DT}, pluck="name")
		return fields, setters

	def test_a_user_with_write_on_the_doctype_is_allowed(self):
		frappe.set_user(self.WRITER)
		apply_field_properties(CUSTOM_DT, self.CHANGE)
		self.assertEqual(frappe.get_meta(CUSTOM_DT).get_field("cover_section").depends_on, "eval:doc.needs_cover")

	@patch("one_bpmn.api.docu._may_change_forms", return_value=True)
	def test_a_user_without_write_gets_a_permission_error_and_nothing_changes(self, _gate):
		before = self._snapshot()
		frappe.set_user(self.READER)
		with self.assertRaises(frappe.PermissionError):
			apply_field_properties(CUSTOM_DT, self.CHANGE)
		frappe.set_user("Administrator")
		self.assertEqual(self._snapshot(), before)

	def test_the_requester_is_checked_when_the_session_is_the_agent(self):
		before = self._snapshot()
		frappe.flags.requesting_user = self.READER
		with self.assertRaises(frappe.PermissionError):
			apply_field_properties(CUSTOM_DT, self.CHANGE)
		self.assertEqual(self._snapshot(), before)


class TestClassifierRoutes(FrappeTestCase):
	def test_edit_field_property_is_accepted_and_routed_to_the_new_stage(self):
		scope = {"intent": "EDIT_FIELD_PROPERTY", "_cheap_intents": ()}
		exec(fix.ACCEPT_NEW + "\n    intent = 'CREATE'\n" + fix.ROUTE_NEW, scope)
		self.assertEqual(scope["nxt"], "edit_field_property")

	def test_the_classifier_prompt_gains_the_intent_before_disambiguate(self):
		prompt = '- MODIFY  - change fields\n- DISAMBIGUATE - vague\n{"intent": "CREATE|MODIFY|DISAMBIGUATE|SMALL_TALK"}'
		text = prompt.replace(fix.INTENT_ANCHOR, fix.INTENT_RULE + fix.INTENT_ANCHOR, 1)
		text = text.replace(fix.ENUM_OLD, fix.ENUM_NEW, 1)
		self.assertLess(text.index("EDIT_FIELD_PROPERTY:"), text.index("- DISAMBIGUATE"))
		self.assertIn('"CREATE|MODIFY|EDIT_FIELD_PROPERTY|DISAMBIGUATE|', text)
