# Copyright (c) 2026, one-fm and contributors
"""A request about a sub-process changes the inside of that sub-process and nothing else."""

import json
import re
from xml.etree import ElementTree as ET

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir
from one_bpmn.agents.prosally_helpers import resolve_scope, splice_subprocess, transfer_properties

BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
BPMNDI = "{http://www.omg.org/spec/BPMN/20100524/DI}"
SPIFF = 'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"'

DIAGRAM = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" {SPIFF} id="Defs_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" name="Doctype Sync" isExecutable="true">
    <bpmn:startEvent id="start" name="Start"><bpmn:outgoing>F1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:intermediateThrowEvent id="mid" name="Intermediate"><bpmn:incoming>F1</bpmn:incoming><bpmn:outgoing>F2</bpmn:outgoing></bpmn:intermediateThrowEvent>
    <bpmn:endEvent id="end" name="End"><bpmn:incoming>F2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="F1" sourceRef="start" targetRef="mid"/>
    <bpmn:sequenceFlow id="F2" sourceRef="mid" targetRef="end"/>
    <bpmn:subProcess id="sub" name="Test Sub Process">
      <bpmn:task id="old_step" name="Old step" spiffworkflow:assignmentMode="Session User"/>
    </bpmn:subProcess>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="D1"><bpmndi:BPMNPlane id="P1" bpmnElement="Process_1">
    <bpmndi:BPMNShape id="s1" bpmnElement="start"><dc:Bounds x="100" y="100" width="36" height="36"/></bpmndi:BPMNShape>
    <bpmndi:BPMNShape id="s2" bpmnElement="mid"><dc:Bounds x="220" y="100" width="36" height="36"/></bpmndi:BPMNShape>
    <bpmndi:BPMNShape id="s3" bpmnElement="end"><dc:Bounds x="340" y="100" width="36" height="36"/></bpmndi:BPMNShape>
    <bpmndi:BPMNShape id="s4" bpmnElement="sub" isExpanded="false"><dc:Bounds x="200" y="250" width="100" height="80"/></bpmndi:BPMNShape>
  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
  <bpmndi:BPMNDiagram id="BPMNDiagram_sub"><bpmndi:BPMNPlane id="BPMNPlane_sub" bpmnElement="sub">
    <bpmndi:BPMNShape id="old_step_di" bpmnElement="old_step"><dc:Bounds x="100" y="100" width="100" height="80"/></bpmndi:BPMNShape>
  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>"""

STEPS = {
	"name": "Test Sub Process",
	"nodes": [
		{"id": "a", "type": "startEvent", "name": "Start"},
		{"id": "navigate", "type": "userTask", "name": "Navigate to the list"},
		{"id": "z", "type": "endEvent", "name": "Document is saved"},
	],
	"flows": [{"from": "a", "to": "navigate"}, {"from": "navigate", "to": "z"}],
}


def _main_ids(xml):
	process = ET.fromstring(xml).find(f"{BPMN}process")
	return [(e.tag.split("}")[1], e.get("id")) for e in process if e.get("id")]


def _inside(xml, sub_id):
	sub = next(e for e in ET.fromstring(xml).iter(f"{BPMN}subProcess") if e.get("id") == sub_id)
	return [e.get("id") for e in sub if e.get("id")]


class TestResolveScope(FrappeTestCase):
	def test_open_sub_process_wins_over_any_name(self):
		scope = resolve_scope(DIAGRAM, ["unrelated"], "sub")
		self.assertEqual((scope["id"], scope["name"]), ("sub", "Test Sub Process"))

	def test_message_naming_the_sub_process_resolves_it_ignoring_spacing_and_case(self):
		scope = resolve_scope(DIAGRAM, ["Yes, proceed", "Model the test subprocess as follows: ..."], "")
		self.assertEqual(scope["id"], "sub")

	def test_newest_message_that_names_one_is_used(self):
		xml = DIAGRAM.replace("</bpmn:process>", '<bpmn:subProcess id="other" name="Approval"/></bpmn:process>')
		scope = resolve_scope(xml, ["Yes, proceed", "add steps to the approval sub-process", "test sub process"], "")
		self.assertEqual(scope["id"], "other")

	def test_no_scope_when_nothing_names_a_sub_process(self):
		self.assertIsNone(resolve_scope(DIAGRAM, ["Add an email step after Start"], ""))
		self.assertIsNone(resolve_scope("", ["test sub process"], ""))

	def test_scope_carries_the_current_inner_xml(self):
		self.assertIn('id="old_step"', resolve_scope(DIAGRAM, [], "sub")["xml"])


class TestSpliceSubprocess(FrappeTestCase):
	def setUp(self):
		compiled = compile_ir(json.loads(json.dumps(STEPS)))
		self.assertTrue(compiled["ok"], compiled["problems"])
		self.compiled_xml = compiled["xml"]
		self.spliced = splice_subprocess(DIAGRAM, self.compiled_xml, "sub")

	def test_steps_land_inside_the_sub_process_and_the_old_ones_are_gone(self):
		inner = [i for i in _inside(self.spliced, "sub") if not i.startswith("flow_")]
		self.assertEqual(sorted(inner), ["a", "navigate", "z"])
		self.assertNotIn("old_step", self.spliced)

	def test_main_diagram_is_untouched(self):
		self.assertEqual(_main_ids(self.spliced)[:3], _main_ids(DIAGRAM)[:3])
		self.assertIn("intermediateThrowEvent", self.spliced)

	def test_sub_process_is_drawn_on_its_own_plane_only(self):
		root = ET.fromstring(self.spliced)
		planes = {p.get("bpmnElement"): p for p in root.iter(f"{BPMNDI}BPMNPlane")}
		self.assertEqual(sorted(planes), ["Process_1", "sub"])

		def drawn(plane):
			return {s.get("bpmnElement") for s in plane.iter(f"{BPMNDI}BPMNShape")}

		self.assertEqual(drawn(planes["sub"]), {"a", "navigate", "z"})
		self.assertEqual(drawn(planes["Process_1"]), {"start", "mid", "end", "sub"})

	def test_diagram_and_plane_ids_stay_unique(self):
		ids = re.findall(r'<bpmndi:BPMNDiagram id="([^"]+)"', self.spliced)
		self.assertEqual(len(ids), len(set(ids)))

	def test_configuration_of_a_step_that_stays_is_kept(self):
		kept = DIAGRAM.replace('id="old_step"', 'id="navigate"').replace('bpmnElement="old_step"', 'bpmnElement="navigate"')
		merged, removed = transfer_properties(kept, splice_subprocess(kept, self.compiled_xml, "sub"))
		self.assertEqual(removed, [])
		self.assertIn('assignmentMode="Session User"', merged)

	def test_a_configured_step_that_goes_is_reported_as_removed(self):
		_, removed = transfer_properties(DIAGRAM, self.spliced)
		self.assertEqual([r["id"] for r in removed], ["old_step"])
