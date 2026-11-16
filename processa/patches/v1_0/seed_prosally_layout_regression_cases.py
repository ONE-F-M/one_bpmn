"""Seeds three layout-instruction cases into ProsAlly Regressions, each expecting RELAYOUT and no drawing tool.

Idempotent by suite and case title.
"""

import json

import frappe

AGENT_ID = "prosally_agent"
SUITE_TITLE_LIKE = "%Regressions%"

# A laned diagram, so the classifier sees a model to lay out rather than a request to draw one.
CURRENT_XML = (
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="d">'
	'<bpmn:collaboration id="c"><bpmn:participant id="pool" processRef="p" /></bpmn:collaboration>'
	'<bpmn:process id="p" isExecutable="false"><bpmn:laneSet id="ls"><bpmn:lane id="lane_hr" name="HR">'
	"<bpmn:flowNodeRef>s</bpmn:flowNodeRef><bpmn:flowNodeRef>t</bpmn:flowNodeRef><bpmn:flowNodeRef>e</bpmn:flowNodeRef>"
	'</bpmn:lane></bpmn:laneSet><bpmn:startEvent id="s" name="Request raised" /><bpmn:task id="t" name="Review" />'
	'<bpmn:endEvent id="e" name="Cancelled" /><bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t" />'
	'<bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e" /></bpmn:process></bpmn:definitions>'
)

PROMPTS = (
	("A connection correction is a relayout", "in cancelled correct the connection"),
	("Label placement is a relayout", "Put names above the line it should not be crossed by the line"),
	(
		"A layout-only routing request is a relayout",
		'Clean up the visual routing of the three Cancel edges into the "Cancelled" gateway. This is a '
		"layout-only change. Do not alter any source, target or condition.",
	),
)

ASSERTIONS = [
	{"assertion_type": "regex", "value": r'(?i)"intent"\s*:\s*"RELAYOUT"'},
	{"assertion_type": "no_tool_call", "value": "modify_process, generate_process"},
]
TRACE = [{"call_order": 1, "tool_name": "classify_intent"}]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "title": ["like", SUITE_TITLE_LIKE]}, "name"
	)
	if not suite:
		return
	for title, prompt in PROMPTS:
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.suite = suite
		case.title = title
		case.case_type = "Trajectory"
		case.process_model = process_model
		case.input_user_prompt = prompt
		case.input_context = json.dumps({"current_xml": CURRENT_XML})
		case.set("assertions", ASSERTIONS)
		case.set("expected_tool_calls", TRACE)
		if existing:
			case.save(ignore_permissions=True)  # patch: seeded eval case
		else:
			case.insert(ignore_permissions=True)  # patch: seeded eval case
