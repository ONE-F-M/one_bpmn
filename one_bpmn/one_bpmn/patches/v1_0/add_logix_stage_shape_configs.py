import frappe

MODEL_NAME = "Logix – Script Task Agent"

# bpmn_id -> the dedicated AI Agent Configuration created by
# create_logix_stage_agent_configs.py, which this patch must run after.
STAGE_CONFIGS = {
	"classify_intent": "Logix – Intent Classifier",
	"clarify": "Logix – Clarifier",
	"write_script": "Logix – Script Writer",
	"review_script": "Logix – Script Reviewer",
	"write_agent_tool": "Logix – Tool Writer (Agent Tools)",
	"finalize": "Logix – Test Writer",
}

OLD_TAGS = {
	"classify_intent": '<bpmn:scriptTask id="classify_intent" name="classify_intent" spiffworkflow:serverScript="Logix – Tool Classify Intent" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Classify Intent">',
	"clarify": '<bpmn:scriptTask id="clarify" name="clarify" spiffworkflow:serverScript="Logix – Tool Clarify" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Clarify">',
	"write_script": '<bpmn:scriptTask id="write_script" name="write_script" spiffworkflow:serverScript="Logix – Tool Write Script" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Write Script">',
	"review_script": '<bpmn:scriptTask id="review_script" name="review_script" spiffworkflow:serverScript="Logix – Tool Review Script" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Review Script">',
	"write_agent_tool": '<bpmn:scriptTask id="write_agent_tool" name="write_agent_tool" spiffworkflow:serverScript="Logix – Tool Write Agent Tool" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Write Agent Tool">',
	"finalize": '<bpmn:scriptTask id="finalize" name="finalize" spiffworkflow:serverScript="Logix – Tool Finalize" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Finalize">',
}


def execute():
	"""Point each pipeline-stage Script Task at its own dedicated AI Agent
	Configuration via a new spiffworkflow:aiSubAgentConfig attribute, so the
	stage tools no longer depend on the Sub Prompts table (being retired) or
	a config name hardcoded in the Server Script body.
	"""
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if "aiSubAgentConfig" in xml:
		return  # already migrated

	changed = False
	for bpmn_id, old_tag in OLD_TAGS.items():
		if old_tag not in xml:
			frappe.log_error(
				title="add_logix_stage_shape_configs: anchor not found",
				message=f"Shape '{bpmn_id}' tag diverged from the expected form; "
				"add spiffworkflow:aiSubAgentConfig manually.",
			)
			continue
		new_tag = old_tag[:-1] + f' spiffworkflow:aiSubAgentConfig="{STAGE_CONFIGS[bpmn_id]}">'
		xml = xml.replace(old_tag, new_tag, 1)
		changed = True

	if not changed:
		return

	# db_set avoids the editability gate — trusted content migration, same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="add_logix_stage_shape_configs: recompile failed",
			message=frappe.get_traceback(),
		)
