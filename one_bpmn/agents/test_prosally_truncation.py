"""
ProsAlly's modify_process / generate_process tool scripts must
read an explicit max_tokens from agent configuration (floored at 16384,
capped at the configured model's own ceiling) and must turn a truncated
completion into a real explanation instead of letting the finalize tool's
generic fallback question paper over it.

These tool bodies are inlined Server Script strings (see
one_bpmn/one_bpmn/patches/v1_0/inline_prosally_tool_scripts.py) rather than
importable functions, so they are tested the same way the platform runs
them: compiled and exec'd as flat top-level code against a stand-in
``result``/``context_docname`` namespace, with their own module-level
imports (get_turn, get_agent_config, get_llm_adapter_from_settings, ...)
patched so no real LLM call or BPMN compile happens.
"""

from unittest.mock import AsyncMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import shape_tools
from one_bpmn.agents.llm_provider.base import LLMTruncatedError
from one_bpmn.one_bpmn.patches.v1_0.inline_prosally_tool_scripts import (
	FINALIZE,
	GENERATE,
	MODIFY,
)


class TestProsAllyTruncationHandling(FrappeTestCase):
	def _run_script(self, body: str, context_docname="turn-1", extra_globals=None):
		ns = {"frappe": frappe, "context_docname": context_docname, "result": {}}
		if extra_globals:
			ns.update(extra_globals)
		exec(compile(body, "<prosally-tool>", "exec"), ns)
		return ns

	def _fake_adapter(self, *, raises=None, text="{}"):
		adapter = frappe._dict()
		if raises:
			adapter.complete = AsyncMock(side_effect=raises)
		else:
			adapter.complete = AsyncMock(return_value=frappe._dict(text=text))
		return adapter


	def test_modify_process_truncated_writes_size_explanation_not_fallback(self):
		turn = {
			"process_name": "Onboarding",
			"chat_history": [],
			"current_xml": "<bpmn/>",
		}
		captured_turns = {}

		def fake_update_turn(docname, **kwargs):
			captured_turns.update(kwargs)

		adapter = self._fake_adapter(raises=LLMTruncatedError("hit ceiling"))

		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
			patch("one_bpmn.agents.turn_state.update_turn", side_effect=fake_update_turn),
			patch(
				"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
				return_value={"sub_prompts": {}, "max_tokens": 1024, "agent_id": "prosally_agent"},
			),
			patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
		):
			ns = self._run_script(MODIFY)

		result = ns["result"]
		self.assertTrue(result.get("truncated"))
		self.assertFalse(result.get("modified"))
		self.assertIn("too large", result.get("response", "").lower())
		self.assertNotIn("tell me more about the process", result.get("response", ""))

		self.assertTrue(captured_turns.get("done"))
		self.assertEqual(captured_turns.get("output", {}).get("intent"), "CLARIFY")
		self.assertIn("too large", captured_turns["output"]["response"].lower())

	def test_finalize_does_not_overwrite_the_size_explanation(self):
		"""Once modify_process has closed the turn with done=True, finalize
		must report success without emitting its own generic question."""
		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value={"done": True}),
			patch("one_bpmn.agents.turn_state.update_turn") as mock_update,
		):
			ns = self._run_script(FINALIZE)

		self.assertTrue(ns["result"].get("finalized"))
		self.assertNotIn("fallback", ns["result"])
		mock_update.assert_not_called()


	def test_modify_process_uses_configured_max_tokens_above_floor(self):
		turn = {"process_name": "P", "chat_history": [], "current_xml": ""}
		adapter = self._fake_adapter(raises=LLMTruncatedError("still truncated"))

		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
			patch("one_bpmn.agents.turn_state.update_turn"),
			patch(
				"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
				return_value={"sub_prompts": {}, "max_tokens": 32000, "agent_id": "prosally_agent"},
			),
			patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
		):
			self._run_script(MODIFY)

		_, kwargs = adapter.complete.call_args
		self.assertEqual(kwargs.get("max_tokens"), 32000)

	def test_modify_process_floors_low_configured_max_tokens_at_16384(self):
		"""This is the exact regression from AI Agent Run bq30d9ujpm: agent
		config carried max_tokens=1024, and it must never reach the adapter
		unmodified."""
		turn = {"process_name": "P", "chat_history": [], "current_xml": ""}
		adapter = self._fake_adapter(raises=LLMTruncatedError("truncated"))

		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
			patch("one_bpmn.agents.turn_state.update_turn"),
			patch(
				"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
				return_value={"sub_prompts": {}, "max_tokens": 1024, "agent_id": "prosally_agent"},
			),
			patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
		):
			self._run_script(MODIFY)

		_, kwargs = adapter.complete.call_args
		self.assertEqual(kwargs.get("max_tokens"), 16384)

	def test_generate_process_uses_configured_max_tokens(self):
		turn = {"intent": "GENERATE_NEW", "process_name": "P", "chat_history": []}
		adapter = self._fake_adapter(raises=LLMTruncatedError("truncated"))

		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
			patch("one_bpmn.agents.turn_state.update_turn"),
			patch(
				"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
				return_value={"sub_prompts": {}, "max_tokens": 20000, "agent_id": "prosally_agent"},
			),
			patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
		):
			ns = self._run_script(GENERATE)

		_, kwargs = adapter.complete.call_args
		self.assertEqual(kwargs.get("max_tokens"), 20000)
		self.assertTrue(ns["result"].get("truncated"))
		self.assertIn("too large", ns["result"].get("response", "").lower())


	def test_modify_process_normal_completion_still_succeeds(self):
		"""A completion that returns cleanly (no LLMTruncatedError) must still
		reach the ordinary success path — the truncation handling must not
		interfere with the everyday case."""
		turn = {"process_name": "Onboarding", "chat_history": [], "current_xml": ""}
		captured_turns = {}

		def fake_update_turn(docname, **kwargs):
			captured_turns.update(kwargs)

		adapter = self._fake_adapter(text='{"nodes": [], "lanes": []}')

		fake_compile_result = {
			"xml": "<bpmn>ok</bpmn>",
			"problems": [],
			"ok": True,
			"topology": {},
			"layout": {},
			"normalizedIR": None,
		}

		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
			patch("one_bpmn.agents.turn_state.update_turn", side_effect=fake_update_turn),
			patch(
				"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
				return_value={"sub_prompts": {}, "max_tokens": 16384, "agent_id": "prosally_agent"},
			),
			patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
			patch("one_bpmn.agents.bpmn_ir_pipeline.compile_ir", return_value=fake_compile_result),
			patch("one_bpmn.agents.bpmn_ir_pipeline.extract_process_name", return_value="Onboarding"),
			patch("one_bpmn.agents.bpmn_ir_pipeline.extract_element_ids", return_value=""),
			patch("one_bpmn.security.bpmn_validator.validate_bpmn_xml", return_value={"valid": True}),
		):
			ns = self._run_script(MODIFY)

		result = ns["result"]
		self.assertFalse(result.get("truncated"))
		self.assertTrue(result.get("modified"))
		self.assertEqual(captured_turns.get("output", {}).get("intent"), "BPMN_MODIFIED")


class TestShapeToolGenericFailureCarriesException(FrappeTestCase):
	def test_generic_failure_includes_exception_class_and_message(self):
		"""The catch-all branch has to name the exception it caught.

		"See the Error Log" tells a model nothing it can act on, so it invents
		an explanation, and the one it invents is usually that the work is done.
		The permission and validation branches already carry their reason; this
		is the branch that did not.
		"""
		import json
		from unittest.mock import patch

		instance = frappe._dict({"_service_task_extensions": {}, "context_docname": None})
		task_cfg = {"serverScript": "Any Script"}

		# A missing script throws ValidationError, which an earlier branch
		# answers, so the trap has to be sprung at the call itself.
		with patch.object(shape_tools, "_run_server_script", side_effect=RuntimeError("chair not found")):
			raw = shape_tools.execute_shape(instance, "modify_process", task_cfg, {})

		payload = json.loads(raw)
		self.assertIn("modify_process", payload["error"])
		self.assertIn("RuntimeError", payload["error"])
		self.assertIn("chair not found", payload["error"])
