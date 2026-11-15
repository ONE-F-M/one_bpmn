# Copyright (c) 2026, one-fm and contributors
"""Logix refuses only when a written script failed the gate, asks what is missing otherwise, and reverts from history."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import tools
from processa.patches.v1_0 import seed_logix_refusal_regression_cases as seed
from processa.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn

CONV = "zz-logix-gate"
FINALIZE = f"Logix {chr(0x2013)} Tool Finalize"
FIRST = 'result["count"] = 1'
SECOND = 'result["count"] = 2'


class TestRevertOutput(FrappeTestCase):
	def setUp(self):
		self.addCleanup(clear_turn, CONV)
		frappe.set_user("Administrator")
		name = "ZZ Revert Probe " + frappe.generate_hash(length=6)
		self.script = frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": name,
				"script": FIRST,
			}
		).insert()
		self.addCleanup(frappe.delete_doc, "Server Script", name, force=True)

	def test_the_previous_version_comes_back_as_a_diff_to_apply(self):
		self.script.script = SECOND
		self.script.save(ignore_version=False)  # the test runner skips versions by default
		set_turn(CONV, {"current_script": self.script.name})

		result = tools.revert_output(CONV)

		output = get_turn(CONV)["output"]
		self.assertTrue(result["has_fix"])
		self.assertEqual(output["intent"], "MODIFY")
		self.assertEqual(output["modified_script"], FIRST)
		self.assertEqual(output["original_script"], SECOND)
		self.assertIn("-" + SECOND, output["diff"])
		self.assertIn("+" + FIRST, output["diff"])
		self.assertIn("Apply it to put it back", output["response"])

	def test_a_script_without_history_says_so(self):
		set_turn(CONV, {"current_script": self.script.name})

		tools.revert_output(CONV)

		output = get_turn(CONV)["output"]
		self.assertEqual(output["intent"], "REVERT")
		self.assertIsNone(output["modified_script"])
		self.assertIn("no earlier version", output["response"])

	def test_no_linked_script_means_nothing_to_revert(self):
		set_turn(CONV, {"current_script": ""})

		tools.revert_output(CONV)

		self.assertIn("nothing to revert", get_turn(CONV)["output"]["response"])


class TestFinalizeRefusesOnlyAfterTheGate(FrappeTestCase):
	"""Runs the site's Finalize script on a prepared turn, the way the Logix map does."""

	def setUp(self):
		if not frappe.db.exists("Server Script", FINALIZE):
			self.skipTest("Logix is not on this site")
		self.addCleanup(clear_turn, CONV)
		self.script = frappe.db.get_value("Server Script", FINALIZE, "script")
		if "revert_output" not in self.script:
			self.skipTest("the site's Finalize script predates the revert path")

	def _finalize(self, **turn):
		set_turn(CONV, {"user_text": "x", "current_script": "", **turn})
		result = {}
		exec(
			self.script, {"frappe": frappe, "context_docname": CONV, "result": result, "bpmn_id": "finalize"}
		)
		return get_turn(CONV)["output"], result

	def test_an_empty_turn_asks_what_is_missing(self):
		output, result = self._finalize(intent="CREATE")

		self.assertEqual(output["intent"], "DISAMBIGUATE")
		for word in ("DocType", "event", "output"):
			self.assertIn(word, output["response"])
		self.assertNotIn("unable to generate a safe script", output["response"])
		self.assertNotIn("safe", result)

	def test_a_gate_failure_on_the_last_attempt_refuses_and_records_the_violations(self):
		blocked = "doc.save(ignore_permissions=True)"  # test data: the line the gate names
		findings = [{"rule": "No ignore_permissions", "line": 2, "code": blocked}]
		output, result = self._finalize(
			intent="CREATE",
			final="```python\nx\n```",
			script_safe=False,
			findings=findings,
			violations=["No ignore_permissions"],
			review_suggestions=[],
		)

		self.assertIn("safety check blocks it", output["response"])
		self.assertIn("No ignore_permissions", output["response"])
		self.assertFalse(result["safe"])
		self.assertEqual(result["violations"], ["No ignore_permissions"])

	def test_unreviewed_code_is_gated_here_and_refused_only_when_it_fails(self):
		code = "doc = frappe.get_doc('ToDo', 'T1')\ndoc.save(ignore_permissions=True)"  # test data: fails the gate
		output, result = self._finalize(intent="CREATE", final=f"Here it is.\n```python\n{code}\n```")

		self.assertIn("safety check blocks it", output["response"])
		self.assertTrue(result["violations"])

	def test_unreviewed_clean_code_is_published(self):
		with (
			patch.object(tools, "get_agent_config", return_value={}),
			patch(
				"processa.processa_engine.agent_runtime.llm_factory.get_llm_adapter_from_settings",
				side_effect=RuntimeError("no model in tests"),
			),
		):
			output, _result = self._finalize(
				intent="MODIFY", original_script_content=FIRST, final=f"Done.\n```python\n{SECOND}\n```"
			)

		self.assertEqual(output["intent"], "MODIFY")
		self.assertEqual(output["modified_script"], SECOND)

	def test_a_revert_turn_goes_through_the_history(self):
		with patch.object(
			tools, "revert_output", side_effect=lambda conv: tools._reply(conv, "reverted")
		) as revert:
			output, _result = self._finalize(intent="REVERT")

		revert.assert_called_once_with(CONV)
		self.assertEqual(output["response"], "reverted")


class TestRegressionCases(FrappeTestCase):
	def test_the_four_messages_are_seeded_once(self):
		if not frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "process_model"):
			self.skipTest("Logix is not on this site")

		seed.execute()
		seed.execute()

		titles = [c["title"] for c in seed.CASES]
		cases = frappe.get_all("AI Eval Case", filters={"title": ["in", titles]}, fields=["name", "title"])
		self.assertEqual(sorted(c.title for c in cases), sorted(titles))
		revert = frappe.get_doc("AI Eval Case", next(c.name for c in cases if "Revert" in c.title))
		self.assertEqual([c.tool_name for c in revert.expected_tool_calls], ["classify_intent", "finalize"])
		self.assertTrue(any("unable to generate a safe script" in a.value for a in revert.assertions))
		self.assertEqual(json.loads(revert.input_context)["current_script"], "Activity_0imgq8b")
