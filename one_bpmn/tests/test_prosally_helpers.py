# Copyright (c) 2026, one-fm and contributors
"""The shared ProsAlly helpers behave exactly as the copies inlined in the tool scripts did."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.turn_state import clear_turn, get_turn
from one_bpmn.one_bpmn.patches.v1_0 import (
	prosally_build_context_confirmed_action_pending_only as build_context_patch,
)
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

	def test_a_diagram_that_is_not_xml_raises(self):
		from xml.etree import ElementTree as ET

		with self.assertRaises(ET.ParseError):
			helpers.extract_configured_elements("<bpmn:definitions")
		with self.assertRaises(ET.ParseError):
			helpers.transfer_properties(OLD_XML, "<bpmn:definitions")


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


# The Build Context script as it runs on the BA site.
REAL_BUILD_CONTEXT = """# Seeds the turn store with this turn's inputs. The transcript and the
# "Established so far" facts come from the platform's history step.
conversation_id = task_data.get("conversation_id", context_docname)
for _k in ['process_name', 'diagram_name', 'confirmed_action', 'current_xml']:
    _v = task_data.get(_k)
    if _v not in (None, ""):
        result[_k] = _v
result["agent_response_ready"] = False

from one_bpmn.agents.prosally_helpers import answer_to_confirmation
from one_bpmn.agents.turn_state import set_turn
# A typed reply to the last confirmation counts the same as clicking its button.
_confirmed = task_data.get("confirmed_action", "") or ""
_answer = {} if _confirmed else answer_to_confirmation(conversation_id, task_data.get("user_text", "") or "")
set_turn(conversation_id, {
    "user_text": task_data.get("user_text", "") or "",
    "process_name": task_data.get("process_name", "") or "",
    "diagram_name": task_data.get("diagram_name", "") or "",
    "confirmed_action": _confirmed or _answer.get("confirmed_action", ""),
    "declined_action": _answer.get("declined_action", ""),
    "current_xml": task_data.get("current_xml", "") or "",
})

# The AI Agent Task does tool-calling internally, so the modeled
# "Needs to call tools?" gateway always takes the default (no) path.
result["needs_tools"] = False
"""
CONVERSATION = "_test_prosally_pending"
STATED = '_confirmed = task_data.get("confirmed_action", "") or ""'


def _last_bot_message(metadata):
	rows = [frappe._dict(metadata=json.dumps(metadata))] if metadata is not None else []
	return patch.object(frappe, "get_all", return_value=rows)


CARD = {"intent": "CONFIRM", "agent_result": {"action_intent": "GENERATE_NEW"}}
CLARIFY = {"intent": "CLARIFY", "agent_result": {"action_intent": None}}


class TestPendingConfirmation(FrappeTestCase):
	def test_a_confirmation_card_gives_its_action(self):
		with _last_bot_message(CARD):
			self.assertEqual(helpers.pending_confirmation(CONVERSATION), "GENERATE_NEW")

	def test_a_clarify_or_no_bot_message_gives_empty(self):
		with _last_bot_message(CLARIFY):
			self.assertEqual(helpers.pending_confirmation(CONVERSATION), "")
		with _last_bot_message(None):
			self.assertEqual(helpers.pending_confirmation(CONVERSATION), "")

	def test_a_card_without_an_action_gives_empty(self):
		with _last_bot_message({"intent": "CONFIRM", "agent_result": {}}):
			self.assertEqual(helpers.pending_confirmation(CONVERSATION), "")

	def test_answer_to_confirmation_reuses_it(self):
		with patch.object(helpers, "pending_confirmation", return_value="MODIFY_EXISTING") as pending:
			self.assertEqual(
				helpers.answer_to_confirmation(CONVERSATION, "Yes, proceed"),
				{"confirmed_action": "MODIFY_EXISTING"},
			)
		pending.assert_called_once_with(CONVERSATION)
		with patch.object(helpers, "pending_confirmation", return_value=""):
			self.assertEqual(helpers.answer_to_confirmation(CONVERSATION, "yes"), {})


class TestBuildContextPatch(FrappeTestCase):
	def tearDown(self):
		clear_turn(CONVERSATION)

	def _run(self, script, metadata, confirmed_action="GENERATE_NEW"):
		namespace = {
			"frappe": frappe,
			"context_docname": CONVERSATION,
			"result": {},
			"task_data": {
				"conversation_id": CONVERSATION,
				"confirmed_action": confirmed_action,
				"user_text": "draw a leave process",
			},
		}
		with _last_bot_message(metadata):
			exec(script, namespace)
		return get_turn(CONVERSATION)

	def test_only_the_confirmed_action_line_changes(self):
		old, new = (
			REAL_BUILD_CONTEXT.splitlines(),
			build_context_patch.rewrite(REAL_BUILD_CONTEXT).splitlines(),
		)
		self.assertEqual([line for line in old if line not in new], [STATED])
		self.assertEqual([line for line in old if line in new], [line for line in new if line in old])
		self.assertIn("pending_confirmation(conversation_id)", "\n".join(new))

	def test_the_patched_real_script_compiles(self):
		compile(build_context_patch.rewrite(REAL_BUILD_CONTEXT), "build_context", "exec")

	def test_the_patch_is_idempotent(self):
		once = build_context_patch.rewrite(REAL_BUILD_CONTEXT)
		self.assertEqual(build_context_patch.rewrite(once), once)

	def test_a_script_without_the_assignment_is_left_alone(self):
		script = 'message = task_data.get("message")\n'
		self.assertEqual(build_context_patch.rewrite(script), script)

	def test_a_stale_action_after_a_clarify_is_dropped(self):
		turn = self._run(build_context_patch.rewrite(REAL_BUILD_CONTEXT), CLARIFY)
		self.assertEqual(turn["confirmed_action"], "")
		self.assertEqual(turn["user_text"], "draw a leave process")

	def test_the_unpatched_script_keeps_the_stale_action(self):
		self.assertEqual(self._run(REAL_BUILD_CONTEXT, CLARIFY)["confirmed_action"], "GENERATE_NEW")

	def test_a_real_card_keeps_its_action(self):
		turn = self._run(build_context_patch.rewrite(REAL_BUILD_CONTEXT), CARD)
		self.assertEqual(turn["confirmed_action"], "GENERATE_NEW")

	def test_an_action_that_is_not_the_pending_one_is_dropped(self):
		turn = self._run(
			build_context_patch.rewrite(REAL_BUILD_CONTEXT), CARD, confirmed_action="OVERWRITE_EXISTING"
		)
		self.assertEqual(turn["confirmed_action"], "")


class TestBuildContextPatchExecute(FrappeTestCase):
	def test_the_script_is_looked_up_by_api_method_not_by_name(self):
		with (
			patch.object(frappe.db, "get_value", side_effect=["Any Name", REAL_BUILD_CONTEXT]) as get_value,
			patch.object(frappe.db, "set_value") as set_value,
		):
			build_context_patch.execute()
		self.assertEqual(
			get_value.call_args_list[0].args,
			("Server Script", {"api_method": "prosally_build_context"}, "name"),
		)
		self.assertEqual(set_value.call_args.args[:3], ("Server Script", "Any Name", "script"))
		self.assertIn("pending_confirmation(conversation_id)", set_value.call_args.args[3])

	def test_a_site_without_the_script_logs_and_changes_nothing(self):
		with (
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(frappe, "log_error") as log_error,
			patch.object(frappe.db, "set_value") as set_value,
		):
			build_context_patch.execute()
		log_error.assert_called_once()
		set_value.assert_not_called()

	def test_a_script_without_the_assignment_is_logged_and_left_alone(self):
		with (
			patch.object(frappe.db, "get_value", side_effect=["Any Name", "x = 1\n"]),
			patch.object(frappe, "log_error") as log_error,
			patch.object(frappe.db, "set_value") as set_value,
		):
			build_context_patch.execute()
		log_error.assert_called_once()
		set_value.assert_not_called()


class FakeAdapter:
	def __init__(self, reply):
		self.reply = reply

	async def complete(self, system, user):
		return SimpleNamespace(text=self.reply)


class TestClassifyAfterBuildContext(FrappeTestCase):
	"""Runs the live Classify Intent Server Script with the model faked; it reaches a site with the ProsAlly map by export."""

	def setUp(self):
		self.script = frappe.db.get_value(
			"Server Script", {"api_method": "prosally_tool_classify_intent"}, "script"
		)
		if not self.script:
			self.skipTest("the ProsAlly Classify Intent script is not on this site")

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _classify(self, metadata, model_reply=""):
		namespace = {
			"frappe": frappe,
			"context_docname": CONVERSATION,
			"result": {},
			"task_data": {
				"conversation_id": CONVERSATION,
				"confirmed_action": "GENERATE_NEW",
				"user_text": "tell me how to divide it in smaller parts",
				"process_name": "Leave",
			},
		}
		with _last_bot_message(metadata):
			exec(build_context_patch.rewrite(REAL_BUILD_CONTEXT), namespace)
		result = {}
		with patch(
			"one_bpmn.agents.llm_provider.get_llm_adapter_from_settings",
			return_value=FakeAdapter(model_reply),
		) as adapter:
			exec(self.script, {"frappe": frappe, "context_docname": CONVERSATION, "result": result})
		return result, adapter

	def test_a_stale_yes_after_a_clarify_classifies_normally(self):
		reply = {"intent": "INCOMPLETE", "reason": "r", "summary": "", "question": ""}
		result, adapter = self._classify(CLARIFY, json.dumps(reply))
		adapter.assert_called_once()
		self.assertNotIn("already_confirmed", result)

	def test_yes_proceed_on_a_real_card_starts_generation(self):
		result, adapter = self._classify(CARD)
		adapter.assert_not_called()
		self.assertEqual(result["next"], "generate_process")
		self.assertTrue(result["already_confirmed"])
