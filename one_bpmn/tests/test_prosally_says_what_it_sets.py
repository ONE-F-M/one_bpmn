# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir
from one_bpmn.agents.prosally_helpers import describe_task_config
from one_bpmn.one_bpmn.patches.v1_0 import prosally_says_what_it_sets as patch

START = {
	"id": "start",
	"type": "startEvent",
	"name": "Incident Raised",
	"lane": "staff",
	"config": {"triggerDoctype": "Incident Report", "triggerType": "After Insert"},
}
REVIEW = {
	"id": "review",
	"type": "userTask",
	"name": "Review Incident",
	"lane": "supervisor",
	"config": {
		"targetDoctype": "Incident Report",
		"assigneeMode": "DocField",
		"assigneeDocfield": "supervisor",
		"taskActions": [{"action": "Approve", "confirmTransition": True}, "Reject"],
	},
}
CLOSE = {
	"id": "close",
	"type": "serviceTask",
	"name": "Close Incident",
	"lane": "supervisor",
	"config": {"serviceType": "apply_workflow", "serviceTargetDoctype": "Incident Report", "workflowState": "Closed"},
}
END = {"id": "end", "type": "endEvent", "name": "Done", "lane": "supervisor"}


def _diagram(with_close_step=False):
	steps = [START, REVIEW, CLOSE, END] if with_close_step else [START, REVIEW, END]
	ir = {
		"process": {"id": "incident", "name": "Incident Handling"},
		"lanes": [{"id": "staff", "name": "Staff"}, {"id": "supervisor", "name": "Supervisor"}],
		"nodes": [dict(step) for step in steps],
		"flows": [{"from": a["id"], "to": b["id"]} for a, b in zip(steps, steps[1:])],
	}
	return compile_ir(ir)["xml"]


class TestTheReplyListsWhatWasSet(FrappeTestCase):
	def test_a_new_diagram_lists_its_trigger_and_assignment(self):
		text = describe_task_config(_diagram())
		self.assertIn("The process starts when a new Incident Report is created.", text)
		self.assertIn(
			"Review Incident works on the Incident Report, is assigned to the person in the supervisor field, "
			"has the buttons Approve, Reject.",
			text,
		)

	def test_an_update_lists_only_the_settings_it_added(self):
		text = describe_task_config(_diagram(with_close_step=True), _diagram())
		self.assertIn("Close Incident moves the Incident Report to Closed.", text)
		self.assertNotIn("Review Incident", text)
		self.assertNotIn("starts when", text)

	def test_a_diagram_without_new_settings_adds_nothing_to_the_reply(self):
		self.assertEqual(describe_task_config(_diagram(), _diagram()), "")
		self.assertEqual(describe_task_config(""), "")

	def test_a_task_waiting_for_an_assignee_says_so(self):
		xml = _diagram().replace(' spiffworkflow:assigneeDocfield="supervisor"', "")
		self.assertIn("Review Incident works on the Incident Report, has no one chosen to do it yet", describe_task_config(xml))


class TestThePatch(FrappeTestCase):
	def test_the_stage_scripts_call_the_describer_once_each_after_a_rerun(self):
		patch.execute()
		patch.execute()
		for pattern in patch.SCRIPTS:
			script = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "script")
			if script is None:
				self.skipTest("ProsAlly is not on this site")
			self.assertEqual(script.count("describe_task_config("), 1, pattern)

	def test_the_prompts_carry_their_rules_once_after_a_rerun(self):
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": patch.AGENT_ID}, "name")
		if not name:
			self.skipTest("ProsAlly is not on this site")
		patch.execute()
		patch.execute()
		prompts = {r.sub_agent_id: r.prompt_text for r in frappe.get_doc("AI Agent Configuration", name).sub_prompts}
		self.assertEqual(prompts["intent_classifier"].count('reply "draw only"'), 1)
		self.assertEqual(prompts["process_generator"].count("leave out every config object"), 1)
