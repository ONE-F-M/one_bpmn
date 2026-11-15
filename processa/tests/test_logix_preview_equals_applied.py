# Copyright (c) 2026, one-fm and contributors
"""The script shown in the Logix reply is the script applied to the task, and a pagination request is a Baseline case."""

import json
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import tools
from processa.patches.v1_0 import seed_logix_pagination_case as seed
from processa.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn

CONV = "zz-logix-preview"
FINALIZE = f"Logix {chr(0x2013)} Tool Finalize"
FENCE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
SHOWN = 'employees = frappe.get_all("Employee")\nresult["employees"] = employees'
APPLIED = 'employees = frappe.get_all("Employee", limit_page_length=5)\nresult["employees"] = employees'


class TestReplyWithCode(FrappeTestCase):
	def test_the_code_block_is_replaced_by_the_applied_script(self):
		text = f"Done.\n\n```python\n{SHOWN}\n```\n\nIt lists employees."

		out = tools.reply_with_code(text, APPLIED)

		self.assertEqual(FENCE.search(out).group(1), APPLIED + "\n")
		self.assertTrue(out.startswith("Done.") and out.endswith("It lists employees."))

	def test_a_reply_without_a_block_gains_one(self):
		out = tools.reply_with_code("Here it is.", APPLIED)

		self.assertEqual(FENCE.search(out).group(1), APPLIED + "\n")

	def test_no_code_leaves_the_words_alone(self):
		self.assertEqual(tools.reply_with_code("Just words.", ""), "Just words.")


class TestFinalizeShowsTheAppliedScript(FrappeTestCase):
	"""Runs the site's Finalize script on a turn whose reply text and reviewed code differ."""

	def setUp(self):
		if not frappe.db.exists("Server Script", FINALIZE):
			self.skipTest("Logix is not on this site")
		self.script = frappe.db.get_value("Server Script", FINALIZE, "script")
		if "reply_with_code" not in self.script:
			self.skipTest("the site's Finalize script predates the preview sync")
		self.addCleanup(clear_turn, CONV)

	def test_the_reply_block_is_byte_identical_to_modified_script(self):
		set_turn(
			CONV,
			{
				"user_text": "add a limit of 5",
				"intent": "MODIFY",
				"original_script_content": SHOWN,
				"final": f"Limited to five.\n\n```python\n{SHOWN}\n```",
				"modified_code": APPLIED,
				"script_safe": True,
			},
		)
		try:
			exec(
				self.script, {"frappe": frappe, "context_docname": CONV, "result": {}, "bpmn_id": "finalize"}
			)
		except ImportError as e:
			self.skipTest(f"the site's Finalize script needs code not on this branch: {e}")

		output = get_turn(CONV)["output"]
		self.assertEqual(output["modified_script"], APPLIED)
		self.assertEqual(FENCE.search(output["response"]).group(1), APPLIED + "\n")
		self.assertIn("limit_page_length=5", output["diff"])


class TestPaginationCase(FrappeTestCase):
	def test_the_case_is_seeded_once_and_forbids_loops(self):
		if not frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "process_model"):
			self.skipTest("Logix is not on this site")

		seed.execute()
		seed.execute()

		cases = frappe.get_all("AI Eval Case", filters={"title": seed.TITLE}, pluck="name")
		self.assertEqual(len(cases), 1)
		case = frappe.get_doc("AI Eval Case", cases[0])
		values = [
			json.loads(a.value)["expected"] for a in case.assertions if a.assertion_type == "tool_artifact"
		]
		self.assertIn("limit_page_length", values)
		self.assertTrue(any("while" in v for v in values))
		self.assertEqual([c.tool_name for c in case.expected_tool_calls][-1], "finalize")
