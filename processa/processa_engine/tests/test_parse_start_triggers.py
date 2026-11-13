# Copyright (c) 2026, one-fm and contributors
"""parse_start_triggers reads every start condition from one parse of the BPMN XML."""

from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from lxml import etree

from processa.processa_engine.triggers import _maybe_start_instance, parse_start_triggers

_ALL_NONE = {"workflow_state": None, "field_condition": None, "conditional_start": None}

_FULL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">
  <bpmn:process id="p">
    <bpmn:startEvent id="s" spiffworkflow:triggerWorkflowState="Open"
        spiffworkflow:triggerFieldName="agent_mode" spiffworkflow:triggerFieldValue="ProsAlly">
      <bpmn:conditionalEventDefinition>
        <bpmn:condition>agent_mode == "ProsAlly"</bpmn:condition>
      </bpmn:conditionalEventDefinition>
    </bpmn:startEvent>
  </bpmn:process>
</bpmn:definitions>"""

_PLAIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <bpmn:process id="p"><bpmn:startEvent id="s"/></bpmn:process>
</bpmn:definitions>"""


class TestParseStartTriggers(FrappeTestCase):
	def test_a_start_event_with_all_three_gives_all_three_keys(self):
		self.assertEqual(
			parse_start_triggers(_FULL_XML),
			{
				"workflow_state": "Open",
				"field_condition": ("agent_mode", "ProsAlly"),
				"conditional_start": 'agent_mode == "ProsAlly"',
			},
		)

	def test_xml_with_none_of_them_gives_all_none(self):
		self.assertEqual(parse_start_triggers(_PLAIN_XML), _ALL_NONE)

	def test_empty_xml_gives_all_none(self):
		self.assertEqual(parse_start_triggers(""), _ALL_NONE)
		self.assertEqual(parse_start_triggers(None), _ALL_NONE)

	def test_malformed_xml_gives_all_none(self):
		self.assertEqual(parse_start_triggers("<bpmn:definitions><unclosed>"), _ALL_NONE)

	def test_maybe_start_instance_parses_once_per_model(self):
		real_fromstring = etree.fromstring
		calls = []

		def counting(*args, **kwargs):
			calls.append(1)
			return real_fromstring(*args, **kwargs)

		model = SimpleNamespace(serialized_spec="spec", bpmn_xml=_FULL_XML)
		# workflow_state differs from the trigger's "Open", so each call stops after the checks
		doc = SimpleNamespace(doctype="ToDo", name="x", workflow_state="Closed")

		with (
			patch("processa.processa_engine.triggers.frappe.get_doc", return_value=model),
			patch("processa.processa_engine.triggers.frappe.new_doc") as new_doc,
			patch.object(etree, "fromstring", side_effect=counting),
		):
			_maybe_start_instance(doc, "model-one")
			self.assertEqual(len(calls), 1)
			_maybe_start_instance(doc, "model-two")
			self.assertEqual(len(calls), 2)

		new_doc.assert_not_called()
