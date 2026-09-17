# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Let Docu set who may use a DocType, when the process owner says so in chat.

Docu could design any form but never decided who could open it. Every DocType
it created got one hardcoded System Manager rule, so a process owner asking for
"HR Manager should be able to raise these" was answered with a form only an
administrator could reach, and the permission table had to be edited afterwards
in the desk.

The IR now carries a ``permissions`` array, and docu_api applies it on create
AND on update. This patch is the other half: the schema writer has to know the
key exists, or it will never emit one. Three marker-guarded edits on the
``schema_writer`` sub-prompt — the shape, the rule, and the tool that lists real
role names so the model does not invent one and fail the gate.

Roles are validated server-side against the Role table before anything is
written, so a hallucinated role is a violation the writer is asked to fix, never
a permission that silently lands. Saying nothing about permissions still leaves
an existing DocType's rules untouched.

Idempotent: each edit fires only when its anchor is present and the new text is
not. doc.save() clears the agent_config:docu_agent cache.
"""
import frappe

AGENT_ID = "docu_agent"

# Present once applied — the "already done" signal.
_MARKER = '"permissions": ['

# ── 1) The IR shape gains the array ──────────────────────────────────────────
SHAPE_OLD = """  ]
}
Only 'fieldname', 'label', and 'fieldtype' are required per field;"""
SHAPE_NEW = """  ],
  "permissions": [                           // who may use it — omit entirely unless asked; see PERMISSIONS
    {"role": "HR Manager", "permlevel": 0, "read": 1, "write": 1, "create": 1, "delete": 0, "submit": 0}
  ]
}
Only 'fieldname', 'label', and 'fieldtype' are required per field;"""

# ── 2) The rule, placed with the other numbered rules ────────────────────────
RULE_OLD = """NAMING (how records are titled) — set 'autoname' when it matters:"""
RULE_NEW = """10. WHO MAY USE IT: only include "permissions" when the person tells you who should have access ("HR can raise these", "only supervisors approve"). Leave the key out otherwise — omitting it keeps whatever access the DocType already has, while sending it REPLACES every rule, so a partial list silently removes the rest. Call `list_roles` first and use the exact names it returns; a role you invent is rejected. One rule per role: 'read' to look, 'write' to change, 'create' to add, 'delete' to remove, 'submit' only on a submittable DocType. Leave 'permlevel' at 0 unless the person describes a second tier of access. Never drop System Manager — an administrator locked out of a form cannot repair it.

PERMISSIONS — turning what they said into rules:
- "HR can raise and edit these"            → {"role": "HR Manager", "read": 1, "write": 1, "create": 1}
- "supervisors only approve, not edit"     → {"role": "Supervisor", "read": 1, "submit": 1}
- "everyone in the company can see them"   → {"role": "Employee", "read": 1}
Say in plain English who you gave access to and what they can do, so the person can correct you.

NAMING (how records are titled) — set 'autoname' when it matters:"""

# ── 3) The tool that keeps role names real ───────────────────────────────────
TOOLS_OLD = "- `validate_doctype`: run it on your finished design"
TOOLS_NEW = (
	"- `list_roles`: call it before writing any permission rule, and use the exact names it "
	"returns — a role that does not exist fails the schema gate.\n"
	"- `validate_doctype`: run it on your finished design"
)

_REPLACEMENTS = (
	("schema_writer", SHAPE_OLD, SHAPE_NEW),
	("schema_writer", RULE_OLD, RULE_NEW),
	("schema_writer", TOOLS_OLD, TOOLS_NEW),
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	doc = frappe.get_doc("AI Agent Configuration", name)

	updated = False
	for row in doc.sub_prompts:
		for sub_agent_id, old, new in _REPLACEMENTS:
			if row.sub_agent_id != sub_agent_id:
				continue
			text = row.prompt_text or ""
			if new not in text and old in text:
				row.prompt_text = text.replace(old, new, 1)
				updated = True

	# A prompt that diverged from the expected layout would be skipped silently,
	# leaving Docu unable to set permissions with no sign of why.
	for row in doc.sub_prompts:
		if row.sub_agent_id == "schema_writer" and _MARKER not in (row.prompt_text or ""):
			frappe.log_error(
				title="docu_writes_permission_rules: anchor not found",
				message=(
					"The Docu schema_writer sub-prompt did not contain the expected "
					"anchors, so the permission-rule contract was not added. Add it by "
					"hand or check the prompt text."
				),
			)

	if updated:
		doc.save(ignore_permissions=True)
		frappe.db.commit()
