# Copyright (c) 2026, one-fm and contributors
"""ProsAlly reads another process map through its read_process_map tool.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_read_process_map
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.process_links import MAX_TURN_MAPS, read_process_map_for_turn
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_reads_process_maps as maps_patch
from one_bpmn.tests.test_process_links import CATCH_SIGNAL, THROW_SIGNAL, _model
from one_bpmn.tests.test_prosally_cross_process import CFG, TOOLS_MAP

CONVERSATION = "zz-prosally-read-map-test"


class TestReadProcessMapTool(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.thrower = _model("rm_thrower", THROW_SIGNAL, signal="Read map signal")
		set_turn(CONVERSATION, {"user_text": "change the approval step"})

	def tearDown(self):
		frappe.set_user("Administrator")
		clear_turn(CONVERSATION)
		frappe.db.rollback()

	def test_a_map_name_returns_its_digest_and_keeps_it_on_the_turn(self):
		found = read_process_map_for_turn(CONVERSATION, self.thrower)

		self.assertIn("[signal: Read map signal]", found["digest"])
		self.assertEqual(get_turn(CONVERSATION)["process_maps"], [{"process_model": self.thrower, "digest": found["digest"]}])

	def test_reading_a_map_again_replaces_it_and_the_turn_keeps_the_last_three(self):
		names = [_model(f"rm_extra_{i}", CATCH_SIGNAL, signal=f"Read map extra {i}") for i in range(MAX_TURN_MAPS)]

		for name in (self.thrower, *names, names[0]):
			read_process_map_for_turn(CONVERSATION, name)

		kept = [row["process_model"] for row in get_turn(CONVERSATION)["process_maps"]]
		self.assertEqual(kept, [names[1], names[2], names[0]])

	def test_a_name_that_matches_no_map_returns_the_search_and_keeps_nothing(self):
		with patch("one_bpmn.agents.process_links.find_process_models", return_value={"results": []}) as find:
			found = read_process_map_for_turn(CONVERSATION, "leave approval")

		find.assert_called_once_with("leave approval")
		self.assertEqual(found, {"results": []})
		self.assertNotIn("process_maps", get_turn(CONVERSATION))

	def test_no_name_is_a_search_error_and_keeps_nothing(self):
		self.assertIn("error", read_process_map_for_turn(CONVERSATION, None))
		self.assertNotIn("process_maps", get_turn(CONVERSATION))

	def test_a_user_who_cannot_read_the_map_gets_nothing_kept(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			read_process_map_for_turn(CONVERSATION, self.thrower)
		self.assertNotIn("process_maps", get_turn(CONVERSATION))

	def test_the_tool_never_changes_the_map_it_reads(self):
		before = frappe.db.get_value("BPMN Process Model", self.thrower, ["modified", "bpmn_xml"])

		read_process_map_for_turn(CONVERSATION, self.thrower)

		self.assertEqual(frappe.db.get_value("BPMN Process Model", self.thrower, ["modified", "bpmn_xml"]), before)


class TestProcessMapsBlock(FrappeTestCase):
	def prompt(self, sub_id, turn):
		return helpers.stage_system_prompt(CFG, sub_id, "", turn)

	def test_the_block_is_empty_when_no_map_was_read(self):
		self.assertEqual(helpers.process_maps_block({}), "")
		self.assertEqual(helpers.process_maps_block(None), "")

	def test_generate_and_modify_prompts_carry_the_digests_and_the_edit_rule(self):
		turn = {"process_maps": [{"process_model": "Onboarding", "digest": "Steps in diagram order:\n- startEvent: Begin"}]}

		for sub_id, label in (("process_generator", "GENERATOR"), ("modifier", "MODIFIER")):
			prompt = self.prompt(sub_id, turn)
			self.assertTrue(prompt.startswith(label))
			self.assertIn(helpers.MAPS_HEADER, prompt)
			self.assertIn("Never change another map", prompt)
			self.assertIn("Map Onboarding:\nSteps in diagram order:\n- startEvent: Begin", prompt)

	def test_the_intent_classifier_prompt_has_no_maps(self):
		turn = {"process_maps": [{"process_model": "Onboarding", "digest": "digest text"}]}

		self.assertEqual(self.prompt("intent_classifier", turn), "CLASSIFIER")

	def test_prompts_are_unchanged_when_the_tool_was_not_called(self):
		self.assertEqual(self.prompt("modifier", {}), "MODIFIER")


class TestReadProcessMapPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_tool_script_calls_the_turn_tool_with_the_shape_argument(self):
		maps_patch._upsert_tool_script()

		script = frappe.db.get_value("Server Script", maps_patch.TOOL_SCRIPT, "script")

		self.assertIn('read_process_map_for_turn(context_docname, task_data.get("process_model"))', script)

	def test_shape_lands_in_the_tools_sub_process_with_bounds(self):
		xml = maps_patch.splice_shape(TOOLS_MAP)

		tools = xml[xml.index('id="prosally_tools"') : xml.index("</bpmn:adHocSubProcess>")]
		self.assertIn('<bpmn:scriptTask id="read_process_map"', tools)
		self.assertIn(f"<bpmn:script>{maps_patch.TOOL_SCRIPT}</bpmn:script>", tools)
		self.assertIn('bpmnElement="read_process_map"', xml)

	def test_splicing_twice_changes_nothing(self):
		once = maps_patch.splice_shape(TOOLS_MAP)

		self.assertEqual(maps_patch.splice_shape(once), once)

	def test_a_map_without_the_tools_sub_process_is_left_alone(self):
		self.assertIsNone(maps_patch.splice_shape("<bpmn:process id='p'></bpmn:process>"))

	def test_a_refused_recompile_is_logged_and_does_not_stop_the_patch(self):
		refused = patch("one_bpmn.api.deploy.compile_process_model", side_effect=frappe.ValidationError("not Live"))
		with patch.object(frappe.db, "get_value", side_effect=["Model", TOOLS_MAP]), patch.object(
			frappe.db, "set_value"
		) as set_value, refused, patch.object(frappe, "log_error") as log_error:
			maps_patch._update_process_model()

		self.assertIn("read_process_map", set_value.call_args.args[3])
		log_error.assert_called_once()

	def test_prompt_gets_the_map_rules_once(self):
		frappe.db.delete("AI Agent Configuration", {"agent_id": maps_patch.AGENT_ID})
		config = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_id": maps_patch.AGENT_ID,
				"agent_name": "ZZ ProsAlly",
				"chat_mode_label": "ZZ ProsAlly",
				"agent_type": "Chat",
				"agent_framework": "Direct API",
				"lifecycle_status": "Live",
				"enabled": 1,
				"system_prompt": "Exactly THREE tool calls per turn.",
			}
		).insert(ignore_permissions=True)

		maps_patch.append_prompt()
		maps_patch.append_prompt()

		prompt = frappe.db.get_value("AI Agent Configuration", config.name, "system_prompt")
		self.assertEqual(prompt.count("OTHER PROCESS MAPS"), 1)
		self.assertIn("read_process_map", prompt)
