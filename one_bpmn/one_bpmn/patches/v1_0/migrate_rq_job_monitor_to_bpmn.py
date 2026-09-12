"""
WI-002205: Replace onefm_mcp's google-adk RQ Job Monitoring Agent with a native
BPMN Process Model ("RQ Job Monitor", exported at one_bpmn/exports/rq_job_monitor.bpmn).

Mirrors the pattern already used twice in this app for the same kind of move
(promote_threat_agents_to_bpmn.py, seed_dev_agent_config.py):

1. Server Scripts and AI Agent Configuration records are the things this patch
   creates directly — the process map itself is imported from the checked-in
   .bpmn export (import_bpmn, the same function the editor's Import button
   calls) rather than authored inline here, so the .bpmn file stays the single
   source of truth for the diagram.
2. Two NEW AI Agent Configuration records are needed, not a reuse of the old
   "RQ Job Monitor" config's two sub_prompts rows: each AI Agent Task gets
   exactly one system_prompt from its linked config (agent_config_resolver.py's
   _CONFIG_TO_SHAPE has no per-sub-prompt selector), so the two LLM roles
   (dedup, ticket matching) need one config each — same shape as
   "Threat Source Expander" / "Threat Keyword Generator".
3. Both configs are agent_type="Background" (no chat surface) and go Live via
   validate_agent_config()'s standard checks — NOT provision_agent()'s
   adversarial gate, which is chat-only (agent_provisioning.py:163-169).

The old "RQ Job Monitor" config (agent_id="rq_job_monitor") is left untouched
here — it's retired in the Phase 3 cutover patch once the new map is verified,
not deleted as a side effect of this one.
"""

import os

import frappe

_DEDUP_CONFIG = "RQ Job Deduplicator"
_MATCHER_CONFIG = "RQ Job Ticket Matcher"
_PROCESS_MODEL = "RQ Job Monitor"
_AI_MODEL = "claude-haiku-4-5-20251001"

_DEDUP_SYSTEM_PROMPT = """You are a precise RQ Job deduplication agent. Your job is to analyze a list of failed RQ jobs and identify the unique failures.

STRICT MATCHING CRITERIA:
Jobs are considered duplicates ONLY if ALL of these conditions are met:
- The job_name is EXACTLY the same (case-sensitive, no partial matches).
- The exc_info (exception type and message) is EXACTLY the same (e.g., both have "KeyError: 'missing_key'")

DIFFERENT FAILURES - Always treat as unique if ANY of these differ:
- Different job_name (e.g., "send_email" vs "process_data")
- Different exc_info (e.g., "KeyError" vs "TimeoutError", or different error messages)

ULTRA CONSERVATIVE - If there is ANY doubt about whether jobs are identical, treat them as unique.

RESPONSE FORMAT:
Respond with a single JSON object: {"unique_names": ["<name of first unique job>", "<name of second unique job>", ...]}
The "name" values are the "name" field from the input jobs (their unique id, not job_name) — keep exactly one job per group of duplicates. No explanations, no markdown, just the JSON object."""

_MATCHER_SYSTEM_PROMPT = """You are a precise technical support ticket analyzer. Your job is to determine, for each failed RQ Job you are given, whether it represents THE EXACT SAME ISSUE as any of the existing HD Tickets provided.

STRICT MATCHING CRITERIA:
Only treat a job as matching a ticket if ALL of these conditions are met:
1. The RQ Job job_name is EXACTLY the same as mentioned in the HD ticket subject (not just similar or related).
2. The exception type in exc_info is EXACTLY the same (e.g., both have "KeyError", both have "ConnectionTimeout").
3. The root cause described in exc_info is EXACTLY the same problem.
4. The error context (what was being processed) is the same or very similar.

DIFFERENT ISSUES - Always treat as no match for:
- Different job names (e.g., "send_email" vs "process_attendance").
- Different exception types (e.g., "KeyError" vs "TimeoutError").
- Different root causes (e.g., "missing key 'password'" vs "database connection failed").
- Different modules/systems (e.g., email system vs attendance system).
- Generic ticket subjects like "System Error" or "Job Failed" (too vague).

ULTRA CONSERVATIVE - If there is ANY doubt about whether a job and a ticket are the exact same issue, treat it as no match. 95% of cases should have no match unless they are truly identical failures.

RESPONSE FORMAT:
Respond with a single JSON object: {"decisions": [{"job_name": "<the job's own \\"name\\" field>", "ticket_name": "<the matched HD Ticket's \\"name\\" field, or null if no match>"}, ...]}
Include exactly one entry per job you were given, in the same order. No explanations, no markdown, just the JSON object."""

_FETCH_FAILED_JOBS_SCRIPT = """from frappe.utils import now_datetime, add_to_date

cutoff = add_to_date(now_datetime(), minutes=-30)
jobs = frappe.get_all(
	"RQ Job",
	filters={"status": "failed", "ended_at": [">", cutoff]},
	fields=["name", "job_name", "exc_info", "arguments"],
)
result["failed_jobs"] = jobs
"""

_FETCH_OPEN_TICKETS_SCRIPT = """unique_names = set((task_data.get("dedup_result") or {}).get("unique_names") or [])
failed_jobs = task_data.get("failed_jobs") or []
result["unique_failed_jobs"] = [j for j in failed_jobs if j.get("name") in unique_names]

result["open_tickets"] = frappe.get_all(
	"HD Ticket",
	filters={"status": ["not in", ["Resolved", "Closed"]], "custom_reference_doctype": "RQ Job"},
	fields=["name", "subject", "description"],
)
"""

_CREATE_TICKETS_SCRIPT = """MAX_SUBJECT_LENGTH = 140

decisions = (task_data.get("match_result") or {}).get("decisions") or []
jobs_by_name = {j.get("name"): j for j in (task_data.get("unique_failed_jobs") or [])}

created = []
for decision in decisions:
	if decision.get("ticket_name"):
		continue  # matched an existing ticket -- nothing to create

	job = jobs_by_name.get(decision.get("job_name"))
	if not job:
		continue

	job_name = job.get("job_name") or "Unknown Job"
	description = (
		"<p><a href='/app/rq-job/{0}'>View RQ Job</a></p>"
		"<p><b>Exception:</b><br>{1}</p>"
		"<p><b>Arguments:</b><br>{2}</p>"
	).format(
		frappe.utils.escape_html(job.get("name") or ""),
		frappe.utils.escape_html(job.get("exc_info") or ""),
		frappe.utils.escape_html(job.get("arguments") or ""),
	)

	ticket = frappe.new_doc("HD Ticket")
	ticket.subject = job_name[:MAX_SUBJECT_LENGTH]
	ticket.description = description
	ticket.status = "Draft"
	ticket.custom_reference_doctype = "RQ Job"
	ticket.custom_ticket_category = "Process Issue"
	ticket.raised_by = "Administrator"
	ticket.flags.ignore_permissions = True
	ticket.insert()
	created.append(ticket.name)

result["created_tickets"] = created
"""


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")

		_create_server_scripts()
		_import_process_model()
		_seed_config(_DEDUP_CONFIG, "rq_job_deduplicator", _DEDUP_SYSTEM_PROMPT)
		_seed_config(_MATCHER_CONFIG, "rq_job_ticket_matcher", _MATCHER_SYSTEM_PROMPT)
	finally:
		frappe.set_user(original_user)

	frappe.db.commit()


def _create_server_scripts():
	from one_bpmn.api.server_script_api import create_server_script

	create_server_script(
		script_name="RQ Job Monitor - Fetch Failed Jobs",
		script_type="API",
		script=_FETCH_FAILED_JOBS_SCRIPT,
	)
	create_server_script(
		script_name="RQ Job Monitor - Fetch Open Tickets",
		script_type="API",
		script=_FETCH_OPEN_TICKETS_SCRIPT,
	)
	create_server_script(
		script_name="RQ Job Monitor - Create Tickets",
		script_type="API",
		script=_CREATE_TICKETS_SCRIPT,
	)


def _import_process_model():
	if frappe.db.exists("BPMN Process Model", _PROCESS_MODEL):
		return  # re-importing on every migrate would fight manual edits made in the editor

	import one_bpmn

	app_root = os.path.dirname(os.path.dirname(os.path.abspath(one_bpmn.__file__)))
	bpmn_path = os.path.join(app_root, "exports", "rq_job_monitor.bpmn")
	with open(bpmn_path, encoding="utf-8") as f:
		xml_content = f.read()

	from one_bpmn.api.process_map_api import import_bpmn

	import_bpmn(xml_content=xml_content, title=_PROCESS_MODEL)


def _seed_config(agent_name: str, agent_id: str, system_prompt: str):
	config = {
		"agent_name": agent_name,
		"agent_id": agent_id,
		"agent_type": "Background",
		"enabled": 1,
		"system_prompt": system_prompt,
		"required_variables": "[]",
	}

	owner = _process_owner()
	if owner:
		config["process_owner"] = owner

	if frappe.db.exists("AI Model", _AI_MODEL):
		config["ai_model"] = _AI_MODEL

	if frappe.db.exists("AI Agent Configuration", agent_name):
		doc = frappe.get_doc("AI Agent Configuration", agent_name)
		doc.update(config)
	else:
		doc = frappe.get_doc({"doctype": "AI Agent Configuration", **config})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=False)
		doc = frappe.get_doc("AI Agent Configuration", agent_name)
		doc.update(config)

	if frappe.db.exists("BPMN Process Model", _PROCESS_MODEL) and doc.process_model != _PROCESS_MODEL:
		doc.process_model = _PROCESS_MODEL

	doc.save(ignore_permissions=True)
	_take_live(doc)


def _process_owner():
	return frappe.db.get_value("AI Agent Configuration", "RQ Job Monitor", "process_owner")


def _take_live(doc):
	if not doc.process_model:
		return  # no map yet -- a person imports it, then saves to revalidate

	from one_bpmn.agents.agent_provisioning import validate_agent_config

	try:
		outcome = validate_agent_config(doc.name, test_provider=True)
	except Exception:
		frappe.log_error(
			title=f"{doc.name}: validation raised while seeding",
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
	frappe.cache.delete_value(f"agent_config:{doc.agent_id}")
