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

import ast
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


def replace_code_block(text: str, new_code: str) -> str:
    """Swap the body of the first ```python fenced block in ``text`` for
    ``new_code``.

    Used to keep the reply the user reads identical to the script that will
    actually be applied after the optimizer rewrites it. Returns ``text``
    unchanged when it contains no python fence (e.g. the agent asked a
    question instead of writing code).
    """
    pattern = re.compile(r"(```python\s*\n)(.*?)(```)", re.DOTALL)
    if not pattern.search(text or ""):
        return text
    return pattern.sub(
        lambda m: m.group(1) + new_code.rstrip("\n") + "\n" + m.group(3),
        text or "",
        count=1,
    )


# ── Optimization pass ────────────────────────────────────────────────────────
# Names the BPMN engine injects into every Server Script's scope
# (engine.py FrappeScriptEngine._run_frappe_server_script). They are pre-defined
# and — in the case of ``result`` — read back by the engine after the script
# runs, so a binding to one of them is NEVER dead code, even if the script never
# reads it back itself.
_ENGINE_INJECTED_NAMES = frozenset({
    "frappe", "doc", "task_data", "result",
    "context_doctype", "context_docname",
})


def _is_side_effect_free(node: ast.AST) -> bool:
    """True when evaluating ``node`` cannot have a side effect, so an assignment
    whose value is never read can be dropped entirely rather than merely unbound.

    Deliberately conservative: only literals, bare names, and pure combinations
    of those qualify. A call, attribute access, comprehension, subscript, await,
    etc. is treated as potentially side-effecting and its assignment is KEPT
    (e.g. ``x = frappe.db.set_value(...)`` stays even if ``x`` is unused).
    """
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_side_effect_free(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return (all(_is_side_effect_free(k) for k in node.keys if k is not None)
                and all(_is_side_effect_free(v) for v in node.values))
    if isinstance(node, ast.BinOp):
        return _is_side_effect_free(node.left) and _is_side_effect_free(node.right)
    if isinstance(node, ast.UnaryOp):
        return _is_side_effect_free(node.operand)
    if isinstance(node, ast.BoolOp):
        return all(_is_side_effect_free(v) for v in node.values)
    if isinstance(node, ast.Compare):
        return (_is_side_effect_free(node.left)
                and all(_is_side_effect_free(c) for c in node.comparators))
    if isinstance(node, ast.IfExp):
        return all(_is_side_effect_free(n) for n in (node.test, node.body, node.orelse))
    if isinstance(node, ast.JoinedStr):
        return all(_is_side_effect_free(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _is_side_effect_free(node.value)
    return False


def optimize_script(code: str, max_passes: int = 6) -> str:
    """Conservatively strip dead code from a generated Server Script.

    Two removals, both provably behaviour-preserving:

      * **unused imports** — an ``import`` / ``from … import`` whose every bound
        name is never referenced (skips ``from __future__`` and star imports),
      * **unused variable assignments** whose right-hand side is side-effect-free
        (see :func:`_is_side_effect_free`) and whose single ``Name`` target is
        never referenced.

    Everything else is left untouched: assignments to engine-injected names,
    tuple / attribute / subscript targets, chained and augmented/annotated
    assignments, and any binding whose value could have a side effect. Comments
    and formatting survive because removal is line-based, and a flagged node is
    skipped whenever it shares a physical line with another statement (so a
    compound one-liner like ``if x: y = 1`` is never mangled).

    Runs to a fixpoint (one removal can orphan another binding). NEVER raises and
    NEVER returns code that fails to parse: on any parse failure it returns the
    last version that parsed (the original when the first parse already fails).
    """
    if not code or not code.strip():
        return code

    current = code
    for _ in range(max_passes):
        try:
            tree = ast.parse(current)
        except SyntaxError:
            return current

        # A name is "referenced" if it is read (Load), deleted (Del — a later
        # `del x` would NameError if we dropped its binding), or declared
        # global/nonlocal. Store-only names are the removal candidates.
        referenced: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Load, ast.Del)):
                referenced.add(n.id)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                referenced.update(n.names)

        # Start line of every statement, so a flagged node that shares a line
        # with a statement we must keep (compound one-liners, `a; b`) is spared.
        stmt_starts = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.stmt)]

        drop_lines: set[int] = set()

        def _flag(node: ast.AST) -> None:
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            # Exactly one statement (this node) may start within the span.
            if sum(1 for s in stmt_starts if start <= s <= end) != 1:
                return
            drop_lines.update(range(start, end + 1))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                bound = [a.asname or a.name.split(".")[0] for a in node.names]
                if bound and all(
                    b not in referenced and b not in _ENGINE_INJECTED_NAMES for b in bound
                ):
                    _flag(node)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "__future__" or any(a.name == "*" for a in node.names):
                    continue
                bound = [a.asname or a.name for a in node.names]
                if bound and all(
                    b not in referenced and b not in _ENGINE_INJECTED_NAMES for b in bound
                ):
                    _flag(node)
            elif isinstance(node, ast.Assign):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    name = node.targets[0].id
                    if (name not in referenced
                            and name not in _ENGINE_INJECTED_NAMES
                            and _is_side_effect_free(node.value)):
                        _flag(node)

        if not drop_lines:
            break

        lines = current.split("\n")
        candidate = "\n".join(
            ln for i, ln in enumerate(lines, start=1) if i not in drop_lines
        )
        try:
            ast.parse(candidate)  # never emit something that won't parse
        except SyntaxError:
            break
        if candidate == current:
            break
        current = candidate

    return current


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
