"""Memory distillation and reconciliation move to a Healthy AI Model, once memory is scoped.

Raises when LuCrusher, Docu, Logix or ProsAlly are not yet scoped per Process or per person,
so migrate stops instead of letting memory write rows shared with everyone. Idempotent.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.replace_dead_ai_models import (
	SHARED_MODEL,
	disable_unused_dead_models,
	is_healthy,
)

DASH = "–"
MODEL_FIELDS = ("memory_distill_model", "memory_reconcile_model")
SETTING_FIELDS = ("default_memory_distill_model", "default_memory_reconcile_model")
ENTITY_AGENTS = ("lucrusher",)
PERSONAL_AGENTS = ("docu_agent", "logix_agent")
NO_MEMORY_AGENTS = ("logix_intent_classifier", "logix_clarifier", "logix_script_writer", "logix_tool_writer")
UNSCOPED_AGENT = "Lumina General Chat"
SCRIPT_MARKERS = {
	f"LuCrusher {DASH} Build Context": "memory_reference_name",
	f"ProsAlly {DASH} Build Context": "recall_process_memory",
	f"ProsAlly {DASH} Save Response": "queue_process_memory",
}


def execute():
	if not frappe.db.exists("DocType", "AI Agent Configuration"):
		return

	check_memory_is_scoped()
	if not is_healthy(SHARED_MODEL):
		frappe.throw(f"{SHARED_MODEL} is not an enabled, Healthy AI Model")

	repoint_defaults()
	blank_dead_overrides()
	stop_unscoped_writes()
	disable_unused_dead_models()


def check_memory_is_scoped():
	problems = []
	problems += scope_problems(ENTITY_AGENTS, "memory_scope", "Entity")
	problems += scope_problems(PERSONAL_AGENTS, "memory_scope", "User and Agent")
	problems += scope_problems(NO_MEMORY_AGENTS, "long_term_memory", "Disabled")
	for script, marker in SCRIPT_MARKERS.items():
		code = frappe.db.get_value("Server Script", script, "script")
		if code is not None and marker not in code:
			problems.append(f"{script} lacks {marker}")
	if problems:
		frappe.throw("Memory is not scoped yet: " + "; ".join(problems))


def scope_problems(agent_ids, field, expected):
	problems = []
	for agent_id in agent_ids:
		for name in frappe.get_all("AI Agent Configuration", filters={"agent_id": agent_id}, pluck="name"):
			actual = frappe.db.get_value("AI Agent Configuration", name, field)
			if actual != expected:
				problems.append(f"{name} {field} is {actual}, expected {expected}")
	return problems


def repoint_defaults():
	for field in SETTING_FIELDS:
		if not is_healthy(frappe.db.get_single_value("Processa Settings", field)):
			frappe.db.set_single_value("Processa Settings", field, SHARED_MODEL)


def blank_dead_overrides():
	for agent in frappe.get_all("AI Agent Configuration", fields=["name", *MODEL_FIELDS]):
		dead = [field for field in MODEL_FIELDS if agent.get(field) and not is_healthy(agent.get(field))]
		if dead:
			doc = frappe.get_doc("AI Agent Configuration", agent.name)
			for field in dead:
				doc.set(field, "")
			doc.save(ignore_permissions=True)


def stop_unscoped_writes():
	if frappe.db.exists("AI Agent Configuration", UNSCOPED_AGENT):
		frappe.db.set_value("AI Agent Configuration", UNSCOPED_AGENT, "memory_write_mode", "off")
