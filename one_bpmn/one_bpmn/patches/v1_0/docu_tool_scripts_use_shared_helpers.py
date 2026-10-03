"""Docu's Clarify and Write Schema scripts call the shared format_history and extract_json instead of their inlined copies.

Scripts are found by api_method. A script whose block no longer matches is left as-is and logged.
Idempotent: each edit applies only once.
"""

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import _edit_script

HISTORY_BLOCK = """# ── format history (inline) ──
_hist = ""
if chat_history:
    _hlines = []
    for _e in chat_history[-10:]:
        {role} = _e.get("role") or _e.get("type", "user")
        _content = (_e.get("content") or "").strip()
        if _content:
            _hlines.append(("User" if {role} == "user" else "Docu") + ": " + _content)
    _hist = "\\n".join(_hlines)
"""
HISTORY_CALL = (
	"from one_bpmn.agents.prosally_helpers import format_history\n"
	'_hist = format_history(chat_history, "Docu")\n'
)

CLARIFY_JSON_BLOCK = """# ── extract the first JSON object (inline); tolerates fenced or prose-wrapped ──
_txt = (raw or "").strip()
data = None
_fence = re.search(r"```(?:json)?\\s*\\n?([\\s\\S]*?)```", _txt)
if _fence:
    try:
        data = json.loads(_fence.group(1).strip())
    except (json.JSONDecodeError, ValueError, TypeError):
        data = None
else:
    try:
        data = json.loads(_txt)
    except (json.JSONDecodeError, ValueError, TypeError):
        _brace = re.search(r"\\{[\\s\\S]*\\}", _txt)
        if _brace:
            try:
                data = json.loads(_brace.group(0))
            except (json.JSONDecodeError, ValueError, TypeError):
                data = None
"""
CLARIFY_JSON_CALL = "from one_bpmn.agents.prosally_helpers import extract_json\ndata = extract_json(raw)\n"


def execute():
	_edit_script("docu_tool_clarify", HISTORY_BLOCK.format(role="_role"), HISTORY_CALL)
	_edit_script("docu_tool_clarify", CLARIFY_JSON_BLOCK, CLARIFY_JSON_CALL)
	_edit_script("docu_tool_write_schema", HISTORY_BLOCK.format(role="_role2"), HISTORY_CALL)
