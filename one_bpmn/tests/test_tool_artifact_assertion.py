# Copyright (c) 2026, one-fm and contributors
"""The tool_artifact assertion, the trace field it reads, and the ProsAlly cases built on it."""

from __future__ import annotations

import json
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import eval_runner
from one_bpmn.agents.eval_runner import _evaluate_assertion
from one_bpmn.one_bpmn.patches.v1_0 import seed_prosally_baseline_suite

IR = {"ir": {"lanes": [{"id": "r", "name": "Recruiter"}, {"id": "m", "name": "GRD Manager"}]}}
LANES = ["Recruiter", "GRD Manager"]


def _check(spec, trace):
	assertion = SimpleNamespace(assertion_type="tool_artifact", value=json.dumps(spec))
	return _evaluate_assertion(assertion, "reply", {"tool_trace": trace})


def _call(tool="generate_process", artifact="", artifact_file=None):
	return {"tool": tool, "args": {}, "status": "Success", "artifact": artifact, "artifact_file": artifact_file}


def _lanes_spec(matcher="equals", expected=LANES):
	return {"tool": "generate_process", "path": "ir.lanes.name", "matcher": matcher, "expected": expected}


class TestToolArtifactAssertion(FrappeTestCase):
	def test_a_path_through_a_list_matches_every_item(self):
		self.assertTrue(_check(_lanes_spec(), [_call(artifact=json.dumps(IR))])["passed"])

	def test_an_extra_lane_fails(self):
		ir = {"ir": {"lanes": [*IR["ir"]["lanes"], {"id": "s", "name": "System (Automatic)"}]}}
		result = _check(_lanes_spec(), [_call(artifact=json.dumps(ir))])
		self.assertFalse(result["passed"])
		self.assertFalse(result.get("error"))

	def test_contains_finds_one_lane(self):
		spec = _lanes_spec("contains", "GRD Manager")
		self.assertTrue(_check(spec, [_call(artifact=json.dumps(IR))])["passed"])

	def test_the_last_call_with_an_artifact_is_the_one_checked(self):
		stale = {"ir": {"lanes": [{"id": "u", "name": "User"}]}}
		trace = [_call(artifact=json.dumps(stale)), _call(artifact=json.dumps(IR)), _call()]
		self.assertTrue(_check(_lanes_spec(), trace)["passed"])

	def test_no_artifact_is_an_error_not_a_pass(self):
		result = _check(_lanes_spec(), [_call(), _call(tool="finalize", artifact=json.dumps(IR))])
		self.assertFalse(result["passed"])
		self.assertTrue(result["error"])

	def test_a_replay_cannot_check_an_artifact(self):
		assertion = SimpleNamespace(assertion_type="tool_artifact", value=json.dumps(_lanes_spec()))
		result = _evaluate_assertion(assertion, "reply")
		self.assertTrue(result["error"])

	def test_an_artifact_offloaded_to_a_file_is_read_from_it(self):
		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": "generate_process-artifact-test.txt",
			"content": json.dumps(IR),
			"is_private": 1,
		}).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "File", file_doc.name, force=True)
		self.assertTrue(_check(_lanes_spec(), [_call(artifact_file=file_doc.name)])["passed"])

	def test_the_trace_carries_the_recorded_artifact(self):
		run = frappe.get_doc({
			"doctype": "AI Agent Run",
			"bpmn_id": "run_prosally_agent",
			"origin": "eval",
			"eval_case": "artifact-case",
			"eval_run": "artifact-run",
			"status": "Success",
			"started_at": frappe.utils.now_datetime(),
		}).insert(ignore_permissions=True, ignore_links=True)
		step = frappe.get_doc({"doctype": "AI Agent Step", "run": run.name, "step_index": 1, "role": "assistant"})
		step.append("tool_calls", {"tool_name": "generate_process", "status": "Success", "tool_artifact": json.dumps(IR)})
		step.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "AI Agent Step", step.name, force=True)
		self.addCleanup(frappe.delete_doc, "AI Agent Run", run.name, force=True)

		trace = eval_runner._tool_trace_for(SimpleNamespace(name="artifact-case"), "artifact-run")
		self.assertEqual(trace[0]["artifact"], json.dumps(IR))
		self.assertTrue(_check(_lanes_spec(), trace)["passed"])


class TestProsAllyBaselineCases(FrappeTestCase):
	def test_the_named_lane_case_passes_on_exactly_those_lanes_and_fails_on_an_extra_one(self):
		lane_check = next(
			a for a in seed_prosally_baseline_suite.CASES[0]["assertions"] if a["assertion_type"] == "tool_artifact"
		)
		spec = json.loads(lane_check["value"])
		names = spec["expected"]
		good = {"ir": {"lanes": [{"id": str(i), "name": n} for i, n in enumerate(names)]}}
		bad = {"ir": {"lanes": [*good["ir"]["lanes"], {"id": "s", "name": "System (Automatic)"}]}}
		self.assertTrue(_check(spec, [_call(artifact=json.dumps(good))])["passed"])
		self.assertFalse(_check(spec, [_call(artifact=json.dumps(bad))])["passed"])

	def test_every_case_forbids_the_skill_tools(self):
		for case in seed_prosally_baseline_suite.CASES:
			banned = [a["value"] for a in case["assertions"] if a["assertion_type"] == "no_tool_call"]
			self.assertIn("load_skill", banned[0], case["title"])
