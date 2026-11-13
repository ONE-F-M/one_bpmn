# Copyright (c) 2026, one-fm and contributors
"""The patch that points stored connector paths at the processa package after the app rename."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import repath_stored_paths_to_processa as P
from processa.processa_connectors.tests.test_connector_dispatch import _ensure_echo_connector

OLD_HANDLER = "one_bpmn.processa_connectors.operations.google_drive.download_text"
OLD_TRANSFORM = "one_bpmn.processa_connectors.google.common.normalize_drive_id"
OLD_CHOICES = "one_bpmn.api.lookups.get_doctypes"


class TestRepathStoredPathsToProcessa(FrappeTestCase):
	def setUp(self):
		_ensure_echo_connector()
		self.op = frappe.db.get_value(
			"BPMN Connector Operation", {"connector": "test_echo", "operation_id": "echo"}, "name"
		)
		self.field = frappe.db.get_value(
			"BPMN Connector Field", {"parent": self.op, "field_name": "a"}, "name"
		)
		frappe.db.set_value("BPMN Connector Operation", self.op, "handler_path", OLD_HANDLER)
		frappe.db.set_value(
			"BPMN Connector Field",
			self.field,
			{"value_transform": OLD_TRANSFORM, "choices_source_path": OLD_CHOICES},
		)

	def _stored(self):
		field = frappe.db.get_value(
			"BPMN Connector Field", self.field, ["value_transform", "choices_source_path"], as_dict=True
		)
		return frappe.db.get_value("BPMN Connector Operation", self.op, "handler_path"), field

	def test_stored_paths_move_to_the_processa_package(self):
		P.execute()
		handler, field = self._stored()
		self.assertEqual(handler, "processa.processa_connectors.operations.google_drive.download_text")
		self.assertEqual(
			field.value_transform, "processa.processa_connectors.google.common.normalize_drive_id"
		)
		self.assertEqual(field.choices_source_path, "processa.api.lookups.get_doctypes")

	def test_running_twice_changes_nothing_more(self):
		P.execute()
		first = self._stored()
		P.execute()
		self.assertEqual(self._stored(), first)
