# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A direct chat turn is recorded like any other turn.

The two process paths have always opened an AI Agent Run, written the prompt
steps and finalized with the tokens. The direct path opened nothing, so every
Direct API agent on a site was invisible to Insights: no run, no prompt hash,
no snapshot, no cost. Recording must never cost the person their answer, so a
failure to record leaves the turn alone.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import agent_invocation

PERSIST = "one_bpmn.utils.chat_persistence"
ADAPTER = "one_bpmn.agents.llm_provider.get_llm_adapter_from_settings"


def _completion(text="the answer"):
	return SimpleNamespace(text=text, trace=[], prompt_tokens=1200, completion_tokens=48)


class _FakeAdapter:
	def __init__(self, completion):
		self._completion = completion

	async def complete(self, **kwargs):
		return self._completion


class TestDirectChatIsRecorded(FrappeTestCase):
	def setUp(self):
		self.config = {
			"name": "Reval Agent Direct",
			"agent_id": "direct_test_agent",
			"ai_model": "some-model",
			"ai_provider": "Anthropic",
			"chat_mode_label": "Direct Test",
			"system_prompt": "You are a test agent.",
		}

	def _run(self, completion=None, **patches):
		completion = completion or _completion()
		with patch(ADAPTER, return_value=_FakeAdapter(completion)), patch(
			f"{PERSIST}.save_user_message"
		), patch(f"{PERSIST}.save_bot_message"), patch(
			"one_bpmn.agents.context_assembler.build_static_context_from_config",
			return_value="composed system prompt",
		):
			return agent_invocation._run_direct_api(self.config, "CONV-1", "what is a delivery note?", {})

	def test_the_turn_opens_a_run_and_writes_its_prompt_steps(self):
		with patch("one_bpmn.agents.observability.create_ai_run") as create, patch(
			"one_bpmn.agents.observability.record_ai_step"
		) as step, patch("one_bpmn.agents.observability.record_selector_turns"), patch(
			"one_bpmn.agents.observability.finalize_ai_run"
		):
			create.return_value = SimpleNamespace(name="RUN-FAKE", stub=False)
			self._run()

		create.assert_called_once()
		cfg = create.call_args.kwargs["config"]
		self.assertEqual(cfg.backend, "direct_api")
		self.assertEqual(cfg.model, "some-model")
		self.assertEqual(cfg.provider_name, "Anthropic")
		self.assertEqual(cfg.agent_config_name, "Reval Agent Direct")
		self.assertEqual(cfg.system_prompt, "composed system prompt")
		self.assertEqual(create.call_args.kwargs["bpmn_id"], "direct_test_agent")

		roles = [call.args[2] for call in step.call_args_list]
		self.assertEqual(roles, ["system", "user"])
		self.assertEqual(step.call_args_list[0].args[3], "composed system prompt")
		self.assertEqual(step.call_args_list[1].args[3], "what is a delivery note?")

	def test_the_run_is_finalized_with_the_tokens_the_turn_cost(self):
		with patch("one_bpmn.agents.observability.create_ai_run") as create, patch(
			"one_bpmn.agents.observability.record_ai_step"
		), patch("one_bpmn.agents.observability.record_selector_turns"), patch(
			"one_bpmn.agents.observability.finalize_ai_run"
		) as finalize:
			create.return_value = SimpleNamespace(name="RUN-FAKE", stub=False)
			out = self._run()

		self.assertEqual(out["response"], "the answer")
		result = finalize.call_args.args[1]
		self.assertEqual(result.output, "the answer")
		self.assertEqual(result.token_usage.prompt_tokens, 1200)
		self.assertEqual(result.token_usage.completion_tokens, 48)
		self.assertEqual(result.token_usage.total_tokens, 1248)

	def test_a_failed_model_call_finalizes_the_run_and_still_raises(self):
		class _Boom(_FakeAdapter):
			async def complete(self, **kwargs):
				raise RuntimeError("provider down")

		with patch(ADAPTER, return_value=_Boom(None)), patch(f"{PERSIST}.save_user_message"), patch(
			f"{PERSIST}.save_bot_message"
		), patch(
			"one_bpmn.agents.context_assembler.build_static_context_from_config", return_value="sp"
		), patch("one_bpmn.agents.observability.create_ai_run") as create, patch(
			"one_bpmn.agents.observability.record_ai_step"
		), patch("one_bpmn.agents.observability.finalize_ai_run_on_exception") as failed:
			create.return_value = SimpleNamespace(name="RUN-FAKE", stub=False)
			with self.assertRaises(RuntimeError):
				agent_invocation._run_direct_api(self.config, "CONV-2", "hello", {})

		failed.assert_called_once()

	def test_recording_that_fails_does_not_cost_the_answer(self):
		"""The person asked a question. Bookkeeping is not worth their turn."""
		with patch(
			"one_bpmn.agents.observability.create_ai_run", side_effect=RuntimeError("no run")
		), patch("frappe.log_error"):
			out = self._run()

		self.assertEqual(out["response"], "the answer")
