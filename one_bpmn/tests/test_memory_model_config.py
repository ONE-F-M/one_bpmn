# Copyright (c) 2026, one-fm and contributors
# WI-001793: memory settings live on the AI Agent Configuration, and the model
# that distills is chosen independently of the one that reconciles.
#
# Covers the resolver's config->shape overlay (including the two values that
# have no blank state and so must not clobber a diagram's older attributes),
# the dispatch-time precedence chain, and the distill/reconcile split.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import config_field_map
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D

AGENT = "ZZ WI1793 Memory Agent"
MODEL_CHAT = "ZZ-wi1793-chat"
MODEL_DISTILL = "ZZ-wi1793-distill"
MODEL_RECONCILE = "ZZ-wi1793-reconcile"
MODEL_GLOBAL = "ZZ-wi1793-global"


class TestMemoryModelConfig(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.credentials = frappe.db.get_value("AI Provider Credentials", {}, "name")

	def setUp(self):
		self._cleanup()
		for model in (MODEL_CHAT, MODEL_DISTILL, MODEL_RECONCILE, MODEL_GLOBAL):
			frappe.get_doc(
				{"doctype": "AI Model", "model_name": model, "ai_provider_credentials": self.credentials}
			).insert(ignore_permissions=True)
		self.agent = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": AGENT,
				"agent_id": "zz_wi1793_memory_agent",
				"agent_type": "Background",
				"agent_framework": "Direct API",
				"enabled": 1,
				"ai_model": MODEL_CHAT,
			}
		).insert(ignore_permissions=True)
		self._set_globals(None, None)

	def tearDown(self):
		self._set_globals(None, None)
		self._cleanup()
		frappe.db.commit()

	def _cleanup(self):
		frappe.db.delete("AI Agent Configuration", {"agent_name": AGENT})
		frappe.db.delete("AI Model", {"model_name": ("like", "ZZ-wi1793-%")})

	def _set_globals(self, distill, reconcile):
		frappe.db.set_single_value("Processa Settings", "default_memory_distill_model", distill)
		frappe.db.set_single_value("Processa Settings", "default_memory_reconcile_model", reconcile)
		frappe.clear_document_cache("Processa Settings", "Processa Settings")

	# ------------------------------------------------------------------
	# config -> shape overlay
	# ------------------------------------------------------------------
	def test_memory_fields_reach_the_dispatch_overlay(self):
		self.agent.db_set(
			{
				"conversation_store": "document_store",
				"context_max_messages": 12,
				"long_term_memory": "Enabled",
				"memory_scope": "Entity",
				"memory_write_mode": "distilled",
				"memory_distill_model": MODEL_DISTILL,
				"memory_reconcile_model": MODEL_RECONCILE,
			}
		)
		out = config_field_map(self.agent.name)

		self.assertEqual(out["aiConversationStore"], "document_store")
		self.assertEqual(out["aiContextMaxMessages"], 12)
		self.assertEqual(out["aiMemoryScope"], "Entity")
		self.assertEqual(out["aiMemoryWriteMode"], "distilled")
		self.assertEqual(out["aiMemoryDistillModel"], MODEL_DISTILL)
		self.assertEqual(out["aiMemoryReconcileModel"], MODEL_RECONCILE)

	def test_unset_memory_fields_do_not_override_the_diagram(self):
		"""Blank on the agent must fall through to the shape's older XML value."""
		out = config_field_map(self.agent.name)
		for key in (
			"aiConversationStore",
			"aiContextMaxMessages",
			"aiLongTermMemory",
			"aiMemoryScope",
			"aiMemoryWriteMode",
			"aiMemoryDistillModel",
			"aiMemoryReconcileModel",
		):
			self.assertNotIn(key, out, f"{key} must not be emitted when the agent leaves it blank")

		# Overlaying the config onto a configured shape leaves its memory keys
		# untouched (the overlay still carries the agent's non-memory fields).
		shape = {"aiConversationStore": "process_variable", "aiContextMaxMessages": 40}
		merged = {**shape, **out}
		self.assertEqual(merged["aiConversationStore"], "process_variable")
		self.assertEqual(merged["aiContextMaxMessages"], 40)

	def test_zero_context_window_is_treated_as_unset(self):
		"""Int has no blank state — 0 means 'not configured here', not 'zero messages'."""
		self.agent.db_set("context_max_messages", 0)
		self.assertNotIn("aiContextMaxMessages", config_field_map(self.agent.name))

	def test_long_term_memory_select_maps_onto_the_truthiness_check(self):
		self.agent.db_set("long_term_memory", "Enabled")
		self.assertTrue(D._cfg_truthy(config_field_map(self.agent.name)["aiLongTermMemory"]))

		self.agent.db_set("long_term_memory", "Disabled")
		self.assertFalse(D._cfg_truthy(config_field_map(self.agent.name)["aiLongTermMemory"]))

	def test_disabled_on_the_agent_overrides_an_enabled_diagram(self):
		"""The agent is authoritative — turning memory off must actually turn it off."""
		self.agent.db_set("long_term_memory", "Disabled")
		merged = {**{"aiLongTermMemory": "true"}, **config_field_map(self.agent.name)}
		self.assertFalse(D._cfg_truthy(merged["aiLongTermMemory"]))

	# ------------------------------------------------------------------
	# dispatch-time precedence
	# ------------------------------------------------------------------
	def test_precedence_agent_then_global_then_agent_model(self):
		key = "aiMemoryDistillModel"

		# 1. the value already overlaid from the agent (or the shape) wins
		self._set_globals(MODEL_GLOBAL, None)
		self.assertEqual(D._memory_model({key: MODEL_DISTILL}, key, MODEL_CHAT), MODEL_DISTILL)

		# 2. nothing on the agent -> the site-wide default
		self.assertEqual(D._memory_model({}, key, MODEL_CHAT), MODEL_GLOBAL)

		# 3. no default either -> the agent's own chat model (today's behaviour)
		self._set_globals(None, None)
		self.assertEqual(D._memory_model({}, key, MODEL_CHAT), MODEL_CHAT)

		# 4. nothing anywhere -> None, which distillation treats as "skip"
		self.assertIsNone(D._memory_model({}, key, None))

	def test_distill_and_reconcile_resolve_independently(self):
		self._set_globals(MODEL_GLOBAL, MODEL_RECONCILE)
		cfg = {"aiMemoryDistillModel": MODEL_DISTILL}

		self.assertEqual(D._memory_model(cfg, "aiMemoryDistillModel", MODEL_CHAT), MODEL_DISTILL)
		self.assertEqual(D._memory_model(cfg, "aiMemoryReconcileModel", MODEL_CHAT), MODEL_RECONCILE)

	def test_blank_string_on_the_shape_is_not_a_model(self):
		self._set_globals(None, None)
		self.assertEqual(
			D._memory_model({"aiMemoryDistillModel": "   "}, "aiMemoryDistillModel", MODEL_CHAT),
			MODEL_CHAT,
		)

	# ------------------------------------------------------------------
	# the distill / reconcile split in the worker
	# ------------------------------------------------------------------
	def test_reconciler_uses_its_own_model(self):
		from one_bpmn.agents.memory import writeback

		captured = {}

		def fake_distill(*args, **kwargs):
			captured["distill_model"] = kwargs.get("model")
			return [{"content": "a durable fact", "topic": "t"}]

		def fake_write(*args, **kwargs):
			captured["reconcile_ctx"] = kwargs.get("reconcile_ctx")
			return {"name": "MEM-1"}

		with patch("one_bpmn.agents.memory.distill.distill_memories", fake_distill), patch(
			"one_bpmn.agents.memory.tools.memory_write", fake_write
		):
			writeback.distill_and_write(
				agent_output="out",
				agent="Act_1",
				scope="Agent",
				scope_key="Act_1",
				provider_name="p",
				backend="direct_api",
				model=MODEL_DISTILL,
				reconcile_model=MODEL_RECONCILE,
				source_run=None,
			)

		self.assertEqual(captured["distill_model"], MODEL_DISTILL)
		self.assertEqual(captured["reconcile_ctx"]["model"], MODEL_RECONCILE)
		# Credentials still come from the task, not from the reconcile model.
		self.assertEqual(captured["reconcile_ctx"]["provider_name"], "p")
		self.assertEqual(captured["reconcile_ctx"]["backend"], "direct_api")

	# ------------------------------------------------------------------
	# End to end: the agent's setting is the model the write actually uses
	# ------------------------------------------------------------------
	def test_changing_the_agent_changes_the_model_the_write_calls(self):
		"""Full dispatch through the real overlay — the AC's 'verified' clause.

		Runs the AI Agent Task dispatcher against a linked agent and captures the
		job arguments the distiller is handed, then changes the agent's Memory
		Models and shows the next run calls different models. Nothing is stubbed
		between the agent record and the job arguments.
		"""
		from types import SimpleNamespace

		from one_bpmn.agents.executor import (
			ErrorCode,
			Executor,
			ExecutorResult,
			TokenUsage,
			register_executor,
		)

		class _Fake(Executor):
			def run(self, config, context):
				return ExecutorResult(
					output="the agent said something worth remembering",
					token_usage=TokenUsage(1, 2, 3),
					error_code=ErrorCode.SUCCESS,
				)

		register_executor("wi1793fake", _Fake)

		self.agent.db_set(
			{
				"long_term_memory": "Enabled",
				"memory_scope": "Agent",
				"memory_write_mode": "distilled",
				"memory_distill_model": MODEL_DISTILL,
				"memory_reconcile_model": MODEL_RECONCILE,
			}
		)

		enqueued = []
		for target, kwargs in (
			("one_bpmn.agents.observability.create_ai_run", {"return_value": SimpleNamespace(name="RUN-X", stub=False)}),
			("one_bpmn.agents.observability.record_ai_step", {}),
			("one_bpmn.agents.observability.finalize_ai_run", {}),
			("one_bpmn.agents.observability.finalize_ai_run_on_exception", {}),
			("one_bpmn.one_bpmn.engine.get_task_display_name", {"return_value": "AI Task"}),
			("frappe.db.commit", {}),
		):
			p = patch(target, **kwargs)
			p.start()
			self.addCleanup(p.stop)

		def run_once():
			enqueued.clear()
			with patch.object(D, "_enqueue_distill", side_effect=lambda **kw: enqueued.append(kw)):
				D.dispatch_ai_agent(
					SimpleNamespace(
						name="INST-WI1793",
						context_doctype="",
						context_docname="",
						process_model="",
						initiated_by="Administrator",
					),
					SimpleNamespace(data={}, task_spec=SimpleNamespace(bpmn_id="Act_M", name="Act_M")),
					{
						"aiBackend": "wi1793fake",
						"aiAgentConfig": self.agent.name,
						"aiSystemPrompt": "SYS",
						"aiUserPrompt": "remember this",
					},
					"Act_M",
				)
			return enqueued[0] if enqueued else None

		first = run_once()
		self.assertIsNotNone(first, "the distiller should have been enqueued")
		self.assertEqual(first["model"], MODEL_DISTILL)
		self.assertEqual(first["reconcile_model"], MODEL_RECONCILE)

		# Change the setting on the agent — nothing else — and re-dispatch.
		self.agent.db_set({"memory_distill_model": MODEL_GLOBAL, "memory_reconcile_model": MODEL_CHAT})
		frappe.clear_document_cache("AI Agent Configuration", self.agent.name)

		second = run_once()
		self.assertEqual(second["model"], MODEL_GLOBAL)
		self.assertEqual(second["reconcile_model"], MODEL_CHAT)

	def test_reconcile_model_defaults_to_the_distill_model(self):
		"""Omitting it preserves the behaviour that predates the split."""
		from one_bpmn.agents.memory import writeback

		captured = {}

		with patch(
			"one_bpmn.agents.memory.distill.distill_memories",
			lambda *a, **k: [{"content": "f", "topic": "t"}],
		), patch(
			"one_bpmn.agents.memory.tools.memory_write",
			lambda *a, **k: captured.update(ctx=k.get("reconcile_ctx")) or {"name": "MEM-1"},
		):
			writeback.distill_and_write(
				agent_output="out",
				agent="Act_1",
				scope="Agent",
				scope_key="Act_1",
				provider_name="p",
				backend="direct_api",
				model=MODEL_DISTILL,
				source_run=None,
			)

		self.assertEqual(captured["ctx"]["model"], MODEL_DISTILL)
