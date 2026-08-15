# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Ready-made maps and agents for testing A2A delegation by hand.

Three maps and three agents, deliberately LLM-free so a test proves the
delegation machinery rather than a model's mood:

- **A2A Test Worker (Fast)** — a map that starts on an A2A Task and ends
  immediately. Answers inside the call, so the caller never parks.
- **A2A Test Worker (Slow)** — the same, with a user task in the middle.
  The caller parks; completing that task lets the reconciler wake it.
- **A2A Test Orchestrator** — the caller. Its map has one Service Task
  using the a2a connector, targeting whichever worker you name when you
  start it.

Run ``execute()`` to create or refresh them, ``teardown()`` to remove
them. Both are idempotent.
"""

import frappe

ORCHESTRATOR = "A2A Test Orchestrator"
WORKER_FAST = "A2A Test Worker (Fast)"
WORKER_SLOW = "A2A Test Worker (Slow)"

_HEAD = (
	'<?xml version="1.0" encoding="UTF-8"?>\n'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
	'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
	'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
	'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
	'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
	'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" '
	'id="Definitions_{pid}" targetNamespace="http://bpmn.io/schema/bpmn">\n'
)
_TAIL = "</bpmn:definitions>\n"


def _di(process_id: str, shapes: list, edges: list) -> str:
	"""The diagram interchange section — coordinates for every element.

	Without this the map is still valid and still runs, but bpmn-js has
	nothing to draw and the canvas opens blank.

	shapes: (id, x, y, width, height). edges: (id, source_id, target_id).
	"""
	box = {s[0]: s[1:] for s in shapes}
	out = [
		f'  <bpmndi:BPMNDiagram id="BPMNDiagram_{process_id}">',
		f'    <bpmndi:BPMNPlane id="BPMNPlane_{process_id}" bpmnElement="{process_id}">',
	]
	for element, x, y, w, h in shapes:
		out.append(f'      <bpmndi:BPMNShape id="{element}_di" bpmnElement="{element}">')
		out.append(f'        <dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" />')
		out.append("      </bpmndi:BPMNShape>")
	for element, source, target in edges:
		sx, sy, sw, sh = box[source]
		tx, ty, tw, th = box[target]
		out.append(
			f'      <bpmndi:BPMNEdge id="{element}_di" bpmnElement="{element}">'
		)
		out.append(f'        <di:waypoint x="{sx + sw}" y="{sy + sh // 2}" />')
		out.append(f'        <di:waypoint x="{tx}" y="{ty + th // 2}" />')
		out.append("      </bpmndi:BPMNEdge>")
	out += ["    </bpmndi:BPMNPlane>", "  </bpmndi:BPMNDiagram>", ""]
	return "\n".join(out)


def _worker_xml(process_id: str, agent_name: str, with_user_task: bool) -> str:
	"""A map an inbound A2A task starts. The condition scopes it to ONE agent,
	so the two workers never answer for each other."""
	steps = (
		'    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="review" />\n'
		'    <bpmn:userTask id="review" name="Review the delegated work">\n'
		"      <bpmn:documentation>Complete this task to let the delegation finish.</bpmn:documentation>\n"
		"    </bpmn:userTask>\n"
		'    <bpmn:sequenceFlow id="f2" sourceRef="review" targetRef="end" />\n'
		if with_user_task
		else '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="end" />\n'
	)
	return (
		_HEAD.format(pid=process_id)
		+ f'  <bpmn:process id="{process_id}" isExecutable="true">\n'
		+ '    <bpmn:startEvent id="start" name="Delegated task received">\n'
		+ '      <bpmn:outgoing>f1</bpmn:outgoing>\n'
		+ '      <bpmn:conditionalEventDefinition id="cond_start" '
		+ 'spiffworkflow:triggerDoctype="A2A Task" spiffworkflow:triggerType="After Insert" '
		+ f'spiffworkflow:triggerFieldName="agent_configuration" spiffworkflow:triggerFieldValue="{agent_name}">\n'
		+ f'        <bpmn:condition>agent_configuration == "{agent_name}"</bpmn:condition>\n'
		+ "      </bpmn:conditionalEventDefinition>\n"
		+ "    </bpmn:startEvent>\n"
		+ steps
		+ '    <bpmn:endEvent id="end" name="Done" />\n'
		+ "  </bpmn:process>\n"
		+ (
			_di(
				process_id,
				[("start", 160, 180, 36, 36), ("review", 260, 158, 120, 80), ("end", 440, 180, 36, 36)],
				[("f1", "start", "review"), ("f2", "review", "end")],
			)
			if with_user_task
			else _di(
				process_id,
				[("start", 160, 180, 36, 36), ("end", 300, 180, 36, 36)],
				[("f1", "start", "end")],
			)
		)
		+ _TAIL
	)


def _caller_xml() -> str:
	"""One Service Task that hands work to whichever agent you name in
	initial_data, so the same map drives the fast and slow scenarios."""
	params = (
		"{&#34;agent&#34;: &#34;{{ task_data.target_agent }}&#34;, "
		"&#34;instruction&#34;: &#34;{{ task_data.instruction }}&#34;}"
	)
	return (
		_HEAD.format(pid="a2a_test_caller")
		+ '  <bpmn:process id="a2a_test_caller" isExecutable="true">\n'
		+ '    <bpmn:startEvent id="start" name="Start test">\n'
		+ "      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		+ "    </bpmn:startEvent>\n"
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="delegate" />\n'
		+ '    <bpmn:serviceTask id="delegate" name="Delegate to an agent on this site" '
		+ 'spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a" '
		+ 'spiffworkflow:operation="delegate_to_local_agent" '
		+ f'spiffworkflow:connectorParams="{params}" '
		+ 'spiffworkflow:resultVariable="delegate_result">\n'
		+ "      <bpmn:documentation>Hands the instruction to the named local agent.</bpmn:documentation>\n"
		+ "    </bpmn:serviceTask>\n"
		+ '    <bpmn:sequenceFlow id="f2" sourceRef="delegate" targetRef="end" />\n'
		+ '    <bpmn:endEvent id="end" name="Delegation finished" />\n'
		+ "  </bpmn:process>\n"
		+ _di(
			"a2a_test_caller",
			[("start", 160, 180, 36, 36), ("delegate", 260, 158, 140, 80), ("end", 460, 180, 36, 36)],
			[("f1", "start", "delegate"), ("f2", "delegate", "end")],
		)
		+ _TAIL
	)


def _upsert_process(name: str) -> str:
	"""Processa lists maps THROUGH their Process record, so a map with no
	process_name is invisible in the UI even though it runs perfectly well.

	One Process EACH, not one shared: deploying a map deactivates every
	sibling under the same Process (that is how versions work), so grouping
	the three would leave only the last one compiled active.
	"""
	if frappe.db.exists("Process", name):
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Process",
			"process_name": name,
			"description": "Maps for testing agent-to-agent delegation by hand. Safe to delete.",
			"process_owner": frappe.session.user if frappe.session.user != "Guest" else "Administrator",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _upsert_model(name: str, process_id: str, xml: str) -> str:
	"""Named by its title, and linked to the fixtures' Process so it shows up
	in Processa."""
	if frappe.db.exists("BPMN Process Model", name):
		model = frappe.get_doc("BPMN Process Model", name)
	else:
		model = frappe.new_doc("BPMN Process Model")
		model.title = name
	model.process_id = process_id
	model.process_name = _upsert_process(name)
	model.version = model.version or 1
	model.bpmn_xml = xml
	model.flags.ignore_permissions = True
	model.flags.ignore_mandatory = True
	model.save(ignore_permissions=True)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(model.name)
	return model.name


def _upsert_agent(name: str, agent_id: str, model: str, exposed: bool, tags: str = "") -> str:
	if frappe.db.exists("AI Agent Configuration", name):
		agent = frappe.get_doc("AI Agent Configuration", name)
	else:
		agent = frappe.new_doc("AI Agent Configuration")
		agent.agent_name = name
	agent.agent_id = agent_id
	agent.agent_type = "Background"
	agent.agent_framework = "Direct API"
	agent.enabled = 1
	agent.process_model = model
	agent.a2a_exposed = 1 if exposed else 0
	agent.a2a_skill_tags = tags
	agent.description = "Fixture for testing A2A delegation by hand."
	agent.system_prompt = "Test fixture. This agent's map does the work; no model is called."
	agent.flags.ignore_permissions = True
	agent.flags.ignore_mandatory = True
	agent.flags.ignore_links = True
	agent.save(ignore_permissions=True)
	# Live is normally stamped by the provisioning map; these fixtures never
	# run it, and delegation requires Live.
	agent.db_set("lifecycle_status", "Live", update_modified=False)
	return agent.name


def execute():
	fast_map = _upsert_model(
		WORKER_FAST, "a2a_worker_fast", _worker_xml("a2a_worker_fast", WORKER_FAST, False)
	)
	slow_map = _upsert_model(
		WORKER_SLOW, "a2a_worker_slow", _worker_xml("a2a_worker_slow", WORKER_SLOW, True)
	)
	caller_map = _upsert_model(ORCHESTRATOR, "a2a_test_caller", _caller_xml())

	_upsert_agent(WORKER_FAST, "a2a_test_worker_fast", fast_map, exposed=True, tags="test, fast")
	_upsert_agent(WORKER_SLOW, "a2a_test_worker_slow", slow_map, exposed=True, tags="test, slow")
	_upsert_agent(ORCHESTRATOR, "a2a_test_orchestrator", caller_map, exposed=False)

	frappe.db.commit()
	print("Created / refreshed:")
	print(f"  maps   : {fast_map} | {slow_map} | {caller_map}")
	print("  each map has its own Process of the same name — open /processa to see them")
	print(f"  agents : {WORKER_FAST} | {WORKER_SLOW} | {ORCHESTRATOR}")
	print("\nRun the FAST scenario:")
	print(
		"  bench execute one_bpmn.api.instance_api.start_process --kwargs "
		f"'{{\"model_name\": \"{ORCHESTRATOR}\", \"initial_data\": "
		f'"{{\\"target_agent\\": \\"{WORKER_FAST}\\", \\"instruction\\": \\"say hello\\"}}"}}\''
	)
	print("\nRun the SLOW scenario: same command with target_agent = " + WORKER_SLOW)


def teardown():
	for name in (WORKER_FAST, WORKER_SLOW, ORCHESTRATOR):
		for row in frappe.get_all("A2A Task", filters={"agent_configuration": name}, pluck="name"):
			frappe.delete_doc("A2A Task", row, force=True, ignore_permissions=True, ignore_missing=True)
		for row in frappe.get_all("BPMN Process Instance", filters={"process_model": name}, pluck="name"):
			frappe.delete_doc(
				"BPMN Process Instance", row, force=True, ignore_permissions=True, ignore_missing=True
			)
		frappe.delete_doc(
			"AI Agent Configuration", name, force=True, ignore_permissions=True, ignore_missing=True
		)
		frappe.delete_doc(
			"BPMN Process Model", name, force=True, ignore_permissions=True, ignore_missing=True
		)
		frappe.delete_doc("Process", name, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()
	print("Removed the A2A test fixtures.")
