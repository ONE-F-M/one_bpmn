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

PROMPTS live entirely in the "Docu Agent" AI Agent Configuration (seeded by
``seed_docu_agent_config.py``, editable in the UI) — never in this module.
``_load_instructions`` reads them via ``get_agent_config`` and fails loudly if a
required sub-prompt is absent.
"""

import asyncio
import json

import frappe

from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
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


class DocuAgent:
	"""Orchestrates intent classification, DocType design, review, and diffing."""

	def __init__(self):
		self._config = dict(get_agent_config(AGENT_ID) or {})
		self._config.setdefault("agent_id", AGENT_ID)
		self._llm = get_llm_adapter_from_settings(self._config)
		self._instructions = self._load_instructions()

	def _load_instructions(self) -> dict:
		"""Load the sub-agent prompts from the AI Agent Configuration.

		Prompts are NOT stored in code — they live in the "Docu Agent" AI Agent
		Configuration, seeded by ``seed_docu_agent_config.py`` and editable in the
		UI. Every required sub-prompt must be present; a missing/empty one is a
		configuration error, so we fail loudly rather than silently degrade.
		"""
		sub_prompts = (self._config or {}).get("sub_prompts", {})
		instructions = {}
		missing = []
		for key in _REQUIRED_SUB_PROMPTS:
			db_prompt = (sub_prompts.get(key, {}) or {}).get("prompt")
			if db_prompt and db_prompt.strip():
				instructions[key] = db_prompt
			else:
				missing.append(key)
		if missing:
			raise RuntimeError(
				"Docu Agent is not configured: missing sub-prompt(s) "
				f"{missing} in the '{AGENT_ID}' AI Agent Configuration. "
				"Run the seed_docu_agent_config patch (bench migrate) or set them in the UI."
			)
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
		import json as _json

		parts = []
		is_modify = bool(doctype and isinstance(current_ir, dict) and current_ir.get("fields"))
		ctx = self._format_process_context(process_context or {}, for_modify=is_modify)
		if ctx:
			parts.append(("For background only — do NOT redesign around this: " if is_modify else "") + ctx)
		if is_modify:
			# Hand the writer the FULL current definition (every field + property +
			# Section/Column/Tab break) as JSON to edit — a lossy field listing makes
			# it drop the structure and redraw from scratch.
			parts.append(f'The DocType "{doctype}" ALREADY EXISTS. Its CURRENT complete definition is below — you are EDITING it, NOT creating a new one.')
			parts.append("```json\n" + _json.dumps(current_ir, indent=2, default=str) + "\n```")
			parts.append(
				"Return the COMPLETE JSON again with ONLY the user's requested change applied. Keep EVERY other "
				"field exactly as above — same fieldname, same properties, and every Section/Column/Tab break in "
				"the same order. Do NOT say it doesn't exist, and do NOT redesign it from the process context."
			)
		else:
			parts.append(
				f"Module to use (a Frappe app module — NOT the business-process name): "
				f"{target_module or _DEFAULT_MODULE}"
			)
			if doctype:
				parts.append(f"Suggested form name: {doctype}")
		history = self._format_history(chat_history)
		if history:
			parts.append(f"**Conversation so far:**\n{history}")
		parts.append(f"**User request:** {message}")
		parts.append("Design the form now and output the JSON definition.")
		return "\n\n".join(parts)

	@staticmethod
	def _format_process_context(ctx: dict, for_modify: bool = False) -> str:
		"""Render the BPMN model context so the agent designs a DocType that fits
		exactly where it sits in the process — the step, its role, and its position
		in the flow (what comes before/after).

		When ``for_modify`` is True the closing "design it to fit this step" directive
		is dropped: on an edit the context is background only, and telling the model to
		(re)design for the step makes it redraw from scratch instead of editing.
		"""
		if not isinstance(ctx, dict) or not ctx:
			return ""
		lines = []
		proc = (ctx.get("process_name") or "").strip()
		step = (ctx.get("element_name") or "").strip()
		etype = (ctx.get("element_type") or "step").strip() or "step"
		role = (ctx.get("field_role") or "").strip()
		desc = (ctx.get("element_description") or "").strip()

		if proc:
			lines.append(f"This DocType belongs to the \"{proc}\" business process.")
		if step:
			s = f"It is attached to the {etype} \"{step}\""
			if role:
				s += f", where it represents {role}"
			lines.append(s + ".")
		elif role:
			lines.append(f"At this step the DocType represents {role}.")
		if desc:
			lines.append(f"That step is described as: {desc}")

		def _names(v):
			return [str(x).strip() for x in (v or []) if str(x).strip()]
		up, down = _names(ctx.get("upstream")), _names(ctx.get("downstream"))
		if up:
			lines.append("Earlier steps in the process: " + ", ".join(up) + ".")
		if down:
			lines.append("Later steps in the process: " + ", ".join(down) + ".")

		if lines and not for_modify:
			lines.append(
				"Design the DocType so it fits this step's purpose — capture exactly what "
				"this step needs (no more), and use field names/labels that match the process."
			)
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
		return text or "Here's the DocType I put together — review it on the right."

def _read_doctype_ir(doctype: str) -> dict | None:
	"""Read an existing DocType into the full Docu IR (MODIFY baseline).

	Delegates to ``tools.read_doctype_definition`` — the single source of truth —
	so the MODIFY baseline carries every field property (depends_on, fetch_from,
	precision, ...) and naming, not just a handful of flags.
	"""
	return docu_tools.read_doctype_definition(doctype)


