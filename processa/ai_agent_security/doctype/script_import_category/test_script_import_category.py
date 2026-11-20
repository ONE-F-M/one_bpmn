# Copyright (c) 2026, one-fm and contributors

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa import install
from processa.ai_agent_security.code_checks.category_seed import CATEGORIES
from processa.ai_agent_security.code_checks.script_categories import category_for, clear_category_cache
from processa.patches.v1_0 import seed_script_import_categories

READER = "script-category-reader@example.com"


class TestScriptImportCategory(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()

	def tearDown(self):
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _category(self, name, *rows):
		if frappe.db.exists("Script Import Category", name):
			frappe.delete_doc("Script Import Category", name, force=True)
		return frappe.get_doc(
			{
				"doctype": "Script Import Category",
				"category_name": name,
				"names": [{"dotted_name": dotted, "kind": kind} for dotted, kind in rows],
			}
		)

	def test_seed_lists_every_category_with_names(self):
		for category in CATEGORIES:
			doc = frappe.get_doc("Script Import Category", category["category_name"])
			self.assertEqual(doc.allowed_by_default, category["allowed_by_default"])
			self.assertEqual(len(doc.names), len(category["names"]))
		self.assertEqual(frappe.db.get_value("Script Import Category", "Size limits", "threshold"), 50000)

	def test_longest_prefix_wins_and_unknown_is_unlisted(self):
		self.assertEqual(category_for("urllib.request.urlopen"), "Network")
		self.assertEqual(category_for("urllib.parse"), "Python basics")
		self.assertEqual(category_for("paramiko"), "Unlisted")

	def test_processa_module_is_processa_backend(self):
		self.assertEqual(
			category_for("processa.ai_agent_registry.definitions.logix.tools"), "Processa backend"
		)

	def test_match_on_any_object(self):
		self.assertEqual(category_for("doc.db_set"), "Database direct")
		self.assertEqual(category_for("settings.get_password"), "Secrets")

	def test_seed_keeps_a_changed_category(self):
		frappe.db.set_value("Script Import Category", "Network", "allowed_by_default", 1)
		seed_script_import_categories.execute()
		self.assertEqual(frappe.db.get_value("Script Import Category", "Network", "allowed_by_default"), 1)

	def test_saved_category_is_used_without_restart(self):
		self.assertEqual(category_for("paramiko"), "Unlisted")
		network = frappe.get_doc("Script Import Category", "Network")
		network.append("names", {"dotted_name": "paramiko", "kind": "Module"})
		network.save()
		self.assertEqual(category_for("paramiko"), "Network")

	def test_same_name_in_two_categories_is_refused(self):
		doc = self._category("Test Duplicate", ("requests", "Module"))
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.insert()
		self.assertIn("Network", str(caught.exception))
		self.assertIn("Test Duplicate", str(caught.exception))

	def test_malformed_dotted_name_is_refused(self):
		doc = self._category("Test Malformed", ("requests..post", "Module"))
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.insert()
		self.assertIn("Row 1", str(caught.exception))

	def test_unknown_syntax_name_is_refused(self):
		doc = self._category("Test Syntax", ("goto", "Syntax"))
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.insert()
		self.assertIn("Row 1", str(caught.exception))

	def test_other_users_can_read_but_not_change(self):
		if not frappe.db.exists("User", READER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": READER,
					"first_name": "Reader",
					"send_welcome_email": 0,
					"roles": [{"role": "Process Designer"}],
				}
			).insert()
		self.assertTrue(frappe.has_permission("Script Import Category", "read", "Network", user=READER))
		self.assertFalse(frappe.has_permission("Script Import Category", "write", "Network", user=READER))

	def test_seed_creates_application_manager_role(self):
		frappe.db.delete("Has Role", {"role": "Application Manager"})
		frappe.db.delete("Role", {"name": "Application Manager"})
		seed_script_import_categories.execute()
		self.assertTrue(frappe.db.exists("Role", "Application Manager"))

	def test_a_fresh_install_seeds_the_categories(self):
		with (
			patch(
				"processa.ai_agent_security.code_checks.category_seed.seed_script_import_categories"
			) as seed,
			patch("frappe.db.commit"),
		):
			install.after_install()
		seed.assert_called_once_with()
