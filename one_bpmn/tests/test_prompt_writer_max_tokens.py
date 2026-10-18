# Copyright (c) 2026, one-fm and contributors
"""The system-prompt writer caps its reply at the agent's own max_tokens."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agent_provisioning
from one_bpmn.agents.executor import DEFAULT_MAX_OUTPUT_TOKENS


def _max_tokens_sent(config_max_tokens: int) -> int:
	cfg = frappe._dict(
		agent_id="stub_agent",
		agent_name="Stub",
		description=None,
		chat_mode_label=None,
		max_tokens=config_max_tokens,
	)
	adapter = MagicMock()
	adapter.complete.return_value = frappe._dict(text="")
	with (
		patch.object(frappe, "get_doc", return_value=cfg),
		patch(
			"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config"
		),
		patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
		patch("one_bpmn.agents.executor.direct_api._run_coro_blocking", side_effect=lambda c: c),
	):
		agent_provisioning.generate_system_prompt("stub")
	return adapter.complete.call_args.kwargs["max_tokens"]


class TestPromptWriterMaxTokens(FrappeTestCase):
	def test_uses_the_configured_max_tokens(self):
		self.assertEqual(_max_tokens_sent(3000), 3000)

	def test_zero_falls_back_to_the_default(self):
		self.assertEqual(_max_tokens_sent(0), DEFAULT_MAX_OUTPUT_TOKENS)
