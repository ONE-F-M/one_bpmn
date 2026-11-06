# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Editability has one source path: check_process_editable goes through the bulk check."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import editability


class TestEditabilitySinglePath(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.tag = frappe.generate_hash(length=6)
		frappe.db.set_single_value("Processa Settings", "connect_to_production", 0)
		frappe.clear_document_cache("Processa Settings", "Processa Settings")
		conf_patch = patch.dict(frappe.conf, {}, clear=False)
		conf_patch.start()
		self.addCleanup(conf_patch.stop)
		frappe.conf.pop("bypass_process_lock", None)

	def _process(self, key):
		name = f"Zz Editability {key} {self.tag}"
		frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": name,
				"description": "editability test",
				"process_owner": "Administrator",
			}
		).insert(ignore_permissions=True)
		return name

	def _implementation(self, process):
		doc = frappe.get_doc(
			{
				"doctype": "Process Implementation",
				"process_name": process,
				"process_owner": "Administrator",
				"business_analyst": "Administrator",
				"goal_description": "editability test",
			}
		).insert(ignore_permissions=True, ignore_links=True)
		frappe.db.set_value(
			"Process Implementation",
			doc.name,
			{"workflow_state": "Active", "editable": 1},
		)
		return doc.name

	def test_process_with_active_editable_implementation_is_editable(self):
		process = self._process("with")
		implementation = self._implementation(process)

		result = editability.check_process_editable(process)

		self.assertTrue(result["editable"])
		self.assertEqual(result["process_implementation"], implementation)
		self.assertEqual(result["workflow_state"], "Active")
		self.assertFalse(result["override"])

	def test_process_without_implementation_is_not_editable(self):
		process = self._process("without")

		result = editability.check_process_editable(process)

		self.assertFalse(result["editable"])
		self.assertIsNone(result["process_implementation"])
		self.assertEqual(result["reason"], editability.NOT_EDITABLE_REASON)

	def test_old_single_process_endpoint_is_gone(self):
		self.assertFalse(hasattr(editability, "is_process_editable"))

	def test_production_creds_read_frappe_conf_when_settings_are_empty(self):
		empty_settings = SimpleNamespace(connect_to_production=0)
		conf = {
			"production_url": "https://prod.example.com/",
			"production_api_key": "conf-key",
			"production_api_secret": "conf-secret",
		}
		with patch.object(frappe, "get_single", return_value=empty_settings), patch.dict(
			frappe.conf, conf
		):
			self.assertEqual(
				editability._production_creds(),
				("https://prod.example.com", "conf-key", "conf-secret"),
			)
			self.assertFalse(editability._is_local_dev_mode())

	def test_local_dev_mode_when_any_credential_is_missing(self):
		empty_settings = SimpleNamespace(connect_to_production=0)
		conf = {"production_url": "https://prod.example.com", "production_api_key": "conf-key"}
		with patch.object(frappe, "get_single", return_value=empty_settings), patch.dict(
			frappe.conf, conf
		):
			frappe.conf.pop("production_api_secret", None)
			self.assertTrue(editability._is_local_dev_mode())
