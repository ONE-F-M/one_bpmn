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

	def test_a_sub_process_named_as_a_place_to_put_a_step_is_not_the_one_being_edited(self):
		for text in (
			"Add a step after Test Sub Process in the main flow",
			"Add a step before the test subprocess where HR is notified",
			"then Test Sub Process, add a notification",
		):
			self.assertIsNone(resolve_scope(DIAGRAM, [text], ""), text)

	def test_a_position_word_elsewhere_in_the_message_does_not_hide_the_sub_process(self):
		text = "Add to the Test Sub Process: a check that runs after the review step"
		self.assertEqual(resolve_scope(DIAGRAM, [text], "")["id"], "sub")

	def test_when_one_is_a_place_and_another_is_the_target_the_target_is_chosen(self):
		xml = DIAGRAM.replace("</bpmn:process>", '<bpmn:subProcess id="other" name="Approval"/></bpmn:process>')
		scope = resolve_scope(xml, ["After Test Sub Process, add steps to the Approval sub-process"], "")
		self.assertEqual(scope["id"], "other")

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

	def test_every_step_carries_the_flow_references_the_editor_lints_on(self):
		sub = next(e for e in ET.fromstring(self.spliced).iter(BPMN + "subProcess") if e.get("id") == "sub")
		flows = [f for f in sub if f.tag == BPMN + "sequenceFlow"]
		for step in [e for e in sub if e.get("id") and e.tag != BPMN + "sequenceFlow"]:
			incoming = [c.text for c in step.findall(BPMN + "incoming")]
			outgoing = [c.text for c in step.findall(BPMN + "outgoing")]
			self.assertEqual(incoming, [f.get("id") for f in flows if f.get("targetRef") == step.get("id")])
			self.assertEqual(outgoing, [f.get("id") for f in flows if f.get("sourceRef") == step.get("id")])

	def test_splicing_the_same_steps_again_does_not_repeat_the_references(self):
		again = splice_subprocess(self.spliced, self.compiled_xml, "sub")
		sub = next(e for e in ET.fromstring(again).iter(BPMN + "subProcess") if e.get("id") == "sub")
		for step in [e for e in sub if e.get("id") and e.tag != BPMN + "sequenceFlow"]:
			refs = [c.text for c in step if c.tag in (BPMN + "incoming", BPMN + "outgoing")]
			self.assertEqual(len(refs), len(set(refs)))


REJOIN = {
	"name": "Finance",
	"nodes": [
		{"id": "s", "type": "startEvent", "name": "Start"},
		{"id": "g", "type": "exclusiveGateway", "name": "Payable?"},
		{"id": "a", "type": "userTask", "name": "Submit"},
		{"id": "b", "type": "userTask", "name": "Prepare cheque"},
		{"id": "t", "type": "userTask", "name": "Sign"},
		{"id": "e", "type": "endEvent", "name": "Done"},
	],
	"flows": [
		{"from": "s", "to": "g"},
		{"from": "g", "to": "a", "condition": "payable == True"},
		{"from": "g", "to": "b", "default": True},
		{"from": "a", "to": "t"},
		{"from": "b", "to": "t"},
		{"from": "t", "to": "e"},
	],
}
OTHER_SUB = """<bpmn:subProcess id="other" name="Other"><bpmn:exclusiveGateway id="gw_join_1" name="Other join"/></bpmn:subProcess>"""
OTHER_PLANE = """<bpmndi:BPMNDiagram id="BPMNDiagram_other"><bpmndi:BPMNPlane id="BPMNPlane_other" bpmnElement="other">
    <bpmndi:BPMNShape id="gw_join_1_di" bpmnElement="gw_join_1"><dc:Bounds x="10" y="10" width="50" height="50"/></bpmndi:BPMNShape>
  </bpmndi:BPMNPlane></bpmndi:BPMNDiagram>
</bpmn:definitions>"""


class TestSpliceKeepsIdsUnique(FrappeTestCase):
	"""Two sub-processes each compiled alone both get a compiler-inferred gateway numbered from 1."""

	def setUp(self):
		compiled = compile_ir(json.loads(json.dumps(REJOIN)))
		self.assertTrue(compiled["ok"], compiled["problems"])
		self.assertIn('id="gw_join_1"', compiled["xml"])
		xml = DIAGRAM.replace("</bpmn:process>", OTHER_SUB + "</bpmn:process>").replace("</bpmn:definitions>", OTHER_PLANE)
		self.spliced = splice_subprocess(xml, compiled["xml"], "sub")
		self.root = ET.fromstring(self.spliced)

	def _ids(self):
		return [e.get("id") for e in self.root.iter() if e.get("id")]

	def test_no_id_appears_twice_in_the_document(self):
		ids = self._ids()
		self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [])

	def test_the_other_sub_process_keeps_its_gateway_and_drawing(self):
		other = next(e for e in self.root.iter(BPMN + "subProcess") if e.get("id") == "other")
		self.assertEqual([e.get("id") for e in other], ["gw_join_1"])
		self.assertIn('bpmnElement="gw_join_1"', self.spliced)

	def test_every_reference_resolves_and_every_step_is_drawn(self):
		ids = set(self._ids())
		for e in self.root.iter(BPMN + "sequenceFlow"):
			self.assertIn(e.get("sourceRef"), ids)
			self.assertIn(e.get("targetRef"), ids)
		sub = next(e for e in self.root.iter(BPMN + "subProcess") if e.get("id") == "sub")
		plane = next(p for p in self.root.iter(BPMNDI + "BPMNPlane") if p.get("bpmnElement") == "sub")
		drawn = {s.get("bpmnElement") for s in plane.iter() if s.get("bpmnElement")}
		self.assertEqual({e.get("id") for e in sub if e.get("id")} - drawn, set())
