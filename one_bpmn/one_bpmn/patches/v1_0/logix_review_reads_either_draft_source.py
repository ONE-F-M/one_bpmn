# Copyright (c) 2026, one-fm and contributors
"""Logix's reviewer must find the draft wherever the writer left it.

Logix's write step exists in two shapes across sites, because the move from
Server Script to AI Agent Task was made map by map:

* a Script Task, which writes the draft to ``turn["draft"]`` and returns
  ``{has_code, preview}``;
* an AI Agent Task, whose result ``execute_shape`` auto-persists as
  ``turn["write_script_result"]["write_script_output"]``.

A reviewer that knows only one of them reviews an empty string, reports the
turn as a question, and the turn ends with no reply — the user is told
"I couldn't generate a response. Please try again." (or, depending on the
site's Save Response wording, asked to explain the request again). Both
failures have been seen live, on different sites, from the same cause pointing
opposite ways.

So the reviewer reads BOTH, in the order the writer wrote them. This patch
converts the AI-Agent-Task-only variant; the other variant is handled by
``fix_logix_stale_turn_keys``. Idempotent, and it leaves an already-tolerant
script alone.
"""

import frappe

_NAME = "Logix – Tool Review Script"

# The AI-Agent-Task-only form, verbatim.
_OLD = '''draft = (
    (turn.get("write_script_result") or {}).get("write_script_output")
    or (turn.get("write_agent_tool_result") or {}).get("write_agent_tool_output")
    or ""
)'''

_NEW = '''# The write step is a Script Task on some maps and an AI Agent Task on others:
# the first writes `draft`, the second has its result auto-persisted under its
# own bpmn_id. Read both, or the reviewer reviews an empty string and the turn
# ends with no reply at all.
draft = (
    turn.get("draft")
    or (turn.get("write_script_result") or {}).get("write_script_output")
    or (turn.get("write_agent_tool_result") or {}).get("write_agent_tool_output")
    or ""
)
if not isinstance(draft, str):
    draft = str(draft or "")'''

# Present only once the script reads the Script-Task key as well.
_MARKER = 'turn.get("draft")\n    or (turn.get("write_script_result")'


def execute():
	if not frappe.db.exists("Server Script", _NAME):
		return
	script = frappe.db.get_value("Server Script", _NAME, "script") or ""
	if _MARKER in script or _OLD not in script:
		return  # already tolerant, or this site has the other variant
	frappe.db.set_value(
		"Server Script", _NAME, "script", script.replace(_OLD, _NEW, 1), update_modified=False
	)
	print(f"logix_review_reads_either_draft_source: updated {_NAME}")
