"""ProsAlly - Build Context keeps task_data.confirmed_action only when a confirmation card is pending.

The panel sends the approved action with every later turn until it is cleared, so a stale
"GENERATE_NEW" made Classify Intent skip classification and start a redraw nobody asked for.
Now the value is kept only when it equals pending_confirmation(conversation_id), the action_intent
of the last Bot message when that message is a confirmation card (a CLARIFY gives "").

Another story also edits this script, so this patch owns the confirmed_action
assignment line(s) only: it matches those lines and rewrites them in place, and leaves every other
line as it finds it. It never replaces the script body, so it can run before or after that story's patch.

Idempotent: does nothing when the script already calls pending_confirmation. A site with no script
of that api_method, or a script with no line assigning confirmed_action, is left alone and logged.
"""

import re

import frappe

API_METHOD = "prosally_build_context"
IMPORT_LINE = "from one_bpmn.agents.prosally_helpers import pending_confirmation"

# "<target> = <expression mentioning confirmed_action>" - an assignment, not a comparison.
ASSIGNMENT = re.compile(
	r"^(?P<indent>[ \t]*)(?P<target>[A-Za-z_][\w.]*(?:\[[^\]\n]+\])?)[ \t]*=[ \t]*(?P<expr>[^=\n].*confirmed_action.*)$",
	re.MULTILINE,
)


def rewrite(script: str) -> str:
	"""script with each confirmed_action assignment guarded by pending_confirmation; unchanged when not applicable."""
	if "pending_confirmation(" in script:
		return script
	first = []

	def guard(match):
		indent, target, expr = match.group("indent"), match.group("target"), match.group("expr")
		lines = []
		if not first:
			first.append(True)
			lines.append(indent + IMPORT_LINE)
		lines.append(f"{indent}_stated_action = {expr}")
		lines.append(
			f'{indent}{target} = _stated_action if _stated_action and _stated_action == pending_confirmation(conversation_id) else ""'
		)
		return "\n".join(lines)

	return ASSIGNMENT.sub(guard, script)


def execute():
	name = frappe.db.get_value("Server Script", {"api_method": API_METHOD}, "name")
	if not name:
		frappe.log_error(
			title="ProsAlly Build Context: confirmed_action patch skipped",
			message=f"No Server Script has api_method {API_METHOD}, so nothing was changed.",
		)
		return
	script = frappe.db.get_value("Server Script", name, "script") or ""
	updated = rewrite(script)
	if updated == script:
		if "pending_confirmation(" not in script:
			frappe.log_error(
				title="ProsAlly Build Context: no confirmed_action assignment",
				message=f"{name} was left as it is: no line assigns confirmed_action.",
			)
		return
	frappe.db.set_value("Server Script", name, "script", updated, update_modified=False)
