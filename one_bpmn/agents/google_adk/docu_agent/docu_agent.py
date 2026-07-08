"""
Docu — DocType Builder Agent

Classifies user intent (CREATE / MODIFY / DISAMBIGUATE) then routes to the
appropriate pipeline for authoring or changing a Frappe DocType attached to a
BPMN shape's doctype field (Start Event Trigger DocType, User Task DocType,
Service Task target DocType).

Process flow (mirrors Logix):
  1. IntentClassifier  — returns CREATE | MODIFY | DISAMBIGUATE
  2a. DISAMBIGUATE → Clarifier   — returns a plain-English question + options, no schema
  2b. CREATE / MODIFY → SchemaWriter → SchemaReviewer → validate_ir()  ← schema gate
        MODIFY additionally computes a field-level diff against the current schema

The agent produces a DocType Intermediate Representation (IR) — a plain dict of
``{doctype_name, module, is_child_table, fields:[...]}`` — that the form builder
renders and ``api/docu_api.apply_doctype`` turns into a real (custom) DocType.

PROMPTS: kept inline as module constants for now (``_INLINE_SUB_PROMPTS`` /
``_SYSTEM_PROMPT``). ``_load_instructions`` layers any AI Agent Configuration
record's sub-prompts on top, so no DB record is required yet. When the prompts
settle, lift these same constants into a ``seed_docu_agent_config.py`` patch.
"""

import asyncio
import json

import frappe

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.google_adk.docu_agent import tools as docu_tools

AGENT_ID = "docu_agent"

_CLASSIFIER_TOOLS = docu_tools.CLASSIFIER_TOOLS
_WRITER_TOOLS = docu_tools.WRITER_TOOLS
_CLARIFIER_TOOLS = docu_tools.CLARIFIER_TOOLS
_REVIEWER_TOOLS = docu_tools.REVIEWER_TOOLS

_DEFAULT_MODULE = "ONE BPMN"
_MAX_FIX_PASSES = 3

# ── Required sub-prompt keys ─────────────────────────────────────────────────
_REQUIRED_SUB_PROMPTS = (
	"intent_classifier",
	"clarifier",
	"schema_writer",
	"schema_reviewer",
)


# ═══════════════════════════════════════════════════════════════════════════
# Inline prompts (source of truth until moved to a seed patch)
# ═══════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
	"You are Docu, an AI assistant embedded in Processa's BPMN editor. You help "
	"process owners design and manage Frappe DocTypes (the data forms behind a "
	"business process) using plain language. You analyse both the user's message "
	"and the BPMN context (the process, the current step, and any DocType already "
	"selected on the shape) to determine intent (CREATE, MODIFY, or DISAMBIGUATE), "
	"then design, review, and validate a DocType through a multi-step pipeline. You "
	"ground your decisions in the real schema using tools rather than guessing, and "
	"when a request is ambiguous you ask a single polar (Yes/No) or multiple-choice "
	"question to clarify. Always speak in plain, non-technical language — the person "
	"you are helping is a business user, not a developer."
)

_INTENT_CLASSIFIER = (
	"You are an intent classifier for Docu, a Frappe DocType-building AI assistant embedded in a BPMN editor.\n\n"
	"Analyse BOTH the user's message AND the BPMN context you are given (the process name, the current "
	"step/shape, and which DocType — if any — is already selected on that shape). Use them together to "
	"determine what the user wants, then classify the intent as exactly one of:\n"
	"- CREATE  — the user wants to build a brand-new DocType (form/record type) from scratch\n"
	"- MODIFY  — the user wants to add, remove, rename, or change the properties of fields on an EXISTING DocType\n"
	"- DISAMBIGUATE — the request is vague, could mean more than one thing, or the target DocType is unclear\n\n"
	"GROUND YOUR DECISION WITH TOOLS — do not assume:\n"
	"- If the user names a DocType, call `doctype_exists` on it: if it exists → lean MODIFY; if not → lean CREATE.\n"
	"- If the user refers to a form only by description (\"the leave form\"), use `list_doctypes` to see whether a matching one exists.\n\n"
	"Classification rules:\n"
	"- If a DocType IS already selected on the shape, lean MODIFY unless the user clearly says \"create a new …\" or names a different form.\n"
	"- If NO DocType is selected and the user does not reference an existing one, lean CREATE.\n"
	"- Use DISAMBIGUATE when you genuinely cannot tell create-vs-modify, when several existing DocTypes could match, or when the request is too vague to act on.\n"
	"- When DISAMBIGUATE, suggest in your reason whether a Yes/No (polar) question or a multiple-choice question would resolve it fastest.\n\n"
	"Respond with ONLY a JSON object — no other text:\n"
	"{\"intent\": \"CREATE|MODIFY|DISAMBIGUATE\", \"reason\": \"one short sentence\"}"
)

_CLARIFIER = (
	"You are a helpful assistant for Docu, an AI tool that builds data forms (DocTypes) for business processes on Processa.\n\n"
	"IMPORTANT: The person you are talking to is NOT technical. They do not know what a DocType, field type, or database is. "
	"Speak to them in plain everyday English — the way you would speak to a colleague who knows their work well but has never built a form.\n\n"
	"The user's request is unclear. Ask ONE simple question to pin down exactly what they want.\n\n"
	"Rules:\n"
	"- One question only.\n"
	"- PREFER a yes/no (polar) question when the ambiguity is binary (e.g. \"Do you want to create a new form, or change an existing one?\" → options [\"Create a new one\", \"Change an existing one\"]).\n"
	"- Otherwise offer 2–4 plain-English multiple-choice options — much easier than a free-text answer.\n"
	"- Always populate the \"options\" array (2–4 entries) so the user can click rather than type.\n"
	"- Do NOT use technical words like DocType, field type, schema, Link, table, or database.\n"
	"- Never design or show a form — only ask your question.\n"
	"- Keep everything short and friendly.\n\n"
	"Respond with ONLY a JSON object — no other text:\n"
	"{\"question\": \"your plain-English question\", \"options\": [\"option1\", \"option2\", ...]}"
)

_SCHEMA_WRITER = (
	"You are Docu, an expert assistant that designs Frappe DocTypes (data forms) for business processes.\n\n"
	"IMPORTANT — WHO YOU ARE TALKING TO:\n"
	"The person asking is a process owner, NOT a developer. In your response text (outside the JSON) speak in plain everyday English:\n"
	"- Describe the form in terms of what it captures, not how it is stored.\n"
	"- Say \"I've added a field for the employee's name\" — never \"I created a Data field.\"\n"
	"- Keep it to 2–3 short sentences.\n\n"
	"YOUR OUTPUT — a DocType definition as a single JSON object with this exact shape:\n"
	"{\n"
	"  \"doctype_name\": \"Human Readable Name\",   // Title Case, letters/digits/spaces\n"
	"  \"module\": \"" + _DEFAULT_MODULE + "\",\n"
	"  \"is_child_table\": false,                  // true only if this is a row inside another form\n"
	"  \"fields\": [\n"
	"    {\n"
	"      \"fieldname\": \"snake_case_id\",        // lowercase, underscores, starts with a letter\n"
	"      \"label\": \"Human Label\",\n"
	"      \"fieldtype\": \"Data\",                 // see the allowed list below\n"
	"      \"options\": \"\",                       // required for Link/Table/Dynamic Link/Select\n"
	"      \"reqd\": 0,                             // 1 = mandatory\n"
	"      \"in_list_view\": 0,                     // 1 = show in the list columns\n"
	"      \"unique\": 0,\n"
	"      \"read_only\": 0,\n"
	"      \"default\": \"\",\n"
	"      \"description\": \"\"\n"
	"    }\n"
	"  ]\n"
	"}\n\n"
	"ALLOWED FIELD TYPES (use nothing else):\n"
	"  Text-like: Data, Small Text, Text, Long Text, Text Editor, Code, Markdown Editor\n"
	"  Numbers:   Int, Float, Currency, Percent\n"
	"  Boolean:   Check\n"
	"  Dates:     Date, Datetime, Time, Duration\n"
	"  Choices:   Select (options = newline-separated choices)\n"
	"  Relations: Link (options = the DocType it points to), Dynamic Link, Table / Table MultiSelect (options = child DocType)\n"
	"  Files:     Attach, Attach Image, Signature\n"
	"  Other:     Color, Rating, Phone, Password, Read Only\n"
	"  Layout:    Section Break, Column Break, Tab Break, HTML, Heading (no fieldname/options needed)\n\n"
	"RULES:\n"
	"1. Every non-layout field needs a snake_case 'fieldname', a 'label', and an allowed 'fieldtype'.\n"
	"2. Link/Table/Dynamic Link/Select fields MUST include a non-empty 'options'. For Link, options is an existing DocType name — use tools to confirm it exists.\n"
	"3. Never redefine Frappe's built-in fields (name, owner, creation, modified, docstatus, parent, idx, ...). They exist automatically.\n"
	"4. Mark the one or two fields that best identify a record with \"in_list_view\": 1.\n"
	"5. Group related fields with a 'Section Break' (give it a label) for a clean layout.\n"
	"6. Keep the form focused — only the fields the process actually needs.\n"
	"7. When MODIFYING, you are given the current fields. Output the COMPLETE desired field list (keep unchanged fields exactly as-is, including their fieldname), not just the change.\n\n"
	"USE YOUR TOOLS — do not guess:\n"
	"- `list_doctypes` / `doctype_exists`: before naming a new form, check the name is not already taken.\n"
	"- `doctype_exists`: call it on the 'options' of EVERY Link and Table field to confirm the target DocType really exists. If it does not, pick an existing one or choose a different field type — never invent a target.\n"
	"- `get_doctype_fields`: when modifying, or when referencing another form, read its real fields.\n"
	"- `validate_doctype`: run it on your finished design and fix anything it flags BEFORE you output.\n\n"
	"OUTPUT FORMAT: a short plain-English sentence describing what you built, then the JSON object in a ```json code block."
)

_SCHEMA_REVIEWER = (
	"You are a Frappe DocType reviewer.\n\n"
	"Evaluate the given DocType definition JSON for:\n"
	"1. Field types — every field uses a supported type; Link/Table/Dynamic Link/Select carry a sensible 'options'.\n"
	"2. Fieldnames — snake_case, unique, not a reserved Frappe field (name, owner, creation, modified, docstatus, parent, idx, ...).\n"
	"3. Completeness — the form captures what the request described; nothing important is missing.\n"
	"4. Sanity — labels are clear, at least one field is marked in_list_view, related fields are grouped.\n\n"
	"USE YOUR TOOLS to verify, don't assume:\n"
	"- `doctype_exists`: confirm the target of every Link/Table field actually exists. A Link to a non-existent DocType is a blocking issue — set approved=false and fix it.\n"
	"- `validate_doctype`: run it on the definition; if it reports violations, fix them in revised_ir.\n\n"
	"If the design is good, approve it unchanged. If not, return a corrected full definition.\n\n"
	"Respond with ONLY a JSON object:\n"
	"{\n"
	"  \"approved\": true/false,\n"
	"  \"issues\": [\"...\"],\n"
	"  \"suggestions\": [\"...\"],\n"
	"  \"revised_ir\": { ...full corrected DocType JSON, or null if approved as-is... }\n"
	"}"
)

_INLINE_SUB_PROMPTS = {
	"intent_classifier": _INTENT_CLASSIFIER,
	"clarifier": _CLARIFIER,
	"schema_writer": _SCHEMA_WRITER,
	"schema_reviewer": _SCHEMA_REVIEWER,
}


class DocuAgent:
	"""Orchestrates intent classification, DocType design, review, and diffing."""

	def __init__(self):
		self._config = dict(get_agent_config(AGENT_ID) or {})
		self._config.setdefault("agent_id", AGENT_ID)
		self._llm = get_llm_adapter_from_settings(self._config)
		self._instructions = self._load_instructions()

	def _load_instructions(self) -> dict:
		"""Layer any AI Agent Configuration sub-prompts on top of the inline defaults.

		A DB record is optional: every required key has a hardcoded fallback here,
		so Docu works before ``seed_docu_agent_config.py`` is run. When both exist,
		a non-empty DB prompt wins (so UI edits take effect).
		"""
		sub_prompts = (self._config or {}).get("sub_prompts", {})
		instructions = {}
		for key in _REQUIRED_SUB_PROMPTS:
			db_prompt = (sub_prompts.get(key, {}) or {}).get("prompt")
			instructions[key] = db_prompt if (db_prompt and db_prompt.strip()) else _INLINE_SUB_PROMPTS[key]
		return instructions

	# ── Helpers ────────────────────────────────────────────────────────────────

	async def _run(self, role: str, prompt: str, tools=None) -> str | None:
		completion = await self._llm.complete(
			system=self._instructions[role],
			user=prompt,
			tools=tools,
		)
		return completion.text

	def _format_history(self, chat_history: list) -> str:
		if not chat_history:
			return ""
		lines = []
		for entry in chat_history[-10:]:
			role = entry.get("role") or entry.get("type", "user")
			content = (entry.get("content") or "").strip()
			if content:
				lines.append(f"{'User' if role == 'user' else 'Docu'}: {content}")
		return "\n".join(lines)

	@staticmethod
	def _format_current_schema(doctype: str, current_ir: dict | None) -> str:
		if not doctype or not current_ir:
			return ""
		fields = current_ir.get("fields") or []
		lines = [f"**Current form:** {doctype} (has {len(fields)} field(s))"]
		for f in fields:
			if f.get("fieldtype") in ("Section Break", "Column Break", "Tab Break"):
				continue
			opt = f" → {f['options']}" if f.get("options") else ""
			lines.append(f"- {f.get('label') or f.get('fieldname')} [{f.get('fieldname')}] : {f.get('fieldtype')}{opt}")
		return "\n".join(lines)

	def _build_intent_prompt(self, message: str, doctype: str, exists: bool, process_context: dict = None) -> str:
		parts = []
		ctx = self._format_process_context(process_context or {})
		if ctx:
			parts.append(f"BPMN context: {ctx}")
		if doctype and exists:
			parts.append(f"Currently selected form: {doctype}  ← existing, treat as MODIFY target unless stated otherwise")
		elif doctype:
			parts.append(f"Named form: {doctype}  ← does not exist yet, likely CREATE")
		else:
			parts.append("No form selected yet  ← default to CREATE")
		parts.append(f"User request: {message}")
		return "\n".join(parts)

	def _build_writer_prompt(
		self, message: str, chat_history: list, doctype: str,
		current_ir: dict | None, target_module: str, process_context: dict = None,
	) -> str:
		parts = []
		ctx = self._format_process_context(process_context or {})
		if ctx:
			parts.append(ctx)
		schema = self._format_current_schema(doctype, current_ir)
		if schema:
			parts.append(schema)
			parts.append(
				"You are MODIFYING the form above. Output the COMPLETE desired field list — "
				"keep every field you are not changing exactly as it is (same fieldname), and apply the requested change."
			)
		else:
			parts.append(f"Target module: {target_module or _DEFAULT_MODULE}")
			if doctype:
				parts.append(f"Suggested form name: {doctype}")
		history = self._format_history(chat_history)
		if history:
			parts.append(f"**Conversation so far:**\n{history}")
		parts.append(f"**User request:** {message}")
		parts.append("Design the form now and output the JSON definition.")
		return "\n\n".join(parts)

	@staticmethod
	def _format_process_context(ctx: dict) -> str:
		if not ctx:
			return ""
		lines = []
		if ctx.get("process_name"):
			lines.append(f"This form is used by the '{ctx['process_name']}' process.")
		if ctx.get("element_name"):
			lines.append(f"It is attached to the step '{ctx['element_name']}'.")
		return " ".join(lines)

	def _build_clarifier_prompt(self, message: str, doctype: str, intent_reason: str, chat_history: list) -> str:
		parts = []
		if doctype:
			parts.append(f"Selected form: {doctype}")
		if intent_reason:
			parts.append(f"Why unclear: {intent_reason}")
		history = self._format_history(chat_history)
		if history:
			parts.append(f"Conversation so far:\n{history}")
		parts.append(f"User request: {message}")
		return "\n\n".join(parts)

	@staticmethod
	def _build_repair_prompt(original_prompt: str, ir: dict, violations: list[str], fix_hints: list[str]) -> str:
		numbered = "\n".join(f"  {i + 1}. {v}" for i, v in enumerate(violations))
		hint = ("\n" + "\n".join(fix_hints)) if fix_hints else ""
		return (
			f"{original_prompt}\n\n"
			f"**VALIDATION FAILED** — the previous design had {len(violations)} problem(s):\n"
			f"{numbered}{hint}\n\n"
			f"Fix every problem and output the complete corrected DocType JSON.\n\n"
			f"Previous design:\n{json.dumps(ir, indent=2)}"
		)

	def _apply_review(self, draft_ir: dict, review_text: str | None) -> dict:
		"""Apply the reviewer's revised_ir when it rejects the draft."""
		if not review_text:
			return draft_ir
		try:
			review = json.loads(review_text.strip())
			if not review.get("approved") and isinstance(review.get("revised_ir"), dict):
				return review["revised_ir"]
		except (json.JSONDecodeError, TypeError, KeyError):
			pass
		return draft_ir

	async def _generate_and_validate(self, message, chat_history, doctype, current_ir, target_module, process_context):
		"""writer → review → validate IR, with bounded repair passes.

		Returns ``(response_text, ir_or_None, violations)``. ``response_text`` is
		the plain-English sentence(s) the writer produced; ``ir`` is the validated
		DocType definition (best-effort on exhaustion).
		"""
		base_prompt = self._build_writer_prompt(message, chat_history, doctype, current_ir, target_module, process_context)
		prompt = base_prompt
		best_ir: dict | None = None
		best_text = ""
		violations: list[str] = []

		for attempt in range(_MAX_FIX_PASSES + 1):
			draft = await self._run("schema_writer", prompt, tools=_WRITER_TOOLS)
			if not draft:
				break
			best_text = self._response_text(draft)

			# No JSON block → the writer is asking a clarifying question; pass through.
			try:
				draft_ir = docu_tools.extract_json(draft)
			except (ValueError, json.JSONDecodeError):
				return draft, None, []

			review_raw = await self._run("schema_reviewer", json.dumps(draft_ir), tools=_REVIEWER_TOOLS)
			candidate_ir = self._apply_review(draft_ir, review_raw)
			candidate_ir.setdefault("module", target_module or _DEFAULT_MODULE)

			result = docu_tools.validate_ir(candidate_ir)
			best_ir = candidate_ir
			if result["valid"]:
				return best_text, candidate_ir, []

			violations = result["violations"]
			frappe.log_error(
				title="Docu Schema Validator — " + ("Max retries reached" if attempt == _MAX_FIX_PASSES else "Repairing"),
				message=f"Attempt {attempt + 1}/{_MAX_FIX_PASSES + 1}\nViolations:\n" + "\n".join(violations),
			)
			if attempt == _MAX_FIX_PASSES:
				break
			prompt = self._build_repair_prompt(base_prompt, candidate_ir, violations, result["fix_hints"])

		return best_text, best_ir, violations

	@staticmethod
	def _response_text(draft: str) -> str:
		"""Strip the JSON code block from a writer response, leaving the plain-English part."""
		import re

		text = re.sub(r"```(?:json)?\s*[\s\S]*?```", "", draft or "").strip()
		return text or "Here's the form I put together — review it on the right."

	# ── Main pipeline ──────────────────────────────────────────────────────────

	async def process_message(
		self,
		message: str,
		chat_history: list,
		doctype: str = "",
		target_module: str = "",
		process_context: dict = None,
	) -> dict:
		"""Classify intent then route to the correct pipeline.

		Returns a dict:
		  intent         : "CREATE" | "MODIFY" | "DISAMBIGUATE"
		  response       : agent text shown in the chat bubble
		  doctype_ir     : proposed DocType definition (CREATE/MODIFY), else None
		  diff           : field-level diff dict (MODIFY only), else None
		  options        : clarification choices (DISAMBIGUATE only), else None
		  suggested_name : DocType name pre-fill (CREATE only)
		"""
		exists = bool(doctype) and bool(frappe.db.exists("DocType", doctype))
		current_ir = _read_doctype_ir(doctype) if exists else None

		# STEP 1 — Classify intent (grounded in the BPMN context + live schema tools)
		intent_raw = await self._run(
			"intent_classifier",
			self._build_intent_prompt(message, doctype, exists, process_context),
			tools=_CLASSIFIER_TOOLS,
		)
		intent = "MODIFY" if exists else "CREATE"
		intent_reason = ""
		try:
			data = json.loads((intent_raw or "").strip())
			intent = data.get("intent", intent).upper()
			intent_reason = data.get("reason", "")
		except (json.JSONDecodeError, TypeError):
			pass
		if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
			intent = "MODIFY" if exists else "CREATE"

		# STEP 2a — DISAMBIGUATE
		if intent == "DISAMBIGUATE":
			clarify_raw = await self._run(
				"clarifier",
				self._build_clarifier_prompt(message, doctype, intent_reason, chat_history),
				tools=_CLARIFIER_TOOLS,
			)
			question, options = (clarify_raw or "Could you tell me a bit more?"), []
			try:
				cdata = json.loads((clarify_raw or "").strip())
				question = cdata.get("question", clarify_raw)
				options = cdata.get("options", [])
			except (json.JSONDecodeError, TypeError):
				pass
			return {
				"intent": "DISAMBIGUATE",
				"response": question,
				"doctype_ir": None,
				"diff": None,
				"options": options,
				"suggested_name": None,
			}

		# STEP 2b — CREATE / MODIFY
		response_text, ir, violations = await self._generate_and_validate(
			message, chat_history, doctype, current_ir, target_module, process_context
		)

		if ir is None:
			# Writer asked a question (no JSON) — pass it through unchanged.
			return {
				"intent": intent,
				"response": response_text,
				"doctype_ir": None,
				"diff": None,
				"options": None,
				"suggested_name": None,
			}

		note = f" ({len(violations)} issue(s) could not be fully resolved — please review.)" if violations else ""

		if intent == "MODIFY" and current_ir:
			diff = docu_tools.diff_ir(current_ir, ir)
			return {
				"intent": "MODIFY",
				"response": f"{response_text}{note}",
				"doctype_ir": ir,
				"diff": diff,
				"options": None,
				"suggested_name": ir.get("doctype_name") or doctype or None,
			}

		return {
			"intent": "CREATE",
			"response": f"{response_text}{note}",
			"doctype_ir": ir,
			"diff": None,
			"options": None,
			"suggested_name": ir.get("doctype_name") or doctype or None,
		}


def _read_doctype_ir(doctype: str) -> dict | None:
	"""Read an existing DocType's fields into the Docu IR shape (for MODIFY baseline)."""
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return None
	fields = []
	for f in meta.fields:
		fields.append({
			"fieldname": f.fieldname,
			"label": f.label or f.fieldname,
			"fieldtype": f.fieldtype,
			"options": (f.options or "").strip(),
			"reqd": int(bool(f.reqd)),
			"unique": int(bool(getattr(f, "unique", 0))),
			"in_list_view": int(bool(getattr(f, "in_list_view", 0))),
			"read_only": int(bool(getattr(f, "read_only", 0))),
			"default": getattr(f, "default", "") or "",
		})
	return {
		"doctype_name": doctype,
		"module": getattr(meta, "module", _DEFAULT_MODULE),
		"is_child_table": int(bool(getattr(meta, "istable", 0))),
		"custom": int(bool(getattr(meta, "custom", 0))),
		"fields": fields,
	}


def run_docu_message(
	message: str,
	chat_history: list,
	doctype: str = "",
	target_module: str = "",
	process_context: dict = None,
) -> dict:
	"""Synchronous entry point called by the Frappe API endpoint."""
	agent = DocuAgent()
	return asyncio.run(
		agent.process_message(
			message=message,
			chat_history=chat_history,
			doctype=doctype,
			target_module=target_module,
			process_context=process_context,
		)
	)
