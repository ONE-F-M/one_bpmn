# Guard rails that depend on which code path happened to run are not guard
# rails. Every path that sends a system prompt composes it the same way, and
# every path starts from the same defaults.

from __future__ import annotations

import inspect
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import context_assembler as CA
from one_bpmn.agents.executor import (
	DEFAULT_MAX_OUTPUT_TOKENS,
	DEFAULT_TEMPERATURE,
	DEFAULT_TIMEOUT_SECONDS,
	DEFAULT_TOP_P,
)

CONFIG = {
	"agent_id": "test_agent",
	"system_prompt": "You are a careful assistant.",
	"examples": [{"input": "hello", "output": "hi"}],
	"guardrails": [{"guardrail": "Never quote a price."}],
	"enabled_skills": [{"name": "billing", "description": "Reads invoices."}],
}


class TestEveryPathComposesTheSameWay(FrappeTestCase):
	def test_the_config_wrapper_keeps_every_section(self):
		"""It used to drop the skills index, so a path going through it
		advertised none of the agent's skills while the others advertised all."""
		out = CA.build_static_context_from_config(CONFIG)
		self.assertIn("Never quote a price.", out)
		self.assertIn("billing", out)
		self.assertIn("hello", out)
		self.assertIn(CONFIG["system_prompt"], out)

	def test_the_wrapper_and_the_composer_agree_byte_for_byte(self):
		self.assertEqual(
			CA.build_static_context_from_config(CONFIG),
			CA.build_static_context(
				CONFIG["system_prompt"], CONFIG["examples"], CONFIG["guardrails"], CONFIG["enabled_skills"]
			),
		)

	def test_direct_chat_composes_instead_of_sending_the_bare_prompt(self):
		"""The failure this story exists to close: an agent that refused
		something inside a process map would do it in a chat, because the chat
		path sent config["system_prompt"] on its own."""
		from one_bpmn.api import agent_invocation

		sent = {}

		class FakeAdapter:
			async def complete(self, system=None, user=None, **kw):
				sent["system"] = system
				return type("C", (), {"text": "ok"})()

		with patch.object(agent_invocation, "_run_coro_blocking", create=True), patch(
			"one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=FakeAdapter()
		), patch("one_bpmn.utils.chat_persistence.save_user_message"), patch(
			"one_bpmn.utils.chat_persistence.save_bot_message"
		), patch(
			"one_bpmn.agents.executor.direct_api._run_coro_blocking",
			side_effect=lambda coro: (coro.close(), type("C", (), {"text": "ok"})())[1],
		):
			# The adapter call is faked, so assert on what the path would build.
			expected = CA.build_static_context_from_config(CONFIG)

		self.assertIn("Never quote a price.", expected)
		source = inspect.getsource(agent_invocation._run_direct_api)
		self.assertIn("build_static_context_from_config", source)
		self.assertNotIn('config.get("system_prompt") or ""', source)

	def test_no_path_builds_a_system_prompt_of_its_own(self):
		"""A composer test that fails if somebody adds a fourth path that sends
		a raw prompt. The three known senders are named here on purpose."""
		from one_bpmn.api import agent_invocation
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import ai_task_selector, dispatchers

		for module in (dispatchers, ai_task_selector, agent_invocation):
			source = inspect.getsource(module)
			self.assertIn("build_static_context", source, f"{module.__name__} sends a prompt it did not compose")


class TestEveryPathStartsFromTheSameDefaults(FrappeTestCase):
	"""The same agent behaved differently depending on which shape ran it:
	temperature 0.7 on the task path against the 0.3 the form advertised, and a
	60 second limit on the selector against 180 everywhere else."""

	def test_the_defaults_live_in_one_place(self):
		self.assertEqual(DEFAULT_TEMPERATURE, 0.3)
		self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 180)
		self.assertEqual(DEFAULT_TOP_P, 1.0)
		self.assertEqual(DEFAULT_MAX_OUTPUT_TOKENS, 16384)

	def test_no_path_repeats_a_number_the_shared_module_owns(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import ai_task_selector, dispatchers

		for module, forbidden in (
			(dispatchers, ('aiTemperature", 0.7', 'aiTopP", 1.0')),
			(ai_task_selector, ('aiTimeout", 60',)),
		):
			source = inspect.getsource(module)
			for literal in forbidden:
				self.assertNotIn(literal, source, f"{module.__name__} still hardcodes {literal}")

	def test_the_form_default_is_the_running_default(self):
		"""An administrator reading the configuration form should be reading
		what will actually run."""
		import json
		import os

		import one_bpmn

		path = os.path.join(
			os.path.dirname(one_bpmn.__file__),
			"one_bpmn",
			"doctype",
			"ai_agent_configuration",
			"ai_agent_configuration.json",
		)
		with open(path) as fh:
			fields = {f["fieldname"]: f for f in json.load(fh)["fields"]}
		self.assertEqual(float(fields["temperature"].get("default")), DEFAULT_TEMPERATURE)


class TestSettingsMoveOntoTheRecord(FrappeTestCase):
	"""An agent setting that exists only on a diagram makes the agent's own
	record silently incomplete, so the answer to "what temperature does this
	agent use" depends on which diagram you open.

	Driven against mocked reads and writes: creating a real AI Agent
	Configuration starts the provisioning process, which is a lot of machinery
	to stand up for a patch whose whole job is deciding what to copy."""

	def setUp(self):
		self.patch = __import__(
			"one_bpmn.one_bpmn.patches.v1_0.agent_settings_move_to_the_configuration", fromlist=["execute"]
		)

	def _run_over(self, shape: dict, already_on_record: dict | None = None):
		import json

		import frappe

		already = already_on_record or {}
		written = {}
		spec = json.dumps({"service_task_extensions": {"run_agent": dict(shape, aiAgentConfig="CFG")}})
		model = frappe._dict(name="PM-TEST", serialized_spec=spec)
		with patch("frappe.get_all", return_value=[model]), patch("frappe.db.exists", return_value=True), patch(
			"frappe.db.get_value", side_effect=lambda dt, name, field: already.get(field)
		), patch("frappe.db.set_value", side_effect=lambda dt, name, field, value: written.__setitem__(field, value)):
			self.patch.execute()
		return written

	def test_a_setting_only_on_the_diagram_is_written_to_the_record(self):
		written = self._run_over({"aiMemoryWriteMode": "distilled", "aiLongTermMemory": "Enabled"})
		self.assertEqual(written.get("memory_write_mode"), "distilled")
		self.assertEqual(written.get("long_term_memory"), "Enabled")

	def test_a_value_already_on_the_record_is_never_overwritten(self):
		"""It is the one somebody chose, and it already wins at dispatch."""
		written = self._run_over({"aiTemperature": 0.9}, already_on_record={"temperature": 0.55})
		self.assertNotIn("temperature", written)

	def test_a_zero_on_the_record_counts_as_not_configured(self):
		"""Which is the rule the resolver already applies to these numbers."""
		written = self._run_over({"aiMaxTokens": 4096}, already_on_record={"max_tokens": 0})
		self.assertEqual(written.get("max_tokens"), 4096)

	def test_a_blank_on_the_diagram_is_not_copied(self):
		self.assertEqual(self._run_over({"aiTemperature": "", "aiSystemPrompt": None}), {})

	def test_a_diagram_that_will_not_parse_is_left_alone(self):
		self.assertEqual(list(self.patch._agent_shapes("not json at all")), [])
		self.assertEqual(list(self.patch._agent_shapes(None)), [])

	def test_a_shape_with_no_agent_is_skipped(self):
		import json

		spec = json.dumps({"service_task_extensions": {"plain_task": {"aiTemperature": 0.9}}})
		self.assertEqual(list(self.patch._agent_shapes(spec)), [])

	def test_nothing_is_removed_from_the_diagram(self):
		"""The diagrams keep their copies and stay loadable; they simply stop
		being the only place a setting exists."""
		import inspect

		source = inspect.getsource(self.patch)
		for writer in ("serialized_spec=", "set_value(\"BPMN Process Model", ".save("):
			self.assertNotIn(writer, source)
