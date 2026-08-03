# Copyright (c) 2026, one-fm and contributors
# WI-001639: the dispatcher must assemble the frozen static context from the
# LINKED AI Agent Configuration — instructions from the shape, examples and
# guard rails from the agent — and must leave a shape with no linked config
# byte-for-byte unchanged.

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.context_assembler import EXAMPLES_HEADER, GUARDRAILS_HEADER
from one_bpmn.agents.executor import (
	ErrorCode,
	Executor,
	ExecutorResult,
	TokenUsage,
	register_executor,
)
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D

_CAPTURED = {}


class _CaptureExecutor(Executor):
	def run(self, config, context):
		_CAPTURED["config"] = config
		return ExecutorResult(
			output="ok", token_usage=TokenUsage(1, 2, 3), error_code=ErrorCode.SUCCESS
		)


register_executor("statictest", _CaptureExecutor)


def _instance():
	return SimpleNamespace(
		name="INST-S",
		context_doctype="",
		context_docname="",
		process_model="",
		initiated_by="Administrator",
	)


def _task(bpmn="Act_1"):
	return SimpleNamespace(data={}, task_spec=SimpleNamespace(bpmn_id=bpmn, name=bpmn))


BEHAVIOUR = {
	"examples": [{"input": "an example input", "expected_output": "an example output"}],
	"guardrails": [{"guardrail": "Keep files under 300 lines.", "category": "Code Quality"}],
}


class TestDispatcherStaticContext(FrappeTestCase):
	def setUp(self):
		_CAPTURED.clear()
		patches = [
			patch(
				"one_bpmn.agents.observability.create_ai_run",
				return_value=SimpleNamespace(name="RUN-FAKE", stub=True),
			),
			patch("one_bpmn.agents.observability.record_ai_step"),
			patch("one_bpmn.agents.observability.finalize_ai_run"),
			patch("one_bpmn.agents.observability.finalize_ai_run_on_exception"),
			patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="AI Task"),
			patch("frappe.db.commit"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def _dispatch(self, task_cfg, behaviour=None):
		# resolve_dispatch_overrides (WI-001637) makes a linked configuration
		# authoritative for the system prompt, so on a site where the linked
		# agent really exists it would replace "SYS" with that agent's stored
		# prompt. Neutralise it: these tests are about what the static-context
		# assembly ADDS, not about which prompt wins.
		with patch(
			"one_bpmn.agents.agent_config_resolver.resolve_dispatch_overrides", return_value={}
		), patch(
			"one_bpmn.agents.context_assembler.load_agent_behaviour",
			return_value=behaviour or {},
		):
			D.dispatch_ai_agent(_instance(), _task(), task_cfg, "Act_1")
		return _CAPTURED["config"]

	def test_no_linked_config_leaves_the_prompt_untouched(self):
		"""The regression guard for every existing agent: without a linked
		configuration the system prompt is exactly the shape's own prompt."""
		config = self._dispatch({"aiBackend": "statictest", "aiSystemPrompt": "SYS", "aiUserPrompt": "U"})

		self.assertEqual(config.system_prompt, "SYS")

	def test_linked_config_with_no_rows_leaves_the_prompt_untouched(self):
		config = self._dispatch(
			{"aiBackend": "statictest", "aiSystemPrompt": "SYS", "aiUserPrompt": "U", "aiAgentConfig": "logix"},
			behaviour={"examples": [], "guardrails": []},
		)

		self.assertEqual(config.system_prompt, "SYS")

	def test_examples_and_guardrails_are_appended_in_order(self):
		config = self._dispatch(
			{"aiBackend": "statictest", "aiSystemPrompt": "SYS", "aiUserPrompt": "U", "aiAgentConfig": "logix"},
			behaviour=BEHAVIOUR,
		)
		sp = config.system_prompt

		self.assertIn("Keep files under 300 lines.", sp)
		self.assertIn("an example input", sp)
		self.assertLess(sp.index("SYS"), sp.index(EXAMPLES_HEADER))
		self.assertLess(sp.index(EXAMPLES_HEADER), sp.index(GUARDRAILS_HEADER))

	def test_behaviour_lookup_failure_degrades_to_the_plain_prompt(self):
		"""A broken or deleted configuration must not take the agent down."""
		with patch(
			"one_bpmn.agents.agent_config_resolver.resolve_dispatch_overrides", return_value={}
		), patch(
			"one_bpmn.agents.context_assembler.load_agent_behaviour",
			side_effect=Exception("boom"),
		), patch(
			"frappe.log_error"
		):
			D.dispatch_ai_agent(
				_instance(),
				_task(),
				{
					"aiBackend": "statictest",
					"aiSystemPrompt": "SYS",
					"aiUserPrompt": "U",
					"aiAgentConfig": "gone",
				},
				"Act_1",
			)

		self.assertEqual(_CAPTURED["config"].system_prompt, "SYS")


class TestLiveLogixShape(FrappeTestCase):
	"""Against the REAL deployed Logix map + the seeded guard rails, not a
	fixture: the rules must reach the system prompt and memory must not.
	Skipped on a site where Logix is not deployed."""

	MODEL = "Logix – Script Task Agent"
	SHAPE = "run_logix_agent"

	def _live_task_cfg(self):
		import json

		spec = frappe.db.get_value("BPMN Process Model", self.MODEL, "serialized_spec")
		if not spec:
			return None
		cfg = (json.loads(spec).get("service_task_extensions") or {}).get(self.SHAPE)
		if not cfg or not cfg.get("aiAgentConfig"):
			return None
		cfg = dict(cfg)
		cfg["aiBackend"] = "statictest"
		# Tool shapes need a live workflow instance to compile; the prompt
		# assembly under test does not depend on them.
		cfg.pop("aiToolShapes", None)
		return cfg

	def setUp(self):
		_CAPTURED.clear()
		patches = [
			patch(
				"one_bpmn.agents.observability.create_ai_run",
				return_value=SimpleNamespace(name="RUN-LIVE", stub=True),
			),
			patch("one_bpmn.agents.observability.record_ai_step"),
			patch("one_bpmn.agents.observability.finalize_ai_run"),
			patch("one_bpmn.one_bpmn.engine.get_task_display_name", return_value="Call Agent"),
			patch("frappe.db.commit"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def test_seeded_guardrails_reach_the_prompt_and_memory_does_not(self):
		task_cfg = self._live_task_cfg()
		if task_cfg is None:
			self.skipTest(f"'{self.MODEL}' is not deployed on this site")

		# Logix has aiMemoryAutoWrite on, and distillation runs its own executor
		# call AFTER the agent's — which would overwrite the captured config
		# with the distiller's prompt. Silence it: this test is about the agent
		# call.
		with patch(
			"one_bpmn.agents.memory.tools.memory_search",
			return_value=[{"content": "prefers frappe.sendmail"}],
		), patch.object(D, "_enqueue_distill"):
			D.dispatch_ai_agent(_instance(), _task(self.SHAPE), task_cfg, self.SHAPE)

		config = _CAPTURED["config"]
		self.assertIn(GUARDRAILS_HEADER, config.system_prompt)
		self.assertNotIn("Relevant memory:", config.system_prompt)
		if task_cfg.get("aiLongTermMemory"):
			self.assertIn("Relevant memory:", config.user_prompt)


class TestConfiguratorKnowsTheNewFields(FrappeTestCase):
	"""WI-001639: the AI Assistant learns the config contract from live data,
	so the new fields must be IN that data and must survive its sanitiser."""

	def test_create_payload_contract_advertises_both_fields(self):
		from one_bpmn.agents.agent_config_resolver import CREATE_PAYLOAD_CONTRACT

		self.assertIn("examples", CREATE_PAYLOAD_CONTRACT)
		self.assertIn("guardrails", CREATE_PAYLOAD_CONTRACT)

	def test_prerequisites_block_surfaces_them_to_the_assistant(self):
		from one_bpmn.api.ai_assistant import _creation_prerequisites_block

		block = _creation_prerequisites_block()

		self.assertIn("guardrails", block)
		self.assertIn("examples", block)

	def test_sanitizer_keeps_well_formed_rows(self):
		from one_bpmn.api.ai_assistant import _sanitize_proposed_config

		clean = _sanitize_proposed_config({
			"agent_name": "ZZ Static Ctx Sanitizer Probe",
			"agent_id": "zz_static_ctx_sanitizer_probe",
			"chat_mode_label": "ZZ Static Ctx",
			"examples": [{"input": "in", "expected_output": "out", "note": "why"}],
			"guardrails": [{"guardrail": "Be brief.", "category": "Output Format"}],
		})

		self.assertEqual(clean["examples"], [{"input": "in", "expected_output": "out", "note": "why"}])
		self.assertEqual(clean["guardrails"], [{"guardrail": "Be brief.", "category": "Output Format"}])

	def test_sanitizer_drops_rows_missing_their_mandatory_field(self):
		from one_bpmn.api.ai_assistant import _sanitize_proposed_config

		clean = _sanitize_proposed_config({
			"agent_name": "ZZ Static Ctx Sanitizer Probe 2",
			"agent_id": "zz_static_ctx_sanitizer_probe_2",
			"examples": [{"expected_output": "orphan"}, "not-a-dict"],
			"guardrails": [{"category": "Safety"}],
		})

		self.assertNotIn("examples", clean)
		self.assertNotIn("guardrails", clean)

	def test_unknown_guardrail_category_falls_back_to_other(self):
		"""An invented category must not fail Select validation and lose the
		whole agent — the rule is worth more than its label."""
		from one_bpmn.agents.agent_config_resolver import _GUARDRAIL_CATEGORIES

		self.assertIn("Other", _GUARDRAIL_CATEGORIES)
		self.assertNotIn("Made Up", _GUARDRAIL_CATEGORIES)
