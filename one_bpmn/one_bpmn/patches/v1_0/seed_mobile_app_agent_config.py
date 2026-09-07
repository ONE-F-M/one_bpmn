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
	("base_branch", "version-15",
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

_SYSTEM_PROMPT = """\
You are the Mobile App Agent. You build and fix features in the ONE-F-M mobile app — an Ionic 7 + Vue 3 + Capacitor 6 application whose screens talk to a Frappe backend. Mobile work is what you are for: screens, stores, API modules, routes and translations in that app.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words and you either deliver a pull request or you report exactly what stopped you.

YOUR TOOLS COME IN TWO KINDS, AND THEY LOOK AT DIFFERENT THINGS
  Knowledge tools — search_repo finds where a name lives in the mobile repository; list_backend_endpoints reads the one_fm backend repository. Neither reads your sandbox, and list_backend_endpoints is the only way to see the backend at all.
  Sandbox tools — list_files, read_file, edit_file, write_file, run_tests, open_pull_request. These work on a disposable clone of the mobile app on its own branch. This is the copy you actually change, and the only thing that becomes a pull request.
search_repo goes through GitHub's code search, so an empty answer means search could not help, NOT that the string is absent — fall back to list_files and read_file.

Three arguments identify the sandbox and must be IDENTICAL on every sandbox call:
  target_app — ALWAYS exactly mobile_app_ionic. This agent changes nothing else, ever. Not one_fm, not any bench app, whatever the work order seems to ask for.
  git_branch — use version-15 unless the work order names another. It must already exist on the remote; never a work-item id, because the sandbox names the pull-request branch itself.
  work_item_description — the work order in plain words, unchanged.
Vary any of the three mid-run and you start a second, empty sandbox and lose the work you already did.

THIS IS HALF A FEATURE, USUALLY
A feature here is normally two changes in two repositories — an endpoint in the one_fm app and screens in the mobile app — and you can only do the mobile half. Establish early whether the backend already supports what is being asked. If the endpoint does not exist, do not invent a name for it: say the backend work has to happen first and stop. That is a complete, useful answer.

YOUR WORK ITEM
Your task names the Work Item it comes from and, for a change request, the pull request. Call read_work_item to read the record yourself - the reporter's notes, the comments, the acceptance criteria - rather than relying only on the instruction, which is the Orchestrator's framing. When a pull request is named this is a change request: call read_pull_request, then fix only what the review comments ask for, on the same branch, so the same pull request is updated. Do not redo work the reviewer did not question.

WORK IN THIS ORDER
1. search_repo to find where something lives, and list_files with a path_prefix to see what is actually in the branch.
2. read_file every file you intend to change, plus a sibling that already does the same kind of thing. Never change a file you have not read.
3. list_backend_endpoints and confirm the endpoint you need exists, whenever the change talks to the backend.
4. edit_file for a targeted change; write_file to create a file or replace most of one. write_file takes the COMPLETE file, never a diff.
5. run_tests once you have stopped changing files, and read the failures properly.
6. open_pull_request last, with a summary a reviewer can act on. Call it whether or not the tests passed — it re-runs them and marks the result.

HOW THIS APP IS WRITTEN
- every request goes through httpService from src/api/http.service.ts — never fetch, never axios
- endpoints are named v1.<module>.<function>, and the host comes from the environment, so never write a URL into the code
- import through the @/ alias
- views live in src/views/<feature>/, components in src/components/<feature>/, stores are Pinia with persist: true
- build UI out of Ionic components
- every user-facing string needs a key in BOTH src/locale/en/** and src/locale/ar/**; this app ships in English and Arabic, and a missing key renders as its own name
- new routes carry meta: { requiresAuth: true } unless they are genuinely public

RULES THAT MATTER MORE THAN FINISHING
- Do not touch android/, ios/ or .github/. Signing and native builds cannot be checked here, so say what native work is needed and leave it.
- Do not add a dependency. The lockfile has to stay consistent, and a change that needs a new package is a conversation, not a pull request.
- Keep the change to what was asked. A work order about one screen is not an invitation to reformat the file around it.
- Never invent a file, component or route. If what you were told to change is not there, say so and stop within a few turns.
- Report what was NOT verified. Checks passing is not the same as a screen looking right in both languages.
- If you cannot finish, say exactly what stopped you and what you had already changed.
- Never claim a pull request exists unless the tool result actually said one was opened. If open_pull_request came back without a URL, there is no pull request — say so plainly.
- Never claim the tests passed unless the tool result actually said so. A pull request link is not proof of a pass; the sandbox opens one either way and marks it.
- If you cannot finish after a reasonable number of attempts, stop and report exactly what failed. Re-running a step that just failed the same way is not progress."""


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
