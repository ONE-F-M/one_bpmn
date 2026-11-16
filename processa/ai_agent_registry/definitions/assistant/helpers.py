"""The assistant's AG-UI context builder and reply shaper for the config dialog chat."""

from __future__ import annotations

import json

import frappe

from processa.ai_agent_registry.definitions.assistant.helpers_prompts import (
	build_current_config_block,
	catalog_for_mode,
	creation_capability_block,
	linked_config_block,
	selector_output_rules_block,
	selector_rules_block,
)
from processa.ai_agent_registry.definitions.shared.helpers import extract_json

# Layout-only / non-data field types skipped when summarising a DocType schema.
_SKIP_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}

_MAX_SCHEMA_FIELDS = 120
_MAX_SAMPLE_CHARS = 4000

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# Selector candidates match tool_pool eligibility: leaf tasks with no incoming sequence flow.
_LEAF_TASK_TAGS = {
	f"{{{_BPMN_NS}}}task": "Task",
	f"{{{_BPMN_NS}}}userTask": "User Task",
	f"{{{_BPMN_NS}}}manualTask": "Manual Task",
	f"{{{_BPMN_NS}}}scriptTask": "Script Task",
	f"{{{_BPMN_NS}}}serviceTask": "Service Task",
	f"{{{_BPMN_NS}}}sendTask": "Send Task",
	f"{{{_BPMN_NS}}}receiveTask": "Receive Task",
	f"{{{_BPMN_NS}}}businessRuleTask": "Business Rule Task",
}
_GATEWAY_TAGS = {
	f"{{{_BPMN_NS}}}exclusiveGateway": "Exclusive Gateway",
	f"{{{_BPMN_NS}}}parallelGateway": "Parallel Gateway",
	f"{{{_BPMN_NS}}}inclusiveGateway": "Inclusive Gateway",
}

# The shape fields update_agent_config_from_shape accepts; the provider follows the model.
_UPDATABLE_FIELDS = {"aiModel", "aiSystemPrompt", "aiTemperature", "aiMaxTokens"}


def _sanitize_proposed_update(proposed) -> dict | None:
	"""Keep only a valid update proposal: an existing config plus allowlisted fields, or None."""
	if not isinstance(proposed, dict):
		return None
	config_name = str(proposed.get("config_name") or "").strip()
	if not config_name or not frappe.db.exists("AI Agent Configuration", config_name):
		return None
	fields = proposed.get("fields")
	if not isinstance(fields, dict):
		return None
	clean = {
		key: value
		for key, value in fields.items()
		if key in _UPDATABLE_FIELDS and isinstance(value, (str, int, float)) and str(value).strip()
	}
	# Drop a model that is not an AI Model record, so the Apply card never hits a link error.
	if "aiModel" in clean and not frappe.db.exists("AI Model", str(clean["aiModel"])):
		clean.pop("aiModel")
	if not clean:
		return None
	return {"config_name": config_name, "fields": clean}


def _sanitize_created_config(created) -> dict | None:
	"""Keep a created config only when its name is a real AI Agent Configuration, with agent_id read from it.

	None means no onefm.created_config event and no linking.
	"""
	if not isinstance(created, dict):
		return None
	name = str(created.get("name") or "").strip()
	if not name or not frappe.db.exists("AI Agent Configuration", name):
		return None
	return {
		"name": name,
		"agent_id": frappe.db.get_value("AI Agent Configuration", name, "agent_id") or "",
	}


_PROPOSAL_FIELDS = {
	"agent_name", "agent_id", "agent_type", "chat_mode_label",
	"process_model", "ai_model", "system_prompt", "description",
}


def _sanitize_proposed_config(proposed) -> dict | None:
	"""Keep the create-payload fields of a proposal, with its row lists in child-table shape.

	None for an agent that already exists, or for a chat agent on a site with no creation process linked.
	"""
	if not isinstance(proposed, dict):
		return None

	from processa.ai_agent_registry.provisioning.agent_config_resolver import get_creation_process_model

	# Only chat agents need the creation process; background agents go live on insert.
	agent_type = str(proposed.get("agent_type") or "Chat").strip().capitalize()
	if agent_type != "Background" and not get_creation_process_model():
		return None

	agent_name = str(proposed.get("agent_name") or "").strip()
	agent_id = str(proposed.get("agent_id") or "").strip() or (frappe.scrub(agent_name) if agent_name else "")
	if agent_name and frappe.db.exists("AI Agent Configuration", {"agent_name": agent_name}):
		return None
	if agent_id and frappe.db.exists("AI Agent Configuration", {"agent_id": agent_id}):
		return None
	clean = {
		key: str(value)
		for key, value in proposed.items()
		if key in _PROPOSAL_FIELDS and isinstance(value, (str, int, float)) and str(value).strip()
	}
	samples = []
	for row in proposed.get("sample_prompts") or []:
		if isinstance(row, dict) and str(row.get("prompt") or "").strip():
			samples.append({
				"prompt": str(row["prompt"]),
				"expected_behaviour": str(row.get("expected_behaviour") or ""),
			})
	if samples:
		clean["sample_prompts"] = samples

	# Static context rows: a row with an empty mandatory field is dropped, not left to fail at insert.
	examples = []
	for row in proposed.get("examples") or []:
		if isinstance(row, dict) and str(row.get("input") or "").strip():
			examples.append({
				"input": str(row["input"]),
				"expected_output": str(row.get("expected_output") or ""),
				"note": str(row.get("note") or ""),
			})
	if examples:
		clean["examples"] = examples

	guardrails = []
	for row in proposed.get("guardrails") or []:
		if isinstance(row, dict) and str(row.get("guardrail") or "").strip():
			guardrails.append({
				"guardrail": str(row["guardrail"]),
				"category": str(row.get("category") or "Other"),
			})
	if guardrails:
		clean["guardrails"] = guardrails

	return clean or None


_MAX_DIAGRAM_CHARS = 24000


def _build_full_diagram_block(bpmn_xml: str, element_id: str = "", process_model: str = "") -> str:
	"""The whole diagram XML for agent mode, truncated with a marker when too long.

	process_model is the BPMN Process Model open in the editor, the default for a new agent's process.
	"""
	xml = (bpmn_xml or "").strip()
	model_line = (
		f"CURRENT PROCESS MODEL: '{process_model}' — the process open in the editor, "
		"and the default process_model when creating an agent from this dialog.\n"
		if (process_model or "").strip()
		else ""
	)
	if not xml:
		return model_line.strip()
	truncated = ""
	if len(xml) > _MAX_DIAGRAM_CHARS:
		xml = xml[:_MAX_DIAGRAM_CHARS]
		truncated = "\n<!-- … diagram truncated for length … -->"
	focus = f" The AI task being configured is element id '{element_id}'." if element_id else ""
	return (
		model_line
		+ "FULL PROCESS DIAGRAM (read-only context)."
		+ focus
		+ " Use it to ground your recommendations in the surrounding shapes, "
		"sequence flows and process variables; do not propose edits to the "
		"diagram itself:\n```xml\n"
		+ xml
		+ truncated
		+ "\n```"
	)


def _build_diagram_digest(bpmn_xml: str, element_id: str, process_model: str = "") -> dict | None:
	"""A digest of the diagram's ad-hoc subprocess: candidates, automatic chains, state changes and completion.

	Returns {"block", "candidate_ids", "element_ids"}, or None when the diagram has no ad-hoc subprocess.
	"""
	import xml.etree.ElementTree as _ET

	if not (bpmn_xml or "").strip():
		return None
	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except Exception:
		return None

	adhoc = None
	for candidate in root.iter(f"{{{_BPMN_NS}}}adHocSubProcess"):
		if not element_id or candidate.get("id") == element_id:
			adhoc = candidate
			break
	if adhoc is None:
		return None

	# Flow graph within the subprocess.
	flows = {}       # source id -> [target ids]
	has_incoming = set()
	for flow in adhoc.findall(f"{{{_BPMN_NS}}}sequenceFlow"):
		src, tgt = flow.get("sourceRef"), flow.get("targetRef")
		if src and tgt:
			flows.setdefault(src, []).append(tgt)
			has_incoming.add(tgt)

	nodes = {}       # id -> element (tasks + gateways)
	for child in adhoc:
		if child.tag in _LEAF_TASK_TAGS or child.tag in _GATEWAY_TAGS:
			node_id = child.get("id")
			if node_id:
				nodes[node_id] = child

	def spiff(el, attr):
		return el.get(f"{{{_SPIFF_NS}}}{attr}") or ""

	def documentation(el):
		doc_el = el.find(f"{{{_BPMN_NS}}}documentation")
		return (doc_el.text or "").strip() if doc_el is not None else ""

	def describe_effects(el):
		"""One-line behavior summary: what observably happens when this runs."""
		effects = []
		if spiff(el, "serviceType") == "update_field":
			try:
				rows = json.loads(spiff(el, "updateFieldRows") or "[]")
				target = spiff(el, "updateFieldDoctype") or "context document"
				for row in rows:
					effects.append(f"sets {target}.{row.get('field')} = \"{row.get('value')}\"")
			except Exception:
				pass
		script_name = spiff(el, "serverScript")
		if script_name:
			keys = server_script_result_keys(script_name)
			if keys:
				effects.append(
					"runs Server Script \"%s\" which sets process variable(s): %s"
					% (script_name, ", ".join(keys))
				)
			else:
				effects.append(f'runs Server Script "{script_name}"')
		else:
			script_el = el.find(f"{{{_BPMN_NS}}}script")
			if script_el is not None and (script_el.text or "").strip():
				effects.append(f"runs inline script: {script_el.text.strip()[:120]}")
		if spiff(el, "notificationName"):
			effects.append(f'sends notification "{spiff(el, "notificationName")}"')
		if el.tag == f"{{{_BPMN_NS}}}userTask":
			assignee = spiff(el, "assigneeDocfield") or spiff(el, "assigneeMode")
			effects.append(
				"waits for a human"
				+ (f" (assigned from docfield '{assignee}')" if assignee else "")
			)
		return "; ".join(effects)

	def walk_chain(start_id, seen=None):
		"""The steps that run automatically after a candidate, through gateways, until the chain ends."""
		seen = seen or set()
		steps = []
		queue = list(flows.get(start_id, []))
		while queue:
			node_id = queue.pop(0)
			if node_id in seen:
				continue
			seen.add(node_id)
			el = nodes.get(node_id)
			if el is None:
				continue
			if el.tag in _GATEWAY_TAGS:
				queue.extend(flows.get(node_id, []))
				continue
			effect = describe_effects(el)
			label = el.get("name") or node_id
			steps.append(f"{label}" + (f" — {effect}" if effect else ""))
			queue.extend(flows.get(node_id, []))
		return steps

	candidate_lines = []
	candidate_ids = []
	for node_id, el in nodes.items():
		if el.tag not in _LEAF_TASK_TAGS or node_id in has_incoming:
			continue
		candidate_ids.append(node_id)
		line = f'- id: {node_id} | "{el.get("name") or node_id}" | {_LEAF_TASK_TAGS[el.tag]}'
		doc_text = documentation(el)
		if doc_text:
			line += f"\n    description: {doc_text}"
		effects = describe_effects(el)
		if effects:
			line += f"\n    when activated: {effects}"
		chain = walk_chain(node_id)
		if chain:
			line += "\n    then AUTOMATICALLY (do not activate these): " + " → ".join(chain)
		candidate_lines.append(line)

	condition_el = adhoc.find(f"{{{_BPMN_NS}}}completionCondition")
	condition = (condition_el.text or "").strip() if condition_el is not None else ""

	block_parts = [
		f'AD-HOC SUBPROCESS DIGEST ("{adhoc.get("name") or adhoc.get("id")}"):',
		"SELECTABLE TASKS (the model's tools, named by id):",
		"\n".join(candidate_lines) or "  (none)",
	]

	if condition:
		block_parts.append(
			f"COMPLETION CONDITION (Python expression over process variables): {condition}\n"
			"The subprocess ends when this becomes true."
		)

	return {
		"block": "\n\n".join(block_parts),
		"candidate_ids": candidate_ids,
		"element_ids": set(nodes.keys()),
	}


def server_script_result_keys(script_name: str) -> list:
	"""The process variables a Server Script sets through result["key"], which the engine merges into task data."""
	import re as _re

	if not frappe.db.exists("Server Script", script_name):
		return []
	if not frappe.has_permission("Server Script", "read"):
		return []
	script = frappe.db.get_value("Server Script", script_name, "script") or ""
	keys = _re.findall(r"result\[\s*['\"](\w+)['\"]\s*\]", script)
	seen, ordered = set(), []
	for key in keys:
		if key not in seen:
			seen.add(key)
			ordered.append(key)
	return ordered


def _lint_recommended_prompts(recommendations: dict, digest: dict) -> list:
	"""Warnings for task ids the prompts name that the diagram lacks, and candidates they never mention."""
	import re as _re

	text = " ".join(
		str(recommendations.get(key) or "")
		for key in ("aiSystemPrompt", "aiUserPrompt")
	)
	if not text.strip():
		return []

	warnings = []
	known = digest["element_ids"] | set(digest["candidate_ids"])
	mentioned_ids = set(_re.findall(r"\b(?:Activity|Task|Gateway|Event)_[0-9A-Za-z]+\b", text))
	unknown = sorted(mentioned_ids - known)
	if unknown:
		warnings.append(
			"These task ids in the suggested prompts do not exist on the diagram: "
			+ ", ".join(unknown)
		)

	if recommendations.get("aiSystemPrompt"):
		unmentioned = sorted(
			c for c in digest["candidate_ids"] if c not in str(recommendations["aiSystemPrompt"])
		)
		if unmentioned:
			warnings.append(
				"The suggested procedure never mentions these selectable tasks: "
				+ ", ".join(unmentioned)
			)
	return warnings


def _build_context_block(doctype: str, docname: str) -> str:
	if not doctype:
		return ""

	# frappe.get_meta does not check permissions, so check read first.
	if not frappe.has_permission(doctype, "read"):
		return ""

	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return ""

	field_lines = []
	for f in meta.fields:
		if f.fieldtype in _SKIP_FIELDTYPES:
			continue
		line = f"  - {f.fieldname} ({f.fieldtype})"
		if f.label:
			line += f" — {f.label}"
		if f.options and f.fieldtype in ("Link", "Select"):
			opts = str(f.options).replace("\n", ", ")
			line += f" [{opts}]"
		field_lines.append(line)
		if len(field_lines) >= _MAX_SCHEMA_FIELDS:
			break

	block = f"CONTEXT DOCTYPE: {doctype}\nFIELDS:\n" + "\n".join(field_lines)

	sample_name = docname
	if not sample_name:
		try:
			rows = frappe.get_list(doctype, fields=["name"], limit=1, order_by="modified desc")
			if rows:
				sample_name = rows[0]["name"]
		except Exception:
			sample_name = ""

	if sample_name:
		try:
			# get_doc enforces read permission for the current user.
			doc = frappe.get_doc(doctype, sample_name)
			data = {
				k: v
				for k, v in doc.as_dict().items()
				if not k.startswith("_") and not isinstance(v, (list, dict))
			}
			sample_json = frappe.as_json(data)[:_MAX_SAMPLE_CHARS]
			block += f"\n\nSAMPLE RECORD ({sample_name}):\n{sample_json}"
		except frappe.PermissionError:
			block += "\n\n(Sample record omitted — no read permission.)"
		except Exception:
			pass

	return block


# The builder hands the turn's mode and digest to the shaper, in the same request, on frappe.local.
_DIALOG_TURN_FLAG = "assistant_dialog_turn"


def _stash_dialog_turn(mode: str, digest: dict | None = None) -> None:
	frappe.local.flags[_DIALOG_TURN_FLAG] = {"mode": mode, "digest": digest}


def _take_dialog_turn() -> dict:
	return frappe.local.flags.pop(_DIALOG_TURN_FLAG, None) or {}


def build_assistant_turn_context(context: dict) -> dict:
	"""Turn the dialog's raw grounding into the map's dialog_context."""
	grounding = (context or {}).pop("assistant_dialog", None)
	if not isinstance(grounding, dict):
		_stash_dialog_turn("agent")
		return context or {}

	mode = grounding.get("mode") if grounding.get("mode") in ("agent", "selector") else "agent"
	if mode == "selector":
		return _selector_turn_context(context, grounding)

	_stash_dialog_turn("agent")
	catalog = catalog_for_mode("agent")
	dialog_context_parts = [
		creation_capability_block(),
		(
			"PROCESS MODEL OPEN IN THE EDITOR: '{0}' — this is the exact BPMN "
			"Process Model record name. Use it VERBATIM as "
			"proposed_config.process_model when the agent should be mapped to "
			"this process; the human-facing process or diagram title is a "
			"different string and will be rejected.".format(grounding["process_model"])
			if grounding.get("process_model")
			else ""
		),
		linked_config_block(grounding.get("linked_config") or ""),
		_build_full_diagram_block(grounding.get("bpmn_xml") or "", grounding.get("element_id") or ""),
		_build_context_block(
			grounding.get("context_doctype") or "", grounding.get("context_docname") or ""
		),
		build_current_config_block(
			grounding.get("current_config") or "{}", catalog
		),
	]
	# The output rules go last, after every reference block, so the model weighs them most.
	dialog_context_parts.append(
		"FINAL OUTPUT RULES (these override anything above):\n"
		"- While details are missing, ask for them via \"message\" only.\n"
		"- The turn in which a new-agent proposal becomes complete MUST "
		"include \"proposed_config\" in your JSON reply (changes to an "
		"existing agent MUST use \"proposed_update\"). The UI renders it as a "
		"card for the designer to review. Never call the "
		"create_agent_configuration tool in that same turn.\n"
		"- Only a turn whose LATEST designer message explicitly approves that "
		"proposal calls the create_agent_configuration tool — then reply with "
		"\"created_config\" as the contract above describes.\n"
		"- Never say you created or changed anything without a successful "
		"tool result in this conversation, and never describe a proposal as "
		"submitted or in validation. A reply that promises creation without "
		"either \"proposed_config\" (phase 1) or a create tool call (phase 2) "
		"is a contract violation."
	)
	out = dict(context or {})
	out["dialog_context"] = "\n\n".join(p for p in dialog_context_parts if p)
	out["source"] = "task_dialog"
	return out


def _selector_turn_context(context: dict, grounding: dict) -> dict:
	"""Grounding for an AI Task Selector turn: the selector rules and the ad-hoc subprocess digest.

	It carries no agent-creation capability and no whole diagram, since a selector turn configures a shape.
	"""
	digest = _build_diagram_digest(
		grounding.get("bpmn_xml") or "",
		grounding.get("element_id") or "",
		process_model=grounding.get("process_model") or "",
	)
	# The shaper's post-check reads the digest, which is None when the canvas has no ad-hoc subprocess.
	_stash_dialog_turn("selector", digest)

	dialog_context_parts = [
		selector_rules_block(),
		digest["block"] if digest else "",
		_build_context_block(
			grounding.get("context_doctype") or "", grounding.get("context_docname") or ""
		),
		build_current_config_block(
			grounding.get("current_config") or "{}", catalog_for_mode("selector")
		),
		selector_output_rules_block(),
	]
	out = dict(context or {})
	out["dialog_context"] = "\n\n".join(p for p in dialog_context_parts if p)
	out["source"] = "task_dialog"
	return out


def shape_assistant_reply(result: dict) -> dict:
	"""Parse the assistant's JSON reply into the visible message, filtered recommendations and sanitized proposals.

	A selector turn uses the selector catalog, keeps its diagram post-check and drops the proposal keys.
	"""
	turn = _take_dialog_turn()
	selector_mode = turn.get("mode") == "selector"
	digest = turn.get("digest")

	raw = result.get("response") or ""
	parsed = extract_json(raw if isinstance(raw, str) else json.dumps(raw))
	if not isinstance(parsed, dict):
		return result

	catalog = catalog_for_mode("selector" if selector_mode else "agent")
	message = str(parsed.get("message", "")).strip()
	recommendations = {
		key: value
		for key, value in (parsed.get("recommendations") or {}).items()
		if key in catalog and value not in (None, "")
	}

	# Selector post-check: every task id a prompt names exists, and every candidate is covered.
	if digest:
		warnings = _lint_recommended_prompts(recommendations, digest)
		if warnings:
			message = (message + "\n\n" if message else "") + "\n".join(f"⚠️ {w}" for w in warnings)

	shaped = dict(result)
	shaped["response"] = message or (raw if not recommendations else "")
	if recommendations:
		shaped["recommendations"] = recommendations
	if selector_mode:
		return shaped

	proposed_config = _sanitize_proposed_config(parsed.get("proposed_config"))
	if proposed_config:
		shaped["proposed_config"] = proposed_config
	proposed_update = _sanitize_proposed_update(parsed.get("proposed_update"))
	if proposed_update:
		shaped["proposed_update"] = proposed_update
	created_config = _sanitize_created_config(parsed.get("created_config"))
	if created_config:
		shaped["created_config"] = created_config
	return shaped


def _register_agui_hooks():
	from processa.ai_agent_conversations.agui.stream import register_context_builder, register_reply_shaper

	register_context_builder("ai_agent_assistant", build_assistant_turn_context)
	register_reply_shaper("ai_agent_assistant", shape_assistant_reply)


_register_agui_hooks()
