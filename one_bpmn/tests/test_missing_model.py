# Copyright (c) 2026, one-fm and contributors
"""An agent whose provider has no model fails with a named, actionable error."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig
from one_bpmn.agents.executor.direct_api import DirectApiExecutor


class TestMissingModel(FrappeTestCase):
	def test_a_provider_with_no_model_reports_model_not_configured(self):
		result, _get_value = _run_without_a_model()
		self.assertEqual(result.error_code, ErrorCode.MODEL_NOT_CONFIGURED)
		self.assertEqual(result.error_message, "No model is configured for provider Anthropic.")

	def test_the_fallback_looks_for_an_enabled_model_on_the_configured_provider(self):
		_result, get_value = _run_without_a_model("OpenAI")
		get_value.assert_called_once_with("AI Model", {"provider": "OpenAI", "enable_model": 1}, "name")


def _run_without_a_model(provider="Anthropic"):
	cfg = ExecutorConfig(
		backend="direct_api",
		provider_name=provider,
		model="",
		system_prompt="s",
		user_prompt="u",
	)
	with patch.object(frappe.db, "exists", return_value=True), patch.object(
		frappe.db, "get_value", return_value=None
	) as get_value:
		result = DirectApiExecutor().run(cfg, None)
	return result, get_value
