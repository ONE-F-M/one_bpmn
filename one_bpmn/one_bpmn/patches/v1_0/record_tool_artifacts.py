"""The generating tools hand their work product to the run record.

write_script, write_schema, write_agent_tool and generate_process each produce
the thing the agent was asked for and then show the model a 400-character
preview of it. That preview was the only trace left: the script, the schema and
the process IR never reached the AI Agent Tool Call row, so nothing downstream —
review, telemetry, an audit — could see what the agent actually wrote.

Each tool now records the artifact and takes its preview back from the same
call, so the two cannot drift apart. Idempotent: a script already converted is
left alone.
"""

import frappe

_IMPORT = "from one_bpmn.agents.observability import record_tool_artifact"

# The preview line each writer ends on, and what replaces it.
_PREVIEW_OLD = 'result["preview"] = (draft or "")[:400]'
_PREVIEW_NEW = _IMPORT + '\nresult["preview"] = record_tool_artifact(bpmn_id, draft or "")'

_PREVIEW_SCRIPTS = (
	"Docu – Tool Write Schema",
	"Logix – Tool Write Script",
	"Logix – Tool Write Agent Tool",
)

# ProsAlly returns no preview — its artifact is the IR it designed and the XML
# built from it, and both are dropped on the floor once the canvas has them.
_PROSALLY_OLD = 'result["issues"] = len(problems)'
_PROSALLY_NEW = (
	_PROSALLY_OLD
	+ "\n"
	+ _IMPORT
	+ '\nrecord_tool_artifact(bpmn_id, json.dumps({"ir": ir_dict, "bpmn_xml": best_xml}, indent=1))'
)

_PROSALLY_MODIFY_OLD = 'result["issues"] = len(problems)'
_PROSALLY_MODIFY_NEW = (
	_PROSALLY_MODIFY_OLD
	+ "\n"
	+ "    "
	+ _IMPORT
	+ '\n    record_tool_artifact(bpmn_id, json.dumps({"ir": ir_dict, "bpmn_xml": merged_xml}, indent=1))'
)


def execute():
	for name in _PREVIEW_SCRIPTS:
		_rewrite(name, _PREVIEW_OLD, _PREVIEW_NEW)

	_rewrite("ProsAlly – Tool Generate Process", _PROSALLY_OLD, _PROSALLY_NEW)
	# Modify Process ends inside a block, so its call carries the indentation.
	_rewrite("ProsAlly – Tool Modify Process", _PROSALLY_MODIFY_OLD, _PROSALLY_MODIFY_NEW)

	frappe.db.commit()


def _rewrite(script_name: str, old: str, new: str) -> None:
	"""Replace the last occurrence of *old* in *script_name*, once."""
	if not frappe.db.exists("Server Script", script_name):
		return

	code = frappe.db.get_value("Server Script", script_name, "script") or ""
	if _IMPORT in code:
		return
	if old not in code:
		frappe.log_error(
			title="Tool artifact recording: line not found",
			message=f"{script_name} does not end on {old!r}; it needs the call adding by hand.",
		)
		return

	head, _, tail = code.rpartition(old)
	frappe.db.set_value(
		"Server Script", script_name, "script", head + new + tail, update_modified=False
	)
