# Copyright (c) 2026, one-fm and contributors
# Most current Claude models reject temperature and top_p with a 400. The AI Model
# record's Support Temperature decides who is sent them, on the paths with and
# without tools alike; a model name pattern missed claude-fable-5 and claude-opus-4-8.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorConfig
from one_bpmn.agents.executor.direct_api import DirectApiExecutor, _supports_temperature


def _model(name: str, support: int) -> str:
	if not frappe.db.exists("AI Provider", "Anthropic"):
		frappe.get_doc({"doctype": "AI Provider", "provider": "Anthropic"}).insert(ignore_permissions=True)
	if not frappe.db.exists("AI Model", name):
		frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": name,
				"model_api_name": name,
				"provider": "Anthropic",
				"enable_model": 1,
				"support_temperature": support,
				"api_key": "test-key-not-real",
			}
		).insert(ignore_permissions=True)
	return name


def _payload(model: str, **config) -> dict:
	cfg = ExecutorConfig(
		backend="direct_api",
		provider_name="Anthropic",
		model=model,
		system_prompt="s",
		user_prompt="u",
		max_tokens=16,
		**config,
	)
	_url, payload, _headers = DirectApiExecutor()._build_anthropic_request(
		"https://api.anthropic.com", "k", model, cfg
	)
	return payload


class TestAnthropicSamplingParams(FrappeTestCase):
	def test_a_model_with_support_temperature_gets_the_temperature(self):
		payload = _payload(_model("_temp-yes-sonnet-4-5", 1), temperature=0.3)
		self.assertEqual(payload["temperature"], 0.3)
		self.assertNotIn("top_p", payload)

	def test_a_changed_top_p_goes_instead_of_the_temperature(self):
		payload = _payload(_model("_temp-yes-sonnet-4-5", 1), temperature=0.3, top_p=0.9)
		self.assertEqual(payload["top_p"], 0.9)
		self.assertNotIn("temperature", payload)

	def test_a_model_without_it_gets_neither(self):
		payload = _payload(_model("_temp-no-fable-5", 0), temperature=0.3, top_p=0.9)
		self.assertNotIn("temperature", payload)
		self.assertNotIn("top_p", payload)

	def test_an_unknown_or_missing_model_gets_neither(self):
		self.assertFalse(_supports_temperature("_no-such-model"))
		self.assertFalse(_supports_temperature(None))
