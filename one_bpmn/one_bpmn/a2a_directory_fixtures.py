# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Can an agent FIND who to delegate to? The agent directory as a tool.

``a2a_agent_tool_fixtures`` proves an agent will choose to delegate — but
its toolbox names the targets: one shape per specialist, each with the
agent baked into ``connectorParams``. The model picks a box; the diagram
already decided who is behind it. Adding a specialist means editing the
map of every agent that might want it.

This map has no specialist in it at all. The toolbox is two generic
tools:

    find_specialists       list_delegatable_agents  — who is available
    delegate_to_specialist delegate_to_local_agent  — hand work to one

The first returns exactly what a person sees on the A2A page: each
agent's card — name, what it is for, its tags. The model reads that,
picks one, and passes the ``agent`` value straight back as an argument to
the second. So the roster is data at run time, not shapes at design time,
and exposing a new agent on the A2A page is enough to put it in front of
every agent that can delegate.

The scoping matters as much as the listing: the directory is filtered by
the same guardrail that would refuse the delegation
(``guardrails.may_delegate_to``), so an agent can never read about a
specialist it is not allowed to reach. Tick Restrict Delegation on the
router and the directory shrinks with it — same map, smaller world.

The specialists come from ``a2a_scenario_fixtures`` (assessor, parts
checker, compliance logger, maintenance dispatcher — all exposed, all
carrying descriptions and tags because that is what the model reads).
Run that module's ``execute()`` first. This one calls a real model, so it
needs working Claude credentials.

Usage::

    bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.execute
    bench execute one_bpmn.one_bpmn.a2a_directory_fixtures.execute

    bench execute one_bpmn.one_bpmn.a2a_directory_fixtures.run
    bench execute one_bpmn.one_bpmn.a2a_directory_fixtures.show_directory
    bench execute one_bpmn.one_bpmn.a2a_directory_fixtures.teardown
"""

import frappe

from one_bpmn.one_bpmn.a2a_agent_tool_fixtures import (
	_instance_for,
	_upsert_issue_type,
	_wait,
	show_tool_calls,
)
from one_bpmn.one_bpmn.a2a_scenario_fixtures import (
	ASSESSOR,
	_script_step,
	_upsert_model,
	_upsert_script,
)
from one_bpmn.one_bpmn.a2a_test_fixtures import _HEAD, _TAIL, _di

ROUTER_AGENT = "Incident Router (Directory)"
ROUTER_ID = "a2a_incident_router_directory"

ALL_AGENTS = (ROUTER_AGENT,)

PROVIDER = "Claude"
MODEL = "claude-haiku-4-5-20251001"

ISSUE_TYPE = "Facilities Incident (Directory)"

INCIDENT = (
	"Flooding from a burst pipe in the basement plant room at Al Rai Tower; "
	"the chiller pump has stopped."
)

# The prompt names NO agent. It cannot: the whole point is that the router
# does not know who exists until it asks. It is told the shape of the job
# (assess first, then act on the verdict) and that the roster is something to
# look up — the same brief a new coordinator would get on their first day.
SYSTEM_PROMPT = (
	"You route facility incidents for a facilities-management company. You do not "
	"judge severity yourself and you do not do repairs — other agents do that.\n\n"
	"You do not know in advance which agents exist. Start by calling "
	"find_specialists to see who is available and what each one is for, then use "
	"delegate_to_specialist, passing the 'agent' value exactly as the directory "
	"gave it to you.\n\n"
	"Get the incident assessed first — the verdict comes back as Critical or "
	"Routine. A Critical incident then goes to whichever agent handles repairs "
	"and technicians. A Routine one goes to whichever agent keeps the compliance "
	"record instead. Never both.\n\n"
	"Choose from what the directory tells you. If nobody suitable is listed, say "
	"so rather than inventing an agent name.\n\n"
	"Once that second specialist has answered you are done — signing the incident "
	"off is not your job and happens on its own.\n\n"
	"Finish with one plain sentence: who you picked, why, and what they said."
)

# The delegate tool's arguments. `agent` is the interesting one — it is the
# value the model copied out of the directory, so the two tools are joined by
# the model's own reasoning rather than by anything on the diagram.
_DELEGATE_ARGS = (
	"{&#34;properties&#34;: {"
	"&#34;agent&#34;: {&#34;type&#34;: &#34;string&#34;, &#34;description&#34;: "
	"&#34;Which agent to hand this to. Use the 'agent' value exactly as "
	"find_specialists returned it.&#34;}, "
	"&#34;instruction&#34;: {&#34;type&#34;: &#34;string&#34;, &#34;description&#34;: "
	"&#34;What you want that agent to do, in plain words. Include the site and "
	"what happened.&#34;}}, "
	"&#34;required&#34;: [&#34;agent&#34;, &#34;instruction&#34;]}"
)

CLOSE_SCRIPT = "A2A Directory Test: Close Incident"

_CLOSE_INCIDENT = '''
frappe.db.set_value(context_doctype, context_docname, "status", "Closed")
result["incident_closed"] = 1
'''


def _start_event() -> str:
	"""Fires when an Issue of THIS type is created — its own type, so raising
	one incident never starts the other fixtures' maps too."""
	return (
		'    <bpmn:startEvent id="start" name="Incident reported">\n'
		"      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		'      <bpmn:conditionalEventDefinition id="cond_start" '
		'spiffworkflow:triggerDoctype="Issue" spiffworkflow:triggerType="After Insert" '
		f'spiffworkflow:triggerFieldName="issue_type" spiffworkflow:triggerFieldValue="{ISSUE_TYPE}">\n'
		f'        <bpmn:condition>issue_type == "{ISSUE_TYPE}"</bpmn:condition>\n'
		"      </bpmn:conditionalEventDefinition>\n"
		"    </bpmn:startEvent>\n"
	)


def _tool_shapes() -> str:
	"""Two tools, neither naming an agent.

	``find_specialists`` declares no aiToolParams at all: a tool with no
	declared parameters is called with zero arguments, which is right — asking
	who is available takes no input, and giving the model a filter to fill in
	would only let it narrow the roster by guessing.
	"""
	delegate_params = (
		"{&#34;agent&#34;: &#34;{{ task_data.agent }}&#34;, "
		"&#34;instruction&#34;: &#34;{{ task_data.instruction }}&#34;}"
	)
	return (
		'      <bpmn:serviceTask id="find_specialists" name="A2A → who can I delegate to?" '
		'spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a" '
		'spiffworkflow:operation="list_delegatable_agents" '
		'spiffworkflow:connectorParams="{}" '
		'spiffworkflow:resultVariable="directory">\n'
		"        <bpmn:documentation>Lists the agents you may hand work to, with what each one "
		"is for and its tags. Call this before delegating so you know who exists.</bpmn:documentation>\n"
		"      </bpmn:serviceTask>\n"
		'      <bpmn:serviceTask id="delegate_to_specialist" name="A2A → delegate to the agent you picked" '
		'spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a" '
		'spiffworkflow:operation="delegate_to_local_agent" '
		f'spiffworkflow:connectorParams="{delegate_params}" '
		'spiffworkflow:resultVariable="delegation" '
		f'spiffworkflow:aiToolParams="{_DELEGATE_ARGS}">\n'
		"        <bpmn:documentation>Hands a task to one of the agents from find_specialists and "
		"waits for its answer. Some agents answer at once; some involve a person and take "
		"longer.</bpmn:documentation>\n"
		"      </bpmn:serviceTask>\n"
	)


def _router_xml() -> str:
	prompt = SYSTEM_PROMPT.replace("\n", "&#10;").replace('"', "&#34;")
	return (
		_HEAD.format(pid="a2a_directory_router")
		+ '  <bpmn:process id="a2a_directory_router" isExecutable="true">\n'
		+ _start_event()
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="route" />\n'
		+ '    <bpmn:serviceTask id="route" name="Route the incident" '
		+ 'spiffworkflow:serviceType="ai_agent" '
		+ 'spiffworkflow:aiBackend="direct_api" '
		+ f'spiffworkflow:aiProvider="{PROVIDER}" '
		+ f'spiffworkflow:aiModel="{MODEL}" '
		+ f'spiffworkflow:aiAgentConfig="{ROUTER_AGENT}" '
		+ f'spiffworkflow:aiSystemPrompt="{prompt}" '
		+ 'spiffworkflow:aiUserPrompt="Incident raised: {{ doc.subject }}&#10;&#10;{{ doc.description }}" '
		+ 'spiffworkflow:aiOutputVariable="routing_summary" '
		+ 'spiffworkflow:aiResponseFormat="text" '
		+ 'spiffworkflow:aiTemperature="0" '
		+ 'spiffworkflow:aiMaxTokens="1500" '
		+ 'spiffworkflow:aiTimeout="120" '
		+ 'spiffworkflow:aiMaxRetries="1" '
		+ 'spiffworkflow:aiToolsAdhoc="a2a_tools" '
		# One lookup plus two delegations is three calls; the ceiling leaves
		# room for a re-read of the directory without letting a confused model
		# delegate all afternoon.
		+ 'spiffworkflow:aiMaxToolCalls="6">\n'
		+ "      <bpmn:documentation>Looks up which specialist agents exist, then hands the "
		+ "incident to the right ones.</bpmn:documentation>\n"
		+ "    </bpmn:serviceTask>\n"
		+ '    <bpmn:sequenceFlow id="f2" sourceRef="route" targetRef="close" />\n'
		+ _script_step(
			"close",
			"Close the incident",
			CLOSE_SCRIPT,
			"Signs the incident off once the router's turn is done.",
		)
		+ '    <bpmn:sequenceFlow id="f3" sourceRef="close" targetRef="end" />\n'
		+ '    <bpmn:endEvent id="end" name="Routed" />\n'
		+ '    <bpmn:adHocSubProcess id="a2a_tools" name="Delegation tools (A2A)">\n'
		+ "      <bpmn:documentation>Two generic tools: one asks who is available, the other "
		+ "delegates to whichever agent the model picked. No specialist is named on this "
		+ "diagram — exposing an agent on the A2A page is what puts it in reach.</bpmn:documentation>\n"
		+ _tool_shapes()
		+ "    </bpmn:adHocSubProcess>\n"
		+ "  </bpmn:process>\n"
		+ _di(
			"a2a_directory_router",
			[
				("start", 160, 180, 36, 36),
				("route", 260, 158, 160, 80),
				("close", 470, 158, 140, 80),
				("end", 670, 180, 36, 36),
				("a2a_tools", 200, 320, 420, 200),
				("find_specialists", 240, 370, 160, 80),
				("delegate_to_specialist", 430, 370, 160, 80),
			],
			[
				("f1", "start", "route"),
				("f2", "route", "close"),
				("f3", "close", "end"),
			],
			expanded={"a2a_tools"},
		)
		+ _TAIL
	)


def _reserve_router() -> None:
	"""The configuration goes in before the map that names it — the compile
	step refuses a shape whose aiAgentConfig does not exist, and the map and
	the configuration point at each other."""
	if not frappe.db.exists("AI Agent Configuration", ROUTER_AGENT):
		agent = frappe.new_doc("AI Agent Configuration")
		agent.agent_name = ROUTER_AGENT
		agent.agent_id = ROUTER_ID
		agent.agent_type = "Background"
		agent.agent_framework = "Direct API"
		agent.enabled = 1
		agent.flags.ignore_permissions = True
		agent.flags.ignore_mandatory = True
		agent.flags.ignore_links = True
		agent.insert(ignore_permissions=True)
	frappe.db.set_value(
		"AI Agent Configuration",
		ROUTER_AGENT,
		{
			"ai_provider_credentials": PROVIDER,
			"ai_model": MODEL,
			"system_prompt": SYSTEM_PROMPT,
			# Live is stamped by the provisioning map normally; a fixture never
			# runs it, and delegation requires the DELEGATING agent to exist as
			# a Live configuration too.
			"lifecycle_status": "Live",
			# The router delegates and never receives, so it is not exposed —
			# which also keeps it out of its own directory for the right reason
			# rather than only by the self-exclusion rule.
			"a2a_exposed": 0,
			"description": (
				"Looks up which specialist agents are available, then hands the incident to "
				"the right one."
			),
		},
		update_modified=False,
	)


def execute():
	if not frappe.db.exists("AI Agent Configuration", ASSESSOR):
		print("The specialist agents are missing. Run this first:")
		print("  bench execute one_bpmn.one_bpmn.a2a_scenario_fixtures.execute")
		return

	_upsert_issue_type(ISSUE_TYPE)
	_upsert_script(CLOSE_SCRIPT, _CLOSE_INCIDENT)
	_reserve_router()
	model = _upsert_model(ROUTER_AGENT, "a2a_directory_router", _router_xml())
	frappe.db.set_value(
		"AI Agent Configuration", ROUTER_AGENT, {"process_model": model}, update_modified=False
	)
	frappe.db.commit()

	print("Directory-driven delegation fixture is ready.\n")
	print(f"  agent : {ROUTER_AGENT}")
	print("  tools : find_specialists, delegate_to_specialist  (no agent named on the map)")
	print("\nWhat the router will be shown when it asks:")
	show_directory()
	print("\nRun it — creating the Issue is the trigger:")
	print("  bench execute one_bpmn.one_bpmn.a2a_directory_fixtures.run")


def show_directory():
	"""The roster as the router sees it — the same cards the A2A page shows.

	Worth running on its own: if this is empty or missing a specialist, the
	model has nothing to pick and the run proves nothing.
	"""
	from one_bpmn.one_bpmn.connectors.a2a_client_ops import list_delegatable_agents

	result = list_delegatable_agents({"delegating_agent": ROUTER_AGENT}, {})
	if not result["agents"]:
		print("  nobody is exposed over A2A — the router would have nobody to delegate to")
		return result
	print(f"\n  {'agent':<30}{'tags':<30}what it is for")
	print("  " + "-" * 110)
	for row in result["agents"]:
		print(f"  {row['agent'][:28]:<30}{', '.join(row['tags'])[:28]:<30}{row['description'][:48]}")
	return result


def raise_incident() -> str:
	issue = frappe.get_doc(
		{
			"doctype": "Issue",
			"subject": "Flooding in the basement plant room, Al Rai Tower",
			"description": INCIDENT,
			"issue_type": ISSUE_TYPE,
			"status": "Open",
		}
	)
	issue.flags.ignore_permissions = True
	issue.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"Raised {issue.name} ({ISSUE_TYPE})")
	return issue.name


def run():
	"""Raise an incident and watch the router discover who to hand it to."""
	issue = raise_incident()
	instance = _instance_for(issue)
	if not instance:
		return None
	_wait(instance)
	show_tool_calls(instance)
	return instance


def assign_technician():
	"""Play the person the chosen specialist is waiting on, then wake the router.

	Whichever agent the model picked for a Critical incident involves a human
	step, so the router is suspended mid-turn — not parked on a step of its own.
	That is the interesting difference from the scenario fixtures: the delegation
	happened inside a tool call, so the row that has to be reconciled carries a
	``caller_agent_run`` rather than a ``caller_wf_task_id``, and the resume goes
	back through the agent's checkpoint.
	"""
	from frappe.utils import now_datetime

	from one_bpmn.api.instance_api import complete_task, get_instance_tasks
	from one_bpmn.tasks import poll_a2a_tasks

	waiting = frappe.get_all(
		"A2A Task",
		filters={"delegated_by": ROUTER_AGENT, "state": ("in", ("working", "input-required"))},
		fields=["name", "agent_configuration", "instance"],
		order_by="creation desc",
		limit=1,
	)
	if not waiting:
		print("Nothing is waiting on a person. Run run() first.")
		return None

	row = waiting[0]
	active = (get_instance_tasks(row.instance) or {}).get("active_tasks") or []
	if not active:
		print(f"{row.agent_configuration} ({row.instance}) has no open task to complete.")
		return None

	task = active[0]
	print(f"Completing '{task.get('task_name')}' on {row.instance} ({row.agent_configuration})")
	complete_task(row.instance, task.get("task_id"), frappe.as_json({"technician": "Ahmad K."}))
	frappe.db.commit()

	# Parking sets next_poll_at 15 seconds out, so a reconcile this instant would
	# skip the row and look like a bug. The scheduler would simply have waited.
	frappe.db.set_value("A2A Task", row.name, "next_poll_at", now_datetime(), update_modified=False)
	frappe.db.commit()
	poll_a2a_tasks()
	frappe.db.commit()

	instance = frappe.get_all(
		"BPMN Process Instance",
		filters={"process_model": ROUTER_AGENT},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	if instance:
		_wait(instance[0], seconds=120)
		show_tool_calls(instance[0])
		print("\nThe router's own answer:")
		print("  " + (_routing_summary(instance[0]) or "(none recorded)"))
	return row.name


def _routing_summary(instance: str) -> str:
	"""What the router said at the end of its turn.

	Read off the AI Agent Run rather than the instance: the process data lives
	inside the serialised workflow state, and the run is where the agent's own
	final answer is recorded anyway.
	"""
	rows = frappe.get_all(
		"AI Agent Run",
		filters={"instance": instance, "agent_configuration": ROUTER_AGENT},
		fields=["final_output", "status"],
		order_by="creation desc",
		limit=1,
	)
	if not rows:
		return ""
	return (rows[0].final_output or "").strip()


def nudge():
	"""Run the reconciler now instead of waiting for the scheduler.

	Needed more than once on the slow path: completing the human step only frees
	the specialist to carry on (its own model turn, its own sub-delegation), so
	the first reconcile after the click often still sees it working. The
	scheduler would catch it on its next tick; this is that tick, on demand.
	"""
	from frappe.utils import now_datetime

	from one_bpmn.tasks import poll_a2a_tasks

	pending = frappe.get_all(
		"A2A Task", filters={"direction": "Internal", "resume_enqueued": 0}, pluck="name"
	)
	for row in pending:
		frappe.db.set_value("A2A Task", row, "next_poll_at", now_datetime(), update_modified=False)
	frappe.db.commit()
	poll_a2a_tasks()
	frappe.db.commit()

	instance = frappe.get_all(
		"BPMN Process Instance",
		filters={"process_model": ROUTER_AGENT},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	if not instance:
		print("No router instance yet.")
		return None
	_wait(instance[0], seconds=120)
	show_tool_calls(instance[0])
	print("\nThe router's own answer:")
	print("  " + (_routing_summary(instance[0]) or "(none recorded)"))
	return instance[0]


def teardown():
	for row in frappe.get_all(
		"BPMN Process Instance", filters={"process_model": ROUTER_AGENT}, pluck="name"
	):
		frappe.delete_doc(
			"BPMN Process Instance", row, force=True, ignore_permissions=True, ignore_missing=True
		)
	for name in ALL_AGENTS:
		frappe.delete_doc(
			"AI Agent Configuration", name, force=True, ignore_permissions=True, ignore_missing=True
		)
		frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc("Process", name, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.delete_doc("Server Script", CLOSE_SCRIPT, force=True, ignore_permissions=True, ignore_missing=True)
	for issue in frappe.get_all("Issue", filters={"issue_type": ISSUE_TYPE}, pluck="name"):
		frappe.delete_doc("Issue", issue, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.delete_doc("Issue Type", ISSUE_TYPE, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()
	print("Removed the A2A directory fixture.")
