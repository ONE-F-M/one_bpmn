# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Backfill the chat-surface UI fields on the Live chat agents (WI-001996).

The shared AgentChatPanel reads an agent's greeting, composer placeholder and
surface classification from its AI Agent Configuration instead of hardcoded
component strings. This patch seeds the six Live agents with the strings
their Vue components carry today, so behaviour is unchanged on day one; the
hardcoded copies are deleted by each surface's own migration story
(WI-001674…678).

Host-context flourishes (ProsAlly greeting the current process, Docu greeting
the open doctype) stay host-supplied — the panel appends the host's context
line to the configured greeting, so only the context-free sentence lives here.

Unknown agents are skipped silently: a site that never seeded an agent has
nothing to backfill. Existing non-empty values are left alone — reruns and
already-customised sites stay untouched.
"""

import frappe

BACKFILL = {
	"ai_agent_assistant": {
		"greeting": "Describe what this AI Agent Task should do, and I'll recommend field values you can apply one by one.",
		"composer_placeholder": "Describe what this task should do…",
		"surface_type": "Form",
		"artifact_type": "Record",
	},
	"logix_agent": {
		"greeting": "Hello, I am Logix — your process automation assistant. Describe what you need in plain language.",
		"composer_placeholder": "Describe the script you need… (Enter to send)",
		"surface_type": "Document",
		"artifact_type": "Script",
	},
	"prosally_agent": {
		"greeting": "Hello, I am ProsAlly. I can help to draw your process from scratch, redraw an existing model, or modify a specific part.",
		"composer_placeholder": "Describe the process you want ProsAlly to model…",
		"surface_type": "Document",
		"artifact_type": "Diagram",
	},
	"docu_agent": {
		"greeting": "Hello, I am **Docu**. Happy to help with creating doctypes.",
		"composer_placeholder": "Describe the DocType you need… (Enter to send)",
		"surface_type": "Document",
		"artifact_type": "Schema",
	},
	"lumina_general_chat": {
		"greeting": "",
		"composer_placeholder": "Type your query here or drag and drop the image...",
		"surface_type": "Conversation",
		"artifact_type": "None",
	},
	"lucrusher_agent": {
		"greeting": "",
		"composer_placeholder": "Message LuCrusher…",
		"surface_type": "Conversation",
		"artifact_type": "None",
	},
}


def execute():
	for agent_id, values in BACKFILL.items():
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id})
		if not name:
			continue
		updates = {}
		for field, value in values.items():
			if not value:
				continue
			current = frappe.db.get_value("AI Agent Configuration", name, field)
			# Selects carry their defaults on migrated rows; only real,
			# deliberate values block the backfill.
			if field in ("surface_type", "artifact_type"):
				if current in (None, "", "Conversation", "None"):
					updates[field] = value
			elif not current:
				updates[field] = value
		if updates:
			frappe.db.set_value("AI Agent Configuration", name, updates, update_modified=False)
