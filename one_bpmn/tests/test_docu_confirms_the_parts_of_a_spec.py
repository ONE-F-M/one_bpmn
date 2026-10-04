# Copyright (c) 2026, one-fm and contributors
"""Docu confirms the parts of a long spec before writing, and its reply names any part it left out."""

import html
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_confirms_the_parts_of_a_spec as fix
from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit
from one_bpmn.one_bpmn.patches.v1_0.seed_docu_agent_config import _INLINE_SUB_PROMPTS

SPEC = "Payroll enters pending salary, GR enters residency deduction, Finance checks loans."

# The shape of the live Classify Intent script around the three anchors.
CLASSIFY = (
	"import json\n"
	'message = turn.get("user_text", "")\n'
	'intent = ""\n'
	"if not intent:\n"
	"    raw = RAW\n"
	'    intent = "CREATE"\n'
	"    try:\n"
	'        intent = json.loads((raw or "").strip()).get("intent", intent).upper()\n'
	"    except (json.JSONDecodeError, TypeError, AttributeError):\n"
	"        pass\n"
	"if intent in _cheap_intents:\n"
	'    result["next"] = None\n'
	"else:\n"
	"    update_turn(context_docname, intent=intent)\n"
	'    result["next"] = "write_schema"\n'
)

FINALIZE = (
	'final_text = turn.get("final_text")\n'
	"if True:\n"
	"    if True:\n"
	'        ir = turn.get("final_ir")\n'
	'        update_turn(context_docname, output={"response": final_text})\n'
)

CLASSIFY_EDITS = (
	(fix.PENDING_ANCHOR, fix.PENDING),
	(fix.PARSE_ANCHOR, fix.PARSE),
	(fix.ASK_ANCHOR, fix.ASK),
)


def _patched_classify():
	script = CLASSIFY
	for anchor, replacement in CLASSIFY_EDITS:
		script = apply_edit(script, anchor, replacement)
	return script


class _Run:
	"""Runs a patched script with the turn and the session state held in dicts."""

	def __init__(self):
		self.turn, self.state = {}, {}

	def update_turn(self, _conversation, **values):
		self.turn.update(values)

	def record(self, _conversation, values):
		for key, value in values.items():
			if value is None:
				self.state.pop(key, None)
			else:
				self.state[key] = value

	def classify(self, message, parts, intent="CREATE"):
		self.turn = {"user_text": message, "session_state": dict(self.state)}
		result = {}
		namespace = {
			"turn": self.turn,
			"RAW": json.dumps({"intent": intent, "reason": "r", "parts": parts}),
			"_cheap_intents": ("SMALL_TALK", "OFF_TOPIC"),
			"context_docname": "conversation",
			"update_turn": self.update_turn,
			"exists": False,
			"result": result,
		}
		with patch("one_bpmn.agents.memory.session_state.record", self.record):
			exec(_patched_classify(), namespace)
		return result


class TestClassifyAsksAboutTheParts(FrappeTestCase):
	def test_a_spec_with_several_parts_is_confirmed_before_writing(self):
		run = _Run()
		result = run.classify(SPEC, ["Payroll", "GR", "Finance"])
		self.assertIsNone(result["next"])
		self.assertIn("- Payroll\n- GR\n- Finance", result["response"])
		self.assertEqual(run.turn["output"]["options"], [fix.CONFIRM])
		self.assertEqual(run.state, {"pending_parts": ["Payroll", "GR", "Finance"], "pending_spec": SPEC})

	def test_confirming_writes_the_original_spec_with_its_parts(self):
		run = _Run()
		run.classify(SPEC, ["Payroll", "GR", "Finance"])
		result = run.classify(fix.CONFIRM, ["Payroll", "GR", "Finance"])
		self.assertEqual(result["next"], "write_schema")
		self.assertEqual(run.turn["user_text"], SPEC)
		self.assertEqual(run.turn["parts"], ["Payroll", "GR", "Finance"])
		self.assertEqual(run.state, {})

	def test_a_correction_asks_again_with_the_new_list(self):
		run = _Run()
		run.classify(SPEC, ["Payroll", "GR", "Finance"])
		result = run.classify("drop Finance", ["Payroll", "GR"])
		self.assertIsNone(result["next"])
		self.assertEqual(run.state["pending_parts"], ["Payroll", "GR"])
		self.assertTrue(run.state["pending_spec"].endswith("Change to the list of parts: drop Finance"))

	def test_a_single_part_request_goes_straight_to_the_writer(self):
		run = _Run()
		self.assertEqual(run.classify("Add a remarks field", [], "MODIFY")["next"], "write_schema")
		self.assertEqual(run.state, {})

	def test_each_edit_applies_once(self):
		once = _patched_classify()
		for anchor, replacement in CLASSIFY_EDITS:
			self.assertEqual(apply_edit(once, anchor, replacement), once)


class TestFinalizeNamesTheMissingParts(FrappeTestCase):
	def _reply(self, parts, final_text):
		run = _Run()
		run.turn = {"parts": parts, "final_text": final_text, "final_ir": {}}
		exec(
			apply_edit(FINALIZE, fix.MISSING_ANCHOR, fix.MISSING),
			{"turn": run.turn, "update_turn": run.update_turn, "context_docname": "c"},
		)
		return run.turn["output"]["response"]

	def test_a_part_the_reply_does_not_name_is_listed_as_not_covered(self):
		reply = self._reply(
			["Payroll", "GR", "Finance"], "Payroll: a salary section.\nGR: a residency deduction."
		)
		self.assertTrue(reply.endswith("\n\nNot covered yet: Finance."))

	def test_a_reply_that_names_every_part_is_unchanged(self):
		self.assertEqual(self._reply(["Payroll"], "Payroll: a salary section."), "Payroll: a salary section.")


class TestPromptsCarryTheParts(FrappeTestCase):
	def test_the_writer_prompt_lists_the_confirmed_parts(self):
		template = "{% if 1 %}" + html.unescape(fix.WRITER)
		text = frappe.render_template(template, {"turn": {"parts": ["Payroll", "GR"], "user_text": SPEC}})
		self.assertIn("confirmed all of them: Payroll, GR.", text)
		self.assertTrue(text.endswith("**User request:** " + SPEC))

	def test_the_seeded_classifier_asks_for_parts(self):
		self.assertIn('"parts": ["part name", ...]', _INLINE_SUB_PROMPTS["intent_classifier"])
		self.assertIn("- PARTS:", _INLINE_SUB_PROMPTS["intent_classifier"])
