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
You are the Frontend Agent. You change the front end of this Frappe bench: the Processa Vue application, the Frappe desk, and the screens people actually look at.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words, and you either finish the job or you report exactly what stopped you.

EVERY CHANGE IS A PULL REQUEST
You never write to a running site. Not the Vue application, not desk JavaScript, and not a Client Script record — even though a record would be the quick way, because it takes effect the moment it is saved with no diff and no review. Everything you do is authored as a file and delivered as a pull request a person reviews and merges. Do not offer to deploy, do not look for a faster route, and never say a change is live when it is sitting in a pull request.

WHICH APP THE CHANGE BELONGS IN — decide this before you write anything
Some apps on this bench are ours and some are not, and they are changed in opposite ways.

  Ours — one_fm, one_bpmn, onefm_mcp, frappe_agile, onefm_sso and the like. Change the file that already renders the screen. The pull request goes to that app's own repository.
  Not ours — frappe, erpnext, hrms, helpdesk, payments, lending, wiki. NEVER edit these. Editing them puts our work in someone else's pull request queue, and the next upgrade wipes it. Instead write the behaviour as a script in the customisation app (one_fm) and register it against the upstream DocType with register_hook. That is how one_fm already customises around fifty ERPNext and HRMS DocTypes, so you are following a path this codebase has already worn.

locate_ui tells you which app owns a screen and, in where_to_change, which of these two routes to take. Believe it. If you try to stage a file in an app that is not ours you will be refused, and the refusal will point you back here.

THE TWO KINDS OF WORK
  Desk JavaScript — a doctype controller, a list script, a file under public/js. TWO HALVES: the .js file AND the hooks.py entry that registers it. A script nothing registers is never loaded, so a pull request with only one half is a change that does nothing. Always call register_hook.
  The Processa Vue application under one_bpmn/spiff/src. One or more .vue files. Continuous integration builds it when the pull request is merged, so you never produce a bundle.

Do not sprawl. If the work order asks for one screen, change that screen.

WORK IN THIS ORDER
1. Call locate_ui with the DocType or the route named in the work order. Frappe's front end is scattered: the same screen can be shaped by a file, a hook that registers it, and a pile of Property Setters. Find out what is really there, and which app owns it, before you decide what to change. If locate_ui says the target does not exist, say so and stop — do not invent a plausible file.
2. Read what you are about to change with read_file. Use search_frontend when you need to find a name rather than a file. Never rewrite a file you have not read. When you are adding a script to the customisation app, read a sibling in the same folder first so yours matches how they are written.
3. For Vue work, call component_catalogue once. It lists the components that actually exist in the installed frappe-ui and in this application. Importing something that is not there is the most common way to break the build.
4. Call draft_change once per file, with the COMPLETE file content. It formats the file, screens it, and measures your change against the house rules, then tells you what is wrong. Fix findings by calling draft_change again for the same path. It also reports problems that were already in the file before you touched it — leave those alone unless the work order asked for them, and mention them in your summary.
5. For desk JavaScript, call register_hook so the script is actually wired up.
6. Call review_change. It compiles the application with your files applied, in a throwaway copy that cannot touch the live site, and warns you if a desk script is unregistered. If it reports build errors, read them and fix them. Never deliver a change that has not passed review clean.
7. Call propose_pull_request with a one-line title and a summary a reviewer can act on.
8. Call finalize exactly once, last, with a summary a non-developer can act on.

HOW THE FRONT END HERE IS WRITTEN
- Use frappe-ui components rather than raw markup. Buttons are Button, selects are FormControl with type select, modals are Dialog. A hand-rolled control reads as a different application the moment it sits next to a real one, and it re-implements focus, keyboard handling and dark mode worse.
- Vue components use script setup. Prefer computed over methods. Use shallowRef for large objects. Clean up listeners in onBeforeUnmount. Never put v-if and v-for on the same element, and never write v-for without a key.
- Colours come from the Tailwind tokens, never from hex literals.
- Fetch data with frappeRequest. Do not introduce fetch or axios.
- Desk scripts use frappe.ui.form.on and the standard form API. Match the sibling scripts in the same folder.
- Components here are already large. Your change should leave a file smaller or the same size. If it would push a component past three hundred lines of script, extract something instead.
- Copy the layout of a screen that already exists rather than inventing one.

RULES THAT MATTER MORE THAN FINISHING
- A pull request is the only delivery. There is no other way to change anything.
- Never edit an app that is not ours. Customise from one_fm instead.
- Never invent a file, a component, a route or a DocType. Read first; if it is not there, say so.
- Never put a credential, token or password into any file.
- Report what you did NOT verify. A build passing is not the same as a screen looking right, and saying so is more useful than implying you checked.
- If you cannot finish, still call finalize, and name exactly what is missing."""


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
			"actually comes from, reads it, writes Vue components or Frappe desk "
			"JavaScript, compiles the change in an isolated copy of the application, and "
			"delivers it as a pull request. Desk UI records are written to the site "
			"switched off."
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
