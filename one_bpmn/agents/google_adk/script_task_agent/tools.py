# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Logix (Script Task) deterministic tools.

Logix was already half-toolified: the four *read* capabilities
(list_api_server_scripts / get_server_script_content / get_server_script_meta /
get_doctype_fields) were ToolSpecs the writer/clarifier sub-agents call. This
module makes the decomposition complete and gives the Epic-4 multi-turn loop a
single registry (``LOGIX_TOOLS``) to consume — the Camunda agentic-AI
tool-calling pattern.

It adds the deterministic transforms that were previously buried inside the
orchestrator:

    validate_script   security-lint Python + actionable safe-rewrite hints
    diff_scripts      unified diff of two script versions
    extract_code      pull the Python code block out of an LLM response

The LLM-reasoning steps (intent classify / clarify / write / review) stay in the
loop. Core functions return plain dicts/strings (ergonomic for tests); the
ToolSpec wrappers JSON-encode results to match the tool-result convention used
across ``agents/`` (see tool_for_server_scripts.py / tool_registry.py).

SECURITY NOTE: ``validate_script`` is a *safety* gate, not a quality lint. Any
future ``apply_server_script`` action tool MUST re-run it server-side and refuse
on violation — never trust that the loop model validated before applying.

This is the single source of truth — ``script_task_agent.py`` delegates here.
"""

from __future__ import annotations

import difflib
import json
import re

from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.security.script_validator import validate_script as _security_validate_script
from one_bpmn.tools.tool_for_server_scripts import (
    get_doctype_fields,
    get_server_script_content,
    get_server_script_meta,
    list_api_server_scripts,
)

# The safe-rewrite guidance handed back when a script fails the security gate.
# Kept here (not in the orchestrator's regeneration prompt) so any consumer of
# validate_script gets self-repair guidance for free.
SAFE_REWRITE_GUIDANCE = (
    "Rewrite the script WITHOUT any of the flagged patterns. Use only "
    "`frappe.get_doc`, `frappe.db.get_value`, `frappe.get_all`, and other safe "
    "Frappe ORM methods. Do NOT import os, sys, subprocess, or any module "
    "outside the standard Frappe sandbox."
)


# ── Deterministic transforms ────────────────────────────────────────────────
def validate_script(code: str) -> dict:
    """Security-lint a generated Server Script.

    Returns ``{valid, violations, fix_hints}``. ``violations`` are the raw
    validator strings; ``fix_hints`` carries the safe-rewrite guidance a
    self-correcting loop can feed straight back to the model (empty when valid).
    """
    result = _security_validate_script(code)
    violations = result.get("violations", []) or []
    return {
        "valid": bool(result.get("valid")),
        "violations": violations,
        "fix_hints": [] if not violations else [SAFE_REWRITE_GUIDANCE],
    }


def diff_scripts(original: str, modified: str) -> dict:
    """Unified diff between two script versions. Returns ``{diff}`` ("" if identical)."""
    diff = difflib.unified_diff(
        (original or "").splitlines(keepends=True),
        (modified or "").splitlines(keepends=True),
        fromfile="original",
        tofile="modified",
        lineterm="",
    )
    return {"diff": "".join(diff)}


def extract_code(response: str) -> str:
    """Pull the first ```python fenced block from an LLM response; else the whole text."""
    match = re.search(r"```python\s*\n(.*?)```", response or "", re.DOTALL)
    return match.group(1).strip() if match else (response or "").strip()


# ── Read ToolSpecs (already existed on the agent; centralised here) ──────────
TOOL_LIST_SCRIPTS = ToolSpec(
    fn=list_api_server_scripts,
    name="list_api_server_scripts",
    description="List all enabled API-type Server Scripts available in the system.",
    parameters={},
    required=[],
)
TOOL_GET_CONTENT = ToolSpec(
    fn=get_server_script_content,
    name="get_server_script_content",
    description="Fetch the full Python source code of a Frappe Server Script by name.",
    parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
    required=["script_name"],
)
TOOL_GET_META = ToolSpec(
    fn=get_server_script_meta,
    name="get_server_script_meta",
    description="Fetch the metadata (type, doctype, method, disabled status) of a Server Script.",
    parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
    required=["script_name"],
)
TOOL_GET_FIELDS = ToolSpec(
    fn=get_doctype_fields,
    name="get_doctype_fields",
    description="Get the field names and types for a Frappe DocType.",
    parameters={"doctype": {"type": "string", "description": "The DocType name, e.g. 'Employee', 'Sales Order'."}},
    required=["doctype"],
)

# Sub-agent tool bundles (imported by the agent — unchanged behaviour).
WRITER_TOOLS = [TOOL_GET_CONTENT, TOOL_GET_META, TOOL_LIST_SCRIPTS, TOOL_GET_FIELDS]
CLARIFIER_TOOLS = [TOOL_LIST_SCRIPTS, TOOL_GET_META]

# ── Transform ToolSpecs ──────────────────────────────────────────────────────
TOOL_VALIDATE_SCRIPT = ToolSpec(
    fn=lambda code="": json.dumps(validate_script(code)),
    name="validate_script",
    description=(
        "Security-lint a Python Server Script. Returns {valid, violations, fix_hints}. "
        "A script must pass this before it can be applied."
    ),
    parameters={"code": {"type": "string", "description": "The Python script source to validate."}},
    required=["code"],
)
TOOL_DIFF_SCRIPTS = ToolSpec(
    fn=lambda original="", modified="": json.dumps(diff_scripts(original, modified)),
    name="diff_scripts",
    description="Compute a unified diff between an original and a modified script. Returns {diff}.",
    parameters={
        "original": {"type": "string", "description": "The original script source."},
        "modified": {"type": "string", "description": "The modified script source."},
    },
    required=["original", "modified"],
)

# Single export the Epic-4 loop reads: the full Logix tool surface.
LOGIX_TOOLS: list = [
    TOOL_LIST_SCRIPTS,
    TOOL_GET_CONTENT,
    TOOL_GET_META,
    TOOL_GET_FIELDS,
    TOOL_VALIDATE_SCRIPT,
    TOOL_DIFF_SCRIPTS,
]
