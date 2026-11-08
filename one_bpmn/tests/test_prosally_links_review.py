# Copyright (c) 2026, one-fm and contributors
"""ProsAlly answers a review of its map's links to related maps from get_process_links.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_links_review
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_registry.definitions.prosally.tools_links import asks_for_links_review, links_review_output
from one_bpmn.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_reviews_process_links as review_patch
from one_bpmn.one_bpmn.patches.v1_0.prosally_relayouts_and_compares import apply_edits
from one_bpmn.tests.test_process_links import CATCH_SIGNAL, THROW_SIGNAL, _model

CONVERSATION = "zz-prosally-links-review-test"
CLASSIFY_SCRIPT = (
	"from one_bpmn.agents.turn_state import get_turn, update_turn\n"
	"from one_bpmn.agents.prosally_helpers import prosally_config\n"
	"if confirmed in _ACTION_INTENTS:\n"
	"    pass\n"
	'elif turn.get("declined_action"):\n'
	"    pass\n"
	"else:\n"
	"    _cfg = prosally_config()\n"
)


class TestAsksForLinksReview(FrappeTestCase):
	def test_a_review_of_signals_and_messages_across_related_maps_is_one(self):
		for text in (
			"Update this map so every message and signal it catches has a matching sender in my related process maps.",
			"Check the cross-process dependencies of this map: which signals have no throw?",
			"Do my other maps throw the messages this one catches?",
		):
			self.assertTrue(asks_for_links_review(text), text)

	def test_a_request_to_draw_or_change_steps_is_not(self):
		for text in (
			"Modify this map: where a step waits for another process, use a message event named after the related map.",
			"Add a signal throw after approval so the related process maps can catch it.",
			"Draw a leave approval process.",
		):
			self.assertFalse(asks_for_links_review(text), text)

	def test_a_list_to_compare_or_empty_text_is_not(self):
		self.assertFalse(asks_for_links_review("Which of these steps are missing?\n- Approve leave\n- Notify HR"))
		self.assertFalse(asks_for_links_review(""))
		self.assertFalse(asks_for_links_review(None))


class TestLinksReviewOutput(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.catcher = _model("rv_catcher", CATCH_SIGNAL, signal="Review links signal")
		self.thrower = _model("rv_thrower", THROW_SIGNAL, signal="Review links signal")
		set_turn(CONVERSATION, {"diagram_name": self.catcher})

	def tearDown(self):
		clear_turn(CONVERSATION)
		frappe.db.rollback()

	def test_reply_names_the_related_map_and_what_to_change(self):
		output = links_review_output(CONVERSATION)

		self.assertEqual(output["intent"], "CLARIFY")
		self.assertIsNone(output["action_intent"])
		self.assertEqual(output["options"], [])
		self.assertIn(self.thrower, output["response"])
		self.assertIn("What to change:", output["response"])
		self.assertIn("Wait: Signal 'Review links signal' is only matched in", output["response"])

	def test_review_keeps_the_findings_on_the_turn_and_changes_no_map(self):
		fields = ["modified", "bpmn_xml"]
		before = {name: frappe.db.get_value("BPMN Process Model", name, fields) for name in (self.catcher, self.thrower)}

		links_review_output(CONVERSATION)

		self.assertEqual(get_turn(CONVERSATION)["process_links"]["process_model"], self.catcher)
		for name, values in before.items():
			self.assertEqual(frappe.db.get_value("BPMN Process Model", name, fields), values)

	def test_a_map_with_no_events_or_calls_says_it_has_no_links(self):
		set_turn(CONVERSATION, {"diagram_name": _model("rv_plain")})

		self.assertIn("has no links to other maps", links_review_output(CONVERSATION)["response"])

	def test_a_map_that_matches_itself_has_no_gaps(self):
		set_turn(CONVERSATION, {"diagram_name": _model("rv_self", THROW_SIGNAL + CATCH_SIGNAL, signal="Review self signal")})

		self.assertIn("matches a map you can read", links_review_output(CONVERSATION)["response"])

	def test_a_turn_without_a_diagram_name_reads_the_active_map_of_its_process(self):
		frappe.db.set_value("BPMN Process Model", self.catcher, "process_name", "zz review links process")
		set_turn(CONVERSATION, {"process_name": "zz review links process"})

		self.assertIn(self.thrower, links_review_output(CONVERSATION)["response"])
		self.assertEqual(get_turn(CONVERSATION)["process_links"]["process_model"], self.catcher)

	def test_a_turn_with_no_diagram_and_no_process_asks_to_save_the_map(self):
		set_turn(CONVERSATION, {})

		self.assertIn("Save the map", links_review_output(CONVERSATION)["response"])
		self.assertNotIn("process_links", get_turn(CONVERSATION))

	def test_a_map_that_is_not_saved_replies_with_the_error(self):
		set_turn(CONVERSATION, {"diagram_name": f"{self.catcher} unsaved"})

		self.assertIn("No process model named", links_review_output(CONVERSATION)["response"])
		self.assertNotIn("process_links", get_turn(CONVERSATION))


class TestReviewPatch(FrappeTestCase):
	def test_the_route_is_added_before_the_classifier_and_the_import_is_added(self):
		edited = apply_edits(CLASSIFY_SCRIPT, review_patch.SCRIPT_EDITS)

		self.assertIn("import asks_for_links_review, links_review_output", edited)
		self.assertLess(edited.index("elif asks_for_links_review("), edited.index("_cfg = prosally_config()"))
		self.assertIn('result["next"] = "finalize"', edited)
		self.assertIn(review_patch.SCRIPT_MARKER, edited)

	def test_a_script_missing_an_anchor_is_left_alone(self):
		self.assertIsNone(apply_edits("print('nothing to anchor on')", review_patch.SCRIPT_EDITS))
