"""
A real conversation on the BA site asked ProsAlly to "fix it so that the
lines don't cross and increase the spacing" and, two turns later, to turn its
user tasks into call activities. Both are targeted changes to a diagram that
already exists, but the intent classifier routed both to GENERATE_NEW, so
each cost a full from-scratch regeneration (roughly 110-140 seconds each)
instead of a modify. generate_process never reads the current diagram's XML
at all, so each of those regenerations also worked from chat history alone
and discarded whatever the previous turn had actually produced.

The classifier's existing CRITICAL rule only forces MODIFY_EXISTING for the
literal words "fix warnings", "fix errors", "resolve issues", or "clean up
the diagram" - a general layout complaint like crossing lines or cramped
spacing does not match it, and neither does a request to swap the type of
elements that already exist while keeping the same flow.

Two edits to the intent_classifier sub-prompt: broaden the CRITICAL rule to
cover layout complaints, and add one covering a type or representation
change across existing elements. Both keep the existing diagram and structure
in place, which is what MODIFY_EXISTING already means.

Idempotent: each edit fires only when its anchor is present and the new text
is not.
"""

import frappe

AGENT_ID = "prosally_agent"

LAYOUT_OLD = (
	'- CRITICAL: When the user asks to "fix warnings", "fix errors", "resolve issues", '
	'"fix the N warnings/errors", or "clean up the diagram", ALWAYS classify as '
	"MODIFY_EXISTING. These requests mean the user wants to keep their existing diagram "
	"structure and configurations intact while fixing structural issues. Never classify "
	"these as OVERWRITE_EXISTING."
)
LAYOUT_NEW = (
	'- CRITICAL: When the user asks to "fix warnings", "fix errors", "resolve issues", '
	'"fix the N warnings/errors", "clean up the diagram", or reports a layout problem such '
	"as crossing lines, cramped spacing, or overlapping shapes, ALWAYS classify as "
	"MODIFY_EXISTING. These requests mean the user wants to keep their existing diagram "
	"structure and configurations intact while fixing structural or visual issues. Never "
	"classify these as OVERWRITE_EXISTING or GENERATE_NEW.\n"
	"- CRITICAL: When the user asks to change the type or representation of elements that "
	"already exist on the diagram, for example turning user tasks into call activities or "
	"subprocesses, or making manual steps automated, while the overall flow stays the one "
	"already modelled, classify as MODIFY_EXISTING, not GENERATE_NEW or OVERWRITE_EXISTING. "
	"Changing what kind of shape a step is does not mean starting the process over."
)

# Present once applied - the "already done" signal, and the anchor checked
# below for a prompt that has drifted out from under this patch.
_MARKER = "reports a layout problem"


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	doc = frappe.get_doc("AI Agent Configuration", name)

	updated = False
	for row in doc.sub_prompts:
		if row.sub_agent_id != "intent_classifier":
			continue
		text = row.prompt_text or ""
		if LAYOUT_NEW not in text and LAYOUT_OLD in text:
			row.prompt_text = text.replace(LAYOUT_OLD, LAYOUT_NEW, 1)
			updated = True
		elif _MARKER not in text:
			frappe.log_error(
				title="prosally_intent_classifier_covers_layout_and_type_change: anchor not found",
				message="intent_classifier prompt_text does not contain the expected CRITICAL rule anchor.",
			)

	if updated:
		doc.save(ignore_permissions=True)
		frappe.db.commit()
