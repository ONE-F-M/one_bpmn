"""WI-000284: chunked generation for large processes in ProsAlly - Tool Generate Process.

The Server Script body lives in the patch module as GENERATE. These tests run
that body with the model call (complete_sub_prompt) mocked, so no provider is
reached, and check the acceptance criteria from the work item.
"""

import json
import re
from unittest import mock

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider.base import LLMTruncatedError
from one_bpmn.one_bpmn.patches.v1_0.prosally_chunked_generation_split import GENERATE

OUTLINE = {
	"lanes": [{"id": "user", "name": "User"}, {"id": "system", "name": "System (Automatic)"}],
	"phases": [
		{"id": "intake", "name": "Intake", "description": "receive the request"},
		{"id": "review", "name": "Review", "description": "review the request"},
		{"id": "close", "name": "Close", "description": "close the request"},
	],
}

MODULE = "one_bpmn.one_bpmn.patches.v1_0.prosally_chunked_generation_split"


def _phase_reply(tag):
	return json.dumps({
		"nodes": [
			{"id": tag + "_a", "type": "userTask", "name": tag, "lane": "user"},
			{"id": tag + "_b", "type": "userTask", "name": tag, "lane": "user"},
		],
		"flows": [{"from": tag + "_a", "to": tag + "_b"}],
	})


class FakeModel:
	"""Stands in for complete_sub_prompt. Records every call and cuts off the ones asked for."""

	def __init__(self, should_cut):
		self.should_cut = should_cut
		self.calls = []
		self.cut_off = 0

	def __call__(self, cfg, sub_id, user, system=None, max_tokens=None):
		self.calls.append({"user": user, "max_tokens": max_tokens})
		if "output ONLY an outline" in user:
			return json.dumps(OUTLINE)
		if self.should_cut(user, self.calls):
			self.cut_off += 1
			raise LLMTruncatedError("cut off at the token ceiling")
		if "(generating ONE PHASE" not in user:
			return json.dumps({"lanes": [], "nodes": [], "flows": []})
		phase = int(re.search(r"This phase \((\d+) of \d+\)", user).group(1))
		suffix = ""
		if "ONLY part 1 of 2" in user:
			suffix = "a"
		elif "ONLY part 2 of 2" in user:
			suffix = "b"
		return _phase_reply("p" + str(phase) + suffix)


def is_full_attempt(user):
	return "Action: GENERATE_NEW" in user and "(generating ONE PHASE" not in user and "output ONLY an outline" not in user


def _run_doc():
	doc = mock.Mock(model="sonnet")
	doc.name = "RUN-1"
	return doc


def _cfg():
	return {"sub_prompts": {"process_generator": {"prompt": "You generate BPMN IR."}}, "max_tokens": 16384}


INLINE_TYPES = ("StartEvent", "ScriptTask", "ExclusiveGateway", "UserTask", "EndEvent")


def _request(numbered_items=0, inline_elements=0):
	text = "Model a leave request process."
	if numbered_items:
		text += "\n" + "\n".join(str(i + 1) + ". Step number " + str(i + 1) for i in range(numbered_items))
	if inline_elements:
		text += "\nC. ELEMENTS " + " ".join(
			str(i + 1) + " " + INLINE_TYPES[i % len(INLINE_TYPES)] + " 'Step " + str(i + 1) + "'|Sys" for i in range(inline_elements)
		)
	return {"intent": "GENERATE_NEW", "process_name": "Leave", "chat_history": [{"role": "user", "content": text}]}


class TestProsAllyChunkedGeneration(FrappeTestCase):
	def run_generate(self, should_cut, numbered_items=0, inline_elements=0):
		model = FakeModel(should_cut)
		compile_ir = mock.Mock(return_value={"ok": True, "xml": "<definitions/>", "problems": [], "topology": {}, "layout": {}})
		record = mock.Mock()
		result = {}
		with mock.patch("one_bpmn.agents.turn_state.get_turn", return_value=_request(numbered_items, inline_elements)), \
			mock.patch("one_bpmn.agents.turn_state.update_turn"), \
			mock.patch("one_bpmn.agents.prosally_helpers.complete_sub_prompt", side_effect=model), \
			mock.patch("one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration.get_agent_config", return_value=_cfg()), \
			mock.patch("one_bpmn.agents.bpmn_ir_pipeline.compile_ir", compile_ir), \
			mock.patch("one_bpmn.agents.bpmn_ir_pipeline.ensure_default_lanes", return_value=True), \
			mock.patch("one_bpmn.agents.bpmn_ir_pipeline.extract_process_name", return_value="Leave"), \
			mock.patch("one_bpmn.security.bpmn_validator.validate_bpmn_xml", return_value={"valid": True}), \
			mock.patch("one_bpmn.agents.observability.current_sub_call", return_value={"run": "RUN-1", "tool": "Tool Generate Process"}), \
			mock.patch("one_bpmn.agents.observability.record_ai_step", record), \
			mock.patch("frappe.get_doc", return_value=_run_doc()):
			exec(GENERATE, {"frappe": frappe_stub(), "context_docname": "TEST-TURN", "result": result})
		return model, compile_ir, record, result

	def test_ac1_cut_off_phase_is_split_and_the_rest_kept(self):
		state = {"cut": False}

		def cut_full_then_phase_two_once(user, calls):
			if is_full_attempt(user):
				return True
			if "This phase (2 of 3)" in user and "ONLY part" not in user and not state["cut"]:
				state["cut"] = True
				return True
			return False

		model, compile_ir, record, result = self.run_generate(cut_full_then_phase_two_once)

		self.assertTrue(result["generated"])
		compile_ir.assert_called_once()
		merged = compile_ir.call_args[0][0]
		ids = [n["id"] for n in merged["nodes"]]
		self.assertEqual(ids, ["p1_a", "p1_b", "p2a_a", "p2a_b", "p2b_a", "p2b_b", "p3_a", "p3_b"])
		part_prompts = [c["user"] for c in model.calls if "ONLY part" in c["user"]]
		self.assertEqual(len(part_prompts), 2)

	def test_ac2_phase_still_cut_off_after_two_splits_stops_and_names_it(self):
		def always_cut_phase_two(user, calls):
			return is_full_attempt(user) or "This phase (2 of 3)" in user

		model, compile_ir, record, result = self.run_generate(always_cut_phase_two)

		self.assertFalse(result["generated"])
		self.assertTrue(result["truncated"])
		self.assertIn('"Review"', result["response"])
		self.assertIn("I drew 3 phase(s)", result["response"])
		compile_ir.assert_not_called()
		self.assertEqual(record.call_count, model.cut_off)

	def test_ac3_every_cut_off_call_is_recorded(self):
		def cut_full_attempt(user, calls):
			return "Action: GENERATE_NEW" in user and "(generating ONE PHASE" not in user

		model, compile_ir, record, result = self.run_generate(cut_full_attempt)

		self.assertTrue(result["generated"])
		self.assertEqual(record.call_count, 1)
		self.assertEqual(record.call_args.kwargs["step_kind"], "sub_call")
		self.assertEqual(record.call_args.kwargs["error_code"], "TRUNCATED")

	def test_ac4_more_than_25_elements_skips_the_full_attempt(self):
		model, compile_ir, record, result = self.run_generate(lambda user, calls: False, numbered_items=30)

		self.assertIn("output ONLY an outline", model.calls[0]["user"])
		full_attempts = [c for c in model.calls if "Action: GENERATE_NEW" in c["user"] and "outline" not in c["user"] and "(generating ONE PHASE" not in c["user"]]
		self.assertEqual(full_attempts, [])
		self.assertTrue(result["generated"])

	def test_ac4_elements_written_inline_on_one_line_are_counted(self):
		model, _compile_ir, _record, result = self.run_generate(lambda user, calls: False, inline_elements=58)

		self.assertIn("output ONLY an outline", model.calls[0]["user"])
		self.assertTrue(result["generated"])

	def test_ac4_the_limit_is_more_than_25_inline_elements(self):
		at_limit, _c, _r, _res = self.run_generate(lambda user, calls: False, inline_elements=25)
		over, _c, _r, _res = self.run_generate(lambda user, calls: False, inline_elements=26)

		self.assertTrue(is_full_attempt(at_limit.calls[0]["user"]))
		self.assertIn("output ONLY an outline", over.calls[0]["user"])

	def test_ac4_numbers_in_ordinary_prose_do_not_count(self):
		prose = "Draw a process where 3 Tasks run and 40 approvals happen after 5 Events."
		with mock.patch("one_bpmn.tests.test_prosally_chunked_generation._request", return_value={"intent": "GENERATE_NEW", "process_name": "Leave", "chat_history": [{"role": "user", "content": prose}]}):
			model, _c, _r, _res = self.run_generate(lambda user, calls: False)

		self.assertTrue(is_full_attempt(model.calls[0]["user"]))

	def test_ac5_phase_calls_use_full_budget_and_ask_for_one_line_json(self):
		model, compile_ir, record, result = self.run_generate(lambda user, calls: "Action: GENERATE_NEW" in user and "(generating ONE PHASE" not in user)

		phase_calls = [c for c in model.calls if "(generating ONE PHASE" in c["user"]]
		self.assertEqual(len(phase_calls), 3)
		for call in phase_calls:
			self.assertEqual(call["max_tokens"], 16384)
		for call in model.calls:
			self.assertIn("one line", call["user"])
		self.assertNotIn("8192", GENERATE)


def frappe_stub():
	import frappe

	return frappe
