# Copyright (c) 2026, one-fm and contributors
"""ProsAlly reads links to related process maps through its get_process_links tool.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_cross_process
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.process_links import process_links_for_turn
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_reads_related_processes as links_patch
from one_bpmn.tests.test_process_links import CATCH_SIGNAL, THROW_SIGNAL, _model

CONVERSATION = "zz-prosally-links-test"
CFG = {
	"sub_prompts": {
		"process_generator": {"prompt": "GENERATOR"},
		"modifier": {"prompt": "MODIFIER"},
		"intent_classifier": {"prompt": "CLASSIFIER"},
	},
	"constants": {},
}
TOOLS_MAP = """<bpmn:process id="p">
    <bpmn:adHocSubProcess id="prosally_tools" name="Tools">
      <bpmn:scriptTask id="finalize" name="finalize" />
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">True</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
  </bpmn:process>
  <bpmndi:BPMNPlane id="plane">
  </bpmndi:BPMNPlane>"""


class TestProsallyProcessLinksTool(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.catcher = _model("pa_catcher", CATCH_SIGNAL, signal="Prosally links signal")
		self.thrower = _model("pa_thrower", THROW_SIGNAL, signal="Prosally links signal")
		set_turn(CONVERSATION, {"user_text": "change the approval step", "diagram_name": self.catcher})

	def tearDown(self):
		frappe.set_user("Administrator")
		clear_turn(CONVERSATION)
		frappe.db.rollback()

	def prompt(self, sub_id):
		return helpers.stage_system_prompt(CFG, sub_id, "", get_turn(CONVERSATION))

	def test_tool_reads_the_open_map_and_keeps_the_findings_for_the_turn(self):
		found = process_links_for_turn(CONVERSATION)

		kept = get_turn(CONVERSATION)["process_links"]
		self.assertEqual(kept["process_model"], self.catcher)
		self.assertEqual(kept["gaps"], found["gaps"])
		self.assertEqual([gap["kind"] for gap in kept["gaps"]], ["signal_other_process"])

	def test_a_map_that_is_not_saved_is_an_error_and_keeps_nothing(self):
		set_turn(CONVERSATION, {"diagram_name": f"{self.catcher} unsaved"})

		self.assertIn("error", process_links_for_turn(CONVERSATION))
		self.assertNotIn("process_links", get_turn(CONVERSATION))

	def test_generate_and_modify_prompts_carry_the_gaps_and_the_edit_rule(self):
		process_links_for_turn(CONVERSATION)

		for sub_id, label in (("process_generator", "GENERATOR"), ("modifier", "MODIFIER")):
			prompt = self.prompt(sub_id)
			self.assertTrue(prompt.startswith(f"{label}\n\n{helpers.LINKS_HEADER}"))
			self.assertIn("Never change another map", prompt)
			self.assertIn(f"Related map {self.thrower}", prompt)
			self.assertIn("Gap (signal_other_process) at Wait (c1)", prompt)

	def test_prompts_are_unchanged_when_the_tool_was_not_called(self):
		self.assertEqual(self.prompt("process_generator"), "GENERATOR")

	def test_intent_classifier_prompt_has_no_links(self):
		process_links_for_turn(CONVERSATION)

		self.assertEqual(self.prompt("intent_classifier"), "CLASSIFIER")

	def test_block_is_empty_when_there_is_nothing_related(self):
		empty = {"process_model": "m", "related": [], "gaps": [], "truncated": False}

		self.assertEqual(helpers.process_links_block({"process_links": empty}), "")

	def test_block_says_when_related_maps_were_cut(self):
		cut = {"process_model": "m", "related": [{"process_model": "x", "reason": "r"}], "gaps": [], "truncated": True}

		self.assertIn("More related maps exist than are listed.", helpers.process_links_block({"process_links": cut}))

	def test_the_tool_never_changes_a_related_map(self):
		before = frappe.db.get_value("BPMN Process Model", self.thrower, ["modified", "bpmn_xml"])

		process_links_for_turn(CONVERSATION)

		self.assertEqual(frappe.db.get_value("BPMN Process Model", self.thrower, ["modified", "bpmn_xml"]), before)


class TestProsallyProcessLinksPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_tool_script_calls_the_turn_tool(self):
		links_patch._upsert_tool_script()

		script = frappe.db.get_value("Server Script", links_patch.TOOL_SCRIPT, "script")

		self.assertIn("process_links_for_turn(context_docname)", script)

	def test_shape_lands_in_the_tools_sub_process_with_bounds(self):
		xml = links_patch.splice_shape(TOOLS_MAP)

		tools = xml[xml.index('id="prosally_tools"') : xml.index("</bpmn:adHocSubProcess>")]
		self.assertIn('<bpmn:scriptTask id="get_process_links"', tools)
		self.assertIn(f"<bpmn:script>{links_patch.TOOL_SCRIPT}</bpmn:script>", tools)
		self.assertIn('bpmnElement="get_process_links"', xml)

	def test_splicing_twice_changes_nothing(self):
		once = links_patch.splice_shape(TOOLS_MAP)

		self.assertEqual(links_patch.splice_shape(once), once)

	def test_a_map_without_the_tools_sub_process_is_left_alone(self):
		self.assertIsNone(links_patch.splice_shape("<bpmn:process id='p'></bpmn:process>"))

	def test_a_refused_recompile_is_logged_and_does_not_stop_the_patch(self):
		refused = patch("one_bpmn.api.compilation.compile_process_model", side_effect=frappe.ValidationError("not Live"))
		with patch.object(frappe.db, "get_value", side_effect=["Model", TOOLS_MAP]), patch.object(
			frappe.db, "set_value"
		) as set_value, refused, patch.object(frappe, "log_error") as log_error:
			links_patch._update_process_model()

		self.assertIn("get_process_links", set_value.call_args.args[3])
		log_error.assert_called_once()

	def test_prompt_gets_the_link_rules_once(self):
		frappe.db.delete("AI Agent Configuration", {"agent_id": links_patch.AGENT_ID})
		config = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_id": links_patch.AGENT_ID,
				"agent_name": "ZZ ProsAlly",
				"chat_mode_label": "ZZ ProsAlly",
				"agent_type": "Chat",
				"agent_framework": "Direct API",
				"lifecycle_status": "Live",
				"enabled": 1,
				"system_prompt": "Exactly THREE tool calls per turn.",
			}
		).insert(ignore_permissions=True)

		links_patch.append_prompt()
		links_patch.append_prompt()

		prompt = frappe.db.get_value("AI Agent Configuration", config.name, "system_prompt")
		self.assertEqual(prompt.count("CROSS-PROCESS LINKS"), 1)
		self.assertIn("five calls", prompt)
