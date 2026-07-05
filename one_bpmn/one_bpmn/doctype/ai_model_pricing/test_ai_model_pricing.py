"""
Tests for AI Model Pricing — CRUD, utility function, historical pricing.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


def make_ai_model_pricing(**kwargs):
	"""Factory: create an AI Model Pricing record with test defaults."""
	defaults = {
		"doctype": "AI Model Pricing",
		"model_name": f"test-model-{frappe.generate_hash(length=6)}",
		"provider": "openai",
		"input_cost_per_1k": 0.0001,
		"output_cost_per_1k": 0.0004,
		"effective_from": "2026-01-01",
		"is_active": 1,
	}
	defaults.update(kwargs)
	doc = frappe.get_doc(defaults)
	doc.insert(ignore_permissions=True)
	return doc


class TestAIModelPricing(FrappeTestCase):

	def test_create_pricing(self):
		"""An admin can create an AI Model Pricing record."""
		doc = make_ai_model_pricing()
		self.assertTrue(frappe.db.exists("AI Model Pricing", doc.name))

	def test_get_model_pricing_returns_active(self):
		"""get_model_pricing() returns the active pricing record."""
		from one_bpmn.agents.pricing import get_model_pricing

		doc = make_ai_model_pricing()
		result = get_model_pricing(doc.model_name)
		self.assertIsNotNone(result)
		self.assertAlmostEqual(result["input_cost_per_1k"], doc.input_cost_per_1k)
		self.assertAlmostEqual(result["output_cost_per_1k"], doc.output_cost_per_1k)

	def test_get_model_pricing_returns_none_for_unknown(self):
		"""get_model_pricing('nonexistent-model') returns None."""
		from one_bpmn.agents.pricing import get_model_pricing

		result = get_model_pricing("nonexistent-model-that-does-not-exist")
		self.assertIsNone(result)

	def test_historical_pricing_active_wins(self):
		"""When two pricing records exist for the same model (different effective_from),
		the active one is returned."""
		from one_bpmn.agents.pricing import get_model_pricing

		model_name = f"hist-test-{frappe.generate_hash(length=6)}"

		# Old pricing, inactive
		make_ai_model_pricing(
			model_name=model_name,
			effective_from="2025-01-01",
			is_active=0,
		)
		# New pricing, active
		active = make_ai_model_pricing(
			model_name=model_name,
			effective_from="2026-06-01",
			is_active=1,
		)

		result = get_model_pricing(model_name)
		self.assertIsNotNone(result)
		self.assertAlmostEqual(result["input_cost_per_1k"], active.input_cost_per_1k)
