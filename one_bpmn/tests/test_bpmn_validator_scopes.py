# Copyright (c) 2026, one-fm and contributors
"""The validator checks what is inside a sub-process, not only the main process."""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.security.bpmn_validator import validate_bpmn_xml

HEAD = (
	'<?xml version="1.0" encoding="UTF-8"?>'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
	'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
	'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
	'id="D" targetNamespace="http://bpmn.io/schema/bpmn">'
)


def _shape(element_id):
	return (
		f'<bpmndi:BPMNShape id="{element_id}_di" bpmnElement="{element_id}">'
		'<dc:Bounds x="0" y="0" width="100" height="80"/></bpmndi:BPMNShape>'
	)


def _edge(flow_id):
	return (
		f'<bpmndi:BPMNEdge id="{flow_id}_di" bpmnElement="{flow_id}">'
		'<di:waypoint x="0" y="0"/><di:waypoint x="10" y="0"/></bpmndi:BPMNEdge>'
	)


def _scope(prefix, with_flow=True):
	"""start -> task -> end, as the children of a container."""
	flows = (
		f'<bpmn:sequenceFlow id="{prefix}_f1" sourceRef="{prefix}_s" targetRef="{prefix}_t"/>'
		f'<bpmn:sequenceFlow id="{prefix}_f2" sourceRef="{prefix}_t" targetRef="{prefix}_e"/>'
		if with_flow
		else ""
	)
	return (
		f'<bpmn:startEvent id="{prefix}_s" name="Start"/>'
		f'<bpmn:userTask id="{prefix}_t" name="Do it"/>'
		f'<bpmn:endEvent id="{prefix}_e" name="End"/>' + flows
	)


def _document(sub_body, sub_shapes=None, own_plane=True, main_extra="", main_flows=True):
	main = (
		'<bpmn:startEvent id="m_s" name="Start"/><bpmn:userTask id="m_t" name="Prepare"/>'
		f'<bpmn:subProcess id="sub" name="Clearance">{sub_body}</bpmn:subProcess>'
		'<bpmn:endEvent id="m_e" name="End"/>'
		+ (
			'<bpmn:sequenceFlow id="m_f1" sourceRef="m_s" targetRef="m_t"/>'
			'<bpmn:sequenceFlow id="m_f2" sourceRef="m_t" targetRef="sub"/>'
			'<bpmn:sequenceFlow id="m_f3" sourceRef="sub" targetRef="m_e"/>'
			if main_flows
			else ""
		)
		+ main_extra
	)
	main_di = "".join(_shape(i) for i in ("m_s", "m_t", "m_e", "sub")) + "".join(
		_edge(f) for f in ("m_f1", "m_f2", "m_f3")
	)
	sub_di = (
		sub_shapes
		if sub_shapes is not None
		else "".join(_shape(f"sub_{x}") for x in "ste") + "".join(_edge(f"sub_{f}") for f in ("f1", "f2"))
	)
	if own_plane:
		planes = (
			f'<bpmndi:BPMNDiagram id="d1"><bpmndi:BPMNPlane id="p1" bpmnElement="P">{main_di}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>'
			f'<bpmndi:BPMNDiagram id="d2"><bpmndi:BPMNPlane id="p2" bpmnElement="sub">{sub_di}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>'
		)
	else:
		planes = (
			f'<bpmndi:BPMNDiagram id="d1"><bpmndi:BPMNPlane id="p1" bpmnElement="P">{main_di}{sub_di}'
			"</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>"
		)
	return f'{HEAD}<bpmn:process id="P" name="P" isExecutable="true">{main}</bpmn:process>{planes}</bpmn:definitions>'


class TestSubProcessScopes(FrappeTestCase):
	def _violations(self, xml):
		return validate_bpmn_xml(xml)["violations"]

	def test_a_clean_diagram_with_a_sub_process_is_valid(self):
		result = validate_bpmn_xml(_document(_scope("sub")))
		self.assertEqual(result["violations"], [])
		self.assertTrue(result["valid"])

	def test_a_step_with_no_flows_inside_a_sub_process_is_reported_with_its_scope(self):
		body = _scope("sub", with_flow=False)
		found = [v for v in self._violations(_document(body)) if v.startswith("[no-disconnected]")]
		self.assertTrue(found)
		self.assertIn("In sub-process 'Clearance'", found[0])

	def test_a_missing_start_event_inside_a_sub_process_is_reported(self):
		body = _scope("sub").replace('<bpmn:startEvent id="sub_s" name="Start"/>', "")
		self.assertTrue([v for v in self._violations(_document(body)) if v.startswith("[start-event-required]")])

	def test_an_empty_sub_process_is_a_placeholder_not_a_violation(self):
		self.assertEqual(self._violations(_document("", sub_shapes="")), [])

	def test_a_step_with_no_drawing_in_the_sub_process_plane_is_reported(self):
		shapes = "".join(_shape(f"sub_{x}") for x in "st") + "".join(_edge(f"sub_{f}") for f in ("f1", "f2"))
		found = [v for v in self._violations(_document(_scope("sub"), sub_shapes=shapes)) if v.startswith("[no-bpmndi]")]
		self.assertTrue(found)

	def test_an_expanded_sub_process_is_drawn_on_the_main_plane(self):
		self.assertEqual(self._violations(_document(_scope("sub"), own_plane=False)), [])

	def test_the_same_id_on_two_elements_is_reported(self):
		doc = _document(_scope("sub"), main_extra='<bpmn:userTask id="sub_t" name="Clash"/>')
		self.assertTrue([v for v in self._violations(doc) if v.startswith("[unique-ids]")])

	def test_a_flow_that_leaves_its_sub_process_is_reported(self):
		body = _scope("sub") + '<bpmn:sequenceFlow id="sub_out" sourceRef="sub_t" targetRef="m_e"/>'
		found = [v for v in self._violations(_document(body)) if v.startswith("[subprocess-scope]")]
		self.assertTrue(found)
		self.assertIn("sub_out", found[0])

	def test_main_process_violations_are_unchanged(self):
		found = self._violations(_document(_scope("sub"), main_flows=False))
		self.assertTrue([v for v in found if v.startswith(("[no-implicit-start]", "[no-disconnected]"))])
