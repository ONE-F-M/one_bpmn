"""Native Submit, Cancel and Delete are withdrawn from DocTypes Processa runs."""

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.boot import boot_session
from one_bpmn.one_bpmn.trigger import guard_bpmn_document

CONTROLLED = "one_bpmn.api.instance_api.get_processa_controlled_doctypes"


def _doc(doctype="Note"):
	return frappe._dict(doctype=doctype, name="PROBE-0001")


class TestNativeActionGuard(FrappeTestCase):
	def test_submit_and_cancel_are_blocked_without_a_live_instance(self):
		with patch(CONTROLLED, return_value=["Note"]):
			for method in ("before_submit", "before_cancel", "before_workflow_action"):
				with self.assertRaises(frappe.ValidationError):
					guard_bpmn_document(_doc(), method)

	def test_engine_action_is_allowed(self):
		frappe.flags.bpmn_engine_action = True
		self.addCleanup(setattr, frappe.flags, "bpmn_engine_action", False)
		with patch(CONTROLLED, return_value=["Note"]):
			guard_bpmn_document(_doc(), "before_submit")

	def test_doctype_outside_processa_is_unaffected(self):
		with patch(CONTROLLED, return_value=["Blog Post"]):
			guard_bpmn_document(_doc(), "before_submit")

	def test_patches_are_allowed(self):
		frappe.flags.in_patch = True
		self.addCleanup(setattr, frappe.flags, "in_patch", False)
		with patch(CONTROLLED, return_value=["Note"]):
			guard_bpmn_document(_doc(), "before_submit")


class TestListActionsContract(FrappeTestCase):
	def test_boot_carries_the_controlled_doctypes(self):
		bootinfo = frappe._dict()
		with patch("one_bpmn.boot.get_processa_controlled_doctypes", return_value=["Note"]):
			boot_session(bootinfo)
		self.assertEqual(bootinfo.processa_doctypes, ["Note"])

	def test_list_script_removes_the_three_native_items_and_is_loaded(self):
		app = Path(frappe.get_app_path("one_bpmn"))
		source = (app / "public" / "js" / "bpmn_list_actions.js").read_text()
		self.assertIn('["Submit", "Cancel", "Delete"]', source)
		self.assertIn("frappe.boot.processa_doctypes", source)
		self.assertIn("bpmn_list_actions.js", (app / "hooks.py").read_text())
