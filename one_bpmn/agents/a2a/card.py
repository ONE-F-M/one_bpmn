# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Agent Card builder (WI-001931).

Cards are generated fresh from AI Agent Configuration on every request —
never stored, so they cannot drift from the configuration (WI-002010).
Only an enabled, Live, exposed agent has a card at all; everything else
returns None and the discovery endpoint turns that into a 404
indistinguishable from an unknown agent.

Only public information leaves this module: name, description, tags,
sample prompts and (when configured) the public ids of allowed
sub-agents. Prompts, credentials and model settings never appear.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_url

from one_bpmn.agents import a2a_contract

RPC_PATH = "/api/method/one_bpmn.api.a2a_api.rpc"


def build_agent_card(agent_id: str) -> dict | None:
	"""The public card for one exposed agent, or None when the agent is
	unknown, disabled, not Live, or not exposed — callers must not be able
	to tell those cases apart."""
	config_name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
	if not config_name:
		return None

	config = frappe.get_cached_doc("AI Agent Configuration", config_name)
	if not (config.enabled and config.lifecycle_status == "Live" and config.a2a_exposed):
		return None

	description = (config.chat_description or config.description or config.agent_name or "").strip()
	card = {
		"protocolVersion": a2a_contract.PROTOCOL_VERSION,
		"name": config.chat_mode_label or config.agent_name,
		"description": description or config.agent_name,
		"url": get_url(f"{RPC_PATH}?agent_id={config.agent_id}"),
		"version": str(frappe.db.get_value("AI Agent Configuration", config_name, "modified")),
		"capabilities": {
			"streaming": False,
			# We accept a caller's callback and POST task changes to it, so a
			# caller with slow work need not poll. Streaming stays off: holding
			# a connection open for hours is the wrong shape for long work.
			"pushNotifications": True,
			"stateTransitionHistory": False,
		},
		"securitySchemes": {
			"frappeToken": {
				"type": "apiKey",
				"in": "header",
				"name": "Authorization",
				"description": (
					"token <api_key>:<api_secret> of an approved A2A Client "
					"that lists this agent in its allowed agents"
				),
			}
		},
		"defaultInputModes": ["text/plain"],
		"defaultOutputModes": ["text/plain"],
		"skills": [_skill(config)],
	}

	sub_agents = _public_sub_agents(config)
	if sub_agents:
		card["subAgents"] = sub_agents
	return card


def _skill(config) -> dict:
	"""One skill per agent, from configuration data only — never derived
	from tool shapes (that needs a compiled workflow and leaks shape names)."""
	tags = [t.strip() for t in (config.a2a_skill_tags or "").split(",") if t.strip()]
	skill = {
		"id": config.agent_id,
		"name": config.chat_mode_label or config.agent_name,
		"description": (config.chat_description or config.description or config.agent_name or "").strip()
		or config.agent_name,
		"tags": tags or [frappe.scrub(config.agent_type or "agent")],
	}
	examples = [row.prompt for row in (config.sample_prompts or []) if row.prompt][:5]
	if examples:
		skill["examples"] = examples
	return skill


def _public_sub_agents(config) -> list[str]:
	"""agent_ids from allowed_delegates (WI-002010) that are themselves
	publicly discoverable — a private sub-agent is nobody's business."""
	rows = config.get("allowed_delegates") or []
	public: list[str] = []
	for row in rows:
		fields = frappe.db.get_value(
			"AI Agent Configuration",
			row.agent_configuration,
			["agent_id", "enabled", "lifecycle_status", "a2a_exposed"],
			as_dict=True,
		)
		if fields and fields.enabled and fields.lifecycle_status == "Live" and fields.a2a_exposed:
			public.append(fields.agent_id)
	return public


def tool_description(agent_configuration: str, fallback: str = "") -> str | None:
	"""The tool description a model should see for a shape that delegates to
	this agent — the agent's own card, rendered as prose (WI-001933).

	A delegation shape used to be described by whatever the designer typed in
	its documentation, so which specialist the model picked came down to how
	well someone wrote that sentence, in every map that reached the agent.
	The card is the description the agent gives of itself, in one place, and
	it is what a person reads on the A2A page — so the model and the person
	choose on the same evidence.

	Read at run time rather than baked in at deploy: editing an agent's
	description or tags takes effect for every caller immediately, instead of
	going stale until each calling map happens to be redeployed. The read is
	one cached-doc lookup per delegation shape per turn.

	Returns None when the agent has no card — unknown, disabled, not Live or
	not exposed. That is the same set the delegation itself would refuse, so
	a shape pointing at one keeps its documentation and the model is not told
	about a specialist it cannot reach.
	"""
	try:
		config = frappe.get_cached_doc("AI Agent Configuration", agent_configuration)
	except frappe.DoesNotExistError:
		# A diagram naming an agent that no longer exists is the same to the
		# model as one naming a private agent: it is told nothing either way.
		return None
	if not (config.enabled and config.lifecycle_status == "Live" and config.a2a_exposed):
		return None

	# The same gate and the same skill the public card is built from, but not
	# the card itself: building one costs three uncached reads (docname to
	# agent_id and back, plus `modified` for a version string) and a query per
	# allowed delegate, then this would throw away the url, the security
	# schemes and the sub-agents. A tool description needs the skill only.
	skill = _skill(config)
	lines = [f"{skill.get('name')} — {skill.get('description')}".strip(" —")]

	tags = [t for t in (skill.get("tags") or []) if t]
	if tags:
		lines.append(f"Good for: {', '.join(tags)}")

	examples = [e.strip() for e in (skill.get("examples") or []) if e and e.strip()][:3]
	if examples:
		lines.append("For example: " + " / ".join(f'"{e}"' for e in examples))

	# Whatever the designer wrote is kept BELOW the card, not instead of it.
	# The card says what the agent is; the documentation is where a map says
	# something true only here ("only for site incidents"), which the agent
	# cannot know about itself.
	note = (fallback or "").strip()
	if note:
		lines.append(f"In this process: {note}")

	return "\n".join(lines)
