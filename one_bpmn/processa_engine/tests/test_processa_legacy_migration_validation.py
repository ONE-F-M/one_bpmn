# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A migration names an old map, a new map and at least one state mapping row."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcessaLegacyMigrationValidation(FrappeTestCase):
	def _migration(self, to_model: str):
		migration = frappe.get_doc(
			{
				"doctype": "Processa Legacy Migration",
				"from_model": "Software Development v3",
				"to_model": to_model,
				"target_doctype": "Work Item",
				"state_map": [{"old_state": "Open", "new_state": "Open"}],
				"status": "Draft",
			}
		)
		migration.flags.ignore_links = True
		return migration

	def test_both_maps_and_a_state_map_row_are_saved(self):
		with patch("one_bpmn.processa_engine.triggers.on_doc_event"):
			name = self._migration("Software Development v4").insert().name

		stored = frappe.get_doc("Processa Legacy Migration", name)
		self.assertEqual(
			(stored.from_model, stored.to_model), ("Software Development v3", "Software Development v4")
		)
		self.assertEqual([(d.old_state, d.new_state) for d in stored.state_map], [("Open", "Open")])

	def test_a_missing_new_process_map_is_refused(self):
		with (
			patch("one_bpmn.processa_engine.triggers.on_doc_event"),
			self.assertRaises(frappe.MandatoryError),
		):
			self._migration("").insert()
