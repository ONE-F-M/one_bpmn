# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A non-executable process is drawn with plain None tasks, and an executable one never is."""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir
from one_bpmn.agents.bpmn_task_config import use_none_tasks
from one_bpmn.agents.prosally_helpers import xml_to_ir
from one_bpmn.security.bpmn_validator import validate_bpmn_xml


def _document(executable: bool, task_tag: str = "task") -> str:
	shapes = "".join(
		f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}"><dc:Bounds x="0" y="0" width="100" height="80"/></bpmndi:BPMNShape>'
		for i in ("s", "t", "e")
	)
	edges = "".join(
		f'<bpmndi:BPMNEdge id="{i}_di" bpmnElement="{i}"><di:waypoint x="0" y="0"/><di:waypoint x="10" y="0"/></bpmndi:BPMNEdge>'
		for i in ("f1", "f2")
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
		'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="D" targetNamespace="http://bpmn.io/schema/bpmn">'
		f'<bpmn:process id="p" isExecutable="{str(executable).lower()}">'
		'<bpmn:startEvent id="s" name="Start"/>'
		f'<bpmn:{task_tag} id="t" name="Do it"/>'
		'<bpmn:endEvent id="e" name="End"/>'
		'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t"/>'
		'<bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e"/>'
		"</bpmn:process>"
		'<bpmndi:BPMNDiagram id="BD"><bpmndi:BPMNPlane id="BP" bpmnElement="p">' + shapes + edges + "</bpmndi:BPMNPlane>"
		"</bpmndi:BPMNDiagram></bpmn:definitions>"
	)


def _task_type_violations(xml: str) -> list[str]:
	return [v for v in validate_bpmn_xml(xml)["violations"] if v.startswith("[task-type]")]


class TestValidatorAllowsNoneTasksWhenNonExecutable(FrappeTestCase):
	def test_a_plain_task_is_allowed_in_a_non_executable_process(self):
		self.assertEqual(_task_type_violations(_document(executable=False)), [])

	def test_a_plain_task_is_still_rejected_in_an_executable_process(self):
		self.assertEqual(len(_task_type_violations(_document(executable=True))), 1)


def _sub_process_document(executable: bool) -> str:
	ids = ("s", "sub", "e", "ss", "st", "se")
	shapes = "".join(
		f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}"><dc:Bounds x="0" y="0" width="100" height="80"/></bpmndi:BPMNShape>'
		for i in ids
	)
	edges = "".join(
		f'<bpmndi:BPMNEdge id="{i}_di" bpmnElement="{i}"><di:waypoint x="0" y="0"/><di:waypoint x="10" y="0"/></bpmndi:BPMNEdge>'
		for i in ("f1", "f2", "g1", "g2")
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
		'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="D" targetNamespace="http://bpmn.io/schema/bpmn">'
		f'<bpmn:process id="p" isExecutable="{str(executable).lower()}">'
		'<bpmn:startEvent id="s" name="Start"/>'
		'<bpmn:subProcess id="sub" name="Inner">'
		'<bpmn:startEvent id="ss" name="Inner start"/><bpmn:task id="st" name="Inner step"/>'
		'<bpmn:endEvent id="se" name="Inner end"/>'
		'<bpmn:sequenceFlow id="g1" sourceRef="ss" targetRef="st"/>'
		'<bpmn:sequenceFlow id="g2" sourceRef="st" targetRef="se"/>'
		"</bpmn:subProcess>"
		'<bpmn:endEvent id="e" name="End"/>'
		'<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="sub"/>'
		'<bpmn:sequenceFlow id="f2" sourceRef="sub" targetRef="e"/>'
		"</bpmn:process>"
		'<bpmndi:BPMNDiagram id="BD"><bpmndi:BPMNPlane id="BP" bpmnElement="p">' + shapes + edges + "</bpmndi:BPMNPlane>"
		"</bpmndi:BPMNDiagram></bpmn:definitions>"
	)


class TestValidatorKeepsTheKindInsideSubProcesses(FrappeTestCase):
	def test_a_plain_task_in_a_sub_process_of_an_executable_process_is_rejected(self):
		self.assertEqual(len(_task_type_violations(_sub_process_document(executable=True))), 1)

	def test_a_plain_task_in_a_sub_process_of_a_non_executable_process_is_allowed(self):
		self.assertEqual(_task_type_violations(_sub_process_document(executable=False)), [])


TASK_TYPES = ("userTask", "serviceTask", "scriptTask", "manualTask", "businessRuleTask")


def _ir(executable=None):
	nodes = [{"id": "s", "type": "startEvent", "name": "Start", "lane": "a"}]
	nodes += [
		{"id": t, "type": t, "name": t, "lane": "a", "config": {"serviceTargetDoctype": "ToDo"}} for t in TASK_TYPES
	]
	nodes.append({"id": "e", "type": "endEvent", "name": "End", "lane": "a"})
	flows = [{"from": a["id"], "to": b["id"]} for a, b in zip(nodes, nodes[1:])]
	ir = {"name": "P", "lanes": [{"id": "a", "name": "A"}], "nodes": nodes, "flows": flows}
	if executable is not None:
		ir["executable"] = executable
	return ir


class TestUseNoneTasks(FrappeTestCase):
	def test_every_task_type_becomes_a_none_task_when_non_executable(self):
		ir = _ir(executable=False)

		use_none_tasks(ir)

		kinds = {n["id"]: n["type"] for n in ir["nodes"]}
		self.assertEqual({kinds[t] for t in TASK_TYPES}, {"task"})
		self.assertEqual((kinds["s"], kinds["e"]), ("startEvent", "endEvent"))

	def test_task_settings_are_dropped_when_non_executable(self):
		ir = _ir(executable=False)

		use_none_tasks(ir)

		self.assertFalse(any("config" in n or "attrs" in n for n in ir["nodes"]))

	def test_tasks_inside_a_sub_process_are_changed_too(self):
		inner = {"id": "x", "type": "userTask", "name": "Inner"}
		ir = {"executable": False, "nodes": [{"id": "sub", "type": "subProcess", "children": {"nodes": [inner]}}]}

		use_none_tasks(ir)

		self.assertEqual(inner["type"], "task")
		self.assertEqual(ir["nodes"][0]["type"], "subProcess")

	def test_an_executable_process_keeps_its_task_types(self):
		for ir in (_ir(executable=True), _ir()):
			use_none_tasks(ir)

			self.assertEqual([n["type"] for n in ir["nodes"] if n["id"] in TASK_TYPES], list(TASK_TYPES))


class TestCompileNoneTasks(FrappeTestCase):
	def test_a_non_executable_ir_compiles_to_none_tasks_only(self):
		result = compile_ir(_ir(executable=False))

		self.assertTrue(result["ok"], result["problems"])
		self.assertEqual(result["xml"].count("<bpmn:task "), len(TASK_TYPES))
		for tag in ("userTask", "serviceTask", "scriptTask", "manualTask", "businessRuleTask"):
			self.assertNotIn(f"<bpmn:{tag} ", result["xml"])


class TestXmlToIrKeepsTheKind(FrappeTestCase):
	def test_a_non_executable_none_task_map_reads_back_as_non_executable(self):
		ir = xml_to_ir(_document(executable=False))

		self.assertIs(ir["executable"], False)
		self.assertIn("task", {n["type"] for n in ir["nodes"]})

	def test_an_executable_map_carries_no_executable_flag(self):
		ir = xml_to_ir(_document(executable=True, task_tag="userTask"))

		self.assertNotIn("executable", ir)

	def test_a_none_task_map_survives_a_round_trip(self):
		result = compile_ir(xml_to_ir(_document(executable=False)))

		self.assertTrue(result["ok"], result["problems"])
		self.assertIn("<bpmn:task ", result["xml"])
		self.assertIn('isExecutable="false"', result["xml"])
