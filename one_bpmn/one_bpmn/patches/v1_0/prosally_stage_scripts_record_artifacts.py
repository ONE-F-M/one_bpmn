"""ProsAlly's generate and modify scripts record their IR and XML as the tool artifact again.

inline_prosally_tool_scripts rewrites both scripts whole from bodies that lack the
record_tool_artifact call, so a site where it re-ran after record_tool_artifacts lost the call.
Idempotent: record_tool_artifacts._rewrite leaves a script that already imports it.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prosally_stage_skills import STAGES
from one_bpmn.one_bpmn.patches.v1_0.record_tool_artifacts import (
	_PROSALLY_MODIFY_NEW,
	_PROSALLY_MODIFY_OLD,
	_PROSALLY_NEW,
	_PROSALLY_OLD,
	_rewrite,
)

REWRITES = {
	"process_generator": (_PROSALLY_OLD, _PROSALLY_NEW),
	"modifier": (_PROSALLY_MODIFY_OLD, _PROSALLY_MODIFY_NEW),
}


def execute():
	for sub_agent_id, (old, new) in REWRITES.items():
		script_name = frappe.db.get_value("Server Script", {"name": ["like", STAGES[sub_agent_id]]}, "name")
		if script_name:
			_rewrite(script_name, old, new)
