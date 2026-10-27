"""ProsAlly generate and modify ask for the model's output ceiling, capped at 64000, instead of 16384.

Edits both tool scripts in place. One already carrying the change is skipped, and one whose anchor is not found
exactly once is logged and left as it is.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_scope_modify_to_subprocess import apply_edits

BUDGET_OLD = '''_max_tokens = int(_cfg.get("max_tokens") or 0)
if _max_tokens < 16384:
    _max_tokens = 16384
_model_ceiling = 0
if _cfg.get("ai_model"):
    _model_ceiling = frappe.db.get_value("AI Model", _cfg.get("ai_model"), "max_output_tokens") or 0
if _model_ceiling:
    _max_tokens = min(_max_tokens, int(_model_ceiling))
'''
BUDGET_NEW = '''# The IR shares max_tokens with the model's own thinking, so the budget is the
# model's output ceiling capped at 64000, or 16384 when no ceiling is known.
_model_ceiling = 0
if _cfg.get("ai_model"):
    _model_ceiling = int(frappe.db.get_value("AI Model", _cfg.get("ai_model"), "max_output_tokens") or 0)
_max_tokens = min(_model_ceiling, 64000) if _model_ceiling else 16384
_max_tokens = max(_max_tokens, int(_cfg.get("max_tokens") or 0))
if _model_ceiling:
    _max_tokens = min(_max_tokens, _model_ceiling)
'''
COMMENT_OLD = {
	"ProsAlly%Tool Generate Process": (
		"# A configured max_tokens under 16384 cuts a large IR off mid-JSON, so the\n"
		"# floor is 16384 and the ceiling is whatever the model itself allows.\n"
	),
	"ProsAlly%Tool Modify Process": "# A configured max_tokens under 16384 cuts a large modification off mid-JSON.\n",
}
MARKER = "_max_tokens = min(_model_ceiling, 64000) if _model_ceiling else 16384"


def execute():
	for pattern, comment in COMMENT_OLD.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if name:
			apply_edits("Server Script", name, "script", ((comment + BUDGET_OLD, BUDGET_NEW),), MARKER)
