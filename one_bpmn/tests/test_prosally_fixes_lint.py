# Copyright (c) 2026, one-fm and contributors
"""A request to fix lint findings edits the process or sub-process they sit in, and says what it left alone."""

import ast
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.prosally_helpers import (
	describe_flow_references,
	describe_links,
	lint_findings,
	lint_fix_requested,
	lint_leftovers,
	lint_prompt,
	no_lint_fix_reply,
)
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_counts_rebuilt_flow_references as references_patch
from one_bpmn.one_bpmn.patches.v1_0 import prosally_fixes_lint_findings as lint_patch
from one_bpmn.security.script_validator import deep_inspect_script

CONVERSATION = "_test_prosally_fixes_lint"
HEAD = '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
XML = (
	f'{HEAD}<bpmn:process id="P"><bpmn:startEvent id="s" name="Start"/><bpmn:userTask id="a" name="Review"/>'
	'<bpmn:subProcess id="sub" name="Payroll Clearance"><bpmn:userTask id="b" name="Check Salary"/>'
	'<bpmn:exclusiveGateway id="g" name="Salary OK?"/></bpmn:subProcess>'
	'<bpmn:endEvent id="e" name="End"/></bpmn:process></bpmn:definitions>'
)


def _issue(element_id, rule="no-disconnected", message="Element is not connected", category="error"):
	return {"id": element_id, "rule": "bpmnlint/" + rule, "message": message, "category": category}


MAIN_ISSUE = _issue("a")
SUB_ISSUE = _issue("b")
SUB_GATEWAY_ISSUE = _issue("g", "label-required", "Element is missing label/name", "warn")
LAYOUT_ISSUE = _issue("a", "no-overlapping-elements", "Elements overlap", "warn")
REQUEST = "Fix the linting issues"


class RecordingAdapter:
	def __init__(self, reply):
		self.reply = reply
		self.prompts = []

	async def complete(self, system, user):
		self.prompts.append(user)
		return SimpleNamespace(text=json.dumps(self.reply))


class TestLintFixRequested(FrappeTestCase):
	def test_a_request_to_fix_lint_findings_is_detected(self):
		for text in (
			"Fix the linting issues",
			"please resolve the lint errors in this sub-process",
			"Can you fix the warnings on the diagram?",
			"clean up the lint",
			"help me fix the validation problems",
		):
			self.assertTrue(lint_fix_requested([text]), text)

	def test_other_requests_are_not_lint_requests(self):
		for text in (
			"Add a step after Review",
			"Fix the name of the Error Handler step",
			"Rename the warnings step to Alerts",
			"What are the lint rules?",
			"",
		):
			self.assertFalse(lint_fix_requested([text]), text)

	def test_the_request_is_the_newest_message_that_is_not_a_yes_or_a_no(self):
		self.assertTrue(lint_fix_requested(["Yes, proceed", REQUEST, "Add a step"]))
		self.assertFalse(lint_fix_requested(["Yes, proceed", "Add a step", REQUEST]))
		self.assertFalse(lint_fix_requested(["Yes, proceed"]))


class TestLintFindings(FrappeTestCase):
	def test_findings_in_the_main_process_are_fixed_there_and_the_sub_process_ones_are_counted(self):
		found = lint_findings(XML, [MAIN_ISSUE, SUB_ISSUE])
		self.assertIsNone(found["scope"])
		self.assertEqual([f["id"] for f in found["fix"]], ["a"])
		self.assertEqual(found["elsewhere"], [("Payroll Clearance", 1)])

	def test_the_sub_process_that_is_open_is_the_one_edited(self):
		found = lint_findings(XML, [MAIN_ISSUE, SUB_ISSUE, SUB_GATEWAY_ISSUE], scope_id="sub")
		self.assertEqual(found["scope"]["id"], "sub")
		self.assertEqual([f["id"] for f in found["fix"]], ["b", "g"])
		self.assertEqual(found["elsewhere"], [("", 1)])

	def test_findings_only_in_one_sub_process_edit_that_sub_process_without_it_being_open(self):
		found = lint_findings(XML, [SUB_ISSUE, SUB_GATEWAY_ISSUE])
		self.assertEqual(found["scope"]["id"], "sub")
		self.assertEqual(len(found["fix"]), 2)
		self.assertEqual(found["elsewhere"], [])

	def test_a_finding_about_the_contents_of_a_sub_process_belongs_to_it_but_others_belong_to_its_parent(self):
		about_contents = _issue("sub", "start-event-required", "Process is missing start event")
		about_label = _issue("sub", "label-required", "Element is missing label/name", "warn")
		self.assertEqual(lint_findings(XML, [about_contents])["scope"]["id"], "sub")
		self.assertIsNone(lint_findings(XML, [about_label])["scope"])

	def test_findings_that_need_a_person_are_left_out_of_the_fix(self):
		found = lint_findings(XML, [MAIN_ISSUE, LAYOUT_ISSUE])
		self.assertEqual([f["rule"] for f in found["fix"]], ["no-disconnected"])
		self.assertEqual([f["rule"] for f in found["left"]], ["no-overlapping-elements"])

	def test_only_findings_that_need_a_person_leave_nothing_to_fix(self):
		self.assertEqual(lint_findings(XML, [LAYOUT_ISSUE])["fix"], [])

	def test_no_findings_and_no_diagram_give_nothing(self):
		self.assertIsNone(lint_findings(XML, []))
		self.assertIsNone(lint_findings("", [MAIN_ISSUE]))

	def test_a_finding_for_an_element_not_on_the_diagram_is_treated_as_main_process(self):
		found = lint_findings(XML, [_issue("gone")])
		self.assertEqual((found["fix"][0]["name"], found["fix"][0]["owner"]), ("gone", ""))

	def test_only_the_first_findings_are_read(self):
		found = lint_findings(XML, [MAIN_ISSUE] * 60)
		self.assertEqual(len(found["fix"]), 40)


LINKED = XML.replace("</bpmn:subProcess>", '<bpmn:sequenceFlow id="f1" sourceRef="b" targetRef="g"/></bpmn:subProcess>')
REFERENCED = LINKED.replace(
	'<bpmn:userTask id="b" name="Check Salary"/>',
	'<bpmn:userTask id="b" name="Check Salary"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:userTask>',
).replace(
	'<bpmn:exclusiveGateway id="g" name="Salary OK?"/>',
	'<bpmn:exclusiveGateway id="g" name="Salary OK?"><bpmn:incoming>f1</bpmn:incoming></bpmn:exclusiveGateway>',
)


class TestDescribeFlowReferences(FrappeTestCase):
	def test_references_added_to_existing_steps_are_counted(self):
		text = describe_flow_references(LINKED, REFERENCED)
		self.assertIn("Rebuilt the flow references on 2 steps", text)

	def test_references_removed_from_existing_steps_are_counted_too(self):
		self.assertIn("Rebuilt the flow references on 2 steps", describe_flow_references(REFERENCED, LINKED))

	def test_the_same_references_are_not_a_change(self):
		self.assertEqual(describe_flow_references(REFERENCED, REFERENCED), "")

	def test_a_step_that_is_new_is_left_to_the_added_step_line(self):
		with_new_step = REFERENCED.replace(
			"</bpmn:subProcess>", '<bpmn:userTask id="n" name="New"><bpmn:incoming>f9</bpmn:incoming></bpmn:userTask></bpmn:subProcess>'
		)
		self.assertEqual(describe_flow_references(REFERENCED, with_new_step), "")

	def test_no_diagram_before_or_after_gives_nothing(self):
		self.assertEqual(describe_flow_references("", REFERENCED), "")
		self.assertEqual(describe_flow_references(LINKED, ""), "")


class TestDescribeLinks(FrappeTestCase):
	def test_a_path_added_between_existing_steps_is_listed(self):
		text = describe_links(XML, LINKED)
		self.assertIn('Connected "Check Salary" to "Salary OK?".', text)

	def test_a_path_removed_between_existing_steps_is_listed(self):
		self.assertIn('Disconnected "Check Salary" from "Salary OK?".', describe_links(LINKED, XML))

	def test_the_same_path_with_a_new_id_is_not_a_change(self):
		self.assertEqual(describe_links(LINKED, LINKED.replace('id="f1"', 'id="flow_9"')), "")

	def test_a_path_to_a_new_step_is_left_to_the_added_step_line(self):
		with_new_step = XML.replace(
			"</bpmn:subProcess>",
			'<bpmn:userTask id="n" name="New"/><bpmn:sequenceFlow id="f2" sourceRef="b" targetRef="n"/></bpmn:subProcess>',
		)
		self.assertEqual(describe_links(XML, with_new_step), "")

	def test_labeled_paths_are_not_read_here(self):
		labeled = LINKED.replace('id="f1"', 'id="f1" name="Yes"')
		self.assertEqual(describe_links(XML, labeled), "")

	def test_no_diagram_before_or_after_gives_nothing(self):
		self.assertEqual(describe_links("", LINKED), "")
		self.assertEqual(describe_links(XML, ""), "")


class TestLintText(FrappeTestCase):
	def test_the_prompt_lists_each_finding_with_its_element_id_under_where_it_sits(self):
		text = lint_prompt(lint_findings(XML, [SUB_ISSUE, SUB_GATEWAY_ISSUE], scope_id="sub"))
		self.assertTrue(text.startswith("In Payroll Clearance:"))
		self.assertIn('[error] "Check Salary" (id b): Element is not connected (no-disconnected)', text)
		self.assertIn('[warn] "Salary OK?" (id g)', text)

	def test_the_main_process_is_named_when_there_is_no_sub_process(self):
		self.assertTrue(lint_prompt(lint_findings(XML, [MAIN_ISSUE])).startswith("In the main process:"))

	def test_leftovers_name_the_other_places_and_the_ones_that_need_a_person(self):
		text = lint_leftovers(lint_findings(XML, [MAIN_ISSUE, SUB_ISSUE, LAYOUT_ISSUE]))
		self.assertIn('1 in "Payroll Clearance"', text)
		self.assertIn("1 that need a person to fix", text)

	def test_nothing_is_added_when_everything_was_in_scope(self):
		self.assertEqual(lint_leftovers(lint_findings(XML, [MAIN_ISSUE])), "")

	def test_the_replies_when_there_is_nothing_to_change(self):
		self.assertIn("no lint findings to fix", no_lint_fix_reply(None))
		text = no_lint_fix_reply(lint_findings(XML, [LAYOUT_ISSUE]))
		self.assertIn('"Review": Elements overlap', text)


class LintScriptCase(FrappeTestCase):
	def setUp(self):
		lint_patch.execute()
		references_patch.execute()

	def tearDown(self):
		clear_turn(CONVERSATION)

	def _script(self, pattern, marker="resolve_scope("):
		script = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "script")
		if not script or marker not in script:
			self.skipTest("the patched ProsAlly script is not on this site")
		ast.parse(script)
		return script


class TestClassifierFixesLint(LintScriptCase):
	def _classify(self, issues, scope_id="", text=REQUEST, intent="OVERWRITE_EXISTING"):
		script = self._script("ProsAlly%Tool Classify Intent")
		set_turn(
			CONVERSATION,
			{
				"user_text": text,
				"process_name": "P",
				"current_xml": XML,
				"scope_id": scope_id,
				"lint_issues": issues,
				"chat_history": [],
			},
		)
		reply = {"intent": intent, "reason": "r", "summary": {"intro": "I'll fix them", "steps": [], "settings": []}, "question": "Go?"}
		adapter, result = RecordingAdapter(reply), {}
		with (
			patch("one_bpmn.agents.prosally_helpers.get_llm_adapter_from_settings", return_value=adapter),
			patch("one_bpmn.agents.prosally_helpers.unapplied_proposal", return_value=None),
		):
			exec(script, {"frappe": frappe, "context_docname": CONVERSATION, "result": result})
		return result, adapter

	def test_a_request_to_fix_the_findings_is_a_modify_that_lists_them_for_the_confirmation(self):
		result, adapter = self._classify([MAIN_ISSUE])
		self.assertEqual(result["intent"], "MODIFY_EXISTING")
		self.assertIn("fixing exactly these", adapter.prompts[0])
		self.assertIn('"Review" (id a): Element is not connected', adapter.prompts[0])

	def test_findings_inside_a_sub_process_make_it_the_scope(self):
		_, adapter = self._classify([SUB_ISSUE, SUB_GATEWAY_ISSUE])
		self.assertIn("In Payroll Clearance:", adapter.prompts[0])
		self.assertIn('sub-process "Payroll Clearance"', adapter.prompts[0])

	def test_no_findings_is_a_plain_answer_with_nothing_to_confirm(self):
		result, _ = self._classify([])
		self.assertEqual((result["intent"], result["next"]), ("AMBIGUOUS", "finalize"))
		output = get_turn(CONVERSATION)["output"]
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertIn("no lint findings to fix", output["response"])

	def test_findings_that_need_a_person_are_listed_and_not_confirmed(self):
		result, _ = self._classify([LAYOUT_ISSUE])
		self.assertEqual(result["next"], "finalize")
		self.assertIn("need a person", get_turn(CONVERSATION)["output"]["response"])

	def test_a_message_that_is_not_about_lint_is_left_alone(self):
		result, adapter = self._classify([MAIN_ISSUE], text="Add a step after Review")
		self.assertNotIn("lint findings", adapter.prompts[0])
		self.assertEqual(result["intent"], "OVERWRITE_EXISTING")


class TestModifierFixesLint(LintScriptCase):
	def _modify(self, issues, scope_id="", text="Yes, proceed", history=REQUEST, drawn=XML, current=XML):
		script = self._script("ProsAlly%Tool Modify Process")
		set_turn(
			CONVERSATION,
			{
				"user_text": text,
				"process_name": "P",
				"current_xml": current,
				"scope_id": scope_id,
				"lint_issues": issues,
				"chat_history": [{"role": "user", "content": history}],
			},
		)
		prompts = []

		def model(config, sub_agent_id, prompt, **kwargs):
			prompts.append(prompt)
			return '{"nodes": [], "flows": []}'

		with (
			patch("one_bpmn.agents.prosally_helpers.complete_sub_prompt", side_effect=model),
			patch("one_bpmn.agents.prosally_helpers.splice_subprocess", lambda xml, child, scope: drawn),
		):
			exec(script, {"frappe": frappe, "context_docname": CONVERSATION, "result": {}, "bpmn_id": "x"})
		return prompts[0], get_turn(CONVERSATION)["output"]

	def test_the_modifier_is_told_to_fix_exactly_the_findings_and_nothing_else(self):
		prompt, _ = self._modify([MAIN_ISSUE])
		self.assertIn("fix lint findings", prompt)
		self.assertIn('"Review" (id a): Element is not connected (no-disconnected)', prompt)

	def test_findings_inside_a_sub_process_make_the_modifier_edit_only_that_sub_process(self):
		prompt, _ = self._modify([SUB_ISSUE, SUB_GATEWAY_ISSUE])
		self.assertIn('the sub-process "Payroll Clearance"', prompt)
		self.assertIn("steps INSIDE this sub-process", prompt)

	def test_a_request_that_is_not_about_lint_adds_nothing_to_the_prompt(self):
		prompt, _ = self._modify([MAIN_ISSUE], history="Add a step after Review")
		self.assertNotIn("fix lint findings", prompt)

	def test_a_fix_that_only_adds_a_path_is_a_change_with_the_diagram_attached(self):
		_, output = self._modify([SUB_ISSUE], drawn=LINKED)
		self.assertEqual(output["intent"], "BPMN_MODIFIED")
		self.assertEqual(output["bpmn_xml"], LINKED)
		self.assertIn('Connected "Check Salary" to "Salary OK?".', output["response"])

	def test_a_fix_that_changes_nothing_is_a_plain_reply_with_no_diagram(self):
		_, output = self._modify([SUB_ISSUE])
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertNotIn("bpmn_xml", output)

	def test_a_fix_that_only_rebuilds_flow_references_is_a_change_with_the_diagram_attached(self):
		_, output = self._modify([SUB_ISSUE], current=LINKED, drawn=REFERENCED)
		self.assertEqual(output["intent"], "BPMN_MODIFIED")
		self.assertEqual(output["bpmn_xml"], REFERENCED)
		self.assertIn("Rebuilt the flow references on 2 steps", output["response"])

	def test_findings_that_could_not_be_fixed_are_counted_in_the_reply(self):
		_, output = self._modify([SUB_ISSUE, SUB_GATEWAY_ISSUE])
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertIn("could not fix the 2 lint findings", output["response"])
		self.assertIn("no-disconnected", output["response"])

	def test_the_patched_script_passes_the_validator_the_engine_runs_before_it(self):
		self.assertEqual(deep_inspect_script(self._script("ProsAlly%Tool Modify Process")), [])

	def test_what_was_left_alone_is_said_in_the_reply(self):
		_, output = self._modify([SUB_ISSUE, MAIN_ISSUE, LAYOUT_ISSUE], scope_id="sub")
		self.assertIn("Not fixed:", output["response"])
		self.assertIn("in the main process", output["response"])


class TestContextCarriesTheFindings(LintScriptCase):
	def test_the_turn_keeps_the_findings_the_editor_sent(self):
		script = self._script("ProsAlly%Build Context", marker="scope_id")
		with patch("one_bpmn.agents.prosally_helpers.answer_to_confirmation", return_value={}):
			exec(
				script,
				{
					"frappe": frappe,
					"context_docname": CONVERSATION,
					"result": {},
					"task_data": {"conversation_id": CONVERSATION, "user_text": REQUEST, "lint_issues": [MAIN_ISSUE]},
				},
			)
		self.assertEqual(get_turn(CONVERSATION)["lint_issues"], [MAIN_ISSUE])


class TestLintPatch(FrappeTestCase):
	def test_running_it_again_changes_no_script(self):
		lint_patch.execute()
		before = {
			name: frappe.db.get_value("Server Script", {"name": ["like", name]}, "script") for name in lint_patch.SCRIPTS
		}
		lint_patch.execute()
		for name, script in before.items():
			self.assertEqual(frappe.db.get_value("Server Script", {"name": ["like", name]}, "script"), script)


class TestReferencesPatch(FrappeTestCase):
	def test_running_it_again_changes_no_script(self):
		lint_patch.execute()
		references_patch.execute()
		before = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "script")
		references_patch.execute()
		after = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "script")
		self.assertEqual(after, before)
