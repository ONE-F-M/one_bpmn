# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Temperature and top_p reach the provider, but only for a model whose AI Model record supports them."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorConfig, ExecutorContext
from one_bpmn.agents.executor.direct_api import DirectApiExecutor
from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.anthropic_adapter import AnthropicAdapter
from one_bpmn.agents.llm_provider.base import StepResult, ToolSpec
from one_bpmn.one_bpmn.patches.v1_0 import ai_models_mark_temperature_support
from one_bpmn.tests.test_anthropic_sampling_params import _model

TOOL = ToolSpec(
	fn=lambda **kw: "ok", name="search", description="Search.", parameters={"q": {"type": "string"}}
)


class _Stream:
	def __init__(self, sent):
		self.sent = sent

	def __call__(self, **kwargs):
		self.sent.append(kwargs)
		return self

	async def __aenter__(self):
		return self

	async def __aexit__(self, *exc):
		return False

	async def get_final_message(self):
		return SimpleNamespace(
			content=[SimpleNamespace(type="text", text="ok")],
			stop_reason="end_turn",
			usage=SimpleNamespace(input_tokens=1, output_tokens=1),
		)


def _anthropic_request(**step_kwargs) -> dict:
	adapter = AnthropicAdapter(api_key="test-key-not-real", model="claude-sonnet-4-5")
	sent = []
	adapter._client = SimpleNamespace(messages=SimpleNamespace(stream=_Stream(sent)))
	asyncio.run(adapter.step("sys", [{"role": "user", "content": "hi"}], **step_kwargs))
	return sent[0]


class _RecordingAdapter:
	def __init__(self):
		self.calls = []

	async def step(self, system, transcript, tools=None, max_tokens=16384, **kwargs):
		self.calls.append(kwargs)
		return StepResult(content="Done.")


class TestTheAnthropicAdapter(FrappeTestCase):
	def test_the_temperature_is_sent(self):
		self.assertEqual(_anthropic_request(temperature=0.3)["temperature"], 0.3)

	def test_a_changed_top_p_is_sent_instead(self):
		request = _anthropic_request(temperature=0.3, top_p=0.9)
		self.assertEqual(request["top_p"], 0.9)
		self.assertNotIn("temperature", request)

	def test_nothing_is_sent_when_none_is_given(self):
		request = _anthropic_request()
		self.assertNotIn("temperature", request)
		self.assertNotIn("top_p", request)

	def test_extended_thinking_sends_neither(self):
		request = _anthropic_request(temperature=0.3, thinking_budget_tokens=2048, max_tokens=8192)
		self.assertIn("thinking", request)
		self.assertNotIn("temperature", request)


class TestTheLoopPassesThemThrough(FrappeTestCase):
	def test_given_values_reach_every_step(self):
		adapter = _RecordingAdapter()
		asyncio.run(run_agent_loop(adapter, system="s", user="u", tools=[TOOL], temperature=0.3, top_p=0.9))
		self.assertEqual((adapter.calls[0]["temperature"], adapter.calls[0]["top_p"]), (0.3, 0.9))

	def test_no_values_leave_the_step_untouched(self):
		adapter = _RecordingAdapter()
		asyncio.run(run_agent_loop(adapter, system="s", user="u", tools=[TOOL]))
		self.assertNotIn("temperature", adapter.calls[0])


class TestTheExecutorDecidesByTheModel(FrappeTestCase):
	def _first_step(self, model: str) -> dict:
		adapter = _RecordingAdapter()
		config = ExecutorConfig(
			provider_name="Anthropic",
			model=model,
			system_prompt="s",
			user_prompt="u",
			tools=[TOOL],
			temperature=0.3,
		)
		with (
			patch("one_bpmn.agents.llm_provider.factory.get_llm_adapter", return_value=adapter),
			patch("frappe.utils.password.get_decrypted_password", return_value="test-key-not-real"),
		):
			DirectApiExecutor().run(config, ExecutorContext())
		return adapter.calls[0]

	def test_a_supporting_model_gets_the_temperature_with_tools(self):
		self.assertEqual(self._first_step(_model("_temp-yes-sonnet-4-5", 1))["temperature"], 0.3)

	def test_a_model_without_support_gets_none_with_tools(self):
		self.assertNotIn("temperature", self._first_step(_model("_temp-no-fable-5", 0)))


class TestThePatch(FrappeTestCase):
	def test_rows_are_matched_by_api_name(self):
		agent_row = _model("_temp-patch Dev Agent - claude-haiku-4-5", 0)
		frappe.db.set_value("AI Model", agent_row, "model_api_name", "claude-haiku-4-5")
		sonnet_5 = _model("_temp-patch claude-sonnet-5", 0)
		frappe.db.set_value("AI Model", sonnet_5, "model_api_name", "claude-sonnet-5")

		ai_models_mark_temperature_support.execute()
		ai_models_mark_temperature_support.execute()

		self.assertEqual(frappe.db.get_value("AI Model", agent_row, "support_temperature"), 1)
		self.assertEqual(frappe.db.get_value("AI Model", sonnet_5, "support_temperature"), 0)

	def test_gemini_2_models_count(self):
		self.assertTrue(ai_models_mark_temperature_support.accepts_temperature("gemini-2.0-flash"))
		self.assertFalse(ai_models_mark_temperature_support.accepts_temperature("gpt-5-nano"))


class TestTheSaveWarns(FrappeTestCase):
	def _warnings(self) -> str:
		return " ".join(str(m) for m in frappe.local.message_log)

	def test_a_configuration_with_a_temperature_on_an_unsupported_model_warns_and_saves(self):
		frappe.local.message_log = []
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": f"Temp Warn {frappe.generate_hash(length=6)}",
				"agent_id": f"temp_warn_{frappe.generate_hash(length=6)}",
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"ai_model": _model("_temp-no-fable-5", 0),
				"temperature": 0.3,
			}
		)
		doc.warn_unsupported_temperature()
		self.assertIn("does not accept a temperature", self._warnings())

		frappe.local.message_log = []
		doc.ai_model = _model("_temp-yes-sonnet-4-5", 1)
		doc.warn_unsupported_temperature()
		self.assertNotIn("does not accept a temperature", self._warnings())

	def test_a_map_shape_with_a_temperature_on_an_unsupported_model_warns(self):
		frappe.local.message_log = []
		xml = (
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
			'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
			'<bpmn:process id="p"><bpmn:serviceTask id="agent" name="Run the Agent" '
			'spiffworkflow:serviceType="ai_agent" spiffworkflow:aiModel="_temp-no-fable-5" '
			'spiffworkflow:aiTemperature="0.3" /></bpmn:process></bpmn:definitions>'
		)
		_model("_temp-no-fable-5", 0)
		doc = frappe.new_doc("BPMN Process Model")
		doc.bpmn_xml = xml
		doc.warn_unsupported_temperature()
		self.assertIn(
			"Run the Agent: AI Model _temp-no-fable-5 does not accept a temperature", self._warnings()
		)
