# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Docu's tool scripts use the shared helpers, and the editor's list of script names matches what scripts receive."""

from __future__ import annotations

import json
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.shape_tools import SCRIPT_NAMES, execute_shape
from one_bpmn.api.server_script_api import get_script_names
from one_bpmn.one_bpmn.engine import _make_script_engine
from one_bpmn.one_bpmn.patches.v1_0 import chat_agents_post_failed_turn_error as edits
from one_bpmn.one_bpmn.patches.v1_0 import docu_tool_scripts_use_shared_helpers as fix

CHAT_HISTORY = [{"role": "user", "content": f"message {n}"} for n in range(12)] + [
	{"type": "assistant", "content": "  a reply  "},
	{"role": "assistant", "content": ""},
	{"role": "user", "content": None},
]

REPLIES = [
	'{"question": "Which module?", "options": ["HR", "Ops"]}',
	'```json\n{"question": "Fenced?"}\n```',
	'Here you go: {"question": "In prose?", "options": []} thanks',
	"No JSON here at all.",
	"",
	None,
	"[1, 2, 3]",
]


def _run(block: str, **names) -> dict:
	namespace = {"json": json, "re": re, **names}
	exec(block, namespace)
	return namespace


class TestHistoryMatchesTheInlineCopy(FrappeTestCase):
	def test_docu_label_matches_both_inline_variants(self):
		for role in ("_role", "_role2"):
			inline = _run(fix.HISTORY_BLOCK.format(role=role), chat_history=CHAT_HISTORY)["_hist"]
			shared = _run(fix.HISTORY_CALL, chat_history=CHAT_HISTORY)["_hist"]
			self.assertEqual(shared, inline)
		self.assertIn("Docu: a reply", shared)

	def test_prosally_keeps_its_label_by_default(self):
		self.assertTrue(helpers.format_history(CHAT_HISTORY).endswith("ProsAlly: a reply"))


class TestJsonMatchesTheInlineCopy(FrappeTestCase):
	def test_every_reply_the_inline_copy_parsed_parses_the_same(self):
		for raw in REPLIES:
			inline = _run(fix.CLARIFY_JSON_BLOCK, raw=raw)["data"]
			shared = _run(fix.CLARIFY_JSON_CALL, raw=raw)["data"]
			expected = inline if isinstance(inline, dict) else None
			self.assertEqual(shared, expected, raw)

	def test_a_fence_holding_a_list_no_longer_hides_the_object_before_it(self):
		raw = '{"question": "Which form?"}\n```json\n[1, 2]\n```'
		self.assertEqual(_run(fix.CLARIFY_JSON_BLOCK, raw=raw)["data"], [1, 2])
		self.assertEqual(_run(fix.CLARIFY_JSON_CALL, raw=raw)["data"], {"question": "Which form?"})


class TestThePatchEdits(FrappeTestCase):
	def test_each_edit_applies_once(self):
		script = f"chat_history = []\n{fix.HISTORY_BLOCK.format(role='_role')}\nprompt = _hist\n"
		edited = edits.apply_edit(script, fix.HISTORY_BLOCK.format(role="_role"), fix.HISTORY_CALL)
		self.assertNotIn("_hlines", edited)
		self.assertEqual(
			edits.apply_edit(edited, fix.HISTORY_BLOCK.format(role="_role"), fix.HISTORY_CALL), edited
		)

	def test_a_script_without_the_block_is_not_edited(self):
		self.assertIsNone(edits.apply_edit("print(1)\n", fix.CLARIFY_JSON_BLOCK, fix.CLARIFY_JSON_CALL))


class _FakeTaskSpec:
	bpmn_id = "probe"
	name = "probe"


class _FakeTask:
	def __init__(self, data):
		self.data = data
		self.task_spec = _FakeTaskSpec()


class TestTheEditorListIsTrue(FrappeTestCase):
	def _probe_script(self, name: str) -> str:
		checks = "".join(
			f"try:\n    {n}\n    _seen.append({n!r})\nexcept NameError:\n    pass\n"
			for n, *_ in SCRIPT_NAMES
			if not n.startswith("<")
		)
		body = "_seen = []\n" + checks + 'result["seen"] = _seen\n'
		if not frappe.db.exists("Server Script", name):
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": name.lower().replace(" ", "_"),
					"script": body,
				}
			).insert(ignore_permissions=True)
		return name

	def _expected(self, column: int) -> list:
		return [row[0] for row in SCRIPT_NAMES if not row[0].startswith("<") and row[column]]

	def test_a_script_task_receives_exactly_its_listed_names(self):
		task = _FakeTask({})
		_make_script_engine()._run_frappe_server_script(self._probe_script("Script Names Probe"), task)
		self.assertEqual(task.data["seen"], self._expected(2))

	def test_an_agent_tool_receives_exactly_its_listed_names(self):
		instance = frappe._dict(_service_task_extensions={}, context_doctype="", context_docname="")
		out = json.loads(
			execute_shape(instance, "probe", {"serverScript": self._probe_script("Script Names Probe")}, {})
		)
		self.assertEqual(out["seen"], self._expected(3))


class TestTheNamesEndpoint(FrappeTestCase):
	def test_a_user_who_can_read_server_scripts_gets_the_list(self):
		names = {row["name"] for row in get_script_names()}
		self.assertTrue({"frappe", "task_data", "result", "shape_config"} <= names)

	def test_a_user_who_cannot_read_server_scripts_is_refused(self):
		with self.set_user("Guest"):
			self.assertRaises(frappe.PermissionError, get_script_names)
