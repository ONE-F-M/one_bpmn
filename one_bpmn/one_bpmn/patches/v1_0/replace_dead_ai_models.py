"""Agents, grading and compaction move off AI Models whose key is rejected.

Only repoints to records already enabled and Healthy on the site, so no key is needed here.
Memory models are never changed. Idempotent.
"""

import re
from xml.sax.saxutils import escape as xml_escape

import frappe

SHARED_MODEL = "Platform Prompt Engineer - claude-haiku-5-5"
PLATFORM_OWNERS = ("k.sharma@one-fm.com",)
RECIPIENT_FIELDS = ("ai_health_alert_recipients", "eval_alert_recipients")
SUCCESSOR_API_NAMES = {"claude-haiku": "claude-haiku-5-5", "claude-sonnet": "claude-sonnet-5-5"}
XML_LINK = re.compile(r'(aiAgentConfig=")([^"]*)(")')
SPEC_LINK = re.compile(r'("aiAgentConfig": ")([^"]*)(")')


def execute():
	if not frappe.db.exists("DocType", "AI Agent Configuration"):
		return

	repoint_agents()
	repoint_grading_and_compaction()
	add_platform_owners()
	clear_stale_reasons()
	fix_shape_link_case()
	disable_unused_dead_models()


def is_healthy(model: str | None) -> bool:
	if not model:
		return False
	row = frappe.db.get_value("AI Model", model, ["enable_model", "health_status"], as_dict=True)
	return bool(row and row.enable_model and row.health_status == "Healthy")


def is_dead(model: str | None) -> bool:
	return bool(model) and frappe.db.get_value("AI Model", model, "health_status") == "Unhealthy"


def save_field(agent: str, field: str, value: str):
	doc = frappe.get_doc("AI Agent Configuration", agent)
	doc.set(field, value)
	doc.save(ignore_permissions=True)


def repoint_agents():
	for agent in frappe.get_all("AI Agent Configuration", filters={"enabled": 1}, fields=["name", "ai_model"]):
		if not is_dead(agent.ai_model):
			continue
		target = successor_model(agent.name, agent.ai_model)
		if is_healthy(target):
			save_field(agent.name, "ai_model", target)
		else:
			print(f"replace_dead_ai_models: {agent.name} left on {agent.ai_model}, no healthy successor")


def successor_model(agent: str, model: str) -> str | None:
	api_name = frappe.db.get_value("AI Model", model, "model_api_name") or ""
	for prefix, successor in SUCCESSOR_API_NAMES.items():
		if api_name.startswith(prefix):
			return f"{agent} - {successor}"
	return None


def repoint_grading_and_compaction():
	if not is_healthy(SHARED_MODEL):
		return

	grading = frappe.db.get_single_value("Processa Settings", "nightly_eval_grading_model")
	if grading and not is_healthy(grading):
		frappe.db.set_single_value("Processa Settings", "nightly_eval_grading_model", SHARED_MODEL)

	for agent in frappe.get_all(
		"AI Agent Configuration", filters={"compaction_model": ["!=", ""]}, fields=["name", "compaction_model"]
	):
		if not is_healthy(agent.compaction_model):
			save_field(agent.name, "compaction_model", SHARED_MODEL)


def add_platform_owners():
	for field in RECIPIENT_FIELDS:
		if not frappe.db.get_single_value("Processa Settings", field):
			frappe.db.set_single_value("Processa Settings", field, ", ".join(PLATFORM_OWNERS))


def clear_stale_reasons():
	from one_bpmn.agents.agent_provisioning import validate_agent_config

	for agent in frappe.get_all(
		"AI Agent Configuration",
		filters={"lifecycle_status": "Live", "needs_attention_reason": ["!=", ""]},
		fields=["name", "agent_type"],
	):
		result = validate_agent_config(
			agent.name, test_provider=False, require_prompt=agent.agent_type != "Background"
		)
		if result["ok"]:
			frappe.db.set_value(
				"AI Agent Configuration", agent.name, "needs_attention_reason", "", update_modified=False
			)


def relink(text: str | None, pattern: re.Pattern, names: dict[str, str], escape=None) -> str:
	"""Rewrite each aiAgentConfig value to the exact-case name of the configuration it matches."""

	def swap(match):
		exact = names.get(match.group(2).strip().casefold())
		if not exact:
			return match.group(0)
		return match.group(1) + (escape(exact) if escape else exact) + match.group(3)

	return pattern.sub(swap, text or "")


def escape_attribute(name: str) -> str:
	return xml_escape(name, {'"': "&quot;"})


def fix_shape_link_case():
	names = {name.casefold(): name for name in frappe.get_all("AI Agent Configuration", pluck="name")}

	for model in frappe.get_all(
		"BPMN Process Model",
		filters={"bpmn_xml": ["like", "%aiAgentConfig=%"]},
		fields=["name", "bpmn_xml", "serialized_spec"],
	):
		values = {
			"bpmn_xml": relink(model.bpmn_xml, XML_LINK, names, escape_attribute),
			"serialized_spec": relink(model.serialized_spec, SPEC_LINK, names),
		}
		changed = {field: value for field, value in values.items() if value != (model.get(field) or "")}
		if changed:
			frappe.db.set_value("BPMN Process Model", model.name, changed, update_modified=False)


def agent_model_values() -> list[str]:
	values = []
	for field in ("ai_model", "memory_distill_model", "memory_reconcile_model", "compaction_model"):
		values += frappe.get_all(
			"AI Agent Configuration", filters={"enabled": 1, field: ["!=", ""]}, pluck=field
		)
	return values


def models_in_use() -> set[str]:
	in_use = set(agent_model_values())
	for field in ("nightly_eval_grading_model", "default_memory_distill_model", "default_memory_reconcile_model"):
		in_use.add(frappe.db.get_single_value("Processa Settings", field))
	return in_use


def disable_unused_dead_models():
	in_use = models_in_use()
	for model in frappe.get_all(
		"AI Model", filters={"enable_model": 1, "health_status": "Unhealthy"}, pluck="name"
	):
		if model not in in_use:
			frappe.db.set_value("AI Model", model, "enable_model", 0)
