"""
Logix Script Task Agent

Classifies user intent (CREATE / MODIFY / DISAMBIGUATE) then routes to the
appropriate pipeline for writing, modifying, or clarifying Frappe Server Scripts
attached to BPMN Script Tasks.

Process flow:
1. IntentClassifier  — returns CREATE | MODIFY | DISAMBIGUATE
2a. DISAMBIGUATE → Clarifier  — returns a polar/MCQ question, no code written
2b. CREATE / MODIFY → ScriptWriter → ScriptReviewer
    MODIFY additionally computes a unified diff against the original script
"""

import asyncio
import difflib
import json
import os
import re

import frappe
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.security.script_validator import validate_script
from one_bpmn.tools.tool_for_server_scripts import (
	get_doctype_fields,
	get_server_script_content,
	get_server_script_meta,
	list_api_server_scripts,
)

APP_NAME = "logix_script_agent"
USER_ID  = "logix_agent"
AGENT_ID = "logix_script_agent"

# ── Default instructions ───────────────────────────────────────────────────

_DEFAULT_INTENT_CLASSIFIER_INSTRUCTION = """You are an intent classifier for Logix, a BPMN Script Task AI assistant.

Given a user request and task context, classify the intent as exactly one of:
- CREATE  — user wants to write a new server script from scratch
- MODIFY  — user wants to change, update, fix, or extend an existing linked script
- DISAMBIGUATE — the request is vague, targets are unclear, or multiple matching scripts exist

Classification rules:
- If a script IS currently linked to the task, lean toward MODIFY unless the user clearly says "create new" or "replace".
- If NO script is linked, lean toward CREATE unless the user references an existing script by name.
- If the request is ambiguous AND multiple scripts could match (e.g. "update the taxes"), use DISAMBIGUATE.
- If the request is ambiguous but there is only one plausible target, classify as MODIFY.

Respond with ONLY a JSON object — no other text:
{"intent": "CREATE|MODIFY|DISAMBIGUATE", "reason": "one short sentence"}"""

_DEFAULT_CLARIFIER_INSTRUCTION = """You are a disambiguation assistant for Logix, a BPMN Script Task AI.

The user's request is ambiguous. Your job is to ask one precise clarifying question.
Use the available tools to list existing scripts and identify candidates before forming the question.

Rules:
- Prefer a polar (Yes/No) question when there are exactly two options.
- Use multiple-choice (2–4 options) when several specific scripts are plausible targets.
- NEVER write any Python code.
- Keep the question short and direct.

Respond with ONLY a JSON object — no other text:
{"question": "your clarifying question", "options": ["option1", "option2", ...]}"""

_DEFAULT_WRITER_INSTRUCTION = """You are Logix, an expert AI assistant that writes Frappe API-type Server Scripts for BPMN Script Tasks in Processa.

**Script type: always API**
Every script is saved as a Frappe API-type Server Script. The Processa Spiff engine calls it
via HTTP POST to `/api/method/<method_name>`. There is no `doc`, `result`, or `context_*`
variable in scope — the ONLY reliable input is `frappe.form_dict`.

**Reading inputs — `frappe.form_dict`**
Processa sends all workflow variables as POST body parameters. Always read them explicitly:
```python
context_doctype = frappe.form_dict.get("context_doctype")
context_docname = frappe.form_dict.get("context_docname")
# Any other workflow variable the Spiff process sends:
some_var = frappe.form_dict.get("some_var")
```

**Returning outputs — `frappe.response["message"]`**
Always end the script by setting a plain dict so Spiff can map keys back to workflow variables:
```python
frappe.response["message"] = {
    "approved": True,
    "next_step": "manager_review",
    # ... any keys Processa needs to read back
}
```

**Script writing rules:**
1. First lines: read every required variable from `frappe.form_dict`.
2. Last statement: set `frappe.response["message"]` to a dict — never use a bare `return`.
3. Use Frappe ORM: `frappe.db.get_value`, `frappe.get_doc`, `frappe.get_all`, etc.
4. Use `frappe.throw()` for validation failures so Processa receives a clear error response.
5. No raw SQL unless explicitly requested.
6. No external libraries beyond a standard Frappe installation.

**Output format:**
- Wrap the entire script in a single ```python ... ``` code block.
- One-line comment at the top describing what the script does.
- Inline comments only where the logic is non-obvious.

Use tools to inspect existing scripts or confirm field names before writing code."""

_DEFAULT_REVIEWER_INSTRUCTION = """You are a Frappe server script reviewer.

Evaluate the given Python server script for:
1. Correct Frappe ORM usage (no raw SQL unless justified)
2. Security — no arbitrary exec, no hardcoded secrets, no unguarded frappe.db.sql
3. Correctness — logical flow matches the described intent
4. Idiomatic style — follows Frappe conventions

Respond with ONLY a JSON object:
{
    "approved": true/false,
    "issues": ["..."],
    "suggestions": ["..."],
    "revised_script": "full revised script string, or null if approved as-is"
}"""


class ScriptTaskAgent:
	"""Orchestrates intent classification, script writing, review, and diffing."""

	def __init__(self):
		self.gemini_model = None
		self.setup_credentials()
		self._config = get_agent_config(AGENT_ID)
		self.setup_agents()

	def setup_credentials(self):
		os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)
		try:
			settings_doc = frappe.get_doc("AI Chat Settings")
			vertex_api_key = settings_doc.get_password("google_vertex_ai_api_key")
			if vertex_api_key and vertex_api_key.strip():
				os.environ["GOOGLE_API_KEY"] = vertex_api_key.strip()
			else:
				frappe.log_error(
					title="Logix Agent - Missing API Key",
					message="google_vertex_ai_api_key not found in AI Chat Settings",
				)
			self.gemini_model = settings_doc.gemini_model or "gemini-2.0-flash"
		except Exception:
			frappe.log_error(title="Logix Agent - Credential Setup", message=frappe.get_traceback())
			self.gemini_model = "gemini-2.0-flash"

	def setup_agents(self):
		sub_prompts = (self._config or {}).get("sub_prompts", {})

		def _instruction(key, default):
			return sub_prompts.get(key, {}).get("prompt", default)

		self.intent_classifier = LlmAgent(
			name="IntentClassifier",
			model=self.gemini_model,
			instruction=_instruction("intent_classifier", _DEFAULT_INTENT_CLASSIFIER_INSTRUCTION),
			output_key="intent",
		)
		self.clarifier = LlmAgent(
			name="Clarifier",
			model=self.gemini_model,
			instruction=_instruction("clarifier", _DEFAULT_CLARIFIER_INSTRUCTION),
			tools=[list_api_server_scripts, get_server_script_meta],
			output_key="clarification",
		)
		self.script_writer = LlmAgent(
			name="ScriptWriter",
			model=self.gemini_model,
			instruction=_instruction("script_writer", _DEFAULT_WRITER_INSTRUCTION),
			tools=[get_server_script_content, get_server_script_meta, list_api_server_scripts, get_doctype_fields],
			output_key="draft_script",
		)
		self.script_reviewer = LlmAgent(
			name="ScriptReviewer",
			model=self.gemini_model,
			instruction=_instruction("script_reviewer", _DEFAULT_REVIEWER_INSTRUCTION),
			output_key="review",
		)

	# ── Helpers ────────────────────────────────────────────────────────────

	async def _run_agent(self, agent: LlmAgent, prompt: str, session_service, session_id: str) -> str | None:
		"""Run a single LlmAgent and return its final text response."""
		runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
		content = types.Content(role="user", parts=[types.Part(text=prompt)])
		async for event in runner.run_async(user_id=USER_ID, session_id=session_id, new_message=content):
			if event.is_final_response() and event.content:
				return event.content.parts[0].text
		return None

	def _format_history(self, chat_history: list) -> str:
		if not chat_history:
			return ""
		lines = []
		for entry in chat_history[-10:]:
			role    = entry.get("role") or entry.get("type", "user")
			content = (entry.get("content") or "").strip()
			if content:
				lines.append(f"{'User' if role == 'user' else 'Logix'}: {content}")
		return "\n".join(lines)

	def _build_intent_prompt(self, message: str, current_script: str, element_name: str) -> str:
		parts = []
		if element_name:
			parts.append(f"Script Task: {element_name}")
		if current_script:
			parts.append(f"Linked script: {current_script}  ← existing, treat as MODIFY target unless stated otherwise")
		else:
			parts.append("No script linked yet  ← default to CREATE")
		parts.append(f"User request: {message}")
		return "\n".join(parts)

	def _build_writer_prompt(self, message: str, chat_history: list, element_name: str, current_script: str) -> str:
		parts = []
		if element_name:
			parts.append(f"**Script Task:** {element_name}")
		if current_script:
			parts.append(f"**Currently linked Server Script:** {current_script}")
		history = self._format_history(chat_history)
		if history:
			parts.append(f"**Conversation so far:**\n{history}")
		parts.append(f"**User request:** {message}")
		return "\n\n".join(parts)

	@staticmethod
	def _extract_code(response: str) -> str:
		"""Pull the Python code out of a ```python ... ``` block."""
		match = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
		return match.group(1).strip() if match else response.strip()

	@staticmethod
	def _compute_diff(original: str, modified: str) -> str:
		"""Return a unified diff string between the original and modified scripts."""
		diff = difflib.unified_diff(
			original.splitlines(keepends=True),
			modified.splitlines(keepends=True),
			fromfile="original",
			tofile="modified",
			lineterm="",
		)
		return "".join(diff)

	@staticmethod
	def _build_regeneration_prompt(original_prompt: str, violations: list[str]) -> str:
		"""Append a security notice to the writer prompt so the agent avoids flagged patterns."""
		bullet_list = "\n".join(f"  - {v}" for v in violations)
		return (
			f"{original_prompt}\n\n"
			f"**SECURITY REGENERATION REQUEST**\n"
			f"The previous attempt was blocked by the security validator for these violations:\n"
			f"{bullet_list}\n\n"
			f"Rewrite the script WITHOUT any of these patterns. "
			f"Use only `frappe.get_doc`, `frappe.db.get_value`, `frappe.get_all`, "
			f"and other safe Frappe ORM methods. "
			f"Do NOT import os, sys, subprocess, or any module outside the standard Frappe sandbox."
		)

	def _apply_review(self, draft: str, review_text: str | None) -> str:
		if not review_text:
			return draft
		try:
			review = json.loads(review_text.strip())
			if not review.get("approved") and review.get("revised_script"):
				return review["revised_script"]
			if review.get("suggestions"):
				note = "\n\n> **Review notes:** " + "; ".join(review["suggestions"])
				return draft + note
		except (json.JSONDecodeError, TypeError, KeyError):
			pass
		return draft

	# ── Main pipeline ──────────────────────────────────────────────────────

	async def process_message(
		self,
		message: str,
		chat_history: list,
		element_name: str,
		current_script: str,
		original_script_content: str = "",
	) -> dict:
		"""
		Classify intent then route to the correct pipeline.

		Returns a dict:
		  intent   : "CREATE" | "MODIFY" | "DISAMBIGUATE"
		  response : agent text (script with markdown, or clarifying question)
		  diff     : unified diff string (MODIFY only, else None)
		  options  : list of clarification choices (DISAMBIGUATE only, else None)
		  suggested_name : Script Task label pre-filled for Apply dialog (CREATE only)
		"""
		session_service = InMemorySessionService()
		session_id = f"logix_{frappe.utils.now_datetime().strftime('%Y%m%d%H%M%S%f')}"
		await session_service.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id, state={})

		try:
			# STEP 1 — Classify intent
			intent_prompt = self._build_intent_prompt(message, current_script, element_name)
			intent_raw    = await self._run_agent(self.intent_classifier, intent_prompt, session_service, session_id)

			intent = "CREATE" if not current_script else "MODIFY"
			try:
				intent_data = json.loads((intent_raw or "").strip())
				intent = intent_data.get("intent", intent).upper()
			except (json.JSONDecodeError, TypeError):
				pass
			if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
				intent = "CREATE" if not current_script else "MODIFY"

			# STEP 2a — DISAMBIGUATE: ask a clarifying question, write no code
			if intent == "DISAMBIGUATE":
				clarify_raw = await self._run_agent(
					self.clarifier,
					self._build_intent_prompt(message, current_script, element_name),
					session_service,
					session_id,
				)
				try:
					clarify_data = json.loads((clarify_raw or "").strip())
					return {
						"intent":   "DISAMBIGUATE",
						"response": clarify_data.get("question", clarify_raw),
						"options":  clarify_data.get("options", []),
						"diff":     None,
						"suggested_name": None,
					}
				except (json.JSONDecodeError, TypeError):
					return {"intent": "DISAMBIGUATE", "response": clarify_raw or "Could you clarify your request?", "options": [], "diff": None, "suggested_name": None}

			# STEP 2b — CREATE / MODIFY: write → review → validate (up to 3 attempts)
			_MAX_RETRIES   = 2
			writer_prompt  = self._build_writer_prompt(message, chat_history, element_name, current_script)
			final          = None
			modified_code  = ""

			for attempt in range(_MAX_RETRIES + 1):
				draft = await self._run_agent(self.script_writer, writer_prompt, session_service, session_id)
				if not draft:
					break

				review_raw    = await self._run_agent(self.script_reviewer, draft, session_service, session_id)
				candidate     = self._apply_review(draft, review_raw)
				modified_code = self._extract_code(candidate)

				validation = validate_script(modified_code)
				if validation["valid"]:
					final = candidate
					break

				# Security violation — log and decide whether to retry
				frappe.log_error(
					title="Logix Security Validator",
					message=(
						f"Attempt {attempt + 1}/{_MAX_RETRIES + 1} blocked.\n"
						f"Violations: {validation['violations']}\n\n"
						f"Flagged code:\n{modified_code}"
					),
				)

				if attempt == _MAX_RETRIES:
					return {
						"intent":          intent,
						"response":        (
							"I was unable to generate a safe script after multiple attempts. "
							"Please rephrase your request to avoid forbidden operations "
							"(e.g. file access, shell commands, or raw destructive SQL)."
						),
						"diff":            None,
						"original_script": None,
						"modified_script": None,
						"options":         None,
						"suggested_name":  None,
					}

				# Inject violations into the prompt and retry
				writer_prompt = self._build_regeneration_prompt(writer_prompt, validation["violations"])

			if not final:
				return {"intent": intent, "response": "I wasn't able to generate a script. Please try again.", "diff": None, "options": None, "suggested_name": None, "original_script": None, "modified_script": None}

			# STEP 3 — Diff for MODIFY

			if intent == "MODIFY" and original_script_content:
				diff = self._compute_diff(original_script_content, modified_code)
				return {
					"intent":          "MODIFY",
					"response":        final,
					"diff":            diff or None,
					"original_script": original_script_content,
					"modified_script": modified_code,
					"options":         None,
					"suggested_name":  None,
				}

			# CREATE — suggest the Script Task label as the script name
			return {
				"intent":          "CREATE",
				"response":        final,
				"diff":            None,
				"original_script": None,
				"modified_script": modified_code,
				"options":         None,
				"suggested_name":  element_name or None,
			}

		finally:
			await session_service.delete_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)


def run_logix_message(
	message: str,
	chat_history: list,
	element_name: str,
	current_script: str,
	original_script_content: str = "",
) -> dict:
	"""Synchronous entry point called by the Frappe API endpoint."""
	agent = ScriptTaskAgent()
	return asyncio.run(
		agent.process_message(
			message=message,
			chat_history=chat_history,
			element_name=element_name,
			current_script=current_script,
			original_script_content=original_script_content,
		)
	)
