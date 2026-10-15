# Copyright (c) 2026, one-fm and contributors
"""An existing step becomes an expanded sub-process holding the steps described, and nothing else changes."""

import copy
import json
from xml.etree import ElementTree as ET

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir
from one_bpmn.agents.prosally_helpers import (
	convert_step_to_subprocess,
	find_missing_target,
	resolve_step,
	restore_call_activities,
	transfer_properties,
)
from one_bpmn.security.bpmn_validator import validate_bpmn_xml
from one_bpmn.tests.test_prosally_subprocess_scope import STEPS

BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
BPMNDI = "{http://www.omg.org/spec/BPMN/20100524/DI}"
DC = "{http://www.omg.org/spec/DD/20100524/DC}"
DI = "{http://www.omg.org/spec/DD/20100524/DI}"
HEAD = (
	'<?xml version="1.0" encoding="UTF-8"?>'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
	'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
	'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
	'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="D" targetNamespace="http://bpmn.io/schema/bpmn">'
)

# (id, tag, name, x, y, w, h, extra attributes)
STEPS_ON_CANVAS = [
	("s", "startEvent", "Start", 100, 100, 36, 36, ""),
	("prep", "userTask", "Prepare", 200, 82, 100, 80, 'spiffworkflow:assignmentMode="Session User"'),
	("conv", "userTask", "Complete Payroll Clearance", 350, 82, 100, 80, 'spiffworkflow:assignmentMode="Role"'),
	("call", "callActivity", "Call Closure", 500, 82, 100, 80, 'calledElement="Process_Closure"'),
	("notify", "serviceTask", "Notify HR", 650, 82, 100, 80, 'spiffworkflow:serviceType="Email"'),
	("e", "endEvent", "End", 800, 100, 36, 36, ""),
	("below", "userTask", "Audit", 350, 250, 100, 80, ""),
]
PATH = ["s", "prep", "conv", "call", "notify", "e"]


def _diagram(lanes=False):
	by_id = {r[0]: r for r in STEPS_ON_CANVAS}
	elements, shapes, edges = [], [], []
	for i, tag, name, x, y, w, h, extra in STEPS_ON_CANVAS:
		doc = "<bpmn:documentation>Pays out</bpmn:documentation>" if i == "conv" else ""
		elements.append(f'<bpmn:{tag} id="{i}" name="{name}" {extra}>{doc}</bpmn:{tag}>')
		shapes.append(
			f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}"><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}"/></bpmndi:BPMNShape>'
		)
	for n, (a, b) in enumerate(zip(PATH, PATH[1:], strict=False)):
		elements.append(f'<bpmn:sequenceFlow id="f{n}" sourceRef="{a}" targetRef="{b}"/>')
		ax, ay, aw, ah = by_id[a][3:7]
		bx, by_, _, bh = by_id[b][3:7]
		edges.append(
			f'<bpmndi:BPMNEdge id="f{n}_di" bpmnElement="f{n}"><di:waypoint x="{ax + aw}" y="{ay + ah // 2}"/>'
			f'<di:waypoint x="{bx}" y="{by_ + bh // 2}"/></bpmndi:BPMNEdge>'
		)
	pool = ""
	if lanes:
		pool = (
			'<bpmndi:BPMNShape id="part_di" bpmnElement="part" isHorizontal="true"><dc:Bounds x="50" y="40" width="900" height="400"/></bpmndi:BPMNShape>'
			'<bpmndi:BPMNShape id="l1_di" bpmnElement="l1" isHorizontal="true"><dc:Bounds x="80" y="40" width="870" height="200"/></bpmndi:BPMNShape>'
			'<bpmndi:BPMNShape id="l2_di" bpmnElement="l2" isHorizontal="true"><dc:Bounds x="80" y="240" width="870" height="200"/></bpmndi:BPMNShape>'
		)
	root_ref = "Collaboration_1" if lanes else "P"
	collab = (
		'<bpmn:collaboration id="Collaboration_1"><bpmn:participant id="part" name="Offboarding" processRef="P"/></bpmn:collaboration>'
		if lanes
		else ""
	)
	laneset = (
		'<bpmn:laneSet id="ls"><bpmn:lane id="l1" name="Payroll"/><bpmn:lane id="l2" name="Audit"/></bpmn:laneSet>'
		if lanes
		else ""
	)
	return (
		f'{HEAD}{collab}<bpmn:process id="P" name="Employee Offboarding" isExecutable="true">{laneset}{"".join(elements)}</bpmn:process>'
		f'<bpmndi:BPMNDiagram id="d1"><bpmndi:BPMNPlane id="p1" bpmnElement="{root_ref}">{pool}{"".join(shapes)}{"".join(edges)}'
		"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram></bpmn:definitions>"
	)


def _child_xml(ir=STEPS):
	compiled = compile_ir(json.loads(json.dumps(ir)))
	assert compiled["ok"], compiled["problems"]
	return compiled["xml"]


def _rect(root, element_id):
	for shape in root.iter(BPMNDI + "BPMNShape"):
		if shape.get("bpmnElement") == element_id:
			b = shape.find(DC + "Bounds")
			return tuple(float(b.get(k)) for k in ("x", "y", "width", "height"))
	return None


def _shape(root, element_id):
	return next(s for s in root.iter(BPMNDI + "BPMNShape") if s.get("bpmnElement") == element_id)


def _inside(inner, outer):
	return (
		inner[0] >= outer[0]
		and inner[1] >= outer[1]
		and inner[0] + inner[2] <= outer[0] + outer[2]
		and inner[1] + inner[3] <= outer[1] + outer[3]
	)


def _apart(a, b):
	return a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1]


def _element(root, element_id):
	return next(e for e in root.iter() if e.get("id") == element_id)


class TestConvertStep(FrappeTestCase):
	def setUp(self):
		self.before = _diagram()
		self.after = convert_step_to_subprocess(self.before, "conv", _child_xml())
		self.old_root, self.root = ET.fromstring(self.before), ET.fromstring(self.after)

	def test_the_step_becomes_a_sub_process_with_the_same_id_and_name(self):
		sub = _element(self.root, "conv")
		self.assertEqual((sub.tag, sub.get("name")), (BPMN + "subProcess", "Complete Payroll Clearance"))
		inside = [e.get("name") for e in sub if e.tag != BPMN + "sequenceFlow" and e.get("name")]
		self.assertEqual(inside, ["Start", "Navigate to the list", "Document is saved"])

	def test_the_flows_into_and_out_of_the_step_are_untouched(self):
		for flow in ("f1", "f2"):
			self.assertEqual(_element(self.root, flow).attrib, _element(self.old_root, flow).attrib)

	def test_every_other_element_keeps_its_id_and_configuration(self):
		for element_id in ("s", "prep", "notify", "e", "below", "f0", "f3", "f4"):
			old, new = _element(self.old_root, element_id), _element(self.root, element_id)
			self.assertEqual(new.attrib, old.attrib, element_id)
			self.assertEqual([c.tag for c in new], [c.tag for c in old], element_id)

	def test_a_call_activity_and_the_process_it_calls_are_unchanged(self):
		old, new = _element(self.old_root, "call"), _element(self.root, "call")
		self.assertEqual(new.tag, BPMN + "callActivity")
		self.assertEqual(new.attrib, old.attrib)
		self.assertEqual(new.get("calledElement"), "Process_Closure")

	def test_the_documentation_of_the_step_is_kept_and_its_task_settings_are_dropped(self):
		sub = _element(self.root, "conv")
		self.assertEqual(sub.find(BPMN + "documentation").text, "Pays out")
		self.assertFalse([k for k in sub.attrib if "spiffworkflow" in k])

	def test_the_box_is_expanded_and_holds_its_steps_on_the_main_plane(self):
		box = _rect(self.root, "conv")
		self.assertEqual(_shape(self.root, "conv").get("isExpanded"), "true")
		self.assertTrue(box[2] > 100 and box[3] > 80)
		for step in ("navigate", "z", "a"):
			self.assertTrue(_inside(_rect(self.root, step), box), step)
		self.assertEqual(len(list(self.root.iter(BPMNDI + "BPMNPlane"))), 1)

	def test_nothing_overlaps_the_grown_box_and_gaps_to_its_neighbours_are_kept(self):
		box, old = _rect(self.root, "conv"), _rect(self.old_root, "conv")
		for other in ("s", "prep", "call", "notify", "e", "below"):
			self.assertTrue(_apart(_rect(self.root, other), box), other)
		old_gap = _rect(self.old_root, "call")[0] - (old[0] + old[2])
		self.assertEqual(_rect(self.root, "call")[0] - (box[0] + box[2]), old_gap)
		old_below = _rect(self.old_root, "below")[1] - (old[1] + old[3])
		self.assertEqual(_rect(self.root, "below")[1] - (box[1] + box[3]), old_below)

	def test_a_flow_that_meets_the_box_still_meets_it(self):
		box = _rect(self.root, "conv")
		edge = next(e for e in self.root.iter(BPMNDI + "BPMNEdge") if e.get("bpmnElement") == "f2")
		start = edge.findall(DI + "waypoint")[0]
		self.assertEqual(float(start.get("x")), box[0] + box[2])

	def test_the_result_passes_the_validator(self):
		unconnected = [v for v in validate_bpmn_xml(self.after)["violations"] if "below" not in v]
		self.assertEqual(unconnected, [])

	def test_ids_stay_unique_when_the_new_steps_reuse_an_id_already_in_the_diagram(self):
		child = copy.deepcopy(STEPS)
		child["nodes"][1]["id"] = "prep"
		child["flows"] = [{"from": "a", "to": "prep"}, {"from": "prep", "to": "z"}]
		merged = ET.fromstring(convert_step_to_subprocess(self.before, "conv", _child_xml(child)))
		ids = [e.get("id") for e in merged.iter() if e.get("id")]
		self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [])
		self.assertEqual(_element(merged, "prep").get("name"), "Prepare")


class TestConvertStepInALane(FrappeTestCase):
	def test_the_lane_and_the_pool_grow_with_the_box(self):
		before = _diagram(lanes=True)
		after = convert_step_to_subprocess(before, "conv", _child_xml())
		old, new = ET.fromstring(before), ET.fromstring(after)
		grown = _rect(new, "conv")[3] - _rect(old, "conv")[3]
		widened = _rect(new, "conv")[2] - _rect(old, "conv")[2]
		self.assertEqual(_rect(new, "l1")[3] - _rect(old, "l1")[3], grown)
		self.assertEqual(_rect(new, "part")[3] - _rect(old, "part")[3], grown)
		self.assertEqual(_rect(new, "l2")[1] - _rect(old, "l2")[1], grown)
		self.assertEqual(_rect(new, "l1")[2] - _rect(old, "l1")[2], widened)
		for step in ("s", "prep", "conv", "call", "notify", "e"):
			self.assertTrue(_inside(_rect(new, step), _rect(new, "l1")), step)
		self.assertTrue(_inside(_rect(new, "below"), _rect(new, "l2")))


class TestKeepsOldSettingsOff(FrappeTestCase):
	def test_the_settings_of_the_converted_step_are_not_copied_back_onto_the_sub_process(self):
		before = _diagram()
		after = convert_step_to_subprocess(before, "conv", _child_xml())
		merged, removed = transfer_properties(before, after, skip_ids=("conv",))
		sub = _element(ET.fromstring(merged), "conv")
		self.assertFalse([k for k in sub.attrib if "spiffworkflow" in k])
		self.assertEqual(removed, [])
		kept = _element(ET.fromstring(merged), "prep")
		self.assertEqual(kept.get("{http://spiffworkflow.org/bpmn/schema/1.0/core}assignmentMode"), "Session User")


class TestRestoreCallActivities(FrappeTestCase):
	def _regenerated(self):
		"""The diagram as a whole-diagram modify returns it: the call activity compiled as a script task."""
		xml = _diagram()
		return xml.replace(
			'<bpmn:callActivity id="call" name="Call Closure" calledElement="Process_Closure"></bpmn:callActivity>',
			'<bpmn:scriptTask id="call" name="Call Closure"></bpmn:scriptTask>',
		)

	def test_a_call_activity_that_came_back_as_something_else_is_put_back_as_it_was(self):
		regenerated = self._regenerated()
		self.assertNotIn("callActivity", regenerated)
		restored = ET.fromstring(restore_call_activities(_diagram(), regenerated))
		call = _element(restored, "call")
		self.assertEqual(call.tag, BPMN + "callActivity")
		self.assertEqual(call.get("calledElement"), "Process_Closure")
		self.assertEqual(call.get("name"), "Call Closure")

	def test_it_stays_where_it_was_in_the_process(self):
		restored = ET.fromstring(restore_call_activities(_diagram(), self._regenerated()))
		order = [e.get("id") for e in restored.find(BPMN + "process") if e.get("id")]
		self.assertEqual(order.index("call"), [e.get("id") for e in ET.fromstring(_diagram()).find(BPMN + "process")].index("call"))

	def test_a_diagram_with_no_call_activity_comes_back_as_given(self):
		plain = _diagram().replace("callActivity", "scriptTask")
		self.assertEqual(restore_call_activities(plain, plain), plain)

	def test_a_call_activity_the_modify_removed_stays_removed(self):
		gone = self._regenerated().replace('<bpmn:scriptTask id="call" name="Call Closure"></bpmn:scriptTask>', "")
		self.assertNotIn('id="call"', restore_call_activities(_diagram(), gone).split("<bpmndi:")[0])


class TestFindMissingTarget(FrappeTestCase):
	def test_a_misnamed_step_is_reported_with_the_closest_names_on_the_diagram(self):
		missing = find_missing_target(_diagram(), ["Create a sub process for Complete Payroll Acceptance: checks pending salary"])
		self.assertEqual(missing["asked"], "Complete Payroll Acceptance")
		self.assertEqual(missing["candidates"][0], {"name": "Complete Payroll Clearance", "kind": "step"})

	def test_a_sub_process_is_offered_as_one(self):
		xml = _diagram().replace("</bpmn:process>", '<bpmn:subProcess id="sp" name="Payroll Clearance"/></bpmn:process>')
		missing = find_missing_target(xml, ["Create a sub process for Payroll Clearence: steps"])
		self.assertIn({"name": "Payroll Clearance", "kind": "sub-process"}, missing["candidates"])

	def test_what_is_on_the_main_diagram_is_offered_before_a_step_inside_a_sub_process(self):
		xml = _diagram().replace(
			"</bpmn:process>",
			'<bpmn:subProcess id="sp" name="Payroll Clearance"><bpmn:userTask id="in1" name="Submit Payroll Clearance"/>'
			"</bpmn:subProcess></bpmn:process>",
		)
		missing = find_missing_target(xml, ["Create a sub process for Complete Payroll Acceptance: steps"])
		names = [c["name"] for c in missing["candidates"]]
		self.assertLess(names.index("Payroll Clearance"), names.index("Submit Payroll Clearance"))

	def test_an_exact_name_is_not_missing(self):
		self.assertIsNone(find_missing_target(_diagram(), ["Create a sub process for Complete Payroll Clearance: steps"]))

	def test_a_name_with_a_trailing_word_is_not_missing(self):
		self.assertIsNone(find_missing_target(_diagram(), ["Create a sub process for the Complete Payroll Clearance step"]))

	def test_a_new_sub_process_with_no_close_name_is_left_to_the_classifier(self):
		self.assertIsNone(find_missing_target(_diagram(), ["Add a sub process for background checks: verify references"]))

	def test_a_message_that_does_not_ask_for_a_sub_process_is_ignored(self):
		self.assertIsNone(find_missing_target(_diagram(), ["Rename Complete Payroll Acceptance to Done"]))

	def test_an_empty_diagram_has_nothing_to_miss(self):
		self.assertIsNone(find_missing_target("", ["Create a sub process for Complete Payroll Acceptance: steps"]))

	def test_the_newest_message_that_asks_for_one_is_used(self):
		texts = ["Yes, proceed", "Create a sub process for Complete Payroll Acceptance: steps"]
		self.assertEqual(find_missing_target(_diagram(), texts)["asked"], "Complete Payroll Acceptance")


class TestResolveStep(FrappeTestCase):
	def test_a_message_that_asks_for_a_sub_process_for_a_step_names_that_step(self):
		message = "Create a sub process for Complete Payroll Clearance: Payroll Operator checks pending salary"
		step = resolve_step(_diagram(), [message])
		self.assertEqual((step["id"], step["name"]), ("conv", "Complete Payroll Clearance"))

	def test_the_name_may_differ_in_case_and_spacing(self):
		self.assertEqual(resolve_step(_diagram(), ["make complete payroll-clearance a subprocess"])["id"], "conv")

	def test_a_message_that_names_a_step_without_asking_for_a_sub_process_is_not_a_conversion(self):
		self.assertIsNone(resolve_step(_diagram(), ["Rename Complete Payroll Clearance to Payroll done"]))

	def test_a_call_activity_is_never_converted(self):
		self.assertIsNone(resolve_step(_diagram(), ["Create a sub process for Call Closure: do things"]))

	def test_an_earlier_message_still_names_the_step_when_the_latest_is_a_yes(self):
		texts = ["Yes, proceed", "Create a sub process for Complete Payroll Clearance: checks"]
		self.assertEqual(resolve_step(_diagram(), texts)["id"], "conv")

	def test_nothing_matches_a_diagram_without_that_step(self):
		self.assertIsNone(resolve_step(_diagram(), ["Create a sub process for Visa Stamping: steps"]))
		self.assertIsNone(resolve_step("", ["Create a sub process for Complete Payroll Clearance"]))
