# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Remote A2A across two sites: staging asks, BA answers (WI-001933).

Everything exercised so far has been same-site — one bench, no trust
boundary, no network. This sets up the other half: an agent on ONE site
delegating to an agent on ANOTHER, over the A2A protocol.

Two commands, one per site.

**On the answering site (BA):**

    bench execute one_bpmn.one_bpmn.a2a_remote_fixtures.setup_receiver

Creates the Site Safety Assessor as a Background agent exposed over A2A,
with its own process map, and an approved A2A Client for the calling site.
It prints the endpoint URL and the client's API credentials — the caller
needs both, and they are shown once here rather than stored anywhere.

**On the asking site (staging):**

    bench execute one_bpmn.one_bpmn.a2a_remote_fixtures.setup_caller \
        --kwargs '{"url": "<printed>", "api_key": "<printed>", "api_secret": "<printed>"}'

Registers that endpoint as an A2A Remote Agent, fetches its card so there
is something to review, and approves it.

Why two sides at all: a remote hop needs BOTH an approved client on the
answering site (who may knock) and an approved registry entry on the asking
site (who we may call). Neither alone is enough — that is the whole point of
the two registries.
"""

import frappe

ASSESSOR = "Site Safety Assessor"
CALLER_CLIENT = "Staging (A2A caller)"
REMOTE_ENTRY = "BA Site Safety Assessor"

# BA runs its Anthropic credentials under that name, not "Claude" — read off
# the site rather than assumed, and overridable below.
DEFAULT_PROVIDER = "Anthropic"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

READ_BRIEF = "A2A Remote: Read Brief"
RECORD_VERDICT = "A2A Remote: Record Verdict"

_READ_BRIEF = '''
# The caller's instruction arrives on this agent's own A2A Task, which is the
# instance's context document. Nothing copies the caller's variables across a
# site boundary, so lift the brief into workflow data before the agent reads it.
payload = frappe.parse_json(doc.request_payload or "{}") or {}
result["report"] = payload.get("instruction") or ""
'''

_RECORD_VERDICT = '''
# The answer has to land on the A2A Task: that row IS what the caller polls
# over the protocol, so a verdict left only in workflow data never crosses back.
said = (task_data.get("answer_text") or "").strip().lower()
severity = "Routine"
if "critical" in said:
	severity = "Critical"

answer = {"text": severity, "severity": severity, "said": said[:200]}
frappe.db.set_value(
	"A2A Task",
	context_docname,
	{"result": frappe.as_json(answer), "status_message": severity},
	update_modified=True,
)
result["severity"] = severity
'''

ASSESSOR_PROMPT = (
	"You are a site safety assessor for a facilities-management company. You are "
	"given one incident report and you judge how serious it is.\n\n"
	"Critical means it can hurt someone or spread if left: fire, smoke, gas, "
	"flooding, a burst pipe, a spill, an injury, an electrical fault, someone "
	"trapped, a structural failure, or a power loss that takes safety systems "
	"with it. Routine means damage or wear that can wait for the normal repair "
	"round.\n\n"
	"Answer with exactly one word: Critical or Routine. Nothing else."
)

_HEAD = (
	'<?xml version="1.0" encoding="UTF-8"?>\n'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
	'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
	'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
	'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
	'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
	'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" '
	'id="Definitions_a2a_remote_assessor" targetNamespace="http://bpmn.io/schema/bpmn">\n'
)


def _provider() -> str:
	"""Whichever Anthropic-style credential this site actually has."""
	for name in (DEFAULT_PROVIDER, "Claude"):
		if frappe.db.exists("AI Provider Credentials", name):
			return name
	rows = frappe.get_all("AI Provider Credentials", filters={"enabled": 1}, limit=1, pluck="name")
	if not rows:
		frappe.throw("This site has no AI Provider Credentials — the assessor cannot call a model.")
	return rows[0]


def _assessor_xml(provider: str, model: str) -> str:
	"""Read the brief → let the agent judge → write the verdict back.

	The middle step is a real AI Agent Task: a remote caller is asking a
	genuine agent, not a script wearing an agent record.
	"""
	prompt = ASSESSOR_PROMPT.replace("\n", "&#10;").replace('"', "&#34;")
	di = (
		'  <bpmndi:BPMNDiagram id="D_1">\n'
		'    <bpmndi:BPMNPlane id="P_1" bpmnElement="a2a_remote_assessor">\n'
		+ "".join(
			f'      <bpmndi:BPMNShape id="{e}_di" bpmnElement="{e}">'
			f'<dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" /></bpmndi:BPMNShape>\n'
			for e, x, y, w, h in (
				("start", 160, 180, 36, 36),
				("read_brief", 250, 158, 140, 80),
				("judge", 440, 158, 160, 80),
				("record", 650, 158, 140, 80),
				("end", 850, 180, 36, 36),
			)
		)
		+ "".join(
			f'      <bpmndi:BPMNEdge id="{f}_di" bpmnElement="{f}" />\n'
			for f in ("f1", "f2", "f3", "f4")
		)
		+ "    </bpmndi:BPMNPlane>\n  </bpmndi:BPMNDiagram>\n"
	)
	return (
		_HEAD
		+ '  <bpmn:process id="a2a_remote_assessor" isExecutable="true">\n'
		# The door: an inbound A2A Task naming THIS agent starts the map. The
		# condition scopes it so no other agent's work lands here.
		+ '    <bpmn:startEvent id="start" name="Delegated task received">\n'
		+ "      <bpmn:outgoing>f1</bpmn:outgoing>\n"
		+ '      <bpmn:conditionalEventDefinition id="cond_start" '
		+ 'spiffworkflow:triggerDoctype="A2A Task" spiffworkflow:triggerType="After Insert" '
		+ f'spiffworkflow:triggerFieldName="agent_configuration" spiffworkflow:triggerFieldValue="{ASSESSOR}">\n'
		+ f'        <bpmn:condition>agent_configuration == "{ASSESSOR}"</bpmn:condition>\n'
		+ "      </bpmn:conditionalEventDefinition>\n"
		+ "    </bpmn:startEvent>\n"
		+ '    <bpmn:sequenceFlow id="f1" sourceRef="start" targetRef="read_brief" />\n'
		+ f'    <bpmn:scriptTask id="read_brief" name="Read the brief" spiffworkflow:serverScript="{READ_BRIEF}">\n'
		+ "      <bpmn:incoming>f1</bpmn:incoming>\n      <bpmn:outgoing>f2</bpmn:outgoing>\n"
		+ "      <bpmn:documentation>Lifts the caller's instruction off this agent's own task.</bpmn:documentation>\n"
		+ "    </bpmn:scriptTask>\n"
		+ '    <bpmn:sequenceFlow id="f2" sourceRef="read_brief" targetRef="judge" />\n'
		+ '    <bpmn:serviceTask id="judge" name="Judge how serious it is" '
		+ 'spiffworkflow:serviceType="ai_agent" spiffworkflow:aiBackend="direct_api" '
		+ f'spiffworkflow:aiProvider="{provider}" spiffworkflow:aiModel="{model}" '
		+ f'spiffworkflow:aiAgentConfig="{ASSESSOR}" '
		+ f'spiffworkflow:aiSystemPrompt="{prompt}" '
		# Bare `report`: an AI prompt gets workflow variables as top-level
		# names; only a connector's params take the task_data wrapper.
		+ 'spiffworkflow:aiUserPrompt="{{ report }}" '
		+ 'spiffworkflow:aiOutputVariable="answer_text" '
		+ 'spiffworkflow:aiResponseFormat="text" spiffworkflow:aiTemperature="0" '
		+ 'spiffworkflow:aiMaxTokens="1024" spiffworkflow:aiTimeout="120" '
		+ 'spiffworkflow:aiMaxRetries="1">\n'
		+ "      <bpmn:incoming>f2</bpmn:incoming>\n      <bpmn:outgoing>f3</bpmn:outgoing>\n"
		+ "      <bpmn:documentation>Returns Critical or Routine.</bpmn:documentation>\n"
		+ "    </bpmn:serviceTask>\n"
		+ '    <bpmn:sequenceFlow id="f3" sourceRef="judge" targetRef="record" />\n'
		+ f'    <bpmn:scriptTask id="record" name="Answer the caller" spiffworkflow:serverScript="{RECORD_VERDICT}">\n'
		+ "      <bpmn:incoming>f3</bpmn:incoming>\n      <bpmn:outgoing>f4</bpmn:outgoing>\n"
		+ "      <bpmn:documentation>Writes the verdict onto the task the caller polls.</bpmn:documentation>\n"
		+ "    </bpmn:scriptTask>\n"
		+ '    <bpmn:sequenceFlow id="f4" sourceRef="record" targetRef="end" />\n'
		+ '    <bpmn:endEvent id="end" name="Answered"><bpmn:incoming>f4</bpmn:incoming></bpmn:endEvent>\n'
		+ "  </bpmn:process>\n"
		+ di
		+ "</bpmn:definitions>\n"
	)


def _upsert_script(name: str, body: str) -> None:
	"""Server Scripts must exist before a map that names them: the deploy gate
	inspects a script task's script at save time."""
	if frappe.db.exists("Server Script", name):
		doc = frappe.get_doc("Server Script", name)
		if (doc.script or "").strip() != body.strip():
			doc.script = body
			doc.save(ignore_permissions=True)
		if doc.disabled:
			doc.db_set("disabled", 0)
		return
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


def setup_receiver(provider: str | None = None, model: str = DEFAULT_MODEL):
	"""Run on the ANSWERING site (BA). Idempotent."""
	provider = provider or _provider()

	_upsert_script(READ_BRIEF, _READ_BRIEF)
	_upsert_script(RECORD_VERDICT, _RECORD_VERDICT)

	# The configuration must exist and be Live before the map that names it in
	# aiAgentConfig compiles — the deploy gate refuses a Draft agent.
	if not frappe.db.exists("AI Agent Configuration", ASSESSOR):
		agent = frappe.new_doc("AI Agent Configuration")
		agent.agent_name = ASSESSOR
		agent.agent_id = "a2a_site_safety_assessor"
		agent.agent_type = "Background"
		agent.agent_framework = "Direct API"
		agent.enabled = 1
		agent.flags.ignore_permissions = True
		agent.flags.ignore_mandatory = True
		agent.flags.ignore_links = True
		agent.insert(ignore_permissions=True)
	frappe.db.set_value(
		"AI Agent Configuration",
		ASSESSOR,
		{
			"ai_provider_credentials": provider,
			"ai_model": model,
			"system_prompt": ASSESSOR_PROMPT,
			"lifecycle_status": "Live",
			# The grant that opens the A2A door for this agent.
			"a2a_exposed": 1,
			"a2a_skill_tags": "safety, assessment, triage",
			"description": (
				"Judges how serious a reported site incident is, and returns Critical or Routine."
			),
		},
		update_modified=False,
	)

	# Processa lists maps THROUGH a Process record, so a map without one is
	# invisible in the UI even though it runs perfectly well.
	if not frappe.db.exists("Process", ASSESSOR):
		process = frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": ASSESSOR,
				"description": "Answers safety assessments delegated from another site over A2A.",
				"process_owner": frappe.session.user
				if frappe.session.user != "Guest"
				else "Administrator",
			}
		)
		process.flags.ignore_permissions = True
		process.insert(ignore_permissions=True)

	if frappe.db.exists("BPMN Process Model", ASSESSOR):
		model_doc = frappe.get_doc("BPMN Process Model", ASSESSOR)
	else:
		model_doc = frappe.new_doc("BPMN Process Model")
		model_doc.title = ASSESSOR
	model_doc.process_id = "a2a_remote_assessor"
	model_doc.process_name = ASSESSOR
	model_doc.version = model_doc.version or 1
	model_doc.bpmn_xml = _assessor_xml(provider, model)
	model_doc.flags.ignore_permissions = True
	model_doc.flags.ignore_mandatory = True
	model_doc.save(ignore_permissions=True)

	# Deploy: compiling is what makes the map runnable AND A2A-startable.
	from one_bpmn.api.compilation import compile_process_model

	compile_process_model(model_doc.name)
	frappe.db.set_value(
		"AI Agent Configuration", ASSESSOR, "process_model", model_doc.name, update_modified=False
	)

	# The inbound guest list: approving mints the caller's badge (its own user
	# plus API key), and allowed_agents is the positive list that badge may
	# invoke. Approved alone is not enough — the agent has to be listed too.
	if frappe.db.exists("A2A Client", CALLER_CLIENT):
		client = frappe.get_doc("A2A Client", CALLER_CLIENT)
	else:
		client = frappe.new_doc("A2A Client")
		client.client_name = CALLER_CLIENT
	client.enabled = 1
	client.approval_status = "Approved"
	client.description = "The staging site, delegating safety assessments to this one."
	client.set("allowed_agents", [{"agent_configuration": ASSESSOR}])
	client.flags.ignore_permissions = True
	client.save(ignore_permissions=True)

	credentials = client.get_credentials()
	agent_id = frappe.db.get_value("AI Agent Configuration", ASSESSOR, "agent_id")
	site = frappe.utils.get_url()
	url = f"{site}/api/method/one_bpmn.api.a2a_api.rpc?agent_id={agent_id}"

	frappe.db.commit()
	print("Receiver ready on this site.\n")
	print(f"  agent        : {ASSESSOR} (Background, Live, exposed over A2A)")
	print(f"  process map  : {model_doc.name} — open /processa to see it")
	print(f"  client       : {CALLER_CLIENT} (Approved, may invoke only this agent)")
	print("\nGive the CALLING site these three values:\n")
	print(f'  url        = "{url}"')
	print(f'  api_key    = "{credentials["api_key"]}"')
	print(f'  api_secret = "{credentials["api_secret"]}"')
	print("\nThe card is public — check it renders before wiring the caller up:")
	print(f"  curl '{site}/api/method/one_bpmn.api.a2a_api.agent_card?agent_id={agent_id}'")
	return {"url": url, **credentials}


def setup_caller(url: str, api_key: str, api_secret: str):
	"""Run on the ASKING site (staging) with the three values printed above."""
	if not (url and api_key and api_secret):
		frappe.throw("url, api_key and api_secret are all required — see setup_receiver's output.")

	if frappe.db.exists("A2A Remote Agent", REMOTE_ENTRY):
		remote = frappe.get_doc("A2A Remote Agent", REMOTE_ENTRY)
	else:
		remote = frappe.new_doc("A2A Remote Agent")
		remote.agent_name = REMOTE_ENTRY
	remote.endpoint_url = url
	remote.enabled = 1
	remote.auth_scheme = "Bearer"
	remote.auth_header_name = "Authorization"
	# Frappe's token scheme, which is what the remote's card asks for.
	remote.credential = f"token {api_key}:{api_secret}"
	# Two sites on the same private network are "internal" to a host check that
	# exists to stop SSRF against link-local addresses; allow it deliberately.
	remote.allow_internal_hosts = 1
	remote.flags.ignore_permissions = True
	remote.save(ignore_permissions=True)

	# The card is what an approver reviews, so it has to be fetched BEFORE
	# approval — the doctype refuses to approve without one.
	card = remote.fetch_card()
	remote.reload()
	remote.approval_status = "Approved"
	remote.flags.ignore_permissions = True
	remote.save(ignore_permissions=True)
	frappe.db.commit()

	print(f"Registered and approved: {remote.name}")
	print(f"  endpoint : {url}")
	print(f"  card     : {card.get('name')} — {(card.get('description') or '')[:60]}")
	print(f"  skills   : {[s.get('id') for s in (card.get('skills') or [])]}")
	print("\nIt is now selectable on any a2a connector step's 'Remote agent' dropdown.")
	return remote.name


def teardown_receiver():
	for row in frappe.get_all("A2A Task", filters={"agent_configuration": ASSESSOR}, pluck="name"):
		frappe.delete_doc("A2A Task", row, force=True, ignore_permissions=True, ignore_missing=True)
	for row in frappe.get_all("BPMN Process Instance", filters={"process_model": ASSESSOR}, pluck="name"):
		frappe.delete_doc(
			"BPMN Process Instance", row, force=True, ignore_permissions=True, ignore_missing=True
		)
	for dt, name in (
		("A2A Client", CALLER_CLIENT),
		("AI Agent Configuration", ASSESSOR),
		("BPMN Process Model", ASSESSOR),
		("Process", ASSESSOR),
		("Server Script", READ_BRIEF),
		("Server Script", RECORD_VERDICT),
	):
		frappe.delete_doc(dt, name, force=True, ignore_permissions=True, ignore_missing=True)
	frappe.db.commit()
	print("Removed the remote-A2A receiver fixtures.")
