# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""An agent handed back to the creation map is accepted by its start event, keeps its prompt, and never leaves a stuck instance."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import _start_reprovision
from one_bpmn.one_bpmn.patches.v1_0 import creation_map_takes_back_existing_agents as fix

MAP = """<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <bpmn:process id="agent_creation">
    <bpmn:startEvent id="start" name="Agent Created">
      <bpmn:conditionalEventDefinition id="cond_start">
        <bpmn:condition>{start}</bpmn:condition>
      </bpmn:conditionalEventDefinition>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="f_gen" sourceRef="gw_prompt" targetRef="gen_prompt">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">{generate}</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:scriptTask id="validate" name="Validate Config" spiffworkflow:serverScript="AAC - Validate" />
  </bpmn:process>
</bpmn:definitions>"""


def _map(start=fix.START_CONDITIONS_REPLACED[0], generate=fix.GENERATE_CONDITION_REPLACED) -> str:
	return MAP.format(start=start, generate=generate)


class TestTheMapIsUpdated(FrappeTestCase):
	def test_the_original_map_gets_both_new_conditions(self):
		xml, notes = fix.updated_map(_map())
		self.assertIn(f"<bpmn:condition>{fix.START_CONDITION}</bpmn:condition>", xml)
		self.assertIn(fix.GENERATE_CONDITION, xml)
		self.assertEqual(notes, ["start condition updated", "prompt generation condition updated"])

	def test_the_hand_edit_made_on_staging_is_replaced_too(self):
		xml, _notes = fix.updated_map(_map(start=fix.START_CONDITIONS_REPLACED[1]))
		self.assertIn(f"<bpmn:condition>{fix.START_CONDITION}</bpmn:condition>", xml)

	def test_a_second_run_changes_nothing(self):
		once, _notes = fix.updated_map(_map())
		twice, notes = fix.updated_map(once)
		self.assertEqual(twice, once)
		self.assertEqual(
			notes, ["start condition already updated", "prompt generation condition already updated"]
		)

	def test_a_customised_condition_is_reported_and_kept(self):
		xml, notes = fix.updated_map(_map(start='agent_type=="Chat"'))
		self.assertIn('<bpmn:condition>agent_type=="Chat"</bpmn:condition>', xml)
		self.assertIn("customised", notes[0])

	def test_the_scripts_change_once(self):
		validate = "validation_result = validate_agent_config(context_docname)\n"
		new, _note = fix.updated_script(validate, fix.VALIDATE_CALL_REPLACED, fix.VALIDATE_CALL)
		self.assertIn('!= "Background"', new)
		self.assertEqual(
			fix.updated_script(new, fix.VALIDATE_CALL_REPLACED, fix.VALIDATE_CALL), (new, "already updated")
		)

		save = "if _p:\n    frappe.db.set_value(...)\n"
		new, _note = fix.updated_script(save, fix.SAVE_GUARD_REPLACED, fix.SAVE_GUARD)
		self.assertIn(
			'not frappe.db.get_value("AI Agent Configuration", context_docname, "system_prompt")', new
		)

		self.assertEqual(fix.updated_script("x = 1", fix.SAVE_GUARD_REPLACED, fix.SAVE_GUARD)[0], "x = 1")

	def test_the_script_name_is_read_from_the_map(self):
		self.assertEqual(fix._server_script_of(_map(), "validate"), "AAC - Validate")

	def test_a_site_without_a_creation_map_is_left_alone(self):
		with (
			patch("one_bpmn.agents.agent_config_resolver.get_creation_process_model", return_value=None),
			patch("frappe.db.set_value") as write,
		):
			fix.execute()
		write.assert_not_called()


class TestTheReprovisionGuard(FrappeTestCase):
	def setUp(self):
		suffix = frappe.generate_hash(length=6)
		self.agent = (
			frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": f"Reprovision {suffix}",
					"agent_id": f"reprovision_{suffix}",
					"agent_type": "Chat",
					"chat_mode_label": f"Reprovision {suffix}",
					"agent_framework": "Direct API",
					"enabled": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value("AI Agent Configuration", self.agent, "lifecycle_status", "Needs Attention")

	def _reprovision(self, condition: str):
		with (
			patch(
				"one_bpmn.agents.agent_config_resolver.get_creation_process_model",
				return_value="_creation-map",
			),
			patch("one_bpmn.one_bpmn.trigger._get_conditional_start_condition", return_value=condition),
			patch("one_bpmn.api.instance_api.start_process") as start,
		):
			started = _start_reprovision(self.agent)
		return started, start

	def test_a_condition_that_rejects_the_agent_starts_nothing(self):
		started, start = self._reprovision(fix.START_CONDITIONS_REPLACED[0])
		self.assertFalse(started)
		start.assert_not_called()
		self.assertTrue(frappe.db.exists("Error Log", {"method": f"Re-provision skipped for {self.agent}"}))

	def test_the_new_condition_lets_a_parked_agent_in(self):
		started, start = self._reprovision(fix.START_CONDITION)
		self.assertTrue(started)
		start.assert_called_once()


class TestAFailedStartIsNotLeftActive(FrappeTestCase):
	def test_a_map_without_a_compiled_copy_leaves_an_errored_instance(self):
		from one_bpmn.api.instance_api import start_process

		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"Uncompiled {frappe.generate_hash(length=6)}",
				"process_id": "uncompiled_map",
				"process_name": "_uncompiled",
				"is_active": 0,
				"bpmn_xml": _map(),
			}
		)
		model.flags.ignore_links = True
		model.insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			start_process(model.name)

		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", {"process_model": model.name}, "status"), "Errored"
		)
