# Copyright (c) 2026, one-fm and contributors
"""The chat knows when the diagram it proposed is not on the canvas, whether it was discarded or never applied."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.prosally_helpers import unapplied_proposal

HEAD = '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">'
BEFORE = (
	f'{HEAD}<bpmn:process id="P"><bpmn:startEvent id="s" name="Start"/>'
	'<bpmn:subProcess id="payroll" name="Payroll Clearance"/><bpmn:endEvent id="e" name="End"/>'
	'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="payroll"/></bpmn:process></bpmn:definitions>'
)
PROPOSED = BEFORE.replace(
	"</bpmn:process>",
	'<bpmn:subProcess id="accept" name="Complete Payroll Acceptance"><bpmn:userTask id="chk" name="Check Pending Salary"/>'
	'</bpmn:subProcess><bpmn:sequenceFlow id="f9" name="Yes" sourceRef="payroll" targetRef="accept"/></bpmn:process>',
)
REQUEST = "Create a new sub process for Complete Payroll Acceptance: checks pending salary"


def _reply(result):
	meta = json.dumps({"intent": result.get("intent"), "agent_result": result})
	return [SimpleNamespace(metadata=meta, creation="2026-10-15 14:00:00")]


def _modified():
	return _reply({"intent": "BPMN_MODIFIED", "bpmn_xml": PROPOSED})


def _check(last, canvas, previous=(REQUEST,), message=""):
	"""previous: the user messages sent before the reply, newest first."""

	def chat(doctype, filters=None, **kwargs):
		if filters.get("message_type") == "Bot":
			return last
		assert filters["creation"] == ["<", "2026-10-15 14:00:00"]
		return [SimpleNamespace(text=text) for text in previous]

	with patch("one_bpmn.agents.prosally_helpers.frappe.get_all", side_effect=chat):
		return unapplied_proposal("conv", canvas, message)


class TestUnappliedProposal(FrappeTestCase):
	def test_a_proposal_whose_new_elements_are_not_on_the_canvas_is_reported_with_their_names(self):
		found = _check(_modified(), BEFORE)
		self.assertEqual(found["added"], ["Complete Payroll Acceptance", "Check Pending Salary"])

	def test_a_proposal_that_was_applied_is_not_reported(self):
		self.assertIsNone(_check(_modified(), PROPOSED))

	def test_the_request_is_read_from_before_the_reply_not_from_what_the_chat_ended_with(self):
		found = _check(_modified(), BEFORE, previous=[REQUEST])
		self.assertEqual(found["request"], REQUEST)

	def test_the_request_that_led_to_it_is_the_newest_message_that_is_not_a_yes_or_a_no(self):
		found = _check(_modified(), BEFORE, previous=["Yes, proceed", REQUEST, "Something older"])
		self.assertEqual(found["request"], REQUEST)

	def test_a_message_that_names_one_of_the_missing_elements_says_which(self):
		found = _check(_modified(), BEFORE, message="add a step to Complete Payroll Acceptance")
		self.assertEqual(found["named"], ["Complete Payroll Acceptance"])

	def test_the_sub_process_with_no_name_means_the_one_that_was_proposed_when_no_existing_one_is_named(self):
		found = _check(_modified(), BEFORE, message="make the subprocess have an extra approval step")
		self.assertEqual(found["named"], ["Complete Payroll Acceptance"])

	def test_naming_an_existing_sub_process_does_not_claim_the_proposed_one(self):
		found = _check(_modified(), BEFORE, message="make the Payroll Clearance sub process have an extra approval step")
		self.assertEqual(found["named"], [])

	def test_asking_for_a_new_sub_process_does_not_claim_the_proposed_one(self):
		found = _check(_modified(), BEFORE, message="Create a new sub process for background checks: verify references")
		self.assertEqual(found["named"], [])

	def test_no_sub_process_in_the_proposal_means_the_sub_process_with_no_name_claims_nothing(self):
		step_only = BEFORE.replace("</bpmn:process>", '<bpmn:userTask id="t9" name="Notify HR"/></bpmn:process>')
		found = _check(_reply({"intent": "BPMN_MODIFIED", "bpmn_xml": step_only}), BEFORE, message="make the subprocess bigger")
		self.assertEqual(found["named"], [])

	def test_a_message_that_names_none_of_them_names_nothing(self):
		found = _check(_modified(), BEFORE, message="subprocess as call activity next to payroll clearance")
		self.assertEqual(found["named"], [])

	def test_flows_and_unnamed_elements_do_not_count_as_something_added(self):
		only_a_flow = BEFORE.replace(
			"</bpmn:process>", '<bpmn:sequenceFlow id="f9" name="Yes" sourceRef="s" targetRef="e"/></bpmn:process>'
		)
		self.assertIsNone(_check(_reply({"intent": "BPMN_MODIFIED", "bpmn_xml": only_a_flow}), BEFORE))

	def test_the_proposal_is_still_remembered_after_other_replies_came_later(self):
		later = _reply({"intent": "CLARIFY", "response": "I can't turn that into a call activity"})
		found = _check(later + _modified(), BEFORE)
		self.assertEqual(found["added"][0], "Complete Payroll Acceptance")

	def test_only_the_newest_diagram_reply_counts(self):
		newest_applied = _reply({"intent": "BPMN_MODIFIED", "bpmn_xml": BEFORE})
		self.assertIsNone(_check(newest_applied + _modified(), BEFORE))

	def test_a_last_reply_that_is_not_a_diagram_is_ignored(self):
		self.assertIsNone(_check(_reply({"intent": "CONFIRM", "action_intent": "MODIFY_EXISTING"}), BEFORE))

	def test_no_earlier_reply_means_nothing_is_unapplied(self):
		self.assertIsNone(_check([], BEFORE))

	def test_an_empty_canvas_has_nothing_to_compare_with(self):
		self.assertIsNone(_check(_modified(), ""))

	def test_a_reply_whose_result_was_not_kept_as_data_is_ignored(self):
		odd = SimpleNamespace(metadata=json.dumps({"agent_result": "not a dict"}), creation="2026-10-15 14:00:00")
		self.assertIsNone(_check([odd], BEFORE))
