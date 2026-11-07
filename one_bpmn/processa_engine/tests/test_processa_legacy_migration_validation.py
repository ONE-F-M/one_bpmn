# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A migration may keep the status it filters on, to attach process instances to records already in it."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcessaLegacyMigrationValidation(FrappeTestCase):
	def _migration(self, old_status: str, target_status: str):
		return frappe.get_doc(
			{
				"doctype": "Processa Legacy Migration",
				"process_model": "Software Development v4",
				"target_doctype": "Work Item",
				"old_status": old_status,
				"target_status": target_status,
				"create_process_instance": 1,
				"status": "Draft",
			}
		)

	def test_the_same_old_and_target_status_is_saved(self):
		migration = self._migration("Draft", "Draft")
		migration.flags.ignore_links = True
		with patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
			name = migration.insert().name

		stored = frappe.db.get_value("Processa Legacy Migration", name, ["old_status", "target_status"])
		self.assertEqual(stored, ("Draft", "Draft"))

	def test_a_missing_target_status_is_still_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._migration("Draft", "").run_method("validate")
