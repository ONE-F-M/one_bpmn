"""Server Script bodies from old patches, with the agent runtime imports the sites now use."""

import importlib
import re

RUNTIME_IMPORTS = (
	(
		"from processa.agents.llm_provider.base import",
		"from processa.processa_engine.agent_runtime.llm_types import",
	),
	(
		"from processa.agents.llm_provider import get_llm_adapter_from_settings",
		"from processa.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings",
	),
	("from processa.agents.turn_state import", "from processa.processa_engine.agent_runtime.turn_state import"),
	("from processa.agents import turn_signal", "from processa.processa_engine.agent_runtime import turn_signal"),
	(
		"from processa.processa.doctype.ai_agent_configuration.ai_agent_configuration import",
		"from processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import",
	),
	(
		"from processa.agents.memory.session_state import",
		"from processa.ai_agent_conversations.session_state import",
	),
	(
		"from processa.agents.memory import session_state",
		"from processa.ai_agent_conversations import session_state",
	),
)


DEFINITIONS = "processa.ai_agent_registry.definitions"
CODE_CHECKS = "processa.ai_agent_security.code_checks"

MOVED_MODULES = {
	"processa.agents.observability": "processa.ai_agent_observability.observability",
	"processa.agents.bpmn_ir_pipeline": f"{DEFINITIONS}.prosally.tools_pipeline",
	"processa.agents.bpmn_xml_input": f"{DEFINITIONS}.prosally.helpers_xml_input",
	"processa.agents.process_links": f"{DEFINITIONS}.prosally.tools_links",
	"processa.security.bpmn_validator": f"{DEFINITIONS}.prosally.validators",
	"processa.agents.process_digest": f"{DEFINITIONS}.shared.tools_process_digest",
	"processa.agents.dms_search": f"{DEFINITIONS}.shared.tools_dms",
	"processa.security.doctype_validator": f"{DEFINITIONS}.docu.validators",
	"processa.processa.frontend.primitives": f"{DEFINITIONS}.frontend_agent.tools",
	"processa.agents.codebase_index": f"{DEFINITIONS}.lucrusher.tools",
	"processa.security.client_script_validator": f"{CODE_CHECKS}.client_script_validator",
	"processa.security.script_validator": f"{CODE_CHECKS}.script_validator",
}

# A split module's names are looked up in its new modules in this order.
SPLIT_MODULES = {
	"processa.agents.prosally_helpers": tuple(
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
	"processa.agents.logix_debug": (f"{DEFINITIONS}.logix.helpers", f"{DEFINITIONS}.logix.tools"),
	"processa.tools.tool_for_server_scripts": (
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
