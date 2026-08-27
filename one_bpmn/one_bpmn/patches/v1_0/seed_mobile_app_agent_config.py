"""
Seed the AI Agent Configuration for the Mobile App Agent.

The Mobile App Agent implements features and fixes bugs in the ONE-F-M Ionic
mobile app from a work order an orchestrator delegates to it over A2A, and
delivers every change as a pull request. It is a *background* agent: no chat
surface, no conversation.

WHY THIS PATCH SHIPS NOTHING BUT CONFIGURATION
----------------------------------------------
This agent has no Python at all. Its map reaches GitHub through
``frappe.integrations.utils`` and decodes blobs with ``base64`` — both of which
the script gate permits — so every rule it applies, every path it refuses and
every line of its pull request body lives in a Server Script a process owner can
read and change without a developer or a deploy. There is deliberately no
``one_bpmn`` import anywhere in it.

The BPMN Process Model and its Server Scripts are NOT installed here either:
Processa moves a diagram between environments through export/import in the
editor, and ``config_export_import.export_bpmn_config`` already collects every
Server Script the diagram references. A patch that also wrote the XML or the
script bodies would create a second source of truth to drift from the exported
one. The configuration is the one record no export carries, so it is the one
thing a patch is right for.

The repositories the agent may touch are seeded as CONSTANTS rather than left to
the model. They are read by the map's "Read Work Order" step, so no tool takes a
repository argument and the model has no parameter through which to point a pull
request somewhere it was never meant to go.

Idempotent, and safe on a site that has not imported the map yet — the agent only
goes Live once its map is present and validation passes.
"""

import frappe

_AGENT_NAME = "Mobile App Agent"
_AGENT_ID = "mobile_app_agent"
_PROCESS_MODEL = "Mobile App Agent"
_ORCHESTRATOR = "Orchestrator Agent"

# Writing Vue against an unfamiliar codebase from a plain-words brief is exacting
# work, so this is deliberately not a cheap model.
_PREFERRED_MODELS = ("claude-sonnet-5", "claude-sonnet-4-5-20250929")

# The mobile app, and the backend whose endpoints it calls. The second is READ
# ONLY: the agent checks what exists there, and never changes it.
_CONSTANTS = [
	("repo", "ONE-F-M/mobile_app_ionic",
	 "The only repository this agent may read or raise a pull request against."),
	("base_branch", "staging",
	 "Branch every pull request is opened against."),
	("work_ref", "staging",
	 "Branch the agent reads code from. Point it elsewhere to work against a different line of development."),
	("backend_repo", "ONE-F-M/one_fm",
	 "Repository holding the one_fm.api.v1 endpoints the app calls. Read only — the agent never changes it."),
	("backend_ref", "staging",
	 "Branch the backend endpoint catalogue is read from."),
]

_DELEGATE_PURPOSE = (
	"Changes the ONE-F-M Ionic mobile app — screens, stores, API modules, routes and "
	"translations — from a plain-words work order, and delivers it as a pull request. "
	"Mobile half only: backend endpoints stay in one_fm."
)

_SYSTEM_PROMPT = """You are the Mobile App Agent. You make changes to the ONE-F-M mobile app — an Ionic 7 + Vue 3 + Capacitor 6 application whose screens talk to a Frappe backend.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words, and you either deliver a pull request or you report exactly what stopped you.

You do not have the app running. You cannot build it, you cannot open a screen, and you cannot run its tests. Everything you produce is read by a person before it merges, and saying so honestly is part of the job — not a disclaimer you add at the end.

Work in this order.

1. Read before you write. Call read_repo_map to see what is actually in the repository, and read_file on every file you are about to change. Never edit a file you have not read this turn. search_repo helps you find where something lives; an empty result there means search could not help, not that the code is absent.

2. Work out whether the backend already supports what is being asked. Call list_backend_endpoints. A feature here is usually TWO changes in TWO repositories — an endpoint in the one_fm app and screens in the mobile app — and you can only do the mobile half. If the endpoint you need does not exist, do not invent a name for it: stage nothing that calls it, and say in your summary that the backend work has to happen first.

3. Stage the complete change. Call stage_change once per file, passing the entire new text of that file, never a diff or a fragment. Follow what the surrounding code already does:
   - every request goes through httpService from src/api/http.service.ts — never fetch, never axios
   - endpoints are named v1.<module>.<function>, and the host comes from the environment, so never write a URL into the code
   - import through the @/ alias
   - views live in src/views/<feature>/, components in src/components/<feature>/, stores are Pinia with persist: true
   - build UI out of Ionic components
   - every user-facing string needs a key in BOTH src/locale/en/** and src/locale/ar/**; this app ships in English and Arabic, and a missing key renders as its own name
   - new routes carry meta: { requiresAuth: true } unless they are genuinely public

4. Call review_change. It enforces the rules above against what you actually staged, so it catches what you missed rather than what you intended. If it reports issues, fix them by staging corrected files and review again. Never raise a pull request that has not passed review clean.

5. Call open_pull_request with a title a reviewer can read in a list and a body saying what changed and why. It branches off the configured base branch and leaves the work for review — nothing you do merges anything.

6. Call finalize exactly once, last, with a summary a non-developer can act on.

Rules that matter more than finishing:
- Never claim something works. You have not run it. Say what you changed and that it is unverified.
- Do not touch android/, ios/ or .github/. You cannot build or sign the app, so you cannot tell whether a change there is safe. If native work is needed, name it and leave it.
- Do not add a dependency. You cannot run an install, so editing package.json would produce a branch that does not build.
- Keep the change to what was asked. A work order about one screen is not an invitation to reformat the file around it.
- If you cannot finish, still call finalize, and name exactly what stopped you."""


def execute():
	owner = _process_owner()

	config = {
		"agent_name": _AGENT_NAME,
		"agent_id": _AGENT_ID,
		"agent_framework": "Anthropic",
		"agent_type": "Background",
		"enabled": 1,
		"description": (
			"Implements features and fixes bugs in the ONE-F-M Ionic mobile app from a "
			"delegated work order: reads the repository, checks what the one_fm backend "
			"already exposes, stages a changeset, gates it against this codebase's house "
			"rules, and raises a pull request for a person to review."
		),
		"system_prompt": _SYSTEM_PROMPT,
		"temperature": 0.2,
		# 0 resolves to the 1024 default at dispatch, which truncates tool arguments —
		# and this agent's arguments carry whole source files.
		"max_tokens": 32768,
		"surface_type": "Conversation",
		"artifact_type": "Script",
		"icon": "\U0001F4F1",
		"collect_feedback": 1,
		# A2A exposure is what lets an orchestrator pick this agent as a delegation
		# target at all (a2a.local.local_agent_choices filters on it); the tags are
		# what a selector matches a work order against.
		"a2a_exposed": 1,
		"a2a_skill_tags": "mobile, ionic, vue, frontend, mobile app, bug fix, pull request",
		"max_recursion_depth": 5,
		"max_task_handoffs": 10,
		"delegation_deadline_minutes": 60,
		# It reads source off GitHub and folds it into its own prompt, so the injection
		# surface is real: screen input, flag output.
		"pii_screening": "Enabled",
		"injection_screening": "Enabled",
		"injection_action": "Flag",
		"output_screening_mode": "Flag",
	}
	if owner:
		config["process_owner"] = owner

	# The model is a catalog link and the provider credentials are derived from it.
	# Neither is invented: a site with no Anthropic model in the catalog gets the
	# agent in Draft rather than a config pointing at a record that is not there.
	model = _pick_model()
	if model:
		config["ai_model"] = model

	constants = []
	for name, value, description in _CONSTANTS:
		constants.append({
			"constant_name": name,
			"constant_value": value,
			"constant_type": "String",
			"description": description,
		})

	if frappe.db.exists("AI Agent Configuration", _AGENT_NAME):
		doc = frappe.get_doc("AI Agent Configuration", _AGENT_NAME)
		doc.update(config)
		# Constants are replaced wholesale rather than merged: a stale repository left
		# behind by an earlier seed would silently keep aiming the pull requests.
		doc.set("constants", constants)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			**config,
			"constants": constants,
		})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=False)

	# Link the map only when it is here — the diagram arrives by import, which may
	# happen before or after this patch runs.
	if frappe.db.exists("BPMN Process Model", _PROCESS_MODEL) and doc.process_model != _PROCESS_MODEL:
		doc.db_set("process_model", _PROCESS_MODEL, update_modified=False)
		doc.reload()

	_allow_as_delegate()
	_take_live(doc)


def _allow_as_delegate():
	"""Let the orchestrator hand work to this agent.

	``a2a_exposed`` only makes the agent OFFERABLE. When the orchestrator restricts
	its delegates — and it does — a target missing from that table is refused before
	anything is created, so the shape on the diagram would exist and never fire.
	"""
	if not frappe.db.exists("AI Agent Configuration", _ORCHESTRATOR):
		return
	orchestrator = frappe.get_doc("AI Agent Configuration", _ORCHESTRATOR)
	if not orchestrator.restrict_delegates:
		return
	for row in orchestrator.allowed_delegates:
		if row.agent_configuration == _AGENT_NAME:
			return
	orchestrator.append("allowed_delegates", {
		"agent_configuration": _AGENT_NAME,
		"purpose": _DELEGATE_PURPOSE,
	})
	orchestrator.save(ignore_permissions=True)


def _process_owner():
	"""Reuse the owner a sibling agent already has, if one is set."""
	for sibling in ("Connector Agent", "Docu Agent", "logix", "prosally"):
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

	The adversarial go-live gate applies to CHAT agents — a background worker has no
	chat surface to attack — so a Background agent needs only the standard
	configuration validation, which includes a live provider test call.
	"""
	if not doc.process_model:
		return  # no map yet: a person imports it, then saves to revalidate

	from one_bpmn.agents.agent_provisioning import validate_agent_config

	try:
		outcome = validate_agent_config(doc.name, test_provider=True)
	except Exception:
		frappe.log_error(
			title="Mobile App Agent: validation raised while seeding",
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
