# Copyright (c) 2026, one-fm and contributors
"""The direct path sends the dispatcher's assembled system prompt untouched, whatever the configuration is called."""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorConfig
from one_bpmn.agents.executor.direct_api import DirectApiExecutor

ASSEMBLED = "You are the release notes agent.\n\n## Guard rails\n- Never invent a ticket."


class TestDirectApiSystemPrompt(FrappeTestCase):
	def test_the_system_prompt_is_sent_byte_for_byte(self):
		for provider in ("OpenAI", "Anthropic"):
			with self.subTest(provider=provider):
				sent = _system_prompt_sent(provider)
				self.assertEqual(sent, ASSEMBLED)
				self.assertNotIn("Release Notes Agent Config", sent)


def _system_prompt_sent(provider):
	cfg = ExecutorConfig(
		backend="direct_api",
		provider_name=provider,
		agent_config_name="Release Notes Agent Config",
		model="test-model",
		system_prompt=ASSEMBLED,
		user_prompt="Draft the notes.",
		max_retries=0,
	)

	def get_value(doctype, name, fields=None, as_dict=False, **kwargs):
		return frappe._dict(enable_model=1, api_endpoint="") if as_dict else None

	response = MagicMock(status_code=500, text="stop here")
	with (
		patch.object(frappe.db, "exists", return_value=True),
		patch.object(frappe.db, "get_value", side_effect=get_value),
		patch("frappe.utils.password.get_decrypted_password", return_value="key"),
		patch("requests.post", return_value=response) as post,
	):
		DirectApiExecutor().run(cfg, None)

	payload = post.call_args.kwargs["json"]
	if "system" in payload:
		return "".join(block["text"] for block in payload["system"])
	return next(m["content"] for m in payload["messages"] if m["role"] == "system")
