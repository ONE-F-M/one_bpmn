"""Stop a stale configuration from overriding the prompt a map was just imported with.

An AI Agent Configuration's ``system_prompt`` wins over the ``aiSystemPrompt`` on
the shape (agent_config_resolver._CONFIG_TO_SHAPE, applied whenever the field is
not blank). A Processa export carries the map and its Server Scripts but never
the configuration, so importing a map ships a new prompt that the site then
ignores in favour of whatever its configuration already held. Seen on the BA
site on 2026-09-07: the Orchestrator map arrived with the rule telling it to read
the pull request before delegating a change request, and the 1272-character
configuration from six days earlier kept running instead.

The map is the artifact people edit and export, so it is the source of truth
here — unlike the three sandbox agents, whose prompts live in their seed patches
and are synced by sync_sandbox_agent_prompts. Only the prompt is touched: model,
delegates, roles and limits are deliberately per-site.
"""

import xml.etree.ElementTree as ElementTree

import frappe

AGENTS = ("Orchestrator Agent",)


def execute():
	for agent in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", agent):
			continue
		prompt = _prompt_on_map(agent)
		if not prompt:
			continue
		doc = frappe.get_doc("AI Agent Configuration", agent)
		if (doc.system_prompt or "").strip() == prompt.strip():
			continue
		doc.system_prompt = prompt
		doc.flags.ignore_validate_update_after_submit = True
		doc.save(ignore_permissions=True)
		print(f"{agent}: configuration prompt aligned with its map ({len(prompt)} chars)")


def _prompt_on_map(agent: str) -> str | None:
	"""The prompt the agent's own AI Agent Task carries on its active map.

	Parsed as XML rather than matched with a regex: attribute order survives an
	export/import round trip in whatever order the serialiser chose, and a prompt
	is free to contain the ">" that would end a naive tag match. Located by
	``aiAgentConfig`` rather than by shape id, so a renamed or redrawn agent task
	still resolves. Read from the XML the way compilation does, because the
	compiled spec holds the prompt only after a deploy that may not have happened.
	"""
	model = frappe.db.get_value(
		"BPMN Process Model", {"name": _map_of(agent), "is_active": 1}, "bpmn_xml"
	)
	if not model:
		return None
	try:
		root = ElementTree.fromstring(model)
	except ElementTree.ParseError:
		frappe.log_error(
			title=f"Agent prompt alignment: {agent}'s map is not parseable XML",
			message=frappe.get_traceback(),
		)
		return None
	for element in root.iter():
		attrs = {name.split("}")[-1]: value for name, value in element.attrib.items()}
		if attrs.get("aiAgentConfig") == agent and attrs.get("aiSystemPrompt"):
			return attrs["aiSystemPrompt"]
	return None


def _map_of(agent: str) -> str | None:
	return frappe.db.get_value("AI Agent Configuration", agent, "process_model")
