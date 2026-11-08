# Copyright (c) 2026, one-fm and contributors
"""ProsAlly recalls a Process's memory from the process name when the diagram name does not arrive.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_recall_process_name
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_registry.definitions.prosally import helpers
from one_bpmn.one_bpmn.patches.v1_0 import prosally_recall_falls_back_to_process_name as name_patch
from one_bpmn.one_bpmn.patches.v1_0 import prosally_stage_tools_read_process_memory as memory_patch
from one_bpmn.tests.site_scripts import as_deployed

PROCESS = "Zz Test Fallback Process"
OTHER = "Zz Test Other Process"
BUILD_CONTEXT = f"ProsAlly {memory_patch.DASH} Build Context"
ON = {"long_term_memory": "Enabled", "memory_write_mode": "distilled"}


def _process(name):
	frappe.get_doc(
		{"doctype": "Process", "process_name": name, "description": name, "process_owner": "Administrator"}
	).insert(ignore_permissions=True)


class TestProcessForDiagram(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_process(PROCESS)
		_process(OTHER)

	def test_process_name_is_used_when_the_diagram_name_is_empty(self):
		self.assertEqual(helpers.process_for_diagram("", PROCESS), PROCESS)

	def test_process_name_is_used_when_the_diagram_name_matches_nothing(self):
		self.assertEqual(helpers.process_for_diagram("Zz Made Up - v1", PROCESS), PROCESS)

	def test_the_diagram_name_wins_when_it_matches(self):
		self.assertEqual(helpers.process_for_diagram(OTHER + " - v1", PROCESS), OTHER)

	def test_neither_matching_is_blank(self):
		self.assertEqual(helpers.process_for_diagram("Zz Made Up - v1", "Zz Also Made Up"), "")
		self.assertEqual(helpers.process_for_diagram("", ""), "")

	def test_a_call_with_only_the_diagram_name_still_works(self):
		self.assertEqual(helpers.process_for_diagram(PROCESS + " - v1"), PROCESS)


class TestRecallUsesTheProcessName(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_process(PROCESS)

	def test_an_empty_diagram_name_still_keys_the_turn_to_the_process(self):
		key = {"reference_doctype": "Process", "reference_name": PROCESS}
		with patch.object(helpers, "prosally_config", return_value={"name": "CFG"}), patch.object(helpers, "_memory_fields", return_value=ON
		), patch("one_bpmn.agents.memory.tools.memory_search", return_value=[{"content": "a rule"}]) as search:
			recalled = helpers.recall_process_memory("", PROCESS)
		self.assertEqual(recalled["memory_process"], PROCESS)
		self.assertEqual(recalled["memory_notes"], ["a rule"])
		self.assertEqual(search.call_args_list[0].args[:2], ("Entity", key))


class TestBuildContextPatch(FrappeTestCase):
	CODE = memory_patch.EDITS[BUILD_CONTEXT][2]

	def test_the_recall_call_gets_the_process_name_once(self):
		patched = name_patch.add_process_name(self.CODE)
		self.assertEqual(patched.count(name_patch.MARKER), 1)
		compile(patched, "Build Context", "exec")

	def test_the_patched_lines_pass_both_names_to_the_recall(self):
		lines = name_patch.add_process_name(self.CODE).split("# The AI Agent Task")[0]
		scope = {"conversation_id": "CONV-1", "task_data": {"diagram_name": "", "process_name": PROCESS}}
		with patch.object(helpers, "recall_process_memory", return_value={}) as recall, patch(
			"one_bpmn.processa_engine.agent_runtime.turn_state.update_turn"
		):
			exec(as_deployed(lines), scope)  # nosemgrep
		recall.assert_called_once_with("", PROCESS)

	def test_a_missing_anchor_is_none(self):
		self.assertIsNone(name_patch.add_process_name("x = 1\n"))

	def test_second_run_changes_nothing(self):
		store = {"script": self.CODE}
		writes = []

		def set_value(doctype, name, field, value=None, **kwargs):
			store["script"] = value
			writes.append(value)

		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", side_effect=lambda *a, **k: store["script"]
		), patch.object(frappe.db, "set_value", side_effect=set_value):
			name_patch.execute()
			name_patch.execute()
		self.assertEqual(len(writes), 1)

	def test_a_script_missing_the_anchor_is_logged_and_not_written(self):
		with patch.object(frappe.db, "exists", return_value=True), patch.object(
			frappe.db, "get_value", return_value="x = 1\n"
		), patch.object(frappe.db, "set_value") as set_value, patch.object(frappe, "log_error") as log_error:
			name_patch.execute()
		set_value.assert_not_called()
		log_error.assert_called_once()
