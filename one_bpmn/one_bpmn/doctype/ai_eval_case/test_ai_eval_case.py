# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestAIEvalCase(FrappeTestCase):
	"""Tests for AI Eval Case DocType."""

	def tearDown(self):
		frappe.set_user("Administrator")

	def _make_provider(self):
		"""Create a test AI Provider if it doesn't exist."""
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
		return "Test Provider"

	def _make_eval_case(self, **kwargs):
		"""Factory function for creating test AI Eval Case documents."""
		provider = self._make_provider()
		defaults = {
			"doctype": "AI Eval Case",
			"title": "Test Eval Case",
			"provider": provider,
			"model": "gpt-4o",
			"backend": "direct_api",
			"input_user_prompt": "What is 2 + 2?",
		}
		defaults.update(kwargs)
		doc = frappe.get_doc(defaults)
		doc.insert(ignore_permissions=True)
		return doc

	def test_basic_create_and_hash_autoname(self):
		"""AI Eval Case should be created with a random hash name."""
		doc = self._make_eval_case()
		self.assertTrue(doc.name)
		self.assertEqual(len(doc.name), 10)  # Frappe hash names are 10 chars
		self.assertEqual(doc.title, "Test Eval Case")

	def test_create_with_contains_assertion(self):
		"""Case with a 'contains' assertion should save successfully."""
		doc = self._make_eval_case(
			assertions=[{
				"assertion_type": "contains",
				"value": "4",
			}]
		)
		self.assertEqual(len(doc.assertions), 1)
		self.assertEqual(doc.assertions[0].assertion_type, "contains")

	def test_create_with_multiple_assertions(self):
		"""Case with multiple assertion types should save successfully."""
		doc = self._make_eval_case(
			assertions=[
				{"assertion_type": "contains", "value": "4"},
				{"assertion_type": "regex", "value": r"\b4\b"},
				{"assertion_type": "schema_valid", "value": '{"type": "string"}'},
			]
		)
		self.assertEqual(len(doc.assertions), 3)

	def test_llm_judge_requires_judge_provider(self):
		"""llm_judge assertion without judge_provider should raise."""
		with self.assertRaises(frappe.ValidationError):
			self._make_eval_case(
				assertions=[{
					"assertion_type": "llm_judge",
					"value": "The output should be accurate and helpful.",
					"judge_model": "gpt-4o",
				}]
			)

	def test_llm_judge_requires_judge_model(self):
		"""llm_judge assertion without judge_model should raise."""
		provider = self._make_provider()
		with self.assertRaises(frappe.ValidationError):
			self._make_eval_case(
				assertions=[{
					"assertion_type": "llm_judge",
					"value": "The output should be accurate.",
					"judge_provider": provider,
				}]
			)

	def test_llm_judge_invalid_threshold(self):
		"""llm_judge assertion with threshold outside 1-5 should raise."""
		provider = self._make_provider()
		with self.assertRaises(frappe.ValidationError):
			self._make_eval_case(
				assertions=[{
					"assertion_type": "llm_judge",
					"value": "The output should be accurate.",
					"judge_provider": provider,
					"judge_model": "gpt-4o",
					"pass_threshold": 6,
				}]
			)

	def test_llm_judge_valid(self):
		"""llm_judge assertion with all required fields should save."""
		provider = self._make_provider()
		doc = self._make_eval_case(
			assertions=[{
				"assertion_type": "llm_judge",
				"value": "The output should accurately answer the question.",
				"judge_provider": provider,
				"judge_model": "gpt-4o",
				"pass_threshold": 4,
			}]
		)
		self.assertEqual(len(doc.assertions), 1)
		self.assertEqual(doc.assertions[0].pass_threshold, 4)

	def test_default_backend(self):
		"""Backend should default to 'direct_api'."""
		doc = self._make_eval_case()
		self.assertEqual(doc.backend, "direct_api")

	def test_optional_fields_nullable(self):
		"""Optional fields should accept None/empty values."""
		doc = self._make_eval_case(
			input_system_prompt=None,
			input_context=None,
			expected_output=None,
			suite=None,
			source_run=None,
			process_model=None,
			bpmn_id=None,
		)
		self.assertIsNone(doc.input_system_prompt)
