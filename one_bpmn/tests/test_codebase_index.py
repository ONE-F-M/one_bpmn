# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The codebase index maps a DocType's display module to its app."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import codebase_index

MSE = "Maintenance Schedule Entry"


def _index(module_app, module="One Fm", name=MSE):
	rows = [{"name": name, "module": module}]
	with patch.object(frappe, "get_all", return_value=rows):
		return codebase_index._doctypes(module_app, codebase_index.get_apps_root())


class TestDoctypeAppMapping(FrappeTestCase):
	def test_scrubbed_module_map_finds_the_app_and_controller(self):
		(entry,) = _index({"one_fm": "one_fm"})
		self.assertEqual(entry["app"], "one_fm")
		self.assertEqual(
			entry["py_file"],
			"one_fm/one_fm/one_fm/doctype/maintenance_schedule_entry/maintenance_schedule_entry.py",
		)
		self.assertTrue(entry["py_exists"])

	def test_display_name_map_still_resolves(self):
		(entry,) = _index({"One Fm": "one_fm"})
		self.assertEqual(entry["app"], "one_fm")

	def test_unknown_module_has_no_app_and_no_controller(self):
		(entry,) = _index({"one_fm": "one_fm"}, module="Nowhere")
		self.assertEqual(entry["app"], "")
		self.assertFalse(entry["py_exists"])

	def test_cached_index_of_the_old_mapping_is_not_reused(self):
		self.assertTrue(codebase_index.INDEX_CACHE_KEY.endswith("_v2"))
