import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.editability import ensure_instance_type_seeded

SETTINGS = "Processa Settings"


def _stored(field):
	return frappe.db.sql(
		"select value from tabSingles where doctype = %s and field = %s", (SETTINGS, field)
	)


class TestInstanceTypeSeed(FrappeTestCase):
	def setUp(self):
		self.original_instance_type = frappe.db.get_single_value(SETTINGS, "instance_type")
		self.original_connect = frappe.db.get_single_value(SETTINGS, "connect_to_production")

	def tearDown(self):
		frappe.db.set_single_value(SETTINGS, "instance_type", self.original_instance_type or "")
		frappe.db.set_single_value(SETTINGS, "connect_to_production", self.original_connect or 0)
		frappe.clear_cache(doctype=SETTINGS)

	def _set(self, instance_type, connect_to_production):
		frappe.db.set_single_value(SETTINGS, "instance_type", instance_type)
		frappe.db.set_single_value(SETTINGS, "connect_to_production", connect_to_production)
		frappe.clear_cache(doctype=SETTINGS)

	def test_seeds_local_when_not_connected_to_production(self):
		self._set("", 0)
		self.assertEqual(ensure_instance_type_seeded(), "Local")
		self.assertEqual(_stored("instance_type")[0][0], "Local")

	def test_seeds_ba_when_connected_to_production(self):
		self._set("", 1)
		self.assertEqual(ensure_instance_type_seeded(), "BA")
		self.assertEqual(_stored("instance_type")[0][0], "BA")

	def test_existing_value_is_left_alone(self):
		self._set("Production", 1)
		self.assertEqual(ensure_instance_type_seeded(), "Production")
		self.assertEqual(_stored("instance_type")[0][0], "Production")

	def test_second_run_changes_nothing(self):
		self._set("", 0)
		first = ensure_instance_type_seeded()
		self.assertEqual(ensure_instance_type_seeded(), first)
		self.assertEqual(_stored("instance_type")[0][0], first)

	def test_after_install_hook_is_registered(self):
		self.assertIn("one_bpmn.install.after_install", frappe.get_hooks("after_install"))
