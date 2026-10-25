# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's replies say which lanes it drew, which named lane it missed, and what a modify changed."""

import json
import re
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0.prosally_replies_say_what_was_drawn import STAGES, with_reply_call

GENERATE_API_METHOD = "prosally_tool_generate_process"
CONVERSATION = "_test_prosally_replies"
THREE_LANES = "Create a Visa Request process with 3 lanes only: Recruiter, GRD Operator, GRD Manager. The recruiter raises it."

TWO_LANE_IR = {
	"lanes": [{"id": "recruiter", "name": "Recruiter"}, {"id": "grd_manager", "name": "GRD Manager"}],
	"nodes": [
		{"id": "start", "type": "startEvent", "name": "Request raised", "lane": "recruiter"},
		{"id": "raise", "type": "userTask", "name": "Raise visa request", "lane": "recruiter"},
		{"id": "approve", "type": "userTask", "name": "Approve request", "lane": "grd_manager"},
		{"id": "end", "type": "endEvent", "name": "Request approved", "lane": "grd_manager"},
	],
	"flows": [
		{"from": "start", "to": "raise", "name": "Start"},
		{"from": "raise", "to": "approve", "name": "Raised"},
		{"from": "approve", "to": "end", "name": "Approved"},
	],
}


class TestRequestedLanes(FrappeTestCase):
	def test_named_lane_lists_are_read(self):
		self.assertEqual(helpers.requested_lanes([THREE_LANES]), ["Recruiter", "GRD Operator", "GRD Manager"])
		self.assertEqual(
			helpers.requested_lanes(
				["Draw it with lanes Requester, Finance and Stores: the requester asks."]
			),
			["Requester", "Finance", "Stores"],
		)

	def test_the_latest_list_wins_and_vague_mentions_name_nothing(self):
		self.assertEqual(
			helpers.requested_lanes(["lanes A, B", "now use lanes Employee and Manager"]),
			["Employee", "Manager"],
		)
		self.assertEqual(helpers.requested_lanes(["add swimlanes for each role", "use lanes for HR"]), [])


class TestDescribeLanes(FrappeTestCase):
	def test_a_missing_named_lane_is_named(self):
		text = helpers.describe_lanes([{"role": "user", "content": THREE_LANES}], "Yes, proceed", TWO_LANE_IR)
		self.assertIn("Lanes drawn:\n- Recruiter\n- GRD Manager\n\nYou also asked for GRD Operator", text)

	def test_all_lanes_drawn_names_nothing_missing(self):
		text = helpers.describe_lanes([], "Draw it with lanes Recruiter and GRD Manager.", TWO_LANE_IR)
		self.assertNotIn("You also asked", text)
		self.assertEqual(helpers.describe_lanes([], THREE_LANES, {"lanes": []}), "")


class TestDescribeChanges(FrappeTestCase):
	OLD = (
		'<bpmn:userTask id="visit" name="Site Visit" /><bpmn:userTask id="ok" name="Approve" />'
		'<bpmn:sequenceFlow id="f1" sourceRef="visit" targetRef="ok" />'
	)
	NEW = (
		'<bpmn:userTask id="ok" name="Manager Approves" /><bpmn:exclusiveGateway id="dsot" name="DSOT possible?" />'
		'<bpmn:sequenceFlow id="f2" name="No" sourceRef="dsot" targetRef="ok" />'
	)

	def test_added_removed_and_renamed_are_listed(self):
		text = helpers.describe_changes(self.OLD, self.NEW)
		self.assertIn('Added the decision "DSOT possible?".', text)
		self.assertIn('Added the path "No".', text)
		self.assertIn('Removed the step "Site Visit".', text)
		self.assertIn('Renamed the step "Approve" to "Manager Approves".', text)

	def test_a_path_given_a_new_id_is_not_a_change(self):
		old = '<bpmn:userTask id="a" name="Raise" /><bpmn:sequenceFlow id="f1" name="Done" sourceRef="a" targetRef="a" />'
		new = old.replace('id="f1"', 'id="flow_7"')
		self.assertIn("could not find any change", helpers.describe_changes(old, new))

	def test_no_change_is_said_out_loud(self):
		self.assertIn("could not find any change", helpers.describe_changes(self.OLD, self.OLD))

	STEPS = (
		'<bpmn:userTask id="a" name="Raise" /><bpmn:userTask id="b" name="Review" />'
		'<bpmn:userTask id="c" name="Approve" />'
	)

	def test_a_rerouted_arrow_without_a_label_is_a_move(self):
		old = self.STEPS + '<bpmn:sequenceFlow id="f1" sourceRef="a" targetRef="b" />'
		new = self.STEPS + '<bpmn:sequenceFlow id="f1" sourceRef="a" targetRef="c" />'
		text = helpers.describe_changes(old, new)
		self.assertIn('Moved the arrow from "Raise" to "Approve".', text)
		self.assertNotIn("could not find any change", text)

	def test_a_rerouted_labeled_arrow_is_a_move(self):
		old = self.STEPS + '<bpmn:sequenceFlow id="f1" name="Yes" sourceRef="a" targetRef="b" />'
		new = self.STEPS + '<bpmn:sequenceFlow id="f9" name="Yes" sourceRef="a" targetRef="c" />'
		self.assertIn('Moved the arrow from "Raise" to "Approve".', helpers.describe_changes(old, new))

	def test_an_unlabeled_arrow_given_a_new_id_is_not_a_change(self):
		old = self.STEPS + '<bpmn:sequenceFlow id="f1" sourceRef="a" targetRef="b" />'
		new = old.replace('id="f1"', 'id="flow_7"')
		self.assertIn("could not find any change", helpers.describe_changes(old, new))


class TestGenerateNamesTheMissingLane(FrappeTestCase):
	"""Runs the live Generate Process Server Script; the script reaches a site with the ProsAlly map by export."""

	def setUp(self):
		self.script = frappe.db.get_value("Server Script", {"api_method": GENERATE_API_METHOD}, "script")
		if not self.script or "describe_lanes" not in self.script:
			self.skipTest("the patched ProsAlly Generate Process script is not on this site")

	def tearDown(self):
		clear_turn(CONVERSATION)

	def test_three_named_lanes_and_two_drawn_names_the_third(self):
		set_turn(
			CONVERSATION,
			{
				"intent": "GENERATE_NEW",
				"process_name": "Visa Request",
				"user_text": THREE_LANES,
				"chat_history": [],
			},
		)
		with (
			patch.object(helpers, "complete_sub_prompt", return_value=json.dumps(TWO_LANE_IR)),
			patch("one_bpmn.agents.observability.record_tool_artifact"),
		):
			exec(
				self.script,
				{
					"frappe": frappe,
					"context_docname": CONVERSATION,
					"result": {},
					"bpmn_id": "generate_process",
				},
			)
		self.assertIn("You also asked for GRD Operator", get_turn(CONVERSATION)["output"]["response"])


class TestPatchTransform(FrappeTestCase):
	def test_the_reply_gains_the_call_and_the_import(self):
		helper, anchor, call = STAGES["ProsAlly%Tool Modify Process"]
		script = (
			"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, extract_json\n"
			f'"response": ("I\'ve updated it."\n                {anchor},\n'
		)
		patched = with_reply_call(script, helper, anchor, call)
		self.assertIn("import complete_sub_prompt, describe_changes, extract_json", patched)
		self.assertIn(anchor + call, patched)

	def test_a_moved_anchor_leaves_the_script_alone(self):
		helper, anchor, call = STAGES["ProsAlly%Tool Generate Process"]
		self.assertIsNone(
			with_reply_call(
				"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, x\n", helper, anchor, call
			)
		)


class TestRelayout(FrappeTestCase):
	"""Draws the real fuel requisition map again; needs node to compile."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		path = frappe.get_app_path("one_bpmn", "tests", "fixtures", "lane_layout_fuel_requisition_ir.json")
		with open(path) as f:
			cls.ir = json.load(f)
		compiled = helpers.compile_ir(cls.ir)
		if not compiled.get("ok"):
			raise unittest.SkipTest("node or pipeline.mjs unavailable")
		cls.xml = compiled["xml"]

	def test_the_ir_read_back_keeps_every_step_and_arrow(self):
		ir = helpers.xml_to_ir(self.xml)
		self.assertEqual({n["id"] for n in ir["nodes"]}, {n["id"] for n in self.ir["nodes"]})
		self.assertEqual(len(ir["flows"]), len(self.ir["flows"]))
		self.assertEqual(len(ir["lanes"]), len(self.ir["lanes"]))

	def test_a_diagram_already_laid_out_says_so(self):
		self.assertEqual(helpers.relayout(self.xml), (None, "same"))

	def test_a_moved_shape_is_put_back_and_ids_and_settings_are_kept(self):
		step = self.ir["nodes"][1]["id"]
		messy = re.sub(
			rf'(<bpmndi:BPMNShape id="[^"]*" bpmnElement="{step}">\s*<dc:Bounds x=")[\d.]+', r"\g<1>9999", self.xml
		).replace(f'<bpmn:userTask id="{step}"', f'<bpmn:userTask id="{step}" spiffworkflow:assignee="kept"')
		new_xml, reason = helpers.relayout(messy)
		self.assertEqual(reason, "")
		self.assertEqual(helpers.element_names(new_xml).keys(), helpers.element_names(messy).keys())
		self.assertNotIn('x="9999"', new_xml)

	def test_a_diagram_without_lanes_is_left_to_the_editor(self):
		self.assertEqual(helpers.relayout('<bpmn:process id="p"><bpmn:startEvent id="s" /></bpmn:process>')[1], "lane-less")

	def _classify(self, turn, llm_reply="{}"):
		script = frappe.db.get_value("Server Script", {"api_method": "prosally_tool_classify_intent"}, "script")
		if not script or "relayout_output" not in script:
			self.skipTest("the patched ProsAlly Classify Intent script is not on this site")
		set_turn("RELAYOUT-TEST", {"process_name": "P", "scope_id": "", "chat_history": [], **turn})
		result = {}
		with patch("one_bpmn.agents.prosally_helpers.complete_sub_prompt", return_value=llm_reply):
			exec(script, {"frappe": frappe, "context_docname": "RELAYOUT-TEST", "result": result})
		output = get_turn("RELAYOUT-TEST").get("output")
		clear_turn("RELAYOUT-TEST")
		return result, output

	def test_a_confirmed_relayout_returns_the_diagram_drawn_again(self):
		step = self.ir["nodes"][1]["id"]
		messy = re.sub(
			rf'(<bpmndi:BPMNShape id="[^"]*" bpmnElement="{step}">\s*<dc:Bounds x=")[\d.]+', r"\g<1>9999", self.xml
		)
		result, output = self._classify({"confirmed_action": "RELAYOUT", "current_xml": messy})
		self.assertTrue(result["modified"])
		self.assertEqual(result["next"], "finalize")
		self.assertNotIn('x="9999"', output["bpmn_xml"])

	def test_a_confirmed_relayout_of_a_tidy_diagram_says_so_and_attaches_nothing(self):
		result, output = self._classify({"confirmed_action": "RELAYOUT", "current_xml": self.xml})
		self.assertFalse(result["modified"])
		self.assertNotIn("bpmn_xml", output)
		self.assertIn("already the best", output["response"])
		self.assertNotIn("I've updated", output["response"])

	def test_a_layout_complaint_asks_before_laying_out_again(self):
		reply = '{"intent": "RELAYOUT", "reason": "layout", "summary": "", "question": "Shall I lay it out again?"}'
		_result, output = self._classify(
			{"user_text": "Fix the spacing and remove the crossing lines", "current_xml": self.xml}, reply
		)
		self.assertEqual((output["intent"], output["action_intent"]), ("CONFIRM", "RELAYOUT"))

	def test_a_spec_asked_about_lists_what_is_missing_and_asks_first(self):
		spec = "What is missing?\n- Verify Final Settlement Statement\n- " + self.ir["nodes"][1]["name"]
		result, output = self._classify(
			{"user_text": spec, "current_xml": self.xml}, '{"intent": "COMPARE", "reason": "compare"}'
		)
		self.assertEqual(result["next"], "finalize")
		self.assertEqual((output["intent"], output["action_intent"]), ("CONFIRM", "MODIFY_EXISTING"))
		self.assertIn("- Verify Final Settlement Statement", output["response"])
		self.assertNotIn("- " + self.ir["nodes"][1]["name"], output["response"])
		self.assertIn("Shall I add them?", output["response"])


class TestCompareReadsInlineLists(FrappeTestCase):
	SPEC = "What is missing? Check: - Set to Draft, - Manager approves the request, - Send reminder to HR"
	XML = (
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">'
		'<bpmn:scriptTask id="a" name="Set to Draft" /><bpmn:scriptTask id="b" name="Update linked Goal progress" />'
		"</bpmn:definitions>"
	)

	def test_dash_items_run_together_on_one_line_are_each_an_item(self):
		self.assertEqual(
			helpers.spec_items(self.SPEC), ["Set to Draft", "Manager approves the request", "Send reminder to HR"]
		)

	def test_a_hyphen_inside_an_item_does_not_split_it(self):
		self.assertEqual(helpers.spec_items("- Review - then approve\n- Close"), ["Review - then approve", "Close"])

	def test_the_missing_items_of_an_inline_list_are_asked_about(self):
		output = helpers.compare_output(self.XML, [self.SPEC])
		self.assertEqual(output["intent"], "CONFIRM")
		self.assertIn("- Manager approves the request", output["response"])
		self.assertIn("- Send reminder to HR", output["response"])
		self.assertNotIn("- Set to Draft", output["response"])


class TestNoChangeIsNotAnUpdate(FrappeTestCase):
	"""Runs the live Modify Process script on a saved diagram that lists its flow references."""

	IR = {
		"name": "P",
		"lanes": [{"id": "staff", "name": "Staff"}, {"id": "manager", "name": "Manager"}],
		"nodes": [
			{"id": "start", "name": "Request raised", "type": "startEvent", "lane": "staff"},
			{"id": "raise", "name": "Raise the request", "type": "userTask", "lane": "staff"},
			{"id": "approve", "name": "Approve the request", "type": "userTask", "lane": "manager"},
			{"id": "end", "name": "Request closed", "type": "endEvent", "lane": "manager"},
		],
		"flows": [
			{"from": "start", "to": "raise"},
			{"from": "raise", "to": "approve"},
			{"from": "approve", "to": "end"},
		],
	}

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		compiled = helpers.compile_ir(cls.IR)
		if not compiled.get("ok"):
			raise unittest.SkipTest("node or pipeline.mjs unavailable")
		helpers._register_namespaces()
		root = ET.fromstring(compiled["xml"])
		for process in root.iter("{" + helpers.NS["bpmn"] + "}process"):
			helpers.add_flow_references(process)
		cls.with_references = ET.tostring(root, encoding="unicode")

	def _modify(self, user_text):
		name = frappe.db.get_value("Server Script", {"name": ["like", "ProsAlly%Tool Modify Process"]}, "name")
		script = frappe.db.get_value("Server Script", name, "script") if name else ""
		if "describe_flow_references" not in (script or ""):
			self.skipTest("the patched ProsAlly Modify Process script is not on this site")
		set_turn(
			"NO-CHANGE-TEST",
			{"user_text": user_text, "process_name": "P", "current_xml": self.with_references, "scope_id": "", "chat_history": []},
		)
		result = {}
		with patch("one_bpmn.agents.prosally_helpers.complete_sub_prompt", return_value=json.dumps(self.IR)):
			exec(script, {"frappe": frappe, "context_docname": "NO-CHANGE-TEST", "result": result, "bpmn_id": "x"})
		output = get_turn("NO-CHANGE-TEST")["output"]
		clear_turn("NO-CHANGE-TEST")
		return result, output

	def test_a_request_that_only_rebuilds_flow_references_changes_nothing(self):
		result, output = self._modify("Add a step Approve the request")
		self.assertFalse(result["modified"])
		self.assertEqual(output["intent"], "CLARIFY")
		self.assertNotIn("bpmn_xml", output)
		self.assertNotIn("I've updated", output["response"])
		self.assertNotIn("Rebuilt the flow references", output["response"])
