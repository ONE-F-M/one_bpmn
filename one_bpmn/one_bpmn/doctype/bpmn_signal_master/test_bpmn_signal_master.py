import frappe
from frappe.tests.utils import FrappeTestCase

DOCTYPE = "BPMN Signal Master"


def make_bpmn_signal_master(name="Client Event Decision"):
	return frappe.get_doc({"doctype": DOCTYPE, "bpmn_signal_name": name}).insert()


def make_user_with_role(role):
	email = f"signal.{frappe.scrub(role)}@example.com"
	frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "Signal Tester", "send_welcome_email": 0, "roles": [{"role": role}]}
	).insert(ignore_if_duplicate=True)
	return email


class TestBPMNSignalMaster(FrappeTestCase):
	def test_name_is_the_record_id(self):
		self.assertEqual(make_bpmn_signal_master("Roster Decision").name, "Roster Decision")

	def test_surrounding_spaces_are_stripped(self):
		self.assertEqual(make_bpmn_signal_master("  Roster Published ").name, "Roster Published")

	def test_duplicate_in_other_case_is_rejected(self):
		make_bpmn_signal_master("Client Event Decision")
		with self.assertRaises(frappe.DuplicateEntryError):
			make_bpmn_signal_master("client event decision")

	def test_process_designer_can_create_and_edit(self):
		with self.set_user(make_user_with_role("Process Designer")):
			self.assertTrue(frappe.has_permission(DOCTYPE, "create"))
			self.assertTrue(frappe.has_permission(DOCTYPE, "write"))

	def test_process_owner_can_read_but_not_create_or_edit(self):
		with self.set_user(make_user_with_role("Process Owner")):
			self.assertTrue(frappe.has_permission(DOCTYPE, "read"))
			self.assertFalse(frappe.has_permission(DOCTYPE, "create"))
			self.assertFalse(frappe.has_permission(DOCTYPE, "write"))
