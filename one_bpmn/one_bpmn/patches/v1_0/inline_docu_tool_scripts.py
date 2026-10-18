"""
Full-rip conversion (per-agent migration follow-up): the Docu chat agent has no
Python backend left. Each tool Server Script in the process map's ad-hoc Tools
sub-process carries its own self-contained, FLAT logic, and the
one_bpmn.agents.google_adk.docu_agent package (DocuAgent orchestrator, then
tools.py) has been deleted. This patch installs those bodies idempotently so
every environment converges on the process-model-only Docu agent.

The bodies are FLAT (no def/lambda, no comprehension referencing a module-level
name) because the AI Agent shape-tool executor runs them under SPLIT
globals/locals (shape_tools._run_server_script) — a nested scope cannot see
top-level imports/consts there. That is also why each script builds its read
ToolSpecs inline around importable callables: a tool ``fn`` defined in the script
body could not see the script's own imports.

They call only shared infrastructure reused across agents: turn_state, the LLM
adapter factory, get_agent_config, the schema-safety validator, and the DocType
schema tools in one_bpmn.tools.tool_for_server_scripts (the same module the
Logix map and api/docu_api.py use).

Idempotent: only updates a Server Script that exists and whose body differs.
Ordered after seed_docu_agent_config (which creates the rows) and after the
Logix/ProsAlly inline patches.

NOTE: new agent migrations must NOT add patches like this one — a BPMN map and
its Server Scripts travel by Processa export/import (export_bpmn_config collects
every script the diagram references). This patch is kept only because it already
shipped; it is updated here so a fresh site cannot install a body that imports
the deleted package.
"""

import frappe

CLASSIFY = r'''# Docu – Tool Classify Intent (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — so it uses NO
# def/lambda and no comprehension that references a module-level import/const.
# Classify the request as CREATE, MODIFY, or DISAMBIGUATE. Called first.
import json
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.tools.tool_for_server_scripts import (
    doctype_exists,
    list_doctypes,
    read_doctype_definition,
)

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

_classifier_tools = [
    ToolSpec(fn=doctype_exists, name="doctype_exists",
             description=("Check whether a DocType exists and whether it is a custom DocType. Returns {exists, custom}. "
                          "Call this on the 'options' of every Link/Table field to confirm the target really exists."),
             parameters={"doctype": {"type": "string", "description": "The DocType name to check."}},
             required=["doctype"]),
    ToolSpec(fn=list_doctypes, name="list_doctypes",
             description="List existing DocTypes (name, module, custom flag). Optionally filter by a search term.",
             parameters={"search": {"type": "string", "description": "Optional substring to filter DocType names."}},
             required=[]),
]

doctype = turn.get("doctype", "")
exists = bool(doctype) and bool(frappe.db.exists("DocType", doctype))
message = turn.get("user_text", "")
ctx = turn.get("process_context") or {}

# ── format process context (inline; for_modify=False) ──
_ctx_str = ""
if isinstance(ctx, dict) and ctx:
    _lines = []
    _proc = (ctx.get("process_name") or "").strip()
    _step = (ctx.get("element_name") or "").strip()
    _etype = (ctx.get("element_type") or "step").strip() or "step"
    _role = (ctx.get("field_role") or "").strip()
    _desc = (ctx.get("element_description") or "").strip()
    if _proc:
        _lines.append('This DocType belongs to the "' + _proc + '" business process.')
    if _step:
        _s = 'It is attached to the ' + _etype + ' "' + _step + '"'
        if _role:
            _s += ", where it represents " + _role
        _lines.append(_s + ".")
    elif _role:
        _lines.append("At this step the DocType represents " + _role + ".")
    if _desc:
        _lines.append("That step is described as: " + _desc)
    _up = []
    for _x in (ctx.get("upstream") or []):
        _xs = str(_x).strip()
        if _xs:
            _up.append(_xs)
    _down = []
    for _x in (ctx.get("downstream") or []):
        _xs = str(_x).strip()
        if _xs:
            _down.append(_xs)
    if _up:
        _lines.append("Earlier steps in the process: " + ", ".join(_up) + ".")
    if _down:
        _lines.append("Later steps in the process: " + ", ".join(_down) + ".")
    if _lines:
        _lines.append("Design the DocType so it fits this step's purpose — capture exactly what this step needs (no more), and use field names/labels that match the process.")
    _ctx_str = " ".join(_lines)

# ── build intent prompt (inline) ──
_parts = []
if _ctx_str:
    _parts.append("BPMN context: " + _ctx_str)
if doctype and exists:
    _parts.append("Currently selected form: " + doctype + "  ← existing, treat as MODIFY target unless stated otherwise")
elif doctype:
    _parts.append("Named form: " + doctype + "  ← does not exist yet, likely CREATE")
else:
    _parts.append("No form selected yet  ← default to CREATE")
_parts.append("User request: " + message)
prompt = "\n".join(_parts)

_system = (_subs.get("intent_classifier") or {}).get("prompt") or ""
raw = run_sync(_adapter.complete(system=_system, user=prompt, tools=_classifier_tools)).text

intent = "MODIFY" if exists else "CREATE"
try:
    intent = json.loads((raw or "").strip()).get("intent", intent).upper()
except (json.JSONDecodeError, TypeError, AttributeError):
    pass
if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
    intent = "MODIFY" if exists else "CREATE"

# Deterministic routing so the orchestrator never skips a stage.
nxt = "clarify" if intent == "DISAMBIGUATE" else "write_schema"

# Seed the MODIFY baseline once so write_schema/finalize can diff against it.
current_ir = read_doctype_definition(doctype) if exists else None
update_turn(context_docname, intent=intent, exists=exists, current_ir=current_ir)
result["intent"] = intent
result["next"] = nxt
'''

CLARIFY = r'''# Docu – Tool Clarify (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Ask one focused clarifying question (use only when intent is DISAMBIGUATE).
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.tools.tool_for_server_scripts import doctype_exists, list_doctypes

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

_clarifier_tools = [
    ToolSpec(fn=list_doctypes, name="list_doctypes",
             description="List existing DocTypes (name, module, custom flag). Optionally filter by a search term.",
             parameters={"search": {"type": "string", "description": "Optional substring to filter DocType names."}},
             required=[]),
    ToolSpec(fn=doctype_exists, name="doctype_exists",
             description=("Check whether a DocType exists and whether it is a custom DocType. Returns {exists, custom}. "
                          "Call this on the 'options' of every Link/Table field to confirm the target really exists."),
             parameters={"doctype": {"type": "string", "description": "The DocType name to check."}},
             required=["doctype"]),
]

message = turn.get("user_text", "")
doctype = turn.get("doctype", "")
chat_history = turn.get("chat_history", []) or []

# ── format history (inline) ──
_hist = ""
if chat_history:
    _hlines = []
    for _e in chat_history[-10:]:
        _role = _e.get("role") or _e.get("type", "user")
        _content = (_e.get("content") or "").strip()
        if _content:
            _hlines.append(("User" if _role == "user" else "Docu") + ": " + _content)
    _hist = "\n".join(_hlines)

# ── build clarifier prompt (inline; intent_reason is empty) ──
_parts = []
if doctype:
    _parts.append("Selected form: " + doctype)
if _hist:
    _parts.append("Conversation so far:\n" + _hist)
_parts.append("User request: " + message)
prompt = "\n\n".join(_parts)

_system = (_subs.get("clarifier") or {}).get("prompt") or ""
raw = run_sync(_adapter.complete(system=_system, user=prompt, tools=_clarifier_tools)).text

question = raw or "Could you tell me a bit more?"
options = []

# ── extract the first JSON object (inline); tolerates fenced or prose-wrapped ──
_txt = (raw or "").strip()
data = None
_fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", _txt)
if _fence:
    try:
        data = json.loads(_fence.group(1).strip())
    except (json.JSONDecodeError, ValueError, TypeError):
        data = None
else:
    try:
        data = json.loads(_txt)
    except (json.JSONDecodeError, ValueError, TypeError):
        _brace = re.search(r"\{[\s\S]*\}", _txt)
        if _brace:
            try:
                data = json.loads(_brace.group(0))
            except (json.JSONDecodeError, ValueError, TypeError):
                data = None
if isinstance(data, dict):
    question = data.get("question") or raw
    options = data.get("options") or []

output = {
    "intent": "DISAMBIGUATE",
    "response": question,
    "options": options,
    "doctype_ir": None,
    "diff": None,
    "suggested_name": None,
}
update_turn(context_docname, output=output, done=True)
result["response"] = question
result["options"] = options
'''

WRITE = r'''# Docu – Tool Write Schema (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda;
# comprehensions reference only their own loop var.
# Design (or redesign) the DocType for the current request.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.tools.tool_for_server_scripts import (
    doctype_exists,
    get_doctype_definition,
    get_doctype_fields,
    list_doctypes,
    read_doctype_definition,
    validate_doctype_json,
)

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)
_DEFAULT_MODULE = "ONE BPMN"

_writer_tools = [
    ToolSpec(fn=get_doctype_definition, name="get_doctype_definition",
             description=("Get the COMPLETE definition of a DocType — every field with all its properties "
                          "(options, reqd, unique, in_list_view, read_only, hidden, default, depends_on, "
                          "fetch_from, precision, ...) plus naming. Use this before modifying a DocType so you "
                          "preserve existing field properties exactly."),
             parameters={"doctype": {"type": "string", "description": "The exact DocType name, e.g. 'Employee'."}},
             required=["doctype"]),
    ToolSpec(fn=get_doctype_fields, name="get_doctype_fields",
             description="Get the existing fields (fieldname, fieldtype, label, reqd) of a DocType. Use before modifying one.",
             parameters={"doctype": {"type": "string", "description": "The exact DocType name, e.g. 'Employee'."}},
             required=["doctype"]),
    ToolSpec(fn=doctype_exists, name="doctype_exists",
             description=("Check whether a DocType exists and whether it is a custom DocType. Returns {exists, custom}. "
                          "Call this on the 'options' of every Link/Table field to confirm the target really exists."),
             parameters={"doctype": {"type": "string", "description": "The DocType name to check."}},
             required=["doctype"]),
    ToolSpec(fn=list_doctypes, name="list_doctypes",
             description="List existing DocTypes (name, module, custom flag). Optionally filter by a search term.",
             parameters={"search": {"type": "string", "description": "Optional substring to filter DocType names."}},
             required=[]),
    ToolSpec(fn=validate_doctype_json, name="validate_doctype",
             description=("Validate a DocType definition (JSON) against the schema-safety rules. "
                          "Returns {valid, violations, fix_hints}. Call this on your design before you finalize it, "
                          "and fix any violations it reports."),
             parameters={"ir": {"type": "string", "description": "The DocType definition as a JSON object string."}},
             required=["ir"]),
]

message = turn.get("user_text", "")
chat_history = turn.get("chat_history", []) or []
doctype = turn.get("doctype", "")
target_module = turn.get("target_module", "")
ctx = turn.get("process_context") or {}

# The MODIFY baseline: use what classify seeded, else read it fresh so the writer
# edits the existing DocType instead of redrawing from scratch.
current_ir = turn.get("current_ir")
if current_ir is None and doctype and bool(frappe.db.exists("DocType", doctype)):
    current_ir = read_doctype_definition(doctype)
    update_turn(context_docname, current_ir=current_ir)  # cache for finalize's diff

_is_modify = bool(doctype and isinstance(current_ir, dict) and current_ir.get("fields"))

# ── format process context (inline; for_modify=_is_modify) ──
_ctx_str = ""
if isinstance(ctx, dict) and ctx:
    _lines = []
    _proc = (ctx.get("process_name") or "").strip()
    _step = (ctx.get("element_name") or "").strip()
    _etype = (ctx.get("element_type") or "step").strip() or "step"
    _role = (ctx.get("field_role") or "").strip()
    _desc = (ctx.get("element_description") or "").strip()
    if _proc:
        _lines.append('This DocType belongs to the "' + _proc + '" business process.')
    if _step:
        _s = 'It is attached to the ' + _etype + ' "' + _step + '"'
        if _role:
            _s += ", where it represents " + _role
        _lines.append(_s + ".")
    elif _role:
        _lines.append("At this step the DocType represents " + _role + ".")
    if _desc:
        _lines.append("That step is described as: " + _desc)
    _up = []
    for _x in (ctx.get("upstream") or []):
        _xs = str(_x).strip()
        if _xs:
            _up.append(_xs)
    _down = []
    for _x in (ctx.get("downstream") or []):
        _xs = str(_x).strip()
        if _xs:
            _down.append(_xs)
    if _up:
        _lines.append("Earlier steps in the process: " + ", ".join(_up) + ".")
    if _down:
        _lines.append("Later steps in the process: " + ", ".join(_down) + ".")
    if _lines and not _is_modify:
        _lines.append("Design the DocType so it fits this step's purpose — capture exactly what this step needs (no more), and use field names/labels that match the process.")
    _ctx_str = " ".join(_lines)

# ── format history (inline) ──
_hist = ""
if chat_history:
    _hlines = []
    for _e in chat_history[-10:]:
        _role2 = _e.get("role") or _e.get("type", "user")
        _content = (_e.get("content") or "").strip()
        if _content:
            _hlines.append(("User" if _role2 == "user" else "Docu") + ": " + _content)
    _hist = "\n".join(_hlines)

# ── build writer prompt (inline) ──
_parts = []
if _ctx_str:
    _parts.append(("For background only — do NOT redesign around this: " if _is_modify else "") + _ctx_str)
if _is_modify:
    _parts.append('The DocType "' + doctype + '" ALREADY EXISTS. Its CURRENT complete definition is below — you are EDITING it, NOT creating a new one.')
    _parts.append("```json\n" + json.dumps(current_ir, indent=2, default=str) + "\n```")
    _parts.append("Return the COMPLETE JSON again with ONLY the user's requested change applied. Keep EVERY other field exactly as above — same fieldname, same properties, and every Section/Column/Tab break in the same order. Do NOT say it doesn't exist, and do NOT redesign it from the process context.")
else:
    _parts.append("Module to use (a Frappe app module — NOT the business-process name): " + (target_module or _DEFAULT_MODULE))
    if doctype:
        _parts.append("Suggested form name: " + doctype)
if _hist:
    _parts.append("**Conversation so far:**\n" + _hist)
_parts.append("**User request:** " + message)
_parts.append("Design the form now and output the JSON definition.")
base_prompt = "\n\n".join(_parts)

# ── repair prompt when a prior review flagged validation problems (inline) ──
violations = turn.get("violations") or []
prompt = base_prompt
if violations and turn.get("draft_ir"):
    _numbered_lines = []
    _i = 0
    for _v in violations:
        _i += 1
        _numbered_lines.append("  " + str(_i) + ". " + str(_v))
    _numbered = "\n".join(_numbered_lines)
    prompt = (
        base_prompt + "\n\n"
        "**VALIDATION FAILED** — the previous design had " + str(len(violations)) + " problem(s):\n"
        + _numbered + "\n\n"
        "Fix every problem and output the complete corrected DocType JSON.\n\n"
        "Previous design:\n" + json.dumps(turn["draft_ir"], indent=2)
    )

_system = (_subs.get("schema_writer") or {}).get("prompt") or ""
draft = run_sync(_adapter.complete(system=_system, user=prompt, tools=_writer_tools)).text or ""
# ── extract the drafted IR (inline); None => the writer asked a question ──
_txt = (draft or "").strip()
draft_ir = None
_fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", _txt)
if _fence:
    try:
        draft_ir = json.loads(_fence.group(1).strip())
    except (json.JSONDecodeError, ValueError, TypeError):
        draft_ir = None
else:
    try:
        draft_ir = json.loads(_txt)
    except (json.JSONDecodeError, ValueError, TypeError):
        _brace = re.search(r"\{[\s\S]*\}", _txt)
        if _brace:
            try:
                draft_ir = json.loads(_brace.group(0))
            except (json.JSONDecodeError, ValueError, TypeError):
                draft_ir = None
update_turn(context_docname, draft_text=draft, draft_ir=draft_ir)
result["has_ir"] = bool(draft_ir)
result["preview"] = (draft or "")[:400]
'''

REVIEW = r'''# Docu – Tool Review Schema (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Review the drafted DocType and run the mandatory schema-safety gate.
import json
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.security.doctype_validator import validate_doctype_ir
from one_bpmn.tools.tool_for_server_scripts import (
    doctype_exists,
    get_doctype_definition,
    validate_doctype_json,
)

_MAX_SECURITY_RETRIES = 3  # matches the old DocuAgent._MAX_FIX_PASSES

turn = get_turn(context_docname)
_cfg = get_agent_config("docu_agent") or {}
_cfg.setdefault("agent_id", "docu_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

_reviewer_tools = [
    ToolSpec(fn=get_doctype_definition, name="get_doctype_definition",
             description=("Get the COMPLETE definition of a DocType — every field with all its properties "
                          "(options, reqd, unique, in_list_view, read_only, hidden, default, depends_on, "
                          "fetch_from, precision, ...) plus naming. Use this before modifying a DocType so you "
                          "preserve existing field properties exactly."),
             parameters={"doctype": {"type": "string", "description": "The exact DocType name, e.g. 'Employee'."}},
             required=["doctype"]),
    ToolSpec(fn=doctype_exists, name="doctype_exists",
             description=("Check whether a DocType exists and whether it is a custom DocType. Returns {exists, custom}. "
                          "Call this on the 'options' of every Link/Table field to confirm the target really exists."),
             parameters={"doctype": {"type": "string", "description": "The DocType name to check."}},
             required=["doctype"]),
    ToolSpec(fn=validate_doctype_json, name="validate_doctype",
             description=("Validate a DocType definition (JSON) against the schema-safety rules. "
                          "Returns {valid, violations, fix_hints}. Call this on your design before you finalize it, "
                          "and fix any violations it reports."),
             parameters={"ir": {"type": "string", "description": "The DocType definition as a JSON object string."}},
             required=["ir"]),
]

draft_ir = turn.get("draft_ir")

# No JSON -> the writer is asking a question; pass it through unvalidated.
if not draft_ir:
    update_turn(
        context_docname, final_text=turn.get("draft_text", ""), final_ir=None,
        schema_safe=True, is_question=True,
    )
    result["approved"] = True
    result["is_question"] = True
else:
    _system = (_subs.get("schema_reviewer") or {}).get("prompt") or ""
    review_raw = run_sync(_adapter.complete(system=_system, user=json.dumps(draft_ir), tools=_reviewer_tools)).text

    # ── apply review (inline) ──
    candidate = draft_ir
    if review_raw:
        try:
            _review = json.loads(review_raw.strip())
            if (not _review.get("approved")) and isinstance(_review.get("revised_ir"), dict):
                candidate = _review["revised_ir"]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    candidate.setdefault("module", turn.get("target_module") or "ONE BPMN")

    validation = validate_doctype_ir(candidate)
    if validation["valid"]:
        update_turn(
            context_docname, final_ir=candidate, final_text=turn.get("draft_text", ""),
            schema_safe=True, violations=[],
        )
        result["approved"] = True
        result["valid"] = True
    else:
        retries = int(turn.get("security_retries", 0)) + 1
        update_turn(
            context_docname, draft_ir=candidate, violations=validation["violations"],
            schema_safe=False, security_retries=retries,
        )
        frappe.log_error(
            title="Docu Schema Validator — " + (
                "Max retries reached" if retries > _MAX_SECURITY_RETRIES else "Regeneration requested"
            ),
            message="Attempt " + str(retries) + "\nViolations: " + str(validation["violations"]),
        )
        result["approved"] = False
        result["valid"] = False
        result["violations"] = validation["violations"]
        result["fix_hints"] = validation["fix_hints"]
        result["retries_used"] = retries
        result["max_retries"] = _MAX_SECURITY_RETRIES
'''

FINALIZE = r'''# Docu – Tool Finalize (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Assemble the final structured reply for this turn. Always called last.
import re
from one_bpmn.agents.turn_state import get_turn, update_turn
from one_bpmn.tools.tool_for_server_scripts import diff_ir

_REFUSAL = (
    "I couldn't produce a safe form definition after several attempts. "
    "Please rephrase what you'd like the form to capture and I'll try again."
)

turn = get_turn(context_docname)
if turn.get("done"):  # clarify already produced the output
    result["finalized"] = True
else:
    intent = turn.get("intent", "CREATE")
    if not turn.get("schema_safe"):
        update_turn(context_docname, output={
            "intent": intent,
            "response": _REFUSAL,
            "doctype_ir": None,
            "diff": None,
            "options": None,
            "suggested_name": None,
        }, done=True)
        result["finalized"] = True
        result["safe"] = False
    else:
        # ── response text (inline _response_text: strip any JSON code block) ──
        _ft = turn.get("final_text", "")
        final_text = re.sub(r"```(?:json)?\s*[\s\S]*?```", "", _ft or "").strip()
        if not final_text:
            final_text = "Here's the DocType I put together — review it on the right."
        ir = turn.get("final_ir")
        # Question passthrough (reviewer returned no JSON)
        if turn.get("is_question") or not ir:
            update_turn(context_docname, output={
                "intent": intent,
                "response": final_text,
                "doctype_ir": None,
                "diff": None,
                "options": None,
                "suggested_name": None,
            }, done=True)
            result["finalized"] = True
        elif intent == "MODIFY" and turn.get("current_ir"):
            diff = diff_ir(turn["current_ir"], ir)
            update_turn(context_docname, output={
                "intent": "MODIFY",
                "response": final_text,
                "doctype_ir": ir,
                "diff": diff,
                "options": None,
                "suggested_name": ir.get("doctype_name") or turn.get("doctype") or None,
            }, done=True)
            result["finalized"] = True
        else:
            update_turn(context_docname, output={
                "intent": "CREATE",
                "response": final_text,
                "doctype_ir": ir,
                "diff": None,
                "options": None,
                "suggested_name": ir.get("doctype_name") or turn.get("doctype") or None,
            }, done=True)
            result["finalized"] = True
'''

SCRIPTS = {
	"Docu – Tool Classify Intent": CLASSIFY,
	"Docu – Tool Clarify": CLARIFY,
	"Docu – Tool Write Schema": WRITE,
	"Docu – Tool Review Schema": REVIEW,
	"Docu – Tool Finalize": FINALIZE,
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
