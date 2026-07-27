"""
WI-001539 / per-agent migration: complete the ``docu`` AI Agent Configuration
so Docu chat runs through the generic invocation path (create_agent_conversation
+ invoke_agent), and carry it to Live through lifecycle validation.

Idempotent. The DocuCanvas panel behaviour is unchanged: because the config
links the Docu process map, ``invoke_agent`` selects the ``bpmn_map`` runner and
the map performs all the work (Save User Message → Run Docu Agent → Save
Response). All Docu pipeline tools live in the map's ad-hoc Tools sub-process;
the backend agent orchestrator (DocuAgent) has been deleted and its logic
inlined into the DB Server Scripts. Docu's async invoke/poll pair
(docu_chat_async / docu_chat_status) is preserved as an async wrapper over the
same generic entry point (a Docu turn runs 25–50s).

What it fixes:
  * icon -> a chat-metadata glyph so the agent renders in the chat registry
    (the record shipped without one).
  * chat_mode_label / agent_type / process_model / ai_provider_credentials ->
    asserted (chat_mode_label already shipped as "Docu" — the capital label the
    map's conditional start trigger fires on — and the map + Anthropic
    credentials are already linked; the credentials link preserves the effective
    provider/model, so behavior is unchanged).
  * lifecycle_status -> "Live" once ``validate_agent_config`` passes; a Draft
    agent is invocable only by its owner, so go-live is required for end users.

The map already exists (bespoke "Docu – DocType Agent"), so this does NOT run
provision_agent (which would clone a fresh chat-map template). It validates the
existing configuration and promotes it directly.
"""

import frappe

AGENT_ID = "docu_agent"
CHAT_LABEL = "Docu"
ICON = "📄"
PROCESS_MODEL = "Docu – DocType Agent"


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	updates = {}
	current = frappe.db.get_value(
		"AI Agent Configuration",
		name,
		["chat_mode_label", "icon", "agent_type", "process_model"],
		as_dict=True,
	)

	if current.chat_mode_label != CHAT_LABEL:
		updates["chat_mode_label"] = CHAT_LABEL
	if not current.icon:
		updates["icon"] = ICON
	if current.agent_type != "Chat":
		updates["agent_type"] = "Chat"
	# Assert the map link (leave any deliberate re-point in place otherwise).
	if not current.process_model and frappe.db.exists("BPMN Process Model", PROCESS_MODEL):
		updates["process_model"] = PROCESS_MODEL

	if updates:
		for field, value in updates.items():
			frappe.db.set_value("AI Agent Configuration", name, field, value, update_modified=False)
		frappe.cache.delete_value(f"agent_config:{AGENT_ID}")

	# Take Live through lifecycle validation (identity, prompt, credentials, chat
	# label, and a live provider test call). Only promote on a clean pass; a
	# failure lands the agent in Needs Attention with the reason logged, matching
	# the provisioning flow.
	try:
		from one_bpmn.agents.agent_provisioning import validate_agent_config

		result = validate_agent_config(name, test_provider=True)
	except Exception:
		frappe.log_error(
			title="Docu migration: validation raised",
			message=frappe.get_traceback(),
		)
		return

	status = "Live" if result.get("ok") else "Needs Attention"
	frappe.db.set_value("AI Agent Configuration", name, "lifecycle_status", status, update_modified=False)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	frappe.db.commit()

	if status != "Live":
		frappe.log_error(
			title=f"Docu migration: not promoted to Live ({AGENT_ID})",
			message="\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok",
		)
