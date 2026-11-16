# Copyright (c) 2026, one-fm and contributors
"""Deploy warnings: advisory findings returned with a successful deploy, never a refusal."""

import frappe
from frappe import _


def check_eval_suite_gating(model_name: str) -> list:
	"""Advisory warnings for gating eval suites that have never run or last failed."""
	warnings = []

	suites = frappe.get_list(
		"AI Eval Suite",
		filters={"process_model": model_name, "gate_deployment": 1},
		fields=["name", "title"],
		ignore_permissions=True,  # the deploy gate reads every suite and run linked to the model
	)

	if not suites:
		return warnings

	for suite in suites:
		suite_title = suite.title or suite.name

		latest_runs = frappe.get_list(
			"AI Eval Run",
			filters={"suite": suite.name},
			fields=["name", "status", "started_at"],
			order_by="started_at desc",
			limit_page_length=1,
			ignore_permissions=True,  # the deploy gate reads every suite and run linked to the model
		)

		if not latest_runs:
			warnings.append(
				_("Eval suite '{0}' has never been run. "
				  "Consider running it before deploying.").format(suite_title)
			)
		elif latest_runs[0].status == "Failed":
			run_date = frappe.utils.formatdate(latest_runs[0].started_at)
			warnings.append(
				_("Eval suite '{0}' failed - last run on {1}. "
				  "Consider re-running the suite before deploying.").format(
					suite_title, run_date
				)
			)

	return warnings


def check_connector_tools_can_answer(bpmn_xml: str) -> list:
	"""Warn for each connector tool with no Result Variable, which runs but returns nothing to the agent."""
	from processa.processa_engine.maps.readiness import connector_tools_without_result_variable

	return [
		{
			"label": _("Connector tool returns nothing"),
			"icon": "plug",
			"type": "warning",
			"detail": _(
				"'{0}' has no Result Variable, so the {1} connector will run for the "
				"'{2}' agent but return no data to it. Set a Result Variable on that shape."
			).format(g["shape"] or g["bpmn_id"], g["connector"] or _("connector"), g["agent"]),
		}
		for g in connector_tools_without_result_variable(bpmn_xml)
	]


def check_ai_tasks_have_a_user_prompt(spec_data: dict) -> list:
	"""Warn for each AI Agent Task with a system prompt but no user prompt."""
	warnings = []
	for bpmn_id, cfg in (spec_data.get("service_task_extensions") or {}).items():
		if (cfg or {}).get("serviceType") != "ai_agent":
			continue
		if not str(cfg.get("aiSystemPrompt") or "").strip():
			continue
		if str(cfg.get("aiUserPrompt") or "").strip():
			continue
		warnings.append({
			"label": _("AI task has no user prompt"),
			"icon": "message-square-off",
			"type": "warning",
			"detail": _(
				"'{0}' has a system prompt but no user prompt, so the agent will be asked "
				"nothing and will reply that it was given no content. Set the User Prompt "
				"on that task - e.g. a variable the map filled in earlier."
			).format(bpmn_id),
		})
	return warnings


def check_email_settings(service_extensions: dict, user_extensions: dict) -> list:
	"""One warning per Send Email task or notifying User Task whose recipients, subject or body are empty."""
	return [_email_warning(bpmn_id, missing) for bpmn_id, missing in email_setting_gaps(service_extensions, user_extensions)]


def email_setting_gaps(service_extensions: dict, user_extensions: dict) -> list:
	"""(bpmn_id, missing parts) for each Send Email task or notifying User Task with an empty recipient, subject or body."""
	recipient_keys = ("emailTo", "emailToDocFields", "emailToTableField", "emailToRoles")
	gaps = []
	for bpmn_id, cfg in service_extensions.items():
		if cfg.get("serviceType") != "send_email":
			continue
		missing = []
		if not any(str(cfg.get(key) or "").strip() for key in recipient_keys):
			missing.append(_("recipients"))
		if not str(cfg.get("emailSubject") or "").strip():
			missing.append(_("subject"))
		if not str(cfg.get("emailBody") or "").strip():
			missing.append(_("body"))
		if missing:
			gaps.append((bpmn_id, missing))
	for bpmn_id, cfg in user_extensions.items():
		if cfg.get("notifyAssignee") != "true":
			continue
		template = str(cfg.get("notifyAssigneeTemplate") or cfg.get("notifyTemplate") or "").strip()
		subject = str(cfg.get("notifyAssigneeSubject") or cfg.get("notifySubject") or "").strip()
		body = str(cfg.get("notifyAssigneeBody") or cfg.get("notifyBody") or "").strip()
		missing = []
		if not (template or subject):
			missing.append(_("subject"))
		if not (template or body):
			missing.append(_("body"))
		if missing:
			gaps.append((bpmn_id, missing))
	return gaps


def _email_warning(bpmn_id: str, missing: list) -> dict:
	return {
		"label": _("Email settings are empty"),
		"icon": "mail-warning",
		"type": "warning",
		"detail": _("'{0}' sends an email with no {1}. Fill these in so the email goes out as intended.").format(
			bpmn_id, ", ".join(missing)
		),
	}


def check_notification_senders(service_extensions: dict, user_extensions: dict) -> list:
	"""On a Production instance, one warning per notification that does not send from the configured address."""
	expected, gaps = notification_sender_gaps(service_extensions, user_extensions)
	return [
		{
			"label": _("Notification sender is not {0}").format(expected),
			"icon": "mail-warning",
			"type": "warning",
			"detail": _("'{0}' sends from {1}. On this Production site notifications should send from {2}.").format(
				bpmn_id, sender, expected
			),
		}
		for bpmn_id, sender in gaps
	]


def notification_sender_gaps(service_extensions: dict, user_extensions: dict) -> tuple:
	"""(expected address, [(bpmn_id, sender)]) for notifications sending from another address; empty off Production."""
	from processa.api.editability import get_instance_type

	account = frappe.db.get_single_value("Processa Settings", "production_notification_account")
	if get_instance_type() != "Production" or not account:
		return "", []
	expected = frappe.db.get_value("Email Account", account, "email_id") or ""
	accounts = [
		(bpmn_id, cfg.get("emailAccount"))
		for bpmn_id, cfg in service_extensions.items()
		if cfg.get("serviceType") == "send_email"
	]
	accounts += [
		(bpmn_id, cfg.get("notifyAssigneeAccount") or cfg.get("emailAccount"))
		for bpmn_id, cfg in user_extensions.items()
		if cfg.get("notifyAssignee") == "true"
	]
	default_sender = frappe.db.get_value("Email Account", {"default_outgoing": 1}, "email_id")
	gaps = []
	for bpmn_id, account in accounts:
		account = str(account or "").strip()
		sender = frappe.db.get_value("Email Account", account, "email_id") if account else default_sender
		if (sender or "").strip().lower() != expected.lower():
			gaps.append((bpmn_id, sender or account or _("no email account")))
	return expected, gaps


def check_script_tasks_have_a_script(bpmn_xml: str) -> list:
	"""One warning per Script Task with no Server Script and no inline script."""
	import xml.etree.ElementTree as _ET

	return [
		{
			"label": _("Script is empty"),
			"icon": "file-warning",
			"type": "warning",
			"detail": _("'{0}' has no script, so it does nothing when it runs. Pick a Server Script or write one.").format(
				bpmn_id
			),
		}
		for bpmn_id in empty_script_tasks(_ET.fromstring(bpmn_xml.strip().encode("utf-8")))
	]


def empty_script_tasks(root) -> list:
	"""Ids of the Script Tasks under *root* that have neither a Server Script nor an inline script."""
	bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	spiff_ns = "http://spiffworkflow.org/bpmn/schema/1.0/core"
	empty = []
	for task in root.iter(f"{{{bpmn_ns}}}scriptTask"):
		script = task.find(f"{{{bpmn_ns}}}script")
		if (task.get(f"{{{spiff_ns}}}serverScript") or "").strip():
			continue
		if script is not None and (script.text or "").strip():
			continue
		empty.append(task.get("id"))
	return empty


def check_shape_config_drift(service_extensions: dict) -> list:
	"""One warning per AI shape whose prompt, model, temperature or max tokens differ from its linked configuration."""
	from processa.ai_agent_registry.provisioning.agent_config_resolver import config_field_map, shape_config_drift

	warnings = []
	live_by_config = {}
	for bpmn_id, cfg in service_extensions.items():
		if cfg.get("serviceType") not in ("ai_agent", "ai_task_selector"):
			continue
		config_name = cfg.get("aiAgentConfig") or ""
		if config_name not in live_by_config:
			live_by_config[config_name] = config_field_map(config_name)
		drift = shape_config_drift(cfg, live_by_config[config_name])
		if not drift:
			continue
		warnings.append({
			"label": _("AI task differs from its configuration"),
			"icon": "git-compare",
			"type": "warning",
			"detail": _("'{0}' differs from AI Agent Configuration '{1}'. What runs: {2}").format(
				bpmn_id, config_name, "; ".join(_drift_line(d) for d in drift)
			),
		})
	return warnings


def _drift_line(drift: dict) -> str:
	if drift["field"] == "aiSystemPrompt":
		return _("{0} is the configuration's ({1} characters, the shape has {2})").format(
			drift["label"], len(drift["live"]), len(drift["shape"])
		)
	return _("{0} {1} (the shape says {2})").format(drift["label"], drift["live"], drift["shape"] or _("nothing"))


def check_scripts_pending_review(script_names: list) -> list:
	"""Warn for each Server Script the deploy left disabled because it awaits a System Manager's review."""
	return [
		{
			"label": _("Script awaits review"),
			"icon": "shield-alert",
			"type": "warning",
			"detail": _(
				"Server Script '{0}' was written or edited by an agent and stays disabled until a "
				"System Manager reviews and enables it."
			).format(name),
		}
		for name in script_names
	]
