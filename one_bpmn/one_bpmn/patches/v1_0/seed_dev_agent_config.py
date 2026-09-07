"""
Seed the AI Agent Configuration for the Dev Agent.

The Dev Agent turns a work order into a tested, working change: an
orchestrator delegates a development task to it over A2A, it dispatches the
work to an isolated Cloud Run sandbox (a disposable clone of the target app
with its own MariaDB/Redis, never the running site), waits for the
sandbox's real test suite to pass or fail, and — only on a pass — delivers
the change as a pull request. It is a *background* agent: no chat surface,
no conversation. Mirrors seed_connector_agent_config.py's shape exactly;
see that file's docstring for why a patch seeds the configuration but never
the BPMN Process Model or its scripts.

The sandbox itself carries no agent identity of its own — every piece of
its behaviour (this system prompt, its tools, its skills) is resolved from
THIS configuration at dispatch time and handed to it as a request payload.
That is deliberate: the sandbox is a disposable, config-free execution
environment, not a second copy of the agent that could drift from this one.
"""

import frappe

_AGENT_NAME = "Dev Agent"
_AGENT_ID = "dev_agent"
_PROCESS_MODEL = "Dev Agent"

# Running a real test suite against a disposable clone of an actual app is a
# long, exacting job with real code on the other end — not a cheap model.
_PREFERRED_MODELS = ("claude-sonnet-5", "claude-sonnet-4-5-20250929")

_SYSTEM_PROMPT = """\
You are the Dev Agent. You take a development work order — a bug, a small feature, a failing test — and turn it into a reviewed-ready pull request, or you report exactly what stopped you.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words, naming the app it belongs to and the branch to work from, and you either finish the job or you report exactly what stopped you.

HOW YOUR TOOLS WORK
Your code never runs on the live site. Every file tool operates inside an isolated, disposable sandbox — a fresh clone of the target app with its own database, thrown away after the run. A failed attempt costs nothing but the sandbox that tried it.

Three arguments identify that sandbox and must be IDENTICAL on every single call:
  target_app — the app being changed, e.g. one_bpmn. Take it from the work order; a folder inside an app is not an app.
  git_branch — the branch to start FROM, and it must already exist on the remote. Use staging unless the work order names another. Never a work-item id: the sandbox names the pull-request branch itself.
  work_item_description — the work order in plain words, unchanged.
Vary any of the three mid-run and you start a second, empty sandbox and lose the work you already did.

YOUR WORK ITEM
Your task names the Work Item it comes from and, for a change request, the pull request. Call read_work_item to read the record yourself - the reporter's notes, the comments, the acceptance criteria - rather than relying only on the instruction, which is the Orchestrator's framing. When a pull request is named this is a change request: call read_pull_request, then fix only what the review comments ask for, on the same branch, so the same pull request is updated. Do not redo work the reviewer did not question.

WORK IN THIS ORDER
1. list_files with a path_prefix to see what is actually there. Never guess a path.
2. read_file every file you intend to change, plus a sibling that already does the same kind of thing so yours matches how they are written.
3. edit_file for a targeted change; write_file to create a file or replace most of one. write_file takes the COMPLETE file, never a diff.
4. run_tests once you have stopped changing files, and read the failures properly rather than guessing at a cause the output does not support.
5. open_pull_request last, with a summary a non-developer can act on. Call it whether or not the tests passed — it re-runs them itself and marks the pull request clearly if they fail.

RULES THAT MATTER MORE THAN FINISHING
- Never invent a file, function or DocType. If what you were told to change is not there, say so and stop within a few turns.
- Never invent a secret, API key, token or credential, and never write one into a file.
- If the work order does not say which app or which branch, say so and stop — do not guess at a target you were not given.
- Report what you did NOT verify, and if you could not finish, name exactly what failed.
- Never claim a pull request exists unless the tool result actually said one was opened. If open_pull_request came back without a URL, there is no pull request — say so plainly.
- Never claim the tests passed unless the tool result actually said so. A pull request link is not proof of a pass; the sandbox opens one either way and marks it.
- If you cannot finish after a reasonable number of attempts, stop and report exactly what failed. Re-running a step that just failed the same way is not progress."""


def execute():
	owner = _process_owner()

	config = {
		"agent_name": _AGENT_NAME,
		"agent_id": _AGENT_ID,
		# Transitional field, still mandatory. The map's AI Agent Task carries the
		# real backend (direct_api); this mirrors Docu, Connector Agent, and LuCrusher.
		"agent_framework": "Anthropic",
		"agent_type": "Background",
		"enabled": 1,
		"description": (
			"Turns a delegated development work order into a tested pull request: "
			"dispatches the change to an isolated Cloud Run sandbox, runs the "
			"target app's real test suite there, and delivers a passing change as "
			"a PR — never touching the running site directly."
		),
		"system_prompt": _SYSTEM_PROMPT,
		"temperature": 0.2,
		"max_tokens": 32768,
		"surface_type": "Conversation",
		"artifact_type": "Record",
		"icon": "🛠️",
		# A2A exposure is what lets an orchestrator pick this agent as a delegation
		# target at all (a2a.local.local_agent_choices filters on it); the tags are
		# what a selector matches a work order against.
		"a2a_exposed": 1,
		"a2a_skill_tags": "development, coding, bug-fix, testing, pull-request",
		"max_recursion_depth": 5,
		"max_task_handoffs": 10,
		# A sandbox run can genuinely take several minutes (clone + install +
		# real test suite) — longer than the Connector Agent's 60, which never
		# waits on anything slower than an HTTP call.
		"delegation_deadline_minutes": 120,
		"pii_screening": "Enabled",
		"injection_screening": "Enabled",
		"injection_action": "Flag",
		"output_screening_mode": "Flag",
	}
	if owner:
		config["process_owner"] = owner

	# The model is a catalog link and the provider credentials are derived from
	# it. Neither is invented: a site with no Anthropic model in the catalog
	# gets the agent in Draft rather than a config pointing at a record that is
	# not there.
	model = _pick_model()
	if model:
		config["ai_model"] = model

	if frappe.db.exists("AI Agent Configuration", _AGENT_NAME):
		doc = frappe.get_doc("AI Agent Configuration", _AGENT_NAME)
		doc.update(config)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			**config,
		})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=False)

	# Link the map only when it is here — the diagram arrives by import, which
	# may happen before or after this patch runs.
	if frappe.db.exists("BPMN Process Model", _PROCESS_MODEL) and doc.process_model != _PROCESS_MODEL:
		doc.db_set("process_model", _PROCESS_MODEL, update_modified=False)
		doc.reload()

	_take_live(doc)

	# Process-owner User Permission (same pattern as the other agent seeds).
	if owner and not frappe.db.exists(
		"User Permission",
		{"user": owner, "allow": "User", "for_value": owner, "applicable_for": "AI Agent Configuration"},
	):
		frappe.get_doc({
			"doctype": "User Permission",
			"user": owner,
			"allow": "User",
			"for_value": owner,
			"applicable_for": "AI Agent Configuration",
			"apply_to_all_doctypes": 0,
			"hide_descendants": 0,
		}).insert(ignore_permissions=True, ignore_if_duplicate=False)


def _process_owner():
	"""Reuse the owner the sibling agents already have, if one is set."""
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

	The adversarial go-live gate applies to CHAT agents — a background worker
	has no chat surface to attack — so a Background agent needs only the
	standard configuration validation, which includes a live provider test call.
	"""
	if not doc.process_model:
		return  # no map yet: a person imports it, then saves to revalidate

	from one_bpmn.agents.agent_provisioning import validate_agent_config

	try:
		outcome = validate_agent_config(doc.name, test_provider=True)
	except Exception:
		frappe.log_error(
			title="Dev Agent: validation raised while seeding",
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
