import re

import frappe

# Old module to the module that holds all of its names now.
MOVED_MODULES = {
	"processa.agents.adversarial_gate": "processa.ai_agent_evals.adversarial_gate",
	"processa.agents.agent_config_resolver": "processa.ai_agent_registry.provisioning.agent_config_resolver",
	"processa.agents.bpmn_ir_pipeline": "processa.ai_agent_registry.definitions.prosally.tools_pipeline",
	"processa.agents.codebase_index": "processa.ai_agent_registry.definitions.lucrusher.tools",
	"processa.agents.conformance": "processa.ai_agent_registry.provisioning.conformance",
	"processa.agents.dms_search": "processa.ai_agent_registry.definitions.shared.tools_dms",
	"processa.agents.llm_provider": "processa.processa_engine.agent_runtime.llm_factory",
	"processa.agents.llm_provider.base": "processa.processa_engine.agent_runtime.llm_types",
	"processa.agents.memory.session_state": "processa.ai_agent_conversations.session_state",
	"processa.agents.process_digest": "processa.ai_agent_registry.definitions.shared.tools_process_digest",
	"processa.agents.process_links": "processa.ai_agent_registry.definitions.prosally.tools_links",
	"processa.agents.turn_state": "processa.processa_engine.agent_runtime.turn_state",
	"processa.api.compilation": "processa.api.deploy",
	"processa.api.eval_api": "processa.api.evals",
	"processa.api.github_sync": "processa.agents_sandbox.customization.github_sync",
	"processa.processa.connectors.agent_criteria": "processa.agents_sandbox.criteria",
	"processa.processa.connectors.agent_reproduction": "processa.agents_sandbox.reproduction",
	"processa.processa.connectors.agent_sandbox_ops": "processa.agents_sandbox.sandbox.ops",
	"processa.processa.connectors.seed": "processa.processa_connectors.seed",
	"processa.processa.doctype.ai_agent_configuration.ai_agent_configuration": "processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration",
	"processa.security.bpmn_validator": "processa.ai_agent_registry.definitions.prosally.validators",
	"processa.security.client_script_validator": "processa.ai_agent_security.code_checks.client_script_validator",
	"processa.security.doctype_validator": "processa.ai_agent_registry.definitions.docu.validators",
	"processa.security.script_gate": "processa.ai_agent_security.code_checks.script_gate",
	"processa.security.script_validator": "processa.ai_agent_security.code_checks.script_validator",
}

# Old module whose names now live in several modules, by name.
SPLIT_MODULES = {
	"processa.agents.agent_provisioning": {
		"_run_baseline_eval": "processa.ai_agent_registry.provisioning.agent_provisioning",
		"_set_status": "processa.ai_agent_registry.provisioning.agent_provisioning",
		"generate_eval_suite_for_agent": "processa.ai_agent_registry.provisioning.agent_provisioning",
		"validate_agent_config": "processa.ai_agent_registry.provisioning.agent_provisioning",
	},
	"processa.agents.logix_debug": {
		"debug_inputs": "processa.ai_agent_registry.definitions.logix.helpers",
		"run_debug_stage": "processa.ai_agent_registry.definitions.logix.tools",
	},
	"processa.agents.prosally_helpers": {
		"add_document_sources": "processa.ai_agent_registry.definitions.prosally.helpers",
		"answer_to_confirmation": "processa.ai_agent_registry.definitions.prosally.helpers",
		"asks_to_make_call_activity": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"compare_output": "processa.ai_agent_registry.definitions.prosally.tools_review",
		"complete_sub_prompt": "processa.ai_agent_registry.definitions.prosally.helpers",
		"convert_step_to_subprocess": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"describe_changes": "processa.ai_agent_registry.definitions.prosally.tools_replies",
		"describe_flow_references": "processa.ai_agent_registry.definitions.prosally.tools_replies",
		"describe_lanes": "processa.ai_agent_registry.definitions.prosally.tools_prompts",
		"describe_links": "processa.ai_agent_registry.definitions.prosally.tools_replies",
		"describe_task_config": "processa.ai_agent_registry.definitions.prosally.tools_properties",
		"diagnose_output": "processa.ai_agent_registry.definitions.prosally.tools_review",
		"dms_answer_output": "processa.ai_agent_registry.definitions.prosally.tools_prompts",
		"extract_json": "processa.ai_agent_registry.definitions.shared.helpers",
		"find_missing_target": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"format_history": "processa.ai_agent_registry.definitions.shared.helpers",
		"format_removal_warning": "processa.ai_agent_registry.definitions.prosally.tools_properties",
		"join_confirmation": "processa.ai_agent_registry.definitions.prosally.tools_prompts",
		"keep_process_kind": "processa.ai_agent_registry.definitions.prosally.tools_review",
		"lint_findings": "processa.ai_agent_registry.definitions.prosally.tools_lint",
		"lint_fix_requested": "processa.ai_agent_registry.definitions.prosally.tools_lint",
		"lint_leftovers": "processa.ai_agent_registry.definitions.prosally.tools_lint",
		"lint_prompt": "processa.ai_agent_registry.definitions.prosally.tools_lint",
		"lint_unfixed_reply": "processa.ai_agent_registry.definitions.prosally.tools_lint",
		"no_change_reply": "processa.ai_agent_registry.definitions.prosally.tools_replies",
		"no_lint_fix_reply": "processa.ai_agent_registry.definitions.prosally.tools_lint",
		"none_tasks_output": "processa.ai_agent_registry.definitions.prosally.tools_review",
		"overwrite_warning": "processa.ai_agent_registry.definitions.prosally.tools_properties",
		"pending_confirmation": "processa.ai_agent_registry.definitions.prosally.helpers",
		"prosally_config": "processa.ai_agent_registry.definitions.prosally.helpers",
		"queue_process_memory": "processa.ai_agent_registry.definitions.prosally.helpers",
		"recall_process_memory": "processa.ai_agent_registry.definitions.prosally.helpers",
		"relayout_output": "processa.ai_agent_registry.definitions.prosally.tools_review",
		"resolve_scope": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"resolve_step": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"restore_call_activities": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"search_dms_for_turn": "processa.ai_agent_registry.definitions.prosally.tools_prompts",
		"similar_steps": "processa.ai_agent_registry.definitions.prosally.tools_replies",
		"splice_subprocess": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
		"stage_max_tokens": "processa.ai_agent_registry.definitions.prosally.tools_prompts",
		"stage_system_prompt": "processa.ai_agent_registry.definitions.prosally.tools_prompts",
		"transfer_properties": "processa.ai_agent_registry.definitions.prosally.tools_properties",
		"unapplied_proposal": "processa.ai_agent_registry.definitions.prosally.tools_subprocess",
	},
	"processa.api.instance_api": {
		"send_message": "processa.api.instances",
	},
	"processa.api.production_review": {
		"_allowed_repo_owners": "processa.api.production_review",
	},
	"processa.processa.engine": {
		"FrappeScriptEngine": "processa.processa_engine.engine.script_engine",
		"get_serializer": "processa.processa_engine.engine.serializer",
	},
	"processa.processa.integrations.google_drive": {
		"GoogleDriveConfigError": "processa.processa_connectors.google.drive",
		"create_file": "processa.processa_connectors.google.drive",
		"download_file_text": "processa.processa_connectors.google.drive",
		"list_files": "processa.processa_connectors.google.drive",
		"set_permissions": "processa.processa_connectors.google.drive",
		"update_file_content": "processa.processa_connectors.google.drive",
	},
	"processa.tools.tool_for_server_scripts": {
		"diff_ir": "processa.ai_agent_registry.definitions.docu.tools",
		"doctype_exists": "processa.ai_agent_registry.definitions.docu.tools",
		"get_doctype_definition": "processa.ai_agent_registry.definitions.docu.tools",
		"get_doctype_fields": "processa.ai_agent_registry.definitions.shared.tools",
		"get_server_script_content": "processa.ai_agent_registry.definitions.logix.tools",
		"get_server_script_meta": "processa.ai_agent_registry.definitions.logix.tools",
		"list_api_server_scripts": "processa.ai_agent_registry.definitions.logix.tools",
		"list_doctypes": "processa.ai_agent_registry.definitions.docu.tools",
		"list_roles": "processa.ai_agent_registry.definitions.docu.tools",
		"read_doctype_definition": "processa.ai_agent_registry.definitions.docu.tools",
		"timed": "processa.ai_agent_registry.definitions.docu.tools",
		"validate_doctype_json": "processa.ai_agent_registry.definitions.docu.tools",
	},
}

# Old submodule imported by name from its package, to its new module.
MOVED_SUBMODULES = {
	"processa.agents.a2a.delegation": "processa.a2a.delegation",
	"processa.agents.identity": "processa.ai_agent_security.identity",
	"processa.agents.memory.session_state": "processa.ai_agent_conversations.session_state",
	"processa.agents.turn_signal": "processa.processa_engine.agent_runtime.turn_signal",
	"processa.api.github_sync": "processa.agents_sandbox.customization.github_sync",
	"processa.processa.connectors.agent_primitives": "processa.processa_connectors.operations.http",
	"processa.processa.connectors.http_ops": "processa.processa_connectors.operations.http",
	"processa.processa.connectors.manifest": "processa.processa_connectors.manifest",
	"processa.processa.connectors.validator": "processa.processa_connectors.validator",
	"processa.processa.engine": "processa.processa_engine.engine",
	"processa.processa.frontend.primitives": "processa.ai_agent_registry.definitions.frontend_agent.tools",
}

OLD_MODULES = sorted(set(MOVED_MODULES) | set(SPLIT_MODULES) | {k.rsplit(".", 1)[0] for k in MOVED_SUBMODULES}, key=len, reverse=True)
IMPORT_RE = re.compile(r"from\s+(" + "|".join(re.escape(m) for m in OLD_MODULES) + r")\s+import\s+(\([\w\s,]*\)|[\w ,]+)")
DOTTED_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in OLD_MODULES) + r")\.(\w+)")
BARE_RE = re.compile(r"\b(" + "|".join(re.escape(m) for m in sorted(MOVED_MODULES, key=len, reverse=True)) + r")\b(?!\.\w)")

STORED_PATHS = (
	("BPMN Connector Operation", "handler_path"),
	("BPMN Connector Field", "value_transform"),
	("BPMN Connector Field", "choices_source_path"),
)


def execute():
	"""Point stored imports and dotted paths at the modules the processa refactor moved them to, then recompile maps."""
	like = [["like", f"%{module}%"] for module in OLD_MODULES]
	for name in _names_matching("Server Script", "script", like):
		_repath_script(name)
	for doctype, fieldname in STORED_PATHS:
		for name in _names_matching(doctype, fieldname, like):
			value = frappe.db.get_value(doctype, name, fieldname)
			frappe.db.set_value(doctype, name, fieldname, repath(value), update_modified=False)
	for name in _names_matching("BPMN Process Model", "bpmn_xml", like):
		xml = frappe.db.get_value("BPMN Process Model", name, "bpmn_xml")
		frappe.db.set_value("BPMN Process Model", name, "bpmn_xml", repath(xml), update_modified=False)
	frappe.clear_cache(doctype="Server Script")
	for name in frappe.get_all("BPMN Process Model", filters={"serialized_spec": ["like", "%one_bpmn%"]}, pluck="name"):
		_recompile(name)


def repath(text: str) -> str:
	text = IMPORT_RE.sub(_rewrite_import, text)
	text = DOTTED_RE.sub(_rewrite_dotted, text)
	return BARE_RE.sub(lambda match: MOVED_MODULES[match.group(1)], text)


def _names_matching(doctype: str, fieldname: str, like: list) -> set:
	names = set()
	for condition in like:
		names.update(frappe.get_all(doctype, filters={fieldname: condition}, pluck="name"))
	return names


def _repath_script(name: str) -> None:
	original = frappe.db.get_value("Server Script", name, "script")
	script = repath(original)
	if script != original:
		frappe.db.set_value("Server Script", name, "script", script, update_modified=False)


def _rewrite_import(match: re.Match) -> str:
	module, names = match.group(1), match.group(2)
	groups = {}
	for item in names.strip("()").split(","):
		item = " ".join(item.split())
		if not item:
			continue
		name, _, alias = item.partition(" as ")
		bound = alias or name
		submodule = MOVED_SUBMODULES.get(f"{module}.{name}")
		if submodule:
			package, last = submodule.rsplit(".", 1)
			groups.setdefault(package, []).append(last if last == bound else f"{last} as {bound}")
		else:
			groups.setdefault(_target(module, name), []).append(item)
	newline, indent = _line_start(match)
	return (newline + indent).join(f"from {target} import {', '.join(items)}" for target, items in groups.items())


def _rewrite_dotted(match: re.Match) -> str:
	module, name = match.group(1), match.group(2)
	submodule = MOVED_SUBMODULES.get(f"{module}.{name}")
	return submodule or f"{_target(module, name)}.{name}"


def _target(module: str, name: str) -> str:
	return SPLIT_MODULES.get(module, {}).get(name) or MOVED_MODULES.get(module) or module


def _line_start(match: re.Match) -> tuple:
	"""The newline form and indent of the line the import sits on: a real newline, or &#10; inside map XML."""
	before = match.string[: match.start()]
	cut = max(before.rfind("\n"), before.rfind("&#10;"))
	newline = "&#10;" if before.rfind("&#10;") > before.rfind("\n") else "\n"
	start = cut + len(newline) if cut >= 0 else 0
	indent = before[start:]
	return newline, indent if not indent.strip() else ""


def _recompile(model: str) -> None:
	from processa.api.deploy import compile_process_model

	try:
		compile_process_model(model)
	except frappe.ValidationError:
		# A map this site cannot compile must not stop the migration; its runs keep the old compiled copy.
		frappe.log_error(title=f"Map not recompiled after the processa path change: {model}", message=frappe.get_traceback())
