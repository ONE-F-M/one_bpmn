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
	"/assets/one_bpmn/js/bpmn_form_actions.js",
	"/assets/one_bpmn/js/bpmn_list_indicator.js",
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

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

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
	# Pre-deployment security gate: structurally validate the body of any
	# Server Script that a BPMN script task references (unrelated Server
	# Scripts pass through untouched).
	"Server Script": {
		"validate": "one_bpmn.security.script_gate.validate_server_script_on_save",
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

