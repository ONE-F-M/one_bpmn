# Copyright (c) 2026, one-fm and contributors
"""The patch moves each Processa Legacy Migration's process_model into to_model and drops the old column."""

import frappe
from frappe.database.schema import add_column
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0.rename_plm_process_model_to_to_model import DOCTYPE, execute


class TestRenamePlmProcessModelToToModelPatch(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Adding and dropping a column commits, so the row this test adds is removed by hand.
		add_column(DOCTYPE, "process_model", "Data")
		frappe.cache.hdel("table_columns", f"tab{DOCTYPE}")
		table = frappe.qb.DocType(DOCTYPE)
		frappe.qb.update(table).set(table.process_model, table.to_model).run()
		self.name = frappe.generate_hash(length=10)
		self.addCleanup(self._remove_row)
		frappe.get_doc(
			{"doctype": DOCTYPE, "name": self.name, "status": "Draft", "target_doctype": "Note"}
		).db_insert()
		frappe.qb.update(table).set(table.process_model, "PLM Patch Map").where(table.name == self.name).run()

	def _remove_row(self):
		frappe.db.delete(DOCTYPE, {"name": self.name})
		frappe.db.commit()
		frappe.cache.hdel("table_columns", f"tab{DOCTYPE}")

	def test_process_model_moves_to_to_model_and_its_column_is_dropped(self):
		execute()
		frappe.cache.hdel("table_columns", f"tab{DOCTYPE}")
		self.assertEqual(frappe.db.get_value(DOCTYPE, self.name, "to_model"), "PLM Patch Map")
		self.assertFalse(frappe.db.has_column(DOCTYPE, "process_model"))

	def test_a_second_run_changes_nothing(self):
		execute()
		before = frappe.get_all(DOCTYPE, fields=["name", "to_model"], order_by="name")
		# A second migrate starts with a cleared cache, as bench migrate clears it before the patches.
		frappe.cache.hdel("table_columns", f"tab{DOCTYPE}")
		execute()
		self.assertEqual(frappe.get_all(DOCTYPE, fields=["name", "to_model"], order_by="name"), before)
