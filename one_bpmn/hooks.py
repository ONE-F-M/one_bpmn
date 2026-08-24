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

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "one_bpmn",
# 		"logo": "/assets/one_bpmn/logo.png",
# 		"title": "ONE BPMN",
# 		"route": "/one_bpmn",
# 		"has_permission": "one_bpmn.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/one_bpmn/css/one_bpmn.css"
app_include_js = [
	"/assets/one_bpmn/js/bpmn_json_prettify.js",
	# WI-001678: tiny stub defining window.oneAI.openAgentChat — surfaces like
	# the AI Agent Configuration Chat button lazy-load the real bundle on use.
	"/assets/one_bpmn/js/one_ai_loader.js",
	# ?v= is a manual cache-buster — bump it any time this file changes.
	# Plain app_include_js paths (not *.bundle.js) get no automatic
	# versioning from Frappe, and this file has a 12h Cache-Control on
	# /assets/ — without a version bump, browsers can keep serving a
	# stale copy indefinitely even across hard reloads.
	"/assets/one_bpmn/js/bpmn_form_actions.js?v=3",
	"/assets/one_bpmn/js/bpmn_list_indicator.js",
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

# include js, css files in header of web template
# web_include_css = "/assets/one_bpmn/css/one_bpmn.css"
# web_include_js = "/assets/one_bpmn/js/one_bpmn.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "one_bpmn/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "one_bpmn/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "one_bpmn.utils.jinja_methods",
# 	"filters": "one_bpmn.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "one_bpmn.install.before_install"
# after_install = "one_bpmn.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "one_bpmn.uninstall.before_uninstall"
# after_uninstall = "one_bpmn.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "one_bpmn.utils.before_app_install"
# after_app_install = "one_bpmn.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "one_bpmn.utils.before_app_uninstall"
# after_app_uninstall = "one_bpmn.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "one_bpmn.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# WI-001744: scope AI Evals doctypes to the process owner (System Manager sees all).
permission_query_conditions = {
	"AI Eval Suite": "one_bpmn.agents.eval_permissions.eval_suite_query_conditions",
	"AI Eval Case": "one_bpmn.agents.eval_permissions.eval_case_query_conditions",
	"AI Eval Run": "one_bpmn.agents.eval_permissions.eval_run_query_conditions",
}

has_permission = {
	"AI Eval Suite": "one_bpmn.agents.eval_permissions.eval_suite_has_permission",
	"AI Eval Case": "one_bpmn.agents.eval_permissions.eval_case_has_permission",
	"AI Eval Run": "one_bpmn.agents.eval_permissions.eval_run_has_permission",
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
}

# Document Events
# ---------------
# Universal BPMN trigger — fires for every DocType.
# trigger.py checks internally whether a matching active BPMN Process
# Model is configured for that doctype + event before doing anything.
# Internal BPMN doctypes are skipped to prevent recursion.

_BPMN_TRIGGER = "one_bpmn.one_bpmn.trigger.on_doc_event"

# Guard: blocks native Frappe submit/cancel/workflow-action when a BPMN
# process instance is actively controlling the document.
# Documents with NO active BPMN instance are completely unaffected.
_BPMN_GUARD   = "one_bpmn.one_bpmn.trigger.guard_bpmn_document"
_BPMN_DELETE  = "one_bpmn.one_bpmn.trigger.delete_linked_bpmn_instances"

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
	},
	# WI-001620: creating a chat agent configuration kicks off the
	# "AI Agent Creation Process" BPMN map via its conditional start event
	# (handled by the universal _BPMN_TRIGGER above) — no dedicated hook.
	# Pre-deployment security gate: structurally validate the body of any
	# Server Script that a BPMN script task references (unrelated Server
	# Scripts pass through untouched).
	"Server Script": {
		"validate": "one_bpmn.security.script_gate.validate_server_script_on_save",
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
	},
	# WI-001813: the list of Processa-controlled doctypes (used by
	# bpmn_form_actions.js to suppress native Submit/Save/banner) is cached in
	# Redis — drop it whenever a process model is (de)activated or retargeted.
	"BPMN Process Model": {
		"on_update": "one_bpmn.api.instance_api.clear_processa_doctype_cache",
		"after_delete": "one_bpmn.api.instance_api.clear_processa_doctype_cache",
	},
}

# Scheduled Tasks
# ---------------
# BPMN Timer events run every minute:
# - Timer Start Events: check cron expressions, start new instances
# - Timer Catch Events: resume waiting instances whose timers elapsed

scheduler_events = {
	"cron": {
		"* * * * *": [
			"one_bpmn.tasks.process_timer_start_events",
			"one_bpmn.tasks.process_timer_catch_events",
			"one_bpmn.tasks.poll_a2a_tasks",
		],
		"0 * * * *": [
			"one_bpmn.tasks.close_stale_chat_instances",
			# WI-002050: chase a question nobody has answered. Hourly rather than
			# by the minute because the thing being waited on is a person reading
			# their notifications, and it never resolves the question itself.
			"one_bpmn.tasks.chase_unanswered_clarifications",
		],
	}
}

# Testing
# -------

# before_tests = "one_bpmn.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "one_bpmn.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "one_bpmn.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Cache keys that survive frappe.clear_cache()
# --------------------------------------------
# `docu_turn::*` lived here: Docu's enqueue-and-poll chat kept each running
# turn's result in a cache entry that a global wipe would destroy mid-turn.
# WI-001679 deleted that endpoint pair — Docu streams over the shared AG-UI
# endpoint now, and a stream needs no handle to survive a cache wipe — so
# nothing in this app requires an exemption any more.

# Request Events
# ----------------
# before_request = ["one_bpmn.utils.before_request"]
after_request = ["one_bpmn.api.todo_actions.apply_amp_headers"]

# Job Events
# ----------
# before_job = ["one_bpmn.utils.before_job"]
# after_job = ["one_bpmn.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"one_bpmn.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Reuse Frappe's Log Settings for AI Memory retention instead of a custom scheduler.
# 0 = retain indefinitely by default; an administrator can lower it in Log Settings.
default_log_clearing_doctypes = {
	"AI Memory": 0,
}

# Custom short-term conversation store for AI agents (backend = "custom").
# Point this at a dotted path to a
# one_bpmn.agents.memory.conversation_store.ConversationStore subclass.
# Consumed by get_conversation_store("custom"); optional.
# ai_conversation_store = "your_app.path.to.YourConversationStore"

