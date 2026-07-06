# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
AI Agent Task configuration assistant.

Powers the in-modal chat panel on the AI Agent Task config page. The assistant
uses the SAME AI Provider the designer has selected for the task to recommend
values for the task's fields (prompts, model, output variable, response format,
advanced limits) based on a plain-language requirement.

It can optionally look at a context DocType's schema and one sample record so
its prompt suggestions reference real field names. Schema and record reads go
through Frappe's permission system (frappe.get_meta / frappe.get_doc), so a
designer only ever sees data they are already allowed to read.

No LLM SDK lives here — the call is made through the shared executor backends
(direct_api / antigravity), exactly like a real AI Agent Task dispatch.
"""
from __future__ import annotations

import json

import frappe
from frappe import _


# Catalogue of the task-config fields the assistant is allowed to recommend.
# Keys match the spiffworkflow:ai* attribute names (without the prefix) and the
# AIAgentConfigModal form keys exactly, so the frontend can apply them 1:1.
FIELD_CATALOG = {
	"aiBackend":        'Executor backend — "direct_api" or "antigravity".',
	"aiModel":          "Model name override (blank = provider default).",
	"aiOutputVariable": "Process variable name to store the result, e.g. ai_result.",
	"aiSystemPrompt":   "System prompt. Jinja2 — {{ doc }}, {{ instance }} available.",
	"aiUserPrompt":     "User prompt / task instruction. Jinja2 supported.",
	"aiResponseFormat": '"text" or "json".',
	"aiResponseSchema": "JSON Schema string (only meaningful when format is json).",
	"aiTemperature":    "Float 0.0–2.0.",
	"aiTopP":           "Float 0.0–1.0.",
	"aiMaxTokens":      "Integer — max output tokens.",
	"aiTimeout":        "Integer — request timeout in seconds.",
	"aiMaxRetries":     "Integer — number of retries on transient failure.",
}

# Fields the assistant may recommend in SELECTOR mode (AI Task Selector on an
# ad-hoc subprocess). Mirrors what the selector dispatch reads at runtime and
# the modal's selector-mode form. aiProvider is deliberately absent — the
# designer picks it, and it powers the assistant itself.
SELECTOR_FIELD_CATALOG = {
	"aiModel":        "Model name override (blank = provider default).",
	"aiSystemPrompt": "The selection procedure: rules for which task to activate at each decision point, referencing tasks by their BPMN id.",
	"aiUserPrompt":   "The evidence template. Jinja2 — {{ doc.<field> }} for the live context document, process variables like {{ my_var }}, and {% if my_var is defined %} guards for variables that appear mid-process.",
	"aiMaxTokens":    "Integer — max output tokens per decision.",
	"aiTimeout":      "Integer — request timeout in seconds per decision.",
}

# Layout-only / non-data field types skipped when summarising a DocType schema.
_SKIP_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}

_MAX_SCHEMA_FIELDS = 120
_MAX_SAMPLE_CHARS = 4000

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# Mirrors tool_pool eligibility (2026-07-02 decision): only leaf task
# activities with no incoming sequence flow are selector candidates.
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


@frappe.whitelist()
def recommend_ai_task_config(
	provider: str,
	backend: str = "direct_api",
	requirement: str = "",
	context_doctype: str = "",
	context_docname: str = "",
	history: str = "[]",
	mode: str = "agent",
	bpmn_xml: str = "",
	element_id: str = "",
	current_config: str = "{}",
	process_model: str = "",
) -> dict:
	"""Return assistant recommendations for an AI Agent Task's configuration.

	Args:
		provider: AI Provider name powering the assistant (the task's own provider).
		backend: Executor backend ("direct_api" | "antigravity").
		requirement: The designer's latest chat message.
		context_doctype: Optional DocType whose schema/sample to show the model.
		context_docname: Optional specific record; if blank, the latest readable
			record of context_doctype is used as the sample.
		history: JSON array of prior turns [{"role": "...", "content": "..."}].
		mode: "agent" (AI Agent Task) or "selector" (AI Task Selector on an
			ad-hoc subprocess). Selector mode teaches the model the selector
			runtime semantics and shows it the diagram digest.
		bpmn_xml: The LIVE diagram XML from the editor canvas (selector mode) —
			the saved model may be stale while the designer edits.
		element_id: BPMN id of the ad-hoc subprocess being configured.
		current_config: JSON of the form's current values so the assistant can
			refine drafts instead of starting over.

	Returns:
		{"ok": True, "message": str, "recommendations": {field: value, ...}}
		or {"ok": False, "error_code": str, "message": str} on failure.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to use the assistant."))

	if not provider:
		frappe.throw(_("Select an AI Provider before using the assistant."))

	if not frappe.db.exists("AI Provider", provider):
		frappe.throw(_("AI Provider '{0}' not found.").format(provider))

	if not (requirement or "").strip():
		frappe.throw(_("Describe what you want the AI Agent Task to do."))

	mode = mode if mode in ("agent", "selector") else "agent"
	catalog = _catalog_for_mode(mode)

	turns = _parse_history(history)
	context_block = _build_context_block(context_doctype, context_docname)

	digest = None
	if mode == "selector":
		digest = _build_diagram_digest(bpmn_xml, element_id, process_model=process_model)
		system_prompt = _build_selector_system_prompt()
	else:
		system_prompt = _build_system_prompt()
	user_prompt = _build_user_prompt(
		requirement,
		turns,
		context_block,
		diagram_block=digest["block"] if digest else "",
		current_config_block=_build_current_config_block(current_config, catalog),
	)

	from one_bpmn.agents.executor import (
		ExecutorConfig,
		ExecutorContext,
		ErrorCode,
		get_executor,
	)
	# Importing the backend modules registers them in the executor registry.
	from one_bpmn.agents.executor import direct_api, antigravity  # noqa: F401

	backend = backend or "direct_api"
	try:
		executor_cls = get_executor(backend)
	except ValueError:
		frappe.throw(_("Unknown executor backend '{0}'.").format(backend))

	config = ExecutorConfig(
		backend=backend,
		provider_name=provider,
		model="",  # blank -> provider's default_model
		system_prompt=system_prompt,
		user_prompt=user_prompt,
		temperature=0.3,
		top_p=1.0,
		# Generous: reasoning models (gpt-5 family) spend completion budget
		# on hidden reasoning first — 1800 yielded empty visible output.
		max_tokens=6000,
		timeout_seconds=60,
		response_format="text",  # parsed tolerantly below
		max_retries=1,
	)

	result = executor_cls().run(config, ExecutorContext(jinja_context={}))

	if result.error_code != ErrorCode.SUCCESS:
		return {
			"ok": False,
			"error_code": result.error_code.value,
			"message": result.error_message or _("The assistant request failed."),
		}

	if not (result.output or "").strip() if isinstance(result.output, str) else not result.output:
		# Reasoning models can exhaust the completion budget on hidden
		# reasoning and return nothing visible — surface it instead of a
		# silent empty recommendation set.
		return {
			"ok": False,
			"error_code": "EMPTY_OUTPUT",
			"message": _(
				"The model returned no visible text — its token budget was "
				"likely consumed by internal reasoning. Try again, or use a "
				"different model for the assistant."
			),
		}

	parsed = _extract_json(result.output if isinstance(result.output, str) else json.dumps(result.output))
	if not isinstance(parsed, dict):
		# Model answered but not as JSON — surface the text, no field changes.
		text = result.output if isinstance(result.output, str) else _("No recommendation returned.")
		return {"ok": True, "message": text, "recommendations": {}}

	message = str(parsed.get("message", "")).strip()
	raw_recs = parsed.get("recommendations") or {}
	recommendations = {}
	if isinstance(raw_recs, dict):
		for key, value in raw_recs.items():
			if key in catalog and value not in (None, ""):
				recommendations[key] = value

	# Post-check (selector mode): every task id a recommended prompt mentions
	# must exist on the diagram, and every candidate should be covered.
	if digest:
		warnings = _lint_recommended_prompts(recommendations, digest)
		if warnings:
			message = (message + "\n\n" if message else "") + "\n".join(f"⚠️ {w}" for w in warnings)

	return {"ok": True, "message": message, "recommendations": recommendations}


def _catalog_for_mode(mode: str) -> dict:
	return SELECTOR_FIELD_CATALOG if mode == "selector" else FIELD_CATALOG


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
	field_lines = "\n".join(f'  - "{name}": {desc}' for name, desc in FIELD_CATALOG.items())
	return (
		"You are a configuration assistant embedded in a BPMN editor. You help a "
		"process designer configure an 'AI Agent Task' — a workflow step that makes "
		"a single LLM call at runtime.\n\n"
		"At runtime the task renders its prompts with Jinja2 against a context "
		"document, exposing {{ doc }} (the context record), {{ instance }} (the BPMN "
		"process instance) and {{ frappe }}. The task stores the model's reply in a "
		"process variable named by aiOutputVariable, which downstream gateways and "
		"script tasks can read.\n\n"
		"Based on the designer's requirement (and any DocType schema / sample record "
		"provided), recommend values for these fields:\n"
		f"{field_lines}\n\n"
		"Guidance:\n"
		"  - Write clear, specific prompts. Use Jinja {{ doc.<fieldname> }} placeholders "
		"that match the provided schema field names.\n"
		"  - Suggest a concise snake_case aiOutputVariable.\n"
		"  - Use aiResponseFormat 'json' (with an aiResponseSchema) only when the task "
		"should return structured data; otherwise 'text'.\n"
		"  - Only include a field in 'recommendations' when you have a concrete value "
		"for it. Omit fields you are unsure about.\n\n"
		"Respond with ONLY a single JSON object, no prose outside it, in this exact shape:\n"
		'{\n'
		'  "message": "<a short, friendly explanation of what you suggested>",\n'
		'  "recommendations": { "aiUserPrompt": "...", "aiOutputVariable": "...", ... }\n'
		'}'
	)


def _build_selector_system_prompt() -> str:
	field_lines = "\n".join(f'  - "{name}": {desc}' for name, desc in SELECTOR_FIELD_CATALOG.items())
	return (
		"You are a configuration assistant embedded in a BPMN editor. You help a "
		"process designer write the prompts for an 'AI Task Selector' — an ad-hoc "
		"subprocess where an LLM decides, one decision at a time, which inner task "
		"to activate next.\n\n"
		"HOW THE SELECTOR RUNS (these facts are non-negotiable — your prompts must "
		"work within them):\n"
		"  1. Every decision is a FRESH, stateless LLM call. The only memory between "
		"decisions is process data, surfaced through Jinja placeholders in the user "
		"prompt, plus the live context document ({{ doc.<field> }} is re-read every "
		"decision).\n"
		"  2. The model is offered the candidate tasks as tools NAMED BY THEIR BPMN "
		"ID (the documentation text is the tool description). Prompts must reference "
		"tasks by those exact ids.\n"
		"  3. Exactly one task may be activated per decision. The very FIRST decision "
		"happens at subprocess entry, before anything has run.\n"
		"  4. Completed tasks are NOT offered as tools; the user prompt is "
		"automatically appended an authoritative progress line naming tasks that "
		"already ran, plus a standing guard: if the prescribed task is not "
		"offered, activate nothing. Selection procedures should still lean on "
		"observable EVIDENCE (document field values, process variables) to "
		"decide the next step — never on the model remembering.\n"
		"  5. Tasks connected by sequence flows to a candidate run AUTOMATICALLY "
		"after it — never instruct the model to activate those; instead use their "
		"effects (e.g. a status value they set) as evidence.\n"
		"  5b. REGISTRY TOOLS listed in the digest are callable functions, not "
		"tasks: the model may call them freely within a decision (they answer "
		"immediately) and still activate one task. Their latest result persists "
		"in a <selector id>_toolCallResult process variable as a JSON string.\n"
		"  6. The subprocess ends when its completion condition becomes true "
		"(usually a variable set by a wrap-up script task).\n\n"
		"A DIAGRAM DIGEST of the subprocess follows in the user message: the "
		"selectable tasks with their ids and behaviors, the automatic chains, the "
		"observable state changes, and the completion condition. Build the "
		"selection procedure (aiSystemPrompt) as explicit if/then rules over that "
		"evidence, referencing only ids from the digest, and build the evidence "
		"template (aiUserPrompt) so every rule's condition is actually visible in "
		"it — use {% if var is defined %} guards for variables that only appear "
		"after some task runs.\n\n"
		"Recommend values for these fields:\n"
		f"{field_lines}\n\n"
		"Respond with ONLY a single JSON object, no prose outside it, in this exact shape:\n"
		'{\n'
		'  "message": "<a short, friendly explanation of what you suggested>",\n'
		'  "recommendations": { "aiSystemPrompt": "...", "aiUserPrompt": "...", ... }\n'
		'}'
	)


def _build_user_prompt(
	requirement: str,
	turns: list,
	context_block: str,
	diagram_block: str = "",
	current_config_block: str = "",
) -> str:
	parts = []
	if diagram_block:
		parts.append(diagram_block)
	if context_block:
		parts.append(context_block)
	if current_config_block:
		parts.append(current_config_block)
	if turns:
		convo = "\n".join(
			f"{str(t.get('role', 'user')).upper()}: {t.get('content', '')}"
			for t in turns
			if isinstance(t, dict)
		)
		if convo:
			parts.append("CONVERSATION SO FAR:\n" + convo)
	parts.append("DESIGNER REQUIREMENT:\n" + requirement.strip())
	parts.append(
		"Return the JSON object with your recommended field values now."
	)
	return "\n\n".join(parts)


def _build_current_config_block(current_config: str, catalog: dict) -> str:
	try:
		cfg = json.loads(current_config or "{}")
	except Exception:
		return ""
	if not isinstance(cfg, dict):
		return ""
	lines = [
		f"  {key}: {value}"
		for key, value in cfg.items()
		if key in catalog and str(value or "").strip()
	]
	if not lines:
		return ""
	return "CURRENT CONFIGURATION (refine these rather than starting over when the designer asks for changes):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Diagram digest (selector mode)
# ---------------------------------------------------------------------------

def _build_diagram_digest(bpmn_xml: str, element_id: str, process_model: str = "") -> dict | None:
	"""Parse the ad-hoc subprocess out of the live diagram XML and produce a
	model-readable digest: selectable candidates, automatic chains, observable
	state changes, evidence variables and the completion condition.

	Returns {"block": str, "candidate_ids": [..], "element_ids": {..}} or None
	when no ad-hoc subprocess is found (the assistant then works blind, as
	before).
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

	# ── flow graph within the subprocess ──
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
			keys = _server_script_result_keys(script_name)
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
		"""Follow sequence flows from a candidate, describing the automatic
		continuation (through gateways) until the chain ends."""
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

	# The AI Agent Tool registry was removed (WI-001423) — a selector's tools
	# are the ad-hoc sub-process's own shapes, already listed above.
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


def _server_script_result_keys(script_name: str) -> list:
	"""Sniff which process variables a BPMN Server Script sets: the engine
	merges the injected ``result`` dict into task data, so result["key"]
	assignments become Jinja-visible variables."""
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
	"""Cross-check recommended prompts against the real diagram: flag task-id
	lookalikes that don't exist, and candidates the procedure never mentions."""
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


# ---------------------------------------------------------------------------
# Context gathering (permission-aware)
# ---------------------------------------------------------------------------

def _build_context_block(doctype: str, docname: str) -> str:
	if not doctype:
		return ""

	# Do not expose schema for DocTypes the current user cannot read —
	# frappe.get_meta() does not enforce permissions.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_history(history: str) -> list:
	try:
		turns = json.loads(history or "[]")
	except Exception:
		return []
	return turns if isinstance(turns, list) else []


def _extract_json(text: str):
	"""Tolerantly extract a JSON object from a model reply.

	Handles plain JSON, fenced ```json blocks, and prose wrapped around an
	object. Returns the parsed object/dict, or None if nothing parses.
	"""
	if not text:
		return None
	text = text.strip()

	# Strip markdown code fences if present.
	if text.startswith("```"):
		text = text.strip("`")
		if text[:4].lower() == "json":
			text = text[4:]
		text = text.strip()

	try:
		return json.loads(text)
	except Exception:
		pass

	start = text.find("{")
	end = text.rfind("}")
	if start != -1 and end != -1 and end > start:
		try:
			return json.loads(text[start:end + 1])
		except Exception:
			return None
	return None
