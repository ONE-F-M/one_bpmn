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
import re

import frappe

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.security.script_validator import validate_script
from one_bpmn.agents.llm_provider import ToolSpec, get_llm_adapter_from_settings
from one_bpmn.tools.tool_for_server_scripts import (
    get_doctype_fields,
    get_server_script_content,
    get_server_script_meta,
    list_api_server_scripts,
)

AGENT_ID = "logix_agent"

# ── Tool specs ─────────────────────────────────────────────────────────────────

_TOOL_LIST_SCRIPTS = ToolSpec(
    fn=list_api_server_scripts,
    name="list_api_server_scripts",
    description="List all enabled API-type Server Scripts available in the system.",
    parameters={},
    required=[],
)
_TOOL_GET_CONTENT = ToolSpec(
    fn=get_server_script_content,
    name="get_server_script_content",
    description="Fetch the full Python source code of a Frappe Server Script by name.",
    parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
    required=["script_name"],
)
_TOOL_GET_META = ToolSpec(
    fn=get_server_script_meta,
    name="get_server_script_meta",
    description="Fetch the metadata (type, doctype, method, disabled status) of a Server Script.",
    parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
    required=["script_name"],
)
_TOOL_GET_FIELDS = ToolSpec(
    fn=get_doctype_fields,
    name="get_doctype_fields",
    description="Get the field names and types for a Frappe DocType.",
    parameters={"doctype": {"type": "string", "description": "The DocType name, e.g. 'Employee', 'Sales Order'."}},
    required=["doctype"],
)

_WRITER_TOOLS   = [_TOOL_GET_CONTENT, _TOOL_GET_META, _TOOL_LIST_SCRIPTS, _TOOL_GET_FIELDS]
_CLARIFIER_TOOLS = [_TOOL_LIST_SCRIPTS, _TOOL_GET_META]

# ── Default instructions ───────────────────────────────────────────────────────

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

_DEFAULT_CLARIFIER_INSTRUCTION = """You are a helpful assistant for Logix, an AI tool that writes automation scripts for business processes on Processa.

IMPORTANT: The person you are talking to is NOT a technical person. They do not know what code, scripts, APIs, or functions are. Speak to them in plain everyday English — the way you would speak to a colleague who knows their work well but has never written a line of code.

The user's request is unclear — it could mean more than one thing. Your job is to ask ONE simple question to find out exactly what they want.

Rules:
- One question only.
- Give 2–4 plain-English options to choose from whenever possible — it is much easier for them than typing a free answer.
- Do NOT use technical words like API, script, function, endpoint, method, variable, code, or module.
- Never write or show any code.
- Keep everything short and friendly.

Respond with ONLY a JSON object — no other text:
{"question": "your plain-English question", "options": ["option1", "option2", ...]}"""

_DEFAULT_WRITER_INSTRUCTION = """You are Logix, an expert AI assistant that writes Frappe API-type Server Scripts for BPMN Script Tasks in Processa.

IMPORTANT — WHO YOU ARE TALKING TO:
The person asking you is a process owner or business user. They are NOT a developer. They do not read code, do not know what an API is, and do not understand technical terms. When you write your response text (outside the code block), speak to them in plain everyday English:
- Explain what the script does in terms of the business outcome, not how the code works.
- Never say "I used frappe.get_all()" or "the API returns a JSON response" — instead say "the script looks up the employees" or "the system will return the list."
- Keep explanations to 2–3 short sentences max.
- The code itself is for a developer to review — your words are for the process owner.

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

**CRITICAL — no `return` statements (Python syntax error in Frappe scripts):**
Frappe Server Scripts execute as TOP-LEVEL code, NOT inside a function. A bare `return`
is a Python SyntaxError and will be rejected on save. This includes early-exit patterns:

WRONG — causes SyntaxError:
```python
if not employees:
    frappe.response["message"] = {"employees": []}
    return   # ← SyntaxError: 'return' outside function
```

CORRECT — use if/else or frappe.throw() instead:
```python
if not employees:
    frappe.response["message"] = {"employees": [], "count": 0}
else:
    # ... rest of logic ...
    frappe.response["message"] = {"employees": result, "count": len(result)}
```
Or for true validation failures (abort the request):
```python
if not department:
    frappe.throw("Department is required")  # raises exception — no return needed
```

**Script writing rules:**
1. First lines: read every required variable from `frappe.form_dict`.
2. NEVER write `return` anywhere — it is a SyntaxError. Use `if/else` for branching and `frappe.throw()` to abort.
3. Last statement: set `frappe.response["message"]` to a dict.
4. Use Frappe ORM: `frappe.db.get_value`, `frappe.get_doc`, `frappe.get_all`, etc.
5. Use `frappe.throw()` for validation failures so Processa receives a clear error response.
6. No raw SQL unless explicitly requested.
7. No external libraries beyond a standard Frappe installation.

**Output format:**
- Wrap the entire script in a single ```python ... ``` code block.
- One-line comment at the top describing what the script does.
- Inline comments only where the logic is non-obvious.

Use tools to inspect existing scripts or confirm field names before writing code."""

_DEFAULT_TEST_WRITER_INSTRUCTION = """You are writing verification tests for a business process owner who cannot code.
Your job is to produce 3–5 plain-English test scenarios that the owner can run with one click to confirm the script does what it should.

**Language rules — non-negotiable:**
- Zero technical jargon. No words like "API", "endpoint", "JSON", "null", "boolean", "exception", "parameter".
- Write the way you would explain it to a colleague over coffee.
- "When:" describes the situation in plain English.
- "Expect:" describes what the person should see happen — in terms of the business outcome.

**`inputs` field — CRITICAL:**
Each scenario must include an `inputs` dict of the exact values to send as POST parameters.
Look at every `frappe.form_dict.get(...)` call in the script and provide a concrete, realistic value:
- Happy path: all required fields present with plausible values (e.g. "EMP-00001", "Sales Order", "SO-0001").
- Negative path: leave out a required field OR use a clearly wrong value (empty string, "INVALID-999").

**`expect_success` field:**
- `true`  → the script should complete and return information without stopping.
- `false` → the script should stop and show a validation message (e.g. "Employee is required").

**Return ONLY a JSON object — no markdown, no other text:**
{
    "checklist": [
        {
            "scenario": "Short plain-English title",
            "when": "Describe the situation in plain English",
            "expect": "Describe the expected business outcome in plain English",
            "inputs": {"context_doctype": "Employee", "context_docname": "EMP-00001"},
            "expect_success": true
        }
    ]
}"""

_DEFAULT_REVIEWER_INSTRUCTION = """You are a Frappe server script reviewer.

**HARD RULE — bare `return` is a SyntaxError:**
Frappe Server Scripts run as top-level Python code, not inside a function.
Any bare `return` statement (even `return` with no value) is a Python SyntaxError
that Frappe will reject on save. If the script contains ANY `return` statement
outside of a `def` block, you MUST set approved=false and rewrite it:
- Replace early-return guard patterns with if/else blocks
- Replace `return` used to skip code with restructured conditionals
- `frappe.throw()` is the correct way to abort — it raises an exception

Evaluate the given Python server script for:
1. Bare `return` outside a function — MUST fix (SyntaxError)
2. Correct Frappe ORM usage (no raw SQL unless justified)
3. Security — no arbitrary exec, no hardcoded secrets, no unguarded frappe.db.sql
4. Correctness — logical flow matches the described intent
5. Idiomatic style — follows Frappe conventions

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
        self._config = dict(get_agent_config(AGENT_ID) or {})
        self._config.setdefault("agent_id", AGENT_ID)
        self._llm    = get_llm_adapter_from_settings(self._config)
        self._instructions = self._load_instructions()

    def _load_instructions(self) -> dict:
        sub_prompts = (self._config or {}).get("sub_prompts", {})

        def _get(key, default):
            return sub_prompts.get(key, {}).get("prompt", default)

        return {
            "intent_classifier": _get("intent_classifier", _DEFAULT_INTENT_CLASSIFIER_INSTRUCTION),
            "clarifier":         _get("clarifier",         _DEFAULT_CLARIFIER_INSTRUCTION),
            "script_writer":     _get("script_writer",     _DEFAULT_WRITER_INSTRUCTION),
            "script_reviewer":   _get("script_reviewer",   _DEFAULT_REVIEWER_INSTRUCTION),
            "test_writer":       _get("test_writer",       _DEFAULT_TEST_WRITER_INSTRUCTION),
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _run(self, role: str, prompt: str, tools=None) -> str | None:
        return await self._llm.complete(
            system=self._instructions[role],
            user=prompt,
            tools=tools,
        )

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

    @staticmethod
    def _format_process_context(ctx: dict) -> str:
        if not ctx:
            return ""
        lines = ["**Process Context (from the BPMN diagram):**"]
        if ctx.get("process_name"):
            lines.append(f"- Process: {ctx['process_name']}")
        incoming = ctx.get("incoming") or []
        outgoing = ctx.get("outgoing") or []
        if incoming:
            neighbours = ", ".join(f"{n['name']} ({n['type']})" for n in incoming)
            lines.append(f"- This script runs AFTER: {neighbours}")
        if outgoing:
            neighbours = ", ".join(f"{n['name']} ({n['type']})" for n in outgoing)
            lines.append(f"- This script leads TO: {neighbours}")
        if not incoming and not outgoing:
            return ""
        lines.append(
            "Use this context to infer what workflow variables are available as inputs "
            "and what outputs the next step will need."
        )
        return "\n".join(lines)

    def _build_writer_prompt(
        self, message: str, chat_history: list, element_name: str,
        current_script: str, process_context: dict = None,
    ) -> str:
        parts = []
        ctx_str = self._format_process_context(process_context or {})
        if ctx_str:
            parts.append(ctx_str)
        if element_name:
            parts.append(f"**Script Task:** {element_name}")
        if current_script:
            parts.append(f"**Currently linked Server Script:** {current_script}")
        history = self._format_history(chat_history)
        if history:
            parts.append(f"**Conversation so far:**\n{history}")
        parts.append(f"**User request:** {message}")
        return "\n\n".join(parts)

    def _build_test_prompt(self, script_code: str, element_name: str, process_context: dict = None) -> str:
        parts = [f"**Script Task name:** {element_name or 'Unknown'}"]
        ctx_str = self._format_process_context(process_context or {})
        if ctx_str:
            parts.append(ctx_str)
        parts.append(f"**Script code to test:**\n```python\n{script_code}\n```")
        parts.append(
            "Generate a plain-English test checklist for this script. "
            "Return ONLY the JSON object as described in your instructions — no extra text, no code fences."
        )
        return "\n\n".join(parts)

    @staticmethod
    def _extract_code(response: str) -> str:
        match = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
        return match.group(1).strip() if match else response.strip()

    @staticmethod
    def _compute_diff(original: str, modified: str) -> str:
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

    # ── Main pipeline ──────────────────────────────────────────────────────────

    async def process_message(
        self,
        message: str,
        chat_history: list,
        element_name: str,
        current_script: str,
        original_script_content: str = "",
        process_context: dict = None,
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
        # STEP 1 — Classify intent
        intent_prompt = self._build_intent_prompt(message, current_script, element_name)
        intent_raw    = await self._run("intent_classifier", intent_prompt)

        intent = "CREATE" if not current_script else "MODIFY"
        try:
            intent_data = json.loads((intent_raw or "").strip())
            intent = intent_data.get("intent", intent).upper()
        except (json.JSONDecodeError, TypeError):
            pass
        if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
            intent = "CREATE" if not current_script else "MODIFY"

        # STEP 2a — DISAMBIGUATE
        if intent == "DISAMBIGUATE":
            clarify_raw = await self._run(
                "clarifier",
                self._build_intent_prompt(message, current_script, element_name),
                tools=_CLARIFIER_TOOLS,
            )
            try:
                clarify_data = json.loads((clarify_raw or "").strip())
                return {
                    "intent":         "DISAMBIGUATE",
                    "response":       clarify_data.get("question", clarify_raw),
                    "options":        clarify_data.get("options", []),
                    "diff":           None,
                    "suggested_name": None,
                }
            except (json.JSONDecodeError, TypeError):
                return {
                    "intent":         "DISAMBIGUATE",
                    "response":       clarify_raw or "Could you clarify your request?",
                    "options":        [],
                    "diff":           None,
                    "suggested_name": None,
                }

        # STEP 2b — CREATE / MODIFY: write → review → validate (up to 3 attempts)
        _MAX_RETRIES  = 2
        writer_prompt = self._build_writer_prompt(message, chat_history, element_name, current_script, process_context)
        final         = None
        modified_code = ""

        for attempt in range(_MAX_RETRIES + 1):
            draft = await self._run("script_writer", writer_prompt, tools=_WRITER_TOOLS)
            if not draft:
                break

            review_raw    = await self._run("script_reviewer", draft)
            candidate     = self._apply_review(draft, review_raw)

            # If there's no Python code block the agent is asking a question —
            # pass it straight through without security validation.
            if not re.search(r"```python\s*\n.*?```", candidate, re.DOTALL):
                final = candidate
                break

            modified_code = self._extract_code(candidate)

            validation = validate_script(modified_code)
            if validation["valid"]:
                final = candidate
                break

            is_last = attempt == _MAX_RETRIES
            frappe.log_error(
                title="Logix Security Validator — " + ("Max retries reached" if is_last else "Auto-regenerating"),
                message=(
                    f"Attempt {attempt + 1}/{_MAX_RETRIES + 1} blocked.\n"
                    f"Violations: {validation['violations']}\n"
                    f"Action: {'Returning error to user' if is_last else 'Regenerating with safe Frappe ORM prompt'}\n\n"
                    f"Flagged code:\n{modified_code}"
                ),
            )

            if is_last:
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

            writer_prompt = self._build_regeneration_prompt(writer_prompt, validation["violations"])

        if not final:
            return {
                "intent":          intent,
                "response":        "I wasn't able to generate a script. Please try again.",
                "diff":            None,
                "options":         None,
                "suggested_name":  None,
                "original_script": None,
                "modified_script": None,
            }

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

        # STEP 3 (CREATE only) — generate plain-English verification checklist
        tests_checklist = []
        if modified_code:
            test_raw = None
            try:
                test_prompt = self._build_test_prompt(modified_code, element_name, process_context)
                test_raw    = await self._run("test_writer", test_prompt)
                # Strip markdown fences that LLMs often wrap JSON in
                raw_stripped = (test_raw or "").strip()
                if raw_stripped.startswith("```"):
                    # Remove opening fence (```json or ```) and closing fence (```)
                    raw_stripped = raw_stripped.split("\n", 1)[-1]
                    if raw_stripped.endswith("```"):
                        raw_stripped = raw_stripped[: raw_stripped.rfind("```")].strip()
                test_data = json.loads(raw_stripped)
                tests_checklist = test_data.get("checklist", [])
            except Exception as exc:
                # Tests are bonus — don't fail the whole response, but log for visibility
                frappe.log_error(
                    title="Logix test_writer parse error",
                    message=(
                        f"Error: {exc}\n"
                        f"Raw output (first 500 chars):\n{(test_raw or '')[:500]}"
                    ),
                )

        return {
            "intent":           "CREATE",
            "response":         final,
            "diff":             None,
            "original_script":  None,
            "modified_script":  modified_code,
            "options":          None,
            "suggested_name":   element_name or None,
            "tests_checklist":  tests_checklist,
        }


def run_logix_message(
    message: str,
    chat_history: list,
    element_name: str,
    current_script: str,
    original_script_content: str = "",
    process_context: dict = None,
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
            process_context=process_context,
        )
    )
