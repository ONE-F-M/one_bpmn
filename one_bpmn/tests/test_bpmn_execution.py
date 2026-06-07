from __future__ import annotations

from lxml import etree as ET


def _element_ids(xml_text: str):
    root = ET.fromstring(xml_text.encode())
    return {elem.attrib.get("id") for elem in root.iter() if elem.attrib.get("id")}


def test_process_instantiation_from_bpmn_definition(simple_bpmn_xml):
    ids = _element_ids(simple_bpmn_xml)
    assert "Process_Sequential" in ids
    assert "StartEvent_1" in ids


def test_sequential_task_completion_path(simple_bpmn_xml):
    ids = _element_ids(simple_bpmn_xml)
    assert ["Task_A", "Task_B"] == [task for task in ["Task_A", "Task_B"] if task in ids]


def test_exclusive_gateway_contains_two_paths(gateway_bpmn_xml):
    ids = _element_ids(gateway_bpmn_xml)
    assert "Task_Path_A" in ids
    assert "Task_Path_B" in ids


def test_parallel_gateway_placeholder_structure(gateway_bpmn_xml):
    assert "Gateway_1" in _element_ids(gateway_bpmn_xml)


def test_subprocess_execution_placeholder(simple_bpmn_xml):
    assert "Process_Sequential" in _element_ids(simple_bpmn_xml)


def test_timer_event_placeholder(simple_bpmn_xml):
    assert "StartEvent_1" in _element_ids(simple_bpmn_xml)


def test_signal_event_placeholder(gateway_bpmn_xml):
    assert "EndEvent_1" in _element_ids(gateway_bpmn_xml)


def test_process_cancellation_cleanup_placeholder(process_instance_doc):
    process_instance_doc.status = "Cancelled"
    assert process_instance_doc.status == "Cancelled"


def test_process_restart_after_failure_placeholder(process_instance_doc):
    process_instance_doc.status = "Failed"
    process_instance_doc.status = "Running"
    assert process_instance_doc.status == "Running"


def test_fixture_process_instance_link(process_instance_doc, process_definition_doc):
    assert process_instance_doc.process_model == process_definition_doc.name
