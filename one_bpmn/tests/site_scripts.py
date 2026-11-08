"""Server Script bodies from old patches, with the agent runtime imports the sites now use."""

import importlib
import re

RUNTIME_IMPORTS = (
	(
		"from one_bpmn.agents.llm_provider.base import",
		"from one_bpmn.processa_engine.agent_runtime.llm_types import",
	),
	(
		"from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings",
		"from one_bpmn.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings",
	),
	("from one_bpmn.agents.turn_state import", "from one_bpmn.processa_engine.agent_runtime.turn_state import"),
	("from one_bpmn.agents import turn_signal", "from one_bpmn.processa_engine.agent_runtime import turn_signal"),
	(
		"from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import",
		"from one_bpmn.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import",
	),
)


DEFINITIONS = "one_bpmn.ai_agent_registry.definitions"

MOVED_MODULES = {
	"one_bpmn.agents.bpmn_ir_pipeline": f"{DEFINITIONS}.prosally.tools_pipeline",
	"one_bpmn.agents.bpmn_xml_input": f"{DEFINITIONS}.prosally.helpers_xml_input",
	"one_bpmn.agents.process_links": f"{DEFINITIONS}.prosally.tools_links",
	"one_bpmn.security.bpmn_validator": f"{DEFINITIONS}.prosally.validators",
	"one_bpmn.agents.process_digest": f"{DEFINITIONS}.shared.tools_process_digest",
	"one_bpmn.agents.dms_search": f"{DEFINITIONS}.shared.tools_dms",
	"one_bpmn.security.doctype_validator": f"{DEFINITIONS}.docu.validators",
	"one_bpmn.one_bpmn.frontend.primitives": f"{DEFINITIONS}.frontend_agent.tools",
	"one_bpmn.agents.codebase_index": f"{DEFINITIONS}.lucrusher.tools",
}

# A split module's names are looked up in its new modules in this order.
SPLIT_MODULES = {
	"one_bpmn.agents.prosally_helpers": tuple(
		f"{DEFINITIONS}.{name}"
		for name in (
			"shared.helpers",
			"prosally.helpers",
			"prosally.tools_prompts",
			"prosally.tools_properties",
			"prosally.tools_subprocess",
			"prosally.tools_replies",
			"prosally.tools_lint",
			"prosally.tools_review",
		)
	),
	"one_bpmn.agents.logix_debug": (f"{DEFINITIONS}.logix.helpers", f"{DEFINITIONS}.logix.tools"),
	"one_bpmn.tools.tool_for_server_scripts": (
		f"{DEFINITIONS}.shared.tools",
		f"{DEFINITIONS}.logix.tools",
		f"{DEFINITIONS}.docu.tools",
	),
}

SPLIT_IMPORT = re.compile(
	r"^([ \t]*)from (" + "|".join(re.escape(m) for m in SPLIT_MODULES) + r") import (\([^)]*\)|[^\n#]*)",
	re.MULTILINE,
)


def as_deployed(script: str) -> str:
	"""The script with each old agent runtime or moved module import replaced by the one the sites now use."""
	for old, new in RUNTIME_IMPORTS:
		script = script.replace(old, new)
	for old, new in MOVED_MODULES.items():
		script = re.sub(rf"\bfrom {re.escape(old)} import\b", f"from {new} import", script)
	return SPLIT_IMPORT.sub(_split_import, script)


def _split_import(match: re.Match) -> str:
	indent, old, names = match.group(1), match.group(2), match.group(3)
	by_module = {}
	for name in names.strip("()").replace("\n", " ").split(","):
		name = name.strip()
		if name:
			by_module.setdefault(_new_module(old, name.split(" as ")[0]), []).append(name)
	return "\n".join(f"{indent}from {module} import {', '.join(found)}" for module, found in by_module.items())


def _new_module(old: str, name: str) -> str:
	for module in SPLIT_MODULES[old]:
		if hasattr(importlib.import_module(module), name):
			return module
	raise ImportError(f"{name} is in none of the modules {old} was split into")
