# Copyright (c) 2026, one-fm and contributors
"""auto_fix_ir fixes what the compiler names exactly, so ProsAlly spends no repair pass on it."""

import copy
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers
from one_bpmn.agents.bpmn_ir_pipeline import auto_fix_ir, compile_ir
from one_bpmn.agents.turn_state import clear_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_stages_read_the_latest_message as message_patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_auto_fix_ir import with_auto_fix

GENERATE_API_METHOD = "prosally_tool_generate_process"
CONVERSATION = "_test_prosally_auto_fix_ir"

# One of each problem: no lane on "record", no default on "gw", a flow to the missing node "archive".
BROKEN_IR = {
	"lanes": [{"id": "employee", "name": "Employee"}, {"id": "manager", "name": "Manager"}],
	"nodes": [
		{"id": "start", "type": "startEvent", "name": "Request raised", "lane": "employee"},
		{"id": "submit", "type": "userTask", "name": "Submit leave request", "lane": "employee"},
		{"id": "review", "type": "userTask", "name": "Review request", "lane": "manager"},
		{"id": "gw", "type": "exclusiveGateway", "name": "Approved?", "lane": "manager"},
		{"id": "record", "type": "userTask", "name": "Record approval"},
		{"id": "end_ok", "type": "endEvent", "name": "Approved", "lane": "manager"},
		{"id": "end_no", "type": "endEvent", "name": "Rejected", "lane": "manager"},
	],
	"flows": [
		{"from": "start", "to": "submit", "name": "Start"},
		{"from": "submit", "to": "review", "name": "Submitted"},
		{"from": "review", "to": "gw", "name": "Reviewed"},
		{"from": "gw", "to": "record", "name": "Yes", "condition": "approved == true"},
		{"from": "gw", "to": "end_no", "name": "No"},
		{"from": "record", "to": "end_ok", "name": "Done"},
		{"from": "record", "to": "archive", "name": "Archive"},
	],
}


class TestAutoFixIr(FrappeTestCase):
	def test_each_exact_problem_is_fixed_and_reported(self):
		ir = copy.deepcopy(BROKEN_IR)
		fixes = auto_fix_ir(ir)
		self.assertEqual(len(fixes), 3)
		self.assertNotIn("archive", [f["to"] for f in ir["flows"]])
		self.assertTrue(next(f for f in ir["flows"] if f["to"] == "end_no")["default"])
		self.assertEqual(next(n for n in ir["nodes"] if n["id"] == "record")["lane"], "manager")
		self.assertTrue(compile_ir(ir)["ok"])
		self.assertEqual(auto_fix_ir(ir), [])

	def test_judgement_problems_stay_with_the_model(self):
		ir = copy.deepcopy(BROKEN_IR)
		next(f for f in ir["flows"] if f["to"] == "end_no")["condition"] = "approved == true"
		auto_fix_ir(ir)
		self.assertFalse(any(f.get("default") for f in ir["flows"]))

	def test_no_lanes_means_no_lane_is_invented(self):
		ir = copy.deepcopy(BROKEN_IR)
		ir["lanes"] = []
		auto_fix_ir(ir)
		self.assertNotIn("lane", next(n for n in ir["nodes"] if n["id"] == "record"))


class TestGenerateSpendsNoRepairPass(FrappeTestCase):
	"""Runs the live Generate Process Server Script; the script reaches a site with the ProsAlly map by export."""

	def setUp(self):
		self.script = frappe.db.get_value("Server Script", {"api_method": GENERATE_API_METHOD}, "script")
		if not self.script or "auto_fix_ir" not in self.script:
			self.skipTest("the patched ProsAlly Generate Process script is not on this site")

	def tearDown(self):
		clear_turn(CONVERSATION)

	def test_the_broken_ir_compiles_with_one_model_call(self):
		set_turn(CONVERSATION, {"intent": "GENERATE_NEW", "process_name": "Leave", "chat_history": []})
		result = {}
		with (
			patch.object(
				prosally_helpers, "complete_sub_prompt", return_value=json.dumps(BROKEN_IR)
			) as model,
			patch("one_bpmn.agents.observability.record_tool_artifact"),
		):
			exec(
				self.script,
				{
					"frappe": frappe,
					"context_docname": CONVERSATION,
					"result": result,
					"bpmn_id": "generate_process",
				},
			)
		self.assertEqual(model.call_count, 1)
		self.assertEqual(result["issues"], 0)
		self.assertEqual(len(result["auto_fixes"]), 3)


class TestPatchTransform(FrappeTestCase):
	SCRIPT = (
		"from one_bpmn.agents.bpmn_ir_pipeline import compile_ir, translate_problems\n"
		"repair_hints = []\nfor attempt in range(_MAX_FIX_PASSES + 1):\n"
		"    _res = compile_ir(ir_dict)\n"
		'record_tool_artifact(bpmn_id, json.dumps({"ir": ir_dict, "bpmn_xml": best_xml}, indent=1))\n'
	)

	def test_the_script_calls_auto_fix_before_compiling_and_reports_it(self):
		script = with_auto_fix(self.SCRIPT)
		self.assertIn("auto_fixes.extend(auto_fix_ir(ir_dict))\n    _res = compile_ir(ir_dict)", script)
		self.assertIn('result["auto_fixes"] = auto_fixes', script)
		self.assertIn('"auto_fixes": auto_fixes}', script)

	def test_a_moved_anchor_leaves_the_script_alone(self):
		self.assertIsNone(with_auto_fix(self.SCRIPT.replace("    _res = compile_ir(ir_dict)\n", "")))


class TestStagesReadTheLatestMessage(FrappeTestCase):
	def _run(self, script):
		doc = frappe._dict(script=script)
		doc.save = lambda **kwargs: None
		with (
			patch.object(frappe.db, "get_value", return_value="ProsAlly Generate"),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "log_error") as log_error,
		):
			message_patch.execute()
			message_patch.execute()
		return doc.script, log_error

	def test_the_message_follows_the_history_once(self):
		anchor = message_patch.ANCHORS["ProsAlly%Tool Generate Process"]
		script, _ = self._run("if _hist:\n" + anchor + '_parts.append("Output the IR JSON now.")\n')
		self.assertEqual(script.count(message_patch.MESSAGE_LINES), 1)
		self.assertIn(anchor + message_patch.MESSAGE_LINES, script)

	def test_a_script_without_the_anchor_is_logged_and_left(self):
		script, log_error = self._run("_parts = []\n")
		self.assertEqual(script, "_parts = []\n")
		log_error.assert_called()
