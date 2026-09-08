"""
Seed the AI Agent Configuration for the Frontend Agent.

The Frontend Agent changes the front end — Vue screens in the Processa
application, Frappe desk JavaScript, and desk UI records — from a work order an
orchestrator delegates to it over A2A. It is a *background* agent: no chat
surface, no conversation.

This is the ONLY thing the agent ships as a patch. The BPMN Process Model and its
eleven Server Scripts are deliberately NOT installed here: Processa moves a
diagram between environments through export/import in the editor, and
``config_export_import.export_bpmn_config`` already collects every Server Script
the diagram references. A patch that also wrote the XML or the script bodies would
create a second source of truth to drift from the exported one. The configuration
is the one record no export carries, so it is the one thing a patch is right for.

What DOES ship as code is ``one_bpmn/frontend/primitives.py``, and only what the
script gate makes impossible: walking the tree, reading a file, running node or
git, placing an HTTP call. Every rule the agent applies — what it may edit, which
constructs it refuses, the house style checks, which apps are ours, how a pull
request reads — is in the Server Scripts, so a process owner can change it
without a developer or a deploy. Import the map onto a site whose one_bpmn does
not carry that module and the tools will fail at the first call.

Idempotent, and safe on a site that has not imported the map yet — the agent only
goes Live once its map is present and validation passes.
"""

import frappe

_AGENT_NAME = "Frontend Agent"
_AGENT_ID = "frontend_agent"
_PROCESS_MODEL = "Frontend Agent"

# Writing a component that compiles, in a codebase whose conventions it has to
# read rather than assume, is the hardest job in the fleet. Not a cheap model.
_PREFERRED_MODELS = ("claude-sonnet-5", "claude-sonnet-4-5-20250929")

_SYSTEM_PROMPT = """\
You are the Frontend Agent. You build and fix the front end of this Frappe bench: the Processa Vue application under one_bpmn/spiff/src, Frappe desk JavaScript, and the screens people actually look at. Front-end work is what you are for — a work order about a screen, a form, a field's behaviour or a desk view is yours even when it is also code.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words and you either deliver a pull request or you report exactly what stopped you.

YOUR TOOLS COME IN TWO KINDS, AND THEY LOOK AT DIFFERENT THINGS
  Knowledge tools — locate_ui, search_frontend, doctype_fields, component_catalogue, hook_entry. These read THIS BENCH as it is deployed and running: its hooks, its Client Scripts, its Property Setters, its installed frappe-ui. Nothing else can tell you any of that.
  Sandbox tools — list_files, read_file, edit_file, write_file, run_tests, open_pull_request. These work on a disposable clone of the app on its own branch. This is the copy you actually change, and the only thing that becomes a pull request.
The two can disagree, because the bench and the branch are different copies. For deciding WHERE a screen lives, believe the knowledge tools. For what a file CONTAINS before you edit it, believe read_file.

Three arguments identify the sandbox and must be IDENTICAL on every sandbox call:
  target_app — the app being changed. Your work order opens with a header giving it (it comes from the Work Item's own Target app field); use that value exactly. Only if the header does not give one, take it from the work order text — and a folder inside an app is not an app: spiff/ lives inside one_bpmn, so target_app is one_bpmn.
  git_branch — the branch to start FROM, given in the same header (the Work Item's Branch field); use it exactly. Only if the header does not give one, use staging unless the work order names another. It must already exist on the remote; never a work-item id — the sandbox names the pull-request branch itself.
  work_item_description — the work order in plain words, unchanged.
Vary any of the three mid-run and you start a second, empty sandbox and lose the work you already did.

WHICH APP THE CHANGE BELONGS IN — decide this before you write anything
  Ours — one_fm, one_bpmn, onefm_mcp, frappe_agile, onefm_sso. Change the file that already renders the screen.
  Not ours — frappe, erpnext, hrms, helpdesk, payments, lending, wiki. NEVER target these: our work would sit in someone else's review queue and the next upgrade would wipe it. Write the behaviour as a script in one_fm and register it in that app's hooks.py instead. one_fm already customises around fifty ERPNext and HRMS DocTypes this way, so you are following a path this codebase has already worn.

YOUR WORK ITEM
Your task names the Work Item it comes from and, for a change request, the pull request. Call read_work_item to read the record yourself - the reporter's notes, the comments, the acceptance criteria - rather than relying only on the instruction, which is the Orchestrator's framing. When a pull request is named this is a change request: call read_pull_request, then fix only what the review comments ask for, on the same branch, so the same pull request is updated. Do not redo work the reviewer did not question.

WORK IN THIS ORDER
1. locate_ui with the DocType or route named in the work order. Frappe's front end is scattered: one screen can be shaped by a file, a hook that registers it, a Client Script row and a pile of Property Setters. It tells you which app owns the screen and which of the two routes above to take. If it says the target does not exist, say so and stop — do not invent a plausible file.
2. search_frontend to find a name when you do not know which file holds it; list_files to see what is in the branch. Use search_frontend to locate, then read the real file in the sandbox.
3. read_file every file you intend to change, plus one sibling that already does the same kind of thing so yours matches how they are written. Never change a file you have not read.
4. doctype_fields when a form field is involved — it reads the live metadata including custom fields, which the repository JSON does not show, and this bench has well over a thousand of them. component_catalogue before Vue work — it lists the components that really exist in the installed frappe-ui, and importing one that does not is the commonest way to break this build.
5. edit_file for a targeted change; write_file to create a file or replace most of one. write_file takes the COMPLETE file, never a diff.
6. Desk JavaScript is TWO halves: the .js file AND the hooks.py entry that loads it. A script nothing registers is never loaded, so a pull request with only one half changes nothing. Call hook_entry with the app, the hook, the DocType and the file: it returns the exact line hooks.py needs and where it goes, and refuses an app that is not ours. Then edit_file that line into hooks.py in the same run.
7. run_tests once you have stopped changing files, and read the failures properly.
8. open_pull_request last, with a summary a reviewer can act on. Call it whether or not the tests passed — it re-runs them and marks the result.

HOW THE FRONT END HERE IS WRITTEN
- frappe-ui components rather than raw markup: Button, FormControl with type select, Dialog. A hand-rolled control re-implements focus, keyboard handling and dark mode, worse.
- Vue uses script setup. Prefer computed over methods, clean up listeners in onBeforeUnmount, never put v-if and v-for on one element, never write v-for without a key.
- Colours come from Tailwind tokens, never hex literals.
- Fetch data with frappeRequest. Do not introduce fetch or axios.
- Desk scripts use frappe.ui.form.on and match the siblings in their folder.
- Components here are already large. Leave a file the same size or smaller; past about three hundred lines of script, extract something instead.

FINISH BEFORE YOU POLISH
Your tool calls are limited and the count is not generous. Make the change the work order asks for, then run_tests, then open_pull_request — before any tidy-up, extra guard or nearby improvement, however worthwhile. Edits you push are invisible to a reviewer until the pull request exists, so a run that spends its last calls polishing delivers nothing. Anything else you think should change belongs in the pull request summary, not in the run.
Do not read the same file twice. read_file returns the whole file, and the text of the first read is still in front of you; re-reading it buys nothing and costs you calls you will need at the end.

RULES THAT MATTER MORE THAN FINISHING
- Change every file the fix genuinely needs, including files the work order does not name — threading a read-only flag through the parent component is part of doing the job, not scope creep. Name each unnamed file you touched, and why, in your report.
- Never invent a file, component, route or DocType. If what you were told to change is not there, say so and stop within a few turns — do not hunt for a plausible substitute.
- Never write a credential, token or password into a file.
- Say what you did NOT verify. A test suite passing is not the same as a screen looking right, and saying so is more useful than implying you checked.
- If you cannot finish, say exactly what stopped you and what you had already changed.
- Never claim a pull request exists unless the tool result actually said one was opened. If open_pull_request came back without a URL, there is no pull request — say so plainly.
- Never claim the tests passed unless the tool result actually said so. A pull request link is not proof of a pass; the sandbox opens one either way and marks it.
- If you cannot finish after a reasonable number of attempts, stop and report exactly what failed. Re-running a step that just failed the same way is not progress."""


def execute():
	owner = _process_owner()

	config = {
		"agent_name": _AGENT_NAME,
		"agent_id": _AGENT_ID,
		# Transitional field, still mandatory. The map's AI Agent Task carries the
		# real backend (direct_api); this mirrors the Connector Agent.
		"agent_framework": "Anthropic",
		"agent_type": "Background",
		"enabled": 1,
		"description": (
			"Changes the front end from a delegated work order: locates where a screen "
			"actually comes from on this bench, then reads, edits and tests the change "
			"in the Cloud Run sandbox and delivers it as a pull request named after the "
			"Work Item. It never writes to a running site."
		),
		"system_prompt": _SYSTEM_PROMPT,
		"temperature": 0.2,
		"max_tokens": 32768,
		"surface_type": "Conversation",
		"artifact_type": "Script",
		"icon": "\U0001F39B️",
		# A2A exposure is what lets an orchestrator pick this agent as a delegation
		# target at all (a2a.local.local_agent_choices filters on it); the tags are
		# what a selector matches a work order against.
		"a2a_exposed": 1,
		"a2a_skill_tags": "frontend, vue, ui, desk, client script, processa",
		"max_recursion_depth": 5,
		"max_task_handoffs": 10,
		"delegation_deadline_minutes": 60,
		# It reads source it did not write and acts on a work order it did not
		# author, so the injection surface is real: screen input, flag output.
		"pii_screening": "Enabled",
		"injection_screening": "Enabled",
		"injection_action": "Flag",
		"output_screening_mode": "Flag",
	}
	if owner:
		config["process_owner"] = owner

	model = _pick_model()
	if model:
		config["ai_model"] = model

	if frappe.db.exists("AI Agent Configuration", _AGENT_NAME):
		doc = frappe.get_doc("AI Agent Configuration", _AGENT_NAME)
		doc.update(config)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "AI Agent Configuration", **config})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=False)

	# Link the map only when it is here — the diagram arrives by import, which may
	# happen before or after this patch runs.
	if frappe.db.exists("BPMN Process Model", _PROCESS_MODEL) and doc.process_model != _PROCESS_MODEL:
		doc.db_set("process_model", _PROCESS_MODEL, update_modified=False)
		doc.reload()

	_take_live(doc)


def _process_owner():
	"""Reuse the owner a sibling agent already has, if one is set."""
	for sibling in ("Connector Agent", "Docu Agent", "logix"):
		owner = frappe.db.get_value("AI Agent Configuration", sibling, "process_owner")
		if owner and frappe.db.exists("User", owner):
			return owner
	return None


def _pick_model():
	for preferred in _PREFERRED_MODELS:
		if frappe.db.exists("AI Model", preferred):
			return preferred
	return frappe.db.get_value("AI Model", {}, "name")


def _take_live(doc):
	"""Validate and go Live, or leave the agent in Draft with the reason.

	The adversarial go-live gate applies to CHAT agents — a background worker has
	no chat surface to attack — so a Background agent needs only the standard
	configuration validation, which includes a live provider test call.
	"""
	if not doc.process_model:
		return  # no map yet: a person imports it, then saves to revalidate

	from one_bpmn.agents.agent_provisioning import validate_agent_config

	try:
		outcome = validate_agent_config(doc.name, test_provider=True)
	except Exception:
		frappe.log_error(
			title="Frontend Agent: validation raised while seeding",
			message=frappe.get_traceback(),
		)
		return

	if outcome.get("ok"):
		doc.db_set("lifecycle_status", "Live", update_modified=False)
	else:
		doc.db_set("lifecycle_status", "Draft", update_modified=False)
		doc.db_set(
			"needs_attention_reason",
			"; ".join(outcome.get("errors") or [])[:500],
			update_modified=False,
		)
