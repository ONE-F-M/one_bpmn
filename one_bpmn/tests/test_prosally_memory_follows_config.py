# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's process memory is controlled by its AI Agent Configuration.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_memory_follows_config
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D
from one_bpmn.one_bpmn.patches.v1_0 import prosally_memory_follows_agent_configuration as config_patch

ON = {"long_term_memory": "Enabled", "memory_write_mode": "distilled"}
TURN = {"memory_process": "Zz Process", "user_text": "yes", "memory_notes": [], "chat_history": []}
DRAWN = {"intent": "BPMN_GENERATED", "response": "Drew it."}


class TestRecallFollowsTheConfiguration(FrappeTestCase):
	def _recall(self, fields):
		with patch.object(helpers, "prosally_config", return_value={"name": "CFG"}), patch.object(
			helpers, "_memory_fields", return_value=fields
		), patch.object(helpers, "process_for_diagram", return_value="Zz Process"), patch(
			"one_bpmn.agents.memory.tools.memory_search", return_value=[{"content": "a note"}]
		) as search:
			return helpers.recall_process_memory("Zz Process - v1"), search

	def test_long_term_memory_disabled_recalls_nothing(self):
		recalled, search = self._recall({"long_term_memory": "Disabled", "memory_write_mode": "distilled"})
		self.assertEqual(recalled, {"memory_process": "", "memory_notes": []})
		search.assert_not_called()

	def test_a_blank_setting_recalls_nothing(self):
		recalled, search = self._recall({})
		self.assertEqual(recalled["memory_notes"], [])
		search.assert_not_called()

	def test_the_token_budget_comes_from_the_configuration(self):
		with patch.object(D, "_bound_memories_to_budget", side_effect=lambda rows, budget: rows) as bound:
			self._recall({**ON, "memory_token_budget": 50})
		self.assertEqual(bound.call_args.args[1], 50)

	def test_a_zero_budget_uses_the_default(self):
		with patch.object(D, "_bound_memories_to_budget", side_effect=lambda rows, budget: rows) as bound:
			self._recall({**ON, "memory_token_budget": 0})
		self.assertEqual(bound.call_args.args[1], D.DEFAULT_MEMORY_TOKEN_BUDGET)


class TestWriteFollowsTheConfiguration(FrappeTestCase):
	def _queue(self, fields):
		cfg = {"name": "CFG", "ai_model": "agent-model", "ai_provider": "p"}
		with patch.object(helpers, "prosally_config", return_value=cfg), patch.object(
			helpers, "_memory_fields", return_value=fields
		), patch.object(D, "_enqueue_distill") as enqueue:
			helpers.queue_process_memory(TURN, DRAWN)
		return enqueue

	def test_distilled_writes_queue(self):
		self._queue(ON).assert_called_once()

	def test_write_mode_off_or_raw_writes_nothing(self):
		for mode in ("off", "raw", "", None):
			self._queue({**ON, "memory_write_mode": mode}).assert_not_called()

	def test_the_models_come_from_the_configuration(self):
		fields = {**ON, "memory_distill_model": "distill-x", "memory_reconcile_model": "reconcile-y"}
		kwargs = self._queue(fields).call_args.kwargs
		self.assertEqual((kwargs["model"], kwargs["reconcile_model"]), ("distill-x", "reconcile-y"))

	def test_unset_models_fall_back_to_the_agents_own(self):
		with patch.object(frappe.db, "get_single_value", return_value=None):
			kwargs = self._queue(ON).call_args.kwargs
		self.assertEqual((kwargs["model"], kwargs["reconcile_model"]), ("agent-model", "agent-model"))


class TestOrchestratorSkipsMemory(FrappeTestCase):
	INSTANCE = SimpleNamespace(context_doctype="Chat Conversation", context_docname="CONV-1")

	def test_blank_keys_stop_the_dispatcher_under_entity_scope(self):
		task_data = {"memory_reference_doctype": "", "memory_reference_name": ""}
		self.assertIsNone(D._resolve_memory_target({"aiMemoryScope": "Entity"}, self.INSTANCE, "run", task_data))

	def test_without_the_keys_the_conversation_would_be_the_key(self):
		target = D._resolve_memory_target({"aiMemoryScope": "Entity"}, self.INSTANCE, "run", {})
		self.assertEqual(target[1]["reference_name"], "CONV-1")


class TestConfigurationPatch(FrappeTestCase):
	CODE = "x = 1\n# The AI Agent Task does tool-calling internally\nresult = 1\n"

	def _run(self, code, budget):
		store = {"script": code}
		config_writes = []

		def get_value(doctype, name, field=None, *args, **kwargs):
			if doctype == "Server Script":
				return store["script"]
			return budget if field == "memory_token_budget" else "Prosally"

		def set_value(doctype, name, field, value=None, **kwargs):
			if doctype == "Server Script":
				store["script"] = value
			else:
				config_writes.append(field)

		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", side_effect=get_value
		), patch.object(frappe.db, "set_value", side_effect=set_value), patch.object(
			frappe, "log_error"
		) as log_error:
			config_patch.execute()
			config_patch.execute()
		return store["script"], config_writes, log_error

	def test_blank_keys_are_added_once_and_the_script_compiles(self):
		script, _, _ = self._run(self.CODE, 0)
		self.assertEqual(script.count("memory_reference_name"), 1)
		compile(script, "Build Context", "exec")

	def test_the_agent_is_set_to_entity_scope_and_distilled_writes(self):
		_, config_writes, _ = self._run(self.CODE, 0)
		self.assertEqual(
			config_writes[0],
			{
				"long_term_memory": "Enabled",
				"memory_scope": "Entity",
				"memory_write_mode": "distilled",
				"memory_token_budget": 800,
			},
		)

	def test_an_existing_token_budget_is_kept(self):
		_, config_writes, _ = self._run(self.CODE, 1200)
		self.assertNotIn("memory_token_budget", config_writes[0])

	def test_a_missing_anchor_is_logged_and_not_written(self):
		script, _, log_error = self._run("x = 1\n", 0)
		self.assertEqual(script, "x = 1\n")
		self.assertEqual(log_error.call_count, 2)
