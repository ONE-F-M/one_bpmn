# Copyright (c) 2026, kartiksharma9319@gmail.com and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_engine.doctype.bpmn_activity_log.bpmn_activity_log import on_doctype_update


class TestBPMNActivityLog(FrappeTestCase):
	def test_duplicate_check_has_an_instance_task_action_index(self):
		on_doctype_update()
		self.assertTrue(frappe.db.has_index("tabBPMN Activity Log", "instance_task_id_action_index"))

	def test_the_patch_creates_the_index_on_a_site_that_lacks_it(self):
		from processa.patches.v1_0.add_activity_log_lookup_index import execute

		if frappe.db.has_index("tabBPMN Activity Log", "instance_task_id_action_index"):
			frappe.db.sql_ddl("ALTER TABLE `tabBPMN Activity Log` DROP INDEX `instance_task_id_action_index`")
		execute()
		self.assertTrue(frappe.db.has_index("tabBPMN Activity Log", "instance_task_id_action_index"))
