# Copyright (c) 2026, one-fm and contributors
"""The shared ProsAlly helpers behave as the inlined copies did; the routed replies, the lost reply and the confirmed briefs."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_observability.observability import terminal_tool_failure
from processa.ai_agent_registry.definitions.prosally import helpers, tools_prompts, tools_properties, tools_replies
from processa.ai_agent_registry.definitions.shared import helpers as shared_helpers
from processa.patches.v1_0 import seed_prosally_confirmed_brief_cases as seed
from processa.processa_engine.agent_runtime.executor import ErrorCode
from processa.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn
from processa.patches.v1_0 import (
	prosally_build_context_confirmed_action_pending_only as build_context_patch,
)
from processa.patches.v1_0.prosally_merge_classify_and_confirm import CLASSIFY_INTENT
from processa.ai_agent_security.code_checks.script_validator import deep_inspect_script
from processa.tests.site_scripts import as_deployed

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
		configured = tools_properties.extract_configured_elements(OLD_XML)
		self.assertEqual(configured, self.inlined("extract", OLD_XML))
		self.assertEqual(sorted(configured), ["approve", "notify"])

	def test_transfer_is_unchanged(self):
		merged, removed = tools_properties.transfer_properties(OLD_XML, NEW_XML)
		self.assertEqual((merged, removed), self.inlined("transfer", OLD_XML, NEW_XML))
		self.assertIn('spiffworkflow:roundRobinRole="HR Manager"', merged)
		self.assertIn("The HR manager approves or rejects.", merged)
		self.assertEqual([r["id"] for r in removed], ["notify"])

	def test_warnings_name_the_configured_shapes(self):
		_, removed = tools_properties.transfer_properties(OLD_XML, NEW_XML)
		self.assertIn(
			"**Notify Employee** (Script Task) - Server Script: Leave Notify",
			tools_properties.format_removal_warning(removed),
		)
		warning = tools_properties.overwrite_warning(OLD_XML)
		self.assertIn(
			"**Approve Leave** (User Task) - Assignment Mode, Round Robin Role, Documentation", warning
		)
		self.assertEqual(tools_properties.overwrite_warning(NEW_XML), "")

	def test_a_diagram_that_is_not_xml_raises(self):
		from xml.etree import ElementTree as ET

		with self.assertRaises(ET.ParseError):
			tools_properties.extract_configured_elements("<bpmn:definitions")
		with self.assertRaises(ET.ParseError):
			tools_properties.transfer_properties(OLD_XML, "<bpmn:definitions")


class TestExtractJson(FrappeTestCase):
	def test_plain_fenced_and_embedded_objects(self):
		self.assertEqual(shared_helpers.extract_json('{"intent": "GENERATE_NEW"}'), {"intent": "GENERATE_NEW"})
		self.assertEqual(
			shared_helpers.extract_json('```json\n{"intent": "MODIFY_EXISTING"}\n```'), {"intent": "MODIFY_EXISTING"}
		)
		self.assertEqual(shared_helpers.extract_json('```{"nodes": []}```'), {"nodes": []})
		self.assertEqual(
			shared_helpers.extract_json('Sure, here it is: {"question": "Which lane?"} Thanks.'),
			{"question": "Which lane?"},
		)

	def test_the_first_of_two_objects_in_prose(self):
		self.assertEqual(shared_helpers.extract_json('First {"a": 1} then {"b": 2}'), {"a": 1})

	def test_no_object(self):
		self.assertIsNone(shared_helpers.extract_json(""))
		self.assertIsNone(shared_helpers.extract_json("no json here"))
		self.assertIsNone(shared_helpers.extract_json("[1, 2]"))


class TestHistoryAndBudget(FrappeTestCase):
	def test_history_keeps_the_last_ten_non_empty_turns(self):
		history = [{"role": "user", "content": f"m{i}"} for i in range(12)]
		history[-1] = {"role": "assistant", "content": "  "}
		history.append({"type": "assistant", "content": "done"})
		lines = shared_helpers.format_history(history).split("\n")
		self.assertEqual(lines[0], "User: m3")
		self.assertEqual(lines[-1], "ProsAlly: done")
		self.assertEqual(len(lines), 9)
		self.assertEqual(shared_helpers.format_history([]), "")

	def test_stage_budget_has_a_floor_and_the_model_ceiling(self):
		self.assertEqual(tools_prompts.stage_max_tokens({"max_tokens": 1024}), tools_prompts.MIN_STAGE_TOKENS)
		self.assertEqual(tools_prompts.stage_max_tokens({"max_tokens": 40000}), 40000)
		with patch.object(frappe.db, "get_value", return_value=20000):
			self.assertEqual(tools_prompts.stage_max_tokens({"max_tokens": 40000, "ai_model": "m"}), 20000)


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
		system = tools_prompts.stage_system_prompt(self._cfg(), "modifier", "modify_skills")
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

from processa.agents.prosally_helpers import answer_to_confirmation
from processa.processa_engine.agent_runtime.turn_state import set_turn
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
# The same script on Staging and on a local site: confirmed_action is staged inside the set_turn dict.
OLDER_BUILD_CONTEXT = """# Builds the LLM conversation history and seeds the per-turn scratch store.
conversation_id = task_data.get("conversation_id", context_docname)
for _k in ['process_name', 'diagram_name', 'confirmed_action', 'current_xml']:
    _v = task_data.get(_k)
    if _v not in (None, ""):
        result[_k] = _v
messages = frappe.get_all("Chat Message", filters={"conversation": conversation_id, "message_type": ["in", ["User", "Bot"]]}, fields=["text", "message_type"], order_by="creation desc", limit=20)
messages.reverse()
chat_history = []
for m in messages:
    role = "user" if m.message_type == "User" else "assistant"
    if m.text:
        chat_history.append({"role": role, "content": m.text})
result["chat_history"] = chat_history
result["agent_response_ready"] = False
from processa.processa_engine.agent_runtime.turn_state import set_turn
set_turn(conversation_id, {
    "user_text": task_data.get("user_text", "") or "",
    "chat_history": chat_history,
    "process_name": task_data.get("process_name", "") or "",
    "diagram_name": task_data.get("diagram_name", "") or "",
    "confirmed_action": task_data.get("confirmed_action", "") or "",
    "current_xml": task_data.get("current_xml", "") or "",
})

# Illustrative Camunda loop: the AI Agent Task does tool-calling internally,
# so the modeled "Needs to call tools?" gateway always takes the default (no) path.
result["needs_tools"] = False
"""
OLDER_STAGED = '    "confirmed_action": task_data.get("confirmed_action", "") or "",'


def _last_bot_message(metadata):
	rows = [frappe._dict(metadata=json.dumps(metadata))] if metadata is not None else []
	return patch.object(frappe, "get_all", return_value=rows)


CARD = {"intent": "CONFIRM", "agent_result": {"action_intent": "GENERATE_NEW"}}
CLARIFY = {"intent": "CLARIFY", "agent_result": {"action_intent": None}}


def _run_build_context(script, metadata, confirmed_action="GENERATE_NEW"):
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
		exec(as_deployed(script), namespace)
	return get_turn(CONVERSATION)


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
		turn = _run_build_context(build_context_patch.rewrite(REAL_BUILD_CONTEXT), CLARIFY)
		self.assertEqual(turn["confirmed_action"], "")
		self.assertEqual(turn["user_text"], "draw a leave process")

	def test_the_unpatched_script_keeps_the_stale_action(self):
		self.assertEqual(_run_build_context(REAL_BUILD_CONTEXT, CLARIFY)["confirmed_action"], "GENERATE_NEW")

	def test_a_real_card_keeps_its_action(self):
		turn = _run_build_context(build_context_patch.rewrite(REAL_BUILD_CONTEXT), CARD)
		self.assertEqual(turn["confirmed_action"], "GENERATE_NEW")

	def test_an_action_that_is_not_the_pending_one_is_dropped(self):
		turn = _run_build_context(
			build_context_patch.rewrite(REAL_BUILD_CONTEXT), CARD, confirmed_action="OVERWRITE_EXISTING"
		)
		self.assertEqual(turn["confirmed_action"], "")


class TestBuildContextPatchOlderShape(FrappeTestCase):
	"""Staging and local sites keep confirmed_action inside the dict handed to set_turn, with no assignment."""

	def tearDown(self):
		clear_turn(CONVERSATION)

	def test_only_the_confirmed_action_entry_changes(self):
		old = OLDER_BUILD_CONTEXT.splitlines()
		new = build_context_patch.rewrite(OLDER_BUILD_CONTEXT).splitlines()
		self.assertEqual([line for line in old if line not in new], [OLDER_STAGED])
		self.assertEqual([line for line in old if line in new], [line for line in new if line in old])

	def test_the_check_sits_after_conversation_id_and_before_set_turn(self):
		new = build_context_patch.rewrite(OLDER_BUILD_CONTEXT)
		check = new.index("pending_confirmation(conversation_id)")
		self.assertLess(new.index("conversation_id = "), check)
		self.assertLess(check, new.index("set_turn(conversation_id"))

	def test_the_patched_script_compiles_and_a_second_run_changes_nothing(self):
		once = build_context_patch.rewrite(OLDER_BUILD_CONTEXT)
		compile(once, "build_context", "exec")
		self.assertEqual(build_context_patch.rewrite(once), once)

	def test_a_stale_action_after_a_clarify_is_dropped(self):
		turn = _run_build_context(build_context_patch.rewrite(OLDER_BUILD_CONTEXT), CLARIFY)
		self.assertEqual(turn["confirmed_action"], "")
		self.assertEqual(turn["user_text"], "draw a leave process")

	def test_the_unpatched_script_keeps_the_stale_action(self):
		self.assertEqual(_run_build_context(OLDER_BUILD_CONTEXT, CLARIFY)["confirmed_action"], "GENERATE_NEW")

	def test_a_real_card_keeps_its_action(self):
		turn = _run_build_context(build_context_patch.rewrite(OLDER_BUILD_CONTEXT), CARD)
		self.assertEqual(turn["confirmed_action"], "GENERATE_NEW")

	def test_an_action_that_is_not_the_pending_one_is_dropped(self):
		script = build_context_patch.rewrite(OLDER_BUILD_CONTEXT)
		self.assertEqual(
			_run_build_context(script, CARD, confirmed_action="OVERWRITE_EXISTING")["confirmed_action"], ""
		)

	def test_an_entry_with_no_set_turn_call_is_left_alone(self):
		script = '"confirmed_action": task_data.get("confirmed_action", "") or "",\n'
		self.assertEqual(build_context_patch.rewrite(script), script)


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

	def test_an_older_script_is_patched_too(self):
		with (
			patch.object(frappe.db, "get_value", side_effect=["Any Name", OLDER_BUILD_CONTEXT]),
			patch.object(frappe.db, "set_value") as set_value,
		):
			build_context_patch.execute()
		self.assertIn('"confirmed_action": _confirmed,', set_value.call_args.args[3])

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
			exec(as_deployed(build_context_patch.rewrite(REAL_BUILD_CONTEXT)), namespace)
		result = {}
		# The script reaches the model through complete_sub_prompt on BA and through the adapter on older sites.
		with (
			patch.object(helpers, "complete_sub_prompt", return_value=model_reply) as helper,
			patch(
				"processa.processa_engine.agent_runtime.llm_factory.get_llm_adapter_from_settings",
				return_value=FakeAdapter(model_reply),
			) as adapter,
		):
			exec(as_deployed(self.script), {"frappe": frappe, "context_docname": CONVERSATION, "result": result})
		return result, helper.call_count + adapter.call_count

	def test_a_stale_yes_after_a_clarify_classifies_normally(self):
		reply = {"intent": "INCOMPLETE", "reason": "r", "summary": "", "question": ""}
		result, model_calls = self._classify(CLARIFY, json.dumps(reply))
		self.assertEqual(model_calls, 1)
		self.assertNotIn("already_confirmed", result)

	def test_yes_proceed_on_a_real_card_starts_generation(self):
		result, model_calls = self._classify(CARD)
		self.assertEqual(model_calls, 0)
		self.assertEqual(result["next"], "generate_process")
		self.assertTrue(result["already_confirmed"])


class TestTheEngineValidatorAcceptsThePatchedBuildContext(FrappeTestCase):
	"""The engine blocks a Server Script on any validator finding right before it runs."""

	def test_both_script_shapes_have_no_findings_after_the_patch(self):
		for label, script in (("assigned", REAL_BUILD_CONTEXT), ("in the dict", OLDER_BUILD_CONTEXT)):
			with self.subTest(shape=label):
				self.assertEqual(deep_inspect_script(build_context_patch.rewrite(script)), [])


CONV = "zz-prosally-route"
FINALIZE_SCRIPT = f"ProsAlly {chr(0x2013)} Tool Finalize"
CLARIFY_SCRIPT = f"ProsAlly {chr(0x2013)} Tool Clarify"
GENERIC = "Could you tell me more about the process you'd like to model?"
FAILED_FINALIZE = '{"error": "NO_STAGE_REPLY: no stage wrote a reply", "error_code": "NO_STAGE_REPLY"}'


class TestTerminalToolError(FrappeTestCase):
	def test_the_error_code_is_in_the_enum(self):
		self.assertEqual(ErrorCode.NO_STAGE_REPLY.value, "NO_STAGE_REPLY")

	def test_a_last_tool_that_names_a_code_fails_the_run(self):
		trace = [
			{"tool_calls": [{"name": "classify_intent", "result": '{"next": "clarify"}'}]},
			{"tool_calls": [{"name": "finalize", "result": FAILED_FINALIZE}]},
		]

		self.assertEqual(
			terminal_tool_failure(trace),
			{
				"status": "Error",
				"error_code": "NO_STAGE_REPLY",
				"error_message": "NO_STAGE_REPLY: no stage wrote a reply",
			},
		)

	def test_an_error_without_a_code_or_a_clean_finalize_leaves_the_run_alone(self):
		clean = [{"tool_calls": [{"name": "finalize", "result": '{"finalized": true}'}]}]
		uncoded = [{"tool_calls": [{"name": "x", "result": '{"error": "boom"}'}]}]

		self.assertEqual(terminal_tool_failure(clean), {})
		self.assertEqual(terminal_tool_failure(uncoded), {})
		self.assertEqual(terminal_tool_failure([]), {})


class TestRouteHelpers(FrappeTestCase):
	def setUp(self):
		self.addCleanup(clear_turn, CONV)

	def test_no_stage_reply_names_the_failure_and_marks_the_turn(self):
		set_turn(CONV, {"user_text": "Yes, proceed"})

		envelope = tools_replies.no_stage_reply(CONV)

		turn = get_turn(CONV)
		self.assertEqual(envelope["error_code"], "NO_STAGE_REPLY")
		self.assertEqual(turn["tool_error"]["error_code"], "NO_STAGE_REPLY")
		self.assertIn("NO_STAGE_REPLY", turn["output"]["response"])
		self.assertNotIn(GENERIC, turn["output"]["response"])
		self.assertTrue(turn["done"])

	def test_the_missing_piece_question_follows_the_reason(self):
		self.assertIn("lane", tools_replies.missing_piece_question("no lanes named"))
		self.assertIn("starts", tools_replies.missing_piece_question("the trigger is unknown"))
		self.assertIn("finished", tools_replies.missing_piece_question("end state missing"))
		self.assertIn("called", tools_replies.missing_piece_question(""))

	def test_clarify_without_a_model_answer_asks_for_the_missing_piece(self):
		set_turn(CONV, {"user_text": "draw it", "intent_reason": "no lanes named", "chat_history": []})

		with patch.object(tools_replies, "complete_sub_prompt", return_value="not json"):
			out = tools_replies.clarify_output(CONV)

		self.assertIn("lane", out["response"])
		self.assertEqual(get_turn(CONV)["output"]["intent"], "CLARIFY")

	def test_clarify_keeps_the_model_question_and_options(self):
		set_turn(CONV, {"user_text": "draw it", "intent_reason": "", "chat_history": []})
		reply = json.dumps({"question": "Who starts it?", "options": ["HR", "Employee"]})

		with patch.object(tools_replies, "complete_sub_prompt", return_value=reply):
			out = tools_replies.clarify_output(CONV)

		self.assertEqual((out["response"], out["options"]), ("Who starts it?", ["HR", "Employee"]))


class TestFinalizeRunsTheRoutedTool(FrappeTestCase):
	"""Runs the site's Finalize script the way the map does."""

	def setUp(self):
		for name in (FINALIZE_SCRIPT, CLARIFY_SCRIPT):
			if not frappe.db.exists("Server Script", name):
				self.skipTest("ProsAlly is not on this site")
		self.script = frappe.db.get_value("Server Script", FINALIZE_SCRIPT, "script")
		if "no_stage_reply" not in self.script:
			self.skipTest("the site's Finalize script predates the routed reply")
		self.addCleanup(clear_turn, CONV)

	def _finalize(self, turn: dict) -> dict:
		set_turn(CONV, turn)
		result = {}
		exec(self.script, {"frappe": frappe, "context_docname": CONV, "result": result, "instance": None})
		return result

	def test_the_generic_sentence_is_gone_from_both_scripts(self):
		for name in (FINALIZE_SCRIPT, CLARIFY_SCRIPT):
			self.assertNotIn(GENERIC, frappe.db.get_value("Server Script", name, "script"))

	def test_a_skipped_clarify_runs_in_finalize(self):
		reply = '{"question": "Which lanes?", "options": []}'
		with patch.object(tools_replies, "complete_sub_prompt", return_value=reply):
			result = self._finalize(
				{"user_text": "x", "routed_tool": "clarify", "intent_reason": "no lanes", "chat_history": []}
			)

		self.assertEqual(result["ran"], "clarify")
		self.assertEqual(get_turn(CONV)["output"]["response"], "Which lanes?")

	def test_a_turn_with_no_reply_at_all_fails_with_the_code(self):
		result = self._finalize({"user_text": "Yes, proceed"})

		self.assertEqual(result["error_code"], "NO_STAGE_REPLY")
		self.assertIn("NO_STAGE_REPLY", get_turn(CONV)["output"]["response"])

	def test_a_turn_already_answered_is_left_alone(self):
		output = {"intent": "BPMN_GENERATED", "response": "Drawn.", "options": []}
		result = self._finalize({"routed_tool": "generate_process", "output": output, "done": True})

		self.assertEqual(result, {"finalized": True})
		self.assertEqual(get_turn(CONV)["output"], output)


class TestConfirmedBriefCases(FrappeTestCase):
	def test_five_cases_are_seeded_once_with_the_brief_and_the_card(self):
		if not frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name"):
			self.skipTest("the ProsAlly Baseline suite is not on this site")

		seed.execute()
		seed.execute()

		titles = [c["title"] for c in json.loads(seed.BRIEFS.read_text())]
		cases = frappe.get_all(
			"AI Eval Case", filters={"title": ["in", titles]}, fields=["name", "input_context"]
		)
		self.assertEqual(len(cases), 5)
		context = json.loads(cases[0].input_context)
		self.assertEqual([m["message_type"] for m in context["conversation_messages"]], ["User", "Bot"])
		self.assertEqual(context["conversation_messages"][1]["metadata"]["intent"], "CONFIRM")
		case = frappe.get_doc("AI Eval Case", cases[0].name)
		self.assertEqual(case.input_user_prompt, "Yes, proceed")
		self.assertEqual(
			[c.tool_name for c in case.expected_tool_calls], ["classify_intent", "generate_process"]
		)
