"""Server Script bodies from old patches, with the agent runtime imports the sites now use."""

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
)


def as_deployed(script: str) -> str:
	"""The script with each old agent runtime import line replaced by its new one."""
	for old, new in RUNTIME_IMPORTS:
		script = script.replace(old, new)
	return script
