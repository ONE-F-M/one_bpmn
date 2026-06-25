# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAIEvalSuite(FrappeTestCase):
	"""Tests for AI Eval Suite DocType."""

	def tearDown(self):
		frappe.set_user("Administrator")

	def _get_process_model(self):
		"""Return the name of any existing BPMN Process Model for testing."""
		name = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not name:
			self.skipTest("No BPMN Process Model exists for testing")
		return name

	def _make_eval_suite(self, **kwargs):
		"""Factory function for creating test AI Eval Suite documents."""
		defaults = {
			"doctype": "AI Eval Suite",
			"title": "Test Eval Suite",
			"process_model": self._get_process_model(),
			"gate_deployment": 0,
		}
		defaults.update(kwargs)
		doc = frappe.get_doc(defaults)
		doc.insert(ignore_permissions=True)
		return doc

	def test_basic_create_and_hash_autoname(self):
		"""AI Eval Suite should be created with a random hash name."""
		doc = self._make_eval_suite()
		self.assertTrue(doc.name)
		self.assertEqual(len(doc.name), 10)  # Frappe hash names are 10 chars
		self.assertEqual(doc.title, "Test Eval Suite")

	def test_gate_deployment_defaults_to_zero(self):
		"""gate_deployment should default to 0."""
		doc = self._make_eval_suite()
		self.assertEqual(doc.gate_deployment, 0)

	def test_gate_deployment_enabled(self):
		"""gate_deployment can be set to 1."""
		doc = self._make_eval_suite(gate_deployment=1)
		self.assertEqual(doc.gate_deployment, 1)

	def test_title_required(self):
		"""Creating a suite without title should raise."""
		with self.assertRaises(frappe.exceptions.MandatoryError):
			self._make_eval_suite(title=None)

	def test_process_model_required(self):
		"""Creating a suite without process_model should raise."""
		with self.assertRaises(frappe.exceptions.MandatoryError):
			self._make_eval_suite(process_model=None)

	def test_description_optional(self):
		"""Description field should accept None."""
		doc = self._make_eval_suite(description=None)
		self.assertFalse(doc.description)

	def test_cases_queryable_by_suite(self):
		"""Cases linked to this suite should be queryable via get_list."""
		suite = self._make_eval_suite()

		# Create a provider for the eval case
		if not frappe.db.exists("AI Provider", "Test Provider"):
			frappe.get_doc({
				"doctype": "AI Provider",
				"provider_name": "Test Provider",
				"provider_type": "OpenAI",
				"api_endpoint": "https://api.openai.com/v1",
				"api_key": "sk-test-key",
				"default_model": "gpt-4o",
				"enabled": 1,
			}).insert(ignore_permissions=True)

		case = frappe.get_doc({
			"doctype": "AI Eval Case",
			"title": "Suite-linked Case",
			"suite": suite.name,
			"provider": "Test Provider",
			"model": "gpt-4o",
			"input_user_prompt": "Test prompt",
		})
		case.insert(ignore_permissions=True)

		cases = frappe.get_list(
			"AI Eval Case",
			filters={"suite": suite.name},
			fields=["name", "title"],
		)
		self.assertEqual(len(cases), 1)
		self.assertEqual(cases[0].title, "Suite-linked Case")
