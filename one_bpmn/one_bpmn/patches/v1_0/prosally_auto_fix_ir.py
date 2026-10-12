"""ProsAlly's generate and modify stages fix the IR problems the compiler names exactly before compiling.

Each script calls auto_fix_ir before every compile and records the fixes under auto_fixes, so only
the remaining problems go back to the model. Edits the site scripts in place; a script already
calling auto_fix_ir is skipped, and one whose anchors moved is logged and left as it is.
"""

import re

import frappe

# Matched with like to avoid the dash in the Server Script names.
SCRIPTS = ("ProsAlly%Tool Generate Process", "ProsAlly%Tool Modify Process")
MARKER = "auto_fix_ir"

IMPORT_OLD = "from one_bpmn.agents.bpmn_ir_pipeline import compile_ir, "
IMPORT_NEW = "from one_bpmn.agents.bpmn_ir_pipeline import auto_fix_ir, compile_ir, "
LOOP_OLD = "repair_hints = []\nfor attempt in range(_MAX_FIX_PASSES + 1):\n"
LOOP_NEW = "repair_hints = []\nauto_fixes = []\nfor attempt in range(_MAX_FIX_PASSES + 1):\n"
COMPILE_OLD = "    _res = compile_ir(ir_dict)\n"
COMPILE_NEW = "    auto_fixes.extend(auto_fix_ir(ir_dict))\n    _res = compile_ir(ir_dict)\n"
ARTIFACT = re.compile(
	r'(?P<indent>[ ]*)record_tool_artifact\(bpmn_id, json\.dumps\(\{"ir": ir_dict, "bpmn_xml": (?P<xml>\w+)\}'
)


def execute():
	for pattern in SCRIPTS:
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if not name:
			continue
		doc = frappe.get_doc("Server Script", name)
		if MARKER in doc.script:
			continue
		script = with_auto_fix(doc.script)
		if script is None:
			frappe.log_error(
				title="prosally_auto_fix_ir: anchors not found",
				message=f"{name} does not carry each anchor exactly once; the script is left as it is.",
			)
			continue
		doc.script = script
		doc.save(ignore_permissions=True)


def with_auto_fix(script: str) -> str | None:
	"""The script calling auto_fix_ir before each compile and reporting auto_fixes, or None if an anchor moved."""
	replacements = ((IMPORT_OLD, IMPORT_NEW), (LOOP_OLD, LOOP_NEW), (COMPILE_OLD, COMPILE_NEW))
	if any(script.count(old) != 1 for old, _ in replacements):
		return None
	if len(ARTIFACT.findall(script)) != 1:
		return None
	for old, new in replacements:
		script = script.replace(old, new, 1)
	return ARTIFACT.sub(
		lambda m: (
			f'{m["indent"]}result["auto_fixes"] = auto_fixes\n'
			f'{m["indent"]}record_tool_artifact(bpmn_id, json.dumps({{"ir": ir_dict, "bpmn_xml": {m["xml"]}, '
			'"auto_fixes": auto_fixes}'
		),
		script,
	)
