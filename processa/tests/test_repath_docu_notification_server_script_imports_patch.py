# Copyright (c) 2026, one-fm and contributors
"""The patch that points stored Server Script imports at the renamed Docu, notification and Server Script modules."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import repath_docu_notification_server_script_imports as P

SCRIPT_NAME = "ZZ Repath Docu Notification Server Script Imports"
OLD_SCRIPT = (
	"from processa.api.docu_api import apply_field_properties\n"
	"from processa.api.server_script_api import turn_failure_text\n"
	"# processa.api.notification_api.get_email_preview\n"
)
NEW_SCRIPT = (
	"from processa.api.docu import apply_field_properties\n"
	"from processa.api.server_scripts import turn_failure_text\n"
	"# processa.api.notifications.get_email_preview\n"
)


class TestRepathDocuNotificationServerScriptImports(FrappeTestCase):
	def setUp(self):
		frappe.db.delete("Server Script", {"name": SCRIPT_NAME})
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT_NAME,
				"script_type": "API",
				"api_method": "zz_repath_docu_notification_imports",
				"script": OLD_SCRIPT,
			}
		).insert()

	def test_script_imports_move(self):
		P.execute()
		self.assertEqual(frappe.db.get_value("Server Script", SCRIPT_NAME, "script"), NEW_SCRIPT)

	def test_running_twice_changes_nothing_more(self):
		P.execute()
		P.execute()
		self.assertEqual(frappe.db.get_value("Server Script", SCRIPT_NAME, "script"), NEW_SCRIPT)
