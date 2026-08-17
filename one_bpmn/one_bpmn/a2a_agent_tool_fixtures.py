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
fast delegation answers inside the call and neither cares. A slow one has
nothing to park on the tool path, so that path suspends the AGENT instead
and resumes it through its checkpoint — the same pause a human tool
produces, with another agent supplying the answer instead of a person.

So both surfaces get both kinds of target here, on purpose:

    ask_safety_assessor  → Site Safety Assessor    fast, answers inline
    send_to_maintenance  → Maintenance Dispatcher  slow, parks on a person
    log_for_compliance   → Compliance Logger       fast, answers inline

**Verified on both surfaces (2026-08-17, prod-backup, claude-haiku-4.5).**
The model reaches a specialist agent on merit, unprompted about which
one; it writes its own brief; and a slow delegate parks the caller until
the answer arrives. On the Agent Task the final answer read:

    "I assessed the flooding and stopped chiller pump at Al Rai Tower as
     Critical, and maintenance has assigned a technician and ordered parts."

— which the agent could only know after a person assigned the technician,
so it genuinely waited and was woken.

Both surfaces were broken when this module was written, in different
places, and each is now fixed:

*AI Agent Task* lost any SLOW delegate. Tool shapes run on a synthetic
task, so nothing was parked, and the connector's waiting marker was
handed back to the model as though it were the answer; the process
completed while the other agent was still working. Now a parked
delegation raises ``ToolDeferred``, the loop suspends on it exactly as it
does for a human tool, and the reconciler feeds the answer back through
the agent's checkpoint.

*AI Task Selector* could not pass ARGUMENTS: every candidate was built
with ``parameters={}``, so the model could say which step to run but not
what to run it on, and ``{{ task_data.instruction }}`` reached the
delegate as an unresolved placeholder. Compilation now embeds the same
tool descriptors for selectors as for Agent Tasks, so the argument schema
is there to read. Visible in the outcome: the assessor answers "Critical"
for the flooding incident where an empty brief had it answering
"Routine".

**Open issue (selector, 2026-08-17).** Triggering, grounding and both
delegations work: the Issue insert starts the process, the assessor
answers "Critical" from the document, maintenance parks and is reconciled
back with "Technician assigned; parts on order." But the ad-hoc decision
loop then stops asking — ``close_incident`` never runs, so the Issue stays
Open and the instance stays Active. No error is logged and no flag is
stuck (``engine_in_progress`` 0, ``waiting_for_ai`` 0); re-entering
``run_parked_ai_task(kind="adhoc_decision")`` by hand does not advance it
either, which points at the gate finding no promotable head rather than a
lost job. A manually started run of the same map DID complete earlier, so
the trigger is not the cause. Concrete lead: in the activity log the
assessor has both "Ad-Hoc Task Activated" and "Completed" while
maintenance has only "Completed" — the second activation skipped the hook
that the loop's re-entry depends on.

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

# ── What raises an incident ──────────────────────────────────────────────────
#
# Both maps start when an Issue of their own type is created. Issue was picked
# over the alternatives after checking what it actually costs to create one on
# this bench:
#
#   ToDo       — 2 fields (description + allocated_to). Cheapest to create, but
#                UNSAFE to trigger on: Frappe creates a ToDo for every
#                assignment, including the ones these agents' own human steps
#                create, so an After Insert trigger would feed itself.
#   HD Ticket  — cannot be created at all here: it sends an acknowledgement
#                email on insert and throws without a default outgoing account.
#   Issue      — 2 fields (subject + issue_type), and issue_type gives a clean
#                scope so only records deliberately marked as ours start a
#                process. Same friction as ToDo, none of the feedback loop.
#
# One type per map, so each can be exercised on its own — creating one Issue
# must not start both processes.
ISSUE_TYPE_AGENT = "Facilities Incident (Agent)"
ISSUE_TYPE_SELECTOR = "Facilities Incident (Selector)"

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

# (tool id, target agent, result variable, description shown to the LLM).
#
# The shape's DISPLAY name is derived from the target agent rather than the
# action, because an A2A hop has two ends and a reader of the diagram needs to
# see both: the AI Agent Task is the agent initiating, and each tool names the
# agent receiving. Naming these "Ask the safety assessor" hid half of that
# behind the properties panel.
TOOLS = (
	(
		"ask_safety_assessor",
		ASSESSOR,
		"assessment",
		"Ask the site safety assessor how serious an incident is. Returns Critical or Routine.",
	),
	(
		"send_to_maintenance",
		DISPATCHER,
		"dispatch",
		"Hand a CRITICAL incident to maintenance. They assign a technician and check parts, "
		"so this one takes a while to come back.",
	),
	(
		"log_for_compliance",
		LOGGER,
		"logged",
		"Record a ROUTINE incident for the compliance trail. Use this when no maintenance is needed.",
	),
)


def _incident_start(issue_type: str) -> str:
	"""A start event that fires when an Issue of THIS type is created.

	Scoped by issue_type on purpose. The universal trigger is registered on
	every DocType, so an unscoped Issue trigger would start this process for
	every issue anyone raises on the site.
	"""
	return (
		'    <bpmn:startEvent id="start" name="Incident reported">\n'
		"      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		'      <bpmn:conditionalEventDefinition id="cond_start" '
		'spiffworkflow:triggerDoctype="Issue" spiffworkflow:triggerType="After Insert" '
		f'spiffworkflow:triggerFieldName="issue_type" spiffworkflow:triggerFieldValue="{issue_type}">\n'
		f'        <bpmn:condition>issue_type == "{issue_type}"</bpmn:condition>\n'
		"      </bpmn:conditionalEventDefinition>\n"
		"    </bpmn:startEvent>\n"
	)


def _tool_shape(element: str, agent: str, variable: str, description: str) -> str:
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
		f'      <bpmn:serviceTask id="{element}" name="A2A → {agent}" '
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
		+ _incident_start(ISSUE_TYPE_AGENT)
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="triage" />\n'
		+ '    <bpmn:serviceTask id="triage" name="Triage the incident" '
		+ 'spiffworkflow:serviceType="ai_agent" '
		+ 'spiffworkflow:aiBackend="direct_api" '
		+ f'spiffworkflow:aiProvider="{PROVIDER}" '
		+ f'spiffworkflow:aiModel="{MODEL}" '
		+ f'spiffworkflow:aiAgentConfig="{AGENT_TASK_AGENT}" '
		+ f'spiffworkflow:aiSystemPrompt="{prompt}" '
		# The incident record IS the trigger, so the brief comes off the
		# document. It used to read {{ incident }} from initial_data, which does
		# not exist on a triggered run — the model would have received the
		# literal placeholder.
		+ 'spiffworkflow:aiUserPrompt="Incident raised: {{ doc.subject }}&#10;&#10;{{ doc.description }}" '
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
		+ '    <bpmn:adHocSubProcess id="a2a_tools" name="Delegation tools (A2A)">\n'
		+ "      <bpmn:documentation>The agents this one may hand work to. Referenced by the "
		+ "AI Agent Task as its toolbox, so it is not wired into the sequence flow: the model "
		+ "calls these, the engine does not run them in order.</bpmn:documentation>\n"
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
			expanded={"a2a_tools"},
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
		"At every decision you ACTIVATE EXACTLY ONE task by calling it. Activating a "
		"task IS your answer — you never reply conversationally, never explain your "
		"reasoning instead of acting, and never ask questions.\n\n"
		"Work down this list and activate the FIRST rule that matches:\n"
		"1. Assessor verdict is NOT ASSESSED YET → activate ask_safety_assessor.\n"
		"2. Verdict is Critical and maintenance is 'not sent' → activate "
		"send_to_maintenance.\n"
		"3. Verdict is Routine and compliance is 'not logged' → activate "
		"log_for_compliance.\n"
		"4. Otherwise — one of them has answered — activate close_incident.\n\n"
		"Rule 4 is not optional and it is not a formality. An incident stays open until "
		"close_incident runs, so if you activate nothing the work you just arranged is "
		"never signed off and this incident hangs unresolved. Deciding that the job is "
		"done is precisely when you MUST activate close_incident.\n\n"
		"Only ONE of maintenance and compliance ever runs, and rule 4 does not care "
		"which: seeing maintenance answered is a reason to close, never a reason to "
		"stop.\n\n"
		"You have no memory between decisions. The evidence below is what has already "
		"run and what it returned — trust it over anything you think you remember.\n\n"
		"Call the task FIRST, before any explanation. Do not restate the evidence, do "
		"not tick items off, do not summarise what has happened: a decision that spends "
		"its words describing the situation runs out of room before it acts, and an "
		"unspoken decision does nothing at all. One short sentence at most."
	).replace("\n", "&#10;").replace('"', "&#34;")
	user_prompt = (
		"Incident: {{ doc.subject }} — {{ doc.description }}&#10;&#10;"
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
		+ _incident_start(ISSUE_TYPE_SELECTOR)
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="a2a_tools" />\n'
		+ '    <bpmn:adHocSubProcess id="a2a_tools" name="Delegation tools (A2A)" '
		+ 'cancelRemainingInstances="false" '
		+ 'spiffworkflow:serviceType="ai_task_selector" '
		+ f'spiffworkflow:aiProvider="{PROVIDER}" '
		+ f'spiffworkflow:aiModel="{MODEL}" '
		+ f'spiffworkflow:aiAgentConfig="{SELECTOR_AGENT}" '
		+ f'spiffworkflow:aiSystemPrompt="{prompt}" '
		+ f'spiffworkflow:aiUserPrompt="{user_prompt}" '
		+ 'spiffworkflow:aiToolSources="diagram" '
		# 800 was not enough: the model narrated its reasoning, hit the ceiling
		# mid-sentence, and the truncated reply carried no tool call — so the
		# decision activated nothing and the sub-process stalled with no error.
		+ 'spiffworkflow:aiMaxTokens="2000" '
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
			expanded={"a2a_tools"},
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

	_upsert_issue_type(ISSUE_TYPE_AGENT)
	_upsert_issue_type(ISSUE_TYPE_SELECTOR)
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
	print("\nBoth start when an Issue of their own type is created:")
	print(f"  {ISSUE_TYPE_AGENT}")
	print(f"  {ISSUE_TYPE_SELECTOR}")
	print("\nRun them:")
	print("  bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.run_agent_task")
	print("  bench execute one_bpmn.one_bpmn.a2a_agent_tool_fixtures.run_task_selector")


# ── Running ──────────────────────────────────────────────────────────────────


def _upsert_issue_type(name: str) -> str:
	if not frappe.db.exists("Issue Type", name):
		doc = frappe.get_doc({"doctype": "Issue Type", "name": name})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	return name


def raise_incident(issue_type: str) -> str:
	"""Report an incident, the way a person would.

	Creating the record IS the start — the map's conditional start event fires
	on the insert. Nothing here calls start_process, which is the point: this
	exercises the trigger, not a hand-built instance.
	"""
	issue = frappe.get_doc(
		{
			"doctype": "Issue",
			"subject": "Flooding in the basement plant room, Al Rai Tower",
			"description": INCIDENT,
			"issue_type": issue_type,
			"status": "Open",
		}
	)
	issue.flags.ignore_permissions = True
	issue.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"Raised {issue.name} ({issue_type})")
	return issue.name


def _instance_for(issue: str, seconds: int = 30) -> str | None:
	"""The instance the trigger started for this incident, once it appears."""
	import time

	for _ in range(seconds):
		frappe.db.rollback()
		rows = frappe.get_all(
			"BPMN Process Instance",
			filters={"context_doctype": "Issue", "context_docname": issue},
			order_by="creation desc",
			limit=1,
			pluck="name",
		)
		if rows:
			return rows[0]
		time.sleep(1)
	print(f"  no process started for {issue} — is the map deployed and the agent Live?")
	return None


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
	issue = raise_incident(ISSUE_TYPE_AGENT)
	instance = _instance_for(issue)
	if not instance:
		return None
	_wait(instance)
	show_tool_calls(instance)
	return instance


def run_task_selector():
	"""Surface 2: the LLM activates a shape as a real process step."""
	issue = raise_incident(ISSUE_TYPE_SELECTOR)
	instance = _instance_for(issue)
	if not instance:
		return None
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

	print(f"\n  {'state':<16}{'delegated by':<26}{'handled by':<28}{'caller task id':<22}answer")
	print("  " + "-" * 126)
	for row in rows:
		answer = row.status_message or row.error_message or ""
		print(
			f"  {row.state:<16}{(row.delegated_by or '—')[:24]:<26}"
			f"{row.agent_configuration[:26]:<28}"
			f"{str(row.caller_wf_task_id)[:20]:<22}{answer[:36]}"
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
	for issue_type in (ISSUE_TYPE_AGENT, ISSUE_TYPE_SELECTOR):
		for issue in frappe.get_all("Issue", filters={"issue_type": issue_type}, pluck="name"):
			frappe.delete_doc("Issue", issue, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc(
			"Issue Type", issue_type, force=True, ignore_permissions=True, ignore_missing=True
		)
	frappe.db.commit()
	print("Removed the A2A agent-tool fixtures.")
