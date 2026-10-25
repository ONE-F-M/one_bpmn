"""ProsAlly - Tool Generate Process records its cut-off calls through a helper, so the engine's script validator accepts it.

The split patch put a block in the script that calls getattr(), which the validator blocks, so every
Generate Process call failed before it ran. This patch replaces that block with a call to
record_truncated_calls and leaves every other line as found.

Idempotent: a script without the old block is left alone.
"""

import re

import frappe

API_METHOD = "prosally_tool_generate_process"
OLD_BLOCK = re.compile(
	r"^if _cut_offs:\n"
	r"    from one_bpmn\.agents\.observability import SUB_CALL_TURN_FLAG, current_sub_call, record_ai_step, sub_call_tag\n"
	r"(?:.*\n)*?(?=^if not _truncated_error:$)",
	re.MULTILINE,
)
NEW_BLOCK = "if _cut_offs:\n    from one_bpmn.agents.observability import record_truncated_calls\n    record_truncated_calls(_cut_offs)\n"


def rewrite(script: str) -> str:
	"""script with the getattr recording block replaced by a helper call; unchanged when it has no such block."""
	return OLD_BLOCK.sub(NEW_BLOCK, script, count=1)


def execute():
	name = frappe.db.get_value("Server Script", {"api_method": API_METHOD}, "name")
	if not name:
		return
	script = frappe.db.get_value("Server Script", name, "script") or ""
	updated = rewrite(script)
	if updated != script:
		frappe.db.set_value("Server Script", name, "script", updated, update_modified=False)
	elif "getattr(_run_doc" in script:
		frappe.log_error(
			title="ProsAlly Generate Process: getattr repair skipped",
			message=f"{name} still calls getattr but its recording block is not the one the split patch wrote, so it was left as it is.",
		)
