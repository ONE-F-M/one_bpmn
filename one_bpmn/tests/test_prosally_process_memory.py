# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's stage prompts carry the memory of the Process the diagram is named after.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_process_memory
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D
from one_bpmn.one_bpmn.patches.v1_0 import prosally_stage_tools_read_process_memory as memory_patch

PROMOTION = "Zz Test Employee Promotion"
OFFBOARDING = "Zz Test Employee Offboarding"
ABSENCE = "Zz Test Absence"
OTHER_USER = "Guest"
BUILD_CONTEXT = f"ProsAlly {memory_patch.DASH} Build Context"


def _process(name):
	frappe.get_doc(
		{"doctype": "Process", "process_name": name, "description": name, "process_owner": "Administrator"}
	).insert(ignore_permissions=True)


def _process_row(process, content):
	frappe.get_doc(
		{
			"doctype": "AI Memory",
			"memory_scope": "Entity",
			"reference_doctype": "Process",
			"reference_name": process,
			"content": content,
		}
	).insert(ignore_permissions=True)


def _user_row(user, content):
	frappe.get_doc({"doctype": "AI Memory", "memory_scope": "User", "user": user, "content": content}).insert(
		ignore_permissions=True
	)


class TestProcessForDiagram(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_process(PROMOTION)

	def test_version_suffix_is_removed(self):
		self.assertEqual(helpers.process_for_diagram(PROMOTION + " - v1"), PROMOTION)
		self.assertEqual(helpers.process_for_diagram(PROMOTION + " - v12"), PROMOTION)

	def test_name_without_a_suffix_resolves(self):
		self.assertEqual(helpers.process_for_diagram(PROMOTION), PROMOTION)

	def test_name_matching_no_process_is_blank(self):
		self.assertEqual(helpers.process_for_diagram("Zz Made Up Process - v1"), "")
		self.assertEqual(helpers.process_for_diagram(""), "")


class TestRecall(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for name in (PROMOTION, OFFBOARDING, ABSENCE):
			_process(name)
		_process_row(PROMOTION, "promotion needs the board lane")
		_process_row(OFFBOARDING, "offboarding closes the badge")
		_process_row(ABSENCE, "absence needs a manager")
		_user_row("Administrator", "administrator prefers short names")
		_user_row(OTHER_USER, "guest prefers long names")

	def test_recall_is_the_process_plus_the_requesters_own_rows(self):
		recalled = helpers.recall_process_memory(PROMOTION + " - v1")
		self.assertEqual(recalled["memory_process"], PROMOTION)
		self.assertEqual(
			sorted(recalled["memory_notes"]),
			["administrator prefers short names", "promotion needs the board lane"],
		)

	def test_a_diagram_matching_no_process_recalls_only_the_preferences(self):
		recalled = helpers.recall_process_memory("Zz Made Up Process - v1")
		self.assertEqual(recalled, {"memory_process": "", "memory_notes": ["administrator prefers short names"]})

	def test_guest_with_no_process_recalls_nothing(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(
			helpers.recall_process_memory("Zz Made Up Process - v1"), {"memory_process": "", "memory_notes": []}
		)


class TestPrompt(FrappeTestCase):
	CFG: ClassVar[dict] = {"sub_prompts": {"modifier": {"prompt": "MODIFIER"}}, "constants": {}}
	TURN: ClassVar[dict] = {"memory_notes": ["promotion needs the board lane"]}

	def test_notes_sit_under_their_heading_after_the_sub_prompt(self):
		prompt = helpers.stage_system_prompt(self.CFG, "modifier", "modify_skills", self.TURN)
		self.assertTrue(prompt.startswith("MODIFIER\n\nNotes from earlier work on this process:"))
		self.assertIn("- promotion needs the board lane", prompt)
		self.assertNotIn("Offboarding", prompt)

	def test_without_notes_the_prompt_is_unchanged(self):
		self.assertEqual(helpers.stage_system_prompt(self.CFG, "modifier", "modify_skills"), "MODIFIER")
		turn = {"memory_notes": []}
		self.assertEqual(helpers.stage_system_prompt(self.CFG, "modifier", "modify_skills", turn), "MODIFIER")

	def test_blank_skills_constant_loads_no_skills(self):
		with patch.object(frappe, "get_all") as get_all:
			helpers.stage_system_prompt(self.CFG, "modifier", "", self.TURN)
		get_all.assert_not_called()


class TestQueueProcessMemory(FrappeTestCase):
	TURN: ClassVar[dict] = {
		"memory_process": PROMOTION,
		"user_text": "yes",
		"memory_notes": ["a note"],
		"chat_history": [],
	}

	def _queue(self, turn, intent):
		cfg = {"name": "CFG", "ai_model": "m", "ai_provider": "p"}
		with patch.object(helpers, "prosally_config", return_value=cfg), patch.object(
			D, "_enqueue_distill"
		) as enqueue:
			helpers.queue_process_memory(turn, {"intent": intent, "response": "Drew it."})
		return enqueue

	def test_a_drawn_or_changed_diagram_queues_a_write_keyed_to_the_process(self):
		for intent in ("BPMN_GENERATED", "BPMN_MODIFIED"):
			kwargs = self._queue(self.TURN, intent).call_args.kwargs
			self.assertEqual(kwargs["scope"], "Entity")
			self.assertEqual(kwargs["scope_key"], {"reference_doctype": "Process", "reference_name": PROMOTION})
			self.assertEqual(kwargs["user"], "Administrator")
			self.assertIn("Drew it.", kwargs["agent_output"])
			self.assertIn("a note", kwargs["exclude_context"])

	def test_other_turn_endings_write_nothing(self):
		for intent in ("CLARIFY", "IRRELEVANT", "CONFIRM", "CONFIRM_REMOVAL", "ERROR", "TOOL_ERROR", None):
			self._queue(self.TURN, intent).assert_not_called()

	def test_a_turn_with_no_process_writes_nothing(self):
		self._queue({**self.TURN, "memory_process": ""}, "BPMN_GENERATED").assert_not_called()

	def test_eval_runs_write_nothing(self):
		frappe.flags.eval_origin = True
		self.addCleanup(frappe.flags.pop, "eval_origin", None)
		self._queue(self.TURN, "BPMN_GENERATED").assert_not_called()


class TestStageToolsPatch(FrappeTestCase):
	SCRIPTS: ClassVar[dict] = {
		BUILD_CONTEXT: "x = 1\n# The AI Agent Task does tool-calling internally\nresult = 1\n",
		f"ProsAlly {memory_patch.DASH} Tool Classify Intent": (
			"if a:\n    pass\nelse:\n    _cfg = 1\n"
			'    data = extract_json(complete_sub_prompt(_cfg, "intent_classifier", prompt))\n'
		),
		f"ProsAlly {memory_patch.DASH} Tool Generate Process": (
			'_system = stage_system_prompt(_cfg, "process_generator", "generate_skills")\n'
		),
		f"ProsAlly {memory_patch.DASH} Tool Modify Process": (
			'_system = stage_system_prompt(_cfg, "modifier", "modify_skills")\n'
		),
		f"ProsAlly {memory_patch.DASH} Save Response": 'x = 1\nresult["response_saved"] = True\n',
	}

	def _run(self, scripts):
		store = dict(scripts)
		writes = []

		def get_value(doctype, name, *args, **kwargs):
			if doctype == "Server Script":
				return store[name]
			return "Prosally" if doctype == "AI Agent Configuration" else None

		def set_value(doctype, name, field, value=None, **kwargs):
			if doctype == "Server Script":
				store[name] = value
			writes.append((doctype, field))

		def exists(doctype, name=None):
			return name in store

		with patch.object(frappe.db, "exists", side_effect=exists), patch.object(
			frappe.db, "get_value", side_effect=get_value
		), patch.object(frappe.db, "set_value", side_effect=set_value), patch.object(
			frappe, "log_error"
		) as log_error:
			memory_patch.execute()
			memory_patch.execute()
		return store, writes, log_error

	def test_every_script_is_edited_once_and_still_compiles(self):
		store, writes, _ = self._run(self.SCRIPTS)
		self.assertEqual(len([w for w in writes if w[0] == "Server Script"]), len(self.SCRIPTS))
		for name, (marker, _anchor, _replacement) in memory_patch.EDITS.items():
			self.assertIn(marker, store[name])
			compile(store[name], name, "exec")

	def test_the_orchestrator_task_stops_using_memory(self):
		_, writes, _ = self._run(self.SCRIPTS)
		config_writes = [w for w in writes if w[0] == "AI Agent Configuration"]
		memory_off = {"long_term_memory": "Disabled", "memory_write_mode": "off"}
		self.assertEqual(config_writes[0], ("AI Agent Configuration", memory_off))

	def test_a_missing_anchor_is_logged_and_not_written(self):
		scripts = {name: "x = 1\n" for name in self.SCRIPTS}
		_, writes, log_error = self._run(scripts)
		self.assertEqual([w for w in writes if w[0] == "Server Script"], [])
		self.assertEqual(log_error.call_count, 2 * len(scripts))

	def test_build_context_lines_put_the_notes_in_the_turn(self):
		lines = memory_patch.EDITS[BUILD_CONTEXT][2].split("# The AI Agent Task")[0]
		recalled = {"memory_process": PROMOTION, "memory_notes": ["a note"]}
		scope = {"conversation_id": "CONV-1", "task_data": {"diagram_name": PROMOTION + " - v1"}}
		with patch.object(helpers, "recall_process_memory", return_value=recalled) as recall, patch(
			"one_bpmn.agents.turn_state.update_turn"
		) as update:
			exec(lines, scope)  # nosemgrep
		recall.assert_called_once_with(PROMOTION + " - v1")
		update.assert_called_once_with("CONV-1", **recalled)
