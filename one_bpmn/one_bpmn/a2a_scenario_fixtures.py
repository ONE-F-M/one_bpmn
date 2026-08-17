# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A realistic same-site delegation scenario: Site Incident Response.

``a2a_test_fixtures`` proves the machinery with the smallest possible
maps — one fast worker, one slow worker. This module is the opposite end:
a chain of five agents that behaves like real facilities work, so a test
exercises the things a one-hop probe cannot.

**The story.** An incident is reported at a site. The coordinator asks a
safety specialist how serious it is, and the answer decides what happens
next — a critical incident goes to maintenance, who assign a technician
and check parts before confirming; anything routine is just logged for
compliance.

    Incident Coordinator  (the caller — never receives work)
      ├─ Site Safety Assessor          answers inline          depth 1
      ├─ Maintenance Dispatcher        parks on a person       depth 1
      │    └─ Parts Availability Checker                       depth 2
      └─ Compliance Logger             answers inline          depth 1

What this covers that the fast/slow pair does not:

- **A branch that depends on a delegate's answer.** The assessor's verdict
  is read back into workflow data and a gateway routes on it, so a wrong
  or empty result is visible as the process taking the wrong path rather
  than as a green instance that did nothing.
- **Nesting.** The dispatcher delegates onward while it is itself doing
  delegated work, so ``delegation_depth`` reaches 2 and its two tasks share
  one ``task_execution_id`` — the counters the guardrails read. (Each
  delegation the coordinator makes starts its own chain: the coordinator's
  own process was not delegated to it, so there is nothing above it to
  continue counting from.)
- **Both answer shapes in one run.** A fast worker answers inside the
  call and the caller never parks; the dispatcher parks on a user task,
  and the caller only continues once the reconciler settles it.
- **A refusal you can trigger on purpose** — see ``restrict_coordinator``.
  Note what a refused delegation leaves behind: nothing. An off-the-list
  target never became work, so there is no A2A Task to find — only the
  errored instance and the missing row say it happened. (A breached depth
  or handoff LIMIT does leave a failed task; the allow-list does not.)

Everything is deterministic and LLM-free: the maps do the work and the
verdicts come from keywords in the incident text, so the same input gives
the same route every time.

Usage::

    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.execute

    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.run_routine
    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.run_critical
    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.assign_technician
    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.show_chain

    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.restrict_coordinator
    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.unrestrict_coordinator
    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.teardown

``assign_technician`` plays the person in the middle and then reconciles,
so the whole slow path is two commands rather than a trip through the UI.

``execute()`` and ``teardown()`` are idempotent.
"""

import frappe

# The map/agent/process plumbing is identical to the minimal fixtures —
# only the story differs, so it is imported rather than copied.
from one_bpmn.one_bpmn.a2a_test_fixtures import (
	_HEAD,
	_TAIL,
	_di,
	_upsert_process,
	add_flow_refs,
)

COORDINATOR = "Incident Coordinator"
ASSESSOR = "Site Safety Assessor"
DISPATCHER = "Maintenance Dispatcher"
PARTS = "Parts Availability Checker"
LOGGER = "Compliance Logger"

ALL_AGENTS = (COORDINATOR, ASSESSOR, DISPATCHER, PARTS, LOGGER)

# ── The decision logic, as Server Scripts ────────────────────────────────────
#
# A BPMN script task runs a Server Script with the workflow's variables, the
# instance's context document as `doc`, and a `result` dict whose keys are
# merged back into workflow data for downstream gateways.
#
# A worker writes its answer onto its OWN A2A Task row (`doc` — a worker
# instance's context document IS the task that asked for the work). It writes
# `result` and `status_message` but deliberately NOT `state`: the caller sets
# the state from the instance a moment later, and a worker fighting it for the
# field would make the row's history depend on timing.

_CLASSIFY_INCIDENT = '''
payload = frappe.parse_json(doc.request_payload or "{}") or {}
report = (payload.get("instruction") or "").lower()

# Anything that can hurt someone or spread goes straight to maintenance.
severity = "Routine"
for word in (
	"fire", "smoke", "gas", "flood", "leak", "burst", "spill",
	"injury", "shock", "trapped", "collapse", "outage",
):
	if word in report:
		severity = "Critical"

answer = {
	"text": severity,
	"severity": severity,
	"assessed_by": "Site Safety Assessor",
}
frappe.db.set_value(
	"A2A Task",
	context_docname,
	{"result": frappe.as_json(answer), "status_message": severity},
	update_modified=True,
)
result["severity"] = severity
'''

_READ_WORK_ORDER = '''
# A worker starts with an empty slate: the caller's workflow variables are the
# CALLER's, and nothing copies them across. What the worker was actually asked
# to do is on its own A2A Task, so lift it into workflow data before any step
# that needs to quote it.
payload = frappe.parse_json(doc.request_payload or "{}") or {}
result["report"] = payload.get("instruction") or ""
'''

_READ_ASSESSMENT = '''
# Both answer shapes land here: a worker that replied inside the call gives
# {"a2a_task", "state", "text"}, and one the reconciler settled gives the
# worker's own result payload. `text` is the field they share.
assessment = task_data.get("assessment") or {}
severity = assessment.get("text") or assessment.get("severity") or "Routine"
if severity not in ("Critical", "Routine"):
	severity = "Routine"
result["severity"] = severity
'''

_CHECK_PARTS = '''
payload = frappe.parse_json(doc.request_payload or "{}") or {}
report = (payload.get("instruction") or "").lower()

# The store carries consumables; anything mechanical has to be ordered in.
in_stock = True
for word in ("pump", "compressor", "motor", "chiller"):
	if word in report:
		in_stock = False

availability = "in stock"
if not in_stock:
	availability = "on order"

answer = {"text": availability, "in_stock": in_stock}
frappe.db.set_value(
	"A2A Task",
	context_docname,
	{"result": frappe.as_json(answer), "status_message": availability},
	update_modified=True,
)
result["parts_available"] = availability
'''

_CONFIRM_DISPATCH = '''
parts = task_data.get("parts") or {}
availability = parts.get("text") or "unknown"

note = "Technician assigned; parts " + availability + "."
answer = {"text": note, "parts": availability, "dispatched": True}
frappe.db.set_value(
	"A2A Task",
	context_docname,
	{"result": frappe.as_json(answer), "status_message": note[:140]},
	update_modified=True,
)
result["dispatch_note"] = note
'''

_COMPLIANCE_NOTE = '''
payload = frappe.parse_json(doc.request_payload or "{}") or {}
report = payload.get("instruction") or ""

note = "Logged for compliance, no maintenance raised: " + report
answer = {"text": note, "logged": True}
frappe.db.set_value(
	"A2A Task",
	context_docname,
	{"result": frappe.as_json(answer), "status_message": note[:140]},
	update_modified=True,
)
result["compliance_note"] = note
'''

SCRIPTS = {
	"A2A Scenario: Read Work Order": _READ_WORK_ORDER,
	"A2A Scenario: Classify Incident": _CLASSIFY_INCIDENT,
	"A2A Scenario: Read Assessment": _READ_ASSESSMENT,
	"A2A Scenario: Check Parts": _CHECK_PARTS,
	"A2A Scenario: Confirm Dispatch": _CONFIRM_DISPATCH,
	"A2A Scenario: Compliance Note": _COMPLIANCE_NOTE,
}


def _upsert_script(name: str, body: str) -> str:
	"""Server Scripts must exist before any map that names them: the deploy
	gate inspects a script task's script at save time."""
	if frappe.db.exists("Server Script", name):
		doc = frappe.get_doc("Server Script", name)
		if (doc.script or "").strip() != body.strip():
			doc.script = body
			doc.save(ignore_permissions=True)
		if doc.disabled:
			doc.db_set("disabled", 0)
		return name
	doc = frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": name.lower().replace(" ", "_").replace(":", ""),
			"script": body,
			"disabled": 0,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return name


# ── The maps ─────────────────────────────────────────────────────────────────


def _a2a_start(agent_name: str) -> str:
	"""The door a delegated task comes through: a start event that fires on
	an A2A Task insert naming this agent. The condition scopes it to ONE
	agent so the workers never answer for each other."""
	return (
		'    <bpmn:startEvent id="start" name="Delegated task received">\n'
		"      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		'      <bpmn:conditionalEventDefinition id="cond_start" '
		'spiffworkflow:triggerDoctype="A2A Task" spiffworkflow:triggerType="After Insert" '
		f'spiffworkflow:triggerFieldName="agent_configuration" spiffworkflow:triggerFieldValue="{agent_name}">\n'
		f'        <bpmn:condition>agent_configuration == "{agent_name}"</bpmn:condition>\n'
		"      </bpmn:conditionalEventDefinition>\n"
		"    </bpmn:startEvent>\n"
	)


def _delegation_task(element: str, name: str, agent: str, instruction: str, variable: str) -> str:
	"""A Service Task that hands work to a named agent on this site.

	``failOnError`` is on deliberately. Without it a connector error is logged
	and the process carries on to its end event, so a delegation that never
	happened — a refused target, an agent that is not Live — still leaves a
	green instance. For incident work that is the worst outcome: the report
	looks handled and nobody was told. With it, a refusal errors the instance
	where someone will see it.
	"""
	params = (
		f"{{&#34;agent&#34;: &#34;{agent}&#34;, "
		f"&#34;instruction&#34;: &#34;{instruction}&#34;}}"
	)
	return (
		f'    <bpmn:serviceTask id="{element}" name="{name}" '
		'spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a" '
		'spiffworkflow:operation="delegate_to_local_agent" '
		f'spiffworkflow:connectorParams="{params}" '
		f'spiffworkflow:resultVariable="{variable}" '
		'spiffworkflow:failOnError="true">\n'
		f"      <bpmn:documentation>Hands this to {agent} and waits for the answer.</bpmn:documentation>\n"
		"    </bpmn:serviceTask>\n"
	)


def _script_step(element: str, name: str, script: str, documentation: str) -> str:
	return (
		f'    <bpmn:scriptTask id="{element}" name="{name}" '
		f'spiffworkflow:serverScript="{script}">\n'
		f"      <bpmn:documentation>{documentation}</bpmn:documentation>\n"
		"    </bpmn:scriptTask>\n"
	)


def _flow(element: str, source: str, target: str, name: str = "", condition: str = "") -> str:
	label = f' name="{name}"' if name else ""
	if not condition:
		return f'    <bpmn:sequenceFlow id="{element}"{label} sourceRef="{source}" targetRef="{target}" />\n'
	return (
		f'    <bpmn:sequenceFlow id="{element}"{label} sourceRef="{source}" targetRef="{target}">\n'
		f'      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">{condition}</bpmn:conditionExpression>\n'
		"    </bpmn:sequenceFlow>\n"
	)


def _coordinator_xml() -> str:
	"""Ask the assessor, then route on what it said."""
	return (
		_HEAD.format(pid="a2a_incident_coordinator")
		+ '  <bpmn:process id="a2a_incident_coordinator" isExecutable="true">\n'
		+ '    <bpmn:startEvent id="start" name="Incident reported">\n'
		+ "      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		+ "    </bpmn:startEvent>\n"
		+ _flow("f1", "start", "ask_assessor")
		+ _delegation_task(
			"ask_assessor",
			"Ask the safety assessor",
			ASSESSOR,
			"Assess this incident at {{ task_data.site }}: {{ task_data.report }}",
			"assessment",
		)
		+ _flow("f2", "ask_assessor", "read_assessment")
		+ _script_step(
			"read_assessment",
			"Read the assessment",
			"A2A Scenario: Read Assessment",
			"Pulls the verdict out of the delegate's answer so the gateway can route on it.",
		)
		+ _flow("f3", "read_assessment", "gw_severity")
		+ '    <bpmn:exclusiveGateway id="gw_severity" name="How serious is it?" default="f5">\n'
		+ "      <bpmn:incoming>f3</bpmn:incoming>\n"
		+ "      <bpmn:outgoing>f4</bpmn:outgoing>\n"
		+ "      <bpmn:outgoing>f5</bpmn:outgoing>\n"
		+ "    </bpmn:exclusiveGateway>\n"
		+ _flow("f4", "gw_severity", "to_maintenance", "Critical", 'severity == "Critical"')
		+ _flow("f5", "gw_severity", "to_compliance", "Routine")
		+ _delegation_task(
			"to_maintenance",
			"Send it to maintenance",
			DISPATCHER,
			"Critical incident at {{ task_data.site }}: {{ task_data.report }}",
			"dispatch",
		)
		+ _flow("f6", "to_maintenance", "end_critical")
		+ _delegation_task(
			"to_compliance",
			"Log it for compliance",
			LOGGER,
			"Routine incident at {{ task_data.site }}: {{ task_data.report }}",
			"logged",
		)
		+ _flow("f7", "to_compliance", "end_routine")
		+ '    <bpmn:endEvent id="end_critical" name="Maintenance handled it" />\n'
		+ '    <bpmn:endEvent id="end_routine" name="Logged only" />\n'
		+ "  </bpmn:process>\n"
		+ _di(
			"a2a_incident_coordinator",
			[
				("start", 160, 260, 36, 36),
				("ask_assessor", 250, 238, 140, 80),
				("read_assessment", 440, 238, 140, 80),
				("gw_severity", 630, 253, 50, 50),
				("to_maintenance", 740, 128, 140, 80),
				("to_compliance", 740, 348, 140, 80),
				("end_critical", 940, 150, 36, 36),
				("end_routine", 940, 370, 36, 36),
			],
			[
				("f1", "start", "ask_assessor"),
				("f2", "ask_assessor", "read_assessment"),
				("f3", "read_assessment", "gw_severity"),
				("f4", "gw_severity", "to_maintenance"),
				("f5", "gw_severity", "to_compliance"),
				("f6", "to_maintenance", "end_critical"),
				("f7", "to_compliance", "end_routine"),
			],
		)
		+ _TAIL
	)


def _single_step_worker_xml(process_id: str, agent_name: str, step_name: str, script: str, documentation: str) -> str:
	"""A worker that answers inside the caller's call: one script task, done."""
	return (
		_HEAD.format(pid=process_id)
		+ f'  <bpmn:process id="{process_id}" isExecutable="true">\n'
		+ _a2a_start(agent_name)
		+ _flow("f1", "start", "work")
		+ _script_step("work", step_name, script, documentation)
		+ _flow("f2", "work", "end")
		+ '    <bpmn:endEvent id="end" name="Answered" />\n'
		+ "  </bpmn:process>\n"
		+ _di(
			process_id,
			[("start", 160, 180, 36, 36), ("work", 260, 158, 160, 80), ("end", 480, 180, 36, 36)],
			[("f1", "start", "work"), ("f2", "work", "end")],
		)
		+ _TAIL
	)


def _dispatcher_xml() -> str:
	"""The slow worker, and the only one that delegates onward: a person
	assigns the technician, then parts are checked at depth 2."""
	return (
		_HEAD.format(pid="a2a_maintenance_dispatcher")
		+ '  <bpmn:process id="a2a_maintenance_dispatcher" isExecutable="true">\n'
		+ _a2a_start(DISPATCHER)
		+ _flow("f1", "start", "read_order")
		+ _script_step(
			"read_order",
			"Read the work order",
			"A2A Scenario: Read Work Order",
			"Lifts the incident text off this agent's own task into workflow data.",
		)
		+ _flow("f2", "read_order", "assign")
		+ '    <bpmn:userTask id="assign" name="Assign a technician">\n'
		+ "      <bpmn:documentation>Complete this to let the delegation continue. "
		+ "While it is open the caller is parked, which is the state the reconciler settles."
		+ "</bpmn:documentation>\n"
		+ "    </bpmn:userTask>\n"
		+ _flow("f3", "assign", "check_parts")
		+ _delegation_task(
			"check_parts",
			"Check parts availability",
			PARTS,
			"Parts needed for: {{ task_data.report }}",
			"parts",
		)
		+ _flow("f4", "check_parts", "confirm")
		+ _script_step(
			"confirm",
			"Confirm the dispatch",
			"A2A Scenario: Confirm Dispatch",
			"Writes the answer the coordinator is waiting for.",
		)
		+ _flow("f5", "confirm", "end")
		+ '    <bpmn:endEvent id="end" name="Dispatched" />\n'
		+ "  </bpmn:process>\n"
		+ _di(
			"a2a_maintenance_dispatcher",
			[
				("start", 160, 180, 36, 36),
				("read_order", 250, 158, 140, 80),
				("assign", 440, 158, 140, 80),
				("check_parts", 630, 158, 140, 80),
				("confirm", 820, 158, 140, 80),
				("end", 1020, 180, 36, 36),
			],
			[
				("f1", "start", "read_order"),
				("f2", "read_order", "assign"),
				("f3", "assign", "check_parts"),
				("f4", "check_parts", "confirm"),
				("f5", "confirm", "end"),
			],
		)
		+ _TAIL
	)


# ── Building the site ────────────────────────────────────────────────────────


def _upsert_model(name: str, process_id: str, xml: str) -> str:
	if frappe.db.exists("BPMN Process Model", name):
		model = frappe.get_doc("BPMN Process Model", name)
	else:
		model = frappe.new_doc("BPMN Process Model")
		model.title = name
	model.process_id = process_id
	model.process_name = _upsert_process(name)
	model.version = model.version or 1
	model.bpmn_xml = add_flow_refs(xml)
	model.flags.ignore_permissions = True
	model.flags.ignore_mandatory = True
	model.save(ignore_permissions=True)

	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(model.name)
	return model.name


def _upsert_agent(
	name: str,
	agent_id: str,
	model: str,
	description: str,
	*,
	exposed: bool,
	tags: str = "",
	deadline_minutes: int = 0,
) -> str:
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
	agent.description = description
	agent.system_prompt = "Scenario fixture. This agent's map does the work; no model is called."
	if deadline_minutes:
		agent.delegation_deadline_minutes = deadline_minutes
	agent.flags.ignore_permissions = True
	agent.flags.ignore_mandatory = True
	agent.flags.ignore_links = True
	agent.save(ignore_permissions=True)
	# Live is normally stamped by the provisioning map; these fixtures never run
	# it, and delegation requires Live.
	agent.db_set("lifecycle_status", "Live", update_modified=False)
	return agent.name


def execute():
	for name, body in SCRIPTS.items():
		_upsert_script(name, body)

	assessor_map = _upsert_model(
		ASSESSOR,
		"a2a_safety_assessor",
		_single_step_worker_xml(
			"a2a_safety_assessor",
			ASSESSOR,
			"Classify the incident",
			"A2A Scenario: Classify Incident",
			"Reads the report and returns Critical or Routine.",
		),
	)
	parts_map = _upsert_model(
		PARTS,
		"a2a_parts_checker",
		_single_step_worker_xml(
			"a2a_parts_checker",
			PARTS,
			"Check the store",
			"A2A Scenario: Check Parts",
			"Says whether the parts are in stock or have to be ordered.",
		),
	)
	logger_map = _upsert_model(
		LOGGER,
		"a2a_compliance_logger",
		_single_step_worker_xml(
			"a2a_compliance_logger",
			LOGGER,
			"Write the compliance note",
			"A2A Scenario: Compliance Note",
			"Records a routine incident with no maintenance raised.",
		),
	)
	dispatcher_map = _upsert_model(DISPATCHER, "a2a_maintenance_dispatcher", _dispatcher_xml())
	coordinator_map = _upsert_model(COORDINATOR, "a2a_incident_coordinator", _coordinator_xml())

	_upsert_agent(
		ASSESSOR,
		"a2a_site_safety_assessor",
		assessor_map,
		"Judges how serious a reported site incident is, and returns Critical or Routine.",
		exposed=True,
		tags="safety, assessment, triage",
	)
	_upsert_agent(
		PARTS,
		"a2a_parts_checker",
		parts_map,
		"Reports whether the parts a repair needs are in stock or on order.",
		exposed=True,
		tags="inventory, parts",
	)
	_upsert_agent(
		LOGGER,
		"a2a_compliance_logger",
		logger_map,
		"Records incidents that need no maintenance, for the compliance trail.",
		exposed=True,
		tags="compliance, records",
	)
	_upsert_agent(
		DISPATCHER,
		"a2a_maintenance_dispatcher",
		dispatcher_map,
		"Assigns a technician to a critical incident and confirms parts before dispatch.",
		exposed=True,
		tags="maintenance, dispatch",
		# Shorter than the 240-minute backstop, so a step that names no deadline
		# still gets this agent's own answer to "how long do I need".
		deadline_minutes=60,
	)
	_upsert_agent(
		COORDINATOR,
		"a2a_incident_coordinator",
		coordinator_map,
		"Takes an incident report and decides who handles it.",
		# The caller is not exposed: it delegates, it never receives.
		exposed=False,
	)

	frappe.db.commit()
	print("Site Incident Response scenario is ready.\n")
	print("  agents : " + "\n           ".join(ALL_AGENTS))
	print("  maps   : one Process each — open /processa to see them\n")
	print("Run the CRITICAL path (parks on a person, nests to depth 2):")
	print("  bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.run_critical")
	print("\nRun the ROUTINE path (answers inline, never parks):")
	print("  bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.run_routine")
	print("\nThen inspect the delegation chain:")
	print("  bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.show_chain")


# ── Running a scenario ───────────────────────────────────────────────────────

CRITICAL_REPORT = "Flooding from a burst pipe in the basement plant room; the chiller pump has stopped."
ROUTINE_REPORT = "A ceiling tile in the third floor corridor is stained and needs replacing."


def _start(site: str, report: str) -> str:
	from one_bpmn.api.instance_api import start_process

	result = start_process(
		model_name=COORDINATOR,
		initial_data=frappe.as_json({"site": site, "report": report}),
	)
	frappe.db.commit()
	instance = result.get("instance") or result.get("name")
	print(f"Started {instance}")
	print(f"  site   : {site}")
	print(f"  report : {report}")
	return instance


def run_critical():
	"""The long path: assessor says Critical, maintenance parks on a person.

	The coordinator will be waiting when this returns — that is the point.
	Complete the dispatcher's user task, then run the reconciler.
	"""
	instance = _start("Al Rai Tower", CRITICAL_REPORT)
	print("\nThe coordinator is now parked waiting on maintenance.")
	print("Next:")
	print("  1. complete 'Assign a technician' on the dispatcher's instance")
	print("  2. bench execute one_bpmn.tasks.poll_a2a_tasks")
	print("  3. bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.show_chain")
	return instance


def run_routine():
	"""The short path: assessor says Routine, the logger answers inline and
	the whole thing finishes inside the one call."""
	instance = _start("Al Rai Tower", ROUTINE_REPORT)
	print("\nThis path parks nowhere — check it finished:")
	print("  bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.show_chain")
	return instance


def assign_technician():
	"""Play the person in the middle: complete the dispatcher's open user
	task, then run the reconciler so the parked coordinator wakes up.

	This is the step a human does in the UI. Doing it here keeps the slow
	path to one command when you only care about the delegation machinery.
	"""
	from one_bpmn.api.instance_api import complete_task, get_instance_tasks

	rows = frappe.get_all(
		"BPMN Process Instance",
		filters={"process_model": DISPATCHER, "status": ("in", ("Queued", "Active"))},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	if not rows:
		print(f"No {DISPATCHER} instance is waiting. Run run_critical() first.")
		return None

	instance = rows[0]
	active = (get_instance_tasks(instance) or {}).get("active_tasks") or []
	if not active:
		print(f"{instance} has no open task to complete.")
		return None

	task = active[0]
	print(f"Completing '{task.get('task_name')}' on {instance}")
	complete_task(instance, task.get("task_id"), frappe.as_json({"technician": "Ahmad K."}))
	frappe.db.commit()

	# The dispatcher's answer is ready, but the CALLER is still parked: it only
	# moves when the reconciler notices the delegated task went terminal.
	#
	# Parking sets next_poll_at 15 seconds out, and the reconciler only looks at
	# rows that are due — so a poll run this instant would skip everything and
	# look like a bug. The scheduler would simply have waited; pulling the due
	# time back does the same thing without the wait.
	from frappe.utils import now_datetime

	from one_bpmn.tasks import poll_a2a_tasks

	pending = frappe.get_all(
		"A2A Task",
		filters={"direction": "Internal", "resume_enqueued": 0, "caller_wf_task_id": ("is", "set")},
		pluck="name",
	)
	for row in pending:
		frappe.db.set_value("A2A Task", row, "next_poll_at", now_datetime(), update_modified=False)
	frappe.db.commit()

	poll_a2a_tasks()
	frappe.db.commit()

	# The resume itself is a job on the bpmn_ai_agent queue, so the caller wakes
	# a moment later — wait for it rather than printing a half-finished chain.
	_wait_for_coordinator()
	print("\nReconciler run. The coordinator should have resumed:")
	show_chain()
	return instance


def _wait_for_coordinator(seconds: int = 30) -> None:
	"""Give the bpmn_ai_agent worker time to run the resume job."""
	import time

	for _ in range(seconds):
		frappe.db.rollback()  # drop this connection's snapshot so we see the worker's commit
		waiting = frappe.get_all(
			"BPMN Process Instance",
			filters={"process_model": COORDINATOR, "status": ("in", ("Queued", "Active"))},
			limit=1,
			pluck="name",
		)
		if not waiting:
			return
		time.sleep(1)
	print("The coordinator is still running — re-run show_chain() in a moment.")


def show_chain():
	"""Print every delegation this scenario has made, newest first.

	A green process does NOT prove a delegation worked — a connector error
	is swallowed unless the step sets failOnError — so this row is the thing
	worth reading.
	"""
	rows = frappe.get_all(
		"A2A Task",
		filters={"agent_configuration": ("in", ALL_AGENTS)},
		fields=[
			"name",
			"agent_configuration",
			"delegated_by",
			"state",
			"delegation_depth",
			"handoff_count",
			"task_execution_id",
			"status_message",
			"error_message",
			"creation",
		],
		order_by="creation desc",
		limit=40,
	)
	if not rows:
		print("No delegations yet.")
		return rows

	print(f"{'depth':<6}{'state':<16}{'delegated by':<26}{'agent':<28}answer")
	print("-" * 118)
	for row in rows:
		answer = row.status_message or row.error_message or ""
		print(
			f"{row.delegation_depth or 0:<6}{row.state:<16}"
			f"{(row.delegated_by or '—')[:24]:<26}{row.agent_configuration[:26]:<28}{answer[:44]}"
		)
	chains = {row.task_execution_id for row in rows if row.task_execution_id}
	print(f"\n{len(rows)} task(s) across {len(chains) or 1} execution chain(s).")
	return rows


# ── The refusal scenario ─────────────────────────────────────────────────────


def restrict_coordinator():
	"""Narrow the coordinator to safety + compliance only, so a critical
	incident is refused when it tries to reach maintenance.

	Exposure is what grants delegation; this list only narrows it. Run
	``run_critical`` afterwards and the delegation fails with a plain reason
	instead of dispatching.
	"""
	agent = frappe.get_doc("AI Agent Configuration", COORDINATOR)
	agent.restrict_delegates = 1
	agent.set("allowed_delegates", [])
	for target in (ASSESSOR, LOGGER):
		agent.append("allowed_delegates", {"agent_configuration": target})
	agent.flags.ignore_permissions = True
	agent.flags.ignore_mandatory = True
	agent.flags.ignore_links = True
	agent.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"{COORDINATOR} may now delegate only to: {ASSESSOR}, {LOGGER}.")
	print("Run run_critical() — reaching maintenance is now refused.")


def unrestrict_coordinator():
	"""Put the coordinator back to delegating anywhere that is exposed."""
	agent = frappe.get_doc("AI Agent Configuration", COORDINATOR)
	agent.restrict_delegates = 0
	agent.set("allowed_delegates", [])
	agent.flags.ignore_permissions = True
	agent.flags.ignore_mandatory = True
	agent.flags.ignore_links = True
	agent.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"{COORDINATOR} may delegate to any exposed agent again.")


# ── Cleanup ──────────────────────────────────────────────────────────────────


def teardown():
	for name in ALL_AGENTS:
		for row in frappe.get_all("A2A Task", filters={"agent_configuration": name}, pluck="name"):
			frappe.delete_doc("A2A Task", row, force=True, ignore_permissions=True, ignore_missing=True)
		for row in frappe.get_all("BPMN Process Instance", filters={"process_model": name}, pluck="name"):
			frappe.delete_doc(
				"BPMN Process Instance", row, force=True, ignore_permissions=True, ignore_missing=True
			)
		frappe.delete_doc(
			"AI Agent Configuration", name, force=True, ignore_permissions=True, ignore_missing=True
		)
		frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc("Process", name, force=True, ignore_permissions=True, ignore_missing=True)
	for name in SCRIPTS:
		frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()
	print("Removed the Site Incident Response scenario.")
