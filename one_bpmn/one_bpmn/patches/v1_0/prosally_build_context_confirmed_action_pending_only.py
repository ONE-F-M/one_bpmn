"""ProsAlly - Build Context keeps task_data.confirmed_action only when a confirmation card is pending.

The panel sends the approved action with every later turn until it is cleared, so a stale
"GENERATE_NEW" made Classify Intent skip classification and start a redraw nobody asked for.
Now the value is kept only when it equals pending_confirmation(conversation_id), the action_intent
of the last Bot message when that message is a confirmation card (a CLARIFY gives "").

The script has two shapes across sites. Where it assigns the value to a variable, that assignment is
guarded in place. Where it only stages the value inside the dict handed to set_turn, that dict entry
is guarded, with the check added just before the set_turn call. Every other line is left as found
and the script body is never replaced, so the patch can run before or after another story's patch.

Idempotent: does nothing when the script already calls pending_confirmation. A site with no script
of that api_method, or a script with neither shape, is left alone and logged.
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
# `"confirmed_action": <expression mentioning confirmed_action>,` - the entry of the dict handed to set_turn.
TURN_ENTRY = re.compile(
	r"^(?P<indent>[ \t]*)(?P<key>[\"']confirmed_action[\"'])[ \t]*:[ \t]*(?P<expr>[^\n]*confirmed_action[^\n]*?),[ \t]*$",
	re.MULTILINE,
)
SET_TURN_CALL = re.compile(r"^(?P<indent>[ \t]*)set_turn\(", re.MULTILINE)


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

	updated = ASSIGNMENT.sub(guard, script)
	if updated != script:
		return updated
	return _guard_turn_entry(script)


def _guard_turn_entry(script: str) -> str:
	"""script with the confirmed_action entry of the set_turn dict guarded; unchanged when there is none."""
	entry = TURN_ENTRY.search(script)
	calls = list(SET_TURN_CALL.finditer(script, 0, entry.start())) if entry else []
	if not calls:
		return script
	call = calls[-1]
	indent = call.group("indent")
	guard = (
		f"{indent}{IMPORT_LINE}\n"
		f"{indent}_stated_action = {entry.group('expr')}\n"
		f'{indent}_confirmed = _stated_action if _stated_action and _stated_action == pending_confirmation(conversation_id) else ""\n'
	)
	staged = f"{entry.group('indent')}{entry.group('key')}: _confirmed,"
	return (
		script[: call.start()] + guard + script[call.start() : entry.start()] + staged + script[entry.end() :]
	)


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
				title="ProsAlly Build Context: no confirmed_action line",
				message=f"{name} was left as it is: no line assigns or stages confirmed_action.",
			)
		return
	frappe.db.set_value("Server Script", name, "script", updated, update_modified=False)
