app_name = "one_bpmn"
app_title = "ONE BPMN"
app_publisher = "kartiksharma9319@gmail.com"
app_description = "Spiffworkflow integration with Frappe"
app_email = "kartiksharma9319@gmail.com"
app_license = "mit"

# Website route rules for Vue.js frontend
website_route_rules = [
	{"from_route": "/processa/<path:app_path>", "to_route": "processa"},
	{"from_route": "/processa", "to_route": "processa"},
	# WI-001678: the ONE AI chat page. The template folder must stay
	# importable (www/one_ai/index.py), so the pretty route is mapped here
	# rather than named with a hyphen on disk.
	{"from_route": "/one-ai", "to_route": "one_ai"},
]

# Includes in <head>
# ------------------

extend_bootinfo = "one_bpmn.boot.boot_session"

app_include_js = [
	"/assets/one_bpmn/js/bpmn_json_prettify.js",
	"/assets/one_bpmn/js/one_ai_loader.js",
	"/assets/one_bpmn/js/bpmn_form_actions.js?v=6",
	"/assets/one_bpmn/js/bpmn_list_indicator.js",
	"/assets/one_bpmn/js/bpmn_list_actions.js?v=1",
	"/assets/one_bpmn/js/bpmn_cancel_request.js?v=1",
	# WI-002050: an agent's question appears on the document it is about, whatever
	# that document is. Loaded for every form rather than bound to one doctype:
	# the clarification record names a doctype and a document, so it was never
	# Work-Item-specific, and the moment an agent is pointed at anything else a
	# question about it has to surface on that thing. The script asks once which
	# doctypes have ever had a question asked about them and does nothing on the
	# rest, so a form nobody has ever asked about costs no round trip.
	# ?v= as above — a plain path gets no automatic cache-busting.
	"/assets/one_bpmn/js/ai_clarification_on_document.js?v=1",
]

# Purge action on the AI Memory list view, mirroring the memory browser's
# Purge button. Calls the same one_bpmn.api.memory_api.purge_memories.
doctype_list_js = {
	"AI Memory": "public/js/ai_memory_list.js",
}

# Installation
# ------------

after_install = [
	"one_bpmn.install.after_install",
	"one_bpmn.processa_connectors.seed.import_seed_manifests",
]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# WI-001744: scope AI Evals doctypes to the process owner (System Manager sees all).
permission_query_conditions = {
	"AI Eval Suite": "one_bpmn.agents.eval_permissions.eval_suite_query_conditions",
	"AI Eval Case": "one_bpmn.agents.eval_permissions.eval_case_query_conditions",
	"AI Eval Run": "one_bpmn.agents.eval_permissions.eval_run_query_conditions",
	# Your own memories plus the shared ones; a System Manager sees everybody's.
	# Enforced here so it holds for the browser, the Desk list and any report,
	# instead of being re-stated at each call site.
	"AI Memory": "one_bpmn.agents.memory.permissions.ai_memory_query_conditions",
	# A conversation with an agent is private to the person who had it. Enforced
	# here so it holds for the list, the Desk, any report and /api/resource alike.
	"Chat Message": "one_bpmn.agents.chat_permissions.chat_message_query_conditions",
	"Doctype Change Request": "one_bpmn.one_bpmn.doctype.doctype_change_request.doctype_change_request.get_permission_query_conditions",
}

has_permission = {
	"AI Eval Suite": "one_bpmn.agents.eval_permissions.eval_suite_has_permission",
	"AI Eval Case": "one_bpmn.agents.eval_permissions.eval_case_has_permission",
	"AI Eval Run": "one_bpmn.agents.eval_permissions.eval_run_has_permission",
	"AI Memory": "one_bpmn.agents.memory.permissions.ai_memory_has_permission",
	"Chat Message": "one_bpmn.agents.chat_permissions.chat_message_has_permission",
	"Doctype Change Request": "one_bpmn.one_bpmn.doctype.doctype_change_request.doctype_change_request.has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# WI-002055: the jobs that WAKE parked agent work get a queue of their own.
# Frappe derives a scheduled job's queue from its frequency alone, so a Cron job
# is always on "default" — shared here with 172 other enabled jobs. A long job
# ahead of them means a finished delegation still reads as running and a passed
# deadline goes unnoticed until it clears. Agent turns already have their own
# worker for this reason; this gives the same to the clock that wakes them.
#
# Our three methods only. Every other scheduled job on the site falls through to
# Frappe's own behaviour, and ours fall back to "default" unless the site
# actually declares the queue — so this is safe to deploy before the worker.
override_doctype_class = {
	"Scheduled Job Type": "one_bpmn.overrides.scheduled_job_type.ProcessaScheduledJobType",
	"Server Script": "one_bpmn.overrides.server_script.ProcessaServerScript",
}

# Document Events
# ---------------
# Universal BPMN trigger — fires for every DocType.
# processa_engine/triggers.py checks internally whether a matching active BPMN Process
# Model is configured for that doctype + event before doing anything.
# Internal BPMN doctypes are skipped to prevent recursion.

_BPMN_TRIGGER = "one_bpmn.processa_engine.triggers.on_doc_event"

# Guard: blocks native Frappe submit/cancel/workflow-action when a BPMN
# process instance is actively controlling the document.
# Documents with NO active BPMN instance are completely unaffected.
_BPMN_GUARD   = "one_bpmn.processa_engine.triggers.guard_bpmn_document"
_BPMN_DELETE  = "one_bpmn.processa_engine.triggers.delete_linked_bpmn_instances"

# Copies each AI Agent Configuration's prompt, model, temperature and max tokens onto the map shapes that link it.
after_migrate = ["one_bpmn.ai_agent_registry.provisioning.agent_config_resolver.sync_all_shapes_to_configs"]

# Jinja globals for aiUserPrompt templates.
jinja = {
	"methods": [
		"one_bpmn.processa_engine.agent_runtime.turn_state.get_turn",
		"one_bpmn.tools.tool_for_server_scripts.compact_ir",
	]
}

doc_events = {
	"*": {
		# Start new BPMN instances / bidirectional sync
		"after_insert":           _BPMN_TRIGGER,
		"on_update":              _BPMN_TRIGGER,
		"after_save":             _BPMN_TRIGGER,
		"on_submit":              _BPMN_TRIGGER,
		"on_cancel":              _BPMN_TRIGGER,
		"on_update_after_submit": _BPMN_TRIGGER,

		# Gate: block native actions when BPMN is controlling the doc
		"before_submit":          _BPMN_GUARD,
		"before_cancel":          _BPMN_GUARD,
		"before_workflow_action": _BPMN_GUARD,
		"on_trash":               _BPMN_DELETE,
		"onload":                 "one_bpmn.processa_engine.instances.cancellation.set_pending_cancellation_onload",
	},
	# WI-001620: creating a chat agent configuration kicks off the
	# "AI Agent Creation Process" BPMN map via its conditional start event
	# (handled by the universal _BPMN_TRIGGER above) — no dedicated hook.
	# Pre-deployment security gate: structurally validate the body of any
	# Server Script that a BPMN script task references (unrelated Server
	# Scripts pass through untouched).
	"Server Script": {
		"validate": [
			"one_bpmn.security.script_gate.apply_server_script_approval",
			"one_bpmn.security.script_gate.validate_server_script_on_save",
		],
	},
	# WI-001644: PII input screening. The map-driven agents read the user's
	# text back off the stored Chat Message, so redacting the in-flight
	# message is not enough — the stored row has to be redacted too.
	"Chat Message": {
		"before_insert": [
			"one_bpmn.security.pii.screen_chat_message",
			# The output half: the same argument as above, in the other direction.
			# A map-driven agent writes its reply as a Chat Message and the surface
			# reads it back from there, so screening only the in-flight string would
			# be undone by the stored row.
			"one_bpmn.security.output_screening.screen_chat_response",
		],
		"after_insert": [
			# The count and turn-boundary compaction triggers. after_insert, not
			# before: the message this turn produced has to be part of the count,
			# and a failed insert must not leave work queued about it. The handler
			# only ever ENQUEUES — summarising on this thread would put its
			# latency in front of the person waiting for a reply.
			"one_bpmn.agents.memory.compaction_triggers.on_chat_message",
		],
	},
	# WI-001813: the list of Processa-controlled doctypes (used by
	# bpmn_form_actions.js to suppress native Submit/Save/banner) is cached in
	# Redis — drop it whenever a process model is (de)activated or retargeted.
	"BPMN Process Model": {
		"on_update": "one_bpmn.processa_engine.instances.listing.clear_processa_doctype_cache",
		"after_delete": "one_bpmn.processa_engine.instances.listing.clear_processa_doctype_cache",
	},
}

# Scheduled Tasks
# ---------------
# BPMN Timer events run every minute:
# - Timer Start Events: check cron expressions, start new instances
# - Timer Catch Events: resume waiting instances whose timers elapsed

scheduler_events = {
	"cron": {
		# Retention runs once a day, in the small hours: it is the only job here
		# that DELETES anything, and a bounded nightly pass is easier to reason
		# about (and to notice going wrong) than a trickle through the day.
		"30 2 * * *": [
			"one_bpmn.tasks.sweep_conversation_retention",
			# A published rate change has a date but the catalogue has no date
			# field, so something has to notice the day arriving.
			"one_bpmn.tasks.apply_due_model_rates",
			# Soft-retires memories that decayed, were never corroborated, or
			# are minor and old. Sets expires_on with the reason in metadata;
			# deletes nothing.
			"one_bpmn.tasks.prune_ai_memory",
			# Memory search ranks with an exact scan and no vector index, a
			# decision bounded by row counts. Once a day is enough to notice a
			# bound being approached; nothing here acts on it.
			"one_bpmn.tasks.check_ai_memory_volume",
		],
		# A sandbox run whose callback never arrives would leave its agent waiting for good.
		"*/2 * * * *": [
			"one_bpmn.agents_sandbox.sandbox.reaper.reap",
			"one_bpmn.agents_sandbox.sandbox.reaper.reap_sessions",
		],
		"* * * * *": [
			"one_bpmn.processa_engine.timers.process_timer_start_events",
			"one_bpmn.processa_engine.timers.process_timer_catch_events",
			"one_bpmn.a2a.poller.poll_a2a_tasks",
		],
		# WI-002191: try every enabled model's credentials against its provider
		# (a free list call, not a completion), then tell someone about any model
		# that is Unhealthy and has not been announced yet — once per kind of
		# problem. Fifteen minutes is often enough that a fixed key lifts the
		# block before the person who fixed it has moved on, and rare enough to
		# be invisible in the provider's request log.
		"*/15 * * * *": [
			"one_bpmn.ai_agent_registry.model_health.check_ai_model_credentials",
		],
		# A lane job that is killed (worker restart, RQ timeout) never gets to
		# enqueue its own successor or notice it was the last lane home, so a
		# fanned-out run it belonged to would sit on "Running" forever without
		# this. Five minutes is the same cadence as the credential check above
		# and well inside the margin a run's own deadline already carries.
		"*/5 * * * *": [
			"one_bpmn.agents.eval_runner.sweep_stale_eval_runs",
			# A parked AI step whose job was lost from the queue would otherwise wait for the delegation deadline.
			"one_bpmn.processa_engine.timers.requeue_stranded_ai_steps",
		],
		"0 * * * *": [
			"one_bpmn.tasks.close_stale_chat_instances",
			# WI-002050: chase a question nobody has answered. Hourly rather than
			# by the minute because the thing being waited on is a person reading
			# their notifications, and it never resolves the question itself.
			"one_bpmn.tasks.chase_unanswered_clarifications",
			# The TIME compaction trigger. Hourly rather than by the minute
			# because the thing being waited on is a conversation going quiet,
			# and the thresholds that drive it are configured in minutes but
			# meant in tens of minutes.
			"one_bpmn.tasks.compact_idle_conversations",
		],
	}
}

# Cache keys that survive frappe.clear_cache()
# --------------------------------------------
# The stage tools' per-turn store (processa_engine/agent_runtime/turn_state.py) is live state for a running turn.
persistent_cache_keys = ["ait_turn:*"]

# Request Events
# ----------------
after_request = ["one_bpmn.processa_engine.notifications.actions.apply_amp_headers"]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Reuse Frappe's Log Settings for AI Memory retention instead of a custom scheduler.
# 0 = retain indefinitely by default; an administrator can lower it in Log Settings.
default_log_clearing_doctypes = {
	"AI Memory": 0,
}
