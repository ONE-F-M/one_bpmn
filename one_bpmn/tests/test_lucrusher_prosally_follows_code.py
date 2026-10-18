# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""LuCrusher's ProsAlly drafts follow the code and the Workflow, run against the BA site's scripts."""

import html
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.tool_bounds import validate_tool_arguments
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_prosally_follows_code_and_workflow as p
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import SKILLS
from one_bpmn.security.script_validator import deep_inspect_script

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
	return (FIXTURES / name).read_text(encoding="utf-8")


def _block(elements, header="C: ELEMENTS"):
	lines = [f"{n}. UserTask | Step {n} | Lane | src=a.py:b" for n in range(1, elements + 1)]
	return "\n".join(["A: HEADER", "B: LANES", header, *lines, "D: SEQUENCE FLOWS", "1. 1 -> 2"])


def _process(elements=5, process_id="p1", **extra):
	return {
		"process_name": "P",
		"process_id": process_id,
		"element_count": elements,
		"prompt_block": _block(elements),
		"source": "Page 1",
		**extra,
	}


class TestSkillEdit(FrappeTestCase):
	def setUp(self):
		body = next(s["body"] for s in SKILLS if s["skill_name"] == p.PROSALLY_SKILL)
		self.body = body.replace("prompt_block}]}", "prompt_block, source}]}")

	def test_skill_gains_the_rules_once(self):
		out = p.with_grounding(self.body)
		for text in ("allowed field", "read_doctype_logic", "at most 25 elements", "## Conflicts", "coverage"):
			self.assertIn(text, out)
		self.assertEqual(p.with_grounding(out), out)

	def test_edited_skill_is_left_alone(self):
		edited = self.body.replace(p.RULE_OLD, "- Edited.")
		self.assertEqual(p.with_grounding(edited), edited)


def _schema_xml(prosally):
	schema = {
		"properties": {
			"intent": {"type": "string"},
			"response": {"type": "string"},
			"prosally_prompts": {"type": "object", "properties": {"processes": prosally}},
		},
		"required": ["intent", "response"],
	}
	params = html.escape(json.dumps(schema), quote=True)
	return f'<bpmn:scriptTask id="finalize" name="finalize" spiffworkflow:aiToolParams="{params}">'


def _checker(omit_coverage=False):
	xml = p.with_prosally_schema(_schema_xml({"type": "array"}))
	schema = json.loads(html.unescape(p.FINALIZE_PARAMS.search(xml).group(1)))

	def check(**prompts):
		if not omit_coverage:
			prompts.setdefault("coverage", [])
		return validate_tool_arguments(
			"finalize",
			schema["properties"],
			schema["required"],
			{"intent": "PROSALLY_PROMPT_DRAFT", "response": "ok", "prosally_prompts": prompts},
		)

	return check


class TestFinalizeSchema(FrappeTestCase):
	def test_schema_is_added_once(self):
		before = _schema_xml({"type": "array"})
		xml = p.with_prosally_schema(before)
		self.assertNotEqual(xml, before)
		self.assertEqual(p.with_prosally_schema(xml), xml)

	def test_xml_without_a_finalize_shape_is_left_alone(self):
		self.assertEqual(p.with_prosally_schema("<bpmn:definitions/>"), "<bpmn:definitions/>")

	def test_three_processes_are_rejected_and_two_pass(self):
		check = _checker()
		three = [_process(process_id=f"p{n}") for n in range(3)]
		self.assertIn("processes", check(processes=three))
		self.assertIsNone(check(processes=three[:2]))

	def test_element_count_over_25_is_rejected(self):
		check = _checker()
		self.assertIn("element_count", check(processes=[_process(26)]))
		self.assertIsNone(check(processes=[_process(25)]))

	def test_covered_row_needs_an_element_and_a_gap_does_not(self):
		check = _checker()
		covered = {"behaviour": "wait", "citation": "a.py:b", "status": "Covered"}
		gap = {"behaviour": "wait", "citation": "a.py:b", "status": "Gap"}
		self.assertIsNotNone(check(processes=[_process()], coverage=[covered]))
		self.assertIsNone(check(processes=[_process()], coverage=[{**covered, "element": 3}, gap]))

	def test_a_draft_without_coverage_is_rejected(self):
		self.assertIn("coverage", _checker(omit_coverage=True)(processes=[_process()]))

	def test_conflict_needs_a_topic_and_citation(self):
		check = _checker()
		self.assertIsNotNone(check(processes=[_process()], conflicts=[{"topic": "base date"}]))
		self.assertIsNone(
			check(processes=[_process()], conflicts=[{"topic": "base date", "citation": "a.py:b"}])
		)


def _finalize_script():
	return p.apply_edits(_fixture("lucrusher_finalize_ba.txt"), p.FINALIZE_EDITS, p.FINALIZE_MARKER)


def _run_finalize(prosally_prompts):
	scope = {"task_data": {"prosally_prompts": prosally_prompts}, "context_docname": "x", "result": {}}
	stored = {}
	with (
		patch("one_bpmn.agents.turn_state.get_turn", return_value={}),
		patch("one_bpmn.agents.turn_state.update_turn", side_effect=lambda _n, **kw: stored.update(kw)),
	):
		exec(_finalize_script(), scope, {})  # noqa: S102 - the patched script text under test
	return stored["output"]["prosally_prompts"]


class TestFinalizeScript(FrappeTestCase):
	def test_script_passes_the_script_gate(self):
		self.assertEqual(deep_inspect_script(_finalize_script()), [])

	def test_edit_is_applied_once_and_a_moved_anchor_is_left_alone(self):
		original = _fixture("lucrusher_finalize_ba.txt")
		once = _finalize_script()
		self.assertNotEqual(once, original)
		self.assertEqual(p.apply_edits(once, p.FINALIZE_EDITS, p.FINALIZE_MARKER), once)
		self.assertEqual(p.apply_edits("x = 1\n", p.FINALIZE_EDITS, p.FINALIZE_MARKER), "x = 1\n")

	def test_block_over_25_raises_even_when_it_reports_fewer(self):
		with self.assertRaises(ValueError) as caught:
			_run_finalize({"processes": [{**_process(26), "element_count": 20}]})
		self.assertIn("26", str(caught.exception))

	def test_element_count_is_the_counted_one(self):
		out = _run_finalize({"processes": [{**_process(25), "element_count": 3}]})
		self.assertEqual(out["processes"][0]["element_count"], 25)

	def test_confirmation_without_prompts_passes(self):
		self.assertIsNone(_run_finalize(None))


def _run_save_response(previous, new):
	script = p.apply_edits(_fixture("lucrusher_save_response_current_ba.txt"), p.SAVE_EDITS, p.SAVE_MARKER)
	recorded = {}
	message = SimpleNamespace(name="MSG-1", insert=lambda: None)
	output = {"intent": "PROSALLY_PROMPT_DRAFT", "response": "ok", "prosally_prompts": new}
	scope = {
		"frappe": SimpleNamespace(new_doc=lambda _doctype: message),
		"task_data": {"conversation_id": "c"},
		"context_docname": "c",
		"result": {},
	}
	with (
		patch("one_bpmn.agents.turn_state.get_turn", return_value={"output": output, "context_state": previous}),
		patch("one_bpmn.agents.turn_state.clear_turn"),
		patch("one_bpmn.agents.memory.session_state.record", side_effect=lambda _c, snap: recorded.update(snap)),
	):
		exec(script, scope)  # noqa: S102 - the patched script text under test, whose helpers read its module names
	return recorded["prosally_prompts"], json.loads(message.metadata)["agent_result"]["prosally_prompts"]


class TestSaveResponseMerge(FrappeTestCase):
	def test_second_call_adds_to_the_first_and_replaces_a_redraft(self):
		first = {"processes": [_process(3, "a"), _process(4, "b")], "remaining": ["c"]}
		second = {"processes": [_process(7, "b"), _process(5, "c")], "remaining": []}
		held, shown = _run_save_response({"prosally_prompts": first}, second)
		for value in (held, shown):
			self.assertEqual(sorted(x["process_id"] for x in value["processes"]), ["a", "b", "c"])
			self.assertEqual({x["process_id"]: x["element_count"] for x in value["processes"]}["b"], 7)
			self.assertEqual(value["remaining"], [])

	def test_first_call_is_kept_as_sent(self):
		first = {"processes": [_process(3, "a")], "remaining": ["b"]}
		held, _ = _run_save_response({}, first)
		self.assertEqual(held, first)

	def test_moved_anchor_is_left_alone(self):
		self.assertEqual(p.apply_edits("x = 1\n", p.SAVE_EDITS, p.SAVE_MARKER), "x = 1\n")


class TestBuildContextLine(FrappeTestCase):
	def test_line_names_the_processes_left(self):
		script = p.apply_edits(_fixture("lucrusher_build_context_ba.txt"), p.CONTEXT_EDITS, p.CONTEXT_MARKER)
		self.assertIn('" remaining: "', script)
		compile(script, "build_context", "exec")
		self.assertEqual(p.apply_edits(script, p.CONTEXT_EDITS, p.CONTEXT_MARKER), script)
