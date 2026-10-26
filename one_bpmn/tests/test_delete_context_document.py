# Copyright (c) 2026, one-fm and contributors
"""A context document deletes even when its process instance catches the delete and is kept for the record."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import BPMNProcessInstance


class TestDeleteContextDocument(FrappeTestCase):
	def test_a_document_deletes_when_its_kept_instance_has_task_rows_naming_it(self):
		todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "context document", "allocated_to": "Administrator"}
		).insert()
		model = frappe.get_doc(
			{"doctype": "BPMN Process Model", "title": "ZZ delete context test", "process_id": "zz_delete", "version": 1}
		).insert()
		instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": model.name,
				"context_doctype": "ToDo",
				"context_docname": todo.name,
				"status": "Active",
				"active_tasks": [
					{
						"task_id": "t1",
						"task_name": "Approve",
						"status": "Waiting",
						"target_doctype": "ToDo",
						"target_docname": todo.name,
					}
				],
			}
		)
		instance.insert()

		# The diagram catches the delete message, so the instance is kept rather than removed.
		with patch.object(BPMNProcessInstance, "receive_message", return_value=None):
			frappe.delete_doc("ToDo", todo.name)

		self.assertFalse(frappe.db.exists("ToDo", todo.name))
		kept = frappe.get_doc("BPMN Process Instance", instance.name)
		self.assertEqual(kept.status, "Cancelled")
		self.assertFalse(kept.active_tasks[0].target_docname)
