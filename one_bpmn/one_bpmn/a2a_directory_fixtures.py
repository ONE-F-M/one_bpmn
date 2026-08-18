# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Does an agent pick the right specialist from the CARDS alone?

``a2a_agent_tool_fixtures`` proves an agent will choose to delegate, but it
leans on prose: each delegation shape carries a ``<documentation>`` sentence
someone wrote, and that sentence is what the model reads. So the routing was
only ever as good as the writing on the diagram, and every map that reached
an agent had to describe that agent again — differently, and going stale on
its own schedule.

Here the delegation shapes carry NO documentation at all. Each one is
described to the model by its target agent's card (WI-001933) — the same
card a person reads on the A2A page — assembled at run time:

    Site Safety Assessor — Judges how serious a reported site incident is,
    and returns Critical or Routine.
    Good for: safety, assessment, triage

(A third line, "For example: ...", appears too when the agent has sample
prompts. None of these fixtures set any, so run ``show_directory`` rather
than trusting this sample.)

So the diagram says only WHO is reachable; what each one is FOR comes from
the agent itself. Edit an agent's description or tags on the A2A page and
every caller describes it the new way on its next turn, with nothing to
redeploy.

The specialists come from ``a2a_scenario_fixtures`` (assessor, parts
checker, compliance logger, maintenance dispatcher — all exposed, all
carrying descriptions and tags, because that is now the only thing the model
has to go on). Run that module's ``execute()`` first. This one calls a real
model, so it needs working Claude credentials.

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
	DISPATCHER,
	LOGGER,
	PARTS,
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

# The prompt names NO agent and describes none of them. It cannot: the whole
# point is that what each specialist is for reaches the model as a tool
# description built from that agent's card, never as prose written here. All
# the prompt supplies is the SHAPE of the job — assess first, then act on the
# verdict — which is the one thing no single agent's card can tell it.
SYSTEM_PROMPT = (
	"You route facility incidents for a facilities-management company. You do not "
	"judge severity yourself and you do not do repairs — other agents do that.\n\n"
	"Your tools are the specialists you may hand work to. Read what each one says "
	"it is for and pick on that alone.\n\n"
	"Get the incident assessed first — the verdict comes back as Critical or "
	"Routine. A Critical incident then goes to whichever specialist handles repairs "
	"and technicians. A Routine one goes to whichever keeps the compliance record "
	"instead. Never both.\n\n"
	"If no tool suits, say so rather than forcing one.\n\n"
	"Once that second specialist has answered you are done — signing the incident "
	"off is not your job and happens on its own.\n\n"
	"Finish with one plain sentence: who you picked, why, and what they said."
)

# What the model supplies when it calls a delegation tool. Only the
# instruction: WHICH agent is the tool it chose, baked into that shape's
# connectorParams, so the choice is the tool call itself rather than a string
# the model has to copy correctly from somewhere else.
_DELEGATE_ARGS = (
	"{&#34;properties&#34;: {"
	"&#34;instruction&#34;: {&#34;type&#34;: &#34;string&#34;, &#34;description&#34;: "
	"&#34;What you want this specialist to do, in plain words. Include the site "
	"and what happened.&#34;}}, "
	"&#34;required&#34;: [&#34;instruction&#34;]}"
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


# One shape per reachable specialist. The bpmn_id is a neutral slot name on
# purpose — delegate_1, not delegate_to_the_safety_assessor — so that if the
# card ever failed to load, the model would be choosing between meaningless
# names and the failure would be obvious instead of quietly working from the
# shape id.
SPECIALISTS = (
	("delegate_1", ASSESSOR),
	("delegate_2", DISPATCHER),
	("delegate_3", LOGGER),
	("delegate_4", PARTS),
)


def _tool_shapes() -> str:
	"""One delegation shape per specialist, each carrying NO documentation.

	That absence is the fixture. With no documentation the model has only the
	description built from the target's agent card, so a correct route proves
	the card carried the meaning — if it did not, the model is picking between
	four indistinguishable tools called delegate_1..4 and will route wrongly.
	"""
	shapes = []
	for element, agent in SPECIALISTS:
		params = (
			f"{{&#34;agent&#34;: &#34;{agent}&#34;, "
			"&#34;instruction&#34;: &#34;{{ task_data.instruction }}&#34;}"
		)
		shapes.append(
			f'      <bpmn:serviceTask id="{element}" name="A2A → {agent}" '
			'spiffworkflow:serviceType="connector" spiffworkflow:connectorId="a2a" '
			'spiffworkflow:operation="delegate_to_local_agent" '
			f'spiffworkflow:connectorParams="{params}" '
			f'spiffworkflow:resultVariable="{element}_result" '
			f'spiffworkflow:aiToolParams="{_DELEGATE_ARGS}" />\n'
		)
	return "".join(shapes)


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
		# Two delegations is the whole job now that no lookup call is needed.
		# The ceiling leaves room for one wrong turn without letting a confused
		# model work through the whole roster.
		+ 'spiffworkflow:aiMaxToolCalls="4">\n'
		+ "      <bpmn:documentation>Hands the incident to the right specialists, chosen "
		+ "from what each one's card says it does.</bpmn:documentation>\n"
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
		+ "      <bpmn:documentation>One delegation per reachable specialist. None of them "
		+ "carries a description: what each is for is read from that agent's own card at run "
		+ "time, so this diagram never restates it.</bpmn:documentation>\n"
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
				("a2a_tools", 200, 320, 800, 200),
				("delegate_1", 240, 370, 160, 80),
				("delegate_2", 430, 370, 160, 80),
				("delegate_3", 620, 370, 160, 80),
				("delegate_4", 810, 370, 160, 80),
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
	print(f"  tools : {len(SPECIALISTS)} delegations, none of them described on the map")
	print("\nWhat the router is shown for each tool — cards only:")
	show_directory()
	print("\nRun it — creating the Issue is the trigger:")
	print("  bench execute one_bpmn.one_bpmn.a2a_directory_fixtures.run")


def show_directory():
	"""Exactly what the model will be shown for each delegation tool.

	Worth running before a scenario: this is the model's whole basis for
	choosing, so if a specialist prints as just its slot name, its card did
	not build — it is not exposed, not Live, or has no description — and the
	run would prove nothing about card-driven routing.
	"""
	from one_bpmn.agents.a2a.card import tool_description

	print(f"\n  What {ROUTER_AGENT} sees:\n")
	missing = []
	for element, agent in SPECIALISTS:
		text = tool_description(agent)
		if not text:
			missing.append(agent)
			print(f"  {element}  —  NO CARD ({agent}): not exposed, not Live, or no description")
			continue
		first, *rest = text.split("\n")
		print(f"  {element}  —  {first}")
		for line in rest:
			print(f"  {' ' * len(element)}     {line}")
		print()
	if missing:
		print("  Fix those before running: the model cannot tell them apart.")
	return missing


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
