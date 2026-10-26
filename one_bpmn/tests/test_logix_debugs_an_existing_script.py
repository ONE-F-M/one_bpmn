# Copyright (c) 2026, one-fm and contributors
"""A request to fix a failing script gets a diagnosis and a diff against that script, not a new script."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import logix_debug
from one_bpmn.agents.llm_provider.base import StepResult
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import logix_debugs_an_existing_script as p

CONV = "zz-logix-debug"
PASTED = 'rate = doc.grand_total / doc.total_qty\nresult["rate"] = rate'
FIXED = 'rate = doc.grand_total / doc.total_qty if doc.total_qty else 0\nresult["rate"] = rate'
TRACE = 'Traceback (most recent call last):\n  File "<string>", line 1\nZeroDivisionError: division by zero'
USER_TEXT = f"this script fails when I generate the invoice\n```python\n{PASTED}\n```\n{TRACE}"

BUILD_CONTEXT_STUB = """from one_bpmn.agents.turn_state import set_turn
set_turn(conversation_id, {
    "user_text": task_data.get("user_text", "") or "",
    "process_context": task_data.get("process_context") or {},
})
"""


class FakeAdapter:
	def __init__(self, *replies):
		self.replies = list(replies)
		self.prompts = []
		self.schemas = []

	async def step(self, system, transcript, response_schema=None, **kwargs):
		self.prompts.append(transcript[0]["content"])
		self.schemas.append(response_schema)
		return StepResult(content=json.dumps(self.replies.pop(0)))


class TestLogixDebugsAnExistingScript(FrappeTestCase):
	def setUp(self):
		self.addCleanup(clear_turn, CONV)
		set_turn(CONV, {"user_text": USER_TEXT, **logix_debug.debug_inputs(USER_TEXT, "", "")})

	def _run(self, adapter):
		with (
			patch.object(logix_debug, "get_agent_config", return_value={}),
			patch.object(logix_debug, "get_llm_adapter_from_settings", return_value=adapter),
		):
			logix_debug.run_debug_stage(CONV)
		return get_turn(CONV)["output"]

	def test_the_reply_is_a_diff_against_the_pasted_script(self):
		adapter = FakeAdapter(
			{"explanation": "It divides by a quantity of zero.", "fixed_script": FIXED},
			{"approved": True, "issues": [], "suggestions": []},
		)
		output = self._run(adapter)

		self.assertEqual(output["intent"], "MODIFY")
		self.assertEqual(output["original_script"], PASTED)
		self.assertIn("--- your script", output["diff"])
		self.assertIn("-rate = doc.grand_total / doc.total_qty\n", output["diff"])
		self.assertIn("+rate = doc.grand_total / doc.total_qty if doc.total_qty else 0\n", output["diff"])
		self.assertIn("ZeroDivisionError", adapter.prompts[0])
		self.assertIn("```diff", adapter.prompts[1])
		self.assertNotIn("```python", adapter.prompts[1])

	def test_both_model_calls_send_a_closed_schema(self):
		adapter = FakeAdapter(
			{"explanation": "It divides by a quantity of zero.", "fixed_script": FIXED},
			{"approved": True, "issues": [], "suggestions": []},
		)
		self._run(adapter)

		self.assertEqual(len(adapter.schemas), 2)
		for schema in adapter.schemas:
			self.assertIs(schema["additionalProperties"], False)

	def test_a_fix_the_gate_blocks_is_not_offered(self):
		adapter = FakeAdapter(
			{
				"explanation": "It divides by zero.",
				"fixed_script": FIXED + "\ndoc.save(ignore_permissions=True)",
			},
			{"approved": True, "issues": [], "suggestions": []},
		)
		output = self._run(adapter)

		self.assertIsNone(output["modified_script"])
		self.assertIn("does not pass review", output["response"])
		self.assertIn("line 3: `doc.save(ignore_permissions=True)`", output["response"])

	def test_a_fix_the_reviewer_rejects_is_not_offered(self):
		adapter = FakeAdapter(
			{"explanation": "It divides by zero.", "fixed_script": FIXED},
			{"approved": False, "issues": ["The fix hides a missing quantity."], "suggestions": []},
		)
		output = self._run(adapter)

		self.assertIsNone(output["diff"])
		self.assertIn("The fix hides a missing quantity.", output["response"])

	def test_the_linked_script_and_its_logged_error_are_used_when_nothing_is_pasted(self):
		frappe.get_doc(
			{
				"doctype": "Error Log",
				"method": logix_debug.ENGINE_ERROR_TITLE.format("ZZ Rate"),
				"error": TRACE,
			}
		).insert(ignore_permissions=True)
		inputs = logix_debug.debug_inputs("it shows a white screen then fails", PASTED, "ZZ Rate")

		self.assertEqual(inputs, {"script_text": PASTED, "last_error": TRACE})


class TestLogixDebugPatch(FrappeTestCase):
	def test_build_context_puts_the_script_and_its_error_on_the_turn(self):
		if not frappe.db.exists("Server Script", p.BUILD_CONTEXT):
			self.skipTest(f"{p.BUILD_CONTEXT} is not on this site")
		frappe.db.set_value("Server Script", p.BUILD_CONTEXT, "script", BUILD_CONTEXT_STUB)
		self.addCleanup(clear_turn, CONV)
		p._edit_text(
			"Server Script", p.BUILD_CONTEXT, "script", p.BUILD_CONTEXT_MARKER, p.BUILD_CONTEXT_EDITS
		)

		exec(
			frappe.db.get_value("Server Script", p.BUILD_CONTEXT, "script"),
			{"conversation_id": CONV, "task_data": {"user_text": USER_TEXT}},
		)
		turn = get_turn(CONV)
		self.assertEqual(turn["script_text"], PASTED)
		self.assertTrue(turn["last_error"].startswith("Traceback"))

	def test_the_map_edits_apply_once(self):
		xml = (
			"&#34;enum&#34;: [&#34;CREATE&#34;, &#34;MODIFY&#34;, &#34;DISAMBIGUATE&#34;] "
			"&#34;enum&#34;: [&#34;clarify&#34;, &#34;write_script&#34;, &#34;write_agent_tool&#34;] "
			"<bpmn:completionCondition /></bpmndi:BPMNPlane>"
		)
		for old, new in p.MAP_EDITS:
			xml = xml.replace(old, new, 1)

		self.assertIn("&#34;DEBUG_EXISTING&#34;", xml)
		self.assertIn("&#34;debug_script&#34;]", xml)
		self.assertEqual(xml.count(p.MAP_MARKER), 1)
		self.assertIn('bpmnElement="debug_script"', xml)
