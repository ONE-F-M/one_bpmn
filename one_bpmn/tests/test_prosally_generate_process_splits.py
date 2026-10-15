# Copyright (c) 2026, one-fm and contributors
"""A large ProsAlly process is drawn in split phases instead of failing as too large.

The tests run the live Generate Process script as it is on BA and on Staging (the two files under
fixtures/), with the split patch applied and only the model and the database faked.
"""

import difflib
import json
import re
from contextlib import ExitStack
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir
from one_bpmn.agents.llm_provider.base import LLMTruncatedError
from one_bpmn.agents.observability import record_truncated_calls
from one_bpmn.one_bpmn.patches.v1_0 import (
	prosally_generate_process_records_cut_offs_without_getattr as repair_patch,
)
from one_bpmn.one_bpmn.patches.v1_0 import prosally_generate_process_splits_cut_off_phases as split_patch
from one_bpmn.security.script_validator import ValidatorOptions, deep_inspect_script

FIXTURES = Path(__file__).parent / "fixtures"
SHAPES = ("ba", "staging")
HELPERS = "one_bpmn.agents.prosally_helpers"
PIPELINE = "one_bpmn.agents.bpmn_ir_pipeline"
OBSERVABILITY = "one_bpmn.agents.observability"
TOOL = "ProsAlly - Tool Generate Process"

OUTLINE = {
	"lanes": [{"id": "user", "name": "User"}, {"id": "system", "name": "System (Automatic)"}],
	"phases": [
		{"id": "intake", "name": "Intake", "description": "receive the request"},
		{"id": "review", "name": "Review", "description": "review the request"},
		{"id": "close", "name": "Close", "description": "close the request"},
	],
}
FULL_IR = {
	"lanes": OUTLINE["lanes"],
	"nodes": [
		{"id": "s", "type": "startEvent", "name": "Start", "lane": "user"},
		{"id": "t", "type": "userTask", "name": "Do it", "lane": "user"},
		{"id": "e", "type": "endEvent", "name": "End", "lane": "user"},
	],
	"flows": [{"from": "s", "to": "t"}, {"from": "t", "to": "e"}],
}
COMPILED = {"ok": True, "xml": "<definitions/>", "problems": [], "topology": {}, "layout": {}}
INLINE_TYPES = ("StartEvent", "ScriptTask", "ExclusiveGateway", "UserTask", "EndEvent")
EDITED_LINES = 8
STRICT = ValidatorOptions(strict_builtins=True, strict_frappe_attrs=True)


def _script(shape):
	return (FIXTURES / f"prosally_generate_process_{shape}.txt").read_text()


def _is_full_attempt(user):
	return (
		"Action: GENERATE_NEW" in user
		and "(generating ONE PHASE" not in user
		and "output ONLY an outline" not in user
	)


def _phase_reply(user):
	index = int(re.search(r"This phase \((\d+) of \d+\)", user).group(1))
	piece = re.search(r"from (\d+)% to (\d+)%", user)
	tag = "p" + str(index) + (f"_{piece.group(1)}_{piece.group(2)}" if piece else "")
	nodes = []
	if "include the process's single startEvent" in user:
		nodes.append({"id": tag + "_start", "type": "startEvent", "name": "Start", "lane": "user"})
	nodes.append({"id": tag + "_a", "type": "userTask", "name": tag, "lane": "user"})
	nodes.append({"id": tag + "_b", "type": "userTask", "name": tag, "lane": "user"})
	if "include at least one endEvent" in user:
		nodes.append({"id": tag + "_end", "type": "endEvent", "name": "End", "lane": "user"})
	flows = [{"from": a["id"], "to": b["id"]} for a, b in pairwise(nodes)]
	incoming = re.search(r'must come from node id "([^"]+)"', user)
	if incoming:
		flows.insert(0, {"from": incoming.group(1), "to": nodes[0]["id"]})
	return json.dumps({"nodes": nodes, "flows": flows})


class FakeModel:
	"""Answers the prompts of the Generate Process script, recording each call and cutting off the ones asked for."""

	def __init__(self, should_cut):
		self.should_cut = should_cut
		self.calls = []
		self.cut_offs = 0

	def answer(self, user, max_tokens):
		self.calls.append({"user": user, "max_tokens": max_tokens})
		if "output ONLY an outline" in user and "(generating ONE PHASE" not in user:
			return json.dumps(OUTLINE)
		if self.should_cut(user):
			self.cut_offs += 1
			raise LLMTruncatedError("cut off at the token ceiling")
		if "(generating ONE PHASE" in user:
			return _phase_reply(user)
		return json.dumps(FULL_IR)

	@property
	def phase_calls(self):
		return [c for c in self.calls if "(generating ONE PHASE" in c["user"]]


class FakeAdapter:
	"""The model adapter the older Staging script calls directly."""

	def __init__(self, model):
		self.model = model

	async def complete(self, system, user, max_tokens=None):
		return SimpleNamespace(text=self.model.answer(user, max_tokens))


def run_generate(shape, should_cut=lambda user: False, text="Model a leave request process."):
	model = FakeModel(should_cut)
	script = split_patch.rewrite(_script(shape))
	cfg = {"sub_prompts": {"process_generator": {"prompt": "You generate BPMN IR."}}, "max_tokens": 16384}
	turn = {
		"intent": "GENERATE_NEW",
		"process_name": "Leave",
		"chat_history": [{"role": "user", "content": text}],
		"user_text": "Yes, proceed",
	}
	run_doc = mock.Mock(model="sonnet")
	run_doc.name = "RUN-1"
	ran = SimpleNamespace(
		model=model,
		result={},
		compile_ir=mock.Mock(return_value=COMPILED),
		record_step=mock.Mock(),
		record_artifact=mock.Mock(),
		update_turn=mock.Mock(),
		auto_fix_ir=mock.Mock(return_value=[]),
	)

	def fake_complete(cfg, sub_id, user, system=None, max_tokens=None):
		return model.answer(user, max_tokens)

	patches = [
		mock.patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
		mock.patch("one_bpmn.agents.turn_state.update_turn", ran.update_turn),
		mock.patch(f"{PIPELINE}.compile_ir", ran.compile_ir),
		mock.patch(f"{PIPELINE}.auto_fix_ir", ran.auto_fix_ir),
		mock.patch(f"{PIPELINE}.ensure_default_lanes", return_value=True),
		mock.patch(f"{PIPELINE}.extract_process_name", return_value="Leave"),
		mock.patch("one_bpmn.security.bpmn_validator.validate_bpmn_xml", return_value={"valid": True}),
		mock.patch(f"{OBSERVABILITY}.current_sub_call", return_value={"run": "RUN-1", "tool": TOOL}),
		mock.patch(f"{OBSERVABILITY}.record_ai_step", ran.record_step),
		mock.patch(f"{OBSERVABILITY}.record_tool_artifact", ran.record_artifact),
		mock.patch.object(frappe, "get_doc", return_value=run_doc),
		mock.patch.object(frappe.db, "count", return_value=0),
	]
	if shape == "ba":
		patches += [
			mock.patch(f"{HELPERS}.complete_sub_prompt", fake_complete),
			mock.patch(f"{HELPERS}.prosally_config", return_value=cfg),
			mock.patch(f"{HELPERS}.stage_max_tokens", return_value=16384),
			mock.patch(f"{HELPERS}.stage_system_prompt", return_value="SYSTEM"),
			mock.patch(f"{HELPERS}.describe_lanes", return_value=" LANES"),
			mock.patch(f"{HELPERS}.describe_task_config", return_value=" TASKS"),
		]
	else:
		patches += [
			mock.patch(
				"one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=FakeAdapter(model)
			),
			mock.patch(
				"one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config",
				return_value=cfg,
			),
			mock.patch.object(frappe, "get_all", return_value=[]),
		]
	with ExitStack() as stack:
		for patcher in patches:
			stack.enter_context(patcher)
		# Split globals and locals, as the tool-script runner executes it: names in a def or comprehension body are not visible.
		exec(
			script,
			{"frappe": frappe, "context_docname": "TEST-TURN", "result": ran.result, "bpmn_id": "BPMN-1"},
			{},
		)
	return ran


def _request(inline=0, numbered=0):
	text = "Model a leave request process."
	if numbered:
		text += "\n" + "\n".join(f"{i + 1}. Step number {i + 1}" for i in range(numbered))
	if inline:
		text += "\nC. ELEMENTS " + " ".join(
			f"{i + 1} {INLINE_TYPES[i % len(INLINE_TYPES)]} 'Step {i + 1}'|Sys" for i in range(inline)
		)
	return text


def cut_phase_two_once(user):
	return "This phase (2 of 3)" in user and "% to " not in user


def cut_every_piece_of_review(user):
	return "(generating ONE PHASE" in user and "Review" in user


class TestThePatchOnTheRealScripts(FrappeTestCase):
	def test_it_applies_compiles_and_a_second_run_changes_nothing(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				script = _script(shape)
				patched = split_patch.rewrite(script)
				compile(patched, shape, "exec")
				self.assertNotEqual(patched, script)
				self.assertEqual(split_patch.rewrite(patched), patched)

	def test_every_feature_the_script_already_has_is_kept(self):
		features = (
			"auto_fix_ir",
			"record_tool_artifact",
			"merge_chunked_ir",
			"chunk_exit_node_id",
			"ensure_default_lanes",
			"validate_bpmn_xml",
			"stage_system_prompt",
			"describe_lanes",
			"describe_task_config",
			"prosally_config",
			"format_history",
			"stage_max_tokens",
		)
		for shape in SHAPES:
			with self.subTest(shape=shape):
				before, after = _script(shape), split_patch.rewrite(_script(shape))
				self.assertEqual([f for f in features if f in before and f not in after], [])

	def test_a_script_missing_an_anchor_raises_and_changes_nothing(self):
		with self.assertRaises(ValueError):
			split_patch.rewrite("import json\nx = 1\n")

	def test_the_script_is_found_by_api_method_and_written_back_patched(self):
		with (
			mock.patch.object(frappe.db, "get_value", side_effect=["Any Name", _script("ba")]) as get_value,
			mock.patch.object(frappe.db, "set_value") as set_value,
		):
			split_patch.execute()
		self.assertEqual(
			get_value.call_args_list[0].args,
			("Server Script", {"api_method": "prosally_tool_generate_process"}, "name"),
		)
		self.assertEqual(set_value.call_args.args[:3], ("Server Script", "Any Name", "script"))
		self.assertIn("_MAX_SPLIT_DEPTH", set_value.call_args.args[3])

	def test_a_missing_script_or_anchor_is_logged_and_nothing_is_written(self):
		for values in ([None], ["Any Name", "import json\nx = 1\n"]):
			with (
				mock.patch.object(frappe.db, "get_value", side_effect=values),
				mock.patch.object(frappe, "log_error") as log_error,
				mock.patch.object(frappe.db, "set_value") as set_value,
			):
				split_patch.execute()
			log_error.assert_called_once()
			set_value.assert_not_called()


class TestASplitPhase(FrappeTestCase):
	def test_a_cut_off_phase_is_split_in_two_and_the_other_phases_are_kept(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(
					shape, should_cut=lambda user: _is_full_attempt(user) or cut_phase_two_once(user)
				)
				ids = {n["id"] for n in ran.compile_ir.call_args.args[0]["nodes"]}
				for kept in ("p1_start", "p2_0_50_a", "p3_50_100_a", "p4_end"):
					self.assertIn(kept, ids)
				self.assertEqual(len(ran.model.phase_calls), 5)
				self.assertTrue(ran.result["generated"])

	def test_the_merged_diagram_compiles(self):
		ran = run_generate("ba", should_cut=lambda user: _is_full_attempt(user) or cut_phase_two_once(user))
		self.assertTrue(compile_ir(ran.compile_ir.call_args.args[0])["ok"])

	def test_phase_calls_use_the_full_token_budget_not_8192(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(shape, should_cut=_is_full_attempt)
				self.assertEqual({c["max_tokens"] for c in ran.model.phase_calls}, {16384})

	def test_a_phase_still_cut_off_after_two_splits_stops_names_it_and_says_how_many_were_drawn(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(
					shape, should_cut=lambda user: _is_full_attempt(user) or cut_every_piece_of_review(user)
				)
				self.assertFalse(ran.result["generated"])
				self.assertIn('"Review"', ran.result["response"])
				self.assertIn("I drew 1 of 3 phases", ran.result["response"])
				self.assertEqual(len([c for c in ran.model.phase_calls if "Review" in c["user"]]), 3)
				ran.compile_ir.assert_not_called()


class TestCutOffCallsAreRecorded(FrappeTestCase):
	def test_each_cut_off_call_is_a_sub_call_step_with_error_code_truncated(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(
					shape, should_cut=lambda user: _is_full_attempt(user) or cut_phase_two_once(user)
				)
				self.assertEqual(ran.model.cut_offs, 2)
				self.assertEqual(ran.record_step.call_count, 2)
				for call in ran.record_step.call_args_list:
					self.assertEqual(call.kwargs["error_code"], "TRUNCATED")
					self.assertEqual(call.kwargs["step_kind"], "sub_call")
					self.assertTrue(call.args[3].startswith("[sub-call: " + TOOL + " via "))

	def test_a_run_with_no_cut_off_records_nothing(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(shape)
				ran.record_step.assert_not_called()
				self.assertTrue(ran.result["generated"])


class TestABigRequestStartsWithTheOutline(FrappeTestCase):
	def test_more_than_25_elements_written_inline_skip_the_full_attempt(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(shape, text=_request(inline=58))
				self.assertIn("output ONLY an outline", ran.model.calls[0]["user"])
				self.assertEqual([c for c in ran.model.calls if _is_full_attempt(c["user"])], [])
				ran.record_step.assert_not_called()
				self.assertTrue(ran.result["generated"])

	def test_numbered_lines_still_count(self):
		ran = run_generate("ba", text=_request(numbered=30))
		self.assertIn("output ONLY an outline", ran.model.calls[0]["user"])

	def test_the_limit_is_more_than_25(self):
		self.assertTrue(_is_full_attempt(run_generate("ba", text=_request(inline=25)).model.calls[0]["user"]))
		self.assertIn(
			"output ONLY an outline", run_generate("ba", text=_request(inline=26)).model.calls[0]["user"]
		)

	def test_numbers_in_ordinary_prose_do_not_count(self):
		prose = "Draw a process where 3 Tasks run and 40 approvals happen after 5 Events."
		self.assertTrue(_is_full_attempt(run_generate("ba", text=prose).model.calls[0]["user"]))


class TestPromptsAskForOneLineJson(FrappeTestCase):
	def test_the_full_outline_and_phase_prompts_ask_for_it(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(shape, should_cut=_is_full_attempt)
				full, outline, phase = ran.model.calls[0], ran.model.calls[1], ran.model.phase_calls[0]
				self.assertIn("as one line of JSON with no indentation or line breaks", full["user"])
				self.assertIn("as one line of JSON with no indentation", outline["user"])
				self.assertIn("as one line of JSON with no indentation", phase["user"])


class TestTheExistingFeaturesStillRun(FrappeTestCase):
	def test_the_reply_the_artifact_and_the_auto_fix_still_happen(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				ran = run_generate(shape)
				ran.auto_fix_ir.assert_called()
				ran.record_artifact.assert_called_once()
				output = ran.update_turn.call_args.kwargs["output"]
				self.assertEqual(output["intent"], "BPMN_GENERATED")
				if shape == "ba":
					self.assertIn(" LANES TASKS", output["response"])


class TestTheDiffIsSmall(FrappeTestCase):
	def test_the_patched_script_differs_from_the_live_one_by_added_blocks_and_eight_edited_lines(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				diff = difflib.unified_diff(
					_script(shape).splitlines(),
					split_patch.rewrite(_script(shape)).splitlines(),
					lineterm="",
					n=0,
				)
				removed = [line for line in diff if line.startswith("-") and not line.startswith("---")]
				self.assertEqual(len(removed), EDITED_LINES)


class TestTheEngineValidatorAcceptsTheScript(FrappeTestCase):
	"""The engine runs this validator right before it executes a Server Script and blocks the call on any finding."""

	def test_the_patched_scripts_have_no_findings(self):
		for shape in SHAPES:
			with self.subTest(shape=shape):
				patched = split_patch.rewrite(_script(shape))
				self.assertEqual(deep_inspect_script(patched), [])
				self.assertEqual(deep_inspect_script(patched, STRICT), [])

	def test_the_script_as_the_first_version_of_the_patch_left_it_was_blocked(self):
		broken = _script("ba_after_split_patch")
		self.assertEqual(deep_inspect_script(broken), ["getattr() is not allowed"])


class TestTheRepairOfTheBlockedScript(FrappeTestCase):
	def test_the_repaired_script_has_no_findings_compiles_and_a_second_run_changes_nothing(self):
		repaired = repair_patch.rewrite(_script("ba_after_split_patch"))
		self.assertEqual(deep_inspect_script(repaired), [])
		self.assertEqual(deep_inspect_script(repaired, STRICT), [])
		compile(repaired, "repaired", "exec")
		self.assertEqual(repair_patch.rewrite(repaired), repaired)

	def test_only_the_recording_block_changes(self):
		broken = _script("ba_after_split_patch")
		diff = list(
			difflib.unified_diff(
				broken.splitlines(), repair_patch.rewrite(broken).splitlines(), lineterm="", n=0
			)
		)
		removed = [line for line in diff if line.startswith("-") and not line.startswith("---")]
		added = [line for line in diff if line.startswith("+") and not line.startswith("+++")]
		self.assertEqual((len(removed), len(added)), (15, 2))
		self.assertTrue(all("getattr" not in line for line in added))

	def test_a_script_without_the_old_block_is_left_alone(self):
		for script in (_script("ba"), split_patch.rewrite(_script("ba"))):
			self.assertEqual(repair_patch.rewrite(script), script)

	def test_the_script_is_found_by_api_method_and_written_back_repaired(self):
		with (
			mock.patch.object(
				frappe.db, "get_value", side_effect=["Any Name", _script("ba_after_split_patch")]
			) as get_value,
			mock.patch.object(frappe.db, "set_value") as set_value,
		):
			repair_patch.execute()
		self.assertEqual(
			get_value.call_args_list[0].args,
			("Server Script", {"api_method": "prosally_tool_generate_process"}, "name"),
		)
		self.assertEqual(deep_inspect_script(set_value.call_args.args[3]), [])

	def test_a_site_without_the_script_or_with_nothing_to_repair_writes_nothing(self):
		for values in ([None], ["Any Name", split_patch.rewrite(_script("ba"))]):
			with (
				mock.patch.object(frappe.db, "get_value", side_effect=values),
				mock.patch.object(frappe.db, "set_value") as set_value,
				mock.patch.object(frappe, "log_error") as log_error,
			):
				repair_patch.execute()
			set_value.assert_not_called()
			log_error.assert_not_called()

	def test_a_script_that_still_has_getattr_but_a_different_block_is_logged_and_left_alone(self):
		odd = 'if _cut_offs:\n    x = getattr(_run_doc, "model", None)\nif not _truncated_error:\n    pass\n'
		with (
			mock.patch.object(frappe.db, "get_value", side_effect=["Any Name", odd]),
			mock.patch.object(frappe.db, "set_value") as set_value,
			mock.patch.object(frappe, "log_error") as log_error,
		):
			repair_patch.execute()
		set_value.assert_not_called()
		log_error.assert_called_once()


class TestRecordTruncatedCalls(FrappeTestCase):
	def _run(self, scope):
		run_doc = mock.Mock(model="sonnet")
		run_doc.name = "RUN-1"
		with (
			mock.patch(f"{OBSERVABILITY}.current_sub_call", return_value=scope),
			mock.patch(f"{OBSERVABILITY}.record_ai_step") as record,
			mock.patch.object(frappe, "get_doc", return_value=run_doc),
			mock.patch.object(frappe.db, "count", side_effect=[4, 5]),
		):
			record_truncated_calls([(120, "outline"), (340, "Review (part)")])
		return record

	def test_each_cut_off_call_becomes_a_sub_call_step_with_error_code_truncated(self):
		record = self._run({"run": "RUN-1", "tool": TOOL})
		self.assertEqual(record.call_count, 2)
		first, second = record.call_args_list
		self.assertEqual((first.args[1], second.args[1]), (5, 6))
		self.assertTrue(first.args[3].startswith("[sub-call: " + TOOL + " via sonnet"))
		self.assertIn("outline cut off at the token ceiling", first.args[3])
		self.assertEqual((first.kwargs["latency_ms"], second.kwargs["latency_ms"]), (120, 340))
		for call in (first, second):
			self.assertEqual((call.kwargs["error_code"], call.kwargs["step_kind"]), ("TRUNCATED", "sub_call"))

	def test_outside_a_sub_call_scope_or_with_nothing_cut_off_nothing_is_recorded(self):
		self.assertEqual(self._run(None).call_count, 0)
		with (
			mock.patch(f"{OBSERVABILITY}.current_sub_call", return_value={"run": "RUN-1", "tool": TOOL}),
			mock.patch(f"{OBSERVABILITY}.record_ai_step") as record,
		):
			record_truncated_calls([])
		record.assert_not_called()
