"""
Tests for the XML Property Preserver.

Covers:
  1. SpiffWorkflow extension attributes preserved during transfer
  2. Camunda namespace attributes preserved during transfer
  3. <documentation> elements preserved during transfer
  4. extensionElements children preserved during transfer
  5. Removed elements reported with correct configs
  6. Documentation loss reported in removal warning
  7. extract_configured_elements captures all property types
  8. Smoke test: full round-trip with mixed property types
  9. Empty / malformed XML handled gracefully
 10. summarize_configured_elements includes documentation
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from one_bpmn.agents.google_adk.prosally_agent.xml_property_preserver import (
	extract_configured_elements,
	format_removal_warning,
	summarize_configured_elements,
	transfer_properties,
)


# ── Namespace constants ───────────────────────────────────────────────────────
BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF = "http://spiffworkflow.org/bpmn/schema/1.0/core"
CAMUNDA = "http://camunda.org/schema/1.0/bpmn"
CUSTOM = "http://custom/text-style"


# ── Fixture XML strings ──────────────────────────────────────────────────────

_OLD_XML_SPIFF = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <userTask id="Task_A" name="Review"
              spiffworkflow:assignmentMode="round_robin"
              spiffworkflow:assignee="john">
      <documentation>Reviewer checks request.</documentation>
    </userTask>
    <scriptTask id="Task_B" name="Notify"
                spiffworkflow:serverScript="send_email()">
      <documentation>System sends notification.</documentation>
    </scriptTask>
    <startEvent id="Start_1" name="Start" />
    <endEvent id="End_1" name="Done" />
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="Task_B" />
    <sequenceFlow id="Flow_3" sourceRef="Task_B" targetRef="End_1" />
  </process>
</definitions>"""


_OLD_XML_CAMUNDA = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:camunda="http://camunda.org/schema/1.0/bpmn"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <userTask id="Task_A" name="Review Request"
              camunda:assignee="${reviewer}"
              camunda:candidateGroups="review_team">
      <documentation>Reviewer checks the incoming request.</documentation>
    </userTask>
    <startEvent id="Start_1" name="Start" />
    <endEvent id="End_1" name="Done" />
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="End_1" />
  </process>
</definitions>"""


def _make_new_xml(task_ids: list[str], extra_tasks: list[str] | None = None) -> str:
	"""Build a minimal new XML with the given task IDs (no extension attrs)."""
	tasks = ""
	for tid in task_ids:
		tasks += f'    <userTask id="{tid}" name="Task {tid}" />\n'
	for tid in (extra_tasks or []):
		tasks += f'    <scriptTask id="{tid}" name="Task {tid}" />\n'
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
{tasks}    <endEvent id="End_1" name="Done" />
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="{task_ids[0]}" />
    <sequenceFlow id="Flow_last" sourceRef="{task_ids[-1] if task_ids else 'Start_1'}" targetRef="End_1" />
  </process>
</definitions>"""


# ── Test 1: SpiffWorkflow extension attributes preserved ──────────────────────

def test_spiffworkflow_attrs_preserved():
	new_xml = _make_new_xml(["Task_A", "Task_B"], extra_tasks=[])
	# Add Task_B as scriptTask
	new_xml = new_xml.replace(
		'<userTask id="Task_B"',
		'<scriptTask id="Task_B"'
	).replace(
		'</userTask>',
		'</scriptTask>',
		1  # Only replace the second closing tag — but simpler to just use a clean new XML
	)
	# Simpler approach: build new XML manually
	new_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
    <userTask id="Task_A" name="Review" />
    <scriptTask id="Task_B" name="Notify" />
    <endEvent id="End_1" name="Done" />
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="Task_B" />
    <sequenceFlow id="Flow_3" sourceRef="Task_B" targetRef="End_1" />
  </process>
</definitions>"""

	merged, removed = transfer_properties(_OLD_XML_SPIFF, new_xml)

	assert not removed, f"No elements were removed, but got: {removed}"

	root = ET.fromstring(merged)
	task_a = root.find(f".//{{{BPMN}}}userTask[@id='Task_A']")
	assert task_a is not None, "Task_A should exist in merged XML"
	assert task_a.get(f"{{{SPIFF}}}assignmentMode") == "round_robin"
	assert task_a.get(f"{{{SPIFF}}}assignee") == "john"

	task_b = root.find(f".//{{{BPMN}}}scriptTask[@id='Task_B']")
	assert task_b is not None, "Task_B should exist in merged XML"
	assert task_b.get(f"{{{SPIFF}}}serverScript") == "send_email()"


# ── Test 2: Camunda namespace attributes preserved ────────────────────────────

def test_camunda_attrs_preserved():
	new_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
    <userTask id="Task_A" name="Review Request" />
    <endEvent id="End_1" name="Done" />
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="End_1" />
  </process>
</definitions>"""

	merged, removed = transfer_properties(_OLD_XML_CAMUNDA, new_xml)

	assert not removed, f"No elements were removed, but got: {removed}"

	root = ET.fromstring(merged)
	task_a = root.find(f".//{{{BPMN}}}userTask[@id='Task_A']")
	assert task_a is not None
	assert task_a.get(f"{{{CAMUNDA}}}assignee") == "${reviewer}"
	assert task_a.get(f"{{{CAMUNDA}}}candidateGroups") == "review_team"


# ── Test 3: Documentation elements preserved ─────────────────────────────────

def test_documentation_preserved():
	new_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
    <userTask id="Task_A" name="Review" />
    <scriptTask id="Task_B" name="Notify" />
    <endEvent id="End_1" name="Done" />
    <sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_2" sourceRef="Task_A" targetRef="Task_B" />
    <sequenceFlow id="Flow_3" sourceRef="Task_B" targetRef="End_1" />
  </process>
</definitions>"""

	merged, removed = transfer_properties(_OLD_XML_SPIFF, new_xml)

	root = ET.fromstring(merged)
	task_a = root.find(f".//{{{BPMN}}}userTask[@id='Task_A']")
	doc_a = task_a.find(f"{{{BPMN}}}documentation")
	assert doc_a is not None, "Task_A should have documentation element after merge"
	assert doc_a.text == "Reviewer checks request."

	task_b = root.find(f".//{{{BPMN}}}scriptTask[@id='Task_B']")
	doc_b = task_b.find(f"{{{BPMN}}}documentation")
	assert doc_b is not None, "Task_B should have documentation element after merge"
	assert doc_b.text == "System sends notification."


# ── Test 4: Documentation NOT overwritten if new XML already has it ───────────

def test_documentation_not_overwritten_if_existing():
	new_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
    <userTask id="Task_A" name="Review">
      <documentation>New documentation from LLM.</documentation>
    </userTask>
    <scriptTask id="Task_B" name="Notify" />
    <endEvent id="End_1" name="Done" />
  </process>
</definitions>"""

	merged, _ = transfer_properties(_OLD_XML_SPIFF, new_xml)
	root = ET.fromstring(merged)
	task_a = root.find(f".//{{{BPMN}}}userTask[@id='Task_A']")
	doc_a = task_a.find(f"{{{BPMN}}}documentation")
	assert doc_a is not None
	# Existing non-empty documentation should NOT be overwritten
	assert doc_a.text == "New documentation from LLM."


# ── Test 5: Removed elements include documentation in configs ─────────────────

def test_removed_element_reports_documentation():
	"""When an element with documentation is removed, the removal warning should
	include a preview of the documentation text."""
	new_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
    <userTask id="Task_A" name="Review" />
    <endEvent id="End_1" name="Done" />
  </process>
</definitions>"""

	# Task_B is in old but not in new — it should be reported as removed
	_, removed = transfer_properties(_OLD_XML_SPIFF, new_xml)

	assert len(removed) == 1, f"Expected 1 removed element, got: {removed}"
	assert removed[0]["id"] == "Task_B"
	configs = removed[0]["configs"]
	has_doc = any("Documentation:" in c for c in configs)
	assert has_doc, f"Removal should mention documentation, got configs: {configs}"
	has_script = any("Server Script" in c for c in configs)
	assert has_script, f"Removal should mention server script, got configs: {configs}"


# ── Test 6: extract_configured_elements captures all property types ───────────

def test_extract_configured_elements_comprehensive():
	configured = extract_configured_elements(_OLD_XML_SPIFF)

	assert "Task_A" in configured
	assert configured["Task_A"]["attrs"][f"{{{SPIFF}}}assignmentMode"] == "round_robin"
	assert configured["Task_A"]["attrs"][f"{{{SPIFF}}}assignee"] == "john"
	assert configured["Task_A"]["documentation"] == "Reviewer checks request."

	assert "Task_B" in configured
	assert configured["Task_B"]["attrs"][f"{{{SPIFF}}}serverScript"] == "send_email()"
	assert configured["Task_B"]["documentation"] == "System sends notification."


def test_extract_configured_elements_camunda():
	configured = extract_configured_elements(_OLD_XML_CAMUNDA)

	assert "Task_A" in configured
	assert configured["Task_A"]["attrs"][f"{{{CAMUNDA}}}assignee"] == "${reviewer}"
	assert configured["Task_A"]["attrs"][f"{{{CAMUNDA}}}candidateGroups"] == "review_team"
	assert configured["Task_A"]["documentation"] == "Reviewer checks the incoming request."


# ── Test 7: Smoke test — full round-trip with the user's smoke test XML ───────

_SMOKE_TEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
             xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
             xmlns:omgdc="http://www.omg.org/spec/DD/20100524/DC"
             xmlns:omgdi="http://www.omg.org/spec/DD/20100524/DI"
             xmlns:camunda="http://camunda.org/schema/1.0/bpmn"
             targetNamespace="http://www.example.org/smoke-test"
             id="Definitions_1">
  <process id="Process_SmokeTest" name="Smoke Test Process" isExecutable="true">
    <startEvent id="StartEvent_1" name="Start">
      <documentation>Process entry point.</documentation>
    </startEvent>
    <userTask id="Task_A" name="Review Request"
              camunda:assignee="${reviewer}"
              camunda:candidateGroups="review_team">
      <documentation>Reviewer checks the incoming request for completeness.</documentation>
    </userTask>
    <userTask id="Task_B" name="Process Request">
      <documentation>Handler processes the approved request.</documentation>
    </userTask>
    <exclusiveGateway id="Gateway_Open" name="Approved?" />
    <endEvent id="EndEvent_1" name="Done" />
    <sequenceFlow id="Flow_A_In"  sourceRef="StartEvent_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_A_Out" sourceRef="Task_A" targetRef="Gateway_Open" />
    <sequenceFlow id="Flow_Gateway_Yes" name="Yes" sourceRef="Gateway_Open" targetRef="Task_B">
      <conditionExpression xsi:type="tFormalExpression">${approved == true}</conditionExpression>
    </sequenceFlow>
    <sequenceFlow id="Flow_B_End" sourceRef="Task_B" targetRef="EndEvent_1" />
  </process>
</definitions>"""


_FIXED_SMOKE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="StartEvent_1" name="Start" />
    <userTask id="Task_A" name="Review Request" />
    <exclusiveGateway id="Gateway_Open" name="Approved?" />
    <userTask id="Task_B" name="Process Request" />
    <endEvent id="EndEvent_1" name="Done" />
    <sequenceFlow id="Flow_A_In"  sourceRef="StartEvent_1" targetRef="Task_A" />
    <sequenceFlow id="Flow_A_Out" sourceRef="Task_A" targetRef="Gateway_Open" />
    <sequenceFlow id="Flow_Gateway_Yes" name="Yes" sourceRef="Gateway_Open" targetRef="Task_B" />
    <sequenceFlow id="Flow_B_End" sourceRef="Task_B" targetRef="EndEvent_1" />
  </process>
</definitions>"""


def test_smoke_test_round_trip():
	"""Simulates ProsAlly fixing warnings: the 'fixed' XML drops extension attrs
	and docs, but transfer_properties should restore them all."""
	merged, removed = transfer_properties(_SMOKE_TEST_XML, _FIXED_SMOKE_XML)

	assert not removed, f"All configured elements exist in both — none removed: {removed}"

	root = ET.fromstring(merged)

	# Task_A: camunda attrs + documentation preserved
	task_a = root.find(f".//{{{BPMN}}}userTask[@id='Task_A']")
	assert task_a is not None
	assert task_a.get(f"{{{CAMUNDA}}}assignee") == "${reviewer}"
	assert task_a.get(f"{{{CAMUNDA}}}candidateGroups") == "review_team"
	doc_a = task_a.find(f"{{{BPMN}}}documentation")
	assert doc_a is not None
	assert "Reviewer checks" in doc_a.text

	# Task_B: documentation preserved
	task_b = root.find(f".//{{{BPMN}}}userTask[@id='Task_B']")
	assert task_b is not None
	doc_b = task_b.find(f"{{{BPMN}}}documentation")
	assert doc_b is not None
	assert "Handler processes" in doc_b.text

	# StartEvent_1: documentation preserved
	start = root.find(f".//{{{BPMN}}}startEvent[@id='StartEvent_1']")
	assert start is not None
	doc_start = start.find(f"{{{BPMN}}}documentation")
	assert doc_start is not None
	assert "Process entry point" in doc_start.text


# ── Test 8: Empty/malformed XML handled gracefully ────────────────────────────

def test_empty_xml_returns_gracefully():
	result, removed = transfer_properties("", "<definitions/>")
	assert result == "<definitions/>"
	assert removed == []


def test_malformed_old_xml_returns_new():
	new = "<definitions><process id='P'/></definitions>"
	result, removed = transfer_properties("<not valid xml!!!>", new)
	assert result == new
	assert removed == []


# ── Test 9: format_removal_warning includes documentation ─────────────────────

def test_format_removal_warning_with_documentation():
	removed = [{
		"id": "Task_X",
		"name": "Important Task",
		"type": "User Task",
		"configs": [
			"Assignee: john",
			"Documentation: This task is very important and must be done carefully."
		],
	}]
	warning = format_removal_warning(removed)
	assert "Important Task" in warning
	assert "Assignee: john" in warning
	assert "Documentation:" in warning


# ── Test 10: summarize_configured_elements includes documentation ─────────────

def test_summarize_includes_documentation():
	configured = {
		"Task_A": {
			"name": "My Task",
			"type": "User Task",
			"attrs": {f"{{{SPIFF}}}assignee": "john"},
			"extension_elements_xml": None,
			"documentation": "This is important documentation.",
		}
	}
	summary = summarize_configured_elements(configured)
	assert "My Task" in summary
	assert "Documentation" in summary
	assert "Assignee" in summary


# ── Test 11: ExtensionElements preserved ──────────────────────────────────────

def test_extension_elements_preserved():
	old_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <scriptTask id="Task_A" name="Automated Check">
      <extensionElements>
        <spiffworkflow:preScript>print("before")</spiffworkflow:preScript>
        <spiffworkflow:postScript>print("after")</spiffworkflow:postScript>
      </extensionElements>
    </scriptTask>
    <startEvent id="Start_1" name="Start" />
    <endEvent id="End_1" name="Done" />
  </process>
</definitions>"""

	new_xml = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://test" id="Defs">
  <process id="P1" isExecutable="true">
    <startEvent id="Start_1" name="Start" />
    <scriptTask id="Task_A" name="Automated Check" />
    <endEvent id="End_1" name="Done" />
  </process>
</definitions>"""

	merged, removed = transfer_properties(old_xml, new_xml)
	assert not removed

	root = ET.fromstring(merged)
	task_a = root.find(f".//{{{BPMN}}}scriptTask[@id='Task_A']")
	ext_el = task_a.find(f"{{{BPMN}}}extensionElements")
	assert ext_el is not None, "extensionElements should be transferred"
	children = list(ext_el)
	assert len(children) == 2, f"Expected 2 extension children, got {len(children)}"
