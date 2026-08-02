"""
WI-001539 / per-agent migration: complete the ``logix`` AI Agent Configuration
so Logix chat runs through the generic invocation path, and carry it to Live
through lifecycle validation.

Idempotent. Only the CHAT TURN is migrated — the Logix Server Script CRUD +
test-runner endpoints stay as-is (they are tooling, not chat).

What it fixes:
  * chat_mode_label -> "Logix" (capital L). ``create_agent_conversation`` stamps
    this on the Chat Conversation as its agent_mode, and the Logix process map's
    conditional start trigger fires on ``agent_mode == "Logix"``. The record
    shipped with the lowercase "logix", which would NOT arm the map on the
    generic path — this is the crux of the migration.
  * icon -> a chat-metadata glyph so the agent renders in the chat registry.
  * process_model / ai_provider_credentials -> asserted (already linked by
    earlier patches; the credentials link preserves the effective Anthropic
    model, so behavior is unchanged).
  * lifecycle_status -> "Live" once ``validate_agent_config`` passes; a Draft
    agent is invocable only by its owner, so go-live is required for end users.

The map already exists (bespoke "Logix – Script Task Agent"), so this does NOT
run provision_agent (which would clone a fresh chat-map template). It validates
the existing configuration and promotes it directly.
"""

import frappe

AGENT_ID = "logix_agent"
CHAT_LABEL = "Logix"
ICON = "⚙️"
PROCESS_MODEL = "Logix – Script Task Agent"


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
			title="Logix migration: validation raised",
			message=frappe.get_traceback(),
		)
		return

	status = "Live" if result.get("ok") else "Needs Attention"
	frappe.db.set_value("AI Agent Configuration", name, "lifecycle_status", status, update_modified=False)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	frappe.db.commit()

	if status != "Live":
		frappe.log_error(
			title=f"Logix migration: not promoted to Live ({AGENT_ID})",
			message="\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok",
		)
