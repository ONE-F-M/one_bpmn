# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Helpers the ProsAlly tool scripts share: property preservation, JSON extraction, confirmation replies, history, model calls."""

import copy
import difflib
import json
import re
from collections import Counter
from xml.etree import ElementTree as ET

import frappe
from frappe import _

from one_bpmn.agents.bpmn_ir_pipeline import compile_ir, element_names, has_lanes
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.memory.text_clean import strip_html, unescape_entities
from one_bpmn.agents.turn_state import run_sync
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

AGENT_ID = "prosally_agent"
HISTORY_TURNS = 10
MIN_STAGE_TOKENS = 16384
# The most steps and settings a confirmation summary lists (WI-003582).
MAX_CONFIRMATION_STEPS = 8
MAX_CONFIRMATION_SETTINGS = 6

# Whole replies that approve a pending confirmation, after punctuation and "please" or "thanks" are dropped.
AFFIRMATIONS = frozenset(
	{
		"yes",
		"y",
		"yeah",
		"yep",
		"yup",
		"sure",
		"ok",
		"okay",
		"alright",
		"all right",
		"go",
		"go ahead",
		"yes go ahead",
		"ok go ahead",
		"okay go ahead",
		"proceed",
		"yes proceed",
		"ok proceed",
		"do it",
		"yes do it",
		"do",
		"just do it",
		"go for it",
		"draw it",
		"yes draw it",
		"confirm",
		"confirmed",
		"yes confirm",
		"sounds good",
		"looks good",
		"yes sounds good",
		"yes looks good",
		"perfect",
		"correct",
		"yes correct",
		"thats right",
		"yes thats right",
		"absolutely",
		"of course",
	}
)
# Replies starting with one of these turn a pending confirmation down.
DECLINES = ("no", "nope", "nah", "wait", "change", "not yet", "hold on", "stop", "dont", "do not", "cancel")
_POLITE_WORDS = re.compile(r"\b(please|thanks|thank you)\b")

# "lanes" then optional "only/named/called/are" and a colon, then the list up to the end of the clause.
_LANE_LIST = re.compile(r"\blanes\b(?:\s+(?:only|named|called|are))*\s*:?\s*([^.;:\n]+)", re.I)
# Plain words for the element types a designer sees in a change list.
_ELEMENT_WORDS = {
	"startEvent": "the start",
	"endEvent": "the end",
	"exclusiveGateway": "the decision",
	"inclusiveGateway": "the decision",
	"eventBasedGateway": "the decision",
	"parallelGateway": "the parallel split",
	"sequenceFlow": "the path",
	"subProcess": "the sub-process",
	"intermediateCatchEvent": "the event",
	"intermediateThrowEvent": "the event",
	"boundaryEvent": "the event",
	"userTask": "the step",
	"serviceTask": "the step",
	"scriptTask": "the step",
	"manualTask": "the step",
	"sendTask": "the step",
	"receiveTask": "the step",
	"businessRuleTask": "the step",
	"callActivity": "the step",
	"task": "the step",
}

NS = {
	"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
	"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
	"dc": "http://www.omg.org/spec/DD/20100524/DC",
	"di": "http://www.omg.org/spec/DD/20100524/DI",
	"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
	"custom": "http://custom/text-style",
	"camunda": "http://camunda.org/schema/1.0/bpmn",
}
SUBPROCESS_KEPT_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag for tag in ("incoming", "outgoing", "extensionElements", "documentation")
)
ID_REF_ATTRS = ("id", "sourceRef", "targetRef", "bpmnElement", "default", "attachedToRef")
STEP_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag for tag in ("task", "userTask", "scriptTask", "serviceTask", "manualTask", "businessRuleTask")
)
SUBPROCESS_REQUEST = re.compile(r"sub[\s-]?process\s+(?:for|of|on)\s+(?:the\s+)?(?:step\s+)?([^:,.;\n]+)", re.I)
BECOME_SUBPROCESS = re.compile(
	r"([^:,.;\n]+?)\s+(?:should\s+be|must\s+be|needs?\s+to\s+be|to\s+be|become|becomes|into|as|a|an)\s+(?:a\s+|an\s+)?(?:expanded\s+)?sub[\s-]?process",
	re.I,
)
LINT_FIX_REQUEST = re.compile(
	r"\b(?:fix|resolve|clear|clean\s*up|correct|repair|solve|sort\s*out)\b[^.:]{0,60}\b(?:lint(?:ing)?|linter|warnings?|errors?|issues?|problems?)\b"
	r"(?!\s+(?:handler|step|task|event|gateway|flow|path|boundary|code))"
	r"|\blint(?:ing)?\b[^.:]{0,40}\b(?:fix|resolve|clear|clean\s*up|correct|repair)",
	re.I,
)
LINT_NOT_FIXABLE = frozenset(
	(
		"no-overlapping-elements",
		"no-crossing-edges",
		"script-task-missing-script",
		"call-activity-missing-process",
		"no-prohibited-shapes",
		"no-bpmndi",
		"ad-hoc-sub-process",
	)
)
LINT_ABOUT_CONTENTS = frozenset(
	("start-event-required", "end-event-required", "sub-process-blank-start-event", "single-blank-start-event")
)
MAX_LINT_FINDINGS = 40
DIAGRAM_REPLIES = ("BPMN_MODIFIED", "BPMN_GENERATED")
DIAGRAM_VERSION_SUFFIX = re.compile(r"\s+-\s+v\d+\s*$", re.I)
MEMORY_NOTES_LIMIT = 8
MEMORY_NOTES_HEADER = "Notes from earlier work on this process:"
MEMORY_NOTES_PROVENANCE = "These were agreed in other conversations; they do not mean the diagram exists."
MEMORY_BACKEND = "direct_api"
REQUEST_STOPWORDS = frozenset(
	("create", "sub", "process", "subprocess", "step", "steps", "with", "that", "this", "from", "into", "inside", "when", "then", "should")
)
RECENT_REPLIES = 10
DEFINITE_SUBPROCESS = re.compile(r"(?<!new\s)\b(?:the|that|this|my|your)\s+sub[\s-]?p(?:ro|or)ces{1,2}\b", re.I)
TYPO_SIMILARITY = 0.75
POSITION_WORDS = (
	r"\b(?:after|before|following|preceding|then|next\s+to|beside|alongside|near|adjacent\s+to|above|below)\s+(?:the\s+|a\s+)?$"
)
CALL_ACTIVITY_CONVERSION = re.compile(
	r"\b(?:as|into|to)\s+(?:a\s+|an\s+)?call[\s-]?activit|\b(?:make|turn|convert|change)\b[^.:]{0,80}\bcall[\s-]?activit", re.I
)
EXPANDED_PAD = 24
EXPANDED_HEADER = 36
EXTENSION_NS_URIS = (
	"{http://spiffworkflow.org/bpmn/schema/1.0/core}",
	"{http://custom/text-style}",
	"{http://camunda.org/schema/1.0/bpmn}",
)
ATTR_FAMILY_LABELS = {
	"serverScript": "Server Script",
	"assignmentMode": "Assignment Mode",
	"assigneeDocField": "Assignee (Doc Field)",
	"roundRobinRole": "Round Robin Role",
	"loadBalancingRole": "Load Balancing Role",
	"leaveRelieverEnabled": "Leave Reliever",
	"triggerType": "Trigger Type",
	"triggerDoctype": "Trigger DocType",
	"serviceType": "Service Type",
	"serviceTargetDoctype": "Target DocType",
	"workflowState": "Workflow State",
	"docStatus": "Doc Status",
	"emailSubject": "Email Subject",
	"emailTo": "Email To",
	"emailBody": "Email Body",
	"emailAccount": "Email Account",
	"gchatMessage": "Google Chat Message",
	"gchatSpaceId": "Google Chat Space",
	"pushTitle": "Push Notification Title",
	"pushMessage": "Push Notification Message",
	"updateFieldDoctype": "Update Field DocType",
	"updateFieldName": "Update Field Name",
	"updateFieldValue": "Update Field Value",
	"calledDecisionId": "Decision Table",
	"notificationName": "Notification",
	"fontFamily": "Font Family",
	"fontSize": "Font Size",
	"fontWeight": "Font Weight",
	"fontStyle": "Font Style",
	"textColor": "Text Color",
	"textDecoration": "Text Decoration",
	"assignee": "Assignee",
	"candidateGroups": "Candidate Groups",
	"candidateUsers": "Candidate Users",
	"formKey": "Form Key",
	"dueDate": "Due Date",
	"followUpDate": "Follow-Up Date",
	"priority": "Priority",
	"asyncBefore": "Async Before",
	"asyncAfter": "Async After",
}


def prosally_config() -> dict:
	"""ProsAlly's resolved agent configuration."""
	cfg = get_agent_config(AGENT_ID) or {}
	cfg.setdefault("agent_id", AGENT_ID)
	return cfg


def complete_sub_prompt(cfg: dict, sub_id: str, user: str, system: str | None = None, max_tokens=None) -> str:
	"""One model call with a sub-prompt as the system prompt, returning the reply text."""
	if system is None:
		system = ((cfg.get("sub_prompts") or {}).get(sub_id) or {}).get("prompt") or ""
	kwargs = {"system": system, "user": user}
	if max_tokens:
		kwargs["max_tokens"] = max_tokens
	return run_sync(get_llm_adapter_from_settings(cfg).complete(**kwargs)).text


def stage_system_prompt(cfg: dict, sub_id: str, skills_constant: str, turn: dict | None = None) -> str:
	"""A stage's sub-prompt, the turn's process notes, then the Active skills named in ``skills_constant``."""
	system = ((cfg.get("sub_prompts") or {}).get(sub_id) or {}).get("prompt") or ""
	names = [
		n.strip() for n in ((cfg.get("constants") or {}).get(skills_constant) or "").split(",") if n.strip()
	]
	skills = []
	if names:
		skills = frappe.get_all(
			"AI Skill",
			filters={"name": ["in", names], "status": "Active"},
			fields=["name", "body"],
			order_by="name asc",
		)
	notes = memory_notes_block(turn)
	sections = [system] + ([notes] if notes else [])
	sections += ["## Skill: " + sk.name + "\n\n" + sk.body for sk in skills]
	return "\n\n".join(sections)


def process_for_diagram(diagram_name: str) -> str:
	"""The Process a diagram is named after, with its version suffix removed; "" when there is none."""
	name = DIAGRAM_VERSION_SUFFIX.sub("", diagram_name or "").strip()
	return name if name and frappe.db.exists("Process", name) else ""


def recall_process_memory(diagram_name: str) -> dict:
	"""The diagram's Process and the notes recalled for it and the requester, for the turn store."""
	from one_bpmn.agents.memory.tools import memory_search
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import (
		DEFAULT_MEMORY_TOKEN_BUDGET,
		_bound_memories_to_budget,
		_requesting_user,
	)

	process = process_for_diagram(diagram_name)
	user = _requesting_user()
	rows = []
	# An empty query lists the key's newest rows: a confirmation turn's text matches nothing.
	if process:
		key = {"reference_doctype": "Process", "reference_name": process}
		rows += memory_search("Entity", key, "", limit=MEMORY_NOTES_LIMIT, ignore_permissions=True)
	if user:
		rows += memory_search("User", {"user": user}, "", limit=MEMORY_NOTES_LIMIT, ignore_permissions=True)
	notes = list(dict.fromkeys((r.get("content") or "").strip() for r in rows))
	kept = _bound_memories_to_budget([{"content": n} for n in notes if n], DEFAULT_MEMORY_TOKEN_BUDGET)
	return {"memory_process": process, "memory_notes": [r["content"] for r in kept]}


def memory_notes_block(turn: dict | None) -> str:
	"""The turn's recalled notes under their heading; "" when it has none."""
	notes = (turn or {}).get("memory_notes") or []
	if not notes:
		return ""
	return "\n".join([MEMORY_NOTES_HEADER, MEMORY_NOTES_PROVENANCE] + ["- " + n for n in notes])


def queue_process_memory(turn: dict, agent_result: dict | None) -> None:
	"""Queue distillation of a turn that drew or changed a diagram into its Process's memory."""
	process = (turn or {}).get("memory_process")
	intent = (agent_result or {}).get("intent")
	if not process or intent not in DIAGRAM_REPLIES or frappe.flags.get("eval_origin"):
		return
	from one_bpmn.agents.memory.model_resolution import resolve_memory_model
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import (
		_enqueue_distill,
		_provider_for_model,
		_requesting_user,
	)

	cfg = prosally_config()
	own = frappe.db.get_value(
		"AI Agent Configuration", cfg.get("name"), ["memory_distill_model", "memory_reconcile_model"], as_dict=True
	) or {}
	distill_model = resolve_memory_model(
		own.get("memory_distill_model"), "default_memory_distill_model", cfg.get("ai_model")
	)
	reconcile_model = resolve_memory_model(
		own.get("memory_reconcile_model"), "default_memory_reconcile_model", cfg.get("ai_model")
	)
	source = "\n\n".join(
		[
			"[User message]\n" + (turn.get("user_text") or "")[:3000],
			"[ProsAlly reply]\n" + (agent_result.get("response") or ""),
			"[Conversation]\n" + format_history(turn.get("chat_history")),
		]
	)
	_enqueue_distill(
		agent_output=source,
		agent=AGENT_ID,
		scope="Entity",
		scope_key={"reference_doctype": "Process", "reference_name": process},
		provider_name=_provider_for_model(distill_model, cfg.get("ai_provider")),
		backend=MEMORY_BACKEND,
		model=distill_model,
		reconcile_model=reconcile_model,
		reconcile_provider=_provider_for_model(reconcile_model, cfg.get("ai_provider")),
		source_run=None,
		user=_requesting_user(),
		exclude_context=memory_notes_block(turn),
	)


def stage_max_tokens(cfg: dict) -> int:
	"""Output budget for a full IR: at least MIN_STAGE_TOKENS, at most what the model allows."""
	max_tokens = max(int(cfg.get("max_tokens") or 0), MIN_STAGE_TOKENS)
	ceiling = 0
	if cfg.get("ai_model"):
		ceiling = frappe.db.get_value("AI Model", cfg.get("ai_model"), "max_output_tokens") or 0
	if ceiling:
		max_tokens = min(max_tokens, int(ceiling))
	return max_tokens


def pending_confirmation(conversation: str) -> str:
	"""The action_intent the last Bot message asks the user to confirm; "" when that message is not a confirmation card."""
	last = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Bot"},
		fields=["metadata"],
		order_by="creation desc",
		limit=1,
	)
	meta = frappe.parse_json(last[0].metadata or "{}") if last else {}
	action = (meta.get("agent_result") or {}).get("action_intent")
	if meta.get("intent") != "CONFIRM" or not action:
		return ""
	return action


def answer_to_confirmation(conversation: str, user_text: str) -> dict:
	"""{"confirmed_action": ...} or {"declined_action": ...} when user_text answers the last Bot confirmation, else {}."""
	action = pending_confirmation(conversation)
	if not action:
		return {}
	reply = confirmation_reply(user_text)
	if reply == "yes":
		return {"confirmed_action": action}
	if reply == "no":
		return {"declined_action": action}
	return {}


def confirmation_reply(text: str) -> str:
	""" "yes" when text is a plain affirmation, "no" when it starts with a decline, else ""."""
	words = re.sub(r"[^a-z ]", " ", strip_html(text).lower().replace("'", ""))
	words = " ".join(_POLITE_WORDS.sub(" ", words).split())
	if words in AFFIRMATIONS:
		return "yes"
	if any(words == d or words.startswith(d + " ") for d in DECLINES):
		return "no"
	return ""


def join_confirmation(summary: str | dict, question: str) -> str:
	"""The summary then the question as its own paragraph, without a closing summary sentence that repeats the question.

	A summary given as {"intro", "steps", "settings"} is laid out as a paragraph and two one-per-line lists."""
	if isinstance(summary, dict):
		summary = _confirmation_text(summary)
	summary = (summary or "").strip()
	question = (question or "").strip()
	last = re.search(r"[^.!?\n]*[.!?]?\s*$", summary)
	if question and _comparable(last.group(0)) == _comparable(question):
		summary = summary[: last.start()].rstrip()
	return (summary + "\n\n" + question) if summary else question


def _confirmation_text(parts: dict) -> str:
	"""The intro, the steps understood and the settings planned, each list one item per line."""
	steps = [str(step).strip() for step in parts.get("steps") or [] if str(step).strip()]
	settings = [str(setting).strip() for setting in parts.get("settings") or [] if str(setting).strip()]
	# Backstop for the classifier prompt's own cap: a long list is cut, never shown whole.
	steps = steps[:MAX_CONFIRMATION_STEPS]
	settings = settings[:MAX_CONFIRMATION_SETTINGS]
	blocks = [str(parts.get("intro") or "").strip()]
	if steps:
		blocks.append(_("Here's what I understood:") + "\n" + "\n".join("- " + step for step in steps))
	if settings:
		blocks.append(_("I'll also set these up on the steps:") + "\n" + "\n".join("- " + setting for setting in settings))
		blocks.append(_('Reply "draw only" if you\'d rather I draw just the steps, without these settings.'))
	return "\n\n".join(block for block in blocks if block)


def _comparable(text: str) -> str:
	return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def format_history(chat_history: list, agent_label: str = "ProsAlly") -> str:
	"""The last HISTORY_TURNS messages as "User: ..." lines and lines labelled with the agent's name."""
	lines = []
	for entry in (chat_history or [])[-HISTORY_TURNS:]:
		role = entry.get("role") or entry.get("type", "user")
		content = (entry.get("content") or "").strip()
		if content:
			lines.append(("User" if role == "user" else agent_label) + ": " + content)
	return "\n".join(lines)


def extract_json(raw: str) -> dict | None:
	"""The first JSON object found in a model reply: whole, fenced, or embedded in prose."""
	if not raw:
		return None
	stripped = raw.strip()
	candidates = [stripped]
	fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
	if fenced:
		candidates.append(fenced.group(1).strip())
	greedy = re.search(r"\{[\s\S]*\}", raw)
	if greedy:
		candidates.append(greedy.group(0))
	if stripped.startswith("```"):
		unfenced = stripped.split("\n", 1)[-1]
		if unfenced.rstrip().endswith("```"):
			unfenced = unfenced.rstrip()[: unfenced.rstrip().rfind("```")]
		candidates.append(unfenced.strip())
	start = raw.find("{")
	if start != -1:
		depth = 0
		for i in range(start, len(raw)):
			if raw[i] == "{":
				depth += 1
			elif raw[i] == "}":
				depth -= 1
				if depth == 0:
					candidates.append(raw[start : i + 1])
					break
	for candidate in candidates:
		try:
			parsed = json.loads(candidate)
		except json.JSONDecodeError:
			continue
		if isinstance(parsed, dict):
			return parsed
	return None


def overwrite_warning(xml: str) -> str:
	"""The warning listing the configured shapes an overwrite would discard, or "" when none are."""
	configured = extract_configured_elements(xml)
	if not configured:
		return ""
	return summarize_configured_elements(configured)


def transfer_properties(old_xml: str, new_xml: str, skip_ids: tuple = ()) -> tuple:
	"""Copy configuration from old_xml onto the same ids in new_xml, except skip_ids; return (merged_xml, removed)."""
	if not (old_xml or "").strip():
		return new_xml, []
	if not (new_xml or "").strip():
		return new_xml, []
	old_configured = {k: v for k, v in extract_configured_elements(old_xml).items() if k not in skip_ids}
	if not old_configured:
		return new_xml, []
	_register_namespaces()
	new_root = ET.fromstring(new_xml)
	new_by_id = {elem.get("id"): elem for elem in new_root.iter() if elem.get("id")}
	removed = []
	for elem_id, old_data in old_configured.items():
		if elem_id in new_by_id:
			_copy_configuration(new_by_id[elem_id], old_data)
		else:
			removed.append(
				{
					"id": elem_id,
					"name": old_data["name"],
					"type": old_data["type"],
					"configs": _config_descriptions(old_data),
				}
			)
	merged_xml = ET.tostring(new_root, encoding="unicode", xml_declaration=True)
	merged_xml = re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', merged_xml)
	return merged_xml, removed


def resolve_scope(xml: str, texts: list, scope_id: str = "") -> dict | None:
	"""The sub-process a request is about: the one open on the canvas, else the one the newest message names."""
	if not (xml or "").strip():
		return None
	_register_namespaces()
	subs = {e.get("id"): e for e in ET.fromstring(xml).iter("{" + NS["bpmn"] + "}subProcess") if e.get("id")}
	chosen = subs.get(scope_id)
	for text in texts:
		if chosen is not None:
			break
		named = [e for e in subs.values() if e.get("name") and _is_named(text or "", e.get("name"))]
		if named:
			chosen = max(named, key=lambda e: len(e.get("name")))
	if chosen is None:
		return None
	return {"id": chosen.get("id"), "name": chosen.get("name") or chosen.get("id"), "xml": ET.tostring(chosen, encoding="unicode")}


def _is_named(text: str, name: str) -> bool:
	"""True when text names the sub-process as the thing to edit, not as a place to put a step before or after."""
	pattern = r"[\s\-]*".join(re.escape(word) for word in re.split(r"[^A-Za-z0-9]+", name) if word)
	for match in re.finditer(pattern, text, re.I):
		if not re.search(POSITION_WORDS, text[: match.start()], re.I):
			return True
	return False


def splice_subprocess(xml: str, child_xml: str, scope_id: str) -> str:
	"""xml with the sub-process scope_id holding the steps compiled in child_xml and its own plane redrawn."""
	_register_namespaces()
	root = ET.fromstring(xml)
	child_root = ET.fromstring(child_xml)
	bpmn, bpmndi = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}"
	sub = next(e for e in root.iter(bpmn + "subProcess") if e.get("id") == scope_id)
	for step in [e for e in sub if e.tag not in SUBPROCESS_KEPT_TAGS]:
		sub.remove(step)
	for diagram in root.findall(bpmndi + "BPMNDiagram"):
		if diagram.find(bpmndi + "BPMNPlane").get("bpmnElement") == scope_id:
			root.remove(diagram)
	di_prefixes = tuple("{" + NS[prefix] for prefix in ("bpmndi", "dc", "di"))
	semantic = {e.get("id") for e in root.iter() if e.get("id") and not e.tag.startswith(di_prefixes)}
	for diagram in root.findall(bpmndi + "BPMNDiagram"):
		plane = diagram.find(bpmndi + "BPMNPlane")
		for gone in [e for e in plane if e.get("bpmnElement") not in semantic]:
			plane.remove(gone)
		for shape in plane.findall(bpmndi + "BPMNShape"):
			if shape.get("bpmnElement") == scope_id:
				shape.set("isExpanded", "false")

	_rename_taken_ids(child_root, {e.get("id") for e in root.iter() if e.get("id")}, scope_id)
	sub.extend(child_root.find(bpmn + "process"))
	for scope in sub.iter(bpmn + "subProcess"):
		add_flow_references(scope)
	for diagram in child_root.findall(bpmndi + "BPMNDiagram"):
		diagram.set("id", "BPMNDiagram_" + scope_id)
		plane = diagram.find(bpmndi + "BPMNPlane")
		plane.set("id", "BPMNPlane_" + scope_id)
		plane.set("bpmnElement", scope_id)
		root.append(diagram)
	spliced = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', spliced)


def _rename_taken_ids(child_root: ET.Element, taken: set, suffix: str) -> None:
	"""Rename every id in child_root that is already in taken, and every reference to it."""
	bpmn = "{" + NS["bpmn"] + "}"
	renames = {e.get("id"): e.get("id") + "_" + suffix for e in child_root.iter() if e.get("id") in taken}
	for e in child_root.iter():
		for attr in ID_REF_ATTRS:
			if e.get(attr) in renames:
				e.set(attr, renames[e.get(attr)])
		if e.tag in (bpmn + "incoming", bpmn + "outgoing") and e.text in renames:
			e.text = renames[e.text]


def add_flow_references(scope: ET.Element) -> None:
	"""Give each step of scope the incoming and outgoing flow references the editor and its linter read."""
	bpmn = "{" + NS["bpmn"] + "}"
	steps = {e.get("id"): e for e in scope if e.get("id") and e.tag != bpmn + "sequenceFlow"}
	for flow in scope.findall(bpmn + "sequenceFlow"):
		for ref, tag in ((flow.get("sourceRef"), "outgoing"), (flow.get("targetRef"), "incoming")):
			step = steps.get(ref)
			if step is not None and flow.get("id") not in [c.text for c in step.findall(bpmn + tag)]:
				ET.SubElement(step, bpmn + tag).text = flow.get("id")


def restore_call_activities(old_xml: str, new_xml: str) -> str:
	"""new_xml with each call activity of old_xml put back as it was, so a modify never changes one."""
	_register_namespaces()
	call = "{" + NS["bpmn"] + "}callActivity"
	bpmn = "{" + NS["bpmn"] + "}"
	originals = {e.get("id"): e for e in ET.fromstring(old_xml).iter(call) if e.get("id")}
	if not originals:
		return new_xml
	root = ET.fromstring(new_xml)
	for parent in list(root.iter()):
		for index, child in enumerate(list(parent)):
			original = originals.get(child.get("id"))
			if original is not None:
				kept = copy.deepcopy(original)
				for reference in [c for c in kept if c.tag in (bpmn + "incoming", bpmn + "outgoing")]:
					kept.remove(reference)
				parent[index] = kept
	restored = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', restored)


def unapplied_proposal(conversation: str, current_xml: str, message: str = "") -> dict | None:
	"""What the newest diagram reply adds that the canvas lacks, the request behind it, and which of those the message names."""
	if not (current_xml or "").strip():
		return None
	replies = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Bot"},
		fields=["metadata", "creation"],
		order_by="creation desc",
		limit=RECENT_REPLIES,
	)
	found = [(frappe.parse_json(reply.metadata or "{}").get("agent_result"), reply.creation) for reply in replies]
	result, replied_at = next(
		((r, at) for r, at in found if isinstance(r, dict) and r.get("intent") in DIAGRAM_REPLIES and r.get("bpmn_xml")),
		(None, None),
	)
	if result is None:
		return None
	on_canvas = element_names(current_xml)
	proposed = [
		(kind, name)
		for element_id, (kind, name) in element_names(result["bpmn_xml"]).items()
		if name and kind != "sequenceFlow" and element_id not in on_canvas
	]
	if not proposed:
		return None
	added = [name for _, name in proposed]
	earlier = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "User", "creation": ["<", replied_at]},
		fields=["text"],
		order_by="creation desc",
		limit=RECENT_REPLIES,
	)
	request = next((strip_html(m.text) for m in earlier if m.text and not confirmation_reply(m.text)), "")
	named = [name for name in added if _squash(name) in _squash(message or "")]
	existing = [name for kind, name in on_canvas.values() if kind == "subProcess" and name]
	refers_to_it = DEFINITE_SUBPROCESS.search(message or "") and not any(_is_named(message, name) for name in existing)
	if not named and refers_to_it:
		named = [name for kind, name in proposed if kind == "subProcess"][:1]
	return {"added": added[:8], "request": request, "named": named}


def asks_to_make_call_activity(text: str) -> bool:
	"""True when the message asks to show or turn something into a call activity, which runs a separate process."""
	return bool(CALL_ACTIVITY_CONVERSION.search(text or ""))


def find_missing_target(xml: str, texts: list) -> dict | None:
	"""The name a message asks for a sub-process on when no step or sub-process has it, with the closest names that exist."""
	if not (xml or "").strip():
		return None
	_register_namespaces()
	sub_tag = "{" + NS["bpmn"] + "}subProcess"
	root = ET.fromstring(xml)
	parents = {child: parent for parent in root.iter() for child in parent}
	depth = {}
	known = {}
	existing = [e.get("name") for e in root.iter() if e.tag == "{" + NS["bpmn"] + "}callActivity" and e.get("name")]
	for e in root.iter():
		if e.tag in (*STEP_TAGS, sub_tag) and e.get("id") and e.get("name"):
			ancestors, node = 0, e
			while node in parents:
				node = parents[node]
				ancestors += node.tag == sub_tag
			known.setdefault(e.get("name"), "sub-process" if e.tag == sub_tag else "step")
			depth[e.get("name")] = min(ancestors, depth.get(e.get("name"), ancestors))
	for text in texts:
		match = SUBPROCESS_REQUEST.search(text or "")
		if not match:
			continue
		asked = match.group(1).strip()
		if any(_squash(name) in _squash(asked) or _squash(asked) in _squash(name) for name in (*known, *existing)):
			return None
		similarity = {name: difflib.SequenceMatcher(None, asked.lower(), name.lower()).ratio() for name in known}
		asks_for_new = re.search(r"\bnew\s+sub[\s-]?process", text, re.I)
		close = sorted(
			(name for name in known if similarity[name] >= TYPO_SIMILARITY and not asks_for_new),
			key=lambda name: (depth[name], -similarity[name]),
		)
		return {"asked": asked, "text": text, "candidates": [{"name": name, "kind": known[name]} for name in close[:3]]}
	return None


def _squash(text: str) -> str:
	return re.sub(r"[^a-z0-9]", "", text.lower())


def resolve_step(xml: str, texts: list) -> dict | None:
	"""The step the newest message asking for a sub-process names; a call activity is never converted."""
	if not (xml or "").strip():
		return None
	_register_namespaces()
	steps = [e for e in ET.fromstring(xml).iter() if e.tag in STEP_TAGS and e.get("id") and e.get("name")]
	for text in texts:
		targets = [match[1] for match in (*SUBPROCESS_REQUEST.finditer(text or ""), *BECOME_SUBPROCESS.finditer(text or ""))]
		squashed = _squash(" ".join(targets))
		named = [e for e in steps if _squash(e.get("name")) in squashed]
		if named:
			chosen = max(named, key=lambda e: len(e.get("name")))
			return {"id": chosen.get("id"), "name": chosen.get("name")}
	return None


def convert_step_to_subprocess(xml: str, step_id: str, child_xml: str) -> str:
	"""xml with the step step_id turned into an expanded sub-process holding the steps compiled in child_xml."""
	_register_namespaces()
	root = ET.fromstring(xml)
	child_root = ET.fromstring(child_xml)
	bpmn, bpmndi = "{" + NS["bpmn"] + "}", "{" + NS["bpmndi"] + "}"
	parent = next(p for p in root.iter() if any(c.get("id") == step_id for c in p))
	step = next(c for c in parent if c.get("id") == step_id)
	sub = ET.Element(bpmn + "subProcess", {"id": step_id, "name": step.get("name", "")})
	sub.extend([c for c in step if c.tag in (bpmn + "documentation", bpmn + "incoming", bpmn + "outgoing")])
	parent[list(parent).index(step)] = sub
	_rename_taken_ids(child_root, {e.get("id") for e in root.iter() if e.get("id")}, step_id)
	sub.extend(child_root.find(bpmn + "process"))
	add_flow_references(sub)
	plane = next((p for p in root.iter(bpmndi + "BPMNPlane") if any(s.get("bpmnElement") == step_id for s in p)), None)
	if plane is not None:
		_draw_expanded(plane, step_id, child_root.find(bpmndi + "BPMNDiagram/" + bpmndi + "BPMNPlane"))
	converted = ET.tostring(root, encoding="unicode", xml_declaration=True)
	return re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', converted)


def _draw_expanded(plane: ET.Element, step_id: str, child_plane: ET.Element) -> None:
	"""Grow the step's box to hold the child drawing, make room for it, and draw the steps inside."""
	dc, bpmndi = "{" + NS["dc"] + "}", "{" + NS["bpmndi"] + "}"
	shape = next(s for s in plane.findall(bpmndi + "BPMNShape") if s.get("bpmnElement") == step_id)
	bounds = shape.find(dc + "Bounds")
	x, y, w, h = (float(bounds.get(k)) for k in ("x", "y", "width", "height"))
	left, top, right, bottom = _extent(child_plane)
	new_w = max(200.0, right - left + 2 * EXPANDED_PAD)
	new_h = max(120.0, bottom - top + EXPANDED_PAD + EXPANDED_HEADER)
	_make_room(plane, shape, (x + w, y + h, y + h / 2), max(0.0, new_w - w), max(0.0, new_h - h))
	bounds.set("width", _num(max(w, new_w)))
	bounds.set("height", _num(max(h, new_h)))
	shape.set("isExpanded", "true")
	for drawn in child_plane:
		moved = copy.deepcopy(drawn)
		_shift(moved, x + EXPANDED_PAD - left, y + EXPANDED_HEADER - top, lambda px, py: (px, py))
		plane.append(moved)


def _extent(drawing: ET.Element) -> tuple:
	"""The left, top, right and bottom edges of everything drawn under drawing."""
	dc, di = "{" + NS["dc"] + "}", "{" + NS["di"] + "}"
	xs, ys = [], []
	for b in drawing.iter(dc + "Bounds"):
		xs += [float(b.get("x")), float(b.get("x")) + float(b.get("width"))]
		ys += [float(b.get("y")), float(b.get("y")) + float(b.get("height"))]
	for p in drawing.iter(di + "waypoint"):
		xs.append(float(p.get("x")))
		ys.append(float(p.get("y")))
	return min(xs), min(ys), max(xs), max(ys)


def _make_room(plane: ET.Element, step_shape: ET.Element, edges: tuple, dw: float, dh: float) -> None:
	"""Move what is right of the step by dw and what is below it by dh; widen and heighten the lanes and pool."""
	dc, bpmndi = "{" + NS["dc"] + "}", "{" + NS["bpmndi"] + "}"
	right, bottom, centre = edges
	horizontal = [s for s in plane.findall(bpmndi + "BPMNShape") if s.get("isHorizontal") == "true"]
	containing = []
	for lane in horizontal:
		b = lane.find(dc + "Bounds")
		if float(b.get("y")) <= centre <= float(b.get("y")) + float(b.get("height")):
			containing.append(float(b.get("y")) + float(b.get("height")))
	lane_bottom = min(containing) if containing else None
	for drawn in plane:
		if drawn is step_shape:
			continue
		if drawn in horizontal:
			b = drawn.find(dc + "Bounds")
			b.set("width", _num(float(b.get("width")) + dw))
			top, height = float(b.get("y")), float(b.get("height"))
			if top <= centre <= top + height:
				b.set("height", _num(height + dh))
			elif lane_bottom is not None and top >= lane_bottom:
				b.set("y", _num(top + dh))
			continue
		_shift(drawn, 0, 0, lambda px, py: (px + dw if px >= right else px, py + dh if py >= bottom else py))


def _shift(drawn: ET.Element, dx: float, dy: float, rule) -> None:
	"""Move a shape, with its label, or an edge point by point: each point moves as rule says, then by dx and dy."""
	dc, di = "{" + NS["dc"] + "}", "{" + NS["di"] + "}"
	own = drawn.find(dc + "Bounds")
	pinned = None if own is None else _offset(own, rule)
	for b in drawn.iter(dc + "Bounds"):
		ox, oy = pinned or _offset(b, rule)
		b.set("x", _num(float(b.get("x")) + ox + dx))
		b.set("y", _num(float(b.get("y")) + oy + dy))
	for p in drawn.iter(di + "waypoint"):
		ox, oy = _offset(p, rule)
		p.set("x", _num(float(p.get("x")) + ox + dx))
		p.set("y", _num(float(p.get("y")) + oy + dy))


def _offset(point: ET.Element, rule) -> tuple:
	x, y = float(point.get("x")), float(point.get("y"))
	new_x, new_y = rule(x, y)
	return new_x - x, new_y - y


def _num(value: float) -> str:
	return str(int(value)) if value == int(value) else str(round(value, 2))


def format_removal_warning(removed_elements: list) -> str:
	"""The message asking the user to confirm a change that drops configured shapes."""
	lines = [
		_(
			"I've prepared the changes, but the following configured shapes will be removed and their settings will be lost:\n"
		)
	]
	for elem in removed_elements:
		line = _("• **{0}** ({1})").format(elem["name"], elem["type"])
		configs = elem["configs"]
		if configs:
			detail = list(configs[:3])
			if len(configs) > 3:
				detail.append(_("and {0} more").format(len(configs) - 3))
			line = line + " - " + ", ".join(detail)
		lines.append(line)
	lines.append(
		_(
			"\nThese configurations (scripts, assignments, triggers, documentation, etc.) cannot be recovered after applying the changes.\n\nShall I apply the changes anyway?"
		)
	)
	return "\n".join(lines)


def extract_configured_elements(xml: str) -> dict:
	"""Every BPMN element carrying extension attributes, extension elements or documentation, by id."""
	if not xml or not xml.strip():
		return {}
	_register_namespaces()
	root = ET.fromstring(xml)
	configured = {}
	for elem in root.iter():
		tag = elem.tag
		if any(ns in tag for ns in (NS["bpmndi"], NS["dc"], NS["di"])):
			continue
		elem_id = elem.get("id")
		if not elem_id:
			continue
		ext_attrs = {name: value for name, value in elem.attrib.items() if _is_extension_attr(name)}
		ext_elements_xml = None
		ext_el = elem.find("{" + NS["bpmn"] + "}extensionElements")
		if ext_el is not None and len(ext_el) > 0:
			ext_elements_xml = ET.tostring(ext_el, encoding="unicode")
		documentation = _get_documentation_text(elem)
		if ext_attrs or ext_elements_xml or documentation:
			configured[elem_id] = {
				"name": elem.get("name", elem_id),
				"type": _element_type_label(tag),
				"attrs": ext_attrs,
				"extension_elements_xml": ext_elements_xml,
				"documentation": documentation,
			}
	return configured


def summarize_configured_elements(configured: dict) -> str:
	"""The overwrite warning text for shapes that carry configuration."""
	lines = [
		_(
			"This will completely replace the existing diagram. The following shapes have configurations that will be lost:\n"
		)
	]
	for data in configured.values():
		config_labels = []
		for clark in data["attrs"]:
			label = _attr_label(clark)
			if label not in config_labels:
				config_labels.append(label)
		if data.get("extension_elements_xml"):
			config_labels.append(_("Extension Elements"))
		if data.get("documentation"):
			config_labels.append(_("Documentation"))
		line = _("• **{0}** ({1})").format(data["name"], data["type"])
		if config_labels:
			line = line + " - " + ", ".join(config_labels[:4])
			if len(config_labels) > 4:
				line = line + " " + _("and {0} more").format(len(config_labels) - 4)
		lines.append(line)
	lines.append(_("\nAll of these configurations will be lost. Are you sure you want to proceed?"))
	return "\n".join(lines)


def describe_task_config(xml: str, previous_xml: str = "") -> str:
	"""The settings on the diagram's shapes as plain sentences, leaving out any previous_xml already had; "" when none."""
	before = extract_configured_elements(previous_xml)
	lines = []
	for elem_id, data in extract_configured_elements(xml).items():
		config = {_local_name(clark): value for clark, value in data["attrs"].items()}
		previous = {_local_name(clark): value for clark, value in before.get(elem_id, {}).get("attrs", {}).items()}
		if elem_id in before and previous == config:
			continue
		kind = data["type"].replace(" ", "")
		if kind == "StartEvent" and config.get("triggerDoctype"):
			lines.append(_("The process starts when a new {0} is created.").format(config["triggerDoctype"]))
		elif kind == "ServiceTask":
			lines.append(_service_task_sentence(data["name"], config))
		elif kind == "UserTask":
			lines.append(_user_task_sentence(data["name"], config))
	lines = [line for line in lines if line]
	if not lines:
		return ""
	return "\n\n" + _("I also set these up on the steps:") + "\n" + "\n".join("- " + line for line in lines)


def _service_task_sentence(name: str, config: dict) -> str:
	service = config.get("serviceType")
	if service == "apply_workflow":
		return _("{0} moves the {1} to {2}.").format(
			name, config.get("serviceTargetDoctype") or _("document"), config.get("workflowState") or _("its next state")
		)
	if service == "send_email":
		return _("{0} sends an email.").format(name)
	if service == "update_field":
		return _("{0} updates a field on the {1}.").format(name, config.get("updateFieldDoctype") or _("document"))
	if service == "google_chat":
		return _("{0} sends a Google Chat message.").format(name)
	if service == "push_notification":
		return _("{0} sends a push notification.").format(name)
	if service == "connector":
		return _("{0} runs the {1} connector.").format(name, config.get("connectorId") or "")
	return ""


def _user_task_sentence(name: str, config: dict) -> str:
	parts = []
	if config.get("targetDoctype"):
		parts.append(_("works on the {0}").format(config["targetDoctype"]))
	mode = config.get("assigneeMode")
	if mode == "User" and config.get("assigneeUser"):
		parts.append(_("is assigned to {0}").format(config["assigneeUser"]))
	elif mode == "DocField" and config.get("assigneeDocfield"):
		parts.append(_("is assigned to the person in the {0} field").format(config["assigneeDocfield"]))
	elif mode == "Table Field" and config.get("assigneeTableField"):
		parts.append(_("is assigned to the people in the {0} table").format(config["assigneeTableField"]))
	elif mode == "Round Robin":
		parts.append(_("is assigned by round robin"))
	elif mode == "Load Balancing":
		parts.append(_("is assigned by load balancing"))
	elif mode:
		parts.append(_("has no one chosen to do it yet"))
	actions = config.get("taskActions") or []
	if isinstance(actions, str):
		actions = json.loads(actions)
	actions = [a.get("action") if isinstance(a, dict) else a for a in actions]
	actions = [str(a) for a in actions if a]
	if actions:
		parts.append(_("has the buttons {0}").format(", ".join(actions)))
	if not parts:
		return ""
	return _("{0} {1}.").format(name, ", ".join(parts))


def describe_changes(previous_xml: str, xml: str) -> str:
	"""What a modify added, removed and renamed on the diagram, as plain lines; says so when nothing changed."""
	before = element_names(previous_xml)
	after = element_names(xml)
	lines = []
	for elem_id, (kind, name) in after.items():
		if kind == "sequenceFlow":
			continue
		if elem_id not in before:
			lines.append(_("Added {0}.").format(_element_label(kind, name)))
			continue
		old_name = before[elem_id][1]
		if name and old_name and name != old_name:
			lines.append(_("Renamed {0} to {1}.").format(_element_label(kind, old_name), _quoted(name)))
	for elem_id, (kind, name) in before.items():
		if kind != "sequenceFlow" and elem_id not in after:
			lines.append(_("Removed {0}.").format(_element_label(kind, name)))
	# Paths are compared by label, since a modify may give an unchanged path a new id.
	old_paths = Counter(name for kind, name in before.values() if kind == "sequenceFlow" and name)
	new_paths = Counter(name for kind, name in after.values() if kind == "sequenceFlow" and name)
	for name in (new_paths - old_paths).elements():
		lines.append(_("Added {0}.").format(_element_label("sequenceFlow", name)))
	for name in (old_paths - new_paths).elements():
		lines.append(_("Removed {0}.").format(_element_label("sequenceFlow", name)))
	lines += _moved_arrows(previous_xml, xml)
	if not lines:
		return "\n\n" + _("I could not find any change on the diagram. Check that your request was applied.")
	return "\n\n" + _("What changed:") + "\n" + "\n".join("- " + line for line in lines)


def _moved_arrows(previous_xml: str, xml: str) -> list[str]:
	"""Arrows between steps that exist before and after whose source or target changed, as plain lines."""
	old_names = {i: name for i, (kind, name) in element_names(previous_xml).items() if kind != "sequenceFlow"}
	new_names = {i: name for i, (kind, name) in element_names(xml).items() if kind != "sequenceFlow"}

	def arrows(text):
		found = Counter()
		for attrs in re.findall(r"<bpmn:sequenceFlow\s([^>]*?)/?>", text or ""):
			values = {key: val for key, val in re.findall(r'(\w+)="([^"]*)"', attrs)}
			found[(values.get("sourceRef"), values.get("targetRef"), values.get("name", ""))] += 1
		return found

	gone = list((arrows(previous_xml) - arrows(xml)).elements())
	lines = []
	for source, target, label in (arrows(xml) - arrows(previous_xml)).elements():
		if source not in old_names or target not in old_names:
			continue
		match = next(
			(
				old
				for old in gone
				if old[2] == label and (old[0] == source) != (old[1] == target) and old[0] in new_names and old[1] in new_names
			),
			None,
		)
		if match:
			gone.remove(match)
			lines.append(
				_("Moved the arrow from {0} to {1}.").format(_quoted(new_names[source] or source), _quoted(new_names[target] or target))
			)
	return lines

IR_NODE_TYPES = frozenset(
	{
		"startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent", "userTask", "scriptTask",
		"serviceTask", "manualTask", "businessRuleTask", "exclusiveGateway", "parallelGateway", "inclusiveGateway",
		"subProcess", "callActivity",
	}
)  # fmt: skip


def xml_to_ir(xml: str) -> dict | None:
	"""The IR that draws xml again, or None when xml has an element the IR cannot hold."""
	bpmn = "{" + NS["bpmn"] + "}"
	process = next(iter(ET.fromstring(xml).iter(bpmn + "process")), None)
	if process is None:
		return None
	lane_of = {}
	lanes = []
	for lane in process.iter(bpmn + "lane"):
		lanes.append({"id": lane.get("id"), "name": lane.get("name") or lane.get("id")})
		for ref in lane.findall(bpmn + "flowNodeRef"):
			lane_of[(ref.text or "").strip()] = lane.get("id")

	def scope(parent):
		nodes, flows = [], []
		for elem in parent:
			tag = elem.tag.removeprefix(bpmn)
			if tag in IR_NODE_TYPES:
				node = {"id": elem.get("id"), "name": elem.get("name") or "", "type": tag}
				if elem.get("id") in lane_of:
					node["lane"] = lane_of[elem.get("id")]
				if elem.get("calledElement"):
					node["calledElement"] = elem.get("calledElement")
				if tag == "subProcess":
					inner = scope(elem)
					if inner is None:
						return None
					node["children"] = inner
				nodes.append(node)
			elif tag == "sequenceFlow":
				flow = {"id": elem.get("id"), "from": elem.get("sourceRef"), "to": elem.get("targetRef")}
				if elem.get("name"):
					flow["name"] = elem.get("name")
				body = elem.find(bpmn + "conditionExpression")
				if body is not None and body.text:
					flow["condition"] = body.text
				if parent.get("default") == elem.get("id"):
					flow["default"] = True
				flows.append(flow)
			elif tag not in ("laneSet", "extensionElements", "incoming", "outgoing", "documentation"):
				return None
		return {"nodes": nodes, "flows": flows}

	body = scope(process)
	if body is None:
		return None
	return {"name": process.get("name") or "", "lanes": lanes, **body}


def diagram_geometry(xml: str) -> list:
	"""Every drawn shape and arrow of xml with its position, in a stable order."""
	bpmndi, dc, di = ("{" + NS[prefix] + "}" for prefix in ("bpmndi", "dc", "di"))
	drawn = []
	for elem in ET.fromstring(xml).iter():
		if elem.tag in (bpmndi + "BPMNShape", bpmndi + "BPMNEdge"):
			points = [(b.get("x"), b.get("y"), b.get("width"), b.get("height")) for b in elem.iter(dc + "Bounds")]
			points += [(p.get("x"), p.get("y")) for p in elem.iter(di + "waypoint")]
			drawn.append((elem.get("bpmnElement"), tuple(points)))
	return sorted(drawn)


def relayout(xml: str) -> tuple[str | None, str]:
	"""(new xml, "") with the diagram drawn again and every id and setting kept; (None, reason) when it cannot be."""
	if not has_lanes(xml):
		return None, "lane-less"
	ir = xml_to_ir(xml)
	if ir is None:
		return None, "unsupported"
	compiled = compile_ir(ir)
	if not compiled.get("ok") or not compiled.get("xml"):
		return None, "failed"
	merged, _removed = transfer_properties(xml, compiled["xml"])
	if element_names(merged).keys() != element_names(xml).keys():
		return None, "ids-changed"
	if diagram_geometry(merged) == diagram_geometry(xml):
		return None, "same"
	return merged, ""


LIST_ITEM = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|[a-z][.)])\s+(.+?)\s*$", re.I)


def spec_items(text: str) -> list[str]:
	"""The bulleted or numbered lines of text, without their markers."""
	lines = unescape_entities(re.sub(r"<[^>]+>", "", re.sub(r"<(?:br|/p|/li|/div)[^>]*>", "\n", text or ""))).splitlines()
	return [m.group(1) for line in lines if (m := LIST_ITEM.match(line))]


def missing_spec_items(xml: str, spec: str) -> list[str]:
	"""The list items of spec that no step on the diagram shares two significant words with."""
	return [item for item in spec_items(spec) if len(item.split()) > 1 and not similar_steps(xml, [item])]


def compare_output(xml: str, texts: list) -> dict:
	"""The reply to a pasted specification asked about "what is missing": the gaps, and a question before adding them."""
	spec = next((text for text in texts if len(spec_items(text or "")) > 1), "")
	if not spec:
		return {
			"intent": "CLARIFY",
			"response": _("Paste the list of steps you want to check, one per line, and I will tell you which are missing."),
		}
	missing = missing_spec_items(xml, spec)
	if not missing:
		return {"intent": "CLARIFY", "response": _("Every item in your list is already on the diagram, so I changed nothing.")}
	listing = "\n".join("- " + item for item in missing)
	return {
		"intent": "CONFIRM",
		"action_intent": "MODIFY_EXISTING",
		"response": _("These items from your list are not on the diagram:") + "\n" + listing + "\n\n" + _("Shall I add them?"),
		"options": [_("Yes, proceed"), _("No, let me adjust")],
	}


def relayout_output(xml: str) -> dict:
	"""The reply to a confirmed re-layout: the diagram drawn again, or why nothing changed."""
	new_xml, reason = relayout(xml)
	if new_xml:
		return {
			"intent": "BPMN_MODIFIED",
			"action_intent": "RELAYOUT",
			"bpmn_xml": new_xml,
			"response": _("I laid the diagram out again. Every step, arrow and setting is kept. Review it on the canvas."),
			"options": [],
		}
	if reason == "same":
		say = _("The layout is already the best I can make, so I changed nothing.")
	elif reason == "lane-less":
		say = _("This diagram has no lanes, so the editor lays it out itself. I changed nothing.")
	else:
		say = _("I could not lay the diagram out again without risking your steps, so I changed nothing.")
	return {"intent": "CLARIFY", "response": say}


def similar_steps(xml: str, texts: list, skip: str = "") -> list[str]:
	"""Up to three steps in xml sharing two or more significant words with the newest request in texts, best first."""
	request = next((strip_html(text) for text in texts if text and not confirmation_reply(text)), "")
	skipped = {word[:5] for word in re.findall(r"[a-z]{4,}", skip.lower())}
	wanted = {
		word[:5] for word in re.findall(r"[a-z]{4,}", request.split(":", 1)[-1].lower()) if word not in REQUEST_STOPWORDS
	} - skipped
	scored = []
	for elem in ET.fromstring(xml).iter():
		if elem.tag in STEP_TAGS and elem.get("name"):
			shared = len(wanted & {word[:5] for word in re.findall(r"[a-z]{4,}", elem.get("name").lower())})
			if wanted and shared >= min(2, len(wanted)):
				scored.append((shared, elem.get("name")))
	scored.sort(key=lambda entry: -entry[0])
	return [name for _, name in scored[:3]]


def no_change_reply(where: str, similar: list[str]) -> str:
	"""The answer when a modify changed nothing: what already covers the request and what to say next."""
	if not similar:
		return _("I did not change {0}. Tell me which step to add or change, and where it goes.").format(where)
	label = _("the step") if len(similar) == 1 else _("the steps")
	return _("I did not change {0}. It already has {1} {2}. Tell me what else to add or change, and where it goes.").format(
		where, label, ", ".join(_quoted(name) for name in similar)
	)


def describe_links(previous_xml: str, xml: str) -> str:
	"""Unlabeled paths added or removed between steps that exist before and after, as plain lines; "" when none."""
	if not (previous_xml or "").strip() or not (xml or "").strip():
		return ""
	old_root, new_root = ET.fromstring(previous_xml), ET.fromstring(xml)
	old_names, new_names = _names_by_id(old_root), _names_by_id(new_root)
	old_links, new_links = _unlabeled_links(old_root), _unlabeled_links(new_root)
	lines = [
		_("Connected {0} to {1}.").format(_quoted(new_names[source]), _quoted(new_names[target]))
		for source, target in new_links - old_links
		if source in old_names and target in old_names
	]
	lines += [
		_("Disconnected {0} from {1}.").format(_quoted(old_names[source]), _quoted(old_names[target]))
		for source, target in old_links - new_links
		if source in new_names and target in new_names
	]
	if not lines:
		return ""
	return "\n\n" + _("What changed:") + "\n" + "\n".join("- " + line for line in lines)


def _names_by_id(root: ET.Element) -> dict:
	return {e.get("id"): e.get("name") or e.get("id") for e in root.iter() if e.get("id")}


def _unlabeled_links(root: ET.Element) -> Counter:
	flow = "{" + NS["bpmn"] + "}sequenceFlow"
	return Counter((f.get("sourceRef"), f.get("targetRef")) for f in root.iter(flow) if not f.get("name"))


def lint_fix_requested(texts: list) -> bool:
	"""True when the newest message that is not a yes or a no asks to fix lint findings."""
	request = next((strip_html(text) for text in texts if text and not confirmation_reply(text)), "")
	return bool(LINT_FIX_REQUEST.search(request))


def lint_findings(xml: str, issues: list, scope_id: str = "") -> dict | None:
	"""The findings to fix in the process or sub-process to edit, those that need a person, and the rest by place."""
	if not (xml or "").strip() or not issues:
		return None
	_register_namespaces()
	root = ET.fromstring(xml)
	sub_tag = "{" + NS["bpmn"] + "}subProcess"
	parents = {child: node for node in root.iter() for child in node}
	elements = {e.get("id"): e for e in root.iter() if e.get("id")}
	subs = {e.get("id"): e for e in root.iter(sub_tag)}
	found = []
	for issue in issues[:MAX_LINT_FINDINGS]:
		element = elements.get(issue.get("id"))
		rule = str(issue.get("rule") or "").rsplit("/", 1)[-1]
		inside = element is not None and element.tag == sub_tag and rule in LINT_ABOUT_CONTENTS
		node = element if inside else parents.get(element)
		while node is not None and node.tag != sub_tag:
			node = parents.get(node)
		found.append(
			{
				"id": str(issue.get("id") or ""),
				"name": (element.get("name") if element is not None else "") or str(issue.get("id") or ""),
				"rule": rule,
				"message": str(issue.get("message") or ""),
				"category": str(issue.get("category") or "warn"),
				"owner": node.get("id") if node is not None else "",
			}
		)
	fixable = [f for f in found if f["rule"] not in LINT_NOT_FIXABLE]
	by_owner = Counter(f["owner"] for f in fixable)
	chosen = scope_id if scope_id in subs else ""
	if not chosen and by_owner and "" not in by_owner:
		chosen = by_owner.most_common(1)[0][0]
	return {
		"scope": resolve_scope(xml, [], chosen) if chosen else None,
		"fix": [f for f in fixable if f["owner"] == chosen],
		"left": [f for f in found if f["rule"] in LINT_NOT_FIXABLE],
		"elsewhere": [
			(subs[owner].get("name") or owner if owner else "", count) for owner, count in by_owner.items() if owner != chosen
		],
	}


def lint_prompt(findings: dict) -> str:
	"""The findings to fix, one per line, under where they sit."""
	where = findings["scope"]["name"] if findings["scope"] else "the main process"
	lines = [
		"- [{0}] {1} (id {2}): {3} ({4})".format(f["category"], _quoted(f["name"]), f["id"], f["message"], f["rule"])
		for f in findings["fix"]
	]
	return "In {0}:\n{1}".format(where, "\n".join(lines))


def lint_leftovers(findings: dict) -> str:
	"""What a lint fix did not touch: findings in other places and findings that need a person."""
	parts = []
	for name, count in findings["elsewhere"]:
		parts.append(_("{0} in {1}").format(count, _quoted(name) if name else _("the main process")))
	if findings["left"]:
		parts.append(_("{0} that need a person to fix").format(len(findings["left"])))
	if not parts:
		return ""
	return "\n\n" + _("Not fixed: {0}. Ask me again from there, or fix them in the editor.").format(", ".join(parts))


def no_lint_fix_reply(findings: dict | None) -> str:
	"""The answer to a request to fix lint findings when there is nothing ProsAlly can change."""
	if not findings:
		return _("The editor shows no lint findings to fix. If you expect some, open the lint panel and ask again.")
	lines = "\n".join("- {0}: {1}".format(_quoted(f["name"]), f["message"]) for f in findings["left"])
	return _("None of these findings can be fixed by changing the steps and paths, so they need a person in the editor:") + (
		"\n" + lines
	)


def describe_lanes(chat_history: list, user_text: str, ir: dict | None) -> str:
	"""The lanes drawn, and any lane the person named that is not among them; "" when no lanes were drawn."""
	drawn = [lane.get("name") for lane in (ir or {}).get("lanes") or [] if lane.get("name")]
	if not drawn:
		return ""
	text = "\n\n" + _("Lanes drawn:") + "\n" + "\n".join("- " + lane for lane in drawn)
	asked = [e.get("content") or "" for e in chat_history if (e.get("role") or e.get("type")) == "user"]
	missing = [
		lane
		for lane in requested_lanes([*asked, user_text or ""])
		if not any(lane.lower() in d.lower() or d.lower() in lane.lower() for d in drawn)
	]
	if missing:
		text += "\n\n" + _("You also asked for {0}, which I did not draw. Ask me to add it.").format(
			", ".join(missing)
		)
	return text


def requested_lanes(texts: list) -> list[str]:
	"""The lane names listed after "lanes" in the latest of texts that lists two or more, else []."""
	for text in reversed(texts):
		for match in _LANE_LIST.finditer(strip_html(text)):
			names = [
				re.sub(r"^the\s+", "", n.strip(), flags=re.I) for n in re.split(r",|\band\b|&", match[1])
			]
			names = [n for n in names if n and n[0].isupper() and len(n.split()) <= 4]
			if len(names) >= 2:
				return names
	return []


def _element_label(kind: str, name: str) -> str:
	return _ELEMENT_WORDS.get(kind, "the element") + (" " + _quoted(name) if name else "")


def _quoted(name: str) -> str:
	return '"' + name + '"'


def _copy_configuration(new_elem, old_data: dict) -> None:
	for clark, value in old_data["attrs"].items():
		new_elem.set(clark, value)
	if old_data["extension_elements_xml"]:
		new_ext_el = new_elem.find("{" + NS["bpmn"] + "}extensionElements")
		if new_ext_el is None:
			new_ext_el = ET.SubElement(new_elem, "{" + NS["bpmn"] + "}extensionElements")
		for child in ET.fromstring(old_data["extension_elements_xml"]):
			new_ext_el.append(child)
	if old_data.get("documentation"):
		_set_documentation(new_elem, old_data["documentation"])


def _config_descriptions(old_data: dict) -> list:
	configs = [_attr_label(clark) + ": " + value for clark, value in old_data["attrs"].items()]
	if old_data["extension_elements_xml"]:
		configs.append(_("Extension Elements (pre/post scripts or other)"))
	if old_data.get("documentation"):
		preview = old_data["documentation"][:80]
		if len(old_data["documentation"]) > 80:
			preview = preview + "…"
		configs.append(_("Documentation: {0}").format(preview))
	return configs


def _register_namespaces() -> None:
	for prefix, uri in NS.items():
		ET.register_namespace(prefix, uri)


def _is_extension_attr(attr_name: str) -> bool:
	return any(attr_name.startswith(uri) for uri in EXTENSION_NS_URIS)


def _attr_label(clark_name: str) -> str:
	local = clark_name.split("}", 1)[1] if "}" in clark_name else clark_name
	return _(ATTR_FAMILY_LABELS.get(local, local))


def _local_name(clark_name: str) -> str:
	return clark_name.split("}", 1)[1] if "}" in clark_name else clark_name


def _element_type_label(tag: str) -> str:
	local = tag.split("}", 1)[-1] if "}" in tag else tag
	return re.sub(r"([a-z])([A-Z])", r"\1 \2", local).title()


def _get_documentation_text(elem):
	doc_el = elem.find("{" + NS["bpmn"] + "}documentation")
	if doc_el is not None and doc_el.text:
		return doc_el.text.strip()
	return None


def _set_documentation(elem, text: str) -> None:
	doc_tag = "{" + NS["bpmn"] + "}documentation"
	doc_el = elem.find(doc_tag)
	if doc_el is not None:
		if not (doc_el.text or "").strip():
			doc_el.text = text
	else:
		doc_el = ET.Element(doc_tag)
		doc_el.text = text
		elem.insert(0, doc_el)
