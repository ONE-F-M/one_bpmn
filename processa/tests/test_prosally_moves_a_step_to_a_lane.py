# Copyright (c) 2026, one-fm and contributors
"""Moving a step to another lane is done on the diagram itself: no model redraws the process."""

import re
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import tools_review
from processa.ai_agent_registry.definitions.prosally.tools_pipeline import compile_ir, element_names

BUDDY = "Assign Buddy and First-Week Tasks"
IR = {
	"name": "Onboarding",
	"lanes": [{"id": "lane_hr", "name": "HR Officer"}, {"id": "lane_hm", "name": "Hiring Manager"}],
	"nodes": [
		{"id": "start", "name": "Offer accepted", "type": "startEvent", "lane": "lane_hr"},
		{"id": "buddy", "name": BUDDY, "type": "userTask", "lane": "lane_hr"},
		{"id": "confirm", "name": "Confirm Start Date", "type": "userTask", "lane": "lane_hm"},
		{"id": "done", "name": "Confirmed", "type": "endEvent", "lane": "lane_hm"},
	],
	"flows": [
		{"id": "f1", "from": "start", "to": "buddy"},
		{"id": "f2", "from": "buddy", "to": "confirm"},
		{"id": "f3", "from": "confirm", "to": "done"},
	],
}


def _lane_of(xml: str, step_id: str) -> str:
	for name, body in re.findall(r'<bpmn:lane\s[^>]*name="([^"]*)"[^>]*>(.*?)</bpmn:lane>', xml, re.S):
		if f"<bpmn:flowNodeRef>{step_id}</bpmn:flowNodeRef>" in body:
			return name
	return ""


class TestMoveAStepToALane(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		compiled = compile_ir(IR)
		assert compiled.get("ok"), compiled.get("problems")
		# A setting on the step, to prove the move keeps it.
		cls.xml = (
			compiled["xml"]
			.replace(
				"<bpmn:definitions ",
				'<bpmn:definitions xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" ',
				1,
			)
			.replace('id="buddy"', 'id="buddy" spiffworkflow:targetDoctype="Employee"', 1)
		)
		assert _lane_of(cls.xml, "buddy") == "HR Officer"

	def _move(self, text: str):
		with patch.object(
			tools_review, "complete_sub_prompt", side_effect=AssertionError("a model was asked")
		):
			return tools_review.move_to_lane_output(self.xml, text)

	def test_the_step_moves_and_everything_else_is_kept(self):
		out = self._move("bring back assign buddy and first week tasks, into hiring manager")

		self.assertEqual((out["intent"], out["action_intent"]), ("BPMN_MODIFIED", "MOVE_TO_LANE"))
		self.assertEqual(_lane_of(out["bpmn_xml"], "buddy"), "Hiring Manager")
		self.assertEqual(_lane_of(out["bpmn_xml"], "confirm"), "Hiring Manager")
		self.assertEqual(element_names(out["bpmn_xml"]), element_names(self.xml))
		self.assertIn('spiffworkflow:targetDoctype="Employee"', out["bpmn_xml"])
		self.assertIn(f'I moved "{BUDDY}" to the lane "Hiring Manager"', out["response"])

	def test_a_message_that_asks_for_more_than_the_move_is_left_to_the_modifier(self):
		self.assertIsNone(
			self._move(f"move {BUDDY} to the Hiring Manager lane and rename it to Welcome Pack")
		)
		self.assertIsNone(self._move("add a review step to the Hiring Manager lane"))

	def test_a_step_or_a_lane_that_is_not_on_the_diagram_is_left_to_the_classifier(self):
		self.assertIsNone(self._move("move Issue ID Card to the Hiring Manager lane"))
		self.assertIsNone(self._move(f"move {BUDDY} to the Finance lane"))

	def test_a_step_already_in_that_lane_is_not_a_move(self):
		self.assertIsNone(self._move("move Confirm Start Date to the Hiring Manager lane"))
