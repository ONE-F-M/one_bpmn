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
import json
import re

import frappe

from onefm_mcp.onefm_mcp.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.google_adk.script_task_agent import tools as logix_tools

AGENT_ID = "logix_agent"

# Tool specs and the deterministic transforms now live in tools.py (the single
# source of truth shared with the Epic-4 loop). LOGIX_TOOLS is the full surface;
# these bundles are the per-sub-agent subsets the current single-call flow uses.
_WRITER_TOOLS = logix_tools.WRITER_TOOLS
_CLARIFIER_TOOLS = logix_tools.CLARIFIER_TOOLS

# ── Required sub-prompt keys (must exist in AI Agent Configuration) ─────────────
_REQUIRED_SUB_PROMPTS = (
    "intent_classifier",
    "clarifier",
    "script_writer",
    "script_reviewer",
    "test_writer",
)


class ScriptTaskAgent:
    """Orchestrates intent classification, script writing, review, and diffing."""

    def __init__(self):
        self._config = dict(get_agent_config(AGENT_ID) or {})
        self._config.setdefault("agent_id", AGENT_ID)
        self._llm    = get_llm_adapter_from_settings(self._config)
        self._instructions = self._load_instructions()

    def _load_instructions(self) -> dict:
        """Load all sub-prompt instructions from AI Agent Configuration.

        Raises frappe.ValidationError if a required sub-prompt is missing,
        directing the user to populate it in the AI Agent Configuration UI.
        """
        sub_prompts = (self._config or {}).get("sub_prompts", {})
        instructions = {}

        for key in _REQUIRED_SUB_PROMPTS:
            prompt = sub_prompts.get(key, {}).get("prompt")
            if not prompt:
                import frappe as _frappe
                _frappe.throw(
                    f"AI Agent Configuration for '{AGENT_ID}' is missing "
                    f"the required sub-prompt '{key}'. "
                    f"Please add it in the AI Agent Configuration DocType."
                )
            instructions[key] = prompt

        return instructions

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
        """Pull the python code block from an LLM response. See tools.extract_code."""
        return logix_tools.extract_code(response)

    @staticmethod
    def _compute_diff(original: str, modified: str) -> str:
        """Unified diff between two script versions. See tools.diff_scripts."""
        return logix_tools.diff_scripts(original, modified)["diff"]

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

            validation = logix_tools.validate_script(modified_code)
            if validation["valid"]:
                # Strip dead code (unused imports + unused pure assignments) from
                # the approved script, then re-validate so an optimized script can
                # never slip past the security gate. Keep the reply text in sync
                # with the code that will actually be applied.
                optimized = logix_tools.optimize_script(modified_code)
                if optimized != modified_code and logix_tools.validate_script(optimized)["valid"]:
                    candidate     = logix_tools.replace_code_block(candidate, optimized)
                    modified_code = optimized
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
