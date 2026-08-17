# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Can an agent DECIDE to delegate? A2A as an agent tool.

The scenario fixtures wire delegation into the map by hand: the Service
Task is on the diagram, so the delegation happens whether or not anything
intelligent wanted it to. That proves the connector works; it does not
prove the thing we actually sell — an agent that looks at a problem and
chooses to hand part of it to another agent.

This module tests that, on both surfaces where an LLM picks work:

**AI Agent Task** (``serviceType="ai_agent"`` + ``aiToolsAdhoc``). The
shapes of the referenced ad-hoc sub-process become function tools. The
LLM calls one, the shape executes INLINE inside the tool loop, and the
return value goes back to the model as the tool result.

**AI Task Selector** (``serviceType="ai_task_selector"`` on the ad-hoc
sub-process itself). The LLM does not execute anything — it picks which
child shape the engine should ACTIVATE next, and that shape runs as a
real process step.

The difference matters for A2A specifically, and it is the whole reason
this module exists. A tool shape runs against a SYNTHETIC task
(``shape_tools._synthetic_task``) that exists only for the duration of
the call; an activated shape runs against a real SpiffWorkflow task. A
fast delegation answers inside the call and neither cares. A slow one
parks the calling Service Task and waits for the reconciler to wake it —
and there is nothing to wake when the task was synthetic.

So both surfaces get both kinds of target here, on purpose:

    ask_safety_assessor  → Site Safety Assessor    fast, answers inline
    send_to_maintenance  → Maintenance Dispatcher  slow, parks on a person
    log_for_compliance   → Compliance Logger       fast, answers inline

**What the runs showed (2026-08-17, prod-backup, claude-haiku-4.5).**
Both surfaces do delegate — the model reaches a specialist agent on
merit, unprompted about which one. Each has one gap, and they are not
the same gap:

*AI Agent Task.* The model's own words reach the delegate: it wrote
"Assess the severity of flooding from a burst pipe…" and that arrived as
the A2A Task's instruction. But a SLOW target is lost. The tool runs on a
synthetic task, so ``caller_wf_task_id`` is recorded as the string
``"None"``, nothing is parked, and the tool returns the parking marker to
the model as if it were an answer. The process then COMPLETES while the
delegate is still working — it finishes, correctly, into nothing. Fast
targets are unaffected.

*AI Task Selector.* The slow target is handled properly: the chosen shape
is activated as a real process step, so it parks with a real task id, the
instance stays Active, and the reconciler resumes it when the delegate
answers. But the model cannot pass ARGUMENTS —
``tool_pool._diagram_candidates`` builds every candidate with
``parameters={}``, ignoring the shape's ``aiToolParams`` (only the Agent
Task path reads it). A connector input written as
``{{ task_data.instruction }}`` therefore renders as the literal
``{{ no such element: dict object['instruction'] }}`` and the delegate is
briefed with nonsense.

So today: use the Agent Task when the delegate answers immediately and
the brief matters; use the Selector when the delegate is slow and a fixed
brief will do. Neither covers both.

Depends on ``a2a_scenario_fixtures`` for the worker agents — run its
``execute()`` first. Unlike that module this one really does call an LLM,
so it needs working Claude credentials.

Usage::

    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.execute
    bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.execute

    bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.run_agent_task
    bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.run_task_selector
    bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.show_tool_calls

    bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.teardown
"""

import frappe

from one_bpmn.one_bpmn.a2a_scenario_fixtures import (
	ASSESSOR,
	DISPATCHER,
	LOGGER,
	_upsert_agent,
	_upsert_model,
	_upsert_script,
)
from one_bpmn.one_bpmn.a2a_test_fixtures import _HEAD, _TAIL, _di

AGENT_TASK_AGENT = "Incident Intake Agent"
SELECTOR_AGENT = "Incident Triage Selector"

ALL_AGENTS = (AGENT_TASK_AGENT, SELECTOR_AGENT)

PROVIDER = "Claude"
MODEL = "claude-haiku-4-5-20251001"

INCIDENT = "Flooding from a burst pipe in the basement plant room at Al Rai Tower; the chiller pump has stopped."

# What the agent is told. Deliberately does NOT name a tool order beyond the
# rule that assessment comes first — if the model still reaches the right
# specialist, the tools are described well enough to be chosen on merit.
SYSTEM_PROMPT = (
	"You triage facility incidents for a facilities-management company. "
	"You do not judge severity yourself and you do not do repairs: other agents "
	"do that, and you reach them with your tools.\n\n"
	"Always ask the safety assessor first — its verdict is either Critical or "
	"Routine. A Critical incident must then go to maintenance. A Routine one "
	"must be logged for compliance instead. Never do both.\n\n"
	"When you are finished, reply with one plain sentence saying what you did "
	"and what the specialists told you."
)

_TOOL_ARGS = (
	"{&#34;properties&#34;: {&#34;instruction&#34;: {&#34;type&#34;: &#34;string&#34;, "
	"&#34;description&#34;: &#34;What you want this agent to do, in plain words. "
	"Include the site and what happened.&#34;}}, &#34;required&#34;: [&#34;instruction&#34;]}"
)

TOOLS = (
	(
		"ask_safety_assessor",
		"Ask the safety assessor",
		ASSESSOR,
		"assessment",
		"Ask the site safety assessor how serious an incident is. Returns Critical or Routine.",
	),
	(
		"send_to_maintenance",
		"Send it to maintenance",
		DISPATCHER,
		"dispatch",
		"Hand a CRITICAL incident to maintenance. They assign a technician and check parts, "
		"so this one takes a while to come back.",
	),
	(
		"log_for_compliance",
		"Log it for compliance",
		LOGGER,
		"logged",
		"Record a ROUTINE incident for the compliance trail. Use this when no maintenance is needed.",
	),
)


def _tool_shape(element: str, name: str, agent: str, variable: str, description: str) -> str:
	"""One delegation, offered to the LLM as a function tool.

	``instruction`` is the LLM's own argument reaching the connector's input
	through the same Jinja render any connector field uses — which is what
	makes this a real tool rather than a fixed call the model merely triggers.
	"""
	params = (
		f"{{&#34;agent&#34;: &#34;{agent}&#34;, "
		"&#34;instruction&#34;: &#34;{{ task_data.instruction }}&#34;}"
	)
	return (
		f'      <bpmn:serviceTask id="{element}" name="{name}" '
		'spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a" '
		'spiffworkflow:operation="delegate_to_local_agent" '
		f'spiffworkflow:connectorParams="{params}" '
		f'spiffworkflow:resultVariable="{variable}" '
		f'spiffworkflow:aiToolParams="{_TOOL_ARGS}">\n'
		f"        <bpmn:documentation>{description}</bpmn:documentation>\n"
		"      </bpmn:serviceTask>\n"
	)


CLOSE_SCRIPT = "A2A Tool Test: Close Incident"

_CLOSE_INCIDENT = '''
frappe.db.set_value(context_doctype, context_docname, "status", "Closed")
result["incident_closed"] = 1
'''


def _close_shape() -> str:
	"""The selector's way of saying "done".

	An ad-hoc sub-process needs a completionCondition — SpiffWorkflow evaluates
	it every time a child completes, and a missing one raises rather than
	defaulting to "never". Tying the condition to the incident record means the
	loop ends because the selector DECIDED it was finished, which is the
	behaviour worth testing, rather than because it ran out of shapes.
	"""
	return (
		f'      <bpmn:scriptTask id="close_incident" name="Close the incident" '
		f'spiffworkflow:serverScript="{CLOSE_SCRIPT}" '
		'spiffworkflow:aiToolParams="{&#34;properties&#34;: {}, &#34;required&#34;: []}">\n'
		"        <bpmn:documentation>Close the incident. Use this once a specialist has "
		"answered and there is nothing left to hand out.</bpmn:documentation>\n"
		"      </bpmn:scriptTask>\n"
	)


def _tool_shapes(with_close: bool = False) -> str:
	shapes = "".join(_tool_shape(*tool) for tool in TOOLS)
	return shapes + _close_shape() if with_close else shapes


def _tool_di(with_close: bool = False) -> list:
	"""Coordinates for the ad-hoc container and the tools sitting inside it."""
	names = [tool[0] for tool in TOOLS] + (["close_incident"] if with_close else [])
	shapes = [("a2a_tools", 200, 320, 190 * len(names) + 40, 200)]
	for index, name in enumerate(names):
		shapes.append((name, 240 + index * 190, 370, 160, 80))
	return shapes


# ── Surface 1: the AI Agent Task ─────────────────────────────────────────────


def _agent_task_xml() -> str:
	"""One AI Agent Task whose toolbox is three delegations."""
	prompt = SYSTEM_PROMPT.replace("\n", "&#10;").replace('"', "&#34;")
	return (
		_HEAD.format(pid="a2a_tool_agent_task")
		+ '  <bpmn:process id="a2a_tool_agent_task" isExecutable="true">\n'
		+ '    <bpmn:startEvent id="start" name="Incident reported">\n'
		+ "      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		+ "    </bpmn:startEvent>\n"
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="triage" />\n'
		+ '    <bpmn:serviceTask id="triage" name="Triage the incident" '
		+ 'spiffworkflow:serviceType="ai_agent" '
		+ 'spiffworkflow:aiBackend="direct_api" '
		+ f'spiffworkflow:aiProvider="{PROVIDER}" '
		+ f'spiffworkflow:aiModel="{MODEL}" '
		+ f'spiffworkflow:aiAgentConfig="{AGENT_TASK_AGENT}" '
		+ f'spiffworkflow:aiSystemPrompt="{prompt}" '
		+ 'spiffworkflow:aiUserPrompt="{{ incident }}" '
		+ 'spiffworkflow:aiOutputVariable="triage_summary" '
		+ 'spiffworkflow:aiResponseFormat="text" '
		+ 'spiffworkflow:aiTemperature="0" '
		+ 'spiffworkflow:aiMaxTokens="1024" '
		+ 'spiffworkflow:aiTimeout="120" '
		+ 'spiffworkflow:aiMaxRetries="1" '
		+ 'spiffworkflow:aiToolsAdhoc="a2a_tools" '
		+ 'spiffworkflow:aiMaxToolCalls="6">\n'
		+ "      <bpmn:documentation>Decides which specialist agent should handle this.</bpmn:documentation>\n"
		+ "    </bpmn:serviceTask>\n"
		+ '    <bpmn:sequenceFlow id="f2" sourceRef="triage" targetRef="end" />\n'
		+ '    <bpmn:endEvent id="end" name="Triaged" />\n'
		+ '    <bpmn:adHocSubProcess id="a2a_tools" name="Delegation tools">\n'
		+ _tool_shapes()
		+ "    </bpmn:adHocSubProcess>\n"
		+ "  </bpmn:process>\n"
		+ _di(
			"a2a_tool_agent_task",
			[
				("start", 160, 180, 36, 36),
				("triage", 260, 158, 160, 80),
				("end", 480, 180, 36, 36),
			]
			+ _tool_di(),
			[("f1", "start", "triage"), ("f2", "triage", "end")],
		)
		+ _TAIL
	)


# ── Surface 2: the AI Task Selector ──────────────────────────────────────────


def _selector_xml() -> str:
	"""The same three delegations, but ACTIVATED as process steps rather than
	executed inside a tool call.

	Two things differ from the tool-loop prompt, both learned the hard way:

	1. The prompt reads the incident from ``doc``, not from a workflow
	   variable. A selector renders against the AD-HOC SUB-PROCESS's own data
	   plus {doc, instance, frappe} — the parent process's variables are not
	   in scope, and frappe's renderer leaves an unknown name as the literal
	   ``{{ incident }}``, which the model then complains about instead of
	   working. Every selector in this codebase reads ``doc`` for the same
	   reason.
	2. It tells the model in as many words that its job is to ACTIVATE one
	   named task. Given the tool-loop wording, a small model answers
	   conversationally, nothing is activated, and the sub-process stalls.
	"""
	prompt = (
		"You triage facility incidents for a facilities-management company. You do not "
		"judge severity yourself and you do not do repairs: other agents do that.\n\n"
		"At each decision you ACTIVATE exactly one task, by calling it — or none, when "
		"the work is done. You never answer conversationally and you never ask questions; "
		"activating a task IS your answer.\n\n"
		"The order is fixed:\n"
		"1. Nothing assessed yet → activate ask_safety_assessor.\n"
		"2. The verdict says Critical → activate send_to_maintenance.\n"
		"3. The verdict says Routine → activate log_for_compliance.\n"
		"4. Maintenance or compliance has already answered → activate close_incident.\n\n"
		"You have no memory between decisions. The evidence below is what has already "
		"run and what it returned — trust it over anything you think you remember."
	).replace("\n", "&#10;").replace('"', "&#34;")
	user_prompt = (
		"Incident: {{ doc.description }}&#10;&#10;"
		"Assessor verdict so far: {% if assessment %}{{ assessment }}"
		"{% else %}NOT ASSESSED YET{% endif %}&#10;"
		"Maintenance result so far: {% if dispatch %}{{ dispatch }}"
		"{% else %}not sent{% endif %}&#10;"
		"Compliance result so far: {% if logged %}{{ logged }}"
		"{% else %}not logged{% endif %}"
	)
	return (
		_HEAD.format(pid="a2a_tool_selector")
		+ '  <bpmn:process id="a2a_tool_selector" isExecutable="true">\n'
		+ '    <bpmn:startEvent id="start" name="Incident reported">\n'
		+ "      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		+ "    </bpmn:startEvent>\n"
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="a2a_tools" />\n'
		+ '    <bpmn:adHocSubProcess id="a2a_tools" name="Delegation tools" '
		+ 'cancelRemainingInstances="false" '
		+ 'spiffworkflow:serviceType="ai_task_selector" '
		+ f'spiffworkflow:aiProvider="{PROVIDER}" '
		+ f'spiffworkflow:aiModel="{MODEL}" '
		+ f'spiffworkflow:aiAgentConfig="{SELECTOR_AGENT}" '
		+ f'spiffworkflow:aiSystemPrompt="{prompt}" '
		+ f'spiffworkflow:aiUserPrompt="{user_prompt}" '
		+ 'spiffworkflow:aiToolSources="diagram" '
		+ 'spiffworkflow:aiMaxTokens="800" '
		+ 'spiffworkflow:aiTimeout="120">\n'
		+ '      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">'
		+ 'doc.status == "Closed"</bpmn:completionCondition>\n'
		+ _tool_shapes(with_close=True)
		+ "    </bpmn:adHocSubProcess>\n"
		+ '    <bpmn:sequenceFlow id="f2" sourceRef="a2a_tools" targetRef="end" />\n'
		+ '    <bpmn:endEvent id="end" name="Triaged" />\n'
		+ "  </bpmn:process>\n"
		+ _di(
			"a2a_tool_selector",
			[("start", 160, 400, 36, 36), ("end", 1060, 400, 36, 36)] + _tool_di(with_close=True),
			[("f1", "start", "a2a_tools"), ("f2", "a2a_tools", "end")],
		)
		+ _TAIL
	)


# ── Building ─────────────────────────────────────────────────────────────────


def _reserve_agent(name: str, agent_id: str) -> None:
	"""Create the configuration row before the map that names it.

	The two reference each other — the shape carries ``aiAgentConfig`` and the
	configuration carries ``process_model`` — and the compile step refuses a
	shape whose configuration does not exist yet. So the row goes in first with
	no map, and gets its map once the map compiles.
	"""
	if frappe.db.exists("AI Agent Configuration", name):
		return
	agent = frappe.new_doc("AI Agent Configuration")
	agent.agent_name = name
	agent.agent_id = agent_id
	agent.agent_type = "Background"
	agent.agent_framework = "Direct API"
	agent.enabled = 1
	agent.ai_provider_credentials = PROVIDER
	agent.ai_model = MODEL
	agent.system_prompt = SYSTEM_PROMPT
	agent.flags.ignore_permissions = True
	agent.flags.ignore_mandatory = True
	agent.flags.ignore_links = True
	agent.insert(ignore_permissions=True)
	# The deploy gate refuses a shape whose agent is still Draft, and the
	# provisioning map that would normally stamp this never runs for a fixture.
	agent.db_set("lifecycle_status", "Live", update_modified=False)


def _upsert_llm_agent(name: str, agent_id: str, model: str, description: str) -> str:
	agent = _upsert_agent(name, agent_id, model, description, exposed=False)
	# These two actually call a model, unlike every other agent in the scenario.
	frappe.db.set_value(
		"AI Agent Configuration",
		agent,
		{"ai_provider_credentials": PROVIDER, "ai_model": MODEL, "system_prompt": SYSTEM_PROMPT},
		update_modified=False,
	)
	return agent


def execute():
	if not frappe.db.exists("AI Agent Configuration", ASSESSOR):
		print("The worker agents are missing. Run this first:")
		print("  bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.execute")
		return

	_upsert_script(CLOSE_SCRIPT, _CLOSE_INCIDENT)
	_reserve_agent(AGENT_TASK_AGENT, "a2a_incident_intake_agent")
	_reserve_agent(SELECTOR_AGENT, "a2a_incident_triage_selector")

	agent_task_map = _upsert_model(AGENT_TASK_AGENT, "a2a_tool_agent_task", _agent_task_xml())
	selector_map = _upsert_model(SELECTOR_AGENT, "a2a_tool_selector", _selector_xml())

	_upsert_llm_agent(
		AGENT_TASK_AGENT,
		"a2a_incident_intake_agent",
		agent_task_map,
		"Reads an incident report and chooses which specialist agent to hand it to.",
	)
	_upsert_llm_agent(
		SELECTOR_AGENT,
		"a2a_incident_triage_selector",
		selector_map,
		"Picks which delegation step runs next for an incident.",
	)

	frappe.db.commit()
	print("A2A-as-agent-tool fixtures are ready.\n")
	print("  AI Agent Task    : " + AGENT_TASK_AGENT)
	print("  AI Task Selector : " + SELECTOR_AGENT)
	print("  tools in both    : " + ", ".join(tool[0] for tool in TOOLS))
	print("\nRun them:")
	print("  bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.run_agent_task")
	print("  bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.run_task_selector")


# ── Running ──────────────────────────────────────────────────────────────────


def _start(model_name: str, context: tuple | None = None) -> str:
	from one_bpmn.api.instance_api import start_process

	result = start_process(
		model_name=model_name,
		context_doctype=context[0] if context else None,
		context_docname=context[1] if context else None,
		initial_data=frappe.as_json({"incident": INCIDENT}),
	)
	frappe.db.commit()
	instance = result.get("instance") or result.get("name")
	print(f"Started {instance} on {model_name}")
	return instance


def _incident_record() -> tuple:
	"""The incident as a document the selector can read.

	A ToDo stands in for whatever a real site would use — an HD Ticket, a
	maintenance request. What matters is that there IS a context document:
	a selector's prompt can reach ``doc`` but not the parent process's
	workflow variables.
	"""
	todo = frappe.get_doc(
		{
			"doctype": "ToDo",
			"description": INCIDENT,
			"status": "Open",
			"allocated_to": frappe.session.user
			if frappe.session.user != "Guest"
			else "Administrator",
		}
	)
	todo.flags.ignore_permissions = True
	todo.insert(ignore_permissions=True)
	frappe.db.commit()
	return ("ToDo", todo.name)


def _wait(instance: str, seconds: int = 180) -> str:
	"""The LLM turn is parked to the bpmn_ai_agent worker, so nothing useful
	has happened when start_process returns."""
	import time

	for _ in range(seconds):
		frappe.db.rollback()  # see the worker's commits, not this connection's snapshot
		status = frappe.db.get_value("BPMN Process Instance", instance, "status")
		if status not in ("Queued", "Active"):
			print(f"  {instance} → {status}")
			return status
		time.sleep(1)
	print(f"  {instance} is still {frappe.db.get_value('BPMN Process Instance', instance, 'status')}")
	return "timeout"


def run_agent_task():
	"""Surface 1: tools executed inline inside the LLM's tool loop."""
	instance = _start(AGENT_TASK_AGENT)
	_wait(instance)
	show_tool_calls(instance)
	return instance


def run_task_selector():
	"""Surface 2: the LLM activates a shape as a real process step."""
	instance = _start(SELECTOR_AGENT, context=_incident_record())
	_wait(instance)
	show_tool_calls(instance)
	return instance


def show_tool_calls(instance: str = None):
	"""What the agent actually decided, and what the delegation did.

	Reads the A2A Task rows rather than the agent's prose: a model happy to
	say "I have escalated this to maintenance" proves nothing at all.
	"""
	filters = {"caller_instance": instance} if instance else {}
	rows = frappe.get_all(
		"A2A Task",
		filters=filters,
		fields=[
			"name",
			"agent_configuration",
			"delegated_by",
			"state",
			"caller_wf_task_id",
			"resume_enqueued",
			"status_message",
			"error_message",
		],
		order_by="creation asc",
		limit=20,
	)
	if not rows:
		print("  no delegation happened — the agent never called a tool")
		return rows

	print(f"\n  {'state':<16}{'agent':<28}{'caller task id':<22}answer")
	print("  " + "-" * 104)
	for row in rows:
		answer = row.status_message or row.error_message or ""
		print(
			f"  {row.state:<16}{row.agent_configuration[:26]:<28}"
			f"{str(row.caller_wf_task_id)[:20]:<22}{answer[:40]}"
		)

	if instance:
		summary = frappe.db.get_value("BPMN Process Instance", instance, "status")
		print(f"\n  instance {instance}: {summary}")
	return rows


def teardown():
	for name in ALL_AGENTS:
		for row in frappe.get_all("BPMN Process Instance", filters={"process_model": name}, pluck="name"):
			frappe.delete_doc(
				"BPMN Process Instance", row, force=True, ignore_permissions=True, ignore_missing=True
			)
		frappe.delete_doc(
			"AI Agent Configuration", name, force=True, ignore_permissions=True, ignore_missing=True
		)
		frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc("Process", name, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.delete_doc("Server Script", CLOSE_SCRIPT, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()
	print("Removed the A2A agent-tool fixtures.")
