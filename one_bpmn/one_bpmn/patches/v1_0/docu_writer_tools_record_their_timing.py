"""The Docu writer tools put when each call started and ended, and how long it took, in their result.

Each anchor must be found exactly once; anything else is logged and left as it is. Idempotent: a
script that already times its call is left alone.
"""

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import _edit_script

# (api_method, the script's one call line, the name the timing carries)
TOOLS = (
	("docu_writer_tool_doctype_exists", 'result["answer"] = doctype_exists(doctype)', "doctype_exists"),
	(
		"docu_writer_tool_get_doctype_definition",
		'result["definition"] = get_doctype_definition(doctype)',
		"get_doctype_definition",
	),
	(
		"docu_writer_tool_get_doctype_fields",
		'result["fields"] = get_doctype_fields(doctype)',
		"get_doctype_fields",
	),
	(
		"docu_writer_tool_list_doctypes",
		'result["doctypes"] = list_doctypes(_search or "")',
		"list_doctypes",
	),
	("docu_writer_tool_list_roles", 'result["roles"] = list_roles(_search or "")', "list_roles"),
	(
		"docu_writer_tool_validate_doctype",
		'result["validation"] = validate_doctype_json(ir)',
		"validate_doctype_json",
	),
)


def execute():
	for api_method, line, call in TOOLS:
		block = (
			"from one_bpmn.tools.tool_for_server_scripts import timed\n"
			"_timings = []\n"
			f'with timed(_timings, "{call}"):\n'
			f"    {line}\n"
			'result["timings"] = _timings'
		)
		_edit_script(api_method, line, block)
