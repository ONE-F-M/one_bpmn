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

# Layout-only / non-data field types skipped when summarising a DocType schema.
_SKIP_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}

_MAX_SCHEMA_FIELDS = 120
_MAX_SAMPLE_CHARS = 4000


@frappe.whitelist()
def recommend_ai_task_config(
	provider: str,
	backend: str = "direct_api",
	requirement: str = "",
	context_doctype: str = "",
	context_docname: str = "",
	history: str = "[]",
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

	turns = _parse_history(history)
	context_block = _build_context_block(context_doctype, context_docname)

	system_prompt = _build_system_prompt()
	user_prompt = _build_user_prompt(requirement, turns, context_block)

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
		max_tokens=1800,
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
			if key in FIELD_CATALOG and value not in (None, ""):
				recommendations[key] = value

	return {"ok": True, "message": message, "recommendations": recommendations}


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


def _build_user_prompt(requirement: str, turns: list, context_block: str) -> str:
	parts = []
	if context_block:
		parts.append(context_block)
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


# ---------------------------------------------------------------------------
# Context gathering (permission-aware)
# ---------------------------------------------------------------------------

def _build_context_block(doctype: str, docname: str) -> str:
	if not doctype:
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
