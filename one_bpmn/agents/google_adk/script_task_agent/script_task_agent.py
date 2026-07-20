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

# Optional specialist sub-prompts: loaded when present, but their absence must
# not break the whole agent (the general writer/reviewer path still works).
_OPTIONAL_SUB_PROMPTS = (
    "tool_writer",
)

# Human-readable element labels per shape kind (see logix-agent.instructions.md).
_SHAPE_KIND_LABELS = {
    "agent_tool": "Agent Tool",
    "script_task": "Script Task",
}


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

        for key in _OPTIONAL_SUB_PROMPTS:
            prompt = sub_prompts.get(key, {}).get("prompt")
            if prompt:
                instructions[key] = prompt

        return instructions

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _run(self, role: str, prompt: str, tools=None) -> str | None:
        # complete() returns a CompletionResult since WI-001356; this agent
        # only needs the final answer text.
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
            role    = entry.get("role") or entry.get("type", "user")
            content = (entry.get("content") or "").strip()
            if content:
                lines.append(f"{'User' if role == 'user' else 'Logix'}: {content}")
        return "\n".join(lines)

    def _build_intent_prompt(
        self, message: str, current_script: str, element_name: str, shape_kind: str = "",
    ) -> str:
        parts = []
        label = _SHAPE_KIND_LABELS.get(shape_kind, "Script Task")
        if element_name:
            parts.append(f"{label}: {element_name}")
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
        is_tool = ctx.get("shape_kind") == "agent_tool"
        lines = ["**Process Context (from the BPMN diagram):**"]
        if ctx.get("process_name"):
            lines.append(f"- Process: {ctx['process_name']}")
        if is_tool:
            lines.append(
                "- This element is an AGENT TOOL inside an AI Agent Task's ad-hoc Tools "
                "sub-process — an LLM calls it on demand; it is NOT a sequential process step."
            )
        incoming = ctx.get("incoming") or []
        outgoing = ctx.get("outgoing") or []
        if incoming:
            neighbours = ", ".join(f"{n['name']} ({n['type']})" for n in incoming)
            lines.append(f"- This script runs AFTER: {neighbours}")
        if outgoing:
            neighbours = ", ".join(f"{n['name']} ({n['type']})" for n in outgoing)
            lines.append(f"- This script leads TO: {neighbours}")
        if not incoming and not outgoing and not is_tool:
            return ""
        if is_tool:
            # Agent tools receive NO workflow variables — never invite the model
            # to "infer available workflow variables" for one.
            lines.append(
                "Remember: an agent tool receives ONLY the arguments the calling LLM "
                "passes (plus frappe/doc/context_doctype/context_docname/result) — "
                "no workflow variables and no task_data exist in its namespace."
            )
        else:
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
        ctx = process_context or {}
        shape_kind = ctx.get("shape_kind") or "script_task"
        ctx_str = self._format_process_context(ctx)
        if ctx_str:
            parts.append(ctx_str)
        parts.append(f"**Shape kind:** {shape_kind}")
        if element_name:
            label = _SHAPE_KIND_LABELS.get(shape_kind, "Script Task")
            parts.append(f"**{label}:** {element_name}")
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

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        """Remove a surrounding ```json ... ``` fence LLMs often wrap JSON in."""
        stripped = (text or "").strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[: stripped.rstrip().rfind("```")]
        return stripped.strip()

    @staticmethod
    def _extract_json(text: str | None) -> dict | None:
        """Best-effort parse of a JSON object from an LLM reply.

        Models asked to "respond with ONLY a JSON object" still frequently wrap
        it in ```json fences and/or lead with prose. Without this, callers fall
        back to showing the raw blob to the user. Tries, in order: the whole
        text, the fence-stripped text, the first fenced block, and the first
        balanced {...} span.
        """
        if not text:
            return None
        candidates = [text.strip(), ScriptTaskAgent._strip_json_fences(text)]
        fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fenced:
            candidates.append(fenced.group(1).strip())
        start = text.find("{")
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start:i + 1])
                        break
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _apply_review(self, draft: str, review_text: str | None) -> str:
        if not review_text:
            return draft
        try:
            # Fenced JSON must not silently void the review — a rejected draft
            # would otherwise pass through unrevised.
            review = json.loads(self._strip_json_fences(review_text))
            if not review.get("approved") and review.get("revised_script"):
                # Keep the reply text and its ```python fence intact — returning
                # the bare revised code makes the downstream fence check
                # misclassify the reply as a question and skip validation.
                revised = review["revised_script"]
                if re.search(r"```python\s*\n.*?```", draft, re.DOTALL):
                    return logix_tools.replace_code_block(draft, revised)
                return f"```python\n{revised}\n```"
            if review.get("suggestions"):
                note = "\n\n> **Review notes:** " + "; ".join(review["suggestions"])
                return draft + note
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
        return draft
