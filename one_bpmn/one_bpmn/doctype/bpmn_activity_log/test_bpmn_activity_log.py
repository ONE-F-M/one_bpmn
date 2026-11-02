# Copyright (c) 2026, kartiksharma9319@gmail.com and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_activity_log.bpmn_activity_log import on_doctype_update


class TestBPMNActivityLog(FrappeTestCase):
	def test_duplicate_check_has_an_instance_task_action_index(self):
		on_doctype_update()
		self.assertTrue(frappe.db.has_index("tabBPMN Activity Log", "instance_task_id_action_index"))
