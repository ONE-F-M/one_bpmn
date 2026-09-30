# Copyright (c) 2026, one-fm and contributors
"""The shared ProsAlly helpers behave exactly as the copies inlined in the tool scripts did."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.one_bpmn.patches.v1_0.prosally_merge_classify_and_confirm import CLASSIFY_INTENT

OLD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs_1">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="start" />
    <bpmn:userTask id="approve" name="Approve Leave" spiffworkflow:assignmentMode="Round Robin"
        spiffworkflow:roundRobinRole="HR Manager">
      <bpmn:documentation>The HR manager approves or rejects.</bpmn:documentation>
    </bpmn:userTask>
    <bpmn:scriptTask id="notify" name="Notify Employee" spiffworkflow:serverScript="Leave Notify">
      <bpmn:extensionElements><spiffworkflow:preScript>x = 1</spiffworkflow:preScript></bpmn:extensionElements>
    </bpmn:scriptTask>
    <bpmn:endEvent id="end" />
  </bpmn:process>
</bpmn:definitions>
"""

NEW_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_1">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="start" />
    <bpmn:userTask id="approve" name="Approve Leave" />
    <bpmn:userTask id="record" name="Record Leave" />
    <bpmn:endEvent id="end" />
  </bpmn:process>
</bpmn:definitions>
"""


def _inlined_preserver():
	source = CLASSIFY_INTENT[
		CLASSIFY_INTENT.index("def _prosally_preserver") : CLASSIFY_INTENT.index("\n_ACTION_INTENTS")
	]
	namespace = {}
	exec(source, namespace)
	return namespace["_prosally_preserver"]


class TestPreserverMatchesTheInlinedCopy(FrappeTestCase):
	def setUp(self):
		self.inlined = _inlined_preserver()

	def test_extract_is_unchanged(self):
		configured = helpers.extract_configured_elements(OLD_XML)
		self.assertEqual(configured, self.inlined("extract", OLD_XML))
		self.assertEqual(sorted(configured), ["approve", "notify"])

	def test_transfer_is_unchanged(self):
		merged, removed = helpers.transfer_properties(OLD_XML, NEW_XML)
		self.assertEqual((merged, removed), self.inlined("transfer", OLD_XML, NEW_XML))
		self.assertIn('spiffworkflow:roundRobinRole="HR Manager"', merged)
		self.assertIn("The HR manager approves or rejects.", merged)
		self.assertEqual([r["id"] for r in removed], ["notify"])

	def test_warnings_name_the_configured_shapes(self):
		_, removed = helpers.transfer_properties(OLD_XML, NEW_XML)
		self.assertIn(
			"**Notify Employee** (Script Task) - Server Script: Leave Notify",
			helpers.format_removal_warning(removed),
		)
		warning = helpers.overwrite_warning(OLD_XML)
		self.assertIn(
			"**Approve Leave** (User Task) - Assignment Mode, Round Robin Role, Documentation", warning
		)
		self.assertEqual(helpers.overwrite_warning(NEW_XML), "")


class TestExtractJson(FrappeTestCase):
	def test_plain_fenced_and_embedded_objects(self):
		self.assertEqual(helpers.extract_json('{"intent": "GENERATE_NEW"}'), {"intent": "GENERATE_NEW"})
		self.assertEqual(
			helpers.extract_json('```json\n{"intent": "MODIFY_EXISTING"}\n```'), {"intent": "MODIFY_EXISTING"}
		)
		self.assertEqual(helpers.extract_json('```{"nodes": []}```'), {"nodes": []})
		self.assertEqual(
			helpers.extract_json('Sure, here it is: {"question": "Which lane?"} Thanks.'),
			{"question": "Which lane?"},
		)

	def test_the_first_of_two_objects_in_prose(self):
		self.assertEqual(helpers.extract_json('First {"a": 1} then {"b": 2}'), {"a": 1})

	def test_no_object(self):
		self.assertIsNone(helpers.extract_json(""))
		self.assertIsNone(helpers.extract_json("no json here"))
		self.assertIsNone(helpers.extract_json("[1, 2]"))


class TestHistoryAndBudget(FrappeTestCase):
	def test_history_keeps_the_last_ten_non_empty_turns(self):
		history = [{"role": "user", "content": f"m{i}"} for i in range(12)]
		history[-1] = {"role": "assistant", "content": "  "}
		history.append({"type": "assistant", "content": "done"})
		lines = helpers.format_history(history).split("\n")
		self.assertEqual(lines[0], "User: m3")
		self.assertEqual(lines[-1], "ProsAlly: done")
		self.assertEqual(len(lines), 9)
		self.assertEqual(helpers.format_history([]), "")

	def test_stage_budget_has_a_floor_and_the_model_ceiling(self):
		self.assertEqual(helpers.stage_max_tokens({"max_tokens": 1024}), helpers.MIN_STAGE_TOKENS)
		self.assertEqual(helpers.stage_max_tokens({"max_tokens": 40000}), 40000)
		with patch.object(frappe.db, "get_value", return_value=20000):
			self.assertEqual(helpers.stage_max_tokens({"max_tokens": 40000, "ai_model": "m"}), 20000)


class TestModelCalls(FrappeTestCase):
	def _cfg(self):
		return {
			"sub_prompts": {"modifier": {"prompt": "You modify BPMN.", "temperature": "0.2"}},
			"constants": {"modify_skills": "_Test ProsAlly Rules, _Test ProsAlly Draft, "},
		}

	def test_complete_sub_prompt_sends_the_sub_prompt_as_system(self):
		calls = []

		class Adapter:
			async def complete(self, **kwargs):
				calls.append(kwargs)
				return SimpleNamespace(text="reply")

		with patch.object(helpers, "get_llm_adapter_from_settings", return_value=Adapter()):
			self.assertEqual(helpers.complete_sub_prompt(self._cfg(), "modifier", "change it"), "reply")
			helpers.complete_sub_prompt(self._cfg(), "modifier", "again", system="custom", max_tokens=4096)
		self.assertEqual(calls[0], {"system": "You modify BPMN.", "user": "change it"})
		self.assertEqual(calls[1], {"system": "custom", "user": "again", "max_tokens": 4096})

	def test_stage_system_prompt_appends_only_active_named_skills(self):
		for name, status in (("_Test ProsAlly Rules", "Active"), ("_Test ProsAlly Draft", "Draft")):
			if not frappe.db.exists("AI Skill", name):
				frappe.get_doc(
					{
						"doctype": "AI Skill",
						"skill_name": name,
						"status": status,
						"description": name,
						"body": name + " body",
					}
				).insert()
		system = helpers.stage_system_prompt(self._cfg(), "modifier", "modify_skills")
		self.assertEqual(
			system, "You modify BPMN.\n\n## Skill: _Test ProsAlly Rules\n\n_Test ProsAlly Rules body"
		)
