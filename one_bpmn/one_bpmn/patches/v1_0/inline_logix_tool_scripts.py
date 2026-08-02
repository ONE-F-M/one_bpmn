"""
Full-rip conversion (per-agent migration follow-up): the Logix chat agent's
pipeline stage tools no longer import any Python package. Each tool Server
Script in the process map's ad-hoc Tools sub-process now carries its own
self-contained, FLAT logic; the one_bpmn.agents.google_adk.script_task_agent
package has been deleted. This patch installs those bodies idempotently so
every environment converges on the process-model-only Logix agent.

The bodies are FLAT (no def/lambda, no comprehension referencing a module-level
name) because the AI Agent shape-tool executor runs them under SPLIT
globals/locals (shape_tools._run_server_script) — a nested scope cannot see
top-level imports/consts there. They call only shared infrastructure reused
across agents: turn_state, the LLM adapter factory, get_agent_config, the
security validator, and the generic tool_for_server_scripts read tools.

Idempotent: only updates a Server Script that exists and whose body differs.
Ordered after add_logix_agent_tool_authoring (which creates the rows).
"""

import frappe

CLASSIFY = r'''# Logix – Tool Classify Intent (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — so it uses NO
# def/lambda and no comprehension that references a module-level import/const.
# Classify the request as CREATE, MODIFY, or DISAMBIGUATE. Called first.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

turn = get_turn(context_docname)
_cfg = get_agent_config("logix_agent") or {}
_cfg.setdefault("agent_id", "logix_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

current_script = turn.get("current_script", "")
shape_kind = (turn.get("process_context") or {}).get("shape_kind") or "script_task"
element_name = turn.get("element_name", "")
message = turn.get("user_text", "")

# ── build intent prompt (inline) ──
_label = "Agent Tool" if shape_kind == "agent_tool" else "Script Task"
_parts = []
if element_name:
    _parts.append(_label + ": " + element_name)
if current_script:
    _parts.append("Linked script: " + current_script + "  ← existing, treat as MODIFY target unless stated otherwise")
else:
    _parts.append("No script linked yet  ← default to CREATE")
_parts.append("User request: " + message)
prompt = "\n".join(_parts)

_system = (_subs.get("intent_classifier") or {}).get("prompt") or ""
raw = run_sync(_adapter.complete(system=_system, user=prompt)).text

# ── best-effort JSON extraction (inline) ──
data = None
if raw:
    _cands = [raw.strip()]
    _s2 = raw.strip()
    if _s2.startswith("```"):
        _s2 = _s2.split("\n", 1)[-1]
        if _s2.rstrip().endswith("```"):
            _s2 = _s2.rstrip()[: _s2.rstrip().rfind("```")]
    _cands.append(_s2.strip())
    _fenced = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if _fenced:
        _cands.append(_fenced.group(1).strip())
    _start = raw.find("{")
    if _start != -1:
        _depth = 0
        for _i in range(_start, len(raw)):
            if raw[_i] == "{":
                _depth += 1
            elif raw[_i] == "}":
                _depth -= 1
                if _depth == 0:
                    _cands.append(raw[_start:_i + 1])
                    break
    for _c in _cands:
        try:
            _p = json.loads(_c)
            if isinstance(_p, dict):
                data = _p
                break
        except (json.JSONDecodeError, TypeError):
            continue

intent = "CREATE" if not current_script else "MODIFY"
if data and data.get("intent"):
    intent = str(data["intent"]).upper()
if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
    intent = "CREATE" if not current_script else "MODIFY"

# Deterministic routing so the orchestrator never skips a stage.
if intent == "DISAMBIGUATE":
    nxt = "clarify"
elif shape_kind == "agent_tool":
    nxt = "write_agent_tool"
else:
    nxt = "write_script"

update_turn(context_docname, intent=intent, shape_kind=shape_kind)
result["intent"] = intent
result["shape_kind"] = shape_kind
result["next"] = nxt
'''

CLARIFY = r'''# Logix – Tool Clarify (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Ask one focused clarifying question (use only when intent is DISAMBIGUATE).
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.tools.tool_for_server_scripts import get_server_script_meta, list_api_server_scripts

turn = get_turn(context_docname)
_cfg = get_agent_config("logix_agent") or {}
_cfg.setdefault("agent_id", "logix_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

_clarifier_tools = [
    ToolSpec(
        fn=list_api_server_scripts,
        name="list_api_server_scripts",
        description="List all enabled API-type Server Scripts available in the system.",
        parameters={},
        required=[],
    ),
    ToolSpec(
        fn=get_server_script_meta,
        name="get_server_script_meta",
        description="Fetch the metadata (type, doctype, method, disabled status) of a Server Script.",
        parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
        required=["script_name"],
    ),
]

# ── build intent prompt (inline) ──
current_script = turn.get("current_script", "")
element_name = turn.get("element_name", "")
message = turn.get("user_text", "")
_parts = []
if element_name:
    _parts.append("Script Task: " + element_name)
if current_script:
    _parts.append("Linked script: " + current_script + "  ← existing, treat as MODIFY target unless stated otherwise")
else:
    _parts.append("No script linked yet  ← default to CREATE")
_parts.append("User request: " + message)
prompt = "\n".join(_parts)

_system = (_subs.get("clarifier") or {}).get("prompt") or ""
raw = run_sync(_adapter.complete(system=_system, user=prompt, tools=_clarifier_tools)).text

# ── best-effort JSON extraction (inline) ──
data = None
if raw:
    _cands = [raw.strip()]
    _s2 = raw.strip()
    if _s2.startswith("```"):
        _s2 = _s2.split("\n", 1)[-1]
        if _s2.rstrip().endswith("```"):
            _s2 = _s2.rstrip()[: _s2.rstrip().rfind("```")]
    _cands.append(_s2.strip())
    _fenced = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if _fenced:
        _cands.append(_fenced.group(1).strip())
    _start = raw.find("{")
    if _start != -1:
        _depth = 0
        for _i in range(_start, len(raw)):
            if raw[_i] == "{":
                _depth += 1
            elif raw[_i] == "}":
                _depth -= 1
                if _depth == 0:
                    _cands.append(raw[_start:_i + 1])
                    break
    for _c in _cands:
        try:
            _p = json.loads(_c)
            if isinstance(_p, dict):
                data = _p
                break
        except (json.JSONDecodeError, TypeError):
            continue

question = raw or "Could you clarify your request?"
options = []
if data:
    question = data.get("question") or question
    options = data.get("options") or []

output = {
    "intent": "DISAMBIGUATE",
    "response": question,
    "options": options,
    "diff": None,
    "suggested_name": None,
}
update_turn(context_docname, output=output, done=True)
result["response"] = question
result["options"] = options
'''

WRITE = r'''# Logix – Tool Write Script (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda;
# comprehensions reference only their own loop var.
# Write or rewrite the Server Script. Regenerates safe code if review flagged violations.
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.tools.tool_for_server_scripts import (
    get_doctype_fields,
    get_server_script_content,
    get_server_script_meta,
    list_api_server_scripts,
)

turn = get_turn(context_docname)
_cfg = get_agent_config("logix_agent") or {}
_cfg.setdefault("agent_id", "logix_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

_writer_tools = [
    ToolSpec(fn=get_server_script_content, name="get_server_script_content",
             description="Fetch the full Python source code of a Frappe Server Script by name.",
             parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
             required=["script_name"]),
    ToolSpec(fn=get_server_script_meta, name="get_server_script_meta",
             description="Fetch the metadata (type, doctype, method, disabled status) of a Server Script.",
             parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
             required=["script_name"]),
    ToolSpec(fn=list_api_server_scripts, name="list_api_server_scripts",
             description="List all enabled API-type Server Scripts available in the system.",
             parameters={}, required=[]),
    ToolSpec(fn=get_doctype_fields, name="get_doctype_fields",
             description="Get the field names and types for a Frappe DocType.",
             parameters={"doctype": {"type": "string", "description": "The DocType name, e.g. 'Employee', 'Sales Order'."}},
             required=["doctype"]),
]

message = turn.get("user_text", "")
chat_history = turn.get("chat_history", []) or []
element_name = turn.get("element_name", "")
current_script = turn.get("current_script", "")
ctx = turn.get("process_context") or {}
shape_kind = ctx.get("shape_kind") or "script_task"
_label = "Agent Tool" if shape_kind == "agent_tool" else "Script Task"

# ── format process context (inline) ──
_ctx_str = ""
if ctx:
    _is_tool = ctx.get("shape_kind") == "agent_tool"
    _clines = ["**Process Context (from the BPMN diagram):**"]
    if ctx.get("process_name"):
        _clines.append("- Process: " + str(ctx["process_name"]))
    if _is_tool:
        _clines.append("- This element is an AGENT TOOL inside an AI Agent Task's ad-hoc Tools sub-process — an LLM calls it on demand; it is NOT a sequential process step.")
    _incoming = ctx.get("incoming") or []
    _outgoing = ctx.get("outgoing") or []
    if _incoming:
        _clines.append("- This script runs AFTER: " + ", ".join(n["name"] + " (" + n["type"] + ")" for n in _incoming))
    if _outgoing:
        _clines.append("- This script leads TO: " + ", ".join(n["name"] + " (" + n["type"] + ")" for n in _outgoing))
    if not _incoming and not _outgoing and not _is_tool:
        _ctx_str = ""
    elif _is_tool:
        _clines.append("Remember: an agent tool receives ONLY the arguments the calling LLM passes (plus frappe/doc/context_doctype/context_docname/result) — no workflow variables and no task_data exist in its namespace.")
        _ctx_str = "\n".join(_clines)
    else:
        _clines.append("Use this context to infer what workflow variables are available as inputs and what outputs the next step will need.")
        _ctx_str = "\n".join(_clines)

# ── format history (inline) ──
_hist = ""
if chat_history:
    _hlines = []
    for _e in chat_history[-10:]:
        _role = _e.get("role") or _e.get("type", "user")
        _content = (_e.get("content") or "").strip()
        if _content:
            _hlines.append(("User" if _role == "user" else "Logix") + ": " + _content)
    _hist = "\n".join(_hlines)

# ── build writer prompt (inline) ──
_parts = []
if _ctx_str:
    _parts.append(_ctx_str)
_parts.append("**Shape kind:** " + shape_kind)
if element_name:
    _parts.append("**" + _label + ":** " + element_name)
if current_script:
    _parts.append("**Currently linked Server Script:** " + current_script)
_original = turn.get("original_script_content", "")
if _original:
    _parts.append("**Existing script (the CURRENT code of the linked Server Script) - you are MODIFYING this. Rewrite THIS code, preserve its intent and structure, and change only what the user asked. Do NOT invent a new script from scratch:**\n```python\n" + _original + "\n```")
if _hist:
    _parts.append("**Conversation so far:**\n" + _hist)
_parts.append("**User request:** " + message)
prompt = "\n\n".join(_parts)

# ── security regeneration (inline) ──
violations = turn.get("violations") or []
if violations:
    _bullets = "\n".join("  - " + v for v in violations)
    prompt = (
        prompt + "\n\n"
        "**SECURITY REGENERATION REQUEST**\n"
        "The previous attempt was blocked by the security validator for these violations:\n"
        + _bullets + "\n\n"
        "Rewrite the script WITHOUT any of these patterns. "
        "Use only `frappe.get_doc`, `frappe.db.get_value`, `frappe.get_all`, "
        "and other safe Frappe ORM methods. "
        "Do NOT import os, sys, subprocess, or any module outside the standard Frappe sandbox."
    )

_system = (_subs.get("script_writer") or {}).get("prompt") or ""
draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text
update_turn(context_docname, draft=(draft or ""))
has_code = bool(re.search(r"```python\s*\n.*?```", draft or "", re.DOTALL))
result["has_code"] = has_code
result["preview"] = (draft or "")[:400]
'''

WRITE_AGENT_TOOL = r'''# Logix – Tool Write Agent Tool (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Author an Agent Tool script (element inside an AI Agent Task's ad-hoc Tools
# sub-process). Regenerates safe code if review flagged violations.
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.tools.tool_for_server_scripts import (
    get_doctype_fields,
    get_server_script_content,
    get_server_script_meta,
    list_api_server_scripts,
)

turn = get_turn(context_docname)
_cfg = get_agent_config("logix_agent") or {}
_cfg.setdefault("agent_id", "logix_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

_writer_tools = [
    ToolSpec(fn=get_server_script_content, name="get_server_script_content",
             description="Fetch the full Python source code of a Frappe Server Script by name.",
             parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
             required=["script_name"]),
    ToolSpec(fn=get_server_script_meta, name="get_server_script_meta",
             description="Fetch the metadata (type, doctype, method, disabled status) of a Server Script.",
             parameters={"script_name": {"type": "string", "description": "The exact name (document ID) of the Server Script."}},
             required=["script_name"]),
    ToolSpec(fn=list_api_server_scripts, name="list_api_server_scripts",
             description="List all enabled API-type Server Scripts available in the system.",
             parameters={}, required=[]),
    ToolSpec(fn=get_doctype_fields, name="get_doctype_fields",
             description="Get the field names and types for a Frappe DocType.",
             parameters={"doctype": {"type": "string", "description": "The DocType name, e.g. 'Employee', 'Sales Order'."}},
             required=["doctype"]),
]

message = turn.get("user_text", "")
chat_history = turn.get("chat_history", []) or []
element_name = turn.get("element_name", "")
current_script = turn.get("current_script", "")
ctx = turn.get("process_context") or {}
shape_kind = ctx.get("shape_kind") or "script_task"
_label = "Agent Tool" if shape_kind == "agent_tool" else "Script Task"

# ── format process context (inline) ──
_ctx_str = ""
if ctx:
    _is_tool = ctx.get("shape_kind") == "agent_tool"
    _clines = ["**Process Context (from the BPMN diagram):**"]
    if ctx.get("process_name"):
        _clines.append("- Process: " + str(ctx["process_name"]))
    if _is_tool:
        _clines.append("- This element is an AGENT TOOL inside an AI Agent Task's ad-hoc Tools sub-process — an LLM calls it on demand; it is NOT a sequential process step.")
    _incoming = ctx.get("incoming") or []
    _outgoing = ctx.get("outgoing") or []
    if _incoming:
        _clines.append("- This script runs AFTER: " + ", ".join(n["name"] + " (" + n["type"] + ")" for n in _incoming))
    if _outgoing:
        _clines.append("- This script leads TO: " + ", ".join(n["name"] + " (" + n["type"] + ")" for n in _outgoing))
    if not _incoming and not _outgoing and not _is_tool:
        _ctx_str = ""
    elif _is_tool:
        _clines.append("Remember: an agent tool receives ONLY the arguments the calling LLM passes (plus frappe/doc/context_doctype/context_docname/result) — no workflow variables and no task_data exist in its namespace.")
        _ctx_str = "\n".join(_clines)
    else:
        _clines.append("Use this context to infer what workflow variables are available as inputs and what outputs the next step will need.")
        _ctx_str = "\n".join(_clines)

# ── format history (inline) ──
_hist = ""
if chat_history:
    _hlines = []
    for _e in chat_history[-10:]:
        _role = _e.get("role") or _e.get("type", "user")
        _content = (_e.get("content") or "").strip()
        if _content:
            _hlines.append(("User" if _role == "user" else "Logix") + ": " + _content)
    _hist = "\n".join(_hlines)

# ── build writer prompt (inline) ──
_parts = []
if _ctx_str:
    _parts.append(_ctx_str)
_parts.append("**Shape kind:** " + shape_kind)
if element_name:
    _parts.append("**" + _label + ":** " + element_name)
if current_script:
    _parts.append("**Currently linked Server Script:** " + current_script)
_original = turn.get("original_script_content", "")
if _original:
    _parts.append("**Existing script (the CURRENT code of the linked Server Script) - you are MODIFYING this. Rewrite THIS code, preserve its intent and structure, and change only what the user asked. Do NOT invent a new script from scratch:**\n```python\n" + _original + "\n```")
if _hist:
    _parts.append("**Conversation so far:**\n" + _hist)
_parts.append("**User request:** " + message)
prompt = "\n\n".join(_parts)

# ── security regeneration (inline) ──
violations = turn.get("violations") or []
if violations:
    _bullets = "\n".join("  - " + v for v in violations)
    prompt = (
        prompt + "\n\n"
        "**SECURITY REGENERATION REQUEST**\n"
        "The previous attempt was blocked by the security validator for these violations:\n"
        + _bullets + "\n\n"
        "Rewrite the script WITHOUT any of these patterns. "
        "Use only `frappe.get_doc`, `frappe.db.get_value`, `frappe.get_all`, "
        "and other safe Frappe ORM methods. "
        "Do NOT import os, sys, subprocess, or any module outside the standard Frappe sandbox."
    )

# The specialist tool_writer sub-agent owns the Agent Tool standard; fall back to
# the general dual-contract writer if the sub-prompt is not seeded yet.
role = "tool_writer" if (_subs.get("tool_writer") or {}).get("prompt") else "script_writer"
_system = (_subs.get(role) or {}).get("prompt") or ""
draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text
update_turn(context_docname, draft=(draft or ""))
has_code = bool(re.search(r"```python\s*\n.*?```", draft or "", re.DOTALL))
result["has_code"] = has_code
result["role_used"] = role
result["preview"] = (draft or "")[:400]
'''

REVIEW = r'''# Logix – Tool Review Script (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda,
# no recursion, and no comprehension referencing a module-level import/const.
# Review the drafted script, run the mandatory security gate, then optimise.
import ast
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.security.script_validator import validate_script as _security_validate_script

_MAX_SECURITY_RETRIES = 2
_SAFE_REWRITE_GUIDANCE = (
    "Rewrite the script WITHOUT any of the flagged patterns. Use only "
    "`frappe.get_doc`, `frappe.db.get_value`, `frappe.get_all`, and other safe "
    "Frappe ORM methods. Do NOT import os, sys, subprocess, or any module "
    "outside the standard Frappe sandbox."
)
_INJECTED = frozenset({"frappe", "doc", "task_data", "result", "context_doctype", "context_docname"})
# A right-hand side is safe to drop (when its target is unused) only if it can
# have NO side effect. Conservative: any call / attribute / subscript / await /
# comprehension / lambda / walrus anywhere in the value tree keeps the binding.
_DANGER = (
    ast.Call, ast.Attribute, ast.Subscript, ast.Await, ast.Yield, ast.YieldFrom,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda,
    ast.NamedExpr, ast.Starred,
)

turn = get_turn(context_docname)
_cfg = get_agent_config("logix_agent") or {}
_cfg.setdefault("agent_id", "logix_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

draft = turn.get("draft", "")
shape_kind = turn.get("shape_kind") or (turn.get("process_context") or {}).get("shape_kind") or "script_task"
_system = (_subs.get("script_reviewer") or {}).get("prompt") or ""
review_raw = run_sync(_adapter.complete(system=_system, user="Shape kind: " + shape_kind + "\n\n" + draft)).text

# ── apply review (inline) ──
candidate = draft
if review_raw:
    _rt = review_raw.strip()
    if _rt.startswith("```"):
        _rt = _rt.split("\n", 1)[-1]
        if _rt.rstrip().endswith("```"):
            _rt = _rt.rstrip()[: _rt.rstrip().rfind("```")]
    _review = None
    try:
        _review = json.loads(_rt.strip())
    except (json.JSONDecodeError, TypeError):
        _review = None
    if isinstance(_review, dict):
        if (not _review.get("approved")) and _review.get("revised_script"):
            _revised = _review["revised_script"]
            _mm = re.search(r"(```python\s*\n)(.*?)(```)", draft, re.DOTALL)
            if _mm:
                candidate = draft[:_mm.start(2)] + _revised.rstrip("\n") + "\n" + draft[_mm.end(2):]
            else:
                candidate = "```python\n" + _revised + "\n```"
        elif _review.get("suggestions"):
            candidate = draft + "\n\n> **Review notes:** " + "; ".join(_review["suggestions"])

# No Python block -> the agent is asking a question; pass through unvalidated.
if not re.search(r"```python\s*\n.*?```", candidate, re.DOTALL):
    update_turn(context_docname, final=candidate, modified_code="", script_safe=True, is_question=True)
    result["approved"] = True
    result["is_question"] = True
else:
    # extract code (inline)
    _cm = re.search(r"```python\s*\n(.*?)```", candidate, re.DOTALL)
    code = _cm.group(1).strip() if _cm else candidate.strip()

    # security gate (inline)
    _vres = _security_validate_script(code)
    _violations = _vres.get("violations", []) or []
    _valid = bool(_vres.get("valid"))

    if _valid:
        # ── optimise: strip unused imports + unused pure assignments (FLAT) ──
        _optimized = code
        for _pass in range(6):
            try:
                _tree = ast.parse(_optimized)
            except SyntaxError:
                break
            _referenced = set()
            for _n in ast.walk(_tree):
                if isinstance(_n, ast.Name) and isinstance(_n.ctx, (ast.Load, ast.Del)):
                    _referenced.add(_n.id)
                elif isinstance(_n, (ast.Global, ast.Nonlocal)):
                    for _nm in _n.names:
                        _referenced.add(_nm)
            _stmt_starts = []
            for _n in ast.walk(_tree):
                if isinstance(_n, ast.stmt):
                    _stmt_starts.append(_n.lineno)
            _drop = set()
            for _node in ast.walk(_tree):
                _bound = None
                if isinstance(_node, ast.Import):
                    _bound = []
                    for _a in _node.names:
                        _bound.append(_a.asname or _a.name.split(".")[0])
                elif isinstance(_node, ast.ImportFrom):
                    if _node.module == "__future__":
                        continue
                    _has_star = False
                    for _a in _node.names:
                        if _a.name == "*":
                            _has_star = True
                    if _has_star:
                        continue
                    _bound = []
                    for _a in _node.names:
                        _bound.append(_a.asname or _a.name)
                elif isinstance(_node, ast.Assign):
                    if len(_node.targets) == 1 and isinstance(_node.targets[0], ast.Name):
                        _nm = _node.targets[0].id
                        _sef = True
                        for _sub in ast.walk(_node.value):
                            if isinstance(_sub, _DANGER):
                                _sef = False
                                break
                        if _nm not in _referenced and _nm not in _INJECTED and _sef:
                            _bound = [_nm]
                # decide whether every bound name is unused
                _do_flag = False
                if _bound:
                    if isinstance(_node, (ast.Import, ast.ImportFrom)):
                        _all_unused = True
                        for _b in _bound:
                            if _b in _referenced or _b in _INJECTED:
                                _all_unused = False
                                break
                        _do_flag = _all_unused
                    else:
                        _do_flag = True
                if _do_flag:
                    _start = _node.lineno
                    _end = _node.end_lineno or _start
                    _cnt = 0
                    for _s in _stmt_starts:
                        if _start <= _s <= _end:
                            _cnt += 1
                    if _cnt == 1:
                        for _ln in range(_start, _end + 1):
                            _drop.add(_ln)
            if not _drop:
                break
            _kept = []
            _idx = 0
            for _line_text in _optimized.split("\n"):
                _idx += 1
                if _idx not in _drop:
                    _kept.append(_line_text)
            _cand2 = "\n".join(_kept)
            try:
                ast.parse(_cand2)
            except SyntaxError:
                break
            if _cand2 == _optimized:
                break
            _optimized = _cand2

        # Re-validate the optimised code so the optimiser can never bypass the gate,
        # and keep the reply text in sync with the code that will be applied.
        if _optimized != code:
            _rev2 = _security_validate_script(_optimized)
            if bool(_rev2.get("valid")):
                _rm = re.search(r"(```python\s*\n)(.*?)(```)", candidate, re.DOTALL)
                if _rm:
                    candidate = candidate[:_rm.start(2)] + _optimized.rstrip("\n") + "\n" + candidate[_rm.end(2):]
                code = _optimized

        update_turn(context_docname, final=candidate, modified_code=code, script_safe=True, violations=[])
        result["approved"] = True
        result["valid"] = True
    else:
        retries = int(turn.get("security_retries", 0)) + 1
        update_turn(context_docname, violations=_violations, script_safe=False, security_retries=retries)
        frappe.log_error(
            title="Logix Security Validator — " + ("Max retries reached" if retries > _MAX_SECURITY_RETRIES else "Regeneration requested"),
            message="Attempt " + str(retries) + "\nViolations: " + str(_violations) + "\n\nCode:\n" + code,
        )
        result["approved"] = False
        result["valid"] = False
        result["violations"] = _violations
        result["fix_hints"] = [] if not _violations else [_SAFE_REWRITE_GUIDANCE]
        result["retries_used"] = retries
        result["max_retries"] = _MAX_SECURITY_RETRIES
'''

FINALIZE = r'''# Logix – Tool Finalize (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Assemble the final structured reply for this turn. Always called last.
import difflib
import json
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

_REFUSAL = (
    "I was unable to generate a safe script after multiple attempts. "
    "Please rephrase your request to avoid forbidden operations "
    "(e.g. file access, shell commands, or raw destructive SQL)."
)

turn = get_turn(context_docname)
if turn.get("done"):  # clarify already produced the output
    result["finalized"] = True
else:
    intent = turn.get("intent", "CREATE")
    if not turn.get("script_safe"):
        update_turn(context_docname, output={
            "intent": intent, "response": _REFUSAL, "diff": None,
            "original_script": None, "modified_script": None,
            "options": None, "suggested_name": None,
        }, done=True)
        result["finalized"] = True
        result["safe"] = False
    else:
        final = turn.get("final", "")
        code = turn.get("modified_code", "")
        if turn.get("is_question") or not code:
            # Question passthrough (reviewer returned no code block)
            update_turn(context_docname, output={
                "intent": intent, "response": final, "diff": None,
                "original_script": None, "modified_script": None,
                "options": None, "suggested_name": None,
            }, done=True)
            result["finalized"] = True
        else:
            original = turn.get("original_script_content", "")
            if intent == "MODIFY" and original:
                _diff = "".join(difflib.unified_diff(
                    (original or "").splitlines(keepends=True),
                    (code or "").splitlines(keepends=True),
                    fromfile="original", tofile="modified", lineterm="",
                ))
                update_turn(context_docname, output={
                    "intent": "MODIFY", "response": final, "diff": _diff or None,
                    "original_script": original, "modified_script": code,
                    "options": None, "suggested_name": None,
                }, done=True)
                result["finalized"] = True
            else:
                # CREATE — plain-English verification checklist (bonus; never fails the turn)
                checklist = []
                _cfg = get_agent_config("logix_agent") or {}
                _cfg.setdefault("agent_id", "logix_agent")
                _subs = _cfg.get("sub_prompts") or {}
                _adapter = get_llm_adapter_from_settings(_cfg)
                element_name = turn.get("element_name", "")
                ctx = turn.get("process_context") or {}

                # build test prompt (inline; incl. process-context formatting)
                _ctx_str = ""
                if ctx:
                    _is_tool = ctx.get("shape_kind") == "agent_tool"
                    _clines = ["**Process Context (from the BPMN diagram):**"]
                    if ctx.get("process_name"):
                        _clines.append("- Process: " + str(ctx["process_name"]))
                    if _is_tool:
                        _clines.append("- This element is an AGENT TOOL inside an AI Agent Task's ad-hoc Tools sub-process — an LLM calls it on demand; it is NOT a sequential process step.")
                    _incoming = ctx.get("incoming") or []
                    _outgoing = ctx.get("outgoing") or []
                    if _incoming:
                        _clines.append("- This script runs AFTER: " + ", ".join(n["name"] + " (" + n["type"] + ")" for n in _incoming))
                    if _outgoing:
                        _clines.append("- This script leads TO: " + ", ".join(n["name"] + " (" + n["type"] + ")" for n in _outgoing))
                    if not _incoming and not _outgoing and not _is_tool:
                        _ctx_str = ""
                    elif _is_tool:
                        _clines.append("Remember: an agent tool receives ONLY the arguments the calling LLM passes (plus frappe/doc/context_doctype/context_docname/result) — no workflow variables and no task_data exist in its namespace.")
                        _ctx_str = "\n".join(_clines)
                    else:
                        _clines.append("Use this context to infer what workflow variables are available as inputs and what outputs the next step will need.")
                        _ctx_str = "\n".join(_clines)

                _tparts = ["**Script Task name:** " + (element_name or "Unknown")]
                if _ctx_str:
                    _tparts.append(_ctx_str)
                _tparts.append("**Script code to test:**\n```python\n" + code + "\n```")
                _tparts.append("Generate a plain-English test checklist for this script. Return ONLY the JSON object as described in your instructions — no extra text, no code fences.")
                test_prompt = "\n\n".join(_tparts)

                try:
                    _tsys = (_subs.get("test_writer") or {}).get("prompt") or ""
                    test_raw = run_sync(_adapter.complete(system=_tsys, user=test_prompt)).text or ""
                    _stripped = test_raw.strip()
                    if _stripped.startswith("```"):
                        _stripped = _stripped.split("\n", 1)[-1]
                        if _stripped.endswith("```"):
                            _stripped = _stripped[: _stripped.rfind("```")].strip()
                    checklist = json.loads(_stripped).get("checklist", [])
                except Exception as _exc:
                    frappe.log_error(title="Logix test_writer parse error (stage tool)", message=str(_exc))

                update_turn(context_docname, output={
                    "intent": "CREATE", "response": final, "diff": None,
                    "original_script": None, "modified_script": code,
                    "options": None, "suggested_name": (element_name or None),
                    "tests_checklist": checklist,
                }, done=True)
                result["finalized"] = True
'''

SCRIPTS = {
    "Logix – Tool Classify Intent": CLASSIFY,
    "Logix – Tool Clarify": CLARIFY,
    "Logix – Tool Write Script": WRITE,
    "Logix – Tool Write Agent Tool": WRITE_AGENT_TOOL,
    "Logix – Tool Review Script": REVIEW,
    "Logix – Tool Finalize": FINALIZE,
}


def execute():
    original_user = frappe.session.user
    try:
        frappe.set_user("Administrator")
        for name, body in SCRIPTS.items():
            if not frappe.db.exists("Server Script", name):
                continue
            doc = frappe.get_doc("Server Script", name)
            if (doc.script or "").strip() == body.strip():
                continue
            doc.script = body
            doc.save(ignore_permissions=True)
        frappe.db.commit()
    finally:
        frappe.set_user(original_user)
