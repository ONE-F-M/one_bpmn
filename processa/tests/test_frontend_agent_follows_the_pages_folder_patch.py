# Copyright (c) 2026, one-fm and contributors
"""Locate UI reads the router from its new path and the retired tool scripts are gone."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import frontend_agent_follows_the_pages_folder as patch


class TestFrontendAgentFollowsThePagesFolderPatch(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _install_retired_script(self, name: str):
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": frappe.scrub(name),
				"allow_guest": 0,
				"script": "frappe.response['message'] = 'retired'",
			}
		).insert()

	def test_locate_ui_reads_the_router_from_its_new_path(self):
		if not frappe.db.exists("Server Script", patch.LOCATE_UI):
			self.skipTest(f"{patch.LOCATE_UI} is not on this site")
		doc = frappe.get_doc("Server Script", patch.LOCATE_UI)
		doc.script = doc.script.replace(patch.NEW_ROUTER, patch.OLD_ROUTER)
		doc.save()

		patch.execute()

		script = frappe.db.get_value("Server Script", patch.LOCATE_UI, "script")
		self.assertIn(patch.NEW_ROUTER, script)
		self.assertNotIn(patch.OLD_ROUTER, script)

	def test_the_retired_scripts_are_removed_and_the_others_stay(self):
		retired = patch.RETIRED_SCRIPTS[0]
		if not frappe.db.exists("Server Script", retired):
			self._install_retired_script(retired)
		kept = "Frontend Agent: Tool Component Catalogue"
		kept_before = frappe.db.exists("Server Script", kept)

		patch.execute()

		self.assertFalse(frappe.db.exists("Server Script", retired))
		self.assertEqual(frappe.db.exists("Server Script", kept), kept_before)

	def test_a_second_run_changes_nothing(self):
		patch.execute()
		patch.execute()
		for name in patch.RETIRED_SCRIPTS:
			self.assertFalse(frappe.db.exists("Server Script", name))
