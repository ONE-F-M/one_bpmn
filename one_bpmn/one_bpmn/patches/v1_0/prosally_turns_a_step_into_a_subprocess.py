"""ProsAlly turns an existing step into an expanded sub-process, adds a new one, keeps call activities, and checks the result.

Edits the Classify Intent and Modify Process scripts, the IR schema skill and three sub-prompts in place, then adds two
baseline eval cases. Text already carrying the change is skipped, and text whose anchors are not each found exactly once
is logged and left as it is.
"""

import json

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits, with_edits

AGENT_ID = "prosally_agent"
SUITE_TITLE = "Prosally - Baseline"

CLASSIFY_IMPORT = (
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, join_confirmation, resolve_scope, ",
	"from one_bpmn.agents.prosally_helpers import asks_to_make_call_activity, complete_sub_prompt, find_missing_target, "
	"join_confirmation, resolve_scope, resolve_step, unapplied_proposal, ",
)
CLASSIFY_CONVERT = (
	'    scope = resolve_scope(current_xml, _scope_texts, turn.get("scope_id", ""))\n',
	'    scope = resolve_scope(current_xml, _scope_texts, turn.get("scope_id", ""))\n'
	"    convert = resolve_step(current_xml, _scope_texts)\n"
	"    wants_call = asks_to_make_call_activity(message)\n"
	"    ghost = unapplied_proposal(context_docname, current_xml, message)\n"
	'    named_ghost = ghost if (ghost and ghost["named"]) else None\n'
	"    missing = None if (scope or convert) else find_missing_target(current_xml, _scope_texts)\n"
	'    near = missing if (missing and missing["candidates"]) else None\n'
	'    fresh = missing if (missing and not missing["candidates"]) else None\n'
	"    if near:\n"
	'        _closest = ", ".join([c["name"] + " (" + c["kind"] + ")" for c in near["candidates"]])\n',
)
CLASSIFY_HINT = (
	'    if scope:\n        _parts.append("The diagram already has the sub-process',
	r'''    if convert:
        _parts.append("The diagram already has the step \"" + convert["name"] + "\" and this request turns it into a sub-process holding the steps described. Classify it as MODIFY_EXISTING and describe it as turning that step into a sub-process, never as drawing or redrawing the process.")
    if near:
        _parts.append("The diagram has no step or sub-process called \"" + near["asked"] + "\". The closest are: " + _closest + ". Classify it as AMBIGUOUS and ask which one the person meant, never confirm a step that is not on the diagram.")
    if fresh:
        _parts.append("The diagram has no step or sub-process called \"" + fresh["asked"] + "\", so this asks for a NEW sub-process holding the steps described. Classify it as MODIFY_EXISTING and describe it as adding a new sub-process called that name, never as redrawing the process.")
    if ghost and not ghost["named"]:
        _parts.append("The previous reply proposed these additions, but they are NOT on the diagram because the person discarded the change or has not applied it: " + ", ".join(ghost["added"]) + ". Treat them as not done.")
    if scope and not convert:
        _parts.append("The diagram already has the sub-process''',
)
CLASSIFY_GUARD = (
	'    if scope and intent in _GENERATE_INTENTS:\n        intent = "MODIFY_EXISTING"\n',
	'    if (scope or convert or fresh) and intent in _GENERATE_INTENTS:\n'
	'        intent = "MODIFY_EXISTING"\n'
	"    if wants_call and intent in _ACTION_INTENTS:\n"
	'        intent = "AMBIGUOUS"\n'
	'        reason = "The request asks for a call activity, which runs a separate process that ProsAlly cannot create."\n'
	"    if named_ghost and intent in _ACTION_INTENTS:\n"
	'        intent = "AMBIGUOUS"\n'
	'        reason = "\\"" + named_ghost["named"][0] + "\\" is not on the diagram: the change that added it was discarded or has not been applied."\n'
	"    if near and intent in _ACTION_INTENTS:\n"
	'        intent = "AMBIGUOUS"\n'
	'        reason = "There is no step or sub-process called \\"" + near["asked"] + "\\" on the diagram. The closest are: " + _closest + "."\n',
)
CLASSIFY_REPLY = (
	'    elif intent in _NEEDS_CLARIFICATION:\n        result["next"] = "clarify"\n',
	r'''    elif intent in _NEEDS_CLARIFICATION:
        result["next"] = "clarify"
        if wants_call:
            _reply = "I can't turn a sub-process or a step into a call activity: a call activity runs a separate process, and I can't create one. I can keep it as a sub-process, or add a call activity that calls a process that already exists. Tell me which process it should call and where it goes."
            update_turn(context_docname, output={"intent": "CLARIFY", "action_intent": None, "response": _reply, "options": []}, done=True)
            result["next"] = "finalize"
        elif named_ghost:
            _reply = "\"" + named_ghost["named"][0] + "\" is not on the diagram: the change that added it was discarded or has not been applied. Want me to add it first?"
            _again = [named_ghost["request"]] if named_ghost["request"] else []
            update_turn(context_docname, output={"intent": "CLARIFY", "action_intent": None, "response": _reply, "options": _again}, done=True)
            result["next"] = "finalize"
        elif near:
            _lines ="\n".join(["- " + c["name"] + " (" + c["kind"] + ")" for c in near["candidates"]])
            _reply = "I can't find a step or sub-process called \"" + near["asked"] + "\" on the " + (process_name or "current") + " diagram. These are the closest:\n" + _lines + "\n\nPick one to resend your request with that name, or tell me it is a new sub-process to add."
            _fixed = [near["text"].replace(near["asked"], c["name"], 1) for c in near["candidates"][:2]]
            update_turn(context_docname, output={"intent": "CLARIFY", "action_intent": None, "response": _reply, "options": _fixed}, done=True)
            result["next"] = "finalize"
''',
)

MODIFY_IMPORT = (
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, resolve_scope, splice_subprocess, ",
	"from one_bpmn.agents.prosally_helpers import complete_sub_prompt, convert_step_to_subprocess, find_missing_target, "
	"resolve_scope, resolve_step, restore_call_activities, splice_subprocess, unapplied_proposal, ",
)
MODIFY_CONVERT = (
	'scope = resolve_scope(current_xml, _scope_texts, turn.get("scope_id", ""))\n',
	'scope = resolve_scope(current_xml, _scope_texts, turn.get("scope_id", ""))\n'
	"convert = resolve_step(current_xml, _scope_texts)\n"
	"if convert:\n"
	"    scope = None\n"
	"missing = None if (scope or convert) else find_missing_target(current_xml, _scope_texts)\n"
	'ghost = unapplied_proposal(context_docname, current_xml, turn.get("user_text", ""))\n',
)
MODIFY_PROMPT = (
	'        "Output the complete IR JSON for the inside of the sub-process now.",\n    ])\n',
	r'''        "Output the complete IR JSON for the inside of the sub-process now.",
    ])
if convert:
    initial_prompt = "\n\n".join([
        "Action: MODIFY_EXISTING - turn the step \"" + convert["name"] + "\" (id " + convert["id"] + ") into a sub-process that holds the steps described.",
        "Output the IR JSON for the steps INSIDE the new sub-process and nothing else: its own startEvent, its steps and flows, and its endEvent. Do NOT output the step itself, the rest of the process, or lanes. Flows join only steps inside it.",
        "Modification request from conversation:\n" + _hist,
        "Latest message: " + turn.get("user_text", ""),
        "Output the complete IR JSON for the steps inside the new sub-process now.",
    ])
''',
)
MODIFY_NEW_SUBPROCESS = (
	'_system = stage_system_prompt(_cfg, "modifier", "modify_skills")\n',
	r'''if missing and not missing["candidates"]:
    initial_prompt = initial_prompt + "\n\nThe diagram has no step or sub-process called \"" + missing["asked"] + "\", so add a NEW sub-process: one subProcess node named exactly that, with \"expanded\": true and the steps described in \"children\" (its own startEvent, steps, flows and endEvent), placed where it fits in the main flow. Keep every other node, flow and id exactly as in the current diagram."
if ghost:
    initial_prompt = initial_prompt + "\n\nThese elements from an earlier proposal are NOT on the diagram, so do not assume they exist: " + ", ".join(ghost["added"]) + "."
_system = stage_system_prompt(_cfg, "modifier", "modify_skills")
''',
)
MODIFY_MERGE = (
	"    if scope and best_xml:\n"
	'        best_xml = splice_subprocess(current_xml, best_xml, scope["id"])\n'
	"    merged_xml, removed_elements = transfer_properties(current_xml, best_xml)\n",
	"    if scope and best_xml:\n"
	'        best_xml = splice_subprocess(current_xml, best_xml, scope["id"])\n'
	"    if convert and best_xml:\n"
	'        best_xml = convert_step_to_subprocess(current_xml, convert["id"], best_xml)\n'
	'    merged_xml, removed_elements = transfer_properties(current_xml, best_xml, skip_ids=((convert["id"],) if convert else ()))\n'
	"    if current_xml.strip() and merged_xml.strip():\n"
	"        merged_xml = restore_call_activities(current_xml, merged_xml)\n"
	"        _merged = validate_bpmn_xml(merged_xml)\n"
	'        if not _merged.get("valid"):\n'
	'            problems = _merged.get("violations") or []\n'
	'            note = " (" + str(len(problems)) + " issue(s) remain - review the canvas.)" + topology_note\n',
)
MODIFY_WHERE = (
	'        _where = ("sub-process \\"" + scope["name"] + "\\"") if scope else (xml_name + " process")\n',
	'        _where = ("sub-process \\"" + scope["name"] + "\\"") if scope else (xml_name + " process")\n'
	"        if convert:\n"
	'            _where = "step \\"" + convert["name"] + "\\", which is now a sub-process"\n',
)

SKILL_SECTION = (
	"## The IR / element schema\n",
	"## Sub-processes and call activities\n"
	'A subProcess holds its own steps in `children`: `{"nodes": [...], "flows": [...]}`, with their own startEvent and endEvent. '
	"Flows inside `children` join only the steps inside it, and a flow outside never names a step inside it. "
	'Add `"expanded": true` to draw the steps inside the box on the same canvas. '
	"When asked to turn one existing step into a sub-process, the step becomes the sub-process: it keeps its id and name, "
	"and the steps described go inside it.\n"
	"A callActivity runs another process. Keep its `calledElement` exactly and never turn a callActivity into a subProcess or any other type.\n\n"
	"## The IR / element schema\n",
)

CLASSIFIER_RULE = (
	"- CRITICAL: When the user asks to change the type or representation of elements that already exist on the diagram",
	'- CRITICAL: When the user asks for a sub-process for one step that already exists on the diagram, for example "Create a sub process '
	'for <step name>: ...", ALWAYS classify as MODIFY_EXISTING and write the confirmation as turning that step into a sub-process, '
	"never as drawing or redrawing the process.\n"
	"- CRITICAL: When the user asks to change the type or representation of elements that already exist on the diagram",
)
CLASSIFIER_EXAMPLE = (
	'  - MODIFY_EXISTING: "I\'ll update [the specific part] of the [process name] process..."\n',
	'  - MODIFY_EXISTING: "I\'ll update [the specific part] of the [process name] process..."\n'
	'  - MODIFY_EXISTING for a step turned into a sub-process: "I\'ll turn the step [step name] into a sub-process..."\n',
)
MODIFIER_TYPES = (
	"exclusiveGateway | parallelGateway | subProcess",
	"exclusiveGateway | parallelGateway | subProcess | callActivity",
)
MODIFIER_MAPPING = (
	"  bpmn:subProcess        → type: subProcess",
	'  bpmn:subProcess        → type: subProcess (its steps go in "children": {"nodes": [...], "flows": [...]}, with "expanded": true to draw them inside the box)\n'
	'  bpmn:callActivity      → type: callActivity (keep "calledElement" exactly; never change a call activity into another type)',
)

SCRIPTS = {
	"ProsAlly%Tool Classify Intent": (CLASSIFY_IMPORT, CLASSIFY_CONVERT, CLASSIFY_HINT, CLASSIFY_GUARD, CLASSIFY_REPLY),
	"ProsAlly%Tool Modify Process": (
		MODIFY_IMPORT,
		MODIFY_CONVERT,
		MODIFY_PROMPT,
		MODIFY_NEW_SUBPROCESS,
		MODIFY_MERGE,
		MODIFY_WHERE,
	),
}
# sub-prompt id -> (edits, marker of an applied change)
PROMPTS = {
	"intent_classifier": ((CLASSIFIER_RULE, CLASSIFIER_EXAMPLE), "sub-process for one step"),
	"modifier": ((MODIFIER_TYPES, MODIFIER_MAPPING), "bpmn:callActivity"),
	"process_generator": ((MODIFIER_TYPES,), "| subProcess | callActivity"),
}
SKILL = "bpmn-modelling-rules-and-ir-schema"

STEP_ID = "task_complete_payroll_clearance"
CALL_ID = "task_call_closure"


def execute():
	for pattern, edits in SCRIPTS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			apply_edits("Server Script", name, "script", edits, "find_missing_target(")
	if frappe.db.exists("AI Skill", SKILL):
		apply_edits("AI Skill", SKILL, "body", (SKILL_SECTION,), "## Sub-processes and call activities")
	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if config:
		for sub_agent_id, (edits, marker) in PROMPTS.items():
			edit_prompt(config, sub_agent_id, edits, marker)
		add_eval_cases()


def edit_prompt(config: str, sub_agent_id: str, edits: tuple, marker: str) -> None:
	"""Apply edits to one sub-prompt of the agent, unless marker is already in it."""
	row = frappe.db.get_value(
		"AI Agent Sub Prompt", {"parent": config, "sub_agent_id": sub_agent_id}, ["name", "prompt_text"]
	)
	if not row or marker in (row[1] or ""):
		return
	edited = with_edits(row[1] or "", edits)
	if edited is None:
		frappe.log_error(
			title="prosally_turns_a_step_into_a_subprocess: anchors not found",
			message=f"The {sub_agent_id} sub-prompt does not carry each anchor exactly once; it is left as it is.",
		)
		return
	frappe.db.set_value("AI Agent Sub Prompt", row[0], "prompt_text", edited)


def fixture_xml() -> str:
	"""A saved diagram with the step to convert, a call activity after it, and the drawing of both."""
	shapes = "".join(
		f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}"><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}"/></bpmndi:BPMNShape>'
		for i, x, y, w, h in (
			("start", 100, 100, 36, 36),
			(STEP_ID, 190, 78, 100, 80),
			(CALL_ID, 340, 78, 100, 80),
			("end", 490, 100, 36, 36),
		)
	)
	edges = "".join(
		f'<bpmndi:BPMNEdge id="{f}_di" bpmnElement="{f}"><di:waypoint x="{a}" y="118"/><di:waypoint x="{b}" y="118"/></bpmndi:BPMNEdge>'
		for f, a, b in (("f1", 136, 190), ("f2", 290, 340), ("f3", 440, 490))
	)
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
		'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">'
		'<bpmn:process id="Process_1" name="Employee Offboarding" isExecutable="true">'
		'<bpmn:startEvent id="start" name="Resignation accepted"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>'
		f'<bpmn:userTask id="{STEP_ID}" name="Complete Payroll Clearance">'
		"<bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing></bpmn:userTask>"
		f'<bpmn:callActivity id="{CALL_ID}" name="Call Closure" calledElement="Process_Closure">'
		"<bpmn:incoming>f2</bpmn:incoming><bpmn:outgoing>f3</bpmn:outgoing></bpmn:callActivity>"
		'<bpmn:endEvent id="end" name="Offboarding closed"><bpmn:incoming>f3</bpmn:incoming></bpmn:endEvent>'
		f'<bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="{STEP_ID}"/>'
		f'<bpmn:sequenceFlow id="f2" sourceRef="{STEP_ID}" targetRef="{CALL_ID}"/>'
		f'<bpmn:sequenceFlow id="f3" sourceRef="{CALL_ID}" targetRef="end"/>'
		"</bpmn:process>"
		f'<bpmndi:BPMNDiagram id="D1"><bpmndi:BPMNPlane id="P1" bpmnElement="Process_1">{shapes}{edges}</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>'
		"</bpmn:definitions>"
	)


def artifact_assertion(expected: str) -> dict:
	"""An assertion that the modify_process artifact's bpmn_xml matches the regex expected."""
	spec = {"tool": "modify_process", "path": "bpmn_xml", "matcher": "regex", "expected": expected}
	return {"assertion_type": "tool_artifact", "value": json.dumps(spec)}


def eval_cases() -> list:
	"""The two cases: the confirmation says the step is updated, and confirming expands that step in place."""
	request = (
		"Create a sub process for Complete Payroll Clearance: Payroll Operator checks pending salary, "
		"if there is any enters the amount, otherwise marks it not applicable, then submits"
	)
	context = {"current_xml": fixture_xml(), "process_name": "Employee Offboarding"}
	return [
		{
			"title": "A request for a sub-process on an existing step is confirmed as an update, not a redraw",
			"input_user_prompt": request,
			"input_context": json.dumps(context),
			"assertions": [
				{"assertion_type": "contains", "value": "Complete Payroll Clearance"},
				{"assertion_type": "regex", "value": "(?i)sub-?process"},
				{
					"assertion_type": "regex",
					"value": "(?i)^(?![\\s\\S]*(redraw|from scratch|draw the [A-Za-z ]+ process))[\\s\\S]*$",
				},
			],
			"expected_tool_calls": [{"call_order": 1, "tool_name": "classify_intent", "matcher": "equals"}],
		},
		{
			"title": "Confirming it expands that step in place and leaves the call activity as it was",
			"input_user_prompt": request,
			"input_context": json.dumps({**context, "confirmed_action": "MODIFY_EXISTING"}),
			"assertions": [
				{"assertion_type": "tool_calls", "value": "IN_ORDER"},
				artifact_assertion(f'<bpmn:subProcess id=\\"{STEP_ID}\\"'),
				artifact_assertion('isExpanded=\\"true\\"'),
				artifact_assertion(f'<bpmn:callActivity id=\\"{CALL_ID}\\"[^>]*calledElement=\\"Process_Closure\\"'),
			],
			"expected_tool_calls": [
				{"call_order": 1, "tool_name": "classify_intent", "matcher": "equals"},
				{"call_order": 2, "tool_name": "modify_process", "matcher": "equals"},
			],
		},
	]


def add_eval_cases() -> None:
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not suite:
		return
	for case in eval_cases():
		if frappe.db.exists("AI Eval Case", {"suite": suite, "title": case["title"]}):
			continue
		frappe.get_doc({"doctype": "AI Eval Case", "suite": suite, "case_type": "Trajectory", **case}).insert(
			ignore_permissions=True
		)
